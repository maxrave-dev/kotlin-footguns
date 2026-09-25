---
name: audio-fade-separate-gain-line
description: Implement a programmatic audio fade — a sleep timer, an alarm ramp, a duck — on a gain line of its own instead of the user's volume, and restore that gain from the player's own completion path. Use when a fade drags the volume slider down in the UI, when the app comes back permanently silent with a full slider, when a fade still ends in an audible click, or when audio briefly swells back after a fade completes.
---

# A fade needs its own gain line

A sleep timer that ends on a bare `pause()` chops the music off. Ramping to silence first
is a two-line change with three ways to get it wrong. The rule that avoids all three: the
fade gets **its own gain line**, multiplied with the user's volume at the point the value
reaches the audio path.

```kotlin
interface MediaPlayerInterface {
    var volume: Float           // the user's level — reported back to the UI
    var sleepFadeFactor: Float  // 0f..1f, the fade's own line
}
```

- **Android (Media3):** a small `AudioProcessor` in the chain, one instance per player, all
  reading the same `@Volatile` field: `arrayOf(crossfadeFilter, sleepFade)`.
- **Desktop:** engines commonly expose two levels — a device-mixer level and a software
  level. Put the fade on one and the crossfade ramp on the other; they then multiply and
  neither has to know the other exists.

## Traps

**Ramping the user's volume.** It is the obvious implementation and it is wrong twice over.
That value is reported back through the volume-changed callback, so the slider visibly
crawls to zero while the user watches. Worse, if the process ends mid-fade the persisted
level is now near zero: the app comes back silent with a full-looking slider, and no code
path restores it because nothing knows a fade was interrupted. The user's level must be
the one thing a fade never writes.

**Pausing the instant the ramp reaches zero.** Gain is applied *ahead* of a buffered output
stage. Several hundred milliseconds of already-attenuated-but-not-silent audio is still
queued when the ramp finishes, so the pause cuts it at a clearly audible level. Hold
silence for a short tail before pausing:

```kotlin
delay(remaining - fadeMs - tailMs)
fadeOutForSleep(fadeMs)     // ramps to 0
delay(tailMs)               // let the tail drain
player.pause()
```

Tune the tail against the platform's own output buffer; measure by ear at the boundary
rather than copying a number. Both fade and tail must be **clamped to fit inside what is
left** (`fadeMs.coerceAtMost(remaining)`, then `tailMs.coerceAtMost(remaining - fadeMs)`),
or an "end of current song" timer runs past the end of the song and pauses inside the next.

**Restoring the gain from the caller, right after `pause()`.** This is the subtle one.
`pause()` is asynchronous *and* suspends partway through (committing a crossfade joins a
job). A single-threaded dispatcher therefore does **not** order "pause, then restore": the
suspension releases the thread, the queued restore runs first, and the mixer re-opens over
the last of the audio — a short swell right after the fade. The restore belongs in the
player adapter's own completion path:

```kotlin
override fun pause() {
    scope.launch {
        try { /* commit any fade, then pause */ }
        finally { internalSleepFadeFactor = 1f }   // playback has genuinely stopped here
    }
}
```

**Putting the restore on the happy path instead of in `finally`.** The block above can throw
or be cancelled — committing a crossfade joins a job that may itself be cancelled. Any path
that skips the restore leaves every sample multiplied by ~0 for the rest of the process,
with a full volume slider and no way back. `finally` is not defensive style here; it is the
only correct placement.

**Forgetting an early-return branch of `pause()`.** A handoff to a remote-playback session
typically returns before the coroutine is ever launched. That branch must clear the factor
inline, or the attenuation outlives the remote session: the processor is still in the local
chain and keeps multiplying by ~0 when playback comes back.

**The timer's own `finally` must not double-restore.** The caller still needs a restore for
the *cancelled* path (the user turned the timer off, the scope went away mid-fade). Guard it
so the completed path leaves the job to the adapter:

```kotlin
finally { if (!stoppedPlayback) player.sleepFadeFactor = 1f }
```

**Capturing the gain instead of reading it fresh.** The processor must read the field on
every buffer, not once at configure time — otherwise a fade that starts, or keeps advancing,
in the middle of a crossfade never reaches the output. Same reason the desktop setter
re-reads the field inside the queued task rather than capturing the argument: if the queue
backs up, pending writes collapse onto the newest value instead of replaying a stale ramp.

**Making the processor inactive at full gain.** A processor that reports `isActive = false`
is dropped from the chain and is not reconsulted until the next flush — by which time the
timer has already stopped playback. Keep it always active and make the full-gain case a
bulk copy:

```kotlin
override fun isActive() = true

override fun queueInput(input: ByteBuffer) {
    val out = replaceOutputBuffer(input.remaining())
    val g = gain()
    if (g >= 1f) { out.put(input); out.flip(); return }   // every buffer, all playback
    input.order(ByteOrder.nativeOrder())
    while (input.remaining() >= 2) out.putShort((input.short * g).toInt().toShort())
    while (input.hasRemaining()) out.put(input.get())     // consume ALL of it
    out.flip()
}
```

Leaving even one byte unconsumed makes the pipeline re-offer the same buffer forever,
having made no progress.

**Linear ramps and unbounded step counts.** Use the same equal-power (cosine) curve as a
crossfade — `cos(progress * PI / 2)` — because loudness is perceived logarithmically and a
linear ramp sounds like it drops away early then lingers. And clamp the step count to the
duration: 50 steps at a 1 ms floor takes 50 ms no matter what duration was requested, so a
1-second fade silently becomes an instant one.

```kotlin
val steps = nominalSteps.toLong().coerceAtMost(durationMs).toInt()
val delayPerStep = (durationMs / steps).coerceAtLeast(1L)
```

## Verifying it

- Watch the volume slider through a full fade. It must not move.
- Kill the process mid-fade, relaunch, press play: audio at the user's level, immediately.
- Let a timer complete, then press play: full level, no swell, no residual attenuation.
- Cancel a timer mid-fade: level restored within a step or two.
- If the platform reports the applied gain, log it once per second during the ramp and
  confirm it reaches 0 *before* the pause and 1 *after* it, never between.
