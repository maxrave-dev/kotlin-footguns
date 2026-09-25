---
name: chrome-drawn-outside-the-theme-scope
description: A custom window title bar, splash, or crash dialog composed as a sibling of the app theme rather than inside it reads MaterialTheme's framework DEFAULT scheme — light, always, no matter what the user picked — and nothing errors. Covers extracting the stored-mode-to-boolean decision as one shared composable function so the chrome and the theme cannot answer differently, passing colours in as parameters instead of re-theming, and the colours that must deliberately not follow the theme at all. Use when a title bar or dialog stays light in dark mode, when chrome colours lag one launch behind the setting, or before adding any composable above the theme call.
---

# Chrome drawn outside the theme scope

An app's own window decorations get composed before the theme, because they wrap it:

```kotlin
// adapted — the desktop window body
Column(Modifier.fillMaxSize()) {
    CustomTitleBar(…)     // ← here, MaterialTheme.colorScheme is the FRAMEWORK DEFAULT
    App()                 // ← AppTheme(…) is entered in here
}
```

`MaterialTheme.colorScheme` above that second line is neither an error nor null: the object falls back
to a built-in light scheme when none was provided, so the title bar reads perfectly valid colours that
have nothing to do with the user's choice. The fix is not a second theme — resolve the *decision* once
and hand the chrome finished colours:

```kotlin
// adapted — pulled out of AppTheme so chrome living outside it can ask the same question
@Composable
fun isDarkTheme(themeMode: String): Boolean = when (themeMode) {
    THEME_MODE_LIGHT -> false
    THEME_MODE_SYSTEM -> isSystemInDarkTheme()
    else -> true
}

val isDark = isDarkTheme(themeMode)          // above the theme
CustomTitleBar(containerColor = if (isDark) Color.Black else Color.White,
               titleColor = if (isDark) Color.White else Color.Black, …)
```

## Traps

**The failure is silent and looks like a different bug.** No exception, no lint, no missing-provider
warning — the chrome simply renders in the default palette. Reported symptoms are "the title bar
ignores dark mode" and "the window is white for a second", and both send people hunting in the
chrome's own code, which is correct in isolation.

**A second `MaterialTheme` around the chrome is the wrong repair.** It re-runs palette generation,
gives the chrome a scheme object that is not the app's, and drifts the moment the app theme gains a
modifier the copy does not have. Chrome is a handful of colours; pass them.

**The mode-to-boolean resolution must exist once and be called twice.** Copying the `when` into the
chrome is the classic drift: add a mode later and one copy learns about it. Extracting it is also
what makes the two paths *provably* agree — a single definition with two call sites is greppable in
a way that two identical `when` blocks are not.

**It has to stay a `@Composable` function, and must not be resolved at startup.** The
follow-the-system branch calls `isSystemInDarkTheme()`, which is a composition-time read that
re-runs when the system flips. Cached into a plain value at launch, the chrome is right until the
user changes their system theme and then wrong until the next cold start — the "lags one launch
behind" symptom. For the same reason a forced-dark *subtree* must not call it either: inside such a
subtree the system's answer is the wrong one, so the decision is published as a local
(`force-dark-immersive-subtree`).

**Some colours are fixed by convention and must not follow the theme.** Window-control dots are read
by their colour, not by their contrast, so they are named constants outside the scheme, with the
reason written beside them. The rule that everything follows the theme is what makes an exception
look like an oversight; the comment is what stops the next person from "fixing" it.

**Chrome the app draws itself is inside the window, and therefore inside the reported size.** A
title bar rendered by the app occupies part of the container every layout below it measures against,
unlike a native decoration outside it. Anything computing a height from the window must subtract it,
conditionally — see `responsive-gate-size-not-platform` for what a wrong height does to a layout
gate downstream.

**The chrome must be able to disable itself.** Environments where a custom bar is inappropriate
(virtualised desktops, hosts without compositing) branch it off entirely; the colour resolution then
has to be inside that branch, or you compute a scheme for a bar nobody draws and pay for a
preference read on every launch that skips it.

**A second window is chrome too.** A window composed as a *sibling* of the themed one — a mini
player, a preferences window, a picker — sits outside the theme by construction, exactly like the
title bar. It must either re-enter the theme itself or commit to explicit colours; the second window
here takes the second option and reads no scheme at all, which is only defensible because it is a
decision. One accidental `MaterialTheme.colorScheme` inside it is the silent-light bug again.

**Non-Compose chrome is the easiest to forget.** A crash handler that raises a platform dialog before
any composition exists cannot read the theme at all — its colours come from the toolkit's defaults.
That may be fine for a dialog nobody should be seeing, but decide it rather than discovering it in a
screenshot from a user.

**Enumerate the theme roots, not the screens.** Grep for the theme composable: one definition and one
call site means everything else drawn at that moment is outside it, and that single number is the
whole audit. It also tells you what a new window has to do before it draws anything.

**Do not read the preference twice.** The chrome and the theme should collect from the same stored
value; two independent collectors of the same preference can be one emission apart during startup,
which shows up as a title bar in the old theme over content in the new one for a frame or two. The
tree audited here reads it twice and gets away with it for one reason only — both collectors are
seeded with the same stored default (below). Add a second collector with a different seed and the
title bar is a theme behind the content until the first emission lands.

**Chrome is the first thing drawn and the preference is the last thing to arrive.** The stored mode
reaches the composition asynchronously, so the very first frames use whatever the collector's initial
value is. Seed that collector with the *stored default* rather than a hardcoded light, or every cold
start in dark mode opens with a white flash across the top of the window.

**Colours that never follow the theme still belong in the colour file.** Putting the window-control
constants beside the scheme keeps them findable and keeps their justification next to them; scattering
them as literals inside the chrome composable is how the next person "themes" them by accident.

## Verifying it

```bash
# 1. The shared decision: one definition, and every place that calls it. Two callers is the healthy
#    shape — the theme, and the chrome above it. A `when (themeMode)` anywhere else is a copy.
grep -rn --include='*.kt' 'isDarkTheme(' . | grep -v '/build/'
```

→ observed: three lines — the declaration, the call inside the theme, and one in the window body.

```bash
# 2. Chrome taking colours as parameters rather than reading a scheme. Read the default values:
#    they are the fallback the chrome shows if a caller forgets, so they should be the safe ones.
grep -rn -B6 --include='*.kt' -E '(containerColor|titleColor): Color = Color\.' . | grep -v '/build/'
```

→ observed: a title bar with `containerColor = Color.Black` / `titleColor = Color.White` carrying a
comment saying why, plus an in-theme app bar defaulting to transparent — which correctly reads the
scheme itself.

```bash
# 3. Colours deliberately outside the scheme, each of which needs its reason on the line above.
grep -rn -B3 --include='*.kt' -E 'val window[A-Z][A-Za-z]*Button' . | grep -v '/build/'
```

→ observed: six window-control constants under a comment stating they are fixed by convention,
because users read them by colour. An entry without that justification escaped the scheme.

4. By eye, in both directions: launch dark, switch the app to light *while running*, and watch the
   chrome change with the content rather than at the next launch. Then set follow-system and flip the
   OS theme with the app in the foreground. Finally, screenshot the first frame of a cold start in
   dark mode — a white flash is the default-scheme read happening before the preference arrives.
