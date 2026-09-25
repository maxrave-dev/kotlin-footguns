---
name: animated-gradient-border-ring
description: A rotating sweep-gradient ring around a card, chip or button, built from a clipped box, a full-size gradient and an opaque inset surface parked on its middle — where the modifier order is the whole mechanism and no blend mode is involved — plus why the SrcIn-inside-an-offscreen-layer version of this cannot draw a ring, and what that layer costs. Use when the gradient covers the whole surface instead of the border, when the ring is invisible, when it bleeds over whatever is behind the widget, or when a row of them makes scrolling expensive.
---

# A rotating gradient ring, masked to a border

The ring is not a stroke, and it is not a mask either. It is a gradient painted across the whole
widget with an opaque surface parked on top of its middle; the ring is the gap that surface does not
cover. Everything rests on modifier order — the gradient has to be drawn *outside* the padding that
insets the surface, or it never reaches the gap at all.

```kotlin
// reconstructed, not lifted: the shipped component orders these differently — see the recorded
// suspicion below. The transition, the brush and the radius are the source's.
val transition = rememberInfiniteTransition(label = "ring")
val degrees by transition.animateFloat(
    initialValue = 0f,
    targetValue = 360f,
    animationSpec = infiniteRepeatable(
        animation = tween(durationMillis = oneCycleMillis, easing = LinearEasing),
        repeatMode = RepeatMode.Restart,
    ),
    label = "ringAngle",
)
val grow by animateFloatAsState(if (isAnimated) 1f else 0f, tween(800))

Box(
    modifier = Modifier
        .clip(shape)                  // 1. confine the gradient to the outline
        .drawBehind {                 // 2. paint it across the WHOLE box, gap included
            scale(scale = grow) {
                rotate(degrees = degrees) {
                    drawCircle(brush = brush, radius = size.width)   // no blendMode at all
                }
            }
        }
        .padding(borderWidth),        // 3. only what follows this is inset
) {
    Surface(color = backgroundColor, shape = shape) { content() }    // 4. covers the middle
}
```

`drawBehind` sits before `padding` on purpose: a draw modifier measures whatever is inside it, so
one placed *after* the padding is handed the inner size and cannot paint the border gap however it
blends. `radius = size.width` is deliberate too — a sweep gradient at the default radius
(`minDimension / 2`) leaves the corners of a wide box unlit.

For a ring that runs a fixed number of turns and stops, keep the same draw and gate it — but gate
the *drawing*, not the transition, and key the effect on the flag:

```kotlin
// adapted
var running by rememberSaveable { mutableStateOf(false) }
LaunchedEffect(isAnimated) {                    // NOT LaunchedEffect(true)
    if (isAnimated) {
        running = true
        delay(cycles * oneCycleMillis.toLong())
        running = false
    }
}
```

## Traps

**Order is the mechanism, and no blend mode substitutes for it.** `drawBehind { … }` paints *before*
the node's own content; `drawWithContent { drawContent(); … }` paints after. With no blend, that
ordering is the entire effect. With a blend it decides whether the blend has a destination — and the
arithmetic is worth doing before reaching for one. On premultiplied colour `SrcIn` is
`Result = Src × Dst.a`: the destination contributes nothing but its alpha, used as a mask. Point
that at an opaque surface inset by `padding(borderWidth)` and you get the exact inverse of a ring —
alpha is 0 in the gap, so the gradient is erased precisely where the border belongs, and 1 across
the face, so it survives precisely where it should not. Draw the gradient *first* into a fresh layer
instead and the destination is empty everywhere, so `SrcIn` paints nothing whatsoever. The blend
that would carve a ring is `SrcOut` (`Result = Src × (1 − Dst.a)`), and only over a layer spanning
the *un-padded* box, so that "outside the destination" means the gap. The version above needs
neither, which is why it is the one to reach for.

**`CompositingStrategy.Offscreen` is what gives a blend a scope, and the scope is what it costs.**
A blend composites against whatever is already in the buffer it draws into; without the layer that
buffer is the parent's, so the result shifts with the background and can reach outside the widget's
own bounds. With the layer it is confined — at one offscreen buffer per instance, redrawn every
frame. That is a per-widget cost, fine on a hero element and not on every row of a list. Skip the
blend and you skip the buffer.

**The border width is the padding, not a stroke width.** Two consequences. The inner surface must be
opaque — hand it a transparent container colour and the gradient shows straight through the middle,
which is a gradient blob, not a ring. (The shipped component swaps in an opaque black behind the
content while animating, for exactly this reason.) And the outer `clip` and the inner surface must
use the *same* shape, or the gap width drifts around the corners.

**An infinite transition runs whenever it is composed.** `rememberInfiniteTransition()` created
unconditionally at the top of the composable keeps requesting frames for every instance on screen,
whether or not the ring is drawn — a row of chips is a row of frame loops. Scaling the ring to zero
hides it without stopping anything. If the effect is rare, put the animated variant behind a branch
so the transition is not composed at all.

**`LaunchedEffect(true)` never re-runs.** A fixed-cycle variant whose countdown is keyed on a
constant starts once, at first composition. An instance that mounts with the flag off and turns it
on later — the usual case, since the flag is normally "loading" or "selected" — never animates, and
nothing about the code looks wrong.

**`RepeatMode.Reverse` is not a rotation.** It runs the angle back down, so the ring visibly swings
instead of turning. Restart, from 0f to 360f, is a seamless loop for an angle — for anything else
Restart is the one that jumps.

**A sweep gradient has a seam.** The last colour meets the first at the start angle. Two colours
show a hard edge sweeping past; a list that begins and ends on the same colour hides it.

**Recorded suspicion: the shipped component is ordered the other way.** That
`InfiniteBorderAnimationView` puts its draw modifiers *after* `padding(borderWidth)` and blends
`SrcIn` from `drawBehind` — by the arithmetic above that has no destination alpha to keep and no
access to the gap, so it should paint nothing. It is nonetheless the code on screen, so treat this
as a reading of it rather than a bug report. `Chip(isAnimated = true, isSelected = true)` is the one
live call site; one screenshot of a selected animated chip settles both the shipped order and the
order taught here. Take it before changing anything.

Related: `shimmer-skeleton-loaders` drives a brush from the same kind of infinite transition without
a layer; `liquid-glass-backdrop` is the other effect in this family where the surface's own geometry,
not its position, decides what you see.

## Verifying it

```bash
# every offscreen layer, then whether a blend is near it (proximity only — the first list is truth)
grep -rn "CompositingStrategy.Offscreen" --include="*.kt" .
grep -rn -A12 "CompositingStrategy.Offscreen" --include="*.kt" . | grep "BlendMode"

# frame loops: each hit runs for as long as it is composed
grep -rn "rememberInfiniteTransition" --include="*.kt" .

# effects that can never re-run
grep -rn "LaunchedEffect(true)" --include="*.kt" .
```

A layer with no blend near it is either a deliberate alpha-compositing fix or a buffer being paid
for nothing — open each one. Then, by hand: put the widget over a dark and a light background in
turn (a ring that changes with the background is not confined to its layer), and toggle the flag
*after* the screen is up rather than starting with it on — that is the state the constant-keyed
effect gets wrong.
