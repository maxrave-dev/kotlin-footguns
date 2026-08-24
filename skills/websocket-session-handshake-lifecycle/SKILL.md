---
name: websocket-session-handshake-lifecycle
description: The order a WebSocket session has to be brought up and torn down — reader started before the first message because the answer comes back through it, the handshake settled on a deferred with a timeout, the close frame sent under a non-cancellable context, and an event buffer that suspends rather than drops. Use when a socket connects but the session never becomes usable, when a deliberate disconnect leaves the peer thinking you are still there, or when clients drift out of sync after a burst of traffic.
---

# The handshake travels on the socket it is opening

A WebSocket has no request/response shape: the answer to your first message arrives on the same
stream as everything else, through the same reader. So the reader has to exist *before* the message
goes out, and something has to bridge "a frame arrived in the read loop" back to "the caller waiting
for the handshake". A `CompletableDeferred` is that bridge.

```kotlin
// adapted — names generalized; the capability payload, the resume branch and the log lines elided
val live = client.webSocketSession(url)
session = live
val pending = CompletableDeferred<PeerCapabilities>()
handshake = pending
try {
    coroutineScope {
        val reader = launch { readFrames(live) }        // FIRST — it completes `pending`
        send(HELLO, ourCapabilities())
        val caps = withTimeoutOrNull(HANDSHAKE_TIMEOUT) { pending.await() }
            ?: throw IllegalStateException("Handshake timed out after $HANDSHAKE_TIMEOUT")
        onReady(caps)
        val pinger = launch { pingLoop() }
        reader.join()                                    // returns when the socket closes
        pinger.cancel()
    }
} finally {
    handshake = null
    session = null
    withContext(NonCancellable) { runCatching { live.close() } }
}
```

## Traps

**Sending before the reader is running is a deadlock you cannot see.** The peer answers immediately;
with nothing collecting `incoming`, the answer sits in the transport and the `await` runs out. What
the logs show is a socket that opened fine and a timeout afterwards, which reads as a slow peer. The
ordering is the fix and it is one line — but it is also the line a later refactor moves, so say why
it is where it is.

**Bound the handshake, and treat "connected" as the handshake completing rather than the socket
opening.** A peer that accepts the connection and then goes quiet is indistinguishable from a live
one if your readiness flag is `session != null`. Define it as *socket active **and** handshake
completed*, and let the timeout throw so the failure lands on the reconnect path instead of hanging
a coroutine for the life of the process. That readiness definition is also where a retry budget must
refill — see `retry-needs-backoff-and-cap`.

**The close frame is a suspending call, so a cancelled job never sends it.** The deliberate-disconnect
path cancels the connection job and *then* wants a clean close; with an ordinary `finally` the close
aborts at its first suspension point and the peer is left holding a session it thinks is alive, to be
reaped by a read deadline minutes later. `withContext(NonCancellable)` around the close is what makes
the polite path actually polite. Same reasoning for anything else in that `finally` that suspends.

**Let the event buffer suspend; do not give it a dropping overflow policy.** One lost protocol frame
is a silent desync — the state machine simply never learns about a track change and stays confidently
wrong. A generous buffer plus the default suspending behaviour trades a momentarily slower reader for
correctness. Dropping is right for UI notifications and wrong for anything a state machine consumes.

**A `runCatching` in the read loop cannot `continue`.** Kotlin forbids `break`/`continue` inside a
lambda even when it is inlined, so `getOrElse { continue }` does not compile and the tempting fix —
folding the whole body into the lambda — silently changes what happens after a bad frame. Unwrap to a
nullable first, then branch in the loop body. While you are there, skip frames of the wrong kind
explicitly rather than letting them fall into the decoder.

**Capture the resume token as frames pass through, not by asking the layer above.** The token that
makes a drop survivable arrives inside ordinary messages, often before anything upstream has
subscribed. Read it in the frame handler, replay it on the next connection, and drop it on every
path where it is spent: being removed by the peer, giving up on reconnecting, and the user
deliberately leaving. That last one reads as bookkeeping and is not — skip it and the token outlives
the departure, so the next connect resumes instead of joining. Replaying an expired token gets an
error instead of a session, which then looks like the reconnect logic failing.

**A `send` that returns false means *not sent*, and nothing will resend it.** Reconnection replays
the token, not the traffic. Callers have to handle the false — clear the optimistic state they just
set, or surface it — because the alternative is a UI stuck waiting for a reply to a message that
never left. `pending-state-makes-waiting-legible` is the shape for that.

**Clear the session and handshake handles in the same `finally` that closes, not at the next
connect.** Both are what readiness is computed from, so a stale pair reports a healthy connection
over a dead socket: every send is attempted against a closed session, returns false, and the caller
above sees an inexplicable run of "not sent" with no disconnect anywhere. Nulling them at the start
of the *next* connect is too late by exactly the interval nobody is connecting.

**Give the ping loop both jobs and size it against the peer's read deadline.** It is a keepalive
(any inbound message refreshes the peer's deadline, so the interval must sit comfortably under it)
and it is also the sample source for clock calibration, which wants its first few close together
before opening up — see `monotonic-clock-offset-sync`. A send failure in that loop is the earliest
signal the socket is gone; return from it rather than looping on a dead session.

## Verifying it

```bash
grep -rn 'webSocketSession\|install(WebSockets)' --include='*.kt' . | grep -v '/build/'
grep -rn 'NonCancellable' --include='*.kt' . | grep -v '/build/'
grep -rn 'extraBufferCapacity\|onBufferOverflow\|BufferOverflow\.' --include='*.kt' . | grep -v '/build/'
```

The first is the census of socket-owning clients — three lines each, an import, an install and a
construction site — and audit them separately, because these classes get copied. The second lists
every place cancellation is suspended, and the useful reading is the *comparison*: cross off the
clients from the first list, and any that does not appear here closes only by accident, on the paths
where nothing happened to cancel it. Most of this list will be unrelated cleanup elsewhere in the
tree; only the crossing-off matters. Finding just some of the first list's clients here is the
normal result, and every one of them missing is its own finding. The third shows the buffer
declarations: read the capacity, and note that a stream with **no**
`onBufferOverflow` hit is using the default suspending policy, which is the one you want here —
a `BufferOverflow.DROP_*` next to a protocol stream is the desync.

Then exercise the two paths that differ. Point the client at a peer that accepts connections and
never answers (a bare listener will do): the timeout must fire once, the state must not report ready,
and the reconnect path must take over. Then disconnect deliberately while traffic is flowing and
check from the peer's side that a close frame arrived rather than the session lingering until its
read deadline — that is the only observation that distinguishes a correct teardown from one that
merely stopped.
