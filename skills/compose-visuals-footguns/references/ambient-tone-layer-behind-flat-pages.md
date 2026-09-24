---
name: ambient-tone-layer-behind-flat-pages
description: A reusable top-glow layer that gives pages with no imagery of their own the same tinted ground the image-backed screens get — emitted as the first sibling of a navigation destination's content, with no wrapper, because destinations already stack. Covers why a null tone must collapse the gradient into the page colour instead of substituting a theme colour, why the scroll-away offset belongs in the draw phase, why the first list item must be taller than the layer, and which screens are right to keep their own copy. Use when a flat settings or list page looks unrelated to the rest of the app, when an idle app shows a glow for nothing, or when a glow snaps out of place as the list scrolls.
---

# An ambient tone layer behind flat pages

Image-backed screens get their character from the image; settings, notifications and other flat pages
get nothing and end up looking like a different app. One shared layer fixes that: an angled two-stop
gradient from a tone into the page colour, capped at a fixed height.

```kotlin
// adapted
val AmbientGlowHeight = 360.dp
@Composable
fun AmbientThemeGlow(modifier: Modifier = Modifier, tint: Color? = null) {
    val pageBackground = /* what is ACTUALLY painted behind this page */
    val glow by animateColorAsState(tween(500), targetValue = when {
        tint == null -> pageBackground                    // collapses → layer is invisible
        isLightTheme -> lerp(tint, Color.White, 0.85f)    // pastel lift
        else         -> tint.rgbFactor(0.45f)             // deepen
    })
    Box(modifier.fillMaxWidth().height(AmbientGlowHeight)
            .angledGradientBackground(listOf(glow, pageBackground), 25f)) {
        Box(Modifier.fillMaxWidth().height(180.dp).align(Alignment.BottomCenter)
            .background(artworkScrimBrush(pageBackground)))   // eases the tail — no edge
    }
}
```

Call it as the **first statement** of the screen body, before the list — no wrapper:

```kotlin
// adapted — inside composable<SettingsDestination> { SettingScreen(…) }
AmbientThemeGlow(tint = rememberGlowTint(currentRecord?.imageUrl))
LazyColumn(state = listState, …) { … }
```

## Traps

**No wrapper is needed, and adding one costs you.** A navigation destination's content already
composes into a stacking container — `NavHost` takes a `contentAlignment`, which only means anything
if children draw on top of one another — so an earlier sibling *is* the layer underneath. Wrapping
the screen in your own `Box` instead re-parents it, changes every child's constraints, and is the
usual reason a scroll container measures differently after a "purely visual" change.

**A null tone must collapse the gradient, not substitute a colour.** With nothing selected the layer
should be *invisible*: make both gradient stops the page colour and it still draws, it just draws
nothing you can see. Substituting the theme's primary as a "reasonable fallback" means an idle app
glows for a record that is not playing. One level down, `Color.Unspecified` is the sentinel for "not
resolved yet", never a real colour, or the first frames flash the wrong tone
(`unknown-not-a-valid-score`).

**The tail must aim at what is actually painted behind the page.** On a shell that wraps content in a
panel colour, a tail aimed at `colorScheme.background` ends on a hard seam exactly where the layer
stops — `shell-background-is-not-scheme-background` in full, and why this resolves a page background
rather than reading the scheme.

**Animate the tone, so it breathes rather than pops.** It arrives asynchronously (an image decode, a
palette pass) and a hard swap flashes across the top third of the page; animating also makes the null
case free, since collapsing to the page colour becomes a fade out.

**The mixing factor belongs with the source of the tone, not with the layer.** A mid-saturated image
colour and a pastel theme colour need different treatment — the multiply that darkens the first
attractively renders the second near-black. The shared layer deepens by 0.45 while the screen feeding
its own image-derived tone uses 0.30; wanting one number means a caller is about to look wrong.

**The layer must scroll away with the list, and the offset must be read in the draw phase.**

```kotlin
// adapted
AmbientThemeGlow(tint = …, modifier = Modifier.graphicsLayer {
    translationY =
        if (listState.firstVisibleItemIndex == 0) -listState.firstVisibleItemScrollOffset.toFloat()
        else -size.height          // parked off-screen once item 0 is gone
})
```

A `graphicsLayer` lambda runs at draw time, so scrolling redraws without recomposing; reading the
same scroll state in the composable body recomposes the layer — and every sibling — per scrolled
pixel.

**The first item has to be taller than the layer, or the hand-off jumps.** The branch above swaps
from exact tracking to parked when item 0 leaves; if item 0 is shorter, the layer is still partly
visible then and teleports. One screen here folded two list items into one so item 0 would clear the
layer's height — a layout constraint the layer imposes on its host, invisible until someone splits
that item up again.

**A top app bar's default container colour covers the only part that carries colour.** The tone is
strongest at the very top, exactly where the bar sits: transparent container, and let the bar frost
the glow rather than hide it.

**The height is a shared constant because the hand-rolled copy sizes itself from it.** That screen
imports the height and nothing else, so hardcoding 360 there is how the two drift on the next design
pass. (Its own doc claims a caller gates a frosting bar on it; none does — all three use pixel 0.)

**A hand-rolled copy re-implements the collapse, and usually not exactly.** The screen keeping its own
version gets "invisible until a tone arrives" by defaulting its colour *state*, not by a null branch —
but it defaults to the **scheme** background while its own tail aims at the resolved page background.
Equal without a shell; with one, 360 dp of gradient is fully visible before any tone arrives —
`shell-background-is-not-scheme-background`, showing up inside this skill's own example.

**Screens that need more are right to keep their own copy.** The shared layer takes one tone; a screen
animating a tone out of its own data, or one that must sit inside its own blur source so the bar
frosts it, keeps a hand-rolled copy — share the *recipe and the height constant*, not the composable.

## Verifying it

```bash
# 1. Every user of the layer, plus everything importing its height constant — the hand-rolled
#    copies sit in that second group, and are what to re-check when the recipe changes.
grep -rn --include='*.kt' -e 'AmbientThemeGlow(' -e 'AmbientGlowHeight' . | grep -v '/build/'
```

→ observed: two screens call the shared composable; one imports only the height constant.

```bash
# 2. The draw-phase scroll-away — a layer without one hangs off the ceiling as content moves.
grep -rn -A4 --include='*.kt' 'graphicsLayer {' . | grep -v '/build/' | grep 'firstVisibleItemScrollOffset'

# 3. The null-collapse. The first branch must resolve to the page colour, not to a theme colour.
grep -rn -A4 --include='*.kt' 'tint == null ->' . | grep -v '/build/'
```

→ observed: exactly three scroll-away layers, one per ambient screen, each negating item 0's offset;
and `tint == null -> pageBackground`, with the light and dark shaping branches after it.

```bash
# 4. The stacking claim, against the resolved library: the host's signature carries an alignment,
#    which only exists for a container that stacks its children.
JAR=$(find ~/.gradle/caches/modules-2 -name 'navigation-compose*.jar' | sort -V | tail -1) && echo "$JAR"
D=$(mktemp -d) && unzip -oq "$JAR" -d "$D" && javap -p -classpath "$D" androidx.navigation.compose.NavHostKt | grep -c 'ui\.Alignment'
```

→ observed: 7 overloads take an `androidx.compose.ui.Alignment`, one exposing its content lambda as
a `BoxScope`. `sort -V` picks the newest *cached* artifact — read the echoed path.

5. By eye: with nothing selected, the page must be indistinguishable from the same page with the
layer deleted. Then select something with a strong image, scroll to the bottom and back, and watch
the moment item 0 leaves the viewport for a jump.
