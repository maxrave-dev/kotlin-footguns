---
name: derive-the-flag-dont-store-and-correct-it
description: A boolean that is a pure function of state already being collected gets stored as its own `mutableStateOf` anyway, seeded with a guess and corrected a frame later by a `LaunchedEffect` — so the first frame renders the guess, and later changing only the seed value does nothing once `rememberSaveable` has already saved the old one. Use when a UI element visibly flashes shown-then-hidden-then-shown on cold start, or when editing a `remember`/`rememberSaveable` initializer doesn't change what a warm app already shows.
---

# Derive it, don't store a guess and patch it

A value fully determined by state the composable already collects sometimes still gets its own slot —
`remember` or `rememberSaveable { mutableStateOf(...) }` — written to by a `LaunchedEffect` that
watches the real source and copies a derived answer into it. That slot is strictly worse than reading
the source directly, for the two reasons below: an initial guess renders before anything can correct
it, and the "obvious" fix to the guess does not reach a process that already saved the old one.

```kotlin
// adapted — trimmed to the two relevant declarations; both are otherwise verbatim
// before
var isShowMiniPlayer by rememberSaveable { mutableStateOf(true) }
// ...
LaunchedEffect(nowPlayingData) {
    isShowMiniPlayer = !(nowPlayingData?.mediaItem == null || nowPlayingData?.mediaItem == GenericMediaItem.EMPTY)
}

// after — nothing to be wrong independently of its source
val isShowMiniPlayer by remember {
    derivedStateOf {
        val item = nowPlayingData?.mediaItem
        item != null && item != GenericMediaItem.EMPTY
    }
}
```

## Traps

**A value nothing but its own derivation should ever write does not need a slot anything could write
to.** `isShowMiniPlayer` has exactly one legitimate value at every instant: whatever `nowPlayingData`
says. A separate `mutableStateOf` means the compiler no longer enforces that — it holds whatever the
last write left it holding, from whichever code path wrote last. Every trap below is a way that
separate value ends up disagreeing with its source.

**The effect meant to correct the guess cannot run before the first frame that already used it.**
Composition happens, then effects run — never the reverse. `rememberSaveable { mutableStateOf(true) }`
renders `true` on frame one, before `LaunchedEffect(nowPlayingData)` has run even once, so a cold
start shows the element on a screen that has not connected to any data yet. The effect then runs, sees
the real (absent) state, and flips it off; real data arrives shortly after and flips it back on. Three
renders — shown, hidden, shown — for a value that should have had one answer the whole time. This is
not a race: it is the ordering `LaunchedEffect` always uses, so it reproduces on every single launch.

**Changing the seed does nothing for any process that already saved the old value — a rotation, or a
return from the background after the system killed it.** The tempting one-line fix — seed
`mutableStateOf(false)` instead of `true` — changes nothing there, because `rememberSaveable`
*restores* a previously saved value across that recreation rather than re-running its initializer. A
warm app that already saved `true` under the old code goes on reading `true` regardless of what the
literal now says. This survival is narrower than "persists": a swiped-away task, a force-stop, or a
fresh install/update all discard the saved bundle and pick up the new seed immediately, same as a
cold start. When a fix to a `remember`/`rememberSaveable` default appears to do nothing, check it on
a warm app first — rotate the device, or background it and let the system reclaim the process — and
only trust "the fix works" once it also survives that, not just a cold reinstall.

**The same derived flag can exist as two separate copies, one per composable that draws the element.**
Here it did: a second, platform-specific composable rendered its own version of the same bar with the
same `rememberSaveable` + `LaunchedEffect` pair, verbatim. Fixing the first composable changed nothing
on the configuration that renders through the second, which reads as "the fix doesn't work" rather
than "the fix works everywhere except the file that still has the old copy." Grep for the pattern
project-wide, not just in the file the bug report points at.

**A nullable holder compared against both `null` and an empty sentinel is a sign the holder should
carry the sentinel too.** `nowPlayingData?.mediaItem == null || nowPlayingData?.mediaItem == EMPTY` is
two questions because `nowPlayingData` itself is nullable on top of `mediaItem` having its own empty
value — see `empty-sentinel-instance` for why that doubling happens and when it is avoidable.

## Verifying it

1. **Find the shape**: a `remember`/`rememberSaveable { mutableStateOf(...) }` boolean, and check
   whether its only assignment anywhere in the file sits inside a `LaunchedEffect` body. Match the
   declaration alone — a literal `rememberSaveable { mutableStateOf` on one line finds only 57 of the
   144 `by rememberSaveable` sites in this codebase, silently skipping every declaration that wraps
   its initializer onto its own line, which is exactly the shape the worked example above starts from:

   ```bash
   grep -rn "by rememberSaveable" --include="*.kt" . | grep -v "/build/"
   ```

   For each hit, look for a `LaunchedEffect` nearby assigning the same name from a value already in
   scope — that pairing, not the declaration alone, is the trap; plenty of legitimate `rememberSaveable`
   booleans are written from a click handler instead and are not this bug. Running this against the
   whole tree, not one file, is also the check for a second copy: a platform-specific composable can
   carry its own copy of the exact same pair, fixed by touching neither.

2. **Cold start, watch one frame.** Launch onto the screen that shows the element from a fully killed
   process. A value flashing present-absent-present in the first second is frame one using a guess.

3. **Warm-state check.** With app state already saved from a build that shipped the old seed, change
   only the `mutableStateOf` literal, then rotate the device — or enable Developer Options → Don't
   keep activities and background/foreground the app — instead of a cold relaunch, which would go
   through the swiped-away-task path and clear the saved value regardless of which fix is right. No
   visible change confirms the seed was never the bug — the field holding it is.
