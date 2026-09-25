---
name: noop-actual-not-platform-limit
description: An empty or pass-through platform implementation in a multiplatform project means nobody wrote it, not that the platform cannot do it — check the dependency's resolved variants and the source set that declares it before telling anyone a feature is impossible there. Use when a feature "doesn't work on desktop/iOS", when a platform file returns its input unchanged or has an empty body, or before writing off a feature as a platform limit.
---

# A no-op platform implementation is not a platform limit

In a Kotlin Multiplatform project every shared declaration has one implementation per target. When
one of them looks like this —

```kotlin
// adapted
actual fun Modifier.frostedSurface(source: SurfaceSource): Modifier = this
```

— the honest reading is "this target has no implementation yet". The tempting reading is "this
target cannot do it". Those are wildly different conclusions and the file cannot tell them apart:
a stub written because the API is genuinely absent and a stub written because someone ran out of
afternoon are byte-for-byte identical.

The cost of guessing wrong is asymmetric. Saying "the platform can't" ends the conversation and
the feature gets dropped; saying "nobody has written it" costs one lookup.

## The recorded case

In a multiplatform media app, the desktop implementations of a glass-surface effect were
pass-throughs — the modifier returned unchanged, the container fell back to a plain rounded clip.
That was reported upward as "desktop does not have this effect, nothing will change that".

It was wrong. The effect library was a multiplatform artifact declared in the **shared** source
set, so the build had been resolving its desktop variant all along — the jar was already sitting
in the local dependency cache, with the same public API as the version the Android code used. The
stubs were simply the parts nobody had filled in.

The correction went further than filling them in. Because the library existed on both targets,
the shared/platform split had nothing left to abstract: the platform-specific declaration was
itself what had kept the ~200-line effect stuck in the Android source set, since a shared file
cannot call into a type it only knows as an opaque platform class. Deleting the split let the
whole effect move into shared code, and the call sites kept their names. The recorded note reads:
the abstraction was the blocker.

## Traps

**Reading the stub as the answer.** The empty body is the *question*. Nothing about "returns its
input unchanged" implies an absent capability — it is also exactly what a placeholder looks like.

**Assuming a dependency is single-platform because you only ever saw it used on one.** A
multiplatform artifact is published as one coordinate with per-target variants, and the build
picks the right one silently. If the dependency is declared in the shared source set, resolution
for every target has *already happened* — check the cache before theorising.

**Confusing "the shared API has no binding here" with "the platform has no such feature".** These
fail identically at the call site and have opposite fixes. The first is answered by the artifact
list, the second by the platform's own documentation. Answer the first one first, because it is
cheap and it settles most cases.

**Trusting a comment that names an old dependency.** Recorded in the same app: a pitch control
was hidden on desktop under a comment saying the media engine of the day had no independent pitch
support. The engine had been replaced months earlier and the replacement did support it — the
project was already driving that very filter elsewhere for another feature. The comment was true
when written and became a false platform limit that outlived its subject by a release cycle.

**Assuming the reverse — that a resolved variant means the feature will work.** A variant proves
the code is *reachable*, not that it renders. Effects that go through per-platform shader or
rendering paths can still fail on one of them; the recorded case shipped with an explicit note
that the desktop path was unproven at the time of writing, and named the neighbouring library
whose desktop shader path was known to fail as the first suspect. "Reachable, verify next" is the
correct claim, not "supported".

**Leaving the platform split in place after filling the stub.** Once every target has a real
implementation of the same library API, the split usually costs more than it buys — and while it
exists, shared code cannot call the underlying type at all. Check whether the whole feature can
move into shared code with a type alias left behind so call sites do not change.

**Deciding a stub is fine because "that target is not a priority".** A stub that silently does
nothing produces a feature that appears present and is not. Either implement it, or make the stub
visibly refuse, so the gap shows up in testing rather than in a support thread.

## Verifying it

Run these **before** telling anyone a platform cannot do something.

1. **Does the dependency have a variant for that target, already resolved?** List cached module
   directories, strip the target suffix, and count how many targets each module resolved for —
   anything above 1 is a multiplatform artifact the build is already fetching per target:

   ```bash
   find ~/.gradle/caches/modules-2/files-2.1 -mindepth 2 -maxdepth 2 -type d \
     | sed 's#.*/##' \
     | sed -E 's/-(android|desktop|jvm|iosArm64|iosX64|iosSimulatorArm64|js|wasm-js|linuxX64|macosArm64|macosX64|mingwX64)$//' \
     | sort | uniq -c | sort -rn | head -20
   ```

2. **Which source set declares it?** A dependency in the shared block is being resolved for every
   target; one in a platform block is not:

   ```bash
   grep -rn 'Main.dependencies\|implementation(' --include='build.gradle.kts' . | head -40
   ```

3. **Do the two implementations differ by an order of magnitude?** Pair the platform files by
   base name and compare their sizes — a large file against a tiny one is the stub signature, not
   evidence of anything about the platform:

   ```bash
   find . -name '*.android.kt' -not -path './.git/*' | while read -r a; do
     b=$(basename "$a" .android.kt)
     j=$(find . -name "$b.jvm.kt" -not -path './.git/*' | head -1)
     [ -n "$j" ] && printf '%5s %5s  %s\n' "$(wc -l < "$a")" "$(wc -l < "$j")" "$b"
   done | sort -rn | head -20
   ```

4. **Compare the two public APIs directly.** For a jar, `unzip -l` lists the class surface. For an
   Android archive it does not — that archive holds four entries with the classes inside a nested
   `classes.jar`, so stopping at the outer listing shows no classes at all, on exactly the
   comparison this skill exists to make. Take the extra hop:

   ```bash
   unzip -p <the-aar> classes.jar > /tmp/a.jar
   diff <(unzip -l /tmp/a.jar | awk '/\.class$/{print $4}' | sort) \
        <(unzip -l <the-jar>  | awk '/\.class$/{print $4}' | sort)
   ```

   Pass condition, and the tolerance is the point: "identical API" means identical *apart from*
   the per-platform runtime classes. On the recorded pair both sides carry 63 classes and differ
   only in one platform's rendering-backend class against the other's — that is the same-API
   result, not a difference. Scoring it strictly concludes the opposite of the truth.

5. **Only if steps 1–4 come back empty** is "the platform cannot" a live hypothesis — and then it
   needs a citation from the platform's own documentation or issue tracker, not an inference from
   the stub you started at.
