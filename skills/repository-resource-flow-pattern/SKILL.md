---
name: repository-resource-flow-pattern
description: An envelope family for repository results — a remote wrapper, a local wrapper with a loading state, and a payload-free variant — plus the wrap-side and collect-side helpers that stop every view model from hand-writing the same branch, where the mapping from transport model to domain model belongs, and the one thing the envelope must never swallow. Use when designing repository return types, when error handling has drifted apart between screens, or when a cancelled screen reports a failure it never had.
---

# A result envelope for repository flows

The envelope types live in the domain module beside the repository interfaces that return them, so
both implementation and caller name them without depending on each other (`clean-arch-kmp-readiness`).

Three of them, because three different things happen at a repository boundary:

```kotlin
sealed class Resource<T>(val data: T? = null, val message: String? = null) {
    class Success<T>(data: T) : Resource<T>(data)
    class Error<T>(message: String, data: T? = null) : Resource<T>(data, message)
}

sealed class LocalResource<T>(val data: T? = null, val message: String? = null) {
    class Success<T>(data: T) : LocalResource<T>(data)
    class Error<T>(message: String, data: T? = null) : LocalResource<T>(data, message)
    class Loading<T> : LocalResource<T>()
}

sealed class NoResponseResource(val message: String? = null) {
    class Success : NoResponseResource()
    class Error(message: String) : NoResponseResource(message)
    class Loading : NoResponseResource()
}
```

`Error` carrying an optional payload is the useful part: a partial or cached result comes back
**with** the failure, so a screen can show stale content and a message rather than choosing.

## The wrap side

One helper per shape, each emitting a loading state, running the work on a background dispatcher and
turning either outcome into an envelope. The repository writes the operation and nothing else:

```kotlin
// adapted — fallback message strings shortened
fun <T> wrapDataResource(
    dispatcher: CoroutineDispatcher = Dispatchers.IO,
    block: suspend () -> T,
): Flow<LocalResource<T>> =
    flow {
        emit(LocalResource.Loading())
        runCatching { block() }
            .onSuccess { emit(LocalResource.Success(it)) }
            .onFailure { emit(LocalResource.Error<T>(it.message ?: "unknown")) }
    }.flowOn(dispatcher)

// at the call site
override fun getLocalPlaylist(id: Long): Flow<LocalResource<PlaylistEntity>> =
    wrapDataResource { localDataSource.getLocalPlaylist(id) }
```

Siblings worth having: one for a confirmation-message-only operation, one for an operation already
returning `Result<T>`. `flowOn` inside the helper is the point — no caller decides where work runs.

## The collect side

```kotlin
// adapted — fallback message strings shortened
suspend fun <T> Flow<LocalResource<T>>.collectLatestResource(
    onSuccess: (T?) -> Unit,
    onError: (String) -> Unit = {},
    onLoading: () -> Unit = {},
) = this.collectLatest { resource ->
    when (resource) {
        is LocalResource.Success -> onSuccess(resource.data)
        is LocalResource.Error -> onError(resource.message ?: "unknown")
        is LocalResource.Loading -> onLoading()
    }
}
```

Ship `collect` and `collectLatest` for **every** envelope — plain `collect` stacks work on a
re-entered screen, so callers need both. Easier said than done: here the loading-capable local
envelope and the payload-free one each got both helpers, while `Resource<T>` — the remote,
two-state one — got neither, which is exactly the gap the third trap below describes.

## Where mapping lives

Transport model becomes domain model **inside the repository implementation**, in `internal`
extension functions in the data module — `internal fun ServiceDto.toTrack(): Track`. Never in the
envelope, never in the view model. The envelope carries a domain type or it has achieved nothing:
if `Resource<ServiceSearchResponse>` exists anywhere, every screen imports the transport model.

## Traps

**The envelope must not swallow cancellation.** `runCatching` catches `Throwable`, and structured
concurrency signals cancellation as a throwable — so a screen closing mid-request takes the failure
branch and emits an error nobody is waiting for, surfacing as a message on the *next* screen or an
error state that outlives its cause. Re-throw it:

```kotlin
runCatching { block() }
    .onFailure { if (it is CancellationException) throw it }   // let cancellation propagate
    .onFailure { emit(LocalResource.Error<T>(it.message ?: "unknown")) }
```
Do this in every helper *and* in every hand-rolled repository method. Same lesson as
`guard-on-every-trigger-path`: a guard on one of two paths is a guard nobody can rely on.

**Helpers only pay off if the repository uses them.** Count both shapes before believing otherwise —
and reach the repository directory with `find`, not a `**` glob: unset `globstar` makes the second
command an error that counts as zero, which reads as "helpers dominate" and inverts the answer.
```bash
grep -rn "wrapDataResource\|wrapMessageResource\|wrapResultResource" --include="*.kt" data/src | wc -l
find data/src -path '*/repository/*' -name '*.kt' -exec grep -rn 'runCatching' {} + | wc -l
```
The second number dwarfing the first means the envelope is a convention on paper while the real one
is a hand-rolled `flow { runCatching { … } }` per method — each with its own dispatcher decision,
message default, and cancellation bug.

**An envelope with no collect helper gets a hand-written branch at every call site.** It is easy to
ship the loading-capable variant with helpers and leave the two-state one without, and then every
consumer of the remote flow writes `when (res) { is Resource.Success -> … }` by hand. Declare the
matching helpers in the same file as the envelope, or delete the odd one out.

**Success with a nullable payload pushes a null check into every consumer.** Storing `data` on the
sealed base as `T?` makes it nullable for all states, so `onSuccess` receives `T?` even though
`Success` was built with a non-null value, and every screen writes `val d = res.data ?: return`.
Declare the payload on the `Success` subclass as non-null and read it after the branch.

**Decide which envelope means what, and write it down.** A three-state variant used for local reads
and a two-state one for remote reads is *backwards* from most people's expectation: the slow path is
the one with no loading state. Whichever way round, make it visible at the interface — the caller's
UI depends on whether a loading state will ever arrive. And a suspend function returning a single
envelope value can never be `Loading`, so that state belongs to flow-returning operations only.

**An envelope is not an excuse to erase the failure.** `message: String?` flattens everything to
text, so a caller cannot tell "no network" from "not found" from "sign-in expired" and retry logic
becomes string matching. If any consumer must branch on the *kind* of failure, add a typed reason
alongside the message before that string comparison gets written.
