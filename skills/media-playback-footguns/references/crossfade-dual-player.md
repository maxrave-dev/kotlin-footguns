---
name: crossfade-dual-player
description: Build a crossfade between two media items with one player instance per item and a second live instance during the blend, then keep transport commands and playback settings correct while two players are audible. Use when adding a fade to a player, or when pausing mid-fade leaves the old track playing underneath, a seek appears to do nothing, playback speed reverts to 1.0x after a skip, or the volume slider fights the ramp.
---

# Dual-player crossfade

Two items must be audible at once, so a crossfade cannot be built on one player instance.
The shape that works on both Android (Media3/ExoPlayer) and desktop engines:

- **One player instance per media item.** The audible one is `currentPlayer`; the one
  fading in is `secondaryPlayer`. Upcoming items may already exist as precached instances.
- **One completion move for every early exit** — pause, seek, skip: release the outgoing
  instance, promote the incoming one, restore its normal levels, clear the fading flag.
  Call it *commit the incoming track as current*. The natural finish usually keeps a
  near-twin of its own; hold the two in lockstep — every cleanup step added to one must
  appear in the other, or extract their shared tail.
- **Equal-power (cosine/sine) gain curves**, driven by one cancellable job.

```kotlin
val fadeAngle = (progress * PI / 2).toFloat()
currentPlayer?.volume = targetVolume * cos(fadeAngle)   // outgoing
nextPlayer.volume     = targetVolume * sin(fadeAngle)   // incoming
```

`cos²θ + sin²θ = 1`, so total acoustic power is constant across the blend. A linear ramp
sums to ~0.5 power at the midpoint and is heard as a dip — loudness perception is
logarithmic, so the outgoing track "dies" before the incoming one has filled in.

## Traps

**A transport command arriving mid-fade acts on the wrong player.** `pause()` and the skip
commands usually get this treatment; `seekTo(positionMs)` is the one that gets forgotten,
on every platform. It fails twice over: nothing cancels the fade, so the outgoing track
keeps playing underneath, *and* the seek lands on the outgoing instance — while position
updates during a fade are read from the incoming one, which is what the progress bar shows.
From outside it looks like the seek was ignored and the old song is haunting the new one.
A command that stays on the fading pair must commit first:

```kotlin
override fun seekTo(positionMs: Long) {
    cachedPosition = positionMs          // so the bar does not snap back while queued
    scope.launch {
        if (isCrossfading) commitIncomingAsCurrent()
        currentPlayer?.seekTo(positionMs)
    }
}
```

Audit this by listing every override that reaches a player and checking each for the flag.
A command with no `isCrossfading` branch is a bug waiting for a user to fade and tap. The
branch does not always *commit*: a seek to a **different** item should instead cancel the
fade and release the incoming instance — committing would promote a track the user just
navigated away from. What the audit demands is the branch itself, not one fixed response.

**Committing must not touch the listener or the forwarding delegate.** Both were already
pointed at the incoming instance when the fade started. Re-pointing them here loses the
listener, or detaches the platform media session. The current-item index is likewise
already the incoming one. Commit therefore only: cancel the ramp job, release the outgoing
instance, move the incoming one into `currentPlayer`, restore its filters/volume/speed,
clear the flag. It deliberately does **not** change playback state or seek — the caller
decides whether to pause in place, advance, or go back.

**Playback settings must reach every live handle, not just the current one.** Speed, pitch,
volume and any programmatic fade factor belong to the session, not to an instance. The
instance that is easy to miss is `secondaryPlayer`: it is removed from the precache map
*before* being promoted, so for the length of a fade it belongs to neither collection.
Route every setter through one helper:

```kotlin
private fun forEachLiveHandle(action: (Player) -> Unit) {
    currentPlayer?.let(action)
    secondaryPlayer?.let(action)          // in neither collection during a fade
    precachedPlayers.values.forEach { action(it.player) }
}
```

Applying speed only to `currentPlayer` and re-asserting it when a fade ends looks correct
until the user changes speed and skips: the next track starts at 1.0x.

**On a shared output line, a missed handle does not stay wrong — it undoes the others.**
Where the engine exposes a device-mixer level (all handles of a process land in one output
session on some platforms), a handle left holding an older level re-asserts it on its own
output-reconfiguration event and overwrites everyone else's. Verify by logging the level
each handle believes it holds after a setter, not by listening once.

**A fresh instance starts at engine defaults.** Anything already in force must be pushed
onto a handle *before* it becomes audible, or a fade in progress jumps back to full volume
mid-ramp. When two levels exist, set them in one call — writing the master first publishes
a full-volume moment on the shared line that every other handle hears.

**Cancellation is a second completion path and needs its own cleanup.** The ramp job is
cancelled from more places than you expect — count them in your own code by grepping the
job's name. Its `catch (CancellationException)` must disable both filters,
restore the outgoing instance's speed/pitch, release the incoming instance, and clear the
flag — otherwise a cancelled fade leaves a live instance nobody owns and a flag that blocks
every future fade with no error anywhere.

**The trigger threshold is in wall-clock time, not media time.** At 1.5x speed, 5 s of
media is 3.3 s of listening, so a fade started at `duration - position <= fadeMs` begins
too late and is cut off by the item ending:

```kotlin
val speed = internalPlaybackSpeed.coerceAtLeast(0.1f)
val timeRemaining = ((dur - pos) / speed).toLong()
```

Add a preparation budget when the next item is *not* already precached — resolving and
buffering it otherwise eats into the audible part of the blend.

**Write engine properties from the thread that releases handles.** Volume, fade factor,
seek and playback parameters are often written from the UI thread while releases happen on
a player thread. A handle released between the "is it alive" check and the property write
stops the app hard. Confining every write to one single-threaded scope closes the window —
and, as a side effect, is what makes "pause, then restore" actually ordered.

## Verifying it

- Start a fade, then pause / seek / skip inside it. Correct behaviour: the item the UI
  already shows keeps playing (or freezes in place); the previous item is silent at once.
- Log the id of the handle promoted by the commit, and the count of live handles after it.
  Steady state between fades is exactly one plus the precache count.
- Do not verify curves by ear alone. Log `progress`, both volumes, and assert
  `out² + in² ≈ targetVolume²` for a few steps — both gains are scaled by the user's
  level, so the sum of squares equals that level squared, and only equals 1 at full volume.
