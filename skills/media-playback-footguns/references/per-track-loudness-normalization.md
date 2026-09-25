---
name: per-track-loudness-normalization
description: Apply per-track loudness normalisation with the platform's loudness enhancer when each track gets its own player — re-creating the effect per track because it stays attached to one audio session, skipping it while a remote-playback session is active, and clamping the gain that comes from metadata. Use when normalisation works on the first track and silently stops afterwards, when enabling it throws while nothing is playing, or when every other track in a queue comes out louder.
---

# Per-track loudness normalisation

The platform's loudness enhancer is constructed against an **audio session id** and stays attached
to it for its whole life. That is fine for a single long-lived player. It is a trap the moment a
new player is created per track: each new player gets its own session, and the effect you built for
the previous one is still perfectly alive, still enabled, and no longer connected to anything you
can hear.

The working shape is: on every track change, tear the old one down, build a new one against the
current session, then push the gain the track's metadata asks for.

```kotlin
override fun mayBeNormalizeVolume() {
    if (!normalizeVolume) { releaseEnhancer(); player.volume = 1f; return }
    if (!castState.value.isRemote && player.audioSessionId != AUDIO_SESSION_ID_UNSET) {
        try { enhancer?.release() } catch (_: Exception) {}
        try { enhancer = LoudnessEnhancer(player.audioSessionId) }
        catch (e: Exception) { Logger.e(TAG, "…: ${e.message}") }
    }
    …observe the track's loudness and setTargetGain…
}
```

Call it from the track-transition callback, not from setup.

## Traps

**Re-create it per track — never reuse.** The old effect does not report an error and does not stop
working; it applies its gain to a session nothing is playing on. From outside, normalisation
appears to work for exactly one track and then quietly does nothing, which reads as "the setting is
flaky" rather than as a lifecycle bug. To verify, log the session id you construct against on every
track and check it actually changes.

**Guard the unset session id.** Before a player has an output there is no session, and the id is
`0`. Constructing the effect with `0` throws, and the throw lands in the middle of a track change —
so a case that only happens at cold start, or right after a stop, takes the whole transition with
it. Compare against a named constant rather than a bare literal, since `0` reads like a plausible
id:

```kotlin
const val AUDIO_SESSION_ID_UNSET = 0
```

**Skip it entirely while a remote-playback session is active.** When output has been handed to
another device there is no local audio session to attach to, and the id is unset — so this is the
same guard, but it needs stating separately because the intent differs: not "wait until ready" but
"this feature does not apply here". Bundle both into one condition so a future edit cannot satisfy
one and drop the other.

**Release the old one inside its own `try`, and do not let it abort the track change.** Releasing
an effect whose session no longer exists can throw, and by that point you have nothing to gain from
the failure. Swallow it deliberately, with a comment saying so; wrapping both the release and the
construction in one `try` means a failed release skips the construction and the new track goes
un-normalised.

**Clamp the gain from metadata, and reject rather than clamp.** Loudness figures arriving from a
source are not validated by anyone. A value outside a sane window is not "a very loud track", it is
a bad row — clamping it to the boundary applies a large, wrong correction, while mapping it to zero
applies none:

```kotlin
val loudnessMb = format.loudnessDb.toMb().let { if (it !in -2000..2000) 0 else it }
enhancer?.setTargetGain(0f.toMb() - loudnessMb)
```

**Watch the units.** The platform's target gain is in **millibels**; track metadata is in decibels.
The conversion is ×100 into an `Int`, and losing it is a factor-of-a-hundred error that is
inaudible in one direction and destructive in the other. Keep the conversion in one named helper
rather than writing `* 100` at each site.

**Turning the feature off must release, not just disable.** Setting `enabled = false` leaves the
object attached; the next track then finds a stale reference and the enable/disable state depends
on which path ran last. Release it, null the field, cancel the observation job, and restore any
volume line the feature touched.

**If you run two players, you need two effects — and the second one is easy to leave unwired.** A
crossfade has an incoming player with its own session, which needs its own enhancer. A field
declared for it and released on teardown but never actually *constructed* compiles, runs, and
produces a queue where alternating tracks are normalised and the rest are not. Grep for the
assignment (`secondEnhancer =` with a constructor on the right) — not for the declaration, which
will be there.

**Cancel the observation job before relaunching it.** The gain comes from a flow keyed on the
current track; re-creating the effect per track means re-subscribing per track, and without a
cancel each transition leaves another collector alive, all writing gains for tracks that finished
long ago.

**Release everything at teardown.** Disable, release and null both effects in the service's own
shutdown path, inside a `try`/`catch` — effects outlive the players they were attached to, and a
release against a session that is already gone can throw; whatever teardown steps run after yours
should not die for an effect that no longer exists.

## Verifying it

Run from the repository root; the implementation is
`core/data/src/androidMain/kotlin/com/maxrave/data/mediaservice/MediaServiceHandlerImpl.kt`.

1. **The session guard compares against the named constant, not a bare `0`:**

   ```bash
   grep -rn "AUDIO_SESSION_ID_UNSET" \
     core/domain/src/commonMain/kotlin/com/maxrave/domain/data/player/PlayerConstants.kt \
     core/data/src/androidMain/kotlin/com/maxrave/data/mediaservice/MediaServiceHandlerImpl.kt
   ```

   Pass condition: one `const val AUDIO_SESSION_ID_UNSET = 0`, and the handler's guard reads
   `player.audioSessionId != PlayerConstants.AUDIO_SESSION_ID_UNSET` — never a literal `0`.

2. **Out-of-range loudness is rejected to zero, never clamped to the boundary:**

   ```bash
   grep -n -A4 "loudnessDb.toMb()" \
     core/data/src/androidMain/kotlin/com/maxrave/data/mediaservice/MediaServiceHandlerImpl.kt
   ```

   Pass condition: the branch is `if (it !in -2000..2000) 0 else it` — a reject-to-zero, not
   `.coerceIn(-2000, 2000)`, which would apply a large wrong correction instead of none.

3. **The second enhancer must be constructed, not only released** — grep for the assignment, not
   the declaration:

   ```bash
   grep -n "secondLoudnessEnhancer *=" \
     core/data/src/androidMain/kotlin/com/maxrave/data/mediaservice/MediaServiceHandlerImpl.kt
   ```

   Run against this codebase, the only hit is `secondLoudnessEnhancer = null` at teardown — no
   constructor call anywhere. That is this exact trap, caught live in the mined source: the second
   player of a crossfade never gets an enhancer, so every other track plays unnormalised. A codebase
   without the bug shows at least one hit with `LoudnessEnhancer(` on the right-hand side too.

4. **By hand: play three or more tracks back to back with normalisation on.** Log the session id
   each enhancer is constructed against on every track change. Observable outcome: the logged id is
   different every track, and perceived loudness stays consistent across the whole queue — not loud
   on track one and unnormalised from track two on, which is what a reused enhancer sounds like.
