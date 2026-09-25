---
name: foss-vs-proprietary-module-pairs
description: Ship one codebase in two forms — a full build carrying a proprietary or credentialed integration and an open build carrying a no-op stub — using twin modules with an identical public API selected by a Gradle property rather than product flavors, which do not exist for non-Android multiplatform targets. Reach for it when a tracking, casting, or paid-service dependency must be absent from an open-source build, when call sites are littered with build-flavor branches, or when the "clean" build still pulls the proprietary artifact through a transitive path.
---

# Twin modules: `<feature>` and `<feature>-empty`

Two modules, same package, same declarations. One wraps the real integration; the other returns
values that make every caller take the "not available" path without knowing there is one.

```kotlin
// adapted — <feature>-empty/src/…/<Feature>.kt
package com.example.app.<feature>

// STUB build: <feature> is not available. Every function is a safe no-op so callers
// never branch on the build.

fun init<Feature>(context: Context): Boolean {
    Logger.d(TAG, UNAVAILABLE)
    return false
}

fun is<Feature>Available(): Boolean = false

fun wrapPlayer(context: Context, localPlayer: Player): Player = localPlayer

fun currentDeviceName(): String? = null

@Composable
fun <Feature>IconButton(modifier: Modifier = Modifier, tint: Color = Color.White) {
    // no-op
}
```

Selection is a Gradle property, read the same way in every consuming module:

```kotlin
// adapted — top of each consuming build script
val isFullBuild: Boolean = try { extra["isFullBuild"] == "true" } catch (e: Exception) { false }

// …in that module's dependency block
if (isFullBuild) implementation(projects.<feature>) else implementation(projects.<feature>Empty)
```

The property has a default in `gradle.properties`; continuous integration appends a line to that same
file before invoking Gradle, one value per job — `run: echo "isFullBuild=false" >> ./gradle.properties`.

## Why a property, not product flavors

Product flavors are an Android Gradle Plugin concept. A Kotlin Multiplatform module's `jvm()`,
`ios*()` and common source sets have no flavor dimension, so a flavor cannot select a dependency for
them — and here the twins are consumed from *both* an Android-only module and the `commonMain`
dependency block of a multiplatform module. One property covers every module and every target; a
flavor covers a subset and silently leaves the rest on whichever twin was hardcoded.

## Traps

**Every consuming module must read the same property, or the graph mixes.** The gate is per-module,
so one module that hardcodes the real twin drags the proprietary code into the open build through a
transitive path — and it links fine, so nothing complains. Enumerate both sides and compare:

```bash
grep -rn 'isFullBuild' --include='*.kts' --include='*.properties' --include='*.yml' . | grep -v '/build/'
grep -rn '<feature>Empty\|<feature>-empty' --include='*.kts' . | grep -v '/build/'
```

Every module in the second list must also appear in the first. Here the pairs are gated from build
scripts across the whole tree, including one deep in the data layer that nothing about the user
interface would have led you to.

**Both twins declare the same package *and* the same Android namespace** — that is what makes the
swap invisible: imports do not change, so no call site knows which module it linked against.

**The stub returns identity, never null, wherever the real one transforms.** `wrapPlayer` handing
back `localPlayer` unchanged is the shape to copy. A stub returning `null` there forces every caller
into a branch — the thing this pattern exists to delete.

**The availability check is the entire hiding mechanism.** The stub's `is<Feature>Available()`
returns a hardcoded `false`; the real one derives it from whether the credential was injected:

```kotlin
fun is<Feature>Available(): Boolean = apiKey.isNotEmpty() && sharedSecret.isNotEmpty()
```

That second form is what makes a full build *without* credentials behave exactly like the stub build
instead of offering a login that can never succeed. Pair it with `buildkonfig-secrets-flavors`, which
supplies the empty strings on the no-secrets branch. Then confirm the check is consulted —
`grep -rn 'is<Feature>Available()' --include='*.kt' . | grep -v '/build/'` should hit at least the
settings screen (so the whole block hides) and the service entry point (so background work returns
early).

**The stub needs enough to compile the same signatures, and nothing from the vendor.** The stub here
carries the neutral type artifact for the player interface, the Compose runtime for the composable,
and the project's own shared modules — but no proprietary artifact. Read the difference directly
rather than assuming it, and match the declarations wherever they sit: a multiplatform twin keeps
them indented inside `sourceSets { … { dependencies { … } } }`, where a `/^dependencies {/` capture
matches zero lines and the diff passes silently.

```bash
deps() { grep -hoE '^[[:space:]]*(implementation|api|compileOnly|runtimeOnly)\(.*' "$1" \
           | sed 's/^ *//' | sort; }
diff <(deps <feature>/build.gradle.kts) <(deps <feature>-empty/build.gradle.kts)
```

Lines only on the proprietary side should be the vendor's artifacts. Lines only on the *stub* side
are not automatically drift — a stub often needs a shared or logging module the real twin gets
transitively — so read each one rather than deleting it.

**Missing declarations only fail in the branch you are not building.** The two files are kept in
lockstep by hand, so a function added to the real twin and forgotten in the stub compiles locally and
fails elsewhere. Data classes, sealed hierarchies and constants count: the stub here re-declares the
full result hierarchy including its error codes, because callers pattern match on them.

**Reading the property must not fail when it is absent.** The `try`/`catch` defaulting to `false` is
deliberate — a module with no property in scope gets the stub, the branch that always builds. The
checked-in default may still be the *full* build, as it is here, but that is only safe because the
credential reader catches a missing `local.properties` and writes empty fields, which the
availability check above turns back into stub behaviour. Without that catch, defaulting to full
makes a contributor's first build fail on a missing credential.

**A stub is not a place for TODOs.** These functions are called from playback callbacks and from
composition, so every one must be complete and safe on a hot path. One log line per call is fine;
throwing, or returning a partially initialised object, is not.

## Verifying it

```bash
# the two public surfaces must declare the same names.
# The final `sort` is load-bearing: `uniq -u` only collapses ADJACENT duplicates, so two
# separately sorted lists concatenated make it report every declaration as one-sided.
for m in <feature> <feature>-empty; do
  grep -rhoE '^(fun|suspend fun|data class|sealed interface|@Composable)[^({]*' "$m/src" | sort
done | sort | uniq -u    # must print nothing — anything listed exists on one side only

# both twins stay in the project list unconditionally; selection happens per dependency
grep -n '<feature>' settings.gradle.kts
```

That second point matters. Conditionally `include()`-ing a project makes the whole configuration
depend on the property, which breaks tooling that resolves the project list without one.
