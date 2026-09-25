---
name: lazy-item-grouping-beats-arrangement-gap
description: A lazy list's `spacedBy` arrangement applies between every pair of items and compounds with each item's own edge padding, so blocks that must read as one unit belong in ONE item carrying its own tighter spacing rather than in three items relying on the list's gap. Covers why the visible gap appears in no single constant, why an item boundary is a spacing boundary, and what to do when the group is conditional. Use when a band of dead space opens above one block, when tightening the gap for one pair moves every other pair, or before splitting a header into separate lazy items.
---

# An item boundary is a spacing boundary

A lazy list places nothing between its items unless its arrangement says so — and then it places the
same thing between all of them. A group that has to read as one unit therefore goes in one item:

```kotlin
LazyColumn(verticalArrangement = Arrangement.spacedBy(SECTION_GAP)) {   // SECTION_GAP = 32.dp
    item {
        Column {                                    // header + navigator + count = ONE unit
            PeriodHeader(...)                       // its own 24.dp bottom inset, inside the block
            Spacer(Modifier.height(8.dp))
            Column(verticalArrangement = Arrangement.spacedBy(20.dp)) {
                PeriodNavigator(...)
                HeadlineCount(...)
            }
        }
    }
    item { FirstSection(...) }
    item { SecondSection(...) }
}
```

As three items, the navigator sat `SECTION_GAP` below a header that already ends with its own 24dp
inset, so the space above it was 56dp — a number written nowhere. The arrangement is a property of
the **list**, not of an item: there is no per-item override to reach for, and lowering the constant
to fix this pair would pull every section on the page together with it.

## Traps

**The gap you see is a sum, and no line of source contains it.** It is `arrangement + the bottom
padding of the block above + the top padding of the block below`, and those three live in three
different files with three different owners — the list's constant, and each block's own idea of its
edges. Reading only the arrangement makes the rendered spacing look like a mystery; measure it, then
account for it as a sum before changing anything (step 3 lists the named constants that feed it).

**Splitting into items is a performance instinct that costs layout control.** One item per block is
the right shape for a long list of rows, because the item is the unit of composition. It is the wrong
shape for a handful of always-visible blocks at the top of a page: they are all in the viewport
together, so nothing is saved, and the split has silently handed their spacing to a constant chosen
for section-to-section distance. Put item boundaries where you want gaps.

**One owner of inter-block space, never two.** The two stable arrangements are: the list owns all of
it and no block carries its own top padding, or each block owns its own and the list adds nothing.
A shared section-header component that dropped its own top padding is what usually forces the switch
to a list arrangement — and that fix is correct everywhere except the one block that also kept an
internal inset, which is where the doubled gap comes from. Pick the owner per list and strip the
other side.

**A conditional group belongs in the same item, not in its own.** When the trio only exists in one
layout branch, folding it into the item that holds the block it belongs to keeps the item count
identical in both branches — the item exists either way and its *content* differs. Giving the
condition its own `item { }` re-opens the arrangement gap above it, in whichever branch you did not
open while checking.

**Two spacing systems on one screen is normal; knowing which is which is not optional.** The wide
branch of a page like this often puts everything into a single item holding two `Column`s, each with
its own `spacedBy` — so the list's arrangement applies between two or three items while all the
visible spacing comes from the inner columns. A gap that will not respond to the list constant is
usually being set by an inner column, and vice versa.

**An item that renders nothing still gets spaced.** `item { if (condition) Block() }` is an item
whichever way the condition falls: it measures zero tall when the block is absent, and the list still
puts its gap on *both* sides of it — one dead double gap wherever a section is hidden, growing with
every hidden section. Put the condition around the `item { }` call instead of inside it, so the
absent block is an absent item.

**Inside the merged item, use an arrangement too.** Once the group is one item, its internal spacing
has the same choice to make, and writing it as per-child `padding(top = …)` recreates the two-owner
problem one level down — each child deciding its own distance from a neighbour it cannot see. A
`Column(verticalArrangement = Arrangement.spacedBy(...))` plus, where one gap genuinely differs, a
single explicit `Spacer`, keeps every number in the group visible in one place.

**`contentPadding` is not part of this and is the one thing `spacedBy` will not do.** The arrangement
puts space *between* items only — never before the first or after the last. Space at the ends comes
from the list's `contentPadding` or from a trailing spacer item, and reaching for a bigger arrangement
value to buy room at the bottom moves every internal gap instead.

**Merging items merges their keys.** In a list that declares `key =` (and `contentType`) per item,
three items becoming one is a change to the key set, not only to the spacing: the merged block needs
its own stable key or the list loses the anchor it restores scroll position and item state from when
the data changes. Group blocks that belong together *and* live together — merging a pinned header
with a block that comes and goes buys a gap and costs an anchor.

**Negative padding to cancel a doubled gap is a trap in a lazy list.** It survives exactly as long as
the two blocks stay adjacent; the next item inserted between them inherits a negative offset written
for a neighbour it has never met. Merging the items removes the gap rather than cancelling it.

## Verifying it

```bash
# 1. Every lazy list that delegates its inter-item space to an arrangement. Each hit is a list where
#    the gap is uniform by construction — read what its items are, and whether any two of them are
#    meant to read as one block.
grep -rn --include="*.kt" -A8 -E "Lazy(Column|Row|VerticalGrid|HorizontalGrid)\(" . | grep -v "/build/" \
  | grep -E "Arrangement\.spacedBy"

# 2. Where the items are. The files at the top of this list are the ones whose layout is being
#    decided by item boundaries — a high count next to a hit from step 1 is the shape this covers.
grep -rc --include="*.kt" -E "^ *item(sIndexed)? *\{" . | grep -v "/build/" | grep -v ":0" \
  | sort -t: -k2 -rn | head -6

# 3. The named spacing constants that add up to what you measured on screen. Roll them up per file:
#    the screen carrying the most of them is the one where a rendered gap is least likely to match
#    any single constant.
grep -rn --include="*.kt" -E "^ *(private )?val [A-Z_]+ *= *[0-9]+(\.[0-9]+)?\.dp" . | grep -v "/build/" \
  | cut -d: -f1 | sort | uniq -c | sort -rn | head -5
```

Then change the list's arrangement constant by a large, obvious amount and look at the whole page:
every gap that moves is owned by the list, and every gap that does not is owned by a block. That one
edit answers "which of the two is this gap" faster than reading either. Put it back, merge the group
into one item, and check the *other* boundaries did not tighten with it — a merge removes one
arrangement gap, so the block above the group now sits at the arrangement distance from the header
rather than from the group's last row. Then open the other layout branch, if there is one, and repeat:
the branch you did not edit is where the split items usually survive.

Related: `lazy-scroll-helper-kit` (the other lazy-list arithmetic worth getting right),
`variant-layout-math-stays-in-the-variant` (when the two branches each need their own spacing maths),
`mosaic-arrangements-must-be-hole-free` (the block inside such an item that must not leave gaps of
its own).
