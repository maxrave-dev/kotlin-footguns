---
name: kmp-logger-facade
description: Put one small logging object in the shared module between every call site and the logging library, so a chatty subsystem can be silenced in one line and the library can be replaced without touching call sites. Covers the muted-tag set, a level-as-a-value enum for callers that pick severity at runtime, and why a single direct import of the library anywhere defeats both. Use when one subsystem drowns the log, when swapping or upgrading a logging library means editing hundreds of files, or when muting a tag has no effect on some of its output.
---

# One object between the app and the logging library

Shared (multiplatform) code. The facade is deliberately thin — four methods, one set, no
configuration surface — and its value is entirely in being the *only* door:

```kotlin
// adapted
object Logger {
    private val logger = <LoggingLibrary>.Logger

    // Tags suppressed at all levels. Add a tag here to silence its output globally.
    private val mutedTags = setOf(
        "SomeChattyWebSocket",
    )

    private fun isMuted(tag: String) = tag in mutedTags

    fun d(tag: String, message: String) {
        if (isMuted(tag)) return
        logger.d(tag = tag, message = { message })
    }

    fun i(tag: String, message: String) {
        if (isMuted(tag)) return
        logger.i(tag = tag, message = { message })
    }

    fun w(tag: String, message: String) {
        if (isMuted(tag)) return
        logger.w(tag = tag, message = { message })
    }

    fun e(tag: String, message: String, e: Throwable? = null) {
        if (isMuted(tag)) return
        logger.e(throwable = e, tag = tag, message = { message })
    }
}
```

Two properties follow from the shape, and they are the reason to bother:

- **Muting is one line.** A subsystem that logs on every frame or every socket frame gets added
  to the set; nothing else changes, and nothing has to be found and deleted.
- **The library is replaceable.** Swapping it edits one file, because one file imports it.

## Level as a value

Some callers pick severity at runtime — a shared base class that logs a result whose importance
depends on whether it succeeded. Give them an enum and one mapper, rather than a `when` at each
site:

```kotlin
// adapted
enum class LogLevel { DEBUG, INFO, WARN, ERROR }

// in the shared base class
protected fun log(message: String, logType: LogLevel = LogLevel.WARN) {
    when (logType) {
        LogLevel.DEBUG -> Logger.d(tag, message)
        LogLevel.INFO  -> Logger.i(tag, message)
        LogLevel.WARN  -> Logger.w(tag, message)
        LogLevel.ERROR -> Logger.e(tag, message)
    }
}
```

The enum belongs beside the facade, not in the UI module — the base class that consumes it lives
higher up, and putting the enum there would invert the dependency.

## Traps

**One direct import of the library defeats everything.** A call that goes to the library
straight past the facade is not muted, will not be re-tagged, and will not move when the library
does. This is the invariant to enforce mechanically, because it is invisible in review:

```sh
grep -rn "<logging.library.package>" --include='*.kt' <repo>
```

That must return exactly one hit — the facade's own import line. Any other hit is a leak.
The same grep, run before a library swap, is how you find out whether the swap is a one-file
change or a hundred-file one.

**The muted check returns before the call, so a muted tag drops its throwables too.** Muting is a
blunt instrument by design; a tag that legitimately reports errors should not be in the set. Mute
the chatty tag specifically, and split a subsystem into two tags if only its debug chatter is the
problem.

**The message parameter is eager even though the library's is lazy.** The facade takes a `String`
and passes `{ message }` down. The library's own laziness is therefore already spent: by the time
the lambda exists, the caller's string interpolation has run. That is fine for a formatted
message, and it is not fine for `Logger.d(TAG, "state: ${expensiveDump()}")` — which pays the
full cost even when the tag is muted, and on every release build. If a call site is expensive,
add an overload taking `message: () -> String` and forward it unevaluated; do not tell callers to
"just not log".

**A per-tag switch is not a severity switch.** A facade with only a muted set ships every level
to the library in every build. If you need "debug off in release", that control belongs here
too — one place, applied before the library call — not sprinkled through call sites as
`if (BuildFlags.DEBUG)`.

**Name the object the same as the library's own type at your peril.** A facade called `Logger`
wrapping a library type called `Logger` compiles only because the facade file imports one and
declares the other; a call site that adds the wrong import gets a confusing type error rather
than a helpful one. Worth a comment at the top of the facade file.

**Tags are free-form strings, so they drift.** `"Widget"` and `"widget"` are two tags and only
one of them is muted. Where a tag is used more than once, hang it off a `private const val TAG`
in that file, which is also what makes the grep for a tag's call sites work.

## Verifying it

1. **Run the single-import grep above.** Exactly one hit. Make it a lint rule or a CI grep if the
   codebase has more than a handful of contributors.
2. **Add a tag to the muted set and confirm the subsystem goes quiet across all platforms** — a
   platform whose output still appears is using the library directly, on that source set only.
3. **Check the facade sits in the lowest shared module** every other module already depends on:
   anything above it cannot be imported from below.
4. `grep -rn "Logger\.\(d\|i\|w\|e\)(\"" --include='*.kt' <src>` finds call sites passing a
   string literal tag inline; those are the ones that will drift from the muted set's spelling.
