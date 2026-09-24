---
name: variant-layout-math-stays-in-the-variant
description: When two looks of one screen each need a fit-exactly-one-screen measurement — measure the fixed blocks, split the remainder into equal gaps, floor it at a minimum — keep a copy per look instead of hoisting one; covers the effect keys the block needs, the invisible spacer that must mirror the ratio actually drawn, and which spacer may animate. Use when the gap above or below a hero element keeps last track's size, when content that should end at the fold overflows or leaves a band of dead space, or before extracting "the same" layout maths from two screens into one helper.
---

# Fit-one-screen maths belongs to each look

The block is small and looks shareable: measure the header, the hero frame and the info column, then
`gap = (screenHeight − header − hero − info − minimum) / 2`, floored at `minimum`, drawn above and
below the hero so it lands optically centred with the rest just reaching the fold.

```kotlin
// adapted
LaunchedEffect(headerDp, heroDp, infoDp, screenInfo, minimumDp) {
    if (headerDp > 0 && heroDp > 0 && infoDp > 0 && screenInfo.hDP > 0) {
        val result = (screenInfo.hDP - headerDp - heroDp - infoDp - minimumDp) / 2
        gapDp = if (result > minimumDp) result else minimumDp
    }
}
```

## Traps

**Do not hoist it. The two copies diverge, and one of them diverges silently.** In this tree the hero
frame of one look is always square, while the other's changes shape while a video plays. Written
once, the shared version has to satisfy the union of both constraints — so the simple look pays for
the complex one with an extra effect run and relayout on every track change, and neither look's
author can tell which constraint belongs to whom. Two twenty-line copies with a comment each are the
cheaper artefact; see `screen-shell-content-split` for what genuinely does belong in the shell.

**Key the effect on everything the body reads — including the measured hero height.** The copy whose
hero is a fixed square reads `heroDp` in the body and does not list it as a key. That is a latent
stale read, invisible only because a constant-height hero never changes after the first measurement.
Copied into the look whose hero *does* change height, it became a real bug: the gap kept the previous
track's numbers and the whole column drifted. Add the key in both, so the next copy starts correct.

**The measuring element is an invisible spacer, and its ratio must mirror what is actually drawn.**
The hero is painted by a pager stacked behind the column, so the column reserves the space with a
spacer that reports its own height back. If the drawn frame is 16:9 while a video plays and the
spacer stays square, every number below it is wrong by the difference:

```kotlin
// adapted
Spacer(
    Modifier
        .fillMaxWidth()
        .padding(horizontal = 20.dp)
        .onGloballyPositioned { heroDp = with(density) { it.size.height.toDp().value.toInt() } }
        .aspectRatio(if (isVideo && watchVideo) 16f / 9 else 1f),
)
```

The condition on that last line has to be the *same expression* the drawn frame uses. Two independent
copies of one condition is the actual risk here — put it on the state holder if it starts drifting.

**The gap spacers may animate; the measuring spacer may not.** `animateContentSize()` on a gap makes
the layout settle smoothly when a track changes shape. On the *measured* element it feeds a stream of
intermediate heights into the effect that computes the gap, which changes the gap, which relayouts —
a measure/animate loop with no fixed point. In both copies here the two gap spacers animate and the
measuring spacer does not.

**A spacer that reserves space must not take pointer input**, or it eats the gestures aimed at the
element it is standing in for. A bare `Spacer` is inert; a `Box` with a background or a click is not.

**The floor is a floor, not a guarantee.** On a short window the arithmetic goes negative and the
branch returns `minimum`, so the column overflows and the page scrolls — which is right. What must
never happen is a negative gap being used: it does not clamp, it overlaps.

**Measured heights held in saveable state come back before the next measurement.** After a rotation
or a process restore the first frame computes the gap from the *previous* configuration's numbers and
corrects on the following pass. That is usually invisible and occasionally a one-frame jump; if it
matters, guard the whole block on `screenInfo` matching what the numbers were measured under.

## Verifying it

1. The copies exist, and each one keys on the values it reads. Read the two blocks side by side —
   they should differ only where the two looks genuinely differ:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -A8 "LaunchedEffect($" . \
     | grep -B1 -A8 "HeightDp,\|heightDp," | head -60
   ```

2. Every measuring spacer, with the ratio it declares — each must match the frame its own look draws.
   Match the callback receiver-agnostically: its parameter is named by whoever wrote the block and is
   as often left implicit, so a pattern anchored on one spelling returns an empty listing against a
   tree — or against a snippet lifted from a note like this one — that happens to use the other.

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -A12 "onGloballyPositioned {" . \
     | grep "aspectRatio"
   ```

3. No measuring element animates its own size. This must print nothing:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -B6 "onGloballyPositioned" . \
     | grep "animateContentSize"
   ```

4. By hand, on the look whose hero changes shape: start an audio-only track, note where the info
   column sits, then skip to a track that plays as video and back. The column must return to the same
   place both times — a permanent offset after the round trip is the missing effect key.
