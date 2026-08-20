---
name: config-fails-open-verify-artifact
description: Verifying a config-driven feature against the generated artifact instead of against the config, for formats that fail open and ignore unknown keys — the two-build A/B diff, the artifact fingerprint to grep for, and the CI assertion that keeps it from regressing. Reach for it when a config key looks correct, the build is green, and the feature it configures has simply never been observed working.
---

# When the config fails open, only the artifact is evidence

Many config formats accept keys they do not understand: HOCON and JSON without a schema, most YAML
consumers, `.desktop` files, property lists, manifest dialects. A misspelled key, a key at the wrong
nesting level, or a key that moved between tool versions produces **no error, no warning, no note**.

That turns a whole class of bugs invisible. The failure state and the working state look identical
from inside the repository: same file, same green build, same silence. The only place they differ is
the generated artifact.

## Traps

**Re-reading your config proves nothing.** The config is what you typed; that was never in doubt.
Reviewers checking "is the key spelled right / is it in the file" cannot catch a level error, because
the level looks plausible in both placements. Neither can a diff of the config across versions.

**"It should work" is not a state; "seen working" is.** A config-driven feature falls into three
buckets: observed working, observed broken, and *never observed at all*. The third is where these
bugs live, and it is invisible on a dashboard because nothing is red. Before shipping a key whose
only effect is on the installed artifact, decide which bucket it is in — and if it is the third,
get artifact-level proof.

**The decisive experiment is two builds differing only in key placement.** This is what actually
settles it, and it takes minutes:

1. Build the smallest artifact that carries the feature (one machine, one OS).
2. Move only the disputed key — nothing else — and build again into a separate output directory.
3. `diff -r` the two trees, then grep each one for the feature's fingerprint (below).

Identical trees mean only that moving the key changed nothing observable. *Which* placement is
inert — possibly both — is settled by the fingerprint: present in one artifact and not the other
tells you where the key legally binds; absent from both means neither placement registered the
feature. A differing metadata file gives you the binding from the tool rather than from a guess.
This is the shape that settled a URL-scheme registration written under three per-OS sections: the
arm built with the key under the OS sections shipped with no URL-types block at all, and the fix
moved the key up to the app level. Reading the docs had not settled it, and the misplacement had
gone unnoticed since the key was first written.

**Grep the artifact for the feature's fingerprint, not for your key name.** Your key name usually
does not appear in the output at all — the tool translates it. Learn the fingerprint once:

| Feature | Artifact fingerprint |
|---|---|
| custom URL scheme, macOS | `CFBundleURLTypes` / `CFBundleURLSchemes` in `Contents/Info.plist` |
| custom URL scheme, Linux | `MimeType=...x-scheme-handler/<scheme>` in the installed `.desktop` |
| custom URL scheme, Windows | the per-user `Software\Classes\<scheme>` key, with `URL Protocol` |
| launcher metadata, Linux | the keys inside the `[Desktop Entry]` group |
| runtime flags | the launcher script / `Info.plist` env dict / generated `.cfg` |

```bash
# adapted — run against the built tree, not the source tree
grep -R 'CFBundleURLSchemes' -A6 output/*.app/Contents/Info.plist || echo 'NOT REGISTERED'
grep -R 'x-scheme-handler' output/*.desktop                        || echo 'NOT REGISTERED'
```

**Check the artifact your users actually get, which may not be the one the tool emitted.** If a later
layer re-wraps the output — a directory tree packed into a portable single-file bundle whose startup
script installs its own launcher metadata — then that later file is the one the OS reads, and the
packager's version of it is dead weight. Verify at the end of the pipeline, not in the middle.

**A missing fingerprint tells you nothing about how long it has been missing — the shipped artifacts
do.** Rather than reconstructing dates from the git history, download the last few released
artifacts and run the same grep over each. That gives you the actual regression window and the list
of versions that need a note in the release announcement.

**Once proven, assert it.** The reason this class of bug survives is that nothing observes it, so the
fix is to add an observer. A grep over the built tree that exits non-zero is enough:

```bash
# adapted — CI step, right after packaging
for f in output/*.app/Contents/Info.plist; do
  grep -q 'CFBundleURLSchemes' "$f" || { echo "::error::URL schemes missing from $f"; exit 1; }
done
```

Keep the assertion next to the packaging step, not in a separate test suite — it must fail the job
that produced the artifact.

## Where else this shape appears

The same reasoning applies well beyond packaging, and recognizing it is most of the value:

- A query filter over a nullable column that silently matches nothing and reports success.
- A guard added to one of several trigger paths, where the other path returns early — no error, the
  feature just does not happen.
- A feature flag read from a key the loader never looks at, defaulting to "off".

The common signature is: **an operation that cannot fail, wired to a feature nobody observes.** The
countermeasure is always the same — find the artifact of the operation (a built file, a row count, a
log line) and assert on it, instead of asserting that the input was written correctly.
