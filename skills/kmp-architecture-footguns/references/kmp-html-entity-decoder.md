---
name: kmp-html-entity-decoder
description: Decode named, hexadecimal and decimal character entities in shared multiplatform code, where the platform's own markup helpers are unavailable. Covers the named table, the two numeric passes, the range check that keeps an out-of-range code point from ending the operation, why running the passes in one order over-decodes, and the rule that decoding happens once and at a boundary. Use when entity text such as `&#39;` or `&amp;` reaches the screen undecoded, when text decoded twice loses characters a user typed, or when a large code point stops the parse.
---

# Decoding character entities without a platform helper

Platform markup helpers live on one target and usually do more than you want — they also strip
tags. In shared code the whole job is a small table plus two regular expressions, and it belongs in
the lowest module both the parser and the presentation layer already depend on:

```kotlin
// adapted — the case-insensitive hex marker and the code-point helper are the corrected shape; the
// source matches only lowercase `x` and calls the `Char` constructor directly (see the traps)
fun decodeEntities(text: String): String {
    var result = text
    for ((entity, char) in NAMED) {
        result = result.replace(entity, char, ignoreCase = true)
    }
    result = Regex("""&#[xX]([0-9a-fA-F]+);?""").replace(result) { m ->
        m.groupValues[1].toIntOrNull(16)?.let { codePointToString(it) } ?: m.value
    }
    result = Regex("""&#(\d+);?""").replace(result) { m ->
        m.groupValues[1].toIntOrNull()?.let { codePointToString(it) } ?: m.value
    }
    return result
}
```

`toIntOrNull` is what keeps a run of digits longer than an integer from ending the operation: it
answers null on overflow and the match falls through to its own text unchanged. That guard is
necessary and it is not sufficient — see the first trap.

## Traps

**A code point above the 16-bit range ends the operation.** `Char(code: Int)` in the Kotlin standard
library throws when `code` is outside `Char.MIN_VALUE.code..Char.MAX_VALUE.code`; the documentation
on that function says so and the body is an explicit range check. So `&#128512;` — an emoji, well
inside what a user can type into any text field — parses cleanly as an integer and then stops the
decode. Anything above `0xFFFF` has to become a surrogate pair, and the conversion has to be written
out because the convenient helpers for it are platform-only:

```kotlin
// adapted — the surrogate branch is prescribed; the source has only the first case, unguarded
private fun codePointToString(cp: Int): String? = when {
    cp in 0..0xFFFF -> Char(cp).toString()
    cp in 0x10000..0x10FFFF -> {
        val v = cp - 0x10000
        charArrayOf(Char(0xD800 + (v shr 10)), Char(0xDC00 + (v and 0x3FF))).concatToString()
    }
    else -> null   // out of Unicode range: leave the match verbatim
}
```

`CharArray.concatToString()` is in the shared standard library, so this stays in common code.

**Running the named pass first decodes two layers in one call.** The table is iterated in insertion
order — `mapOf` builds a linked hash map — so if the ampersand entity is listed before the
angle-bracket ones, the input `&amp;lt;` becomes `&lt;` on that iteration and then `<` a few
iterations later. The same happens with the numeric passes: `&amp;#39;` becomes `&#39;` and then an
apostrophe. Text that was correctly encoded twice comes back decoded twice, and a literal ampersand
a user typed in front of entity-shaped text is destroyed. There are two honest fixes and they are
not the same:
- **Run the ampersand substitution last of all the passes** — after the numeric ones, not merely
  last in the named table. Everything it emits is re-read by every pass that follows it, and the
  numeric passes follow the whole table, so moving it to the end of the table alone still lets
  `&amp;#39;` decode all the way to an apostrophe.
- **Scan once** — walk the string, and at each `&` decide what the run is and emit the replacement
  into a builder, never re-reading emitted output. This is the only version where one layer per
  call holds structurally rather than by ordering, and it is also the faster one, because the
  pass-per-entity shape rewrites the whole string once per table row.

**Case sensitivity has to match between the table and the regular expressions.** With
`ignoreCase = true` on the table replace, any hexadecimal entity that also appears in the table
decodes in either case, while every other hexadecimal entity decodes only in the case the pattern
allows. If the pattern is written `&#x([0-9a-fA-F]+);?`, then `&#X41;` matches nothing and reaches
the screen verbatim while `&#x41;` decodes — a difference invisible in review and invisible in tests
that only use lowercase input. Put `[xX]` in the pattern, and treat `ignoreCase` on the table as
covering only the letters of the *names*.

**An optional trailing semicolon makes the decoder greedier than the format.** `;?` with a greedy
digit run means `&#65` decodes with no terminator at all, so ordinary prose containing that shape is
rewritten. Real encoders always emit the semicolon. Accept the un-terminated form only if you have
seen a producer that omits it, and if you do, keep it out of the *named* table — a name without a
terminator has no unambiguous end.

**The table is a fixed list, so everything outside it survives verbatim.** Numeric passes cannot
rescue a named entity, because a name carries no number. Decide deliberately whether the handful of
names you list is the set your inputs actually contain, and print the survivors rather than
guessing — over captured responses or saved fixtures, never over your own source, where the only
hits are the table itself. Subtract the names the table lists; the rest reaches the screen raw:

```sh
grep -rEo '&[a-zA-Z][a-zA-Z0-9]{1,10};' <fixtures-dir> | sed 's/.*://' | sort -u
```

**Decode once, at the boundary, after parsing — not before.** Two separate rules, and both are
routinely broken:
- *Once.* When a parser decodes a field and a later layer decodes the same field again, everything
  in the over-decoding trap above happens on that path. Two layers each decoding "defensively" is
  how a literal ampersand a user typed disappears. Pick the layer that first turns bytes into your
  model, decode there, and make every layer above it assume decoded text.
- *After parsing.* Decode the captured field, never the raw line. A decoder run first can
  manufacture the delimiters the parser is about to look for — `&#91;` is an opening square
  bracket, and a format that marks records with square brackets will then find a record that was
  never in the input.

**Decoding is not sanitizing.** This function turns entity text back into the characters it stood
for, which is the opposite of escaping. Decoded text must never be concatenated into markup, a
query, or a shell command — decode at the edge of your own model and escape again on the way out.

## Verifying it

1. **Confirm there is exactly one decoder** and that shared code is not reaching for a platform one:
   ```sh
   grep -rn "fun decodeEntities\|fun decodeHtmlEntities" --include='*.kt' .
   ```
   One definition. Then check no caller imports a platform markup helper alongside it.
2. **Find every call site and check none of them stack**:
   ```sh
   grep -rn "decodeEntities(\|decodeHtmlEntities(" --include='*.kt' . | grep -v "fun decode"
   ```
   Read each hit and ask what produced the string. A parser hit and a state-layer hit on the same
   field means that field is decoded twice.
3. **Confirm the numeric passes cover both cases of the hexadecimal marker**:
   ```sh
   grep -rn "&#x(\[0-9a-fA-F\]\|&#\[xX\]" --include='*.kt' .
   ```
4. **Assert the single-call result against a hand-written expected value**, because one call must
   remove exactly one layer: `decode("&amp;lt;")` must equal `"&lt;"`, `decode("&amp;#39;")` must
   equal `"&#39;"`, and `decode("a & b")` must come back unchanged. The pass-per-entity shape fails
   the first two, answering `"<"` and `"'"`.
   Do **not** round-trip the decoder against itself instead. `decode(decode(s)) == decode(s)` holds
   on all three inputs *for the defective decoder* — the over-decode finishes inside the first call,
   so its output is already a fixed point — and it fails on a correct one, which peels a layer each
   time it is called. Idempotency is the wrong property, and testing for it signs off the bug.
5. **Feed it an emoji entity** (`"&#128512;"`) and a beyond-Unicode one (`"&#1114112;"`). The first
   must produce the character, the second must come back verbatim, and neither may end the operation.
