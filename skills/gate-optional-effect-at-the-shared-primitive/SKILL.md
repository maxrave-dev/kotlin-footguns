---
name: gate-optional-effect-at-the-shared-primitive
description: Put a user's on/off setting for an optional decorative surface treatment inside the one shared primitive that draws it — published from the theme as a CompositionLocal defaulting to on — instead of asking every call site to check the flag. Covers why the off path must keep the shape and the hit target and change only the paint, why the default is true rather than false, and the difference between a call site that picks a material and one that picks a different composable. Use when a settings toggle reaches only some of the surfaces it names, when a gated component renders as a bare box in previews, or when turning an effect off also moves the layout.
---

# Gate an optional effect at the shared primitive

An optional decorative surface treatment — a blur, a refraction, a glow, anything the user can
switch off — has three parts: a stored preference, a way for the UI to read it, and the draw code.
Only the third one is shared. Wire the gate to the third one.

```kotlin
// adapted — one local, published by the app theme, default ON
val LocalDecorEnabled = staticCompositionLocalOf { true }

// inside AppTheme(…, decorEnabled: Boolean = true, …)
CompositionLocalProvider(
    LocalDecorEnabled provides decorEnabled,
    /* the theme's other locals */
    content = content,
)
```

```kotlin
// adapted — the primitive every surface already goes through
@Composable
fun Modifier.decorSurface(shape: Shape = CircleShape, …): Modifier {
    if (!LocalDecorEnabled.current) {
        // shape and hit target unchanged; only the draw
        return this.clip(shape).background(colorScheme.surfaceContainerHighest.copy(alpha = 0.8f))
    }
    return this.drawTheExpensiveThing(shape = shape, …)
}
```

## Traps

**Gating per call site is a registration list nobody finishes.** Counted here: 10 files call the
primitive — a compact player, two alternate navigation bars, seven ordinary screens — while exactly
2 files anywhere in the tree *branch on* the setting (five mention it; the storage, the accessor and
the settings row do nothing else). One of the two is the compact player, so all seven screens never
checked: they reached for the shared component with no reason to suspect a flag existed, so the
toggle appeared to work — the two surfaces that *did* check it flipped — while every detail screen
kept drawing the effect. Same silence as `nav-tab-registration-drift` and
`guard-on-every-trigger-path`: a rule that lives in a list has to be re-applied by every future
author, and it will not be.

**The default is `true`, not `false`.** A `staticCompositionLocalOf { false }` reads like the safe
choice and is the opposite: every `@Preview`, every composition rooted outside the app theme, and any
second window that forgot to re-provide gets the *stripped* look with no error and no diff. Default
to the appearance the design assumes, so being outside the theme degrades to "looks right" rather
than "looks broken". Same reasoning as the null-means-outside-the-theme default in
`force-dark-immersive-subtree`, arrived at from the other direction.

**`staticCompositionLocalOf`, not `compositionLocalOf`.** The static kind does not track reads: a
change recomposes the whole subtree under the provider. That is exactly right for a value that moves
once, when a human flips a switch, and would be exactly wrong for something changing per frame. The
tracking kind would instead register ~19 read scopes that exist only to observe a value that almost
never changes.

**The off path must return the same geometry.** Keep the `clip(shape)` and whatever gives the
element its size — return a *different paint*, never a different box. Drop the clip and corners
square up; drop a size and every neighbour shifts, so the user's toggle silently reflows the screen
and the setting reads as broken rather than as a preference. The fallback here deliberately reuses
the flat surface the screens drew before the effect existed, so "off" is a state the design has
already been through, not a new one.

**A platform where the setting does not exist provides `true` once, at the theme.** Resolve it in
the single call that builds the theme (`stored == TRUE || platform is the one with no switch`), not
at each call site — that is the per-call-site trap re-entering through the back door.

**Some call sites legitimately branch *before* composing, and those are a different question.** Two
surfaces here pick a whole different composable rather than a different material: a bar that is a
capsule in one style and a row in the other, and a compact player that swaps its container. Those
read the raw setting because the choice is which tree to build, not how to paint one. Keep them
countable — here, eleven comparisons in two files — and make sure both paths read the same stored
value, or the bar can be in one mode while its buttons are in the other. When the two branches are
the *same control* in two materials, see `flat-twin-shares-geometry-not-material`.

**Put the guard before the `remember`s.** The off path returns *above* `rememberGraphicsLayer()` and
the interaction holder, so a disabled surface allocates no layer, starts no animation and installs no
pointer input — most of what the setting exists to save. A gate expressed as an `enabled` parameter
on the expensive draw modifier would already have paid for all three by the time it was read.

**An overload without the guard is a hole in the gate.** The primitive here has two overloads: the
simple one carries the guard, the layer-plus-luminance one does not, because its two callers are both
the compact player — one inner-gated, one on the platform that provides `true` unconditionally.
Defensible, and also exactly what a forgotten overload looks like. So is the **third** door below
both overloads: the bar reaches the draw modifier directly. Write the reason beside each.

**Keep both branches at the same call site.** Returning a different modifier chain from the *same*
composable is what lets the runtime swap materials cleanly. Hoisting the branch into the caller
(`if (enabled) GlassButton() else FlatButton()`) creates two different call sites, so every toggle
discards whatever state that subtree held — animation progress, focus, scroll — and the switch reads
as a flicker rather than a change of finish.

**The theme's own parameter has a default too, and it must agree with the local's.** The theme takes
`decorEnabled: Boolean = true` and hands it to a local defaulting to `true`; make one of those two
`false` and the behaviour depends on which path the code took to get there — a theme call that omits
the argument disagrees with a subtree composed outside any theme, for no visible reason.

**Do not thread the flag through as a parameter.** A `decorEnabled: Boolean` argument on the
primitive puts the decision back at the call site with extra ceremony: every caller must now pass it,
and a caller that forgets gets the default. The local is what makes forgetting impossible.

## Verifying it

```bash
# 1. The gate: locals defaulting to on, and every guard that reads one. One declaration per
#    optional treatment, one reader — the primitive. A reader in a screen file is the trap.
grep -rn --include='*.kt' -e 'staticCompositionLocalOf { true }' -e 'if (!Local' . | grep -v '/build/'
```

→ observed: three lines — two theme-level locals defaulting to `true` (this gate and the is-dark
flag), and exactly one `if (!Local….current) {` guard, in the primitive.

```bash
# 2. Call sites still comparing the raw stored setting. These are the pre-branch exceptions above;
#    read each and confirm it picks a different COMPOSABLE, not a different material.
grep -rn --include='*.kt' -E 'is[A-Za-z]+Enabled ==' . | grep -v '/build/'
```

→ observed: 11 comparisons in exactly 2 files — the shell choosing between two navigation bars, and
two player containers. A third file here would be a screen that should be using the gated primitive.

```bash
# 3. Everything the gate covers. Derive the primitive's declarations from step 1's file rather than
#    typing names, then list every file that calls one of them.
PRIM=$(grep -rl --include='*.kt' 'if (!Local' . | grep -v '/build/' | head -1)
SYMS=$(grep -oE 'fun [A-Za-z]*\.?[A-Za-z]+\(' "$PRIM" | grep -oE '[A-Za-z]+\(' | sort -u | tr -d '(' | paste -sd'|')
grep -rlE --include='*.kt' "($SYMS)\(" . | grep -v '/build/' | grep -v "^$PRIM$"
```

→ observed: 10 files. One is the compact player from step 2, two are the alternate navigation bars
(only ever composed on the enabled branch), and the remaining **7 are ordinary screens with no idea
the setting exists** — that 7-vs-1 split is the whole argument for the local.

4. By eye, and this is the check counting cannot do: screenshot a gated screen with the setting off
   and on, at the same scroll position, and overlay them — anything that *moved* is an off path that
   changed geometry instead of paint. Then open a preview with no theme wrapper: it must look on.
