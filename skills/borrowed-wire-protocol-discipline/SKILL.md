---
name: borrowed-wire-protocol-discipline
description: Rules for implementing a protocol someone else defined — no renaming, no reordering, constants the schema omits read off the counterpart implementation rather than guessed, unknown message types decoded to null instead of thrown, and negotiated capabilities narrowed but never widened. Use when your client must interoperate with an implementation you do not control, when a connection opens and then never gets anywhere, or when a peer on a newer version breaks your session.
---

# A protocol you did not author is not yours to improve

Interoperating with someone else's implementation inverts the usual instincts. The names are not
descriptive enough, the numbering has gaps, half the messages are ones you draw no UI for — and
every one of those is load-bearing. A renamed field or a reordered number is not a refactor; it is a
client that connects successfully and silently cannot join anything.

Write that down where the schema lives, because it is the only defence against a well-meant cleanup:

```kotlin
/*
 * Source of truth: <the schema you are implementing>. Every field number below is that file's
 * number and every constant is its string spelled exactly. NOTHING here may be "improved": a
 * renamed field or a reordered number is a client that silently cannot join.
 */
```

## Traps

**The constants the schema does not state are the ones that will cost you a day.** A schema
describes message *shapes*; it frequently does not name the envelope type strings that carry them,
the ordering requirements, or the size thresholds. Those live only in the counterpart's source. Read
them there and cite the file and symbol you read them from in a comment — a guessed type string is
answered with an "unknown message type" error, so the socket stays open, frames keep flowing, and
the handshake simply never completes. That failure looks like a network problem and is not one.

**Decode an unrecognised message type to null instead of throwing.** The other implementation will
ship new types before you do. A client that dies on an unknown frame cannot share a session with a
newer peer, and the failure arrives as "it worked until someone updated". The dispatch's `else`
branch returns null, the layer above forwards the type with a null payload, and nothing breaks.

**Parse message types you have no feature for.** A text-message frame in a client with no such UI still
has to travel through the codec without disturbing the stream, because a peer running the fuller
implementation *will* send one. "We don't support that feature" is a UI decision; it is not
permission to reject the bytes.

**Narrow a negotiated capability, never widen it.** When the handshake says the peer cannot do
something, turn it off locally. When it says the peer *can*, that is not an instruction to turn it
on — your own thresholds and your own reasons still apply, and a capability you enable on the
strength of the peer's claim is one you have no fallback for. One directional branch, no `else`:

```kotlin
// adapted — the capability is a placeholder
if (!peerCaps.supportsCompression) {
    Logger.w(TAG, "Peer reports no compression support — sending uncompressed")
    codec = MessageCodec(compressionEnabled = false)
}
```

**Split the peer's errors into "about this message" and "about this connection" before reacting to
either.** They arrive on the same channel and look identical. A rate-limit or a malformed-payload
error concerns one frame; treating it as a connection failure tears down a working session and, if
it feeds a retry policy, burns the whole budget on a single bad send. A refusal of the client
itself — an unsupported version, a rejected credential — is the opposite: retrying repeats it
forever. Keep an explicit set of the non-recoverable codes and default everything else to
recoverable, because the peer will add codes you have never seen.

**Do not surface every peer error to the user, either.** An error the user cannot act on — a
rate-limit on a background message — becomes an alarming banner about nothing. Filter at the state
machine, log the rest.

**Field numbers and type strings are the contract, so pin them in tests rather than trusting
review.** A test that asserts the literal string of each handshake type, and one that asserts the
raw tag bytes of the envelope, converts the entire class of "someone tidied the schema" into a build
failure. Without them the first symptom is a user saying they cannot connect, and the change that
caused it looks harmless in a diff. `protobuf-without-codegen-kmp` covers the byte-level half of
this; `api-ok-but-ignored` is the neighbouring lesson that a successful-looking response is not
proof of acceptance.

**Keep the borrowed types behind a module boundary from the first commit.** Because they are
ordinary classes, they spread like ordinary classes — and once a screen imports one, the "nothing
here may be improved" rule has to hold in a file nobody reads it in. `response-to-domain-flow` is
the placement discipline.

## Verifying it

The discipline is mostly about *where* strings live, which greps answer well:

```bash
grep -rnE 'const val [A-Z0-9_]+ = "[a-z][a-z0-9_]*"' --include='*.kt' . | grep -v '/build/' | cut -d: -f1 | sort | uniq -c | sort -rn | head
grep -rnE '[=!]= "[a-z][a-z0-9]*_[a-z0-9_]+"|setOf\("[a-z][a-z0-9]*_[a-z0-9_]+"' --include='*.kt' . | grep -v '/build/'
grep -rnE 'supports[A-Z][A-Za-z]*' --include='*.kt' . | grep -v '/build/' | grep -v Test
```

The first ranks files by how many lowercase wire literals they declare; the protocol's constants
object should tower over everything else in that list, and a second file with a handful of them is
either an unrelated preference key set or the beginning of a duplicate vocabulary. The second is the
sharper check: it finds wire strings **compared inline** rather than referenced by name. Expect a
small number of hits and read every one — in practice message types get constants while *error
codes* stay inline literals in whichever file reacts to them, which is exactly the population that
drifts apart between the send side and the receive side. The third shows the negotiation mixed in
with every unrelated capability predicate in the tree — range support on an HTTP client, a loader's
mime-type override, a query parameter — because that pattern is ordinary English rather than
protocol vocabulary. Read only the hits within reach of the handshake: each of *those* should be a
schema field or a narrowing branch, and a handshake branch that enables something because the peer
supports it is the widening mistake. The rest look identical and are correct code.

Then read the schema file top to bottom once and check that every constant not present in the
published schema carries a comment naming where it was read from. A constant with no provenance is a
guess, and a guess in this file is the failure that presents as a connection that opens and does
nothing.
