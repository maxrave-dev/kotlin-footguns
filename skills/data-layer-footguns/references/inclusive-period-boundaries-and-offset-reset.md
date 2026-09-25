---
name: inclusive-period-boundaries-and-offset-reset
description: Pick one boundary convention for a stepping period navigator and hold it everywhere — a closed upper bound at 23:59:59 drops the last second's sub-second remainder, and half-open bounds handed to an inclusive BETWEEN double-count the shared instant — then reset the step offset whenever the granularity changes, because N periods back at one length is not N periods back at another. Covers clamping at the present, deriving the forward affordance from the same value, and why the current period's totals are not comparable to the previous one's. Use when a period navigator lands on the wrong span after switching granularity, when a boundary event is missing or counted twice, or when a first-of-the-month comparison reads catastrophically low.
---

# One boundary convention, and an offset that resets

The whole navigator is one function called with a different argument. `offset` counts periods
**backwards**: 0 is the current one, 1 the one before it.

```kotlin
// adapted
private fun rangeFor(range: DayRange, offset: Int): Pair<LocalDateTime, LocalDateTime> {
    val today = now().date
    val length = range.lengthInDays
    val end = today.minus(DatePeriod(days = offset * length))
    val start = end.minus(DatePeriod(days = length - 1))
    return start.atTime(0, 0) to end.atTime(23, 59, 59)
}
```

The comparison against the previous period is the same call with `offset + 1`, which is the entire
reason this shape is worth the indirection.

## Traps

**Two conventions in one feature is the normal state, not a hypothetical.** Measured in a single file
here: the period bounds are **closed** (`atTime(0, 0) … atTime(23, 59, 59)`), while the chart's day,
week **and month** buckets are half-open (start of the unit … start of the unit *after*, the month
one taking a December branch to get there). Both conventions are then handed to
queries whose predicate is `BETWEEN` — inclusive at both ends, 11 of them, and not one written as
`>= … <`. Each convention is defensible; together they guarantee that at least one of them is wrong,
and neither produces an error.

**A closed upper bound at 23:59:59 loses the rest of that second.** Sub-second precision does not
vanish because the bound has none: timestamps are stored to the millisecond, so events between
23:59:59.001 and 23:59:59.999 fall outside every period, forever, and are counted by no span at all.
It is roughly one part in 86 400 of the day, so it is invisible in a total and it is *not* invisible
in a "what happened last" list, where the missing row is the newest one. Use the true last
representable instant, or move to half-open and change the predicate with it.

**Half-open bounds fed to an inclusive predicate double-count the seam.** `[day, day+1]` under
`BETWEEN` counts an event landing exactly on midnight in both buckets. Rare, exact, and the kind of
thing that makes two charts on the same screen disagree by one.

**Half-open is the convention to standardise on, and it costs a predicate change.** `>= start AND
< nextStart` has no seam, no lost remainder, and no dependence on the storage precision. `BETWEEN`
cannot express it — so this is a query change, not a bounds change, and doing only half the job makes
things worse than either convention alone.

**The two conventions also disagree about a clock-change day.** "Start of day" resolved through a
zone returns the first *existing* instant, which is 01:00 where midnight does not exist; a bare
`atTime(0, 0)` returns a wall-clock value that no event can carry. Neither is wrong; they are simply
different days, twice a year, on one of the two paths.

**The offset is a count, so a granularity change carries it over silently.** Three periods back at
7 days is 21 days ago; three periods back at 90 days is nine months ago. Nothing type-checks
differently, nothing throws, and the user who switches from weeks to quarters lands somewhere they
never asked for. Reset to the present on every granularity change — it is one field and it is the
only answer that is always defensible:

```kotlin
// adapted
fun setDayRange(range: DayRange) {
    state.update { it.copy(dayRange = range, periodOffset = 0) }
    loadPeriod()
}
```

**Clamp at the present, and return early when the clamp bites.** Without the early return, every
press of a disabled-looking arrow re-issues the whole load — a dozen queries for a state that did not
change:

```kotlin
// adapted
fun stepPeriod(delta: Int) {
    val next = (state.value.periodOffset - delta).coerceAtLeast(0)
    if (next == state.value.periodOffset) return
    state.update { it.copy(periodOffset = next) }
    loadPeriod()
}
```

**Derive the forward affordance from the offset, never track it.** `val canStepForward get() =
periodOffset > 0` cannot disagree with the clamp. A separate boolean can, and will, on the frame the
granularity resets.

**The buckets *inside* a period have their own boundary rule, and it is a different one.** Stepping
decides which span is on screen; chopping that span into bars is a separate decision with its own
failure — unequal bucket widths drawing a longer bar for the wider one (`equal-buckets-or-no-buckets`).
The two interact only through the granularity change that resets the offset.

**A length field that is a lie for one member of the enum.** Fixed-length ranges step by days; a
calendar year steps by years and takes a different branch entirely — so its `lengthInDays` is
declared, unused, and wrong. Someone will use it. Either give the calendar member no length, or make
the stepping unit part of the enum rather than a number that only some members honour.

**The current period is truncated and the previous one is not, so every delta is biased low.** With
fixed lengths the day counts match but the last day is partial, which is a bias of at most one day in
`length`. With calendar granularity it is brutal: on 2 January the current period is two days against
a full previous year, and every figure on the screen reads as a collapse. Either label the current
period as in-progress, or compare like-for-like by truncating the previous period to the same
elapsed fraction — but decide, because "it recovers by the end of the month" is not a fix.

## Verifying it

1. **Find every boundary construction and read the convention on each:**

   ```bash
   grep -rn --include='*.kt' -E "atTime\(23|atTime\(0, 0\)|atStartOfDayIn" . | grep -v '/build/'
   ```

   Mixed `atTime(23, …)` and `atStartOfDay…` hits in one feature are the split described above.

2. **Count how the queries actually compare, because that decides which convention is safe:**

   ```bash
   grep -rn --include='*.kt' 'timestamp BETWEEN' . | grep -v '/build/' | wc -l
   grep -rn --include='*.kt' -E 'timestamp >= .* timestamp <' . | grep -v '/build/' | wc -l
   ```

   Eleven and zero here. Every `BETWEEN` is a closed comparison, so every half-open bound handed to
   one has a seam.

3. **Count the events the closed bound drops.** Where the stored column is millis of the local wall
   clock, this needs no zone function:

   ```sql
   SELECT COUNT(*) FROM activity_event WHERE timestamp % 86400000 > 86399000;
   ```

   Every row returned is an event no period contains. The same expression `= 0` counts the events
   sitting exactly on a bucket seam, which are the ones counted twice.

4. **Step, then switch.** Go three periods back, change the granularity, and read the span label. It
   must say the present. Then step forward at the boundary and confirm nothing reloads — a spinner
   there is the missing early return.
