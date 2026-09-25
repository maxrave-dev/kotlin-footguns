---
name: koin-viewmodel-scoping-traps
description: Wiring view models through a runtime dependency-injection container without losing track of their lifetime — the service-locator base class and what it costs, annotation-based definitions that compile but register nothing, which store owner each accessor addresses and why that (not the accessor's spelling) decides whether two screens share an instance, and what registering a view model as a process-wide singleton makes you responsible for. Use when a view model resolves to a fresh instance that should have been shared, when a lookup fails at runtime for a class that is clearly annotated, or when state vanishes between screens.
---

# View-model wiring traps in a runtime container

A container resolves by type at the moment of the call. A view model has a lifetime the platform
owns. Every trap below is those two facts disagreeing, and none of them fails at compile time.

## The base class as a service locator

```kotlin
// adapted — injected property renamed, body trimmed
abstract class BaseViewModel :
    ViewModel(),
    KoinComponent {
    protected val mediaHandler: MediaPlayerHandler by inject<MediaPlayerHandler>()
    // shared logging, toast, loading-dialog state …
}
```

It works, and it is concise: every subclass gets the shared dependency without threading it through
a dozen constructors, and definitions stay short. The cost is exact — **the dependency disappears
from the constructor**: a subclass's signature no longer says what it touches, a test must stand up
a container rather than pass a fake, and one `by inject()` in the base adds one to every view model.
The defensible split: dependencies **every** subclass genuinely uses go in the base; anything a
subset needs stays a constructor parameter. Re-grep the list periodically — see Verifying it, #1.

## Annotation-based definitions register nothing until the generated module is loaded

The annotation route (`@KoinViewModel`, `@Single`, `@Factory` with the Kotlin Symbol Processing
plugin) generates a module — it does not register anything by itself. If that generated module is
never passed to the container, **everything still compiles**, the symbol processor still runs, and
not one definition exists at runtime.
The failure is entirely runtime and entirely partial: annotated classes that also have a
hand-written definition work, those that do not fail at the first resolve, and classes obtained
through the platform's own factory never notice — which is why it sits for months: everything anyone
opened was in the hand-written module.
Pick one style and enforce it: mixing hand-written definitions with annotations means the module
file is no longer the answer to "what is registered", and the two disagree silently — see
Verifying it, #2 for the census and how to read it.

## The store owner decides identity, not which accessor you typed

The container never holds the instance. Every accessor hands the platform a `ViewModelStore` plus a
key and asks it to resolve, supplying only the factory that builds the object on a miss. With **no
qualifier and no scope** the key comes out null, so the lookup lands on that store's *default* slot
— the same slot the platform's own delegate uses.

| Written | Store owner it addresses | Built on first resolve by |
|---|---|---|
| `by viewModels<V>()` | this screen's own store | the platform factory |
| `by viewModel<V>()` | this screen's own store | your container definition |
| `by activityViewModels<V>()` | the host's store | the platform factory |
| `by activityViewModel<V>()` | the host's store | your container definition |

So the plural/singular pair in each row **collides on one slot and returns the same object** —
whichever ran first decided which factory built it. What produces two instances is the jump between
rows: a screen writing through `viewModel<V>()` and a sibling reading through
`activityViewModel<V>()` address two different stores and never see each other — a difference one
word wide. Giving a definition a qualifier or a container scope splits the slot the other way — the
key stops being null, so one owner now holds two.
Audit by import, not by call — and compare *owners*. Anchor on the delegate packages, or the second
pattern also matches the module-DSL `viewModel` builder, which is a definition and not a call site:
```bash
grep -rnE --include='*.kt' --exclude-dir=build '^import (androidx|org\.koin\.androidx)\.[a-z.]+\.activityViewModels?$' .  # host store
grep -rnE --include='*.kt' --exclude-dir=build '^import (androidx|org\.koin\.androidx)\.[a-z.]+\.viewModels?$' .  # own store
```
The same view-model type reached through both lists is the smell. Both empty, as here, means a
Compose-only codebase where the ambiguity mostly goes away — resolution is `koinViewModel()` at the
composable's default argument and the owner is whatever the navigation entry provides.

## A view model registered as `single` is yours to manage

```kotlin
single { SharedViewModel(get(), get(), get()) }   // adapted — argument list shortened (real ctor takes nine); still process lifetime, you own it
viewModel { AlbumViewModel(get(), get()) }        // accurate as shown — the host's store owns it; you gave it a factory
```

`single` is the right call for a genuinely session-scoped view model — one holding playback or
sign-in state that must survive every screen, and that non-screen components (a widget, a background
job, a notification handler) also need. It is also a promise: nothing clears it, and `onCleared`
will not run at a useful moment.
**Then do not unload the module that defines it.** Unloading removes a module's definitions from the
container. A screen that loads and unloads its module around its own lifetime looks tidy and breaks
every out-of-process or out-of-screen consumer: the next resolve throws "no definition found" for a
class plainly declared in a file you are looking at — the symptom shows up far from the cause, in a widget refresh minutes later,
because that consumer is the only one resolving while no screen is alive. If a module must be reloaded to reset state, reload it at creation, never unload on teardown.

```bash
grep -rn "unloadKoinModules" --include="*.kt" . --exclude-dir=build
```
Every hit needs an answer to "who else resolves from this module, and are they alive right now?"

## Traps

**For one value off a shared flow, inject the repository, not a view model.** A leaf composable — a
top-bar icon needing one boolean — on several screens gets a *separate* view model per screen. Same
reasoning, harder, for a widget or a scheduled job: a `viewModel { }` definition has **no owner**
outside a composition, so there it does not duplicate, it fails to resolve. And if the operation it
wanted is not really presentation state, lift the operation — `no-use-case-layer-decision`.

**`by inject()` in a constructor-injected class is a mixed metaphor.** Once a class takes some
dependencies as parameters and looks the rest up, no reader can tell which is which without reading
the body. Pick one per class.

**Definitions typed by the concrete class do not resolve by interface.** `single { Impl(get()) }`
registers `Impl`; a consumer asking for the interface finds nothing. Write `single<Interface> { … }`.
Same failure shape as the annotation trap: compiles fine, fails at first resolve.

**Do not register a platform host in the container to make a view model reachable.** The container
holds the reference past recreation, and every later resolve hands back a dead one. See
`hilt-to-koin-migration` for the rest of the container-lifetime traps.

## Verifying it

1. **The base class's dependency list, and how far it reaches:**
   ```bash
   BASE_DIR=composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/viewModel/base   # your equivalent
   grep -rn 'by inject' --include='*.kt' "$BASE_DIR"
   grep -rlE '\) ?: ?BaseViewModel\(' --include='*.kt' composeApp/src | wc -l
   ```
   Pass condition: first lists every base-class injection (one, here); second counts the inheritors (22, here).

2. **The annotation route, anchored — unanchored, `@Factory` matches every `return@Factory` label and `@Single` matches a leftover `@Singleton` — and checked both ways, since one grep alone can't tell decorative from unused:**
   ```bash
   grep -rlnE '^[[:space:]]*@(KoinViewModel|Single|Factory)\b' --include="*.kt" . --exclude-dir=build
   grep -rn "org.koin.ksp.generated\|defaultModule" --include="*.kt" . --exclude-dir=build
   ```
   Pass condition: second empty while the first is not means decorative annotations; both empty, as
   here, means the route is unused — a different, equally valid answer.

3. **`SharedViewModel` and `AlbumViewModel` still have the scoping shown above:**
   ```bash
   VM=composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/di/ViewModelModule.kt   # your equivalent
   grep -n -B1 "SharedViewModel($\|AlbumViewModel($" "$VM"
   ```
   Pass condition: `SharedViewModel(` follows `single {`, `AlbumViewModel(` follows `viewModel {` —
   here 2 `single {` blocks stand against 22 `viewModel {` ones.
