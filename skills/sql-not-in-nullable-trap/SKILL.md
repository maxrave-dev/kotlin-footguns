---
name: sql-not-in-nullable-trap
description: Why `x NOT IN (subquery)` matches zero rows and still reports success whenever a NULL is actually present in the subquery result — a standing risk for any nullable column — how to guard every such subquery, and how to make a silently-inert statement detectable instead of invisible. Reach for it when a DELETE or SELECT with a NOT IN filter returns nothing on data you can see with your own eyes, when a cleanup pass "succeeds" and frees nothing, or before writing any NOT IN over a nullable column.
---

# The NOT IN / NULL trap

`NOT IN` over a subquery is the most common way to write a statement that can never be true.
It throws nothing, logs nothing, and matching zero rows is a perfectly ordinary outcome for a
`DELETE`, so the failure has no symptom at all except work that quietly does not happen.

Measured here: one playlist-cleanup statement deleted **0 rows and reported no error** for as long as
it existed, because the column it filtered against was nullable and mostly NULL.

## The mechanism, exactly

`x NOT IN (a, b, c)` is defined as `NOT (x = a OR x = b OR x = c)`. Comparing anything to NULL is
NULL, not false. So with a NULL anywhere in the list:

| case | inner OR | negated | matches? |
|---|---|---|---|
| `x` **is** in the list | `TRUE OR NULL` → `TRUE` | `FALSE` | no — correct |
| `x` is **not** in the list | `FALSE OR NULL` → `NULL` | `NULL` | **no — wrong** |

Rows that should be excluded are still excluded. Rows that should match never do. The net result is
zero matches, and no case anywhere produces an inverted or partial answer that would look wrong on
inspection.

## Traps

**One NULL anywhere in the subquery poisons the whole statement.** Not "rows with NULL behave oddly"
— *every* row of the outer table stops matching. A column that is 99% populated is exactly as fatal
as one that is entirely NULL.

**`IN` is safe where `NOT IN` is not, which is why this survives review.** A positive `IN` still
returns TRUE for a genuine match, so the same NULL in the same subquery is harmless there. Reviewers
who have written `IN` over that column a hundred times have no reason to suspect it.

**Nullability is a schema fact, not a data fact.** "There are no NULLs in production today" is not a
guard — it is a race with the next feature that inserts one. Guard on the schema:

```sql
-- adapted, and the IS NOT NULL is the whole fix
DELETE FROM playlist
 WHERE liked = 0 AND downloadState = 0
   AND id NOT IN (SELECT remotePlaylistId FROM playlist_sync)                       -- column is NOT NULL
   AND id NOT IN (SELECT remotePlaylistId FROM local_playlist
                   WHERE remotePlaylistId IS NOT NULL)                              -- nullable: guarded
```

**Write down why an unguarded `NOT IN` is unguarded.** Once some subqueries carry `IS NOT NULL` and
others do not, the missing guard reads as an oversight. A one-line comment naming the column as
NOT NULL turns "someone forgot" into "someone checked" — and gives the next reader something to
re-verify if the schema changes.

**`NOT EXISTS` sidesteps the whole thing.** A correlated `NOT EXISTS` compares row by row, and a
subquery row whose column is NULL simply fails its own comparison and is ignored:

```sql
DELETE FROM playlist AS p
 WHERE NOT EXISTS (SELECT 1 FROM local_playlist AS l WHERE l.remotePlaylistId = p.id)
```

(The `AS` is not decoration: some engines — SQLite among them — reject a bare `DELETE FROM playlist p`
as a syntax error, while accepting the aliased form only with `AS`.)

Prefer this form for anything new. Keep `NOT IN` only where the column is provably NOT NULL and the
list is small — and note that a `LEFT JOIN … WHERE joined.col IS NULL` is NULL-safe in the same way.

**The trap is a shape, not a SQL quirk.** "A condition that can never be true, on a code path with no
success signal" also describes a guard added to only one of two trigger paths, or a platform
implementation stubbed out to a no-op. Treat *any* change that ships with no observable difference as
unverified until you have made it observable.

## Verifying it

Do all three of these before believing a `NOT IN`:

1. **Count the NULLs in the subquery column.** One statement, decides the question:
   ```sql
   SELECT COUNT(*) FROM local_playlist WHERE remotePlaylistId IS NULL;
   ```
   Anything above zero means every `NOT IN` against that column currently matches nothing.

2. **Run the discriminating test rather than reasoning about it.** Execute the statement in both
   forms — `NOT IN` and the equivalent `NOT EXISTS` — against the same data. If the counts differ,
   you have found it; if they agree, the column really is clean *today*.

3. **Make the statement report.** Declare the DAO method to return the affected-row count, log it,
   and treat a sweep whose stages are all zero as a failure signal rather than as "nothing to do".
   This is the only detection that keeps working after the schema changes under you.
