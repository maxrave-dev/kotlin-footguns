---
name: remote-index-cached-as-rows-with-validator
description: Cache a large published index by parsing it into indexed rows once and re-checking it with the server's own ETag, so a routine freshness check costs a couple of hundred bytes — replaying the stored validator only while rows exist, treating a 200 that parses to nothing as a failure, and never letting a failed check refresh the timestamp. Use when a browsable catalogue is fetched from a static host, or when a cached index went empty and never refilled.
---

# A remote index, stored as rows, revalidated by ETag

Some catalogues are published as one big static file — hundreds of kilobytes, thousands of entries,
updated occasionally. Three separate decisions make this cheap:

1. **Rows, not a blob.** Parse once into a table so a search is an indexed query, not a re-parse.
2. **A time-to-live before you even ask** whether the file changed.
3. **The server's own validator** for the ask itself, so "unchanged" costs headers only.

```kotlin
suspend fun refreshIndex(force: Boolean): Boolean {
    val meta = local.indexMeta()
    val cached = local.entryCount()
    val now = Clock.System.now().toEpochMilliseconds()
    if (!force && meta != null && cached > 0 && now - meta.fetchedAt < INDEX_TTL_MS) return false

    // Replayed ONLY while there are rows it could be describing.
    val etag = meta?.etag?.takeIf { cached > 0 }
    return when (val result = remote.fetchIndex(etag)) {
        is NotModified -> { local.updateIndexMeta(meta!!.copy(fetchedAt = now)); false }
        is Updated     -> { local.replaceIndex(result.entries, Meta(result.etag, now)); true }
        is Failed      -> false          // rows AND fetchedAt both left alone — see below
    }
}
```

This is the sibling of `ttl-keyed-json-cache-lenient-decode`, and the difference is the whole
point. That one keeps a *map of independently-resolved values*, each carrying its own fetch time,
encoded as a single JSON string in preferences — right for tens of entries, wrong for thousands,
because every lookup decodes all of it. Here the payload is **one document with one freshness
signal**, the key space is large, and the query is a substring search — so it is a table with an
index, and the timestamp belongs to the document rather than to any entry.

## Traps

**Replaying the validator when the table is empty makes the emptiness permanent.** A stored ETag
outliving its rows — a failed transaction, a partial migration, a manual wipe — earns a clean 304
on every subsequent check. The app is then correct-by-protocol and empty forever, and no amount of
retrying helps because the server is answering exactly what was asked. `takeIf { cached > 0 }` is
the whole fix, and its absence has no symptom until the day the rows go.

**A 200 that parses to zero entries is a parse failure, not an empty catalogue.** Published index
formats drift: a heading changes, a list marker changes, the file moves to a different shape. The
fetch succeeds, the regex matches nothing, and a naive pipeline replaces a perfectly good cache
with nothing — and then stores a *fresh* ETag for the shape it could not read. Classify it as a
failure at the parse boundary:

```kotlin
val entries = parseIndex(response.bodyAsText())
if (entries.isEmpty()) Failed("index parsed to zero entries") else Updated(entries, response.etag)
```

**A failed check must not refresh the timestamp.** It is the most natural line to write — "we just
checked, record that" — and it converts one network blip into a week of silence, because the
time-to-live then blocks the retry. Success and not-modified refresh it; failure touches neither
the rows nor the timestamp.

**Not-modified *must* refresh it, though.** The asymmetry is easy to get backwards. A 304 is a
successful check with a negative answer; leaving `fetchedAt` alone there makes the app re-ask on
every single launch, which is cheap but not free, and it defeats the reason the time-to-live exists.

**Rows and validator have to land in one transaction.** Written separately, a crash between them
leaves an ETag describing an index the table does not hold — and the next check gets a 304 against
rows that were never written, which is the permanent-emptiness trap arriving by a second route:

```kotlin
@Transaction
suspend fun replaceIndex(entries: List<Entry>, meta: Meta) {
    deleteAllEntries(); insertEntries(entries); upsertMeta(meta)
}
```

**A weak validator is still worth sending.** `W/"…"` on a static host is normal and answers 304
exactly the same way. Skipping the conditional request because the ETag "looks wrong" turns every
check back into a full download. Send whatever the server gave you, verbatim, including the quotes.

**Browsing the index offline and then failing at the last tap is worse than not browsing at all.**
The index holds names; the payload per entry is usually its own small file. Cache each payload as it
is fetched, keyed by the same path the index carries, so an entry used once keeps working with no
connection.

**A user-typed term goes into `LIKE`, so escape its wildcards.** `_` matches any character and is
common inside identifiers; `%` matches anything. Escape `\` **first**, then `_` and `%`, and declare
`ESCAPE '\'` — escaping the backslash last would escape the backslashes you just added:

```kotlin
private fun String.escapeForLike() = replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")
```

**`force` should skip the time-to-live and keep the validator.** A manual "check for updates" that
also drops the ETag turns a two-hundred-byte round trip into a full download every time the user
taps it. Parsing the response is where the cost is; the conditional request is what makes the tap
free when nothing changed.

## Verifying it

Measure before choosing this shape at all — the size of the document is the argument for rows:

```bash
curl -sIL "$INDEX_URL" | grep -iE 'content-length|etag|last-modified'   # uncompressed: the true size
# Then prove the conditional request actually saves the body. `--compressed` on BOTH calls, because
# that is what a real client sends — and it is what makes this host answer with the weak `W/"…"`
# validator the trap above is about, rather than the strong one the bare HEAD shows.
# `-L` on the measuring call is load-bearing: without it a redirecting index URL prints `302 0`,
# which reads exactly like a pass, because a redirect body is empty too.
etag=$(curl -sIL --compressed "$INDEX_URL" | grep -i '^etag:' | cut -d' ' -f2- | tr -d '\r')
curl -sL --compressed -o /dev/null -w '%{http_code} %{size_download}\n' -H "If-None-Match: $etag" "$INDEX_URL"
curl -sL --compressed -o /dev/null -w '%{http_code} %{size_download}\n' -H 'If-None-Match: "x"' "$INDEX_URL"
```

The first of those two should print `304 0`; the second — a deliberately bogus validator — must print
`200` and a non-zero size, or the check is answering 304 to everything and proves nothing. Then the
three states that only appear under fault injection:

- **empty table, live validator** — delete every row, leave the meta row, call refresh, assert rows
  are repopulated. Without `takeIf { cached > 0 }` this asserts zero, forever;
- **200 with an unparseable body** — assert the existing rows and the old `fetchedAt` both survive;
- **transport failure** — assert `fetchedAt` is unchanged, then call refresh again immediately and
  assert a second request was made rather than a time-to-live short-circuit.
