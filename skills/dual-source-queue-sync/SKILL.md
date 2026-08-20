---
name: dual-source-queue-sync
description: A UI-facing track list and the playback engine's timeline both hold the queue, so the UI list is re-derived from the engine timeline by media id after every engine-side change, refused when the sizes disagree, and mutated on both sides for user reorders. Use when the queue on screen plays in a different order than it shows, when shuffle scrambles the list but not playback, or before adding a second place that writes the queue.
---

# Dual-source queue sync

A player engine keeps its own timeline of media items — ids, uris, metadata — while the app keeps a
richer domain list for the UI: artwork, artists, like state, everything the engine has no field for.
Both are the queue. Only one can be the authority on **order**, and it has to be the engine, because
the engine is what actually plays next.

So the domain list is re-derived from the timeline after any engine-side change:

```kotlin
private fun reorderShuffledQueue(timeline: List<GenericMediaItem>) {
    val listTracks = queueData.value.data.listTracks
    if (timeline.isEmpty()) return
    timeline
        .mapNotNull { item -> listTracks.firstOrNull { it.trackId == item.mediaId } }
        .let { sorted ->
            if (sorted.size != listTracks.size) return          // partial timeline: do nothing
            _queueData.update { it.copy(data = it.data.copy(listTracks = sorted)) }
        }
}
```

Read it as a **join, not a merge**: the timeline supplies order, the domain list supplies content,
and nothing is invented on either side.

## Traps

**Re-deriving in the other direction is the bug this pattern exists to prevent.** Pushing the domain
list's order into the engine after a shuffle means computing the shuffle twice — once in the engine,
once in your code — and they will not agree, because the engine reshuffles on its own schedule. The
engine's order is not an opinion you can overrule; it is what the next track will be.

**The size check is a refusal, not a repair.** A timeline arrives partial in normal operation: mid
re-catalog, mid restore, while a chunk is still being inserted. Writing a "best effort" order from
a partial map silently drops the rows that had not been added yet. Returning instead costs nothing —
the change that completes the timeline fires the callback again — and the next full pass writes the
correct order.

**A missing early return on an empty timeline turns a clear into a wipe.** `mapNotNull` over an empty
list yields an empty list, and if the domain list is *also* empty at that moment the size check
passes and the write is harmless — but on the frame where the engine has cleared and the domain list
has not, it is a data loss. Guard `timeline.isEmpty()` explicitly at the top.

**Matching by id collapses duplicates onto the first occurrence.** `firstOrNull { it.trackId == ... }`
maps both timeline entries of a repeated track to the same domain object. The size check does *not*
catch this — one output per timeline entry, so the counts still match. It is benign when the two
entries are equal in content and a genuine loss when they are not (different playlist positions,
different per-entry state). If entries carry per-entry state, key the join on something entry-unique
rather than content-unique, and see `queue-index-vs-shuffle-space` for the related reason never to
resolve the *playing* entry by id.

**User reorders must mutate both sides, in that order.** Nothing re-derives the domain list from a
move the user made unless the engine emits — so the engine goes first and the list follows:

```kotlin
override suspend fun moveItemUp(position: Int) {
    moveMediaItem(position, position - 1)              // engine first
    val list = queueData.value.data.listTracks.toMutableList()
    list[position] = list[position - 1].also { list[position - 1] = list[position] }
    _queueData.update { it.copy(data = it.data.copy(listTracks = list)) }
    _currentSongIndex.value = player.currentMediaItemIndex   // re-publish, the move changed it
}
```

Mutating only the list gives a queue that shows the new order and plays the old one; mutating only
the engine flickers the row back to where it was, because the next re-derivation overwrites the UI.
The index re-publish at the end is easy to forget and is the whole reason a "current index" state
appears to update on drag and never on track change.

**Insert-at-a-position is two different integers the moment shuffle is on.** "Play next" is
`player.currentMediaItemIndex + 1` in the engine — timeline space — while the domain list is kept
in play order, so that integer indexes the list correctly only while shuffle is off. Convert to the
play-order position before the second write (the conversion is the engine's own shuffled walk — see
`queue-index-vs-shuffle-space`). Writing the engine's integer into both sides is the tempting
one-liner, and under shuffle it files the row against the wrong list position — a defect that stays
invisible for as long as some later full re-derivation happens to repair it.

**More than one callback triggers the re-derivation, and all of them must.** The timeline changes on
append and on remove; the *order* changes when shuffle is toggled without the timeline changing at
all. Both callbacks call the same function, plus every load path calls it explicitly after flipping
its state flag:

```
grep -n "reorderShuffledQueue" HandlerImpl.kt
```

Every load, page and error branch should appear. A branch that sets the queue to its terminal state
without reordering leaves the UI in the previous order until something unrelated fires.

**Re-deriving inside the composable does not scale.** Several surfaces render the queue — a sheet, a
mini player, an artwork pager — and each doing its own join means each has its own version of these
traps. Do the join once in the handler and let every surface collect the one list.

## Verifying it

Turn shuffle on with the queue visible and confirm the list reorders to match playback, not merely
that playback becomes random. Then drag a row, and check the list order, the engine order and the
now-playing marker all agree — read the engine order directly (`player.getCurrentMediaTimeLine()`)
rather than trusting the screen, since the screen is the side being tested.
