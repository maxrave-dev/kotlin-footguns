---
name: cache-then-network
description: Serve the stored copy immediately, then the fresh one, from a single repository flow — and emit an error only when nothing was served, because an error after a successful emission replaces working content the user is already reading. Use when a screen shows a spinner on every open despite having shown the same data a minute ago, or when a brief network failure blanks a screen that had perfectly good content on it.
---

# Cache first, then the network, from one flow

The method emits twice on a warm cache and once on a cold one. The caller does not know or care
which — it collects a flow of the usual success/error envelope (see
`repository-resource-flow-pattern`) and renders whatever arrives last.

```kotlin
// adapted — names generalized, and the source's outer runCatching around the whole request block
// is dropped here on purpose: it has no failure handler, so it is exactly the swallowed-emission
// case Verify step 2 below hunts for. Emission order is as written.
override fun getCatalogSections(): Flow<Resource<Catalog>> =
    flow {
        val cached = store.catalogCache.first()
            ?.let { runCatching { json.decodeFromString<Catalog>(it) }.getOrNull() }
        if (cached != null) {
            emit(Resource.Success(cached))
        }
        remote.catalog()
            .onSuccess { result ->
                val fresh = Catalog(result.map { CatalogSection(it.title, it.items.map(::toItem)) })
                emit(Resource.Success(fresh))
                store.setCatalogCache(json.encodeToString(fresh))
            }
            .onFailure { e ->
                // Already showing the cached copy — surfacing an error over it would replace
                // working content with an error state.
                if (cached == null) {
                    emit(Resource.Error(e.message.toString()))
                }
            }
    }.flowOn(Dispatchers.IO)
```

Three ordering decisions are doing all the work, and each is easy to get backwards:

- The cached value is emitted **before** the request starts, not raced against it.
- The fresh value is emitted **before** it is persisted. The user gets the content; the disk write
  is bookkeeping and its latency is nobody's problem.
- The cache is written **only** on success, so a failed request can never overwrite a good copy
  with an empty one.

## Traps

**Emitting an error after a success is the whole bug this pattern exists to prevent.** Without the
`if (cached == null)` guard, a screen that painted correctly from cache goes to an error state a
second later, when the user is already reading it — every time the network is flaky. The guard
must be keyed on *what was actually emitted*, not on whether caching is switched on or whether the
stored string was non-null: here it is the same local `cached` value that the `emit` above
consumed, which is why it cannot fall out of sync. If you add a second early-emission path, that
path has to feed the same variable or the guard silently stops covering it.

**A decode failure must degrade to a cache miss, never to a crash.** The stored copy is written by
whatever build was installed at the time, so treat it as untrusted input:
`runCatching { … }.getOrNull()` leaves `cached == null`, the flow behaves exactly like a cold
start, and the error path correctly re-enables itself. Calling `decodeFromString` bare here takes
down the read for every user whose stored copy predates the last model change. The lenient-decode
settings that go with this are in `ttl-keyed-json-cache-lenient-decode`.

**Both emissions are the same `Success` type, so the consumer cannot tell stale from fresh.** That
is a deliberate simplification, not an oversight — but it has consequences the caller has to
absorb. A screen that resets scroll position, restarts an animation, or re-runs an expensive
derivation on every emission will do all of it twice per open. Either make those reactions
idempotent, or add a freshness bit to the envelope; do not "fix" it by dropping the first emission,
which deletes the feature.

**This is not the same policy as an expiring cache, and the cadence of the data does not pick
between them.** Cache-then-network *always* hits the network and always shows something first. An
expiring cache returns early on a fresh entry and makes no request at all. The method above changes
about as often as the service ships a new section — slow enough that "cache it and skip the
request" sounds obvious — and still uses *this* policy, because one request per screen open is
cheap while a spinner on every open is not. What actually pushes a method to the expiring policy is
the **cost of the request**: a per-key resolution that fires once per tile, N times per screen (the
artwork lookup in `ttl-keyed-json-cache-lenient-decode`), where skipping the request is the entire
point. Both shapes legitimately live in one repository; decide per method by counting requests, not
by how stale the data is allowed to be.

**Persisting before emitting quietly reintroduces the spinner.** If the write is awaited first, the
fresh value reaches the screen after a disk round trip on every refresh — the exact latency the
cached emission was added to hide, moved to the other end of the method.

## Verifying it

The failure modes are invisible in the normal path, so test the two abnormal ones directly:

1. **Warm cache, network unreachable.** Collect the flow into a list. It must contain exactly one
   item and it must be a `Success`. An `Error` in that list is the bug.
2. **Cold cache, network unreachable.** The same list must contain exactly one `Error`. If it is
   empty, the guard is inverted or an outer catch is swallowing the emission.
3. **Warm cache, network reachable.** Two items, both `Success`, in cache-then-fresh order.

Assert on the *list of emissions*, not on the last value — every one of these bugs is about an
emission that should or should not have happened, and the last value alone hides all three. If the
collector conflates (a state holder that only keeps the latest, a fast local read with no real
delay before the response), the cached emission may never be rendered even though the flow emitted
it correctly; measure that at the UI, not at the repository.
