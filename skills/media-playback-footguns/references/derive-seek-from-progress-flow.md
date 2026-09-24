---
name: derive-seek-from-progress-flow
description: Detect a scrub as a playhead that moved further than wall-clock time can account for, from the progress stream every platform already emits, because the platform's own discontinuity callback exists on one backend only and neither the item stream nor the transport stream fires when a scrubber is dragged. Use when a seek by one member of a shared session is never sent, or when a cross-platform layer needs an event only one platform provides.
---

# The only thing that changes when you scrub is the position

Drag a scrubber and check what the app can observe: the current item did not change, the
running/paused state did not change, no user-action callback fired anywhere above the component.
Exactly one thing moved — the position — and the progress stream that reports it is already running
because the UI needs it. So derive the event from that:

```kotlin
// adapted — names generalized; the send call and log elided
var lastProgress = 0L
var lastAt = 0L
progressFlow.collect { position ->
    val now = PROCESS_START.elapsedNow().inWholeMilliseconds   // monotonic
    val previous = lastProgress
    val previousAt = lastAt
    lastProgress = position                                    // baseline updated FIRST
    lastAt = now

    if (!amSource || applyingRemote) return@collect
    if (previousAt == 0L) return@collect                       // no baseline yet
    val elapsed = now - previousAt
    val expected = previous + if (component.isPlaying) elapsed else 0L
    if (abs(position - expected) < SEEK_DETECT_MS) return@collect
    publishSeek(position)
}
```

Ordinary playback advances roughly in step with the clock. Anything that does not is a jump.

## Traps

**Update the baseline before the early returns, not after.** This is the ordering the code above is
careful about and the one that reads as redundant. If the baseline is only refreshed on emissions
that pass the role check, it goes stale for the entire time this client is *not* the source — and
the first tick after taking the role compares against a position from minutes ago and publishes a
spurious jump to the whole session. The same applies to every guard: the baseline is bookkeeping
about the local component and has nothing to do with whether you are allowed to publish.

**Keep the baseline local to the collector, not on the class.** Two `var`s declared inside the
suspending function are scoped to exactly one run of one collector, which is what you want: restart
the collector and the baseline restarts with it, harmlessly skipping one sample. Hoisted to a field
they outlive the collector, get read by whatever else is added later, and reintroduce the stale
comparison from a different direction.

**Skip the first sample.** With no previous timestamp there is no expectation, and treating the
initial zero as one turns the first progress tick of every session into a seek. A sentinel on the
timestamp — not on the position, which can legitimately be zero — is the check.

**Do not advance the expectation while paused.** A pause of any length followed by a resume is not a
jump; expect the position to be unchanged over that interval. Multiplying by the running flag is the
whole fix and it is one term.

**A monotonic source, always.** A wall clock that a time correction can step forward or back
fabricates jumps out of nothing, at moments unrelated to anything the user did — the worst kind of
intermittent. Anchor one mark at process start and measure elapsed from it. The same requirement
appears for peer clock estimation; see `monotonic-clock-offset-sync`.

**The detect threshold and the apply tolerance are different numbers with opposite jobs.** Set the
detector at or below the tolerance that decides "is this worth seeking to", and every published seek
provokes a correction which is itself detected as a seek — a loop that ping-pongs the session. Keep
the detector comfortably the larger of the two, and comfortably above the progress tick interval so
ordinary jitter never trips it. `position-based-group-sync` holds the other half.

**An item change looks exactly like a huge backwards jump.** The position drops to zero while the
detector still holds the previous item's baseline, so the tick after a transition reads as a seek.
Two acceptable answers: reset the baseline when the item id changes, or accept the spurious event on
the grounds that it lands where the new item already is. Choose deliberately and write down which —
the accidental version of this is a mystery seek in the log after every transition.

**Publish the observed position, not the expectation.** The expectation is a computed number that
exists only to decide *whether* something happened; broadcasting it hands the rest of the session
the drift you just detected instead of the truth. Send the position the component actually reports.

**The detector must not run while remote state is being applied.** A correction seek you just
applied is, by every measure this detector uses, a jump — so without the same guard the publishers
carry, applying one immediately republishes it. `sync-room-bridge-echo-guard` covers the guard and
the ordering constraint it interacts with here: the guard check comes *after* the baseline update.

**A stall is indistinguishable from a backwards seek, and that is survivable.** If the component
stops advancing, the expectation runs ahead and the detector eventually publishes a jump back to
where the source actually is. That happens to be the right correction for the rest of the session,
so the degradation is benign — but know it is happening before you tune the threshold down.

**The progress stream's interval is not yours, so do not bake it into the threshold.** It exists to
drive a UI and its tick rate is set by whatever needs it — it can change, and it differs between
backends. Express the threshold as "comfortably larger than any plausible tick" and say so beside
the constant, rather than as a multiple of a number that lives in another module.

**Do not reach for the platform callback because one backend has it.** It exists on one and not the
other, so building on it means the feature works on one platform and is silently missing on the
rest. Derive from the stream both already emit, and the behaviour is identical everywhere by
construction.

## Verifying it

Dump the detector's shape, in line order, and check the ordering claim above:

```bash
for f in $(grep -rlE "(SEEK_DETECT|DETECT|JUMP)[A-Z_]* *= *[0-9_]" --include="*.kt" . \
             | grep -v "/build/"); do
  echo "== $f"
  grep -nE "markNow|elapsedNow|last[A-Z][a-z]+ *=|expected|return@collect|abs\(" "$f"
done
```

The baseline assignments must have **lower line numbers** than the role/guard `return@collect` lines
in the same block; after them is the stale-baseline bug. Then confirm the clock is monotonic:

```bash
grep -rnE "TimeSource\.Monotonic|markNow\(\)|nanoTime\(\)|elapsedRealtime" --include="*.kt" . \
  | grep -v "/build/"
grep -rnE "currentTimeMillis\(\)|Clock\.System\.now\(\)" --include="*.kt" . | grep -v "/build/"
```

The detector's timestamps must come from the first list; anything from the second inside a duration
calculation is the fabricated-jump bug. Finally, check the platform-only callback is not
load-bearing:

```bash
grep -rniE "onPositionDiscontinuity|DISCONTINUITY_REASON" --include="*.kt" . | grep -v "/build/"
```

Hits confined to one backend are fine; a shared layer calling into them is the feature that only
works on one platform.

Behaviourally, with two clients: scrub on the source and confirm the follower jumps once, not
repeatedly. Then let both play untouched for several minutes — the seek log must stay silent, and
any periodic entry is the threshold sitting under the jitter.
