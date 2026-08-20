---
name: cascading-delete-ordering
description: Sweeping a local cache database down to what the user actually owns — ordering container deletes before leaf deletes, telling "kept by state" columns apart from genuine garbage, re-checking conditions inside the DELETE, and pinning the record currently in use. Reach for it when a "clear cache" or "clear history" pass completes without error and frees nothing, when it instead wipes the user's favourites or downloads, or when the item playing on screen vanishes mid-sweep.
---

# Cascading delete ordering

A cache sweep looks like "delete every row nothing points at". It is really a graph traversal,
and the order you visit the graph in decides whether it does anything at all.

The shape that works, as one chain:

```
pin the live record
  → the event log
  → containers whose satellites are keyed on a state flag (and those satellites)
  → containers that cascade to children
  → the remaining containers
  → the leaves, in batches
  → satellite rows already stranded before this run
  → checkpoint + compact
  → unpin
```

Measured on one real 57 MB database: 10 607 leaf rows went, along with 470 + 238 + 50 + 8 container
rows across four container tables and 8 818 satellite rows; the file came back at roughly 12 MB.

## Traps

**Leaf-first deletes nothing, and says so with a zero.** A leaf is orphaned only once every
container has stopped referencing it — so a sweep that starts at the leaves finds them all still
referenced and deletes none. Measured here: 11 322 of 12 221 tracks were held alive by cached
playlists that no other code path ever pruned, and the remainder by the other referencing tables
and the kept-by-state columns — so the track sweep on its own removed **zero rows** and reported
success. From outside this is indistinguishable from "the cache was already clean".
Fix: delete containers first, leaves last, and have every statement return its affected-row count so
the log shows where the sweep actually bit.

**"Referenced by nothing" is the wrong test for state columns.** A liked flag and a download marker
are not foreign keys — they are the *entire* storage backing the Favourites and Downloads libraries.
A track liked straight from a search result belongs to no playlist and no album, so the literal
reading of orphanhood deletes the user's favourites and their downloaded files' only database link.
Every such column has to appear as a predicate:

```sql
-- adapted
SELECT trackId FROM song
 WHERE liked = 0 AND downloadState = 0
   AND trackId NOT IN (SELECT trackId FROM playlist_track)
   ...
```

`downloadState = 0` does double duty: it also spares a download still in flight, which would
otherwise be deleted out from under the transfer. And every `NOT IN` subquery here is safe only
because the selected column is declared NOT NULL — over a nullable column the predicate silently
matches nothing (that failure has a sibling skill of its own: *sql-not-in-nullable-trap*).

**The same rule applies one level up, for a different reason.** A container that backs a kept leaf
should survive too — not because deleting it loses data, but because the leaf's detail page can no
longer render offline once its album artwork and track list are gone. Spare containers by
correlation with kept leaves, not by a blanket "keep everything":

```sql
-- adapted: an album stays if any liked or downloaded track points at it
DELETE FROM album
 WHERE liked = 0 AND downloadState = 0
   AND NOT EXISTS (SELECT 1 FROM song s
                    WHERE s.albumId = album.id AND (s.liked = 1 OR s.downloadState != 0))
```

**A precomputed id list is stale the moment you compute it.** Selecting orphan ids and then deleting
by id is two statements, and the user keeps liking and browsing in between. Repeat the orphan
conditions *inside* the DELETE rather than trusting the list:

```sql
DELETE FROM song WHERE trackId IN (:ids)
   AND liked = 0 AND downloadState = 0
   AND trackId NOT IN (SELECT trackId FROM playlist_track)   -- re-checked, not assumed
```

This matters most where a cascade points back at you: a join table that cascades on leaf deletion
means a track added to a playlist mid-sweep would be pulled straight back out of that playlist.

**The record in use looks orphaned.** Whatever is playing, open or being edited right now is often
persisted lazily — written on pause, on change, on exit, and only when the user opted into
persistence at all. So the live working set is frequently absent from the tables the sweep reads,
and gets deleted. Write it to disk before the sweep starts, deliberately ignoring the user's
persistence setting: this is not "remember my session", it is "do not delete what is on screen".
Then take the pin back out afterwards if the setting was off — leaving it there both stores state
the user declined *and* protects those rows from every future sweep, however long ago they stopped
being live.

**Satellite rows need two passes, not one.** Rows that hang off a leaf (cached lyrics, format
records, extra metadata) must be deleted **after** the leaf and **only for ids that actually went** —
the leaf DELETE above may spare a row, and a spared row must keep its satellites:

```sql
DELETE FROM lyrics WHERE trackId IN (:ids) AND trackId NOT IN (SELECT trackId FROM song)
```

That statement only ever reaches ids in flight, so satellites whose leaf disappeared in some earlier
build are unreachable to it and accumulate forever. Add a separate unconditional pass
(`WHERE trackId NOT IN (SELECT trackId FROM song)`) and run it once at the end.

**The id list will exceed the statement's parameter cap.** Engines limit how many bound values one
statement takes, and an orphan list runs to thousands. Chunk the deletes. Do not hardcode a limit
you read in a blog post — look up the cap for the engine version you actually ship, and pick a chunk
comfortably under it (this codebase uses 400).

## Verifying it

- Return `Int` from every delete and log the counts. A sweep whose numbers are all zero is a
  **signal**, not a clean database — the two most common causes are ordering and a `NOT IN` over a
  nullable column that can never evaluate true.
- Before shipping, count what each stage should find: run the container statement's `WHERE` clause as
  a `SELECT COUNT(*)` and compare it to the delete's reported count. A mismatch means a predicate is
  matching nothing rather than matching correctly.
- Check the file size before and after, not just the row counts — deletes free pages inside the file
  and return nothing to the filesystem until you compact.
