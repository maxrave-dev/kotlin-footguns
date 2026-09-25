---
name: collapsing-parallax-toolbar
description: Build a collapsing header from five siblings in one box — four sharing a single scroll state, one driven by a boolean instead — with artwork moved by a graphics layer at half the scroll rate, a title interpolated along a two-segment curve into the pinned bar, and a derived flip point that swaps the floating back button for a real top bar. Use when a parallax header jitters or re-measures while scrolling, when the collapsing title drifts off its intended path, or when the pinned bar appears at the wrong scroll offset after a window resize.
---

# Collapsing parallax toolbar

Five siblings in one `Box`. Four read the same `ScrollState` and none of them owns it; the fifth
reads no scroll state at all, riding a boolean the toolbar reports back up:

```kotlin
val scroll: ScrollState = rememberScrollState(0)
Box(modifier) {
    Header(scroll, headerHeightPx, imageUrl, backgroundColor, /* … */)   // artwork, parallax + fade
    Body(scroll, headerHeight) { content(color) }                        // the only scrollable
    Toolbar(scroll, headerHeightPx, toolbarHeightPx, onShow = { … })     // pinned bar, appears late
    Title(scroll, title, headerHeight, toolbarHeight)                    // travels between the two
    AnimatedVisibility(showBackButton) { /* floating back button */ }
}
```

Only `Body` scrolls, and it reserves the header's space with a spacer rather than containing it:

```kotlin
Column(modifier.verticalScroll(scroll)) {
    Spacer(Modifier.height(headerHeight))
    Box(Modifier.background(Color.Black)) { content() }
}
```

The header sits outside the scrollable entirely, moved by a graphics layer, so a scroll costs a draw:

```kotlin
.graphicsLayer {
    translationY = -scroll.value.toFloat() / 2f     // half the content's rate — the parallax
    alpha = (-1f / headerHeightPx) * scroll.value + 1
}
```

The header's own height comes from the window's shape, not the platform: taller-than-wide gets a
square frame (the window width), otherwise half the viewport height, **both** floored at the same
250.dp. Only the square case requests a squared source image, because only there does the source fill
the frame exactly. See `responsive-gate-size-not-platform` for why that gate is a comparison not a
platform check, and for the `>=` vs `<` disagreement about square windows.

## Traps

**The flip point is remembered without a key, so it freezes at the first composition.**

```kotlin
val toolbarBottom by remember { mutableFloatStateOf(headerHeightPx - toolbarHeightPx) }
val showToolbar by remember { derivedStateOf { scroll.value >= toolbarBottom } }
```

`headerHeightPx` is derived from the window size and changes on resize, but a keyless `remember`
holds the old number through that recomposition, so afterwards the pinned bar appears early or late
by the difference — it only looks right on a platform that tears the composition down on rotation.
Key it: `remember(headerHeightPx, toolbarHeightPx)`. The `derivedStateOf` beside it is correctly
keyless: it reads both as state and recomposes on the flip frame, not on every scrolled pixel.

**Two back affordances, one at a time.** The floating back button over the artwork and the pinned
bar's navigation icon are different widgets, and the flip hands off between them — the toolbar
reports its own visibility upward (`onShow = { show -> showBackButton = !show }`) and the floating
one animates out as the bar animates in. Drive both from one derived boolean, or both sit on screen.

**The two-segment title path is a quadratic Bézier, and its middle point is shared.** Each axis is
three `lerp`s over the *same* fraction:

```kotlin
val collapseFraction = (scroll.value / (headerHeight.toPx() - toolbarHeight.toPx())).coerceIn(0f, 1f)
val titleYFirst  = lerp(headerHeight - titleHeightPx.toDp() - paddingMedium, headerHeight / 2, collapseFraction)
val titleYSecond = lerp(headerHeight / 2, toolbarHeight / 2 - titleHeightPx.toDp() / 2, collapseFraction)
val titleY       = lerp(titleYFirst, titleYSecond, collapseFraction)
```

`lerp(lerp(A,B,t), lerp(B,C,t), t)` is de Casteljau's construction: a quadratic Bézier from A to C
with B as the control point. Diverge the two middle terms and expand:
`lerp(lerp(A,B1,t), lerp(B2,C,t), t) = (1−t)²A + 2t(1−t)·(B1+B2)/2 + t²C` — *still* one quadratic
Bézier, degree two in `t`, constant second derivative, no kink anywhere for any `B1`, `B2`. What
divergence does instead is move the control point to their **average**, so the path stays smooth and
quietly stops passing near the waypoint you meant: halfway it sits at `(A + B1 + B2 + C)/4` rather
than `(A + 2B + C)/4`, and an adjustment written into one segment arrives at half strength. No corner
appears; the symptom is a title tracking a line nobody drew, felt only as "the animation is off".
Keep the middle term one expression read by both segments; the horizontal axis has its own shared one.

**A scaled title needs its start padding compensated.** `scaleX`/`scaleY` scale about the element's
centre, so a title shrinking toward the bar pulls its left edge inward by half the width it loses:

```kotlin
val titleExtraStartPadding = titleWidthPx.toDp() * (1 - scaleXY.value) / 2f
```

Without it the collapsed title drifts right as it shrinks. The scale is interpolated as a `Dp` purely
to reuse the `Dp` overload of `lerp`, then read back with `.value` — do not read a unit into it.

**The title measures itself, so the first frame computes from zero.** `titleHeightPx` and
`titleWidthPx` start at `0f` and are filled in by `onGloballyPositioned`, which runs *after* the
first layout, so the first frame places the title with a zero height and an uncompensated padding.
Fine for a value that only feeds a transform; not fine for anything that must be right immediately —
never compute the header height, the flip point or a scroll target from a self-measured size.

**Readability through the transition is a scrim and a draw order, not clipping.** The header carries
a vertical gradient, transparent mid-header and opaque at its bottom, so the title has contrast over
artwork; the body's opaque background then covers the header as it scrolls up. And the title is
declared *after* the toolbar in the box, so it draws on top and lands inside the collapsed bar rather
than behind it; reorder the siblings and it vanishes at the end of the collapse. `maxLines = 1` does
the rest — a wrapping title changes its own measured height mid-transition and drags everything.

**The alpha ramp is not clamped.** It reaches zero after exactly one header height of scroll and
keeps going negative past that — invisible only because the body's opaque background has covered the
header by then. Over a translucent body, coerce it.

**Use the graphics layer, not offset or padding.** `translationY` in a `graphicsLayer` block reads
`scroll.value` in the draw phase, so a scroll frame skips composition and layout entirely.
`Modifier.offset { }` is layout, and a scroll-driven `Modifier.padding` re-measures every frame.

## Verifying it

```bash
# Pinned to this codebase's file name: set TOOLBAR to <your-toolbar-file> first. A name that matches
# nothing makes all three print nothing, which reads exactly like a clean result.
TOOLBAR=CollapsingToolbar.kt

# 1. Geometry in a keyless remember — anything derived from a window or element size must be keyed.
find . -name "$TOOLBAR" -not -path "*/build/*" -exec grep -Hn "remember {" {} +

# 2. Everything the scroll value drives. Each hit should be inside a graphicsLayer or a
#    derivedStateOf — a scroll read in plain composition means a recomposition per frame.
find . -name "$TOOLBAR" -not -path "*/build/*" -exec grep -Hn "scroll.value\|collapseFraction\|graphicsLayer" {} +

# 3. Exactly one scrollable, and the spacer that reserves the header's space right after it.
find . -name "$TOOLBAR" -not -path "*/build/*" -exec grep -Hn "verticalScroll\|rememberScrollState\|Spacer(Modifier.height" {} +
```

Then scroll slowly with a long title and a short one, and watch *where the path goes*, not whether it
is smooth — it is smooth however wrong the control point is. Halfway through the collapse the title
must sit near the middle of the header rather than cutting inside it, must not drift sideways as it
shrinks, and must land centred in the bar rather than beside it. Stop exactly on the flip point: one
back affordance, not two. Finally resize the window — dragging on desktop, split-screen on mobile —
and scroll again: a bar now appearing at the wrong offset is trap one's keyless `remember`.
