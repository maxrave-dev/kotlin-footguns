---
name: sync-room-bridge-echo-guard
description: One bridge joins a local component to a shared room, with the direction of travel decided by role — the source publishes what it does, the follower applies what arrived and publishes nothing — plus a flag held across the apply so a locally-observed side effect of a remote command is not fed straight back. Use when two clients in a synchronised session ping-pong each other, when applying a remote pause immediately republishes a pause, or when a follower's own reactions fire on state it did not cause.
---

# One bridge, two directions, decided by role

A client in a shared room has a component whose state it both *publishes* and *applies*. Write two
classes for that and they drift; write one, and make the direction a runtime decision:

```kotlin
// adapted — names generalized, log lines and the rest of the collector elided
private var applyingRemote = false

private suspend fun watchRoomAsFollower() {
    repository.room
        .map { snapshotOf(it) to (it.inRoom && !it.isSource) }
        .distinctUntilChanged()
        .collect { (snapshot, shouldFollow) ->
            if (!shouldFollow) return@collect
            applyingRemote = true
            try { applyLocally(snapshot) } finally { applyingRemote = false }
        }
}
```

Every publisher then opens with the mirror-image test — *am I the source, and is this change mine?*
— and the role is read inside the collector on every emission, never captured at construction: a
member can be promoted or demoted while the bridge is running.

## Traps

**Role gating stops the publishers; it does not stop the follower's own reactions.** It is tempting
to conclude that a strict source/follower split makes the flag redundant — publishers require the
source role, the apply path requires the follower role, so they can never see each other. They
can: a follower has *local* reactions of its own. One that watches "the user pressed play" fires
identically whether the user pressed play or a remote command did, and without the flag every
applied command triggers whatever that reaction does. This is the case people delete the flag over,
because on paper it looks unreachable.

**The flag is a bet that the local callback arrives synchronously.** It covers exactly the window
between setting and clearing. If the component reports its state change through a listener that
lands a tick later, the flag is already false when the echo arrives and the guard silently does
nothing. Two consequences worth internalising: the guard is a cheap first line, not a correctness
argument, and anything that must not double-fire also needs an idempotence check that does not
depend on timing — a last-applied and a last-published id, compared before acting.

**Guard the derivation, not the transmission.** A helper that only ever runs from inside a guarded
collector inherits the guard; adding a second check there is noise. But a publisher that is *not*
derived from local component state — a barrier answer, a snapshot published because the role or the
member list changed — has nothing to echo, and bolting the flag onto it is an active bug: those
fire precisely while a remote change is being applied. Decide per publisher by asking what triggers
it, not by pattern-matching on the word "send".

**Clear the flag in `finally`, and set it around the *whole* apply.** An apply that throws halfway
— a load failure, a cancelled scope — leaves the flag stuck true and the client silently stops
publishing anything for the rest of the session. That failure has no symptom on the device that
caused it; it shows up as "the others stopped hearing me".

**Make `start()` idempotent.** The bridge is started from wherever the room is entered, and callers
cannot know whether something else already started it. A second call launches a second copy of
every collector, and from then on every command goes out twice.

**Every publisher reacts to a change, so nobody publishes the state that was already there.** A
member who was already running something and *then* takes the source role produces no transition at
all — no item change, no transport event — and the session sits in silence waiting for a command
that only arrives if they happen to touch something. That needs its own collector, on the role flag
itself, publishing a full snapshot. The same argument applies a second time when a new member
arrives after the source's last command.

**Dedupe by identity as well as by flag.** Keep the last id published and the last id applied.
They cost two fields and they are what stops the two ends from trading the same change back and
forth once the flag's window has closed.

**There is no shared "am I allowed" gate — every collector carries its own.** `start()` launches a
handful of independent collectors into one scope, and each is its own lifecycle watching its own
source. Nothing sits above them, so a role check written once at the top of the class protects
nothing: it has to appear inside every collector, and each one added later needs its own copy. The
census below is how you notice the one that does not have it.

**A plain `var` guard is sound only because of a property of the scope somebody else injects.** The
collectors and the apply path share one confined dispatcher — a single thread, or a UI thread — so
an unsynchronised field is fine. Nothing in the bridge says so, and nothing stops a later
refactor from handing it a multi-threaded scope, at which point the flag silently becomes a
visibility bet with no compiler complaint and no runtime error. Either name the requirement where
the scope is injected, or do not depend on the flag for anything the id comparisons cannot cover.

**Keep the bridge on the one interface both platforms implement.** The publishers and the apply
path are the same logic everywhere; the component underneath is not. Writing the bridge against a
concrete player means writing it twice, and the second copy is the one that gets a fix late.

## Verifying it

Take a census of which functions send and which check the guard, then reason about the difference —
the two lists are *not* supposed to match, and reading why is the audit:

```bash
for f in $(grep -rlE "\b(applyingRemote|isApplyingRemote|fromRemote|suppressEcho|remoteApplyInProgress)\b" \
             --include="*.kt" . | grep -v "/build/"); do
  echo "== $f"
  awk '/^ *(private |internal )?(suspend )?fun /{fn=$0}
       /\.send[A-Z]|\.report[A-Z]|\.publish[A-Z]/{print "  SEND  " fn}
       /applyingRemote|isApplyingRemote|fromRemote|suppressEcho/{print "  GUARD " fn}' "$f" | sort -u
done
```

Every `SEND` with no matching `GUARD` must be explainable in one sentence: either it is a helper
called only from a guarded collector, or it is triggered by something other than local component
state. A `SEND` you cannot explain is the echo. If the loop prints nothing at all, no guard field
exists in the tree and every apply path is a candidate feedback loop.

Then confirm the flag is exception-safe and the role is read live:

```bash
grep -rn -A45 "applyingRemote = true" --include="*.kt" . | grep -v "/build/" \
  | grep -E "applyingRemote = (true|false)|try \{|finally \{|catch \("
grep -rnE "\bis(Host|Source|Owner)\b" --include="*.kt" . | grep -v "/build/"
```

The first collapses the apply block down to its structural tokens, and the window has to be wide
enough to span the block: a short one shows the `try` and stops dozens of lines above the `finally`,
so it reads the same whether the shape is right or wrong. What you want out of it is `= true` /
`try {` / `finally {` / `= false`; a `= false` with no `finally` above it is a clear that only runs
on the happy path. The second should show the role being read *inside* collectors; a role captured
once into a `val` at construction is the bug that survives a promotion.

Behaviourally, two clients are the only real test. Drive one, watch the other, and watch the first
one's outbound log while it applies: a command that appears outbound on the applying client is the
echo, and it is invisible from either device alone.
