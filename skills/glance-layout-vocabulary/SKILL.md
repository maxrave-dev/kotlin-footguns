---
name: glance-layout-vocabulary
description: The composable widget toolkit is not Compose with a different import — it has no aspect ratio, its weight is always 1 so an even split is the entire vocabulary, its corner radius only applies from API 31, and a widget always fills the launcher's cell so the spare height must be spent deliberately. Covers the weighted-spacer trick that keeps square tiles square, and where a fill modifier swallows a whole band. Android only. Use when a square tile renders as a rectangle, when a widget shows a block of dead colour below its content, or when corners are round on one device and square on another.
---

# What a widget layout can and cannot express

Android only. Widget composables look like ordinary Compose composables and are not: they compile
down to a `RemoteViews` tree, so every modifier has to have an equivalent in the framework's older
view vocabulary. The ones that do not exist simply are not there, and the surprise is always which.

Three absences account for most broken widget layouts:

- **No aspect ratio.** There is no `aspectRatio` modifier. A square is a square only because you
  gave it the same width and height.
- **Weight is always 1.** `defaultWeight()` takes no argument. Two weighted children split evenly;
  there is no 2:1. An even split is the whole vocabulary.
- **Weight is one-dimensional.** In a row, `defaultWeight()` sets the *width* from the row and
  leaves the height exactly as declared. That is the single most common cause of "my square tiles
  came out rectangular".

## Stretch the gaps, not the tiles

The instinct — give each tile a weight so the row distributes them — is precisely what deforms
them. Give the tiles a fixed size and put the weight on the **spacers between them**:

```kotlin
// adapted — every tile stays square at any row width; only the gaps grow
Row(modifier = GlanceModifier.fillMaxWidth()) {
    tiles.forEachIndexed { index, tile ->
        if (index > 0) Spacer(GlanceModifier.defaultWeight())
        Tile(tile, side = TILE_SIZE)          // one constant, used as width AND height
    }
}
```

`if (index > 0)` puts a gap *between* items and none at the ends, which is what makes the row read
as edge-to-edge inside the widget's own padding. Adding a leading and trailing spacer instead
centres the group and leaves the edges ragged against the padding.

## The spare height has to go somewhere

A widget does not wrap its content. The launcher hands it a cell and it fills it, so whatever height
your bands do not claim is still painted — and unclaimed height reads as a block of dead colour.
Decide explicitly where it lands:

```kotlin
// adapted — both bands weighted, so the cell splits evenly instead of one band swallowing it
Column(GlanceModifier.fillMaxSize().background(stripColour)) {
    Row(GlanceModifier.fillMaxWidth().defaultWeight()) { … }      // upper band
    Column(GlanceModifier.fillMaxWidth().defaultWeight()) { … }   // lower band
}
```

The outer container carries the colour of whichever band should absorb an overflow, so extra height
reads as *more of that band* rather than as a hole showing the home screen through it.

## Traps

**`fillMaxSize()` on one band swallows all the spare height.** It is the obvious way to say "take
what is left" and it takes everything, leaving the band below it flat against the bottom edge with a
slab of colour above. Use `defaultWeight()` on the bands that should share the surplus, and
`fillMaxSize()` only on the outermost container.

**`cornerRadius` is a no-op below API 31.** The modifier compiles and silently does nothing on older
devices, so a circular avatar renders as a square and a rounded tile as a rectangle. That is a
trade-off to make on purpose, not a bug to hunt: decide whether the square fallback is acceptable,
and write the decision next to the call. There is no shape parameter to fall back on — the shape has
to come from a nine-patch or a drawable background instead.

**A circle is `side / 2`, and it has to track the side.** Passing a literal radius that happens to
equal half of today's tile size breaks the moment the tile is resized, and the failure is a subtly
lozenge-shaped avatar nobody files a bug about. Derive it: `radius = TILE_SIZE / 2`.

**A weighted spacer is invisible at count 1.** With a single tile there is no spacer, so the row
collapses to the left and looks nothing like the five-tile version it was designed against. Check
every count from zero up, not just the full row — an empty list, one item, and one short of full are
three different layouts here.

**Text under a fixed-size tile needs its own width, wider than the tile.** A label constrained to
the tile's width truncates to two or three characters; unconstrained, it widens the column and
pushes the weighted spacers around. Give it an explicit width derived from the tile
(`width(TILE_SIZE + 14.dp)`) so the column's footprint stays predictable.

**Every text and icon colour is a `ColorProvider`, and there is no content-colour inheritance.**
Nothing is tinted by an enclosing surface the way it would be in Compose; each `TextStyle` and each
image filter names its colour. When the background became dynamic, a hardcoded grey that had been
fine against a fixed backdrop is now sometimes illegible — derive secondary text from the same
family as the primary (white at an alpha, say) rather than picking a fixed grey.

**Do not size a tile from the widget's measured width.** There is no measurement pass you can read
inside the composition. Sizes are constants, and responsiveness comes from the size buckets declared
in the widget's own metadata plus the weighted spacers absorbing the difference.

## Verifying it

1. **No tile is both weighted and expected to be square.** A weighted child in a row is
   width-from-parent, height-as-declared:

   ```bash
   grep -rn -B1 'defaultWeight()' --include='*.kt' <widget-source-dir> | grep -E 'Spacer\(|size\('
   ```

   Every line this returns should be a weighted `Spacer`. A line pairing `defaultWeight()` with a
   fixed `size(...)` on the same element is the deformation.

2. **Every corner radius is a decision.** Each call should have a nearby note about the pre-API-31
   fallback:

   ```bash
   grep -rn -B3 'cornerRadius(' --include='*.kt' <widget-source-dir>
   ```

3. **`fillMaxSize()` appears on containers only.**

   ```bash
   grep -rn 'fillMaxSize()' --include='*.kt' <widget-source-dir>
   ```

   Two shapes are legitimate: the outermost container of the widget, and an image filling a parent
   whose size is already fixed. Read each hit and ask what it is a sibling of — one on a band that
   has a sibling *below* it is the dead band.

4. **Resize the widget on the launcher through every cell size it declares**, and place it once in
   the largest. The bug this skill is about is invisible at the size you designed against, because
   there is no spare height there.

5. **Render each list length**: zero, one, one short of full, full. Zero must not leave a labelled
   empty band — a section header over nothing is worse than no section.

Companions: `remoteviews-bitmap-budget` for what the tiles cost to draw, and
`glance-widget-over-existing-state` for where the data feeding them comes from.
