---
name: responsive-gate-size-not-platform
description: Gate an adaptive layout on the window's own width-versus-height, never on the platform, and flip every geometry value the gate owns in the same breath — frame sizing, content scale and scrim height. Use when a layout is right on a phone and wrong in a narrow or resized desktop window, when forcing an adaptive flag to one value breaks a different platform's screen, or when artwork swallows the whole page on a wide window.
---

# Gate on the window's shape, not on the platform

A screen that has two headers picks between them from one line, and that line reads the window:

```kotlin
val screenInfo = getScreenSizeInfo()
val isPortrait = screenInfo.wDP < screenInfo.hDP
```

"Portrait" here means *this window is taller than it is wide* — nothing about the device. The size
accessor is per-platform (window metrics on mobile, container size on desktop) but it reports the
**window**, so split-screen, a half-width desktop window and a rotated phone all move the same value
and a recomposition follows each. A platform check answers none of those.

Everything that is not a choice *between* the two layouts stays outside the branch: the palette-derived
page background and the blur source are applied to the list itself, unconditionally. Inside the branch
is the header — and, where the wide header carries its own play/shuffle cluster, where that sits.

## Traps

**One boolean answering two questions.** The gate here started life as `platform == Mobile &&
wDP < hDP` and controlled both "use the immersive treatment" and "which header". Someone forcing it
to `true` to see the wide header on desktop got the wide header *on mobile portrait too*, and the
other orientation lost its layout entirely — the same flag still answered the treatment question. The
split is the fix: the treatment applies to both orientations unconditionally, and the gate owns
exactly one decision. Before adding a condition to an adaptive flag, name every question it answers.

**`platform && shape` is the same bug wearing a shape gate.** Another screen still carries it. Its
comment opens on the device — *two columns only on a phone held upright* — then gives the real reason
in width terms: anywhere wider, two columns stretch each tile to half the window and the fixed 2:1
tile ratio makes it absurdly tall.

```kotlin
val isMobilePortrait = getPlatform() == Platform.Android && screenInfo.wDP < screenInfo.hDP
val moodGridColumns = if (isMobilePortrait) 2 else 4
```

Only the first sentence names a device, and it is the half doing no work. The code still fails the
platform half on a narrow desktop window and hands it the four-column layout the comment was written
to avoid. If the *justification* never needs the platform, the condition must not.

**The gate owns more than the branch you are looking at.** When the frame changes shape, the scaling
and the scrim have to change with it or the result is worse than the un-adapted layout:

```kotlin
// adapted: three sites in one screen, pulled together
Box(
    Modifier.fillMaxWidth().then(
        if (isPortrait) Modifier.aspectRatio(1f) else Modifier.height((screenInfo.hDP / 2).dp),
    ),
) {
    AsyncImage(contentScale = if (isPortrait) ContentScale.FillWidth else ContentScale.Crop, /* … */)
    Box(
        Modifier.fillMaxWidth().align(Alignment.BottomCenter)
            .height(if (isPortrait) (screenInfo.wDP * 0.7f).dp else (screenInfo.hDP * 0.35f).dp)
            .background(scrimBrush(pageBackground)),
    )
}
```

Each pair has its own reason. `aspectRatio(1f)` on a wide window makes a frame as tall as the window
is wide, so the artwork (or a video in it) swallows the page — hence a fraction of the viewport
height. `FillWidth` fits a square source into a square frame, but scales that same source to a *wide*
frame's width and shows only the band the frame is tall enough to hold: the **middle** band, since
`Alignment.Center` is the default, so head and feet are lost (the in-repo comment says *top* slice —
wrong band, right idea). Hence `Crop` when wide. The two scrim figures are one rule twice: 70% of the
frame's own height, which is 70% of the width while square and 35% of the viewport height once not.
Measure the wide branch off the width and the scrim outgrows the artwork it fades.

**Inside the wide branch, measure the remainder — not the column.** A later screen here was designed
to split its landscape body by each block's *natural* width: a fixed ~600dp column for blocks that
stop improving past it, the rest for blocks that keep using width. Sound reasoning, and the recorded
design did not survive contact with real window widths — a fixed column is really a claim about every
*other* width. The in-code note records the outcome: right at 1400dp, and at 986dp the remainder came
out 202dp, narrow enough to wrap a legend one letter per line. What shipped is two sibling `Column`s
at `Modifier.weight(1f)` in one `Row`. Two decisions lived in that block and only one was wrong:
*what goes in which column* — grouped by kind rather than by height, so related blocks stay together
near the top — was right and is unchanged; *how wide each is* needed measuring, and the figure to
measure is the narrowest supported window's leftover, never the widest window's column.

**Two gates that disagree about a square window.** `wDP < hDP` is strictly-taller; a collapsing-header
component here uses `hDP >= wDP`, taller-**or-square**. A square window takes different branches in
the two, and square windows are reachable on desktop by dragging. Pick one comparison, use it
everywhere.

**Chrome that floated on the artwork has nowhere to float.** In the edge-to-edge branch back, like,
search and overflow are overlays on a full-bleed image. The wide branch has a fixed artwork block on
page background, so those become a real top row and the action cluster moves beside it — which is why
the branch keeping it underneath is gated too. Move that code verbatim; each has its own view model.

**Platform checks that legitimately survive are never about layout.** Two remain in these screens,
both asking a capability question no window measurement can answer: whether the renderer supports a
particular blur path (a progressive-blur effect whose signature does not resolve against the pinned
desktop drawing backend), and whether the pointer is a mouse or a finger (click-and-drag reorder
versus long-press-then-drag). Layout is not on that list.

**Five screens carrying the same gate by hand, and counting.** The declaration is duplicated per
screen — a rule change has to land in each, and step 1 is how you find them. Same shape as
`guard-on-every-trigger-path`: a condition present in some of its homes and not others errors
nowhere.

## Verifying it

```bash
# 1. Every shape gate in the codebase, in one shot. Read the operator and the operands of each hit:
#    a `>=` next to a `<` disagrees about square windows, and an `&&` next to a platform call is
#    the contaminated gate.
grep -rn --include="*.kt" -E "\.(wDP|width) *< *[A-Za-z]+\.(hDP|height)|\.(hDP|height) *>= *[A-Za-z]+\.(wDP|width)" . | grep -v "/build/"

# 2. Every platform check left in UI code, comments excluded — 22 hits here; unscoped it returns 27,
#    the extra five being app-shell branches and a view model picking a default. Each must answer a
#    capability question (does this renderer, input device or system integration exist), never a
#    layout one. Exactly one is expected to fail that test: the contaminated gate from step 1.
find . -path "*/ui/*" -name "*.kt" -not -path "*/build/*" -exec grep -Hn -E "getPlatform\(\) *[!=]=" {} + \
  | grep -vE ":[0-9]+: *//"

# 3. Everything one screen's gate owns. Read all of the hits together: they must flip as a set.
find . -path "*/ui/screen/*" -name "*.kt" -not -path "*/build/*" -exec grep -Hn "isPortrait" {} +

# 4. Sizing inside the branches a shape gate owns — 27 hits, 9 of them fixed widths. Each fixed dp
#    is a claim about the leftover at EVERY other window size: read what shares its Row, then
#    compute the remainder at the narrowest window you support.
grep -rl --include="*.kt" "isPortrait" . | grep -v "/build/" \
  | xargs grep -n -E "\.width\([0-9]+\.dp\)|Modifier\.weight\("
```

Then resize rather than rotate, **continuously**: drag a desktop window wide-to-narrow and back,
watching the leftover column rather than the one you sized. The header must swap mid-drag, and each
branch must hold **its own** size rule. Portrait, the artwork is a square measured off the *width*,
so on any window less than twice as tall as it is wide — a 16:9 phone, a portrait tablet, most
split-screen halves — it legitimately covers more than half the viewport. Wide, it is exactly half
the viewport *height*. Only the scrim rule is shared: 70% of a frame that is `wDP` tall, 35% of a
viewport whose half *is* the frame — so a single "never past half the viewport" check fails the
portrait branch on correct code and sends you to the wrong side. Finish in split-screen at half
height: a landscape-shaped window on a portrait device, the case a platform check always gets wrong.
