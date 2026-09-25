---
name: distinct-by-key-reset-cancel-per-item
description: Per-item pipelines that key on the item id with distinctUntilChangedBy, cancel the previous item's in-flight work before starting the next, and reset the visible state before filling it — so nothing from the previous item can appear under the new one. Use when a detail screen briefly shows the last item's artwork or text, when a slow response overwrites a newer one, or when a field stays populated after moving to an item that has no value for it.
---

# One pipeline per item: distinct, cancel, reset, fill

A screen bound to "the current item" gets a stream of state objects, most of which are the same item
with a changed field. Each real item change has to fan out into several independent lookups, and
each of those can outlive the item that asked for it.

Three moves, in this order, at the top of the collector:

```kotlin
// adapted — names generalized
viewModelScope.launch {
    handler.currentItemState
        .distinctUntilChangedBy { it.entity?.id }        // 1. only on a real item change
        .collectLatest { state ->
            perItemJob?.cancel()                         // 2. abandon the previous item's work
            _currentItem.value = state
            state.entity?.let { item ->
                _screenData.value = ScreenData(          // 3. reset to a clean object…
                    title = item.title,
                    artist = item.artists.orEmpty().joinToString(", "),
                    thumbnailUrl = null,
                    extraA = null,
                    extraB = null,
                )
            }
            state.mediaItem.let { now ->                 // …then fill, cheap fields first
                _extra.value = null
                fetchA(now.id)
                fetchB(now.id)
                _screenData.update { it.copy(thumbnailUrl = now.artworkUri) }
            }
        }
}
```

Reset-then-fill is what makes the previous item's data unreachable rather than merely stale: fields
the new item has no value for are `null` from the first frame, instead of holding the old item's
value until a response arrives that may never come.

## Traps

**Cancelling a handle that is never assigned is a no-op, and it looks exactly like protection.** One
per-item handle here is declared and cancelled at the top of this collector, and nothing else — no
line anywhere *assigns* it, so that `cancel()` has never cancelled anything. Its one remaining
mention is a **second** `cancel()`, commented out inside the launcher, which reads at a glance like
the missing assignment. Nothing broke, because the fetch re-checks the item id before writing:

```kotlin
// adapted — names generalized, branch condition verbatim
is Resource.Success if (data != null && currentItemState.value?.mediaItem?.id == requestedId) -> {
    _extra.value = data
}
```

That check is the load-bearing guard, not the cancel. Verify the handle before trusting it:

```
grep -rn "perItemJob" --include="*.kt" src/
```

A field whose only lines are a declaration and a `cancel()` is managing nothing. See
`named-job-lifecycle-discipline`.

**Keep the write-time identity check even when the cancel does work.** Cancellation is cooperative:
a coroutine suspended in a network call is not cancelled until it reaches a cancellable suspension
point, and a response already in hand can still be written on the way out. The id comparison at the
point of assignment costs nothing and is the only guard that holds regardless of timing. Where the
source flow is not cancellable by default, mark it — `.cancellable()` before the terminal operator —
so the collector actually stops at the next emission.

**`distinctUntilChangedBy` on the wrong key is worse than no key.** Keying on the whole state object
defeats the point (every field change is an item change). Keying on something that repeats across
items — a title, a position in the list — makes two genuinely different items look identical and the
pipeline never runs for the second. Key on the stable identifier that the fetches themselves use.

**A nullable key makes different items indistinguishable.** `distinctUntilChangedBy { it.entity?.id }`
keeps one previous key and compares only *consecutive* emissions, so a real item → empty → the same
item again still delivers all three; only a run of nulls collapses. The hazard runs the other way:
two genuinely *different* states that both key to `null` are one key to the operator, so a move from
one entity-less state to another never runs the pipeline. If "no item" is a state the screen must
react to, either make it a distinct key or handle clearing on a separate path.

**A per-item pipeline needs `collectLatest`, and a per-item *sub-fetch* needs its own handle.**
`collectLatest` cancels the collector body when a newer item arrives, but work the body *launched*
into the enclosing scope keeps running. Each sub-fetch therefore owns a field and does the same
cancel-then-assign:

```kotlin
// adapted — names generalized, guard and ordering verbatim
private fun fetchB(id: String?) {
    if (id != _b.value?.id && !id.isNullOrEmpty()) {
        _b.value = null            // reset this slice before the request
        bJob?.cancel()
        bJob = viewModelScope.launch { repository.bFlow(id).cancellable().collectLatest { … } }
    }
}
```

**Reset wipes fields the new item does have.** Building a fresh state object with everything cleared
is correct only if the same write immediately re-populates what is already known — title, artist,
whatever came in with the item. Splitting "clear" and "populate known fields" into two writes puts a
blank frame on screen between them, and on a conflating state holder they can also collapse into
each other unpredictably; see `stateflow-conflation-inverts-state`.

**Order the fill so the cheapest data lands first.** Local fields (title, artist, artwork URL,
flags) come straight off the item and should be written before any suspending call. A single
`update { it.copy(...) }` per slice keeps each arrival independent, so a slow lookup never clobbers a
fast one that landed in the meantime.

## Verifying it

Switch items faster than the slowest lookup returns — hold the "next" control down through several
items and stop. Then check three things, in this order: the visible state matches the item you
stopped on; no field still holds a value from an item you passed through; and the log shows the
lookups for the intermediate items either cancelled or discarded at the id check.

Repeat with the slowest lookup made artificially slow (a delay in the repository is enough). If the
final screen fills with data belonging to an item you passed, the id re-check at write time is
missing — the cancel alone was never going to cover that window.
