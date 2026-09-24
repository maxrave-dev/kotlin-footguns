---
name: identity-compare-immutable-setting
description: Bundle a multi-field setting into one immutable value and hand it to a hot consumer as a supplier, so the consumer asks "has this changed?" with a single reference comparison instead of diffing N numbers per buffer — and can never observe the fields half-updated. Use when a per-buffer or per-frame consumer has to react to a user setting, or when a setting made of several fields is read inconsistently.
---

# One immutable value, compared by identity

A consumer running per audio buffer or per frame needs the current setting on every pass, and needs
to know cheaply whether it changed since last time. Two `@Volatile` fields plus a numeric diff gives
you the worst of both: N comparisons on the hot path, and a window where the consumer sees the new
value of one field beside the old value of the other.

Bundle the setting instead, hand the consumer a supplier, and compare the *reference*:

```kotlin
/** One setting, as a single immutable value. */
data class EqualizerCurve(val bandsDb: List<Float>, val preampDb: Float) {
    val isFlat: Boolean = preampDb == 0f && bandsDb.all { it == 0f }
    companion object { val FLAT = EqualizerCurve(emptyList(), 0f) }
}

class Consumer(private val setting: () -> EqualizerCurve) {
    private var applied: EqualizerCurve? = null

    private fun sync() {
        val next = setting()
        if (next === applied) return     // identity, never equality
        applied = next
        rebuild(next)                    // the expensive part: coefficients, allocation, …
    }
}
```

The producer side is one `@Volatile` field and a fresh value per write:

```kotlin
@Volatile private var current: EqualizerCurve = EqualizerCurve.FLAT

override fun setEqualizer(bandsDb: List<Float>, preampDb: Float) {
    current = EqualizerCurve(bandsDb, preampDb)   // a NEW object, deliberately
}
```

## Traps

**Allocating a fresh value on every write is the point, not waste.** It is tempting to skip the
allocation when the fields did not change. Don't: the whole scheme rests on "different object ⇒
maybe different setting, same object ⇒ definitely unchanged". Reusing an instance for a value the
producer *believes* is equal reintroduces the diff you were avoiding, one level up, and puts it in
the place least able to see the consumer's state. One small object per user gesture is nothing next
to N comparisons per buffer for the whole of playback.

**`===` and `==` are not interchangeable here, and `data class` makes the mistake compile.** A data
class generates `equals`, so `next == applied` type-checks and looks more correct — and it costs a
list walk on every buffer, which is the exact expense the design exists to avoid. Worse, it makes
the *rebuild* path depend on value equality, so a producer that reuses instances and a consumer that
compares by value can each look right in isolation. Write `===` and say why in a comment beside it.

**Identity comparison can only over-rebuild, never under-rebuild — check that direction.** A new
object with identical contents triggers one needless rebuild (harmless). The dangerous direction is
the same object with *mutated contents*, which the consumer will never notice. That is why the
value must be genuinely immutable: `List<Float>` here is a read-only interface over a list the
producer could still hold a mutable reference to. Build it from a defensive copy at the boundary,
or accept the list only from callers that construct it fresh.

**Bundling is what removes the half-updated read, and that bug is invisible in testing.** Two
separate volatile fields written in sequence let a consumer between the writes apply a new band set
with the old trim — the boost without the headroom that makes room for it. It is one buffer long,
it needs a user gesture at exactly the wrong moment, and it never reproduces on demand. One
reference write is atomic; there is no "between".

**A "nothing to do" flag on the value beats recomputing it per pass.** `isFlat` is computed once in
the constructor, so the per-buffer path reads a boolean rather than walking the bands. Compute it
as a `val` in the body — a `get()` looks the same at the call site and re-walks the list every time
it is read. The deciding factor is read frequency, not syntax: on a static table read at composition
a `get()` is fine, and `preset-identity-read-back-from-value` recommends exactly that.

**Invalidate the identity whenever anything *else* the derived state depends on changes.** The
coefficients are a function of the setting **and** the stream format, so after a format change the
same object is no longer "applied" — and identity comparison will happily skip the rebuild. Clear the
marker wherever the other inputs are negotiated:

```kotlin
override fun onConfigure(format: AudioFormat): AudioFormat {
    …
    applied = null      // forces a rebuild against the new sample rate on the first buffer
    return format
}
```

Missing this is the subtlest failure in the design, because it needs a *second* stream at a different
sample rate to appear: everything is right until a track arrives at 44.1 kHz after one at 48.

**The consumer must sample per pass, not capture at configure time.** The supplier only helps if it
is invoked on the hot path. Capturing `setting()` once at stream start is a different, older bug
wearing this design's clothes: the setting reaches the output on the *next* stream and the user
reports "it only works from the next track".

**One consumer instance per stream, one setting for all of them.** The state that forbids sharing a
consumer is its own per-stream state, not the setting. Give every player its own consumer and let
them all close over the same supplier — a single producer write then covers both halves of a
crossfade and every precached player, without anything having to enumerate them. On an engine where
that is *not* true, see `sampled-supplier-vs-per-handle-reapply`.

## Verifying it

```bash
# the consumer must compare by identity — expect no hits. The `[^=!]` matters twice over: it skips
# a correct `===` AND a correct `!==`, which is the natural way to write the early return inverted;
# anchoring on `applied` as an operand also skips unrelated equality like `applied?.isFlat == true`.
grep -rnE --include='*.kt' '[^=!]== *applied|applied *==[^=]' .
# and the producer must allocate per write, not reuse
grep -rn --include='*.kt' -A2 'override fun setEqualizer' .
```

Then two behavioural checks, both of which pass on a broken version if you only run the first:

- write the *same* values twice and assert `rebuild` ran twice — that proves identity, not equality,
  is what is being compared;
- write a value, run one pass, mutate nothing, run a thousand more, and assert `rebuild` ran once.
