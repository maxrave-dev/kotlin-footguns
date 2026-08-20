---
name: model-entity-mapping-extension-layer
description: Put every conversion between transport payloads, domain models and persistence rows in dedicated files of pure extension functions — one direction per function, no suspending work, no logging, nothing else in the file — and keep the layer honest with a grep. Use when conversion code is spreading into data classes, data-access objects or service clients, when a field turns out to be holding a value that belongs to a different field, or when re-reading a row wipes a flag the user set.
---

# A mapping layer made of extension functions

Two hops, two files, and neither of them knows anything about input or output:

```
transport payload  ──►  domain model  ──►  persistence row
   (data module,          (shared module, public extensions)
    internal extensions)
```

```kotlin
// data module — internal, so a transport type can never reach a screen
internal fun SongItem.toTrack(): Track = Track(…)

// shared module — public, both directions declared separately
fun Track.toSongEntity(): SongEntity = SongEntity(…)
fun SongEntity.toTrack(): Track = Track(…)
```

Extension functions rather than methods, because neither side should have to know the other exists:
a `toSongEntity()` written *on* the model drags the persistence module into the model module's
dependencies, and one written on the data-access object turns every query into a conversion site.

## Traps

**One direction per function, and neither direction round-trips.** The downward mapper here keeps
only the last thumbnail URL out of a list; the upward one rebuilds a one-element list with invented
width and height, and re-derives a category flag by looking for a size marker *inside the URL
string*. That is the real cost of dropping a field: something has to guess it back. Expect it, and
never write a test asserting `x.toEntity().toModel() == x` — it will pass only for the fields that
happened to survive, and lock the guesswork in place.

**State the source never carried gets invented by the mapper, and that is only safe on an insert
that ignores conflicts.** The downward mapper fills the user-facing columns — a liked flag, a total
play time, a download state — with zeroes, because the incoming model has no such fields. On an
insert configured to ignore an existing row that is harmless. Point the same mapper at an insert
that replaces, or at an update, and every refresh erases the user's own data. **Check the conflict
strategy before reusing a mapper on a write path**, and prefer an explicit partial update over
mapping a whole row when only some columns are being refreshed.

**Normalization belongs here, but only when it is a pure function of the input.** Rewriting a size
token in an image URL to ask for a larger rendition, padding a null to an empty string, clamping a
missing count to zero — all of these depend on nothing but the argument, so they stay testable and
they stay in one place. Anything that needs a clock, a setting, a network call or a database read is
not normalization; it is a use of the value, and it belongs at the call site.

**Never fill a field from an unrelated source.** A field once held a display subtitle because the
subtitle was the value at hand and the field was nullable and free. Every reader downstream then
invented its own interpretation of that field, and one screen came to depend on the wrong one. The
fix is not a smarter reader: give the second value its own field, default it so payloads already
persisted still decode, and let the original field mean one thing.

**Defaulting a *meaning* is a different job from defaulting a value.** `?: ""` is mapping. Deciding
what an unrecognised or historical string stands for is not — see `enum-normalize-over-legacy-data`
for where that belongs and why comparing raw stored strings misreads rows written by older releases.

**Keep the transport hop `internal`.** Marking the payload-to-model functions `internal` is what
makes "no screen ever holds a transport type" a compiler rule instead of a review habit. The
model-to-row functions stay public, because both the repository and the persistence layer legitimately
need them.

**Purity is the whole point of the file, and it is one command away.** The moment a mapper suspends,
switches dispatcher or logs, it stops being a function you can read top to bottom, and the next one
added beside it will do the same. One of the two mapping files inspected here imports nothing but
model types and a single annotation; the other adds four functions and nothing else — three parsers
and one list converter, each a function of its argument alone. That is the line worth holding: a
parse still reads top to bottom, so it belongs; a dispatcher, a clock or a query does not.

## Verifying it

Point the audit at each mapping file. It should print nothing:

```bash
MAPPER="path/to/YourMapping.kt"
grep -nE "suspend fun|withContext|Dispatchers|runBlocking|^import (java\.|kotlinx\.coroutines|io\.ktor|androidx\.room)" "$MAPPER" || echo "(clean)"
```

List the declared directions and read them as a table — every pair that matters should appear
twice, once each way, and a lone entry is a conversion nobody can undo:

```bash
grep -hoE "fun [A-Za-z0-9_.<>?]+\.to[A-Za-z0-9_]+\(" "$MAPPER" \
  | sed -E 's/^fun (.+)\.to([A-Za-z0-9_]+)\($/\1 -> \2/' | sort
```

Before letting a downward mapper anywhere near a write path, look at what the write does with an
existing row:

```bash
grep -rhoE "OnConflictStrategy\.(Companion\.)?[A-Z]+" --include="*.kt" . | sed 's/Companion\.//' | sort | uniq -c
```

Every replacing insert is a place where a mapper's invented defaults overwrite stored state. Match
each one against the tables whose rows carry user state, and confirm the value being written came
from the row rather than from the mapper.
