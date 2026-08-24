---
name: local-listening-analytics
description: Build per-user listening or usage analytics entirely on-device — an append-only event table plus a denormalized per-contributor table that carries a copy of the timestamp, two completion thresholds instead of one, bare ids in events enriched to titles and artwork only at read time, and every window query parameterised as (start, end) so "last N days" stays an argument. Use when adding a "your year in review" or top-items screen without a backend, when a time-window chart is slow, or when a chart is mysteriously shorter than the row count says it should be.
---

# Local analytics with no service behind it

Two tables. `activity_event` records what happened; `event_entity` — one row per (event,
contributor) — exists only so the "top contributors" query never has to join:

```kotlin
@Entity("activity_event")
data class ActivityEventEntity(
    @PrimaryKey(autoGenerate = true) val eventId: Long = 0,
    val timestamp: LocalDateTime = now(),
    val itemId: String = "", val groupId: String? = null,
    val durationSecond: Long = 0, val listenedSecond: Long = 0,
)

@Entity(
    tableName = "event_entity", primaryKeys = ["eventId", "entityId"],
    foreignKeys = [ForeignKey(ActivityEventEntity::class, ["eventId"], ["eventId"], onDelete = CASCADE)],
    indices = [Index("eventId"), Index("entityId"), Index("timestamp", "entityId")],
)
data class EventEntityRow(val eventId: Long, val entityId: String, val timestamp: LocalDateTime)
```

One item can have several contributors, so the second table is one row per (event, contributor),
written in the same transaction and taking the id the parent insert returned:

```kotlin
@Transaction suspend fun insertEventWithEntities(...): Long {
    val timestamp = now()      // ONE read of the clock, shared by both rows
    val eventId = insertActivityEvent(ActivityEventEntity(timestamp = timestamp, ...))
    entityIds.forEach { insertEventEntityRow(EventEntityRow(eventId, it, timestamp)) }
    return eventId
}
```

## Traps

**Leaving the timestamp off the child row forces a join on the hottest query you have.** Every window
here is `WHERE timestamp BETWEEN :start AND :end`; with the copy, the top-contributors query never
touches the parent table at all:

```sql
SELECT entityId, COUNT(*) AS playCount FROM event_entity
WHERE timestamp BETWEEN :startTimestamp AND :endTimestamp
GROUP BY entityId ORDER BY playCount DESC LIMIT 100
```

The duplication is safe because events are **append-only**: nothing edits a timestamp, so the copy
cannot drift. Both come from one local variable — reading the clock twice straddles a boundary.

**Index the pair the query filters and groups on, not each column separately.** The composite
`Index("timestamp", "entityId")` makes that scan cheap; `eventId` serves the foreign key and its
cascade. Single-column indices instead look thorough and do not help.

**One threshold is not enough — you need a floor and a ceiling.** A play should not count until the
user has heard enough of it to mean something, and past a point it should count whole:

```kotlin
val percent = currentPositionMillis / (item.durationSeconds * 1000f)
if (percent < 0.2f) return                         // too little: no event at all
val listened = if (percent >= 0.8f) item.durationSeconds.toLong()   // near the end: count it whole
               else currentPositionMillis / 1000
```

Without the floor, every skip is an event and the top-items chart charts what the user skipped past.
Without the ceiling, anyone leaving before the last few seconds — almost everyone — never records a
complete listen and total-time reads low forever. Tune both, keep both.

**Store bare ids in the event; resolve them to titles and artwork at read time.** The event table
grows without bound, so every extra column is paid for thousands of times — and titles and artwork
change, so a copy taken at write time becomes a table of names matching nothing. Keep projections
id-shaped: `(itemId, playCount, totalListeningTime)`, `(entityId, playCount)`. A projection is
hand-written, so it is also where a converted column loses its converter
(`stored-timestamp-is-a-local-wall-clock`).

**Enrichment quietly shortens the chart.** The natural join back to display data is
`mapNotNull { repository.getById(it.id) ?: return@mapNotNull null }` — every id whose row was since
deleted disappears, and a "top 100" becomes a top 60 with no error and no gap in the numbering.
Decide the policy per list: this codebase drops unknown tracks, but for contributors fetches first.

**Cap in SQL, not in Kotlin.** `LIMIT 100` in the query means the database sorts and discards;
`.take(100)` after the fact materializes, converts and boxes every row first. At a few thousand
events that is invisible, which is why the wrong one survives until it is not. But the cap belongs to
the *consumer*: once the same grouped query feeds a share-of-the-whole, the cut tail inflates it —
`unbounded-for-shares-capped-for-lists` is a second query with no `LIMIT`, not a merge.

**Parameterise the window from the start; "last N days" is an argument, not a query.** The first
screen only ever asks for the last 7, 30 or 90 days, so the obvious method is
`queryTopItemsLastXDays(n)` over a `timestamp > :cutoff` query. Write the general form instead:

```kotlin
// adapted — the only place "last X days" exists; there is no LastXDays SQL anywhere
suspend fun queryTopItemsLastXDays(x: Int) =
    databaseDao.queryTopItemsInRange(startTimestamp = now().beforeXDays(x), endTimestamp = now())
```

Measured here: **zero** `LastXDays` queries in the DAO against twelve `…InRange` ones — so when a
period navigator arrived much later (arbitrary spans, stepping backwards, every period compared
against the one before) the top lists needed no new query, datasource or repository method. It was a
different argument. One extra parameter the day you write it is the difference between a feature and
a migration the day you need it; coherence is the part it *did* need
(`one-snapshot-per-period-not-many-flows`).

**Aggregate over the source rows, and skip null grouping keys explicitly.** Counting plays is
`COUNT(*)`, total time `SUM(listenedSecond)`; computing either in Kotlin from a *page* of events
answers for that page only, and paged readers are what these tables invite. And `groupId` is
nullable, so a `GROUP BY` over it makes a real "no group" bucket outranking every actual group —
hence `AND groupId IS NOT NULL`.

**Give the user an off switch and a delete path, and check the switch at the write site.** Events
accumulate forever otherwise. The gate belongs where the event is created — one preference read
before any work — and deletes want two shapes: a bounded prune (`DELETE FROM activity_event WHERE
timestamp < :cutoff`) and a full clear. The cascade means clearing the parent clears both; without
one the child holds every row you thought you deleted. Note what the prune costs elsewhere: "first
ever seen" from `MIN(timestamp)` now means *first since the cutoff*
(`first-ever-not-first-in-window`).

## Verifying it

1. **Confirm the window is a parameter, not a query shape** — 0 and 12 here. A `LastXDays` hit in a
   DAO is a second query someone must generalise later; above the DAO it is the shortcut calling the
   range form, which is what you want:

   ```bash
   grep -rn "LastXDays" --include='*Dao*.kt' . | grep -v '/build/' | wc -l
   grep -rn -E "suspend fun (get|query)[A-Za-z]*InRange" --include='*Dao*.kt' . | grep -v '/build/' | wc -l
   ```

2. **Verify the cascade by counting, not by reading the annotation.** Run
   `SELECT (SELECT COUNT(*) FROM activity_event), (SELECT COUNT(*) FROM event_entity);` either side
   of a parent delete; a child count that does not move is a cascade that is not there.

3. **Compare each enriched list's size against its own count query** — a "top 100" rendering 60 rows
   while the count disagrees is enrichment eating the difference, and the only detection for it.
