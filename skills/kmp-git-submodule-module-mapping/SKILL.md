---
name: kmp-git-submodule-module-mapping
description: Consume a git submodule as a set of Gradle modules in a multiplatform repo — mapping its nested directories onto flat project paths, making the recursive clone a hard prerequisite instead of tribal knowledge, and enabling submodules in every continuous-integration job that configures the build. Reach for it when a fresh clone fails with a project that "does not exist", when a build passes locally but fails on a runner, or when shared code changes vanish because the recorded submodule pointer was never moved.
---

# Shared modules living in a submodule

The submodule is a **directory tree of module directories**, not a build of its own. It has no
settings file and no root build script — the parent build's settings file is the only thing that
turns those directories into Gradle projects.

```ini
# .gitmodules
[submodule "<shared>"]
    path = <shared>
    url = https://<host>/<org>/<shared>
```

```kotlin
// settings.gradle.kts — adapted
val sharedDir  = File(rootDir, "<shared>")          // the submodule's checkout root
val serviceDir = File(rootDir, "<shared>/service")

include(":common", ":data", ":domain", ":<service-a>")

project(":common").projectDir      = File(sharedDir, "common")
project(":<service-a>").projectDir = File(serviceDir, "<service-a>")
```

The Gradle path stays flat and short while the disk path is two levels inside a separate repository.
The general form of that mapping, and what it does to typesafe project accessors, is in
`kmp-gradle-settings-catalog`; this skill is about what the submodule adds on top.

## Traps

**A plain clone gives an empty directory and a failure that names the wrong thing.** With the
submodule uninitialised, `projectDir` points at a directory containing no build script. Nothing
complains at that line. The build dies at the first module that depends on one of the mapped
projects, reporting that a project "does not exist" — naming a module the new contributor has never
heard of, in a file they did not open. Check before blaming the build:

```bash
git submodule status
```

A leading `-` on a line means that submodule is not initialised; a leading space means it is checked
out at the recorded commit. The fix is `git clone --recurse-submodules <url>` for a clone that has
not happened yet, or `git submodule update --init --recursive` for one that already exists.

**Put the recursive clone in the README's first code block.** A build error is not documentation.
Check whether yours says it at all —
`grep -rn -i 'recurse-submodules\|submodule update' README.md CONTRIBUTING.md`. If that returns
nothing, every new contributor's first build fails and the error tells them nothing about why.

**Continuous-integration checkout does not fetch submodules by default.** Each job needs it named
explicitly:

```yaml
# adapted
- uses: actions/checkout@<version>
  with:
    submodules: 'recursive'
```

The rule that makes this auditable: **any job that configures the build needs submodules; a job that
only moves artifacts around does not.** Count them per workflow:

```bash
for f in .github/workflows/*.yml; do
  echo "$f  checkouts=$(grep -c 'uses: actions/checkout' "$f")" \
       " recursive=$(grep -c "submodules: 'recursive'" "$f")" \
       " gradle=$(grep -c './gradlew' "$f")"
done
```

A workflow where `checkouts` exceeds `recursive` is not automatically wrong. The loop reports two
such gaps here, in two different workflows, and they are the *same* job duplicated: a macOS wrapping
step that downloads already-built artifacts, reads a tracked version file from the parent repo, and
repackages them without ever invoking Gradle. Read the gap the loop prints rather than assuming one
— a duplicated job is one decision to review, not two, and a job that runs Gradle on a plain checkout
fails on the runner while passing on every developer machine, which already has the submodule.

**The recorded commit is a tracked file in the parent, and moving shared code is two commits.** Push
in the submodule first, then commit the moved pointer in the parent — in that order, or the parent
points at a commit no one else can fetch. The pointer is an ordinary staged change:

```bash
git diff -- <shared>          # a "Subproject commit <old>..<new>" hunk = the pointer moved
```

"It works locally, the runner builds old code" almost always means that second commit is still
unstaged. The developer's tree has the new submodule commit checked out; the runner clones the
pointer the parent recorded.

**The checkout follows a recorded commit, not a branch — unless you ask for one.** With no
`branch =` key in `.gitmodules`, `git submodule update` restores the exact commit the parent pinned,
and the branch name `git submodule status` prints in parentheses is only where that commit happens to
sit. Tracking a branch is opt-in: a `branch =` entry *plus* `git submodule update --remote`. A
`git pull` in the parent does not move the submodule.

**Do not give the submodule its own settings file.** A settings file marks a build boundary: it is
what lets the tree be included or composited as a build in its own right, and it is what an IDE
import latches onto — so the same directories end up claimed twice, once by the parent's `projectDir`
mapping and once by that file. Exactly what breaks depends on how it gets wired, which is the reason
to keep the rule absolute rather than reason it out each time. Check it —
`ls <shared>/settings.gradle* <shared>/build.gradle*` must find nothing. Everything the shared
modules need at the build level (repositories, resolution rules, plugin versions, the version
catalog) comes from the parent, which is what lets the same tree be consumed by more than one
application.

**Anchor the mapping on `rootDir`, never on a relative walk-up out of the repo.** A probe for a
sibling checkout of the same name binds to whatever is parked one level up. This is easier to hit
inside a submodule setup than elsewhere, because the directory name is short and generic by design.

## Verifying it

The only check that reproduces what a new contributor gets is a fresh clone, deliberately without
the flag:

```bash
git clone <url> /tmp/fresh-check && cd /tmp/fresh-check && git submodule status
```

Every line should print with a leading `-`. That is the state your README, your error messages and
your first build have to survive. Then confirm the recovery path from there, and that the mapping
still lines up:

```bash
git submodule update --init --recursive && git submodule status
find <shared> -maxdepth 3 -name 'build.gradle.kts' | wc -l
grep -c 'projectDir' settings.gradle.kts       # the two counts must agree
```
