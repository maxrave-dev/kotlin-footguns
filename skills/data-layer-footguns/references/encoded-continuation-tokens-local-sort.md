---
name: encoded-continuation-tokens-local-sort
description: Carry locally sorted and shuffled paging through the same token slot a remote API uses, by prefixing the token with a mode tag and encoding a cursor after it — and reject an unrecognised prefix loudly, because a silently ignored token leaves the pager stuck in its in-flight state and the list never loads again. Use when one list must page from either a server cursor or a local ordering, or when local sorting made paging stop working with nothing in the log.
---

# One token slot, remote cursors and local ones

A list that pages from a server holds a `continuation: String?`. When the same list must also page a
locally sorted or shuffled ordering, the cheapest correct move is to keep **one** slot and make the
local cursors fit in it, rather than adding a parallel "local page index" that every consumer then
has to know about.

Routing happens twice: the collection id says local or remote, and the token's prefix says which
local mode.

```kotlin
// adapted: names generalized, page size hoisted; encoding as written
"SHUFFLE0_[7,2,19,4]"   // shuffle: page number, then the whole shuffled position list as JSON
"ASC1735689600000"      // oldest-first: the timestamp of the last row read
"DESC1735689600000"     // newest-first: same, other direction
"TITLE3"                // stable order: a page offset
"CUSTOM_ORDER3"         // stable order: a page offset
```

Each mode advances its cursor differently, and that is the point — the token is not a page number,
it is *whatever this ordering needs to resume*:

| Mode | Cursor | Advance | Ends when |
|---|---|---|---|
| Stable order (title, manual) | page offset | `offset + 1` | a page comes back empty |
| Time order | timestamp of the last row | last row's timestamp | a page comes back empty |
| Shuffle | page number + the full shuffled order | page number + 1 | `PAGE * (n + 1) >= order.size` |

The shuffled order is generated once, with the already-playing item removed, and then rides the
token:

```kotlin
// adapted: local variable names generalized; construction as written
val positions = (0 until trackCount).toMutableList().apply { remove(playingIndex) }
positions.shuffle()
_queueData.update { it.copy(data = it.data.copy(continuation = "SHUFFLE0_${json.encodeToString(positions)}")) }
```

## Traps

**An unrecognised prefix must be an error, not a fall-through.** The decoder is an
`if (startsWith("SHUFFLE")) … else if (startsWith(ASC) || startsWith(DESC) || …) …` chain **with no
final `else`**. By the time it runs, the coroutine has already flipped the pager into its in-flight
state — and an unmatched token drops off the end of the block without flipping it back. The guard at
the top of the load function then rejects every later call, so the list stops loading permanently,
with no error and no log line. The bare `?: return@launch` exits inside the branches do the same
thing. Two rules, and the surrounding code already demonstrates both in its sibling branches:
**restore the state flag on every exit path**, and **log the token you could not parse**. Three
behaviours coexist here, not two, and each fails differently: one branch catches its timestamp
parse, logs it and returns; two more return in silence on a `?: return@launch`; and the stable-order
branch is **unguarded** — `removePrefix(TITLE).toInt()` on a malformed token raises, inside launched
work, where nothing above it is catching. So the same malformed-token class yields a log line, a
wedge with no trace, or a thrown exception depending only on which sort the user last picked. That
asymmetry is what makes the silent ones so hard to find, and the unguarded one is the argument for
fixing all three together rather than adding one `else`.

**Route prefixes must not be prefixes of one another.** `startsWith(LOCAL_PLAYLIST_ID)` also matches
ids like `LOCAL_PLAYLIST_ID_SAVED_QUEUE`, and the id is then recovered by
`replace(LOCAL_PLAYLIST_ID, "").toLong()` — which cannot parse the leftover `_SAVED_QUEUE`. **What
that costs depends on which of the two conversion sites you reach, and neither answer is "an error
the user sees".** On the paging path the conversion is wrapped (`catch (NumberFormatException) {
return@launch }`) — but the in-flight flag was already set a few lines above and nothing restores it
on that exit, so the symptom is the wedge from the trap above, not a raised exception. The other
site, on the shuffle path, is bare: there the exception is real. It is safe today only because its
one caller overwrites the playlist id with a well-formed one immediately before calling in — safety
borrowed from a caller, which is not safety. In this codebase the sibling id is also only ever
installed together with a null token, so the paging branch is not currently reached: the collision
is latent, not live. It is still the wrong shape. Use a separator that cannot appear in the payload,
match longest-prefix-first, or keep the discriminator out of the id entirely.

**Reconstructing a prefix from a parsed value is not the same as splitting on a separator.** The
page number is pulled out with a lookaround regex and the payload is then obtained by
`removePrefix("SHUFFLE${n}_")` — which assumes the number formats back to exactly the characters it
was parsed from. It does today, because the only writer formats a plain `Int`. Any token whose
number is padded or spaced round-trips to a *different* prefix, `removePrefix` finds no match and
silently returns the whole token, and the payload decode then fails into one of those silent
returns. Split once on the first separator instead: it cannot disagree with itself.

**Treat the token as untrusted input even though your own code wrote it.** It survives state
updates and, if you persist the queue, restarts and upgrades — so a token written by last release
can arrive at this release's decoder. Only one of the two parses here is actually total: the JSON
decode is wrapped and yields null on anything malformed, so it needs nothing but for the null to be
reported rather than absorbed. `regex.find(token)?.value?.toInt()` only *looks* like its equal — the
`?.` guards the **pattern miss**, and the `toInt()` beyond it is unguarded, so a token whose digit
run is longer than an `Int` matches the pattern and then raises. Elvis-on-a-nullable-lookup is the
easiest thing in this file to mistake for a safe parse; `toIntOrNull()` is the one that keeps the
promise the shape appears to make.

**The shuffle token's size is the collection's size.** Embedding the entire shuffled order is the
only way to make a random ordering resumable without storing it somewhere — that is a genuine
design win, and it costs one integer per item, re-encoded and re-decoded on every page. A few
hundred items is nothing; a few tens of thousands is a string you do not want to write to disk or
put in a log line. If the token ever leaves memory, this is the number to check first.

**The page size shows up three times in the shuffle branch** — the slice start, the slice end, and
the last-page test. Two of the three disagreeing gives you a truncated list or a loop that never
ends, in both cases with no error. Hoist it to one constant, the same way the whole-table reader in
`generic-paged-db-accumulator` has to.

**Local paging and remote paging still share one contract downstream.** Whatever the prefix, the
result is the same page-plus-next-token handoff described in
`continuation-token-pagination-contract`, and `null` still means the end — so the last local page
must null the token out, exactly as the remote branch does.

## Verifying it

The decoder is a pure function of one string, so test it as one:

- Feed a token with an unknown prefix and assert an error is raised or logged **and** that the pager
  is still able to load afterwards. Scrolling in the app cannot distinguish "wedged" from "the list
  really ended".
- Feed a truncated and a malformed payload for each mode. Every one must fail the same way.
- Page a shuffled list to its end and assert the union of all pages equals the original set, with no
  duplicates. Off-by-one in the slice arithmetic shows up as a repeated or missing item near a page
  boundary and nowhere else — check the boundary specifically, with a collection whose size is an
  exact multiple of the page size and one that is not.
- Delete an item mid-paging and re-check: an offset cursor will skip a row, a timestamp cursor will
  not. If your local orderings mix the two, that difference is a behaviour difference your users can
  see.
