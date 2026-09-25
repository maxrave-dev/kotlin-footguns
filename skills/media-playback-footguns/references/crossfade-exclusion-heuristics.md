---
name: crossfade-exclusion-heuristics
description: Decide when a crossfade must NOT run — the item plays as video, the item is too short for the fade, or two consecutive items belong to the same album — and encode each rule so it survives shuffle, an auto-length fade and a queue that keeps growing. Use when a fade cuts a song short, a video jumps to its first frame under the previous track, a 25-second interlude spends half its length fading, or an album sequenced to run continuously is interrupted between every track.
---

# Crossfade exclusions

A crossfade is a default, not a law. Three exclusions earn their place; each is a small
predicate consulted at the trigger point, and each has a way of being written that quietly
does nothing.

```kotlin
val shouldCrossfade =
    crossfadeEnabled && hasNextMediaItem() &&
        !isCurrentTrackVideo() && !isNextTrackVideo() &&
        !isCurrentTrackTooShortForCrossfade() && !isWithinAlbum()
```

Every one of these must also be present on the *other* path that starts a fade — see
`guard-on-every-trigger-path`; a predicate on one path only is dead code with no symptom.

## Traps

**The video check has to be symmetric, and it has to honour the user's setting.** Two
separate rules, both needed:

```kotlin
private fun isNextTrackVideo()    = watchVideoEnabled && next()?.isVideo() == true
private fun isCurrentTrackVideo() = watchVideoEnabled && currentMediaItem?.isVideo() == true
```

The *next* check exists because a video source is expensive and error-prone to prepare in
the middle of a fade, and because a video should start from its first frame rather than
fade in under the outgoing song. The *current* check exists because a video should play out
to its last frame rather than fade out under the incoming one. The current-track half is
the one that gets deleted: an early version tested only "is this item a video?" and ignored
whether the user had video playback switched on at all, so it suppressed fades for
audio-only listeners. The fix is to make it symmetric with the next-track check, not to
remove it. `watchVideoEnabled &&` is doing the real work in both.

**A fixed minimum length is wrong at both ends of the fade-length range.** The bar must
scale with the fade:

```kotlin
private const val MIN_CROSSFADE_TRACK_MS = 20_000L
return duration < maxOf(MIN_CROSSFADE_TRACK_MS, fadeMs * 3L)
```

At a 5 s fade a 20 s interlude would spend half its length fading; at a 15 s fade it is
swallowed whole. `3×` keeps at least a third of any item playing unblended, and the floor
keeps short fades from letting 10-second items through.

**An auto-length fade must feed the bar, not the default.** When the fade duration is a
setting that can be "Auto", the bar must be computed from the *resolved* value:

```kotlin
val fadeMs =
    if (crossfadeDurationMs == CROSSFADE_DURATION_AUTO)
        resolveAutoCrossfadeDurationMs(currentId, nextId)   // here: 20_000..45_000
    else crossfadeDurationMs
```

Measuring against the 5 s default instead lets a 30 s item pass the bar and then blends it
for 30 s. Do not hardcode the auto range into this check — read it from the same resolver
the ramp uses, so the two cannot drift.

**Only the current item can be measured.** The next item has not been prepared, so its
duration is unknown until it becomes current. A check that tries to read the next item's
duration gets `0` or `-1` and must not treat that as "short" — guard with
`if (duration <= 0L) return false`.

**Album membership is a set of ids, never a count or a range.** "The next N items are the
album" breaks the moment shuffle reorders the queue — and shuffle reorders appended items
too, so position tells you nothing:

```kotlin
private fun isWithinAlbum(): Boolean {
    if (!skipCrossfadeInAlbum) return false
    val ids = albumTrackIds
    if (ids.isEmpty()) return false
    val current = currentMediaItem?.mediaId ?: return false
    val next = next()?.mediaId ?: return false
    return current in ids && next in ids            // BOTH sides
}
```

**Requiring both sides is what keeps the album's edges alive.** Testing only the current
item would suppress the fade from the last album track into whatever an endless queue
appended next — exactly the transition a listener most wants blended. Both-in-set means
inside the album is untouched and the boundaries still fade.

**The snapshot stays album-only only because appends bypass the setter.** The set is
written once, when the album is loaded. It survives because the code paths that append
more items write the queue list directly instead of going through the setter that would
rebuild the snapshot. Routing those appends through the setter — an innocent-looking
cleanup — swallows every appended item into the set and disables the fade for the whole
queue. If you consolidate queue writes, re-check this.

**Recognising an album needs a queue-type tag, and the tag may not survive a restart.**
Tagging a queue as an album must not change anything else: an album behaves exactly like a
playlist for play, ordering and navigation. In particular do not apply it on the *shuffle*
entry point — once shuffled the sequencing the exclusion protects is already gone. And if
the persisted queue record has no column for the type, a restored queue comes back as a
plain playlist and the exclusion silently stops applying. Either add the column or document
the limitation; do not infer the type from the items.

**Ship the album rule off by default.** Video and short-track are correctness rules — they
prevent an audibly broken transition. Album continuity is taste: some listeners want every
transition blended. Default it off and let the setting turn it on.

## Verifying it

- Log, at the trigger point, one line with: resolved fade length, current item duration,
  both video flags, and whether both ids are in the album set. Every skipped fade should be
  explainable from that line alone.
- Check the bar by playing an item just under and just over `max(20 s, 3 × fade)` — then
  change the fade setting and confirm the boundary moved with it.
- Check the album rule by shuffling an album with an endless queue appended: interior
  transitions unblended, the transition out of the album blended.
- Check the video rule with video playback both on and off; with it off, fades must happen
  normally even on items the source labels as video.
