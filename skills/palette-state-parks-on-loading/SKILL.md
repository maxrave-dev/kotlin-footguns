---
name: palette-state-parks-on-loading
description: A palette generator that flips its state to Loading before its own suspension point reports no colour for the entire duration of every generation, and a generation cancelled part-way leaves it Loading with nothing to restart it — so any surface reading the palette directly paints its null fallback. Covers why the effect must be keyed on the bitmap alone (or on nothing at all), why a "already done" flag assigned after a suspension is not a record of done, and why the last resolved colour has to be held separately. Use when a screen tinted from artwork is sometimes right and sometimes black, when the same item tints correctly on one visit and not the next, or when a derived colour scheme silently sits on its fallback.
---

# The palette holder has no "still valid" state

Extraction is asynchronous, and the state holder that wraps it has three states — Loading, Success,
Error — with `palette` readable **only** in Success. The order inside `generate()` is what makes this
sharp: it assigns Loading *before* it suspends. So for the whole duration of every generation the
palette reads null, and null resolves to whatever your fallback is — usually black.

That is fine when a generation always finishes. It stops being fine the moment one can be cancelled,
because a cancelled generation never assigns Success and nothing re-runs it. The holder sits on
Loading, `palette` stays null, and the surface stays on its fallback for as long as the screen lives.

## Traps

**A restarting effect is a cancelling effect, and the key decides what counts as a reason.** Keyed on
the bitmap, a generation is only ever interrupted by a newer bitmap — which is exactly when
interrupting is correct. Keyed on anything coarser, unrelated changes cancel it:

- a **state container** whose other fields (an extra media payload, lyrics, metadata) land after the
  artwork does — deterministic, because the later field always arrives later;
- a **URL** that goes null and comes back to the *same* value across a reload — the key changed
  twice, so the effect restarts twice, even though nothing about the image moved.

Both look like harmless extra keys. Neither adds correctness, and both add a cancellation window.

**The most robust form is an effect that never restarts.** Key on nothing, and let a snapshot flow
decide what a new bitmap is:

```kotlin
// adapted — generation lives in its own effect that cannot be restarted from outside
LaunchedEffect(Unit) {
    snapshotFlow { state.bitmap }
        .filterNotNull()
        .distinctUntilChanged()
        .collectLatest { paletteState.generate(it) }
}
```

`distinctUntilChanged` drops the same-bitmap re-emissions that a recomposition produces, and
`collectLatest` cancels only for a genuinely different bitmap. Nothing else in the composition can
reach it.

**A guard assigned after a suspension is not a record of "done".** The common shape is
`generate(bm); generatedFor = url` inside an `if (generatedFor != url)`. On the cancelled path the
assignment never runs, so the flag and the holder now disagree about what happened — and which way
that fails depends on polarity and timing, which is the worst property a guard can have. If a flag is
genuinely needed, set it before the suspension and clear it on failure, or drop it and let
`distinctUntilChanged` do the deduplication structurally.

**Hold the last colour that actually resolved.** This is the fix that makes the rest of it stop
mattering, and it is one extra piece of state:

```kotlin
// adapted — reading paletteState.palette straight paints black for the whole of every generate()
var pageBackground by remember { mutableStateOf(Color.Black) }
LaunchedEffect(paletteState.palette) {
    paletteState.palette?.let { pageBackground = it.toBackground() }
}
```

Every surface reads `pageBackground`, never the holder. A generation in flight then changes nothing
on screen, and a cancelled one costs the *update*, not the colour.

**Cancellation is not the only way the palette never arrives.** If the bitmap itself never
materialises — a remote image whose load fails, so the success callback never fires — the generator
is never called at all and the same fallback is shown, with a completely different cause and the same
symptom. Check which one you have before fixing the effect; see
`image-fallback-url-retry-in-composition`.

**"Sometimes black" is the signature, and it is why this survives.** A deterministic failure gets
fixed. This one depends on which async result wins a race, so it reproduces on some items, on some
navigations, on a cold start but not a warm one. Treat *any* intermittent artwork-derived colour as
this until proven otherwise, rather than as a rendering glitch.

**Everything downstream of the palette inherits the fallback.** A single accent is obviously wrong
when it is wrong. A whole tonal scheme derived from the seed degrades to a plausible-looking scheme
in the app's default colour, which reads as a design decision — see `artwork-seeded-dynamic-scheme`,
and `artwork-palette-theming` for what to do when extraction genuinely returns nothing. A screen
painting itself from artwork is also a screen that must be forced dark regardless of the app theme
(`force-dark-immersive-subtree`); the two omissions land on the same screens and look nothing alike.

## Verifying it

1. **List every generation and the key of the effect around it.** Read the key on each line, not the
   call:

   ```bash
   grep -rn --include='*.kt' -B 6 "State.generate(" . | grep -v '/build/' \
     | grep -E "LaunchedEffect|State.generate\("
   ```

   Thirteen generations here. Eight are keyed on `bitmap` alone and one on `Unit` with a snapshot
   flow inside; every other key is a cancellation source that needs a reason.

2. **Find surfaces reading the holder directly instead of a held colour:**

   ```bash
   grep -rn --include='*.kt' -E "paletteState\.palette|\.palette\?\." . | grep -v '/build/'
   ```

   Hits inside a `LaunchedEffect` that assigns a remembered colour are the correct shape. A hit
   inside a modifier, a `background(...)` or a theme call paints the fallback during every
   generation.

3. **Reproduce it deliberately rather than waiting for it.** Add a temporary `delay(2000)` before
   `generate(...)`, then navigate onto the screen and immediately trigger whatever else updates that
   effect's key — a reload, a range change, a second data field arriving. With a coarse key the
   surface stays on its fallback; with the bitmap-only key it resolves. Remove the delay afterwards.
