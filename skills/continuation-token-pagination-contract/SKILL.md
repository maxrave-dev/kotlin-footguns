---
name: continuation-token-pagination-contract
description: Model an endpoint that returns a page plus a next-token as Flow<Resource<Pair<items, token?>>> — a null token means the end, the caller stores only the token, and a bounded prefetch primes the first pages before anything is shown. Use when wiring an opaque-cursor API into a repository, or when a list stops loading after one failed request and never recovers, or when paging fires twice for one trigger.
---

# Page plus next-token, as one repository contract

The API answers with items and an opaque token for the next page. Everything downstream follows
from stating that once, in the return type:

```kotlin
// adapted: parameter names generalized; signatures otherwise as written
fun getRelatedData(id: String): Flow<Resource<Pair<List<Track>, String?>>>
fun getRadioFromEndpoint(endpoint: Endpoint): Flow<Resource<Pair<List<Track>, String?>>>
```

- `Pair(items, token)` — the page and the way to ask for the next one.
- **`null` token means end of pages.** Nothing else may mean that.
- The envelope (`Resource`, see `repository-resource-flow-pattern`) carries failure, so a failure is
  never expressed as an empty page or a null token.

The consumer stores exactly one thing — the token — and never a page number:

```kotlin
// adapted: names generalized; structure as written
override fun loadMore() {
    if (queueData.value.queueState == StateSource.STATE_INITIALIZING) return   // re-entrancy guard
    val token = queueData.value.data.continuation ?: return
    scope.launch {
        _queueData.update { it.copy(queueState = StateSource.STATE_INITIALIZING) }
        songRepository.getContinueTrack(playlistId, token).lastOrNull().let { response ->
            val list = response?.first
            if (list != null) {
                loadMoreCatalog(list)                                          // restores the flag
                _queueData.update { it.copy(data = it.data.copy(continuation = response.second)) }
            } else {
                _queueData.update { it.copy(data = it.data.copy(continuation = null)) }
                // …end-of-pages handling, which must also restore the flag
            }
        }
    }
}
```

The in-flight flag that makes `loadMore()` safe to call from a scroll listener *and* from an
end-of-queue event belongs to `queue-rebuild-state-machine`; what matters here is that the paging
path is one of its users and has to honour it on every exit.

## Traps

**A paged read that cannot report failure makes a network hiccup indistinguishable from the end of
the list.** One read in this interface returns a bare `Flow<Pair<List<T>?, String?>>` instead of the
envelope, and its implementation has nowhere to put an error, so it does the only thing left:

```kotlin
.onFailure { emit(Pair(null, null)) }
```

The consumer above reads `list == null`, writes `continuation = null`, and stops paging — for good,
because the token it needed to retry has just been erased. One dropped request permanently truncates
the list and there is nothing in the state to distinguish it from a list that genuinely ended. Put
every paged read behind the same envelope — **and then read the next trap, because the envelope
alone does not fix this.** It buys you a distinguishable failure; it does not stop you throwing that
distinction away. The enveloped consumer in this same codebase pattern-matches a clean
`is Resource.Error` and clears the token in that branch anyway, arriving at the identical permanent
end by a longer route.

**Clear the token when you stop, and only when you stop.** An exhausted token left in state is
retried on every subsequent trigger, which is a request per scroll that can only ever answer "no".
The error path has to make the opposite choice: it should keep the token, because that page is still
retryable — clearing it there is what turns a transient failure into a permanent end. The envelope
makes the failure *visible*; only the failure **branch** can keep the list recoverable, and the two
are separate edits. Auditing one without the other is why this bug survives the migration that was
supposed to remove it.

**The failure path of a prefetch loop must advance the loop.** The bounded prefetch that primes the
first pages reassigns the token *inside* `onSuccess` only. It does not live behind the two
signatures above — it is a **sibling repository's** paged read, the one that builds a radio queue —
so do not go looking for it under those methods; the point is that the same contract is served from
more than one place and only one of them prefetches:

```kotlin
// adapted — names generalized; literals kept, they are the mechanism
var count = 0
while (continuation != null && count < 3) {
    remote.next(endpoint, continuation = continuation)
        .onSuccess { page ->
            data.addAll(page.items)
            continuation = page.continuation
            if (data.size >= 50) count = 3     // enough to start; stop early
            count++
        }
        .onFailure { count = 3 }               // without this, the same page forever
}
```

On failure the token still holds its old value and the condition is unchanged, so omitting the
counter jump is not a retry — it is an unbounded loop re-requesting one page. Whatever the failure
policy, the loop variable has to move.

**Prefetch needs two stop conditions because pages are of unknown size.** A budget of three pages
might yield six items or six hundred; a target of fifty items might never arrive if the source
returns short pages. The page budget bounds the work, the accumulated-item target expresses the
actual goal ("enough to start"), and either one alone is the wrong guarantee.

**Terminal operators are part of the contract, and they disagree.** Call sites here use
`.lastOrNull()`, `.single()` and `.collect { }` against paged reads in the same file. They behave
differently the moment a read emits more than once — `single()` throws, `lastOrNull()` silently
drops the earlier emission — so a repository that later adds a cached first emission (see
`cache-then-network`) breaks some callers loudly and others invisibly. Decide whether a paged read
emits once, write it down in the interface, and keep the operators consistent with it.

**A two-branch `when` over the envelope has to do two jobs on the error branch.** Clear or keep the
token *and* release the in-flight flag. Releasing only on success is the classic version of this
bug: the first failure leaves the flag set, and the guard at the top of `loadMore()` then rejects
every future call — the list stops loading and no error is ever shown, because the code that would
have shown one never runs again.

## Verifying it

Force a failure — a happy-path run proves none of this.

- Make the second page fail. The list must keep the first page, keep its token, and **still page**
  when triggered again. If it never loads again, the flag was not released; if it reports the end of
  the list, failure and end are sharing a representation.
- Log the token on every request and assert it changes. A loop re-requesting one page looks like
  healthy traffic in a network inspector and identical in the UI to a slow feed.
- Assert the final token is `null` after the real last page, then trigger once more and assert **no
  request is made**.
