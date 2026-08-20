---
name: merge-split-av-streams-desktop
description: Playing a separate audio-only stream and video-only stream as ONE source on JVM desktop through the media engine's edit-list URL form — the desktop counterpart of a merging media source — including length-prefixed quoting of stream URLs and why a merged two-URL item must not be prepared in the middle of a crossfade. Reach for it when desktop video plays back completely silent with nothing in the log, when a stream URL is truncated at the first semicolon, or when fading into a video track cuts the outgoing song short.
---

# Merging split audio and video streams on desktop

Adaptive sources hand out audio and video as **separate URLs**. On Android the player library has a
merging media source for exactly this; a C media engine embedded in a JVM desktop app usually has
an equivalent, in the form of an **inline edit-list URL** that names several streams and plays them
simultaneously. "av" here is audio/video.

The important property: the result is still **one source**, so it is one handle. Transport,
position reporting and release are unchanged — there is no second handle to keep in sync.

## The URL shape

Each entry is preceded by a header saying "this is a new *simultaneous* stream" rather than the
next item in a sequence, and every URL is length-quoted:

```kotlin
// adapted — renamed from the source implementation
internal fun buildMergeUrl(videoUrl: String, audioUrl: String): String =
    listOf(videoUrl, audioUrl).joinToString(separator = ";", prefix = "edl://") { url ->
        "!new_stream;${quote(url)}"
    }

/** Length-prefixed quoting: %<len>%<value>. len counts BYTES, not characters. */
internal fun quote(value: String): String =
    "%${value.toByteArray(Charsets.UTF_8).size}%$value"
```

Verify the exact grammar against **your** engine's edit-list documentation before copying this —
the header keyword, the separator and the quoting form are all engine-specific. Two things worth
checking there specifically: whether the header must be first in its entry, and whether the URI
form drops the header line the file form requires.

## Traps

**Length-quoting is mandatory, and the length is in bytes.** Edit-list formats reserve characters
like `,` `;` `!` inside values, and real stream URLs carry `;` and `,` in their query strings — an
unquoted URL is truncated at the first one, so whatever failure follows points at a fragment you
never wrote. The reference implementations of this quoting count **bytes**; the JVM's `String.length`
counts UTF-16 units, so measure the UTF-8 encoding or every non-ASCII URL is quoted with a wrong
length.

**Copy only the documented core headers.** An engine's own resolution script often prefixes extra
headers to each entry. If its documentation says those exist to serve that script's internal needs,
are not part of the core format, and may change at any time, do not copy them. In the case this
was mined from, the clipping header was provably a no-op for whole-file entries with no declared
length; the chapter header was kept in reserve as the documented targeted fix should stray chapter
markers ever show up. Add a header back for a symptom, not for completeness.

**A video-only stream carries no audio — merging it back is not optional.** If you stop asking your
resolver for a pre-muxed single URL, what you get is a genuine video-only stream, and playing it
alone gives silent video **with nothing in the log to say why**. Every branch that returns a video
source must also fetch the audio URL and attach it:

```kotlin
// adapted — lifted from its enclosing watch-video branch
val videoUrl = resolver.getStream(id, isVideo = true).lastOrNull()
if (videoUrl != null) {
    // The stream above is video-ONLY: fetch the audio separately and merge it back.
    val audioUrl = resolver.getStream(id, isVideo = false).lastOrNull()
    return PlayableSource(isVideo = true, url = videoUrl, audioSlaveUrl = audioUrl)
}
```

**Know what asking for "muxed" changes in your own resolver.** The pre-muxed path is tempting
because it is one URL, but it commonly returns the *same* manifest URL as both the audio and the
video answer — so the engine opens one manifest twice — and it takes away the per-track quality
choice. Check the resolver body rather than assuming: here the muxed flag was also passed straight
through as an "anonymous request" flag, silently dropping the signed-in session for that call.
That kind of coupling does not appear in the function's signature.

**Keep the merge decision in one place, and let audio-only sources never carry a second URL.**
One helper turns a resolved source into the single URL handed to the load call:

```kotlin
private fun buildPlaybackUrl(source: PlayableSource): String {
    val audioSlave = source.audioSlaveUrl
    return if (audioSlave != null) buildMergeUrl(source.url, audioSlave) else source.url
}
```

Because an audio-only source never gets a second URL, audio playback can never accidentally open a
video stream — a property worth preserving when you extend the resolver.

**Do not prepare a merged source in the middle of a transition.** A crossfade has to resolve two
stream URLs and build a filter graph while another handle is still fading; doing that for a merged
two-URL source was error-prone enough that it cut the outgoing song short or jumped straight to
the video's first moment. A video also *should* start at its first frame rather than fade in under
the previous song, and should play out to its last frame rather than fade out under the next one —
so both sides get a check, and such transitions take the plain non-crossfade path:

```kotlin
private fun isNextTrackVideo(): Boolean =
    watchVideoEnabled && playlist.getOrNull(nextIndex())?.isVideo() == true

private fun isCurrentTrackVideo(): Boolean =
    watchVideoEnabled && currentMediaItem?.isVideo() == true
```

Note both read the **setting** as well as the item: an item that merely *can* play as video is not
a video track when the user has that setting off, and the condition must match the one your
resolver uses to decide whether to include the video stream at all. A check written against the
item alone disables crossfade for content that is playing as pure audio.

**Put the guard on every path that starts a transition.** A crossfade is typically started from two
places — a position poll and an end-of-file handler — and the end-of-file handler usually returns
early when a transition is already running. A guard added only there is code that never runs, with
no symptom to notice: the feature silently keeps doing the thing you just "fixed". Find them all
before editing:

```bash
grep -rn 'isCrossfading\|shouldCrossfade\|triggerCrossfade' --include='*.kt' <media-module>/
```
