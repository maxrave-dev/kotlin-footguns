---
name: github-actions-multiplatform-release
description: Structure a GitHub Actions release pipeline for a multiplatform desktop app so one Linux runner cross-builds every platform's artifacts and a second, tiny macOS job does only the one step that genuinely requires macOS — with artifact handoff between them and no compilation on the costly runner; reach for it when your release workflow runs three OS jobs that each rebuild the world, or when macOS users hit a hard block dialog on an app the pipeline signed correctly.
---

# Cross-build on one runner, keep a thin OS-only job

A modern desktop packager can cross-build: from a Linux runner it produces the Linux tree, both
macOS architectures and the Windows package, all in one pass. Use that. Fanning out to three
OS-matrixed jobs means three checkouts, three dependency resolutions and three compiles for
artifacts that a single job already produced.

But some steps are genuinely OS-bound. Wrapping a macOS app into a disk image is one: the image
tools ship only with macOS. So the pipeline is **one heavy cross-build job plus one thin OS-only
job**:

```yaml
jobs:
  build-desktop-packages:
    runs-on: ubuntu-22.04          # cross-builds Linux + both macOS arches + Windows
  wrap-mac-dmg:
    runs-on: macos-14
    needs: build-desktop-packages  # unpacks the mac archives, wraps each into a disk image
```

**Keep compilation off the costly runner.** macOS runners are billed at a multiple of Linux ones.
The second job here does no compilation at all — it downloads an archive, unpacks it, and runs
the image tools, roughly a minute or two per architecture. That is the whole design goal: the
expensive-per-minute machine spends its minutes only on the thing that cannot be done anywhere
else.

## Why the disk image at all

The packager's macOS output is a plain archive. On macOS 15 (where this was recorded), an app
extracted from a quarantined **archive** is treated more strictly than the same app propagated
through a mounted **disk image**: the archive route produces the hard-block "developer cannot be
verified" dialog, with no right-click-to-open escape, while the disk-image route produces the
ordinary first-launch prompt. Same app, same signature — different quarantine treatment based on how
it arrived. Wrapping is the only lever, and it is why this job exists.

## Artifact handoff

The two jobs share nothing but the artifact store:

```yaml
# job 1
- uses: actions/upload-artifact@v4
  with: { name: desktop-mac-zips, path: output/*.zip }

# job 2
- uses: actions/download-artifact@v4
  with: { name: desktop-mac-zips, path: mac-zips }
```

Name each upload after what it carries, not after the job — the second job then reads as a
consumer of a named thing rather than of "whatever job one left behind".

## Traps

**An externally invoked packager does not trigger Gradle task dependencies.** When the packager
runs as its own action rather than through a Gradle task, anything you wired with `dependsOn` into
the packaging tasks never runs on that path. Here that is the native-slice staging — and the job
still packages successfully, shipping an installer with those natives missing. The other
prerequisites are not wired that way at all and never were: the license manifest is produced by its
own plugin task into the source tree, and the config generation has to run *before* the packager
rather than hang off it. All of them therefore need explicit workflow steps ahead of the packager —
the `dependsOn`-wired one because its wiring is bypassed, the others because nothing was ever going
to pull them in.

**Generate config in a separate step so the packager never reads build-tool output.** A build that
prints anything to standard output (plugins do) will corrupt a config parser reading a stream. Run
the config-writing task first, let it write a static file, then point the packager at that file.

**A packager that wipes its output directory between invocations will eat what you staged there.**
If you call it twice — once for one platform, once for the rest — anything you copied into the
output directory after the first call is gone after the second. Stage into a directory of your own
and copy in at the end.

**Restrict which platforms each invocation builds.** Without a restriction, an invocation may
re-enter another platform's pipeline as an intermediate — even when that platform's target list is
empty — and fail the whole build on an artifact you never intended to produce.

**Derive per-architecture values from the filename, and fail if you cannot.** A loop over
downloaded archives should extract the architecture rather than assume an order:

```bash
arch="$(basename "$zip" | sed -nE 's/.*-mac-([a-z0-9]+)\.zip/\1/p')"
[[ -z "$arch" ]] && { echo "Cannot infer arch from $zip" >&2; exit 1; }
```

**`set -euo pipefail` and `shopt -s nullglob` in every multi-line shell step.** Without nullglob, a
`for f in dir/*.zip` loop with no matches iterates once with the literal pattern and produces a
baffling error; without `pipefail`, a failure mid-pipe is invisible.

**Read the version from the file that defines it.** Grepping the version catalog keeps the workflow
from drifting from the build:

```yaml
- id: version
  run: echo "version=$(grep '^version-name' gradle/libs.versions.toml | head -1 | cut -d'"' -f2)" >> "$GITHUB_OUTPUT"
```

**Install only what the runner actually needs, and revisit it.** Runner setup steps accumulate: a
toolchain added for a build approach you have since replaced stays in the workflow for months. When
a step's job changes from "extract natives from a prebuilt bundle" to "download prepared archives",
the extraction toolchain should leave with it — and the comment should say what remains and why.

**Write the reason for the job split at the top of the file.** A future reader looking at a Linux
job that builds macOS artifacts and a macOS job that builds none will otherwise "simplify" it back
into an OS matrix, and re-acquire the block dialog.

## Verifying it

- `ls -lh` the output directory as its own step. It costs nothing and it is the first thing you
  will want from a failed run's log.
- Assert on artifacts that a later step depends on **at the point they should exist**, with
  `::error::` annotations, rather than letting the step that consumes them fail.
- Confirm the release experience on a machine that has never built the app — the quarantine
  behaviour above is invisible on any host that produced the artifact locally.
