---
name: delta-absent-not-infinite
description: Render a change figure against an empty or zero baseline as nothing at all — never "+100%", never an infinity, never a saturated integer — and guard the two spans being compared as well as the divisor. Use when a new user's first period shows a huge increase against every figure, when "+0%" appears beside a number that went down, or when every delta on a screen reads as a decline for reasons nobody can explain.
---

# A change with no baseline is absent, not infinite

A screen that prints "514" tells the reader nothing they can act on; "514, a quarter more than last
period" does. The whole value is in the comparison — which is exactly why the comparison must refuse
to exist when it would be meaningless, rather than manufacture a number.

```kotlin
/** A change against the same span one period earlier, or null when there is nothing to compare to. */
fun percentDelta(now: Long, before: Long?): Int? {
    if (before == null || before <= 0L) return null
    return (((now - before) * 100.0) / before).toInt()
}
```

Two guards live at different levels and both are needed. At the state level the whole previous
snapshot is dropped when it holds no events at all, so **no** figure on the screen gets a delta:

```kotlin
previousStats = previous.takeIf { p -> !p.isEmpty }   // isEmpty == (events == 0)
```

At the figure level `before <= 0` catches the case where the period had events but *this particular*
number was zero. Keeping only the first lets a single zero produce a division by zero; keeping only
the second is fine arithmetically but scatters "no data" reasoning across every call site.

## Traps

**"+100%" against an empty baseline is noise dressed as insight.** Every figure a first-period user
sees would carry the same maximal increase, so the column stops distinguishing anything and instead
trains the reader to ignore it. The failure is not a crash and not a wrong number — it is a whole
column of correct-looking numbers that mean nothing.

**Absence must be *rendered* as absence, and there are only two honest renderings.** Either omit the
element entirely (`if (delta != null) { … }`) or print an explicit phrase in its place
("no previous period"). Both appear in a single screen here for different figures, and both are
fine. What is not fine is a dash, a zero, or an em dash placed where a percentage goes: the reader
parses those as values because of where they sit.

**A clamped magnitude is not a guarded one.** `((now - before) * 100.0 / before).toInt()` on the JVM
saturates rather than wrapping, so a baseline of 1 against a present value of a billion yields
`Int.MAX_VALUE` — a twelve-character number in a `labelSmall` with `maxLines = 1`. Guarding the
*existence* of the baseline does nothing about its *size*. If tiny baselines are reachable, either
suppress the delta below a minimum baseline or format it as "×N" past some threshold.

**Truncation toward zero turns a small decline into "+0%".** `toInt()` truncates, and the sign
branch is usually `if (delta >= 0) "+$delta%"`. A change of −0.5% therefore becomes `0`, which is
`>= 0`, which prints **"+0%" next to a number that fell**. A genuine +0.5% prints the same string, so
"+0%" is ambiguous in both directions. Round instead of truncating, or branch the sign on the raw
ratio rather than on the rounded integer.

**A single accent colour for both directions leaves the sign carrying everything.** Rendering rises
and falls in the same colour makes a leading `-` at small type the only difference between "a
quarter more" and "a quarter less" — and it is a few pixels wide next to a three-character number.
Either encode direction (colour, an arrow) or set the figure at a size where the sign is legible;
do not rely on the reader spotting a hyphen.

**Compare like spans, or the delta measures the calendar.** Derive both windows from *one* function
called with `offset` and `offset + 1`, so equal length is structural rather than remembered. The
version that bites is a "this year" branch whose current window ends **today** while the previous
window ends on 31 December:

```kotlin
val end = if (offset == 0) today else LocalDate(year, 12, 31)   // current span is short
```

In March that compares a fifth of a year against a whole one, and every figure on the screen reads
as roughly an 80% collapse. The same bias exists in miniature for any rolling window whose newest
day is still in progress. Either compare against the same *elapsed fraction* of the earlier period,
or exclude the incomplete unit from both — and if neither, label the current period as partial.

**Absence is not the same as zero, and only the type can carry that.** `Int?` is doing real work
here: collapsing it to `0` would print "+0%" for "we have no idea", which is the numeric-display
version of the fallback problem in `unknown-not-a-valid-score`. Keep the nullable all the way to
the composable and branch there; the moment a default is applied the information is gone.

**A missing baseline must also remove its legend, key and caption.** Anything that names the
comparison — a legend entry, an axis, a "vs previous period" caption — has to disappear with the
number it describes, or the reader spends time hunting for a shape that was never drawn.

Both snapshots must be fetched as a coherent pair, or a count from this period can render beside a
total from the last one: `one-snapshot-per-period-not-many-flows`.

## Verifying it

Run these from the repository root. They are read-only.

1. Every place a delta is produced, so you can check each call site handles the null rather than
   defaulting it. Expect one definition and one hit per figure on the screen:

   ```bash
   grep -rn --include='*.kt' "percentDelta(" . | grep -v '/build/'
   ```

2. The truncation, demonstrated. Both a small decline and a small rise collapse to the same integer,
   which the `>= 0` branch then prints with a plus sign:

   ```bash
   LC_ALL=C awk 'BEGIN{printf "199 vs 200 -> %d%%\n201 vs 200 -> %d%%\n", ((199-200)*100.0)/200, ((201-200)*100.0)/200}'
   grep -rn --include='*.kt' 'delta >= 0' . | grep -v '/build/'
   ```

   The first prints `0%` twice; the second shows every site that would render both as `+0%`.

3. Both spans come from one function, and the branch that breaks that promise:

   ```bash
   grep -rn --include='*.kt' "rangeFor(" . | grep -v '/build/'
   grep -rn --include='*.kt' "if (offset == 0)" . | grep -v '/build/'
   ```

   The first shows the pair built as `offset` / `offset + 1`; the second shows the one branch where
   the current window stops early and the comparison stops being like-for-like.
