---
name: named-job-lifecycle-discipline
description: "One `var xJob: Job?` field per concern, cancel-before-relaunch as an invariant at every launch site, and teardown writes wrapped so a cancellation cannot stop them halfway. Use when periodic updates arrive several times per tick, when stale results from a previous item overwrite the current one, or when a long-lived object keeps working after it was released."
---

# Named job lifecycle discipline

A long-lived object — a service handler, a screen model, a session controller — launches background
work from callbacks it does not control and that fire more often than anyone expects. Left
unmanaged, each firing leaks another live coroutine doing the same thing.

The shape that survives is one nullable `Job` field per *concern*, never one shared field for
several:

```kotlin
// adapted — a representative slice; the real list is longer
private var progressJob: Job? = null
private var bufferedJob: Job? = null
private var sleepTimerJob: Job? = null
private var loadJob: Job? = null
private var metadataJob: Job? = null
// …one per concern
```

Every launch site opens the same way, and the assignment is inseparable from the cancel:

```kotlin
// adapted — comment reworded for a generic player
override fun startProgressUpdate() {
    // Cancel any previous loop first: the "is playing" callback can fire repeatedly (a transition
    // swap, rebuffer→ready, resume after focus is regained) and a leaked loop would otherwise
    // multiply both the UI updates and the periodic position writes.
    progressJob?.cancel()
    progressJob = coroutineScope.launch { /* … */ }
}
```

Teardown then cancels and nulls every field, in one block, before the scope itself is cancelled.

## Traps

**Cancel-before-relaunch is an invariant, not a habit — check every launch site.** A concern with two
entry points needs the cancel on both. Enumerate the fields, then walk each one:

```
grep -rn "Job? = null" --include="*.kt" src/          # the field list
grep -rn "metadataJob" --include="*.kt" src/           # every use of one field
```

Read the second output as pairs. Every line that *assigns* the field must be immediately preceded by
a line that cancels it. An assignment without its cancel is the leak.

**A field that is cancelled but never assigned is dead code with no symptom.** One handle here is
declared once and cancelled once, at the top of a per-item collector, and that is the whole of it —
no line anywhere *assigns* it, so the cancel has always been a no-op. Its only other mention is a
**second** `cancel()`, commented out at the launch site, which at a glance reads like the missing
assignment and is not one. Nothing failed loudly, because a second guard downstream (re-checking the
item id before writing the result) was quietly doing the whole job. The grep above catches it: a
field whose uses are a declaration and a cancel, with no assignment, is not managing anything. See
`distinct-by-key-reset-cancel-per-item` for why the write-time identity check has to exist regardless.

**A `stopX()` helper cancels only the newest handle.** If the launch site does not cancel, the stop
site cannot make up for it — it holds a reference to the most recent job only, and every earlier one
keeps running. The symptom is *multiplied writes and no error at all*: the same state written 2×,
then 3×, then 5× per tick as more loops accumulate, which reads as flicker or as a flag that will
not settle rather than as a leak. See `stateflow-conflation-inverts-state` for what that does to a
conflating state holder.

**Pre-seeding the fields with a bare `Job()` is worse than leaving them null.** An initializer that
assigns `progressJob = Job()` to a dozen fields reads as harmless tidying — `?.cancel()` on `null`
was already a no-op, so it removes no branch. But `Job()` returns a `JobImpl`, constructed as
`JobSupport(active = true)`: it is **active from the moment it exists**, with nothing running behind
it. That is exactly what the sibling relaunch guard tests —
`if (xJob?.isActive != true) xJob = scope.launch { … }`, the idiom taught in
`combine-two-flags-to-gate` and live in this handler — so a pre-seeded field reads as live work and
the launch it guards is skipped for a job that will never do anything. The placeholders also drift:
two of the fields cancelled in teardown here never appear in that initializer at all.

**Teardown writes must not be cancellable.** When cleanup runs inside a `collectLatest` action, a
newer upstream emission cancels that action mid-flight and leaves the object half torn down — which
the next pass then sees as "already running". Wrap the cleanup so it completes:

```kotlin
// adapted — resource names generalized; comment and structure verbatim
// NonCancellable: this cleanup must run to completion even if a newer upstream emission cancels
// this collectLatest action mid-flight, otherwise the next pass could see a half-torn-down state.
withContext(NonCancellable) {
    senderJob?.cancel()
    senderJob = null
    connection?.close()
    connection = null
    retainedSnapshot.value = null   // so a relaunched sender cannot replay a stale value
}
```

Use the same wrapper for any multi-step sweep that is only coherent once finished. Do not use it to
swallow cancellation: catch `CancellationException` separately and rethrow it, or structured
concurrency breaks and a user whose work in fact completed gets an error message.

**`cancel()` returns immediately; it does not wait.** Where the next step depends on the previous
one having actually stopped — reusing a resource the job holds, or reading what it wrote — `join()`
the handle rather than assuming the cancel took effect.

**Cancel jobs before the scope, not after.** The teardown block here cancels each named job, nulls
each field, and only then cancels the scopes. Cancelling the scope first makes every subsequent
`job?.cancel()` a formality and hides which handles were actually still live.

## Verifying it

Counting is the test. Put one log line inside each periodic loop, then drive the callback that
launches it repeatedly — change items several times, pause and resume, force a stall. The line rate
must be identical after ten items and after one. Any climb means a launch site is missing its
cancel.

For the one-shot jobs, do the same with the previous item's slow path: start item A, switch to B
before A's work returns, and confirm A's result never reaches the state. If it does, check whether
the field is assigned at all — a cancel on an unassigned handle looks exactly like a cancel that
did not work.

Finally, release the object and confirm the loops stop. A log line that keeps arriving after
teardown means a job was launched into a scope other than the one being cancelled.
