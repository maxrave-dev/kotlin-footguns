---
name: position-based-group-sync
description: Keep a group of clients together by publishing the playhead with every command, correcting it for the time the command spent in flight, and seeking only when the local gap exceeds a tolerance — rather than by making everyone wait for the slowest member. Use when a synchronised session drifts audibly apart, when followers stutter continuously as they chase the source, or when each device resolves its own stream and therefore takes a different amount of time to be ready.
---

# Absorb the loading gap with position, not with waiting

Each client in a shared session resolves its own stream, so "start now" arrives at devices that will
be ready at different moments. There are two ways to keep them together and only one of them scales:
hold everybody until the slowest is ready, or let everybody start when they can and land at the
*right position*. The second is what makes the session feel live.

That costs three things, all of which have to be present together:

```kotlin
// adapted — names generalized; the role checks and logging elided
private suspend fun applyTransport(running: Boolean, position: Long) = withContext(uiContext) {
    // 1. the command carried a position, and 2. it is advanced by however long it spent in flight
    val corrected = clock.positionAt(position, running)
    // 3. a small drift is normal; seeking on every tick stutters. Only a real gap earns a seek.
    if (abs(component.currentPosition - corrected) > SEEK_TOLERANCE_MS) component.seekTo(corrected)
    …
}
```

Missing (1) and the follower has nothing to correct against. Missing (2) and every correction lands
one round trip late, so the group converges on being consistently behind. Missing (3) and the
follower seeks on every tick, which is audible as a permanent stutter and is usually mistaken for a
decoding problem.

## Traps

**Publish the position with *every* command, not only with seeks.** A play, a pause and an item
change all carry it, because the follower's correction is only as good as the last position it was
told. This is the single cheapest thing in the design and the one most often trimmed as redundant.

**Advance the position only while running.** Correcting a paused position by flight time walks a
paused session forward, so every member resumes at a different place — further ahead the longer the
pause lasted. The running flag has to be a parameter of the correction, not an assumption.

**Fall back to the raw position whenever the clock is not calibrated.** Before the first round trip
lands there is no offset, and a guessed one produces a wrong seek. A slightly late position is
recoverable; a seek to the wrong place is heard by everyone. See `monotonic-clock-offset-sync` for
how the offset is estimated and why its source must be monotonic.

**A non-positive position means "from the top", and must never reach the correction.** Item-change
commands routinely carry zero. Run it through flight-time correction and it becomes *however long
ago the last command was*, which on an idle session can seek past the end.
`play-intent-decided-before-load` covers the three position cases at load time.

**The apply tolerance and the seek-detect threshold are two numbers with opposite jobs.** One says
"below this, do not seek"; the other says "above this, a jump was a deliberate seek worth
publishing". Set the detect threshold at or below the apply tolerance and each published seek
provokes a correction that looks like another seek — a loop that ping-pongs the whole session. Keep
them named separately and keep the detect one comfortably the larger.
`derive-seek-from-progress-flow` is the other half.

**The tolerance is measured, not derived.** It trades stutter against audible separation and the
right value depends on the medium and on how the component handles a short seek. Record where yours
came from; the command below finds it, and a tolerance with no comment is one nobody can safely
change.

**A position with no "as of when" cannot be corrected.** The flight-time correction needs the
timestamp the command was effective at, which means the transport has to carry it and the client has
to keep the most recent one alongside the position. If that timestamp is missing, absent or zero,
the correction has to fall through to the raw position — which is the honest answer, and much better
than treating "unknown" as "now".

**Compare against the local position at the moment of applying.** Not against the position last
seen, not against a cached one — the whole point is the gap *now*, after however long the command
took to arrive and the item took to load.

**Position rides on commands, not on a timer.** A periodic position broadcast is the design everyone
reaches for first, and it multiplies traffic by the tick rate while adding nothing: between commands
each client's own playback advances at the same rate as everyone else's, so there is nothing to
correct. Publish on the events you already publish, and the bandwidth is proportional to what the
session actually does.

**Not every seek in the apply path is a correction.** Restoring the playhead after rebuilding the
same item is a deliberate, unconditional seek and must not be tolerance-gated. Keep the two visibly
different, or someone tidies the guard onto both and the queue-arrived-late rebuild starts jumping.

**Waiting has one legitimate use, and it is not per command.** A barrier that holds the group until
every member reports ready belongs on mid-item stalls, not on every transition — see
`readiness-barrier-needs-every-answer`, including why a member that never answers freezes everyone.

## Verifying it

Read the tolerance your tree actually uses, and confirm it is named rather than inline:

```bash
grep -rnE "(TOLERANCE|THRESHOLD|DRIFT|SLOP)[A-Z_]* *= *[0-9_]+" --include="*.kt" . | grep -v "/build/"
```

Then census every seek inside a file that does clock correction, and classify each one:

```bash
for f in $(grep -rlE "positionAt|correctedPosition|serverPosition|clockOffset" --include="*.kt" . \
             | grep -v "/build/"); do
  echo "== $f"
  grep -n -B4 "seekTo(" "$f" | grep -E "abs\(|TOLERANCE|THRESHOLD|seekTo\("
done
```

Each seek must be either preceded by an `abs(...) > TOLERANCE` line — a correction — or be an
unconditional restore you can name in one sentence. A correction with no guard above it is the
permanent stutter. Most of the listed files will print no seek at all, and that is correct —
transport and clock files carry the position, they do not act on it. The file that *applies*
incoming commands is the one obliged to print seeks; none there means it is publishing positions
nobody applies.

Behaviourally, with two clients and a stopwatch:

- Start both, let them run for several minutes, and compare. Silence from the correction path is the
  goal; a log line on every tick means the tolerance is too small or absent.
- Throttle one client's network so it loads slowly, then release it. It must *land ahead* — at the
  position the session reached while it was loading — not resume where it stalled.
- Pause the whole session for a minute, then resume. Both must resume at the same place. Resuming
  further apart the longer the pause lasted is the correction advancing a paused position.
