---
name: buildkonfig-secrets-flavors
description: Wire build-time configuration into a Kotlin Multiplatform app with BuildKonfig — secrets read from an untracked local properties file and injected as generated constants, with the no-secrets branch getting empty strings so the feature disables itself instead of failing the build, plus the task-dependency wiring newer Gradle demands for generated sources; reach for it when common code needs a compile-time constant, when an open-source build must not carry credentials, or when a build fails on an implicit dependency between a generated-source task and a consumer.
---

# Build-time configuration across a multiplatform app

Android's generated config object does not exist in common code. BuildKonfig fills that gap: it
generates one object, visible from `commonMain`, from values the build script supplies.

```kotlin
buildkonfig {
    packageName = "com.example.app"
    exposeObjectWithName = "BuildKonfig"
    defaultConfigs {
        buildConfigField(STRING, "versionName", libs.versions.version.name.get())
        buildConfigField(INT, "versionCode", libs.versions.version.code.get())
        // …plus the secret-bearing fields below
    }
}
```

The result is a plain `public object` of `public val`s in the package you named, so every platform
and every source set reads it identically — no `expect`/`actual`, no platform accessor.

## Secrets, and the two branches

Secrets come from an untracked properties file at the repo root (git-ignored; CI writes it from
repository secrets before the build). The build has two branches selected by a Gradle property —
one flavour that carries paid-integration credentials, one that carries none:

```kotlin
// adapted — field names genericised
val isFullBuild: Boolean = try { extra["isFullBuild"] == "true" } catch (e: Exception) { false }

if (isFullBuild) {
    try {
        val properties = Properties()
        properties.load(rootProject.file("local.properties").inputStream())
        buildConfigField(STRING, "integrationApiKey", properties.getProperty("INTEGRATION_API_KEY") ?: "")
        buildConfigField(STRING, "integrationSecret", properties.getProperty("INTEGRATION_SECRET") ?: "")
        buildConfigField(STRING, "crashReportingDsn", properties.getProperty("CRASH_DSN") ?: "")
    } catch (e: Exception) {
        println("Failed to load secrets from local.properties: ${e.message}")
        buildConfigField(STRING, "integrationApiKey", "")
        buildConfigField(STRING, "integrationSecret", "")
        buildConfigField(STRING, "crashReportingDsn", "")
    }
} else {
    // The no-secrets branch ships no credentials, so the availability check stays false
    // and the feature hides itself. The stub module is linked in this flavour anyway.
    buildConfigField(STRING, "integrationApiKey", "")
    buildConfigField(STRING, "integrationSecret", "")
    buildConfigField(STRING, "crashReportingDsn", "")
}
```

CI supplies the file, one line per secret, before invoking Gradle:

```yaml
- run: |
    echo 'CRASH_DSN=${{ secrets.CRASH_DSN }}' > ./local.properties
    echo 'INTEGRATION_API_KEY=${{ secrets.INTEGRATION_API_KEY }}' >> ./local.properties
```

## Traps

**Empty strings, never a missing field.** Both branches must declare **the same field names**. A
field defined only in one branch is a compile error in common code for the other, so the branch
without secrets would have to be a different source set — which is exactly the structure you are
trying to avoid. An empty value keeps one codebase.

**Make blank mean absent at runtime, once, in a named check.** Then the disable path is one
function every consumer already calls:

```kotlin
fun isIntegrationAvailable(): Boolean = apiKey.isNotEmpty() && sharedSecret.isNotEmpty()
```

Every entry point returns early on it, and the settings screen hides the whole block. The
paid-integration branch and the stub branch then behave identically for a build with no
credentials, so a contributor without secrets gets a working app rather than a broken feature.

**Catch and fall through, do not let a missing file fail the build.** A fresh clone has no
properties file. Loading it inside a `try` whose `catch` writes the same empty fields means a
contributor's first build succeeds — that is the difference between "you must be an employee to
compile this" and "you must be an employee to use this one feature".

**Never read the generated file for its values.** The generated source under the build directory
holds whatever the last local build injected, credentials included. Read the *shape* there if you
must; take the values from the build script.

**Guard the consumer on the value, not on the flavour.** Initialise optional services only when the
field is non-blank — `if (BuildKonfig.crashReportingDsn.isNotEmpty()) { … }`. A flavour check
compiles fine and then breaks the moment someone builds the full flavour without a secrets file.

**Newer Gradle rejects the implicit dependency between the generation task and its consumers.**
Under Gradle 9's strict task-dependency validation, a task that consumes generated sources without
declaring it fails the build rather than warning. If the plugin has not caught up, wire it yourself
by name:

```kotlin
afterEvaluate {
    tasks.matching { it.name.startsWith("prepare") && it.name.endsWith("ArtProfile") }
        .configureEach { dependsOn("generateBuildKonfig") }
}
```

The error names both tasks but *fails* the consuming one, so the message reads as being about a
subsystem you never touched. Match by name pattern rather than listing tasks: the set varies with
build type and flavour, so a hardcoded list breaks on the next variant added.

**Version values belong in the catalog, not in this block.** Reading them out of the version
catalog (`libs.versions.version.name.get()`) keeps one source of truth for a value that also
appears in packaging config and release workflows.

## Verifying it

```bash
# the untracked file must be ignored AND actually untracked
git check-ignore -v local.properties
git ls-files --error-unmatch local.properties   # must report "did not match any file"

# what the current build injected — SHAPE ONLY, values elided so no secret hits the terminal
find <app-module>/build/generated/source/buildkonfig -name 'BuildKonfig.kt' \
  -exec sed 's/=.*/= <elided>/' {} \;

# nothing secret should ever appear in a tracked file
git grep -nI -e 'API_KEY' -e 'SECRET' -e 'DSN' -- '*.kts' '*.kt' '*.yml'
```

The last one should only ever hit *names* — the property keys and the secret references in CI. A
hit on a value means it has already been committed, and the fix is rotating the credential, not
deleting the line.
