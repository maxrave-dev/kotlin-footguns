---
name: event-not-state-edge-for-one-shot-effects
description: Fire a one-shot celebration effect from the click that caused it, never from the state that click produced — an effect watching a boolean for a false→true edge cannot tell a tap from data arriving a beat later, so moving to an already-marked record fires the same edge. Covers the @Stable holder that owns live effects, judging the meaning at tap time, why the previous-value variable is a second source of truth, and keeping concurrent effects additive. Use when an effect plays by itself while skipping between records, when it celebrates something the user did not do, or when the first genuine tap after a screen returns is silently swallowed.
---

# One-shot effects are events, not state edges

A celebration burst, a haptic tick, a "saved!" toast — anything that must happen **once, because a
human did something**. The instinct is to watch the flag the action flips. That instinct is the bug.

```kotlin
// adapted — the holder owns every live effect and is the only thing that can start one
@Stable
class BurstState internal constructor(private val scope: CoroutineScope) {
    internal val bursts = mutableStateListOf<Burst>()

    /** One burst, now. Call from the tap that MARKS (i.e. while the toggle is still unmarked). */
    fun fire() {
        val burst = Burst(List(PARTICLES_PER_BURST) { randomSpark() })
        bursts += burst
        scope.launch {
            burst.progress.animateTo(1f, tween(BURST_DURATION_MS, easing = LinearEasing))
            bursts.remove(burst)
        }
    }
}

// remembered once above the modifier, so the scope outlives it:
//   val scope = rememberCoroutineScope(); val burst = remember { BurstState(scope) }
```

```kotlin
// adapted — the click handler is the only caller; the modifier only draws
onCheckedChange = {
    if (!record.marked) burst.fire()   // judged at TAP time, before the toggle round-trips
    onToggle()
},
```

## Traps

**A boolean cannot tell a tap from data arriving.** The version this replaced was the textbook edge
detector — `LaunchedEffect(checked) { if (checked && !previous) fire(); previous = checked }`. Then
the user skips to the next record. The marked flag for the new record lands from storage a beat
*after* the record itself does, so the same `false → true` transition runs and the UI celebrates a
mark nobody made. Skipping back does it again. Nothing at the state layer distinguishes the two
events, so no debounce, no `distinctUntilChanged`, no delay fixes it — only moving the trigger.

**Judge the meaning at tap time, not afterwards.** `if (!checked) fire()` reads the value that is
still current when the finger lands, which is the only moment "this tap is a mark" is knowable.
Waiting for the toggle to round-trip and then comparing gives you whatever the storage layer
settled on — and on an *un*-mark the flag also changes, so the effect fires for the opposite action.

**The previous-value variable is a second source of truth, and it lies after remounting.** `var
previous by remember { mutableStateOf(checked) }`, written from inside the effect that reads it,
re-initialises to the **current** value whenever the composable leaves and re-enters — a tab swap,
a configuration change, a list row scrolling out and back. It comes back already `true`, so the next
real tap is swallowed. Deleting the edge detection deletes the variable and the whole failure mode.

**The holder needs a scope that outlives the modifier.** `rememberCoroutineScope()` taken *inside*
the `Modifier.x()` extension dies with that modifier's composition, cancelling running animations
mid-flight and leaving orphaned entries in the list. Take the scope once where the holder is
remembered and pass it in. `@Stable` on the holder is what lets call sites hold it without dragging
their subtree into recomposition every time a burst starts or ends.

**`fire()` must be additive, not a toggle.** A list of live effects, each carrying its own
`Animatable`, lets a fast double-tap overlap two bursts. A single `isBursting` boolean restarts
instead, so the second tap visibly *cancels* the first — the exact opposite of what the user asked
for. Each entry removes itself when its animation completes, so the list needs no cleanup pass.

**Do not push the flag down into the modifier to "keep the call site clean".** Passing `checked`
into the draw modifier so it can decide reproduces the identical bug one layer lower, and now it is
inside a component every screen shares. The modifier's whole job is to draw what the holder holds.

**Two call sites means two holders, and that is correct.** A compact row toggle and a large
detail-screen toggle each `remember` their own state; there is no app-wide singleton and no key.
An effect is
scoped to the widget the finger touched, so a burst must not appear on a second copy of the same
control somewhere else on screen. The holder is cheap — a list and a scope reference.

**The same false edge exists on any state that is refreshed rather than pushed.** Anything reloaded
from storage on record change — a rating, a download flag, a follow status — arrives late and
arrives as a change. If an effect currently hangs off one of those, the fix is the same shape:
expose `fire()`, call it from the gesture, and let the state layer go back to describing what *is*
rather than announcing what *happened*.

**Optional decoration still belongs behind one gate, not per call site.** If the effect is a
setting the user can switch off, put that check inside the shared primitive rather than at every
`fire()` — see `gate-optional-effect-at-the-shared-primitive`.

**The glyph the toggle swaps is state-driven and should stay that way.** Only the *effect* moves to
the click handler; the filled/outlined icon pair still derives from the flag, because that is a
description of the current value rather than an announcement that it changed. If the two halves of
that pair render identically, the cause is upstream in how they were generated — see
`material-symbols-icon-system`.

**This rule is specific to one-shot effects.** A looping or reversible animation genuinely *is*
state-driven and should stay that way — see `hoist-the-flag-not-the-animation` for the shape that
belongs on a shared boolean, and `text-brush-shimmer-sweep` for one that must not be gated at all.

## Verifying it

```bash
# 1. every place a one-shot effect is started, with the two lines above it
grep -rn -B2 '\.fire()' --include='*.kt' .

# 2. effects hanging off a bare boolean — each is a candidate for the same defect
grep -rnE 'LaunchedEffect\((is|has|was|checked|selected|marked)[A-Za-z]*\)' --include='*.kt' .
```

1. → observed: every hit sits inside a click or checked-change lambda, guarded by the *pre-toggle*
   value. A `.fire()` reached from a `LaunchedEffect`, a `snapshotFlow`, or a `derivedStateOf` is
   the defect — it is being driven by state, and state has no idea who caused it.
2. → observed: a handful, none of them starting a one-shot effect. This grep is a triage list, not
   a verdict: a `LaunchedEffect` over a boolean is fine for *continuous* work (requesting focus,
   starting a poll). It is wrong only when what follows can happen exactly once and is user-visible.

Then, by hand — this is the discriminating test, and it takes fifteen seconds:

- Tap an unmarked toggle → exactly one effect.
- Tap it again to unmark → nothing.
- Now move to a record that is **already marked** → nothing. Move back and forth repeatedly →
  still nothing. An effect here means the trigger is still reading state.
- Leave the screen and return, then tap → the effect must still fire on the first tap.
