---
name: word-timed-karaoke-lyrics
description: A per-word karaoke wipe driven straight off a ticking time source looks stepped instead of smooth, a word that was already fully sung stays lit after the user seeks backward past it, or skinning an existing line-level lyrics renderer for word-level highlighting leaves an unsynced sheet glowing white end to end. Use when building or debugging word-by-word lyric highlighting, a synced-transcript view, or any left-to-right text "fill" effect driven by a playback clock.
---

# Word-timed karaoke lyrics

A word-level lyric line only stores a **start time per word**; there is no end time in the data.
The renderer infers it as the next word's start time, falling back to the line's own end time (or a
guessed duration) only for the line's last word:

```kotlin
data class WordTiming(
    val text: String,
    val startTimeMs: Long,
)
```

Each word then animates its own "wipe" independently, driven by a wall-clock `Animatable` rather than
by reading the playback clock's value directly — that split is where most of the traps live. Above
the word layer, a line degrades through three tiers: word-level wipe when per-word timestamps parse,
a flat per-line highlight when only line timestamps exist, uniform dim text when there is no sync
data. Making the tiers look like a graceful downgrade, not three renderers bolted together, is the
other half of this skill.

## Traps

**Reading the playback clock's value straight into the wipe's progress is wrong in two directions.**
A time source that only emits every ~100ms produces a progress fraction that visibly steps instead
of gliding. The fix — an `Animatable` that snaps to the sampled fraction and then `animateTo(1f)` in
real wall-clock time — introduces the opposite bug: the animatable's raw `.value` now holds whatever
it last animated to, including after the word stops being "active." Seek backward past a word that
was already fully sung and its animatable is still sitting near `1f`; read it raw and the word lights
up before it has started. The fix is to never trust the animatable's value directly — derive the
exposed progress from the discrete state instead, and only feed the animatable on the two edges that
have a definite answer:

```kotlin
// adapted — collapsed from a multi-line `when`, with the surrounding block comment's reasoning
// folded into two inline comments that are not present in the source
val wordProgress = when {
    isPast -> 1f
    isActive -> progress   // the animatable — only trusted here
    else -> 0f             // future word: always zero, whatever the animatable holds
}
```

**Word duration needs both a floor and a shape, not one linear scale.** A word lasting 80ms of song
time animated in 80ms of wall-clock time is imperceptible — clamp the animation to a minimum (e.g.
150ms) and let the *next* word's `isPast` snap-to-`1f` catch up the small lag; matching the wipe
exactly to the data makes every short word invisible. Duration also needs the right curve, not a
bigger one: scaling one easing by "how long the word lasts" makes long held notes look flat —
backwards from how singing reads. Use two growth curves gated on duration relative to a reference
length: *cubed* below it (syllables get almost no emphasis), *square root* above it (a held note
plateaus instead of blowing out).

**Snapping a per-character effect on or off at each character's boundary reads as flicker.** If a
travelling highlight within a word is "character N is lit / character N is not," the light switches
off completely between one glyph and the next instead of handing over. Compute a continuous falloff
from the playhead's fractional position to each character's center, so brightness fades out of one
glyph as it fades into its neighbour.

**A glow that should bleed outside a glyph's box must not go through an alpha modifier.** Fading a
node's opacity forces it into an offscreen layer sized to the node's own bounds, clipping anything
meant to spill past that box — a bloom around a character gets sliced into a flat rectangle. Keep the
glowing text permanently composed and animate the *glow's own color alpha* instead of node opacity.

**A parse failure has to fall back to a line the same shape as its neighbours, not a shorter one.**
When per-word parsing fails on a single malformed line, falling back to a plainer, differently-styled
line item renders that one line at a different size than everything around it — worse than the
word-level effect just not firing. Fall back to the same visual shape with highlighting turned off.

**Copying a sibling renderer's "treat everything as current" boolean turns a whole page into one glow.**
A line-level renderer commonly renders an unsynced sheet with every line "bold" — `isCurrent = index
== currentLineIndex || syncType != "LINE_SYNCED"` — a reasonable default when "current" only toggles
a font weight. Reuse that OR-clause in a differently-skinned renderer where "current" also drives full
brightness, an active glow and zero blur, and every line in an unsynced sheet lights up simultaneously
— there's no "the sung line" without sync data, and the *other* renderer's convenience default said
otherwise. Check what "current" actually triggers before reusing a boolean across renderers.

**The check for "no active line yet" must run before the check for "this is the active line."** A
dedicated pre-roll treatment (uniform dim, unblurred, before the first cue) has to be evaluated first
in the branch that computes focus per line — read in the other order, every line compares
`distance == 0` against a sentinel index, and the *first* line looks active during the intro.

**Anchoring the active line to a fixed row offset from the top breaks the moment a line wraps.**
"Keep one physical text row of the previous line visible above the active one" is not the same as
scrolling to `activeIndex - 1`: a wrapped lyric is one list item spanning several rows, so anchoring
the *item* hangs the whole multi-row block above the active line instead of one row of it. Anchor the
active item itself and back off by one row's *height* in pixels, not by one list index — this still
needs the one-frame-wait-then-measure dance any "scroll to and align an item" helper needs; see
`lazy-scroll-helper-kit` for that half.

**Splitting a string into individual `Char`s to drive a per-character effect assumes one `Char` is
one glyph.** It is not, for any text that contains a combining mark or a character outside the Basic
Multilingual Plane — see `combining-chars-break-char-literals`. A per-character wipe or glow built
on `word.toCharArray()` is safe for plain Latin lyrics and silently wrong the moment a word contains
a combining accent or vowel sign, which renders as its own, separately-colored cell next to an
incomplete base glyph instead of as part of one character. When the effect doesn't need per-character
timing, `text-brush-shimmer-sweep` gets a travelling highlight with no per-`Char` split at all, by
animating a gradient directly on the `TextStyle`.

**A rich-synced line's raw string still carries its inline per-word timestamps — any secondary
consumer must strip them first, or it processes the markers instead of the words.** The renderer
needs the raw `<mm:ss.xx>` markers to drive the wipe, but nothing else reading that same string does:
romanization strips them before handing the line to the romanizer (`LyricsView.kt:453`), and the
share sheet strips every line the same way before flattening it to plain text
(`ShareLyricsLines.kt:16`). Both call one shared helper, `stripRichSyncTimestamps()`
(`NowPlayingContentState.kt:56`: replace each `<mm:ss.xx>` marker with a space, collapse whitespace,
trim) rather than rolling their own regex — a new reader of a rich-synced line owes it that same call.

## Verifying it

Run from the root of the mined repository (adapt file names to your own):

```bash
# 1. the timing model stores only a start time; the end is computed downstream, not stored
grep -n "data class WordTiming" -A3 composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/extension/RichSyncParser.kt
grep -n "wordEndTimeMs =" composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/LyricsView.kt

# 2. progress is derived from discrete state, never read raw off the animatable
grep -n "val wordProgress" -A6 composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/LyricsView.kt

# 3. the pre-roll branch is checked before the "this is the active line" branch
grep -n "!hasActiveLine ->" -A3 composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/AppleMusicLyricsLines.kt

# 4. the two sibling renderers disagree about the OR-clause, on purpose
grep -n "NOT Classic's" -A7 composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/LyricsView.kt

# 5. a parse failure falls back to the SAME-shaped line item, not a smaller one
grep -n "Parsing failed" -A3 composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/LyricsView.kt
```

Pass condition for 1–2: `WordTiming` has no end-time field, and `wordEndTimeMs` is a local `val`
computed per word, not a property read off the parsed model. For 3: `!hasActiveLine` is the first
arm of the `when`. For 4: the comment names the exact clause being deliberately omitted. For 5: the
fallback constructor is the style-matching one (`AppleMusicLyricsLineItem`), not the plain one.

Then by hand: play a rich-synced line and confirm the wipe never steps; seek backward into a sung
line and confirm no word lights early; open an unsynced song and confirm nothing looks "active."
