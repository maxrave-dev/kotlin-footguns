---
name: kmp-gradle-settings-catalog
description: Settings-file patterns for a many-module Kotlin Multiplatform repo — mapping deeply nested in-repo directories onto flat Gradle project paths, turning on typesafe project accessors and knowing how they mangle names, declaring repositories in the two places that need them, and pinning one transitive artifact repo-wide for a conflict that only shows at runtime. Reach for it when Gradle reports a project that "does not exist" from a module you never edited, when a project accessor will not resolve, or when a repository you added is invisible to plugin resolution.
---

# Settings for a many-module multiplatform repo

The Gradle project path and the directory on disk are two independent things. `include()` declares
the path; `projectDir` says where it lives. Use that to keep a flat, memorable set of project paths
over a nested directory tree:

```kotlin
// settings.gradle.kts — adapted
val sharedDir  = File(rootDir, "<shared>")
val serviceDir = File(rootDir, "<shared>/service")
val mediaDir   = File(rootDir, "<shared>/media")

rootProject.name = "<App>"

include(
    ":<android-launcher>", ":<shared-ui>", ":<desktop-launcher>",
    ":common", ":data", ":domain",
    ":<service-a>", ":<service-b>",
    ":<media-a>", ":<media-a>-ui",
    ":<feature>", ":<feature>-empty",
)

project(":common").projectDir     = File(sharedDir, "common")
project(":<service-a>").projectDir = File(serviceDir, "<service-a>")
project(":<media-a>").projectDir   = File(mediaDir, "<media-a>")

enableFeaturePreview("TYPESAFE_PROJECT_ACCESSORS")
```

Consumers then write `:<service-a>` and `projects.<serviceA>` and never learn how deep the file
actually sits. Move the directory, change one line here, and nothing else in the repo changes.

## Traps

**`include()` must come first.** `project(":x")` looks up an already-included path; calling it before
the `include` block fails in the settings file itself. Keep all includes in one block, all
`projectDir` assignments after it, in the same order.

**A wrong `projectDir` fails nowhere near where you wrote it.** Pointing at a directory with no build
script does not error at assignment. It surfaces at the first module that depends on it, as a missing
project or an unresolvable accessor — naming a module the reader never touched. Check the mapping
directly: `grep -c 'projectDir' settings.gradle.kts` against
`find <shared> -maxdepth 3 -name 'build.gradle.kts' | wc -l`. The two should agree, plus any modules
at the repo root that need no mapping.

**Anchor every path on `rootDir`, never on a relative walk-up.** A lookup that probes a sibling
directory outside the repo — `../<name>` for co-development — binds to whatever happens to sit
there. The settings file here records exactly that failure: another checkout one level up used the
same folder name, the probe bound to it, and configuration died on a module that "does not exist".
`File(rootDir, …)` cannot reach outside the repo, which is the property you want.

**Typesafe accessors are generated from the Gradle path, and the mangling is where twin modules
bite.** Each path segment is camel-cased across `-` and `_`, and the disk path never appears:

| Gradle path | Accessor |
|---|---|
| `:<feature>-empty` | `projects.<feature>Empty` |
| `:<media-a>-ui` | `projects.<mediaA>Ui` |
| `:<service-a>` (already camel) | `projects.<serviceA>` |

So renaming a *directory* changes nothing, while renaming an `include()` entry rewrites every
consumer. Pick the project paths once, before the accessors spread.

**Repositories are declared in two blocks and one does not feed the other.** `pluginManagement`
resolves plugin markers; `dependencyResolutionManagement` resolves everything else. A repository
added to only one is invisible to the other, and the failure reads as "plugin not found" even though
the artifact is plainly in your other list. The two lists here overlap but are not identical: the
same third-party hosts appear in both, while `dependencyResolutionManagement` carries two more that
plugin resolution never needs — a snapshot repository and a raw-git-hosted one.

**`FAIL_ON_PROJECT_REPOS` is what keeps the list honest.** With
`repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)`, any module declaring its own
`repositories { }` fails the build instead of quietly resolving from a source no one else has. Turn
it on early — retrofitting it means finding every stray block at once.

**Delete a dead repository, and say why in a comment.** Both blocks here carry a comment recording
which host was removed and what its removal fixed — as recorded there, an unreachable host answering
with gateway errors disabled the whole set and blocked fallback to a repository that *did* have the
artifact, so the symptom was "nothing resolves" rather than "one thing is slow". Whatever your own
resolver does with a dead host, the comment is what stops the next reader adding it back.

**A version force belongs in exactly one place, above every module — and in this repo that place is
the root build script, not the settings file:**

```kotlin
// root build.gradle.kts — adapted
subprojects {
    // Two third-party libraries depend on the same artifact pinned to different source
    // revisions. Default resolution picks the one missing a method the other library's
    // fallback path calls, so the app stops only when that fallback runs — at runtime,
    // on a code path most sessions never reach. Force one revision everywhere so the
    // merged output carries a single copy with the API both callers expect.
    configurations.all {
        resolutionStrategy {
            force("com.example.group:shared-json:<pinned-revision>")
        }
    }
}
```

Two things make this repo-wide rather than a module fix. The coordinate's "version" is a source
revision string, so the default newest-wins comparison is not comparing anything meaningful — the
winner is arbitrary from your point of view. And the packaged artifact merges the runtime classpath
of *every* module, so forcing it only in the module you were debugging leaves the others free to
reintroduce the loser. Pin it once, and keep the reason in the comment: a bare `force(...)` line is
unmaintainable, because the next reader cannot tell whether it is still needed. See
`transitive-version-pinning`.

**Toolchain provisioning is a settings-level plugin.** The resolver convention plugin belongs in the
settings `plugins { }` block, so `jvmToolchain(…)` in any module can be satisfied on a machine that
lacks that JDK. Without it a contributor's build fails on the toolchain, not on what they changed.

## Verifying it

```bash
# what the settings file actually declares, in order
grep -n 'include(\|projectDir\|enableFeaturePreview\|RepositoriesMode' settings.gradle.kts

# every accessor in use must correspond to an included path
grep -rhoE 'projects\.[A-Za-z0-9]+' --include='*.kts' . | grep -v '/build/' | sort -u

# nothing outside settings may declare repositories
grep -rn '^\s*repositories {' --include='*.kts' . | grep -v settings.gradle.kts | grep -v '/build/'
```

The last command must return nothing; a hit means `FAIL_ON_PROJECT_REPOS` is off, or about to fail
someone else's build. When the module tree spans a git submodule the mapping is the same but the
failure modes differ — see `kmp-git-submodule-module-mapping`.
