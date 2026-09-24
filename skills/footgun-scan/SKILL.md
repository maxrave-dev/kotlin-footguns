---
name: footgun-scan
description: "Scan a Kotlin or Compose Multiplatform diff for known footgun shapes and open the matching trap to confirm each hit. Use before committing, when reviewing a Kotlin change, or to audit a codebase."
---

# Footgun scan

`scripts/scan.py` matches 32 patterns against the lines a change adds. Each pattern is tied to one
trap file in the kotlin-footguns area skills. It finds shapes, not bugs: every hit needs the trap's
judgment before it becomes a finding.

## Run it

From inside the user's git repository, with this skill's base directory as `<skill>`:

```bash
python3 <skill>/scripts/scan.py                     # lines added in the working tree and index since HEAD
python3 <skill>/scripts/scan.py --base origin/main  # lines added on this branch since it left main
python3 <skill>/scripts/scan.py --all src/          # every line under a path: an audit, and noisier
```

Pick the scope from the request. Uncommitted work takes the default. A branch or pull request takes
`--base` with its target branch. "Audit the codebase" takes `--all`, narrowed to the paths that matter.
For a pre-commit hook or CI step, add `--fail` to exit 1 on any `likely` hit.

## Triage every hit

1. Read the trap file the hit points to (the `->` path).
2. Read the code around the hit and decide, by the trap's own conditions, whether it applies.
   A `likely` hit is wrong unless the exception the trap names holds. A `look` hit is a place the
   trap says to inspect before trusting it.
3. Report each confirmed problem with the trap's fix and its Verifying step. List dismissed hits one
   line each with the reason, for example "column is NOT NULL" or "the fade goes to black".

Hits of one detector in one file are grouped: triage the group once, then check the listed lines
for exceptions.

## When the scanner cannot run

It needs `python3` and `git`. Without them, read `scripts/scan.py`: the `DETECTORS` list gives
each pattern, its message and its trap. Run those patterns with the Grep tool over the changed
files and triage the same way.
