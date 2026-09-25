---
name: smooth-scrim-gradient
description: Build a scrim that melts artwork into the page background without a visible seam — smoothstep easing so the ramp is flat at both ends, colour stops interpolated in Kotlin rather than left to the renderer, and a transparent stop that carries your own RGB instead of Color.Transparent. Use when a gradient overlay shows a hard line where it starts or ends, when the middle of a fade turns muddy grey or darker than either end, or when a fade that looks right on one platform bands into stripes on another.
---

# Smooth scrim gradient

A scrim is the block of gradient that sits between artwork and the page below it, so the image
appears to dissolve into the background. Written the obvious way —
`Brush.verticalGradient(listOf(Color.Transparent, background))` — it produces two artefacts at once:
a visible line where the fade begins, and a dirty band through the middle. Both are fixable, and
neither is fixed by adding more alpha.

```kotlin
// adapted (the colour lerp is imported unqualified here)
fun smoothScrimBrush(
    from: Color,
    to: Color,
    startFraction: Float = 0f,
    endFraction: Float = 1f,
    startY: Float = 0f,
    endY: Float = Float.POSITIVE_INFINITY,
    steps: Int = 24,
): Brush =
    Brush.verticalGradient(
        colorStops =
            Array(steps + 1) { i ->
                val t = i / steps.toFloat()
                val position = startFraction + (endFraction - startFraction) * t
                position to lerp(from, to, t * t * (3f - 2f * t))
            },
        startY = startY,
        endY = endY,
    )

// the common case: ramp one colour from invisible to opaque
fun artworkScrimBrush(color: Color, steps: Int = 24): Brush =
    smoothScrimBrush(from = color.copy(alpha = 0f), to = color, steps = steps)
```

## Traps

**A linear ramp has a corner, and the corner is the edge you keep seeing.** The eye is far more
sensitive to a change in the *rate* of brightness than to brightness itself, so the discontinuity
where a straight ramp leaves 0 (and where it arrives at 1) reads as a drawn line. Smoothstep,
`t² (3 − 2t)`, has zero slope at both `t = 0` and `t = 1`, so there is no corner at either end. Ease
**both** ends: easing only the start moves the seam to the bottom of the scrim instead of removing it.

**`Color.Transparent` is black at alpha 0, so a coloured fade drags through black.** Take a scrim
that should fade a blue-grey page colour to nothing. Interpolating that colour against
`Color.Transparent` walks the RGB channels toward `(0, 0, 0)` at the same time as the alpha, so at
the halfway stop you get half-brightness colour at half alpha — which composites darker and less
saturated than the correct half-alpha stop, and reads as a muddy band across the middle of the fade.
Pass `yourColor.copy(alpha = 0f)` as the transparent end and the RGB never moves. (The originating
code's comment records the underlying reason as the renderer interpolating gradient stops
un-premultiplied; you do not need that to be true for the rule to hold — matching the RGB at both
ends makes the ramp correct under either interpolation.)

**Interpolate the colours yourself and hand over many stops.** Two stops delegate the whole curve to
the renderer: you get its interpolation, in its colour space, with its premultiplication choice, and
those differ between backends. Emitting pre-interpolated stops fixes the stop values themselves and
leaves the renderer only the short segments between them — and it is the only way to put a non-linear
curve into a brush that has no easing parameter.

**Two stops cannot express a curve.** Even with smoothstep in hand, a gradient with a stop at each
end is a straight line again; the curve only exists in the stops you emit. Enough stops turn the
S-curve into a piecewise-linear approximation whose kinks fall below the visible threshold.

**Choose the step count by looking, not by copying a number.** Too few stops and the joins between
segments show as faint bands; too many is wasted work in the shader. Render the scrim over the
darkest background you ship (dark backgrounds are where 8-bit quantisation bites, because the
colour delta per output level is smallest there), halve the count until banding appears, then go
back one. The `steps = 24` in the sample above is the value that survived that test where this was
mined — a starting point, not a constant: yours depends on your ramp length and colour delta.

**Confine the ramp with fractions instead of shrinking the box.** A short scrim is a *steep* scrim,
and steep is exactly what makes a fade read as an edge — so when a fade suddenly looks like a line,
check whether someone capped its height. `startFraction`/`endFraction` (or `startY`/`endY` when you
know the pixels) keep the box tall while confining where the ramp happens.

**Tile mode matters on exactly one of the three routes.** `Brush.verticalGradient` takes
`(colorStops, startY, endY, tileMode)`, and it is tempting to credit the default clamp with holding
the flat regions above and below the ramp. Usually it is not doing that. On the default
`endY = Float.POSITIVE_INFINITY` route the shader substitutes the box's own height for the infinite
coordinate, so the ramp spans exactly the box, the gradient parameter never leaves `[0, 1]`, and tile
mode is never consulted. On the `startFraction`/`endFraction` route the ramp is confined by moving
the *stop positions* inward, so the flat ends are held by the first and last stop — still not by the
tile mode. Only an explicit `startY`/`endY` pair inside the box leaves anything outside the ramp for
the tile mode to answer for; switching it to repeat or mirror changes that route and only that route.

**Fade to the colour that is actually behind the scrim.** The bottom of a scrim must equal the page
background exactly, or you have moved the seam rather than removed it. When that background is
derived from the artwork, the two must come from the same source — see the sibling skill
`artwork-palette-theming`, and its fallback for items that have no artwork at all,
`deterministic-title-placeholder-painter`.

## Verifying it

Run these from the repository root. They are cheap and read-only.

1. No transparent stop inside a gradient call. Any hit is either a comment or a bug — read each one:

   ```bash
   grep -rn -A4 --include='*.kt' -E "verticalGradient\(|horizontalGradient\(|linearGradient\(" . \
     | grep -v '/build/' | grep "Color.Transparent"
   ```

2. Every gradient brush in the codebase, so you can check each is either eased or deliberately
   linear (a two-colour decorative gradient across a small tile does not need a curve; a scrim does):

   ```bash
   grep -rln --include='*.kt' -E "verticalGradient\(|horizontalGradient\(" . | grep -v '/build/'
   ```

3. Visually: put the scrim over a flat mid-tone fill instead of artwork. Artwork hides banding and
   hides seams; a flat fill shows both immediately. Then repeat on your darkest background.
