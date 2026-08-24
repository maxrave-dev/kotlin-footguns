---
name: one-setting-two-backends
description: Make one stored value mean the same thing on two unrelated audio backends by defining the band centres, the width and the range once, verifying both against a reference implementation instead of by ear, and declining the platform's built-in effect whose parameters vary per device. Use when a tone or gain setting is being added on more than one platform, or when the same saved setting sounds different on each.
---

# One curve, two backends

Two platforms, two entirely different audio engines, one stored setting. It only survives the trip
if the *definition* — centres, width, range — lives in one place and both backends are proven
against a third, neutral implementation. "It sounds about right on both" is not a check; the whole
point of a stored curve is that a value dialled in on one device transfers to another.

Pin the definition where both sides can quote it, and make the second definition point at the first:

```kotlin
/**
 * The ten band centres, in Hz. Identical to the constant the other backend passes to its own
 * filter, and to the centres a published fixed-band profile set is generated at — up to the
 * rounding that set applies to its two lowest bands when it writes them out — so one stored curve
 * means the same thing on both platforms and an imported profile lands on the bands it was
 * computed for.
 */
val EQUALIZER_BANDS_HZ = intArrayOf(31, 62, 125, 250, 500, 1_000, 2_000, 4_000, 8_000, 16_000)

/** Q per band, matching the width the other backend passes and the Q the profiles are built at. */
private const val EQUALIZER_Q = 1.41
```

## Traps

**Two constants drift silently, and the symptom is not a bug report.** Nothing crashes when the
centres disagree: the setting still applies, still sounds like *something*, and only ever fails the
comparison a user makes between their two devices. Neither backend can detect it. Put the number in
one file per backend at most, with each naming the other, and treat any third copy as a defect.

**A width constant without its unit is the classic drift.** The same band width is expressed as Q,
as bandwidth in octaves, or as Hz, depending on whose API you are holding — and 1.41 is a
*plausible-looking* number in all three. Copy the value together with the parameter that selects the
unit (`width_type=q` and `width=1.41` travel as a pair), and name the unit in the constant's KDoc so
the next reader does not have to infer it from the engine on the other side.

**Verify against a reference implementation, not against each other.** Two backends that agree can
both be wrong in the same way — most often because one was written by reading the other. Take a
neutral third implementation of the same textbook filter, drive an impulse through it, and compare
the measured magnitude to your own coefficients analytically. Anything worse than a few thousandths
of a dB at the centres means one of you has the wrong parameterisation.

**Declining the platform's own effect API is a decision worth writing down.** A built-in equalizer
is implemented by the device's own audio stack: its band count, its centres and its response all
vary by handset. A curve dialled in on one phone does not transfer to another phone, let alone to a
desktop build or to an imported profile — which is the entire property being bought here. The cost
of writing the filter yourself is a page of arithmetic; the cost of the built-in one is that the
stored value no longer means anything.

**Two effects on one output multiply.** If the platform effect stays reachable beside your own, a
user with both engaged gets the product of the two curves and blames yours. When the in-app one
becomes the answer, the other has to *go* — and removing it has its own audit; see
`removing-a-feature-audit-shared-handles`.

**Where the trim sits relative to the bands has to match on both.** A gain stage ahead of the bands
takes headroom out before anything is boosted; the same stage behind them takes it out after the
boost has already clipped. The response is identical either way — all the stages are linear — so
this never shows up in a magnitude comparison, only as distortion on one platform.

**Once an external profile format drops in untouched, your constants are a compatibility contract.**
A published fixed-band profile set is generated at particular centres, at a particular Q, bounded to
a particular range. Matching all three is what lets a profile be imported with no conversion at all
— and it also means changing any of them later silently invalidates every profile already stored.
Record that in the constant's KDoc, next to the number.

**A backend addressed by a formatted string needs a locale-independent formatter.** Where one side
builds its filter graph as text, `String.format("%.4f", gain)` picks up the JVM default locale — on a
`vi_VN` device that is `0,9800`, and the engine's own parser stops at the comma and rejects the value:

```
String.format(new Locale("vi","VN"), "%.4f", 0.98f)  →  0,9800
String.format(Locale.ROOT,           "%.4f", 0.98f)  →  0.9800
Float.toString(0.98f)                                →  0.98      (always locale-independent)
```

`Locale.ROOT` is load-bearing, not pedantic — and forcing the *native* numeric locale does nothing
for numbers formatted on the JVM side, so both are needed if you rely on either.

**A label list is a third copy of the definition.** The UI's `"31", "62", … "16k"` lives beside the
filter constant, not derived from it, and nothing catches a drift: the response stays correct while
the user drags the wrong band. Derive the labels from the centres, or assert equal lengths in a test.

**Both backends need the range too, not just the centres.** A stored curve produced under a ±12 dB
control and re-opened on a build whose control stops at ±10 is pinned to the end of the track while
holding a different number — see `control-range-must-cover-stored-values`.

## Verifying it

Drive an impulse through a reference implementation of the same filter and compare it to your own
coefficients, computed exactly as your code computes them:

```bash
python3 -c "import struct;n=1<<15;open('imp.raw','wb').write(struct.pack('<f',1.0)+b'\x00'*4*(n-1))"
ffmpeg -v error -f f32le -ar 48000 -ac 1 -i imp.raw \
  -af "equalizer=f=1000:width_type=q:width=1.41:g=6" -f f32le -ar 48000 -ac 1 -y ref.raw
python3 - <<'PY'
import struct, cmath, math
FS, Q, F0, G = 48000.0, 1.41, 1000.0, 6.0
h = struct.unpack('<32768f', open('ref.raw','rb').read())
def measured(f):
    w = 2*math.pi*f/FS
    return 20*math.log10(abs(sum(h[n]*cmath.exp(-1j*w*n) for n in range(4096))))
def analytic(f):                       # transcribe YOUR coefficient code here, verbatim
    A = 10.0**(G/40.0); w0 = 2*math.pi*F0/FS
    al = math.sin(w0)/(2*Q); a0 = 1 + al/A
    b = [(1+al*A)/a0, (-2*math.cos(w0))/a0, (1-al*A)/a0]
    a = [(-2*math.cos(w0))/a0, (1-al/A)/a0]
    z = cmath.exp(-1j*2*math.pi*f/FS)
    return 20*math.log10(abs((b[0]+b[1]*z+b[2]*z*z)/(1+a[0]*z+a[1]*z*z)))
for f in (31,62,125,250,500,1000,2000,4000,8000,16000):
    print(f"{f:>6} {measured(f):>9.4f} {analytic(f):>9.4f} {measured(f)-analytic(f):>+9.4f}")
PY
```

Every delta should print `+0.0000` or `-0.0000` — the sign is float noise, the four zeros are the
result. Then check the definition is genuinely single: grep both
backends for a hardcoded `31` or `1.41` outside the two constants, and grep for a second copy of the
band list in the UI — a label list that drifts from the filter list is the same bug in a place
nobody thinks to look.
