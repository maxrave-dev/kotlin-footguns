---
name: structural-defensive-parsing
description: Reading a response whose shape drifts — classify each field by the marker the payload itself declares rather than by its position, treat a filtering map as data loss and count what it drops, refuse to substitute a placeholder for a failed parse, and parse composite strings from their stable end. Use when a parser works in one locale and not another, when a list arrives shorter than the source shows, or when a made-up value turns up somewhere it was never entered.
---

# Let the payload say what it is

When you consume an unofficial or unstable API, the response is a rendering of somebody's UI, not a
contract: rows are laid out differently depending on what the row *is*, and the layout changes
without notice. Never ask "which column is this" — ask "what does it say it is".

```kotlin
// adapted — every field and constant is renamed to a neutral equivalent (`columns`, `link`, `kind`,
// `KIND_ARTIST`, `ID_PREFIX_RELEASE`); the source's provider-specific names are not reproduced. The
// branch structure, the fallback order and the ordering of the text checks are unchanged.
internal enum class RunType { RELEASE, CREATOR, DURATION, YEAR, COUNT }

internal fun classifyRun(run: Run): RunType {
    val linkId = run.link?.target?.id                      // a linked run names itself
    if (linkId != null) {
        return if (linkId.startsWith(ID_PREFIX_RELEASE)) RunType.RELEASE else RunType.CREATOR
    }
    val text = run.text                                    // only unlinked runs need guessing,
    return when {                                          // cheapest and most certain first
        DURATION_REGEX.matches(text) -> RunType.DURATION
        YEAR_REGEX.matches(text) -> RunType.YEAR
        parseCount(text) != null -> RunType.COUNT
        else -> RunType.CREATOR                            // an unlinked name, no page to link to
    }
}

internal fun findColumns(row: Row): Columns {
    var titleIndex: Int? = null; var creatorIndex: Int? = null; var releaseIndex: Int? = null
    var durationIndex: Int? = null; var unrecognizedIndex: Int? = null
    val channelIndexes = mutableListOf<Int>()
    for (index in row.columns.indices) {
        val run = row.columns[index].renderer.text?.runs?.firstOrNull() ?: continue
        val link = run.link
        if (link == null) {
            when (classifyRun(run)) {
                RunType.DURATION -> durationIndex = index
                // only the first; later unlinked columns are metadata, not names
                else -> if (unrecognizedIndex == null) unrecognizedIndex = index
            }
            continue
        }
        if (link.play != null) { titleIndex = index; continue }
        when (link.target?.kind) {
            KIND_ARTIST -> creatorIndex = index
            KIND_RELEASE, KIND_LONGFORM -> releaseIndex = index
            KIND_CHANNEL -> channelIndexes.add(index)
        }
    }
    if (creatorIndex == null) creatorIndex = unrecognizedIndex          // not clickable
    if (creatorIndex == null) creatorIndex = channelIndexes.lastOrNull() // non-music item
    return Columns(titleIndex, creatorIndex, releaseIndex, durationIndex)
}
```

## Traps

**A positional guess forces a second, worse guess.** Assume "the creator is column 1" and you find
that column also holds the release and a play count, joined by separators — so the count has to be
filtered back out by matching the word for "views". That word is localised, the formatting is
localised, and some scripts write it with no separator at all, so the filter works in the language it
was written in and leaks a play count into the creator's name everywhere else. Identify the column
structurally and the problem disappears instead of being papered over: the right column contains only
creators, so nothing needs filtering. Stepping by two over a column's runs is the same assumption in
miniature — it holds only while values and separators alternate, so classify every run and keep what
you want rather than trusting the stride.

**Absent is a shape, not a failure.** No linked release, an unavailable item, an extra column — all
normal. Model "which column holds what" as nullable indices and read null as *absent*; a parser that
errors on a shape it has merely not seen drowns the signal you need when the format does change.

**Have a fallback order, and write down what each fallback is for.** Here: the declared marker, then
the first unclassifiable column (a name with no page to link to), then the *last* channel-style column
(a non-music item lists channels, not creators). Fallbacks with no recorded reason get "simplified"
into one, and the case that needed the odd one out breaks silently.

**A filtering map is silent data loss.** `mapNotNull` over rows is the most common way an entire
class of items disappears with no exception, no log line and no failed request — the list is simply
shorter than the source shows. It happens whenever the source wraps some rows in an extra layer:
reading only the bare shape yields null for every wrapped one. The tell in existing code is an
accessor written as `bare ?: wrapped.primary` — it exists because someone found this the hard way.
Read *both* shapes there, and never let a filtering map be the last word:

```kotlin
val items = rows.mapNotNull { it.toItem() }
if (items.size != rows.size) Logger.w(TAG, "dropped ${rows.size - items.size} of ${rows.size} rows")
```

Wrapping can also be conditional on request context — authenticated and anonymous responses need not
have the same shape — so a parser tested one way may be losing most of its rows the other way.

**Never invent a placeholder for something you failed to read.** A literal `"Album"` or `"Unknown"`
does not stay in the parser: it is stored, displayed, published to whatever reads that metadata, and
indistinguishable from a real value forever after. Use null. If the value does exist elsewhere in the
payload — often in the column's own text, not the menu carrying only an id — read it from there.

**Parse composite strings from the stable end — and fix every copy.** In `H:MM:SS` the seconds are
always last and the hours only sometimes first, so walk the parts in reverse multiplying by 1, 60,
3600. The left-to-right form is the classic bug here: `parts[0] * 60 + parts[1]` reads an hour-long
duration as a minute-long one and throws outright on a string with no separator, because it indexes a
one-element list. These helpers also get duplicated — one in the service layer, one in the data layer
— and a fix lands in whichever one's bug was reported, so grep for the *pattern*, not the name.

**Guard a text heuristic at both ends and say why.** A count parser that strips a leading localised
word must not strip anything when the text contains Latin letters — else a name like "Maroon 5"
becomes a number — and must reject a bare ASCII token with no space, or a name beginning with a digit
parses as a count. Both guards look removable; each holds up a real case.

**Spell invisible characters as escapes.** Bidirectional control marks, non-breaking spaces and
full-width punctuation belong in a pattern as `\uXXXX`; written literally they are invisible in a
diff, and one stray paste silently changes what the pattern matches.

## Verifying it

```bash
find . -path '*/parser/*' -name '*.kt' -not -path '*/build/*' -exec grep -cH 'mapNotNull' {} +
find . -path '*/parser/*' -name '*.kt' -not -path '*/build/*' \
  -exec grep -nE 'getOrNull\([0-9]+\)|\[[0-9]+\]' {} +
find . -path '*/parser/*' -name '*.kt' -not -path '*/build/*' -exec grep -nE '\* *60 *\+' {} +
```

Use `find … -path` rather than a `**` glob: with globstar unset, `**` is an error the shell reports
before the search runs, and an error producing no output reads exactly like a clean result. The first
is then the data-loss census — every non-zero file is a place rows can vanish, and each needs either
a size comparison or a written reason it cannot drop anything. The second finds positional reads: a
numeric index into a runs or columns list is a guess, and each hit is either a documented invariant
or the first trap above. The third finds left-to-right duration parses — it also matches comments
*describing* the bug, so read the hits rather than counting them; a codebase with the fix documented
in one module and the bug live in another looks clean at a glance.

For the classification itself, the test that matters is a fixture per row *variant* — a plain row,
one with the extra column, an unavailable one, one with no linked release, and one captured from an
authenticated session — asserting the resolved fields **and** the row count. A set holding only the
common shape passes on a parser that drops most of the real data. Related:
`response-to-domain-flow` is where this layer sits; `enum-normalize-over-legacy-data` covers the
markers it reads.
