---
name: filter-chain-two-owners-one-writer
description: Two independent features want entries in one engine property that holds the WHOLE chain, so writing it replaces everything — keep each feature's entries in its own field, compose them in a single writer, and let "clear" drop only its own tier. Use when a second effect is added beside an existing one, or when one of two effects works and then randomly stops working after a transition.
---

# One property, two owners, one writer

Media engines that expose their processing graph as a **string property** — a comma-separated
list of stages — hand you an all-or-nothing setter. There is no "append a stage" and no "remove
the stage I added": every write is the entire chain. The moment a second feature wants a stage in
there, direct writes stop being viable.

The shape that survives is one field per owner and exactly one function that touches the property:

```kotlin
// adapted — the engine's filter-chain property is called `chainProperty` here, and the stage
// strings are shortened to `"eq(...)"` / `"sweep(...)"`; the real grammar is engine-specific.

@Volatile private var eqEntry: String? = null          // owner A: null while flat
@Volatile private var transitionEntries: List<String> = emptyList()   // owner B

/**
 * The only place the property is ever written. Owner A first: it shapes what B then acts on.
 * Read-modify-write over two fields, so callers must reach this on the thread that owns the
 * handle — name where that is enforced, because nothing here enforces it.
 */
private fun applyChain(): Boolean {
    val entries = listOfNotNull(eqEntry) + transitionEntries
    return setStringProperty(chainProperty, entries.joinToString(","))
}

fun setEqualizer(bands: List<Float>, preampDb: Float): Boolean {
    eqEntry = if (isFlat(bands, preampDb)) null else "eq(${bands.joinToString(",")};$preampDb)"
    return applyChain()
}

/** Drops owner B's tier only. Blanking the property here is what used to take A down with it. */
fun clearTransitionFilters() {
    transitionEntries = emptyList()
    applyChain()
}
```

## Traps

**The bug is silent, intermittent, and blames the wrong feature.** The feature that writes the
property directly usually ships first and looks fine forever; the *second* feature is the one that
"works, then randomly doesn't". It stops precisely when the first feature next writes — at the start
or the end of a transition — which from the outside is a timing that correlates with nothing the
user did to the second feature. Anyone bisecting will land on the second feature's commit.

**"Clear" is the half everybody forgets.** Installing through the composer and then clearing with a
blank write is the same bug wearing a different hat, and it is *worse*: install happens once per
transition, clear happens at the end of **every** transition, including the ones that were cancelled.
See `guard-on-every-trigger-path` — a chain owner has the same two-entry-point problem, and covering
only the install path leaves the wipe on the path that runs more often.

**An absent tier must contribute no entry, not an empty one.** `"$a,$b"` with `a` empty yields a
leading comma, and a comma-separated graph parser reads that as a stage with an empty name — which
fails the **whole** string, so the tier that *did* have entries goes down too:

```
$ ffmpeg -v error -f f32le -ar 48000 -ac 1 -i imp.raw -af ",volume=2" -f null -
[AVFilterGraph] No such filter: ''
[aost#0:0] Error initializing a simple filtergraph
```

`listOfNotNull(a) + b` then `joinToString(",")` is not tidiness; it is the defense.

**Order between tiers is a decision, and it belongs to the writer.** Two linear stages compose to
the same response either way, so nothing sounds wrong — but order decides *which stage a boost can
clip in*, and the trim that makes room for a boost has to travel with it. Write the reason down at
the composer, because it is the one place a reader can see both tiers at once.

**Label your entries if the engine lets you address them later.** Per-stage updates that retune a
live filter in place are far cheaper than rebuilding the graph (the engine typically drains and
re-creates it on every property write), but they need a handle on the stage. Labelling also stops
the two owners from addressing each other's stages by position, which silently breaks the moment
the other tier's length changes.

**`@Volatile` on both fields does not make the composer atomic.** A settings screen writes `eqEntry`
while a transition animation writes `transitionEntries` — hence `@Volatile` on both. But
`applyChain()` *reads both fields and then writes the property*, a read-modify-write: volatile stops
a torn read of either field, not two threads interleaving inside the composer and publishing owner
A's new entry beside owner B's already-cleared list. Confine `applyChain()` itself to the thread
that owns the handle and the whole read-modify-write becomes atomic — which also closes the
use-after-free where a handle is released between the liveness check and the write. The sample above
calls the composer straight from the caller's thread, so the confinement is the *caller's* contract:
name where it is enforced, at the composer, or the next reader copies the race.

**Every freshly created handle starts with an empty chain.** The composer covers "two owners on one
handle"; it does nothing for "the same setting on a handle created later". That is the separate
problem in `sampled-supplier-vs-per-handle-reapply`, and on an engine of this shape you need both.

**Guard the composer's return value where a tier is optional.** If a stage can be rejected by the
engine (an optional build-time dependency, a codec that is not there), a single boolean "did the
write land" is not enough to know *which* tier survived — see
`optional-engine-feature-degrade-in-tiers`.

## Verifying it

The invariant is "exactly one call site writes the property", so check it as a grep, not as a test:

```bash
# every write of the chain property — expect exactly ONE hit, and it must be the composer's own
# line. Resist filtering the composer out: against a block body the filter removes nothing, and
# against a single-expression `fun applyChain() = setStringProperty(…)` it hides the one real hit.
grep -rn --include='*.kt' 'setStringProperty(chainProperty' .
```

Then drive the interleaving that produced the original bug, in this order, asserting the property
after each step: set owner A → start a transition → **cancel** it → read the property. A test that
only runs a transition to completion passes against the blank-write version too, because completion
and cancellation reach the clear by different paths.
