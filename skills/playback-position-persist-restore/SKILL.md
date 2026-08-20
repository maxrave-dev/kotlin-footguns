---
name: playback-position-persist-restore
description: Persisting and restoring the playback position cheaply — a full queue save on lifecycle edges versus a light five-second position tick that rides an existing loop, skipping the save while the queue is being rebuilt, and snapshotting values before issuing player commands that change them. Use when background playback resumes from the start of a track after the process is killed, or when a restore lands on the wrong track or position.
---

# Persisting and restoring the playback position

Saving "where the user was" has two very different costs. Rewriting the whole queue means a full
list serialized to storage; saving the position means two small values. Doing the expensive one on a
timer is wasteful, and doing the cheap one only on lifecycle edges misses the case that matters most:
a long uninterrupted background session ended by the system, with no pause and no track change to
trigger a save.

So there are two save shapes with different triggers:

```kotlin
// Heavy — track change, pause, teardown. Rewrites the queue AND the position.
override fun mayBeSaveRecentSong(runBlocking: Boolean) {
    val unit = suspend {
        if (!settings.saveRecentSongAndQueue()) return@suspend
        val trackId = nowPlayingState.value.songEntity?.trackId
        if (trackId != null && queueData.value.queueState == StateSource.STATE_INITIALIZED) {
            settings.saveRecentSong(trackId, player.contentPosition)
            songRepository.recoverQueue(ArrayList(queueData.value.data.listTracks))
        }
    }
    if (runBlocking) runBlocking { unit() } else scope.launch { unit() }
}

// Light — every 5 s while playing. Position only.
private fun mayBeSaveRecentPosition() = scope.launch {
    if (!settings.saveRecentSongAndQueue()) return@launch
    val trackId = nowPlayingState.value.songEntity?.trackId ?: return@launch
    settings.saveRecentSong(trackId, player.contentPosition)
}
```

## Traps

**Do not add a timer for the light save — ride the loop that already exists.** A progress loop is
already ticking to drive the seek bar. Counting inside it costs one integer:

```kotlin
progressJob = scope.launch {
    var sinceLastSaveMs = 0L
    while (true) {
        delay(100)
        _state.value = Progress(player.currentPosition)
        sinceLastSaveMs += 100
        if (sinceLastSaveMs >= 5_000L) { sinceLastSaveMs = 0; mayBeSaveRecentPosition() }
    }
}
```

Five seconds of granularity is the trade: worst case the user loses five seconds of position. A
second coroutine on its own schedule buys nothing and adds a lifecycle to get wrong.

**Cancel the previous loop before relaunching it.** The callback that starts this loop fires more
than once per session — a resume, a transition between two internal players, a rebuffer that
resolves. Without `progressJob?.cancel()` on the first line, each one leaves a live loop behind, and
every leaked loop multiplies both the UI writes and the position writes for the rest of the session.
Verify by logging in the loop body and counting lines per second: it should be a flat ten, not a
number that grows after each skip.

**Skip the heavy save while the queue is being rebuilt.** A re-catalog empties the list and re-adds
the playing track last, so a save landing in that window persists a queue that does not contain the
track being heard — and the next restore starts elsewhere. The flag lives on the queue state; see
`queue-rebuild-state-machine`. The light save has no such condition on purpose: it writes only the
id and position, neither of which the rebuild touches.

**Snapshot values before issuing player commands that change them.** This is the subtle one. The
restore path reads the saved position, then loads the queue — and loading fires a track-change
callback, which triggers the heavy save, which overwrites the stored position with the *current*
one (zero) before the seek can read it:

```kotlin
val savedPosition = settings.recentPosition.first().toLongOrNull() ?: 0L   // read FIRST
val savedTracks = songRepository.getSavedQueue()...
// ...enqueue, which will fire callbacks that rewrite storage...
player.seekTo(index, savedPosition)                                        // uses the snapshot
```

Any value read from storage *after* a player command has been issued is a value the player's own
listeners may already have replaced. The rule is general: snapshot, then command, then use the
snapshot.

**The saved track may not be in the saved queue, and the index must still point at it.** The queue
and the position are written by different triggers, so they can disagree — most often when the queue
was saved during a rebuild. The seeding path skips the item at `index` as "already in the player",
so an index pointing anywhere else shifts the whole queue against the engine:

```kotlin
var index = savedTracks.indexOfFirst { it.trackId == currentTrack.trackId }
val listTracks = if (index == -1) { index = 0; listOf(currentTrack) + savedTracks }
                 else savedTracks
```

**Wait for the load before seeking.** `loadJob?.join()` between enqueueing the queue and seeking is
what makes the seek land on a timeline that exists. Seeking first appears to work with a short queue
and drops silently with a long one, because the index is not there yet.

**Use one save body with a blocking switch, not two copies.** Teardown must complete the write
before the process goes away, while the periodic path must not block:

```kotlin
if (runBlocking) runBlocking { unit() } else scope.launch { unit() }
```

Two separate implementations drift — the async one gains a condition the blocking one never gets,
and the bug only appears on the path that runs when the app is closing, which is the hardest to
observe.

**Position and duration are not the same clock.** `contentPosition` excludes any inserted content;
`currentPosition` does not. Persist the one the seek will consume, or a restore drifts by whatever
was inserted before the playhead.

**Persisting is gated by a user setting, so the restore path must degrade cleanly.** With the setting
off there is no stored queue at all — the restore must be a no-op, not an attempt to resume from a
blank id, which enqueues an item with no source and stalls.

## Verifying it

Start a long track, let it play in the background past the five-second mark, and end the process
from the system rather than from the app so no lifecycle callback runs. Relaunch: the same track
should resume within five seconds of where it stopped. Then repeat while a page of the queue is
loading — the restored queue must still contain the playing track. Reading the stored values
directly before and after each step is more reliable than watching the UI, since the UI is fed by
the same restore you are testing.
