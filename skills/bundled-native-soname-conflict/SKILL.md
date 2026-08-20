---
name: bundled-native-soname-conflict
description: A native library you bundle with a desktop app drags its own copy of a general-purpose base library along, that copy claims the shared-object name for the whole process the moment your native loads, and an unrelated platform API then fails with a missing-symbol message naming a third library. Use when a feature that opens links or system dialogs works on your machine but silently does nothing on users' machines, when a platform API reports itself unsupported at runtime, or when deciding what a native bundle may contain.
---

# A bundled base library claims a system library name

Ship a native library with your app and you ship its whole dependency closure. If that closure
contains a **general-purpose base library the host desktop also has** — a utility/collections
library, a compression library, a crypto library — then the first copy loaded wins the
**shared-object name** (on Linux, the `soname` recorded in the library's dynamic section) for the rest of the
process. Your native loads early, so your copy wins.

Nothing fails at that moment. It fails later, in code that has nothing to do with your native:
a platform API opens the *system* counterpart of that same family, the system copy needs a
symbol the older bundled copy does not export, the load fails, and the platform marks the whole
API unsupported for the remainder of the process.

Worked example (Linux): a bundled media library carried a utility library built on an older
distribution. The JDK's desktop-integration API (`java.awt.Desktop`) probes its native backing
on first use; on a host with a newer system copy of that family the probe died with an
undefined-symbol message naming a *third* library in the same family. From then on the JDK
reported the desktop API unsupported, and all external-link call sites broke at once.

## The two fixes, in order

**Cure** — exclude base-system libraries when staging the bundle:

```sh
# adapted — the staging script's exclusion list
SYSTEM_LIBS="
libc.so.6 libm.so.6 libdl.so.2 libpthread.so.0 librt.so.1
ld-linux-x86-64.so.2 libgcc_s.so.1 libstdc++.so.6
libz.so.1 libbz2.so.1.0 liblzma.so.5
"
is_system() { for s in $SYSTEM_LIBS; do [[ "$1" == "$s" ]] && return 0; done; return 1; }
```

**Workaround, while the bundle is being rebuilt** — force the affected platform API to probe
*before* anything can load your native. The platform caches that probe on first call, so running
it while only the system copy is mapped pins the answer:

```kotlin
fun runApp() {
    java.awt.Desktop.isDesktopSupported()   // adapted — warm-up, must run first
    startEverythingElse()
}
```

Write the removal condition next to it: *remove once the base library is excluded from the
bundle and the native tarball is republished.*

## Traps

**Your machine cannot reproduce it, for two independent reasons.** If the bundle was never
staged locally, the loader quietly resolves your native against a system-wide copy and nothing
is claimed at all. And even with the bundle staged, the break needs a host whose system copy is
*newer* than the bundled one — a build container pinned to an old distribution produces a bundle
that is fine on that distribution and broken on the current one. So: **log the resolved path of
every native you load** (`NativeLibrary.getInstance(name).file`). That log line is the only thing
that distinguishes "using the bundle" from "quietly using the system copy".

**The message names the wrong library.** The error text names a third, transitively-loaded member
of the family — not the API that failed, and not the copy that caused it. The symbol it could not
find actually lives in the library you bundled: newer system releases of that library export it,
your older bundled copy does not, and your copy owns the name. Match on the *family*, not on the
name in the message.

**The exclusion list gets written around the C runtime and stops there.** That is the rule that
was actually applied above: "things every desktop is guaranteed to have". The real rule is
broader — **anything the host process also loads**, which includes whatever your GUI toolkit's
own desktop integration opens at runtime, long after startup. Those are invisible to a
dependency walk of your native.

**A broken capability must not fail in silence.** When the platform API went unsupported, two
call sites of the same capability behaved oppositely: one was an `if` with no `else`, so every
external link in the app quietly did nothing — no error, no log, no message to the user — while
the UI framework's own link handler called the API on its first line and threw straight out of
the click handler, taking the app down. Give the capability a fallback chain and a visible last
resort:

```kotlin
// adapted
fun openUrl(url: String) {
    if (openWithDesktopApi(url)) return        // may be permanently unsupported
    if (openWithSystemLauncher(url)) return    // per-OS launcher, ordered by likelihood
    Logger.e(TAG, "Could not open $url by any means")
    showToast("Could not open the link")
}
```

Order the per-OS launchers by how likely each is to exist, and treat a successful spawn as good
enough — waiting for an exit code blocks the UI thread you were called on.

**Bundling a second copy of the process's C runtime is the same bug, harder.** The host runtime
is already mapped before your code runs; a second copy in one process cannot be made to work.

## Verifying it

1. **List what you actually bundled**, and read it as a human — not as a dependency walk:
   `ls <staged-native-dir>/lib`. Anything a stock desktop already provides is a candidate.
2. **Grep every call site of the fragile capability** and check each one has an `else`:
   `grep -rn "isDesktopSupported\|Desktop.getDesktop" --include='*.kt' <src>`
3. **Log the resolved path** for each native at load, and read it in a packaged build.
4. **Test on a host newer than the build environment.** A container image of the current
   distribution release is the cheapest reproduction — the break needs a system copy newer than
   the bundled one, so anything at or older than the build environment's release will pass.
5. After the exclusion lands, confirm the closure still resolves and the library still
   initialises — a staging step that drops a library the native genuinely needs fails at the
   *next* user instead. Gate the build on a load-and-initialise smoke test.
