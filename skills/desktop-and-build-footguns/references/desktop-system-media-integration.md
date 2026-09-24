---
name: desktop-system-media-integration
description: Wire a desktop app into each OS's system now-playing and transport surface behind one facade, so a failed native initialisation disables the integration and never takes playback down. Covers initialising on the platform's main thread inside a packaged app, reaching an OS media framework through the JVM's native-access layer, holding strong references to callbacks handed to the OS, and confining the integration to its own thread. Use when media keys or the system now-playing panel work under a plain Gradle run but not in the packaged app, when only the app name renders instead of the track title, or when transport callbacks stop arriving after a while.
---

# System media integration on three desktop OSes

Each desktop OS exposes a now-playing panel and hardware/media-key transport: macOS through its
media-player framework's info centre and command centre, Windows through its system transport
controls, Linux through the session-bus media interface. Put all three behind one facade in the
player handler and let each platform choose its backend.

```kotlin
// adapted — Linux and Windows share one cross-platform backend, macOS has its own
private val systemControls =
    if (platform is Platform.Linux || platform is Platform.Windows) {
        runCatching { CrossPlatformNowPlaying(platform) }.getOrNull()
    } else {
        null
    }

private val macIntegration: MacIntegration? by lazy {
    if (MacIntegration.isSupported()) MacIntegration.getInstance() else null
}
```

Two rules make that shape work, and they are the whole point of the facade:

- **A failed native init returns null, it does not throw.** `runCatching { … }.getOrNull()`.
- **Every call site is null-safe** (`systemControls?.setNowPlaying(…)`), so a null simply means
  the app has no system media controls. Nothing else in the player changes.

Every method on the integration itself repeats the guard, because init can fail *after* the
object exists:

```kotlin
// adapted
fun updateNowPlayingInfo(info: NowPlayingInfo) {
    if (!isSupported() || !initialized.get()) return
    try { … } catch (e: Exception) { Logger.e(TAG, "…", e) }
}
```

## Traps

**Your `main()` is not necessarily the platform's main thread.** macOS registers command handlers
against thread 0 only. A packaged launcher typically keeps thread 0 for the platform event loop
and starts the JVM on another thread — so nothing your dependency graph builds at startup runs on
the main thread. This is exactly why the integration works under a plain `gradle run`, where
`main()` owns thread 0, and silently does not in the shipped app. Ask the platform instead of
assuming, and hop:

```kotlin
// adapted
fun initialize(): Boolean {
    var result = false
    val reached = runCatching { MainQueue.runSync { result = initOnMainThread() } }
        .onFailure { Logger.e(TAG, "main-queue init threw: ${it.message}", it) }
        .getOrDefault(false)
    if (!reached) { Logger.e(TAG, "could not reach the main queue; integration stays disabled"); return false }
    return result
}
```

The main queue is reachable at all because the UI toolkit keeps a run loop on thread 0 and that
run loop drains it.

**Dispatching synchronously onto the queue you are already on deadlocks.** Check first
(`pthread_main_np()` on Darwin returns 1 on the initial thread) and just run the block inline.

**Never let an exception cross back into the platform's dispatch call.** Catch inside the work
block, stash it, and rethrow on your side after the dispatch returns — an exception escaping into
native dispatch stops the process. The same rule holds for every exported entry point on Windows:
guard each one, so no failure crosses the native boundary.

**Callbacks handed to the OS must be held.** The OS keeps only a function pointer. A callback
object created inside the registration function becomes garbage as soon as that function returns,
and the OS then invokes a trampoline for an object that is gone — typically minutes later, when
the user first presses a media key. Keep them in fields for the lifetime of the integration, and
do the same for any native buffer you handed over:

```kotlin
// adapted
private val callbacks = mutableListOf<Callback>()   // strong refs, released only in release()
private val nativeBuffers = mutableListOf<Memory>()
```

Clear them in `release()`, together with clearing the now-playing info and disabling every
command — not before.

**Framework string constants are not their literal names.** Some resolve to a short property name,
others to the full constant name. Read them out of the framework as exported symbols and
dereference (the symbol holds a pointer to the string object); do not hardcode guesses. Log which
ones failed to resolve — a missing key silently drops one field.

**The OS boolean is one byte, and the message send promotes it.** Passing a language-level boolean
where the OS expects its 1-byte boolean gives the wrong argument. Build the value explicitly and
pass it as an int through the message-send call.

**Set the media type before the display properties (Windows).** With the type unset, the panel
renders the app name and no title or artist. It is a one-line ordering fix that looks like a
metadata bug.

**Keep the Windows integration on its own dedicated thread, off the UI toolkit's event thread
(Windows).** This is the opposite arrangement from the macOS rule above — there the platform pins
initialisation to thread 0, which the UI toolkit owns; here the platform library must be confined
to a worker thread of its own and never run on the toolkit's event thread. Also Windows-attested:
initialising the component runtime has to tolerate a thread already initialised in a different
mode, and the OS media object needs to stay alive for the process lifetime rather than per-track.

**Artwork is a download, not a property write.** Fetch bytes off the UI path, cache by URL, and
skip the work when the URL has not changed — the now-playing info is rewritten on every progress
update, so an uncached fetch there repeats for the life of the track.

## Verifying it

1. **Test the packaged app, not `gradle run`.** Thread ownership differs, and that is the single
   most common reason this feature ships broken.
2. Log the thread the initialisation ran on and whether the main-queue hop was needed.
3. Confirm the facade is genuinely optional:
   `grep -rn "<facadeField>" --include='*.kt' <src>` — every hit must be `?.` or inside a
   null check. One unguarded call turns a disabled integration into a crash.
4. Exercise each remote command from the OS surface (media keys, the panel's buttons, and
   scrubbing the panel's position slider) — the position command carries a payload the others do
   not, so it is the one that breaks alone.
5. Leave the app idle for several minutes, then press a media key. A command that works
   immediately after launch and not later is a dropped callback reference.
