---
name: stacked-bars-double-consume-window-insets
description: Inset consumption travels to a composable's descendants and never to its siblings, so two inset-aware bars stacked in one column each reserve the system bar and open a band of dead space exactly one bar tall. Covers parameterising a bar's `windowInsets` with the framework default, deciding once who consumes, and why the same component must keep the default at its overlay call sites. Use when a strip of empty space appears between two bars, when it only shows in one mode of a screen, or when a bar's leading icon is clipped in landscape after you zeroed its insets.
---

# Stacked bars each reserve the system bar

A bar that can be used two ways takes its insets as a parameter, defaulted to the framework value:

```kotlin
@Composable
fun SelectionTopAppBar(
    state: SelectionState,
    /* … */
    // Defaults to the status-bar inset, like any top bar. Pass WindowInsets(0) when this bar is
    // STACKED below something that already consumed that inset.
    windowInsets: WindowInsets = TopAppBarDefaults.windowInsets,
) {
    TopAppBar(windowInsets = windowInsets, /* … */)
}
```

`Modifier.windowInsetsPadding(insets)` — which every inset-aware component applies internally — pads
by the insets **and consumes them for its own descendants**. Consumption is a parent-to-child
relationship; it does not travel sideways. Two bars that are siblings in a `Column` therefore each
read the full, unconsumed inset and each pad by it. The first pushes itself clear of the status bar;
the second pushes itself clear of the status bar *again*, from a position already below it, and what
is left between them is a band exactly one status bar tall.

## Traps

**The component does not decide; the parent's layout does.** The same bar is correct with the default
on one screen and correct with zero on the next, and nothing inside it can tell which. Stacked as a
sibling **below** another bar in a Column: zero. Drawn in a `Box` **over** the screen's own bar,
replacing it while a mode is active: the default, because it is then the only thing at that position
and nothing above it reserved anything. Grep will not separate these — step 2 lists the call sites,
and each has to be read for the container it sits in.

**Two right answers, and mixing them reopens the band.** Either the container consumes once
(`Modifier.windowInsetsPadding(...)` on the Column, every stacked child passed zero) or the first
child owns it (the top bar keeps the default, everything stacked under it passes zero). Both work;
what fails is doing one for the container and forgetting a child, which is the original defect with
an extra step in front of it. Record which shape a screen uses — the second call site gets added by
someone who cannot see the first.

**Default the new parameter to the framework value, never to zero.** Adding
`windowInsets: WindowInsets = TopAppBarDefaults.windowInsets` is a no-op for every existing caller,
which is what makes it safe to add to a component already used on a dozen screens. Defaulting it to
`WindowInsets(0)` silently removes the inset from every overlay call site — bars that were correct
now sit under the status bar, in a change that looks like it touched only the two screens you edited.

**Zeroing the parameter drops more than the top.** A top bar's framework default covers the
horizontal system-bar sides as well as the top. Replace it with `WindowInsets(0)` and the bar also
loses its landscape side inset, so on a device with a cutout the leading icon slides under it.
Whatever consumes once for the stack has to carry those sides too, or the stacked children need a
horizontal-only inset rather than a flat zero.

**It hides in whichever mode is conditional.** A selection bar wrapped in
`AnimatedVisibility(selectionActive)` only stacks while selection is on, so the band exists in a mode
nobody screenshots — and on the screens where the same component *replaces* a bar rather than
stacking under one, the identical code is fine. The overlap of "second bar visible" and "stacked, not
overlaid" is the only configuration that shows it.

**Measure the gap before naming it.** Dead space between two bars has several possible parents: a
`spacedBy` arrangement, a padding constant, a stray `Spacer`. This one is identifiable — its height
equals the status bar exactly, so it changes with the device, grows on a tall-status-bar phone, and
vanishes on a desktop window where that inset is zero. A gap that survives on a window with no system
bars is not this.

**Never subtract it back.** A negative offset or a hardcoded `-24.dp` on the lower bar cancels the
doubled inset on the one device it was measured on and is wrong on every other, plus in landscape,
plus in split-screen. The inset is a runtime value; the only correct edit is to stop reserving it
twice.

**Chained on one element they see each other; placed on two siblings they do not.** This is the whole
rule in one comparison. `Modifier.navigationBarsPadding().imePadding()` on a single element behaves,
because a modifier chain is a parent-to-child chain and the second node sees what the first consumed.
Move those two onto two children of a Column and each applies in full. When a gap appears, the first
question is not "which inset" but "are these two paddings in series along the axis" — only stacked
siblings sum; a parent-child chain consumes, and two siblings *overlaid* in a Box share an edge.

**A scaffold's `PaddingValues` reserves without consuming.** `Modifier.padding(innerPadding)` is
ordinary padding: it makes room and tells nothing downstream, so a bar inside it that keeps its
default insets reserves the same space a second time — the identical band, arrived at from a
different direction. The pairing is `Modifier.consumeWindowInsets(innerPadding)` alongside the
padding, or handing the children zero explicitly.

**An explicit zero can be redundant and still worth writing.** Under a container that already
consumed, a child routing its insets through `windowInsetsPadding` resolves them to zero on its own,
so passing zero changes nothing there. It still belongs at the call site: it survives a refactor that
moves the consumption, and it is the only thing that helps a child which reads a raw
`WindowInsets.statusBars` value, since a raw read ignores consumption entirely.

## Verifying it

```bash
# 1. Every inset an inset-aware component is handed or defaults to. Read the shape of each: a
#    parameter declaration is a component that can be stacked, an argument is a decision someone
#    made. Note the `[:=]` — a declaration reads `windowInsets: WindowInsets = …`, so a regex closed
#    on `=` matches the arguments and none of the components that can be stacked.
grep -rn --include="*.kt" -E "windowInsets *[:=]" . | grep -v "/build/"

# 2. Every zero — note the open paren, since `WindowInsets(0)` and `WindowInsets(0, 0, 0, 0)` are
#    the same argument and a regex closed on `(0)` silently misses most of them. Not every hit is a
#    stacked bar: a sheet or dialog zeroes because it does its own inset handling. The ones to read
#    are the bars, and each must sit under something that consumed the inset once.
grep -rn --include="*.kt" -E "windowInsets = WindowInsets\(0" . | grep -v "/build/"

# 3. Who consumes at all. Compare against step 1: consumption is what makes a zero correct, so a
#    screen passing zeros with nothing from this list above them is mis-stacked.
grep -rn --include="*.kt" -E "windowInsetsPadding\(|consumeWindowInsets\(" . | grep -v "/build/"

# 4. Screens holding more than one bar — the candidate list. For each, read whether the bars are
#    siblings in a Column (stacked: all but one pass zero) or in a Box (overlay: all keep the default).
grep -rn --include="*.kt" -E "^ *[A-Za-z]*(TopAppBar|SearchBar|BottomAppBar)\(" . | grep -v "/build/" \
  | cut -d: -f1 | sort | uniq -c | sort -rn | awk '$1 > 1'
```

Then put the screen into the mode that stacks the bars, on a device with a visible status bar, and
compare the gap between them against the status bar itself — a phone with a tall cutout makes a
correct build look unchanged and a doubled one obviously wrong. Rotate to landscape while stacked:
the horizontal sides are the half people forget, and a leading icon sliding under a cutout is a zero
that should have been a horizontal-only inset. Finally run the same screen where that inset is zero —
a desktop window, or a fullscreen mode with the bars hidden — and confirm the layout is identical in
both builds, which is what proves the band was the inset and not a padding constant.

Related: `selection-mode-state-holder` (the holder behind a bar that appears and disappears),
`responsive-gate-size-not-platform` (the other reason one screen renders two different bar
arrangements).
