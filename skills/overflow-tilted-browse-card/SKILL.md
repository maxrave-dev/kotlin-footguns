---
name: overflow-tilted-browse-card
description: Build a browse tile whose cover art is tilted and runs off the clipped corner — the modifier order that makes the diagonal a cut rather than a pasted square, the rotated bounding-box growth that decides how much room siblings must leave, and why a non-square tile cannot size its decoration off the width. Use when a rotated image shows sliced corners, when text collides with tilted art or reflows the moment that art loads, or when a rotated child covers its neighbours instead of being clipped by its parent.
---

# Overflow tilted browse card

The effect is a rectangular tile with a small cover art rotated a few degrees and hanging off one
corner, cut cleanly by the tile's rounded edge. Everything about it comes from two decisions:
the parent clips, and the child is moved *past* the edge before it is rotated.

```kotlin
// adapted
Box(
    modifier = modifier
        .fillMaxWidth()
        .aspectRatio(2f)
        .clip(RoundedCornerShape(10.dp))          // must precede everything it should clip
        .angledGradientBackground(colors = gradientFromTitle(title), degrees = 45f)
        .drawBehind {
            // 2:1 tile, so anchor decoration on the HEIGHT (see Traps)
            val radius = size.height * 0.09f
            val centre = Offset(size.width - radius * 2f, radius * 2f)
            drawCircle(center = centre, color = Color.White, radius = radius)
            val badgeSize = Size(radius * 3f, radius * 3f)
            translate(centre.x - badgeSize.width / 2f, centre.y - badgeSize.height / 2f) {
                with(badge) { draw(badgeSize, alpha = 0.2f) }
            }
        }
        .clickable(onClick = onClick),
) {
    if (artworkUrl != null) {
        AsyncImage(
            model = artworkUrl,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .offset(x = 8.dp, y = 12.dp)      // past the corner FIRST
                .size(64.dp)
                .rotate(25f)                      // then rotate
                .clip(RoundedCornerShape(2.dp)),  // clip inside the rotation
        )
    }
    Text(
        text = title,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier
            .align(Alignment.TopStart)
            .padding(start = 12.dp, top = 12.dp, bottom = 12.dp, end = 72.dp),
    )
}
```

## Traps

**The clip that produces the cut diagonal is the parent's, not the child's.** `offset` moves where a
child *draws* without changing what the parent measured, so the child genuinely hangs outside the
tile — and the tile's `clip` is what turns that overhang into a diagonal edge. Remove the parent clip
and the same code renders as a square photo pasted over the neighbouring tiles.

**Modifier order decides which of the two clips wins.** Modifiers wrap left to right, so the leftmost
draws outermost. On the child, `rotate` then `clip` means the rounded corners are applied inside the
rotation and turn with the art; `clip` then `rotate` applies an axis-aligned rounded rectangle over
the already-rotated image and slices its corners off — the classic "why is my tilted image
chamfered". On the parent, the `clip` must come before the background and `drawBehind` it is meant to
contain, or those paint square corners outside it.

**Rotation does not change the measured size, so every neighbour's spacing is your arithmetic.** The
parent still lays the child out as an `s × s` box; only the drawing turns. A square of side `s`
rotated by θ occupies an axis-aligned box of side

```
s · (|cos θ| + |sin θ|)
```

which for 64 dp at 25° is 64 × (0.906 + 0.423) ≈ 85 dp — about **10.5 dp further out on every side**
than the box the layout system knows about, since the growth `s(|cos θ| + |sin θ|) − s` is split
between the two edges. Combine that with the outward offset to get the real intrusion: aligned to the
bottom-end corner and pushed 8 dp past it, the art's left extent is `64 − 8 + 10.5 ≈ 66.5 dp` inside
the tile, which is what the text's ~72 dp end padding is buying room for. Compute this once and put
the number where the sibling's padding is written, with the working next to it — nobody will
re-derive it, and every change to the size or the angle invalidates it.

**Reserve the space whether or not the art loads.** The cover is usually nullable — resolved by a
separate request, arriving late or never. Pad the text unconditionally, so the tile does not reflow
under the user when the image appears, and design the gradient-plus-badge state to look finished on
its own rather than as an empty slot.

**Fractional decoration sizes are relative to the dimension you choose, and a square tile hides the
choice.** Sizing a badge off the width works fine on a 1:1 tile; on a 2:1 tile the same fraction
doubles it. Anchor on the height (or on `min(width, height)`) so the badge stays the size the eye
expects across aspect ratios, and say so in a comment — this is not visible from the constants.

**Give the cover a content scale that fills.** Source art is arbitrary aspect; `ContentScale.Crop`
fills the square so the rotation never exposes background through a corner. `Fit` will letterbox and
the letterbox turns with the image.

**`offset` versus `absoluteOffset` matters in right-to-left.** `offset` mirrors its horizontal value
in an RTL layout direction, which for a corner-hugging decoration is usually what you want — but the
alignment must mirror with it. Decide deliberately rather than by default, and check the tile in an
RTL locale, because a decoration that mirrors while its alignment does not lands in the middle.

**The background here is a gradient at an angle, not a colour**, and is drawn by a draw modifier that
needs the box size — see `angled-gradient-modifier`. Deriving its colours from the item's title, with
the same generator the coverless placeholder uses, is what makes an unloaded tile look intentional
rather than empty: `deterministic-title-placeholder-painter`.

## Verifying it

1. Every rotation, with the surrounding chain, so you can check clip order at each site:

   ```bash
   grep -rn --include='*.kt' -B3 -A2 "\.rotate(" . | grep -v '/build/'
   ```

2. The dangerous order specifically — a `clip` applied *before* a rotation on the same element:

   ```bash
   grep -rn --include='*.kt' -A2 "\.clip(" . | grep -v '/build/' \
     | grep -E "^[^:]+-[0-9]+-.*\.rotate\(|\.clip\(.*\.rotate\("
   ```

   Every hit is a site whose rotated corners are being sliced. The two alternatives do different
   jobs: `-[0-9]+-` keeps only grep's *context* lines, catching a `clip` with a `rotate` below it,
   while `\.clip\(.*\.rotate\(` catches the same order written on one line. Excluding the matched
   line matters, because `-A2` prints it too — a bare `grep "\.rotate("` after it would also report
   the *safe* single-line `.rotate(…).clip(…)`.

3. Children offset outward, each of which needs a clipping parent:

   ```bash
   grep -rn --include='*.kt' -E "\.offset\(x = [0-9]" . | grep -v '/build/'
   ```

4. By eye, and this is the test that catches the arithmetic: put the longest title you support on the
   tile and confirm the ellipsis lands clear of the tilted art, not merely clear of the 64 dp box.
   Then set the angle to 45°, where the bounding box is at its widest (`s·√2`), and confirm the
   padding was derived rather than eyeballed.
