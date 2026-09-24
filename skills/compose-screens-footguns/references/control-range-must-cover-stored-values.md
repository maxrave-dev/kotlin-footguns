---
name: control-range-must-cover-stored-values
description: Size a slider's range from the real distribution of values it will be handed — stored, imported, migrated — rather than from a neighbouring control's range, because a value outside the range parks the thumb at the end of the track while your readout shows a different number, and the first touch silently rewrites it. Use when adding a slider for a value that can arrive from anywhere but the slider itself.
---

# A control's range is a claim about its input

`valueRange` is not a styling choice. It is an assertion that every value the control will ever be
handed lies inside it — and the control is handed values by import, restore, migration and the
previous version of your own code, not only by the user's finger.

```kotlin
/**
 * Deeper than the ±12 dB the bands span, because an imported profile's own trim is computed from
 * the summed response rather than from its tallest band, and so goes past −12: the lowest across a
 * sample of sixty published profiles was −12.1 dB.
 */
private const val PREAMP_MIN_DB = -15f

Slider(value = draft ?: stored, valueRange = PREAMP_MIN_DB..0f, …)
```

## Traps

**Out of range does not clamp the value — it clamps the *thumb*, and your readout keeps telling the
truth.** The widget positions the thumb from a fraction it computes and then coerces:

```
calcFraction(a, b, pos) = if (b - a == 0f) 0f else (pos - a) / (b - a)   … .coerceIn(0f, 1f)
```

So `−12.1` on a `−12f..0f` range draws exactly like `−12.0`, while a readout rendering the stored
value prints `-12`… or `-12.1`, depending on your rounding. The user sees a control sitting at its
limit next to a number that is not the limit, and no exception is thrown anywhere.

**Pressing the thumb where you can see it rewrites the value, and that is data loss with no prompt.**
The setter does not coerce, and nothing is emitted merely because the control became interactive —
the emit is *gesture-driven*. A press sets the raw offset from the **pointer position**, and the
handler is invoked with the value that position scales to, not with a clamped copy of the stored
one. Since the thumb is drawn at the clamped position, a user pressing it exactly where the widget
put it hands you the range endpoint, and your handler stores that over the out-of-range value. That
is worse than a coercing setter, not better: the pinned thumb is what aims the gesture at the wrong
number, so the widget looks correct right up to the moment it destroys the value it was showing.
The user opened the screen to *look* at the setting and left having changed it.
Nothing logs this; it is indistinguishable from a deliberate edit.

**Sizing from the neighbouring control is the specific mistake.** The bands span ±12, so ±12 looks
like the obvious bound for the trim beside them. They are not the same quantity: one band's gain is
one filter's gain, while a trim that makes room for *all* of them is computed from the summed
response and legitimately goes deeper than any single band. Two controls in the same block, drawn
the same way, measuring different things.

**Measure the distribution before you pick the bound, and write the measurement into the constant.**
"The lowest across a sample of sixty published profiles was −12.1 dB" is worth ten times a round
number, because it tells the next maintainer what would have to change for the bound to be wrong —
and it is falsifiable. A bound with no recorded basis gets widened by guesswork on the next report.

**Asymmetric is fine, and often correct.** A trim whose purpose is to make headroom should not be
allowed to boost; that would only move the clipping somewhere else. Do not "balance" a range for
symmetry's sake — the range should follow what the value means, then be widened to cover what
arrives.

**If you genuinely must narrow the range, clamp at ingest and say so.** Let the *import* reject or
clamp, with a message, rather than letting the widget do it on first touch. A clamp the user was
told about is a decision; a clamp the widget performs is a silent edit.

**Round the readout the same way the control steps.** A readout rounding to whole units over a
continuous range shows the same number for two genuinely different states, so a user nudging the
control sees nothing happen and nudges again. Either give the control discrete steps or print
enough digits to distinguish them.

**The bound belongs to the *stored* range, not the control.** Anything else that reads the value —
a second backend, an exporter, a settings summary — has to accept the same span. See
`one-setting-two-backends`: a curve produced under one build's range and re-opened under a narrower
one is the same failure arriving from your own past release.

## Verifying it

Compute the extremes of the real input distribution and compare them to the declared range, rather
than reasoning about it:

```bash
# every declared range in the UI
grep -rn --include='*.kt' 'valueRange' .

# the extremes of what actually arrives — here, the trim line of a sample of profile files.
# LC_ALL=C is load-bearing: under a non-C LC_NUMERIC, `sort -g` orders by the integer part only
# and reports a wrong extreme with no error (-12.1 before -12.9), which is the one thing this
# command exists to get right.
grep -h -i '^Preamp:' sample-profiles/*.txt \
  | sed -E 's/^[Pp]reamp:[[:space:]]*(-?[0-9.]+).*/\1/' \
  | LC_ALL=C sort -g | sed -n '1p;$p'
```

Then the two states that only appear with a value from outside:

- seed the store with a value one step **outside** the range, open the screen, and assert the
  rendered number equals the stored one — this is the check that catches the pinned thumb;
- do the same, then press the **thumb** and assert the stored value did not become exactly the range
  endpoint. Assert *that*, not "unchanged": a press anywhere emits the position it landed on, on a
  correct range too, so an unchanged-assertion fails on code that is right. Seeded at −12.1 against
  `−12f..0f` the press yields exactly −12.0; against `−15f..0f` the thumb sits at the true position
  and the emitted value stays within a pixel of −12.1. A test that only *drags* passes on a broken
  range either way, because dragging is supposed to change the value.
