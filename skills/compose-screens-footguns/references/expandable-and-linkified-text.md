---
name: expandable-and-linkified-text
description: Clamp long text to a few lines with a more/less affordance driven by measured overflow instead of a character count, and make timestamps or URLs inside the same text tappable. Use when "more" shows on text that already fits, never shows on text that does not, gets truncated along with the text, or when tapping a link expands the block instead of following the link.
---

# Expandable text, and tappable spans inside it

Two features that read as one and share no parts: clamping to N lines with a more/less affordance is
`maxLines` plus `onTextLayout { hasVisualOverflow }`; tappable substrings are `buildAnnotatedString`
plus `pushStringAnnotation`, hit-tested by character offset. They compete for the same tap, so
decide what a tap on the body means before writing either.

## Clamping on measured overflow

Only the layout pass knows whether the text overflows — the same string wraps differently per
width, font, text scale and translation. Ask it, and re-clamp by hand so the affordance is not
itself truncated:

```kotlin
// adapted: names shortened; the source's runCatching if/else (which re-called getLineEnd on the
// success branch) folded into getOrDefault, and its Character.isWhitespace(it) into it.isWhitespace()
var isExpanded by remember { mutableStateOf(false) }
var clickable by remember { mutableStateOf(false) }
var lastCharIndex by remember { mutableIntStateOf(0) }

Box(Modifier.clickable { isExpanded = !isExpanded }) {   // the only write to isExpanded
    Text(
        text = buildAnnotatedString {
            if (clickable) {
                if (isExpanded) {
                    append(text)
                    withStyle(showLessStyle) { append(showLessText) }
                } else {
                    val adjusted = text.substring(startIndex = 0, endIndex = lastCharIndex)
                        .dropLast(showMoreText.length)
                        .dropLastWhile { it.isWhitespace() || it == '.' }
                    append(adjusted)
                    withStyle(showMoreStyle) { append(showMoreText) }
                }
            } else {
                append(text)          // no overflow: no affordance at all
            }
        },
        maxLines = if (isExpanded) Int.MAX_VALUE else collapsedMaxLine,
        onTextLayout = { result ->
            if (!isExpanded && result.hasVisualOverflow) {
                clickable = true
                lastCharIndex = runCatching { result.getLineEnd(collapsedMaxLine - 1) }
                    .getOrDefault(text.length - 1)
            }
        },
    )
}
```

`maxLines` does the visual clamp on the first frame; the string surgery only exists so the "more"
label fits *inside* those lines instead of being cut off with them.

## Tappable spans

Tag the matches while building the string, then resolve a tap to a character offset and ask the
string what is annotated there:

```kotlin
// adapted: tag constants named, the two per-kind branches folded into one append
val timeRegex = Regex("""(\d+):(\d+)(?::(\d+))?""")
val urlRegex = Regex("""https?://\S+""")
val combined = Regex("${timeRegex.pattern}|${urlRegex.pattern}")
// walk combined.findAll(text): append the gap before each match, then the match itself
val tag = if (timeRegex.matches(match.value)) TAG_TIME else TAG_URL
builder.withStyle(linkStyle) {
    pushStringAnnotation(tag, match.value); append(match.value); pop()
}

Modifier.pointerInput(Unit) {
    detectTapGestures { offset ->
        val position = layoutResult?.getOffsetForPosition(offset) ?: return@detectTapGestures
        annotated.getStringAnnotations(start = position, end = position)
            .firstOrNull { it.tag.startsWith(TAG_PREFIX) }
            ?.let { onSpanClick(it.tag, it.item) }
    }
}
```

A timestamp span carries its own raw text (`"1:02:33"`), so the click handler — not the text
component — decides what it means: parse it and seek, or ignore it on a screen with no player.

## Traps

**Overflow is a measurement, not a length.** A "longer than 120 characters" heuristic is wrong at
every width but the one you tested, and again at a larger text scale. `hasVisualOverflow` arrives in
a layout callback: the clamp is right on frame one, the "more" label appears on the next.

**The affordance has to be cut out of the string.** `getLineEnd(lastVisibleLine)` gives the last
character that fits; appending "… more" pushes the line over and the label is what gets truncated.
Drop as many characters as the label costs, then trim trailing spaces and stops.

**Latched flags outlive their text.** `remember { mutableStateOf(false) }` with no key keeps
`clickable` and `lastCharIndex` from the previous string when the composable is reused for another
item — a short description then shows "more" and clamps at an index from a longer one. Key on text.

**A line index past the last laid-out line is not valid.** The callback fires for every layout the
text goes through, including ones with fewer lines than the clamp, so `getLineEnd(n)` needs a
guard and a fallback rather than an optimistic call.

**One tap, two handlers, and the outer one loses.** The container `clickable` in the first excerpt
*is* the entire expand affordance — the "more" label is painted text, not a button — so adding the
second excerpt's `detectTapGestures` to the same component means the text consumes the tap first:
tapping the body silently stops expanding, and only over the text. Pick one shape per component —
the whole block toggles and carries no spans, or the body owns the spans and a separate label toggles.

**Hit-testing snaps to the nearest character.** `getOffsetForPosition` returns the closest offset,
not "inside a glyph", so a tap in the blank space past the end of a line resolves onto the span that
ends it.

**Build the annotated string inside `remember(text)`.** Otherwise the regex scan runs on every
recomposition — and since `findAll` is a lazy sequence, calling `count()` on it inside the loop over
its own matches re-scans the whole text once per match.

**JDK character helpers are not multiplatform.** `Character.isWhitespace(c)` compiles in shared code
only while every target is JVM-family; `c.isWhitespace()` is the Kotlin one and always works.

## Verifying it

```bash
# every overflow-driven clamp in the codebase (a component with none is guessing at lengths)
grep -rn "hasVisualOverflow" --include="*.kt" .

# annotations written but never read, or read but never written, is a dead affordance
grep -rln "pushStringAnnotation" --include="*.kt" .
grep -rln "getStringAnnotations" --include="*.kt" .

# JDK-only character helpers sitting in shared source
find . -path "*/commonMain/*" -name "*.kt" -exec grep -ln "Character\." {} +
```

Then, by hand: shrink the window until a two-line string wraps to four and check that "more"
appears *and* that the text before it still ends mid-sentence rather than mid-label; expand and
collapse twice (a latched flag shows up on the second collapse); tap a link and confirm the block
did not also expand.
