---
name: room-migrations-at-scale
description: Keep a Room database upgradable after twenty-plus schema versions — declaring the whole graph of (from,to) edges instead of assuming users only ever hop one version, filling the gaps a generated migration cannot express, and recreating triggers idempotently in the on-open callback. Use when an upgrade from an old build reports no migration path, when a trigger exists on upgraded databases but not on fresh installs (or the reverse), or before shipping a schema change to a long-lived app.
---

# Migrations once you have many versions

Migrations are a **directed graph**, not a ladder. Room walks it from the version on disk to the
version in the code, and it can only walk edges you declared. A long-lived app has users on almost
every version it ever shipped, so the set of starting points is the whole history — not just the
previous release.

Two kinds of edge exist and they cover different work:

- **Generated** (`autoMigrations = [AutoMigration(from = 23, to = 24)]`) — produced at build time by
  diffing two exported schema files. Only expresses what a schema diff can express: added tables and
  columns, and — with a spec class — renames and deletions.
- **Hand-written** (`.addMigrations(object : Migration(5, 6) { … })`) — anything that moves data.

## Traps

**The walker chains single steps — reachability needs every consecutive edge, and fan-in is an
optimisation on top.** The library composes an upgrade path out of the edges you declared, one hop
at a time, so an unbroken chain of `N → N+1` edges already carries every old version to the head.
Fan-in edges onto each new target then shorten the walk for the common upgrades:

```kotlin
AutoMigration(21, 22), AutoMigration(20, 22), AutoMigration(19, 22),
AutoMigration(22, 23), AutoMigration(21, 23), AutoMigration(20, 23),
AutoMigration(23, 24), AutoMigration(22, 24), AutoMigration(21, 24),
```

Each extra edge costs one generated class and nothing at runtime — worth declaring, never *required*
while the consecutive chain is intact. **Verify coverage by listing the `from` values you
declared** and checking that every version you ever released either has its `N → N+1` edge or is
bridged by a direct edge over the gap (next trap).

**A chain is only walkable if every intermediate edge exists — one skipped edge orphans everything
before it.** This schema history has no `1 → 2` edge at all; version 1 reaches version 3 by a direct
`AutoMigration(from = 1, to = 3)`. Without that direct edge, every database still on version 1 would
be unreachable no matter how complete the rest of the graph is. When you skip a step, say so with a
direct edge over the gap.

**A generated migration cannot move data, and the failure is not a build error.** A schema diff sees
"column dropped, table added" and happily throws the old contents away. Two shapes always need a
hand-written step:

- *Reshaping a column into rows.* Migration 5→6 here reads a JSON array column out of every row,
  turns it into join-table rows, creates the join table and its indices, then inserts them.
- *Rebuilding a table with a different key.* Migration 10→11 collects the rows it wants to keep,
  drops the table, recreates it with a composite primary key, and re-inserts.

The tell is that the migration body runs a `SELECT` before it runs any DDL. If it does, it cannot
be generated.

**Values interpolated into a migration statement are concatenated, not bound.** Hand-written
migrations build their SQL as strings:

```kotlin
// adapted — trimmed to three of the real statement's four columns
connection.execSQL(
    "INSERT OR IGNORE INTO pair_song_local_playlist (playlistId, songId, position) " +
        "VALUES (${pair.playlistId}, '${pair.songId}', ${pair.position})"
)
```

Every one of those values came out of the user's own database, so a value containing a quote ends
the statement early and the migration stops partway. Prepare the statement and bind instead, or —
if you keep the concatenation — escape the text values and be able to say why the data cannot
contain the delimiter.

**Triggers, views and pragmas are not part of the schema Room migrates.** Nothing creates them on a
fresh install, and nothing recreates them after a table is rebuilt. Put them in the **on-open
callback**, written so running twice is harmless:

```kotlin
.addCallback(object : RoomDatabase.Callback() {
    override fun onOpen(connection: SQLiteConnection) {
        super.onOpen(connection)
        connection.execSQL(
            "CREATE TRIGGER IF NOT EXISTS on_delete_pair_song_local_playlist " +
                "AFTER DELETE ON pair_song_local_playlist FOR EACH ROW BEGIN " +
                "  UPDATE pair_song_local_playlist SET position = position - 1 " +
                "  WHERE playlistId = OLD.playlistId AND position > OLD.position; END;"
        )
    }
})
```

`onOpen` fires on every open, after any migration has run — which is exactly what makes it the one
place that ends up correct after a fresh install *and* after an upgrade. `IF NOT EXISTS` is what
makes "every open" affordable.

**In a multiplatform module the migration list is registered in the platform actual, so it only
exists on the platforms that register it.** Here `addMigrations(...)` and `addCallback(...)` are
attached inside the Android builder; the desktop and iOS builders attach neither. There is no
warning — those platforms simply have no trigger and no hand-written step. Hoist the shared
registration into a common function that every actual calls, and keep the actual down to the file
path.

**Keep every exported schema file in version control.** A generated migration is produced by
diffing the file for `from` against the file for `to`. Delete `17.json` and the build still
succeeds — until someone declares an edge out of 17 and the diff has nothing to read. The
directory is configured once (`room { schemaDirectory("$projectDir/schemas") }`) and should be
reviewed like source.

**A deletion spec is a declaration, not the deletion.** `@DeleteTable` / `@DeleteColumn` tell the
generator what changed so it can compute the diff. When the intent is "the table is gone", say it
explicitly as well:

```kotlin
@DeleteTable(tableName = "format")
internal class AutoMigration7_8 : AutoMigrationSpec {
    override fun onPostMigrate(connection: SQLiteConnection) {
        super.onPostMigrate(connection)
        connection.execSQL("DROP TABLE IF EXISTS `format`")
    }
}
```

**Verify an upgrade path by starting from an old database file, not from a fresh one.** Keep a copy
of a real database at each of the last few versions and open it with the current code. A fresh
install exercises none of your migrations, so "it works on my machine" is the one result that
proves nothing here.
