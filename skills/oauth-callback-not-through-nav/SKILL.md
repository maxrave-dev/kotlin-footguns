---
name: oauth-callback-not-through-nav
description: Deliver a returning auth callback's token straight to session state and let the login screen close itself by observing the stored session — routing the token through navigation pushes a second login screen and the post-login close peels the wrong one. Use when a browser-based login succeeds but the user is left staring at the login screen.
---

# The callback arrives at the app, not at a screen

A login that hands off to the system browser leaves the app running. The screen the user started
from is *still on the navigation stack* — nothing popped it, because nothing navigated away. When
the browser redirects back, the token arrives at the **process**, through whatever link mechanism
the platform uses (`desktop-deep-link-plumbing` covers getting it that far).

The tempting next move is to route it to the screen that needs it, by navigating to that screen with
the token as an argument. That pushes a **second copy** on top of the first. Login then succeeds,
the screen runs its "close myself" step, and that pops only the copy — landing the user on an
identical login screen with no error and no explanation. It reads as "logged in, but stuck on the
login page", and it gets investigated in the browser, in the redirect, in the service's dashboard —
anywhere but in the back stack, because nothing failed.

Two rules, and they only work together:

```kotlin
// adapted — names generalized: the link handler, at the app's entry point
if (uri.scheme == CALLBACK_SCHEME && uri.host == CALLBACK_HOST) {
    val token = uri.getQueryParameter("token")
    clearPendingLink()
    // Deliberately no navigation: the login screen is almost certainly already open — the browser
    // was opened from it — and navigating would stack a second copy on top of it.
    token?.let { sharedState.completeLogin(it) }
}
```

```kotlin
// adapted — names generalized: the login screen
// Closes on the *stored* session rather than on this screen's own state, because the redirect
// never reaches this screen.
LaunchedEffect(loggedIn) { if (loggedIn) navController.navigateUp() }
```

`loggedIn` is derived from the persisted session record, not from a result the screen was handed.
The screen is a passive observer of a fact stored elsewhere, which is what makes it correct no
matter who completed the login.

## Traps

**The screen may not exist by the time the token comes back.** The user left for a browser; on a
memory-constrained platform the process can be killed and restarted behind them, and the callback
then arrives at a cold app with no login screen anywhere. Anything that assumes "the screen that
started this is still composed" — a callback lambda, a screen-scoped state holder, a suspending
function awaiting a result — is broken for that path. Session state must live above the screen and
survive the trip.

**Screens that embed a web view never hit this, which is why it looks like a one-off.** An in-app
web view keeps the whole flow inside the process, so the screen genuinely does receive the result
and the naive wiring works. The bug only appears on flows that hand off to the *system* browser —
the normal shape on a desktop host, where a real embedded browser is often unavailable. A codebase
with several logins will have the embedded-web-view ones working and the browser-handoff one not,
and the difference is not the service.

**Only one of the two request-token flows ends in a redirect.** Services that mint a request token
usually offer both: either you send the user to the authorization page with *no* token and the
service mints one and redirects to your registered callback, or you fetch the token yourself first
and open the authorization page with it already attached. The second tells the service that your app
already holds the token — so it renders a "you can return to the application now" page and **never
calls your callback**. Choosing it produces a flow that looks entirely healthy up to the last step
and then silently never completes, which is indistinguishable from a broken scheme registration.
Pick the redirect flow whenever you have a registered callback.

**Do not let a link normalizer rewrite the callback.** Apps that canonicalize incoming links into
one internal form will happily rewrite the callback too, and the token reader — which matches on the
original scheme and host — silently stops matching. Exclude the callback shape from the rewrite, and
match it *before* the general link handling, not after.

**Clear the pending link before completing.** Whatever cached the incoming URL for delivery will
replay it on the next composition or the next restore if it is not cleared, re-submitting an
already-spent token and producing a spurious failure toast over a successful login. Clear first,
complete second.

**Assume the token is single-use and short-lived.** It buys exactly one session; the second
exchange fails. That makes every accidental duplicate delivery — a replayed cache, a second
`LaunchedEffect` pass, a re-created screen — visible as a failure *after* a success, which is a
confusing pair of toasts. One delivery point, one exchange.

**Give the user a way in when no handler exists.** On a host with no scheme handler at all the
browser simply lands on the callback URL and shows it in the address bar. A field on the login
screen that accepts that pasted URL and pulls the token out of it reuses the parser you already have
and turns a dead end into a workaround — route it into the *same* completion function, never a
second one.

## Verifying it

Find the callback entry point and confirm nothing between it and the session store navigates:

```bash
grep -rn "getQueryParameter\|\.scheme ==\|\.host ==" --include="*.kt" . | grep -v "/build/"
grep -rn "navigate(" --include="*.kt" . | grep -v "/build/"
```

Then confirm the login screen closes on stored state rather than on a handed-in result:

```bash
grep -rn -A3 "LaunchedEffect(loggedIn)\|LaunchedEffect(isLoggedIn)" --include="*.kt" . | grep -v "/build/"
```

Behaviourally, run the login three ways, because they are three code paths: complete it with the app
still in the foreground; complete it after backgrounding the app long enough for the process to be
killed; and complete it by pasting the callback URL by hand. All three must end on the screen the
user was on *before* the login screen. If any of them lands on a login screen, inspect the back
stack — the failure is a duplicate entry, not the login.
