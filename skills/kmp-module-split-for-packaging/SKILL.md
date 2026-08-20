---
name: kmp-module-split-for-packaging
description: Split one Kotlin Multiplatform UI module into a shared app LIBRARY plus thin per-platform launcher modules — an Android application module that only packages, and a JVM/desktop module that owns main() and hands off to a public function in the library. Reach for it when the Android Gradle Plugin refuses to let your app module also be a multiplatform target, when packaging config and shared UI are tangled in one build script, or when a resource accessor class stopped generating after a module became a library.
---

# One shared library, thin launchers

Three modules, and each has exactly one job:

| Module | Plugins applied | Owns |
|---|---|---|
| `<shared-ui>` | Kotlin Multiplatform + the Android **multiplatform library** plugin + Compose | all UI, view models, `expect`/`actual`, shared resources |
| `<android-launcher>` | the Android **application** plugin, plus whatever its own sources and packaging need | manifest, launcher icons, application class, shrinker rules, ABI splits, store config |
| `<desktop-launcher>` | Kotlin Multiplatform with a single `jvm()` target + Compose desktop + the packaging plugin | `main()`, packaging targets, installer metadata, shrinker wiring |

**Plugin lists overlap, and that is expected.** All three modules here apply the Compose compiler;
the shared module and the desktop launcher both apply Kotlin Multiplatform and Compose
Multiplatform. A launcher applies whatever its own sources and packaging block need. What the split
makes exclusive is **ownership** — app identity and packaging versus shared code — not which plugin
ids may appear where; dropping one from a launcher breaks that launcher's own sources.

Both launchers depend on the library and add nothing to it:

```kotlin
// <android-launcher>/build.gradle.kts
implementation(projects.<sharedUi>)

// <desktop-launcher>/build.gradle.kts — inside sourceSets { jvmMain { dependencies { … } } }
implementation(project(":<shared-ui>"))
```

## Why the Android side is not optional

The Android Gradle Plugin (AGP) ships its multiplatform support as a **library** plugin, and only
that. Check your own version rather than trusting a version note:

```bash
AGP=$(grep -oP '^android\s*=\s*"\K[^"]+' gradle/libs.versions.toml)
unzip -l "$(find ~/.gradle/caches/modules-2 -path '*com.android.tools.build/gradle/*' \
  -name "gradle-$AGP.jar" | head -1)" | grep -o 'META-INF/gradle-plugins/[a-z.]*\.properties'
```

Under AGP 9.2.1 that lists `com.android.application` and `com.android.kotlin.multiplatform.library`
as separate plugin ids, with **no multiplatform *application* id at all** — and among the jar's
`KotlinMultiplatformAndroid*` types, the ones naming a module kind name the library
(`…LibraryExtensionImpl`, `…LibraryTargetImpl`) while **none is named `…Application…`**. So the
module carrying your Android multiplatform target is a library by construction, and the module that
produces the installable artifact has to be a different, plain Android application module.

## The desktop handoff is one public function

The library keeps every window, tray, crash-handler and dependency-container detail. It exposes one
entry point; the launcher owns `main()` and therefore owns argv:

```kotlin
// <shared-ui>/src/jvmMain/…/DesktopApp.kt
fun runDesktopApp(args: Array<String> = emptyArray()) { /* windows, dependency-injection start-up, deep links, tray */ }

// <desktop-launcher>/src/jvmMain/…/Main.kt — adapted
fun main(args: Array<String>) {
    forcePlatformWindowClass()   // pre-UI platform tweak that must run before any window opens
    runDesktopApp(args)
}
```

The packaging block points at exactly this file — `mainClass = "com.example.app.MainKt"`. Keeping the
handoff a plain function (not a class the packager instantiates) is what still lets the library be
launched directly in development.

## Traps

**A library and an application do not default the same way, and the difference is silent.** The
build script here records that once the shared module became a library, the Compose resources plugin
stopped generating the resource accessor class under its default `auto` mode — its reading is that a
library is not treated as owning the public resource class. Either way, the pin is the fix:

```kotlin
compose.resources { generateResClass = always }
```

Verify against the artifact, not the setting: `find <shared-ui>/build/generated -name 'Res.kt'` must
find one. Audit every other "app vs library" default the same way after the split.

**A task defined in the library is not wired into the launcher's packaging by proximity.** Native
staging, code generation and asset preparation can stay in the library, but each packaging task in
the launcher must name the cross-project dependency itself:

```kotlin
tasks.register<Exec>("package<Platform>") {
    dependsOn(":<shared-ui>:stageNatives")
    …
}
```

Find the ones you forgot: `grep -n 'tasks.register\|dependsOn' <desktop-launcher>/build.gradle.kts`
and check that every packaging task listed has a `dependsOn` line. A missing one packages whatever
happened to be left in the staging directory from a previous run — it succeeds, and ships stale
binaries.

**Plugin order in the launcher is load-bearing, not style.** A packaging plugin that creates its
tasks at apply time can only do so once the task it looks for already exists, and a plugin applied
after it can replace that task under a different name. The launcher here records that ordering in a
comment above its `plugins { }` block — treat a reorder as a behavioural change, not a tidy-up.

**A single-target launcher may still need the multiplatform plugin.** The desktop launcher applies
Kotlin Multiplatform for one `jvm()` target and nothing else, because the packaging plugin resolves
a runtime classpath under the multiplatform naming convention — that is what the build script
records. Confirm your packager finds a classpath before dropping to a plain JVM plugin.

**Every conditional in the dependency graph must be repeated per launcher.** A dependency chosen by
a Gradle property is chosen in *each* module that declares it — the Android launcher and the shared
library each carry their own branch. See `foss-vs-proprietary-module-pairs`.

**The shrinker runs in the launcher while its rules file often stays with the library.** The desktop
launcher points at `rootDir.resolve("<shared-ui>/proguard-desktop-rules.pro")`. That is fine, but it
means neither file mentions the other — grep for the rules file by name before assuming it is unused.
See `r8-proguard-desktop-survival`.

**Do not let the launcher grow.** Anything in it is, by definition, unshared — so measure it rather
than trusting the intent: `find <android-launcher>/src -name '*.kt' | wc -l`. The desktop launcher
here holds a single file; the Android one holds the application class, the activity and the
platform-only pieces that genuinely cannot move. A UI file in that list belongs in the library —
*unless* the platform only accepts that UI from an application module. The home-screen widget
composables here (`MainAppWidget`, `TurntableWidget`, `WidgetIconButton`) are the standing exception:
their receiver is declared in the application manifest, so the UI cannot move away from it.

## Verifying it

```bash
# read each module's plugin list — overlap is expected; what must not overlap is what they own
grep -n -A12 '^plugins {' <shared-ui>/build.gradle.kts \
  <android-launcher>/build.gradle.kts <desktop-launcher>/build.gradle.kts

# nothing may depend on a launcher; anchor on the dependency forms or comments drown the result
grep -rnE 'project\(":(<android-launcher>|<desktop-launcher>)"\)|projects\.(<androidLauncher>|<desktopLauncher>)' \
  --include='*.kts' . | grep -v '/build/'
```

The second must return nothing at all — `include()` lines do not match it, so there is no
expected-hit list to remember.
