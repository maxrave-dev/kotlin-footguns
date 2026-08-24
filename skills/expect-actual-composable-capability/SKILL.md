---
name: expect-actual-composable-capability
description: Expose a device capability to shared Compose code as a @Composable expect function, with a full implementation on the platform that has it and a stub that returns the neutral value on the platform that does not. Covers the three shapes these take — a measurement, an effect with an undo, and a subscription read as state — and why a stub must still be correct. Use when shared UI needs a window measurement, a keep-awake flag or a windowing-mode state, when one platform stops the app the first time a screen paints, or when a shared screen behaves as if a capability is off on a platform that has it.
---

# Platform capabilities as composable expect functions

Three shapes cover almost everything, and they are worth telling apart because each fails
differently:

```kotlin
@Composable expect fun getScreenSizeInfo(): ScreenSizeInfo   // a measurement
@Composable expect fun KeepScreenOn()                        // an effect with an undo
@Composable expect fun rememberIsInPipMode(): Boolean        // a subscription, read as state
```

Every declared type is a **common** type: the measurement returns a small data class declared in the
shared module, not a platform window object. That is the whole point — callers in shared code stay
free of platform types, and the platform detail lives in exactly one file per target.

A capability one platform lacks still gets a full `actual`. It returns the neutral value:

```kotlin
@Composable actual fun rememberIsInPipMode(): Boolean = false   // this platform has no such mode
@Composable actual fun KeepScreenOn() { /* no display timeout to hold off here */ }
```

## Traps

**A stub must be correct, not absent.** `TODO()` in an `actual` compiles, ships, and stops the app
the first time that platform paints the screen — and because it sits behind a capability nobody tests
on the secondary platform, it reaches users. The neutral value is almost always obvious: `false` for
"is this mode active", an empty body for an effect, an empty list for a query. Write it, with the
reason on the same line.

**An empty `actual` is a decision, and it is not the same decision as "the platform cannot".** Both
look identical in the source. In the file inspected here the desktop target implements the
measurement fully — from ordinary shared Compose APIs — while leaving the keep-awake effect empty
under a note to implement it later. The full measurement proves nothing about the empty effect: they
are unrelated capabilities, and an empty body in that company says nobody wrote anything, not that
the platform cannot. Before concluding a platform lacks a capability, check that someone actually
looked — see `noop-actual-not-platform-limit`.

**The neutral return is a real answer, and callers act on it.** A stub returning `false` for a
windowing-mode query does not mean "unknown" — every `if` in shared code reads it as "not in that
mode" and lays out accordingly. Correct for a platform with no such mode; wrong for one that has it
and simply is not wired yet. If that difference matters, make the capability able to say "not
supported here", and make the callers handle it.

**`@Composable` belongs on the `expect` *and* on every `actual`.** It is part of the declaration, not
an implementation detail, and a mismatch is rejected — but the confusing case is the reverse: an
`actual` that does not need composition still carries the annotation, so do not "clean it off" the
stub.

**Effect-shaped capabilities must undo themselves.** The keep-awake actual sets the flag inside a
`DisposableEffect` and clears it in `onDispose`; the subscription actual registers its listener the
same way and removes it. A capability that sets a device-wide flag and never clears it outlives the
screen that asked for it, and the symptom appears somewhere else entirely. If an actual has no
`onDispose`, it is either genuinely stateless or a leak.

**A measurement needs a cache key, and the right key differs per platform.** The Android actual wraps
its computation in `remember(configuration)`, so it recomputes on configuration change and not on
every recomposition. The desktop actual reads a Compose-provided window value that is already
observable and needs no key. Copying the Android shape over as `remember(Unit)` freezes the value at
first composition and never updates on resize — a bug only the platform with resizable windows shows.

**A measurement reports the container, and your own chrome may be inside it.** A title bar drawn *by
the app*, above the content, is still part of the container the measurement reads — so the height it
returns includes a strip no layout can use, and every consumer computing "how much room have I got"
overflows by exactly that strip. It reads as a styling difference rather than a wrong number, and
anything gating on the measurement inherits it (`responsive-gate-size-not-platform`). Two things make
the correction survive: **one constant**, read by both the bar that draws the strip and the actual
that subtracts it, and a **conditional** subtraction:

```kotlin
// adapted — the flag is published once, at window creation, before the first frame
object WindowChrome { const val TITLE_BAR_HEIGHT_DP = 40; @Volatile var inWindowBar = false }
val chromeTopPx = if (WindowChrome.inWindowBar)
    with(density) { WindowChrome.TITLE_BAR_HEIGHT_DP.dp.roundToPx() } else 0
val contentHeightPx = (window.containerSize.height - chromeTopPx).coerceAtLeast(0)
```

The condition is not "which platform": the same platform draws its own bar in some configurations and
lets the system decorate the window in others, and a **system** decoration lives *outside* the
container size — subtracting there under-reports by the same amount. Check which windows call the
measurement, too: a secondary window with different chrome needs its own answer.

**The platform actual is where the activity hunt lives, and how it asks decides what happens when
there is none.** The Android file inspected here walks the context chain twice, in two functions: one
returns null when it runs out, the other throws. A composable built on the throwing walk takes the
screen down when hosted outside an activity — a preview, an embedded host, a test. Pick per
capability: a measurement can fall back to zero, a mode subscription probably cannot subscribe.

**Version branches and their suppressions live in the actual, and that is correct.** The Android
measurement carries `@Suppress("DEPRECATION")` for its older-API branch. Keeping that inside the
actual is what stops the suppression from applying to shared code, so resist hoisting it.

## Verifying it

Confirm every `expect` has an `actual` in every source set you build, by name:

```bash
grep -rhoE "expect fun [a-zA-Z][A-Za-z0-9_]*" --include="*.kt" . | sed 's/expect fun //' | sort -u | while read -r f; do
  printf '%-30s actual in: %s\n' "$f" "$(grep -rlE "actual fun $f\b" --include="*.kt" . | sed -E 's|.*/src/([^/]+)/.*|\1|' | sort -u | tr '\n' ' ')"
done
```

Read the column, not the count: a declaration listing fewer source sets than its siblings is either a
target that will not link or a hierarchy where one parent covers several — both worth knowing before
a release build tells you.

Then find the stubs, so each one is a decision you have seen:

```bash
find . -path "*/src/*Main/*" -name "*.kt" | while read -r f; do
  sed -E 's://.*$::' "$f" | grep -vE "^[[:space:]]*$" \
  | grep -A1 "actual fun " | grep -B1 "^[[:space:]]*\}$" \
  | grep -oE "actual fun [A-Za-z_][A-Za-z0-9_]*" | sed "s|^|$f  |"
done
```

Stripping comments first is what finds the ones written as a bare comment inside an otherwise empty
body — exactly how a stub is usually spelled. Each hit needs a reason next to it; the ones without
are candidates for `noop-actual-not-platform-limit`.

And confirm nothing ships an unwritten branch:

```bash
grep -rn -A4 "actual fun " --include="*.kt" . | grep -E "TODO\(\)|NotImplementedError"
```

Finally, for a measurement actual, confirm the chrome strip has **one** definition and **two**
readers — the composable that draws it and the actual that subtracts it:

```bash
grep -rn 'TITLE_BAR_HEIGHT\|_BAR_HEIGHT_DP' --include='*.kt' . | grep -v '/build/'
```

A literal height in the bar plus a separate literal in the actual is the drift this prevents; one
reader and no other is a subtraction nothing keeps honest.
