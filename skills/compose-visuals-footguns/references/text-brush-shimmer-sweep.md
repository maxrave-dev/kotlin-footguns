---
name: text-brush-shimmer-sweep
description: Sweep a travelling highlight through a label by putting a moving gradient on the TextStyle itself — the glyphs are painted by the brush, so there is no overlay, no clip and no measured width to keep in sync. Covers declaring the infinite transition unconditionally so the sweep does not restart every time the label appears, why the sweep head must be a pure high-contrast colour rather than the label's own, why the gradient stops are pixels and must travel past both ends, and that a brush replaces the text colour outright. Use when a shimmering label jumps back to the start whenever it reappears, when the gleam is invisible against the label's own grey, or when setting a brush makes a carefully chosen text colour vanish.
---

# A highlight that travels through the glyphs

`TextStyle` takes a `Brush`. Animate the gradient's `startX`/`endX` and the *text* shimmers — not a
rectangle over it, not a masked copy of it. Nothing has to measure the label, so it keeps working
at any width, in any language, wrapped or not.

```kotlin
// adapted — the transition is declared OUTSIDE the gate that shows the label
val sweep = rememberInfiniteTransition(label = "sweep")
val head by sweep.animateFloat(
    initialValue = 0f, targetValue = 1f,
    animationSpec = infiniteRepeatable(tween(3200, easing = LinearEasing), RepeatMode.Restart),
    label = "sweepHead",
)

AnimatedVisibility(visible = isBusy, enter = fadeIn(), exit = fadeOut()) {
    val span = 140f                          // pixels of gradient, in the text's own space
    val x = head * (span * 3f) - span        // starts fully left of the label, ends fully right
    Text(
        text = stringResource(Res.string.working),
        style = typo().bodySmall.copy(
            brush = Brush.horizontalGradient(
                0f to labelColor.copy(alpha = 0.45f),
                0.5f to Color.White,         // the gleam: pure, not the label's own colour
                1f to labelColor.copy(alpha = 0.45f),
                startX = x, endX = x + span,
                tileMode = TileMode.Clamp,
            ),
        ),
        maxLines = 1,
    )
}
```

## Traps

**Declare the endless animation unconditionally; gate only what draws it.** Put
`rememberInfiniteTransition` inside the `AnimatedVisibility` (or behind an `if`) and it is created
fresh each time the label appears, so every appearance restarts the sweep at phase zero. On a label
that comes and goes — a transient status line — the gleam visibly snaps back to the left edge on
arrival instead of continuing. The transition costs one animation frame subscription while nothing
reads it; that is the entire price of the fix.

**The gleam must be a pure high-contrast colour, not the label's resting colour.** The instinct is
to sweep "the label colour, brighter" — but a label colour is usually an adaptive grey chosen for
readability against whatever is behind it, and a lighter grey against grey reads as nothing at all.
Pin the middle stop to a real white (or, on a light surface, a real black) and let the two ends
carry the adaptive colour at a reduced alpha. The gleam is a highlight; a highlight needs a value
gap, not a hue shift.

**A brush replaces the text colour — it does not tint it.** Once the style carries one, the
foreground is the brush and the colour is gone: the brush-carrying `copy` overload has no `color`
parameter at all, and the resulting foreground reports its colour as unspecified. So the resting
appearance of the label is now entirely the two end stops of your gradient. If it looks washed out
when idle, that is the stops' alpha, not a theme problem — and hiding the whole thing behind
`AnimatedVisibility` means the styled version only exists while the sweep is running anyway.

**`startX`/`endX` are pixels in the text's layout space, and the band must clear both ends.** A
sweep that runs `0f → width` starts with the gleam already on the first glyph and ends with it
parked on the last one. Travelling `-span → 2 × span` (which is what `head * span * 3 - span`
gives) puts the band fully off the left before the pass and fully off the right after it, so each
cycle is a clean entry and exit. Because the band is a fixed pixel span rather than a fraction, a
long label takes proportionally longer to cross — which is what you want; a fraction makes the
gleam physically wider on long labels and it stops looking like one light source.

**Those pixel figures are raw pixels, not density-independent units.** The drawing space these
gradient stops live in is the same one the text was laid out in, so a hardcoded `140f` band is
140 *physical* pixels — roughly a third as wide on a high-density handset as on a low-density
display, and the sweep crosses a given label that much faster there. It looks tuned on whichever
device it was tuned on. Convert from a dp figure at the call site
(`with(LocalDensity.current) { 48.dp.toPx() }`) if the effect has to read the same everywhere.

**`TileMode.Clamp`, not `Repeated` or `Mirror`.** Outside the band, clamping holds the nearest
stop — which is the resting colour, so the rest of the label looks normal. Repeating puts a second
and third gleam on screen and turns a sweep into a barber pole.

**Give the label room before it exists.** The styled label usually appears next to something
already occupying the row. A neighbour on `weight(1f)` claims the whole width and pushes the label
out of view the moment it appears; `weight(1f, fill = false)` lets it shrink and give the label its
space. This is invisible until the state that shows the label actually occurs.

**One transition per label is fine; one per list row is not.** Inside a lazy list, each row creates
and destroys its own transition as it scrolls, so rows sweep out of phase and restart on recycle.
Hoist a single transition above the list and pass the value down.

**Do not animate `Text(color = …)` for this.** A flat colour animation brightens every glyph at
once, which reads as a blink; the whole point of the brush is that different glyphs are at
different points of the gradient at the same instant.

Related: `shimmer-skeleton-loaders` is the other half of this family — a sweep across a *block*
standing in for content that has not loaded, where the modifier must learn its own size because
there are no glyphs to paint. `hoist-the-flag-not-the-animation` covers sharing the boolean that
decides when this label is visible without sharing the tween that fades it.

## Verifying it

```bash
# 1. no endless animation is declared inside a visibility gate
grep -rn --include='*.kt' -A6 'AnimatedVisibility(' . | grep -c 'rememberInfiniteTransition'

# 2. every endless animation in the tree — read each one's enclosing block
grep -rn --include='*.kt' 'rememberInfiniteTransition(' .

# 3. a brush foreground has no colour left to override
TX=$(find ~/.gradle/caches -name 'ui-text-desktop-*.jar' | head -1)
javap -c -p -classpath "$TX" androidx.compose.ui.text.style.BrushStyle \
  | sed -n '/getColor/,/lreturn/p'

# 4. ...and the brush-taking copy overload does not accept one
javap -p -classpath "$TX" androidx.compose.ui.text.TextStyle \
  | grep 'TextStyle copy' | grep -c 'graphics.Brush'
```

1. → observed: `0`. Any non-zero hit is the restart-from-zero defect, and it is silent — the
   animation runs, it just never continues where it left off.
2. → observed: a dozen or so, each declared at the level of the composable that owns the animated
   value rather than inside the branch that renders it. A few of them drive text sweeps — the
   enclosing block is what tells you which, since the rest animate colour, rotation or a placeholder.
3. → observed: the getter loads `Color.Companion.Unspecified` and returns it. There is no colour
   under the brush to fall back to.
4. → observed: `4` — two brush-taking `copy` overloads plus their default-argument bridges. Compare
   with the colour-taking overloads: they are separate methods, so `copy(brush = …)` selects a
   signature that has no `color` parameter and the previous colour is discarded, not merged.

Then, by hand: trigger the label, let it disappear, and trigger it again within a second or two.
The gleam must be wherever the clock put it — mid-label is the healthy sign — not back at the left
edge. Watch it on both themes: the gleam must be visible on each, which is what fails when the
middle stop derives from the label colour.
