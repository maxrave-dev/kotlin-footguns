---
name: like-wildcard-escaping-ids
description: Matching a machine-generated id inside a text or JSON column with LIKE — why `_` and `%` in the id silently widen the match, how to escape them with nested replace() plus an explicit ESCAPE character, and why the id must be matched as a quoted token rather than as a bare substring. Reach for it when a cleanup spares rows it should have deleted, when a lookup returns a row belonging to a different id, or before putting any id into a LIKE pattern.
---

# LIKE wildcards in machine-generated ids

`LIKE` is not substring matching. `_` matches any single character and `%` matches any run of them,
and neither is opt-in — they are live in every pattern unless you escape them. Machine-generated ids
are full of `_`: in one measured dataset, **1 748 of the ids contained one**.

So a pattern built from the id `abc_def` also matches `abcXdef`. In a sweep that uses LIKE to decide
"is this id still referenced?", that means a row is spared because of an id it has nothing to do
with — the sweep deletes less than it should and reports success. In an inclusion query the same
mistake goes the other way and returns somebody else's row.

## The pattern that works

Escape `\`, then `_`, then `%`, wrap the id in the delimiters it actually has in the column, and
declare the escape character:

```sql
-- adapted: is this track id still listed inside any playlist's JSON array of ids?
NOT EXISTS (
  SELECT 1 FROM playlist
   WHERE playlist.tracks LIKE
         '%"' || replace(replace(replace(song.trackId, '\', '\\'), '_', '\_'), '%', '\%') || '"%'
         ESCAPE '\'
)
```

Two independent things are happening in that expression, and both are required: the nested
`replace()` neutralises the wildcards, and `'%"' || … || '"%'` pins the match to a whole token.

## Traps

**Escape order is not free.** `\` must be escaped **first**. Escaping it last would double the
backslashes the `_` and `%` passes just introduced, turning `\_` into `\\_` — a literal backslash
followed by "any character", which is the bug you were fixing plus a new one.

**Without an `ESCAPE` clause the escaping does nothing on many engines.** SQLite, SQL Server,
Oracle and the SQL standard define no default escape character for `LIKE`; PostgreSQL and MySQL
default to backslash — there the bare `replace()` happens to work, which is exactly what makes the
missing clause look portable. On the first group the nested `replace()` alone just inserts literal backslashes into the pattern,
so `\_` means "a backslash, then any character" and now matches *less* than it should. The clause is
what gives the character its meaning; it is not optional decoration.

**Parameter binding does not escape wildcards.** Binding protects you from quoting and injection, not
from pattern metacharacters — the driver has no idea the value is destined for a `LIKE`. A bound
parameter needs exactly the same treatment, escaped either in the host language before binding or in
SQL around the placeholder.

**When the value comes from a column, the host language cannot help at all.** ORMs escape bind
parameters; they cannot escape `other_table.some_column`. That is the case that forces the nested
`replace()` into the SQL itself, and it is worth a comment where it appears, because it looks like
noise that a well-meaning cleanup will "simplify" away.

**A bare substring match is not an identity match.** `'%' || id || '%'` finds the id inside a longer
id, so a short id matches a long one that merely contains it. Include the delimiters the storage
format guarantees. Verify the format first rather than assuming: for a JSON array of strings the id
is always stored as `"id"`, so quotes work — and they still work for an array of objects, where the
id remains a quoted value. A comma-separated column needs different delimiters, and one that stores a
bare id needs `=` rather than `LIKE` at all.

**Every escape hop needs escaping again.** Written inside a Kotlin/Java string the SQL backslash is
already doubled (`'\\_'` in source is `'\_'` in SQL), and if the string then passes through another
layer that processes escapes it doubles again. Confirm by logging the final SQL text the driver
receives, not the source line.

**It is a full table scan and no index can help.** A pattern with a leading `%` cannot use an index.
That is acceptable when the scanned tables hold at most a few hundred rows — as in the example above, where the
alternative was deserialising every playlist and the whole saved queue just to read one field back
out. It is not acceptable at a million rows: normalise those ids into a join table instead.

## Verifying it

- **Count the exposure before deciding it does not apply to you:**
  ```sql
  SELECT COUNT(*) FROM song WHERE trackId LIKE '%\_%' ESCAPE '\';
  ```
  If that returns anything above zero, every unescaped LIKE against those ids is already wrong.
- **Test with a deliberate near-miss.** Insert two rows whose ids differ only where the wildcard sits
  (`abc_def` and `abcXdef`), then run the pattern. Correct escaping returns one row; the unescaped
  version returns both. Do this rather than reading the pattern and convincing yourself.
- **Test a containment pair too** — an id and a longer id that ends with it — to prove the delimiters
  are doing their job independently of the escaping.
- **Log the finished statement.** Most of the mistakes above are visible in the SQL text and
  invisible in the source.
