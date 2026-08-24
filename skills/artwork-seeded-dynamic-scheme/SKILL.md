---
name: artwork-seeded-dynamic-scheme
description: Derive a complete tonal colour scheme from one artwork-extracted seed and wrap only that subtree in it, so every control inherits contrast-paired roles instead of hand-picked swatches — covers falling back by comparing against the sentinel the seed was initialised with, tweening the seed rather than the scheme, and the cost of re-deriving per animation frame. Use when a screen should recolour itself to its artwork, when foreground text on a tinted surface comes out unreadable, or when a colour change lands as a visible flash.
---

# A whole scheme from one seed colour

Two ways to let artwork colour a screen. `artwork-palette-theming` picks *swatches* — an accent, a
background — and you place each one by hand. This one derives an entire scheme from a single seed and
wraps the subtree in it, so every button, container and label resolves through roles and you place
nothing.

```kotlin
// adapted
val seedColor = if (paletteColor == Color.Black) fallbackSeed else paletteColor
val animatedSeed by animateColorAsState(seedColor, tween(durationMillis = 800))
val scheme = rememberDynamicColorScheme(seedColor = animatedSeed, isDark = true, style = Vibrant)
ThemeWrapper(colorScheme = scheme) { Content(state, actions) }
```

The payoff is the reason to prefer it: every `onX` role is generated contrast-paired with its `X`. A
foreground picked by hand from a palette is where unreadable text comes from.

## Traps

**Fall back by comparing against the sentinel the seed was initialised with, not against null.** The
seed usually arrives through an animatable, which is never null — it holds whatever it was created
with. "Unresolved" therefore means "still equal to that initial value", and the comparison has to
name it explicitly. Two consequences worth accepting deliberately: an artwork whose extracted colour
genuinely *is* the sentinel keeps the fallback forever, so choose a sentinel real artwork rarely
produces; and if extraction never completes, the fallback is permanent and silent — see
`palette-state-parks-on-loading` for the mechanism that makes that happen more often than expected.

**Tween the seed and re-derive; never animate the scheme.** A scheme is dozens of roles that were
generated together. Animating them independently lets them cross — a foreground can pass its own
background mid-flight — and there is no moment at which the set is coherent. One animated seed keeps
every intermediate scheme internally consistent.

**Without the tween the swap reads as a flash, not as a colour change.** Every surface, container,
outline and label changes in the same frame; the eye reports that as a flicker. Around 800 ms is slow
enough to read as the screen recolouring itself and short enough not to lag the artwork.

**Deriving a scheme is real work, and a tween asks for one per frame.** Tonal-palette generation runs
for each distinct seed value, so an 800 ms animation is tens of derivations. Fine for one screen
transition; not fine per item in a list, and not fine on a seed that changes with scroll. If it must
be cheap, step the animation to a handful of values instead of tweening continuously.

**Reading the seed at the top of the content composable subscribes the whole subtree to it.** The
seed usually arrives as an animatable owned by the shell; reading its `.value` in the outermost
composable means every frame of that animation recomposes everything below. Read it in the smallest
composable that needs it, or accept the cost knowingly — and never read it in two places, which
doubles the subscription for one value.

**Wrap the subtree, not the app.** The theme wrapper goes around the content composable so the rest
of the app keeps the user's theme. Sheets and dialogs opened from inside will inherit it across the
window boundary — that is usually what you want, and `force-dark-immersive-subtree` covers why it
happens and what does *not* inherit.

**Pin the brightness; do not ask the system.** A screen dark by construction derives with a fixed
dark flag. Reading the system setting inside a subtree that has already decided produces a scheme
that disagrees with the surface it is painted on.

**Inside the subtree, hardcoded colours are the only thing that will not follow.** They are not all
wrong — a control floating over a photo or a video legitimately stays white — but each one is an
exception to a rule, and an exception with no reason written next to it is how the rule rots. See
`a-stated-rule-needs-annotated-exceptions`.

**The generation style is a per-surface decision.** A vivid style keeps much more of the artwork's
chroma than a muted one; the same seed produces a scheme that reads as "the artwork's colour" under one
and "a tasteful tint" under the other. Choose it where the scheme is derived, and do not let two
surfaces in one app derive with different styles from the same seed by accident.

## Verifying it

1. The derivation, the wrap and the fallback, in one place — all three should sit within a few lines
   of each other:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -B6 "rememberDynamicColorScheme(" .
   ```

2. Every seed fallback is a comparison against a named sentinel, not a null check:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -B2 -A2 "seedColor = " . | grep -E "== Color\.|\?:"
   ```

3. The seed is animated and the scheme is not:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "animateColorAsState(" . | grep -i "seed"
   grep -rn --include='*.kt' --exclude-dir=build "animate.*ColorScheme\|ColorScheme.*animate" .
   ```

   The second command must print nothing.

4. Hardcoded colours inside the themed subtree, so each can be checked for a written reason:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -B2 "Color\.White\|Color\.Black" \
     $(grep -rl --include='*.kt' --exclude-dir=build "rememberDynamicColorScheme(" . | head -1)
   ```

5. By eye: play something with strongly coloured artwork, then skip to something with artwork of a
   very different hue, and watch the *containers* rather than the background — a scheme that is
   really being derived recolours the buttons too. Then switch the app to light theme and confirm the
   subtree is unchanged while the screen behind it follows.
