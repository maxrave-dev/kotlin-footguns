---
name: enum-normalize-over-legacy-data
description: Reading a type marker the remote source declares for itself — normalizing before every comparison because locally stored rows from older app versions hold labels the app invented, treating null as "the source did not say" rather than as a default, exposing an is-known predicate so callers branch on knowledge, and correcting old rows by write-through instead of a migration. Use when a stored type column holds several spellings, when an item is treated as the wrong kind, or before adding a database migration to fix historical values.
---

# Read the marker the source declares — then normalize it

An unstable source usually does state what a thing is, in one place, in its own vocabulary. The
mistake is not reading it: without that, every screen invents its own label for the same column and
nothing can ask "what kind is this?" and get a true answer.

Read it, and put the comparison in **one** small object rather than at each call site:

```kotlin
// adapted — the marker family, its prefix and the field name are renamed to neutral equivalents;
// the source's provider-specific constants are not reproduced. Every body is otherwise unchanged.
object ItemKind {
    private const val PREFIX = "ITEM_KIND_"

    /** Keeps [value] only if it is one of the source's own markers, otherwise null. */
    fun normalize(value: String?): String? = value?.takeIf { it.startsWith(PREFIX) }

    /** Whether the source reported a kind at all. */
    fun isKnown(value: String?): Boolean = normalize(value) != null

    /** True only when the source explicitly said this is the plain one. */
    fun isPlain(value: String?): Boolean = normalize(value) == KIND_PLAIN

    /** True only when the source named a kind AND it is not the plain one. */
    fun isRich(value: String?): Boolean = normalize(value)?.let { it != KIND_PLAIN } == true

    /** Sub-families go through the same gate. */
    fun isEpisode(value: String?): Boolean = normalize(value)?.contains("EPISODE") == true
}
```

Put it in the lowest module that both the integration layer and the data layer already depend on.
Placing it in either of those inverts an existing dependency edge, and placing it in a new module
adds one — the domain module is usually already the answer.

## Traps

**Normalize first, in every predicate — that is what the object is for.** These functions are handed
values read straight out of local storage, and rows written by earlier versions of the app hold
whatever that version's mapper put there. If every stored value were a real marker, `normalize`
would be a no-op and would not exist; the fact that it does is the evidence that they are not. The
normalizer's own documentation here records three shapes that reached this column — a display word,
a lowercase spelling, and a value from an entirely different field that one mapper had nothing else
to put in. Compare any of those raw and a predicate confidently answers about a value the source
never sent.

**Never let a marker column double as somewhere to park an unrelated value.** A field named for a
type that occasionally holds a count is worse than a field that is null: null is honest and a
normalizer neutralises it, whereas a plausible string is indistinguishable from a real marker until
someone compares them. If a mapper has nothing to put in the field, the field is nullable.

**`null` means "the source did not say". It is not a default and must never be folded into one.**
A response that simply omitted the marker must not be recorded as a definite kind, because that
invented label then outlives the response that lacked it and is passed on to everything downstream.
The rule applies at write time even more than at read time.

**Each predicate resolves the unknown one way, and which way is not obvious — so say it, and ship
`isKnown`.** `isRich` above returns false for an unknown, so it means *"known to be rich"*, not
*"not known to be plain"*. The normalizer's own documentation here records that two reference
implementations of the same idea resolve the unknown in opposite directions — one toward the plain
kind, the other toward the rich one. Both are defensible; silently picking one is not. Document the
direction on each predicate, and expose `isKnown` so a caller that actually cares can branch on
knowledge before branching on kind.

**Two predicates both returning false for the same value is correct, and is the tell.** With an
unknown, `isPlain` and `isRich` are both false — because there are three states, not two. Any caller
written as `if (isRich(x)) … else …` has just assigned every unknown to the plain branch. Look for
that shape whenever a new predicate is added.

**Prefer a write-through correction to a migration.** When a fresh, authoritative value arrives —
the item is opened, played, refreshed — compare it against the stored one and update the row, guarded
so that an unknown can never overwrite a known value:

```kotlin
ItemKind.normalize(fresh?.kind)?.let { freshKind ->
    if (stored.kind != freshKind) repository.updateKind(freshKind, stored.id)
}
```

This is cheaper than a migration, needs no downtime, and cannot corrupt a row it fails to improve.
Its cost is honest and must be stated: rows for items the user never revisits stay wrong
indefinitely. That is only acceptable *because* the normalizer neutralises them on every read — the
two techniques are a pair, and shipping the write-through without the read-time gate leaves the old
values live.

**Normalize on the way in as well, and make the ingest fallback something the read gate also
rejects.** Values arriving from a file import or a backup have the same problem as old rows and
worse provenance. When the column is non-nullable, the ingest path needs a fallback — and that
fallback must itself normalize back to nothing on read (an empty string does; a plausible-looking
word that starts with the prefix does not). Two gates, agreeing on what "unknown" looks like.

**A prefix test is deliberately open, and that is a trade.** `startsWith(PREFIX)` accepts markers the
source has not invented yet, so a new member of the family works without a release. It also accepts a
typo or a fabricated value that happens to start with the prefix. Take the openness when the source
adds members without notice; take an explicit allow-list when the set is stable and a wrong value is
expensive.

**Do not spell the comparison at call sites.** The reason to have the object at all is that a raw
comparison against a marker literal, scattered through parsers and screens, cannot be normalized,
cannot be found when the marker family changes, and is where the disagreement between "did not say"
and "said plain" creeps back in one call site at a time.

## Verifying it

```bash
find . -name '*.kt' -not -path '*/build/*' -exec grep -l 'fun normalize(' {} +
find . -name '*.kt' -not -path '*/build/*' -exec grep -l 'fun normalize(' {} + \
  | xargs grep -nE 'fun (is|has)[A-Za-z]*\('
grep -rn 'normalize(' --include='*.kt' . | grep -v '/build/'
grep -rnE '== *"[A-Z][A-Z0-9_]{4,}"' --include='*.kt' . | grep -v '/build/'
```

The first should return exactly one file; two means the discipline has already been forked. The
second lists that file's predicates — read each line and confirm the body calls `normalize`, because
a predicate that skips it is invisible from the outside and answers about raw stored text. The third
widens to every call site: expect the predicates themselves, plus the ingest path, plus the
write-through guard — a codebase with the object but no hits outside it has a normalizer nobody
routes through.

The fourth is the drift census: raw comparisons against upper-case marker literals. Parsers
accumulate these, and each hit is a place the family's vocabulary is spelled out again. It is a
find-and-read list, not a number to drive to zero — some of those literals are unrelated — but a long
list under one integration is a marker family that deserves an object of its own.

For the states themselves, the test is three cases per predicate, not two: a known plain value, a
known non-plain value, and `null`. A test suite with only the first two passes on a version that has
folded the unknown into a default, which is the failure this whole discipline exists to prevent.

Related: `structural-defensive-parsing` reads the marker out of the response in the first place, and
`response-to-domain-flow` is the pipeline that carries it to the column this normalizes.
