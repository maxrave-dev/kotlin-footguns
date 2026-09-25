---
name: joiner-catches-up-by-asking
description: The state a relay pushes to a new member is the source's last command replayed, so its position is however old that command is — obeying it drops the joiner at the start of something everyone else is halfway through. Ask for the live position the moment you are in, and again whenever this client rejoins the shared timeline. Use when a member who joins mid-session starts from the beginning, or restarts at whatever position they last had locally.
---

# The pushed state is a replay, not a reading

A relay holding shared session state hands a new member whatever it last heard. That payload is
correct — and its position field is frozen at the instant of the command that produced it. If the
source has been playing uninterrupted for four minutes, the last command it sent was the item change
four minutes ago, carrying position zero.

Apply it verbatim and the joiner starts at the beginning while everybody else is four minutes in. So
the joining sequence has two steps, not one:

```kotlin
// adapted — names generalized; the surrounding collector's role check elided
.collect { inSession ->
    if (inSession && !isSource) {
        // The state pushed on join carries the position as of the source's LAST command, which
        // can be minutes old. Ask for where the session actually is.
        repository.requestSync()
    }
}
```

Apply the pushed state anyway — it is what puts something on screen immediately — and let the answer
overwrite it a round trip later.

## Traps

**Do not extrapolate the stale position from a timestamp.** It is tempting: the payload has a
position and you know roughly when it was set, so advance it. That is a confident wrong answer the
moment the session paused, seeked or changed item in between — and it is wrong *silently*, because
the extrapolated number looks entirely plausible. Asking costs one round trip and cannot be wrong.

**The ask will end up being issued from more than one layer, so make it idempotent and cheap.** The
protocol layer wants to fire it on the approval message; the app layer wants to fire it when its own
"I am in a session" flag flips. Both are legitimate, they are driven by different state, and either
can be the one that survives a refactor. Two asks cost two small frames; one missing ask costs the
joiner the whole session.

**An empty pushed state is a different failure with the same symptom.** If the source has not issued
a command since the session opened, the relay has nothing to push and the ask returns nothing
either. The cure is on the *source* side — publish a snapshot on taking the role, and again when a
member arrives — and no amount of asking from the joiner substitutes for it. Diagnose the two apart
by whether the payload has an item id at all.

**Joining is not the only time this client leaves the shared timeline.** A follower that paused
locally, or dropped and reconnected, is in exactly the same position as a joiner: it knows where it
stopped, and that is not where the session is. Every path back onto the timeline issues the same
ask — see `follower-transport-stays-local` for the resume case.

**Do not block the join on the answer.** The join has already succeeded; waiting for a sync reply
before showing anything turns a working session into a spinner whenever the reply is slow, and there
is no bound on how slow. Show the pushed state, then correct.

**The ask tends to get buried in whatever collector already watches the in-session transition.** It
is one line inside a function named for something else entirely, and from then on nobody looking for
"where do we catch up?" finds it. Either give it its own collector or name it in the log line it
emits — the census below is what recovers it otherwise.

**The reply arrives through the ordinary apply path, so check that path will not drop it.** A
catch-up answer often differs from the state already held in exactly one field: the position. If the
follower's collector dedupes on a key that omits that field, the ask is answered and the answer is
discarded — a bug with no error anywhere, in which the catch-up code is provably running and
provably useless. Whatever key the follow path compares on must include every field the reply can
change.

**Ask on transitions, never on every emission.** The catch-up call is cheap once and expensive
continuously: wired to a state flow rather than to a transition, it becomes a poll that the relay
answers with a state update, which fires the flow again. Attach it to `distinctUntilChanged` edges
and nothing else.

**A joiner needs the queue, not only the position.** The catch-up reply is where the follower learns
what comes *after* the current item. Apply only the transport half and the client is perfectly in
sync on an item with nothing behind it — so the session's next advance arrives as a full rebuild
rather than as a step, with the restart-from-zero that implies. Build the queue from the reply, with
the current item leading it.

**An omitted collection in the reply means "no change", not "empty".** Relays commonly leave a
queue out rather than asserting it is empty; clearing on an omitted field wipes what the joiner just
received a moment earlier through the pushed state.

**Correct with a tolerance once the answer lands.** The reply is a position that was true a round
trip ago, so it goes through the same flight-time correction and the same seek tolerance as every
other command. `position-based-group-sync` covers both.

## Verifying it

List every trigger that asks for the live state, with the function it fires from:

```bash
for f in $(grep -rlE "requestSync\(\)|REQUEST_SYNC" --include="*.kt" . | grep -v "/build/"); do
  echo "== $f"
  awk '/^ *(private |internal |override )?(suspend )?fun |MessageTypes\.[A-Z_]+ ->/{ctx=$0}
       /requestSync\(\)|MessageTypes\.REQUEST_SYNC/{print "   asked from:" ctx}' "$f" | sort -u
done
```

Ignore the declaration and delegation rows — the interface method and the one-line override. What is
left is the trigger list, and it should contain the approval message, the in-session transition, and
the local-resume path. A trigger list with only the approval message on it is a client that catches
up once and never again. An empty list is one that trusts the pushed state.

Then confirm the catch-up vocabulary exists at all:

```bash
grep -rniE "requestSync|request_sync|syncRequest|askForState" --include="*.kt" . | grep -v "/build/"
```

Behaviourally, with two clients, the test only works if you are patient:

- Start a session on one, let it run for **several minutes** without touching anything, then join
  with the second. It must land beside the first. Joining after ten seconds passes even when broken,
  which is why this gets shipped.
- Join a session whose source has opened it but never pressed anything. The joiner must show the
  source's current item, not an empty session — that failure is the source's missing snapshot, not
  the joiner's missing ask.
- Drop the follower's network for a minute and restore it. It must land where the session is now,
  not resume where it stalled.
