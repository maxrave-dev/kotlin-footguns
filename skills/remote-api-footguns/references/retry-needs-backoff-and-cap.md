---
name: retry-needs-backoff-and-cap
description: Give every reconnect loop exponential backoff, a ceiling, a class of failures it refuses to retry, and a lifecycle gate — then give the feature a health signal, because one that fails silently stays broken for months. Use when a background connection drains the battery, when a bad credential produces an endless reconnect, or when an integration quietly stopped working.
---

# A retry loop with no brakes is a heater

A connection that retries immediately on every failure is fine while failures are rare and
catastrophic when they are permanent. Hand it a credential the service will never accept and it
becomes: connect, authenticate, get rejected, reconnect — thousands of times an hour, radio awake
throughout, for as long as the app runs. Users report it as heat and battery drain, one of the least
diagnosable bug reports there is, because nothing in the app looks busy.

Four independent brakes, all of which you need:

```kotlin
// adapted — names generalized; teardown, log lines, the close handler's code lookup and its other
// branches elided, and that handler shown taking its code as a parameter
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
gate above it (`combine-two-flags-to-gate`), so withdrawing the credential or turning the feature off
tears down the connection *and* whatever retry was pending, rather than leaving them to discover it.

## Traps

**Distinguish "try again later" from "this will never work".** Backoff alone does not fix a rejected
credential — it only slows the loop down to one attempt a minute, forever. Enumerate the close
reasons or error codes that mean *the credential itself is wrong* (authentication failed, permission
not granted, protocol version refused) and stop on them completely, with a log line saying so. Every
other failure gets the backoff. Getting this set wrong in the safe direction — treating a transient
failure as terminal — costs a reconnect that a user action would have triggered anyway; getting it
wrong the other way is the heater. Keep the terminal set explicit and default everything else to
recoverable: where errors arrive over the same channel as everything else, most codes are about *one
message* (rate limited, malformed payload, unrecognised type) rather than about the connection, and
treating one of those as a connection failure tears down a working session on a single bad send.

**A retry that re-enters the public entry point resets the budget, so the cap can never fire.** The
function the user calls to connect legitimately clears the attempt counter — that is what makes a
deliberate reconnect start fresh. Let the retry scheduler call it too and every attempt clears the
counter, the limit is compared against a number that is always zero, and the loop runs forever while
reading as though it is bounded. Route retries through the *private* start, and say why on the public
one:

```kotlin
// adapted — names generalized
fun connect() {                       // user-initiated: the budget begins again
    reconnectAttempts = 0
    currentDelay = INITIAL_DELAY
    startConnection()                 // the retry path calls THIS, not connect()
}
```

**Reset the delay AND the attempt count on the milestone that means the connection is useful, not on
the socket opening.** For protocols with a handshake, a socket that opens and then fails to
authenticate has achieved nothing — and if the backoff counter resets the moment the socket opens,
the exponential curve never grows and you are back to a fixed-interval loop wearing a backoff's
clothes. Reset where you set "we are ready", which for a handshaking protocol is the ready/resumed
event, not the connect call. Refilling there is also what holds the cap against a peer that accepts
the socket and then goes quiet: it never reaches the milestone, so it never buys itself another
budget. And count attempts rather than elapsed time — a budget in seconds grows with the delay.

**Advance the counter where a cancellation cannot skip it.** The scheduler above stores its job in
the same field the connect path reassigns — so the connect call, from inside the scheduler's own
coroutine, cancels the coroutine it is running in, and the increment survives only because it is not
a suspension point. One refactor from a loop that never backs off: increment *before* the attempt, or
keep the retry state in a field the attempt path does not touch.

**A retry that never gives up forces every waiter to be bounded — and vice versa.** Once you adopt
"some failures are terminal", any code that waits for readiness may wait forever, so it needs a
timeout rather than a spin-wait. A bounded waiter with an unbounded retry loop hides the problem; an
unbounded waiter with a bounded retry policy hangs a coroutine for the life of the process.

```kotlin
// adapted — names generalized
val ready = withTimeoutOrNull(READY_TIMEOUT) {
    while (!isConnectedAndAuthenticated()) delay(100.milliseconds)
    true
} ?: false
if (!ready) { Logger.w(TAG, "Not connected within timeout — dropping update"); return }
```

**Gate the connection on the app actually doing the thing it reports.** A connection that only
mirrors live activity has no reason to exist while nothing is happening; closing it when the activity
stops and reopening it when it resumes removes the entire idle retry surface, because an idle app
holds no socket to lose. The cheapest brake, and the one most often skipped — it "works" without it.

**A feature that fails silently stays broken for months.** Recorded independently from a second
integration in the source project's mining notes: a dependency went away, the feature it fed simply
stopped producing output with no error anywhere, and a user found it before the project did. Any
feature whose failure mode is *does nothing* needs an explicit signal where a human looks — a warning
log at the moment of the drop with the reason in it, a visible state in the settings entry that owns
the feature, or both. Silence is not evidence that the retry policy is working.

## Verifying it

Find the retry sites first — a delay whose argument is a variable rather than a literal, plus the
explicit retry vocabulary — then ask each site for its ceiling:

```bash
grep -rnE "delay\([a-zA-Z_][A-Za-z0-9_]*\)|reconnect|maxRetries|attempt(s)?\+\+|Result\.retry" \
  --include="*.kt" . | grep -v "/build/"
grep -n "coerceAtMost\|coerceIn\|MAX_\|maxAttempts\|withTimeout" <each-file-from-the-first-list>
```

Those are two disjoint vocabularies, so do not compare them as sets — run the second one per file.
Read the enclosing function of each hit and confirm a ceiling or a `withTimeout*` applies to it, and
check what the retry path *calls*: a call to the public connect function is the budget-reset defect.
A file with retry hits and no ceiling hit is the one to read next; a constant `delay(` argument in a
retry path is the defect. A bare `delay(` sweep is not this list — it collects animation waits, poll
intervals and settle delays that never retry anything.

Then exercise the four failure classes — four separate code paths — and watch the log:

- **Transient** — take the network away. Attempts must space out visibly and stop growing at the
  cap, not stay at one per second.
- **Terminal** — supply a credential the service rejects. Exactly one attempt, one log line naming
  the reason, then nothing. A repeating log means that code is missing from your terminal set.
- **Exhaustion** — leave the network away past the cap. The attempts must *stop* and the user must
  be told; a loop that never announces giving up is the budget-reset defect.
- **Recovery** — restore the network after several backed-off attempts. The next successful
  connection must reset the delay: the *following* failure waits the initial interval, not the cap.

Then leave the app idle for minutes on each — any periodic line is a retry loop you did not gate.
