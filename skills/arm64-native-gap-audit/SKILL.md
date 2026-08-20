---
name: arm64-native-gap-audit
description: Audit every native dependency for a slice on a CPU architecture before promising that target in a multiplatform desktop build — one missing native takes the whole target down at first use rather than at build time, so make the audit a repeatable command over the resolved artifacts and re-run it on every dependency bump; reach for it when deciding whether to add an ARM64 target, or when a build that packaged and installed cleanly dies the first time it touches the database, the renderer or the media layer.
---

# Auditing an architecture before you promise it

Adding a CPU-architecture target to a desktop build is not a build-system question. Everything
compiles; the packager happily produces an installer; the app launches. Then the first call into
a dependency that carries a compiled binary fails, because that dependency shipped slices for four
architectures and yours was not one of them.

**One missing native takes the whole target down.** There is no partial success and no graceful
degradation: a database driver with no slice for your architecture cannot open a connection, so the
app is not "missing a feature", it is finished.

**The failure is at first use, not at build time.** Nothing in a normal pipeline — compile, package,
sign, install, launch — touches the native. Only exercising the feature does. That is why this must
be an *audit you run deliberately*, not something you expect CI to tell you.

## The audit

Native code reaches the JVM in three packaging shapes, and only the second is visible in your
dependency list:

1. **All slices inside one jar**, in a directory named per platform.
2. **One jar per platform**, with the architecture in the artifact coordinate.
3. **Staged by your own build** into a directory the packager copies in.

So the audit is: resolve the runtime classpath, then look *inside* each jar.

```bash
# First pass: every jar in the local dependency cache, and the native
# directories each one carries. (Narrow it to your real classpath next.)
find ~/.gradle/caches/modules-2 -name '*.jar' \
| while read -r jar; do
    slices=$(unzip -l "$jar" 2>/dev/null \
      | grep -Eio '[^ ]+\.(so|dll|dylib)$' \
      | xargs -n1 dirname | sort -u)
    [ -n "$slices" ] && printf '\n== %s\n%s\n' "$(basename "$jar")" "$slices"
  done
```

Point it at the exact set your build resolves rather than the whole cache by having Gradle print
the classpath first (a `doLast` that iterates `configurations.getByName("…RuntimeClasspath")` and
prints each file), then feeding those paths into the same loop.

Real output, two jars, two completely different layouts:

```
# adapted — jar names genericised; the second listing is a selection from its 23 rows
== bundled-database-driver.jar
natives/linux_arm64
natives/linux_x64
natives/osx_arm64
natives/osx_x64
natives/windows_x64          <- no windows_arm64: this is the gap

== native-access-library.jar
com/sun/jna/linux-aarch64
com/sun/jna/linux-x86-64
com/sun/jna/win32-x86
…
```

## Traps

**There is no common naming convention, so you cannot grep for one directory name.** One library
writes `natives/windows_x64`, another `com/sun/jna/win32-x86`, a third puts the architecture in the
artifact id and ships nothing platform-shaped inside the jar at all. Any audit built on a fixed
pattern reports "no natives found" for the dependency that is about to break you. List and read.

**Absence is invisible.** The output above only tells you something is missing if you already knew
which architectures to expect. Diff the slice list of *every* native dependency against your target
list, and treat "this one has fewer rows than the others" as the finding.

**Auditing the obvious dependencies is not auditing.** In one real audit the renderer, the media
backend and the JVM distribution all had slices for the architecture in question — every dependency
anyone thought to check. The one that did not was the bundled database driver, which nobody
associates with native code at all. The rule is *every* dependency that carries a binary, including
the ones that feel like pure library code.

**A pre-release of the same library is not a fix.** Verify the slice exists in the exact version you
would ship. In the audited case the gap was present in both the stable version and a later alpha.

**Re-run it on every dependency bump.** Slices get added, and occasionally dropped. This is the
cheapest thing in the pipeline to re-run and the most expensive thing to discover in the field.

**Check your own staged natives with the same eye.** Slices your build downloads or compiles are a
dependency too, and they are the one set nobody upstream is maintaining for you.

**Also check what your JVM distribution ships.** Not every vendor publishes a build for every
architecture; a packager that bundles a runtime fails at package time complaining that no runtime
inputs were supplied for that machine target — accurate, but easy to misread as your configuration
mistake rather than a vendor gap.

## When the gap is real

Drop the target. Do not ship a build you know cannot open its own database. On Windows, an
x64 package runs under the OS's emulation layer on ARM64 hosts and works correctly, which is a
better user experience than a native build that dies at its first database connection — say so in
the release notes.

Then make the decision recoverable: **keep the plumbing in git history and name the commits that
hold it** in the message that removes the target, plus the exact upstream condition that would let
you re-enable it ("re-enable once the driver publishes a windows-arm64 slice"). A future reader
otherwise cannot tell "we decided against this" from "nobody got around to it".

## Related

The same audit belongs in the database setup itself — see the sibling skill `room-kmp-setup`. The
architecture gap lives in the driver **artifact**, not in the database class, so no amount of
reading your own persistence code will surface it.
