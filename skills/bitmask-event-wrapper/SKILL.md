---
name: bitmask-event-wrapper
description: Wrap an integer flag set handed up from a lower layer in a single-field value class exposing contains and containsAny, so call sites stop writing raw bitwise tests against library constants. Covers keeping the wrapper allocation-free, why the flag constants must travel with it, the difference between "any of these bits" and "all of these bits", and what happens when a non-flag constant is passed to a flag test. Use when the same bitwise expression is copied across call sites, when a flag test is written as an equality check, or when a wrapper type exists but nothing ever calls it.
---

# One value class over an integer flag set

A lower layer — a player, a permission system, a change-notification callback — hands up a single
integer whose bits each mean something. Left raw, every call site writes the mask by hand and every
call site can get it wrong in a different way. The wrapper is small enough to be obviously correct:

```kotlin
// adapted — the source is a data class with no all-bits predicate; both changes are the point of
// the traps below
@JvmInline
value class EventSet(val flags: Int) {
    fun contains(event: Int): Boolean = flags and event != 0
    fun containsAny(vararg events: Int): Boolean = events.any { flags and it != 0 }
    fun containsAll(mask: Int): Boolean = flags and mask == mask
}
```

Two properties are the entire point. Call sites read as a question rather than an expression, so a
missing `!= 0` cannot be introduced by copy-paste. And the type is distinct: a function taking
`EventSet` cannot be handed a position, a duration, or a state constant, which a function taking
`Int` accepts silently.

**Keep it a value class, not a data class.** A `data class` around one integer allocates an object
for every event delivered, and events on a hot callback arrive continuously. A single-field value
class is represented as the bare integer at runtime in the common cases — with the exception that
matters here: it is boxed when it is used as a nullable, as a generic type argument, or through an
interface. A listener signature of `onEvents(events: EventSet)` stays unboxed; one of
`onEvents(events: EventSet?)` does not.

## Traps

**`and != 0` is "any of these bits", never "all of them".** This is the single most common defect in
hand-written flag code, and the wrapper inherits it unless you name the two operations separately.
A constant that happens to carry two bits — several libraries define composite constants — passed to
`contains` answers true when *either* is present. If the question is "did both happen", the
comparison is `flags and mask == mask`. Name the methods so that the wrong one is hard to reach for,
and never let a single method serve both by accident.

**Equality against a mask asks a third question that is almost never the one you want.**

```kotlin
if (flags == EVENT_A or EVENT_B) { … }   // exactly these two bits and nothing else
```

That is true only when no other bit is set, so it starts working, then stops the moment the lower
layer adds a flag it had every right to add. The fix is masking, not a longer equality:

```kotlin
if (events.containsAll(EVENT_A or EVENT_B)) { … }
```

The same mistake wearing a different hat is comparing to a single constant — `flags == EVENT_A`
passes only when `EVENT_A` arrived alone, and events are delivered in batches precisely so that they
do not.

**The constants have to travel with the wrapper — but read their *values* first.** A wrapper placed
in a shared module while its `EVENT_*` vocabulary stays in the layer below leaves call sites with a
type they cannot name any argument for, so they keep calling that layer's own predicate on its own
type and the wrapper sits unreferenced. The repair is not to copy the names across. A vocabulary
numbered `0, 1, 2, 3, …` in sequence is an ordinal enumeration, not a set of masks — and a layer
that delivers its events as a *set object* rather than a packed integer numbers them exactly that
way. Lifted into flag positions they compile and answer wrong: index `0` makes `and != 0` always
false, index `4` silently reads bit 2, index `7` is true whenever any of the three lowest bits is
set. So if the upstream values really are single bits, define them beside the wrapper in the same
commit — as `1 shl n`, never by copying an ordinal into a flag position. If they are ordinals,
there is no packed integer to wrap and the wrapper should not exist at all.

**A constant from a neighbouring set will be accepted and quietly answer nonsense.** Layers that
define their own vocabulary usually mix two kinds of integer in one place: bit flags, and plain
enumerations numbered 1, 2, 3, 4. Both are `Int`, so `contains(STATE_READY)` compiles. With
`STATE_READY == 3`, `flags and 3 != 0` is true whenever *either* of the two lowest flag bits is
set. It answers plausibly rather than obviously wrongly, which is what stops anyone noticing.
Give the flags their own type, or at minimum keep flags and enumerations in separate declarations
with names that do not read alike.

**Shift distances are taken modulo the width, so a flag past the end silently aliases flag zero.**
On Kotlin/JVM the shift functions use only the five lowest-order bits of the count for `Int` and the
six lowest for `Long`; the standard library documents this on the operations themselves. So a
thirty-third flag written `1 shl 32` is `1` — the same value as the first flag — and both bits test
true for each other with no error anywhere. Thirty-two flags is the hard ceiling for an `Int`. Move
to `Long` before you reach it, and treat "we are near the limit" as the trigger, not "we hit it".

**The highest bit of a signed integer is negative, which is fine until something compares.**
`1 shl 31` is the most negative integer. Masking works normally — `and`, `or`, `xor` are bit
operations and do not care — but any code that sorts flag values, prints them as decimal, or stores
them in a column with a range check will behave surprisingly for that one flag. Print flag sets in
hexadecimal or binary when debugging.

**A `vararg` predicate allocates an array on every call.** `containsAny(A, B, C)` builds an
`IntArray` per invocation, which on a callback that fires per frame is a steady allocation stream
for a question that is one `or` and one `and`. Provide a mask overload and prefer it on hot paths:

```kotlin
fun containsAny(mask: Int): Boolean = flags and mask != 0
```

Keep the `vararg` form for readability at cold call sites if you like — but do not let it be the
only form.

**The wrapper must not grow interpretation.** Adding `isImportant()` or `shouldRefresh()` to it
moves policy into a type whose whole value is being mechanical. Those belong to the consumer that
knows what matters; the wrapper answers only which bits are present.

## Verifying it

1. **Confirm the wrapper is actually used**, which is the failure this pattern most often has.
   Grep the *type*, in construction and type positions — not the method names:
   ```sh
   grep -rnE "\bEventSet\s*\(|:\s*EventSet\b|<\s*EventSet\s*>" --include='*.kt' .
   ```
   Every hit outside the wrapper's own file is a real use; only its own declaration coming back is
   the unreferenced case. A bare `containsAny(`/`contains(` grep is not enough — the layer you are
   wrapping very likely exposes a predicate of the same name on its own type, and those hits will
   make an unreferenced wrapper look used.
2. **Find raw bitwise tests that bypass it**:
   ```sh
   grep -rnE "and +[A-Za-z_][A-Za-z0-9_.]* *!= *0" --include='*.kt' .
   ```
   The wrapper's own two method bodies will match. Every other hit is a call site hand-writing the
   mask, and each one is a place the `!= 0` can go missing in the next copy-paste.
3. **Find equality comparisons against flag constants**:
   ```sh
   grep -rnE "== *[A-Za-z_]*EVENT_[A-Z_]+|== *\([A-Za-z_]*EVENT_" --include='*.kt' .
   ```
   Each of these is the exactly-these-bits question; confirm that is what was meant.
4. **Confirm it is a value class**:
   ```sh
   grep -rn -B 6 "fun contains(event" --include='*.kt' .
   ```
   The enclosing declaration should read `@JvmInline value class`; `data class` means one allocation
   per event delivered.
5. **Check the flag constants and any plain enumerations are not in the same object.** Read the
   constants file: values `0, 1, 2, 3` in sequence are an enumeration, values `1, 2, 4, 8` are flags,
   and a file containing both without a type separating them is the mixing trap waiting to happen.
