---
name: floating-overlay-reserves-its-own-strip
description: A control floated over a scrolling column is a sibling that takes part in no measurement, so the column has to reserve the strip it covers explicitly — as a leading spacer, or as a header row whose twin spacers keep a centred title centred over the hole. Covers what the strip constant may and may not count, why every scrolling branch needs its own, and why floating is what keeps the control reachable once the page has scrolled. Use when a floating back button sits on top of the first line of content, when a centred title is off by half a button, or when a control scrolls out of reach on a long page.
---

# A floating control reserves nothing; the content must

Aligning a control inside the `Box` that also holds the page puts it *beside* the content in the
layout tree, not above it:

```kotlin
BoxWithConstraints(Modifier.fillMaxSize()) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(innerPadding)) {
        Spacer(Modifier.height(BACK_BUTTON_STRIP))   // the strip the button is drawn over
        TitleBlock()
        /* … */
    }

    // Sibling of the column: aligned, not stacked. It influences nothing below it.
    GlassIconButton(
        modifier = Modifier
            .align(Alignment.TopStart)
            .windowInsetsPadding(WindowInsets.statusBars)
            .padding(start = 12.dp, top = 8.dp)
            .size(48.dp),
        onClick = onBack,
    )
}
```

`BACK_BUTTON_STRIP` is `8.dp + 48.dp` — the button's own offset plus its size — and deliberately
**not** the status bar, because the column already carries that through `innerPadding` and the button
carries it through `windowInsetsPadding`. The strip is only the part of the button that hangs below
the inset both of them already start from.

Floating it is also what keeps it reachable: in the scrolling column it would leave the screen with
the rest of the page. A control that refracts or blurs what is behind it has a second reason — its
backdrop source has to be a sibling too, and nesting the control inside that source is a feedback
loop rather than a layout mistake.

## Traps

**"Aligned" means it influences nothing, and nothing warns you.** No measurement, no arrangement, no
scroll extent accounts for the overlay — the first line of content sits under it and looks like a
padding bug. The layout is not wrong anywhere; the reservation simply does not exist. Every floated
control needs a matching hole cut by hand in whatever it covers.

**Do not reserve it on the container.** Padding the `Box` (or the scaffold around it) moves the
overlay by the same amount, because the overlay is aligned inside that same container: the hole and
the control travel together and the collision survives. The reservation belongs to the scrolling
content — the one thing the overlay is *not* attached to.

**The strip constant is a sum, and the system inset usually is not part of it.** Write out what it
counts: the control's own size, plus the offset it is pushed down by, plus the inset **only if the
content does not already carry it**. Counting the inset in both places produces a gap exactly one
status bar tall, which is the same defect as `stacked-bars-double-consume-window-insets` in a
different costume — and it is device-dependent, so it looks fine on whatever you measured on.

**Every scrolling branch reserves its own, and only the branch the control covers.** A screen with a
narrow and a wide layout has two independent scrollers; a wide layout may have two side by side. The
control is aligned to one corner, so it covers exactly one of them — the other must **not** reserve
anything or it grows a hole with nothing in it. Step 2 below interleaves the scrollers, the
reservations and the alignment so you can pair them off; the same shape as
`guard-on-every-trigger-path`, where a condition present in some of its homes and absent in the rest
raises no error anywhere.

**A header row can be the reservation, and then it needs a twin.** Instead of a spacer, a real row of
the control's height with a leading `Spacer(Modifier.width(48.dp))` — the control's width — under
which the control floats. The row's title must then be `weight(1f)` **between two** such spacers: with
one, the title's slot starts at 48dp and runs to the row's end, so its centre is half a button
(24dp) right of the row's. Nobody sees it on a short word; a long title ellipsises asymmetrically and
looks like a text bug.

**Centring the title with `Box` + `align(Center)` fails differently.** It is the other obvious shape,
and it centres the title over the *whole* width rather than over what is left beside the control — so
a short title looks identical and a long one runs straight under the control, where the two overlap
instead of one truncating. The weighted-row-between-two-spacers version cannot do that, because the
title's slot excludes both reserved ends.

**Content passes under the control, which is a design decision, not a detail.** Once scrolled, the
reservation is gone and the page runs beneath the floating control. That is correct when the control
is small and translucent and wrong when it is opaque and the content under it matters — in which case
the answer is a pinned bar that takes part in the layout, not a bigger strip.

**The control carries its own insets, because it inherits none.** Being a sibling means it does not
receive the scaffold padding the scrolling column got: without its own
`windowInsetsPadding(WindowInsets.statusBars)` it lands under the status bar on one device class and
looks perfect on another. Two siblings **overlaid** in a Box each applying that inset do not double
it — they share a top edge rather than stacking, and doubling needs the two paddings in series along
the axis, which is what `stacked-bars-double-consume-window-insets` is about. It does mean the strip
constant has to know both of them already start below it.

**Once the reservation has scrolled away, the control sits on arbitrary content.** That is the deal
floating makes: it stays put, everything passes underneath. So it needs a background of its own —
glass, a scrim, a filled shape — chosen to stay legible over artwork, over text, over a dark row and
a light one. A bare icon that reads perfectly against the top of the page is unreadable a hundred
pixels down, and no strip arithmetic fixes that.

**Declaration order and traversal order are separate questions.** The overlay is declared after the
whole page so that it draws on top; whether assistive traversal reaches it first is decided elsewhere.
Dump the semantics tree, or run the platform's accessibility scanner, rather than assuming the drawing
order carried over — a back control that is announced after the entire page is a defect a screenshot
cannot show.

## Verifying it

```bash
# 1. Candidate screens: something scrolls AND something is corner-aligned in the same file.
grep -rln --include="*.kt" -E "verticalScroll\(|LazyColumn\(" . | grep -v "/build/" \
  | xargs grep -ln -E "align\(Alignment\.Top(Start|End)"

# 2. For one of them, interleave the scrollers, the reservations and the overlay. Read from the first
#    scroller down to the alignment line and pair them off — hits further down the file are ordinary
#    layout. A scroller with no reservation is either one the control does not cover, or one whose
#    reservation IS a header row of the control's height — twin width spacers, not a height spacer.
#    Either way, say which corner the overlay is aligned to. (`_STRIP` names the reservation here.)
grep -n -E "verticalScroll\(|LazyColumn\(|_STRIP|\.(height|width)\([0-9]+\.dp\)|align\(Alignment\.Top" \
  <that file>

# 3. Named strips across the tree. Open every hit and check its arithmetic against what it reserves.
grep -rn --include="*.kt" -E "^ *(private )?val [A-Z_]+ *= *[0-9]+(\.[0-9]+)?\.dp" . | grep -v "/build/" \
  | grep -iE "strip|bar|button"

# 4. Fixed-width spacers per file. In a header row that centres a title over a floating control they
#    come in PAIRS — an odd count in such a row is a title off by half a button.
grep -rn --include="*.kt" -E "Spacer\(Modifier\.width\([0-9]+\.dp\)\)" . | grep -v "/build/" \
  | cut -d: -f1 | sort | uniq -c | sort -rn | head -8
```

Then scroll to the bottom and back: the control must not move, and nothing may be permanently hidden
under it at rest. Check the reservation by giving the strip spacer a temporary background colour — it
should sit exactly under the control, no margin above or below — in every layout branch, and on a
device with a tall status bar, where a strip that wrongly counts the inset shows as a gap rather than
a fit. For the centred-title shape, load the longest title you have: an off-centre slot shows as
ellipsis on one side while there is still room on the other.

Related: `stacked-bars-double-consume-window-insets` (the inset the strip must not count twice),
`liquid-glass-backdrop` (why a refracting control must be a sibling of its backdrop source),
`shell-background-is-not-scheme-background` (what that backdrop source is actually painting),
`empty-state-must-keep-its-navigation` (this control has to survive a page with no content at all).
