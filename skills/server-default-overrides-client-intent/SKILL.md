---
name: server-default-overrides-client-intent
description: A relay that owns the shared state stamps its own default onto fields your command did not set — most painfully forcing "not running" onto every item change — so a follower that obeys the message verbatim stops the thing it just loaded. Carry the previous intent across the change, and publish the missing field as a second command. Use when followers in a synchronised room go silent on every next/previous/end-of-item while the source plays on.
---

# The relay fills in the blanks, and its blanks are not neutral

A relay holding shared session state has a struct with every field in it. A command that changes one
field still produces a full struct on the wire, and the fields you did not set take the relay's
default — which for a running/paused flag is almost always `false`. So an item-change command
arrives at every follower carrying "not running", on a session that never paused.

Obey it and the follower loads the new item and stops. This looks like a client bug and is not one:

```kotlin
// adapted — names generalized
// The relay forces "not running" on EVERY item change: protocol default, not a member pausing.
// Carry the session's previous intent across the change; a real pause arrives as its own
// command, with the item unchanged, and is applied normally.
val running = if (itemChanged && !incomingRunning) lastSessionRunning else incomingRunning
lastSessionRunning = running
```

And on the publishing side, the mirror obligation: after announcing an item change, send the
running/paused state as a **separate** command, because the item-change command has no field the
relay will keep.

## Traps

**The override must be narrow or it eats real pauses.** Both halves of `itemChanged && !incoming`
matter. Drop the first and every pause is ignored. Drop the second and a genuine "pause on the next
item" is overridden into playing. Anything wider than "the item changed *and* the flag is sitting at
the relay's default" is a client that cannot be paused.

**Update the carried value on every applied command, not only on item changes.** It is "what the
session most recently intended", so a pause must write it too. Update only on item changes and the
carried value goes stale after the first pause/resume pair, at which point the next item resurrects
whatever the session was doing several commands ago.

**Write the carried value from the *resolved* result, not from the incoming field.** After the
override runs you have two values in scope — what arrived and what you decided — and storing the
wrong one makes the carry a one-shot: the next item change reads back the relay's default, which is
the thing you just compensated for. One line, and it silently halves the fix.

**Every field your command omits gets a default, not only the running flag.** A queue you did not
send comes back empty, a title comes back blank, a position comes back zero. Which of those are
assertions and which are "nothing to say" is a property of the relay, and the answer is usually
"nothing to say" — so an omitted collection should preserve what you had rather than clear it.

**Clear it when leaving.** A carried "was running" that survives leaving the session makes the next
one you join start playing on its first item change, before anyone has pressed anything.

**Nothing on the source side will send the missing field for you.** The source's own local state
does not change when one running item follows another — no transition, no emission, no publisher
fires. That is why the second command has to be sent explicitly from the item-change path, and why
"it works when I press play manually" is the misleading observation that stalls this bug for days.

**Publishing a full snapshot means two commands, not one.** Whenever you push current state — on
taking the source role, on a new member arriving — send the item change *and* the running state
after it, for exactly the same reason. One command leaves the session announced-but-paused.

**The relay may silently drop your correction for a reason unrelated to the default.** A
running/paused command carrying an item id the relay no longer considers current can be rejected as
stale and dropped without an error — treat that last part as a hypothesis rather than a fact you can
observe: the relay is not in your tree, no client path branches on the rejection, and the only
record of it is likely to be the implementing author's own note. The prescription survives either
way, because it costs nothing: where the protocol allows it, send the id empty and let the relay
fill in its own current item, which is always right by construction. See `api-ok-but-ignored` for
the general shape: accepted-and-discarded is its own outcome.

**Do not fix this in the relay.** If the wire format and the counterpart implementation are not
yours, a "cleaner" default is a client that no longer interoperates with anyone else in the session.
The default is a fact about the protocol; the compensation belongs in your client.
`borrowed-wire-protocol-discipline` is the general rule.

**Resolve the flag once, above the load, and use the same value for both steps.** The compensated
value is what decides whether the new item starts *and* what the transport step applies. Computing
it twice — once for each — is two places to get the condition right, and they diverge the first time
someone edits one of them.

**Compensating on your own source side does not excuse the follower side.** A session can contain a
client you did not write, whose source path knows nothing about the missing field. The follower's
carry is what makes the session work with those clients, and it is the half that gets dropped as
redundant once your own two clients talk to each other correctly.

**It is invisible from the device that causes it.** The source plays through the whole change
correctly. Every symptom is on the other members, which is why this is worth writing down rather
than rediscovering: a single-device test suite can never fail on it.

## Verifying it

Find the carried-intent field and confirm it is written on every applied command, not just on item
changes:

```bash
grep -rnE "private var last[A-Z][A-Za-z]*" --include="*.kt" . | grep -v "/build/"
```

Then check that the publish side really emits two commands per item change — the second one, with an
empty item id, is the field the relay would otherwise default:

```bash
grep -rn -A40 -E "CHANGE_TRACK|CHANGE_ITEM|changeTrack" --include="*.kt" . | grep -v "/build/" \
  | grep -E "PlaybackActions\.(PLAY|PAUSE)|action = (PLAY|PAUSE)"
```

The window is deliberately wide: on the path that waits for intent to settle, the follow-up command
sits thirty-odd lines below the change. Count the hits against the number of change sites — a change
site with no play/pause command after it is the one that leaves followers loaded and stopped. If the
second grep returns nothing at all, no publish path is compensating and every item change in the
tree lands as a pause on the other side.

Behaviourally, this needs two clients and three separate transitions, because they fail
independently:

- **next** and **previous** on the source — the follower must keep playing through both.
- **end of item**, where the source advances on its own — the transition with no user input, and
  the one most often missed because nothing "happened".
- a **real pause** issued right after an item change, which must still pause the follower. Passing
  the first three and failing this one means the override is too wide.
