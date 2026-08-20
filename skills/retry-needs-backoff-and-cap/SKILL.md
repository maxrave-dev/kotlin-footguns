---
name: retry-needs-backoff-and-cap
description: Give every reconnect loop exponential backoff, a ceiling, a class of failures it refuses to retry, and a lifecycle gate — then give the feature a health signal, because one that fails silently stays broken for months. Use when a background connection drains the battery, when a bad credential produces an endless reconnect, or when an integration quietly stopped working.
---

# A retry loop with no brakes is a heater

A connection that retries immediately on every failure is fine while failures are rare and
catastrophic when they are permanent. Hand it a credential the service will never accept and it
becomes: connect, authenticate, get rejected, reconnect — thousands of times an hour, radio awake
throughout, for as long as the app is running. Users report it as heat and battery drain, which is
one of the least diagnosable bug reports there is, because nothing in the app looks busy.

Four independent brakes, all of which you need:

```kotlin
// adapted — names generalized; the scheduler's teardown and log lines elided, and the close handler
// shown taking its code as a parameter, with its own teardown, code lookup and other branches elided
private var currentDelay = INITIAL_DELAY

private fun scheduleReconnection() {
    if (reconnectJob?.isActive == true) return     // 1. never stack two schedulers
    reconnectJob = launch {
        delay(currentDelay)
        connect()
        currentDelay = (currentDelay * 2).coerceAtMost(MAX_DELAY)   // 2. exponential, capped
    }
}

private suspend fun handleClose(code: Int) = when (code) {
    in CREDENTIAL_REJECTED_CODES ->                // 3. some failures are not retryable at all
        Logger.e(TAG, "Closed with non-recoverable code $code — not reconnecting.")
    else -> scheduleReconnection()
}
```

The fourth brake is not in the connection at all: the whole subsystem is created and destroyed by a
gate above it (`combine-two-flags-to-gate`), so withdrawing the credential or turning the feature
off tears down the connection *and* whatever retry was pending, rather than leaving them to discover
it.

## Traps

**Distinguish "try again later" from "this will never work".** Backoff alone does not fix a rejected
credential — it only slows the loop down to one attempt a minute, forever. Enumerate the close
reasons or error codes that mean *the credential itself is wrong* (authentication failed, permission
not granted, protocol version refused) and stop on them completely, with a log line saying so. Every
other failure gets the backoff. Getting this set wrong in the safe direction — treating a transient
failure as terminal — costs a reconnect that a user action would have triggered anyway; getting it
wrong the other way is the heater.

**Reset the delay on the milestone that means the connection is useful, not on the socket opening.**
For protocols with a handshake, a socket that opens and then fails to authenticate has achieved
nothing — and if the backoff counter resets the moment the socket opens, the exponential curve never
grows and you are back to a fixed-interval loop wearing a backoff's clothes. Reset where you set
"we are ready", which for a handshaking protocol is the ready/resumed event, not the connect call.

**Advance the counter where a cancellation cannot skip it.** The scheduler above stores its job in
the same field the connect path reassigns — so the connect call, from inside the scheduler's own
coroutine, cancels the coroutine it is running in. The increment survives only because it is not a
suspension point. That is one refactor away from a loop that never backs off; increment *before* the
attempt, or keep the retry state in a field the attempt path does not touch.

**A retry that never gives up forces every waiter to be bounded — and vice versa.** Once you adopt
"some failures are terminal", any code that waits for readiness may wait forever, so it needs a
timeout rather than a spin-wait. The two decisions are a pair: a bounded waiter with an unbounded
retry loop hides the problem, and an unbounded waiter with a bounded retry policy hangs a coroutine
for the life of the process.

```kotlin
// adapted — names generalized
val ready = withTimeoutOrNull(READY_TIMEOUT) {
    while (!isConnectedAndAuthenticated()) delay(100.milliseconds)
    true
} ?: false
if (!ready) { Logger.w(TAG, "Not connected within timeout — dropping update"); return }
```

**Gate the connection on the app actually doing the thing it reports.** A connection whose only job
is to mirror live activity has no reason to exist while nothing is happening. Closing it when the
activity stops — and opening it again when it resumes — removes the entire idle retry surface,
because an idle app holds no socket to lose. This is the cheapest of the four brakes and the one
most often skipped, since the connection "works" without it.

**A feature that fails silently stays broken for months.** This is the recurring lesson, recorded
independently from a second integration in the source project's mining notes: a dependency went away
and the feature it fed simply stopped producing output, with no error anywhere, and the failure was
found by a user rather than by the project. Any feature whose failure mode is *does nothing* needs
an explicit signal somewhere a human looks — a warning log at the moment of the drop with the reason
in it, a visible state in the settings entry that owns the feature, or both. Silence is not evidence
that the retry policy is working.

## Verifying it

Find the retry sites first — a delay whose argument is a variable rather than a literal, plus the
explicit retry vocabulary — then ask each site for its ceiling:

```bash
grep -rnE "delay\([a-zA-Z_][A-Za-z0-9_]*\)|reconnect|maxRetries|attempt(s)?\+\+|Result\.retry" \
  --include="*.kt" . | grep -v "/build/"
grep -n "coerceAtMost\|coerceIn\|MAX_\|maxAttempts\|withTimeout" <each-file-from-the-first-list>
```

Those are two disjoint vocabularies, so do not compare them as sets — run the second one per file.
Read the enclosing function of each hit and confirm a ceiling or a `withTimeout*` applies to it. A
file with retry hits and no ceiling hit anywhere is the one to read next; a constant `delay(`
argument in a retry path is the defect. A tree-wide sweep for bare `delay(` is not this list — it
collects animation waits, poll intervals and settle delays that never retry anything.

Then exercise the three failure classes, which are three separate code paths, and watch the log:

- **Transient** — take the network away. Attempts must space out visibly and stop growing at the
  cap, not stay at one per second.
- **Terminal** — supply a credential the service rejects. There must be exactly one attempt, one
  log line naming the reason, and then nothing at all. If the log keeps repeating, the rejection
  code is missing from your terminal set.
- **Recovery** — restore the network after several backed-off attempts. The next successful
  connection must reset the delay: the *following* failure should wait the initial interval again,
  not the capped one.

Leave the app idle for several minutes on each and confirm the log goes quiet. Any periodic line
while idle is a retry loop you did not gate.
