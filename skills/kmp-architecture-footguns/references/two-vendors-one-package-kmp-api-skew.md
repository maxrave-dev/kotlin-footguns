---
name: two-vendors-one-package-kmp-api-skew
description: Two vendors ship the same package name at different versions into different source sets of one multiplatform build, so a member function that one vendor has already turned into a top-level extension resolves on exactly one target — a specific import compiles for Android and fails for desktop, or the reverse. Covers spotting the duplicate coordinate, why a wildcard import is the correct fix here rather than a smell, and the pinning discipline that keeps the pair readable. Use when shared UI code stops compiling on one target only after a routine dependency bump, when an unresolved-reference error names a symbol you can plainly see in the other target's sources, or when two catalog entries carry the same artifact name.
---

# One package, two vendors, two API shapes

A multiplatform UI build usually has **two** suppliers for the same UI toolkit: the platform
vendor's artifact, which only exists for the platform target, and the multiplatform vendor's port,
which covers every target. They publish the **same package name** — that is deliberate, and it is
what lets shared code import one symbol and get whichever copy the target resolves.

They do not release together. The platform vendor's line runs ahead, so at any moment a symbol may
have a **different shape** in each:

```kotlin
// adapted — the platform vendor's newer line moved this off the scope
interface MenuBoxScope { @Composable fun Menu(…) }          // multiplatform port: a member
@Composable fun MenuBoxScope.Menu(…)                        // platform vendor: a top-level extension
```

Call sites are identical either way — `scope.Menu(…)` compiles against both. **The import is not.**
A member needs no import beyond its enclosing scope; a top-level extension must be imported by name.
So a file listing `import <ui>.material3.MenuBoxScope` and nothing else compiles on the port and
fails on the platform vendor, while a file that also names the extension does the reverse.

The fix is the one import style everybody else has been trained to remove:

```kotlin
// adapted — keep the reason on the import, because the next tidy-up pass will delete it otherwise
// Deliberate wildcard: the platform vendor's <newer version> turned MenuBoxScope's Menu member
// into a top-level extension, while the multiplatform port at <pinned version> still ships the
// member. A wildcard tolerates both shapes; a specific import compiles on exactly one target.
import <ui>.material3.*
```

This is a different mechanism from `transitive-version-pinning`, and the two are easy to confuse
because both arrive after a version bump. That one is about **resolution** — a strict constraint
choosing a version you did not pick, failing at runtime in an unrelated component. This one is about
**import shape** — two versions coexisting on purpose, failing at compile time in the file you just
edited. Neither fix helps the other.

## Traps

**Look for the duplicate coordinate before reading any error.** The tell is in the version catalog,
not the stack: two entries with the *same artifact name* under *different groups*. That pair is the
entire precondition, and it takes one command (step 1 below). Without it you are looking at an
ordinary missing dependency.

**A wildcard import here is load-bearing, and it looks exactly like laziness.** Every style guide in
reach says to expand it, every IDE offers to, and doing so re-breaks one target. The comment above
the import is the only thing standing between the build and a formatter. Put the *reason* in it —
which vendor moved which symbol, in which version — not just "do not touch".

**A second wildcard added later for convenience is indistinguishable from the deliberate one.**
Once one file carries `import <pkg>.*` with a good reason, the next author copies the shape without
the reason, and the audit in step 2 stops separating signal from habit. Every wildcard in shared
source needs a comment on the line above or it should be expanded.

**Bumping only the platform vendor is a source change, not a dependency change.** The catalog edit
looks like six routine version numbers; the compile break lands in a UI file nobody touched. Treat
any bump of the platform vendor's UI line as a change that must be compiled on **every** target
before it is called done — the shared source set is the one that decides, and it is the one a
single-target build never exercises.

**Pin both sides with the reason inline, in the catalog.** A version bump bot rewrites numbers and
keeps comments, so the catalog is the only place a constraint survives:

```toml
# adapted
platform-ui = "<X.Y.Z-alphaN>"   # alphaN turned MenuBoxScope.Menu into a top-level extension;
                                 # <file>.kt uses a wildcard import to stay compilable on both targets
multiplatform-ui = "<A.B.C>"     # ≈ platform alpha(N-7); the port still ships the member
```

Recording the **approximate correspondence** between the two lines is the part people skip and the
part that pays: it is what lets the next reader predict whether a symbol has skewed yet, instead of
finding out from a failed build.

**The skew runs both ways over time.** The port eventually catches up, and then the wildcard is
merely harmless rather than necessary. It does not become wrong — but the comment does, so the exit
condition belongs in it: *expand this once the port reaches the version that moved the symbol*.
Without that, the wildcard is permanent by default.

**Do not "fix" it by moving the file into a platform source set.** The file is shared because the
call sites are shared. Splitting it into two actuals duplicates a whole composable to paper over one
import line, and the two copies then drift for real reasons.

## Verifying it

Run from the repository root.

1. **Is there a duplicate coordinate at all?** Same artifact name, two groups:

   ```bash
   grep -oE 'group *= *"[^"]+", *name *= *"[^"]+"' gradle/libs.versions.toml \
     | sed -E 's/group *= *"([^"]+)", *name *= *"([^"]+)"/\2\t\1/' \
     | sort -u \
     | awk -F'\t' '{n[$1]++; g[$1]=g[$1]" "$2} END{for(k in n) if(n[k]>1) print k":"g[k]}'
   ```

   Any line naming two different vendor groups for one artifact is a candidate. Test-only pairs
   (a test runner and its extension) are noise; a UI toolkit appearing twice is the finding.

2. **Every wildcard import in shared source is either documented or a mistake.** This prints the
   verdict per import rather than a count, which is what you need to act on:

   ```bash
   grep -rlE '^import .*\*$' --include='*.kt' */src */*/src */*/*/src 2>/dev/null | while read -r f; do
     awk '/^import .*\*$/{printf "%s:%d  %s\n", FILENAME, FNR, \
          (prev ~ /^[[:space:]]*\/\//) ? "documented" : "UNDOCUMENTED"} {prev=$0}' "$f"
   done
   ```

   Pass condition: every hit inside a **shared** source set reads `documented`. Platform-only files
   are a separate judgement — they resolve one vendor and never skew.

3. **Which source set gets which vendor** — read the dependency blocks, not the imports:

   ```bash
   grep -rn -B20 'implementation(libs\..*material3' --include='build.gradle.kts' . \
     | grep -E 'Main\.dependencies|material3'
   ```

   A shared block naming the multiplatform port and a platform block naming the platform vendor is
   the configuration this skill describes. One vendor in both is a different build and none of this
   applies.

4. **Compile the shared source set for every target after any bump of either line.** A single-target
   assemble is not evidence: the file that breaks is the one both targets share, and only the target
   whose vendor moved the symbol reports it.
