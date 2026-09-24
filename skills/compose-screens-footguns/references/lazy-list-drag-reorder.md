---
name: lazy-list-drag-reorder
description: A complete drag-to-reorder state holder for a lazily composed Compose list — pointer offset accumulation, target-index math over the visible window, how the lift animation and the built-in item placement animation must not overlap, edge auto-scroll as a delta the caller drives, and the commit-on-drop contract with the data layer. Use when building reorder, or when a dragged row snaps back to its old slot, jitters as the list re-lays-out under it, commits a move that the user cancelled, or scrolls the list instead of moving the row.
---

# Drag-to-reorder in a lazy list

Three pieces, and the split matters: a **state holder** owning the drag, a **per-item wrapper** that
decides how each row animates, and **one gesture detector on the list** — not on each row. A lazy
list discards rows, so a per-row detector dies mid-drag; the list-level one hit-tests instead:

```kotlin
// adapted — on drag start, find which laid-out row the finger came down on
state.layoutInfo.visibleItemsInfo
    .firstOrNull { offset.y.toInt() in it.offset..(it.offset + it.size) }
    ?.also { currentIndex = it.index; initialElement = it; initialOffset = it.offset }
```

The lifted row's translation is recomputed every frame against its **current** laid-out offset,
never accumulated blindly:

```kotlin
internal val draggingItemOffset: Float
    get() = draggingItemLayoutInfo?.let { item ->
        draggingItemInitialOffset + draggedDistance - item.offset
    } ?: 0f                                                                    // adapted
```

That `- item.offset` is the whole trick. Every time a swap fires the list re-lays-out and the dragged
row's slot moves; subtracting the fresh offset cancels that motion, so the row stays under the finger
instead of jumping by one row height per swap.

Target selection runs over the visible window, and is direction-dependent:

```kotlin
// adapted — pick the first neighbour whose far edge the dragged band has passed
state.layoutInfo.visibleItemsInfo
    .filterNot { it.offsetEnd < startOffset || it.offset > endOffset || it.index == hovered.index }
    .firstOrNull { item ->
        if (startOffset - hovered.offset > 0) endOffset > item.offsetEnd   // moving down
        else                                  startOffset < item.offset     // moving up
    }
    ?.also { currentSwapFromTo = hovered.index to it.index }
```

## Traps

**The built-in placement animation is for the rows you are *not* dragging.** Give the dragged row
`zIndex(1f)` plus `graphicsLayer { translationY = … }` and every other row `Modifier.animateItem()`.
Put both on one row and they fight — the layer follows the finger while the placement animation walks
the row to its new slot — which reads as lag and overshoot. Disable `animateItem`'s fade specs too.

**The just-dropped row needs its own settle animation, and it belongs to the destination index.**
The moment the drag index clears, the placement animation would snap the row from wherever the finger
left it. So the holder keeps a *second* pair — a previous index and an `Animatable` — snaps it to the
leftover offset, animates it to zero, then clears the index. Note which index: the holder assigns
`currentIndexOfDraggedItem = to` first, so the settle plays where the row **landed**, not where it
came from — the origin index would animate an innocent neighbour.

**Record the swap continuously, commit it only on a real drop.** The cancel path and the end path are
different events, and only the end path may reach the data layer:

```kotlin
// adapted
fun onDragInterrupted(end: Boolean = false) {
    currentSwapFromTo?.let { (from, to) ->
        if (from != to && from >= 0 && to >= 0 && end) onSwap(from, to)
        currentIndexOfDraggedItem = to
    }
    …
}
```

Wire `onDragEnd → onDragInterrupted(true)` and `onDragCancel → onDragInterrupted()`. Passing `true`
from both writes a reorder every time a parent steals the gesture or a phone call interrupts it.

**Consume the drag change, or the list scrolls under the finger.** The detector and the list's own
scroll both want the vertical drag. `change.consume()` in `onDrag` is what keeps them apart.

**Auto-scroll is a delta the holder computes and the caller must act on.** The holder reports how far
past the viewport edge the dragged band has reached; the caller launches the scroll. Two rules on that
job: single-flight — check `isActive` first, or every drag frame launches a competing animation — and
cancelled on **both** exit paths, or the list glides on. See `named-job-lifecycle-discipline`.

```kotlin
// adapted
if (overscrollJob?.isActive != true) {
    dragDropState.checkForOverScroll().takeIf { it != 0f }
        ?.let { overscrollJob = scope.launch { state.animateScrollBy(it * 1.3f, tween(…)) } }
        ?: run { overscrollJob?.cancel() }
}
```

**The ±50 inside that delta is a lead-in margin, not a dead zone — read the sign before copying it.**

```kotlin
// adapted — `state.layoutInfo.` elided from the two viewport reads
draggedDistance > 0 -> (endOffset - viewportEndOffset + 50f).takeIf { diff -> diff > 0 }
draggedDistance < 0 -> (startOffset - viewportStartOffset - 50f).takeIf { diff -> diff < 0 }
```

Adding 50 *before* the `> 0` test makes it true while the band's far edge is still 50 px **inside**
the viewport, and inflates the delta by that same 50 — the scroll fires early and its first step is
oversized. Call it a dead zone and it inverts: you would suppress firing exactly where the dragged
row lives, and nothing would move until the row was clipped. For a real one, subtract instead.

**Translating an absolute list index into the visible window is arithmetic, and it has an edge.** The
convenient form subtracts the first visible index —
`visibleItemsInfo.getOrNull(absoluteIndex - visibleItemsInfo.first().index)` — but `first()` throws
on an empty window and the subtraction assumes contiguity. The safe alternative already sits in the
same holder: `visibleItemsInfo.firstOrNull { it.index == target }`, a linear scan that cannot throw.

**Header items shift the index space; convert at the boundary.** The holder reports lazy-list indices,
which include every `item { }` above the rows; the data layer wants positions in the backing list.
Subtract the header count once, where you call the repository:
`viewModel.moveItem(from - headerCount, to - headerCount)`.

**A touch drag must start after a long press; a pointer drag must not.** On touch, an immediate drag
detector on a scrollable list steals every scroll gesture, so use the after-long-press detector there;
with a mouse there is no ambiguity and a long press before every drag feels broken. Hoist the four
callbacks into `val`s and branch on platform between `detectDragGestures` and its long-press form.

**Gate the detector when another mode owns the long press.** Reorder and multi-select both want it.
Whichever flag decides between them must be the `pointerInput` key, not just an `if` inside the
block — see `swipe-action-list-row` for why keying on `Unit` strands the captured flag.

## Verifying it

1. **Every auto-scroll caller cancels its job on both exit paths.**
   `grep -rn 'checkForOverScroll\|overscrollJob' --include='*.kt' . | grep -v 'fun checkForOverScroll'`
   → observed: each call site declares the job, guards on `isActive`, and cancels it twice — once in
   `onDragEnd`, once in `onDragCancel`.
2. **The drop commits only on a real drag end.**
   `grep -rn 'onDragInterrupted' --include='*.kt' .`
   → observed: `onDragInterrupted(true)` appears only under `onDragEnd`; the cancel path calls the
   no-argument form. A second `(true)` anywhere is a reorder written on a cancelled gesture.
3. Drag a row to the very bottom of the viewport and hold it still. Scrolling should begin slightly
   before the row reaches the edge (that is the lead-in) and stop the instant you lift.
4. Drag a row past several neighbours without lifting. The row must stay pinned under the pointer
   throughout; a jump of exactly one row height per swap means the laid-out offset is not subtracted.
