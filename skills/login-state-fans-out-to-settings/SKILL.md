---
name: login-state-fans-out-to-settings
description: Logging out must reset every setting that depended on being logged in, at the logout choke point itself — otherwise a gated switch stays on for a service you are no longer authenticated to and silently no-ops forever, or errors on every tick. Use when a feature toggle is stuck on, cannot be switched off, or keeps running against a credential that is gone.
---

# Withdrawing a credential is a fan-out, not a field write

Logging out looks like one line: clear the stored credential. It is not. Around that credential sits
everything the app derived from it or gated behind it — a feature switch the user turned on, a
cached access token and the timestamp saying when it expires, a per-feature sub-switch, a cached
profile name shown in the settings entry. Clearing only the credential leaves all of it behind,
pointing at an account you no longer have.

The state that survives is worse than useless, because it is *inconsistent in a direction the user
cannot fix*: a feature switch gated behind "logged in" greys out when the user logs out, so the
switch reads ON and refuses to be turned OFF. Only code can clear it now, and the code that should
have is the logout you just wrote.

Do the fan-out where the credential is withdrawn:

```kotlin
// adapted — names generalized; the source spells this as a login setter taking false, so its state
// emit is folded into the refresh here; a second derived-token/expiry pair and a settle delay elided
fun logOut() {
    viewModelScope.launch {
        settings.setCredential("")
        // Everything gated behind that credential comes down with it. Otherwise the sub-switches
        // stay stuck ON with no way to switch them off (they grey out when logged out) and stale
        // derived tokens linger.
        settings.setFeatureAEnabled(false)
        settings.setFeatureBEnabled(false)
        settings.setDerivedToken("")
        settings.setDerivedTokenExpires(0)
        refreshLoginState()
    }
}
```

## Traps

**There is more than one way to lose a credential, and only one of them is a button.** The user can
log out; the *service* can also revoke the session, which your client discovers as one specific
error code on an ordinary call. The revocation path must run the same reset, or every symptom in
this skill appears without anyone having touched the logout button — and it is much harder to
reproduce, because the trigger happened on someone else's server. Route both paths through one
function rather than clearing the credential in two places:

```kotlin
// adapted — names generalized
if (error.needsReauth) {
    // Clearing the stored session puts the settings entry back to "log in" instead of the feature
    // silently doing nothing forever.
    settings.clearSession()
}
```

**A UI-level auto-disable is not a substitute for the choke point.** A settings row that turns its
own switch off when its gate goes false (`nested-flag-settings-auto-disable`) only runs while that
screen is composed. Log out from somewhere else, or have the session revoked in the background, and
nothing runs — the flag stays on until the user happens to open settings again. Where a codebase has
several integrations, this is usually why one of them looks fixed and another does not: they were
fixed at different layers.

**Two failure shapes, and the quiet one is worse.** If the consumer gates correctly on the
credential, a stuck flag produces a feature that is on and does *nothing*, indefinitely, with no
error — the user believes it is working. If the consumer does not gate, the same stuck flag produces
a call against an empty credential on every tick, which at best floods the log and at worst becomes
an endless authentication retry (`retry-needs-backoff-and-cap`). Both need fixing, and the silent
one will not be reported.

**Gate the consumer as well, and derive the gate from both facts.** The reset is the cure; the gate
is the seatbelt, and it also closes the window between the credential being cleared and the flag
being written. Combine the switch and the credential into one derived boolean and let the subsystem
follow it — see `combine-two-flags-to-gate` for the shape and for making both branches idempotent.

**Clear the derived artifacts too, including their expiry stamps.** A cleared session next to a
still-valid cached token is a state no code path expects: the credential check says logged out while
the cached token still works, so behaviour depends on which one a given call happens to read. Clear
the token and the timestamp that describes it in the same write, and treat "session cleared" as
implying "everything minted from that session is void".

**Refresh whatever the UI reads, after the writes.** If the screen's state comes from a snapshot
rather than a live subscription to the stored values, the fan-out is invisible until the screen is
re-entered — which looks exactly like the bug you just fixed. Prefer a subscription; if you must
refresh imperatively, do it last, after every write has landed.

**Enumerate the dependents mechanically, not from memory.** The list is longer than it feels, and
each integration has its own. Grep for the gate before writing the logout, and again afterwards —
and grep for the *withdrawal*, not for the word "logout", because a codebase that models login as a
boolean setting spells its logout `setLoggedIn(false)` and hides it from every verb-shaped search.

## Verifying it

List every logout entry point, then every setting whose enabled-ness is derived from a login state,
then for each gated setting find the logout path that resets it. A logout is frequently not a
verb-named function at all — it is a state setter called with `false`, or a bare credential-clearing
write — so searching for the verb alone inverts the answer, reporting that the integration with the
*most* complete fan-out has no logout entry point whatsoever:

```bash
grep -rnE "fun (logOut|logout|signOut)|clearSession" --include="*.kt" . | grep -v "/build/"
grep -rnE "fun set[A-Za-z]*Log[A-Za-z]*\(" --include="*.kt" . | grep -v "/build/"
grep -rnE "set[A-Za-z]*(Token|Session|Cookie|Credential)\(\s*([a-zA-Z]+ = )?\"\"" \
  --include="*.kt" . | grep -v "/build/"
grep -rn "isEnable = \|enabled = " --include="*.kt" . | grep -v "/build/"
grep -rn "needsReauth\|invalidSession\|reauth" --include="*.kt" . | grep -v "/build/"
```

The first three are one list between them: the verb, the login-state setter, and the write that
actually clears the credential. Read them together, and expect the same logout to appear in two of
them. The last command finds the revocation path. If it returns nothing, your client cannot tell a
dead session from any other error, and the fan-out has exactly one trigger where it needs two.

Behaviourally, for each integration: turn on every sub-switch it offers, log out, and reopen the
settings screen. Every switch must read OFF and be interactive again. Then repeat *without* opening
settings — log out, force-stop, relaunch, go straight to the feature. It must be off. Finally,
revoke the session from the service's own account page while the app runs, exercise the feature, and
confirm the app returns to a logged-out state rather than failing on every call.
