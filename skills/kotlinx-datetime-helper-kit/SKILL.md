---
name: kotlinx-datetime-helper-kit
description: Wrap the multiplatform date-time library's instant-to-local-date-time conversions in a few named helpers — now, epoch converters, comparisons, a shifted-window helper and a relative "time ago" formatter — so call sites read as intent instead of ceremony. Covers what each wrapper must pin explicitly, and the trap family behind it: a helper reading one time zone while persistence reads another, arithmetic done on wall-clock types, a formatter that can only run during composition, and a parse failure that returns a legal value. Use when stored timestamps come back shifted by the device's offset, when a duration is wrong only around a clock change or only for some users, or when a relative label stays stale on screen.
---

# Named wrappers over the instant / local-date-time dance

The multiplatform date-time library deliberately separates an *instant* (a point on the timeline)
from a *local date-time* (wall-clock fields with no zone attached), and converting between them
needs a zone every time. Written inline, that is three lines of ceremony around one intent, so the
kit is worth having:

```kotlin
// adapted
private val zone get() = TimeZone.currentSystemDefault()

fun now(): LocalDateTime = Clock.System.now().toLocalDateTime(zone)

fun epochMillisToLocalDateTime(epochMillis: Long): LocalDateTime =
    Instant.fromEpochMilliseconds(epochMillis).toLocalDateTime(zone)

fun LocalDateTime.plusSeconds(seconds: Long): LocalDateTime =
    this.toInstant(zone).plus(seconds, DateTimeUnit.SECOND, zone).toLocalDateTime(zone)

fun LocalDateTime.isBefore(other: LocalDateTime): Boolean = this < other
```

`plusSeconds` is the shape to copy: it converts **to an instant, does the arithmetic there, and
converts back**. Everything below is about what happens when a helper skips that round trip, or
when two helpers disagree about which zone they are in.

## Traps

**A wall-clock value written through a converter that assumes a different zone is stored shifted.**
This is the one that survives review, because both halves look correct on their own. The kit reads
the device's zone; a persistence type converter is very often written against a fixed zone, because
storing "as UTC" reads like the careful choice:

```kotlin
// the converter — a different zone from the one the kit used
fun dateToTimestamp(date: LocalDateTime?): Long? = date?.toInstant(TimeZone.UTC)?.toEpochMilliseconds()
fun fromTimestamp(value: Long?): LocalDateTime? =
    value?.let { Instant.fromEpochMilliseconds(it).toLocalDateTime(TimeZone.UTC) }
```

A value produced by `now()` in a zone at +07:00 is then persisted as an instant seven hours earlier
than the moment it was captured. Nothing breaks while the device stays put — the value read back
equals the value written, and a comparison against a fresh `now()` is consistent because *both*
sides carry the same error. It surfaces when the offset changes: after travel or a daylight-saving
transition, rows written before and after are on two different scales, expiry checks fire early or
late, and a "last 7 days" window quietly moves. Pick one rule — **store instants, in epoch
milliseconds, and convert to local only for display** — and make the converter and the kit agree.

**Comparison operators on a wall-clock type compare fields, not moments.** `a < b` on a local
date-time is a lexicographic comparison of year, month, day, hour, and so on. That is the right
answer only when both values were built in the same zone. Wrappers named after the instant-style
API of a platform date library invite exactly the wrong assumption — the name says "is before",
which sounds like a question about the timeline. Either compare instants, or keep the wall-clock
comparison and name it so nobody expects otherwise.

**Calendar arithmetic and elapsed-time arithmetic are different operations.** Subtracting days from
the date part and re-attaching the same time-of-day —

```kotlin
fun LocalDateTime.beforeXDays(x: Int): LocalDateTime = this.date.minus(x, DateTimeUnit.DAY).atTime(this.time)
```

— asks "the same clock time, x days earlier", which is what a human means by "since Monday" and is
*not* `x × 24 hours` across a clock change. Both are legitimate; they differ by an hour twice a
year and by more in zones that have changed their rules. Decide which one the caller wanted. If it
is elapsed time, go through the instant the way `plusSeconds` does; if it is calendar days, keep
this and say so at the declaration, because the next reader will assume the other one.

**A relative formatter written as a composable can only ever run in the presentation layer.**
Reaching for the string-resource lookup inside the function pins it there —
`@Composable fun LocalDateTime.formatTimeAgo(): String`, reading `now()` in its own body.
Three consequences, all of them felt later. It cannot be unit-tested without a composition. It
cannot be used from a view model, a notification builder, or a widget. And it reads the clock
during composition with nothing to invalidate on, so the label it produced is frozen until some
unrelated state change re-runs it — an item that says "recently" keeps saying it an hour later.
Split it: a pure function taking `(from: Instant, to: Instant)` returning a small sealed result, and
a thin composable that maps that result to a string resource. Then drive the *to* argument from a
ticking state so the screen actually updates.

**The period's `hours` is a component, not a total.** This library's calendar period decomposes a
gap into years, months, days, hours, … — so a 25-hour gap is `days = 1, hours = 1`, never
`hours = 25`. The field is there; reading it as an elapsed-hours figure is the trap, and it is the
real reason a correct "time ago" computes half its branches from a different source. Take months and
days from the period, but take a single "hours ago" number from the duration between the two
instants. (A date-only period, from date-to-date subtraction, has no time components at all — its
hours are always zero.) Then order the branches coarsest to finest and make the boundary explicit,
so a 25-hour gap cannot satisfy both the "days" branch and the "hours" branch depending on which
runs first.

**A parse failure that returns zero is indistinguishable from a real result.** A timestamp parser
that answers `0.0` when the input is malformed has produced a legal value: zero is the start of the
track, the top of the hour, the epoch. The caller cannot branch on it, so it silently proceeds with
a wrong number. Return null and make the caller decide — see `unknown-not-a-valid-score`.

**Calling the clock directly, anywhere, is what makes time untestable.** A module that reaches for
the system clock inside its own logic can only be tested by waiting. Route reads through the kit,
and let the kit's clock be substitutable so a test can pin it.

**A "shared" helper file that imports a Java-runtime type is only shared across targets that have
one.** Duration and number formatting are where this creeps in: the concurrency time-unit enum, the
locale type, and the platform's format function are all Java-runtime types, and a file in the shared
source set that imports them compiles for Android and desktop while silently excluding native
targets. Either keep those in a platform source set, or format with the multiplatform library's own
formatting and plain arithmetic.

## Verifying it

1. **Confirm one zone rule across the codebase.** These two lists must not disagree about the same
   values:
   ```sh
   grep -rn "TimeZone.UTC" --include='*.kt' .
   grep -rn "TimeZone.currentSystemDefault()" --include='*.kt' .
   ```
   Any type converter or serializer in the first list whose values are produced by a helper from the
   second is the shift described above.
2. **Find clock reads that bypass the kit**:
   ```sh
   grep -rn "Clock.System.now()" --include='*.kt' .
   ```
   Ideally one hit, inside the kit. Every other hit is a place a test cannot control time.
3. **Find Java-runtime imports in shared source sets**:
   ```sh
   find . -path '*/commonMain/*' -name '*.kt' -exec grep -l '^import java\.' {} +
   ```
   Each file listed compiles only where a Java runtime exists.
4. **Find parse helpers that answer with a legal value**:
   ```sh
   grep -rn "return 0.0\|return 0L\|return 0$" --include='*.kt' .
   ```
   Read each hit inside a parser or converter and ask whether the caller could tell that apart from
   success.
5. **Move the device's clock forward across a daylight-saving boundary, then re-read stored rows.**
   Expiry checks and day-window queries that use a fixed zone on one side and the device zone on the
   other change their answers; ones that agree do not.
