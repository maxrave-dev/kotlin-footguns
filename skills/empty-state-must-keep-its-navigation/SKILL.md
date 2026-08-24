---
name: empty-state-must-keep-its-navigation
description: Replace a populated header with an empty-state message without deleting the controls that header owned — re-supply them only in the branch that owned them, order the loading branch above the empty one, and stop reserving the artwork's height for a line of text. Use when a user reaches an empty period, filter or search result and cannot get back out, when an empty message flashes on every reload, or when the same control renders twice.
---

# An empty state inherits the container's duties

A header composable is rarely just a header. It usually also carries the controls that change what
the screen is showing — a period navigator, a filter chip row, a sort control. Swapping the whole
thing for "nothing here" therefore removes the only way to reach a state that *does* have something,
and the user is parked.

```kotlin
when {
    topItems is Resource.Loading -> LoadingHeader(headerHeight)   // FIRST, always
    topItem == null              -> EmptyPeriodHeader(uiState, isPortrait, onStep)
    isPortrait                   -> PortraitHeader(topItem, headerHeight, …)
    else                         -> LandscapeHeader(uiState, topItem, onStep, …)
}
```

```kotlin
// inside EmptyPeriodHeader: re-supply the navigator ONLY where the header owned it
if (!isPortrait) {
    Spacer(Modifier.height(20.dp))
    PeriodNavigator(uiState, onStep, 0.dp)
}
```

## Traps

**Take an inventory of what the replaced container owned before replacing it.** The wide arrangement
keeps the navigator inside its header; the tall one renders it as a separate item further down the
list. Substituting an empty-state header therefore deletes the navigator in one arrangement and not
in the other — the same edit, two different bugs, and only one of them reproducible on the device
you happen to be holding.

**Re-supplying it unconditionally is the opposite bug.** Add the control to the empty state without
the orientation test and the tall arrangement renders it **twice**: once inside the empty header and
once as the list item that was always there. The condition is not defensive noise; it mirrors the
ownership split exactly, so it has to be re-checked whenever either arrangement moves the control.

**Order the loading branch above the empty branch.** Both are usually expressed as "no data yet", and
`data == null` is true during a load. With the branches the other way round, every step to a new
period flashes "this period is empty" before the rows arrive — and users then report an emptiness
bug that does not exist. Loading first is a structural fix; an `isLoading &&` bolted onto the empty
condition is the same thing said badly.

**An empty state has two causes and two different recoveries.** "Nothing here yet — go and do
something" is the right sentence only for a user who has never produced any data. Once they have stepped to
another window it is simply false — what they need to know is that *this* window is empty and the
arrows lead elsewhere. Branch the message on the offset (or on whether any data exists at all), not
on the emptiness of the current query.

**Do not reserve the artwork's height for a line of text.** The populated header takes a fraction of
the window (40% here) because an image fills it. The empty branch inherits that number by accident,
and the result is a dead band with a sentence floating in it and the only actionable control pushed
below. Give the empty branch its own bottom inset — a fixed 32dp here — chosen for text.

**Floating siblings still occupy the top of an empty screen.** Back buttons and pickers positioned
over the header are siblings of the list, not children of it, so they keep their place when the
header is swapped. Anything the empty branch draws above their bottom edge lands underneath them.
The populated branch never showed this, because an image is exactly what glass controls are designed
to float over; a line of text is not.

**The reservation for that strip must be one number, not two spellings of it.** One branch reserves
it as a named `TOP_STRIP = 80.dp`; the other spells it as `vertical = 16.dp` plus `Spacer(48.dp)`
plus `Spacer(16.dp)`. Both are 16 + 48 + 16, and a change to the button's 48dp size updates neither
of them. A constant referenced from exactly one place is the tell.

**Alignment is a property of the branch, not of the screen.** The empty branch is reached from both
arrangements, so every inset it applies has to be conditional too — centred in the tall one, leading
in the wide one, and at different horizontal insets in each. A single unconditional padding value is
right for one arrangement and visibly wrong in the other.

**Line the empty text up with the body, not with the header.** In the wide arrangement the sections
below sit at the outer gutter *plus* their own content inset; text placed at only the gutter misses
by the inset and reads as broken beside the first section heading. Two additions, not one.

**One period, two emptiness sources, is a screen that can disagree with itself.** The header here
tests the top-items query while every section below tests the aggregate snapshot. They come from the
same events over the same window so they agree in practice — but they are separate asynchronous
calls, so during a step one can land before the other. Deriving both from one snapshot removes the
window entirely: `one-snapshot-per-period-not-many-flows`.

Which arrangement is in play must be decided by window size, not by platform —
`responsive-gate-size-not-platform`. And an empty state that hides *itself* is the failure in
`partial-chart-must-say-so`: the case that most needs an explanation is the one rendering nothing.

## Verifying it

Run these from the repository root. They are read-only.

1. Every place the navigation control is instantiated. One per branch that owns it, plus the
   definition — a count lower than the number of header branches means some branch has no way out:

   ```bash
   grep -rn --include='*.kt' "PeriodNavigator(" . | grep -v '/build/'
   ```

   Expect three call sites (tall arrangement's list item, empty branch, wide arrangement's header)
   and one definition.

2. Branch order inside the header's `when`. Within a file, the loading label must carry a lower line
   number than the null label; unrelated `== null ->` branches in other files also match:

   ```bash
   grep -rn --include='*.kt' -E "^ +[A-Za-z]+ is [A-Za-z.]*Loading ->|^ +[A-Za-z]+ == null ->" . | grep -v '/build/'
   ```

3. The conditional re-supply, and the strip constant that only one branch uses:

   ```bash
   grep -rn --include='*.kt' -B2 "PeriodNavigator(" . | grep -v '/build/' | grep -E "if \(|isPortrait"
   grep -rn --include='*.kt' "TOP_STRIP" . | grep -v '/build/'
   ```

   The first prints the single `if (!isPortrait)` guard; the second prints a definition and exactly
   one use — the other branch is spelling the same reservation out by hand.

4. By hand: step back to a window with no data in **both** orientations. Confirm the arrows are
   present in each, appear once, and still step; then step forward again and confirm no empty
   message flashes while the rows load.
