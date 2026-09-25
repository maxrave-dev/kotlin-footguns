---
name: unbounded-for-shares-capped-for-lists
description: A top-N query is right for a list and wrong for a share-of-the-whole — the cut tail shrinks the denominator and the entropy normaliser, inflating concentration and diversity alike — so the same grouped data needs two queries with different bounds. Covers why the truncation is invisible in the result, why the unbounded query's ORDER BY becomes load-bearing, and when unbounded is actually safe. Use when a "top 5 share" or diversity score reads implausibly high, when one grouped query is feeding both a leaderboard and a statistic, or before reusing a capped DAO method for anything that divides by a total.
---

# Two bounds over the same grouping

The same `GROUP BY` feeds two consumers with opposite needs. A leaderboard wants the head and
nothing else; a share-of-the-whole wants the whole:

```kotlin
// adapted — for the list on screen
@Query("SELECT entityId, COUNT(*) AS eventCount FROM event_entity" +
       " WHERE timestamp BETWEEN :start AND :end" +
       " GROUP BY entityId ORDER BY eventCount DESC LIMIT 100")
suspend fun queryTopEntitiesInRange(start: LocalDateTime, end: LocalDateTime): List<EntityCount>

// adapted — for anything that divides by a total. Unbounded, and it says why.
@Query("SELECT entityId, COUNT(*) AS eventCount FROM event_entity" +
       " WHERE timestamp BETWEEN :start AND :end" +
       " GROUP BY entityId ORDER BY eventCount DESC")
suspend fun getEntityCountsInRange(start: LocalDateTime, end: LocalDateTime): List<EntityCount>
```

Two nearly identical queries look like duplication waiting to be merged. They are not: the `LIMIT`
is the difference between a list and a distribution.

## Traps

**The truncated answer is inflated, not merely approximate.** Both directions run the same way, and
the second is the counter-intuitive one. Concentration is `top5 / total`, and the cut tail removes
mass from the denominator only. Normalised entropy is `H / ln(n)`, and dropping the many rare
entries lowers `H` — but lowers `ln(n)` faster, so the ratio *rises*. Measured on a Zipf-shaped
500-entity period whose top 100 already hold 84% of the events:

| | rows | total | concentration | diversity |
|---|---|---|---|---|
| unbounded | 500 | 10182 | 0.423 | 0.689 |
| `LIMIT 100` | 100 | 8505 | **0.506** | **0.748** |

Both read as "this user is more focused *and* more varied than they are" — a contradiction that
never surfaces, because nothing on the screen compares them.

**Nothing in the result says it was cut.** A capped query returns exactly `LIMIT` rows and no error;
the consumer cannot tell 100-of-100 from 100-of-512. Compare the row count against a
`COUNT(DISTINCT …)` over the same window if you need to know — and treat a result whose size equals
the limit exactly as unverified.

**The reuse happens because the columns match.** The statistic needs `(id, count)` and a method
returning `(id, count)` already exists, already scoped to the window, already on the datasource.
Nothing about the call site suggests a cap is in play; the cap lives in a string constant in another
module. This is the whole failure mode — not someone choosing wrongly, but someone not being offered
a choice.

**The unbounded query's `ORDER BY` becomes load-bearing.** With no `LIMIT`, an `ORDER BY` looks
purely cosmetic and is exactly the kind of thing that gets deleted as a needless sort. But the
concentration figure is computed as `counts.take(5).sum() / total` — a *positional* read of the
result. Drop the ordering and "top-5 share" silently becomes "some-5 share", still bounded 0..1,
still plausible, still wrong. Either keep the sort and say at the query why it is not decoration, or
make the consumer sort for itself and stop depending on the query at all.

**Unbounded is only safe when the grouping key bounds the row count.** `GROUP BY entityId` returns at
most one row per distinct entity in the window, which is bounded by how many distinct things a person
interacted with — hundreds, not millions. That is a fact about the *data*, not about the query, so
write down the order of magnitude you expect and re-check it if the window can widen. An unbounded
`GROUP BY` over a high-cardinality key is a different decision with the same syntax.

**A share query usually does not need the ids at all.** Concentration and entropy consume counts
only. Projecting the key as well is harmless at these sizes and is worth noticing, because it is what
makes the two queries look interchangeable in the first place.

**"Large enough" is still a cap, and it is the change reviewers approve.** Raising `LIMIT 100` to
`LIMIT 10000` makes the error smaller, makes it impossible to reproduce on test data, and leaves it
correct only for users below the new bound — which is precisely the users nobody investigates. A
share needs *all* the mass or it is not a share; there is no bound that makes it one.

**The same split appears wherever a cap meets a denominator.** A capped list joined to compute a
percentage, a paged read summed into a total, a "top tags" query reused for coverage — all the same
shape. If a number is divided by anything, trace its source to a query and read the bound.

## Verifying it

1. **Every capped grouped query, in one shot.** The annotation precedes its function, so the name is
   *below* the `LIMIT`, never above it — `-A 2` is what puts it in the output. Read each hit and ask
   which consumers use it:

   ```bash
   grep -rn --include='*.kt' -B 6 -A 2 "LIMIT 100" . | grep -v '/build/' | grep -E "GROUP BY|LIMIT|suspend fun"
   ```

2. **Find consumers that divide by a total derived from a capped result** — 11 hits here; read each
   and keep the ones that divide by a total, which is two of them. Those are the ones to move:

   ```bash
   grep -rn --include='*.kt' -E "\.take\([0-9]+\)|\.sum\(\)" . | grep -v '/build/'
   ```

   A `.take(n)` over a query result is also the positional dependency described above — each hit
   needs the source query's `ORDER BY` to be intentional.

3. **Reproduce the inflation on your own distribution rather than trusting the table above.**
   Read-only, no database needed:

   ```bash
   python3 -c "
   import math
   counts = sorted([max(1,int(2000/(r**1.1))) for r in range(1,501)], reverse=True)
   def s(c):
       t=sum(c); return sum(c[:5])/t, (-sum((x/t)*math.log(x/t) for x in c))/math.log(len(c))
   print('unbounded %.3f %.3f' % s(counts)); print('capped    %.3f %.3f' % s(counts[:100]))"
   ```

   Swap the synthetic counts for a real export of one window. If the two rows agree, your tail is
   short enough that the cap does not bite *today* — which is a fact about this period, not a
   licence to share the query.
