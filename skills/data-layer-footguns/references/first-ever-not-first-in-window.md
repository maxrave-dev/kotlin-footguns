---
name: first-ever-not-first-in-window
description: Counting entities encountered for the first time means taking MIN over the entity's whole history and asking whether that minimum lands inside the window — the natural version, which filters to the window and then groups, calls every entity new. Covers why the wrong query passes its first test, why the window belongs in HAVING rather than WHERE, what an unbounded scan needs from the index, and how a retention prune quietly redefines "ever". Use when a "new this period" figure tracks the distinct count exactly, when discovery rate is implausibly close to 1, or before writing any first-seen query.
---

# First-ever, not first-in-window

"How many entities did the user meet for the first time in this period" is not a question about the
period's rows. It is a question about each entity's whole history, asked once per entity:

```kotlin
// adapted — the window is in HAVING, deliberately, and the subquery scans everything
@Query("SELECT COUNT(*) FROM (SELECT entityId FROM event_entity GROUP BY entityId" +
       " HAVING MIN(timestamp) BETWEEN :startTimestamp AND :endTimestamp)")
suspend fun getNewEntityCountInRange(startTimestamp: LocalDateTime, endTimestamp: LocalDateTime): Int
```

The version everybody writes first puts the window one clause higher:

```sql
-- wrong: this is "distinct entities in the window", under a different name
SELECT COUNT(DISTINCT entityId) FROM event_entity
 WHERE timestamp BETWEEN :start AND :end
```

Both return a plausible integer, bounded by the same maximum, moving in the same direction as
activity.

## Traps

**The wrong query passes its first test, because early on the two answers are identical.** On a
fresh install every entity in the window genuinely is new, so the filter-then-group version is right
by accident for as long as the test data is short. It only diverges once there is a history to be
"not new" against — which is after release, on other people's devices.

**The tell is that discovery pins at 1.0.** Any rate of the form `new / distinct` computed from the
wrong query is `distinct / distinct`. It never varies, never responds to behaviour, and reads as a
suspiciously flattering statistic rather than as a bug. Watch for the ratio, not the count: the count
alone looks entirely reasonable.

**`WHERE` filters rows; `HAVING` filters groups — and only one of them can see outside the window.**
Moving the predicate into `HAVING` is what lets the group be formed from *all* of an entity's rows
before the question is asked. A predicate on the same column in both places is not a redundancy to
clean up: the `WHERE` version changes the answer.

**The aggregate has to be nested, and the nesting is not stylistic.** There is no way to ask
`COUNT(DISTINCT …)` and `HAVING MIN(…)` at one level; the grouped select must be a subquery whose
rows the outer statement counts. Some engines also require the derived table to carry an alias —
worth knowing before "simplifying" the extra `SELECT` away.

**This query deliberately scans history, so the index it wants is not the one the window queries
want.** The rest of this family filters on `timestamp` and benefits from a composite starting with
it. This one groups by the entity key across every row and then reads `MIN(timestamp)` per group, so
the covering shape is `(entityKey, timestamp)` — the same two columns in the other order. A
single-column index on the key alone gets the grouping and still visits the table for the minimum.
Check which index exists before assuming this query is cheap; it is the one query here whose cost
grows with total history rather than with the window.

**A retention prune silently redefines "ever".** Where old events are deleted on a cutoff — from the
parent `activity_event`, taking the `event_entity` rows above with it through the cascade —

```sql
DELETE FROM activity_event WHERE timestamp < :cutoffTimestamp
```

— `MIN(timestamp)` is the minimum over what *remains*, so an entity whose early rows have aged out
becomes new again, and a long-dormant favourite is counted as a discovery. That is a defensible
product answer and an indefensible surprise. If first-seen matters, keep it somewhere the prune does
not reach — a first-seen column on the entity, written once — rather than re-deriving it from a table
designed to be trimmed. At minimum, state the retention window next to the query so the figure is
read as "new within the last N months".

**Do not derive the distinct count from this one, or the other way round.** They are different
questions over different row sets, and a rate needs both. Two queries, both cheap, both explicit.

**The absolute definition is what makes period-over-period comparison mean anything.** "First-ever"
does not depend on how long the window is, so this period's figure and the previous one's are
comparable. A first-in-window figure scales with window length, which turns a delta between a 7-day
and a 7-day span into a real number and a delta across a granularity change into noise.

**Its mirror image is "lapsed", and it fails identically.** "Entities not seen since the window" is
`MAX(timestamp)` over the whole history, filtered in `HAVING` the same way; computed inside the
window it degenerates to "entities seen in the window", which is the *opposite* of what was asked and
still returns a believable number. Any question of the form *first / last / only, ever* is a `HAVING`
over an ungrouped history — and the wrong version is always the one where the window sits in the
`WHERE`.

## Verifying it

1. **Find every first-seen or "new" query and read which clause holds the window** — 5 hits here:

   ```bash
   grep -rn --include='*.kt' -E "MIN\(timestamp\)|HAVING|COUNT\(DISTINCT" . | grep -v '/build/'
   ```

   Every `MIN(...)` hit should sit in a `HAVING`; a "new" query whose only window predicate is in a
   `WHERE` is the distinct count wearing another name.

2. **Check what the prune reaches, because that is what "ever" means:**

   ```bash
   grep -rn --include='*.kt' -E "DELETE FROM [a-z_]*event" . | grep -v '/build/'
   ```

   Anything here bounds the history the `MIN` can see — including deletes that reach the table only
   by cascade.

3. **Run the discriminating test on real data.** Pick a window you know contains a long-standing
   favourite, and run both forms:

   ```sql
   SELECT COUNT(*) FROM (SELECT entityId FROM event_entity GROUP BY entityId
     HAVING MIN(timestamp) BETWEEN :start AND :end);
   SELECT COUNT(DISTINCT entityId) FROM event_entity WHERE timestamp BETWEEN :start AND :end;
   ```

   On any account with history the first must be strictly smaller. Equal numbers mean either a brand
   new dataset or the wrong query in production — and the same two statements, run over the earliest
   window you have, are how you tell those apart.
