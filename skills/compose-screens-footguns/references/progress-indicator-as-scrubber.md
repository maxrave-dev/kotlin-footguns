---
name: progress-indicator-as-scrubber
description: Build a seek control from a progress indicator plus a transparent pointer layer instead of from a slider — a hit box taller than the visual, drags consumed so an ancestor pager cannot steal a scrub, the drag's own fraction shown while interacting, a thumb drawn by you, and the separate decision of drawing an element closer without moving its layout slot. Use when the visual you need has no slider equivalent, when a scrub gets hijacked by a swipe or a sheet, when the bar jumps back mid-drag, or when a thin control is impossible to hit.
---

# A scrubber made from a progress indicator

Two layers in one box: the indicator draws, and a transparent gesture layer over it maps positions to
a fraction. You own the hit area, the arbitration and the thumb — which is the whole reason to do it
this way.

Reach for `custom-thin-media-slider` instead when the platform slider can render what you want and
you only need custom track and thumb slots; it keeps the accessibility semantics and the keyboard
handling for free. Come here when the visual has no slider counterpart, or when you need a hit area
and a consumption policy the slider does not expose — and then accept that semantics are now yours to
add.

## Traps

**The hit area is a separate size from the visual, and it is the one thing a slider will not give
you.** A few-pixels-tall line is unhittable. Put the indicator inside a box with a comfortable height
(40dp here), centre it, and hang the gestures on the box:

```kotlin
// adapted
Box(contentAlignment = Alignment.CenterStart, modifier = modifier.fillMaxWidth().height(40.dp)
        .onSizeChanged { widthPx = it.width }
        .pointerInput(Unit) { detectTapGestures { … } }
        .pointerInput(Unit) { detectHorizontalDragGestures(…) }) { Indicator(…); Thumb(…) }
```

**Consume the drag, every event, or an ancestor steals the scrub in progress.** A horizontal pager or
a draggable sheet above this control will claim the gesture the moment its own threshold is crossed,
and the scrub stops halfway with the page sliding away. `change.consume()` inside `onHorizontalDrag`
is what prevents it.

**While interacting, the drag's fraction wins over the incoming position.** The player keeps
publishing positions during the scrub; if the bar renders those, it visibly fights the finger. One
line settles it:

```kotlin
// as written
val displayedFraction = (if (isInteracting) dragFraction else progressFraction).coerceIn(0f, 1f)
```

The same gate is why `isInteracting` must be cleared in `onDragCancel` as well as `onDragEnd` — a
cancelled gesture that leaves the flag set freezes the bar on the last drag value forever.

**Tap and drag are two `pointerInput` blocks, not one.** A tap is not a zero-length drag, and the two
detectors in a single block have to arbitrate by hand. Separate blocks let the tap commit
immediately — set the fraction, emit, and emit the finished callback in the same breath — while the
drag path holds `isInteracting` for its duration.

**Guard the width.** `onSizeChanged` has not fired on the first frames, so every fraction computed
from it divides by zero: `if (widthPx <= 0) 0f else (x / widthPx).coerceIn(0f, 1f)`.

**Subtract the thumb's own width when placing it**, or the thumb overhangs the right edge at the end
of the track: `x = ((widthPx - thumbWidthPx) * displayedFraction)`. Compute it inside the
`offset { }` lambda so a morphing thumb re-places itself without recomposing the caller.

**Decoration must vanish at zero.** A wave, glow or ripple drawn on an empty track reads as progress
that is not there — gate it on the drawn fraction (`if (p > 0f) amplitude else 0f`), and see
`dont-pre-animate-a-self-animating-property` for why that amplitude must be a raw target rather than
a tween.

**Drawing something closer is not the same decision as moving it.** The time row under the bar sat
too far from the wave and too close to the transport row. `Modifier.offset(y = (-8).dp)` shifts what
is *painted*: the row keeps its layout slot, so the 8dp it gives up above reappears below, and — the
part that matters — the scrubber's 40dp touch target is untouched. Reaching for padding or a smaller
height instead trades a visual nudge for a smaller hit area, which is the bug this control exists to
avoid. The rule generalises: if the fix is about appearance only, use a draw-time modifier and leave
measurement alone.

**Convert scales once, at the boundary.** Internally everything is a 0..1 fraction; the callback
emits whatever the rest of the app already speaks (here a 0..100 percent). Doing that arithmetic in
more than one place is how a bar ends up permanently full or permanently empty.

**You have opted out of the slider's semantics.** Nothing here is focusable, announces a value, or
responds to a keyboard. If the surface needs any of that, add `Modifier.semantics` with a progress
value and a `setProgress` action explicitly — the cost is real, and it is the argument for
`custom-thin-media-slider` where a slider would have done.

## Verifying it

1. Every horizontal drag detector, paired with its consume call — a detector with no `change.consume()`
   under it is a scrub waiting to be stolen:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -A18 "detectHorizontalDragGestures(" . \
     | grep -E "detectHorizontalDragGestures\(|change.consume\(\)"
   ```

2. Both interaction-end paths clear the flag. `onDragEnd` and `onDragCancel` must both appear:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "onDragEnd = \|onDragCancel = " .
   ```

3. Draw-time nudges, each of which should be a deliberate appearance-only decision:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -A2 "\.offset(y = " .
   ```

4. By hand, in this order: tap near the right edge (thumb lands under the finger, not past the end);
   drag slowly and stop mid-track while audio keeps playing (the bar must not jump); start a drag on
   the bar and continue horizontally well past it (the page behind must not move); start a drag and
   let go outside the window (the bar must resume following the player).
