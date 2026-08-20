---
name: custom-shuffle-order
description: Replacing a media engine's default shuffle order so that tracks added mid-playback land contiguously after the current one instead of being scattered through the rest of the queue. Use when "play next" or an appended continuation page ends up in random positions while shuffle is on, or when writing any custom shuffle order and needing the insert/remove/clone contract to stay consistent.
---

# Custom shuffle order

A media engine keeps items in timeline order and plays them through a **shuffle order**: a
permutation array `shuffled`, where `shuffled[playPosition] = timelineIndex`. The engine asks it for
next/previous and for the first/last entry, and asks it to *clone itself* whenever the queue changes.

The default implementation shuffles newly inserted items into random positions across the whole
remaining order. That is defensible for "shuffle the album" and wrong for everything else: a user
who hits "play next" wants the track next, and a queue that grows by appending a continuation page
wants that page to stay in one block. Replacing it is a small class:

```kotlin
class BetterShuffleOrder(private val shuffled: IntArray) : ShuffleOrder {
    // reverse map: indexInShuffled[timelineIndex] = playPosition
    private val indexInShuffled = IntArray(shuffled.size).also {
        for (i in shuffled.indices) it[shuffled[i]] = i
    }

    override fun getNextIndex(index: Int): Int {
        val next = indexInShuffled[index] + 1
        return if (next < shuffled.size) shuffled[next] else INDEX_UNSET
    }
}
```

Two arrays, always built together: the forward map answers "what plays at position N", the reverse
map answers "where in the play order does timeline item N sit". Every operation below has to leave
both consistent.

## Traps

**The reverse map is derived, never edited in place.** Every constructor path must rebuild
`indexInShuffled` from `shuffled` — deriving it in the property initialiser, as above (an `init`
block does the same job), makes that structural rather than a rule someone has to remember. An insert or remove that patches only the forward array
leaves the reverse one describing the previous queue, and the symptom is not a failure: playback
simply jumps to an unrelated track at the next boundary.

**Insert has to do two different things at once, and it is easy to do only one.** Existing entries
whose *timeline* index sits at or after the insertion point shift up by the insert count; separately,
the new entries must be placed at a *play* position next to the pivot. Both, or the order is
corrupt:

```kotlin
override fun cloneAndInsert(insertionIndex: Int, insertionCount: Int): ShuffleOrder {
    val pivot = if (insertionIndex < shuffled.size) indexInShuffled[insertionIndex]
                else indexInShuffled.size
    val out = IntArray(shuffled.size + insertionCount)
    for (i in shuffled.indices) {
        val timelineIndex = shuffled[i].let { if (it > insertionIndex) it + insertionCount else it }
        if (i <= pivot) out[i] = timelineIndex else out[i + insertionCount] = timelineIndex
    }
    for (i in 0 until insertionCount) {
        if (insertionIndex < shuffled.size) {
            out[pivot + i + 1] = insertionIndex + i + 1   // insert after the pivot entry
        } else {
            out[pivot + i] = insertionIndex + i           // append past the end: no pivot entry
        }
    }
    return BetterShuffleOrder(out)
}
```

Both branches on `insertionIndex < shuffled.size` are load-bearing: appending past the end has no
pivot entry to read, so the new items start at `pivot` rather than `pivot + 1` and their timeline
indices are not shifted. Dropping the append branch either leaves an uninitialised `0` in the middle
of the order — which plays the first track again at a random moment — or writes one slot past the
end of the array.

**Remove has to renumber survivors, not just drop entries.** Timeline indices above the removed
range all shift down by the removed count. Dropping the entries and leaving the rest as-is produces
an order that points past the end of a shrinking queue.

```kotlin
newShuffled[i - foundSoFar] =
    if (shuffled[i] >= indexFrom) shuffled[i] - removedCount else shuffled[i]
```

**These are `cloneAnd*`, not `insert`/`remove`.** The engine holds the old instance while building
the new timeline and may discard the result. Mutating `this` and returning it appears to work until
a queue edit is rolled back, and then the order describes a queue that never existed. Return a new
instance from every one of them, including `cloneAndClear`.

**The start index must be swapped to the front, not just included.** Shuffling a queue while a track
plays must keep that track first, or turning shuffle on restarts playback from something else:

```kotlin
if (startIndex != -1) {
    val pos = shuffled.indexOf(startIndex)
    shuffled[0] = shuffled[pos].also { shuffled[pos] = shuffled[0] }
}
```

**Generate the permutation with the inside-out variant, not `List.shuffle()` on a copy.** The
inside-out Fisher–Yates fills and permutes in one pass over `0 until length`, which keeps the
allocation to the single output array:

```kotlin
for (i in 0 until length) {
    val swap = (0..i).random()
    shuffled[i] = shuffled[swap]
    shuffled[swap] = i
}
```

**Every entry point must survive an empty order.** `getFirstIndex`, `getLastIndex` and
`cloneAndInsert` are all reachable with `shuffled.size == 0` — a queue cleared while shuffle stays
on. Each needs an explicit branch (`INDEX_UNSET`, or a fresh order built from the insert count);
an unguarded `shuffled[0]` there stops playback with an out-of-range read.

**Un-shuffling does not restore your custom insert positions.** The engine reverts to timeline order
when shuffle is turned off, so a track that was "played next" reappears wherever it was inserted in
the timeline. Deciding whether that is acceptable is a product call — it is not something the
shuffle order can fix, because timeline order is the other authority.

## Verifying it

Log the array itself, not the behaviour: print `shuffled` after each clone and check by hand that
it is a permutation of `0 until size` (no repeats, no gaps) with the inserted block contiguous right
after the current play position. A corrupted order is almost always a repeated or missing value, and
that is visible in one printed line long before it is visible as a skipped track.

---
*Provenance: the design shown here follows the GPL-3.0 `BetterShuffleOrder` from the Auxio project
(Alexander Capehart). Reproducing the code — rather than the pattern — in your own project carries
that license and its attribution with it.*
