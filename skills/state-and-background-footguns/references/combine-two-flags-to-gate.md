---
name: combine-two-flags-to-gate
description: Turn several independent condition flows into one on/off gate with `combine` + `distinctUntilChanged` + `collectLatest`, make both the start and the teardown branch idempotent, and run teardown uncancellably. Use when a subsystem starts before it is fully configured, keeps running after one of its preconditions is withdrawn, or ends up half-started after a fast toggle.
---

# Combine independent conditions into one gate

An expensive subsystem — a network connection, a background sender, a polling loop — usually needs
more than one thing to be true: a user setting is on, *and* the credential it needs is present.
Watching those separately gives two collectors that each know half the answer, and the classic
failure is a subsystem started on the setting alone that then loops forever failing to authenticate.

One derived boolean fixes both directions at once:

```kotlin
// adapted — names generalized
combine(
    settings.featureEnabled,
    settings.credential,
) { enabled, credential ->
    enabled == TRUE && credential.isNotBlank()
}.distinctUntilChanged().collectLatest { shouldRun ->
    if (shouldRun) {
        // Both branches are independently idempotent: a toggle on→off→on race must not skip
        // (re)creating whichever of the two dropped out.
        if (connection == null) connection = Connection(settings.credential.first())
        if (senderJob?.isActive != true) senderJob = scope.launch { /* … */ }
    } else {
        withContext(NonCancellable) {
            senderJob?.cancel(); senderJob = null
            connection?.close(); connection = null
            retainedSnapshot.value = null
        }
    }
}
```

The same operator answers a much smaller question just as well — deriving one exposed value from two
state flows, with no side effects at all:

```kotlin
// adapted — names generalized
combine(handler.currentItemState, handler.controlState) { item, control -> item to control }
    .collect { (item, control) ->
        _currentId.value = if (control.isPlaying) item.entity?.id.orEmpty() else ""
    }
```

## Traps

**`combine` emits nothing until every source has emitted at least once.** A gate that never fires is
usually one input that is still empty — a flow with no initial value, a query that returns nothing,
a preference that has never been written. This is silent: no error, no log, the subsystem simply
never starts. Give each source a defined starting value (`StateFlow`, or `onStart { emit(default) }`)
rather than assuming a preference store always emits.

**Without `distinctUntilChanged`, the branch re-runs on every upstream tick.** Both inputs re-emit
for reasons unrelated to the gate — a preference store commonly re-emits the same value on any
write. The derived boolean flattens those to the same value, but the collector still runs, tearing
down and rebuilding a connection for no reason. Dedupe the derived value, not the sources.

**`collectLatest` cancels the previous action mid-flight, which is what makes teardown fragile.**
That cancellation is desirable for the start branch (a flip to off should abandon a connection
attempt) and dangerous for the teardown branch (a flip back to on will abandon the cleanup halfway,
leaving a closed connection with a live sender or the reverse). Teardown therefore runs inside
`withContext(NonCancellable)` — see `named-job-lifecycle-discipline` for the shape and for how to
avoid swallowing cancellation while doing it.

**Idempotence belongs on each sub-resource, not on the branch.** `if (!running) { start() }` around
the whole start branch is the version that breaks: a fast off→on can leave the connection alive but
the sender cancelled, and one branch-level flag reports "already running" and skips the rebuild. Each
resource gets its own check — `if (connection == null)`, `if (senderJob?.isActive != true)` — so any
subset that dropped out is restored.

**Clear retained values on teardown, or a relaunched consumer replays them.** A restarted sender
begins with fresh local bookkeeping (a sequence counter back at zero, an empty "last seen" set) and
will happily re-process whatever a state holder is still holding — pushing a stale update into a
freshly created connection. Anything monotonic must *not* be reset with it; here the retained
snapshot is cleared while the sequence counter deliberately keeps counting across toggles.

**Reading a source again inside the branch can disagree with the value that opened it.**
`settings.credential.first()` inside the start branch re-reads the store; between the gate
evaluating and the branch running, that value can change. Prefer the value `combine` already
produced — widen the transform to emit the data rather than only a boolean — when a mismatch would
matter.

**`collect` is fine when the body is a pure assignment.** The derived-value example above uses plain
`collect` because its body cannot be left half-done. Reach for `collectLatest` when the body starts,
awaits, or tears down anything; the cancellation semantics are only worth the hazard when there is
in-flight work to cancel.

**Do not gate on `player.isPlaying`-style live queries from another thread.** Where the branch needs
"is it still running", read the state flow's `.value` — a plain field read that is safe from any
thread — rather than re-querying an engine object with thread affinity.

## Verifying it

Toggle each input independently and watch the gate's own log line, one per emission past
`distinctUntilChanged`. Turning the setting on while the credential is absent must produce nothing.
Supplying the credential afterwards must produce exactly one `true`. Withdrawing either one must
produce exactly one `false`, and the subsystem's own activity must stop within that emission — not
"eventually".

Then toggle fast, several times in under a second, and inspect the resources individually rather
than the gate: connection non-null, sender job active, both or neither. The failure this pattern
exists to prevent is precisely the state where one is set and the other is not, and it is invisible
from the gate's log.
