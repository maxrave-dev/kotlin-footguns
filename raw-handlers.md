# Raw mining report — Lane 9: queue/catalog, StateFlow derivation, offline-first repos, cache/bitmap

> Mined 2026-08-19. 22 candidates. Neutral vocabulary. Both Android + JVM handlers implement the SAME queue algorithm against a platform-abstracted player (shared-by-copy) → queue candidates are KMP-portable.

## A. Queue / catalog management over a player

**1. queue-rebuild-state-machine** — paging fires twice / persists a half-built queue / spinner sticks after load.
- Two-state source flag (`STATE_INITIALIZING` → `STATE_INITIALIZED`) inside the queue's state object.
- Every append/rebuild entry (`loadMore`, `getRelated`, `loadMoreCatalog`, `updateCatalog`) early-returns while INITIALIZING → free re-entrancy protection.
- Persistence reads the same flag: recent-queue save skipped unless INITIALIZED, so no snapshot written mid-rebuild (list transiently emptied).
- Flip back to INITIALIZED on BOTH success and error before reordering.
- Evidence: `MediaServiceHandlerImpl.kt:1267-1268,1531,1647-1656,1769-1789,2172-2200`. Generality: B.

**2. dual-source-queue-sync (engine timeline ↔ domain list)** — keep UI list in the order the player actually plays, incl. after shuffle.
- Keep UI `listTracks` alongside engine's (shuffled) timeline; engine is source of truth for order.
- On `onTimelineChanged`, re-derive domain list by mapping each engine item's `mediaId` back to the domain track (`reorderShuffledQueue`).
- Bail the reorder if mapped size ≠ domain size (partial/stale timeline) rather than writing a broken order.
- User moves (`moveItemUp/Down`, `playNext` at `currentIndex+1`) mutate BOTH engine (`player.moveMediaItem`) and list, then re-sync `currentSongIndex`.
- Evidence: `MediaServiceHandlerImpl.kt:1585-1623,2013-2131,2715-2751`; `JvmMediaPlayerHandlerImpl.kt:2811-2830`. Generality: B.

**3. chunked-catalog-rebuild-skip-current** — rebuilding a large queue blocks or drops the playing track.
- Snapshot list, empty queue state, rebuild in fixed chunks (`chunked(100)`) so a huge queue doesn't rebuild in one pass.
- Capture currently-playing item by index up front and `continue` past it → never re-added/double-inserted.
- Re-insert per-chunk metadata incrementally, then a single terminal reorder.
- Evidence: `MediaServiceHandlerImpl.kt:1769-1797,1978-1982`. Generality: C.

**4. continuation-token-pagination-contract** — wrap an endpoint returning page + next-token as a clean repo flow.
- Contract: remote paged reads → `Flow<Resource<Pair<items, nextToken?>>>`; `null` token = end.
- Consumer stores token in queue/UI state, calls `loadMore`, replaces token from response, stops on `null`.
- Bounded prefetch to start: `while (token != null && count < 3)`, early exit once accumulated `>= 50`, failed page terminates loop.
- Evidence: `MediaServiceHandlerImpl.kt:1453-1511,1530-1563`; `PlaylistRepositoryImpl.kt:151-170`. Generality: A.

**5. encoded-continuation-tokens-for-local-sort-shuffle** — page a locally-sorted/shuffled list through the same continuation slot as remote.
- Reuse the single `continuation: String?` to carry LOCAL paging state by prefixing with a mode tag (asc/desc/title/custom-order/shuffle) + cursor.
- Cursor form by mode: offset int (stable orders), serialized timestamp (time-ordered, resume after instant), or serialized shuffled index-list + page number (shuffle).
- Decode by prefix at top of `loadMore`, compute "is last page", advance cursor, null out at end.
- Evidence: `MediaServiceHandlerImpl.kt:1276-1451` (shuffle 1291-1324; time 1344-1403; offset 1405-1449). Generality: B.

**6. endless-queue-auto-radio-append** — auto-continue with related tracks when playlist runs out.
- When continuation exhausted + "endless" setting on, derive a radio/seed id from last track, swap into queue's playlist id.
- Guard against re-seeding when already in that radio context (compare derived id to current) → no infinite append.
- Evidence: `MediaServiceHandlerImpl.kt:1486-1527,1530-1563`. Generality: C.

**7. polymorphic-load-media-entry-point** — one function to start playback from song/video/playlist/album/radio.
- Generic `loadMediaItem<T>(anyTrack, type, index)` normalizes types into one track type via `when`.
- A `type` discriminator routes the SEED strategy: single → fetch related to seed queue; playlist/album/radio → paged load at index.
- Pre-enqueue policy gates here (explicit-content → toast + abort; first item auto-prepares; "recover" restores without auto-play).
- Evidence: `MediaServiceHandlerImpl.kt:2134-2166`; auto-prepare `addMediaItemNotSet:749-761`. Generality: B.

**8. dual-mode-persist-blocking-or-async** — save periodically in background but synchronously on teardown.
- Define save body once as `suspend { }`; take `runBlocking: Boolean`; execute via `runBlocking { }` on shutdown, `scope.launch { }` otherwise.
- Split heavy (full-queue rewrite, guarded by rebuild-state flag) vs light (position-only tick, frequent).
- Evidence: `MediaServiceHandlerImpl.kt:2172-2222`. Generality: A.

## B. StateFlow / combine derivation

**9. readonly-stateflow-exposure-and-cold-to-hot** — expose mutable state safely; turn a settings/DataStore flow into StateFlow.
- Backing `MutableStateFlow` private; expose `asStateFlow()`/`asSharedFlow()`.
- Cold→hot: `flow.stateIn(scope, SharingStarted.WhileSubscribed(5000L), initial)` — upstream stops 5s after last collector (survives config/recomposition churn, no leak).
- Evidence: `SharedViewModel.kt:128-209` (`openAppTime:207`); handler `:133-198`. Generality: A.

**10. flatmaplatest-resubscribe-plus-composite-key-gate** — re-run a side effect only when a derived tuple truly changes, not every progress tick.
- `flatMapLatest` from a key flow (now-playing) into a fast flow (timeline) so the pair re-subscribes when key changes.
- `distinctUntilChanged { old,new -> }` on a COMPOSITE key (hash of duration + item id) collapses high-frequency emissions to "meaningful change" before firing expensive one-shot work.
- Inside collector, also guard "only if not already loaded" → idempotent.
- Evidence: `SharedViewModel.kt:221-250`. Generality: A.

**11. distinct-by-key-reset-and-cancel-per-item-job** — reset per-item UI and cancel the previous item's in-flight work when current item changes.
- `distinctUntilChangedBy { it.key }` → collector runs only on actual item change.
- First action: cancel previous per-item `Job` (`canvasJob?.cancel()`) before new work → no stale results bleed in.
- Reset derived screen state to `initial()`, then progressively fill.
- Evidence: `SharedViewModel.kt:298-320`. Generality: B.

**12. combine-two-flags-to-gate-a-feature** — enable an expensive subsystem only when several conditions hold; tear down when any drops.
- `combine(flagA, flagB) { a,b -> a && b.isValid() }.distinctUntilChanged().collectLatest { on -> }`.
- `collectLatest` cancels in-flight work on flip; each start branch idempotent so on→off→on can't skip re-creation.
- Base variant: `combine(nowPlaying, controlState)` to expose a derived id only while playing.
- Evidence: `MediaServiceHandlerImpl.kt:420-448`; `BaseViewModel.kt:95-107`. Generality: A.

## C. Offline-first repository composition

**13. repository-flow-conventions** — consistent repo shapes over Room + a network source.
- Local read: `flow { emit(local.x()) }.flowOn(IO)`. Remote read: `flow { runCatching { api.x().onSuccess{ emit(Success(parse)) }.onFailure{ emit(Error(msg)) } } }.flowOn(IO)`. Writes: `withContext(IO){ dao.write() }`.
- Evidence: `AlbumRepositoryImpl.kt:29-144`, `HomeRepositoryImpl.kt:62-403`, `PodcastRepositoryImpl.kt`. Generality: A.

**14. cache-then-network (stale-while-revalidate)** — paint instantly from cache, then refresh, without flashing an error over good content.
- One flow: read cache first, `emit(Success(cached))` if present; then network, `emit(Success(fresh))`.
- On network failure, only `emit(Error)` when nothing was cached — never replace shown content with an error.
- Persist fresh result back after emitting.
- Evidence: `HomeRepositoryImpl.kt:283-327`. Generality: A.

**15. ttl-keyed-json-cache-lenient-decode** — cache resolved values that drift over time and survive model changes.
- Wrap cached values with a fetch timestamp; `isStale()` vs a TTL constant; serve only if present AND not stale, else re-resolve + re-store.
- Store a whole keyed map serialized as JSON; merge-and-rewrite on each resolution.
- Decode with lenient JSON (`ignoreUnknownKeys = true`) so a cache written by an older build doesn't crash after the model gains a field.
- Evidence: `HomeRepositoryImpl.kt:31-60,329-363`. Generality: A.

**16. generic-paged-db-accumulator** — read an entire table through a (limit, offset) DAO without an unbounded query.
- Generic `getFullDataFromDB(func: suspend (limit, offset) -> List<T>): List<T>` loops fixed pages, accumulates, stops when a page returns fewer than page size.
- Reused across "get all liked/favorite" reads; bounds memory + query size, centralizes termination.
- Evidence: `DatabaseExt.kt:1-23`; callers `AlbumRepositoryImpl.kt:41-51,90-97`, `PodcastRepositoryImpl.kt:211-255`, `PlaylistRepositoryImpl.kt:66-71`. Generality: A.

**17. two-way-sync-state-machine-delta-diff** — mirror a local list with a remote list, pushing only what changed.
- Per-record sync-state enum (NotSynced/Syncing/Synced); flip to Syncing before push, Synced on success → interrupted sync is resumable + observable.
- Compute delta (new local items not on remote), push only that set.
- Keep local↔remote id mapping so later edits/removals target the right remote record.
- Evidence: `LocalPlaylistRepositoryImpl.kt:244-353,359-411,434-478,555-566`. Generality: B.

**18. order-preserving-section-mapping** — a sectioned response breaks when the backend inserts/removes a section.
- Map ALL sections in received order into `Section(title, items)` instead of `result[0]`/`result[1]`.
- Resilient to an extra leading section appearing (e.g. a personalized shelf) without index drift.
- Evidence: `HomeRepositoryImpl.kt:299-316`. Generality: B.

## D. Cache boundary, bitmap loading

**19. cache-completeness-check-before-serving** — decide if a cached media resource is safe to play from disk.
- Fully usable only when all three hold: known total length (>0), requested position inside it, AND full byte range `isCached(key,0,total)` present.
- Stored length alone is insufficient — written as soon as length is known, long before bytes finish; a truncated upstream records a short length, so the position guard prevents an out-of-range read the player refuses to retry.
- Treat the answer as a momentary snapshot: an evictor / "clear cache" can delete spans right after — short trust window.
- Evidence: `Media3Ext.kt:210-237` (`Cache.isFullyCached`). Generality: B.

**20. coil-to-media3-bitmaploader-bridge** — supply artwork bitmaps to a media session/notification via an existing image loader.
- Implement `BitmapLoader` bridging coroutines → Guava `ListenableFuture` with `coroutineScope.future(IO) { }`.
- Run the app's Coil `imageLoader.execute(request)` inside; convert ErrorResult/null → `ExecutionException` so the media stack sees a real failure.
- `allowHardware(false)` so the bitmap is safe across threads / to notification APIs.
- Evidence: `CoilBitmapLoader.kt:20-53`. Generality: B.

**21. role-keyed-multi-cache-registry** — manage several on-disk caches (player/download/artwork) behind one API.
- Inject multiple `SimpleCache`; dispatch size/clear/list by a role name constant. `clearCache` iterates `cache.keys` + `removeResource`; size via `cacheSpace`; unknown role = safe no-op/0.
- Evidence: `CacheRepositoryImpl.kt:9-61`. Generality: B.

**22. thumbnail-upscale-and-track-vs-video-heuristic** — normalize thumbnail URLs and classify audio track vs music video.
- Upscale by regex-rewriting the width/height token (`Regex("([=-][wh])\\d+").replace(url,"$1544")`); fall back to a deterministic max-res URL.
- Classify song vs video from thumbnail geometry: a SQUARE thumbnail with known non-zero height + URL lacking video-frame markers → song; stamp into item description for later `isSong()`/`isVideo()`.
- Evidence: `Media3Ext.kt:71-119`; handler `:1660-1677,1798-1814,2022-2039`. Generality: C.

## Duplicates (covered, not re-counted)
Position-persistence tick, loudness normalization, segment-skipping, sleep-fade, scrobble, named-job discipline, abstract player interface, system media/command buttons. #1 and #8 are NEW persistence angles; #20's coroutine↔future bridge is the NEW system-media-artwork angle.

## Not reached
- JVM handler full bodies (grep-confirmed identical algorithm shared-by-copy → no JVM-only queue pattern).
- SharedViewModel ~320-2057 (only top derivation block sampled); ArtistRepositoryImpl / SongRepositoryImpl / StreamRepositoryImpl bodies; PlaylistRepositoryImpl 206-791.
- WART (not a skill, worth a fix): `ArtistRepositoryImpl.kt.kt` has a double `.kt.kt` extension in `core/data/.../repository/`.
