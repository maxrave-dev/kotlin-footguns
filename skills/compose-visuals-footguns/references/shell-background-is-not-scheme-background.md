---
name: shell-background-is-not-scheme-background
description: The moment an app shell paints its content panels in anything other than colorScheme.background, every gradient, scrim and fade whose tail converges on colorScheme.background ends on a hard seam — the decoration is still correct, its destination colour is just no longer on screen. Covers resolving one page-background value and handing it to every decoration, the two valid answers (aim at the shell colour, or paint your own ground), and sizing a decoration with matchParentSize over the content it decorates rather than a constant measured on one form factor. Use when a gradient stops mid-screen with a visible edge, when a fade looks right on a phone and wrong in a desktop window, or when adding a window chrome breaks screens that were never touched.
---

# The shell's background is not the scheme's background

A desktop shell is usually a window colour with rounded panels floating on it. The panel is not
`colorScheme.background` — it is one shade back toward the middle, so it reads as raised:

```kotlin
// adapted — resolved INSIDE the theme, so MaterialTheme already holds the resolved scheme
val isLight = MaterialTheme.colorScheme.background.luminance() > 0.5f
val windowColor = if (isLight) Color(0xFFFFFFFF) else Color(0xFF000000)   // the extreme
val panelColor  = if (isLight) colorScheme.surfaceContainer else Color(0xFF121212)  // one step back

Scaffold(containerColor = if (isDesktopShell) windowColor else colorScheme.background) { … }
// … and the content area, deeper in: .padding(8.dp).clip(RoundedCornerShape(12.dp)).background(panelColor)
```

That is one commit. The arc worth learning is what came after it, and it is not the arc you would
guess. **Exactly one later commit repaired a decoration converging on the old colour**: one screen's
list-header gradient, together with a translucent button beside it whose blur source was still seeded
with the scheme background and so drew as a grey coin over the panel. That screen was the only one
that pre-dated the shell; nothing in the shell's diff named it, and it had not broken on the platform
it was written on. Two more decorations of the same kind exist here — a shared glow layer and a
second screen's copy of this same recipe — and both were **authored afterwards, already aiming at the
panel colour**, in one commit whose diff adds the resolved value and never removes a converging tail.

So the bill is one-time on what already exists, and after that a question every new decoration has to
answer for good. The second half is the expensive one: nothing enforces it, and the only reason those
two were born correct is that a human had just paid the first half and remembered.

## Traps

**The seam is not a bug in the gradient.** A two-stop gradient from a tone to `colorScheme.background`
is doing exactly what it says; the failure is that nothing paints `colorScheme.background` behind it
any more, so the tail lands on a colour that differs from its neighbour by one step of lightness and
draws a crisp horizontal line. Nothing errors, nothing logs, and on the platform without the shell
it still looks perfect — which is why it reads as "the desktop build has a weird line on Home".

**There are exactly two correct answers, and picking neither is the seam.** Either aim the tail at
what the shell actually paints, or paint your own opaque ground and aim at that. Both are live here:
the pages that let the panel show through resolve a `pageBackground` and hand it to the gradient
*and* to the scrim; the pages that draw their own full-size background box aim at that box's colour
instead. What you must not do is aim at the scheme while letting the shell's panel show.

**Resolve it once, hand it in — the current tree is the cautionary example.** Three files carry a
character-identical copy of the same six-line `pageBackground` expression, and a fourth (the shell)
computes the same value under a different name. That drifts on the next edit: the fix is one function
or one CompositionLocal (`semantic-color-tokens-compositionlocal` is the shape), and the smell is the
decoration asking "which platform am I on?" at all — a page-background token would answer without
the question.

**The light/dark test must be the same test everywhere.** All four sites here ask
`background.luminance() > 0.5f` rather than reading a theme flag, and that only works because it is
literally the same expression. Two decorations using two different tests (one luminance, one
`isSystemInDarkTheme()`, one a stored mode string) will disagree on exactly the configurations that
are hardest to check — see `force-dark-immersive-subtree`, where a forced-dark subtree makes
"ask the system" the wrong question outright.

**Resolve inside the theme, never outside it.** The panel colour is derived from
`MaterialTheme.colorScheme` (`surfaceContainer` on light), so it has to be computed under the theme
that resolved that scheme. Computed above it you get the framework default —
`chrome-drawn-outside-the-theme-scope` is that failure in full.

**Size a decoration with `matchParentSize()` over the thing it decorates, not with a constant.** A
`height(300.dp)` behind the first list item is the height of that item *on a phone*. In a wide window
the item is taller, the gradient stops partway down it, and everything below falls back to the flat
colour — the same hard seam, from the other direction. `matchParentSize()` takes part in no
measurement, so it cannot inflate the item it is sizing to; the bottom scrim then always lands on the
item's own edge. A constant is only ever right for a decoration that is genuinely fixed-height, like
a top glow that must not grow with its page.

**Three colours are in play, not two.** The window, the panel the shell floats on it, and the
scheme's own background — plus a fourth whenever a screen paints its own opaque ground. A decoration
author has to answer "what is directly behind *me*", and on a shell that answer is almost never the
scheme. Name the resolved value `pageBackground` rather than `background` for exactly that reason.

**Resolve the pair together or it inverts in one theme.** The window takes the extreme and the panel
steps one shade back toward the middle, in *both* themes; take one from a constant and the other from
the scheme and the two land on the same side in one of them. The panel dissolving into the window
arrives as "the desktop layout lost its cards", which does not sound like a colour bug at all.

**An app bar's default container colour paints over the only part that carries colour.** These
decorations put their strongest tone in the top ~180 dp, which is exactly where a top bar sits. A bar
left on `TopAppBarDefaults.topAppBarColors()` draws an opaque strip across it and the decoration
looks like it starts too low. Transparent container, and let the bar frost instead.

**Adding a shell is a change to every screen, and the diff will not say so.** Nothing in the
shell commit references the screens it breaks. Before shipping one, grep the tree for decorations
that terminate on the scheme background and settle each one; afterwards, treat "gradient looks wrong
on <platform>" reports as this bug until proven otherwise.

## Verifying it

```bash
# 1. Every copy of the resolved page background. More than one is drift waiting to happen; the
#    bodies must be identical, and the light/dark test inside them must be the same expression.
grep -rn -A5 --include='*.kt' 'val pageBackground =' . | grep -v '/build/'
```

→ observed: three character-identical copies (a shared glow component and two screens), each
`if (desktop) { if (light) surfaceContainer else <panel> } else { background }`. The shell computes
the same value a fourth time under its own name.

```bash
# 2. Every decoration and what its tail converges on. Each hit must end either on the resolved
#    page background, or on a colour the same composable paints itself.
grep -rn --include='*.kt' 'angledGradientBackground(listOf(' . | grep -v '/build/'
```

→ observed: five gradients. Three end on `pageBackground` (the shell-aware answer); two end on a
local `bg` that the same screen paints as a full-size opaque box first (the paint-your-own-ground
answer). A sixth ending on `MaterialTheme.colorScheme.background` with no such box would be the bug.

```bash
# 3. Decorations sized to their content rather than to a guess.
grep -rn --include='*.kt' 'matchParentSize()' . | grep -v '/build/'
```

→ observed: the list-header gradient, the ground boxes on the two self-grounded screens, and a
handful of full-bleed overlays. A `height(<constant>.dp)` behind a variable-height item is the
form-factor bug; a constant on a fixed-height layer is fine.

4. By eye, and it takes both form factors because each one hides the other's version: open the app
   narrow and wide, and look at the *boundary* where each decoration ends rather than at its bright
   end. Then temporarily set the shell's panel colour to something violent — the seam becomes a
   stripe and every decoration still aimed at the old colour announces itself at once.
