---
name: lazy-scroll-helper-kit
description: Four small lazy-list utilities worth carrying between apps — scroll-direction as derived state, centre-an-item scrolling that waits a frame before measuring, an item's visible percentage, and a lookup into the visible window — with the trap each one hides. Use when a hide-on-scroll bar flickers or sticks, when scrolling to an item lands it at the edge or does nothing, or when viewport arithmetic returns values for the wrong item.
---

# Lazy list helpers, and what each one gets wrong

Four utilities, each a handful of lines, each with a failure mode that only shows in a real list.
Keep them together: they all read `layoutInfo` — the **last completed layout**, never the next one.

## Scroll direction, as derived state

```kotlin
// adapted: logging removed, list and grid variants collapsed into one
@Composable
fun LazyListState.isScrollingUp(): State<Boolean> {
    var previousIndex by remember(this) { mutableIntStateOf(firstVisibleItemIndex) }
    var previousOffset by remember(this) { mutableIntStateOf(firstVisibleItemScrollOffset) }

    LaunchedEffect(Unit) {
        snapshotFlow { layoutInfo.totalItemsCount }.collect {
            previousIndex = firstVisibleItemIndex
            previousOffset = firstVisibleItemScrollOffset
        }
    }

    return remember(this) {
        derivedStateOf {
            if (firstVisibleItemIndex > 0) {
                if (previousIndex != firstVisibleItemIndex) {
                    previousIndex > firstVisibleItemIndex
                } else {
                    previousOffset >= firstVisibleItemScrollOffset
                }.also {
                    previousIndex = firstVisibleItemIndex
                    previousOffset = firstVisibleItemScrollOffset
                }
            } else {
                true
            }
        }
    }
}
```

Returning `State<Boolean>` keeps the read in the scope that uses it (`val up by state.isScrollingUp()`).
The `> 0` branch makes the top of the list always answer "up", so a fling cannot leave a bar hidden there.

## Centre an item — after a layout pass

```kotlin
// adapted: receiver kept, comments condensed, the visibility check inlined
suspend fun LazyListState.animateScrollAndCentralizeItem(index: Int) {
    if (index < 0) return
    if (layoutInfo.visibleItemsInfo.none { it.index == index }) scrollToItem(index)  // measure it
    withFrameNanos { }                           // let that layout happen before reading it
    val item = layoutInfo.visibleItemsInfo.firstOrNull { it.index == index } ?: return
    val viewportCentre = (layoutInfo.viewportStartOffset + layoutInfo.viewportEndOffset) / 2
    val itemCentre = item.offset + item.size / 2
    animateScrollBy(
        value = (itemCentre - viewportCentre).toFloat(),
        animationSpec = tween(durationMillis = 300, easing = LinearOutSlowInEasing),
    )
}
```

The `?: return` is the proof, not a defensive habit: without the frame wait, an item that was off
screen a moment ago is still absent from `visibleItemsInfo` and there is nothing to measure.

## Viewport arithmetic

```kotlin
// adapted
fun LazyListState.visibilityPercent(info: LazyListItemInfo): Float {
    val cutTop = max(0, layoutInfo.viewportStartOffset - info.offset)
    val cutBottom = max(0, info.offset + info.size - layoutInfo.viewportEndOffset)
    return max(0f, 100f - (cutTop + cutBottom) * 100f / info.size)
}

fun LazyListState.getVisibleItemInfoFor(absoluteIndex: Int): LazyListItemInfo? =
    layoutInfo.visibleItemsInfo.getOrNull(absoluteIndex - layoutInfo.visibleItemsInfo.first().index)
```

`viewportStartOffset` and `viewportEndOffset` already account for content padding.

## Traps

**The direction helper writes state from inside `derivedStateOf`.** Updating the previous values is
a side effect of *reading* the derived value, which makes the block impure in the one place Compose
assumes purity. It works, and everybody copies it, but the answer now depends on when it was last
read, and anything else you add there runs on a schedule you do not control.

**A list that grows reports a direction nobody scrolled.** Appending a page — or worse, inserting
above the viewport — moves `firstVisibleItemIndex` with no gesture, and the comparison against the
remembered value reads as a scroll. Hence the `totalItemsCount` collector: reset the baseline on a
size change, not only on a gesture.

**`layoutInfo` is one frame behind your own scroll.** Any "scroll, then measure" inside one suspend
function reads the layout from *before* the scroll; `withFrameNanos { }` — an empty body, purely a
yield — is the cheapest way to let it run first. It is also why `animateScrollToItem` cannot centre
anything, though not for the reason it looks like: it is deterministic, landing the item's leading
edge at the viewport start plus `scrollOffset` pixels, and it never consults the item's size. The
offset is biased the other way too — positive pushes the item further *past* the start — so centring
needs a **negative** `scrollOffset` of `(viewportSize - itemSize) / 2`, which you cannot compute
until the item has been laid out. Hence the shape above: scroll close, wait a frame, measure, then
`animateScrollBy` the remainder.

**`visibleItemsInfo.first()` throws on an empty list.** Before the first layout, and for a list with
no items, the lookup crashes rather than returning the null its `getOrNull` looks like it protects.

**Index arithmetic assumes the visible window is one contiguous run.** Subtracting the first entry's
index only works while `visibleItemsInfo` is "items N through N+k, in order" — a pinned or sticky
entry is the usual counter-example. `visibleItemsInfo.firstOrNull { it.index == target }` scans a
handful of entries and cannot be wrong; use the arithmetic only where the scan measurably costs you.

**A visibility percentage is a percentage of the item.** An item taller than the viewport never
reaches 100, and two items with the same visible height report different numbers.

**Re-key the helpers on the state object.** `remember(this)`, not `remember { }`: a screen that
swaps lists between tabs otherwise carries the previous list's baseline into the new one.

Related: `lazy-list-drag-reorder` reads the visible window on every drag frame — where the
contiguity assumption is load-bearing.

## Verifying it

```bash
# every place that waits for a layout pass — and, by absence, every place that forgot to
grep -rn "withFrameNanos" --include="*.kt" .

# every read of the visible window; each one is a read of the previous layout
grep -rn "visibleItemsInfo" --include="*.kt" .

# the helpers themselves, so duplicates in screen files are visible
grep -rn "fun LazyListState\.\|fun LazyGridState\." --include="*.kt" .
```

Then, by hand: fling a long list both ways and watch the bar (a stale baseline flickers at the turn);
scroll to an item far off screen and confirm it lands centred; append a page while a hide-on-scroll
bar is hidden — it must not move on its own.
