---
name: liquid-glass-backdrop
description: Build refracting "liquid glass" surfaces in Compose with a backdrop library, and avoid the two failures that waste the most time — a rim highlight that is directional by default and so goes nearly invisible on small round buttons, and a backdrop source nested inside the glass it feeds, which is a render-feedback loop that stops the shader. Covers the source/surface split, the effect stack, keeping the press gesture observe-only, and the swap experiment that tells a geometry problem from a placement problem. Use when a glass surface renders as a flat rounded box, when the rim shows on a wide pill but not on a circular button, or when the draw pass crashes inside the shader.
---

# Liquid glass: source, surface, rim

A backdrop library splits the effect in two. A **source** modifier marks a composable whose
rendering is recorded into a graphics layer. A **draw** modifier on the **surface** samples that
recording, pushes it through an effect stack, and paints the result behind itself:

```kotlin
// adapted
Modifier.drawBackdrop(
    backdrop = backdrop,
    shape = { shape },
    highlight = { highlight },
    effects = {
        vibrancy()
        colorControls(brightness = 0.05f, contrast = 1f, saturation = 1.5f)
        blur(radius)
        // keep the refraction height below the inradius (minDimension / 2) so the top and bottom
        // refractions never meet at the medial axis — where they meet on a wide pill is where the
        // dark horizontal seam comes from
        lens(size.minDimension / 4f, size.minDimension / 2f, false)
    },
    onDrawSurface = {
        // darken as the background brightens, or bright artwork washes the glass out to white
        drawRect(scrimColor.copy(alpha = darken))
    },
)
```

Three moving parts, in order of trouble caused: the **rim highlight**, the **source/surface
relationship**, and the effect stack. The stack is the easy one — a list of filters you tune by eye.

## Traps

**The rim highlight's default style is directional, not an outline.** This is why a wide pill looks
like glass and a 48 dp circular button next to it looks like nothing at all — same modifier, same
parameters. Read the default style's shader rather than guessing:

```glsl
// annotated — the library's own shader body, re-indented and `=`-aligned; the comments are added
float2 grad     = gradSdRoundedRect(centeredCoord, halfSize, gradRadius);  // outward edge normal
float2 normal   = float2(cos(angle), sin(angle));                          // one light direction
float d         = dot(grad, normal);
float intensity = pow(abs(d), falloff);
return color * intensity;
```

Brightness at a point on the outline is the alignment between that point's **edge normal** and one
fixed direction. On a stadium an entire straight edge shares one axis-aligned normal, so both long
edges light to a constant at once — most of the outline, uniformly, which reads as a rim. On a
circle the normal sweeps every direction, so intensity runs `|cos(θ − angle)|`: full at two opposing
points, **zero at the two 90° away**, below 70% over half the circumference. On a 48 dp button with
a one-pixel rim, nothing is left to see.

Two independent levers fix it. **Swap the style** for the library's uniform one — only a colour and
a blend mode, no angle, no falloff, therefore no direction. Or **widen the rim, keeping the
directional style**: `width` feeds `strokeWidth = ceil(width.toPx()) * 2`, so the 0.5 dp default is
the thinnest stroke the library draws, and `Highlight(width = 1.dp)` puts back enough pixels for the
surviving arc to register. The audited tree ships the *second*, at all four round-button sites — a
wider directional rim keeps them matched to the pills beside them, which a style swap would not. In
the 2.0.x line resolved here the default is white at 0.5 alpha, additive blend, 45°, falloff 1; the
uniform style white at 0.38 alpha, additive blend.

**The backdrop source must be a sibling of the glass, never its parent.** The source records what it
draws; the surface reads that recording while drawing itself. Put the surface *inside* the source
and the recording depends on its own output — the loop stops the shader in the draw pass:

```kotlin
// adapted — the source is the content column; the glass buttons are siblings placed with align()
Box(modifier = Modifier.fillMaxWidth()) {
    Column(modifier = Modifier.fillMaxWidth().layerBackdrop(headerBackdrop)) {
        Spacer(modifier = Modifier.height(48.dp))   // reserves the strip the buttons sit over
        …artwork and text…
    }
    GlassIconButton(backdrop = headerBackdrop, …, modifier = Modifier.align(Alignment.TopStart))
}
```

**A source that draws nothing gives the glass nothing to bend.** Over an empty region the output is
the surface scrim and nothing else, which looks exactly like the effect being broken. Make the
source the column that holds the artwork, reserving the buttons' strip with a `Spacer` inside it.

**Run the discriminating experiment before changing the code.** When one glass widget works and
another does not, swap their positions in the layout. If the effect follows the *widget*, the cause
is the widget's own geometry (the rim trap above); if it follows the *position*, the cause is what
the source records there. Four rebuilds went on plausible fixes before that swap was run — widening
the button to 96 dp (which *does* make the rim appear, because a longer edge catches more of the
sweep: a symptom, not a fix), shrinking the lens radii, moving the source between a full-size box
and the content column, and painting the artwork into the source at low alpha — visible, but it
silently changes the design; do not reach for it.

**Keep the press gesture observe-only.** The glass reacts to press by scaling up and drawing a glow
that follows the pointer — and it wraps buttons that need their own clicks. The recogniser must
never `consume()`, must accept already-consumed downs (`awaitFirstDown(requireUnconsumed = false)`),
and must bail when a change *has* been consumed rather than fight for it. Get this wrong and the
surface animates beautifully while the button inside it stops responding.

**Check whether the library ships a variant for your other targets before writing a no-op actual.**
It is easy to assume a shader-heavy effect is one-platform, declare `expect`/`actual`, and stub the
desktop side — after which the effect is dead code there and nobody notices, because it compiles and
renders a plain rounded box. If the artifact is multiplatform the abstraction has nothing to
abstract: delete the `expect class`, keep a `typealias` so call sites do not churn, move the effect
into common code — which an `expect class` blocks anyway, since it cannot be handed to the library's
own common-code entry points.

## Verifying it

The first two read the resolved library artifact out of the dependency cache — no build needed:

1. **Confirm the default rim is directional and the uniform one is not.** The range must start at
   the uniform block, not at `half4 main` — the declarations sit above the body:
   ```bash
   JAR=$(find ~/.gradle/caches -name '*backdrop*.jar' | head -1)
   DEF=$(unzip -l "$JAR"   | awk '/HighlightStyle\$Default\.class/{print $4}')
   PLAIN=$(unzip -l "$JAR" | awk '/HighlightStyle\$Plain\.class/{print $4}')
   unzip -p "$JAR" "$DEF"   | strings -n 6 | sed -n '/uniform float2 size/,/return color/p'
   unzip -p "$JAR" "$PLAIN" | strings -n 6 | grep -c 'angle\|falloff'
   ```
   → observed: `uniform float angle` and `uniform float falloff` declared, then the
   `dot(grad, normal)` main quoted above; then `0` — the uniform style ships no shader source at all.
2. **List every backdrop source and read each one's enclosing block.**
   `grep -rn 'layerBackdrop(' --include='*.kt' . | grep -v 'fun Modifier'`
   → observed: every hit is a `Box`/`Column` that is a *sibling* of the glass it feeds. A source
   whose own subtree contains a `drawBackdrop` for the same backdrop is the feedback loop.
3. **See which rim lever each call site reaches for.**
   `grep -rn 'highlight = ' --include='*.kt' . | grep -v 'fun \|highlight: '`
   → observed: four round-button sites pass `Highlight(width = 1.dp)` — the wider-rim lever, style
   left directional — one bar passes `Highlight.Default.copy(alpha = …)`, and nothing passes the
   uniform style. A round button left on the bare default is the first one to look at.
4. Resize one glass button between a circle and a wide pill with the effect otherwise unchanged.
   A rim that appears only in the pill state is the highlight-style trap, not a source problem. Then
   A/B the two levers on that button: if the uniform style rescues it *and* a wider directional rim
   also does, the geometry diagnosis is confirmed and you can pick on looks.

Related: `compose-desktop-runtime-hardening` for shader-adjacent crashes that come from the
rendering backend rather than from your own draw code.
