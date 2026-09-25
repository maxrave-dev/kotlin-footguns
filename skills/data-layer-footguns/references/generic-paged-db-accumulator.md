---
name: generic-paged-db-accumulator
description: One reusable helper that reads an entire table through a (limit, offset) data-access function in a bounded loop, stopping on the first short page — plus when reading everything is legitimate (export, backup, bulk mapping) and the smell that means you needed a real query instead. Use when several repositories each hand-roll the same paging loop, or when a "read all" call gets slower than linearly as the table grows.
---

# Reading a whole table in bounded pages

Within the paged family — the queries written to be read a page at a time — the data-access layer
exposes only `(limit, offset)` functions, so no call in that family can return an unbounded result
set. (The rest of the layer is not like this and does not pretend to be: plenty of queries take no
limit at all and read a whole table, and at least one takes a limit with the offset pinned at zero.
Those are not the ones this helper is for.) One generic helper turns any member of the paged family
into a full read, and every repository gets the same termination rule instead of writing its own:

```kotlin
// adapted — page size hoisted to a constant (the original repeats the literal three times), and
// the loop restructured for clarity: the source carries its state as a `Pair<Boolean, Int>`
// reassigned at the bottom of the body and has no `break`. Semantics identical.
private const val PAGE = 100

suspend fun <T> getFullDataFromDB(
    func: suspend (limit: Int, offset: Int) -> List<T>,
): List<T> {
    val all = mutableListOf<T>()
    var offset = 0
    while (true) {
        val fetched = func(PAGE, offset)
        all.addAll(fetched)
        if (fetched.size < PAGE) break        // short page == last page
        offset += PAGE
    }
    return all
}
```

Call sites stay one line, and the paging never leaks into the repository:

```kotlin
// adapted: data-source name generalized; shape as written
override fun getLikedAlbums(): Flow<List<AlbumEntity>> =
    flow { emit(getFullDataFromDB { limit, offset -> local.getLikedAlbums(limit, offset) }) }
        .flowOn(Dispatchers.IO)
```

**When this is the right call:** an export or backup, a one-shot bulk mapping, a migration, or any
consumer that genuinely needs every row in memory at once. **When it is a smell:** the result is
immediately filtered, counted, sorted, or `.take(n)`'d — every one of those is a query you declined
to write, and the database would have done it without materializing the table. Feeding a scrolling
list is the loudest version: paging exists there precisely so that everything is *not* materialized.

## Traps

**The page size and the short-page test must be the same constant.** Written out literally, the
loop contains the page size three times — once as the argument, once in the termination test, once
in the increment. Two that disagree fail in opposite directions and both fail quietly: a test
larger than the request stops after the first page and silently returns a truncated list; a test
smaller than the request never stops. The same thing happens without any edit if a query clamps its
own limit (`LIMIT MIN(:limit, 50)`) — the caller asks for 100, gets 50, and the helper calls it the
end of the table. One constant, and let the query take the limit it is given.

**Nothing bounds the number of iterations.** A query that ignores its offset — a hand-written
statement where the parameter was left out, a view that re-sorts — returns a full page forever, and
this loop accumulates into memory until the process dies. A ceiling costs one line and converts an
unrecoverable hang into a log line you can act on.

**Offset paging needs a total order, or pages overlap.** `LIMIT`/`OFFSET` is only meaningful
relative to an ordering, and an ordering with ties is not total: rows that compare equal may land in
a different relative position on each query, so one gets returned twice and another never. Ordering
by a timestamp (`ORDER BY favoriteAt DESC`) is exactly the shape that has ties. Add the primary key
as a tiebreaker and the pages become a partition of the table.

**Each page is its own transaction, so writes during the read shift every later offset.** An insert
near the front pushes a row across the page boundary and you read it twice; a delete pulls one back
and you never see it. For an export from a quiet database this is theoretical; for a read racing
the user's own edits it is not. Wrap the whole loop in one transaction if the snapshot has to be
consistent, or page by a cursor on the ordering column (`WHERE favoriteAt < :lastSeen`) instead of
by offset — a cursor is immune to shifts and does not degrade.

**Offset is not free, and it gets less free every page.** The database produces and discards the
first *offset* rows for each request, so reading M rows in pages of P costs on the order of M²/P row
visits. The helper reads as "safely bounded", which is true of memory per query and false of total
work: at the table size that motivated bounding it, this is close to the slowest way to read
everything. Measure before assuming the loop is cheap.

**The result is a list, not a flow, and the wrapper re-reads on every collection.** The
`flow { emit(getFullDataFromDB { … }) }` shape means the whole table is read again each time
anything collects, including on a recomposition or a configuration change that re-subscribes. If
the caller collects more than once, either cache the result or hand back the database's own live
flow (see `repository-flow-conventions` for which shape belongs where).

## Verifying it

The truncation failures all return a plausible-looking list, so compare it to the database's own
answer rather than eyeballing it:

```sql
SELECT COUNT(*) FROM album WHERE liked = 1;
```

Assert `getFullDataFromDB { … }.size` equals that count, on a table with **more rows than one
page** — a fixture of ten rows exercises exactly none of the paging logic and passes on a helper
that only ever runs one iteration. Add a fixture of exactly `PAGE` rows too: that is the boundary
where a full final page forces one extra, empty query, and a helper that stops on `size <= PAGE`
instead of `< PAGE` loses the last page there and nowhere else.

To find the hand-rolled copies this helper is meant to replace, quote the include glob or the shell
will expand it before `grep` sees it:

```bash
grep -rn 'offset += \|offset + 100\|size < 100' --include='*.kt' .
```
