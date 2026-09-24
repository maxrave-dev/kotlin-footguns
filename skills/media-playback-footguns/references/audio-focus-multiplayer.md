---
name: audio-focus-multiplayer
description: Hold Android audio focus once at app level when several player instances are alive at the same time — dual-player crossfade, precached players — and keep focus-driven ducking off whatever gain line a fade already owns. Use when background playback dies between tracks, autoplay stalls after the first item, a duck never takes effect or never lifts, or volume jumps back to full in the middle of a transition.
---

# Audio focus with more than one live player

Android's per-player focus handling assumes one player for the life of the app. A
crossfade breaks that assumption: instances are created, promoted and released constantly.

- Releasing the outgoing instance **abandons focus for the whole app**.
- The incoming instance was built with focus handling **off**, so it never re-requests it.
- Result: the app is playing with no focus. The system pauses it at the next opportunity —
  or another app takes over and it never comes back.

The fix is one focus request owned by the component that owns the swap:

```kotlin
ExoPlayer.Builder(context)
    .setAudioAttributes(audioAttributes, /* handleAudioFocus = */ false)  // every instance
    .build()
```

```kotlin
private val audioFocusRequest by lazy {
    AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
        .setAudioAttributes(/* USAGE_MEDIA, CONTENT_TYPE_MUSIC */)
        .setOnAudioFocusChangeListener(audioFocusListener)
        .setWillPauseWhenDucked(false)     // we duck ourselves
        .build()
}

private fun requestAudioFocusInternal(): Boolean {
    if (hasAudioFocus) return true         // idempotent
    hasAudioFocus = audioManager.requestAudioFocus(audioFocusRequest) ==
        AudioManager.AUDIOFOCUS_REQUEST_GRANTED
    return hasAudioFocus
}
```

Focus now survives every swap, because no player instance ever held it.

## Traps

**Leaving `handleAudioFocus = true` on "just the main" instance.** There is no main instance
— the one holding focus is released at the end of every transition. Set it `false` on every
instance you build, including precached ones, and let the adapter hold the single request.

**Requesting focus only from the play button.** Playback also starts from paths the user
never taps: the transition that starts the incoming instance, and the load-and-play path
used when a queue advances. Each of those must call the idempotent request. Because it is a
no-op while focus is held, calling it in three places costs nothing and closes the gap where
the app resumes with no focus after a transient loss.

**Abandoning focus on every player release.** Abandon only where playback genuinely ends —
`stop()`, `release()`, and the branch that hands playback to another output. A release that is
part of a swap must not touch focus. Keep the request object itself as a single `lazy`
field: abandoning with a *different* request object than the one granted does nothing and
fails silently.

**Ducking on the same gain line as the fade ramp.** A crossfade rewrites the player volume
~50 times per transition. A duck written to that same line is erased by the next ramp step,
and when the duck lifts it writes full volume over a fade in progress — heard as the music
jumping back to full mid-transition. Guard both directions on the fading flag:

```kotlin
AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK ->
    if (!isCrossfading) currentPlayer?.volume = internalVolume * duckVolumeFactor

AudioManager.AUDIOFOCUS_GAIN ->
    if (!isCrossfading) currentPlayer?.volume = internalVolume   // don't fight the ramp
```

This is a workaround, not the cure. The structural fix is the one a sleep-timer fade already
needs: give the duck **its own gain line** and multiply the lines together at the audio path,
so neither writer can erase the other. Reach for that as soon as a second automatic gain
appears — two writers on one line is the pattern, and each new one doubles the interactions.

**Restoring the duck to a hardcoded 1.0f.** Restore to the *user's* level
(`internalVolume`), never to full. Restoring to full silently discards the volume setting
after every navigation prompt.

**Treating all three losses the same.** They mean different things and want different
responses:

| Focus change | Response |
|---|---|
| `LOSS` | permanent — pause, clear the resume flag, mark focus not held |
| `LOSS_TRANSIENT` | pause, **and record whether you were actually playing** so regain resumes only then |
| `LOSS_TRANSIENT_CAN_DUCK` | attenuate, do not pause |
| `GAIN` | restore the level, resume only if the flag was set |

Resuming unconditionally on `GAIN` starts music the user had paused before the interruption.

**Ducking while a programmatic fade is running.** A duck and a sleep-timer fade are two
independent attenuations. Once each has its own line the answer is simply that they
multiply; sharing a line makes it a question with no good answer.

**Assuming focus and the media session agree.** A swap moves the session's listener to the
incoming instance. Focus is unrelated and app-scoped. Do not derive one from the other, and
do not let the session's own focus handling be enabled alongside yours — two owners fight.

## Verifying it

- Log the grant result on every request and every abandon. Between the first item and the
  last, `hasAudioFocus` must never go false; a false in the middle of a queue is the bug.
- Play with the screen off through at least three transitions. Playback dying between items
  is the classic signature of focus lost on a swap.
- Trigger a duck (a navigation prompt, or any app requesting transient-can-duck) both during
  steady playback and in the middle of a fade, and confirm the level returns to the *user's*
  level afterwards in both cases.
- Take a phone call mid-playback and mid-fade. Correct: pause, then resume at the right
  level. Incorrect: resumes at full volume, or resumes when you had it paused.
- `grep -n "requestAudioFocus\|abandonAudioFocus"` should show one request object, requests
  from every path that starts audio, and abandons only from terminal paths.
