---
name: local-listening-analytics
description: Build per-user listening or usage analytics entirely on-device — an append-only event table plus a denormalized per-contributor table that carries a copy of the timestamp, two completion thresholds instead of one, and bare ids in events enriched to titles and artwork only at read time. Use when adding a "your year in review" or top-items screen without a backend, when a time-window chart is slow, or when a chart is mysteriously shorter than the row count says it should be.
---

# Local analytics with no service behind it

Two tables. The **event** table is the record of what happened; the **contributor** table exists
only so the "top contributors" query never has to join:

```kotlin
@Entity("playback_event")
data class PlaybackEventEntity(
    @PrimaryKey(autoGenerate = true) val eventId: Long = 0,
    val timestamp: LocalDateTime = now(),
    val videoId: String = "",
    val albumBrowseId: String? = null,
    val durationSecond: Long = 0,
    val listenedSecond: Long = 0,
)

@Entity(
    tableName = "event_artist",
    primaryKeys = ["eventId", "channelId"],
    foreignKeys = [ForeignKey(
        entity = PlaybackEventEntity::class,
        parentColumns = ["eventId"], childColumns = ["eventId"],
        onDelete = ForeignKey.CASCADE,
    )],
    indices = [Index("eventId"), Index("channelId"), Index("timestamp", "channelId")],
)
data class EventArtistEntity(val eventId: Long, val channelId: String, val timestamp: LocalDateTime)
```

One item can have several contributors, so the second table is one row per (event, contributor).
Both rows are written in a single transaction, the child taking the id the parent insert returned:

```kotlin
@Transaction
suspend fun insertPlaybackWithArtists(...): Long {
    val timestamp = now()
    val eventId = insertPlaybackEvent(PlaybackEventEntity(timestamp = timestamp, ...))
    channelIds.forEach { insertEventArtist(EventArtistEntity(eventId, it, timestamp)) }
    return eventId
}
```

## Traps

**Leaving the timestamp off the child row forces a join on the hottest query you have.** Every
window in this feature is `WHERE timestamp BETWEEN :start AND :end`. With the copy, the top-
contributors query never touches the parent table at all:

```sql
SELECT channelId, COUNT(*) AS playCount FROM event_artist
WHERE timestamp BETWEEN :startTimestamp AND :endTimestamp
GROUP BY channelId ORDER BY playCount DESC LIMIT 100
```

The duplication is safe precisely because events are **append-only**: nothing ever edits a
timestamp, so the copy cannot drift. Write both from the same local variable inside the
transaction — reading the clock twice puts the two rows in different windows at a boundary.

**Index the pair the query actually filters and groups on, not each column separately.** The
composite `Index("timestamp", "channelId")` is what makes the window scan cheap; the `eventId`
index serves the foreign key and its cascade. Adding single-column indices instead looks
thorough and does not help this query.

**One threshold is not enough — you need a floor and a ceiling.** A play should not count at all
until the user has heard enough of it to mean something, and past a certain point it should count
as the whole thing rather than as the exact seconds:

```kotlin
val percent = currentPositionMillis / (song.durationSeconds * 1000f)
if (percent < 0.2f) return                         // too little: no event at all
val listened = if (percent >= 0.8f) song.durationSeconds.toLong()   // near the end: count it whole
               else currentPositionMillis / 1000
```

Without the floor, every skip is an event and the top-items chart becomes a chart of what the user
skipped past. Without the ceiling, a user who leaves before the last few seconds — which is almost
everyone — never records a complete listen, and total-time figures read low forever. Tune the two
numbers, but keep both.

**Store bare ids in the event; resolve them to titles and artwork at read time.** The event table is
the one that grows without bound, so every extra column is paid for thousands of times. Titles and
cover art also change, and a copy taken at play time slowly turns into a table of names that no
longer match anything. Keep the projections id-shaped:

```kotlin
data class TopPlayedTracks(val videoId: String, val playCount: Int, val totalListeningTime: Long)
data class TopPlayedArtist(val channelId: String, val playCount: Int)
```

**Enrichment quietly shortens the chart.** The natural way to join ids back to display data is
`mapNotNull { repository.getById(it.id) ?: return@mapNotNull null }` — and every id whose row was
since deleted disappears from the result. A "top 100" becomes a top 60 with no error and no gap in
the numbering. Decide the policy per list and make it explicit: this codebase drops unknown tracks,
but for contributors it falls back to a fetch before giving up. Whichever you choose, **verify by
comparing the returned list size against the count query** — if they differ, enrichment ate the
difference.

**Cap in SQL, not in Kotlin.** `LIMIT 100` inside the query means the database sorts and discards;
`.take(100)` after the fact means every matching row is materialized, converted and boxed first. At
a few thousand events the difference is invisible, which is exactly why the wrong one survives to
the point where it is not.

**Aggregate over the source rows, not over rows you already grouped.** Counting plays is
`COUNT(*)`; total time is `SUM(listenedSecond)`. Computing either in Kotlin from a page of events
gives the answer for that page only, and paged readers (`LIMIT`/`OFFSET`) are exactly what these
tables invite.

**Skip null grouping keys explicitly.** `albumBrowseId` is nullable, and a `GROUP BY` over it
produces a real "no album" bucket that outranks every actual album. The query says
`AND albumBrowseId IS NOT NULL` for that reason.

**Give the user an off switch and a delete path, and check the switch at the write site.** Events
accumulate forever otherwise. The gate belongs where the event is created — one preference read
before doing any work — and the delete paths are worth having in two shapes: a bounded prune
(`DELETE FROM playback_event WHERE timestamp < :cutoff`) and a full clear. The cascade on the child
table means clearing the parent clears both; a child table with no cascade would be left holding
every row you thought you deleted. **Verify the cascade** by counting both tables before and after,
not by reading the annotation.
