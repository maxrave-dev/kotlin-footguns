---
name: forwarding-player-hot-swap
description: Swap the underlying player beneath a `ForwardingPlayer` at runtime while the media session and the UI keep one stable reference — re-attaching listeners and the video output, and answering the playlist questions a one-item timeline cannot. Use when next/previous buttons vanish from the system notification, when nothing updates after the first swap, when video stops rendering after a track change, or when reporting a playlist index makes the app stop.
---

# Hot-swapping the delegate under a forwarding player

Some designs need a *new* player object per track — one media item each, two alive at once during a
transition. Everything above (the session, the notification, the UI) wants one object that never
changes. A `ForwardingPlayer` whose delegate can be replaced bridges the two:

```kotlin
internal class DelegatingForwardingPlayer(initial: Player) : ForwardingPlayer(initial) {
    fun swapDelegate(newDelegate: Player) { … }
}
```

The swap is: snapshot the listeners → detach the video output from the old delegate → remove the
listeners → replace the delegate → re-add the listeners → re-attach the video output → verify.

## Traps

**Listeners are bound to the delegate at the moment they are added.** The wrapper registers an
internal adapter per listener against the *current* delegate; replacing the delegate leaves those
adapters pointing at the old object. From outside this looks like "everything worked for the first
track and then the notification and the UI froze". Track every listener yourself and cycle them:

```kotlin
private val tracked = mutableListOf<Player.Listener>()
override fun addListener(l: Player.Listener)    { tracked.add(l);    super.addListener(l) }
override fun removeListener(l: Player.Listener) { tracked.remove(l); super.removeListener(l) }
// in swapDelegate: tracked.toList() → super.removeListener each → set field → super.addListener each
// toList() snapshots defensively: a listener that re-enters add/removeListener mid-cycle would
// otherwise mutate tracked while this loop iterates it.
```

**The delegate field is not writable through the public API.** Reach it once, reflectively, in a
companion, and cache the handle; a per-swap lookup is both slow and gives you no single place to
fail. Fail *loudly* when the lookup returned nothing, rather than skipping the swap and leaving the
old delegate in place — a silent no-op swap is far harder to diagnose than a thrown error:

```kotlin
private val PLAYER_FIELD: Field? = try {
    ForwardingPlayer::class.java.getDeclaredField("player").apply { isAccessible = true }
} catch (e: Exception) { Logger.e(TAG, "…", e); null }
```

Treat this as version-coupled: pin the library version, and re-run one swap after every upgrade.

**Detach the video output from the old delegate *before* swapping, then re-attach after.** A native
video surface can be connected to one decoder at a time; leaving it attached makes the incoming
player's attach fail and the app stop. And nothing re-sends the surface to a new delegate on your
behalf, so without the re-attach video simply stops rendering while audio continues. Remember which
kind of output was set — surface, surface view, texture view, surface holder — because you have to
call the matching setter again.

**Answer the playlist questions yourself.** Each delegate holds one item, so its own
`hasNextMediaItem()`/`hasPreviousMediaItem()` are always false, and the session concludes there is
nothing to skip to: next/previous vanish from the notification and from external controllers. Inject
a tiny provider backed by your real queue and override **both** the per-command query and command set:

```kotlin
override fun getAvailableCommands(): Player.Commands {
    val nav = playlistNavigationProvider ?: return super.getAvailableCommands()
    return super.getAvailableCommands().buildUpon().apply {
        add(Player.COMMAND_SEEK_TO_PREVIOUS)                       // always: restart current track
        if (nav.hasNextMediaItem())     { add(Player.COMMAND_SEEK_TO_NEXT); add(Player.COMMAND_SEEK_TO_NEXT_MEDIA_ITEM) }
        if (nav.hasPreviousMediaItem()) { add(Player.COMMAND_SEEK_TO_PREVIOUS_MEDIA_ITEM) }
    }.build()
}
```

Overriding only `isCommandAvailable` is the common half-fix: some surfaces read the `Commands` set
instead and still show nothing.

**Do NOT override the item count or the current index.** It is tempting to report the real queue
position, and it is the one override that will stop the app: the session layer validates
`currentMediaItemIndex < timeline.windowCount`, and your delegate's timeline genuinely has one
window. Index and count must stay consistent with the delegate (count 1, index 0); only the
*navigation* answers come from your queue.

**"Previous" and "previous item" are two different commands.** `seekToPrevious` carries the
restart-the-current-track-if-past-three-seconds rule, which users expect from a hardware button.
`seekToPreviousMediaItem` must always move. Keep both in the provider, with the unconditional one
defaulting to the other so implementers can ignore the distinction when it does not matter:

```kotlin
interface PlaylistNavigationProvider {
    fun hasNextMediaItem(): Boolean
    fun hasPreviousMediaItem(): Boolean
    fun seekToNext()
    fun seekToPrevious()
    fun seekToPreviousMediaItem() = seekToPrevious()
}
```

**`play()`/`pause()`/`setPlayWhenReady()` need the same routing, or the intent falls through to the
raw delegate.** `ForwardingPlayer`'s own implementations act on whichever delegate is *currently*
attached, not on whatever tracks your play-intent across a swap. A system surface (notification,
Bluetooth, headset, Android Auto) calling through the wrapper resumes that delegate's audio while
your own "should the next item auto-play" bookkeeping stays exactly where it was — so the *next*
track-change swap reads stale intent and loads the incoming track paused. The current track keeps
playing; the transition silently does not. Override all three and route them through the same
provider that already answers the navigation questions above:

```kotlin
override fun play() {
    val nav = playlistNavigationProvider
    if (nav != null) nav.play() else super.play()
}
```

Same shape for `pause()` and `setPlayWhenReady()`; `super.X()` is correct only when there is no
provider at all — a swap without this trio plays the current track fine and goes silent on the next.

**Nobody replays the events the new delegate already fired.** The incoming player was prepared,
given its item and possibly started *before* the swap, so the listeners you just re-attached missed
its item-transition and metadata events, and the notification keeps showing the previous track.
Dispatch them by hand right after the swap — item transition, metadata, then available-commands so
the buttons re-evaluate — each in its own `try`/`catch`, so one bad listener can't abort the rest.

**Guard the degenerate swap and verify the real one.** Return early when the new delegate is the
current one (the cycle would remove and re-add every listener for nothing), and after setting the
field, read it back and log loudly if it did not take. A swap that silently failed presents as
"the app plays the old track's audio with the new track's artwork", which nobody diagnoses quickly.

## Verifying it

Run from the `core` submodule root. List the provider interface's members, then the wrapper's own
overrides, and confirm every provider name reappears as an `override fun` — a gap there is a
transport method routed straight to `super`, silently:

```bash
FILE=media/media3/src/main/java/com/maxrave/media3/exoplayer/DelegatingForwardingPlayer.kt
sed -n '/interface PlaylistNavigationProvider/,/^    }/p' "$FILE" | grep -oE 'fun [a-zA-Z]+'
grep -oE 'override fun [a-zA-Z]+' "$FILE" | sort -u
```

Behaviourally: start playback, pause and resume from the notification and a headset button, let a
track end naturally, and confirm the next item auto-plays.
