---
name: endless-queue-management
description: One StateFlow holds a growing playback queue but has two write paths on purpose — a full setter that resets derived snapshots, and continuation appends that write the backing field directly so those snapshots survive. Use when a feature keyed on "where the queue came from" stops working once the queue auto-extends, or before refactoring two queue write paths into one.
---

# Endless queue management

An endlessly extending queue starts as a finite list (an album, a playlist) and then grows: when the
source's continuation runs out and the "keep playing" setting is on, the app derives a follow-on
source from the last track and appends to the same queue.

That gives the queue state **two kinds of write**, and they must not be the same function:

```kotlin
// Path 1 — the setter. A NEW queue: replaces the data and recomputes what is derived from it.
override fun setQueueData(data: QueueData.Data) {
    _queueData.update { it.copy(data = data) }
    player.albumTrackIds =                      // derived snapshot, recomputed here
        if (data.playlistType == PlaylistType.ALBUM) data.listTracks.map { it.trackId }.toSet()
        else emptySet()
}

// Path 2 — appends. The SAME queue, longer: write the backing field, leave snapshots alone.
_queueData.update { it.addTrackList(newPage) }
```

The asymmetry is the design. `albumTrackIds` answers "did these two tracks come from the same album",
which a transition effect uses to step aside inside an album and resume at its edge. Auto-appended
tracks are *not* album tracks — that boundary is precisely where the effect should come back. Routing
appends through the setter would fold them into the set and disable the feature for the whole queue;
recomputing the snapshot on append would do the same thing one page at a time.

## Traps

**The asymmetry is invisible at the append site.** `_queueData.update { it.addTrackList(page) }`
reads like an ordinary state write. Nothing about it says "and deliberately not `setQueueData`",
so the next person to notice two write paths consolidates them, every test still passes, and the
derived feature silently stops. Comment **both** ends — the setter says why it recomputes, the
append says why it must not — and say what breaks, not just what the code does.

**Grep before you consolidate.** The question is never "do these two paths do the same thing to the
list" (they do) but "does either have a side effect the other must not run":

```
grep -n "_queueData.update\|_queueData.value\|setQueueData(" HandlerImpl.kt
```

Then read only the setter body. If it touches anything outside the flow, the paths are not
interchangeable regardless of how similar the list mutation looks.

**The snapshot must be a set of ids, not a count or a range.** "The first N tracks are the album" is
the tempting cheap version and it is wrong the moment shuffle runs, because shuffling reorders the
whole queue including whatever was appended. A set of ids is order-independent, which is exactly the
property needed. The membership test then has to hold for **both** tracks involved in a transition:

```kotlin
val bothFromAlbum = currentId in player.albumTrackIds && nextId in player.albumTrackIds
```

Testing only the current track keeps the effect suppressed across the album's last boundary — the
one place it should fire.

**Guard the re-seed or the queue appends forever.** Deriving the follow-on source id from the last
track and swapping it into the queue's own source id is what makes the next page load. Without a
check, the derivation runs again on the *new* last track and the queue never terminates:

```kotlin
val nextSourceId = deriveFollowOnId(lastTrack.trackId)
if (nextSourceId == queueData.value.data.playlistId) return   // already in that context
```

Compare the derived id against the queue's current source id — not against a boolean "already
extended" flag, which cannot tell a second legitimate extension from a repeat of the first.

**Derived snapshots do not survive a process restart.** The snapshot is computed at load time from
data the restore path may not carry — if the persisted queue row has no column for the source type,
restore falls back to a generic type and the snapshot comes back empty. The feature then works for
the rest of the session and not after a restart, which reads as flakiness. Either persist the
discriminator or document the limitation next to the restore code; the one thing not to do is leave
it unexplained.

**An append that changes the source id is still an append.** Swapping the queue's `playlistId` to the
follow-on source is a metadata change on the existing queue, so it belongs on the direct-write path
too. Sending it through the setter because "the source changed" resets the snapshot and is the exact
bug this whole split exists to avoid.

**`update {}` on a data class is not the same as constructing new state.** The append helpers
(`addTrackList`, `addToIndex`, `removeTrackWithIndex`) return a copied queue with the list replaced,
so they compose safely under `update`. A helper that returned a *fully default* copy with the list
filled in would silently drop the source id and continuation token, which shows up much later as a
queue that refuses to load more. Keep every helper a `copy` of the receiver.

## Verifying it

Play an album to the end with auto-extend on, and check three things in order: the queue grew past
the album's track count; the derived snapshot still holds exactly the album's ids (log its size —
it should not change when the queue does); and the feature it gates behaves differently at the last
album boundary than between two album tracks. If the snapshot size grew with the queue, an append
went through the setter.
