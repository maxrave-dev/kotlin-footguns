---
name: room-kmp-setup
description: Set up one Room database shared across Android, JVM/desktop and iOS with an expect/actual builder per platform, a bundled SQLite driver chosen once at the injection site, and a per-architecture audit of the driver artifact. Use when adding Room to a Kotlin Multiplatform module, when one target fails at the first database connection while the others work, or when a target compiles but its generated database implementation is missing.
---

# Room in a multiplatform module

The database class, its entities and its DAOs live in `commonMain`. Only two things vary per
platform: **where the file goes** and **what the builder is handed**. Both hide behind one
`expect`:

```kotlin
// commonMain
@Database(entities = [...], version = <N>, exportSchema = true, autoMigrations = [...])
@TypeConverters(Converters::class)
abstract class MusicDatabase : RoomDatabase() {
    abstract fun getDatabaseDao(): DatabaseDao
}

expect fun getDatabaseBuilder(converters: Converters): RoomDatabase.Builder<MusicDatabase>
```

The driver and the query dispatcher are set **once**, at the shared injection site, so no platform
can disagree about them:

```kotlin
// commonMain DI
single(createdAtStart = true) {
    getDatabaseBuilder(get<Converters>())
        .setDriver(BundledSQLiteDriver())
        .setQueryCoroutineContext(Dispatchers.IO)
        .build()
}
```

The actuals differ only in the overload they reach for. Desktop and iOS pass an **absolute file
path** as `name`; Android passes a context, the class and a **bare filename**:

```kotlin
// jvmMain            Room.databaseBuilder<MusicDatabase>(name = absolutePathTo(DB_NAME))
// iosMain            Room.databaseBuilder<MusicDatabase>(name = documentsDir() + "/$DB_NAME")
// androidMain        Room.databaseBuilder(context, MusicDatabase::class.java, DB_NAME)
```

## Traps

**One annotation-processor configuration per declared target — a missing one is silent until
link time.** The processor generates the database implementation per compilation, so every target
you declare needs its own entry:

```kotlin
dependencies {
    add("kspAndroid", libs.room.compiler)
    add("kspJvm", libs.room.compiler)
    add("kspIosArm64", libs.room.compiler)
    add("kspIosSimulatorArm64", libs.room.compiler)
}
```

Forget one and that target compiles your source fine, then fails with no generated implementation for the abstract database class
(reproduced below, against every simulator variant too).

**Anything registered on the builder lives in the platform actual, so it exists only on the platforms that register it.** Migrations,
`addCallback`, destructive-fallback policy and open-helper tweaks are all builder calls. In this codebase the hand-written migrations
and the trigger-recreating `onOpen` callback are attached inside the Android actual only; the JVM and iOS actuals register nothing
beyond the type converter. Nothing warns about it — those platforms simply run a database with no triggers and no hand-written
migration steps. **Put everything shared in a common extension the actuals call**, and keep the actual down to the path.

**The expect signature is the lowest common denominator, so a platform-only dependency has to be reached another way.**
`getDatabaseBuilder(converters)` cannot take an Android `Context`, so the Android actual pulls one from the service locator
(`getKoin().get<Context>()`). That works, but it moves a compile-time error to a runtime one: the container must already hold a
context by the time the database singleton is created. If your container builds eagerly, register the context first.

**Export the schema directory or generated migrations cannot exist.** Generated migrations are
produced by diffing two exported schema files at build time:

```kotlin
room { schemaDirectory("$projectDir/schemas") }
```

Commit every `<version>.json` it writes. Deleting an old one does not break the build — it breaks the upgrade path for users still on that version, months later.

**The bundled driver ships one native slice per CPU architecture, and one missing slice kills the
whole target.** Do not assume coverage from the fact that the artifact is "multiplatform". Open the
JAR and look:

```bash
# pin the version you actually build with — read it from your version catalog first
unzip -l $(find ~/.gradle/caches -name "sqlite-bundled-jvm-<your-version>.jar" | head -1) \
  | grep -oE 'natives/[a-z0-9_]+/' | sort -u
```

A Gradle cache holds every version ever resolved, so an unpinned wildcard with `head -1` can audit
a version you no longer ship.

At one version we inspected, this printed `linux_arm64`, `linux_x64`, `osx_arm64`, `osx_x64` and `windows_x64` — Windows on ARM was
**the one combination with no slice**, even though Linux and macOS both had theirs. A desktop build promising that target starts,
paints its first screen, and then fails at the first database connection. Re-run the command against *your* version rather than
trusting this list; slices get added over time (below, this repo's own pinned version drops a *different* one). The same audit
applies to every native dependency in a desktop target: run it before you promise an architecture, because one gap drops the target.

**Driver choice and native linking are configured in different files.** The iOS framework here
declares `linkerOpts.add("-lsqlite3")` — the flag a system-SQLite driver needs — while the shared DI
module installs the bundled driver. Neither file mentions the other. **Verify which driver the
running app got**, by logging it at the injection site or by breaking on the builder, rather than
by reading either file alone.

**Type converters are constructor-injected, so they are a dependency of the database, not a
detail of it.** `addTypeConverter(converters)` takes an *instance*; whatever that instance needs
(a JSON format, a clock) must be constructible before the database. Registering it as its own
eagerly-created singleton keeps that ordering explicit instead of accidental.

## Verifying it

Run from the repository root.

1. **Audit the bundled driver's native slices against your own pinned version — a recorded list goes stale in either direction:**

   ```bash
   grep -n 'sqlite = "' gradle/libs.versions.toml
   unzip -l $(find ~/.gradle/caches -name "sqlite-bundled-jvm-2.7.0.jar" | head -1) | grep -oE 'natives/[a-z0-9_]+/' | sort -u
   ```

   Run here, at the version this repo actually pins (`2.7.0`): `linux_arm64`, `linux_x64`, `osx_arm64`, `windows_x64` — `osx_x64`
   (Intel Mac) is the slice missing, not the Windows-ARM one this file names above. That mismatch is the point: re-run against your version.

2. **Migrations/callback and the ksp processor are each all-or-nothing across targets, never a silent subset:**

   ```bash
   grep -n "addMigrations\|addCallback" core/data/src/androidMain/kotlin/com/maxrave/data/db/MusicDatabase.android.kt \
     core/data/src/jvmMain/kotlin/com/maxrave/data/db/MusicDatabase.jvm.kt core/data/src/iosMain/kotlin/com/maxrave/data/db/MusicDatabase.ios.kt
   grep -n 'add("ksp' core/data/build.gradle.kts
   grep -nE '^\s*(android|jvm) \{|ios[A-Za-z0-9]+\(\)' core/data/build.gradle.kts
   ```

   Pass condition: the first command hits only in the `.android.kt` file; the second and third lists match one-for-one — here,
   `kspAndroid`/`kspJvm`/`kspIosArm64`/`kspIosSimulatorArm64` against `android {`/`jvm {`/`iosArm64()`/`iosSimulatorArm64()`.

3. **By hand: log which driver the running app actually got**, at the injection site, on both the desktop and iOS builds. Correct:
   the log always names the bundled driver — the iOS linker flag alone would suggest otherwise, and neither file mentions the other.
