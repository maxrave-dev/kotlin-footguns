---
name: publish-a-snapshot-on-taking-the-role
description: Every publisher in a shared session is edge-triggered off a change, so a participant who was already running when they took the publishing role emits nothing and the group sits in silence — publish a full snapshot on becoming the source, and again when a new member arrives. Use when a session starts empty until someone touches the transport, when a late joiner sees nothing, or when your state watchers all look correct and the group still knows nothing.
---

# Edge-triggered publishers have nothing to say about the past

A source-of-truth participant publishes by watching its own state and reacting to changes: an item
transition, a play/pause, a seek, a queue edit. Each of those is a collector over a flow with
`distinctUntilChanged` on it, and that is the right shape — it is also why the group can start
completely empty.

Someone who was already playing when they opened the session produces **no change at all**. Nothing
transitions, nothing toggles, so none of the watchers fire, and every follower waits for a command
that only arrives if the source happens to touch its transport. Two level-triggered publishers close
the gap:

```kotlin
// adapted — names generalized
private suspend fun publishOnTakingTheRole() {
    room.map { it.inRoom && it.isSource }.distinctUntilChanged()
        .collect { isSource -> if (isSource) publishSnapshot() }
}

private suspend fun publishWhenSomeoneArrives() {
    room.map { it.members.size }.distinctUntilChanged()
        .collect { count ->
            val state = room.value
            if (state.inRoom && state.isSource && count > 1) publishSnapshot()
        }
}
```

## Traps

**A relay that remembers the session's last state only remembers what it was told.** "The server
keeps the room state" is not a substitute for the snapshot: it keeps the *last command*, and before
the first command there is nothing to keep. A member approved before the source has issued one joins
an empty session, which is why the second publisher above exists alongside the first.

**A snapshot is usually more than one command, because the item-change command does not carry play
state.** Protocols commonly reset the running flag on an item change — the relay stamps its own
default rather than the source pausing — so a snapshot that sends only "now playing X" hands every
follower a loaded, silent item. Send the item, then send the explicit play-or-pause as its own
command. Get this wrong and the symptom is precise and misleading: followers load the right thing
and sit there stopped. The companion lesson is `server-default-overrides-client-intent`.

**Read the intent flag for that second command, not the observed one.** At the moment a snapshot is
taken the local player may be mid-load, reporting "not playing" while fully committed to playing. A
snapshot built from the observed flag broadcasts a pause the source never asked for — see
`intent-flag-not-observed-state`.

**The snapshot must write the same bookkeeping the change publishers read.** The item-change
publisher skips an item it has already published, using a `lastPublished…` field. If the snapshot
does not set that field, the very next emission from the item flow republishes the same item; if it
sets a *different* field, the two publishers stop agreeing about what has been sent. One field,
written by both. This is the kind of coupling that survives review because each function is
individually correct.

**Key the arrival publisher on membership, and remember that it also fires on departures.** A count
that goes 2 → 1 is still a change, which is why the branch re-checks `count > 1` rather than trusting
the emission. Keying on the count instead of the member list is deliberate: a member's
buffering/connected flags churn constantly, and keying on the list republishes the whole session
state on every one of them.

**Do not fold the snapshot into the role flag's other consumers.** The role transition usually drives
several things at once — enabling publishing, disabling a conflicting feature, requesting a sync.
Keeping the snapshot in its own collector is what lets it be re-entered from the arrival path too,
and what keeps the other consumers from acquiring an ordering dependency on it.

**Put the role in the key, not only in the body.** The role publisher maps the whole state down to a
single boolean *before* `distinctUntilChanged`, so it emits once per transition. Collect the state
object instead and test the role inside the collector and it fires on every unrelated field — member
flags, positions, buffering — republishing the entire session state each time. On a busy session that
is a broadcast storm, and it looks like a network problem rather than a key that is too wide.

**A snapshot with nothing in it is worse than no snapshot.** Unlike the change publishers, this one
fires on a *transition of the role*, which can easily land before anything is loaded — the user opens
the session first and picks something afterwards. Return early on a null current item and on a blank
identifier, in that order, or the group is handed an empty item and every follower dutifully loads
nothing. The change publishers will cover it the moment something starts.

**A follower does not publish, including when it takes over.** The role flag gates the publishers,
so a handover has to flip that flag *before* the snapshot runs, or the new source publishes nothing
and the old one has already stopped. Verify the handover by watching the flag, not by watching the
transport.

## Verifying it

The property is "every publisher is edge-triggered except the ones that are deliberately not", so
census them and look at what each is keyed on:

```bash
grep -rnE '(suspend )?fun publish[A-Za-z]*\(' --include='*.kt' . | grep -v '/build/'
grep -rlE '(suspend )?fun publish[A-Za-z]*\(' --include='*.kt' . | grep -v '/build/' | xargs -r grep -n -B10 'distinctUntilChanged()' | grep -E '\.map \{|distinctUntilChanged\(\)'
```

The first lists the publishers. Expect the edge-triggered set (item change, play/pause, seek, queue)
plus **two** level-triggered entries — one keyed on the role, one on membership — plus the plain
functions those delegate to, which is usually a snapshot builder and a queue sender. Around eight
entries is normal. Only one of the two level-triggered ones is the common shipping state, and the missing
one is a real defect with a distinct symptom: no role publisher means the session starts empty, no
arrival publisher means late joiners see nothing while everyone already in it is fine.

The second prints each collector's key next to its `distinctUntilChanged`. Read the `.map` lines as a
list: one should be the role flag, one the member count, and the rest should be state that genuinely
changes when the source acts. The window is wide because a key can be a multi-line projection: a
`.map {` with nothing after the brace proves such a key exists without showing you what is in it, so
read that collector by hand — it is usually the most interesting one in the file — and a
`distinctUntilChanged()` with no `.map` above it at all means the window is still too narrow for
this tree rather than that the collector has no key. A key that is an object rather than the fields
you care about is a different bug — see `flatmaplatest-resubscribe-composite-key`.

Then run the one scenario that only these publishers cover: start playing something, *then* open the
session, and have a second client join without anybody touching the transport afterwards. The joiner
must land on the right item, at roughly the right position, in the right play state. Touching the
transport to "check it works" is what hides this — every other publisher fires the moment you do.
