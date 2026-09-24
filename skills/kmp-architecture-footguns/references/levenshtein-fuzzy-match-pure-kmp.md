---
name: levenshtein-fuzzy-match-pure-kmp
description: Match a string against a candidate list with a two-row edit-distance loop and no dependency, so the matcher lives in shared multiplatform code. Covers the two-row memory shape, normalizing before comparing, a similarity threshold that refuses rather than returning the least-bad candidate, picking a top-N without corrupting the indices, and the cases where fuzzy matching is the wrong tool. Use when a title-to-title lookup picks a confidently wrong candidate, when a "top 3" helper returns indices that point at the wrong rows or at -1, or when a matcher cannot move into shared code because the library it uses is platform-only.
---

# Edit distance and candidate selection, in shared code

Edit distance is one nested loop and two integer arrays. Writing it out is cheaper than finding a
multiplatform library for it, and the result compiles into shared code with no `expect`/`actual`:

```kotlin
// adapted
fun levenshtein(lhs: CharSequence, rhs: CharSequence): Int {
    var cost = IntArray(lhs.length + 1) { it }      // row for rhs-prefix of length 0
    var newCost = IntArray(lhs.length + 1) { 0 }

    for (i in 1..rhs.length) {
        newCost[0] = i
        for (j in 1..lhs.length) {
            val editCost = if (lhs[j - 1] == rhs[i - 1]) 0 else 1
            newCost[j] = minOf(
                cost[j] + 1,            // insert
                newCost[j - 1] + 1,     // delete
                cost[j - 1] + editCost, // replace
            )
        }
        val swap = cost; cost = newCost; newCost = swap
    }
    return cost[lhs.length]
}
```

**Two rows, not the matrix.** The recurrence only ever reads the previous row and the cell to the
left, so `(n+1) × (m+1)` cells collapse to `2 × (n+1)`. Keep the swap — reallocating a row per
iteration turns a flat allocation into one per character of the second string.

Selection sits on top and is where the design decisions are:

```kotlin
// adapted
fun bestMatchingIndex(query: String, candidates: List<String>): Int? {
    val costs = candidates.map { levenshtein(query, it) }
    val min = costs.minOrNull() ?: return null
    return if (min < THRESHOLD) costs.indexOf(min) else null   // refuse, don't approximate
}
```

## Traps

**An absolute distance threshold is not a similarity threshold.** A fixed bar such as
`min < 20` means a 6-character query accepts *any* candidate — 20 edits rewrites the whole string —
while a 200-character query is refused over a trivial difference. Normalize by length so the bar
means the same thing at every size:

```kotlin
val similarity = 1.0 - distance.toDouble() / maxOf(query.length, candidate.length, 1)
return if (similarity >= 0.8) index else null
```

**Normalize both sides before measuring, or you are measuring formatting.** Raw comparison charges
an edit for every case difference, every accent, and every run of extra spaces, so
`"Cafe  Del Mar"` and `"café del mar"` land several edits apart on a string that a human calls
identical. Lowercase, collapse whitespace, strip accents and trim — on the query *and* every
candidate — before the loop runs. Normalizing only the query is worse than normalizing neither,
because the distance then reflects the candidate's formatting alone.

**Returning the least-bad candidate is the failure mode this whole function exists to prevent.**
The nullable return is load-bearing: with no threshold, a query matches whatever is closest even
when nothing is close, and the caller has no way to tell a real match from an arbitrary one. Any
selection helper that returns a plain `Int` or a non-empty list is making that mistake by
construction. See `unknown-not-a-valid-score` for the general rule — a failure signal must not be
a value that is legal on the success path, and index `0` is legal.

**An index into a filtered array is not an index into the original list.** The classic way a
"top N" helper goes wrong is rebuilding the cost array while skipping already-picked entries, then
calling `indexOf` on it:

```kotlin
// broken — costs is now compacted, so its positions no longer line up with candidates
for (i in candidates.indices) {
    if (picked.contains(i)) continue
    costs.add(levenshtein(query, candidates[i]))
}
picked.add(costs.indexOf(costs.minOrNull()))
```

Every skipped entry shifts the rest left by one, so from the second pick onward the returned
positions address the wrong rows and can repeat a row already picked. When the compacted array
runs out, `minOrNull()` is null, `indexOf` answers `-1`, and that `-1` is added to the result and
then used to index the candidate list. Carry the original index alongside the cost instead:

```kotlin
candidates.withIndex()
    .map { (i, c) -> i to levenshtein(query, c) }
    .sortedBy { it.second }
    .take(n)
    .filter { it.second < threshold }
    .map { it.first }
```

**Do not log inside the matcher.** A log line in the distance function builds its message on every
candidate comparison; one in the selection helper builds it once per call. Both run in release builds,
and both build it even when the tag is muted — see `kmp-logger-facade`. Return the score instead.

**Fuzzy matching is the wrong tool more often than it looks.** Reach for something else when:
- **a stable identifier exists on both sides.** Matching by title when both records carry an id is
  a fabricated problem; the id match is exact, constant-time, and cannot be confidently wrong.
- **the source already ranked the candidates.** Re-ranking a provider's ordered results by string
  distance discards ranking signals you cannot reconstruct.
- **the input is a prefix being typed.** Edit distance charges for every character not yet typed,
  so the best match early in a query is noise. Use prefix matching for autocomplete.
- **the two sides are in different scripts or transliterations.** Distance between a native-script
  string and its romanization is near the string length; the answer is meaningless, not merely bad.
- **the list is large.** Cost is `O(candidates × n × m)` with no early exit. Filter by a cheap key
  first — first character, length band, a shared token — and only measure the survivors.

## Verifying it

1. **Confirm the matcher has no platform dependency**, which is what lets it live in shared code:
   ```sh
   grep -rln "fun levenshtein(" --include='*.kt' . | xargs -r grep -nE "^import (java|android)\."
   ```
   No output. Any hit pins the matcher's file to one target and blocks the move into shared code.
2. **Find selection helpers that cannot refuse** — a non-nullable return is the tell. Signatures are
   usually wrapped across lines, so print each declaration with its return type:
   ```sh
   grep -rn -A 5 "fun .*[Mm]atching" --include='*.kt' . | grep -E "fun |\):"
   ```
   A helper returning `Int?` can refuse. One returning `Int`, or a list type, cannot — it either
   needs a threshold and a nullable/empty result, or documentation of what it means when nothing
   was close.
3. **Find the compacted-index shape** before it ships:
   ```sh
   grep -rn "indexOf(.*minOrNull())" --include='*.kt' .
   ```
   Each hit needs the cost array to be parallel to the candidate list at that moment.
4. **Check the threshold is length-relative.** Read the comparison: a bare integer literal against a
   raw distance is the absolute-threshold shape above.
5. **Feed it a query with no plausible match** and assert it returns null. A matcher without this
   test passes every other test while being confidently wrong in production.
