---
name: liquid-glass-backdrop
description: Build refracting "liquid glass" surfaces in Compose with a backdrop library, and avoid the three failures that waste the most time — a rim highlight that is directional by default and so goes nearly invisible on small round buttons, a backdrop source nested inside the glass it feeds, which is a render-feedback loop that stops the shader, and a source with nothing in it, which renders the control as a grey coin over a flat page. Covers the source/surface split, giving a flat page a ground worth refracting rather than dropping the effect, the white default tint that only suits forced-dark screens, the effect stack, keeping the press gesture observe-only, and the swap experiment that tells a geometry problem from a placement problem. Use when a glass surface renders as a flat rounded box or a grey coin, when the rim shows on a wide pill but not on a circular button, when its glyph disappears at light theme, or when the draw pass crashes inside the shader.
---

# Liquid glass: source, surface, rim

A backdrop library splits the effect in two. A **source** modifier records a composable's rendering
into a graphics layer; a **draw** modifier on the **surface** samples that recording, pushes it
through an effect stack, and paints the result behind itself:

```kotlin
// adapted
Modifier.drawBackdrop(
    backdrop = backdrop,
    shape = { shape }, highlight = { highlight },
    effects = {
        vibrancy()
        colorControls(brightness = 0.05f, contrast = 1f, saturation = 1.5f)
        blur(radius)
        // refraction height below the inradius (minDimension / 2), so top and bottom refractions
        // never meet at the medial axis — that meeting is the dark seam on a wide pill
        lens(size.minDimension / 4f, size.minDimension / 2f, false)
    },
    // darken as the background brightens, or bright artwork washes the glass out to white
    onDrawSurface = { drawRect(scrimColor.copy(alpha = darken)) },
)
```

Three moving parts, in order of trouble caused: the **rim highlight**, the **source/surface
relationship**, and the effect stack — the stack being a list of filters you tune by eye.

## Traps

**The rim highlight's default style is directional, not an outline.** This is why a wide pill looks
like glass and a 48 dp circular button beside it looks like nothing — same modifier, same parameters.
Read the default style's shader rather than guessing:

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
edges light to a constant at once — most of the outline, uniformly, which reads as a rim. On a circle
the normal sweeps every direction, so intensity runs `|cos(θ − angle)|`: full at two opposing points,
**zero at the two 90° away**, under 70% over half the circumference — nothing left on a 48 dp button.

Two independent levers fix it. **Swap the style** for the library's uniform one (a colour and a blend
mode; no angle, no falloff, therefore no direction). Or **widen the rim, keeping the directional
style**: `width` feeds `strokeWidth = ceil(width.toPx()) * 2`, so the 0.5 dp default is the thinnest
stroke the library draws and `Highlight(width = 1.dp)` puts back enough pixels for the surviving arc.
The audited tree ships the *second* at every site that reaches for a lever, keeping them matched to
the pills beside them as a style swap would not. In the 2.0.x line resolved here the default is white
at 0.5 alpha, additive, 45°, falloff 1; the uniform style white at 0.38 alpha, additive.

**The backdrop source must be a sibling of the glass, never its parent.** The source records what it
draws and the surface reads that recording while drawing itself, so a surface *inside* the source
makes the recording depend on its own output — the loop stops the shader in the draw pass:

```kotlin
// adapted — the source is the content column; the glass buttons are siblings placed with align()
Box(Modifier.fillMaxWidth()) {
    Column(Modifier.fillMaxWidth().layerBackdrop(headerBackdrop)) {
        Spacer(Modifier.height(48.dp))              // reserves the strip the buttons sit over
        …artwork and text…
    }
    GlassIconButton(headerBackdrop, …, modifier = Modifier.align(Alignment.TopStart))
}
```

**A source that draws nothing gives the glass nothing to bend — and the cure is a ground, not a
retreat.** Over an empty region the output is the surface scrim and nothing else: on a flat page the
control renders as a grey coin, worse than no chrome at all. That is a full arc here — glass
introduced, then *removed* for a plain icon button with exactly that reasoning written into the
commit, then restored once the page had a ground worth refracting. The ground is a `matchParentSize()`
box carrying the page colour plus the page's ambient tone, and the source is **that box** — never the
content column, which is mostly transparent and rendered the control as a solid dark coin over a
tinted page. Where the content genuinely draws (a list whose first item is a full-width image header)
it is the right source, its strip reserved by a `Spacer`. The glass must also *float* over the
ground rather than ride the scrolling column, which scrolls it away on a flat page.

**The default tint assumes a forced-dark screen.** These controls are usually built first for screens
inside a forced-dark subtree, where a white glyph always sits over dark artwork and `Color.White` is
sound. On a theme-following page it is white-on-white at light theme — and the flat fallback an
off-setting swaps in is light too, so the glyph vanishes in both materials. Pass the scheme's
on-surface token instead; `force-dark-immersive-subtree` is why the donor screens never hit this.

**Run the discriminating experiment before changing the code.** When one glass widget works and
another does not, swap their positions: if the effect follows the *widget* the cause is its own
geometry (the rim trap above), if it follows the *position* it is what the source records there. Four
rebuilds went on plausible fixes first — widening the button to 96 dp (a longer edge catches more of
the sweep, so the rim *does* appear: a symptom, not a fix), shrinking the lens radii, moving the
source between a full-size box and the content column, and painting artwork in at low alpha.

**Keep the press gesture observe-only.** The glass scales up and draws a pointer-following glow on
press, and it wraps buttons that need their own clicks. The recogniser must never `consume()`, must
accept already-consumed downs (`awaitFirstDown(requireUnconsumed = false)`), and must bail when a
change *has* been consumed — or the surface animates while the button inside it stops responding.

**Check whether the library ships a variant for your other targets before writing a no-op actual.**
Assuming a shader-heavy effect is one-platform and stubbing the desktop `actual` leaves it dead code
there that nobody notices — it compiles and renders a plain rounded box. If the artifact is
multiplatform the abstraction has nothing to abstract: delete the `expect class`, keep a `typealias`
so call sites do not churn, and move the effect into common code — which the class blocked anyway.

## Verifying it

1. **Confirm the default rim is directional and the uniform one is not**, out of the dependency
   cache, no build. The range starts at the uniform block, not at `half4 main`:
   ```bash
   JAR=$(find ~/.gradle/caches -name '*backdrop*.jar' | head -1)
   DEF=$(unzip -l "$JAR"   | awk '/HighlightStyle\$Default\.class/{print $4}')
   PLAIN=$(unzip -l "$JAR" | awk '/HighlightStyle\$Plain\.class/{print $4}')
   unzip -p "$JAR" "$DEF"   | strings -n 6 | sed -n '/uniform float2 size/,/return color/p'
   unzip -p "$JAR" "$PLAIN" | strings -n 6 | grep -c 'angle\|falloff'
   ```
   → observed: `uniform float angle` and `uniform float falloff` declared, then the
   `dot(grad, normal)` main quoted above; then `0` — the uniform style ships no shader source at all.
2. **List every backdrop source; read each one's enclosing block, and what it draws.**
   `grep -rn 'layerBackdrop(' --include='*.kt' . | grep -v 'fun Modifier'`
   → observed: every hit is a `Box`/`Column` *sibling* of the glass it feeds — including the analytics
   screen, whose source is the `LazyColumn` itself (first item an image header, so it draws), buttons
   placed after it by `align()`. A source whose subtree holds a `drawBackdrop` for the same backdrop
   is the crash; a bare transparent source is the grey coin.
3. **See which rim lever each call site reaches for.**
   `grep -rn 'highlight = ' --include='*.kt' . | grep -v 'fun \|highlight: '`
   → observed: six sites pass `Highlight(width = 1.dp)` (the wider-rim lever, style left directional),
   one bar passes `Highlight.Default.copy(alpha = …)`, nothing passes the uniform style. Two 48 dp
   back buttons on the theme-following pair are on the bare default — the first ones to look at.
4. Resize one glass button between circle and wide pill, everything else unchanged: a rim appearing
   only in the pill state is the highlight trap. If both levers rescue it, geometry is confirmed.

Related: `compose-desktop-runtime-hardening` (shader-adjacent crashes from the rendering backend
rather than your draw code) and `shell-background-is-not-scheme-background` (what a ground is made of).
