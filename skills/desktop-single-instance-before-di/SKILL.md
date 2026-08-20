---
name: desktop-single-instance-before-di
description: Order a desktop app's startup so the single-instance guard runs before the dependency container and before anything opens on-disk state. Covers forwarding a second launch's arguments to the running instance and exiting, bridging a restore request from outside the UI framework into the live window, and the platforms where a second launch never produces a second process at all. Use when launching the app a second time crashes or corrupts settings, when a link opened while the app is running does nothing, or when the second window steals a file the first one owns.
---

# The single-instance guard belongs at the very top

Desktop. A second launch of your app is a second *process*. Everything that process does before
it discovers it is redundant, it does to files the first process already owns.

The dependency container is where it goes wrong, but not by the mechanism people assume. The
container is **lazy**: a definition is built when something first asks for it, and eagerness is
opt-in per definition (`single<SettingsStore>(createdAtStart = true)`). Constructing the store
usually opens nothing either — it builds cold flows, and the file is opened by the first *read*.

That read is never far away. In the reference it is the statement right after the container
starts: a blocking read of the saved language, to pick the UI locale. So the gap between
"container up" and "settings file open" is one line — and an eager definition that *does* touch
disk in its constructor closes even that. Either way the guard has to sit above the container.

Two processes then hold the same preferences file, and the store's write path — which saves to a
temporary file and renames it over the real one — fails on the operating systems that refuse to
replace an open file. Attested on Windows as a rename step failing with an input/output error at
launch, before any window appeared.

So the guard goes above the container, not inside the UI:

```kotlin
// adapted — order is the point
fun runDesktopApp(args: Array<String> = emptyArray()) {
    installCrashHandler()
    warmUpPlatformProbes()        // see `compose-desktop-runtime-hardening`
    setRendererProperties()

    val deepLinkArg = args.firstOrNull()?.takeIf { DEEP_LINK_ARG.matches(it) }

    // Single-instance guard — MUST run before the container starts.
    val isSingleInstance = SingleInstance.acquire(
        onRestoreRequest = { RestoreSignal.request() },
    )
    if (!isSingleInstance) {
        // Second instance: hand our argument to the running one, then leave.
        deepLinkArg?.let { PendingUri.write(it) }
        return                     // nothing on disk has been touched
    }

    if (!isMacOs) deepLinkArg?.let { DeepLinkHandler.onNewUri(it) }

    startContainer()               // first instance only
    …
}
```

The comment worth writing at that `return` is the invariant, not the mechanism: *nothing has
touched the settings file yet.*

## Bridging back into the running instance

The guard runs outside the UI framework, so its restore callback cannot touch composition state
directly. A tiny object with a buffered hot stream carries it across:

```kotlin
// adapted
private object RestoreSignal {
    private val _requests = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val requests: SharedFlow<Unit> = _requests.asSharedFlow()
    fun request() { _requests.tryEmit(Unit) }
}
```

`tryEmit` with spare buffer capacity means the guard's callback never suspends and never blocks
whatever thread the lock library calls it on. The window collects `requests` and un-hides,
un-minimises, raises itself, and consumes any forwarded argument.

## Traps

**Anything you "just" do before the guard is state the second process touched.** Reading a
settings value to pick a language, initialising a database, opening a log file, warming a cache —
each is a foothold in a directory the first instance owns. Keep the pre-guard region to things
that touch nothing: installing the crash handler, setting system properties, parsing argv.

**One platform never gives you a second process.** On macOS, opening a registered URL scheme or
clicking the dock icon of a running app delivers an application event to the *existing* process;
no second launch occurs, so the guard's restore callback can never fire for it. Register those
event handlers separately and route them into the same restore signal, or the app comes forward
for a second launch but not for a dock click.

**The forwarded argument must be written before the exit, and read after the raise.** The second
process's only job is to leave the value somewhere the first can find it. The first consumes it
in the restore collector, after making itself visible — consuming it earlier means a link opens
behind a still-hidden window.

**Filter argv by shape, not against a list of schemes.** A fixed list of accepted prefixes drops
every scheme added later; the symptom is that the app merely comes to the foreground while the
feature that needed the argument waits forever. Match any `scheme://…`:

```kotlin
private val DEEP_LINK_ARG = Regex("^[A-Za-z][A-Za-z0-9+.\\-]*://.+")
```

Full treatment of scheme registration and delivery is in `desktop-deep-link-plumbing`.

**A guard placed inside the UI is a guard that runs too late** even when it looks early — by then
the framework, the container and the window state have all initialised. The give-away is that
your "second instance" check lives in a composable or a window callback.

**The guard's own state must be released.** Whatever backs it — a lock file, a bound local port —
outlives an abrupt termination on some systems, and the next launch then believes an instance is
already running and exits immediately. Test a hard kill followed by a relaunch.

## Verifying it

1. **Launch the app twice while it is running** and confirm the first window comes forward and
   the second process exits, on every platform you ship.
2. **Read the entry function top to bottom** and check nothing before the guard touches disk.
   Drop the import block and the comments first, or the guard's own explanatory comment counts
   against it:
   `grep -n "<container-start-fn>\|DataStore\|openDatabase\|File(" <entry-file> | grep -vE
   "^[0-9]+: *(import|//|\*)"` — every surviving hit must sit *below* the guard's line number.
3. **Launch a second time with an argument** and confirm it reaches the running instance.
4. **Kill the process abruptly, then relaunch.** It must start, not silently exit as "already
   running".
5. On macOS specifically, test the dock-icon click and a scheme launch of the *running* app —
   those take the application-event path, not the guard path, and break independently.
