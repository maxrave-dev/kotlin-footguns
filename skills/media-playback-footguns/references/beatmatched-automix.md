---
name: beatmatched-automix
description: Derive an automatic crossfade duration and a tempo/key match from how far apart two tracks are, the way a DJ would — halftime normalisation before comparing tempos, beat-quantised durations, a front-loaded ramp and quantised gain/speed steps. Use when an automatic transition length feels arbitrary, when tracks an octave apart in tempo are treated as a huge gap, when tempo matching only lands after the outgoing track is inaudible, or when ramping speed produces ticks.
---

# Beat-matched automatic transitions

Given tempo (beats per minute) and musical key for both the outgoing and the incoming track — from
a streaming source's metadata, from local analysis, from a tag — three things can be derived:

1. **how long** the blend should last,
2. **how much to bend the outgoing track's tempo** so both share a beat during the overlap,
3. **how much to shift its pitch** so the two keys do not clash.

Everything is applied to the **outgoing** track only and dies with it, so the incoming track plays
at its natural tempo and pitch from its first solo moment.

```
base duration from current tempo   (slower track → longer blend)
  × tempo-gap factor               (bigger gap → longer, to hide it)
  × key-gap factor                 (harmonically distant → longer, to mask it)
  → snap to a whole number of beats → clamp to a sane range
```

## Traps

**Normalise halftime / double-time before comparing tempos.** 70 and 140 are the same groove; the
raw ratio says 2.0 and every downstream decision reads it as the largest possible gap. Fold the
ratio into a window around 1 first — and guard non-positive values *before* the loops, or a zero
tempo spins forever:

```kotlin
if (currentBpm <= 0 || nextBpm <= 0) return 1.0f
var ratio = nextBpm.toFloat() / currentBpm.toFloat()
while (ratio > 1.5f) ratio /= 2f
while (ratio < 0.67f) ratio *= 2f
```

The loops run in sequence, so a bad pair cannot make them alternate — what non-reciprocal bounds
actually cost is symmetry: one direction gets folded into a different window than the other, and
(70, 140) stops agreeing with (140, 70).

**Unknown must not read as compatible.** A key you cannot parse, and a key that is simply absent,
must return the *same* fallback — and that fallback must be greater than 1.0, i.e. "blend longer
because we know nothing". Returning 1.0 for an unparseable key means the blend gets *shorter*
exactly on the tracks you have the least information about, which is precisely backwards:

```kotlin
val currentCode = keyToWheel(currentKey, currentScale) ?: return UNKNOWN_GAP_DEFAULT_FACTOR
```

**Bend one side, not both.** Adjusting the incoming track leaves it at the wrong tempo after the
transition and needs a second ramp to undo it; adjusting only the outgoing one is self-cleaning —
released when the blend completes. The ratio is `nextTempo / currentTempo`, applied to the outgoing
player, so its effective tempo lands on the incoming track's.

**A linear ramp to the end matches tempo only when nobody can hear it.** With an equal-power
volume curve the outgoing track is already far down by 70 % of the blend; a tempo ramp that
reaches target at 100 % has matched nothing audible. Front-load it, then **hold**:

```kotlin
val linear = if (rampPortion <= 0f) 1f else (progress / rampPortion).coerceAtMost(1f)
val ramp = linear * linear * (3f - 2f * linear)      // smoothstep: slow → fast → slow
val outSpeed = lerp(1.0f, targetSpeedRatio, ramp)
```

with `rampPortion` around 0.6 — target reached by 60 % of the blend and held, so most of the audible overlap is beat-aligned.

**Quantise the tempo and pitch steps, and only push a changed value.** Rewriting playback
parameters fifty times a transition with sub-percent differences retriggers the resampler and each
retrigger is an audible tick. Snap to a step (2 % works) and compare against the last value pushed:

```kotlin
fun quantize(v: Float) = Math.round(v / SPEED_PITCH_STEP) * SPEED_PITCH_STEP
val q = quantize(rawSpeed * userSpeed)
if (q != lastPushed) { player.playbackParameters = PlaybackParameters(q, qPitch); lastPushed = q }
```

Note `rawSpeed * userSpeed`: the automatic ratio multiplies the user's own choice; drop it and their
setting is silently discarded for the length of every transition.

**Refuse a ratio outside the safe band instead of clamping it.** Past roughly ±25 % the bend is
audible as a fault rather than as a mix. A clamped value is the worst of both — still audibly
stretched, and still not matching. Return 1.0 and let the transition be an ordinary fade.

**Quantise the duration to whole beats, then clamp.** A blend that ends mid-bar sounds like a
mistake even when every other number is right. Pick from a list of musical beat counts by nearest
fit, then clamp to a range the UI can live with:

```kotlin
val beatMs = 60_000.0 / currentBpm
val beats = BEAT_COUNT_OPTIONS.minByOrNull { abs(it * beatMs - adjustedTargetMs) } ?: DEFAULT_BEATS
return (beats * beatMs).toInt().coerceIn(MIN_DURATION_MS, MAX_DURATION_MS)
```

**Key distance is circular, plus a mode term.** On the twelve-position wheel used by DJ software,
neighbouring numbers and the relative major/minor of the same number are compatible. The distance
is the shorter way round the circle *plus* one if the modes differ:

```kotlin
val diff = abs(a.number - b.number)
return minOf(diff, 12 - diff) + if (a.isMinor != b.isMinor) 1 else 0
```

A distance ≤ 1 needs no shift — return early, before computing any pitch ratio.

**A semitone is a ratio, not an offset.** `2^(n/12)`, i.e. `exp(ln(2) * n / 12)`. Search outward
from the smallest shift (`-1, +1, -2, +2`) and take the first that brings the distance to ≤ 1;
beyond a whole tone the shift is more noticeable than the clash it fixes, so give up and return
1.0.

**Normalise key names before matching them.** Sources spell accidentals out — `FSharp`, `CFlat` —
rather than using symbols, and case varies. Normalise, then map to a semitone; return a sentinel
(`-1`, or `null` from the wheel lookup) for anything unrecognised, never `0`, which is a real key.

**Metadata arrives late, or not at all.** Load it lazily right before the calculation and cache it
by track id, and have every derived value fall back cleanly — a fixed fallback duration, a ratio of
1.0 — so a track with no analysis still transitions, just without the matching.

## Verifying it

Run from the repository root against `core/media/media3/src/main/java/com/maxrave/media3/exoplayer/CrossfadeExoPlayerAdapter.kt`.

1. **The unknown-key fallback and the quantise-guard are in place, and the fold is symmetric:**

   ```bash
   grep -n "UNKNOWN_GAP_DEFAULT_FACTOR\|lastOutgoingSpeed\|playbackParameters =" \
     core/media/media3/src/main/java/com/maxrave/media3/exoplayer/CrossfadeExoPlayerAdapter.kt
   python3 -c "
   for r in (140/70, 70/140):
       while r > 1.5: r /= 2
       while r < 0.67: r *= 2
       print(r)"
   ```

   Pass condition: the factor is `> 1.0` (here `1.25`) and reused by name on the four listed paths; the
   `playbackParameters =` write sits behind `if (qOutSpeed != lastOutgoingSpeed || …)`; the fold prints `1.0` for both ratios.

2. **By hand:** queue two tracks with a large tempo gap and a compatible key, DJ crossfade on.
   Listen around 60% into the transition — the outgoing beat should already match, not still slide.
