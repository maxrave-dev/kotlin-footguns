---
name: intent-flag-not-observed-state
description: A component that is committed to running but not yet running reports "not running", so anything that means intent must read the intent flag, not the observed one — and at a transition the intent flag must be waited for with a timeout rather than sampled inline. Use when one client's buffering hiccup stops a whole synchronised group, when appending to a queue in the background silences the track that was about to start, when a resume command is issued on every tick, or when a state read is wrong on exactly the transitions it exists for.
---

# Two flags, and only one of them is a decision

Most playing/running components expose both, and they are not two names for one thing:

- **observed** (`isPlaying`, `isActive`, `isRunning`) — output is actually happening *right now*.
- **intent** (`playWhenReady`, `shouldRun`, `startRequested`) — someone asked for it to happen.

Between the two sits a third state nobody names: **committed, not yet producing**. Buffering,
resolving a stream, opening a device. Observed is `false` there, and it is `false` for a user pause
too — so a comparison against observed cannot tell "the network stuttered" from "the user pressed
pause". In a shared session that difference is the whole feature: publish the first as if it were
the second and one member's hiccup stops everybody.

```kotlin
// adapted — names generalized; the collector's role checks and the send call elided
.map { it.isPlaying }             // collect the observed one: it is the one with a flow
.distinctUntilChanged()
.collect { observed ->
    val intent = component.playWhenReady   // publish the intent one
    if (observed != intent) return@collect // a dip where they disagree is not news
    publish(if (intent) PLAY else PAUSE)
}
```

Note the shape: you *collect* observed because it is what changes, and you *act on* intent, dropping
the emission entirely whenever the two disagree. Applying works the same way in reverse — compare
the incoming command against the local intent, not against local output, or a still-buffering item
gets a fresh play command on every tick and a stale pause can land on an item that was about to
start.

## Traps

**Do not sample the intent flag inline at a transition — wait for it.** This is the same read, and
it is wrong at exactly the moments it exists for. The intent flag is false while the next item
buffers, and false again for the instant the component is rebuilt for an item picked out of a list.
Both are transitions, and both are when something needs publishing:

```kotlin
// adapted — names generalized
val started = withTimeoutOrNull(SETTLE_TIMEOUT_MS) {
    while (!component.playWhenReady && !component.isPlaying) delay(SETTLE_POLL_MS)
} != null
if (started) publish(PLAY)
```

**The timeout is the negative answer, not an error path.** A source that is genuinely paused simply
never satisfies the wait, the publish never fires, and the group stays paused — which is correct.
Treating the timeout as a failure to log or retry inverts that.

**Wait for *either* flag, not for the intent alone.** Which one flips first depends on the path: on
one the intent commits before any output exists, on another output starts before the intent field is
written. Requiring both is a wait that sometimes never ends.

**Do not wait for the observed flag alone.** Output waits on stream resolution, which is unbounded —
longer than any timeout you would be willing to hold a transition for. Waiting for audio here is
what leaves followers paused after the source picks a new item.

**Poll it; there is usually no flow behind a plain property.** Which makes the timeout mandatory
rather than optional: a bare `while` around a property read is a coroutine parked for the life of
the process, and it pairs with whatever gave up on the other side. `retry-needs-backoff-and-cap`
states the pairing rule — a bounded retry policy and an unbounded waiter is a hang.

**Dedupe the observed stream before you act on it.** Components re-emit the same running value
freely — on every buffer, on every internal state change — and without a `distinctUntilChanged` the
publisher fires on ticks where nothing changed, which is traffic the whole session pays for. Map to
the single boolean first, dedupe, then read the intent inside the collector.

**Keep the poll step and the timeout as named constants next to each other.** They are one decision:
a 50 ms step under a 2 s ceiling is forty chances to observe a flag that flips once. Tuning either
without seeing the other is how a settle wait becomes either a busy loop or a stall.

**The apply side needs the same rule, and it is easier to get wrong.** `if (remoteWantsPlay &&
!component.isPlaying) play()` re-issues play on every tick of a buffering item, because the item
stays observed-false the whole time. Compare against the local *intent* and the command fires once.

**The same misread happens locally, with no synced group in sight.** A guard meant to keep an
already-paused player paused has to read the intent flag too, not just the apply-side command above:

```kotlin
// wrong: also fires while the next item is still preparing
if (!player.isPlaying && isAddToQueue) player.playWhenReady = false
```

`isPlaying` is false both while genuinely paused and while the next track is still buffering, so
appending to the queue in the background during that ordinary buffering window reads as "paused" and
writes `playWhenReady = false` onto a player that was committed to playing — the incoming track then
loads silent. `if (!player.playWhenReady && isAddToQueue)` is both correct and idempotent:
already-false stays false, and a player mid-buffer with real intent is left alone.

**The intent flag is a property, not a stream, and that shapes every use of it.** Nothing tells you
when it changes, so there are only two legitimate reads: a sample taken at a moment you know is
settled, and a bounded wait. Anything else — a periodic poll that publishes, a read in a hot path —
is inventing an event source the component does not offer.

**The wait stalls the collector it sits in.** It is inside a `collect` block, so for as long as it
runs, later emissions from that same stream queue up behind it. That makes the timeout a bound on
*the whole publish path*, not just on this transition: set it generously and a burst of item changes
arrives at the other members long after the fact. Keep it in the low seconds, and keep the wait as
the last thing the collector does.

**"Both flags mean the same thing here" is a claim with a shelf life.** Some components genuinely
keep them in step at the moment you check. They stop doing so the first time a slow network, a
device change or a rebuild appears — none of which are in the tests. Read the intent because it is
the question you are asking, not because you measured a divergence.

## Verifying it

Find every settle wait and every unbounded poll in one pass — the paired `while`/`delay` census:

```bash
grep -rn -A3 --include="*.kt" -E "while *\(" . | grep -v "/build/" \
  | awk '/while *\(/{w=$0} /delay\(/{if(w!=""){print w; w=""}}'
```

Read the enclosing call of each: a poll on a component property with no `withTimeout*` around it is
the hang, and a `while (someDuration <= 0)` shape is the same bug wearing a different condition.
Then check that the waits which *do* exist accept either flag:

```bash
grep -rn -B2 -A6 "withTimeoutOrNull" --include="*.kt" . | grep -v "/build/" \
  | grep -E "playWhenReady|isPlaying|isActive|shouldRun"
```

Finally, census the two vocabularies and read each observed-state hit for whether it is answering an
intent question:

```bash
grep -rnE "\.(isPlaying|isActive|isRunning)\b" --include="*.kt" . | grep -v "/build/"
grep -rnE "playWhenReady|shouldPlay|startRequested|playbackIntent" --include="*.kt" . | grep -v "/build/"
```

Behaviourally, the two flags only diverge under conditions you have to create: throttle the network
on the source and confirm the group does *not* pause; then pause on the source and confirm it does.
A build that fails the first and passes the second is reading observed state.
