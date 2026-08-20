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

This is concise and it works: every subclass gets the shared dependency without threading it
through a dozen constructors, and the container definitions stay short. The cost is exact — **the
dependency disappears from the constructor**. Reading a subclass's signature no longer tells you
what it touches, a test must stand up a container instead of passing a fake, and one more
`by inject()` in the base silently adds a dependency to every view model in the app.

The defensible split: dependencies **every** subclass genuinely uses go in the base; anything a
subset needs stays a constructor parameter. Re-grep the base class periodically — the list only grows.

```bash
find <app>/src -type d -path '*/viewModel/base' -exec grep -rn 'by inject' --include='*.kt' {} +
```

## Annotation-based definitions register nothing until the generated module is loaded

The annotation route (`@KoinViewModel`, `@Single`, `@Factory` with the Kotlin Symbol Processing
plugin) generates a module — it does not register anything by itself. If that generated module is
never passed to the container, **everything still compiles**, the symbol processor still runs, and
not one definition exists at runtime.

The failure mode is entirely runtime and entirely partial: annotated classes that also have a
hand-written definition work, annotated classes that do not fail at the first resolve, and classes
obtained through the platform's own factory never notice. That combination is why it can sit in a
codebase for months — everything anyone actually opened happened to be in the hand-written module.

Anchor the first pattern where an annotation can sit — line start, optional indent, word boundary.
Unanchored, `@Factory` matches every `return@Factory` label return and `@Single` matches a leftover
`@Singleton` from the framework you are leaving, so it reports annotated files in a codebase with none:

```bash
# the annotations exist …
grep -rlnE '^[[:space:]]*@(KoinViewModel|Single|Factory)\b' --include="*.kt" . --exclude-dir=build
# … but is the generated module ever loaded?
grep -rn "org.koin.ksp.generated\|defaultModule" --include="*.kt" . --exclude-dir=build
```

Second grep empty while the first is not means every annotation is decorative. Both empty — the
result here — means the annotation route is not in use at all, a different answer and not a finding.
The proof is conclusive: remove the annotation dependency and the annotations; if nothing breaks,
nothing was registered.

Pick one style and enforce it. Mixing hand-written definitions with annotations means the module
file is no longer the answer to "what is registered", and the two disagree silently.

## The store owner decides identity, not which accessor you typed

The container never holds the instance. Every container accessor hands the platform a
`ViewModelStore` plus a key and asks it to resolve, supplying only the factory that builds the object
on a miss. With **no qualifier and no scope** the key comes out null, so the lookup lands on the
*default* slot of that store — the same slot the platform's own delegate uses.

| Written | Store owner it addresses | Built on first resolve by |
|---|---|---|
| `by viewModels<V>()` | this screen's own store | the platform factory |
| `by viewModel<V>()` | this screen's own store | your container definition |
| `by activityViewModels<V>()` | the host's store | the platform factory |
| `by activityViewModel<V>()` | the host's store | your container definition |

So the plural/singular pair in each row **collides on one slot and returns the same object** —
whichever ran first decided which factory built it. What produces two instances is the jump between
rows: a screen writing through `viewModel<V>()` and a sibling reading through
`activityViewModel<V>()` address two different stores and never see each other. That is the
difference worth grepping for, and it is one word wide. Giving a definition a qualifier or a
container scope splits the slot the other way — the key stops being null, so one owner now holds two.

Audit by import, not by call — and compare *owners*. Anchor on the delegate packages, or the second
pattern also matches the module-DSL `viewModel` builder, which is a definition and not a call site:
```bash
grep -rnE '^import (androidx|org\.koin\.androidx)\.[a-z.]+\.activityViewModels?$' \
  --include="*.kt" . --exclude-dir=build      # host store
grep -rnE '^import (androidx|org\.koin\.androidx)\.[a-z.]+\.viewModels?$' \
  --include="*.kt" . --exclude-dir=build      # this screen's own store
```
The same view-model type reached through both lists is the smell. Both empty, as here, means a
Compose-only codebase where the ambiguity mostly goes away — resolution is `koinViewModel()` at the
composable's default argument and the owner is whatever the navigation entry provides.

## A view model registered as `single` is yours to manage

```kotlin
single { SharedViewModel(get(), get(), get()) }   // process lifetime — you own it
viewModel { AlbumViewModel(get(), get()) }        // the host's store owns it; you gave it a factory
```

`single` is the right call for a genuinely session-scoped view model — one holding playback or
sign-in state that must survive every screen, and that non-screen components (a widget, a background
job, a notification handler) also need. It is also a promise: nothing clears it, and `onCleared`
will not run at a useful moment.

**Then do not unload the module that defines it.** Unloading removes a module's definitions from the
container. A screen that loads and unloads its module around its own lifetime looks tidy and breaks
every out-of-process or out-of-screen consumer: the next resolve throws "no definition found" for a
class plainly declared in a file you are looking at. The symptom shows up far from the cause — in a
widget refresh, minutes later — because that consumer is the only one resolving while no screen is
alive. If a module must be reloaded to reset state, reload it at creation, never unload on teardown.

```bash
grep -rn "unloadKoinModules" --include="*.kt" . --exclude-dir=build
```
Every hit needs an answer to "who else resolves from this module, and are they alive right now?"

## Traps

**A view model injected into a non-view-model is a design signal.** A widget or scheduled job
needing a view model means the operation it wants is not really presentation state. Lift the
operation instead — `no-use-case-layer-decision` covers when that is worth naming.

**`by inject()` in a constructor-injected class is a mixed metaphor.** Once a class takes some
dependencies as parameters and looks the rest up, no reader can tell which is which without reading
the body. Pick one per class.

**Definitions typed by the concrete class do not resolve by interface.** `single { Impl(get()) }`
registers `Impl`; a consumer asking for the interface finds nothing. Write `single<Interface> { … }`.
Same failure shape as the annotation trap: compiles fine, fails at first resolve.

**Do not register a platform host in the container to make a view model reachable.** The container
holds the reference past recreation, and every later resolve hands back a dead one. See
`hilt-to-koin-migration` for the rest of the container-lifetime traps.
