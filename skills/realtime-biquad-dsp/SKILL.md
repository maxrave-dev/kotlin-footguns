---
name: realtime-biquad-dsp
description: Build a small real-time IIR filter in pure Kotlin from the audio-EQ-cookbook formulas — low-pass, high-pass, or a bank of peaking sections — with cascaded stages for a steeper slope, independent state per channel, neutral stages that keep the state size fixed, and lazy coefficient recompute. Use when a sweepable filter is needed inside an audio callback, when a stereo filter collapses the stereo image, when the filter output is silence or NaN, or when sweeping a cutoff or dragging a band produces ticks.
---

# A real-time biquad in pure Kotlin

A biquad is five coefficients and four state values per channel. No library is needed and no
allocation happens per sample:

```kotlin
val y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
x2 = x1; x1 = x
y2 = y1; y1 = y
```

The coefficients come from the standard audio-EQ-cookbook formulas (Robert Bristow-Johnson).
For a low-pass, with `ω = 2π·fc/fs`, `α = sin(ω)/(2Q)`:

```kotlin
val v = (1.0 - cos(omega)) / 2.0
b0 = v;  b1 = 1.0 - cos(omega);  b2 = v
val a0 = 1.0 + alpha
a1 = -2.0 * cos(omega);  a2 = 1.0 - alpha
// then divide all five by a0
```

High-pass is the same shape with `v = (1 + cos ω)/2` and `b1 = −(1 + cos ω)`; `a0`, `a1`, `a2` are
identical. Reach for this when you need a filter you can *sweep* — a transition effect, a
tone control, a crossover — inside an audio callback that must not allocate.

## Traps

**Every channel needs its own four state values.** Sharing `x1/x2/y1/y2` between left and right
feeds each channel the other's history: the output is not "slightly wrong", it is a mono-ish
smear where the stereo image collapses and moving content sounds phasey. Name the fields so the
mistake is visible — `x1L`, `x1R` — and treat "one filter object, N channel state sets" as the
shape, not "N filter objects".

**Cascading N sections needs N *state sets* as well as N coefficient sets.** Two stages that share
delay lines is not a 4th-order filter — it is some other filter you did not design, each stage
feeding on the other's history. The coefficients may legitimately be
identical across stages; the state never is:

```kotlin
val mid = b0_1 * input + b1_1 * s1_x1L + b2_1 * s1_x2L - a1_1 * s1_y1L - a2_1 * s1_y2L
s1_x2L = s1_x1L; s1_x1L = input;  s1_y2L = s1_y1L; s1_y1L = mid
val out = b0_2 * mid   + b1_2 * s2_x1L + b2_2 * s2_x2L - a1_2 * s2_y1L - a2_2 * s2_y2L
s2_x2L = s2_x1L; s2_x1L = mid;    s2_y2L = s2_y1L; s2_y1L = out
```

**"Two cascaded Butterworth sections" is not a 4th-order Butterworth.** A single Q = 0.707 section
is −3 dB at the cutoff; two of them in series is −6 dB there. A textbook 4th-order Butterworth uses
two sections with *different* Q values and stays −3 dB at cutoff. Cascading identical 0.707
sections is a perfectly good choice — it is the Linkwitz–Riley shape used for crossovers — but the
cutoff you set is no longer the −3 dB point, so a comment reading "4th-order Butterworth" will send
the next reader looking for a bug that is not there. Verify the response rather than the label:
feed a sine at the cutoff and compare its output amplitude to a sine well inside the passband.

**Keep every stage in the chain at neutral gain — do not skip it.** In a bank of peaking sections it
is tempting to build only the bands the user moved. Then every adjustment resizes the coefficient
array *and the state array with it*, and a resized state array is a cleared one: the delay lines
vanish mid-stream and the user hears a click on every drag. With `A = 10^(gainDb/40)`:

```
b = [1 + alpha*A, -2*cos(w0), 1 - alpha*A]      a = [1 + alpha/A, -2*cos(w0), 1 - alpha/A]
```

At 0 dB, `A` is exactly `1`, so `alpha*A` and `alpha/A` are the same number and `b` equals `a`
term for term. After normalising by `a0`, `b0` is `(1+alpha)/(1+alpha)` — exactly `1.0` in IEEE
754 — and `b1 == a1`, `b2 == a2`:

```
0 dB → [1.0, -1.8951700997919003, 0.9115234478756887, -1.8951700997919003, 0.9115234478756887]
       b0 is exactly 1.0: True | b1 is a1: True | b2 is a2: True
```

So `H(z) ≡ 1` and the array sizes depend only on the format. It is not *bit*-identical: accumulating
left to right does not cancel exactly. Over 200 000 random samples from cleared state, one neutral
stage at the design point above (1 kHz, 48 kHz, Q 1.41) gives `max |y − x|` = `1.0e-14`, some 190 dB
below the 16-bit LSB; a full ten-stage flat bank gives `1.6e-12`. In the comment claim
"identity transfer function", not "bit-identical": the second one is checkable and false.

**A centre above half the sample rate gets the identity stage, not a `continue`.** 16 kHz is already
past Nyquist at 22.05 kHz, which some streams still use — and skipping the band there re-introduces
the resize you just eliminated, on a subset of streams. Substitute 0 dB and write the stage anyway.

**Entering bypass must clear the history.** Those delay lines were shaped by the *previous* setting,
so re-enabling with them still in there splices a fragment of the old shape onto the front of the
new one. It matters even when every stage is neutral, and the figures are setup-specific: seed a
500 Hz stage (48 kHz, Q 1.41) at +9 dB with a full-scale sine at its centre, then set it to 0 dB and
feed silence — the residue starts at 1.58 full scale and is still 1.5e-2 two hundred samples later.

**Capture `a0` before you overwrite anything with it.** The normalisation divides all five
coefficients by the raw `a0`, and `a0` is built from `alpha`, which several formulas also reuse.
Capture it in a local, then divide: doing it in place, one coefficient at a time, in the wrong
order, produces plausible-looking coefficients and a filter that either goes silent or runs away.

**Clamp the cutoff into `20 .. (sampleRate / 2 − 1)`.** Past half the sample rate the design has
no meaning: the recursion stops being stable, the output grows without bound until it overflows
into NaN — and once a NaN enters `y1`, every subsequent sample is NaN forever, because the state
feeds back. Silence that never recovers after one bad parameter write is the signature.

```kotlin
val clamped = cutoffHz.coerceIn(20f, (sampleRate / 2f) - 1f)
```

**Recompute lazily, on a dirty flag, and only at a buffer boundary.** Trigonometry per sample is
wasteful; worse, coefficients written from another thread mid-buffer leave the filter running half
one set and half another. Set a `@Volatile coefficientsDirty` from every parameter setter — the
cutoff **and** the filter type, forgetting the type is the classic one — and consult it once at the
top of each buffer.

**Sweep exponentially, not linearly.** Hearing is logarithmic: a linear ramp from 20 kHz to 200 Hz
spends most of its time in a region nobody can hear it move through and then lurches. Interpolate
in the log domain:

```kotlin
fun exponentialInterpolate(start: Float, end: Float, t: Float): Float {
    if (start <= 0f || end <= 0f) return end
    return exp(ln(start) + (ln(end) - ln(start)) * t).toFloat()
}
```

**Reset the history whenever the stream changes, and when the filter is switched off.** On a flush,
a seek, or a disable, the delay lines still hold the last stream's samples; re-enabling the filter
then starts it with foreign history and produces an audible transient. `reset()` zeroes state only
— never coefficients, or the first buffer after every seek runs at pass-through.

**Coefficients are cross-thread, state is not.** Mark the coefficient fields `@Volatile` because
a UI or animation thread writes them; leave the state fields plain, because only the audio thread
touches them and volatile reads in the inner loop are pure cost.

**Scale to and from the sample format explicitly.** Work in `Double` in the range −1…1, and clamp
on the way out before converting back — an IIR filter can overshoot past full scale at a transient,
and an unclamped conversion wraps into a loud click rather than clipping:

```kotlin
output.putShort((filtered.coerceIn(-1.0, 1.0) * Short.MAX_VALUE).toInt().toShort())
```
