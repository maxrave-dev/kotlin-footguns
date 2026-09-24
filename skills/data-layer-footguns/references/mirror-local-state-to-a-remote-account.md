---
name: mirror-local-state-to-a-remote-account
description: An opt-in switch that mirrors a local flag onto a signed-in remote account — turning it on back-fills everything already flagged, turning it off stops mirroring and deliberately does not undo, and the per-item call is three-valued so "not attempted" is distinguishable from "failed". Covers writing locally first and unconditionally, which of the two paths is allowed to speak to the user, and why the back-fill is sequential. Use when a mirrored flag silently disagrees with the account, when the user cannot tell a failure from a no-op, or before wiring a settings switch to a remote write.
---

# Mirroring a local flag onto a remote account

The feature is one switch: *when I mark a record as followed here, mark it followed on my account
too*. Almost all the difficulty is in what the switch means at its two edges, and in what the
per-item call is allowed to return.

```kotlin
// adapted — the whole contract, in the repository interface
/**
 * Records the flag locally, and mirrors it onto the account when mirroring is enabled.
 *
 * Returns null when mirroring is off or was not attempted, true when the account was updated,
 * false when the call failed — the caller decides whether that is worth telling the user about.
 * The local flag is written either way: marking a record must not depend on the network.
 */
suspend fun setFollowed(recordId: String, followed: Int): Boolean?

/** Mirrors every record already flagged locally. Emits (succeeded, attempted). */
fun backfillFollowedToAccount(): Flow<Pair<Int, Int>>
```

## The switch is asymmetric on purpose

**Turning it on is a statement about the whole collection**, not about the next record touched.
Without a back-fill, everything flagged before the switch stays invisible to the account forever,
and the user has no way to discover that except by comparing two lists by hand.

**Turning it off is not a request to undo.** Stopping the mirror is not the same as asking for every
previously mirrored record to be un-flagged remotely — the user may well have wanted them there.
Undoing is a destructive operation on someone else's account performed by a switch labelled *stop
doing this*, which is exactly the shape a user never expects.

```kotlin
// adapted
fun setMirroringEnabled(enabled: Boolean) {
    scope.launch {
        settings.setMirroringEnabled(enabled)
        if (enabled) repository.backfillFollowedToAccount().collect { }
    }
}
```

## Traps

**Write locally first, unconditionally, and never roll it back.** The local flag is the feature the
user is actually using; the mirror is a courtesy. A local write conditional on a remote success
means the record does not appear as flagged when the connection is down — and if the remote write
is attempted first, a timeout costs the user their action entirely. Order is: local write, then
consult the setting, then attempt the mirror.

**Two states are not enough, and the third is the important one.** A `Boolean` return folds *nothing
was attempted* into *it failed*, so a user with mirroring switched off sees a failure notice on every
action. `null` for "not attempted" is what lets the caller stay silent in exactly the case where
there is nothing to say. Do not substitute a `false` plus a separate "is mirroring on" read at the
call site: those are two reads of a setting that can change between them.

**Only the path the user is watching reports.** The per-record call happens because someone tapped
something and is waiting to see it take effect, so both outcomes are worth a notice. The back-fill
runs behind a settings switch, over an unbounded number of records, and the user is not watching a
single one of them — a notice per record, or even one at the end, is noise about work they did not
ask to observe. Same repository, same failure, opposite decision.

**The notice speaks for the account, not for the local action.** The local flag succeeded; that is
already reflected on screen. Word the message so it is unambiguous which of the two it refers to —
*"followed on your account"* and *"couldn't update your account"* rather than *"followed"* and
*"failed"*, which read as though the local action did not happen.

**The back-fill is sequential, and that is not laziness.** These are writes to someone else's
account. Firing a few hundred concurrently is the shape that gets a session rate-limited or
challenged, and the user's punishment for enabling a convenience feature is losing their session.
A plain `forEach` with a counter is the right implementation; if it needs to be faster, it needs a
bounded worker count and a backoff, not `async`.

**Read the whole local collection in bounded pages, not one query.** The back-fill's input is "every
record with the flag set", which is unbounded by construction — see `generic-paged-db-accumulator`
for the accumulator shape and for when reading everything is legitimate at all.

**The switch needs a session, so it needs all three defences.** Mirroring cannot work signed out, so
the row is inert then — which means the user cannot switch it off, which means it must switch
*itself* off. Greying the row is only the visible half; the callback must **clear the stored flag**
(`nested-flag-settings-auto-disable`), and the sign-out path must clear it too, because a settings
row that is scrolled off screen never runs its effect (`login-state-fans-out-to-settings`).

**A failure is logged, not retried, and that is a decision to write down.** A single mirror call
that fails leaves the two sides disagreeing with nothing scheduled to reconcile them. That is
acceptable *because* re-running the back-fill reconciles everything at once — so the back-fill is
not only an onboarding step, it is the repair mechanism, and something should be able to trigger it
again. Without that, "log and move on" is silent permanent drift.

**The remote call is one function with a boolean, not two call sites.** Set and clear differ by one
argument; splitting them into separate paths is how one of the two ends up missing its error
handling. Wrap both in a single private helper that returns whether the account was updated.

## Verifying it

1. **The per-item call is three-valued all the way up.** Find the contract, then check what every
   caller does with the third state — a `?: false` has thrown it away:

   ```bash
   grep -rnF '): Boolean?' --include='*.kt' . | grep -v '/build/'          # the contract
   grep -rn -A16 '<mirror-function>(' --include='*.kt' . | grep -v '/build/' \
     | grep -E 'null ->|== null|\?: (true|false)'                          # what callers do
   ```

   A `null ->` branch per caller is the shape you want. The wide context window matters: the
   handling sits at the bottom of a `when`, well past the call itself.

2. **The back-fill exists and is called from the enable path only:**

   ```bash
   grep -rn 'backfill\|syncAll\|syncFollowed' --include='*.kt' . | grep -v '/build/'
   ```

   Expect exactly one caller, inside an `if (enabled)`. A caller on the disable path is the undo
   nobody asked for; no caller at all means the switch only ever affects future actions.

3. **The gated row clears its own flag.** Count the rows declaring a gate against the rows that
   supply the clear-callback, then judge the gap per line rather than by the count: a gate on a
   **static build fact** (`isEnable = getPlatform() == …`, `isEnable = true`) has nothing to clear,
   and the rest of the gap is the set of switches that grey out and stay set:

   ```bash
   grep -rn 'isEnable = ' --include='*.kt' <settings-screen> | wc -l
   grep -rn 'onDisable = ' --include='*.kt' <settings-screen> | wc -l
   ```

4. **Behaviourally, five runs**, because they exercise five different decisions:

   - Mirroring **off**: flag a record. It must flag locally and say **nothing**.
   - Mirroring **on**, network unplugged: it must still flag locally and report the *account* failure.
   - Flag several records with mirroring off, then turn the switch **on**: all of them must reach
     the account, with no per-record notices.
   - Turn the switch **off**: previously mirrored records must remain on the account.
   - Sign out with the switch on, then read the stored value without opening settings: it must be off.
