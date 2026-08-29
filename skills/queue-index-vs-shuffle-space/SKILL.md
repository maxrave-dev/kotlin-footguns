---
name: queue-index-vs-shuffle-space
description: A player's "current index" is exposed to the UI but freezes on track change or highlights the wrong row once shuffle is on, because the engine's timeline order and the shuffled play order are two different index spaces. Use when the now-playing marker in a queue list is stuck, points one row off, or lights up every copy of a repeated track.
---

# Queue index vs shuffle space

A media engine holds items in **timeline order** — the order you added them. When shuffle is on it
plays them in a **shuffled order**, which is a permutation stored separately. Anything the engine
reports as "current index" is in timeline space. Anything a list on screen shows is in play order.
They are equal only while shuffle is off, which is why this bug ships.

The fix has two halves, both at the player layer, never in the list composable:

1. Publish the current index from the **track-change callback**, not only from queue mutations.
2. Expose **both directions** of the permutation and convert by position — never by matching ids.

```kotlin
interface MediaPlayerInterface {
    // play order -> timeline: "the user tapped row N of what they see"
    fun getUnshuffledIndex(shuffledIndex: Int): Int
    // timeline -> play order: "which row do I highlight"
    fun getShuffledIndex(timelineIndex: Int): Int
}
```

Each adapter already keeps the permutation to answer next/previous. Both directions are one lookup
into the two arrays it already maintains — see `custom-shuffle-order` for the pair.

## Traps

**The index state is written by every mutation except the one that matters.** A backing
`MutableStateFlow<Int>` typically gets assigned inside `moveMediaItem`, `removeMediaItem`,
`moveItemUp/Down` and a public setter — and *not* inside the track-transition callback. The flow
then holds the index of the last edit forever, so the marker moves when the user drags a row and
never when a song ends. To verify, grep every write of the backing field and check the transition
callback against that list:

```
grep -n "_currentSongIndex" HandlerImpl.kt      # every write site
grep -n "onMediaItemTransition" HandlerImpl.kt  # is it among them?
```

A public setter with **no callers** is the tell that someone meant to wire this and stopped.

**The index and the list it indexes live in different spaces.** `player.currentMediaItemIndex` is
timeline space; a UI list that was re-derived from the engine timeline (see `dual-source-queue-sync`)
is play order. Handing one to the other is correct with shuffle off and silently wrong with it on —
which is exactly why it survives review. Verify by turning shuffle on with a queue longer than the
screen and checking whether the highlighted row is the audible one.

**Resolving the playing row by matching ids breaks on duplicates.** The usual patch is:

```kotlin
// wrong: every copy of a repeated track matches
queue.listTracks.indexOfLast { it.trackId == player.currentMediaItem?.mediaId }
```

A queue can legitimately hold the same track twice — the user queued it again, or a continuation
page re-served it. Both copies then satisfy the predicate, so `indexOfFirst` highlights the wrong
one and `indexOfLast` highlights the other wrong one. Ids identify *content*; positions identify
*queue entries*. The playing entry is a position, so only a position can answer it. Prefer a
position the player already reports (its own order index) over a fresh id search — but validate it
against the id before trusting it, and fall back to the id search when they disagree: during a queue
rebuild the list and the player timeline are briefly out of step, and an unvalidated position can
point at some other track entirely.

**Only one direction of the map usually exists.** Adapters implement play-order → timeline first,
because tapping a row needs it: `player.seekTo(getUnshuffledIndex(tappedRow), 0)`. Nothing needs the
reverse until you draw the marker, so it is missing, and the id-matching hack above appears to fill
the gap. Verify before writing the hack: grep the player interface for an index-conversion function
and count the directions.

**The id you compare may not be the id you stored.** Engines are often handed a decorated media id —
a prefix marking which of several renditions of one track is loaded, or a cache key. A comparison
that works for plain audio then quietly fails for every decorated entry:

```kotlin
it.trackId == player.currentMediaItem?.mediaId?.removePrefix(VIDEO_MARKER)
```

That `removePrefix` is load-bearing. Any position-based fix removes the need for it entirely, which
is a good sign you picked the right fix.

**A shuffle permutation is not stable across queue edits.** Insert, remove and re-shuffle each
produce a *new* permutation, so an index cached in a view model outlives its meaning. Read it fresh
from the player on every use, or re-publish it from the callbacks that change the queue.

**Fixing it in the list composable looks like it works.** Deduplicating in the row's `isPlaying`
check — comparing an index the composable computed itself — makes the visible symptom go away in
the one screen you tested and leaves it in the queue sheet, the mini player and the artwork pager,
each of which computes its own. Any component that needs "which entry is playing" is a consumer of
one value the player layer should publish.

**Reconstructing an absolute index from a sliced sublist is a third index space, and it looks like
arithmetic rather than state.** A queue view that renders only the *upcoming* tracks slices the full
list first and then, at click time, adds the slice's own offset back to a local position to get an
index the player understands:

```kotlin
// adapted — names generalized; wrong: index is local to `upcoming`, offset is read again separately
val upcoming = queue.drop(offset)
itemsIndexed(upcoming) { index, track ->
    onClick = { actions.onSeekToQueueIndex(offset + index) }   // reconstructed, not carried
}
```

A sibling view of the exact same queue that renders the *whole* list has nothing to reconstruct —
`itemsIndexed` already hands it the absolute index — so it never shows this failure, which is the
first clue when one screen mishandles a tap and its twin does not. Attach the absolute index to each
element *before* slicing, so it survives the slice as data instead of being rebuilt from a value read
a second time:

```kotlin
// adapted — names generalized; the key is simplified (the real one concatenates index and track id)
val upcoming = queue.withIndex().drop(offset)   // index attached first, from the full list
itemsIndexed(upcoming, key = { _, item -> item.index }) { _, item ->
    onClick = { actions.onSeekToQueueIndex(item.index) }        // carried, not reconstructed
}
```

A stale or wrong offset can still cut the slice at the wrong place; carrying the index means it can no
longer make a visible row seek to a different track than the one it shows.

## Verifying it

Build a queue that contains one track twice, start it, and turn shuffle on. Then check, in order:
the marker follows a natural track end; it follows a skip; tapping a row plays *that* row (not its
duplicate); dragging a row keeps the marker on the audible track. All four read the same value, so
a fix that passes only some of them is still in the wrong index space.
