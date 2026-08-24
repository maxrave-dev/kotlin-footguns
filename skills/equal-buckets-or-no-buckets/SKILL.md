---
name: equal-buckets-or-no-buckets
description: Split a span into buckets of exactly equal width and let the remainder fall outside, pick the bucket unit from how many rows a person will read, and never draw a partial newest bucket at full width. Use when a bar chart's oldest or newest bar is inexplicably long or short, when a range produces thirty rows nobody reads, or when one range in a set renders in the opposite direction from the others.
---

# Equal buckets, or no buckets

A range chart has two independent decisions: how wide each bucket is, and how many of them there
are. Getting the second wrong makes a chart nobody reads; getting the first wrong makes a chart that
is actively wrong, because bar **length** encodes a count and a wider bucket collects more counts.

```kotlin
// adapted: four buckets of exactly seven days, newest first, remainder deliberately outside
DayRange.LAST_30_DAYS ->
    (0 until 4).map { week ->
        Bucket.Week(
            start = endDate.minus(DatePeriod(days = week * 7 + 6)),
            end   = endDate.minus(DatePeriod(days = week * 7)),
        )
    }
```

Four × 7 covers 28 of the nominal 30 days. That is the point: the alternative — four-and-a-bit
buckets covering all thirty — gives one bucket 9 days and three of them 7.

## Traps

**A wider bucket draws a longer bar for a reason that is not in the data.** The bar encodes the
count of events in the bucket; a bucket covering nine days collects roughly 29% more events than one
covering seven, and the reader takes the extra length as "more activity". Unequal buckets do not
introduce noise, they introduce a **bias in a known direction**, which is worse — it looks like a
trend. Take exact equal widths and let the leftover days fall outside the chart.

**Dropping the remainder is only honest if the labels make it discoverable.** Each bucket here is
labelled with its own start and end date, so a reader who cares can see the chart begins 28 days
back rather than 30. A bucket labelled "Week 4" with no dates makes silently-dropped days
undiscoverable, and then the total under the chart will not match the total on the rest of the
screen.

**Calendar months are unequal — allowed only because the label names the unit.** A reader knows
February is short; nobody knows that "bucket 3" is nine days. So the rule is not literally "equal
widths", it is: *unequal widths are permitted exactly when the width is legible from the label*. That
exemption covers months and quarters and covers nothing else you invent.

**The newest calendar bucket is partial and is being drawn at full width.** Both the 90-day and
year branches emit buckets whose range runs to the first of the following month, while the data
stops today. On the 3rd, the newest month's bar is two days of events beside neighbours holding
thirty — an apparent collapse, every month, in every month-bucketed chart ever built. Fix it by
excluding the in-progress unit, by scaling that one bucket by elapsed fraction, or by labelling it
"so far" — but not by leaving it.

**Bucket order is part of the bucket contract, and the renderer will not fix it.** Three of the four
branches above emit newest-first; the year branch emits January-first. The renderer is a plain
`forEach` over the list, so one range out of four reads backwards from its siblings, and nothing in
the type system notices. Decide the direction once, assert it where the list is built, and give the
renderer no say.

**Pick the unit from the row count a person will actually read.** Thirty rows is not a chart, it is a
list nobody reaches the end of; three rows is a chart that says nothing. Seven days → seven day
rows; thirty days → four week rows; ninety days → three month rows. The unit is a **reading**
decision that then constrains the arithmetic, not the other way round.

**An inclusive `end` needs an exclusive query bound.** A bucket described as `[start, end]` must be
queried as `start .. end.plus(1 day)` (or to `23:59:59`), or every event in the last hours of each
bucket lands in the next one — a quiet redistribution that is invisible on the chart and shows up
only as a total that will not reconcile.

**A zero bucket must still occupy a row, and the count must live outside the bar.** A floor clamp
(`coerceIn(0.001f, 1f)`) keeps an empty bucket visible as a hairline, which is right — the empty
buckets are usually the information. But if the count label is drawn *inside* the bar, at that fill
it sits on the track instead, in the bar's foreground colour. The sibling chart in the same feature
puts its count in a fixed-width column to the right of the track; that is the arrangement that
survives a zero.

Bucketing by local hour or local day belongs in code rather than in SQL, and the timestamp you
bucket may not mean what the column type suggests — see `bucket-local-time-in-code-not-in-sql` and
`stored-timestamp-is-a-local-wall-clock`. A bucket set that cannot cover all of its input is the
temporal case of `partial-chart-must-say-so`.

## Verifying it

Run these from the repository root. They are read-only.

1. Every bucket-building branch, so you can check both the width arithmetic and the direction. The
   three `0 until N` branches count backwards from the newest day; the fourth counts forward:

   ```bash
   grep -rn --include='*.kt' -E "\(0 until [0-9]+\)\.map|\(1\.\.[a-zA-Z]+\.number\)\.map" . | grep -v '/build/'
   ```

2. Re-derive the coverage of your own bucket set. Change `n` and `len` to match; if the covered
   total is not the nominal span, the difference is days that are silently outside the chart:

   ```bash
   LC_ALL=C awk 'BEGIN{n=4;len=7;for(w=0;w<n;w++)printf "bucket %d: days -%d .. -%d\n",w,w*len+len-1,w*len;
     printf "covered %d of the %d nominal days\n", n*len, 30}'
   ```

   Prints four buckets and `covered 28 of the 30 nominal days`.

3. The inclusive-end conversion, and the fill floors of every bar chart. Two floors that differ by
   20× is the tell that one of them was tuned for a label drawn inside the bar:

   ```bash
   grep -rn --include='*.kt' "plus(DatePeriod(days = 1))" . | grep -v '/build/'
   grep -rn --include='*.kt' "fillMaxWidth((" . | grep -v '/build/'
   ```
