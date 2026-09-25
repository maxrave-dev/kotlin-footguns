---
name: stored-timestamp-is-a-local-wall-clock
description: A timestamp column written through an ORM type converter can hold the local wall clock encoded as if it were UTC — an exact round trip that is only correct through the converter, and the converter is chosen by the field's TARGET TYPE, so declaring a projection field as a raw number silently opts out and applies the offset a second time. Covers why every total still adds up, why the error is exactly zero on some machines, and why the fix is asking for the type the converter understands rather than picking a time zone. Use when an hour-of-day or day-of-week breakdown is shifted by your own offset while every count and sum is right, when a chart says people are most active at 3am, or before typing a stored time column as a number in a hand-written projection.
---

# The column holds a wall clock, not an instant

Two halves, each defensible on its own, written months apart. The producer captures the **device's**
wall clock:

```kotlin
// adapted
fun now(): LocalDateTime = Clock.System.now().toLocalDateTime(TimeZone.currentSystemDefault())
```

The ORM's converter then encodes that wall clock **as if it were UTC**, and decodes it the same way:

```kotlin
// adapted — an exact inverse of itself
@TypeConverter fun dateToTimestamp(date: LocalDateTime?): Long? =
    date?.toInstant(TimeZone.UTC)?.toEpochMilliseconds()

@TypeConverter fun fromTimestamp(value: Long?): LocalDateTime? =
    value?.let { Instant.fromEpochMilliseconds(it).toLocalDateTime(TimeZone.UTC) }
```

So the number in the column is **not** the instant the event happened. At +07:00 it is that instant
plus seven hours: the wall clock the user was looking at, carried on an epoch-millis scale. Read back
through the converter it is exactly right, and that is the only path on which it is.

## The mechanism, exactly

The converter is selected by the **target type of the field being filled**, not by the column, not by
an annotation you can see at the read site. One word in a projection decides which of these you get:

| projection field | converter | result |
|---|---|---|
| `val ts: LocalDateTime` | runs | the wall clock the user saw — **correct** |
| `val ts: Long` | skipped | the raw number, with no warning anywhere |
| `Long`, then decoded with the device zone | — | offset applied a **second** time |
| `Long`, then decoded with UTC | — | correct, but only because you already knew |

Nothing in the type system objects: the column really is an integer, `Long` really is what it holds,
and a millis-shaped field is the honest-looking choice in a hand-written result class.

## Traps

**Every total still adds up, which is why this ships.** The encoding shifts every row by the same
constant *while the device's offset is constant*, and preserves order within that, so `COUNT`, `SUM`,
`MIN`/`MAX` and any `BETWEEN` whose bounds went through the same converter are all unaffected. A DST
transition makes the shift piecewise: the repeated hour interleaves wrongly under `ORDER BY`, the
skipped hour holds no rows at all, and a difference of two stored values across the transition is off
by the offset change — the totals still add. Only **field extraction** — hour, date, day of week —
reads wrong, and only after the second decode. No assertion fails, no total looks off, no row is
missing. Measured here: the busiest hour landed at 03:00 instead of 20:00, and 34% of events were
attributed to the following day. What caught it was a human asking *who does this at three a.m.?*

**The error is exactly zero in one time zone, and that is usually the author's.** A double decode at
UTC+0 is a no-op. Written and reviewed in London, it is correct; shipped, it is wrong by the user's
own offset, in the direction that makes late-evening activity look like early morning.

**The fix is a type, not a time zone.** Ask for `LocalDateTime` in the projection and the decision
disappears along with the bug — there is no zone left to pick wrongly, and no reader has to know how
the column is encoded:

```kotlin
// adapted — the whole fix is the declared type of the first field
data class ActivitySample(
    @ColumnInfo(name = "timestamp") val timestamp: LocalDateTime,
    @ColumnInfo(name = "listenedSecond") val listenedSecond: Long,
)
```

"Decode the raw number with `TimeZone.UTC`" produces the same answer today and leaves the trap armed
for the next projection someone writes.

**Do not `fix` the column.** The round trip is exact and every existing query — every range bound,
every sort — already agrees with the encoding. Re-encoding to true instants is a migration that
shifts every historical row, and it is a different decision from the one in front of you. Fix the
read; schedule the encoding change on its own, if at all.

**Range bounds must travel the same path as the column.** Here they do: the range parameters are
declared `LocalDateTime`, so the converter encodes them the same way and the comparison happens on
one scale. A window built as raw millis and passed to a converted column silently searches a
shifted span — the same class of error, moved to the other side of the comparison, and just as
total-preserving.

**Wall-clock storage is right for calendar questions and wrong for elapsed-time ones.** "What did I
do on Tuesday" wants the wall clock; "how long has this token been valid" wants an instant, and this
encoding gets it wrong across any offset change. `kotlinx-datetime-helper-kit` covers the other
remediation — store instants, convert to local only for display — and the two are not
interchangeable. Mixing both in one table is worse than committing to either.

**A projection is not covered by the entity's tests.** Whatever exercises the entity round trip
exercises the converter; a hand-written result class for one query does not go near it. Every
`@Query` that returns a bespoke data class is a fresh chance to opt out, one field at a time.

**Wall-clock numbers from two devices are on two different scales.** Inside one database the encoding
is a constant shift, so everything is self-consistent. Across databases it is not: the same instant
written at UTC+7 and at UTC+0 produces numbers seven hours apart, so merging a backup from another
device — or from the same device after the user moved — interleaves the two histories in the wrong
order, silently and irreversibly. Nothing about a single-device restore reveals this; only a merge
does. If these rows will ever be merged or synced, the wall clock is the wrong thing to store and
this is the decision to revisit before the feature exists, not after.

## Verifying it

1. **Find the disagreement in one shot.** These are the only two zone rules that can exist, and a
   producer in the second list feeding a converter in the first is the shape described above:

   ```bash
   grep -rn --include='*.kt' -E "toInstant\(TimeZone\.|toLocalDateTime\(TimeZone\." . \
     | grep -v '/build/' | sed -E 's/.*(TimeZone\.[A-Za-z()]*).*/\1/' | sort | uniq -c
   ```

   Here: 5 × `TimeZone.UTC` (the converter and its siblings) against 15 × `currentSystemDefault()`
   (the producers). Two rules, one table.

2. **List every hand-written projection over a converted column, and read the declared type:**

   ```bash
   grep -rn --include='*.kt' -E "ColumnInfo\(name = \"timestamp\"\)" . | grep -v '/build/'
   ```

   Every hit must say `LocalDateTime`. One saying `Long` is the bug, silent and total-preserving.

3. **Run the discriminating query instead of reasoning about it.** Because the column is a local
   wall clock, millis-since-local-midnight is plain arithmetic — no zone function, no process
   dependency:

   ```sql
   SELECT (timestamp % 86400000) / 3600000 AS local_hour, COUNT(*)
     FROM activity_event GROUP BY local_hour ORDER BY 2 DESC LIMIT 3;
   ```

   Compare that histogram against what the screen draws. If the screen's peak is offset from this
   one by your own UTC offset, the read side decoded twice. If they agree, the projection is typed
   correctly — and this query is also the check to keep, because it keeps working after someone adds
   the next projection.
