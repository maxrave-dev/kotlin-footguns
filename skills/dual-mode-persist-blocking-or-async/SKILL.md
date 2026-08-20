---
name: dual-mode-persist-blocking-or-async
description: One suspend persistence body driven two ways — blocking on the shutdown path, where the write must complete before the scope dies, and fire-and-forget on periodic ticks — instead of two copies that drift apart. Use when saved state is correct while the app runs but wrong after a hard quit, when a teardown save silently does nothing, or when two save functions have grown different guards.
---

# One save body, two execution modes

Persistence has two callers with opposite requirements. The periodic one runs while everything is
alive and must not block anything. The teardown one runs while the object is being released — the
scope it would launch into is about to be cancelled, so a fire-and-forget write is simply lost.

Write the body once and let the caller choose how it runs:

```kotlin
// interface
fun mayBeSaveState(runBlocking: Boolean = false)

// implementation — adapted
override fun mayBeSaveState(runBlocking: Boolean) {
    val unit = suspend {
        if (settings.saveStateEnabled.first() == TRUE) {
            val itemId = currentItemState.value.entity?.id
            // Skip while the item is unknown or the collection is mid-rebuild: the rebuild clears
            // the list and re-inserts the current item only at the end, so saving in that window
            // persists a collection missing it, which desyncs the next restore.
            if (itemId != null && collection.value.state == StateSource.STATE_INITIALIZED) {
                settings.saveState(itemId, player.contentPosition)
                repository.persist(ArrayList(collection.value.data.items))
            }
        }
    }
    if (runBlocking) runBlocking { unit() } else scope.launch { unit() }
}
```

The one blocking caller is the release path, and it saves before it dismantles anything:

```kotlin
// adapted — teardown steps trimmed, order verbatim
override fun release() {
    mayBeSaveState(true)          // must complete: the scopes are cancelled a few lines down
    mayBeSavePlaybackState()
    player.removeListener(this)
    // …
    coroutineScope.cancel()
    backgroundScope.cancel()
}
```

## Traps

**Fire-and-forget at teardown loses the write, and loses it silently.** The launch succeeds, the
coroutine is scheduled, the next lines cancel the scope, and it never runs — with no exception and
nothing in the log. This is the entire reason the flag exists, and it is invisible in any test that
does not actually tear the object down. Blocking here is a deliberate trade: it is acceptable only
because the body is bounded (a preference write and one list write), and it stops being acceptable
the moment someone adds a network call to the shared body.

**The default parameter hides how few callers may pass `true`.** `runBlocking: Boolean = false`
means every existing call site keeps the async behavior, which is what makes the flag safe to add —
and also what makes an accidental `true` easy to miss in review. Enumerate them:

```
grep -rn "mayBeSaveState(true)\|mayBeSaveState(runBlocking = true)" --include="*.kt" src/
```

Each hit must be a real teardown path. A blocking save on a track change or a pause is a stall on
whatever thread the callback arrives on.

**A parameter named after the coroutine builder shadows it.** `if (runBlocking) { runBlocking { … } }`
resolves only because a `Boolean` is not invokable, so the compiler falls through to the function.
It compiles, and it is one refactor away from not compiling — and it reads as a recursive call.
Name the parameter for the intent (`awaitCompletion`, `synchronous`) rather than the mechanism.

**Splitting the body is exactly the drift this pattern prevents — including here.** The light
periodic tick is a *separate* function, and it is missing the rebuild-state guard that the shared
body has:

```kotlin
// adapted — names generalized; the missing guard is real, not an omission here
private fun mayBeSavePosition() {
    scope.launch {
        if (settings.saveStateEnabled.first() == TRUE) {
            val itemId = currentItemState.value.entity?.id ?: return@launch
            settings.saveState(itemId, player.contentPosition)   // no collection-state check
        }
    }
}
```

That is defensible only because it writes the position and nothing else — it never touches the
collection, so a mid-rebuild write cannot corrupt one. The moment it grows a second field, it needs
the guard, and nothing will remind it. Two functions with the same purpose and different guards is
the failure mode; if the light path ever needs the heavy path's conditions, merge them rather than
copying the check. See `queue-rebuild-state-machine` for what that guard protects and
`playback-position-persist-restore` for the read side.

**Read the guard's state, not a snapshot of it.** The body evaluates the enabled flag and the
collection state at execution time, not when the function was called. On the blocking path those are
the same instant; on the async path they are not, and that is the correct behavior — a save queued
just before the user disabled the setting should not write.

**Order matters at teardown.** The save reads the player position and the collection contents, so it
must run before the listener is removed and the resources are released. Moving it below "for
symmetry" produces a save of already-torn-down state, which is worse than no save.

**`runBlocking` on the main thread is still `runBlocking`.** If teardown can be reached from the
main thread — a window closing, a lifecycle callback — the block is a visible freeze proportional to
the write. Keep the body small enough that it is not, and never let it wait on a network.

## Verifying it

Kill the process while state is changing, without a clean exit, and restart. The restored state must
match the moment of the kill, not the last periodic tick. Then do it again with a *clean* exit and
confirm the two paths agree — a discrepancy means the teardown save is running but reading
already-released state.

Then instrument the shared body with one log line at entry and one at completion, and trigger a
clean shutdown. Both lines must appear before the line that cancels the scopes. Seeing only the
entry line is the fire-and-forget failure; seeing neither means the guard rejected the write, which
is a different bug and worth logging distinctly.
