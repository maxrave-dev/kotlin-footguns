---
name: small-collection-utilities
description: Four small helpers worth carrying in a shared module, each with the one way it misleads — a symmetric set difference for diffing two id sets, a position index for constant-time lookups, a tolerant parse/serialize pair for timestamped tokens that returns null instead of throwing, and a translator that rewrites an external link into your own scheme. Use when a diff reports every item as changed, when a position lookup returns the wrong index for a repeated element, when one malformed line takes down a whole screen, or when pasting a link into a search box searches for the link.
---

# Four helpers, four ways they mislead

Small enough to write from memory, which is exactly why nobody re-reads them once they are in.

## Symmetric difference

```kotlin
infix fun <E> Collection<E>.symmetricDifference(other: Collection<E>): Set<E> {
    val left = this subtract other
    val right = other subtract this
    return left union right
}
```

Answers "which elements are on exactly one side" — additions and removals in one pass, when
reconciling a stored list of ids against a freshly fetched one.

**The trap: it is set arithmetic, so membership is all it can answer.** Duplicates collapse, order
is gone, and an element that merely *moved* is on both sides and reports as unchanged. Run it over
models rather than ids and the answer depends on the model's `equals` — for a data class that is
every field, so editing a title reports the item as both removed and added. **Diff the ids, then
compare matched pairs separately for content changes.** Two answers, two questions.

## Position index

```kotlin
fun <T> Iterable<T>.indexMap(): Map<T, Int> {
    val map = mutableMapOf<T, Int>()
    forEachIndexed { i, v -> map[v] = i }
    return map
}
```

Turns a repeated `indexOf` scan inside a loop into one pass plus constant-time lookups — the fix for
sorting one list into another list's order.

**The trap: the assignment is unconditional, so the last occurrence wins.** A repeated element maps
to its final position and the map comes out shorter than the list, silently. Right for a list of
unique ids, wrong for anything else; build it with `getOrPut` if you want the first occurrence. Same
caveat as above on the key type — keying on a model means keying on its whole `equals`.

## A tolerant parse/serialize pair for timestamped tokens

For `<MM:SS.mm> word <MM:SS.mm> word …`, match **only the stamps** and slice the text between them:

```kotlin
val stampRegex = Regex("""<(\d{2}):(\d{2})\.(\d{2,3})>""")
val stamps = stampRegex.findAll(payload).toList()
stamps.forEachIndexed { index, match ->
    val (minutes, seconds, fraction) = match.destructured
    val fractionMs = fraction.toLongOrNull() ?: 0L
    val timeMs = (minutes.toLongOrNull() ?: 0L) * 60_000L + (seconds.toLongOrNull() ?: 0L) * 1_000L +
        if (fraction.length == 2) fractionMs * 10L else fractionMs      // 2 digits are hundredths
    val to = if (index < stamps.size - 1) stamps[index + 1].range.first else payload.length
    val text = payload.substring(match.range.last + 1, to).trim()
    if (text.isNotBlank()) out += Token(text, timeMs)
}
if (out.isEmpty()) return null      // the caller falls back to the coarser format
```

**The trap is threefold, and the first two are silent.** *Matching stamp-and-text in one regex ties
the text's shape to the pattern:* punctuation, another angle bracket, a script the character class
never considered — all dropped, and the payload comes back looking merely short. Slicing to the next
delimiter has no opinion about the text at all.

*The fraction's digit count is its unit.* Read the digits as a number without checking `length` and
every two-digit stamp lands at a tenth of where it belongs — early, plausible, and consistent enough
to look like a tuning problem rather than a parsing one.

*Every numeric field falls back rather than failing*, so "unparseable" and "zero" become one answer.
A legitimate choice — one bad stamp should not lose the other forty — but keep the **whole-payload**
failure as `null`, so the caller falls back to a coarser rendering instead of losing the screen.

Write the serializer beside it, and **re-add whatever the parser stripped** — noticing which parser.
The line-level parse strips the space after the line stamp, and its writer puts that back:

```kotlin
if (lines.isNullOrEmpty() || syncType != RICH) return null    // refuse to write another format
return lines.joinToString("\n") { "[$stamp] ${it.payload}" }  // pad back the separator trim() ate
```

The per-slice `trim()`s inside a line are restored by nothing — safe only while the tokens stay a
render-time value. Serialize them and the words run together, so re-add the separator there too; and
guard on the format tag either way, since writing a payload you were not given parses into nonsense.

## External link to deep link

```kotlin
fun String.toAppDeepLinkOrNull(): Uri? {
    val trimmed = trim()
    if (!trimmed.startsWith("http://", true) && !trimmed.startsWith("https://", true)) return null
    val uri = runCatching { Uri.parse(trimmed) }.getOrNull() ?: return null
    val host = uri.host?.lowercase()?.removePrefix("www.") ?: return null
    …
    return Uri.parse("yourapp://watch?v=$id")     // hand to the handler you already have
}
```

**The trap: the temptation is to handle the link, and the answer is to translate it.** Your existing
deep-link handler already knows the special cases — which id prefixes mean which kind of collection,
which need a prefix added — and a second handler starts as a copy and drifts the next time one of
those rules changes. Rewrite the URL into your own scheme, hand it to the same entry point, and
there is only ever one set of rules.

- **Return `null` for anything unsupported**, so the caller can treat it as ordinary input — a pasted
  link you do not handle should become a search, not a failure.
- **Normalize the host before matching** (`lowercase()`, drop a leading `www.`) or the same link
  works or fails depending on where it was copied. Reject non-`http(s)` text before parsing too.
- **Decide the ambiguous case here, once.** A link carrying both an item and a collection has to
  resolve to one; deciding in the translator is what makes every caller agree.

## Verifying it

The parse entry point should have exactly one failure mode, and it should be `null`:

```bash
PARSER="path/to/YourParser.kt"
grep -nE "return null|throw |!!|require\(|checkNotNull\(" "$PARSER"
```

Every caller of a translator that can return `null` has to say what `null` means:

```bash
FN=toAppDeepLinkOrNull
grep -rn -A3 "\.$FN()" --include="*.kt" .
```

The two collection helpers are only correct over distinct elements, so look at what reaches them:

```bash
grep -rn -B2 "\.indexMap()\|symmetricDifference" --include="*.kt" .
```

Per hit, confirm the receiver holds ids rather than models and cannot repeat. No hits at all is its
own finding: a helper nobody calls is one nobody has checked either.
