---
name: readiness-barrier-needs-every-answer
description: A barrier that holds a group until every member reports ready — answer it on bufferedness rather than on playing, answer only when you are actually named, name who is being waited for in the UI, and understand that one member that never answers freezes everyone. Use when a shared session stalls for all participants after one slow device joins, when playback silently never starts, or when a "loading" state has no explanation attached to it.
---

# The barrier is only as fast as the member that never answers

Several clients each resolve their own copy of the same item, at their own speed. When one of them
cannot keep up, holding the rest with it takes a rendezvous: the server announces who it is still
waiting on, each named client answers when it has the item, and only when the last answer lands does
anybody hear anything.

```kotlin
// adapted — names generalized; the message constants are placeholders
private suspend fun answerBarrier() {
    room.map { it.waitingFor to it.currentItem?.id }
        .distinctUntilChanged()
        .collect { (waitingFor, itemId) ->
            val state = room.value
            if (itemId.isNullOrBlank() || !state.inRoom) return@collect
            if (state.selfId !in waitingFor) return@collect
            // bufferedness, not playing: the barrier asks whether the item is loaded, and playback
            // is exactly what it is holding back.
            if (player.bufferedPercentage >= READY_BUFFER_PERCENT) reportReady(itemId)
        }
}
```

The whole model rests on one uncomfortable property: this is a **liveness dependency on every other
participant**. Everything below follows from that.

## Traps

**Answering on "playing" is a deadlock, and it looks like a hang.** Playback is what the barrier is
holding back, so a client that waits to be playing before reporting ready waits for something the
barrier will never let happen — and because the barrier holds *everyone*, the whole room stops,
including the member driving it. Answer on the loaded/buffered signal instead, at a low threshold: a
few percent proves the stream resolved, which is the actual question. Waiting for a large buffer
just makes the slowest device slower without making the start any more reliable.

**A client that does not implement the answer at all freezes the group silently.** There is no error,
no timeout on the client side, and nothing in the logs of the members who are behaving correctly —
they are simply told to wait and they wait. This is the failure mode to look for first when a shared
session stops working after a new participant joins, and it is why the answer belongs in its own
collector started unconditionally, never inside a branch that some role or setting can skip.

**Only answer when you are named.** The announcement carries the list of members still outstanding;
answering while not in it is at best noise and at worst confuses a server that tracks the set by
membership. The `selfId !in waitingFor` guard is one line and it also makes the collector safe to
run on a re-announcement, which arrives every time somebody else answers.

**Key the answer to the item being waited for, not to "the current item".** Send back the id from
the announcement. If the local item changed in the meantime, the answer is about the wrong thing and
the server keeps waiting — and re-deriving the id from local state is exactly how that happens. The
same reasoning applies to the `distinctUntilChanged` key above: it carries both the outstanding list
and the item id, because either changing is a new question.

**Silence with no explanation reads as a hang, so name the members.** Store ids on the wire and
resolve them to display names at the edge: "waiting for <name>" is the only phrasing that tells a
user what is happening and who to nudge. A bare spinner during a barrier is indistinguishable from a
crash, and users respond by force-quitting — which removes the member the group was waiting for and
makes the barrier appear to "fix itself", hiding the real cause.

**Clear both halves when the barrier completes.** The outstanding list and any per-member flag
derived from it are two pieces of state, and the completion message must reset both. Leaving the
per-member flag set paints one participant as permanently loading, which is a bug report about the
wrong thing entirely. Deriving the flag from the list at read time (`id in waitingFor`) avoids the
whole class.

**Make the answer idempotent rather than one-shot.** The announcement is re-broadcast every time
somebody else answers, so the collector fires repeatedly with a shrinking list — and that is fine,
because the membership guard stops answering as soon as you are removed from it. The tempting
optimisation is a local "already answered for this item" flag, which reintroduces the freeze the
moment a first answer is lost in transit: the flag says done, the barrier says waiting, and neither
side moves. Let re-answering be cheap and let the list be the authority.

**A barrier is not a substitute for position sync, and which gap each one owns is a property of the
server rather than of your client.** In the arrangement this was mined from, the item change
*clears* the outstanding set server-side, so the barrier never gates a change at all: the loading
gap at a transition is absorbed by publishing the position and correcting it for flight time —
`position-based-group-sync` — and the barrier engages only when a device stalls part-way through an
item that is already running. Read the server's own handling instead of assuming, because the client
code is agnostic and cannot tell you which arrangement you are in. Getting it backwards makes every
transition wait on the slowest member, which is the cost the position correction exists to avoid.

## Verifying it

The barrier crosses three layers — protocol, the answering collector, and the UI that explains it —
so verify it as three greps rather than by reading the answering function again:

```bash
grep -rniE 'waitingFor|bufferReady|isBuffering' --include='*.kt' . | grep -v '/build/' | cut -d: -f1 | sort -u
grep -rn 'bufferedPercentage' --include='*.kt' . | grep -v '/build/'
grep -rniE 'waitingFor' --include='*.kt' . | grep -v '/build/' | grep -iE 'name|username|displayName'
```

The first is the census of everything that participates: expect the protocol payloads, the state
machine, the domain model, the answering collector and at least one presentation file. A missing
presentation file is the "silent hang" defect — the barrier exists and nothing tells the user about
it. The second finds every reader of the loaded signal; the one inside the answering collector is the
barrier's, and if that grep shows the collector reading a *playing* flag instead, stop and fix it
before anything else. The third should show the id→name resolution, and it is worth confirming it
lives on the model both the state machine and the UI can see rather than being re-derived in a
composable.

Then run the only test that actually exercises the property: join with two clients and put one of
them on a deliberately slow or blocked network at an item change. The fast client must show the slow
one by name and start when it answers. Kill the slow client instead of letting it answer, and watch
what the fast one does — if it waits forever with no message, the barrier has no give in it and the
group depends on every member behaving, which is worth knowing before users find out.
