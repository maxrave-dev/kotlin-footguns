---
name: ttl-keyed-json-cache-lenient-decode
description: A small keyed cache for values that drift — each entry carries the moment it was fetched and answers an isStale check against a time-to-live constant, the whole map is stored as one JSON string in key-value preferences, and decoding is lenient plus wrapped so a schema change degrades to a cache miss instead of destroying every entry. Use when caching resolved covers, lookups or per-key results without a database table, or when a cache stopped working entirely after a model field was added.
---

# A keyed cache with an expiry, stored as one JSON blob

Small enough not to deserve a table, big enough that re-resolving on every open is rude. Each entry
carries its own fetch time, so expiry is a property of the value rather than of the whole file:

```kotlin
// adapted — names generalized, and the resolution chain condensed: `pickThumbnailUrl` stands in
// for six lines of the source (parse the response, walk its sections, take the *last* thumbnail of
// the first item that has one). The name is invented here; do not read a `first…` into it.
@Serializable
private data class CachedArtwork(val url: String, val cachedAt: Long) {
    fun isStale(): Boolean =
        Clock.System.now().toEpochMilliseconds() - cachedAt > ARTWORK_CACHE_TTL_MILLIS
}

/** Time-to-live (TTL): how long a resolved entry stays usable before it is fetched again. */
private const val ARTWORK_CACHE_TTL_MILLIS = 7L * 24 * 60 * 60 * 1000

private val cacheJson = Json { ignoreUnknownKeys = true }

override fun getCategoryArtwork(key: String): Flow<String?> =
    flow {
        val cache = readArtworkCache()
        val hit = cache[key]
        if (hit != null && !hit.isStale()) {
            emit(hit.url)
            return@flow                                   // fresh hit: no request at all
        }
        val resolved = remote.category(key).getOrNull()?.let(::pickThumbnailUrl)
        emit(resolved)
        if (resolved != null) {
            store.setArtworkCache(
                cacheJson.encodeToString(
                    cache + (key to CachedArtwork(resolved, Clock.System.now().toEpochMilliseconds())),
                ),
            )
        }
    }.flowOn(Dispatchers.IO)

private suspend fun readArtworkCache(): Map<String, CachedArtwork> =
    store.artworkCache.first()
        ?.let { runCatching { cacheJson.decodeFromString<Map<String, CachedArtwork>>(it) }.getOrNull() }
        .orEmpty()
```

The stored value is a `Map<String, CachedArtwork>` encoded as a single string. Preferences storage
holds strings, so one blob is the whole cache; a lookup decodes all of it.

## Traps

**`ignoreUnknownKeys` and the surrounding catch cover two different schema changes, and only one
of them is the common one.** `ignoreUnknownKeys = true` handles keys that are *in the stored JSON
but no longer on the class* — a field you **removed**, and only removed. It does nothing for the
opposite and far more likely case: you **add** a property, every previously stored entry lacks it,
and decoding fails with a missing-field error. A **rename** belongs on that failing side, which is
the one people get backwards: it is a removal *and* an addition at once, so the flag duly ignores
the old key — and then the new property has nothing to read and the decode fails anyway, exactly as
a plain addition does. What saves you there is the `runCatching { … }.getOrNull()` and
the trailing `.orEmpty()`, which turn the failure into an empty map — a total cache miss, one round
of re-resolution, and no crash. Keep both, and give new properties defaults so the common case
degrades to a partial read rather than a wipe. Attributing the protection to the lenient flag alone
is how a codebase ends up with the flag set and the catch removed.

**Merge-and-rewrite is a read-modify-write with no lock.** Two resolutions in flight at once each
decode the same base map and each encode their own copy back; the second write lands last and the
first entry is gone. It costs a request, not correctness, so it is worth accepting for a cache of
this size — but only knowingly. If several keys are routinely resolved together, resolve them into
one map and write once.

**Nothing evicts.** An entry is only replaced when its own key is requested again, so a key that is
never asked for again keeps its slot forever and the blob grows with every distinct key the app has
ever seen. Every lookup pays to decode all of it. Fine at tens of entries, wrong at thousands —
when the key space is unbounded, this shape is the wrong one, and a table with an index is the
answer.

**Expiry rides the wall clock, so a clock change is a cache event.** `now - cachedAt > TTL` goes
negative when the device clock moves backwards, which makes every existing entry permanently fresh
until real time catches up; a clock jumped forwards expires everything at once. Neither is worth
defending against for cosmetic data, and both are worth knowing before you use the same helper for
something that must not be stale.

**A resolution that legitimately finds nothing is never cached.** The write is guarded by
`if (resolved != null)`, so a key with no result is re-requested on every single call — the exact
opposite of what a cache is for, and invisible unless you count requests. If misses are common,
store them: an entry whose value is null but whose timestamp is real.

**The fresh-hit path returns before the request, which is the opposite of serving stale content
while revalidating.** That is the right trade here — the value changes on the order of the
time-to-live — but do not reach for this shape when the user expects current data. `cache-then-network`
is the other policy, and the two can coexist in one repository as long as each method's choice is
deliberate.

## Verifying it

Both interesting paths are time- and history-dependent, so drive them directly:

- **Expiry:** write an entry whose `cachedAt` is `now - TTL - 1` and assert that a request is made.
  Waiting out a seven-day time-to-live is not a test, and shortening the constant for the test
  changes the thing under test.
- **Fallback:** store `"{"` (or last release's JSON shape) and assert the read returns an empty map
  and the caller re-resolves. A test that only stores well-formed current-shape JSON passes on a
  version with no catch at all.
- **Growth:** after resolving N distinct keys, assert the decoded map has N entries. Silent
  overwrites from the read-modify-write race show up here and nowhere else.
