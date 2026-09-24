---
name: preset-identity-read-back-from-value
description: Derive "which preset is this" by comparing the presets against the value in force instead of storing a label beside it, so editing drops to Custom by itself and returning re-selects — and derive any per-preset field that is a function of the preset's own numbers rather than writing it out per row. Use when a preset picker keeps showing a stale name, when a preset never re-selects itself, or when a per-row constant has drifted in one row out of twenty.
---

# Read the preset back off the value

A preset list plus "which one is selected" looks like two pieces of state. It is one. The value is
the truth; the label is a *question you can ask about it*:

```kotlin
/** The preset [bandsDb] currently sits on, or null once it has been dragged off every one. */
fun presetFor(bandsDb: List<Float>): Preset? =
    PRESETS.firstOrNull { preset ->
        preset.bandsDb.indices.all { i -> abs(preset.bandsDb[i] - bandsDb.getOrElse(i) { 0f }) < 0.01f }
    }
```

Nothing on disk records which preset is on. Editing the value drops the label to Custom by itself;
putting the value back re-selects the preset, with nothing having to notice. The same read-back
covers a second, unrelated label over the same value — an imported profile's name — so two pickers
can write one value and each stay honest about it.

## Traps

**Storing the label is not "one extra field", it is one extra field per edit path.** Every writer of
the value now also has to clear the label, and the writers multiply quietly: the picker, a drag on
the control, a reset button, an import, a restore-from-backup, a migration. Missing one leaves a
name pinned to a value it no longer describes, which reads as the app lying rather than as a bug.
Deriving has no edit paths at all.

**Compare with a tolerance, because the value has been through text.** Preferences and exchange
files store floats as decimal strings; `4.5f` written and re-parsed is not obliged to be the same
bit pattern as the literal in the preset table. An exact `==` gives a picker that shows Custom
immediately after the user picked a preset. A tolerance of about `0.01` — well under the smallest
step the control can produce — is the whole fix.

**`firstOrNull` means duplicate presets are unreachable.** Two entries with identical numbers and
different names: the second can never be selected, because the derivation always answers with the
first. Selecting it in the picker "does nothing" from the user's side. If the list can contain
duplicates by design, the label has to be stored after all — which is a reason to keep the list
free of them.

**The two lengths are not symmetric, and whichever side you iterate is the side that decides.**
Iterating the *preset's* indices treats a stored curve that is longer as a match on its prefix: ten
bands agree, an eleventh is boosted, and the picker still says "Rock". Iterating the *value's*
indices has the mirror problem. Two derivations over the same value that pick different sides — one
for presets, one for imported profiles — will disagree with each other. Compare over the union:

```kotlin
val n = maxOf(preset.bandsDb.size, bandsDb.size)
(0 until n).all { i ->
    abs(preset.bandsDb.getOrElse(i) { 0f } - bandsDb.getOrElse(i) { 0f }) < 0.01f
}
```

**Derive per-preset fields too — a field that is a function of the row's own numbers is computed,
not written out.** Twenty-two rows each carrying a hand-written trim is twenty-two chances to get
one wrong, and the wrong one is found by a user, not by a test:

```kotlin
val preampDb: Float get() {
    val loudest = bandsDb.maxOrNull() ?: 0f
    return if (loudest > 0f) -loudest else 0f     // NOT -maxOf(loudest, 0f)
}
```

A `get()` is the right form *here* because the table is static and each row is read at composition.
The deciding factor is how often the field is read, not the syntax: on a per-buffer or per-frame
path the same field must be a `val` in the body, because a `get()` looks identical at the call site
and re-walks the list every time — see `identity-compare-immutable-setting` for that case.

**Spell out the zero case rather than negating a maximum.** `-maxOf(loudest, 0f)` hands you `-0.0f`
for every preset that only cuts, and negative zero is a different value in more places than people
expect. On the JVM:

```
String.valueOf(-0.0f)                             →  "-0.0"     (so it round-trips as text)
-0.0f == 0.0f                                     →  true       (primitive: IEEE)
Float.valueOf(-0.0f).equals(Float.valueOf(0.0f))  →  false      (boxed: total order)
java.util.List.of(-0.0f).contains(0.0f)           →  false      (so does any boxed lookup)
```

Kotlin compares two statically-`Float` operands with IEEE semantics, but the moment the value is
boxed — inside a `List<Float>`, a `Float?`, or any generic position — it compares with `equals`, and
`-0.0` stops being zero. A "is this flat?" check written one way passes and written the other way
fails, on the same number.

**A tolerance-based derivation is O(presets × bands) and runs during composition.** That is nothing
at twenty-two presets and ten bands, and it is not nothing at a thousand rows. Wrap it in a
`remember(value)` so it recomputes when the value changes rather than on every recomposition, and
if the list ever grows past what a linear scan can carry, key the presets by a hash of their rounded
numbers instead of storing a label.

## Verifying it

```bash
# nothing may persist the label — expect no hits
grep -rn --include='*.kt' 'setSelectedPreset\|selected_preset\|PRESET_NAME' .
# and every per-row derived field should be a getter, not a constructor argument
grep -rn --include='*.kt' -A4 'data class Preset' .
```

Then three round-trips, in this order — the first passes on a stored-label version too, the other
two do not:

- pick a preset, assert the label;
- drag one band by the smallest step the control produces, assert the label is Custom;
- drag it **back**, assert the original preset re-selects. That last one is what proves the label is
  derived and not merely cleared on edit.

Finally, assert `presetFor` over a value with more entries than the presets have returns null, and
that the trim of a cuts-only preset is `0.0f` — printing as `"0.0"`, not `"-0.0"`.
