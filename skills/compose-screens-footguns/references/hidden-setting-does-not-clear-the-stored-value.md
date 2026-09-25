---
name: hidden-setting-does-not-clear-the-stored-value
description: A style or effect option is correctly hidden from a settings picker below some OS version or capability floor, yet the effect it names still shows up broken — flat, unblurred, or simply wrong — on a device that should never be able to select it, because the picker gates what a user can choose next, not what a stored preference already holds. Use when a version-gated visual feature has a capability check in one place but the bug still reproduces, or when adding an expect/actual boolean for a modifier that fails silently instead of throwing.
---

# Hidden setting does not clear the stored value

A stored preference can name an effect this device cannot draw. Hiding an option from a settings
picker only stops a user from choosing it *from now on* — it does nothing about a value already
sitting in the preference store, so the real defence has to live at the render site instead, and it
takes the shape of a capability boolean: a small function each render site calls itself, right next
to the preference read, instead of trusting that Settings already filtered the value. Building and
calling that boolean correctly is most of what this skill is about — get it wrong and the render-site
defence collapses back into "the picker already handled it."

Some Compose modifiers do not fail when the platform cannot honour them — they render as a no-op,
with no exception and nothing in the log. `Modifier.blur` on Android is one: below API 31 there is
no `RenderEffect` to back it, so the modifier simply draws the content unblurred. A style built
around that blur being present therefore needs a real capability check, not a version comment:

```kotlin
// adapted — three files combined; each file's own doc comment is replaced with a one-line label
expect fun isLyricsBlurSupported(): Boolean

// Android — the actual version floor
actual fun isLyricsBlurSupported(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S

// Desktop — skia draws Modifier.blur on every target, no version to check
actual fun isLyricsBlurSupported(): Boolean = true
```

The function is named after the capability, not the OS version or the platform, because the two
actuals differ for unrelated reasons: one is a real floor on one target, the other is an
unconditional yes on a renderer that was never version-gated to begin with. A name like
`isAndroid12Plus()` would already be wrong the day a third target answers this differently again.

## Traps

**The failure below the gate has no signal of its own.** Nothing here throws, logs, or shows a
lint warning — the documented behaviour of the modifier itself is to do nothing. That silence is
the entire reason the boolean has to exist: there is no error path to catch instead of writing it,
and the only way to notice a missing gate is to run the build on a device below the floor and look
at the screen.

**Gating the picker is not gating the render path.** Hiding the option from Settings stops a user
from picking it *from now on* — it does nothing about a value already sitting in a preference
store. A backup restored onto an older device, a value synced from a phone that supports the effect
to one that does not, or simply a build from before the gate existed, can all leave the stored
preference holding the unsupported style. Every place that actually renders the effect re-derives
the same condition instead of trusting that Settings already filtered it — three separate call
sites in this codebase do this, each reading its own copy of the stored style:

```kotlin
// adapted — two of the three call sites, `DataStoreManager.` qualifier dropped for width
val appleStyle = lyricsStyle == LYRICS_STYLE_APPLE_MUSIC && isLyricsBlurSupported()
val fullscreenAppleLyrics = fullscreenLyricsStyle == LYRICS_STYLE_APPLE_MUSIC && isLyricsBlurSupported()
```

Treat the settings-level check as a UX nicety — it stops the picker from *offering* a choice that
would look broken — and the render-site check as the one that actually has to be correct every
time, because the enum value alone is not proof of what drew it.

**A cheap, pure predicate is fine to call redundantly; do not "optimize" it into shared state.**
Every site above calls the function directly rather than reading one hoisted flag passed down as a
parameter. For a version comparison or a constant, recomputing it at each of a handful of call
sites is simpler than threading it through — and, unlike a cached flag, it can never go stale
relative to the live value it protects. Hoisting only pays off once the check itself is expensive.

**This is a fourth shape, not one of the three composable ones.** `isLyricsBlurSupported()` is a
plain (non-`@Composable`) `expect fun` returning a constant-for-the-process boolean — it is not a
measurement, an effect with an undo, or a subscription read as state, the three shapes
`expect-actual-composable-capability` covers. Reach for that skill when the capability changes
during composition (window size, keep-awake, PiP mode); reach for this one when the answer is fixed
for the life of the process and the risk is a *stored* value outliving the check that was supposed
to gate it.

## Verifying it

Run from the app's `composeApp` module root.

Find the capability declaration and confirm both actuals answer with a constant, not a TODO:

```bash
grep -rn "expect fun isLyricsBlurSupported\|actual fun isLyricsBlurSupported" --include="*.kt" src
```

Pass condition: three hits — one `expect`, two `actual` — and reading each `actual` body takes one
line; neither throws or calls into a stub.

Find every call site and confirm none of them trusts a value computed elsewhere instead of calling
the function itself:

```bash
grep -rn "isLyricsBlurSupported()" --include="*.kt" src | grep -v "expect fun\|actual fun" | grep -vE ':[0-9]+:[[:space:]]*//'
```

Pass condition: one hit is the settings screen's own picker gate (`if (isLyricsBlurSupported())`,
no stored-style comparison — it only decides whether to offer the choice); every remaining hit is
its own `<style> == LYRICS_STYLE_APPLE_MUSIC && isLyricsBlurSupported()` conjunction sitting next to
the preference read it guards, in the composable that is about to draw. A hit that is a bare
variable with no local preference read is the gap this pattern exists to close — that call site
believed someone else already checked.
