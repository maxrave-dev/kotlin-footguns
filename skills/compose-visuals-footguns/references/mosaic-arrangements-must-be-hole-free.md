---
name: mosaic-arrangements-must-be-hole-free
description: Build a ranked mosaic (one big tile plus smaller ones) with an arm for every possible count, so no entry is silently dropped and no arrangement leaves an empty rectangle — plus one clip around the whole block rather than one per tile. Use when a "top five" shows four, when a grid renders a visible gap at some counts, or when an early return on an "unsupported" size looks harmless.
---

# A mosaic needs an arm for every count

A shelf of equal cards gives every entry the same size, which throws away the one thing a ranked list
is about. A mosaic gives the first entry a tile two to four times the area of the rest — the factor
depends on the arm, and at exactly two entries both tiles come out the same size and the mosaic stops
encoding rank at all — so the ranking is legible before a number is read. The cost is that a mosaic
is a fixed arrangement, and a fixed arrangement has to answer for every input length — which is where
the entries go missing.

```kotlin
// adapted: the wide arrangement, whose column must stay exactly as tall as the first tile
Row(modifier.clip(shape)) {                       // ONE clip, around the whole block
    MosaicTile(items.first(), Modifier.weight(1f).aspectRatio(1f))   // half the width, square
    val rest = items.drop(1)
    if (rest.size == 1) { MosaicTile(rest.first(), Modifier.weight(1f).aspectRatio(1f)); return@Row }
    Column(Modifier.weight(1f)) {
        when (rest.size) {
            2 -> rest.forEach { MosaicTile(it, Modifier.fillMaxWidth().aspectRatio(2f)) }
            3 -> { MosaicTile(rest[0], Modifier.fillMaxWidth().aspectRatio(2f))
                   Row(Modifier.fillMaxWidth()) { rest.subList(1, 3).forEach { SquareTile(it) } } }
            else -> { Row(Modifier.fillMaxWidth()) { rest.subList(0, 2).forEach { SquareTile(it) } }
                      Row(Modifier.fillMaxWidth()) { rest.subList(2, 4).forEach { SquareTile(it) } } }
        }
    }
}
```

## Traps

**An early return on an "unsupported" count deletes an entry with no error.** The shape this replaced
was a banner followed by `if (items.size < 3) return@Column`, a row of two, then `if (items.size < 5)
return@Column`, a row of two. At four entries the second guard fired and the fourth entry was
**never drawn** — the block rendered three, correctly laid out, with nothing to indicate a fourth
existed. Every count needs an arm that renders every item it was given; "too few to fill the
arrangement" is a layout problem, not a licence to discard data.

**A tall arrangement hides the bug; a wide one exposes it.** Stacked vertically, a missing row just
makes the block shorter, which nobody can see. Put the same arm beside a tile as tall as half the
block's width and the missing row is an empty rectangle in plain sight. So the arrangement most
likely to be *correct* is the one that was hardest to build — and a silent-drop bug can survive for
as long as only the forgiving orientation ships.

**Every arm must produce the same block height, and you must derive that yourself.** In the wide
arrangement above the first tile is half the width and square, so the column beside it has to be
exactly that tall at every count: two 2:1 stripes, or a stripe over a pair of squares, or two pairs
of squares — each of those is `W/2`. The tall arrangement steps instead: 0.5 W, 1.0 W, 1.0 W, 1.5 W,
1.5 W as the count goes 1 → 5. **Do not take the height from the doc comment**; the one on this
component claims both arrangements are half as tall as they are wide, which is true of the wide one
and wrong by 3× for the tall one at five tiles. Sum the arms.

**`weight` and `aspectRatio` are what make the arms commensurate.** A tile at
`weight(1f).aspectRatio(1f)` inside a half-width column is a quarter of the block wide and a quarter
tall; a `fillMaxWidth().aspectRatio(2f)` stripe in that same column is a quarter tall too. Two
stripes therefore equal one square row, which is the entire construction. Change one weight and
every arm has to be re-derived — the layout will not complain, it will just leave a gap. Note that
this rests on `weight`'s default `fill = true`: a tile takes its whole slot, which is what makes the
widths (and so the derived heights) predictable. That same default is what pins a sibling to the far
edge in a row meant to read as one cluster — `weight-fill-false-to-center-a-cluster`.

**Clip once, around the block.** Rounding each tile individually breaks the mosaic back into
separate cards, which is precisely the shelf the mosaic exists to avoid. Tiles stay flush; only the
outer silhouette is rounded.

**The rank must survive the arrangement.** In the three-remainder arm the wide stripe goes to
`rest[0]` — rank 2 — so reading top-down still reads down the ranking. Give the stripe to the last
item instead and the biggest tile in the column sits under two smaller ones, which the eye reads as
the reverse order regardless of what the labels say.

**Height is a function of width here, so the block cannot be given a fixed height.** Every tile is
`aspectRatio` inside a `weight`, so the mosaic measures its width and derives its height. Dropping
it into a fixed-height parent either clips the last row or leaves a band under it. The wide
arrangement's constant `0.5 W` is what makes it safe to place beside another column; the tall one's
0.5/1.0/1.5 steps are not, and a two-column page has to account for that.

**A lone trailing tile spans the full width rather than sitting beside a gap.** The alternative — a
half-width tile with empty space next to it — reads as a failed load, not as a shorter list.

**Duplicated tile bodies are what let the guards hide.** Three copies of the same forty-line tile
body put a hundred lines between the two early returns, and nobody reading either one could see the
other. Collapsing them to a single `MosaicTile(image, modifier)` took this component from 308 lines
to 219 and made both guards visible on one screen. The de-duplication is not tidying; it is what
makes the bug findable.

**Guarding empty input removes the section, not just the tiles.** `items?.take(5) ?: return` at the
call site takes the heading with it, so a period with no data shows no explanation of why the block
is gone. Decide whether the empty case is "render nothing" or "render a sentence", and do it at the
section rather than inside the tile builder.

A silent early return that skips an entry is the same failure as a chart guard that skips a row —
see the `radius <= 0` case in `dont-slice-one-circle-between-unrelated-measures`. Which arrangement
is chosen belongs on window size, not on platform: `responsive-gate-size-not-platform`.

## Verifying it

Run these from the repository root. They are read-only.

1. Every arm of every arrangement. Read each hit and confirm it renders all the items in scope —
   there should be no branch whose body is shorter than its condition implies:

   ```bash
   grep -rn --include='*.kt' -E "images\.size|rest\.size|row\.size" . | grep -v '/build/'
   ```

   Expect four hits, all in the mosaic: one row-completeness test, one single-item arm, one
   single-remainder arm, and one `when` over the remainder.

2. Any size test that guards an early return out of a layout scope — the exact shape that drops
   entries:

   ```bash
   grep -rn --include='*.kt' -B3 "return@Column\|return@Row" . | grep -v '/build/' | grep -E "\.size (<|>|==|!=)"
   ```

   Expect one hit (`rest.size == 1`). Open it: that arm *renders* the remaining item before
   returning, which is what separates it from the failure above.

3. Re-derive the block height for each count. Any row where the two columns differ is an
   arrangement whose height depends on its input, which is what produces the visible hole:

   ```bash
   LC_ALL=C awk 'BEGIN{printf "n  wide       tall\n";
     for(n=1;n<=5;n++){ l=0.5; p=0.5; r=n-1; while(r>0){ p+=0.5; r-=2 }
       printf "%d  %.2f W     %.2f W\n", n, l, p } }'
   ```

   Prints `0.50 W` for the wide arrangement at every count, and `0.50 / 1.00 / 1.00 / 1.50 / 1.50`
   for the tall one.
