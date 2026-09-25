---
name: embed-media-engine-desktop
description: Embedding a native C media engine in a JVM desktop app — one handle per media item, a dedicated event-pump thread, pinning the output driver and creating the render context in the right order, confining every property write to the thread that also releases handles, feature-detecting optional engine options, and formatting numbers the way the engine parses them. Reach for it when the app stops while setting a property, when the engine opens a window of its own, or when a value the app clearly sets is silently ignored.
---

# Embedding a native media engine on desktop

A C media engine exposes a handle, a property bag, a command channel and an event stream. The
JVM-side job is almost entirely **ordering and thread ownership**: what must be set before
initialize, what must exist before the first load, and which thread may touch a handle. Get those
wrong and the failures are late, rare, and blame the wrong code.

Model used throughout: **one handle per media item** (so two exist at once during a transition),
one event-pump thread per handle, and one application thread that owns all handle mutation.

## Traps

**Pin the output driver explicitly, on every branch, before initialize.** The engine chooses its
output driver during initialize. Left unset, it auto-probes — and in a windowless JVM process an
auto-probe can land on something you never intended (here: a terminal-graphics driver, which
stopped the whole process during ordinary audio playback). Creating a render context afterwards
does **not** retroactively change a driver that initialize already chose. Treat a failure to pin
as fatal: refusing to create a player is recoverable, a hard native stop is not.

```kotlin
val pinned =
    if (audioOnly) {
        option("vid", "no")                 // adapted: property names are engine-specific
        requiredOption("vo", "null")
    } else {
        requiredOption("vo", "<embedding-driver>")
    }
if (!pinned) { lib.terminate_destroy(ctx); return null }
```

**Create the render context after initialize and before the first load.** Engines that expose an
embedding render API generally require it: video initialization fails, or the engine falls back to
a driver that opens **its own window**. Initialize only applies options; the video output is
instantiated when a file carrying video is loaded, so the window between the two is the correct
place. If the render context cannot be created, disable video decoding outright (a runtime
property) rather than leaving a pinned embedding driver with nothing behind it.

**Confine every property write to one thread — the one that also releases handles.** An
`isReleased`-style check does not protect you: the handle can be released between the check and
the native call. Setting the field synchronously (so getters read back immediately) and deferring
only the native call onto the owning thread closes that window by construction.

```kotlin
// adapted
override var volume: Float
    get() = internalVolume
    set(value) {
        internalVolume = value.coerceIn(0f, 1f)      // synchronous: the getter must read this back
        playerScope.launch {                          // single-threaded scope; releases run here too
            val percent = (internalVolume * 100).toInt()   // re-read, so a backed-up queue collapses
            forEachLiveHandle { it.setMasterVolume(percent) }
        }
        notifyListeners { onVolumeChanged(internalVolume) }
    }
```

The same hop is needed for seek, playback speed and any fade gain — anything that used to look
harmless because it "just sets a property".

**One thread is not enough when the engine's own event thread also writes.** The pump thread handles
events like "the audio output was re-created" by re-applying levels, so it issues writes too, and it
cannot hop anywhere. Any routine that reads several fields and issues more than one native write
needs a lock around the whole read-and-write, or two writers interleave and leave the device on a
combination neither intended. Volatile fields prevent torn reads, not interleaved *pairs* of calls.

**Every playback-wide setting must reach every live handle.** With one handle per item, speed,
volume and any fade gain are properties of the app, not of a handle. The one that gets missed is
the incoming handle mid-transition: it has typically been removed from the pre-cache collection
before being promoted, so it belongs to neither collection. Keep a single helper that enumerates
current + incoming + pre-cached, and route every setting through it. Where the engine's device
level is process-wide rather than per-handle, a missed handle does not merely stay wrong — it
re-asserts its stale level on its next reconfigure and **undoes** the others.

**A fresh handle starts at the engine's defaults.** Push the current levels onto a handle before it
becomes audible, and push the pair of related levels in **one** call: setting them one at a time
publishes an intermediate combination, and on a process-wide device level that intermediate is
audible on whatever is already playing.

**Feature-detect optional options; "no such option" is success when the option turns something
off.** An engine built without a subsystem never had the option — and is already in the state you
were asking for. Warning there reports the goal being met as a problem, on every handle created.

```kotlin
// adapted
fun optionalOption(name: String, value: String) {
    val rc = lib.set_option_string(ctx, name, value)
    if (rc == ERROR_OPTION_NOT_FOUND) {
        Logger.d(TAG, "Option '$name' absent in this build — already off, nothing to do")
    } else if (rc < 0) {
        Logger.w(TAG, "set_option_string($name=$value) failed: ${lib.error_string(rc)}")
    }
}
```

The same applies to optional *filters*: check what the engine actually accepted and degrade, rather
than driving a filter that is not in the chain — those commands fail on every animation step.

**Format numbers in the C locale on both sides.** Two independent failures with one cause:

- **Java side.** The engine's parsers accept `.` and nothing else. A default locale that formats with a
  comma is rejected silently — the setter returns a failure nobody reads, and the feature simply never
  moves. Use `String.format(Locale.ROOT, "%.4f", value)` for every number you hand the engine.
- **Native side.** The JVM sets the process locale from the environment during startup, so the
  engine inherits the user's locale and may refuse to start at all. Reset **only** the numeric
  category back to `C`, so dates, collation and currency elsewhere in the app are untouched. The
  category constant is not portable — verify it per platform rather than reusing one number.

**Shut down in order, and join without a timeout.** Stop the pump and join it *before* destroying the
core: the pump may be inside a call against this handle (its own event handlers call back into the
engine), and a bounded join gives up exactly when the core is busiest tearing down. Free the render
context before destroying the core, and run the whole blocking sequence off the playback thread.
Have the pump loop re-check its stop flag *after* waking, so no new call starts once shutdown has
begun, and wake it explicitly instead of waiting out its poll timeout.

## Verifying it

Run from the repo root, where the `core/media/media-jvm/...` paths below resolve.

1. **The video output is pinned before `mpv_initialize` (a failed pin is fatal, not a warning), and the render context is created after initialize but before the first `loadFile`:**

   ```bash
   grep -n 'requiredOption("vo"\|Refusing to initialize mpv without a pinned video output\|mpv_initialize(ctx)\|MpvVideoFrameSource()\|fun loadFile' core/media/media-jvm/src/main/java/com/simpmusic/media_jvm/mpv/MpvPlayer.kt
   ```

   Pass condition: both `requiredOption("vo", ...)` branches and the refusal message appear before `mpv_initialize`; `MpvVideoFrameSource()` and `loadFile` both appear after it, in that order.

2. **Feature-detection and the C-locale reset are real code, not just described:**

   ```bash
   grep -n -A3 "MPV_ERROR_OPTION_NOT_FOUND" core/media/media-jvm/src/main/java/com/simpmusic/media_jvm/mpv/MpvPlayer.kt
   grep -n "forceCNumericLocale()\|val INSTANCE" core/media/media-jvm/src/main/java/com/simpmusic/media_jvm/mpv/MpvLibrary.kt
   grep -n "MpvLibrary.INSTANCE\|lib.mpv_create()" core/media/media-jvm/src/main/java/com/simpmusic/media_jvm/mpv/MpvPlayer.kt
   ```

   Pass condition: the first shows `Logger.d`, not `Logger.w`, in the code after the match; the second shows `forceCNumericLocale()` inside the lazy `INSTANCE` initializer; the third shows `MpvPlayer` reading that same `INSTANCE` the line before it calls `mpv_create()` — the reset has already run.
