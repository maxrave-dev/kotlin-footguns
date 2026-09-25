---
name: angled-gradient-modifier
description: Draw a linear gradient at an arbitrary angle across a Compose box so both endpoints land exactly on the box edge — the per-quadrant endpoint formula from the requested angle, why rotating the diagonal overshoots and why clamping to the nearest edge distorts the angle, and the degenerate cases that collapse the ramp to nothing. Use when a tilted gradient looks washed out or cut off near the corners, when the visible angle does not match the angle you asked for, or when the same gradient looks different on a wide box than on a tall one.
---

# Angled gradient background

`Brush.linearGradient` takes two points, not an angle. So "a gradient at 30°" is really the question
*where do the two endpoints go so the ramp completes exactly across the box at 30°*, and the answer
depends on the box's aspect ratio — which is why the same brush cannot be built once at composition
time. The whole thing lives inside a draw modifier, where the size is known.

```kotlin
// adapted (guard clauses trimmed; see Traps for the ones that were removed)
fun Modifier.angledGradientBackground(colors: List<Color>, degrees: Float) =
    this.then(
        if (colors.size < 2) Modifier else Modifier.drawBehind {
            val (x, y) = size
            val gamma = atan2(y, x)                 // angle of the box's own corner
            if (gamma == 0f || gamma == (PI / 2).toFloat()) return@drawBehind

            val degreesNormalised = (degrees % 360).let { if (it < 0) it + 360 else it }
            val alpha = (degreesNormalised * PI / 180).toFloat()

            val gradientLength = when (alpha) {
                in 0f..gamma, in (2 * PI - gamma)..2 * PI -> x / cos(alpha)   // exits a vertical edge
                in gamma..(PI - gamma).toFloat()          -> y / sin(alpha)   // exits a horizontal edge
                in (PI - gamma)..(PI + gamma)             -> x / -cos(alpha)
                in (PI + gamma)..(2 * PI - gamma)         -> y / -sin(alpha)
                else                                      -> hypot(x, y)      // unreachable; keep it
            }

            val offsetX = cos(alpha) * gradientLength / 2
            val offsetY = sin(alpha) * gradientLength / 2
            drawRect(
                brush = Brush.linearGradient(
                    colors = colors,
                    start = Offset(center.x - offsetX, center.y - offsetY),
                    end = Offset(center.x + offsetX, center.y + offsetY),
                ),
                size = size,
            )
        },
    )
```

The formula is one line of trigonometry worth understanding rather than copying. `γ = atan2(h, w)`
is the angle at which the ray from the centre passes through the box's corner, so it is exactly the
boundary between "this ray leaves through a vertical edge" and "…through a horizontal edge". In the
vertical-edge case the length is `w / |cos α|`, so the horizontal half-offset is `w/2` — the endpoint
sits *on* the edge by construction — and the other coordinate is `(w/2)·tan α`, which the range test
guarantees is at most `h/2`.

## Traps

**Rotating the diagonal overshoots, and truncating to the edge distorts the angle.** The tempting
shortcut is to take a vector of length `hypot(w, h)/2` and rotate it. That length is only correct at
the four corners: elsewhere the distance from the centre to the boundary is
`min(w / 2|cos α|, h / 2|sin α|)`, which is strictly smaller, so the endpoint lands outside the box
and only the middle of the ramp is visible — a gradient that never reaches either end colour.
Clipping the overshooting point back to the nearest edge fixes the overshoot but moves the point
sideways, so the line between the endpoints is no longer at the angle you asked for.

**Normalise the angle before you compare it.** Kotlin's `%` keeps the sign of the dividend, so
`-30f % 360` is `-30f` and falls through every range test into the fallback branch. Add 360 when the
remainder is negative.

**A degenerate box gives a zero-length gradient, not a division by zero.** `γ` collapses to 0 (zero
height) or π/2 (zero width), and the branch the angle then selects is the one whose *numerator* is
the collapsed dimension — so the length comes out 0 and both endpoints land on the centre. A true
`0/0` needs the divisor to be exactly zero as well, which the `Float` π these angles are built from
does not deliver. Bail out on `γ` anyway: nothing can be drawn, and boxes really do get measured at
zero before they have a size.

**Keep the unreachable `else`.** The four ranges cover `[0, 2π]` mathematically, but they are
compared in floating point with inclusive bounds, and `γ` is a `Float` while the π-derived bounds
are `Double`. Drop the `else` and this does not compile — a `when` used as an expression must be
exhaustive — and the diagonal is a harmless answer for whatever the ranges somehow miss.

**Angles are clockwise on screen, because y grows downward.** 0° runs left→right, 45° runs
top-left→bottom-right, 90° runs top→bottom. Porting angles from a design tool that measures
counter-clockwise means negating them — which the normalisation trap above is what makes safe.

**Guard `colors.size < 2` rather than finding out what your renderer does with one stop.** A single
colour is a caller bug — a "gradient" with one end — and the cost of the guard is one comparison.

**The axis-aligned directions need none of this.** `Brush.linearGradient` substitutes the box's size
for infinite endpoint coordinates: on `ui-graphics-android` 1.12.0-alpha03 its `createShader` tests
all four coordinates against `Float.POSITIVE_INFINITY` and swaps in `size.width` / `size.height`.

```kotlin
Brush.linearGradient(colors, start = Offset.Zero, end = Offset(Float.POSITIVE_INFINITY, 0f))  // left → right
Brush.linearGradient(colors, start = Offset.Zero, end = Offset(0f, Float.POSITIVE_INFINITY))  // top → bottom
Brush.linearGradient(colors, start = Offset.Zero, end = Offset.Infinite)  // the box DIAGONAL, not 45°
```

The third line is the trap inside the shortcut. `Offset.Infinite` is infinite in *both* coordinates,
so both get substituted, the endpoint lands on the far corner, and the ramp runs at `atan2(h, w)` —
the box diagonal, whose angle follows the aspect ratio and is 45° only on a square. That is what
Verify #4 exposes; a real 45° elsewhere needs the arithmetic above. Check it against the artifact:

```bash
AAR=$(find ~/.gradle/caches/modules-2 -path '*ui-graphics-android*' -name '*.aar' | sort -V | tail -1) \
  && echo "$AAR" && D=$(mktemp -d) && unzip -oq "$AAR" classes.jar -d "$D" \
  && unzip -oq "$D/classes.jar" -d "$D/cls" \
  && javap -c -p -classpath "$D/cls" androidx.compose.ui.graphics.LinearGradient \
     | sed -n '/createShader/,/^  public/p' | grep -c "float Infinityf"
```

Expect `4`, one comparison per endpoint coordinate — the count on 1.12.0-alpha03. `sort -V` picks the
newest *cached* version, not necessarily the one your build resolves, so read the echoed path. Reach
for the angle math when the design needs an angle that is not axis-aligned, or when it is animated.

**Do not also set a `background(...)` colour underneath.** `drawBehind` paints on every draw pass, so
a second opaque layer behind it is invisible work. On a browse tile this modifier *is* the
background — see `overflow-tilted-browse-card`.

## Verifying it

1. Find every call site and check the angle constants against the clockwise convention above:

   ```bash
   grep -rn --include='*.kt' "angledGradientBackground(" . | grep -v '/build/'
   ```

2. Find hand-rolled endpoint arithmetic that should be using the modifier instead — any
   `Brush.linearGradient` whose `start`/`end` are computed rather than `Offset.Zero`/`Offset.Infinite`:

   ```bash
   grep -rn -A6 --include='*.kt' "Brush.linearGradient(" . | grep -v '/build/' | grep -E "start =|end ="
   ```

3. Prove the endpoints land on the edge rather than trusting the eye: give the gradient two
   maximally different colours (pure red to pure blue, no alpha) and check that both pure colours
   are visible in the corners of the box. A ramp whose endpoints overshoot shows only muddy purple.

4. Resize the box from square to very wide and back while the gradient is on screen. The visible
   angle must not change — that is the entire point of the per-quadrant branch, and it is the one
   thing a fixed-endpoint gradient gets wrong.
