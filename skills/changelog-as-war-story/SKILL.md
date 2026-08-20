---
name: changelog-as-war-story
description: Keep a tracked markdown file of dated entries that record symptom, mechanism, what was ruled out and the condition for removing the workaround — and enforce it with a rule that the entry lands with the change. Use when a fix rests on non-obvious behaviour someone will later "clean up", when the same investigation keeps being repeated, or when onboarding a human or an agent into an area with expensive traps.
---

# The changelog as a war story

A commit message says what changed. It rarely says what was tried and rejected, why the obvious
alternative is wrong, or what would have to become true before the workaround can go away. That
information has nowhere to live in a normal repository, so it is re-derived — expensively, by
somebody who did not know it existed.

The practice: one **tracked markdown file at the repository root**, containing dated entries in
the project's own vocabulary, read before touching an unfamiliar area. It sits in the same
review, the same diff and the same history as the code it describes.

A useful entry is not a summary. It carries four things:

- **Symptom** — what a person saw, in the words they would have used.
- **Mechanism** — why that happened, at the level where the fix makes sense.
- **What was ruled out** — the plausible alternatives that were tried and did not work, named
  explicitly so the next reader does not spend the same rounds on them.
- **The exit condition** — what would have to change upstream, or in the platform, for this
  entry to be deleted.

## The recorded shape

The app this was mined from keeps such a file at its root, with a dated-entry section and a rule
at the bottom stating when an entry is mandatory. Its entries look like this in outline (adapted;
the real ones name the app's own subsystems):

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

Note what that carries beyond "fixed a crash": the two different shapes of the same failure, the
ordering constraint that makes the workaround work, and an exit condition with the work it
implies. Every one of those was paid for once.

The rule that keeps it alive is written into the same file: after any architecture change,
dependency swap, new module, packaging change or platform migration, the entry is **required** —
and it names what does *not* qualify (routine bug fixes, dependency version bumps without API
change, minor styling), so the section stays a war-story log and not a release note.

## Traps

**Writing conclusions without the ruled-out list.** "We use approach A" invites the next reader
to propose B, because nothing records that B was tried. The ruled-out list is the single highest
value part of an entry and the first thing dropped when writing in a hurry.

**Omitting the exit condition.** Without it, every workaround is permanent. The entries that can
ever be closed are the ones ending in the shape *remove this once upstream frees the resource on
the error path*, or *the actual cure is to stop bundling it* — paraphrased here rather than
quoted, but that shape is exactly what step 5's regex finds. The rest calcify.

**Letting the entry drift from the code.** Prose is not verified by anything. In the source
mined here, one area's recorded entry names a specific style value as the fix while the code at
that call site has since moved to a different one, with its own explanatory comment. The entry is
still valuable — the *mechanism* it records is right — but a reader who copies the literal value
out of it is copying history, not the current state. Treat entries as evidence about mechanism
and always re-derive concrete values from the code.

**Letting it grow without pruning.** A file nobody finishes reading is a file nobody reads.
Entries whose exit condition has been met should be deleted, not archived in place.

**Filing the entry in a follow-up commit that never happens.** The rule exists precisely because
"I'll document it after" does not survive contact with the next task. In the recorded history the
entry lands both ways — sometimes inside the feature commit, sometimes in a `docs:` commit the
same day — and the ones that landed inside the feature commit are the ones that never went
missing.

**Searching commit messages first.** Commit subjects are one line, written before the
consequences were known, and a squashed or merged branch flattens several days of reasoning into
one. Search the tracked markdown first; go to history only when it comes back empty.

**Treating it as a file only humans read.** In this project the same file is the standing brief
for the automated assistants working in the repository, which is why it is written in behavioural
language rather than jargon, and why the auto-update rule is addressed to them.

## Verifying it

Set `DOC` to the tracked file, then:

```bash
DOC=CLAUDE.md
```

1. **Are entries dated and structured, or is it a wall of prose?**

   ```bash
   grep -cE '^- \*\*.*\(20[0-9]{2}-[0-9]{2}-[0-9]{2}' "$DOC"
   grep -oE '^- \*\*[^*]+\(20[0-9]{2}-[0-9]{2}-[0-9]{2}[^)]*\)\*\*' "$DOC" | head
   ```

2. **Is the rule that mandates entries actually in the file?**

   ```bash
   grep -nE '^#+ .*(Auto-Update|MANDATORY|Update Rule)' "$DOC"
   ```

3. **Is it maintained, and does it move with the code?** A history of `docs:`-only commits means
   the entries are written after the fact; a mix that includes `feat:`/`fix:` commits touching it
   means the rule is being enforced at the point of change:

   ```bash
   git log --format='%h %ad %s' --date=short -- "$DOC" | head -20
   ```

4. **Prove the search order for an area you are about to touch.** Markdown first, history second:

   ```bash
   TERM=crossfade
   git grep -n -i "$TERM" -- '*.md'
   git log --all -i --grep="$TERM" --oneline | head
   ```

5. **Check that entries carry exit conditions**, not just fixes:

   ```bash
   grep -oniE 'remove [^.]{0,30}once[^.]{0,40}|the actual cure[^.]{0,40}|once upstream[^.]{0,40}' "$DOC"
   ```

   Zero matches in a file full of workarounds means every one of them is now permanent.

6. **Before shipping an entry**, read it back as a stranger and confirm it answers: what did
   someone see, why did that happen, what did we already try, and when may this be deleted.
