---
name: guard-on-every-trigger-path
description: Keep the start conditions of a feature that fires from two entry points — typically a polling loop and an end-of-item callback — identical on both paths, because a condition added to only one of them is dead code that produces no error, no log and no crash. Use when a newly added guard, exclusion or feature flag appears to have no effect at all, or when a feature behaves correctly most of the time and wrongly in one specific timing.
---

# Guard on every trigger path

Some features are started from two places on purpose:

- a **polling loop** that watches progress and fires when a threshold is crossed
  (`timeRemaining in 1..threshold`, checked every ~200 ms), and
- an **end-of-item callback** that fires when the item actually finishes.

The callback exists as the fallback for every case where polling did not fire: the loop was
not running, the item was too short for the window, the item ended early. It therefore opens
with an early return so the two cannot both start the feature:

```kotlin
private fun handleTrackEndInternal() {
    if (isCrossfading) return          // the poll path already started it
    val shouldStart = enabled && hasNext() && !isVideo() && !isTooShort() && !isInAlbum()
    ...
}
```

That early return is what makes this shape dangerous — and it wears two costumes: the
literal `if (started) return` above, or the same flag folded into one long conjunction
(`!alreadyStarted && enabled && …`). Either way, in the common case the poll path wins
the race, so the callback body is reached only in the minority timing — and a condition
added there alone runs almost never. There is no crash, no warning and no log line: the feature
simply carries on as though the new condition had never been written.

## Traps

**Adding a condition to the callback only.** It reads like the natural home — that function is
where the decision "fade or advance normally?" is spelled out. But by the time it runs in the
common case the feature has already started and the function returned three lines earlier.
Symptom: a shipped exclusion that testers cannot reproduce, and that works only when a track
ends unusually (skip pressed, very short item, playback paused near the end).

**Adding a condition to the polling loop only.** The mirror failure, and the one that *does*
have a symptom — just a rare one. The feature is suppressed almost always, and then fires
anyway on exactly the timing you were trying to exclude.

**Copying the condition list by hand into both places.** This is what the code above actually
does, and it is the reason the trap keeps recurring: two boolean chains that must stay
identical, hundreds of lines apart, edited by different changes. Extract one predicate
instead and call it from both:

```kotlin
private fun shouldStartTransition(): Boolean =
    enabled && hasNext() && !isCurrentVideo() && !isNextVideo() &&
        !isCurrentTooShort() && !isWithinAlbum()
```

If the two paths genuinely differ (the poll path also needs `player.isPlaying`, a positive
duration and the threshold arithmetic), keep the *shared* half in the predicate and let each
path add its own. The rule is that no exclusion ever lives in only one of them.

**Assuming the early return covers you.** `if (alreadyRunning) return` guarantees the feature
is not started twice. It guarantees nothing about the conditions under which it is started at
all — those are evaluated after it, on a path most timings never reach.

**Logging the block reason on the poll path without throttling.** The loop reaches the trigger
site five times a second for as long as the item stays inside the window, so an unconditional
"blocked because X" line buries every other message. Log it once per item:

```kotlin
if (lastBlockedIndex != nextIndex) {
    lastBlockedIndex = nextIndex
    Logger.d(TAG, "transition blocked at $nextIndex: ...")
}
```

**Believing this is specific to crossfade.** The same shape — a timer/poll path plus an event
path, one of them guarded by "already started" — shows up in prefetching the next item,
autosave, analytics flush, wake-lock or foreground-service release, and "load more" in a list
(scroll listener plus an end-of-data callback). Whenever you find `if (alreadyX) return` at
the top of one of two starters, treat every condition below it as suspect.

## Verifying it

You cannot verify this by testing the feature, because the common timing hides the bug.
Verify it structurally:

1. Find every call site of the function that *starts* the feature
   (`grep -n "triggerCrossfadeTransition(" …`). Two or more call sites is the shape.
2. Read the condition list guarding each call site and diff them by eye. They should be one
   shared predicate, or differ only in path-specific mechanics (`isPlaying`, thresholds).
3. Add a log line naming which path started it, then exercise both: let an item run to its
   natural end (poll path) and skip into the last seconds of a very short item (callback path).
   A run where one path never appears in the log means you have not tested it, not that it
   cannot happen.
4. When you add an exclusion, force it true in a debug build and confirm the feature stops on
   **both** paths before believing it works.
