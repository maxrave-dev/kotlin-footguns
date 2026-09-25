---
name: edit-a-shape-as-a-shape
description: When the value being edited is a curve, draw a draggable curve instead of N sliders and embed it in the settings list instead of pushing a screen — with a raw pointer loop rather than a drag-gesture helper, a draft that commits once per gesture, and smoothing that never overshoots a handle the user placed. Use when building a multi-point editor, or when a curve control ignores taps, snaps back on release, or wipes the saved value.
---

# Give the control the shape of the value

Ten sliders show ten unrelated numbers and make the user picture the result. A plot shows the
result. The control should have the shape of the value it edits — and it should sit *in* the
settings list, because the user adjusts it while listening and every navigation step between them
and the curve is a step they take twice.

The skeleton is a draft, a raw pointer loop, and one commit:

```kotlin
var draft by remember { mutableStateOf<List<Float>?>(null) }
val shown = draft ?: bands

// The gesture handler is installed once, so it must not close over the bands of the composition
// that installed it — that is the flat placeholder, before the stored curve has loaded.
val currentBands by rememberUpdatedState(bands)
val commit by rememberUpdatedState(onBandsChange)

// Hands the curve back to the stored value once the commit has been through storage.
LaunchedEffect(bands) { draft = null }

Modifier.pointerInput(count) {
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false)
        var working = currentBands.withPointAt(down.position, size, count)
        draft = working
        down.consume()
        while (true) {
            val change = awaitPointerEvent().changes.firstOrNull() ?: break
            if (!change.pressed) break
            working = working.withPointAt(change.position, size, count)
            draft = working
            change.consume()
        }
        commit(working)          // one write per gesture
    }
}
```

## Traps

**The drag-gesture helper eats the first part of every gesture, including all of a tap.** It waits
for the pointer to travel past a slop threshold before reporting anything, so a plain click on a
handle sets nothing at all and the first few pixels of a real drag are swallowed. On a plot the
press *is* the edit — the point under the finger should move on touch-down. That is why the raw
`awaitEachGesture` loop, not `detectDragGestures`.

**Commit once per gesture, never per event.** Every write here lands in storage and from there in
the audio engine, which typically drains and rebuilds its whole graph to take it. Applying per
pointer event does that at frame rate for the duration of a drag. The draft exists precisely so the
line can follow the finger without any of it reaching storage on the way.

**A handler installed once holds the values from that composition forever.** `pointerInput` does not
recompose with the enclosing function, so the lambda's captured `bands` is whatever existed when the
block was installed — typically the flat placeholder shown before the stored value has loaded. A
drag started from that stale copy commits it and **wipes the saved shape**. `rememberUpdatedState`
for every value the handler reads, including the callback.

**Drop the draft when the stored value arrives, not at release.** Clearing it in the release branch
snaps the curve back to its pre-drag shape for the length of the storage round trip, which reads as
the control rejecting the edit and then accepting it. `LaunchedEffect(storedValue) { draft = null }`
sequences it correctly with no timing assumption.

**Key `pointerInput` on the layout, never on the value.** `pointerInput(bands)` looks like the fix
for the stale-capture trap above and is much worse: the block is torn down and reinstalled the moment
the value changes, which is *every frame of the drag you are currently performing*. The gesture is
cancelled mid-stroke and the curve stops following the finger. Key it on the point count — the only
input that actually changes the gesture's geometry — and take the values through
`rememberUpdatedState`.

**Produce a new list per update; do not mutate.** The draft is read by a draw pass on a later frame,
so a list mutated in place changes underneath the frame that is drawing it. Building a fresh list
also gives you the place to normalise its length, so a value saved by a build with fewer points
still drags instead of throwing at the first index past the end.

**Naive smoothing flattens the curve at every handle.** Putting both control points of a segment on
the current point's own y makes the line leave and arrive horizontally, pushing the whole climb into
the middle of the gap — a row of bevelled steps rather than a curve. Aim each control point along
the direction set by a point's *neighbours* (Catmull-Rom converted to cubic Bézier) so the line
arrives at the slope the shape implies.

**Then clamp the control points to their own segment's span, or the curve disobeys the user.**
Catmull-Rom overshoots after a steep change and dips past a handle that was deliberately placed.
On an editor — as opposed to a chart — that is not a cosmetic wobble; it says the control did
something other than what it was told:

```kotlin
val lo = minOf(p1.y, p2.y); val hi = maxOf(p1.y, p2.y)
cubicTo(p1.x + (p2.x - p0.x) / 6f, (p1.y + (p2.y - p0.y) / 6f).coerceIn(lo, hi), …)
```

**Scales and labels go beside the canvas, never inside it.** Text drawn into the plot ends up under
the finger that is dragging. Once the axis lives in a gutter of its own, the labels below have to be
offset by the *same* gutter width — two places computing one number, so hoist it into a constant or
every label sits off its own gridline.

**Assemble the readouts in Kotlin.** "+12dB", "−15 dB", "03:00 – 04:00" are numbers plus units, and
a resource format string is the wrong place for padding, rounding and symbols — see
`string-resource-format-limits`. A string resource should join already-formatted pieces, or nothing
at all.

**Keep the block on one surface.** A curve, a trim slider and a reset button laid straight into a
settings list read as three unrelated rows; behind one container they read as one control, which is
what they are.

## Verifying it

Measure the control rather than looking at it — bounds and write counts, not screenshots:

```bash
# every commit path — expect exactly one, at the end of the gesture loop
grep -rn --include='*.kt' 'commit(\|onBandsChange(' . | grep -v 'val commit'
# and no stale capture: one rememberUpdatedState per value the handler reads (here, 2)
grep -rn --include='*.kt' -B12 -A20 'pointerInput(' . | grep -c 'rememberUpdatedState'
```

Behaviourally, in this order — the first is the one people skip because it "isn't a drag":

- **tap** a single point, no movement, and assert the value changed;
- **drag** across the whole plot and assert exactly **one** write reached storage;
- open the screen and drag **immediately**, before the stored value has loaded, and assert the saved
  curve is not replaced by the placeholder;
- set two adjacent points far apart and assert the rendered path never leaves the span between
  them — that is the overshoot check, and it needs the path, not a screenshot.
