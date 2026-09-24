---
name: follower-item-built-from-shared-payload
description: Build a follower's playable item from the payload the shared session carries, not by re-resolving it from your own catalogue — a local resolver that infers the rendition from artwork shape lands on the wrong one, and a per-item network round trip inside the apply collector wedges every later command behind it. Use when a follower in a synchronised room gets silent video where the source has audio, or when one slow lookup freezes a client's whole command stream.
---

# The payload is the contract; the catalogue is a guess

A shared session carries item ids plus enough display metadata to render a row. It is tempting to
throw that away and re-resolve the item through the same code path the app uses everywhere else —
same models, same helpers, one less special case. Do not. Build the item straight from what arrived:

```kotlin
// adapted — names generalized
private fun SharedTrack.toSessionItem(): GenericMediaItem =
    GenericMediaItem(
        mediaId = id,
        uri = id,
        metadata = GenericMediaMetadata(
            title = title,
            artist = artist.ifBlank { null },          // blank on the wire means absent
            artworkUri = thumbnail.ifBlank { null },
            // Forced, not inferred: every client in a session must be on the same rendition.
            description = MEDIA_KIND.AUDIO,
        ),
        customCacheKey = id,
    )
```

The *stream* is still resolved locally by the component — the session never ships media between
clients, which is exactly why clients on different platforms can share one at all. Only the
description of what to play comes off the wire.

## Traps

**The local resolver decides the rendition by looking at the artwork, and it is wrong here.** The
common shape is a boolean like "square artwork and not one of the wide filenames ⇒ audio". It works
when the item came out of a search result carrying real dimensions. A follower building from a bare
id has no dimensions and falls back to a constructed URL — whose filename is exactly one of the wide
markers — so nearly every item resolves as video.

**And the rendition is not cosmetic: it selects a different source construction.** An item marked as
video is routed to a merged audio+video source, so the follower ends up watching a silent picture
while the source hears plain audio. Two symptoms, one cause, and neither of them points at the
resolver.

**A network round trip inside the apply collector is a queue of one.** The collector applying shared
commands is a single suspending loop. Any per-item lookup inside it — especially one that waits for
a stream to produce non-null data — blocks not just that item but every command behind it. If a
lookup is genuinely needed, launch it outside the collector and let the collector stay a pure
apply.

**The shared id is the item id, the source uri and the cache key — all three.** The component
resolves the stream from that id, so the payload never carries a resolved URL, and it must not: a
resolved URL is per-client, expires, and can carry credentials. Keeping the same id in all three
slots is also what makes every later id comparison work — the last-applied check, the queue diff,
the barrier answer all compare against ids that arrived on the wire.

**Blank is not the same as absent.** Wire formats usually cannot express "no artist", so an unset
field arrives as an empty string. Passing that through renders an empty metadata line rather than
omitting one; map blank to null at the boundary, once, in the builder.

**Filter blank ids and de-duplicate, with the current item first.** A shared queue is assembled by
other clients and can contain both. The current item leads so the follower's queue position matches
everyone else's; duplicates otherwise make the same item appear twice and desynchronise every
subsequent index.

**Clear before adding, every time.** The queue you build from the payload is the follower's *whole*
queue, not an addition to it. Append instead and every rebuild — and rebuilds happen whenever the
shared queue changes behind an unchanged item — leaves the previous copy in place, so the follower
accumulates duplicates and its indices stop matching everyone else's.

**Add the head and the tail through different calls.** Only the head carries the start decision —
see `play-intent-decided-before-load`. An append that re-asserts playback undoes it, and writing
head and tail as one call makes that mistake unavoidable.

**Publishing has its own version of the same problem, and it is a units bug.** The outgoing payload
is built from two different sources depending on what you have: a catalogue row, whose duration is
usually in seconds, and the live component, whose duration is in milliseconds. Two builders, two
units, one field — and the mismatch is invisible on the sending side because nothing there reads it
back. Convert at the builder, and put the unit in the field's name or its comment.

**Pick the same end of the artwork list on both sides.** Payload builders reach into a list of
thumbnails and take one; taking the largest in one builder and the first in another means two
clients render different art for the same item, which looks like a caching bug and is not.

**Do not "unify" this with the normal path later.** It looks like duplication and it is not: the
normal path serves a user who picked something and can afford a lookup; this one serves a collector
that must not block and must not guess. Leave a one-line reason at the builder, or it gets merged
back within a release or two.

## Verifying it

Read every place a rendition is *inferred* rather than stated:

```bash
grep -rn -A8 -E "val is(Song|Video|Audio|Music)\b *=" --include="*.kt" . | grep -v "/build/"
```

A boolean derived from image dimensions, an aspect-ratio comparison or a URL substring is a
heuristic — fine on data that came with real dimensions, wrong on a bare id. Then list the item
builders and check which state the kind outright:

```bash
grep -rnE "fun [A-Za-z.]*to[A-Za-z]*MediaItem\(" --include="*.kt" . | grep -v "/build/"
grep -rnE "description = [A-Z_]+\.[A-Z]+" --include="*.kt" . | grep -v "/build/"
```

The builder used by the apply path must appear in the second list; if it does not, it is inheriting
the heuristic. Finally, prove the apply collector does not suspend on the network:

```bash
for f in $(grep -rlE "toRoomMediaItem|toSessionItem|SharedTrack|RoomTrack" --include="*.kt" . \
             | grep -v "/build/"); do
  echo "== $f"; grep -nE "\.first *\{|\.firstOrNull *\{|await\(|\.collect *\{" "$f"
done
```

Read each hit for what it waits on: `first`/`firstOrNull` over an in-memory collection is harmless;
the same call over a *data flow* is the wedge. `collect` blocks are the collectors themselves — what
must not appear inside one is anything awaiting a remote answer.

Behaviourally, two clients: play an item the follower has never opened, and confirm it gets
**audio**, not a silent picture — invisible if you only check that "something is playing". Then put
the follower on a slow network and issue several commands in a row: they must all land, in order,
not arrive in a burst after the first one resolves.
