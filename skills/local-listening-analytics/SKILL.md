---
name: local-listening-analytics
description: Build per-user listening or usage analytics entirely on-device — an append-only event table plus a denormalized per-contributor table that carries a copy of the timestamp, two completion thresholds instead of one, bare ids in events enriched to titles and artwork only at read time, and every window query parameterised as (start, end) so "last N days" stays an argument. Use when adding a "your year in review" or top-items screen without a backend, when a time-window chart is slow, when a chart is mysteriously shorter than the row count says it should be, or when a per-contributor total refuses to add up to the period's own figure.
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

The duplication is safe because events are **append-only** — nothing edits a timestamp after the row
is written, so the copy cannot drift from the original — and both copies come from one local
variable; reading the clock twice, instead, could straddle a boundary between them. Index the pair
the query filters and groups on, not each column separately: the composite
`Index("timestamp", "entityId")` makes that scan cheap, while `eventId` alone serves the foreign key
and its cascade — single-column indices look thorough and do not help.

**One threshold is not enough — you need a floor and a ceiling.** A play should not count until the
user has heard enough of it to mean something, and past a point it should count whole:

```kotlin
val percent = currentPositionMillis / (item.durationSeconds * 1000f)
if (percent < 0.2f) return                         // too little: no event at all
val listened = if (percent >= 0.8f) item.durationSeconds.toLong()   // near the end: count it whole
               else currentPositionMillis / 1000
```

Without the floor, every skip is an event and the top-items chart charts what the user skipped past.
Without the ceiling, anyone leaving before the last few seconds never records a complete listen and
total-time reads low forever. Tune both, keep both.

**Store bare ids in the event, resolve them at read time — but that enrichment step quietly shortens
the chart.** The event table grows without bound, so every extra column is paid thousands of times
over, and titles/artwork copied at write time become names matching nothing once they change; keep
projections id-shaped (`(itemId, playCount, totalListeningTime)`, `(entityId, playCount)` —
hand-written, so also where a converted column loses its converter, see
`stored-timestamp-is-a-local-wall-clock`). The natural join back,
`mapNotNull { repository.getById(it.id) ?: return@mapNotNull null }`, silently drops every id whose
row was since deleted — a "top 100" becomes a top 60 with no error. This codebase drops unknown
tracks but fetches contributors first.

**Cap in SQL, not in Kotlin.** `LIMIT 100` in the query means the database sorts and discards;
`.take(100)` after the fact materializes, converts and boxes every row first — invisible at a few
thousand events, which is why the wrong one survives. The cap belongs to the *consumer* though: once
the same grouped query feeds a share-of-the-whole, the cut tail inflates it —
`unbounded-for-shares-capped-for-lists` is a second query with no `LIMIT`, not a merge.

**Parameterise the window from the start; "last N days" is an argument, not a query.** The first
screen only ever asks for the last 7, 30 or 90 days, so the obvious method is
`queryTopItemsLastXDays(n)` over a `timestamp > :cutoff` query. Write the general form instead:

```kotlin
// adapted — the only place "last X days" exists; there is no LastXDays SQL anywhere
suspend fun queryTopItemsLastXDays(x: Int) =
    databaseDao.queryTopItemsInRange(startTimestamp = now().beforeXDays(x), endTimestamp = now())
```

Measured here: **zero** `LastXDays` queries against thirteen `…InRange` ones — a period navigator
needing arbitrary spans, backward stepping and period comparison later needed no new query,
datasource or method, only a different argument: a feature instead of a migration
(`one-snapshot-per-period-not-many-flows` is the coherence it still needed).

**Aggregate over the source rows, and skip null grouping keys explicitly.** Counting plays is
`COUNT(*)`, total time `SUM(listenedSecond)`; computing either in Kotlin from a *page* of events
answers for that page only, and paged readers are what these tables invite. `groupId` is nullable
too, so `GROUP BY` over it outranks every real group with a "no group" bucket — hence
`AND groupId IS NOT NULL`. A per-contributor total the child row does not carry still costs a join —
and will not sum back up, both intentional: total time is per-EVENT, so reading it back per
contributor means a second query and result class, not a column bolted onto the lean one, and each
contributor of a shared item earns that item's FULL `listenedSecond`, not a fraction, so contributors
summed routinely exceed the period's real total on purpose; forcing them to agree reports a number
nobody asked for.

**Give the user an off switch and a delete path; check the switch at the write site** or events
accumulate forever. Deletes need two shapes — a bounded prune (`DELETE FROM activity_event WHERE
timestamp < :cutoff`) and a full clear; the cascade takes the child with the parent, so only the
prune costs elsewhere: "first ever seen" via `MIN(timestamp)` now means *since the cutoff*
(`first-ever-not-first-in-window`).

## Verifying it

Run these from the root of the repository containing your DAO — from this skills repo both commands
below print 0 and half-look like a pass.

1. **Confirm the window is a parameter, not a query shape** — 0 and 13 here. A `LastXDays` hit in a
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
