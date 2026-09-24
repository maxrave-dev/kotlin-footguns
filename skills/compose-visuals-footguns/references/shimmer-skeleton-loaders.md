---
name: shimmer-skeleton-loaders
description: A self-measuring shimmer modifier plus skeleton composables that stand in for a list while it loads — how the modifier learns its own size, why the base colour under the sweep is load-bearing, why the modifier order between clip and background changes what gets rounded, and why the skeleton's lazy lists must have scrolling switched off. Use when building loading placeholders, or when a shimmer renders as a flat block, has square corners under a rounded design, or pauses visibly between passes.
---

# Shimmer placeholders

The shimmer is one modifier. It measures itself, so a caller never passes a size — a placeholder is
just a `Box` with a width, a height, a shape and this on the end:

```kotlin
// adapted
fun Modifier.shimmer(): Modifier = composed {
    val colors = LocalAppColors.current
    var size by remember { mutableStateOf(IntSize.Zero) }
    val transition = rememberInfiniteTransition(label = "Shimmer")
    val startOffsetX by transition.animateFloat(
        initialValue = -2 * size.width.toFloat(),
        targetValue  =  2 * size.width.toFloat(),
        animationSpec = infiniteRepeatable(animation = tween(1000)),
        label = "Shimmer",
    )
    background(
        brush = Brush.linearGradient(
            colors = listOf(colors.shimmerBackground, colors.shimmerLine, colors.shimmerBackground),
            start = Offset(startOffsetX, 0f),
            end   = Offset(startOffsetX + size.width.toFloat(), size.height.toFloat()),
        ),
    ).onGloballyPositioned { size = it.size }
}
```

Skeletons built on it are ordinary layout — no framework, no library. Each is a hand-laid stack of
boxes at the sizes the real row will occupy, wrapped in the same list shape the real content uses.

## Traps

**Put `clip` before `background`, not after.** `clip` is a graphics layer that clips what is drawn
*after* it; a `background` to its left has already been painted, square. So
`.background(base).clip(shape).shimmer()` gives you a square base colour under a rounded sweep —
and looks fine on the day you write it, because the sweep is the visible half. The other order,
`.clip(shape).background(base).shimmer()`, rounds both. It is easy to end up with both orders in
one file; the verify grep below is exactly for that.

**Keep a solid base colour under the sweep — the first frame has no size.** `size` starts at
`IntSize.Zero`, so on the composition before the first layout pass `start` and `end` are the same
point and the gradient is degenerate: what it resolves to is an engine detail, not something to
reason about or rely on. The solid `.background(colors.shimmerBackground)` every call site paints
first is what *guarantees* a painted first frame, whatever the degenerate gradient does over it.

**Each call site animates independently.** `composed { }` materialises per use, so every placeholder
box holds its own `rememberInfiniteTransition` and measures its own width. Twenty boxes are twenty
unsynchronised animations — the sweeps will not line up across a row, and a wide box and a narrow
one beside it travel at different speeds because the travel range is a multiple of each box's own
width. If a screen needs one coherent wave across several boxes, hoist a single transition and pass
the phase down instead.

**The sweep is off the box for roughly half of each cycle.** Travel runs from `-2 × width` to
`+2 × width` while the band itself is one width across, so the band overlaps the box for about half
the cycle; a linear gradient clamps outside its stops, and both outer stops are the base colour, so
the rest of the cycle is a flat pause. That pause is the design here, not a bug — but if you want a
continuous ripple, narrow the travel range rather than speeding up the tween, which only makes the
same pause arrive sooner.

**The sweep is diagonal, and its angle follows the box's aspect ratio.** The gradient ends at
`(startOffsetX + width, height)`, so it runs corner-to-corner: near-horizontal across a short wide
title bar, steep down a tall square thumbnail. Inside one skeleton those angles differ visibly. If
the design calls for one angle everywhere, fix the `end` offset's `y` to a constant instead of the
measured height.

**Switch scrolling off on every lazy list inside a skeleton.** A skeleton holds an arbitrary,
invented number of fake rows standing in for a count nobody knows yet; there is nothing further down
to reach, and any scroll offset the user establishes is discarded the moment the real list — a
different list, with different keys — replaces it. Nested lazy lists also compete for the drag with
whatever scrolls outside them. `LazyColumn(userScrollEnabled = false)` on all of them.

**Derive placeholder sizes from the real row, not by eye.** The point of a skeleton is that nothing
moves when the data lands. Read the real row's thumbnail size, text line heights and paddings and
reuse those numbers; a placeholder that is 4 dp short produces a visible settle on every load, which
reads as jank rather than as a wrong constant.

**Shimmer colours do not belong in the material colour scheme.** The base and the highlight line are
two tokens with no scheme slot to sit in. Carry them in your own immutable colour holder exposed
through a composition local, with a light and a dark instance, so the placeholder tracks the theme
without a `if (isDark)` at every call site.

## Verifying it

Run these from the repository root against your skeleton file and the file holding the modifier.

1. **Find mismatched clip/background order.** List both and compare line numbers per box:
   `grep -n 'clip(\|background(' <skeletonFile>`
   → observed: **two** placeholders had `background(` before `clip(` — at 33/35 and again at 136/138
   — so their base colours are square, while every other pair in the file (56/58, 67/69, 78/80, …)
   puts `clip(` first. One file, both orders, and the second offender is far enough down that reading
   only the first few hits would have missed it: read the whole listing.
2. **Every lazy list in the skeleton has scrolling disabled.** Compare the two counts:
   ```bash
   grep -c 'LazyColumn(\|LazyRow(' <skeletonFile>
   grep -c 'userScrollEnabled = false' <skeletonFile>
   ```
   → observed: `3` and `3`. Any gap is a skeleton the user can scroll.
3. **The modifier measures itself rather than taking a size parameter.**
   `grep -n 'fun Modifier.shimmer\|composed {\|onGloballyPositioned\|size.width' <modifierFile>`
   → observed: the `composed {` factory, the `onGloballyPositioned` write, and the reads of
   `size.width` in both the animation bounds and the gradient end point. A shared extensions file
   will surface unrelated hits from its other modifiers as well; match on the line numbers between
   `fun Modifier.shimmer` and the next declaration.
4. Screenshot the skeleton and the loaded screen at the same scroll position and flip between them.
   Anything that shifts is a placeholder measured by eye.
