---
name: flatmaplatest-resubscribe-composite-key
description: Re-subscribe a downstream flow whenever a key flow changes using flatMapLatest, then collapse the resulting high-frequency stream to a composite key with distinctUntilChanged before firing expensive one-shot work. Use when a fetch re-runs on every progress tick, when it fires for the wrong item after a fast switch, or when a side effect never runs because one of its inputs arrives last.
---

# Re-subscribe on a key change, gate on a composite key

Two flows, at very different rates. One is the *key* — the item currently in view, changing rarely.
The other is fast and continuous — a position, a size, a progress reading. Some one-shot work needs
both, and needs to run once per item, not once per tick.

`flatMapLatest` gives the re-subscription: when the key changes, the inner collection is cancelled
and rebuilt around the new key, so the pair can never mix a new key with the old stream.
`distinctUntilChanged` over a *composite* of the fields that actually matter then collapses the fast
stream down to "something meaningful changed":

```kotlin
// adapted — names generalized
currentItemState
    .filterNotNull()
    .flatMapLatest { item ->
        timeline.map { t -> Pair(t, item) }
    }.distinctUntilChanged { (oldT, oldItem), (newT, newItem) ->
        // true = equivalent = DROP
        oldT.total == newT.total && oldItem.entity?.id == newItem.entity?.id
    }.collectLatest { (timeline, item) ->
        if (timeline.total > 0 && item.entity != null) {
            if (screenData.value.extraA == null) fetchA(item.id, timeline.total)
            if (screenData.value.extraB == null) fetchB(item.entity, timeline.total)
        }
    }
```

The composite is duration plus item id, because the work needs a *usable* duration: the item id
alone changes too early (the duration is still unknown, and the fetch would be issued with a zero),
and the duration alone changes on rewind. Neither field on its own is the event.

## Traps

**The `distinctUntilChanged` predicate answers "are these equivalent", so `true` drops.** Take the
implementation apart and the branch is unambiguous: when the predicate returns true it jumps past
the emit, and only a false result updates the remembered key and forwards downstream. Written as
`old != new` — the reading that feels natural — the operator inverts and drops everything *except*
the changes. The symptom is a side effect that fires on every tick, which is the exact bug the line
was added to fix, so it is easy to conclude the operator "doesn't work".

**Do not build the composite key by concatenating strings and hashing.** The pattern that shows up
in practice is `(a.toString() + b).hashCode()` on both sides. It is lossy twice over: concatenation
is ambiguous (`"1" + "23"` and `"12" + "3"` produce the same string), and a hash collapses distinct
values onto one integer. A missed change here is silent — the work simply never runs for that item.
Compare a `Pair`, a `data class`, or the fields themselves; they are already comparable and cost
nothing:

```kotlin
.distinctUntilChangedBy { (t, item) -> t.total to item.entity?.id }
```

`distinctUntilChangedBy` is the same operator with the key extracted instead of a predicate, and it
removes the chance of inverting the comparison at all.

**A field left out of the key is a whole class of update you will never receive.** This is the mirror
of the hashing mistake and quieter still: whatever the key omits, the operator treats as noise. A
snapshot key of `(item, isPlaying, position)` taken from a state that *also* carries the list behind
the item drops every emission in which only that list changed — so the collector never learns the
list arrived, and the symptom is a feature that is simply absent rather than one that misfires. Give
each field a cheap projection rather than leaving it out: ids rather than objects, so the comparison
is structural and does not depend on the upstream reusing instances.

```kotlin
// adapted — names generalized
.map { Snapshot(it.item, it.isPlaying, it.position, listIds = it.list.map { e -> e.id }) }
.distinctUntilChanged()
```

The rule that makes this decidable without thinking about it: **the key must mention every field the
collector body reads.** A field the body uses and the key ignores is a silent drop; a field the key
mentions and the body ignores costs only a redundant pass. The asymmetry is the whole argument for
erring towards a wider key — and it is why the guard in the next trap is not optional.

**The collector still needs its own idempotence guard.** The composite key changes for reasons
unrelated to the work — a duration correction arriving late will re-fire it for the same item. Each
branch above therefore re-checks that the result it would produce is still missing
(`if (screenData.value.extraA == null)`). The gate reduces the firing rate; the guard is what makes
a re-fire harmless. Skipping the guard because the gate exists is how a duplicate request survives
into release.

**`collectLatest` cancels the previous action; it does not cancel what that action started.** The
inner work above is launched into the surrounding scope and outlives the cancelled action. If the
one-shot work must be abandoned when the key changes, hold it in a named handle and cancel it — see
`named-job-lifecycle-discipline` — or check the item id again at the point where the result is
written, which is the pattern in `distinct-by-key-reset-cancel-per-item`.

**`combine` is not a substitute here, and neither is `zip`.** `combine` re-emits on *either* source,
so the fast flow drives it and the key flow contributes nothing structural — you get the same rate
with no re-subscription. `zip` pairs emissions positionally and stalls the moment the two rates
diverge, which they do immediately.

**`flatMapLatest` requires an explicit opt-in.** It is annotated experimental in the coroutines
library, so the file carries `@OptIn(ExperimentalCoroutinesApi::class)`. That annotation is a real
statement about API stability, not boilerplate: the surrounding code should not depend on the
operator's exact cancellation timing beyond "the previous inner collection is cancelled".

**Order the operators: filter, then flatMapLatest, then distinct, then collect.** Putting
`distinctUntilChanged` *before* the `flatMapLatest` deduplicates the key flow, which is nearly
always a no-op, and leaves the fast flow undamped. The gate belongs on the merged stream.

## Verifying it

Hand-written keys and projected ones need a census each, because the bare no-argument form is not a
hand-written key and never appears in the first list:

```bash
grep -rnE 'distinctUntilChanged *\{|distinctUntilChangedBy' --include='*.kt' . | grep -v '/build/'
grep -rn -A12 -E '^ *\.map \{$' --include='*.kt' . | grep -v '/build/' | grep -E '\.map \{$|distinctUntilChanged\(\)'
```

From the first, expect a handful of hits (plus an import line per file that uses the `By` form). Read
each one against the body of its own collector and answer the two questions above in order: does
`true` mean drop here, and does the key mention every field the body reads? A predicate that compares
one id while the body reads three fields is the silent-drop defect, invisible at the call site.

The second is where an omitted field actually hides, because a multi-line `.map {` feeding a bare
`distinctUntilChanged()` *is* a hand-written key with its fields spread over several lines. Only the
**pairs** in that output count: a `.map {` with no `distinctUntilChanged()` under it is an ordinary
transformation, so read past it. For each pair, open the projection and ask the second question again.

Then instrument the gate, not the collector: log the composite key on every emission that gets *past*
`distinctUntilChanged`. Let one item play through without touching anything. The count must be
small and bounded — one line when the duration becomes known, and nothing for the rest of the item.
A line every tick means the predicate is inverted or the composite includes a field that changes
continuously; **no line at all** for a change you know happened is the omitted field.

Then switch items fast, before the first item's work returns, and confirm two things: a new line
appears for the new item, and no result belonging to the old item is written afterwards. The second
half fails independently of the gate and is the one this operator does not fix by itself.
