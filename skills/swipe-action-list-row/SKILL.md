---
name: swipe-action-list-row
description: One list row carrying three gestures at once — tap, long-press-to-select, and swipe-sideways-for-an-action — plus a mode flag that changes what the tap means. Covers the pointerInput key that decides whether the swipe detector sees the current mode or the one captured at composition, translating the row in the layout phase, latching the commit threshold, and leaving the opposite drag direction to the parent. Use when a row keeps swiping after multi-select has started, when selection only begins working after the row happens to recompose, or when a swipe fights the pager or list underneath.
---

# A row with a swipe action and a selection mode

The row is a `Box` with two children: the action, revealed underneath, and the row content, offset
sideways by an `Animatable`. A mode flag turns the row from "tap to open" into "tap to select".

```kotlin
// adapted
val offsetX = remember { Animatable(0f) }
val maxOffset = 360f

Box(modifier) {
    Crossfade(offsetX.value >= maxOffset / 2) { revealed ->
        if (revealed) ActionIcon(Modifier.align(Alignment.CenterStart))
    }
    Box(
        modifier = Modifier
            .offset { IntOffset(offsetX.value.roundToInt(), 0) }
            .combinedClickable(
                onClick = { if (selectionMode) onSelectToggle(id) else onOpen(id) },
                onLongClick = onLongClick?.let { { it(id) } },
            )
            // Keyed on selectionMode so the detector is torn down when selection starts —
            // keyed on Unit it keeps running with the flag captured at composition.
            .pointerInput(selectionMode) {
                if (isSwipeable && !selectionMode) {
                    detectHorizontalDragGestures(
                        onHorizontalDrag = { change, dragAmount ->
                            if (offsetX.value + dragAmount > 0) {
                                change.consume()
                                scope.launch {
                                    offsetX.snapTo((offsetX.value + dragAmount).coerceAtMost(maxOffset))
                                }
                            }
                        },
                        onDragEnd = {
                            if (offsetX.value == maxOffset) onAction(id)
                            scope.launch { offsetX.animateTo(0f) }
                        },
                    )
                }
            },
    ) { … }
}
```

## Traps

**`pointerInput` must be keyed on the mode flag, and the block must still check it.** The lambda is
a long-lived coroutine that `pointerInput` starts once per key value and keeps running across
recompositions. `selectionMode` here is a plain composable **parameter**, so keyed on `Unit` the
block captures whatever value it was handed when it first ran and never sees another — entering
selection mode leaves a live swipe detector behind, rows still slide under the finger, and the mode
looks like it "only starts working once the row recomposes for some other reason". Keying on the
flag restarts the coroutine; the `if` inside is what makes the restarted coroutine install no
detector at all. Both, or the fix is half-done. (Had the flag been a `mutableStateOf` delegate the
block owned, the capture would read the current value every time and `Unit` would have been fine —
the hazard is the plain captured value, not the flag.) This is the same shape as a guard added to
only one of two trigger paths — see `guard-on-every-trigger-path`.

**Translate the row in the layout phase, not with a `dp` modifier.** `Modifier.offset { … }` takes
a lambda that is read during layout, so the animatable can change 60 times a second without
recomposing the row and everything inside it. `Modifier.offset(x.dp)` reads the value at
composition and forces a recomposition per frame, on a row that contains an image loader and text.

**The commit test compares against the clamp ceiling, and only works because the clamp writes it
exactly.** `snapTo(value.coerceAtMost(maxOffset))` produces the literal ceiling, which is why
`offsetX.value == maxOffset` in `onDragEnd` is reliable. Put any easing, spring or velocity decay
between the finger and the animatable and that equality silently stops matching, and the action
never fires. If you change how the offset is written, change the test to `>= maxOffset` at the same
time.

**The reveal threshold and the commit threshold are different numbers on purpose.** The action icon
crossfades in at half travel while the action only fires at full travel. That is the affordance —
the user sees what the gesture will do before committing to it — but it also means *seeing the icon
is not a promise the action will run*. Do not "fix" a bug report about that by lowering the commit
point to the reveal point; you remove the ability to back out.

**Consume only in the direction you own.** `if (offsetX.value + dragAmount > 0)` guards both the
snap *and* the `change.consume()`, so a drag in the other direction is never consumed and the pager
or list underneath still receives it. Consuming unconditionally makes the row swallow every
horizontal gesture that starts on it, including the one that should page the screen.

**Return the row home from `onDragEnd` unconditionally.** The same `animateTo(0f)` runs whether or
not the action fired. Skipping it on the fired branch leaves the row parked open while the action
completes elsewhere, and the next recomposition snaps it back with no animation.

**Suppress the long press where another mode owns it.** Reorder mode and selection mode both want
the long press; pass `onLongClick = null` while the other mode is active rather than branching
inside the handler, so the row does not consume a gesture it will ignore.

**Do not let `combinedClickable`'s `onClick` fall through in selection mode.** The click handler
stays installed in both modes — it is the *meaning* that changes. Branch inside it on the flag, as
above. A `combinedClickable` that is only attached when the row is not in selection mode also loses
the ripple and the accessibility semantics the moment selection starts.

## Verifying it

1. **Find every gesture detector keyed on `Unit` and read what its block captures.**
   `grep -rn 'pointerInput(Unit)' --include='*.kt' .`
   → observed: a short list (13 hits in the audited tree), and reading each block is the check. What
   makes a hit the bug is a **captured plain value** — a composable parameter, or a local `val` — not
   the mere presence of a flag. A `by remember/rememberSaveable { mutableStateOf(…) }` delegate reads
   through the `MutableState` object and always returns the current value, so it is safe under
   `pointerInput(Unit)`: two hits in the audited tree read and write exactly such a flag (a fullscreen
   overlay toggle) and are correct. Others handle text-link taps, or drive a drag state holder through
   a stable reference. None captured a plain parameter, so all were correct.
2. **Confirm the swipeable row keys on the flag.**
   `grep -n 'pointerInput(' <rowFile>`
   → observed: `.pointerInput(selectionMode) {`.
3. **Confirm the translation is a layout-phase lambda.**
   `grep -n 'offset {\|offset(' <rowFile>`
   → observed: a single `.offset { IntOffset(offsetX.value.roundToInt(), 0) }` — the brace form,
   not the `dp` form.
4. **Confirm the commit threshold matches how the offset is written.**
   `grep -n 'maxOffset' <rowFile>`
   → observed: the declaration, the reveal test at `maxOffset / 2`, the `coerceAtMost(maxOffset)`
   write, and the `== maxOffset` commit — the last two must stay in step.
5. By hand: long-press one row to enter selection mode, then immediately try to swipe a *different*
   row without scrolling or otherwise disturbing the list. If it slides, the detector is keyed on
   `Unit`.
