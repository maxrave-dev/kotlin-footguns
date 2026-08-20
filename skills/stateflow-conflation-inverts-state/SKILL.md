---
name: stateflow-conflation-inverts-state
description: A conflating state holder keeps one slot, so a callback that writes it several times per event makes write ORDER the correctness question — collectors see only the last write. Use when a spinner sits over content that is already loaded, when a loading flag clears at the wrong moment, or when a screen shows the state that was true one step ago.
---

# Conflation makes write order a correctness question

`MutableStateFlow` holds exactly one value. Take the compiled class apart and there is a single
volatile state field and a sequence counter — no per-write buffer — and `collect` allocates a slot
and then re-reads that one field. So a collector on another thread observes whatever is in the slot
when it wakes, and every value written in between is simply gone.

That is fine for a state holder written once per event. It is a correctness bug the moment one
callback writes it more than once, because the *last* write becomes the published truth regardless
of which write was right:

```kotlin
// adapted — the shape that inverted the state
override fun onIsLoadingChanged(isLoading: Boolean) {
    _state.value = Loading(...)              // 1. unconditional
    if (bufferedAhead()) {
        _state.value = Ready(duration)       // 2. an escape hatch, on some paths
    }
    if (isLoading) startBufferedUpdate()
    else stopBufferedUpdate()                // 3. …which ALSO wrote Loading, and runs LAST
}
```

Called with `false` — buffering has just *finished* — the canceller's `Loading` is the last write, so
the sequence settles on `Loading`. The screen puts a spinner over audio that is already playing.
Called with `true` nothing writes after the escape hatch, so it can settle on `Ready`. The published
state is the inverse of the event, on both branches.

The fix is one write per event, decided at the end, and the value must match the argument:

```kotlin
// adapted — state holder renamed, branches unchanged
override fun onIsLoadingChanged(isLoading: Boolean) {
    if (isLoading) {
        startBufferedUpdate()
        // Already holding more than the playhead needs: the stall is nominal, so do not put a
        // spinner over playback that is about to continue.
        _state.value =
            if (player.bufferedPosition > player.currentPosition) Ready(player.duration)
            else Loading(player.bufferedPercentage, player.duration)
    } else {
        stopBufferedUpdate()
        _state.value = Ready(player.duration)
    }
}
```

## Traps

**A helper named `stopX` can still publish.** The write that *won* this race was inside the canceller,
not inside the callback — nothing about the call site suggested it emitted anything at all. Enumerate
the writers before trusting any one of them:

```
grep -rn "_state.value\|_state.update" --include="*.kt" src/
```

Read the output grouped by enclosing function. Any function reached twice in one event, or any pair
of writes with no suspension point between them, is a conflation hazard. Once a canceller stops
emitting, say so where someone will look for the missing write:

```kotlin
override fun stopBufferedUpdate() {
    bufferedJob?.cancel()
    // Deliberately emits nothing: this runs when buffering *ends*, so publishing Loading here
    // said the opposite of what happened.
}
```

**The periodic emitter is the compounding half.** A poller that re-publishes every few hundred
milliseconds must be cancelled before it is relaunched, or each event leaves another live loop
pushing the same value forever. After a handful of events the leaked loops outnumber and outvote the
writes that would clear the flag, so the one-write-per-event fix alone does not hold. Both the
progress loop and the buffered loop here open with `job?.cancel()` for exactly this reason — see
`named-job-lifecycle-discipline`.

**It reproduces on a device and not in a test.** Conflation is a *no guarantee* that intermediate
values are delivered, not a guarantee that they are dropped; whether a collector sees them depends
entirely on scheduling. A same-thread test collector often sees every write, so the ordering bug
passes its test and ships.

**Compare values in one unit before you publish a decision.** The guard above works because
`bufferedPosition` and `currentPosition` are both positions in milliseconds. A guard written against
a buffered *percentage* multiplied by a duration is comparing percent-milliseconds to milliseconds
and is wrong by two orders of magnitude — while still looking like a comparison of two progress
values.

**The consumer can invert it a second time.** A terminal branch that parks the position at a
sentinel negative, when the only formatter renders any negative as a placeholder, leaves that
placeholder on screen — nothing follows a terminal state to correct it, the progress branch ignores
negatives, and the loading branch restores the total without touching the position. Park at a real
value instead:

```kotlin
// adapted — trimmed to the two fields that matter here
Ended -> _timeline.update { it.copy(current = it.total.coerceAtLeast(0L), loading = false) }
```

**Both trigger paths need the same discipline.** Playback state here is published from the
load-changed callback *and* from the playback-state callback. A single-write rule applied to one of
them leaves the other free to overwrite it — the same failure shape as
`guard-on-every-trigger-path`.

## Verifying it

Do not read the state field back in the writer; it will always show your own last write. Log from a
collector instead, one line per emission, and drive the two transitions that matter: start a fresh
item (buffering begins, then ends) and force a mid-item stall. The published sequence must contain
no value that contradicts the event that produced it, and must not contain a repeat of the
pre-event value after the event.

Then play several items in a row and watch the emission *rate* on that same collector. If it climbs
with each item, a periodic emitter is leaking and the ordering fix is being outvoted rather than
being wrong.
