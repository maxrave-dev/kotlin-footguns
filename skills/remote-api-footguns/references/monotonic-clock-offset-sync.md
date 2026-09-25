---
name: monotonic-clock-offset-sync
description: Estimate a peer's clock offset from ping/pong round trips — take the peer's own processing time out before halving, weight each sample against the best round trip seen, insist the local time source is monotonic, and fall back to the uncorrected value while the estimate is not yet usable. Use when several devices must agree what time it is before they can agree where a stream is, when a group drifts apart on a congested network, or when a position correction jumps after the device adjusts its clock.
---

# Two clocks, one offset, estimated from round trips

Every device in a synchronised room runs its own clock with its own drift, so "resume at 1234"
means nothing until both ends agree what time it is. A pong that carries back the client's send
time plus the peer's own receive and send times has everything needed to estimate one-way latency,
and from that the offset between the two clocks:

```kotlin
// adapted — names generalized; the lock, the sample-validity checks and the accessors are elided
val receivedAt = elapsedRealtime()                       // MONOTONIC, injected by the caller
val roundTrip = receivedAt - clientTime
val peerProcessing = peerSendTime - peerReceiveTime
// Time the peer spent thinking is not time on the wire, so it comes out before the halving.
val networkRoundTrip = max(0L, roundTrip - peerProcessing)
val sampleOffset = peerSendTime + networkRoundTrip / 2.0 - receivedAt

if (networkRoundTrip < bestRoundTripMs) bestRoundTripMs = networkRoundTrip
val weight = if (networkRoundTrip <= bestRoundTripMs + GOOD_SAMPLE_MARGIN_MS) 0.25 else 0.05
offsetMs = offsetMs?.let { it + weight * (sampleOffset - it) } ?: sampleOffset
```

`offsetMs` is nullable and that nullability is the feature: everything downstream has to say what it
does when the clock has not been calibrated yet.

## Traps

**Halving the whole round trip charges the peer's think-time to the network.** A relay that queues
a frame for 40 ms adds 40 ms to the measured round trip; halve that and the one-way estimate is
20 ms too large, permanently, on every sample the peer is slow to answer. The peer's receive and
send times are in the message precisely so the difference can be removed first. If the peer does not
report both, you cannot subtract it — and you should treat the resulting offset as a floor rather
than pretending it is exact.

**The local source must be monotonic, and it must be injected rather than read.** An offset is a
difference between two readings of the same local clock; a wall clock that a network time correction
steps backwards makes that difference meaningless and the derived position jump. Take the source as
a constructor parameter — `() -> Long` — so each platform passes its own and a test passes a
variable it controls. Reading a wall clock directly inside the estimator also makes it untestable,
which is how a wrong formula survives.

**"Not calibrated yet" must fall back to the raw value, never to a guess.** Each accessor answers
the uncalibrated case explicitly: the "what time is it" accessor returns null, and the position
correction returns its input unchanged. A wrong seek is worse than a slightly late one — a listener
notices a jump instantly and does not notice a 200 ms lag at all. The same rule covers a peer that
sends 0 for its timestamp: 0 means *unknown*, so it must short-circuit to the raw position, not run
through the arithmetic where it becomes "however long ago the epoch was".

**Weighted, not averaged — which is why the first pings must come in a burst.** A flat mean lets one
congested frame drag the whole room; weighting each sample by how close its round trip is to the
best seen (0.25 when it is good, 0.05 when it is not) keeps a bad frame at the noise level. The cost
is that the estimate moves slowly: the first sample *sets* the offset outright and every later one
shifts it by at most a quarter. So the ping loop has to send its first few close together and only
then open up to its steady interval, or someone joining in the first seconds seeks against an
estimate built from one sample.

**Reject a sample before folding it in, not after.** Five cheap checks pay for themselves: a
non-positive send time, a send time in the local future, a sample older than a cap, a peer whose
send time precedes its own receive time, and a peer *receive* time of zero. That last one is the
guard tests forget, and it has the nastiest tail: unguarded, the peer's think-time becomes its whole
send time, the network round trip collapses to zero, the best-seen baseline pins itself there for
the life of the session, and every later sample is weighted down to noise. The other four produce an
offset wrong by minutes, and once folded in it stays — the weighting that protects against noise
also means a poisoned estimate takes many good samples to walk back.

**Make "the clock became usable" an event.** The fold returns true only for the *first* accepted
sample. That boolean is what lets the layer above announce that corrected positions are now
available, and it exists because there is otherwise no way to distinguish "offset is zero" from "no
offset yet" once the value has been unwrapped. Callers that need the distinction must read the
nullable value, not a defaulted one.

**The formula is a contract between peers, so its test numbers are copied, not recomputed.** Every
client in the room has to derive the same position from the same message; an arithmetic cleanup that
shifts the result by a few milliseconds is a desync, not a refactor. Pin the expected values as
literals taken from the reference implementation and say in the test why they may not be
"simplified". Related: `position-based-group-sync` is what consumes this offset, and
`borrowed-wire-protocol-discipline` is the same rule applied to the message shapes.

## Verifying it

The estimator is small and its correctness is mostly about which clock feeds it, so check the clock
sources across the tree rather than reading the arithmetic again:

```bash
grep -rnE 'TimeSource\.Monotonic|elapsedRealtime' --include='*.kt' . | grep -v '/build/'
grep -rn 'currentTimeMillis()\|Clock\.System\.now()' --include='*.kt' . | grep -v '/build/' | cut -d: -f1 | sort -u
grep -rnE 'roundTrip|RoundTrip|[Oo]ffset[Mm]s' --include='*.kt' . | grep -v '/build/'
```

The first is the monotonic census: expect the injected source, its default anchored at a process-start
mark, the ping that stamps its own send time, and the test substituting a plain variable — all in the
sync module, plus any monotonic anchor elsewhere that is not feeding the estimator at all. Those are
legitimate and the third command is what tells them apart: a file that takes a mark but never shows
up in the arithmetic census is not a second estimator. The second lists *files* holding a wall clock; the two lists must be disjoint, and a file
appearing in both is the defect this skill exists for. The third collects the arithmetic itself: count
the hits per file and expect one file to hold effectively all of them. The stray matches — an
`*OffsetMs` field on some response model, a test named `…RoundTrip…` — are noise, not a second
estimator; a *second* file with the arithmetic in it is the thing to worry about, because two copies
of this formula drift.

Then read the test file rather than trusting the code comments: it should assert a `null` reading
*before* any sample, an exact wall time after one, an unchanged position while the stream is not
running, and an unchanged position after a reset. If a test only asserts that the offset is "close
to" something, it cannot catch the halving mistake at the top of the traps, which is worth exactly
half the peer's queueing delay and nothing else.
