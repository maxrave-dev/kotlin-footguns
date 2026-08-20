---
name: import-format-contract-design
description: Specify a user-facing exchange file between a producer and a consumer you both control — why a version field can be worse than none, rejecting a file whose parse yields nothing, stating the same-length rule that positionally-aligned arrays imply, and naming the legacy values a producer must never emit. Use when designing an import/export or backup format, or when a user reports importing a file and getting nothing with no error.
---

# Designing an exchange-file contract

An exchange file is a contract between a producer (a converter, an exporter, a plugin) and a
consumer (your app). Write the contract down as a document, not as whatever the parser happens to
accept. A worked envelope:

```json
{ "songs": [ … ], "playlists": [ … ] }
```

Start the document by stating **what the consumer refuses to do**, because that is what constrains
the producer more than any field does: *"the app does no matching of its own — if a track has no id
by the time the file is written, it must not appear in the file at all."* Everything downstream
follows from one sentence like that.

## Traps

**A version field you never branch on is worse than none, and a lenient parser makes it invisible.**
This format deliberately has **no `version` and no `source`**, and says why: the consumer parses
with unknown keys ignored, so a producer that adds `"version": 2` sees it silently dropped and
believes it negotiated something. A field nobody reads is a promise nobody keeps.

*Evolve anyway, without one.* Every field except the identifying ones is optional with a stated
default, so an older producer's file still parses. New fields are additive and optional. When a
genuinely incompatible change arrives, the honest move is a new file *shape* the old consumer
cannot mistake for the current one — not a number the old consumer never looked at. **If you do add
a version field, add the rejection branch in the same commit**; that is the only thing that makes it
real.

**A file that parses to nothing is a wrong-file signal, not an empty library.** With unknown keys
ignored, *any* JSON object decodes into an all-defaults envelope. Say so in the contract and reject
it:

> Both keys are optional and default to an empty list, but a file where **both** lists are empty is
> rejected as "not a valid import file" — that is what makes picking the wrong file produce an error
> instead of a silent "imported 0 songs".

Without this the worst outcome is not a crash, it is a success message. The user believes their
library imported, deletes the source, and finds out later.

**Positionally-aligned parallel arrays imply a rule the schema cannot state — so state it in
prose.** Two arrays where index *n* of one describes index *n* of the other:

```json
"artistName": ["A", "B"],
"artistId":   ["UC…A", "UC…B"]
```

The rule is: `artistId` must be **absent/null, or exactly the same length as `artistName`**. Write
both halves of the consequence:

- what the consumer does defensively — it drops the id list entirely when the sizes disagree, rather
  than reading past the end of the shorter one;
- why the producer must still never rely on that — dropping the list **silently loses every id for
  that track**. If only some resolved, emit `null` and keep the names.

A defense that quietly discards data is not a substitute for the rule. Prefer an array of objects
when you are designing fresh; state the rule when you are documenting something that already ships.

**Name the known-bad legacy values, or old files keep arriving forever.** Real advice from this
contract: *"Do not emit the literal string `"Album"` — older builds used it as a placeholder and the
consumer treats it as 'no album'."* Producers cannot avoid a value they were never told about, and
consumers that special-case it without documenting it leave the next maintainer unable to tell a
placeholder from data. List them in the field table where a producer will actually read it.

**Enumerate what the consumer fills in itself.** A producer that guesses at these will fight the
consumer forever:

> Not in the file, and a producer must not supply them: liked state (`false`), availability
> (`true`), play count (`0`), download state, library timestamps (the moment of import), the
> playlist's own id (assigned by the database), sync state (imported playlists are local-only), and
> track positions inside a playlist (derived from the array order).

The list doubles as a review checklist: anything on it that *is* in the file means the producer
found a way to overwrite runtime state.

**Document the caps and say who enforces them.** "10,000 entries in `songs`, 500 in `playlists` —
the producer enforces these, and the consumer relies on them by parsing the whole file in one pass
with no streaming decoder." Both halves matter: a consumer that reads the whole file into memory has
a limit whether or not anyone wrote it down, and a producer that does not know it is the enforcer
will ship the file that finds it.

**Say what re-importing the same file does, because someone will.** Two different answers here, and
both are correct only because they are stated:

- a song already present is **not overwritten** — its play count, liked state and download state
  survive; the import only fills in fields the stored row is missing;
- playlists are **always created fresh** — importing twice creates a second copy of every playlist,
  it does not merge.

**Order is a field even when it has no column.** `videoIds` carries the track order and positions are
taken from the array index. Say that explicitly, or a producer will sort the array for tidiness.

**Decide per field whether a dangling reference is fatal.** Here it is not: an id in `videoIds` with
no entry in `songs` is skipped, the surviving tracks are renumbered so positions stay contiguous,
and the count of skipped entries is reported to the user at the end. Document all three — the
skip, the renumbering, and the report — and still call it a producer bug. "Tolerated" and "correct"
are different words.
