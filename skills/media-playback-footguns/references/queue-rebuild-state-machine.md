---
name: queue-rebuild-state-machine
description: A rebuild-state flag on the queue marks "being rebuilt" versus "stable" (two operative values, whatever the enum declares), so re-entrant load requests return early and nothing snapshots the queue while it is half-built. Use when pagination fires twice for one scroll, when a restored queue comes back missing the track that was playing, or when a loading state never clears after an error.
---

# Queue rebuild state machine

A queue that can be paged, re-cataloged and restored has moments when it is not a valid queue: the
list has been emptied and the rebuild is halfway through re-inserting entries. Anything that reads
it in that window reads garbage, and anything that *writes* to it races the rebuild.

One enum on the queue state object handles both problems:

```kotlin
data class QueueData(
    val queueState: StateSource = StateSource.STATE_CREATED,
    val data: Data = Data(),
) {
    enum class StateSource { STATE_CREATED, STATE_INITIALIZING, STATE_INITIALIZED, STATE_ERROR }
}
```

Every entry point that appends or rebuilds opens with the same line, and every exit sets it back:

```kotlin
override fun loadMore() {
    if (queueData.value.queueState == StateSource.STATE_INITIALIZING) return
    // ...
    _queueData.update { it.copy(queueState = StateSource.STATE_INITIALIZING) }
}
```

Re-entrancy protection and "don't snapshot me yet" fall out of the same flag, which is why it is
worth one enum rather than two booleans that can disagree.

## Traps

**Every entry point needs the check, and there are more of them than you think.** Page-forward,
fetch-related, bulk-append and full re-catalog are four different public functions that all mutate
the same list. A guard on one of them looks like it works, because the one you tested is the one
that used to double-fire. Enumerate them before trusting the guard:

```
grep -n "STATE_INITIALIZING" HandlerImpl.kt   # every set AND every check
```

Read the output as pairs. Any function that *sets* the flag but does not *check* it can still be
entered while another rebuild is running.

**Flip back on the error path too, not only on success.** This is the failure that survives a
release: a failed page leaves the flag at `INITIALIZING`, every later append returns early, and the
queue never loads again for the rest of the session — with no error on screen, because the early
return is silent. The error branch must do the same two things the success branch does:

```kotlin
is Resource.Error -> {
    _queueData.update { it.copy(
        queueState = StateSource.STATE_INITIALIZED,
        data = it.data.copy(continuation = null),   // and stop asking for the same page
    ) }
    reorderShuffledQueue(player.getCurrentMediaTimeLine())
}
```

Clearing the continuation token alongside the flag is what stops a broken page from being retried
on every scroll.

**Persistence must read the same flag.** A rebuild empties the list first and re-inserts the playing
track *last*, so a save that lands in the middle writes a queue that is missing the track the user
is hearing — and the next restore starts somewhere else entirely. The periodic save therefore has
the same condition as the guards:

```kotlin
if (trackId != null && queueData.value.queueState == StateSource.STATE_INITIALIZED) {
    persistQueue(queueData.value.data.listTracks)
}
```

Any *other* trigger for the same save — a lifecycle callback, a track-change listener — needs it as
well. A condition present on one of two trigger paths is dead code with no visible symptom.

**The flag lives on the queue object, not beside it.** Putting it in the same immutable state as the
list means one `update {}` changes both atomically, and a reader can never observe "flag says stable,
list is half-built". A separate `@Volatile var isRebuilding` reintroduces exactly that window.

**`INITIALIZING` is not a UI loading state.** Its timing follows the queue's integrity, not the
user's waiting: most load paths raise it before their network call even starts, a background append
the user never asked about raises it too, and at least one path fetches first and flips it only for
the mutation. Driving a spinner from it produces one that flashes at the wrong times and, after the
error trap above, one that never goes away. Keep the screen's loading state separate and derived
from the request, not from the queue.

**The rebuild's own reset is the reason for all of this.** A chunked re-catalog snapshots the list,
empties it, and re-adds in fixed-size chunks so a long queue does not rebuild in one pass:

```kotlin
val snapshot = ArrayList(queueData.value.data.listTracks)
_queueData.update { it.copy(data = it.data.copy(listTracks = arrayListOf())) }
snapshot.chunked(100).forEach { chunk -> /* re-add, then yield */ }
```

The currently playing item is captured by index up front and skipped inside the loop (`if (track ==
current) continue`) so it is never added twice — it is already in the player. That skip is also why
the restore path must pass an index that really points at the playing track; see
`playback-position-persist-restore`.

**Set the terminal state before the final reorder, not after.** The reorder re-derives the visible
list from the engine timeline, and a UI collector that wakes on that emission will read the flag. If
the flag is still `INITIALIZING` at that moment, whatever it gates skips one more cycle for no
reason. Order every exit the same way: flag first, then reorder.

## Verifying it

Scroll a long queue to its end fast enough to fire two page requests, then kill the process
mid-rebuild and restart. Two things must hold: the second request logged nothing (it returned early),
and the restored queue still contains the track that was playing. Then force a page to fail — cut
the network mid-scroll — and confirm a later scroll still loads. That last check is the one that
catches the missing error-path flip.
