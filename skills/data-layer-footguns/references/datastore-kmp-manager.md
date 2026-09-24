---
name: datastore-kmp-manager
description: Build a multiplatform preferences manager — the store instance produced per platform from nothing but a file path, one observing flow plus one suspend setter per key, and the interface declared in the domain layer so feature code never imports the storage library. Use when adding shared settings to a Kotlin Multiplatform app, when a setting reads back as its default after an upgrade, or when a settings screen shows a stale value until it is reopened.
---

# A preferences manager across platforms

Three files, three jobs:

- **`core/domain` — the interface.** Feature code depends on this and nothing else.
- **`core/data` — the implementation.** The only place the storage library is imported, and the
  only place key names exist.
- **`core/data/<platform>` — the store instance.** An `expect fun` returning the store, whose
  actuals each contain *only a file path* — construction is delegated to one shared function.

```kotlin
// commonMain — shared creation, one line per platform below it
fun createDataStore(producePath: () -> String): DataStore<Preferences> =
    PreferenceDataStoreFactory.createWithPath(produceFile = { producePath().toPath() })

expect fun createDataStoreInstance(): DataStore<Preferences>

// androidMain  filesDir.resolve("datastore/$SETTINGS_FILENAME.preferences_pb").absolutePath
// jvmMain      File(homeFolder(".yourapp"), "$SETTINGS_FILENAME.preferences_pb").absolutePath
// iosMain      documentsDirectory() + "/$SETTINGS_FILENAME.preferences_pb"
```

Every setting is then exactly two members — a flow to observe and a suspending function to write:

```kotlin
// domain
val location: Flow<String>
suspend fun setLocation(location: String)

// data
override val location: Flow<String> =
    settingsDataStore.data.map { preferences -> preferences[LOCATION] ?: "VN" }

override suspend fun setLocation(location: String) {
    withContext(Dispatchers.IO) {
        settingsDataStore.edit { settings -> settings[LOCATION] = location }
    }
}
```

## Traps

**Putting the interface next to the implementation leaks the storage library into every feature.**
If `DataStoreManager` lives in the data module, a view model that wants one setting now compiles
against `Preferences`, `Preferences.Key<T>` and the whole preferences API — and swapping the
storage engine becomes a change to every consumer. The interface belongs in the layer both sides
already depend on. Its members are `Flow<T>` and `suspend fun`; neither is a storage type.

**A flow read once with `.first()` is a snapshot, and the screen stops updating.** This is the
single most common way a settings toggle "does not stick": something collected the value once at
construction, so the write lands in the store and the UI never hears about it. Expose the flow and
let the consumer collect it; reserve `.first()` for the one-shot places (a startup decision, a
value needed inside a write).

**A synchronous getter has to block a thread, and it will be the wrong one.** Where an API outside
your control demands a plain return value, the only way out is to block:

```kotlin
override fun getJVMProxy(): ProxyConfiguration? = runBlocking { /* reads several keys */ }
override fun setPlaybackSpeed(speed: Float) = runBlocking { settingsDataStore.edit { … } }
```

These are real and sometimes unavoidable — a proxy selector or a media-engine callback has no
suspending overload. Keep them **countable**: a handful, each with the reason at the call site.
The moment a UI path calls one, the UI is waiting on disk. **Verify by grepping your implementation
for the blocking call** and checking that no caller is on a main thread.

**Key identity is the name alone — the type parameter is a promise nobody checks.** In the
preferences implementation pinned here, two keys with the same name are *equal* regardless of type
parameter, and a read returns whatever object is stored under that name through an unchecked cast.
Change a key's type in a later release and the read does not miss — it *hits*, handing a value of
the old type to code expecting the new one, and fails at the use site. Renaming a key, by contrast,
really does surface as a silent reset to the default. Treat the key table as a schema either way:
add new keys, never repurpose an old name for a new type or meaning, and migrate explicitly if you
must.

**Pick one representation for booleans and put the constants where both layers can see them.** This
codebase stores them as the strings `"TRUE"` / `"FALSE"`, declared in the domain interface's
companion, so the flow type is `Flow<String>` and comparisons read `enabled == TRUE`. That is a
defensible choice — it survives a value gaining a third state — but it only works because the
constants are in the domain layer. Constants defined in the data module force every consumer to
hardcode string literals, and then one of them will spell it `"true"`.

**Defaults live in the read, not in the write.** `preferences[QUALITY] ?: DEFAULT` means a key never
written still answers correctly, and changing the default in a later release changes it for everyone
who never touched the setting. Writing a default at first launch instead freezes it forever and
makes "never set" indistinguishable from "explicitly set to the old default".

**The dynamic string escape hatch bypasses the typed key table.** A pair like

```kotlin
fun getString(key: String): Flow<String?>
suspend fun putString(key: String, value: String)
```

is genuinely useful for values whose names are computed. It is also how untyped, undiscoverable
keys accumulate: nothing lists them, nothing type-checks them, and a typo is a silent default. Keep
named members the default and reach for this only when the key really is data.

**Confine writes to an IO context, and do it in the manager.** `withContext(Dispatchers.IO)` around
every `edit` means no caller has to remember. Skipping it works — until a setter is called from a
main-thread coroutine and the write serializes behind another one.

**One store instance, created once.** The preferences store owns a file lock and a single write
queue; constructing a second one over the same path is undefined. Register it as a singleton in the
container and hand *that* to the manager, rather than letting the manager create its own.

## Verifying it

1. **The three files, and the platform hook, still match this shape:**
   ```bash
   grep -n "^interface DataStoreManager" core/domain/src/commonMain/kotlin/com/maxrave/domain/manager/DataStoreManager.kt   # your equivalent interface
   grep -rn "fun createDataStoreInstance" --include="*.kt" core/data/src   # your equivalent data module
   ```
   Pass condition: one `interface` in the domain module; one `expect fun` in commonMain and one
   `actual fun` per platform source set that needs it — here, android, jvm and ios each supply one.

2. **The boolean constants live where both layers can see them, not in the data module:**
   ```bash
   grep -n "companion object\|const val TRUE\|const val FALSE" core/domain/src/commonMain/kotlin/com/maxrave/domain/manager/DataStoreManager.kt
   ```
   Pass condition: `TRUE`/`FALSE` sit inside a `companion object` in the same file as the `interface`
   declaration — the domain module, not the data module.

3. **The synchronous getters stay countable, and the store is registered exactly once:**
   ```bash
   IMPL=core/data/src/commonMain/kotlin/com/maxrave/data/dataStore/DataStoreManagerImpl.kt   # your equivalent
   grep -c "runBlocking" "$IMPL"
   grep -rn "single<DataStoreManager>" --include="*.kt" . --exclude-dir=build
   ```
   Pass condition: the first count stays small — a handful, not a growing pattern — here, 7; the
   second finds exactly one registration. A second `single<DataStoreManager>` would mean two stores
   over the same path, which the manager itself has no way to detect.
