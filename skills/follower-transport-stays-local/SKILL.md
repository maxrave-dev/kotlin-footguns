---
name: follower-transport-stays-local
description: A follower in a shared session owns its own stop button — pausing is local and silent, and pressing play asks where the session is now rather than restoring where this device stopped. Use when a follower cannot pause because the next state update immediately resumes it, when a follower's pause stops everyone, or when resuming lands minutes behind the rest of the group.
---

# Following is not being driven

The obvious implementation of "follow the session" is to apply the shared state whenever it changes
and correct any local divergence back toward it. That makes pause *impossible*: press it, the next
state emission notices the divergence, and playback resumes instantly. Users read this as a broken
button, not as a design.

A session is something you listen along with, not something that holds your transport hostage. The
follower's local controls are its own, and the only rule is what happens on the way back in:

```kotlin
// adapted — names generalized; the collector maps the local running flag and dedupes it
.collect { locallyRunning ->
    val session = repository.session.value
    if (!session.inSession || session.isSource || applyingRemote) return@collect
    if (!locallyRunning) return@collect          // paused locally: leave the session running
    repository.requestSync()                     // resumed: ask where the session is NOW
}
```

Two things this deliberately does not do: it publishes nothing, and it restores nothing.

## Traps

**The fix is not in the apply path.** It is tempting to special-case "we paused locally, so ignore
this update" inside the collector that applies shared state. That collector has no way to tell a
local pause from a stale one, and every such special case is a new way for the follower to stop
following. Do it the other way round: the follower simply does not treat its own transport as a
divergence to correct, and the apply path is left alone.

**A follower's pause must publish nothing.** Publishing it stops the whole session on one person's
stop button. Which means the transport publishers are gated on the source role, not merely on
"something changed" — and it is worth checking that gate explicitly, because during development the
same client is usually both.

**Do not restore the local playhead on resume.** Where this device stopped is exactly the wrong
answer: the session moved on while it was paused, possibly through several items. Ask for the live
state instead — see `joiner-catches-up-by-asking`, which is the same problem arriving through a
different door.

**The role check comes before the paused-vs-resumed branch, not inside it.** Ordered the other way,
a *source* pausing falls into the follower's "leave the session running" branch and its pause is
never published — the exact inverse bug, and one that looks like the relay dropping commands.

**Guard the local-transport collector against remotely-applied state.** Applying a remote *play*
sets the local running flag, which fires this collector, which asks for a sync it does not need. It
is harmless here — a redundant sync request — but that is luck, not design: any reaction with a side
effect in this position fires on state the follower did not cause. `sync-room-bridge-echo-guard`
covers the flag and its window.

**Treat the answer as full state, not as a transport update.** A follower that paused for several
minutes may resume onto an item the session left long ago. The catch-up reply carries the current
item, position and queue, and applying only its running flag leaves the follower playing the wrong
thing perfectly in sync.

**Dedupe the local transport stream first.** Components re-emit the same running value on every
internal change, so without a `distinctUntilChanged` the resume branch fires on ticks where nothing
happened and turns the catch-up into a poll. Map to the one boolean, dedupe, then decide.

**Resuming issues a request, not a command.** That distinction is the entire safety of this design:
the follower asks the relay where the session is and applies the answer through the ordinary apply
path. Nothing it does on its own transport ever leaves the device — which is what makes "a follower
may pause" implementable at all rather than a special case bolted onto the publishers.

**The follower's play button is a different action from the source's, wearing the same widget.** On
the source it means "start the session"; on the follower it means "put me back on the timeline".
Naming that in the code — a catch-up call rather than a transport command — is what stops someone
later from "simplifying" the two into one handler that publishes.

**Rejoining after a drop is this same path, not a second mechanism.** A follower whose connection
came back knows where it stopped and nothing about where the session went. Route it through the same
catch-up, and there is one behaviour to get right instead of two that disagree.

**Only the shared axis is shared.** Volume, output device, subtitles, display settings — a follower's
local everything-else is not a divergence either, and a "correct any difference" reflex tends to
grow into those next.

## Verifying it

Read the follower's local-transport collector, and confirm it exits rather than corrects:

```bash
grep -rn -B2 -A14 -E "\.(controlState|transportState)\b" --include="*.kt" . | grep -v "/build/" \
  | grep -E "isHost|isSource|applyingRemote|requestSync|\.play\(\)|\.pause\(\)|return@collect"
```

What you want to see in the follower branch is a role check, an early return on the paused case, and
a catch-up call on the resumed case — and **no** `.play()` or `.pause()` at all. A `.play()` in this
list is the forced restore that makes pause impossible. A branch with no role check publishes a
follower's pause to everyone.

Then confirm the publishers really are source-gated. Role gates come in two idioms and each needs
its own command — the early return, and the one-line `if`:

```bash
grep -rn -B1 -A2 "return@collect" --include="*.kt" . | grep -v "/build/" \
  | grep -E "!.*is(Host|Source)|is(Host|Source) *\|\|"
grep -rnE "if \(.*\bis(Host|Hosting|Source)\b.*\) *[a-z][A-Za-z]*\(" --include="*.kt" . | grep -v "/build/"
```

Between the two lists every transport publisher should appear, and one appearing in neither is a
follower that can stop the session. Do not read the first list on its own: a publisher written as
`if (isSource) publish…` is correctly gated and simply is not in that shape, so taking its absence
for the defect sends you off to rewrite working code.

Behaviourally, with two clients:

- Pause on the follower. The source must keep playing, and the follower must **stay** paused —
  watch it for a full ten seconds, because a forced restore usually takes one update to fire.
- Resume on the follower after a minute. It must land where the source is now. Landing a minute
  behind is a restore; landing at the start of the item is the pushed-state trap.
- Pause on the follower, then let the source change item twice, then resume. The follower must be on
  the source's current item — not still on the old one, in sync.
