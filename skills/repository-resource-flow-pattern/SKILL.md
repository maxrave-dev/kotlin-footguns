---
name: repository-resource-flow-pattern
description: An envelope family for repository results — a remote wrapper, a local wrapper with a loading state, and a payload-free variant — plus the wrap-side and collect-side helpers that stop every view model from hand-writing the same branch, where the mapping from transport model to domain model belongs, and the one thing the envelope must never swallow. Use when designing repository return types, when error handling has drifted apart between screens, or when a cancelled screen reports a failure it never had.
---

# A result envelope for repository flows

The envelope types live in the domain module beside the repository interfaces that return them, so both implementation and caller
name them without depending on each other (`clean-arch-kmp-readiness`). Three of them, because three different things happen at a repository boundary:

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

One helper per shape, each emitting a loading state, running the work on a background dispatcher and turning either outcome into an envelope. The repository writes the operation and nothing else:

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
```

Siblings worth having: one for a confirmation-message-only operation (`wrapMessageResource`) and one for an operation already returning `Result<T>` (`wrapResultResource`) — `flowOn` inside the helper is the point, so no caller decides where work runs.

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
branch and emits an error nobody is waiting for, surfacing later as a stale message. Re-throw it:

```kotlin
runCatching { block() }
    .onFailure { if (it is CancellationException) throw it }   // let cancellation propagate
    .onFailure { emit(LocalResource.Error<T>(it.message ?: "unknown")) }
```
Do this in every helper *and* in every hand-rolled repository method. Same lesson as `guard-on-every-trigger-path`: a guard on one of two paths is a guard nobody can rely on.

**Helpers only pay off if the repository uses them.** Count both shapes before believing otherwise —
and reach the repository directory with `find`, not a `**` glob: unset `globstar` makes the second
command an error that counts as zero, which reads as "helpers dominate" and inverts the answer.
```bash
grep -rn "wrapDataResource\|wrapMessageResource\|wrapResultResource" --include="*.kt" data/src | wc -l
find data/src -path '*/repository/*' -name '*.kt' -exec grep -rn 'runCatching' {} + | wc -l
```
The second number dwarfing the first means the envelope is a convention on paper — the real pattern
is a hand-rolled `flow { runCatching { … } }` per method, bugs and all.

**An envelope with no collect helper gets a hand-written branch at every call site.** It is easy to
ship the loading-capable variant with helpers and leave the two-state one without, and then every
consumer of the remote flow writes `when (res) { is Resource.Success -> … }` by hand. Declare the
matching helpers in the same file as the envelope, or delete the odd one out.

**Success with a nullable payload pushes a null check into every consumer.** Storing `data` on the
sealed base as `T?` makes it nullable for all states, so `onSuccess` receives `T?` even though
`Success` was built with a non-null value, and every screen writes `val d = res.data ?: return`.
Declare the payload on the `Success` subclass as non-null and read it after the branch.

**Decide which envelope means what, and write it down.** A three-state variant for local reads and
a two-state one for remote reads is *backwards* from most people's expectation — the slow path is
the one with no loading state, so make that visible at the interface. A suspend function returning
one envelope value can never be `Loading`; that state belongs only to flow-returning operations.

**An envelope is not an excuse to erase the failure.** `message: String?` flattens everything to
text, so a caller cannot tell "no network" from "not found" from "sign-in expired" and retry logic
becomes string matching. If any consumer must branch on the *kind* of failure, add a typed reason
alongside the message before that string comparison gets written.

## Verifying it

1. **The gap above is real, and the first trap's fix is not yet applied:**
   ```bash
   ENVELOPE=core/domain/src/commonMain/kotlin/com/maxrave/domain/utils/Resource.kt   # your equivalent
   grep -n "Flow<Resource<T>>\|Flow<LocalResource\|Flow<NoResponseResource>" "$ENVELOPE"
   grep -c "CancellationException" "$ENVELOPE"
   ```
   Pass condition: first grep's hits never name bare `Resource<T>` — true here; second is 0 here, so the cancellation fix is a real, open gap in this codebase, not something already shipped.

2. **No repository interface names a transport type inside the envelope — checked by inverting the whitelist instead of naming any one integration:**
   ```bash
   DOMAIN_REPO=core/domain/src/commonMain/kotlin/com/maxrave/domain/repository   # your equivalent
   grep -rh "^import " "$DOMAIN_REPO"/*.kt | grep -v "^import com.maxrave.domain\|^import kotlin" | sort -u
   ```
   Pass condition: nothing printed belongs to an integration module — here it prints one line, `import androidx.paging.PagingData`.
