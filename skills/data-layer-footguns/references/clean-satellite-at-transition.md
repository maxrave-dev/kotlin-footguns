---
name: clean-satellite-at-transition
description: Deleting the dependent rows that exist only to serve a state at the exact transition that ends that state — rather than leaving them to a later bulk sweep — and why a foreign key cannot do this for you when only a flag changes. Reach for it when tables grow without bound and nothing ever deletes from them, when rows survive whose parent no longer justifies them, or when a bulk cleanup has to reason about rows whose parent has already been swept away.
---

# Clean up satellites at the transition

Some rows exist only because of a state on another row: notifications for a followed creator, a
new-release tracking row for a subscription, draft rows for an open editor. When that state ends,
those rows have no reason to exist — and nothing in the schema knows that.

Do the delete where the state changes:

```kotlin
// adapted
override suspend fun updateFollowedStatus(artistId: String, followedStatus: Int) {
    localDataSource.updateFollowed(followedStatus, artistId)
    if (followedStatus == 0) {
        localDataSource.deleteNotificationsByArtistId(artistId)
        localDataSource.deleteReleaseTrackingRow(artistId)
    }
}
```

Before that `if`, unfollowing flipped a flag and nothing else. Every satellite row of every artist
ever unfollowed survived, forever, with no code path anywhere that would remove it.

## Traps

**A flag flip is not a delete, so no cascade fires.** `ON DELETE CASCADE` triggers on a deleted
parent row. Here the parent row is still there — only its state changed — so the engine has no
mechanism to offer and there is nothing to configure. If a state can be turned off, the cleanup for
it is application code you have to write.

**A bulk sweep keyed on "parent row missing" misses the parents that survive.** A cache sweep does
not delete every parent that left the state — it spares any that still backs other kept data — and
a satellite rule shaped as "delete rows whose parent is gone" never reaches the satellites of those
spared, still-unfollowed parents. Key the sweep on the **state**, not on the row's existence, and
run it *after* the parent sweep so deleted and spared parents are both covered:

```sql
DELETE FROM notification
 WHERE artistId NOT IN (SELECT artistId FROM artist WHERE followed = 1);
-- artistId is declared NOT NULL here; over a nullable column this needs IS NOT NULL
-- (that failure has a sibling skill: sql-not-in-nullable-trap)
```

Among the parents the sweep spared, the unfollowed ones now lose their satellites and the followed
ones keep theirs — which is the wanted answer, and only works because the predicate asks about the
follow rather than about the row.

**Shipping the transition cleanup does not repair existing databases.** Every user who unfollowed
before the fix still carries the rows. Keep the bulk sweep permanently as the migration path for
those, and say so in a comment — otherwise the sweep looks redundant once the transition cleanup
exists and someone deletes it.

**Branch on the new value, not on "the value changed".** `if (followedStatus == 0)` runs the cleanup
only when the state actually ends. A branch on "changed" also fires on the follow direction, and one
on "was previously 1" needs a read you would otherwise not do.

**Put it behind the state change, not behind the button.** If the cleanup lives in a screen's click
handler, every other writer of that column — a settings toggle, a sync pass, an undo, a bulk action —
silently skips it. It belongs in the single repository method that owns the transition, and every
caller has to route through that method.

**Do not extend it into deletes the user can undo.** Only rows that are genuinely worthless after the
transition qualify. Anything the user could reasonably expect back on re-following (their own notes,
a read/unread marker they set) is data, not a satellite — leave it, or the cleanup becomes a
data-loss bug that only shows up after a round trip.

## Verifying it

- **Count the stranded rows.** Run the sweep's predicate as a `SELECT COUNT(*)` on a database that
  predates the fix. On a database that has only ever run the fixed build it should be zero after any
  unfollow; on an older one it is positive and never decreases — that difference is the proof the
  transition cleanup is doing something.
- **Find every writer of the state column before believing the coverage.** Search for assignments to
  the column and for calls to the update method, and confirm each path reaches the cleanup. This is
  the check that catches the click-handler placement above.
- **Round-trip it by hand.** Turn the state off, inspect the satellite tables, turn it back on, and
  inspect again. Both halves matter: the first proves the delete runs, the second proves you did not
  delete something the user expected to survive.
- **Watch the table's row count over a long session**, not just across one action. An unbounded table
  is the symptom that started this, and the only observable one before the fix.
