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

"Portrait" here means *this window is taller than it is wide* — nothing about the device. The
size accessor behind it is per-platform (window metrics on mobile, the window's container size on
desktop) but it reports the **window**, so split-screen, a half-width desktop window and a rotated
phone all move the same value, and a recomposition follows each of them. A platform check answers
none of those.

Everything that is not a choice *between* the two layouts stays outside the branch: the page
background derived from the artwork palette and the blur source are applied to the list itself,
unconditionally. What is inside the branch is the header — and, on the screens whose wide header
carries its own copy of the play/shuffle cluster, where that cluster sits.

## Traps

**One boolean answering two questions.** The recorded history of this codebase is that the gate
started life as `platform == Mobile && wDP < hDP` and controlled both "use the immersive treatment"
and "which header". Someone forcing it to `true` to see the wide header on a desktop build got the
wide header *on mobile portrait too*, and the other orientation lost its layout entirely — because
the same flag was still answering the treatment question. The split is the fix: the treatment
applies to both orientations unconditionally, and the gate is left owning exactly one decision.
Before adding a condition to an adaptive flag, name out loud every question it currently answers.

**`platform && shape` is the same bug wearing a shape gate.** Another screen in this codebase still
carries it. Its comment opens on the device — *two columns only on a phone held upright* — and then
gives the actual reason in width terms: anywhere wider, tablet or landscape or desktop, two columns
stretch each tile to half the window, and the fixed 2:1 tile ratio makes it absurdly tall with it.

```kotlin
val isMobilePortrait = getPlatform() == Platform.Android && screenInfo.wDP < screenInfo.hDP
val moodGridColumns = if (isMobilePortrait) 2 else 4
```

Only the first sentence names a device, and it is the half that does no work — the reason given is
entirely about width. The code still fails the platform half on a narrow desktop window and hands it
the four-column layout the comment was written to avoid. If the *justification* never needs the
platform, the condition must not either.

**The gate owns more than the branch you are looking at.** When the frame changes shape, the scaling
and the scrim have to change with it or the result is worse than the un-adapted layout:

```kotlin
// adapted: three sites in one screen, pulled together
Box(
    Modifier.fillMaxWidth().then(
        if (isPortrait) Modifier.aspectRatio(1f)
        else Modifier.height((screenInfo.hDP / 2).dp),
    ),
) {
    AsyncImage(
        contentScale = if (isPortrait) ContentScale.FillWidth else ContentScale.Crop,
        /* … */
    )
    Box(
        Modifier
            .fillMaxWidth()
            .height(if (isPortrait) (screenInfo.wDP * 0.7f).dp else (screenInfo.hDP * 0.35f).dp)
            .align(Alignment.BottomCenter)
            .background(scrimBrush(pageBackground)),
    )
}
```

Each pair has its own reason. `aspectRatio(1f)` on a wide window makes a frame as tall as the window
is wide, so the artwork (or a video playing in it) swallows the page — hence a fraction of the
viewport height instead. `FillWidth` fits a square source into a square frame, but scales that same
source to a *wide* frame's width and then shows only the band of it the frame is tall enough to hold:
the **middle** band, because no alignment is passed and `Alignment.Center` is the default, so what is
lost is the head and the feet. (The in-repo comment there says *top* slice — wrong about which band,
right about the slicing.) Hence `Crop` in the wide branch. And the two scrim figures are the same
rule twice: both are 70% of the frame's own height, which is 70% of the width while the frame is
square and 35% of the viewport height once it is not. Measuring the wide branch off the width makes
the scrim taller than the artwork it is supposed to fade.

**Two gates that disagree about a square window.** `wDP < hDP` is strictly-taller; a
collapsing-header component in the same codebase uses `hDP >= wDP`, which is taller-**or-square**.
A square window takes different branches in the two, and square windows are reachable on desktop by
dragging. Pick one comparison and use it everywhere.

**Chrome that floated on the artwork has nowhere to float.** In the edge-to-edge branch the back,
like, search and overflow controls are overlays on a full-bleed image. The wide branch has a fixed
artwork block with page background around it, so those controls become a real top row — and the
action cluster that lived under the artwork moves beside it, which is why the branch that keeps it
underneath must be gated too. Move that code verbatim rather than re-deriving it; each control is
already wired to its own view model.

**Platform checks that legitimately survive are never about layout.** Two remain in these screens,
and both ask a capability question that no window measurement can answer: whether the renderer
supports a particular blur path (a progressive-blur effect whose signature does not resolve against
the pinned desktop drawing backend, so it is drawn on mobile only), and whether the pointer is a
mouse or a finger (click-and-drag reorder versus long-press-then-drag). Layout is not on that list.

**Four screens carrying the same gate by hand.** The declaration is duplicated per screen, so a
change to the rule has to land in each of them; the grep in step 1 below is how you find them all.
The same shape as `guard-on-every-trigger-path`: a condition that exists in some of its homes and
not the others produces no error anywhere.

## Verifying it

```bash
# 1. Every shape gate in the codebase, in one shot. Read the operator and the operands of each hit:
#    a `>=` next to a `<` disagrees about square windows, and an `&&` next to a platform call is
#    the contaminated gate.
grep -rn --include="*.kt" -E "\.(wDP|width) *< *[A-Za-z]+\.(hDP|height)|\.(hDP|height) *>= *[A-Za-z]+\.(wDP|width)" . | grep -v "/build/"

# 2. Every platform check left in UI code, comments excluded — 17 hits here. Each must answer a
#    capability question — does this renderer, this input device, this system integration exist —
#    never a layout one; exactly one hit is expected to fail that test, the contaminated gate above.
#    Both filters earn their keep: unscoped the same grep returns 21, the extra four being a view
#    model picking a default, two app-shell branches, and a commented-out `if`.
find . -path "*/ui/*" -name "*.kt" -not -path "*/build/*" -exec grep -Hn -E "getPlatform\(\) *[!=]=" {} + \
  | grep -vE ":[0-9]+: *//"

# 3. Everything one screen's gate owns. Read all of the hits together: they must flip as a set.
find . -path "*/ui/screen/*" -name "*.kt" -not -path "*/build/*" -exec grep -Hn "isPortrait" {} +
```

Then resize rather than rotate. Drag a desktop window from wide to narrow and back: the header must
swap mid-drag, and each branch must hold **its own** size rule. Portrait, the artwork is a square
measured off the *width*, so its height is `wDP` and on any window less than twice as tall as it is
wide — a 16:9 phone, a portrait tablet, most split-screen halves — it legitimately covers more than
half the viewport. Wide, it is exactly half the viewport *height* and must never be measured off the
width again. Only the scrim rule is shared: it stays shorter than the artwork it fades in both
branches, at 70% of a frame that is `wDP` tall and 35% of a viewport whose half *is* the frame. A
single "never past half the viewport" check fails the portrait branch on correct code, and sends you
to fix the wrong side. Put the phone in split-screen at half height for the same
reason — that is a landscape-shaped window on a portrait device, and it is the case a platform check
gets wrong every time.
