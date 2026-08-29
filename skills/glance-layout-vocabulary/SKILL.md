---
name: glance-layout-vocabulary
description: The composable widget toolkit is not Compose with a different import — it has no aspect ratio, its weight is always 1 so an even split is the entire vocabulary, its corner radius only applies from API 31, and a widget always fills the launcher's cell so the spare height must be spent deliberately. Covers the weighted-spacer trick that keeps square tiles square, and where a fill modifier swallows a whole band. Android only. Use when a square tile renders as a rectangle, when a widget shows a block of dead colour below its content, or when corners are round on one device and square on another.
---

# What a widget layout can and cannot express

Android only. Widget composables look like ordinary Compose composables and are not: they compile
down to a `RemoteViews` tree, so every modifier has to have an equivalent in the framework's older view vocabulary. The ones that do not exist simply are not there, and the surprise is always which.

Three absences account for most broken widget layouts:

- **No aspect ratio.** There is no `aspectRatio` modifier. A square is a square only because you
  gave it the same width and height.
- **Weight is always 1, and one-dimensional.** `defaultWeight()` takes no argument, so an even split
  is the whole vocabulary — and in a row it sets only the *width* from the row, leaving the height exactly as declared: the single most common cause of "my square tiles came out rectangular".

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

`if (index > 0)` puts a gap *between* items and none at the ends, keeping the row edge-to-edge inside
the widget's own padding — a leading-and-trailing spacer instead centres the group, ragged edges and all.

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

The outer container carries the colour of whichever band should absorb an overflow, so extra height reads as *more of that band* rather than as a hole showing the home screen through it.

## Traps

**`fillMaxSize()` on one band swallows all the spare height.** It is the obvious way to say "take
what is left" and it takes everything, leaving the band below it flat against the bottom edge with a
slab of colour above. Use `defaultWeight()` on the bands that should share the surplus, and
`fillMaxSize()` only on the outermost container.

**`cornerRadius` is a no-op below API 31.** It compiles and silently does nothing on older devices, so
a circular avatar renders as a square and a rounded tile as a rectangle — a trade-off to note next to
the call, not a bug to hunt; the shape then has to come from a nine-patch or drawable background instead.

**A circle is `side / 2`, and it has to track the side.** Passing a literal radius that happens to
equal half of today's tile size breaks the moment the tile is resized, and the failure is a subtly
lozenge-shaped avatar nobody files a bug about. Derive it: `radius = TILE_SIZE / 2`.

**A weighted spacer is invisible at count 1.** With a single tile there is no spacer, so the row
collapses to the left and looks nothing like the five-tile version it was designed against. Check every count from zero up — an empty list, one item, and one short of full are three different layouts.

**Text under a fixed-size tile needs its own width, wider than the tile.** Constrained to the tile's
width it truncates to two or three characters; unconstrained, it widens the column and pushes the weighted spacers around. Derive an explicit width from the tile (`width(TILE_SIZE + 14.dp)`) instead.

**Every text and icon colour is a `ColorProvider`; nothing inherits a content colour.** Each
`TextStyle` and image filter names its own colour instead of being tinted by an enclosing surface —
so a grey that was fine against a fixed backdrop can turn illegible once the background goes dynamic.
Derive secondary text from the primary's own family (white at an alpha) rather than a fixed grey.

**Reading the granted size takes two things agreeing, and either one missing makes the other
pointless.** Under the default `SizeMode.Single`, `LocalSize.current` reports the widget's declared
minimum, not what the launcher actually granted — a tile computed from it is a constant wearing the
appearance of a measurement:

```kotlin
// adapted — trailing comments are the skill's, not the source's
override val sizeMode: SizeMode = SizeMode.Exact   // re-composes per granted size
// … inside provideContent …
val songSide = minOf(SONG_TILE_SIZE, (LocalSize.current.width - 36.dp) / 5)   // shrink-only
```

Five `SONG_TILE_SIZE` tiles (58 dp) plus the container's 12 dp padding per side — 5×58+24 = 314 dp —
can outgrow a cell as narrow as the widget's declared `minWidth` (250 dp in the info xml); `minOf` is
why this shrinks instead, and growing past the fixed size stays the weighted spacers' job above.
`Exact` reads the sizes the launcher actually granted, from the app-widget options bundle, regardless
of `resizeMode` (Glance 1.1.1's `SizeBox.kt`: `extractAllSizes`/`extractOrientationSizes`) — it is
`Single` that discards a resize, by early-returning in `GlanceAppWidget`'s own options-changed
handler. `minResizeWidth`/`minResizeHeight` only reshape the *fallback* `minSize` that `Single`
reports: a small `minResizeWidth` makes `LocalSize` smaller, not measured. What `resizeMode="none"`
actually costs is the user's ability to resize the widget at all.

## Verifying it

Run from the app repo root. Set `WIDGET_SRC=androidApp/src/main/java/com/maxrave/simpmusic/ui/widget`
once and reuse `"$WIDGET_SRC"` below.

1. **No tile is both weighted and expected to be square.** A weighted child in a row is
   width-from-parent, height-as-declared:

   ```bash
   grep -rn -B1 'defaultWeight()' --include='*.kt' "$WIDGET_SRC" | grep -E 'Spacer\(|size\('
   ```

   Every line this returns should be a weighted `Spacer`. A line pairing `defaultWeight()` with a
   fixed `size(...)` on the same element is the deformation.

2. **Every corner radius is a decision.** Each call should have a nearby note about the pre-API-31
   fallback:

   ```bash
   grep -rn -B3 'cornerRadius(' --include='*.kt' "$WIDGET_SRC"
   ```

3. **`fillMaxSize()` appears on containers only.**

   ```bash
   grep -rn 'fillMaxSize()' --include='*.kt' "$WIDGET_SRC"
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
