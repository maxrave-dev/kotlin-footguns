---
name: partial-chart-must-say-so
description: Print the share of input a distribution could actually classify, computed with exactly the predicates that built the buckets, and keep that line reachable when coverage is zero. Use when a chart is built over a nullable join or a parsed text column, when the bars look plausible but the totals underneath disagree, or when the one case that most needs a disclaimer is the case that renders nothing.
---

# A partial distribution has to admit it

A "share by category" chart drawn over a nullable foreign key is partial by construction: events
that carry no group id, whose group row was never cached, or whose stored year does not parse, are
simply absent from every bucket. The bars still add up among themselves, which is exactly why nobody
notices. The fix is one line of text — and getting that line right is most of the work.

```sql
-- adapted: bucket query and coverage query, which MUST share their predicates verbatim
SELECT (CAST(SUBSTR(g.releaseYear, 1, 4) AS INTEGER) / 10) * 10 AS decade, COUNT(*) AS eventCount
  FROM event e JOIN grp g ON g.id = e.groupId
 WHERE e.timestamp BETWEEN :start AND :end
   AND g.releaseYear IS NOT NULL AND CAST(SUBSTR(g.releaseYear, 1, 4) AS INTEGER) > 1900
 GROUP BY decade ORDER BY decade;

SELECT COUNT(*) FROM event e JOIN grp g ON g.id = e.groupId
 WHERE e.timestamp BETWEEN :start AND :end
   AND g.releaseYear IS NOT NULL AND CAST(SUBSTR(g.releaseYear, 1, 4) AS INTEGER) > 1900;
```

```kotlin
val coverage = if (stats.events <= 0) 0 else ((stats.classifiedEvents * 100L) / stats.events).toInt()
```

## Traps

**The disclosure usually lives inside the block that is skipped when it matters most.** The chart
starts `if (buckets.isEmpty()) return`, and buckets are empty exactly when **nothing** could be
classified — so at 0% coverage the bars, the section heading and the "N% of events could be dated"
line all disappear together, and the reader is never told that a whole dimension of their data is
missing. The empty case needs its own branch that renders the sentence *without* the chart. Watch
for the guard being duplicated at the section wrapper too; two copies means two places to fix.

**The coverage figure must be computed by the predicates that built the buckets, not by a simpler
version of them.** Three separate conditions exclude rows here — a null id, a join that finds no
row, and a value that does not parse — and a denominator query that reproduces only the first
reports coverage higher than the chart actually achieved. Write the two queries adjacent so the
`WHERE` clauses can be diffed by eye, and assert the invariant that makes them a pair: **the sum of
the bucket counts equals the numerator**.

**Integer division makes small-but-nonzero coverage print as zero.** `(classified * 100) / total`
truncates, so 4 classified events in 1000 renders "0% could be dated" *above visible bars* — a
screen that contradicts itself. It also flattens 99.6% to 99%, which reads as a real shortfall.
Round, or print "<1%" below the resolution of the format.

**Name the denominator the reader assumes.** "68% of events could be dated" is only honest if the
denominator is every event in the window. Quietly switching it to "events that had a group" — the
join's own output — produces a comfortable number that answers a question nobody asked. If the two
denominators differ a lot, that difference is itself the finding.

**A parse expressed as a range test discards more than garbage.** `CAST(SUBSTR(x, 1, 4) AS INTEGER)`
yields `0` for non-numeric text in SQLite, so `> 1900` is doing double duty as parse check and
sanity check. That is compact and fine — provided you know it silently drops legitimate values below
the sentinel, and that the sentinel is a decision rather than a round number someone typed. Record
what it excludes next to it.

**A bucket key computed by integer division will happily bucket a parse failure.** `(CAST(…) / 10) * 10`
maps an unparseable value's `0` onto a bucket labelled "0s", which then sorts first and sits at the
top of the chart. Nothing in the bucketing rejects it — the range filter in the `WHERE` is the only
thing keeping that bucket off the screen. Loosen or reorder that filter and a parse failure becomes
a category.

**Numerator and denominator taken by separate scans can disagree.** Here the classified count comes
from its own query while the total comes from the length of the sample list, fetched moments earlier
and outside any transaction. Writes landing between them can push coverage above 100%. Take both in
one transaction, or clamp and accept that the clamp is load-bearing.

**Never normalise a partial distribution to 100%.** Scale the bars against the **largest bucket** and
print the raw count beside each one. Scaling against the classified total instead produces
percentages that sum to 100% — of a subset — while looking like 100% of everything, which is the
original lie with a decimal point on it.

**A chart can be shortened by enrichment as well as by classification.** Ids resolved to display rows
at read time silently drop entries whose row has since gone, so a "top 100" quietly becomes a top 60.
Same disease, different stage of the pipeline: `local-listening-analytics`.

**A bucket set can be partial in time as well as in content** — a newest bucket that covers three days
of a month draws its bar at the same width as a full one. That is `equal-buckets-or-no-buckets`, and
it needs the same treatment: state the incompleteness on the chart or do not draw the bucket.

## Verifying it

Run these from the repository root. They are read-only.

1. The two predicates, side by side. Every `AND` after the first hit must appear identically in the
   coverage query below it — a difference is a coverage figure that overstates the chart:

   ```bash
   grep -rn --include='*.kt' "SUBSTR(" . | grep -v '/build/'
   ```

2. Where the disclosure can be reached from. Any early return on "no buckets" that sits *above* the
   coverage text is a 0%-coverage case that renders nothing at all:

   ```bash
   grep -rn --include='*.kt' -E "decades.isEmpty\(\)|datedPlays" . | grep -v '/build/'
   ```

   Expect two `isEmpty()` guards — the section wrapper and the chart itself — with the coverage
   expression two lines below the chart's. `grep -rn` orders by file, so in the output the coverage
   hit sits under whichever guard shares its file, not under the second one listed. That ordering in
   the source is the bug: the guard runs first, so at 0% coverage the line below it never executes.

3. The truncation, demonstrated — one figure that under-reports and one that contradicts the bars
   drawn above it:

   ```bash
   LC_ALL=C awk 'BEGIN{printf "996/1000 -> %d%%\n  4/1000 -> %d%%\n", (996*100)/1000, (4*100)/1000}'
   ```

   Prints `99%` and `0%`.
