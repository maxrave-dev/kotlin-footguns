---
name: kotlin-string-into-c-varargs
description: "Kotlin/Native passes a Kotlin String in a C variadic argument as a UTF-8 char*, never as an NSString, so NSLog(\"... %@\", text) makes the format engine read string bytes as an Objective-C object pointer. Covers why it compiles, why it hides in debug-only loggers, the crash signature on an arm64e device, and the one call shape that is safe. Use when an iOS build crashes with EXC_BREAKPOINT inside NSLog or objc_opt_respondsToSelector, when adding iOS logging from Kotlin, or when reviewing any Kotlin call to a C function that takes a format string."
---

# A Kotlin String in a C vararg is a char*

`NSLog` is a C function with a variadic tail. Kotlin/Native lowers every variadic argument by its
static Kotlin type, and a `String` there is converted to a temporary UTF-8 C string. The format
specifier for that slot is your claim about the type, and `%@` claims an Objective-C object:

```kotlin
// adapted: the shape that shipped
NSLog("cache opened: cipher_version=%@", version)   // version: String -> passed as char*
```

The format engine calls `-description` on what it thinks is an object, dereferences the first eight
bytes of the text as an `isa` pointer, and the process dies. The **format string** is a different
parameter: it is not variadic, it is typed `NSString` in the header, and Kotlin bridges a `String`
there correctly. So the safe call puts the whole message in the format and escapes `%`:

```kotlin
// adapted
internal fun nsLogText(text: String) {
    NSLog(text.replace("%", "%%"))
}

nsLogText("cache opened: cipher_version=$version")
```

## Traps

**It compiles, and nothing warns.** The variadic parameter is `vararg args: Any?`, so any value
type-checks. In the 2.4.20 compiler the mapping is one branch of `mapCalleeFunctionParameter` in
`backend/konan/cgen/CBridgeGen.kt`: a `String` argument that is variadic gets `CStringArgumentPassing`.
The neighbouring `require(!variadic || !isObjCMethod)` makes the same call a compile error for a
variadic Objective-C *method* (the `stringWithFormat:` family), so only plain C functions take the
silent path, and `NSLog` is the one everyone reaches for.

**`%s` "works", and that is its own trap.** A `char*` is what `%s` expects, so the crash goes away.
Apple's format-specifier table says `%s` reads the bytes in the system default encoding, not UTF-8.
Any non-ASCII text in the message comes out garbled. It does not crash, so nobody notices.

**Debug-only call sites hide it until a release path copies the idiom.** Here two network loggers had
carried `NSLog("%@", message)` for four weeks behind a debug gate that defaults to off. The first
release-path line written in the same style crashed every TestFlight launch, on the first open of an
encrypted cache, before any screen loaded. A "log once" flag did not limit the damage. The flag lived
in a fresh object each launch, so it reset with each new process.

**The crash report names the wrong frame.** The faulting frame is `objc_opt_respondsToSelector` or
`objc_object::getIsa` inside `_NSDescriptionWithStringProxyFunc`, under `NSLog`. On arm64e this is
`EXC_BREAKPOINT (SIGTRAP)` with `pointer authentication trap`, not a bad access. The giveaway is
in the register dump: a register holding ASCII, here `x8: 0x6320302e30322e34`, which is
`"4.20.0 c"` read little-endian. That is your string's bytes, used as a pointer.

**Casting at the call site is not the fix to reach for.** The lowering keys on the static type, so an
argument already typed as an Objective-C class (an `NSError`, an `NSString` from a platform API) is
passed as an object and `%@` is correct for it. Re-typing a Kotlin `String` to make the same call pass
depends on bridging details this file has not verified. The format-string shape needs no such
reasoning, and one helper keeps every call site from re-deciding it.

**Escaping `%` is not optional.** The message becomes a format string, so a URL with `%20` or a
progress line with `50%` reads a vararg slot nobody filled. Replace `%` with `%%` once, in the helper.

## Verifying it

1. **Find every Kotlin `NSLog` whose format has `%@` and that passes arguments:**

   ```bash
   grep -rn --include='*.kt' -E 'NSLog\("[^"]*%@[^"]*",' . | grep -v '/build/'
   ```

   On the release that crashed, this returned three lines: the release-path cache log and the two
   debug loggers. After the fix it returns one line, the helper's comment that quotes the old call.
   Each code hit is a defect unless the argument's static type is an Objective-C class.

2. **Widen to every format literal that holds `%@`**, to catch other C formatting functions and
   wrappers around them:

   ```bash
   grep -rn --include='*.kt' '%@' . | grep -v '/build/'
   ```

   It returned the same three lines on the crashing release. Read each hit's callee. A `%@` slot is
   only safe when the Kotlin value is an Objective-C object.

3. **Run the scanner** from the project root. Its kotlin-string-c-vararg detector flags the
   `NSLog` shape:

   ```bash
   python3 .claude/skills/footgun-scan/scripts/scan.py --all
   ```

4. **On a device, exercise one call with each kind of argument.** Run a Release build that reaches
   the log line, then check Console.app. A fixed call prints the whole line. A broken one ends the
   process with the crash signature above. No simulator or unit test reaches this lowering.
