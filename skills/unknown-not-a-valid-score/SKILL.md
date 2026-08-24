---
name: unknown-not-a-valid-score
description: A parse-failure fallback must be a sentinel outside the legal domain, or expressed in the type — never a value the success path can also produce. Expose "not known" as its own question. Use when a field means two different things depending on where it came from, when a placeholder reaches the screen, or when a consumer cannot tell absent from measured.
---

# "Could not parse" is not a value

Every fallback in a parser answers a question the caller will ask later. `?: 0` answers "how many"
with a number that means both *zero of them* and *the parser gave up*. `?: ""` answers "which one"
with a string that means both *none* and *unreadable*. The two meanings then travel together
through every consumer, and each consumer has to guess — differently.

There are only three honest fallbacks:

1. **A sentinel the success path can never produce** — a negative where the domain is
   non-negative, `MAX_VALUE` where the domain is a real measurement.
2. **Absence in the type** — `null`, or an `Unknown` case in a sealed hierarchy.
3. **No fallback at all** — fail the parse and let the caller decide.

Absence in the type is the one that cannot be misread, because the compiler makes every consumer
say what it wants to happen. Reach for a numeric sentinel only where a nullable type is genuinely
not available — a database column, a fixed-width protocol field, an interface you do not own.

## Traps

**A sentinel that is legal in the *type* is not a sentinel.** `-1L` is not a valid position, so
parking a position field at `-1L` looks safe — and it is safe only while every reader agrees. The
source project's own record describes what happened once that agreement broke: one branch wrote
`-1L` to mean "no position", a second ignored negative values entirely and so never overwrote it, a
third restored the neighbouring total without touching it, and the single formatter rendered any
negative as a placeholder. The screen showed a correct total next to a placeholder that never
cleared, because nothing was guaranteed to write again. The fix was to stop minting the sentinel *on
the path with no guaranteed follow-up write*, parking the field there at a real in-domain value. The
initialiser elsewhere still mints it, which is the point: a sentinel is worth exactly as much as the
guarantee that something overwrites it.

The formatter itself was right — reserving the whole negative half is exactly this pattern:

```kotlin
// adapted — names generalized
fun formatDuration(duration: Long): String {
    if (duration < 0L) return notAvailableLabel   // negative is reserved, never a real duration
    …
}
```

The lesson is not "don't use sentinels", it is **one owner decides the sentinel and every reader
goes through the same accessor** — a formatter that renders it, a predicate that tests it. A
sentinel with three independent readers has three definitions.

**A fallback inside the legal range makes every consumer carry the convention.** A duration parser
that returns `0` for unparseable input is documented and deliberate, and it still means every
downstream user must write `takeIf { it > 0 }` before sending, storing, or displaying it — forever,
including the ones added next year. Count the guards: if the same `> 0` appears at more than two
call sites, the fallback is in the wrong place.

**Two questions need two functions.** "Is this a video?" and "did the source say what this is?" are
different, and a boolean that folds an unknown into `false` answers only the first while looking
like it answers both. Expose the second explicitly, and say in the signature which way an unknown
falls, because reasonable implementations resolve it in opposite directions:

```kotlin
// adapted — names generalized
fun isVideo(kind: String?): Boolean = normalize(kind)?.let { it != AUDIO } == true  // unknown → false
fun isAudio(kind: String?): Boolean = normalize(kind) == AUDIO                      // unknown → false
fun isKnown(kind: String?): Boolean = normalize(kind) != null                       // ask this first
```

Both predicates return `false` for an unknown, which is only coherent because `isKnown` exists next
to them. Without it, `!isVideo(x)` reads as "audio" and quietly is not.

**Normalize before comparing, because stored rows outlive the code that wrote them.** A column
populated by earlier builds holds whatever those builds invented — labels from a different
vocabulary, and in one recorded case a numeric count written into a label column. Comparing those
raw classifies all of them as *something*. Run every value through one normalizer that keeps only
values the source itself can emit and returns `null` for everything else, then compare the
normalized result. `null` from that normalizer means "nobody has ever told us", which is exactly
what you want it to mean.

**The same rule has a UI-colour form, and the stand-in is visible.** A colour derived from an image
— a page tint, an accent, a glow — is *not resolved yet* for the first frames, and the tempting
default is a theme colour: it composes and looks plausible. Same defect — a real value the success
path also produces. It flashes as the wrong tone on load, and while nothing is selected it paints a
confident tint for something that does not exist. Two honest answers, used together:

```kotlin
// adapted — Unspecified is the "not resolved" sentinel; null is "nothing is selected"
val state = rememberDominantColorState(defaultColor = Color.Unspecified, …)
fun rememberGlowTint(imageUrl: String?): Color? =
    if (imageUrl == null) null else state.color.takeIf { it.isSpecified }
```

The consumer must then treat `null` as *draw nothing* rather than substituting its own default: the
gradient collapses into the page colour, so the layer is invisible until a tone arrives. A default
at the consumer re-creates the stand-in one layer down, where it is harder to find.

**Never invent a placeholder to satisfy a non-null field.** `"Unknown Artist"`, `"0:00"`, `1970-01-01`
are all values that will be persisted, matched against, sorted, and eventually shown. If the model
demands a value the payload does not contain, the model is wrong — make the field nullable or drop
the record, and see `structural-defensive-parsing` for counting what you drop rather than losing it
silently.

**Mint local failure codes outside the remote range.** When a call fails before reaching the
service there is no service code, and reusing `0` or any legal code makes a local failure
indistinguishable from a remote verdict. A negative code, where the service's own are positive,
keeps the two apart in one comparison — see `api-ok-but-ignored`.

## Verifying it

List the most common fallbacks that land inside the success domain and justify each one — these two
patterns catch the numeric and the invented-placeholder shapes, not every producer of them:

```bash
grep -rnE "to(Int|Long|Float|Double)OrNull\(\) \?: (0|0L|0f|-1|-1L)\b" --include="*.kt" . | grep -v "/build/"
grep -rniE "\?: \"(unknown|n/?a|untitled|none|no name)" --include="*.kt" . | grep -v "/build/"
```

For each hit, ask the one question that settles it: **can the success path produce this same
value?** If yes, the fallback is a defect however well documented. The second command finds invented
placeholders specifically — expect it to hit display strings never meant to be persisted, and check
where each one ends up. Widening either to a bare `?: ""` or `?: emptyList()` does not scale: on any
sizeable codebase it returns hundreds of lines, most legitimate. Narrow to the boundary you audit.

Then confirm the unknown state is reachable by callers:

```bash
grep -rnE "fun isKnown|data object Unknown|-> Unknown|UNKNOWN" --include="*.kt" . | grep -v "/build/"
```

For the colour form, list every derived-colour default beside every sentinel check — a theme role in
the first list with no counterpart in the second is a stand-in nobody can tell from a real value:

```bash
grep -rnE "default(On)?Color *=|fallbackColor *=" --include="*.kt" . | grep -v "/build/"
grep -rn "isSpecified\|Color.Unspecified" --include="*.kt" . | grep -v "/build/"
```

Finally, feed the parser a payload with the field deleted, then one with the field present but
garbage. Those two must be distinguishable at every layer — parser, model, storage, screen. If they
render identically anywhere, the sentinel was lost at that layer and everything below it is guessing.
