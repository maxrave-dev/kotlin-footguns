---
name: commit-archaeology-red-flags
description: Mine a repository's history without being misled by it — an empty-bodied commit's file statistics are its real abstract, a nested-repository bump hides its entire content behind a one-line pointer change, and a merge flattens a branch's decision trail into a single subject. Use when reconstructing why something is the way it is, when a blame lands on a commit whose message explains nothing, or when a change appears to touch one line and cannot possibly be that small.
---

# Commit archaeology: the red flags

History is evidence, but it is evidence written by people who were mid-task and did not know what
would matter later. Three shapes account for most wrong conclusions drawn from it, and all three
look ordinary in a one-line log.

Before starting: search the repository's tracked prose. A project that keeps a war-story document
at its root has the reasoning there in a form commit messages never carry, so history is the
fallback rather than the first stop.

## Red flag 1 — the empty-bodied commit

Most commits have no body at all. In the repository mined here the majority do, so the one-line
subject is the entire written record — and subjects both under-claim and over-claim.

The file statistics are the real abstract. Empty-bodied commits found by step 2 below:

| subject | what `--stat` says |
|---|---|
| `feat: end of friday` | 131 files, ~3,500 added, ~2,600 removed |
| `feat: refactor code folder` | 539 files, 65 added, 5 removed |
| `remove core` | 342 files, ~47,000 removed |

`end of friday` says nothing and is one of the largest changes in the history. `refactor code
folder` touches 539 files and adds 65 lines — a pure move whose subject over-claims a refactor.
Neither can be classified from its subject; both are obvious from one `--stat`.

## Red flag 2 — the nested-repository bump

When part of a project lives in a nested repository, a commit that advances it shows one file and
one changed line in its statistics, and this in its diff:

```
-Subproject commit 4a11e1307c5a0e0909377aba64f885169f4f8b24
+Subproject commit a4f7e5e11a1addde4cc8ed1ebc759a00b3b4f6c6
```

The content is entirely in the range between those pointers, in another repository. Expanded:

```
Submodule core 4a11e1307..a4f7e5e11:
  > fix(lyrics): stop dropping the first character when no space follows the timestamp
  > fix(player): serve cache directly only when the whole track is on disk
```

Two fixes in another repository, invisible to every ordinary history command run in this one. In
the mined repository these bumps are frequent enough that any investigation into that half of the
codebase is incomplete without expanding them.

## Red flag 3 — the flattening merge

A merge commit's subject names branches, not decisions. A branch that took a week of back and
forth arrives as one line, and if it was rebased or squashed first the intermediate reasoning is
not in this repository at all. One merge here carries ~128 files and ~17,600 added lines under a
subject naming two branches. Merges also inflate the population: separate them before measuring.

## Traps

**Classifying a commit from its subject.** The subject is a label written before the consequences
were known. Read the statistics for every commit you intend to cite; it costs one command.

**Reading a one-line change as a small change.** A nested-repository pointer move is the extreme
case; generated files, lock files and version catalogs behave the same way.

**Blaming into a move commit and stopping.** A relocation rewrites the recorded author of every
line it touches, so blame lands on whoever moved the folder. Follow the file across the move
before concluding anything about who wrote what, or why.

**Assuming a nested repository's history is reachable.** Rendering the range requires that
repository to be present locally and to contain both pointers. When it is absent, or the range
spans a rewrite, the log renders nothing — and that silence reads exactly like "no content".

**Searching only the default branch.** Work that was abandoned, superseded or merged from a fork
is often exactly the decision trail you want. Sweep all references.

**Trusting dates for ordering.** Author date is when the change was written, commit date when it
was applied, and rebasing moves one and not the other. Order topologically when sequence matters.

**Concluding a feature was never attempted because the term does not appear.** Subjects use the
vocabulary of the day. Search the code and the tracked prose for the concept, then use the file
paths you find to search history, rather than searching history for the word.

**Quoting a commit subject as the rationale.** It is a label. Look for reasoning in the tracked
prose, the associated review discussion, or the diff itself — and if it is not there, say it is
not recorded rather than paraphrasing the subject.

## Verifying it

1. **How much of this history has no body at all** — that fraction tells you how much weight the
   subjects are carrying:

   ```bash
   git log --all --format='%H%x01%s%x01%b%x02' \
     | awk 'BEGIN{RS="\002"; FS="\001"} NF>1 && $3 ~ /^[[:space:]]*$/ {n++} END{print n+0}'
   git rev-list --all --count
   ```

2. **Rank the empty-bodied commits by how much they actually changed**, so the ones whose subject
   is doing no work are visible:

   ```bash
   git log --all --format='%H%x01%s%x01%b%x02' \
     | awk 'BEGIN{RS="\002"; FS="\001"} NF>1 && $3 ~ /^[[:space:]]*$/ {gsub(/^\n/,"",$1); print $1"\t"$2}' \
     | head -400 \
     | while IFS=$'\t' read -r h s; do
         printf '%s | %s\n' "$(git show --stat --format='' "$h" | tail -1)" "$s"
       done | grep changed | sort -rn | head -12
   ```

   `head -400` is a cost control, not part of the method — it ranks only the 400 most recent
   empty-bodied commits, about a third of them here. Raise it until the ranking stops changing;
   left as is, a larger silent commit further back never enters it and the "largest" is wrong.

3. **Find the nested-repository bumps and expand one:**

   ```bash
   cat .gitmodules
   git log --all --oneline --format='%h %ad %s' --date=short -i --grep='submodule' | head
   git show --submodule=log <bump-commit>
   ```

   Pass condition: the expanded output lists real subjects from the nested repository. One line
   of pointer change means the range did not render, and the investigation is not done.

4. **Separate merges from direct commits before measuring anything, and follow files through
   relocations rather than blaming the move:**

   ```bash
   git log --all --merges --oneline | wc -l
   git log --all --no-merges --oneline | wc -l
   git log --follow --format='%h %ad %s' --date=short -- <path>
   ```

5. **Before citing any commit as evidence**, confirm you have read its statistics — and, if it is
   a nested-repository bump, the expanded range.
