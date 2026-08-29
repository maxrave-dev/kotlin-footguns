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
identical. Reach for this when you need a *sweepable* filter — a transition effect, tone control,
crossover — inside an audio callback that must not allocate.

## Traps

**Every channel needs its own four state values.** Sharing `x1/x2/y1/y2` between left and right feeds
each channel the other's history: not "slightly wrong" — a mono-ish smear where the stereo image
collapses and moving content sounds phasey. Name the fields so the mistake is visible — `x1L`, `x1R`
— and treat "one filter object, N channel state sets" as the shape, not "N filter objects".

**Cascading N sections needs N *state sets* as well as N coefficient sets.** Two stages sharing delay
lines is not a 4th-order filter — it is some other filter, each stage feeding on the other's
history. Coefficients may legitimately be identical across stages; the state never is:

```kotlin
val mid = b0_1 * input + b1_1 * s1_x1L + b2_1 * s1_x2L - a1_1 * s1_y1L - a2_1 * s1_y2L
s1_x2L = s1_x1L; s1_x1L = input;  s1_y2L = s1_y1L; s1_y1L = mid
// stage 2 is the identical shape, reading `mid` and writing its OWN s2_* state — never s1_*
```

**"Two cascaded Butterworth sections" is not a 4th-order Butterworth.** A single Q = 0.707 section
is −3 dB at the cutoff; two of them in series is −6 dB there (reproduced below). A textbook
4th-order Butterworth uses two sections with *different* Q values and stays −3 dB at cutoff.
Cascading identical 0.707 sections is a perfectly good choice — it is the Linkwitz–Riley shape used
for crossovers — but the cutoff you set is no longer the −3 dB point, misleading anyone who reads
"4th-order Butterworth" into hunting a bug that isn't there.

**Keep every stage in the chain at neutral gain — do not skip it.** In a bank of peaking sections it
is tempting to build only the bands the user moved. Then every adjustment resizes the coefficient
array *and the state array with it*, and a resized state array is a cleared one: the delay lines
vanish mid-stream and the user hears a click on every drag. With `A = 10^(gainDb/40)`:

```
b = [1 + alpha*A, -2*cos(w0), 1 - alpha*A]      a = [1 + alpha/A, -2*cos(w0), 1 - alpha/A]
```

At 0 dB, `A` is exactly `1`, so `alpha*A` and `alpha/A` are the same number and `b` equals `a` term
for term — `b0` normalises to exactly `1.0` in IEEE 754, and `b1 == a1`, `b2 == a2` (reproduced
below). So `H(z) ≡ 1`, and the array sizes depend only on the format. It is not *bit*-identical:
accumulating left to right does not cancel exactly: 200 000 random samples from cleared state give
one neutral stage (1 kHz, 48 kHz, Q 1.41) `max |y−x|` = `1.0e-14` (190 dB below the 16-bit LSB), a
ten-stage flat bank `1.6e-12`. Claim "identity transfer function" in comments, never "bit-identical"
— checkable, and false. The same fix applies when a band's centre exceeds Nyquist (16 kHz on a 22.05
kHz-Nyquist stream): substitute the identity stage rather than a `continue`, for the identical
fixed-array-size reason.

**Clear the history on bypass, on a stream change, and on disable — any discontinuity.** Delay lines
shaped by the *previous* setting splice their old shape onto the new one if left in place, even when
every stage is neutral, and even on an ordinary seek. Example: seed a 500 Hz stage (48 kHz, Q 1.41)
at +9 dB with a full-scale sine, switch to 0 dB and feed silence — residue starts at 1.58 full
scale, still 1.5e-2 two hundred samples later (figures are setup-specific). `reset()` zeroes state
only — never coefficients, or the first buffer after every seek runs at pass-through.

**Capture `a0` before you overwrite anything with it.** The normalisation divides all five coefficients
by the raw `a0`, and `a0` is built from `alpha`, which several formulas also reuse. Capture it in a
local, then divide: doing it in place, one coefficient at a time, in the wrong order, produces
plausible-looking coefficients and a filter that either goes silent or runs away.

**Clamp the cutoff into `20 .. (sampleRate / 2 − 1)`.** Past half the sample rate the design is
meaningless: the recursion goes unstable and overflows into NaN — and once NaN enters `y1`, every
sample after it is NaN forever, since the state feeds back. Silence that never recovers after one
bad parameter write is the signature.

```kotlin
val clamped = cutoffHz.coerceIn(20f, (sampleRate / 2f) - 1f)
```

**Recompute lazily, on a dirty flag, and only at a buffer boundary.** Trigonometry per sample is
wasteful; worse, coefficients written from another thread mid-buffer leave the filter running half
one set, half another. Set `@Volatile coefficientsDirty` from every parameter setter — cutoff
**and** filter type, forgetting the type is the classic miss — and consult it once per buffer.

**Sweep exponentially, not linearly.** Hearing is logarithmic: a linear ramp from 20 kHz to 200 Hz spends
most of its time in a region nobody can hear it move through and then lurches. Interpolate in the log domain:

```kotlin
fun exponentialInterpolate(start: Float, end: Float, t: Float): Float {
    if (start <= 0f || end <= 0f) return end
    return exp(ln(start) + (ln(end) - ln(start)) * t).toFloat()
}
```

**Coefficients are cross-thread, state is not.** Mark the coefficient fields `@Volatile` because a UI
or animation thread writes them; leave the state fields plain, because only the audio thread touches
them and volatile reads in the inner loop are pure cost.

## Verifying it

1. **Two numeric claims above, reproduced directly: the identity-stage coefficients and the −3 dB vs
   −6 dB cascade:**

   ```bash
   python3 -c "
   import math, cmath
   w=2*math.pi*1000/48000; c=math.cos(w); al=math.sin(w)/(2*1.41); A=1.0
   b0,b1,b2 = 1+al*A, -2*c, 1-al*A
   a0,a1,a2 = 1+al/A, -2*c, 1-al/A
   print('identity:', b0/a0, b1/a0, b2/a0, '| b1==a1:', b1==a1, 'b2==a2:', b2==a2)
   al2=math.sin(w)/(2*0.707); b0=(1-c)/2/(1+al2); b1=(1-c)/(1+al2); a1=-2*c/(1+al2); a2=(1-al2)/(1+al2)
   z=cmath.exp(-1j*w); H=(b0+b1*z+b0*z*z)/(1+a1*z+a2*z*z)
   print('cascade dB:', 20*math.log10(abs(H)), 20*math.log10(abs(H*H)))"
   ```

   Pass condition: `identity` prints `1.0 -1.8951700997919003 0.9115234478756887` (b0 exactly `1.0`)
   plus `b1==a1: True b2==a2: True`; `cascade dB` prints roughly `-3.01 -6.02` — one stage is
   textbook, two aren't.

2. **By hand:** sweep a filter's cutoff slowly while audio plays, then separately toggle it off and back
   on — a click or zipper noise while sweeping means coefficients aren't gated on a dirty flag or are
   recomputed mid-buffer, a thump after re-enabling means the delay lines weren't cleared. Separately, feed
   a steady sine at the cutoff through one 0.707-Q stage then the same stage cascaded twice — the second
   should sound roughly twice as attenuated, confirming −3/−6 dB by ear.
