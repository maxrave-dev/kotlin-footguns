---
name: self-normalised-axes-need-a-second-shape
description: Build a radar/fingerprint chart whose axes are normalised 0..1 from your own data — no external corpus, one guarded denominator per axis, and a second polygon (the previous period) because a lone shape on self-normalised axes says nothing. Use when a "usage personality" or "year in review" chart needs a reference it cannot get, when a thin period leaves one axis at a guarded zero beside four real readings, or when one axis goes NaN and the whole polygon disappears.
---

# Self-normalised axes need a second shape

Five readings of *behaviour*, each bounded 0..1 by construction, computed from one table of events.
The appeal is that no global corpus is needed — the reference implementations of this chart compare
each axis against an average across every user of a service, and a local-only app has no such
average. The cost is that a single polygon is then uninterpretable, which the second shape fixes.

```kotlin
// adapted: "entity" is whatever contributes to an event (a creator, an author, a correspondent)
private fun fingerprintOf(
    dailyCounts: List<Int>,     // events per active day
    entityEvents: List<Int>,    // events per entity, DESCENDING
    newEntities: Int,
    distinctEntities: Int,
    distinctItems: Int,
    events: Int,
): Fingerprint {
    val consistency =                                     // 1 − coefficient of variation
        if (dailyCounts.size < 2) 0f else {
            val mean = dailyCounts.average()
            if (mean <= 0.0) 0f else {
                val variance = dailyCounts.sumOf { (it - mean) * (it - mean) } / dailyCounts.size
                (1.0 - sqrt(variance) / mean).coerceIn(0.0, 1.0).toFloat()
            }
        }
    val total = entityEvents.sum()
    val diversity =                                       // normalised Shannon entropy
        if (total <= 0 || entityEvents.size < 2) 0f else {
            val h = entityEvents.sumOf { c -> (c.toDouble() / total).let { if (it > 0) -it * ln(it) else 0.0 } }
            (h / ln(entityEvents.size.toDouble())).coerceIn(0.0, 1.0).toFloat()
        }
    return Fingerprint(
        consistency = consistency,
        discovery = if (distinctEntities <= 0) 0f else (newEntities.toFloat() / distinctEntities).coerceIn(0f, 1f),
        diversity = diversity,
        concentration = if (total <= 0) 0f else (entityEvents.take(5).sum().toFloat() / total).coerceIn(0f, 1f),
        replay = if (events <= 0) 0f else (1f - distinctItems.toFloat() / events).coerceIn(0f, 1f),
    )
}
```

## Traps

**A lone polygon on self-normalised axes carries no information.** "Consistency 0.62" is neither high
nor low: the scale was built from this data, so there is nothing outside it to be high or low
against. Draw the previous period's polygon under the current one — stroked, not filled, so the
filled current shape reads as the foreground — and the reader gets a direction even without a
vocabulary for the units. When there is no previous period, **omit its legend entry too**; a legend
that names a shape the canvas does not contain sends the reader hunting for it.

**Every axis here divides, and every divisor can be zero on a thin period.** Four different
denominators (`mean`, `total`, `distinctEntities`, `events`) each need their own guard at their own
site — a single "enough data?" check at the top is the wrong shape, because the axes go empty at
different thresholds. The subtle one is `ln(n)`: it is **zero at n = 1**, so the `entityEvents.size < 2`
test is a divide-by-zero guard wearing the costume of a sample-size guard. Delete it as redundant
and a user with exactly one entity gets `0.0 / 0.0`.

**`coerceIn` is not a zero-guard.** Kotlin's clamp is two comparisons, and every comparison against
NaN is false, so `Double.NaN.coerceIn(0.0, 1.0)` returns NaN unchanged. The value then reaches the
path builder, which multiplies it into a coordinate — and a path with one NaN vertex does not draw a
wrong shape, it draws **no shape**. One unguarded division silently deletes the other four axes with
it. Guard before the ratio; clamp only to fix the sign and the tail.

**`take(5)` means "the top five" only because a query said so.** The concentration axis is the share
landing on the five biggest entities, but nothing in the Kotlin enforces that ordering — it comes
from `ORDER BY count DESC` in the query that produced the list. Reorder that query for some unrelated
reason (or route the list through a `Map`, or `groupBy`) and the axis silently becomes "the share
landing on five arbitrary entities", still bounded 0..1, still plausible on screen.

**Normalise for size, not by size.** Raw entropy grows with the number of entities, so a bigger
library would score higher on diversity forever. Dividing by `ln(n)` — the entropy of a perfectly
even spread over that same n — turns the axis into "how even is this, for its size". Any axis that
does not do this is really measuring volume, and volume already has its own number on the screen.

**Axes stitched from separate queries can contradict each other.** `replay` is `1 − distinctItems / events`
where `events` is the row count from one scan and `distinctItems` is a `COUNT(DISTINCT …)` from
another, taken moments later and outside any transaction. A write landing between them can push
`distinctItems` above `events` and the axis negative. The clamp is what stops that reaching the
canvas — so it is load-bearing, not cosmetic, and a reviewer who "simplifies" it away is removing a
guard. Either take both numbers in one transaction or keep the clamp and say why.

**Write the bound next to the formula, because "bounded 0..1 by construction" is a claim per axis.**
`discovery = newEntities / distinctEntities` is bounded only because every entity counted as new
also appears in the window — that is a property of the two queries, not of the arithmetic. Let "new"
later be computed over a different span than "distinct" and the axis exceeds 1, where the clamp
hides it at exactly 100% forever.

**The share axes need an unbounded query; the list beside them needs a capped one.** Concentration
and diversity are shares of the whole, so feeding them the same `LIMIT 100` list that renders the
top-five panel inflates both — the cut tail is missing from the denominator. Same window, same
grouping, two queries with different bounds: `unbounded-for-shares-capped-for-lists`.

**Zero is a real reading; "not enough data to say" is not.** Every guard above returns `0f`, and
because they trip at different thresholds those zeros arrive **one axis at a time**. A period with
one active day trips only `dailyCounts.size < 2`, so the shape reads consistency 0%, discovery 100%,
diversity 97%, concentration 100%, replay 0% — lopsided, not collapsed, and the two 0%s mean
opposite things: consistency is the guard declining to answer, replay is a real measurement that
nothing was repeated. Nothing on the canvas separates them, so the whole shape reads as measured. If
the distinction matters, carry it in the type rather than in the value (`unknown-not-a-valid-score`),
or suppress the chart under a minimum sample and say why it is missing.

**Print the numbers beside the shape.** They are the only thing that survives when the second polygon
is absent, and they are what makes the chart checkable at all — a polygon cannot be read to two
significant figures, so without them nobody can ever tell you an axis is wrong.

The two snapshots the comparison needs must be fetched as a matched pair, not as independent
streams — see `one-snapshot-per-period-not-many-flows`. Absence of the reference is expressed the
same way absence of a change figure is: see `delta-absent-not-infinite`.

## Verifying it

Run these from the repository root. They are read-only.

1. Every clamped ratio in the codebase, so you can check each divisor is guarded *before* the
   division rather than clamped after it. Expect around a dozen hits; the fingerprint block is five
   consecutive ones:

   ```bash
   grep -rn --include='*.kt' "coerceIn(0" . | grep -v '/build/' | grep -E "/ [a-zA-Z(]"
   ```

2. The hidden ordering dependency. Every `take(5)` that feeds a share must be traceable to a
   descending sort; the two commands should be read together:

   ```bash
   grep -rn --include='*.kt' "take(5)" . | grep -v '/build/'
   grep -rn --include='*.kt' "ORDER BY playCount" . | grep -v '/build/'
   ```

3. By hand, on a fresh install: step to a period with exactly one active day. Only `consistency`
   should read 0%, the other four should read real values, and nothing should mark that 0% as "no
   reading". Then step to a period with no events and confirm the section renders no chart at all
   rather than a collapsed shape — with the legend having dropped the missing polygon's entry too.
