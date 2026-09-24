---
name: room-rawquery-readonly-vacuum
description: Why a raw-query DAO method runs on a read-only connection, so database compaction fails there with "attempt to write a readonly database" while a checkpoint on the same connection succeeds and hides the problem. Reach for it when a bulk delete frees no disk space, or when a raw statement reports a readonly database you clearly opened for writing.
---

# Raw queries take a reader connection

An ORM picks the connection for a statement by deciding whether that statement writes. When the
statement is a parsed, annotated query the generator can read it and see a `DELETE`, so it asks for a
writer. When the statement arrives as an opaque string through a raw-query escape hatch, the
generator cannot know — and it defaults to **read-only**.

In Room specifically (as of Room 2.8), KSP generates a `@RawQuery` method as
`performSuspending(__db, true, false)` — positional booleans, in order `isReadOnly`,
`inTransaction`. Room then takes a *reader*
connection, and readers are opened with `PRAGMA query_only = 1`. Under that pragma `VACUUM` fails
outright with *"attempt to write a readonly database"*.

## Where compaction belongs

On the database class, not the DAO — the DAO has no way to ask for a writer connection at all:

```kotlin
abstract class MusicDatabase : RoomDatabase() {
    abstract fun getDatabaseDao(): DatabaseDao

    suspend fun vacuum() {
        useWriterConnection { it.execSQL("VACUUM") }
    }
}
```

And at the call site, checkpoint first, then compact, and swallow the failure:

```kotlin
// adapted
runCatching {
    localDataSource.checkpoint()   // pragma wal_checkpoint(full)
    localDataSource.vacuum()
}.onFailure { Logger.e(TAG, "compaction after clearing history failed: ${it.message}") }
```

## Traps

**A working raw checkpoint is not evidence that raw statements can write.** `PRAGMA wal_checkpoint`
is accepted on a read-only connection. So a codebase can carry a raw-query checkpoint helper that
works perfectly for years, and everyone reasonably concludes the escape hatch writes fine — until the
first statement that genuinely needs a writer lands next to it and fails. If you keep the checkpoint
helper on the DAO, leave a comment beside it saying why compaction deliberately does *not* live
there; otherwise someone will move it back.

**Compaction cannot run inside a transaction.** SQLite refuses `VACUUM` in one — plainly, with
`cannot VACUUM from within a transaction`. The trap is not the message but the transaction you
cannot see: ORM helpers open one for you, so wrapping the call in `withTransaction { }` — or
running it through any generated path that begins its own transaction — turns a working statement
into a failing one whose error points at a `BEGIN` that appears nowhere in your code. Use an exec
that prepares and steps the statement without opening a transaction (`execSQL`).

**Compact last, outside the deletes.** Anything that leaves a transaction open around the call
reintroduces the trap above, and compaction on a database still mid-sweep has less to reclaim.

**Skip the checkpoint and most of the space stays gone.** The pages a bulk delete frees are sitting
in the write-ahead log; the checkpoint folds them back into the main file so compaction has something
to reclaim. Without it the operation "succeeds" and the file barely shrinks — which reads to the user
as the feature not working.

**A compaction failure is not a failure of the operation.** Every delete has already committed by the
time compaction runs. Letting it throw surfaces an error toast for work that actually succeeded, and
the user will retry the whole expensive sweep for nothing. Log it and move on: the only cost is disk
space the next run reclaims.

**Compaction rewrites the entire file.** It needs room for a second copy and it is not instant on a
large database. Run it where a user expects a long operation (an explicit "clear cache" action), not
on a hot path or at startup.

## Verifying it

- **Read the generated code, do not reason about the generator.** Open the generated DAO
  implementation for your method and look at the flag the call site passes — the read-only decision is
  written there in plain sight, for every method, and it is the only source that stays correct across
  library versions.
- **Ask the connection what it is.** `SELECT * FROM pragma_query_only;` executed through the same path
  as your failing statement answers "am I on a reader?" directly, without guessing from the error.
- **Measure the file, not the row counts.** Record the database file size before the sweep, after the
  deletes, and after compaction. The middle number barely moves even on a successful sweep — that gap
  is exactly what compaction is for, and it is the only way to tell a working compaction from a
  silently swallowed one.
- **Check the log path is reachable.** Because the failure is deliberately swallowed, the log line is
  the entire signal. Force it once (wrap the call in a transaction on purpose) and confirm the message
  actually appears.
