---
name: reproducible-native-bundling-two-tasks
description: Ship prebuilt native libraries to a multiplatform desktop build by splitting bundling into two Gradle tasks with different homes — a dev-machine task that builds the slices, packs tarballs and prints their digests, and a CI task that only downloads and verifies against digests pinned in the build file; reach for it when CI needs a native toolchain it should not have, when a native bump quietly ships the previous binaries, or when the packaged installer launches with the native missing entirely.
---

# Two-task native bundling

A desktop app that loads a native library has to get that library from somewhere. Building it
inside CI drags the whole toolchain (archivers, patchers, container runtimes, a signing host)
onto every runner, for artifacts that do not change between commits.

Split it into **two entry points with different homes**:

| Task | Runs | Does |
|---|---|---|
| `nativesBundleAll` | a dev machine, once per native version bump | build/collect every per-platform slice, pack one tarball each, **print the digests** |
| `nativesSetupAll` | every CI job, every build | download the published tarballs, **verify against pinned digests**, unpack |

The CI task needs nothing but a network connection, `curl` to fetch each tarball, and `tar`.

```kotlin
// adapted — names shortened, real digests elided
val slices = listOf("linux-x64", "macos-arm64", "macos-x64", "windows-x64", "windows-arm64")

val nativesBundleAll by tasks.registering {
    dependsOn(/* the per-platform build tasks */)
    doLast {
        slices.forEach { slice ->
            val sliceDir = rootDir.resolve("natives/$slice")
            check(sliceDir.isDirectory && sliceDir.listFiles()?.isNotEmpty() == true) {
                "natives/$slice is missing or empty — cannot pack an incomplete set"
            }
            runChecked("tar", "-czf", dist.resolve("natives-$slice.tar.gz").absolutePath,
                "-C", rootDir.resolve("natives").absolutePath, slice)
        }
        logger.lifecycle("Paste these into nativesChecksums:")
        slices.forEach { slice ->
            logger.lifecycle("        \"$slice\" to \"${sha256(dist.resolve("natives-$slice.tar.gz"))}\",")
        }
    }
}
```

The bundle task printing lines that are **already in the source syntax of the checksum map** is the
whole ergonomic trick: the update after a bump is a paste, so nobody is tempted to skip it.

## Traps

**An externally invoked packaging step does not trigger Gradle task dependencies.** If the packager
runs as its own CI action rather than through a Gradle task, the `dependsOn(":app:nativesSetupAll")`
you wired into the packaging tasks never fires on that path, and the installers ship with the
native missing — a build that is green and an app that dies on first use. Every workflow that
packages must call the setup task as its own explicit step:

```yaml
# adapted
- name: Populate natives for all OSes
  # The packager is invoked by its own action, NOT through Gradle, so the
  # dependsOn wired into the packaging tasks never fires on this path.
  run: ./gradlew :<app-module>:nativesSetupAll --no-configuration-cache
```

**Without declared inputs, Gradle treats the existing output directory as up to date.** The setup
task's only real output is a directory that already exists from the previous run, so bumping the
release tag or the native version silently keeps shipping the previous binaries. Declare the tag
*and the checksum map* as inputs:

```kotlin
inputs.property("nativesTag", nativesTag)
inputs.property("nativesChecksums", nativesChecksums)
outputs.dir(outputRoot)
```

**Pin the digests in the build file, not from a checksum file served next to the artifact.** A
checksum served from the same place as the artifact catches corruption but not anyone able to
replace release assets — and these files unpack straight into the tree the packager signs. If the
release tag is mutable, the pinned map is the only thing actually pinning what ships.

**Make the cache key include the tag, not just the version.** Re-publishing corrected natives under
a new tag at the same upstream version must not reuse the stale download:
`natives-$slice-$tag.tar.gz`.

**Delete the archive on mismatch.** Otherwise a genuinely corrupt download is cached and every
retry fails identically:

```kotlin
check(actual == expected) {
    archive.delete()
    "Checksum mismatch for natives-$slice.tar.gz\n  expected $expected\n  actual   $actual"
}
```

**Give the not-yet-pinned state its own sentinel and message.** A missing entry should fail with
the instruction, not with a map lookup error: `check(expected != "PENDING") { "No checksum pinned
for $slice. Run the bundle task, publish the archives, then paste the printed digests." }`

**Publish the tarballs somewhere other than the app's own releases.** They are large and change
only on a bump; in the app's release list they bury the downloads users are actually looking for.
A separate repository keeps both lists readable.

**Assert the file type after unpacking, not just its presence.** A digest proves you got the bytes
that were published — it says nothing about whether those bytes are loadable. Cheap checks (the
expected file exists; on ELF, that it is a shared object rather than a position-independent
executable) catch a bad *publish* that verification cannot.

**Strip platform sidecar files after unpacking.** Packing a slice on macOS writes each file's
extended attributes out as a companion `._name` entry. A signer then treats those as ordinary
bundle members and seals them — but macOS folds them back into the real file and deletes the
sidecar the moment the user opens the bundle, leaving it missing everything the seal expects.
Strip `._*` unconditionally; only macOS is bitten, but any slice packed on a Mac carries them.

## Verifying it

Do not trust the workflow log's "success". Check the artifact:

```bash
# what actually reached the staging tree
find natives -type f | sed 's|/[^/]*$||' | sort -u

# recompute a published tarball's digest and compare to the pinned map
shasum -a 256 natives-<slice>.tar.gz
grep -n 'to "' <app-module>/build.gradle.kts
```

And at runtime, log the **resolved path** of the native the process actually loaded. Without it,
"using the bundled slice" and "quietly falling back to one installed system-wide on the dev
machine" look identical — which is how a bundle that never worked passes for months.
