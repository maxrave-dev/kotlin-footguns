---
name: compose-multiplatform-viewmodel-base
description: A shared ViewModel base class for Compose Multiplatform — container-aware so subclasses can pull extra dependencies without constructor threading, with one loading/error surface for every screen — and the blocking resource-lookup hazard that such a base almost always grows. Use when every screen is re-implementing its own loading dialog, when a base class needs a dependency only some subclasses use, or when app start stutters on the main thread before anything is drawn.
---

# A shared ViewModel base for Compose Multiplatform

The multiplatform `ViewModel` gives you `viewModelScope` and `onCleared` on every target. A project
base class on top of it is worth having for three things and no more: a container handle so a
subclass can pull an occasional dependency without adding a constructor parameter, one loading/error
surface so screens do not each invent theirs, and a logging tag derived from the concrete class.

```kotlin
// adapted — trimmed to the three members worth having, names generalized
abstract class BaseViewModel : ViewModel(), ContainerComponent {
    protected val handler: PlaybackHandler by inject()

    protected val tag: String = this::class.simpleName ?: "BaseViewModel"

    private val _showLoadingDialog = MutableStateFlow(false to "")
    val showLoadingDialog: StateFlow<Pair<Boolean, String>> get() = _showLoadingDialog

    fun showLoadingDialog(message: String? = null) { … }
    fun hideLoadingDialog() { … }
}
```

Everything else that lands there should be justified per member: a base class is the one place in
the codebase where a dependency becomes mandatory for every screen at once.

## Traps

**A blocking resource lookup on the constructor path is the dominant hazard.** Multiplatform string
resources are loaded asynchronously — decompile the resources library and `getString` takes a
continuation, i.e. it is a `suspend` function backed by real I/O. Bridging it with `runBlocking` for
call-site convenience:

```kotlin
protected fun getString(resId: StringResource): String = runBlocking { getString(resId) }
```

…is defensible inside a handler already off the main thread, and a stutter everywhere else. The
version that actually hurts is the one reached from a **property initializer**, because that runs
during construction, on whatever thread constructs the screen model — the main thread:

```kotlin
// adapted — the explicit `MutableStateFlow<Pair<Boolean, String>>` type argument dropped
private val _showLoadingDialog = MutableStateFlow(false to getString(Res.string.loading))
```

Every screen now blocks the main thread on a resource read before it can be shown. Give the state a
placeholder and fill it from a coroutine, or make the caller pass the string it already has:

```kotlin
private val _showLoadingDialog = MutableStateFlow(false to "")
private var defaultLoadingText: String = ""
init { viewModelScope.launch { defaultLoadingText = getString(Res.string.loading) } }
```

Find the ones on the constructor path — those are the expensive ones — by matching the helper in a
property declaration rather than anywhere an expression can appear:

```
grep -rnE "^ *(private |protected |internal )?(val|var) .*= .*getString\(" --include="*.kt" src/
```

That is a shape filter, not a scope filter: it still matches a local `val` inside a function body, so
read the indentation — a member initializer sits at class depth. It is worth tightening anyway,
because the looser `"= .*getString("` matches every named argument and every assignment in the
codebase and buries the handful of initializers under a hundred-odd function-body hits.

**`runBlocking` in an initializer is the same trap without the resource API.** Reading a preference
store synchronously to seed a field (`runBlocking { store.value.first() }`) is the identical shape
and shows up in screen models and service handlers alike. It is tolerable exactly once, for a value
that genuinely must exist before the first frame; a base class multiplies it by every screen.

**The worst position for such an accessor is composition, not construction.** An initializer blocks
once per screen; a blocking getter read from a composable blocks on **every recomposition**, on the
frame thread, for as long as the screen is open — and at the call site it looks like a field. Publish
the read as a flow beside it, collect it once at the top of the screen, and pass a plain value down —
under a shared shell, as a state-holder field nothing below can bypass (`screen-shell-content-split`):

```kotlin
// adapted — the two forms side by side, the second comment condensed to one line
fun isUserLoggedIn(): Boolean = runBlocking { dataStoreManager.cookie.first().isNotEmpty() }
// Flow-based variant so composables collect login state once instead of blocking in composition.
fun isUserLoggedInFlow(): Flow<Boolean> = dataStoreManager.cookie.map { it.isNotEmpty() }
```

**Scope that fix to the composition path; do not chase every call site.** The blocking form is fine
from a lifecycle callback or a coroutine — the two that survive here are read in `onDestroy` and once
at startup, so converting them buys a wide diff and nothing else. The leftover worth acting on is the
opposite one: three of the five blocking accessors here now have no caller at all.

**Cancelling `viewModelScope` in `onCleared` is redundant.** Take the runtime apart: `viewModelScope`
is a closeable scope registered on the ViewModel, and clearing the ViewModel closes it, which
cancels it. The extra `viewModelScope.cancel()` changes nothing. Harmless here — but the same line
copied onto a scope the class did *not* create (an injected application scope) cancels shared work
for the rest of the process, and it looks identical in review.

**Calling a method from the base `init` runs it before the subclass exists.** Kotlin runs base-class
initializers first, so anything the base `init` touches must not be overridable and must not read a
subclass field. The call here is safe only because it is `private`, which prevents an override; an
`open` or `abstract` member called from the base `init` reads uninitialized subclass state, and it
fails intermittently, on whichever field happened not to be assigned yet. Prefer a lifecycle method
the subclass calls explicitly.

**Property initialization order inside the base is real too.** Initializers run in declaration order,
and an `init {}` block runs in its position among them — so a block placed above a state field cannot
read that field. Launching a coroutine there is safe (it resumes later); reading a value is not.

**Container-awareness is a loosened contract, not a free one.** `by inject()` moves a dependency out
of the constructor, which means it is no longer visible to a test that constructs the class directly
and no longer checked at compile time. Keep constructor injection as the default and reserve the
container handle for what genuinely belongs to every screen.

**Convenience methods that delegate to a shared handler put behavior in the base.** Helpers such as
`loadMediaItem(...)` or `setQueueData(...)` are inherited by every screen, including those that must
never trigger them (see `polymorphic-load-media-entry-point` for what sits behind such an entry
point). If a subclass would be wrong to call it, it does not belong on the base.

## Verifying it

Measure the constructor, not the screen. Log a timestamp at the first line of the base `init` and at
the first frame the screen draws, then open several screens in sequence. A consistent tens-of-
milliseconds gap that scales with the number of resource or preference reads in initializers is the
blocking lookup, and it will not appear in a unit test — a test constructs the model off the main
thread and blocks nothing anyone can see.

For the base contract itself, construct one subclass directly, with no container configured. If it
throws, a `by inject()` member is on the constructor path and the base has made itself untestable.

Then audit the blocking accessors: a caller inside a `@Composable` is the per-frame case, and a
declaration with no caller at all is dead weight. Read each hit's receiver first: a same-named
member on another class prints as a caller, and narrowing to `\.<name>\(` does not exclude it.

```bash
grep -rnE "fun [A-Za-z]+\(\): [A-Za-z]+ = runBlocking" --include='*.kt' --exclude-dir=build .
# then per name printed above: grep -rn "<name>" --include='*.kt' --exclude-dir=build . | grep -v "fun "
```
