---
name: force-dark-immersive-subtree
description: Keep one part of a Compose app rendered dark — screens drawn over dark artwork — while the rest of the app follows the user's light theme, by providing a whole dark colour scheme plus your own token locals to that subtree; includes why a text-colour flag alone is not enough, and the verified fact that bottom sheets and dialogs inherit these locals across the window boundary while a freshly rooted composition does not. Use when icons or buttons on an image-backed screen turn grey and unreadable in light theme, when a sheet opened from such a screen comes out the wrong colour, or when a forced-dark screen still asks the system whether it is night.
---

# Force-dark immersive subtree

Some screens are dark by construction: they draw over full-bleed artwork with white text on top, and
must ignore a light theme. The mechanism is to re-provide the theme for that subtree only.

```kotlin
// adapted
@Composable
fun ForceDarkContent(content: @Composable () -> Unit) {
    val darkScheme = LocalForcedDarkColorScheme.current ?: MaterialTheme.colorScheme
    MaterialTheme(colorScheme = darkScheme, typography = typo(darkScheme, forceDark = true)) {
        CompositionLocalProvider(
            LocalForceDarkText provides true,
            LocalIsDarkTheme provides true,
            LocalContentColor provides darkScheme.onSurfaceVariant,
            LocalAppColors provides DarkAppColors,
            content = content,
        )
    }
}

// …and the scheme itself is resolved ONCE at the app theme, published through that local:
val forcedDarkScheme =
    if (isDark) colorScheme
    else rememberDynamicColorScheme(seedColor, isDark = true, isAmoled = true, style = TonalSpot)
```

## Traps

**A text-colour flag is not enough, and this is the failure people ship.** A boolean that only feeds
your typography recolours `Text` and nothing else. Icons, buttons, dividers and every other Material
default read `LocalContentColor` and `MaterialTheme.colorScheme`, which in light theme go
dark-on-light and grey against the artwork. The whole scheme fixes the subtree at once.

**Resolve the forced scheme at the theme, not per screen.** A seed-derived scheme is real work, and
screens that each build their own drift apart. Publish one value through a
`staticCompositionLocalOf<ColorScheme?> { null }` whose null default means "outside the app theme"
and lets consumers fall back to `MaterialTheme.colorScheme`.

**Wrap at the navigation destination, not inside the screen composable.** That covers the screen's
top bar, its loading and error states and anything it hosts, and keeps the decision in one readable
list instead of scattered across screen bodies:

```kotlin
// adapted
composable<AlbumDestination> { entry ->
    ForceDarkContent { AlbumScreen(browseId = entry.toRoute<AlbumDestination>().browseId, …) }
}
```

**But that list is a registration list, and registration lists drift.** Nine wrap sites here across
three files, with nothing tying them to the screens that need one — so a new immersive screen is
correct until somebody remembers this file exists. It then fails only in the light theme, which is
the one nobody reviews in. Same shape as `nav-tab-registration-drift`, same remedy: make membership
derivable from the screen — anything painting its background from an extracted palette belongs on
the list, which makes the pairing greppable (step 1). Write the reason at the wrap.

**Sheets and dialogs DO inherit — this is what makes the approach hold, and it is verifiable.** They
render in their own platform window, which looks like it should sever the composition, but the host
view is handed the *calling* composition as its parent composition context. Checked against the
compiled libraries rather than the documentation: in Compose UI's Android artifact,
`PopupLayout.setContent(CompositionContext, content)` calls `setParentCompositionContext(ctx)` first,
`DialogWrapper` exposes the same two-argument `setContent`, and Material 3's
`ModalBottomSheetDialogLayout` does likewise; the context comes from `rememberCompositionContext()`
in the caller. Every CompositionLocal therefore crosses the window boundary — so a sheet's colours
should *read* the flag rather than hardcode dark:

```kotlin
// adapted
@Composable
fun rememberSurfaceColors(): SurfaceColors {
    val cs = MaterialTheme.colorScheme
    return if (LocalForceDarkText.current) SurfaceColors(container = Color(0xFF242424), …)
           else SurfaceColors(container = cs.surfaceContainerLow, …)
}
```

**What does NOT inherit is anything that is not a descendant** — two shapes, the second surprising.
A composition you root yourself: a second activity or desktop window with its own `setContent`, a
widget, or a view inflated without its parent composition context being set (there the runtime
resolves a parent from the window, `AbstractComposeView.resolveParentCompositionContext()`, and your
locals are the defaults). And a **sibling of the navigation host**: an overlay declared beside the
`NavHost` — a persistent mini or expanded player, a global snackbar host — is in the same composition
and still cannot see a local provided at a destination, because provision flows *down*. Two of the
nine wraps here exist for exactly that. Every such root or sibling re-provides the theme itself.

**Do not re-ask the system inside the subtree.** An effect calling `isSystemInDarkTheme()` for a blur
tint or a system-bar appearance disagrees with the forced subtree — publish the decision as a local
(`LocalIsDarkTheme`) and read that everywhere, the wrapper included.

**Force-dark is not accessibility dark mode.** The screen is dark because of what is behind it, not
because the user asked — never let the flag reach settings, persistence or the system-bar appearance.

**Custom token locals must be re-provided too.** Anything outside the Material scheme — brand-state
colours, shimmer tones, overlays — has its own local and light/dark pair, handed over explicitly
(`semantic-color-tokens-compositionlocal`).

## Verifying it

1. Every wrap, against every screen that needs one — compare screen *names*, never paths: the wrap
   sits at the destination and the palette call inside the screen file, so the two lists share no
   path. Every name in the second must be covered by the first — 9 against 15 here — except helpers,
   and the roots and siblings above, which must re-provide the theme themselves; open those and check:

   ```bash
   grep -rn --include='*.kt' -A 3 "ForceDarkContent {" . | grep -v '/build/' | grep -oE "[A-Za-z]+(Screen|ScreenContent|Player)\(" | sort -u
   grep -rln --include='*.kt' "toImmersiveBackground\|rememberPaletteState" . | grep -v '/build/' | xargs -n1 basename | sort
   ```

2. Platform code asking the system directly instead of reading the published local — each hit needs
   a reason:

   ```bash
   grep -rn --include='*.kt' "isSystemInDarkTheme()" . | grep -v '/build/'
   ```

3. Confirm the sheet-inheritance claim against a cached library rather than trusting this file.
   Read-only, no build required:

   ```bash
   AAR=$(find ~/.gradle/caches/modules-2 -name '*.aar' -path '*ui-android*' | sort -V | tail -1) \
     && echo "$AAR" && D=$(mktemp -d) && unzip -oq "$AAR" classes.jar -d "$D" \
     && unzip -oq "$D/classes.jar" -d "$D/cls" \
     && javap -c -p -classpath "$D/cls" androidx.compose.ui.window.PopupLayout \
        | grep -A4 "setContent(androidx.compose.runtime.CompositionContext"
   ```

   Expect `invokevirtual … setParentCompositionContext` as the first call in the body. `sort -V`
   picks the newest *cached* version, not the one your build necessarily resolves — read the echoed
   path (plain `sort` hands you `1.8.3` ahead of `1.12.0`). Swap in
   `androidx.compose.material3.ModalBottomSheetDialogLayout` against a `*material3-android*` AAR.

4. By eye — the test that catches the "text flag only" failure: in **light** theme, open an immersive
   screen and look at the *icons* and *disabled* states rather than the headline text. Then open one
   sheet from that screen and the same sheet from a normal screen, and confirm they differ.
