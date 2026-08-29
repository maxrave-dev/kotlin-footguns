---
name: bulk-json-import-progress
description: Import thousands of rows from a user-supplied file without the UI going dark or the batch dying halfway — chunk the writes and emit progress per chunk, reject a parse that yields nothing before touching the database, and filter incoming rows down to those whose referenced parents exist. Use when building an import/restore feature, when an import of a large file appears frozen, or when a single bad row aborts a whole import.
---

# Importing a large file into a local database

The whole operation is one cold flow that emits a small sealed progress type. The caller collects
it; nothing else needs to know how the work is split.

```kotlin
sealed interface ImportProgress {
    data object Preparing : ImportProgress
    data class Importing(val processed: Int, val total: Int) : ImportProgress
    data class Success(val result: ImportResult) : ImportProgress
    data class Error(val message: String) : ImportProgress
}

override fun import(json: String, invalidFileMessage: String): Flow<ImportProgress> = flow {
    emit(ImportProgress.Preparing)
    …
}.flowOn(Dispatchers.IO)
```

Four phases, in this order: **parse → sanity-check → write songs in chunks → write playlists**.
Nothing touches the database until the first two have passed.

## Traps

**A file that parses but carries nothing is the wrong file, and reporting success is the worst outcome.** With unknown keys ignored
— which you want, so a newer producer's file still imports — *any* JSON object decodes into an all-defaults envelope. Check before writing:

```kotlin
if (data.songs.isEmpty() && data.playlists.isEmpty()) {
    emit(ImportProgress.Error(invalidFileMessage)); return@flow
}
```

A crash gets reported. "Imported 0 songs" does not: the user believes it worked and deletes the source file.

**Row-at-a-time writing is not slow because of the rows, it is slow because of the commits.** If no DAO method takes a list and
there is no ambient transaction, ten thousand inserts are ten thousand commits. Chunk them, and let the chunk size be the emit interval too:

```kotlin
private const val SONG_BATCH_SIZE = 500

var written = 0
data.songs.chunked(SONG_BATCH_SIZE).forEach { chunk ->
    localDataSource.insertSongs(chunk.map { it.toSongEntity() })   // @Transaction
    written += chunk.size
    emit(ImportProgress.Importing(processed = written, total = total))
}
```

**Emit per chunk, never per row.** One emission per row floods a `StateFlow`-backed UI with updates it conflates away anyway, and
the collection overhead can cost more than the inserts. Twenty emissions across a ten-thousand-row import is a smooth progress bar.

**Filter incoming references down to parents that exist, before inserting the children.** A child row pointing at a parent that is
not in the file will be rejected by the foreign key — and because the parent insert is inside a transaction, that one bad reference
takes the whole playlist with it. Build the lookup once and filter:

```kotlin
val songsById = data.songs.associateBy { it.videoId }          // once, not per playlist
val videoIds = playlist.videoIds.filter { songsById.containsKey(it) }
skippedEntries += playlist.videoIds.size - videoIds.size
```

`associateBy` up front is what keeps this linear; `data.songs.any { … }` inside the filter would make it quadratic and turn a fast
import into a hang at exactly the sizes that matter.

**Renumber after filtering, or the gaps become real.** Positions come from the index in the *filtered* list, so they stay contiguous
from 0. Taking the index from the original list leaves holes wherever a reference was dropped, and every later "insert at position n" is then wrong.

**Count what you skipped and report it.** `skippedEntries` is the difference between what the file
asked for and what was written. Surfacing it is the only way a half-empty playlist is a known
outcome rather than a mystery — and it is the signal that tells you the *producer* has a bug, not
the importer.

**Wrap the write phase so a failure becomes an emission, not an escaped exception.** A flow that
throws leaves the collector to handle it, and most collectors do not:

```kotlin
runCatching { /* all writes; returns ImportResult */ }
    .onSuccess { emit(ImportProgress.Success(it)) }
    .onFailure { emit(ImportProgress.Error(it.message ?: invalidFileMessage)) }
```

Note that the parse failure earlier reports the caller-supplied message, while a write failure
reports the underlying one — the user can act on "not a valid file" and cannot act on a parser's
offset, but a write failure is the one you need described when they report it.

**The message text comes from the caller.** Localized strings live in the app module, which the data
module does not depend on. Passing `invalidFileMessage` in keeps the dependency arrow pointing the
right way; building the string in the repository is how the storage layer ends up depending on the
UI.

**Normalize any value that arrives from outside, do not trust it.** Fields written by another program are strings until proven otherwise:

```kotlin
videoType = MusicVideoType.normalize(videoType) ?: ""
```

A real known value is kept, anything else becomes the "unknown" the column already uses and is filled in later from the source of
truth. Storing the raw string means every consumer must now handle whatever the producer invented.

**Enforce a parallel-array length rule at the boundary.** Where two lists are aligned by index,
keep the second only when it matches:

```kotlin
artistId = artistId?.takeIf { it.size == (artistName?.size ?: 0) }
```

Anything else reads past the end of the shorter list later, far from the import, where nothing suggests a file was involved.

**Pick the chunk size against a real file, and measure both halves.** Too small and you pay for
commits; too large and one transaction holds a long write lock and the progress bar stalls in
visible steps. **Verify by timing an import at your documented maximum** — the caps the file format
promises are the size you must actually be fast at, not the size you tested with.

## Verifying it

Run against `core/data/src/commonMain/kotlin/com/maxrave/data/repository/ImportRepositoryImpl.kt` from the repository root.

1. **The batch-size constant drives both the chunk and the emit, and the lookup is built once:**

   ```bash
   grep -n "SONG_BATCH_SIZE\|associateBy { it.videoId }" core/data/src/commonMain/kotlin/com/maxrave/data/repository/ImportRepositoryImpl.kt
   ```

   Pass condition: one `private const val SONG_BATCH_SIZE`, consumed by the same `.chunked(...)` that drives the `Importing(processed, total)` emit; `associateBy` appears once, outside any per-playlist loop.

2. **The two boundary guards are verbatim, not paraphrased:**

   ```bash
   grep -n 'MusicVideoType.normalize(videoType)\|artistId?.takeIf' core/data/src/commonMain/kotlin/com/maxrave/data/repository/ImportRepositoryImpl.kt
   ```

   Pass condition: both lines are present — an unrecognised value falls back to `""`, and a mismatched-length array is dropped rather than read out of bounds later.

3. **By hand: time an import at your documented maximum file size**, not the size you tested with. A stall followed by a jump to 100% means the chunk size is too large to feel responsive at that size.
