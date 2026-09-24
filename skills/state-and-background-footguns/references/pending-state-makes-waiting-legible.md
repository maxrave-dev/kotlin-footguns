---
name: pending-state-makes-waiting-legible
description: Model "asked, and not yet answered" as its own field, because without it a rejected request and a peer who simply has not looked at their screen are indistinguishable — both look like nothing happened. Covers the one set against many clears, clearing locally when no answer will ever come, and giving the user a way out. Use when an action appears to do nothing, when a screen can get stuck waiting forever, or when an error message has no place to appear.
---

# "Nothing happened" is three different states wearing one face

Some requests are not answered by the system you sent them to. They are answered by a *person* —
another participant approving a join, a peer accepting a transfer — and that person may take a
minute, or never look. If the only states you model are "not in" and "in", then a mistyped code, a
peer who declined, a peer who is asleep, and a message that never left the device all render
identically: the button was pressed and the screen did not change.

One nullable field fixes all four:

```kotlin
// adapted — names generalized
/**
 * The code we asked to join and have not heard back about.
 *
 * Joining is not immediate — someone has to approve it — and without this the UI has nothing to
 * show between sending the request and the answer arriving.
 */
val pendingJoinCode: String? = null,
```

and the screen branches on it before it branches on membership, so "waiting for approval, here is
the code you sent, here is a way to give up" is a state the design has to account for.

## Traps

**One place sets it; every terminal path has to clear it.** Approval, rejection, an error while
waiting, the user cancelling, and — easy to miss — the send itself failing because there was no live
connection. That last one is the most misleading if skipped: the request never left, so no answer can
ever arrive, and the screen waits forever on a message that does not exist. Count the writes: one
set against four or five clears is the healthy shape, and a clear-site count equal to the set-site
count means paths are missing.

**Clear locally when the protocol sends nothing back.** Some requests are fire-and-forget by design
— leaving, cancelling — and waiting for a confirmation that will never arrive leaves the session UI
on screen with controls that silently do nothing. Clear the local state at the send and say in a
comment that the silence is expected, or the next reader will "fix" it into a wait.

**Give the user a cancel, and make it local.** A cancel that sends a message needs the connection
that may be the reason they are stuck. Dropping the pending field is enough: if the answer arrives
afterwards it is handled on its own terms, and if it never arrives nothing is leaked.

**Distinguish errors about the request from errors about everything else.** An error arriving while a
request is outstanding is almost always *about* it — a bad code, a full session — so it should clear
the pending field and become the message shown. An error about an unrelated background message must
not: clearing on every error tears down a legitimate wait, and showing every error puts an alarming
banner up for something the user cannot act on. Filter first, then react.

**A one-shot error needs an owner that clears it, or the screen wedges.** Pair the pending field with
an error field that the UI clears once it has shown it. Without that, a transient failure remains the
newest thing the state has to say forever, and the next legitimate attempt renders underneath a stale
message about the last one.

**Do not reuse the pending field as the identity of the thing you are joining.** It holds *what was
asked*, not *what you are in*, and the two have different lifetimes — the answer carries the
authoritative identity and the pending field dies at that moment. Collapsing them produces a session
that appears joined while the request is still outstanding.

**Make it hold what was asked, not a boolean.** `String?` carrying the identifier beats
`isWaiting: Boolean` for two reasons that only show up later: the screen can echo the request back
("waiting on ABCD"), which is how a user notices they typed the wrong thing before anyone answers;
and when an answer finally arrives you can check it is about the request still outstanding rather
than a superseded one. A boolean cannot tell those apart, so a late answer to an abandoned request
lands as though it were the current one.

**A wait that survives a reconnect is a wait for a request the peer never received.** When the
connection drops, anything outstanding died with it — the message may not even have left. If the
disconnect path resets the whole state, this is handled for free; if it only marks the connection as
reconnecting and leaves the rest alone, the pending field lives on and the screen keeps waiting for
an answer nobody was ever asked for. Decide it deliberately: either clear on any disconnect, or
re-send on reconnect. Silently keeping it is the option that looks like neither.

**The pending state belongs to the state machine, not the screen.** Held in a composable it is lost
on rotation, on navigating away, and on the recomposition that a background answer triggers; it also
cannot be cleared by the message handler that learns the answer. Put it on the same state object the
answers update, and let it cross the layer boundary like any other field.

## Verifying it

The set/clear asymmetry is the whole property, and it greps well:

```bash
grep -rnE 'pending[A-Z][A-Za-z]*' --include='*.kt' . | grep -v '/build/' | cut -d: -f1 | sort | uniq -c | sort -rn
grep -rnE 'pending[A-Z][A-Za-z]* *=' --include='*.kt' . | grep -v '/build/'
```

The first ranks files by how much pending vocabulary they carry; the state machine should lead by a
wide margin, since it holds the field and every path that clears it. The screen and the model
contribute a line or two each and sit near the bottom — that is the healthy shape, not a warning. The
list also collects unrelated populations — a platform pending-intent, a pending edit in a settings
form, a pending deep link waiting for the app to finish starting (`desktop-deep-link-plumbing`) — so
read the names before concluding anything. A field sharing the prefix *inside the state machine
itself* may not be a wait either: a name or an identifier parked for a later message reads
identically here. Group by field first, and ask the question below only of the fields that are
nullable and have an answer coming.

The second is the real check: every assignment, set and clear together. Read the field you care about
as a group and confirm you can name the path behind each line — sent, send-failed, approved,
rejected, errored, cancelled. A clear you cannot attribute to a path is dead; a path you cannot find
a clear for is a screen that can hang. Anything appearing exactly once is either a plain mapping
across a layer or a field with no way out of its wait.

Then exercise the four cases by hand, because they differ only in timing: submit a request nobody
answers and confirm the wait persists and the cancel works; submit one that is declined and confirm
the reason replaces the wait; submit a wrong identifier and confirm the error clears it rather than
leaving both on screen; and submit one with the connection down and confirm it fails immediately
instead of waiting for an answer that was never asked for.
