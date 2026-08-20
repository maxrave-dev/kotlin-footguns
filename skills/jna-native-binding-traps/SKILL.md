---
name: jna-native-binding-traps
description: Hand-writing a JVM binding for a C library with JNA (Java Native Access) — the open-flags option that means something else on Windows, structs read by raw offset, callbacks the binding holds weakly, search paths registered too late, and proving which file was actually opened. Reach for it when a binding works on every developer machine and fails on a clean one, or when the very first symbol lookup fails with "the specified module could not be found" while the library is sitting right there.
---

# JNA native binding traps

JNA (Java Native Access) maps a Java/Kotlin interface onto an already-compiled C library at
runtime. Nothing checks that your declarations match the header: a wrong field order, a wrong
open flag or a collected callback are all silent at link time and surface much later, somewhere
else. Write the binding defensively, and log enough to tell a working setup from a broken one.

Verification commands below run against the exact jar you ship, e.g.
`JAR=$(find ~/.gradle/caches -name 'jna-<version>.jar' | head -1)`.

## Traps

**The open-flags option is POSIX-only — the same number means something else on Windows.**
`Library.OPTION_OPEN_FLAGS` is forwarded verbatim to the platform's loader call; JNA does not
translate it. Confirm on your pinned jar:
`javap -p -c -classpath "$JAR" com.sun.jna.NativeLibrary | grep -n 'open-flags\|Native.open'` —
the option key is read and its value flows into `Native.open(String, int)`. On POSIX, `2` is "resolve everything now". On
Windows the same `2` asks the loader to map the file as **plain data**: it appears to load, then
every symbol lookup fails, and the message names the *function* while blaming a missing module.

```kotlin
Native.load(
    name,
    MediaLibrary::class.java,                                   // adapted: renamed
    if (Platform.isWindows()) {
        emptyMap<String, Any>()
    } else {
        mapOf<String, Any>(Library.OPTION_OPEN_FLAGS to 2)      // resolve-now, private scope
    },
)
```

**Why you wanted that flag at all: loading publicly publishes the whole dependency closure.**
JNA's default publishes the library's symbols — and those of everything it drags in — into the
process-wide namespace, where unrelated natives (a rendering toolkit's own libraries) can bind to
them by accident. One such accidental binding produced a hard native stop inside a library the
application never calls, and only ever when the engine shared a process with the UI toolkit;
the same library loaded in a bare JVM was stable. Loading privately keeps the symbols to your
handle. This is also why the Windows branch above is *empty* rather than "some other flag":
Windows never publishes exports process-wide, so there is nothing to guard against there.

**Always log the file that was actually opened, not the name you asked for.**

```kotlin
val resolved = runCatching { NativeLibrary.getInstance(name).file?.absolutePath }
    .getOrNull() ?: "<unknown>"
Logger.d(TAG, "Loaded as '$name' (API ${version shr 16}.${version and 0xFFFF}) from $resolved")   // version = the library's own version call
```

On any machine with a system-wide copy installed, a working bundle and a completely broken bundle
both load and both work. The resolved path is the only thing that distinguishes them, and without
it the bug is invisible until a clean machine reports it.

**A bare library name is not a file name.** JNA maps `"foo"` onto the platform convention
(`libfoo.so`, `libfoo.dylib`, `foo.dll`). Bundles usually ship only the *versioned* file and no
unversioned symlink, so every bare name misses and the loader quietly falls through to a system
copy. Try absolute paths of the files you actually shipped **first**, plain names only as a
fallback.

**Folklore about when the search-path property is read does not survive the bytecode.** A comment
in the codebase this was mined from claimed the JNA path property is parsed once at class init,
making later writes a no-op. Disassembling the pinned jar shows the opposite: `jna.library.path`
is re-read on **every** load call, while the static initializer's own search set is filled from
*other* sources (the web-start path and the platform path property) and consulted only as a
fallback after the first open attempt fails. Two rules fall out:

- Verify against the property *name*, not a field name:
  `javap -p -c -classpath "$JAR" com.sun.jna.NativeLibrary | grep -n 'jna.library.path'` — where
  those reads land (a per-call method versus `static {}`) *is* the answer, and it is
  version-scoped, so re-run it on every JNA bump. Grepping for the internal field instead shows a
  `static {}` assignment and invites exactly the wrong conclusion.
- `NativeLibrary.addSearchPath(name, dir)` remains the explicit per-library-name API and reads
  clearest — use it because it is direct, not because "the property is too late". And do not
  expect the JVM's own `System.loadLibrary` to honour the JNA property: it resolves through
  `java.library.path` and the class loader, and nothing in the jar copies one property into the
  other.

**Structs are read by raw offset.** A field added, removed or reordered upstream is wrong bytes,
never a clean link error. Two defences, both cheap:

- Map only the *stable prefix* of a struct you exclusively read — the fields that have existed
  since the oldest API version you support. The binding then reads exactly those bytes and can
  never run past the end, including against older builds where the trailing fields do not exist
  at all. Only safe for read-only structs; one you write back must be complete.
- Compare the runtime API version against the one you wrote the layouts against, and log loudly
  on a **major** difference. Record in a comment which library version and which header the
  layouts were read from, and re-verify on every major bump.

```kotlin
if ((version shr 16) != (EXPECTED_API_VERSION shr 16)) {
    Logger.e(TAG, "client API major ${version shr 16} != expected ${EXPECTED_API_VERSION shr 16}; " +
        "struct layouts must be re-checked")
}
```

**Callbacks are held weakly.** `javap -classpath "$JAR" com.sun.jna.CallbackReference | head -2`
shows it extends `WeakReference<Callback>`. A collected callback leaves native code holding a
function pointer to nothing, and it fires whenever the native side next feels like it — so the
failure has no relationship to the code that registered it. Keep every registered callback in a
field for as long as it stays registered, and deregister before freeing the object it points at.

**Nothing terminates your array arguments.** A C function taking a `char **` terminated by NULL
needs the trailing null element from you; JNA does not append one.

```kotlin
val argv = arrayOfNulls<String>(args.size + 1)   // last element stays null on purpose
args.forEachIndexed { i, a -> argv[i] = a }
```

**Return an owned buffer as a pointer, not as a `String`.** When the C contract says the caller
owns the result and must hand it back, mapping it to `String` loses the address — so it can never
be handed back, and that memory is never reclaimed for the life of the process. Map it to
`Pointer`, read the value out, then call the library's own release function.
