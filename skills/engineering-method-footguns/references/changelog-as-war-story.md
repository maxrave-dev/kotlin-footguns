---
name: changelog-as-war-story
description: Keep a tracked markdown file of dated entries that record symptom, mechanism, what was ruled out and the condition for removing the workaround — and enforce it with a rule that the entry lands with the change. Use when a fix rests on non-obvious behaviour someone will later "clean up", when the same investigation keeps being repeated, or when onboarding a human or an agent into an area with expensive traps.
---

# The changelog as a war story

A commit message says what changed. It rarely says what was tried and rejected, why the obvious
alternative is wrong, or what must become true before the workaround can go. That has nowhere to
live in a normal repository, so it is re-derived by someone who did not know it existed.

The practice: one **tracked markdown file at the repository root** of dated entries in the project's
own vocabulary, read before touching an unfamiliar area — in the same review, diff and history as
the code it describes.

A useful entry is not a summary. It carries four things:

- **Symptom** — what a person saw, in the words they would have used.
- **Mechanism** — why that happened, at the level where the fix makes sense.
- **What was ruled out** — the plausible alternatives that were tried and did not work, named
  explicitly so the next reader does not spend the same rounds on them.
- **The exit condition** — what would have to change upstream, or in the platform, for this
  entry to be deleted.

## The recorded shape

The app this was mined from keeps such a file at its root: a dated-entry section, and a rule stating
when an entry is mandatory. Entries look like this in outline (adapted):

```markdown
- **Bundled library takes over a system name (2026-07-31)**: the app's own copy of a common
  library was loaded first and claimed the name, so a platform API that dlopens the *system*
  copy could no longer find a matching symbol and reported the whole feature unsupported for
  the rest of the process. All external-link call sites broke at once — one path failed
  silently because its branch had no else, another threw straight out of the click handler.
  Worked around by probing the platform API before the native library loads, so the system
  copy wins the name. **The actual cure is to stop bundling that library** — which needs the
  bundle rebuilt, republished and re-pinned.
```

Note what that carries beyond "fixed a crash": two shapes of the same failure, the ordering
constraint that makes the workaround work, and an exit condition with the work it implies.

The rule is in the same file: after any architecture change, dependency swap, new module, packaging
change or platform migration an entry is **required** — and it names what does *not* qualify (bug
fixes, version bumps without API change, styling), so the section stays a war-story log.

## Traps

**Writing conclusions without the ruled-out list.** "We use approach A" invites the next reader
to propose B, because nothing records that B was tried. The ruled-out list is the single highest
value part of an entry and the first thing dropped when writing in a hurry.

**Omitting the exit condition.** Without it every workaround is permanent. The entries that can ever
be closed end in the shape *remove this once upstream frees the resource on the error path*, or *the
actual cure is to stop bundling it* — the shape step 5's regex finds. The rest calcify.

**An entry records the design that was AGREED, not necessarily what shipped.** Slow drift is the
obvious risk — one entry here names a style value as the fix while that call site has since moved on
— but the drift that bites lands on day one: entries get written from the plan, and the plan changed
during the work. An audit of that file found **three** concrete claims in one dated entry false
against that entry's own ship commit — something said to render inside a card renders at page level,
a modifier said to be passed is not, two of three fields called "intentionally unused" are used.
Nothing had drifted; the entry had never been true. Mine an entry for its *mechanism*, which is
usually right, and re-derive every concrete claim from the tree (`writing-agent-skill-house-style`
states the same rule); correct a wrong one **in place, dated, saying what it claimed before**.

**A working note is scaffolding with a lifetime; the entry is the artefact.** A design document kept
beside a feature while it is built is fine, and it is abandoned the moment the code exists — after
which it outlives and contradicts the entry. Of the two in the recorded history, one was deleted **by
its own ship commit**, its content folded into the dated entry; the other outlived its feature by
three weeks and was swept up only incidentally, by a commit about something else — this very trap,
sitting inside its own evidence. Give every note that lifetime explicitly; the directory is now gone.

**Letting it grow without pruning.** A file nobody finishes reading is a file nobody reads.
Entries whose exit condition has been met should be deleted, not archived in place.

**Filing the entry in a follow-up commit that never happens.** The rule exists because "I'll
document it after" does not survive the next task. In the recorded history the entry lands both ways
— inside the feature commit, or in a `docs:` commit the same day — and those inside the feature
commit are the ones that never went missing.

**Searching commit messages first.** Commit subjects are one line, written before the
consequences were known, and a squashed or merged branch flattens several days of reasoning into
one. Search the tracked markdown first; go to history only when it comes back empty.

**Treating it as a file only humans read.** Here the same file is the standing brief for the
automated assistants working in the repository — which is why it is written in behavioural language
rather than jargon, and why the auto-update rule is addressed to them.

## Verifying it

Set `DOC` to the tracked file (`DOC=CLAUDE.md`), then:

1. **Are entries dated and structured, or is it a wall of prose?**

   ```bash
   grep -cE '^- \*\*.*\(20[0-9]{2}-[0-9]{2}-[0-9]{2}' "$DOC"
   grep -oE '^- \*\*[^*]+\(20[0-9]{2}-[0-9]{2}-[0-9]{2}[^)]*\)\*\*' "$DOC" | head
   ```

2. **Is the rule that mandates entries actually in the file?**

   ```bash
   grep -nE '^#+ .*(Auto-Update|MANDATORY|Update Rule)' "$DOC"
   ```

3. **Is it maintained, and does it move with the code?** `docs:`-only commits mean entries written
   after the fact; `feat:`/`fix:` commits touching it mean the rule is enforced at the point of change:

   ```bash
   git log --format='%h %ad %s' --date=short -- "$DOC" | head -20
   ```

4. **Prove the search order for an area you are about to touch.** Markdown first, history second:

   ```bash
   TERM=crossfade
   git grep -n -i "$TERM" -- '*.md'
   git log --all -i --grep="$TERM" --oneline | head
   ```

5. **Check the entries carry exit conditions, that somebody has audited them, and that the working
   notes beside them are being retired:**

   ```bash
   grep -oniE 'remove [^.]{0,30}once[^.]{0,40}|the actual cure[^.]{0,40}|once upstream[^.]{0,40}' "$DOC"
   grep -cE '\(Corrected [0-9]{4}|previously (claimed|described)' "$DOC"
   grep -oE '[A-Za-z0-9_/]+\.kt:[0-9]+' "$DOC" | sort -u | while IFS=: read -r f l; do echo "$f:$l -> $(git ls-files "*$f" | head -1)"; done
   git log --diff-filter=D --format='%h %s' --name-only -- '*docs/*.md' | head
   ```

   Zero exit conditions in a file full of workarounds means every one is permanent. Zero corrections
   means nobody has checked it against the tree — so open each reference the third command resolves,
   at that line, and read whether the code says what the entry says. An unresolved path is stale or
   lives in a dependency. In the last list, read each deletion's subject against the note it removed:
   a note swept up by a commit about a different feature outlived its own, which is the trap above.

6. **Before shipping an entry**, read it back as a stranger and confirm it answers: what did
   someone see, why did that happen, what did we already try, and when may this be deleted.
