---
name: fgs-state-ended-trap
description: Suppress the "ended" playback state at a forwarding-player boundary while the underlying player is being replaced, so the media service is not torn down in the gap between one player finishing and the next starting. Use when background playback stops partway through a queue on some devices but never on your development phone, when the playback notification disappears between tracks, or when the app is frozen by the system mid-queue.
---

# The ended-state trap during a delegate swap

The "FGS" in the name is Android's **foreground service** — the status that keeps a media app
alive in the background. When each track gets its own player object, the end of a track looks like
this from the outside:

```
player A reports ended ──┐
                         │  ~25 ms
player B swapped in, plays ┘
```

For those few milliseconds the media session is asked for the playback state and answers *ended*.
Foreground status survives only while the player intends to play **and** the state is ready or
buffering — *ended* fails that test, so the service detaches its notification and stops being a
foreground service. (The state field is the one consulted, which is why the fix below remaps the
state rather than faking `isPlaying`.) On stock builds the app
usually survives long enough for player B to arrive. On the more aggressive power-management builds
some manufacturers ship, the app is frozen in that window and playback simply stops mid-queue.

The fix lives at the forwarding boundary — one flag and one getter:

```kotlin
@Volatile var suppressPlaybackEnded = false

override fun getPlaybackState(): Int {
    val state = super.getPlaybackState()
    return if (state == Player.STATE_ENDED && suppressPlaybackEnded) Player.STATE_BUFFERING else state
}
```

The wrapper reports *buffering* — true in substance, since the next player is being prepared — and
the service has no reason to stand down.

## Traps

**Remap in the getter, not by rewriting events.** The session layer does not only listen; it
*queries* the player when it builds its state. Filtering `onPlaybackStateChanged` before it reaches
listeners leaves the pull path untouched, and the pull path is the one that decides the service's
fate. Override the getter and let the events say whatever they say.

**Branch on "is there a next item".** Remapping unconditionally means the genuine end of a queue is
never reported: the UI keeps a spinner forever, the notification never clears, and the service never
stands down at all — which is a worse bug than the one being fixed, just quieter. Set the flag only
on the branch that is about to continue:

```kotlin
Player.STATE_ENDED -> {
    if (hasNextMediaItem()) {
        forwardingPlayer.suppressPlaybackEnded = true
        transitionToState(InternalState.PREPARING)
    } else {
        transitionToState(InternalState.ENDED)
    }
    handleTrackEndInternal()
}
```

**Clear it on *every* exit, not just the happy one.** A flag set and never cleared makes the player
permanently answer "buffering", so the service never releases and the transport controls behave as
if a track were forever about to start. The paths that must clear it:

- the next player actually started playing — the intended exit;
- the track finished loading and reached ready;
- **the load failed** — an error path that leaves the flag set is the trap inside the trap, because
  the app now looks busy forever instead of showing an error;
- `pause()` and `stop()` — the user ended playback themselves, and the flag must not outlive that
  decision.

Grep for the assignment, not the declaration: the count of `= false` sites should match the number
of ways out of the transition, and a review that only reads the getter will not notice one missing.

**Mark it `@Volatile`.** It is written from the playback thread as the track ends and read from
whichever thread the session queries on. Without it, the clear can go unseen and the player is
stuck reporting buffering for the rest of the process.

**This will not reproduce on your device.** The window is a few tens of milliseconds and only
matters where the system is willing to act within it. Testing means turning on the strictest
battery-optimisation setting the device offers, backgrounding the app, locking the screen and
letting a long queue run — not stepping through a debugger, which widens the window past anything
realistic. Log the value the *wrapper* returns rather than the one the underlying player reports;
those are the two different numbers this whole mechanism exists to keep apart.

**Suppression hides genuine end-of-stream from your own code too.** Anything else reading the
state through the wrapper — a UI that resets on ended, analytics that count completions — sees
buffering as well. Keep your internal state machine on its own signal (the adapter above knows
perfectly well that the track ended; it is what set the flag) and treat the remapped value as
something exported to the platform, not as your source of truth.

**Do not extend the window "to be safe".** The temptation is to set the flag on every transition,
or a little earlier, or to leave it until some later checkpoint. Each extension enlarges the period
in which a real stop is invisible to the platform, and the platform's view of your service is the
only thing keeping playback alive. Set it as late as possible, clear it as early as possible, and
make the clear unconditional in a `finally`-shaped position wherever the language allows.
