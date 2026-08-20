---
name: force-dark-immersive-subtree
description: Keep one part of a Compose app rendered dark — screens drawn over dark artwork — while the rest of the app follows the user's light theme, by providing a whole dark colour scheme plus your own token locals to that subtree; includes why a text-colour flag alone is not enough, and the verified fact that bottom sheets and dialogs inherit these locals across the window boundary while a freshly rooted composition does not. Use when icons or buttons on an image-backed screen turn grey and unreadable in light theme, when a sheet opened from such a screen comes out the wrong colour, or when a forced-dark screen still asks the system whether it is night.
---

# Force-dark immersive subtree

Some screens are dark by construction: they draw over full-bleed artwork with white text on top. When
the app also supports a light theme, those screens must ignore it. The mechanism is to re-provide the
theme for that subtree only.

```kotlin
// adapted
@Composable
fun ForceDarkContent(content: @Composable () -> Unit) {
    val darkScheme = LocalForcedDarkColorScheme.current ?: MaterialTheme.colorScheme
    MaterialTheme(
        colorScheme = darkScheme,
        typography = typo(darkScheme, forceDark = true),
    ) {
        CompositionLocalProvider(
            LocalForceDarkText provides true,
            LocalIsDarkTheme provides true,
            LocalContentColor provides darkScheme.onSurfaceVariant,
            LocalAppColors provides DarkAppColors,
            content = content,
        )
    }
}
```

The dark scheme itself is resolved **once**, at the app theme, and published through a local so no
screen builds one of its own:

```kotlin
// adapted
val forcedDarkScheme =
    if (isDark) colorScheme
    else rememberDynamicColorScheme(seedColor, isDark = true, isAmoled = true, style = TonalSpot)
// … CompositionLocalProvider(LocalForcedDarkColorScheme provides forcedDarkScheme) { content() }
```

## Traps

**A text-colour flag is not enough, and this is the failure people ship.** A boolean that only feeds
your typography recolours `Text` and nothing else. Icons, buttons, dividers and every other Material
default read `LocalContentColor` and `MaterialTheme.colorScheme`, which in light theme go
dark-on-light and grey against the artwork. Providing the whole scheme fixes the subtree at once.

**Resolve the forced scheme at the theme, not per screen.** A seed-derived scheme is real work
(tonal-palette generation), and screens that each build their own drift apart. Publish one value
through a `staticCompositionLocalOf<ColorScheme?> { null }` whose null default means "you are outside
the app theme" and lets consumers fall back to `MaterialTheme.colorScheme`.

**Wrap at the navigation destination, not inside the screen composable.** That covers the screen's
top bar, its loading and error states and anything it hosts, and keeps the decision in one readable
list instead of scattered across screen bodies:

```kotlin
// adapted
composable<AlbumDestination> { entry ->
    ForceDarkContent { AlbumScreen(browseId = entry.toRoute<AlbumDestination>().browseId, …) }
}
```

**Sheets and dialogs DO inherit — this is what makes the approach hold, and it is verifiable.** They
render in their own platform window, which looks like it should sever the composition, but the host
view is handed the *calling* composition as its parent composition context. Checked against the
compiled libraries rather than the documentation: in Compose UI's Android artifact,
`PopupLayout.setContent(CompositionContext, content)` calls `setParentCompositionContext(ctx)` first,
`DialogWrapper` exposes the same two-argument `setContent`, and Material 3's
`ModalBottomSheetDialogLayout` does likewise; the context passed in comes from
`rememberCompositionContext()` in the caller. Every CompositionLocal — yours and Material's —
therefore flows across the window boundary. A sheet's colours should therefore *read* the flag rather
than hardcode dark — dark from an immersive screen, theme-following from a normal one:

```kotlin
// adapted
@Composable
fun rememberSurfaceColors(): SurfaceColors {
    val cs = MaterialTheme.colorScheme
    return if (LocalForceDarkText.current) SurfaceColors(container = Color(0xFF242424), …)
           else SurfaceColors(container = cs.surfaceContainerLow, …)
}
```

**What does NOT inherit is a composition you root yourself.** A second activity or desktop window
with its own `setContent`, a widget or other remote composition, or a view inflated without its
parent composition context being set — in that last case the runtime resolves a parent from the
window (`AbstractComposeView.resolveParentCompositionContext()`) and your locals are the defaults.
Every such root must re-provide the theme itself.

**Do not re-ask the system inside the subtree.** A platform effect calling `isSystemInDarkTheme()` to
pick a blur tint or a system-bar appearance will disagree with the forced subtree. Publish the
decision as a local (`LocalIsDarkTheme`) and read that everywhere, including from the wrapper.

**Force-dark is not accessibility dark mode.** These screens are dark because of what is behind them,
not because the user asked for a dark UI. Do not let the flag leak into settings, into what you
persist, or into the system-bar appearance for the rest of the app.

**Custom token locals must be re-provided too.** Anything outside the Material scheme — brand-state
colours, shimmer tones, overlays — has its own local and light/dark instances, and the wrapper must
hand over the dark set explicitly (`semantic-color-tokens-compositionlocal`).

## Verifying it

1. Every place that forces the subtree, to confirm each sits at a destination, not inside a screen:

   ```bash
   grep -rn --include='*.kt' "ForceDarkContent" . | grep -v '/build/'
   ```

2. Platform code that asks the system directly instead of reading the published local — each hit
   needs a reason:

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
   picks the newest *cached* version, not necessarily the one your build resolves — read the echoed
   path (plain `sort` is lexicographic and hands you `1.8.3` ahead of `1.12.0`). Swap the class for
   `androidx.compose.material3.ModalBottomSheetDialogLayout`, against a `*material3-android*` AAR,
   to check the sheet host the same way.

4. By eye, and this is the test that catches the "text flag only" failure: set the app to light
   theme, open an immersive screen, and look at the *icons* and *disabled* states rather than the
   headline text. Then open a sheet from that screen, and open the same sheet from a normal screen,
   and confirm they differ.
