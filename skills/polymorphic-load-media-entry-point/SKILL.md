---
name: polymorphic-load-media-entry-point
description: One generic "load this item and start playing" function normalizes several item types into a single internal shape, routes the queue-seeding strategy off a discriminator, and gates every pre-enqueue policy at that one place. Use when playback can start from many screens and a rule (content filter, dedup, analytics, resume-without-autoplay) keeps getting forgotten on one of the paths.
---

# Polymorphic load-media entry point

Playback starts from a lot of places: a search row, a library row, a playlist, an album, a shared
link, a restored session. Each has its own item type and its own idea of what should be queued next.
Given one entry point per caller, any policy that must hold for *all* of them will be missing from
at least one.

Collapse them into a single function with two parameters that do the varying:

```kotlin
suspend fun <T> loadMediaItem(anyTrack: T, type: String, index: Int? = null) {
    val track = when (anyTrack) {
        is Track -> anyTrack
        is SongEntity -> anyTrack.toTrack()
        else -> return                       // unknown type: do nothing, touch nothing
    }
    // --- pre-enqueue policy: everything below this line assumes the item is allowed to play
    if (track.isExplicit && !settings.explicitContentEnabled()) { showToast(Explicit); return }
    songRepository.insertSong(track.toSongEntity())
    clearMediaItems()
    addMediaItem(track.toGenericMediaItem(), playWhenReady = type != RECOVER_TRACK_QUEUE)
    when (type) {
        SONG_CLICK, VIDEO_CLICK, SHARE       -> getRelated(track.trackId)   // seed from one item
        PLAYLIST_CLICK, ALBUM_CLICK, RADIO_CLICK -> loadPlaylistOrAlbum(index)
    }
}
```

The generic parameter normalizes **content**; the `type` discriminator routes **strategy**. They are
deliberately separate: two callers can pass the same item type and want different queues.

## Traps

**Policy gates must sit before the first player mutation, not after.** Order is the whole point:
the content check returns *before* `clearMediaItems()`, so a blocked item leaves whatever is playing
untouched. Put the gate one line later and a rejected tap stops the music and shows a message — the
user loses their session to a rule that was supposed to change nothing.

**Every side effect that must happen "whenever a track starts" belongs here, and only here.**
Recording the item locally, back-filling its duration, dedup against what is already queued: each of
those, added at a call site, is a rule that holds on the screens someone remembered. Verify by
counting callers — the function should have many, and no caller should reach the player directly:

```
grep -rn "loadMediaItem(" --include='*.kt' .    # should list every playback origin
# in your UI module, nothing should reach the player directly — narrow the pattern to the
# player receiver so the handler's own delegating calls do not count as hits:
grep -rn "player\.addMediaItem(\|player\.setMediaItem(" --include='*.kt' <ui-module>/
```

(Quote the `--include` glob — unquoted, some shells expand it against the working directory and the
command fails before it searches anything.)

**The type normalization needs a real `else` that does nothing.** `else -> return` is not laziness;
it is the only correct answer for a caller that passed something the handler cannot represent.
Throwing turns a caller mistake into a stopped app, and a default of "treat it as a bare track" ships
an item with empty metadata into the queue.

**A `String` discriminator has no exhaustiveness, and the failure is silent.** A typo, or a new
origin added without a branch, falls through the `when` — the first item is enqueued and plays, and
the queue never fills, which reads as "the radio is broken" rather than "the constant is wrong".
Prefer a sealed type or an enum, and if it must stay a `String`, add an `else` branch that logs
loudly. Verify the set is closed by grepping the constants against the branches:

```
grep -rn "SONG_CLICK\|PLAYLIST_CLICK\|ALBUM_CLICK\|RADIO_CLICK\|SHARE\|RECOVER" --include='*.kt' .
```

Any constant that appears at a call site but not in the `when` is a dead origin.

**Auto-play is derived from the discriminator, not passed as a flag.** A restore path enqueues the
same item and must *not* start playing, so `playWhenReady = type != RECOVER_TRACK_QUEUE` keeps that
decision next to the branch that owns it. An extra boolean parameter would let a caller combine
"restore" with "play now", which is a state the app has no handling for.

**The first item and the rest of the queue are seeded by different mechanisms.** The tapped item is
added immediately so audio starts now; the queue fills asynchronously behind it. That means the
helper which adds items must self-start on the first one:

```kotlin
private fun addMediaItemNotSet(item: GenericMediaItem, index: Int? = null) {
    index?.let { player.addMediaItem(it, item) } ?: player.addMediaItem(item)
    if (player.mediaItemCount == 1) { player.prepare(); player.playWhenReady = true }
    updateNextPreviousTrackAvailability()
}
```

Without that count check, an item added into an empty engine sits there prepared-but-idle and the
tap appears to do nothing. With it applied unconditionally, every append restarts playback.

**`index` means "position in the source", and one path re-reads it.** For a playlist origin it is
which track the user tapped; the seeding path re-catalogs around it — moving the already-enqueued
item to that position and skipping it during the re-add, since it is already in the player. An
index that does not point at the item just enqueued shifts
the whole queue against the engine — the same failure the restore path guards against by putting the
track at the front when the saved queue does not contain it.

**Being `suspend` is part of the contract.** The gate reads a setting, and the normalization may hit
storage. Making it fire-and-forget internally would let a caller's own coroutine cancellation race
the gate, so the policy check would sometimes not complete before the item was enqueued.

## Verifying it

Add a temporary log at the top of the entry point and exercise every origin the app has — each tap,
each long-press menu, each share link, plus a cold restore. Every one should print exactly once. An
origin that plays without printing is a call site that reached the player directly, and it is where
the next forgotten rule will land.
