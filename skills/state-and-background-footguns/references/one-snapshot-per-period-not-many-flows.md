---
name: one-snapshot-per-period-not-many-flows
description: Return a whole period's figures as one immutable snapshot from a single suspend call, rather than as a dozen independent flows the screen has to line up — a screen comparing two spans needs each span coherent, and separate emissions let a count from this period render beside a total from the last. Covers when a single-emission flow is a suspend function in costume, which derived figures belong on the snapshot, and why a rate needs the denominator a human means. Use when a comparison screen briefly shows mismatched numbers while reloading, when adding the tenth flow to one screen's repository, or when two places compute the same average differently.
---

# One period, one snapshot

A screen that shows "this span, and how it compares to the last" asks for exactly two things. Make
that the shape of the call — a suspend function returning a value, called twice:

```kotlin
// adapted
suspend fun getPeriodStats(startTimestamp: LocalDateTime, endTimestamp: LocalDateTime): PeriodStats
```

```kotlin
// adapted — a matched pair, never two independently-arriving streams
val (start, end) = rangeFor(range, offset)
val (prevStart, prevEnd) = rangeFor(range, offset + 1)
val current = repository.getPeriodStats(start, end)
val previous = repository.getPeriodStats(prevStart, prevEnd)
state.update { it.copy(stats = Success(current), previous = previous.takeIf { p -> !p.isEmpty }) }
```

Inside, the snapshot is one immutable value carrying every figure the period has — counts, totals,
distinct counts, the per-hour histogram, the derived behaviour axes — with defaults that mean
"empty period" rather than "not loaded yet".

## Traps

**Separate flows let two periods render at once.** Ten flows arrive in ten orders at ten moments. On
every reload — a step backwards, a granularity change — the screen holds a mixture: the new count
against the old total, a delta computed between a period and itself. It is transient, so it looks
like a rendering glitch rather than a data bug, and it never reproduces on demand.

**A single-emission flow is a suspend function wearing a costume.** The shape below is the default
this drifts into, and it buys nothing: it emits once, completes, and every caller does
`.firstOrNull()` or `.collect { }` around a value that was never going to change:

```kotlin
// adapted — thirteen of these in one repository; the period snapshot is a plain suspend fun
override suspend fun getTotalCountInRange(start: LocalDateTime, end: LocalDateTime): Flow<Long> =
    flow { emit(datasource.getTotalCountInRange(start, end)) }.flowOn(Dispatchers.IO)
```

A flow earns its wrapper when the source is live — an observed query that re-emits on write. For a
one-shot read of a fixed window, `withContext(Dispatchers.IO) { … }` returning the value says what is
actually happening. (`repository-flow-conventions` covers the shapes worth keeping.)

**Derived figures belong on the snapshot, not in the UI.** A ratio computed at the call site is
computed differently at the second call site, and a screen with a landscape arm has two of everything:

```kotlin
// adapted
val playsPerActiveDay: Int get() = if (activeDays > 0) (events / activeDays).toInt() else 0
val isEmpty: Boolean get() = events == 0L
```

**The denominator is the part people get wrong, not the numerator.** "Events per day" over a 7-day
span is `events / 7` or `events / activeDays`, and only the second is what a person means by *how
much do I do this on a day I do it at all*. Someone active on two days of seven has an average that
differs by 3.5× between the two readings, and both are defensible until you name which one the label
promises. Name it at the declaration — *the days that had any, not the calendar span* — because the
field name alone cannot carry it.

**Model "nothing to compare against" as absence, once.** The previous snapshot is nullable and is
nulled centrally when it is empty, so every figure on the screen branches on one thing. Left to each
figure, some show a delta against zero and some do not, and a first-period user sees a screen of
infinite increases. Self-normalised readings have the same requirement for a different reason — see
`self-normalised-axes-need-a-second-shape`.

**One snapshot does not mean one query.** Underneath it is still eight reads; the point is that
they are assembled behind one suspension and handed over together. Read the cheapest discriminating
one first — the raw scan that also answers "is this period empty" — and return the default snapshot
before issuing the rest.

**Two snapshots are two full round trips, sequentially.** That is usually right: the previous period
is only wanted once the current one has been resolved, and the pair is what makes it coherent. If the
period is expensive enough that the wait shows, parallelise the *pair* and keep each snapshot whole —
never parallelise the figures within one.

## Verifying it

1. **Count the single-emission wrappers.** Each is a suspend function that could say so — 74
   tree-wide here:

   ```bash
   grep -rn --include='*.kt' -A 1 "flow {" . | grep -v '/build/' | grep -c "emit("
   ```

   Then narrow the path to the one repository this screen uses and read the ratio: thirteen wrappers
   out of fifteen methods, and the period snapshot is not one of the thirteen.

2. **Find every place the same rate is computed, and check they agree on the denominator:**

   ```bash
   grep -rn --include='*.kt' -E "activeDays|/ *[a-zA-Z]*[Dd]ays" . | grep -v '/build/'
   ```

   More than one arithmetic expression producing the same labelled figure is the drift; a single
   `get()` on the snapshot is the fix.

3. **Watch a reload with the numbers on screen.** Step the period back and forward repeatedly while
   looking at a count and a total that must belong to the same span. With a snapshot they change
   together, in one frame. With separate flows they change in separate frames, and that gap — not a
   wrong final value — is the bug this shape removes.
