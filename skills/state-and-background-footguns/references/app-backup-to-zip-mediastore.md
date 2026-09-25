---
name: app-backup-to-zip-mediastore
description: Back an app up into one zip that lands in the user's own Downloads folder with no storage permission, keeping only the newest N archives. Covers checkpointing the database's write-ahead log before the file is copied, assembling the archive in cache first, inserting through the system media store, and pruning old archives with a query over that same collection. Android only. Use when a restored backup is missing the most recent writes, when the backup file is invisible to the user's file manager, or when old backups accumulate forever.
---

# Backing an app up to a zip in the user's Downloads

Android only. Three moving parts, and the order between them is the whole feature:

1. **Checkpoint** the database's write-ahead log (WAL), then copy the database file.
2. Assemble the zip into the app's own cache directory.
3. Stream that temp file into a row you insert in the system media store, then prune.

## Checkpoint, then copy

A database in write-ahead-log mode keeps recent commits in a side log, not in the main
database file. Copying the file alone gives you a database as of the last checkpoint — the
copy silently omits everything committed since. Ask the database to fold the log back in first:

```kotlin
// adapted — inside the archive builder, per entry
val settingsFile = File(context.filesDir, "datastore/$SETTINGS_FILENAME.preferences_pb")
if (settingsFile.exists()) {
    zip.putNextEntry(ZipEntry("$SETTINGS_FILENAME.preferences_pb"))
    settingsFile.inputStream().buffered().use { it.copyTo(zip) }
    zip.closeEntry()
}

// Checkpoint BEFORE reading the database file
repository.databaseDaoCheckpoint()
FileInputStream(repository.getDatabasePath()).use { input ->
    zip.putNextEntry(ZipEntry(DB_NAME))
    input.copyTo(zip)
    zip.closeEntry()
}
```

The checkpoint itself is a `PRAGMA wal_checkpoint(full)` issued through the ORM's raw-query
escape hatch. That escape hatch has its own connection trap — see the sibling skill
`room-rawquery-readonly-vacuum`, which covers which statements a raw query may and may not run.

Optional payloads (a media cache database, a downloads folder) go in behind their own flag,
each guarded by an existence check, because a user who never downloaded anything has neither.

## Insert into the media store, do not write a path

Writing to a public directory by path needs a storage permission. Inserting a row into the
media store's downloads collection does not — the system creates the file for you and hands
back a URI you write through:

```kotlin
// adapted
val values = ContentValues().apply {
    put(MediaStore.Downloads.DISPLAY_NAME, "backup_$timestamp.zip")
    put(MediaStore.Downloads.MIME_TYPE, "application/zip")
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        put(MediaStore.Downloads.RELATIVE_PATH, "Download/<AppFolder>")
    }
}
val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
uri?.let { out ->
    resolver.openOutputStream(out)?.use { sink -> tempZip.inputStream().use { it.copyTo(sink) } }
    true
} ?: false
```

## Traps

**Every read of the database file needs its own checkpoint; every write needs a close as well.**
The scheduled worker and the manual export are the read direction, and they share the pair above:
`checkpoint()`, then copy the file out. Restore is the write-direction sibling, and it needs one
more step — `checkpoint()`, then `closeDatabase()`, *then* overwrite the file. Forget the
checkpoint on a read site and you get a backup that is *almost* right, which is the hardest kind
to notice. Forget the close on the write site and the overwrite lands underneath a live
connection that still holds the replaced file's pages and its own log; restarting the process
immediately after a restore, as both platforms here do, is part of the same precaution, not a
substitute for it.

**`RELATIVE_PATH` does not exist below the scoped-storage API level**, and neither the insert
nor the retention query may use it there. Both sites need the same version branch, or the prune
runs a selection over a column the provider rejects and cleans nothing. Wrap the prune so that
failure is at least *recorded* — a caught-and-logged provider error is the only trace you get,
since nothing about it reaches the user and the symptom is merely that old archives never stop
accumulating.

**The retention query keeps the newest by sorting, not by comparing timestamps.** Sort
descending by date-added and drop the first N; everything left over is old. Flip that sort and
you delete exactly the archives you meant to keep:

```kotlin
// adapted
val sortOrder = "${MediaStore.Downloads.DATE_ADDED} DESC"
…
if (backups.size > maxFiles) {
    backups.drop(maxFiles).forEach { (id, _) ->
        resolver.delete(ContentUris.withAppendedId(EXTERNAL_CONTENT_URI, id), null, null)
    }
}
```

**The `LIKE` selection is not the identity check.** The cursor loop re-tests the name's prefix
and suffix before adding a row to the delete list. A `LIKE` pattern is a wildcard match over a
column other apps also write to; the second check is what stops the prune reaching a file you
did not create.

**Assemble in cache, then copy.** Building the zip straight into the media-store output stream
means a failure mid-archive leaves a truncated file already visible to the user in Downloads.
The temp file is deleted after the copy attempt either way, and retention runs only when the
copy reported success.

**A disabled feature must return success, not failure.** The worker re-reads its own enabled
flag and returns success when the feature is off; only a genuine save failure returns retry.
Returning failure for "user turned it off" burns the retry budget on nothing. Why the worker
re-reads a setting the scheduler already observed is covered in `datastore-driven-workmanager`.

## Verifying it

1. **Find every place the database file is opened as a file** and check each one checkpoints
   first. Grep the *repository's own accessor*, not the bare name — the platform's unrelated
   `Context.getDatabasePath(name)` shares that name, and so do the accessor's own declaration and
   its per-platform implementations:
   `grep -rn "<repo>\.getDatabasePath()" --include='*.kt' <src>`. Every hit that goes on to open a
   stream must have the checkpoint above it in the same block — and, on the write ones, the close
   too. A hit that only stores the path in a field is not a copy site.
2. **Restore onto a fresh install and check for the last thing you did before backing up.** A
   missing checkpoint costs you only the newest writes, so a stale-looking-but-plausible restore
   is the symptom.
3. **Open the file from the device's own file manager**, not through the app. A file written
   without a media-store row exists on disk but never appears there.
4. **Run the schedule past the retention count** (temporarily lower it) and confirm the survivors
   are the newest, by name and by date.
5. Run the whole thing once on a device below the scoped-storage API level, or at least force
   the `else` branch — it is the branch nobody exercises.
