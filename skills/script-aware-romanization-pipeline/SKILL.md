---
name: script-aware-romanization-pipeline
description: Adding a "show pronunciation" or transliteration feature across many non-Latin scripts in a Kotlin Multiplatform module — without pulling in ICU — needs a per-script dispatch built on Unicode block ranges rather than a locale, one line at a time rather than one song at a time, and a hard line between scripts that reduce to a table and the one or two that need a real dictionary. Use when a transliteration result is guessed for the wrong language, an unsupported platform fails outright instead of falling back, or a line that mixes two scripts (an original lyric plus an English aside) picks the wrong one.
---

# A script-aware romanization pipeline

One entry point takes a line of text and a set of enabled languages, and returns a Latin-script
reading of that line or `null`:

```kotlin
// adapted — LyricsRomanizer.romanize's multi-line signature, collapsed to one line here
fun romanize(line: String, enabled: Set<RomanizationLanguage>): String?
```

Everything interesting is in how it decides *which* of several very different transliteration
strategies to run, per **line**, not per song: a lyric sheet routinely interleaves an original-script
line with a plain-English one, and romanizing the English half produces nonsense. Detection therefore
runs fresh on every line, and the twelve supported languages split cleanly into two families —
arithmetic/table scripts that need nothing beyond `commonMain`, and two scripts (Japanese, Chinese)
whose readings genuinely depend on surrounding words and therefore need a real dictionary behind an
`expect`/`actual` boundary. Getting that boundary as narrow as possible is most of the design.

## Traps

**Detecting script by Unicode code-block ranges works — but only in a specific order, not any
order.** A block-range test (`char in '぀'..'ヿ'` for kana, and so on for Han, Hangul,
Devanagari, Gurmukhi, Cyrillic) needs no ICU and no locale, but a Japanese line is written mostly in
kanji with only a few kana particles — counting characters and taking a majority calls it Chinese.
The fix is a priority order, not a count: kana anywhere at all proves the line is Japanese (Chinese
text contains none), so the kana check must run, and win, before the Han check. Any per-script
detector built from "which characters are present" needs this kind of precedence rule wherever two
scripts' ranges can co-occur in the same line.

**One Unicode block can hold several languages that romanize differently, and the block alone cannot
tell them apart.** Seven Cyrillic-alphabet languages here share one range. Resolving *which* one a
line is in has to come from letters each language has that the others do not — ordered
**most-distinctive first**: two languages that share almost their whole alphabet except for one
language's few unique letters must have those unique letters checked before the shared ones, or the
shared letters match first and the unique ones never get a chance. Skip the disambiguation step
entirely when only one candidate language is enabled — there is nothing to guess, and running a
letter-frequency heuristic on a known-single-language line only risks getting it wrong for no reason.
When nothing distinctive matches, fall back to a single hardcoded default, not a computed "closest
alphabet" comparison: the source reaches for Russian specifically — its own comment calls it the most
common of the seven and the one carrying none of the others' unique letters — and only when Russian
itself is not enabled does it fall through to `cyrillicEnabled.first()`, whichever language that
happens to be in iteration order, with no comparison run at all (`RomanizationLanguage.kt:71-73, 99`).

**A script that looks alphabetic can still be an abugida, and a lookup table alone cannot transliterate
one.** Devanagari and Gurmukhi consonants carry an inherent vowel that a following mark can replace or
delete — a plain `Map<Char, String>` gets the base consonant right and the vowel wrong on every
syllable that isn't the default case. This needs a small state machine reading one character of
lookahead, not a bigger map; see `combining-chars-break-char-literals` for the specific complication
this creates once one of those marks is a combining character rather than its own letter.

**Only make a script's transliteration depend on a real dictionary when the rule genuinely cannot be
local to one character.** Two of twelve languages here need a platform library — Japanese, because a
kanji's reading depends on the word it's in, and Chinese, because some characters are heteronyms whose
pronunciation depends on the surrounding word. Every *other* script resolves per character or by pure
arithmetic and needs nothing beyond `commonMain`: a syllabic script's alphabet is a small map, and a
syllable-block script decomposes with integer arithmetic instead of a table at all
(`(codepoint - base) / consonantCount / vowelCount`, or similar, covers the whole script from three
short tables). Reach for a dictionary only for cross-word disambiguation and morphology — properties a
per-character table cannot express by construction. Even where a dictionary IS used, a heteronym
looked up one character at a time returns several valid readings with no ranking between them —
taking the first is a guess; the honest fix is a word-aware lookup, not tuning which array index gets
picked.

**A dictionary-backed language can still be a two-stage pipeline where only the first stage needs the
dictionary.** Getting from kanji to a phonetic reading needs a real morphological analyzer; getting
from that reading to a Latin-script one is still pure table lookup plus a little lookahead — so it
belongs in shared, dictionary-free code, testable without the platform dependency the first stage
needs. Collapsing both into "the platform-specific implementation" denies every other platform a stage
it could have run itself.

**Inside that shared table-lookup stage, a multi-character token must be tried before its own prefix
is tried alone.** A syllable spelled with two characters that together make one sound is a single
token in the output table; matching one character at a time first consumes the first of the pair as
its own (wrong) sound and leaves the second stranded. Check known multi-character sequences starting
at the current position *before* falling back to the single-character table, every time the read
position advances — the shorter match is not a safe default merely because it comes first in a naive
loop.

**Every reason a romanizer might have "nothing to add" should collapse to one signal, not several.**
A line already in Latin, a language switched off in settings, a platform with no library for that
script, and a transliteration that happens to equal its own input are four situations with the same
correct behavior: show nothing extra. Returning `null` for all four — rather than throwing for the
unsupported-platform case — lets every caller be one `if (result != null)` instead of a `when` over
failure reasons, and lets a platform ship with a script's dictionary simply absent, not stubbed.

**"The dictionary is not downloaded yet" and "this platform has no dictionary at all" should be the
same return value, not two.** A library that ships its dictionary as an on-demand download has a
window where the feature is temporarily unavailable rather than permanently unavailable — resist the
urge to add a third state for it. Returning the same `null` for "not ready yet" as for "not supported
here" means every caller that already handles the permanent case handles the temporary one for free,
with no extra branch anywhere — see `on-demand-dictionary-asset` for the provider side of this same
null, where the download-not-finished check actually lives.

**Two consumers that both need to answer "is this character script X" must call the same function, not
duplicate the range check.** A script detector and a per-character transliterator over the same script
are tempting to write as two separate range checks — one per change that touches either. Duplicated
tests drift the moment one is edited without the other; a single shared predicate cannot.

**A specific third-party formatting flag combination throws instead of formatting.** A romanization
library asked for both diacritic tone marks and a particular "how to spell a Latin letter with no
Latin equivalent" option throws a checked exception rather than silently producing something wrong —
worth knowing before it surfaces from production traffic instead of from reading the docs. Confirm the
exact incompatible pairing for your own formatting library before wiring up every option combination.

## Verifying it

Run from the root of a Kotlin Multiplatform module with a similar split (adapt file names):

```bash
# 1. the platform-specific surface really is just the two dictionary-dependent functions
grep -n "expect object\|fun " service/lyricsService/src/commonMain/kotlin/org/simpmusic/lyrics/romanization/PlatformRomanizer.kt

# 2. the platform with no library at all still compiles — both functions just return null
grep -n "actual fun" service/lyricsService/src/iosMain/kotlin/org/simpmusic/lyrics/romanization/PlatformRomanizer.ios.kt

# 3. script detection order: kana is checked (and wins) before Han
grep -n "fun detectScript" -A8 service/lyricsService/src/commonMain/kotlin/org/simpmusic/lyrics/romanization/RomanizationLanguage.kt

# 4. same-block disambiguation: single-candidate shortcut, then most-distinctive-first ordering
grep -n "size == 1" -A6 service/lyricsService/src/commonMain/kotlin/org/simpmusic/lyrics/romanization/RomanizationLanguage.kt

# 5. the two-character token is tried before the single-character table, every position
grep -n "val pair = \|val youon = \|val single = " service/lyricsService/src/commonMain/kotlin/org/simpmusic/lyrics/romanization/KanaRomanizer.kt

# 6. the incompatible formatting combination is a real, catchable exception type (adjust the jar glob to your formatting library)
JAR=$(find ~/.gradle/caches -iname "pinyin4j-*.jar" ! -iname "*sources*" ! -iname "*javadoc*" | head -1)
javap -p -classpath "$JAR" net.sourceforge.pinyin4j.format.exception.BadHanyuPinyinOutputFormatCombination
```

Pass condition for 1: exactly two function signatures inside the `expect object`. For 2: both
`actual fun` bodies are a bare `null`, no imports of a native library. For 3: the kana check is the
first line in the function, before the Han check. For 4: a `size == 1` early return precedes a list
literal whose comment says "most-distinctive first." For 5: `pair` and `youon` are computed and
checked before `single` is even read. For 6: `javap` prints the exception class — confirming it is a
real, named type the calling code can be shown to guard against, not a hypothetical.
