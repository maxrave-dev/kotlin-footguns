---
name: weight-fill-false-to-center-a-cluster
description: A weighted child occupies its whole slot even when its content measures narrower, which pins the sibling beside it to the far edge; `weight(1f, fill = false)` releases the unused width back to the row's arrangement so child, gap and sibling read as one cluster. Covers why the tell is the sibling rather than the weighted child, why the fix is two edits and not one, and why dropping the weight instead is a different layout. Use when a bar looks centred at one content size and lopsided at another, when a button clings to the screen edge with a hole beside it, or when a trailing label sits far from the text it belongs to.
---

# Release the weighted slot to centre a cluster

A row holding a sized-by-content block, a gap and a fixed button, meant to read as one cluster:

```kotlin
Row(
    horizontalArrangement = Arrangement.Center,
    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
) {
    BoxWithConstraints(Modifier.weight(1f, fill = false)) {
        // caps each item at a maximum width, so with few items it draws narrower than maxWidth
        TabCapsule(availableWidth = maxWidth, tabs = tabs)
    }
    Spacer(Modifier.size(12.dp))
    Box(Modifier.size(56.dp)) { SearchButton() }
}
```

The measure pass is what matters. A `Row` measures its **unweighted** children first — here the 12dp
spacer and the 56dp button — then divides what is left into slots by weight. The weighted child is
measured against its slot with `minWidth = slotWidth` when `fill` is true (its default) and
`minWidth = 0` when it is false. So `fill` is not "may this child stretch its content"; it is whether
the child is *forced to report the slot as its own size*. Filled, the children sum to exactly the
row's width, the arrangement has nothing left to place, and `Arrangement.Center` is a no-op: the
button sits at the edge with a hole beside it. Released, the capsule reports its content width and
the leftover becomes free space the arrangement splits — half before the cluster, half after.

## Traps

**The child that is wrong looks right; the sibling is the tell.** The weighted child renders its
content correctly at its own width — it just occupies more slot than it drew. Nothing about it is
inspectable in isolation: its content is the size it asked for, its padding is what you wrote. What
is visibly wrong is the *neighbour*, standing at the far edge of a row whose contents are nowhere
near it. Read a suspicious gap as a claim made by the widget on the other side of it.

**One edit is not the fix.** `fill = false` only releases the space; the arrangement decides where it
goes. Under the default `Arrangement.Start` the freed width collects **after** the last child, which
is exactly right when a trailing label should sit next to its text and useless when the group is
meant to be centred. The two lines change together — and a release with no arrangement line above it
is relying on `Start`, which is why step 2 below prints them as a pair.

**A filled weighted child also disables `SpaceBetween` and `SpaceAround`.** Same arithmetic: the
children sum to the row's width, so there is no free space to distribute and the two ends sit at the
extremes whatever the content is. A row that pairs `SpaceBetween` with a weighted group is describing
an intent that only takes effect once that group stops filling.

**It is a no-op at the size you designed and a bug at the size you never opened.** The released width
is `slot − content`, which is zero whenever the content genuinely fills its budget: a full set of
tabs, a long title, a long device label all look identical under either setting. It appears only in
the *narrow-content* configuration — a flag off so two entries are gone, a one-word value. Resizing
the window will not reproduce it; changing the content will.

**Dropping the weight is a different layout, not a simpler one.** "It should just wrap, so remove the
weight" moves the child into the unweighted pass, where children are measured **in declaration order**
against whatever earlier ones left. A long text declared before an optional trailing badge then takes
the full width and the badge is measured against nothing — the overflow the weight was preventing.
Weighted-and-released keeps the child last in line, able to claim only what the fixed siblings left,
while still shrinking below that. The two differ exactly when the content is long, which is the
opposite end from where `fill` shows up.

**A weighted child cannot push an unweighted sibling off the end.** If something *is* falling off,
this modifier is not the cure: either both children carry a weight, or the row is being measured
against an unbounded width — inside a horizontal scroll, or a parent that wraps its content — where
weights have no remainder to divide. Establish which of the two before reaching for `fill`.

**The budget and the size are two different numbers, and a self-capping child needs both.** Under
`fill = false` a `BoxWithConstraints` still reports the **full slot** as `maxWidth`; only the minimum
dropped. That is what lets a child compute "each item gets `maxWidth / count`, capped" and then hand
the unspent remainder back. Sizing that calculation off the box's own width instead would feed the
cap its own output.

**Content that fills its own maximum cancels the release.** The child is now free to be narrow, not
obliged to be: anything inside it calling `fillMaxWidth()`, or a `Row` with `Modifier.fillMaxWidth()`
one level down, expands straight back to the slot and the row looks exactly as it did before the
edit. The release is only meaningful above content that wraps or caps itself — check the child's own
modifier chain before concluding the setting did not work.

**Released width goes to the arrangement, not to the other weighted child.** Slots are computed from
the remainder *before* any weighted child is measured, so a row with two weighted children does not
hand one of them what the other declined; the unclaimed width stays free space. Anyone reasoning from
CSS flex intuition expects the sibling to grow into it, and it does not. The vertical case is the
same modifier with the same rule — a released weighted `Column` child stops pinning the block below
it to the bottom of the screen.

**Several sites in one release window means the default is the problem, not the screen.** Step 3
prints every commit that introduced the modifier anywhere. Read the dates and the paths together:
hits scattered over months are ordinary, several inside one window across unrelated screens mean the
layouts being written now all want a released slot — and so will the next one.

## Verifying it

```bash
# 1. Weighted children against released ones. The first is a large number in any Compose codebase,
#    the second a short list — read every hit in it and name the sibling it is making room for.
grep -rn --include="*.kt" -E "\.weight\(" . | grep -v "/build/" | wc -l
grep -rn --include="*.kt" "weight(1f, fill = false)" . | grep -v "/build/"

# 2. Each release next to the arrangement of the row it sits in. A hit preceded by an
#    `Arrangement.Center` line is a centred cluster; a hit that prints alone is relying on Start —
#    correct for a trailing label, wrong for anything meant to be centred. Keep the window wide: a
#    row's arrangement sits above ALL its children, which can be thirty lines up, and at -B10 a
#    correctly centred cluster prints alone and reads as a defect.
grep -rn --include="*.kt" -B30 "weight(1f, fill = false)" . | grep -v "/build/" \
  | grep -E "horizontalArrangement|verticalArrangement|weight\(1f, fill = false\)"

# 3. When each site arrived. Several inside one release window, in unrelated files, is the signal.
git log -S'fill = false' --format='%h %ad %s' --date=short -- '*.kt'
```

Then shrink the **content**, not the window: turn off whatever gates an item so the group has two
entries instead of four, or feed the field a one-word value. Filled, the neighbour stays welded to
the edge and the gap beside it grows as the content shrinks — that inverse relationship is the
confirmation, since a correctly centred cluster moves its neighbour inward instead. Check both ends:
at full content the two settings are indistinguishable, so a screenshot taken there proves nothing
either way. Then repeat with the longest value you can produce, which is where the "just drop the
weight" variant fails and this one does not.

Related: `nav-tab-registration-drift` (the item count this row's content depends on is itself
conditional, and changing it is what exposes a filled slot), `responsive-gate-size-not-platform` (the
other half of an adaptive row — the arrangement answers for content size, the gate for window shape).
