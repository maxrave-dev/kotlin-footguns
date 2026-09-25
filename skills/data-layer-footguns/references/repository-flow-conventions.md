---
name: repository-flow-conventions
description: One table of method shapes for a repository sitting over a local database plus a remote API — local reads as a cold flow moved onto the IO dispatcher, remote reads as a flow of a success/error envelope, writes as withContext. Use when adding methods to a repository, when reviewing one whose shapes have drifted apart, or when a screen sits on its loading state forever with nothing in the log.
---

# Repository method shapes

Pick the shape by *where the data comes from*, not by what is convenient at the call site. Four
shapes cover everything a repository over a database and a network API does:

| Kind of method | Shape | Why this one |
|---|---|---|
| One-shot local read | `flow { emit(local.x()) }.flowOn(IO)` | one value, computed lazily on first collection, off the caller's thread |
| Live local read | the database's own `Flow`, returned unchanged | the database library already re-emits on every write and already confines the query |
| Remote read | `flow { api.x().onSuccess { emit(Success(map(it))) }.onFailure { emit(Error(msg)) } }.flowOn(IO)` | a call that can fail needs somewhere to put the failure |
| Write | `suspend fun … = withContext(IO) { local.x() }` | nothing to observe; the caller awaits completion |

```kotlin
// adapted — service and entity names generalized, and two bodies deliberately corrected: the
// source wraps `getAlbumData` in an outer runCatching with no failure handler (the FIRST trap
// below) and writes `updateAlbumLiked` on the Main dispatcher (the THIRD). This is the shape to
// copy, not the shape you will find.
internal class AlbumRepositoryImpl(
    private val local: LocalDataSource,
    private val remote: CatalogApi,
) : AlbumRepository {

    override fun getAllAlbums(limit: Int): Flow<List<AlbumEntity>> =
        flow { emit(local.getAllAlbums(limit)) }.flowOn(Dispatchers.IO)

    override fun getAlbumAsFlow(id: String) = local.getAlbumAsFlow(id)      // live; no flowOn

    override suspend fun updateAlbumLiked(albumId: String, likeStatus: Int) =
        withContext(Dispatchers.IO) { local.updateAlbumLiked(likeStatus, albumId) }

    override fun getAlbumData(albumId: String): Flow<Resource<AlbumBrowse>> =
        flow {
            remote.album(albumId, withSongs = true)
                .onSuccess { emit(Resource.Success(parseAlbumData(it))) }
                .onFailure { emit(Resource.Error(it.message.toString())) }
        }.flowOn(Dispatchers.IO)
}
```

The success/error envelope itself — its states, and how callers unwrap it — is the subject of
`repository-resource-flow-pattern`. This skill is only about which methods get one.

## Traps

**Wrapping the whole body in a catch-all turns a mapper crash into silence.** The remote shape is
often written as `flow { runCatching { api.x().onSuccess { emit(…) }.onFailure { emit(…) } } }`.
That outer `runCatching` has no `onFailure` of its own, and the mapping call sits *inside* it — so
when the parser throws on a response shape it did not expect, neither `emit` runs, the throwable is
discarded, and the flow **completes normally having emitted nothing**. The collector's `when` over
the envelope never executes and the screen keeps whatever state it had, which is the spinner. No
crash, no log line, no error state. Either drop the outer catch and let the exception reach the
collector, or give it an `onFailure` that emits an `Error`. Do not leave it half-written.

**Two envelopes in one interface force callers to invent a third.** When one paged read returns
`Flow<Resource<Pair<List<T>, String?>>>` and its neighbour returns a bare
`Flow<Pair<List<T>?, String?>>`, the bare one has nowhere to report failure — so its implementation
emits `Pair(null, null)`, and the caller ends up reading `null` as *both* "no more pages" and "the
request failed". A caller that stops paging on `null` stops on the first network hiccup and calls
it the end of the list. Pick one envelope for every method that can fail.

**A write on the wrong dispatcher is invisible while the persistence library covers for you.**
Several update methods here read `withContext(Dispatchers.Main)` instead of `IO`. Nothing breaks
today, because the underlying data-access functions are `suspend` and the persistence library moves
the query onto its own executor regardless — so the hop to the main thread is a wasted round trip,
not a stall. That is precisely why the drift survives review: correctness is coming from the
library, not from the code, and the day one of those calls becomes a blocking one the convention
that was supposed to prevent it is already gone. Fix them to `IO` and keep them there.

**A one-shot read and a live read are different contracts with the same return type.** Both are
`Flow<T?>`; one emits once and completes, the other emits forever. A caller that uses `.first()` on
the live one gets the current row and drops every later update; a caller that collects the one-shot
one waiting for changes waits forever. Name them apart — the suffix on `getAlbumAsFlow` next to
`getAlbum` is doing real work.

**Do not mark a function `suspend` when it only builds a flow.** One read here is
`suspend fun getAll(): Flow<List<T>>`. The flow builder is cold, so the `suspend` buys nothing and
costs the caller a coroutine just to *obtain* a flow it has not collected yet — which usually means
the caller launches one, then collects inside it, and now owns two scopes for one read.

**A two-state envelope makes every `when` over it exhaustive by accident.** With only `Success` and
`Error`, consumers legitimately write two-branch `when` expressions with no `else`. Adding a third
state later is a compile error at every one of them — which is the good outcome, as long as you
expect it. Check the blast radius before adding the state, not after.

## Verifying it

Drift is per-method, so read it per-method. Count, do not skim — and **quote the include glob**, or
a shell that expands globs itself will fail the command before `grep` ever sees it. Keep the glob
loose at both ends (`*RepositoryImpl*.kt*`): a tight `*RepositoryImpl.kt` silently skips platform
suffixes (`…Impl.android.kt`) and typo'd doubled extensions — this repository has an
`ArtistRepositoryImpl.kt.kt`, and missing it undercounts both totals. A file you never see is
indistinguishable from a file with nothing in it, which is the failure mode "count, do not skim" is
supposed to prevent:

```bash
grep -rc 'withContext(Dispatchers.Main)' --include='*RepositoryImpl*.kt*' .
grep -rc 'withContext(Dispatchers.IO)'   --include='*RepositoryImpl*.kt*' .
grep -rn 'suspend fun .*: Flow<'         --include='*RepositoryImpl*.kt*' .
```

The first two together tell you the shape of the exception, not just that one exists: a handful of
`Main` against dozens of `IO` is drift to fix; an even split means the convention was never agreed
and writing it down is the first job. The third finds the suspend-returning-flow methods.

To confirm the silent-completion trap in your own code, collect a remote read with a deliberately
broken mapper and assert that *something* was emitted. A test that only asserts "no exception
thrown" passes on the broken version.
