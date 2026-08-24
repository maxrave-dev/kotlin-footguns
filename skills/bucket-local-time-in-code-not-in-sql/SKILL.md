---
name: bucket-local-time-in-code-not-in-sql
description: Group events by local hour or local day in application code from one raw scan, not in SQL — the engine's local-time modifier answers from the process time zone rather than the user's, and four local-time aggregates mean four scans that can disagree with each other. Covers where the line sits between an aggregate that belongs in SQL and one that does not, and what the single scan has to return to stay correct. Use when an hour-of-day or weekday chart differs between platforms or between a device and a desktop build, when adding a fourth "group by day" query, or before writing a date function into a query string.
---

# Derive local buckets from one scan

Four of a period's figures — the hour histogram, the busiest day, the per-day counts and the total —
are all questions about the same rows of an append-only event table (`local-listening-analytics`),
and all four are questions about **local** time. Written as SQL aggregates that is four scans, each
needing a local-time conversion inside the engine. Written as one query returning the raw pairs, it
is one scan and no conversion at all:

```kotlin
// adapted — the only query in this family that returns rows rather than a number
@Query("SELECT timestamp, listenedSecond FROM activity_event" +
       " WHERE timestamp BETWEEN :startTimestamp AND :endTimestamp")
suspend fun getSamplesInRange(startTimestamp: LocalDateTime, endTimestamp: LocalDateTime): List<Sample>
```

```kotlin
// adapted — one pass fills all four
val hours = IntArray(24)
val perDay = mutableMapOf<LocalDate, Int>()
var listened = 0L
samples.forEach { s ->
    hours[s.timestamp.hour]++
    perDay[s.timestamp.date] = (perDay[s.timestamp.date] ?: 0) + 1
    listened += s.listenedSecond
}
val busiest = perDay.maxByOrNull { it.value }
```

## Traps

**The engine's local-time modifier reads the *process* time zone.** SQLite's `'localtime'`, and the
equivalents elsewhere, resolve against whatever the OS hands the process — the `TZ` environment
variable, a service account's zone, a container's default of UTC. That is not reliably the user's
zone, it is not the same on a desktop build as on a phone, and it changes under you when the
deployment does. The same query then returns a different histogram on two machines looking at
identical data, with nothing to blame.

**Four aggregates are four scans that can disagree.** Each runs at its own moment; a write landing
between the second and the third puts the total and the busiest day in different worlds. One scan is
one consistent view of the period as well as being cheaper.

**Only the *bucketing* moves — most aggregates still belong in SQL.** The line is whether the
grouping key is a **local field**. Distinct counts, top-N lists, first-ever minimums, joins and
share-of-whole counts have no local component: they group by an id, or compare timestamps to each
other on whatever scale both sides share. Those stay in the engine, where they cost one row of
result instead of every row. Here, one range query of twelve returns raw rows; the other eleven are
aggregates and are right to be.

**The scan returns rows, so it grows with the window.** A histogram query returns 24 numbers whatever
the period; this returns one row per event. Project it down to the columns the derivation actually
needs — two here — and know what the widest supported window costs before shipping a wider one.
Where a period can be unbounded, this is the wrong shape.

**The raw scan is also the emptiness check.** Reading it first means an empty period can return
early, before the seven aggregates this snapshot issues are sent at all — one round trip instead of
eight, on exactly the periods a new user is looking at. Count what the snapshot issues, not what the
family holds: the rest of it is issued by other loads on the same screen, which the return misses.

**The samples must be typed so the ORM's converter still runs.** Declaring the timestamp field as a
raw number to "keep the projection cheap" hands back an encoding the derivation then has to interpret
by hand, and the local hour is precisely the figure that goes wrong when it interprets it wrongly —
see `stored-timestamp-is-a-local-wall-clock`. Ask for the date-time type; the hour and the date then
read straight off it with no zone arithmetic anywhere in the path.

**Do not push the local question into an index either.** An index over a computed local field bakes
one zone into stored bytes, and is silently wrong for every user in another one — and stale for the
original user after a rule change. The zone belongs at the edge, applied once, in code.

**Every new local bucket is a line in the existing loop, never a new query.** This is where the
pattern erodes: someone adds "busiest weekday" or "weekend versus weekday" and writes a fifth
aggregate, because one more query looks smaller than touching working code. It is not — it is a
fifth scan, a fifth chance to pick a zone, and the first of the answers that can disagree with the
other four. The rule that keeps this stable is mechanical: *if the grouping key comes off a local
date-time, it is a line in the `forEach`.*

**Say so at the declaration.** A query returning raw rows next to eleven returning numbers reads like
someone who had not learned to aggregate. One comment naming the reason — local grouping, one scan,
zone-independent — is what stops it being "optimised" into four `GROUP BY`s later.

## Verifying it

1. **Every local-time function in every query string.** The correct outcome for this family is that
   the only hit is a comment saying why there is none:

   ```bash
   grep -rn --include='*.kt' -E "localtime|strftime\(" . | grep -v '/build/'
   ```

   One hit here, at the query that deliberately does not use it. Any hit inside an actual query
   string is a figure whose answer depends on where the process runs.

2. **The shape of the range family — how many return rows, how many return numbers:**

   ```bash
   grep -rn --include='*Dao*.kt' -E "suspend fun (get|query)[A-Za-z]*InRange" . | grep -v '/build/'
   ```

   Twelve here (32 unscoped, the rest being the datasource, repository and interface forwarding the
   same twelve). Read the return type of each: exactly one returns a `List` of raw samples, and it
   should be the one the local buckets are derived from. A second row-returning query in the same
   family usually means the same scan is being paid for twice.

3. **Run the derivation against the engine, on the same data.** Compute the hour histogram in code,
   then compute it in SQL with the engine's local-time modifier, and compare. They agree only when
   the process zone happens to equal the user's — so run it once with `TZ=UTC` and once with
   `TZ=Asia/Ho_Chi_Minh` in the environment. The code answer must not move; the SQL answer will.
