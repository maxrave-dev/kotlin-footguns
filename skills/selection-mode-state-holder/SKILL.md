---
name: selection-mode-state-holder
description: A small @Stable holder for multi-select in a Compose list — keyed by stable id rather than list position, with every mutation funnelled through one private method so a hard cap on the selection size cannot be bypassed, plus the toggle/clear/select-all semantics that make the two gestures read differently. Use when building bulk actions over a list, when selections drift onto the wrong rows after a reorder or a page load, or when a cap holds for tapping rows but not for select-all.
---

# A multi-select state holder

One `@Stable` class, held by the screen, read by the row. Two pieces of observable state — whether
the mode is on, and which ids are picked — and exactly one way to add to the second:

```kotlin
// adapted
@Stable
class SelectionState(private val limitMessage: String) {
    var isActive by mutableStateOf(false); private set

    private val _selected = mutableStateListOf<String>()
    val selected: List<String> get() = _selected
    val count: Int get() = _selected.size
    val isFull: Boolean get() = _selected.size >= MAX_SELECTION

    fun isSelected(id: String): Boolean = _selected.contains(id)

    /** The only way into [_selected] — which is what makes the cap hold. */
    private fun add(id: String): Boolean {
        if (id.isBlank() || _selected.contains(id)) return true
        if (isFull) { notifyLimitReached(limitMessage); return false }
        _selected.add(id)
        return true
    }
}
```

`start(id)` (long press) turns the mode on and adds one. `toggle(id)` (tap while active) removes or
adds. `toggleSelectAll(ids)` fills up to the cap, or clears. `exit()` turns the mode off and empties.
Every **addition** among them goes through `add` — that is the choke-point, and it is only about
growth. Removals stay direct (`toggle` calls `remove`, select-all and `exit` call `clear`), because
nothing has to be checked on the way out.

## Traps

**Track ids, not list positions.** An index identifies a row only until the list changes shape, and
the lists that get multi-select are exactly the ones that do: paged lists that grow underneath you,
reorderable lists where a drag renumbers everything between the source and the destination. After
either, an index-keyed selection is silently pointing at different rows than the ones the user
ticked — and a bulk action then runs on those. If the same screen also supports drag-to-reorder (see
`lazy-list-drag-reorder`), this is not a hypothetical.

**One private mutator is what makes the cap real.** There are three ways into the selection — long
press, tap, select-all — and a cap checked at each of them is a cap that survives until someone adds
a fourth. Route all three through one private `add`, check there, and the check cannot be bypassed
by the path nobody remembered. The same argument applies to normalisation: `add` rejects blanks and
duplicates, so no caller has to.

**The mutator returns a Boolean so bulk callers can stop.** Select-all loops; without a return value
it either keeps calling past the cap (firing the "limit reached" feedback once per remaining item —
dozens of toasts from one tap) or it needs its own copy of the cap check, which is the duplication
the choke-point exists to prevent:

```kotlin
// adapted
for (id in candidates) { if (!add(id)) return }
```

**Test "everything is already picked" against what select-all *would* pick, not against the whole
list.** Select-all doubles as deselect-all: pressing it again when its work is already done should
clear. But it only ever picks the first `MAX_SELECTION` candidates, so comparing against the full
input list can never report "all picked" on any list longer than the cap — and the button becomes
one-way. Compare against the truncated set:

```kotlin
// adapted
val candidates = ids.filter { it.isNotBlank() }.distinct()
val everythingReachableIsPicked =
    candidates.isNotEmpty() && candidates.take(MAX_SELECTION).all { _selected.contains(it) }
if (everythingReachableIsPicked) { _selected.clear(); return }
```

**Clearing by tap and clearing by select-all must end differently.** Tapping rows off one at a time
until none are left reads as *leaving* the mode, so `toggle` calls `exit()` when it empties the list
— otherwise the user is stranded in an action bar with nothing to act on and no obvious way out.
Pressing select-all a second time reads as *starting over*, so it clears the list and deliberately
stays active. Same end state, two intentions; collapsing them makes one of the two gestures feel
broken.

**Expose counts as derived getters over the snapshot list, not as separate state.** `count` and
`isFull` computed from `_selected.size` cannot go stale, and a header reading `state.count`
subscribes to the snapshot list and recomposes on change without holding the list itself. A cached
`var count` beside the list is a second source of truth for the same fact.

**`@Stable` is a promise the class has to keep.** It tells the compiler that every publicly readable
property changes only through the snapshot system, so composables reading this holder may be
skipped when it has not changed. `isActive` is `mutableStateOf` and `_selected` is
`mutableStateListOf`, so the promise holds. Add one plain `var` that the UI reads and the annotation
becomes a lie: the UI stops recomposing when that field changes, with no warning anywhere.

**A `remember`ed holder keyed on a localised string is rebuilt when the locale changes.** Building
the limit message with a string resource and keying `remember` on it is convenient, but it means the
selection is dropped on a language switch — and plain `remember` drops it on configuration change
and process death anyway. If a selection must survive those, hold it in the screen's view model
instead and pass the message in at the call.

**Reporting the limit from inside the holder is a deliberate trade, not an accident.** Putting the
notification next to the check keeps the cap in one place; the cost is that the state class now
depends on a UI notification API and cannot be exercised off the main thread. If that matters,
have `add` return a richer result and let the screen render it — but keep the *decision* in the
holder, or the cap fragments again.

## Verifying it

1. **Exactly one write path into the backing list.**
   `grep -n '_selected\.' <holderFile>`
   → observed: one `_selected.add(...)`, inside the private mutator; one `_selected.remove(...)` in
   `toggle`; two `_selected.clear()` (select-all and exit); everything else is a read
   (`.size`, `.contains`, `.isEmpty`). A second `.add` anywhere means the cap has a bypass.
2. **The cap constant is referenced by the check and by the truncation, and nowhere re-derived.**
   `grep -rn '<capConstant>' --include='*.kt' .`
   → observed: the declaration, the `isFull` comparison, the `take(...)` in select-all, the message
   formatting, and two references from documentation comments. A numeric literal for the same limit
   at any call site is a second cap.
3. **Every screen that turns the mode on also wires the toggle.** Compare the two per-file counts:
   ```bash
   grep -rc 'selectionMode =' --include='*.kt' . | grep -v ':0$' | sort
   grep -rc 'onSelectToggle =' --include='*.kt' . | grep -v ':0$' | sort
   ```
   → observed: the two listings match file for file and count for count, except one file whose
   `selectionMode` belongs to an unrelated file-picker API — worth knowing, because that is what a
   false positive looks like here. A genuine mismatch is a screen that renders checkboxes nothing
   can tick. Note the patterns carry no trailing space: a wrapped argument puts the value on the
   next line, and `'onSelectToggle = '` silently misses those.
4. By hand: select up to the cap, then press select-all. Nothing should be added and exactly one
   notification should appear — a burst of them means a caller is looping past a mutator whose
   return value it ignores.
5. By hand on a reorderable list: select two rows, drag a third between them, and confirm the same
   two rows are still ticked. If the ticks moved, the holder is keyed on positions.
