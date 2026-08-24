---
name: nested-flag-settings-auto-disable
description: A child toggle gated by a parent condition must key its auto-disable effect on the parent's current value, grey out rather than hide when the gate is closed, and be gated again at the consumer — otherwise the child sticks ON with no way for the user to clear it. Use when a settings switch is stuck on, is greyed out while reading enabled, or keeps acting after its precondition is gone.
---

# A child toggle needs three defences, not one

Settings grow nested flags: a switch that only makes sense while some parent condition holds — a
credential present, a key entered, a capability available. The row is drawn disabled while the
parent is false, and that is where the trouble starts: *disabled* means the user can no longer
switch it off, so a child left ON when the parent goes false is now reachable only by code.

Three defences, at three layers, and each one covers a case the others do not:

1. **The row** turns its own child off when it sees the gate close.
2. **The state owner** clears it wherever the parent is withdrawn (`login-state-fans-out-to-settings`).
3. **The consumer** refuses to act on the child alone (`combine-two-flags-to-gate`).

The row is the one everybody writes first, and on its own it is the weakest of the three.

```kotlin
// adapted — names generalized
@Composable
fun SettingItem(
    isEnable: Boolean = true,
    switch: Pair<Boolean, (Boolean) -> Unit>? = null,
    onDisable: (() -> Unit)? = null,
    …
) {
    // Key on isEnable (not Unit) so the auto-disable fires whenever the gate flips to false
    // mid-session, not only on first composition.
    LaunchedEffect(isEnable) {
        if (!isEnable && onDisable != null) onDisable.invoke()
    }
    …
}
```

At the call site, the callback is guarded so it writes only when there is something to write:

```kotlin
// adapted — names generalized
SettingItem(
    switch = (childEnabled to { viewModel.setChildEnabled(it) }),
    isEnable = parentSatisfied,
    onDisable = { if (childEnabled) viewModel.setChildEnabled(false) },
)
```

## Traps

**`LaunchedEffect(Unit)` is the bug.** `Unit` never changes, so the effect runs once on entering
composition and never again. A parent that goes false *while the screen is open* — the user logs out
in the row above — leaves the child ON with the row now disabled, so the user cannot undo it. Keying
on `isEnable` restarts it on exactly that transition: one token, no visible change on the happy
path, which is why it survives review.

**A gate without a clear-callback is the silent half-fix, and it is the common one.** `isEnable`
alone changes only how the row *looks*: it dims, stops accepting taps, and the flag keeps whatever
it had — so the state you were preventing (flag on, precondition gone) is where you land, with the
control that could fix it now disabled. `onDisable` makes the row *act* rather than report, and it
is an **optional** parameter, so omitting it compiles and reviews cleanly. Withdrawing the
precondition mid-session leaves the flag set until a cold start happens while still withdrawn —
which is why this reproduces on someone else's device and not on yours.

**Guard the callback, or the correct key gives you a write loop.** The effect also runs on the very
first composition, and again on every flip *to* false. If `onDisable` writes unconditionally and the
settings store re-emits on write (most do), the write feeds recomposition which feeds another write.
An `if (childEnabled)` guard makes the callback idempotent and the loop impossible. Put the guard in
the callback, not the effect: `onDisable` is independent of the row's `switch` — a row may pass it
with no switch, or point it at another flag — so the row cannot know which flag to test.

**The gate value must be observed, not sampled.** `LaunchedEffect(isEnable)` restarts only when
`isEnable` actually changes, which requires it to come from a subscription — state collected from
the store — not a value read once when the screen was built. A correct key on a value that never
updates is indistinguishable from `Unit`, and the symptom is identical. Check the flag's provenance.

**Grey it out; do not hide it.** Hiding the row removes it from composition, so the auto-disable
effect *never runs at all* and the flag sticks with no recovery path in the UI. It also removes the
explanation: a user who cannot find a switch they remember turning on assumes the feature was
dropped. Keep the row and its subtitle, dim it, and disable interaction, not just appearance:

```kotlin
// adapted — names generalized
Box(Modifier
    .then(if (onClick != null && isEnable) Modifier.clickable { onClick() } else Modifier)
    .then(if (!isEnable) Modifier.greyScale() else Modifier)
) { … Switch(checked = …, enabled = isEnable) }
```

There is one legitimate exception: hiding an entire section the *build* cannot support — a
capability compiled out, credentials absent from this flavour. That is a static fact, not a runtime
gate, and there is no stuck flag to clear because the feature never existed here.

**In a lazy list, rows off-screen do not exist.** A settings screen is usually a lazy list, so an
effect inside a row runs only while that row is scrolled into view. Log out at the top and the child
toggle far below never composes, never runs its effect, and stays ON. This is the clearest reason
the row-level auto-disable cannot be the source of truth — it is a convenience for when the user is
watching, and nothing more.

**One symptom, three possible causes.** "Switch is stuck on" is produced by all three layers
failing, and by any one of them. Before changing the effect key, check whether the parent's
withdrawal path resets the child at all, and whether the consumer reads the child alone. Fixing only
the row leaves the flag stuck for every path that does not go through that screen.

## Verifying it

Find every effect that should be keyed on a gate but is not, and every gated row:

```bash
grep -rn "LaunchedEffect(Unit)" --include="*.kt" . | grep -v "/build/"
grep -rn -A6 "isEnable = " --include="*.kt" . | grep -v "/build/"
```

Keep the trailing `= ` on the second pattern so it returns rows that *declare* a gate, not every read.
For each hit in the first list, ask whether its body reads a value that can change while the screen is
open — those are the ones to re-key.

Then read every gate beside its clear, interleaved. An `isEnable` line with no `onDisable` under it
is a row that greys out and keeps its flag:

```bash
grep -n -A6 'isEnable = ' <settings-screen> | grep -E 'isEnable|onDisable'
```

Expect a gap, and judge it per line rather than by the count: a gate on a **static build fact**
(`isEnable = getPlatform() == …`, `isEnable = true`) has nothing to clear, and the rest of the gap is
the set of switches that grey out and stay set — a session, a key, a parent switch, each this bug.

Behaviourally, three runs, because they exercise three different layers:

- **Screen open** — turn the child ON, then withdraw the parent from a row on the same screen. The
  child must flip OFF while you watch, and the row must go dim and inert.
- **Screen open, row scrolled away** — same, with the child's row far off-screen. Scroll back: it must
  be OFF. If it is ON, the row-level effect is doing work the withdrawal path should have done.
- **Screen closed** — withdraw the parent elsewhere in the app, force-stop, relaunch, and read the
  stored value without opening settings. Still OFF means the state owner is correct.

Then confirm the consumer independently: set the child ON in storage by hand with the parent absent
and check the subsystem never starts — the defence that holds when the other two are bypassed.
