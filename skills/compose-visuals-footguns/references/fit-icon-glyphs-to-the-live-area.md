---
name: fit-icon-glyphs-to-the-live-area
description: Make a row of same-size icons read as one size by fitting every glyph into the icon grid's 20×20 live area when the icon is built — a symbol font's own glyphs spill into the 2dp padding, judging a glyph by a circle around its farthest point over-shrinks any glyph with one protruding stroke, and a small round icon button clips its content to its own shape. Use when icons drawn at the same size look big-and-small side by side, when the corners of one icon are cut inside a small round button, or when a debug outline shows glyphs crossing their box.
---

# Fitting icon glyphs to the live area

The system-icon grid is a 24×24 box whose glyph belongs in the centred **20×20 live area**, with
2dp of padding around it; inside that square, keyline shapes of about equal area (a 20 circle, an
18 square, 20×16 rectangles) are what make unrelated glyphs read as one size. A symbol font's
generated glyphs do not all keep to it. In the mined set, 24 of 111 spill into the padding — the
note on a lyrics bubble reaches the box's right edge, a group-of-people glyph spans the full 24 —
and at one size those read bigger than every neighbour. The path data is exactly what the font's
own generator emits, so regenerating changes nothing; the fix belongs in the one function every icon
file already ends with (generating the set itself is `material-symbols-icon-system`):

```kotlin
// adapted — the shared ending of every generated icon, in place of .build()
internal fun ImageVector.Builder.buildAppIcon(): ImageVector {
    val glyph = build()
    val extent = glyph.extent() ?: return glyph            // reach from the centre along either axis
    val limit = glyph.viewportWidth * (20f / 24f) / 2f     // half the live area: 10 on the 24 grid
    if (extent <= limit + 0.01f || limit / extent < 0.6f) return glyph
    return try { glyph.scaledAboutCentre(limit / extent) } catch (e: Exception) { glyph }
}
```

`extent()` walks each path's nodes with SVG semantics — relative commands added to the current
point, a reflective control point mirrored only after a curve of its own kind, `close` returning to
the subpath start — and samples each curve; 16 points per curve is exact enough on a 24 grid.
`scaledAboutCentre` rebuilds the vector with every path inside one group whose `scaleX`/`scaleY`
pivot on the viewport centre. In the mined set the deepest shrink is ×0.83, most are ×0.91–0.98.

## Traps

**Fitting glyphs into a circle instead of the square.** A circle about the centre, just inside the
box, looks like the natural yardstick, and it judges a glyph by its single farthest point. A glyph with one
protruding stroke — the note's tip on the lyrics bubble, 15.9 from the centre — had to shrink to
×0.72 to pull that tip in, and then read far smaller than the open queue glyph beside it, which was
not touched at all. The circle changed 43 icons where the square changes 24, and every glyph the
font kept inside its live area stays exactly as drawn.

**Drawing a debug outline that is not the grid.** An outline drawn around each icon to compare a
row becomes the rule people fit to; the circle above came from exactly such an outline.
Draw the live-area square instead, behind a flag that is off by default and set before the first
icon is built — a generated icon is cached in its backing field, so flipping the flag later
changes nothing on screen.

**Enlarging glyphs that sit well inside.** The fit only shrinks. A three-dot overflow glyph or a
plus sign is small by design; scaling it up to the live area produces a giant glyph.

**Letting a measurement failure reach the screen.** The getter runs during composition. An arc the
walker does not measure, a group whose transform it does not apply, an implausible fit (tighter
than ×0.6, which means a stray far point) and a rebuild that throws must all return the glyph as
generated and log — never throw, never return a half-built vector.

**A small round icon button clips its content to its shape.** The standard icon button clips the
box holding its content to `shape`, a circle by default (`.clip(shape)` in its implementation).
Sized 24dp, that circle reaches 12 from the centre, while a glyph filling the 20×20 square reaches
14.1 at its corners — a speech bubble reaches 13.3 — so its corners vanish while round or open
glyphs beside it look fine, and the icon file gets the blame. Give that one button a clip larger
than its slot:

```kotlin
Box(Modifier.size(24.dp)) {                                                        // adapted
    IconButton(onClick, Modifier.requiredSize(28.dp).clip(CircleShape)) { Icon(AppIcons.Comment, null) }
}
```

`requiredSize` keeps the row's 24dp slot and centres the 28dp button on it.

**Sizing each glyph by eye at the call site.** 22, 23 and 24dp side by side is what made the row
read big-small before any glyph was measured. One size per row; only a deliberate hierarchy, such
as a play button over previous and next, gets another.

## Verifying it

Read-only, from the repository root; substitute your icon package path and builder name for
`ui/icon` and `buildAppIcon`.

1. **Every icon file ends with the shared builder.**
   `find . -path '*/ui/icon/*.kt' -not -path '*/build/*' -exec grep -L 'buildAppIcon()' {} +`
   → observed: empty; the file defining the builder names it too.
2. **Nothing still ends with a plain build.**
   `find . -path '*/ui/icon/*.kt' -not -path '*/build/*' -exec grep -l '\.build()$' {} +`
   → observed: one hit, the file that defines the builder, whose rebuild ends with it.
3. **Small round icon buttons, to read against their glyphs.**

   ```bash
   grep -rn -A6 --include='*.kt' 'IconButton($' . | grep -v '/build/' | awk '
     /IconButton\($/ { if (s && c) n++; s=0; c=0 }
     /\.size\(2[0-4]\.dp\)/ { s=1 } /clip\(CircleShape\)/ { c=1 }
     END { if (s && c) n++; print "small round IconButtons:", n+0 }'
   ```

   → observed: 4, each holding a glyph that stays inside the circle. Open every hit and compare its
   glyph's corners with the button's circle; a glyph that fills its live area needs the larger clip.
4. **A guard test keeps a regenerated icon from slipping past.** The mined tree loads every icon by
   reflection — `val AppIcons.X` compiles to a static `getX(AppIcons)` on the file class `XKt` — and
   asserts that each drawn glyph reaches at most 10 of 24 plus rounding, and that a glyph already
   inside was not rebuilt: its root still holds bare paths, not a scaled group.
