---
name: combining-chars-break-char-literals
description: A Devanagari, Gurmukhi, or other diacritic-marked letter that looks like one glyph in the editor fails to compile as a `'x'` character literal with "Too many characters in a character literal," because it is a base letter plus a separate combining mark — two `Char`s, not one. Use when a lookup table keyed by `Char` needs an entry for a marked or accented letter outside plain Latin, or when per-character text processing garbles exactly the words that carry an accent.
---

# Combining characters break `Char` literals

Kotlin's `Char` is documented, precisely, as "a 16-bit Unicode character" — one UTF-16 code unit. A
single letter a reader perceives as one character can need *two* of them: a base letter followed by
a separate combining mark that is rendered on top of it. क़ (Devanagari "qa") is क (KA) plus a
combining nukta sign — two code points, two `Char`s — and `'क़'` does not compile as a character
literal at all. The same wall applies, for an unrelated reason, to any single code point outside the
Basic Multilingual Plane: it needs a surrogate *pair* to represent in UTF-16, so it is also two
`Char`s masquerading as one glyph — see `kmp-html-entity-decoder` for the worked branch that turns a
decoded code point above `0xFFFF` back into that pair.

## Traps

**A map keyed by `Char` cannot hold an entry for a combining sequence — the literal itself fails to
compile.** Perso-Arabic loanword sounds in Hindi are written as a base consonant plus a nukta; the
source here handles it not by trying `'क़' to "q"` (which is rejected outright) but by keeping the
nukta as its **own** `Char` constant and treating it as a modifier the lookup consumes separately:

```kotlin
private const val DEVANAGARI_NUKTA = '\u093C'

// ... GURMUKHI_VIRAMA/NUKTA and the whole DEVANAGARI_CONSONANTS map sit between these two
// declarations in the real file — this is two separate excerpts, not one contiguous block.

private val DEVANAGARI_NUKTA_FORMS: Map<Char, String> =
    mapOf(
        'क' to "q", 'ख' to "kh", 'ग' to "gh", 'ज' to "z",
        'ड' to "r", 'ढ' to "rh", 'फ' to "f",
    )
```

Every key in that map is the plain **base** consonant; the mark is looked up as a peek at the next
index in the string, never as part of the key. The mark on its own compiles fine as a literal — it is
only the base-plus-mark *pair* that a single `Char` cannot hold.

**Most accented letters are a single precomposed `Char` — this skill is about combining sequences,
not diacritics in general.** Vietnamese ế/à/ộ and friends are each ONE code point in their normal
(NFC) form — U+1EBF fits one UTF-16 unit, so `'ế'` compiles as an ordinary literal, and this
codebase's romanizer has no Vietnamese support at all. The two-`Char` wall is specific to scripts
whose *usual* representation keeps a mark separate from its base, or to text arriving pre-decomposed
(NFD) from an external source — a real hazard, but a run-time one, since nobody writes a decomposed
sequence as a source-code literal. Check whether your script's normal encoding is precomposed before
assuming anything below applies to it.

**The stdlib DOES answer "is this a combining mark" in common code — but not "what does this mark
do," and that gap is why the marks below are hardcoded constants, not a lookup.** `kotlin-stdlib`'s
`commonMain` ships `public expect val Char.category: CharCategory`, with `NON_SPACING_MARK`,
`COMBINING_SPACING_MARK` and `ENCLOSING_MARK` among its values — no ICU, no platform split, available
to the same pure-Kotlin-Multiplatform module discussed in `script-aware-romanization-pipeline`. A
generic "is this code point a combining mark" test is one property read away. What `category` cannot
give you is grapheme-cluster segmentation (UAX #29: how many marks attach to this base, where one
displayed character ends) or which-mark/what-it-does semantics — knowing a code point IS a mark says
nothing about whether it is a nukta that changes a consonant's sound or a vowel sign that doesn't. So
the marks a script uses are hardcoded constants instead: exactly four here (`DEVANAGARI_VIRAMA`,
`GURMUKHI_VIRAMA`, `DEVANAGARI_NUKTA`, `GURMUKHI_NUKTA` — two viramas, two nuktas). The vowel signs
that also modify a consonant are not constants at all; they live in `DEVANAGARI_MATRAS`/
`GURMUKHI_MATRAS` maps and are recognized with `containsKey`, matched by equality either way rather
than by asking `category` a question it cannot answer specifically enough.

**The fix is an index-walking loop over the `String`, never a `for (c in text)` or a per-`Char` `map`
lookup.** Once one script needs "peek at the next code unit before deciding what this one means," the
whole routine has to be a hand-rolled `while (index < text.length)` that advances by a variable amount
— one step for an unmarked letter, two when a combining mark follows it. A `Map<Char, String>` applied
character-by-character has no way to look ahead, so it can only ever see the base letter and never the
mark that changes it.

**Any other place that splits a string into individual `Char`s to process them one at a time inherits
this exact hazard, not just lookup tables.** A karaoke-style renderer that colors or animates a word
one glyph at a time by calling `word.toCharArray()` and creating one text node per entry — see
`word-timed-karaoke-lyrics` — will, for the same underlying reason, split a base letter from its
combining mark into two independently-styled cells instead of one. The mark carries no width of its
own, so it does not fail loudly; it just renders as a stray accent beside an incomplete letter, or
overlapping the next one. The failure mode is different from a compile error, but the cause is
identical: treating "one `Char`" as a proxy for "one displayed character."

**String slicing and truncation by index inherit the same hazard.** `text.take(n)` or `text.substring`
cut at a `Char` boundary, not a grapheme boundary — truncating a preview or an ellipsis at a fixed
length can just as easily land in the middle of a base-plus-mark pair (or a surrogate pair) as any
other loop that walks a string one `Char` at a time, silently dropping the mark and leaving the bare
base letter in the truncated output.

## Verifying it

Commands 1–4 run from the module root containing the romanizer (a git submodule in the mined
repository, hence a separate root from command 5's):

```bash
# 1. locate the workaround's stated REASON — a source comment, not yet a verified compiler fact
# (that's check 6, below)
grep -n "Kotlin rejects it outright" -B2 service/lyricsService/src/commonMain/kotlin/org/simpmusic/lyrics/romanization/IndicRomanizer.kt

# 2. the nukta map is keyed by the BASE consonant, never by the composed grapheme
grep -n "DEVANAGARI_NUKTA_FORMS" -A4 service/lyricsService/src/commonMain/kotlin/org/simpmusic/lyrics/romanization/IndicRomanizer.kt

# 3. the mark alone compiles as a literal; it's only paired with a base that it cannot
grep -n "DEVANAGARI_NUKTA = \|GURMUKHI_NUKTA = " service/lyricsService/src/commonMain/kotlin/org/simpmusic/lyrics/romanization/IndicRomanizer.kt

# 4. the module never reaches for Char.category either, despite it being available (expect: no output)
grep -rn "\.category\|CharCategory" service/lyricsService/src/commonMain/
```

Command 5 runs from the app repository root instead — the renderer using this pattern lives outside
the romanizer's own module:

```bash
grep -n "toCharArray()" composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/LyricsView.kt
```

Commands 6–7 are independent of both — they read whichever Kotlin compiler and stdlib sources jars
Gradle has already cached, from anywhere:

```bash
# 6. the quoted compiler diagnostic is real, not paraphrased
JAR=$(find ~/.gradle/caches -iname "kotlin-compiler-embeddable-*.jar" ! -iname "*sources*" | head -1)
unzip -p "$JAR" 2>/dev/null | strings | grep -i "character literal"

# 7. the "16-bit" claim the whole skill rests on
JAR=$(find ~/.gradle/caches -iname "kotlin-stdlib-*-sources.jar" ! -iname "*jdk*" ! -iname "*common*" | head -1)
unzip -p "$JAR" commonMain/kotlin/Char.kt | grep -n "16-bit"
```

Pass condition for 1–3: the excerpts above appear verbatim (the phrase in check 1 wraps across the
comment's own line break, so it is matched on a same-line fragment rather than the full sentence).
For 4: nothing prints — absent, and the trap above explains why `category` alone is not enough, not
that it is unavailable. For 5: a real, distinct occurrence of the same one-`Char`-per-cell pattern, in
an unrelated file. For 6: `Too many characters in a character literal` appears in the compiler's own
message table — the check that check 1 alone was missing, confirming the quoted diagnostic is real. For
7: `/** Represents a 16-bit Unicode character. */` — the authoritative version of the claim this whole
skill rests on.
