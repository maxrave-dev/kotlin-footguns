---
name: readonly-stateflow-cold-to-hot
description: Expose state through `asStateFlow()` rather than an upcast of the mutable holder, and turn a cold source flow hot with `stateIn(scope, WhileSubscribed(timeout), initial)` so it survives collector churn without running forever. Use when a screen re-queries its source on every rotation or navigation, when work continues after the last collector leaves, or when something outside the owner is writing state it should only be reading.
---

# Read-only exposure, and cold sources made hot

Two decisions, one property each. Both are one line, and both are routinely got wrong in a way that
compiles and mostly works.

**Exposure.** A state holder is written by exactly one owner and read by everyone else, so the
public type must be the read-only one:

```kotlin
// adapted — initial value trimmed
private val _controlState = MutableStateFlow(ControlState(...))
val controlState: StateFlow<ControlState> = _controlState.asStateFlow()
```

**Cold to hot.** A source flow — a preferences store, a database query — is cold: every collector
starts its own read. Sharing it once, with a keep-alive window, gives every screen the same value
and stops the upstream a beat after the last collector leaves:

```kotlin
// adapted — two real sites, source names generalized
val openAppTime: StateFlow<Int> =
    dataStore.openAppTime.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000L), 0)

val listPlaylists: StateFlow<List<PlaylistEntity>> =
    repository.getAllPlaylists()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
```

## Traps

**An upcast is not `asStateFlow()`, and the difference is not stylistic.** Decompile the call and
`asStateFlow(m)` allocates a `ReadonlyStateFlow` wrapping `m` — a different object that is not a
`MutableStateFlow` and cannot be cast into one. `val x: StateFlow<T> = _x` hands out *the same
object* under a narrower static type, so anything holding it can cast back and write:

```kotlin
(viewModel.someState as MutableStateFlow<Boolean>).value = true   // compiles, and works
```

The two forms are freely mixed in most codebases — the handler layer here uses `asStateFlow()`
throughout while the screen models mostly upcast. Find the upcasts by looking for the assignment
without the call:

```
grep -rn "StateFlow<.*> = _" --include="*.kt" src/ | grep -v asStateFlow
```

The upcast is a defensible choice for a strictly internal holder; it is not a defensible choice for
anything a different module can reach.

**`get()` on an exposed property is a third form with a different meaning.** `val x: StateFlow<T>
get() = _x` re-evaluates on every read. It is equivalent for a `val` backing field and misleading
for a `var` one, where callers can end up holding different instances at different times. Prefer
one form per layer and stick to it.

**`WhileSubscribed`'s timeout is a policy, not a magic number.** It is how long the upstream stays
alive after the last collector leaves, and it exists to bridge a gap where the screen is
momentarily uncollected — a configuration change, a navigation transition. Too short and the source
is re-read on every rotation; too long and work continues for a user who left the screen. Cost is
what should set it, and here it mostly has not: the preference read and the database query above,
which are nothing alike, carry the *same* 5 s — while the one site that differs spends 1 s on two
`map`s over a `MutableStateFlow` the class already holds in memory, the cheapest upstream of the
three and the one that re-subscribes for free. A project-wide constant is the wrong instinct; so is
a value that cannot be traced back to what re-subscribing actually costs.

**`WhileSubscribed` is not the only option, and the alternatives fail differently.**
`SharingStarted.Eagerly` starts at construction and never stops, which is correct only for something
that must be warm before anyone asks. `SharingStarted.Lazily` starts on first collection and then
never stops — the leak that looks like a fix, because the symptom it removes (re-reading on
rotation) is the same one `WhileSubscribed` removes.

**The initial value is displayed.** `stateIn` needs one synchronously and it is what the screen
paints before the first real emission arrives. `emptyList()` renders as an empty list, not as a
spinner — if the difference matters, make the state type carry "not loaded yet" explicitly rather
than picking an initial value that is indistinguishable from a real empty result.

**Sharing changes the flow's identity, so put it on a property, not in a function.** `stateIn`
called inside a getter or a function body creates a new shared flow per call and shares nothing.
The whole point is the single instance held by the property.

**A `SharedFlow` exposure is not interchangeable.** `asSharedFlow()` over a `MutableStateFlow`
compiles and appears equivalent, but the public type no longer offers `.value`, so callers that need
the current value synchronously silently move to collecting it instead — and a collector that
arrives late gets whatever the replay cache holds rather than "the current state" by definition.
Pick `SharedFlow` when you mean events, `StateFlow` when you mean state.

## Verifying it

For exposure, try the cast. Write the line that casts the public property back to
`MutableStateFlow` and assign to it. If it runs, the property is an upcast; `asStateFlow()` fails
there at runtime. That is a one-off check to run once per layer, not a test to keep.

For sharing, log one line where the cold source is *subscribed* — inside the source flow's own
builder, not in the collector. Then navigate away from the screen and back, faster than the timeout
and again slower than it. Fast: no new subscription line. Slow: exactly one. If a rotation produces
a subscription line, the flow is not shared; if navigating away never stops it, the strategy is
`Lazily` or `Eagerly`.

Do not judge either of these from the value you read back in the owner — the owner writes and reads
the same field and will see a consistent value no matter which form is used.
