---
name: touch-indication-bounds-and-alpha
description: Soften an app-wide touch ripple by alpha alone and give it the right bounds — the colour derives from the local content colour and stays correct inside a forced-scheme subtree, while pinning one paints darker than a near-black surface. Covers why the theme's configuration reaches a bare Modifier.clickable, why .clip(shape) must come before .clickable, why a card and its clip need one shape value, why two clickable modifiers must never stack, and the deprecated constructor that is the only way to set alpha. Use when a tap on a rounded item flashes a square, when the ripple reads as a sooty smudge on a dark theme, or when a long-pressable item ripples twice.
---

# Ripple: one alpha lever, and bounds you owe by hand

The theme publishes one configuration and every touchable surface picks it up. Two things are
worth changing there, and only one of them is safe to change.

```kotlin
// adapted — provided once at the top of the theme, alongside the colour scheme
CompositionLocalProvider(
    LocalRippleConfiguration provides SoftRippleConfiguration,
    LocalContentColor provides colorScheme.onSurfaceVariant,
    …
) { content() }

// Colour deliberately omitted: it defaults to unspecified, which is what makes the ripple
// keep deriving from LocalContentColor. Alpha is the only lever pulled here — each value is
// roughly 40% of the stock set (0.16 / 0.10 / 0.08 / 0.10).
@Suppress("DEPRECATION")
private val SoftRippleConfiguration = RippleConfiguration(
    rippleAlpha = RippleAlpha(
        draggedAlpha = 0.06f, focusedAlpha = 0.04f, hoveredAlpha = 0.03f, pressedAlpha = 0.04f,
    ),
)
```

## Traps

**Never pin the colour to "the right grey".** The resolution order is: an explicit colour on the
indication, else the configuration's colour, else the local content colour. Leaving the first two
unspecified is not laziness — it is what keeps the ripple *contrasting* rather than *matching*. On
a dark theme the content colour is light and the ripple lifts; on a light theme it is dark and the
ripple settles; inside a subtree that forces the opposite scheme (an immersive page that stays dark
under a light app theme) it follows that subtree, because the fallback is a composition local and
the subtree already provided its own. Hard-code a dark grey and the tap paints *darker* than a
near-black surface — a sooty smudge where a highlight belonged, and it is worst exactly on the
screens that forced their own scheme.

**Alpha is the only lever, and it is on a deprecation path with no replacement that keeps it.** In
this artifact family the constructor that takes an alpha set is deprecated, the two non-deprecated
constructors take a colour and a focus style and drop alpha entirely, the class has no `copy()`,
and the defaults object's alpha member carries the same deprecation. Suppress the warning and move
on — there is nothing to migrate to yet. Do not "work around" it by pinning a lower-alpha colour
instead: that is the previous trap wearing a disguise, because a colour with alpha still overrides
the content-colour fall-through.

**`.clip(shape)` must come before `.clickable`.** Indication is drawn by a node in the chain, and a
clip only bounds what comes *after* it. `Modifier.clickable{}.clip(shape)` gives a rounded item a
rectangular flash that overhangs its own corners; `Modifier.clip(shape).clickable{}` bounds it. On
a grid of rounded cards this is the single most visible tap defect, and it never appears in a
screenshot — only under a finger.

**One shape value for a card and the clip around it, or the more aggressive rounding silently
wins.** A clip on the container's modifier wraps the container's own background draw, so if the
clip rounds harder than the shape you passed the component, the clip is what you see and the
component's `shape` argument is dead code. Bind the shape to a local and use that local in both
places — especially where the shape is conditional (a capsule under one setting, a rounded
rectangle under another): two conditionals drift apart on the next edit.

**Do not stack `.clickable` and `.combinedClickable`.** Both install indication and both install
click semantics, so you get two ripples on one tap, doubled accessibility actions, and a long-press
that also fires the short-press handler. `combinedClickable` already takes `onClick`; if you need
long-press, that is the only one you keep.

**This reaches bare `Modifier.clickable`, not just Material components.** The theme provides
`ripple()` as the local indication, and `clickable` without an explicit indication resolves that
local — so a hand-rolled row built from a `Box` and a `clickable` picks up the app-wide
configuration with nothing added. That is also why a stray `indication = null` or a locally
provided indication is worth grepping for: those are the only places the app-wide setting does not
reach.

**Adding a clip to make the ripple behave changes the drawing, not only the touch feedback.** A
`.clip` inserted purely to bound a ripple also clips the content — an overflowing badge, a shadow,
a decorative element drawn past the edge. Check the item still looks right before assuming the clip
was free; if it is not free, see `draw-outside-bounds-particle-modifier` for what a clip costs the
things drawn after it.

**A decorated surface can have its own press feedback on top of this one.** A refracting-glass
button, for instance, scales and glows under the pointer while the ripple still runs underneath —
two responses to one press, and the wrapper's gesture recogniser can swallow the click outright if
it consumes. `liquid-glass-backdrop` covers keeping that recogniser observe-only; decide there
whether the surface keeps its ripple or suppresses it.

## Verifying it

The first two read the resolved artifact out of the dependency cache — no build needed:

```bash
M3=$(find ~/.gradle/caches -name 'material3-desktop-*.jar' | head -1)

# 1. the colour fall-through, in order: explicit -> configuration -> local content colour
javap -c -p -classpath "$M3" \
  'androidx.compose.material3.DelegatingThemeAwareRippleNode$attachNewRipple$calculateColor$1' \
  | grep -E 'getLocalRippleConfiguration|getLocalContentColor|long 16l'

# 2. which constructors carry an alpha set, and which of them are deprecated
javap -v -p -classpath "$M3" androidx.compose.material3.RippleConfiguration \
  | grep -E '^  (public|private) .*RippleConfiguration\(|Deprecated: true|message='

# 3. the app-wide configuration should be provided exactly once
grep -rn --include='*.kt' 'LocalRippleConfiguration' .

# 4. two click modifiers on one chain
grep -rn --include='*.kt' -B1 '\.combinedClickable(' . | grep -c '\.clickable'

# 5. how many click sites are bounded by a clip immediately above them — and out of how many, so
#    the ratio is an outcome rather than an assertion
grep -rn --include='*.kt' -A1 '\.clip(' . | grep -cE '\.(combined)?clickable'
grep -rn --include='*.kt' -E '\.(combined)?clickable' . | wc -l
```

1. → observed: `long 16l` (an unspecified colour), then the configuration local, then `long 16l`
   again, then the content colour. Both earlier stages are *skipped when unspecified*, which is the
   mechanism the first trap depends on.
2. → observed: eleven constructor lines — four real constructors plus their synthetic
   default-argument bridges — and the only one marked `Deprecated: true`, twice, once on the
   signature and once on its bridge, is `(color, rippleAlpha)`, with a message pointing at options
   that do not carry alpha. That is the whole migration story: there isn't one.
3. → observed: one import and one `provides` — both in the theme. A second provider deeper in the
   tree means part of the app is running a different ripple than the rest.
4. → observed: `0`. Any hit is a doubled ripple and a doubled semantics node.
5. → observed: two numbers, the second an order of magnitude larger — roughly one click site in
   twelve is clipped. That ratio is fine on its own: most clickables are on rectangular rows where
   the default bounds are correct. The list to walk is the *rounded* ones: every card, chip, capsule
   and circular button needs its clip above its click.

Then, by hand, on the dark theme: press and hold a rounded card. The flash must stay inside the
corner radius and must be *lighter* than the surface. Repeat inside a screen that forces its own
scheme — if the ripple inverts there, someone pinned a colour.
