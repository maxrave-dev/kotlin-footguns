---
name: hilt-to-koin-migration
description: Move dependency injection from an annotation-processed compile-time framework (Hilt/Dagger) to the multiplatform runtime container (Koin) — the mechanical mapping for providers, view models and qualifiers, what happens to assisted injection, and the two failure modes the migration introduces: a graph that no longer fails at compile time, and a module definition that blocks the thread starting the container. Use when planning the migration, when a binding resolves to nothing at runtime after it, or when app start got slower afterwards.
---

# Migrating dependency injection to a multiplatform container

**The motive is reach, not ergonomics.** Hilt generates Android-specific code; Dagger's processor is
general JVM but is still a Java annotation processor. Neither runs against a `commonMain` source set
compiled for JVM/desktop *and* iOS, so once shared modules must be injected on more than one platform
a multiplatform runtime container is the only way to keep one wiring for all targets. Do not sell it
internally as "less boilerplate" — you trade a compile-time-verified graph for a runtime one, which
is a real cost (see the first trap).

## The mechanical mapping

| Before | After |
|---|---|
| `@Module @InstallIn(SingletonComponent::class) object X` | `val xModule = module { … }` |
| `@Provides @Singleton fun provideA(b: B): A` | `single<A> { provideA(get()) }` |
| `@Binds fun bind(impl: AImpl): A` | `single<A> { AImpl(get()) }` |
| `class C @Inject constructor(d: D)` | `single { C(get()) }` — the constructor is now written out |
| unscoped `@Inject constructor` | `factory { … }` — a new instance per resolve |
| `@HiltViewModel class V @Inject constructor(…)` | `viewModel { V(get(), get()) }` |
| `@Named("x")` / a qualifier annotation | `named("x")` on the definition, `get(named("x"))` at the use site |
| `@Inject lateinit var` field injection | implement `KoinComponent`, then `val a: A by inject()` |
| `@HiltAndroidApp` / `@AndroidEntryPoint` | nothing — call `startKoin { modules(…) }` once |

Constructor injection is the part that inverts. Under the annotation processor the constructor was
the declaration; under the container the constructor is written by hand inside the definition, and
`get()` fills each parameter positionally by type:

```kotlin
// adapted — parameter lists shortened
val repositoryModule = module {
    single<AlbumRepository> { AlbumRepositoryImpl(get(), get()) }
    single<CommonRepository> { CommonRepositoryImpl(get(named(SERVICE_SCOPE)), get(), get()) }
}
```

Type the definition by the **interface** (`single<AlbumRepository>`) or a consumer asking for the
interface finds nothing — the implementation is likely `internal` anyway (`clean-arch-kmp-readiness`).

Modules are then aggregated per layer behind one shared function, with a hook for the platform
parts:

```kotlin
// adapted — two load calls merged, platform hook renamed
fun loadAllModules() {                                  // commonMain
    loadKoinModules(listOf(databaseModule, repositoryModule, mediaHandlerModule))
    loadPlatformModules()
}
expect fun loadPlatformModules()
```

## Assisted injection has no direct equivalent

Assisted injection existed for objects whose constructor is partly supplied by a framework — a
worker handed a context and parameters at construction. The container has no equivalent. Two routes:

```kotlin
// adapted — the migration route: framework parameters stay plain, the injected one moves out
class NotifyWork(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params), KoinComponent {
    private val repository: SomeRepository by inject()
}

// the container's own route, when you control the call site
factory { (id: String) -> Presenter(id, get()) }
val p: Presenter = get { parametersOf(someId) }
```

The first is a genuine downgrade: the dependency leaves the constructor, so a test must stand up a
container instead of passing a fake. Use `parametersOf` wherever *you* own construction.

## Traps

**Nothing fails at compile time any more, and the replacement check is opt-in.** The processor used
to reject a missing binding before the app ran; the container discovers it at the first resolve —
which may be a screen three taps deep, in a release build, on a user's device. A module-verification
test (`checkModules` / `verify()`, from the container's test artifact) is the replacement, and it is
opt-in — put it on the migration checklist:
```bash
grep -rn "checkModules\|verify()" --include="*.kt" --include="*.kts" . --exclude-dir=build
```
A migration landing with no hits has quietly removed the only guarantee it had — the same family as
`config-fails-open-verify-artifact`: absence of an error is not evidence of correctness.

**Anything blocking inside an eager definition runs when the container starts — if that module is
loaded from inside `startKoin`.** Only `startKoin` creates eager instances by default; a
`loadKoinModules` call made *after* start does not, so the same definition is harmless in one
arrangement and blocks start-up in the other. The aggregation snippet above is invoked from inside
the `startKoin { }` lambda here, which is what puts this definition on the start-up path:

```kotlin
// adapted — cache type and provider renamed
single<DiskCache>(qualifier = named(PLAYER_CACHE), createdAtStart = true) {
    provideCache(
        cacheSize = runBlocking { get<SettingsManager>().maxCacheSize.first() },  // blocks start-up
        …
    )
}
```

It works, it is sometimes unavoidable when a constructor demands a plain value and the setting is a
flow, and it is invisible unless you profile start-up specifically. Keep such reads countable and
off the eager path — `datastore-kmp-manager` covers the same tension from the storage side. Audit:
```bash
grep -rn "runBlocking" --include="*.kt" $(find . -type d -name di -not -path "*/build/*")
```

**Whatever must happen before the container starts has to be moved above `startKoin` explicitly.**
Eagerly-created singletons touch real resources — a database file, a preferences file, a lock — the
instant the container starts, so a single-instance guard or a file migration that used to sit in the
first screen is already too late. Ordering is the fix, and only one platform tends to expose it.

**`named("…")` is a string, and a typo compiles.** Qualifier annotations were checked; qualifier
strings are not. Declare each as a constant in a module both sides depend on, and reference it.

**Everything becoming `single` is a silent behaviour change.** Unscoped bindings under the previous
framework produced a new instance per injection point; mapped onto `single` they get process
lifetime, and anything holding per-use state now shares it. Check that `factory` exists at all —
anchored to a **definition site**, or the search answers with prose: an unanchored `factory` matches
comments, and `return@Factory` label returns in unrelated code, so a codebase with no `factory`
definitions at all still looks like it has some:
```bash
grep -rnE '^[[:space:]]*factory(Of)?[[:space:]]*[<({]' --include="*.kt" . --exclude-dir=build
```
No output means every binding became process-wide — deliberate for repositories and clients, usually
wrong for anything holding request- or screen-scoped state. That is the result on this codebase: the
census is `single` and `viewModel` definitions only, with no `factory`, `factoryOf` or `scoped`.

**Do not put a platform component into the container to make injection convenient.** Registering an
activity, a window or a service hands the container a reference that outlives it, so every consumer
resolves a stale one after the first recreation. Pass it as a parameter instead. View-model wiring
has its own set of these — see `koin-viewmodel-scoping-traps`.
