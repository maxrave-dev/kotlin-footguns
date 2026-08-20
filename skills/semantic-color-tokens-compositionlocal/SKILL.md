---
name: semantic-color-tokens-compositionlocal
description: Hold the colours that have no Material role — a liked-state pink, an active-line highlight, shimmer tones, overlays that sit on artwork — in an @Immutable token class provided through staticCompositionLocalOf, with the bytecode-level reason static is the right choice for theme values and a rule for what belongs in the token class versus in the colour scheme. Use when hex literals are spreading through composables, when a colour has to differ between light and dark but is not a scheme role, or when you are choosing between staticCompositionLocalOf and compositionLocalOf.
---

# Semantic colour tokens through a CompositionLocal

A Material colour scheme covers *roles*: surfaces, containers, primary/secondary/tertiary, error and
the `on…` pairs. It does not cover colours whose meaning is your app's — the pink that means "liked",
the highlight on the active line of a running text, the two tones a shimmer sweeps between, the
overlays that dim artwork. Those need a home that is not a scattering of hex literals.

```kotlin
// adapted
@Immutable
data class AppColors(
    val favorite: Color, val lyricActive: Color,
    val shimmerBackground: Color, val shimmerLine: Color,
    val overlay: Color, val overlayHeavy: Color,
)

private val DarkAppColors = AppColors(favorite = favoriteColor, /* … */)

// Overlays stay dark in both themes: they cover artwork, where content is always light.
private val LightAppColors =
    DarkAppColors.copy(shimmerBackground = shimmerBackgroundLight, shimmerLine = shimmerLineLight)

val LocalAppColors = staticCompositionLocalOf { DarkAppColors }
```

and in the theme, alongside the scheme:

```kotlin
// adapted
CompositionLocalProvider(
    LocalAppColors provides if (isDark) DarkAppColors else LightAppColors,
    LocalIsDarkTheme provides isDark,
    content = content,
)
```

## Traps

**Static versus dynamic is a real difference, not a style preference.** The two factories build
different provided values, and you can read that straight out of the compiled runtime. On
`androidx.compose.runtime:runtime-desktop:1.12.0-alpha02`, `staticCompositionLocalOf`'s
`StaticProvidableCompositionLocal` builds its `ProvidedValue` with a **null mutation policy, a null
backing state and an `isDynamic` flag of false**, where `compositionLocalOf`'s
`DynamicProvidableCompositionLocal` passes its policy and sets that flag true. So a static local has
nothing a reader can subscribe to — changing it must invalidate everything under the provider, while
a dynamic one is state-backed and invalidates only the composables that read it.

```bash
JAR=$(find ~/.gradle/caches/modules-2 -path '*androidx.compose.runtime/runtime-desktop/*' -name '*.jar' \
        | sort -V | tail -1) && echo "$JAR" && D=$(mktemp -d) && unzip -oq "$JAR" -d "$D" \
  && javap -c -p -classpath "$D" androidx.compose.runtime.{Static,Dynamic}ProvidableCompositionLocal \
     | grep -E "^public final class|defaultProvidedValue|getfield|aconst_null|iconst_[01]$"
```

Compare the *tails* of the two `defaultProvidedValue$runtime` bodies: static ends `aconst_null ×3,
iconst_0`; dynamic swaps `getfield … policy` for the first null and ends `iconst_1`. `sort -V` picks
the newest *cached* jar, not necessarily what your build resolves — so read the echoed path.

That makes the choice mechanical. Theme tokens change roughly never — a theme switch — and are read
in hundreds of places, so pay nothing at read time and accept a full re-theme on a switch:
**static**. A value that changes often and is read in a few places (a scroll offset, a playing item)
wants the opposite: **dynamic**.

**`@Immutable` is a promise the compiler mostly takes your word for.** Every property `val`, every
type stable. A `var`, a mutable collection or an unstable third-party type inside makes the
annotation a lie, and skipping decisions taken on its strength go wrong silently.

**Hoist the instances to top-level `val`s.** Building the token object inside the theme composable
hands the provider a fresh object on every composition, for no reason: two constants and a `copy()`
cost nothing and are easier to read.

**Derive the second theme with `copy()`, changing only what differs.** It documents intent that a
line of prose cannot: overlays sit on artwork, and artwork is light-on-dark in both themes, so they
are deliberately identical. Two full constructors make that look like an oversight someone will fix.

**Do not duplicate a role that already exists.** A surface tier, an outline, an error, a primary or
secondary accent belongs in the scheme: a token shadowing a role stops following seeded or
wallpaper-derived theming and drifts when the scheme is regenerated. Derivable from the seed? A role.

**The default value is a real fallback, not a placeholder.** Previews, tests, and any composition
rooted outside your theme get it — including sheets or windows hosted from a composition you did not
root (`force-dark-immersive-subtree` covers which of those inherit). Make it your primary set rather
than a throwing lambda, unless you want previews to crash.

**A boolean local beats every consumer re-deriving the theme.** `LocalIsDarkTheme` publishes what
the theme *decided*, which is not the same as what the system reports once any subtree forces a mode.
Platform effects that tint or blur must read the local, never `isSystemInDarkTheme()`.

**Never capture a token inside an unkeyed `remember`.** `remember { colors.favorite }` freezes the
first theme's value for that composable's lifetime, and the bug only appears when a user toggles the
theme without leaving the screen. Key the `remember` on the token, or just read it directly — a
`CompositionLocal` read is cheap, and cheapest of all for a static one.

**Retire legacy colours by deprecating, not deleting.** A colour one screen still needs and nobody
has time to migrate should carry a `@Deprecated` message naming its single remaining use — that is
what stops it spreading again while the migration waits.

## Verifying it

1. Every local you declare, with its factory, so each can be checked against the static/dynamic
   rule above:

   ```bash
   grep -rn --include='*.kt' -E "staticCompositionLocalOf|compositionLocalOf" . | grep -v '/build/'
   ```

2. Every token holder with the two lines above it, so you can check each carries `@Immutable`. The
   command cannot express absence — read the context lines:

   ```bash
   grep -rn --include='*.kt' -B2 "^data class .*Colors\b" . | grep -v '/build/'
   ```

3. Hex literals outside the theme package, which is where tokens leak back out. A one-off
   decorative colour is fine; the real signal is **repetition** — the same literal in several files
   is a token that escaped, so count them rather than reading the list:

   ```bash
   grep -rho --include='*.kt' --exclude-dir=build --exclude-dir=theme \
     -E "Color\(0x[0-9A-Fa-f]{8}\)" . | sort | uniq -c | sort -rn | head
   ```

   Anything with a count above one belongs in the token class or the scheme. Case matters to `uniq`,
   so `0xFFxxxxxx` and `0xffxxxxxx` count separately — that inconsistency is itself worth fixing.

4. Tokens frozen by an unkeyed `remember`. Expect **no output**; every hit survives a theme change
   with the old colour:

   ```bash
   grep -rn --include='*.kt' -E "remember \{[^}]*Local[A-Za-z]+\.current" . | grep -v '/build/'
   ```

5. By eye: toggle the theme *while sitting on a screen*, not by relaunching. A token read through a
   static local updates with the rest of the subtree; one captured in a `remember` does not, and
   relaunching hides exactly that difference.
