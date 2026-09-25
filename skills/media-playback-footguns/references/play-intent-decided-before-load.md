---
name: play-intent-decided-before-load
description: Decide whether the freshly-loaded item should start, and where it should start, before you build it — then pass both into the load call, rather than loading with a hardcoded "start playing" and correcting it a moment later. Reach for it when a follower in a synchronised room bursts into sound in a session everyone else has paused, or when a newly loaded item audibly starts and then stops.
---

# The correction runs after the load; the audio does not wait for it

An apply path that reacts to a remote command usually does two things in a row: load the item the
room is on, then bring the transport into line. Written naively that is:

```kotlin
// the shape to avoid
load(item, startPlaying = true)     // "we'll fix it below if the room is paused"
applyTransport(isPlaying, position)
```

There is no ordering guarantee between "the load call returned" and "the output opened". The load
path commits to playing the moment it has enough of the stream, which can be before, during or
after the correction — so the follower plays a burst of audio into a paused room, and which side
wins depends on the network. Pass the decision *in* instead:

```kotlin
// adapted — names generalized; the position cases are shown in full because they are the trap
val playing = intentForThisChange(remoteIsPlaying)
val startAt = when {
    sameItemRebuilt   -> player.currentPosition       // only the queue changed; keep the playhead
    remotePosition <= 0L -> 0L                        // "from the top" is a value, not a stale clock
    else -> clock.positionAt(remotePosition, playing) // a joiner lands where the group is
}
loadItem(item, keepPosition = startAt, startPlaying = playing)
```

## Traps

**"Correct it afterwards" is a race you lose asymmetrically.** Both orderings are possible, but only
one is noticed: correcting in time produces silence, which looks like nothing happened; losing the
race produces sound in a paused room, which every other member hears. So the bug reports arrive
already skewed toward "sometimes", and it gets filed as flaky rather than as ordering.

**`false` is a real value, not "unset".** A flag typed nullable and defaulting to "play" reintroduces
the bug wearing an `Option`: every path that has not thought about it starts playback. Make the
parameter non-optional at the load boundary and let the compiler collect the call sites.

**The position has three cases and only one of them is "where the room says".** A rebuild of the item
already playing — the queue arrived late, nothing else changed — must keep the local playhead, or
every queue update restarts the item. A genuinely new item starts where the group is, so someone
joining mid-item lands beside everyone else rather than at zero.

**A zero position is not a stale timestamp.** Item-change commands routinely carry position 0
meaning "from the top". Running that through a flight-time correction turns it into *however long
ago the last command was*, which on a room that has been idle can seek past the end of the item.
Special-case the non-positive value before the clock ever sees it — see
`monotonic-clock-offset-sync` for what the correction is doing to it.

**Only the first item carries the flag.** Appending the rest of the queue behind it must not, or
the append re-asserts playback and undoes the decision you just made. Load head and tail through
different calls precisely so this cannot be expressed.

**Re-reading the component after the load is a different question.** "Is it playing now?" is
observed state; "should it play?" is intent, and after a load the two disagree for as long as the
stream takes to resolve. Confirming the decision against the component is how a correct decision
gets reverted — see `intent-flag-not-observed-state`.

**The playhead restore goes after the items are added, never before.** A seek issued against a
component that has no item yet is dropped — usually silently, sometimes clamped to zero — so the
restore has to be the last statement in the load block. It is the same ordering hazard as the play
flag, in the one case where "correct it afterwards" is genuinely the right answer.

**Apply on the thread the component demands, and be honest that it is mandatory.** Bridge code
usually runs on a background scope while UI-thread-confined components throw if touched from it.
Wrapping the load in a main-thread context is load-bearing, not tidiness, and the seek that restores
the playhead has to be inside the same block — otherwise it runs against a component that has
already moved on.

**A defaulted parameter on the load API is a hardcoded literal with better manners.** `fun
addItem(item: T, startPlaying: Boolean = true)` reads as a convenience and behaves as a policy:
every call site that has not thought about the question starts playback, and none of them show up in
a search for the literal. Check the *declaration* as well as the call sites — the second command
below does that — and prefer no default at the boundary that matters.

**The rebuild-because-the-queue-arrived case is the one nobody tests.** A shared session can send
the queue after the item, so the same item gets rebuilt with nothing else changed. If that path
takes the new-item branch it restarts the item from zero, mid-playback, for every member — and it only
happens when the two messages arrive in that order, which is exactly the ordering a local test
never produces.

**A hardcoded literal at a load site is the searchable form of this bug.** Not every one is wrong —
a user tapping an item genuinely means "play" — but each one is a place where the decision was made
by the author instead of by the caller. The census below is worth reading once per feature.

## Verifying it

List every load site that hardcodes the start flag, then read each one for who decided it:

```bash
grep -rnE "(playWhenReady|startPlaying|autoPlay|shouldPlay) *= *(true|false)" --include="*.kt" . \
  | grep -v "/build/"
```

A site inside an apply/follow path with a literal is the defect. A site inside a user-initiated
action with a literal is fine. If the flag never appears as a *parameter* anywhere — only as a
property assignment after the load — the load API is not carrying the decision at all and that is
the thing to fix first:

```bash
grep -rnE "fun [a-zA-Z]*[Ll]oad[A-Za-z]*\(|fun add[A-Za-z]*Item\(" -A6 --include="*.kt" . \
  | grep -v "/build/" | grep -iE "playWhenReady|startPlaying|autoPlay"
```

Then the behavioural check, which needs two clients and cannot be done with one:

- Pause on the source, then skip to another item. The follower must load and stay silent. Any
  audible burst — even a fraction of a second — is the race.
- Play on the source, then skip. The follower must start without a stutter, which is the other
  half: over-correcting toward silence shows up here as an item that loads and never starts.
- Join a session already halfway through an item. The follower must land beside the others, not at
  zero, and not past the end.
