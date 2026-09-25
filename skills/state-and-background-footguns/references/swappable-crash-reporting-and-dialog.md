---
name: swappable-crash-reporting-and-dialog
description: Ship a build with crash reporting and a build with none from one codebase, by swapping a module that exposes three top-level functions instead of an interface, so call sites are byte-identical and the no-tracking build provably contains no reporting code. Also covers a desktop crash dialog built on the older widget toolkit, because the modern UI may be exactly what just died, and how to marshal it onto that toolkit's event thread. Use when a privacy build must contain no reporting dependency at all, when a swapped implementation is drifting from its counterpart, or when the app dies with no visible error and no way for a user to send you the details.
---

# Two modules, three functions, no interface

The unit of the swap is a **module**, not a class. Two source modules share one package name and
one file name, and each defines the same three top-level functions:

```kotlin
// adapted — reporting module
package com.example.crashreporting

fun configCrashReporting(applicationContext: Context, dsn: String) {
    ReportingClient.init(applicationContext) { options -> options.dsn = dsn }
}

fun reportCrash(throwable: Throwable) {
    ReportingClient.captureException(throwable)
}

fun pushPlayerError(error: PlayerError) {
    ReportingClient.captureMessage("Player Error: ${error.message}, code: ${error.errorCode}")
}
```

```kotlin
// adapted — no-tracking module: identical package, identical signatures, logs instead
package com.example.crashreporting

fun configCrashReporting(applicationContext: Context, dsn: String) = Logger.d(TAG, "reporting disabled: start app")
fun reportCrash(throwable: Throwable) = Logger.e(TAG, "reporting disabled: crash: ${throwable.localizedMessage}")
fun pushPlayerError(error: PlayerError) = Logger.e(TAG, "reporting disabled: ${error.message}, code: ${error.errorCode}")
```

The build script picks one:

```kotlin
// adapted
if (isFullBuild) implementation(projects.crashReporting) else implementation(projects.crashReportingEmpty)
```

**Why top-level functions and not an interface.** There is no instance, so nothing to construct,
register, inject, or forget to register. The import line at every call site is the same string in
both builds, and so is the call. An interface would need a binding in each build's dependency
graph — a second place to keep in sync, and one where the no-tracking build can end up bound to
the real thing.

**Why three functions and not one.** Each is a distinct verb: configure once at start-up, report a
caught throwable, report a domain-level non-fatal that is not a throwable at all. Do not collapse
them into `report(Any)` — the third carries structured fields, and it is the one that grows.

**The no-op is not empty.** It logs. A privacy build still needs to be debuggable by the person
running it; a body that is literally `{}` deletes the only signal a maintainer has when reproducing
a user's report locally.

## The desktop crash dialog runs on the older toolkit

The uncaught-exception handler is installed first thing at start-up, before the UI framework
exists. When it fires, the modern UI is the least trustworthy thing in the process — it may be
exactly what threw. Build the dialog from the JDK's own widget toolkit, which needs nothing your
app initialised:

```kotlin
// adapted
fun install() {
    Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
        try {
            if (reportingConfigured) reportCrash(throwable)
        } catch (_: Exception) { /* reporting may never have initialised */ }

        try {
            if (SwingUtilities.isEventDispatchThread()) {
                showCrashDialog(thread, throwable)          // already on the event thread
            } else {
                SwingUtilities.invokeAndWait { showCrashDialog(thread, throwable) }
            }
        } catch (_: Exception) {
            System.err.println("Fatal crash in thread ${thread.name}:")
            throwable.printStackTrace()                     // last resort
        }

        exitProcess(1)
    }
}
```

The dialog carries the version, the thread name, the full stack trace in a selectable read-only
text area, and a **copy** button — the user's only realistic way to send you what happened.

**In the reference the two halves never meet.** The module pair above is an *Android library* —
Android namespace, a minimum SDK, the Android launcher as its only consumer — so the desktop entry
cannot depend on it. Its handler skips `reportCrash` and calls the vendor client directly, gated
on whether a key was compiled in: `if (dsn.isNotEmpty()) ReportingClient.captureException(t)`.
The sample above is therefore the composition you *want*, not the one that is there. Reaching it
means making the module pair multiplatform, so a desktop source set sees the same three functions
— not bolting on a second gate. The split already shows in the surface: the launcher calls
`configCrashReporting` and `pushPlayerError`, while `reportCrash` is defined in both modules and
called from nowhere, which is the drift the last trap below is about.

## Traps

**Report before you show.** The dialog blocks until dismissed and the process exits immediately
after; a report attempted after the dialog can be cut off by the user closing it.

**Wrap the report in its own catch.** The reporting client may never have been configured — that
is the normal state in the no-tracking build, and also the state when the crash happened *during*
start-up. A throw here would replace your crash dialog with a second crash.

**Dispatch to the event thread only when you are not already on it** — and *wait*, do not
post-and-forget. A synchronous "invoke and wait" issued *from* the event thread fails, and a
UI-thread crash is the common case, so the branch you skip testing is the one that fires most. The
process exits on the next line, so a fire-and-forget post shows nothing at all.

**Keep a last resort that needs no windowing at all.** If the event thread is itself broken, the
stack trace still has to reach standard error — that branch is what makes the feature honest on a
headless or wedged session. Set the look-and-feel inside its own try for the same reason: it is
cosmetic, and must not cost you the dialog.

**The two modules drift.** Nothing checks that their public surfaces still match except the
compiler — and the compiler only ever sees one of them per build. Compare them deliberately.

## Verifying it

1. **Diff the two modules' public surfaces**, not their bodies — and include the package line, or
   the check cannot see the thing that makes the swap work at all:
   `grep -rn "^package \|^fun " --include='*.kt' <reporting-module>/src <empty-module>/src`.
   The two lists must match line for line, paths aside.
2. **Build the no-tracking variant and grep the artifact's dependency list** for the reporting
   library. Absence there is the actual privacy claim; a disabled flag is not.
3. **Throw deliberately from a background thread and from the UI thread**, and confirm the dialog
   appears in both cases and the process exits.
4. **Throw before the reporting client is configured** — start-up crash — and confirm you get the
   dialog rather than a silent exit.
5. Confirm the handler is installed first. The install call sits inside the dialog's own
   `install()`, not in the entry file, so grep the source set rather than one file —
   `grep -rn "setDefaultUncaughtExceptionHandler" --include='*.kt' <desktop-src>` — then check
   that the entry function's *first statement* is the call to it.
6. Click **copy** and paste: an empty clipboard here means users send you screenshots instead.
