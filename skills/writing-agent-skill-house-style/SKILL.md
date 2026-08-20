---
name: writing-agent-skill-house-style
description: Write an agent skill that survives an adversarial review — a description carrying both the trigger and the error symptom the reader is staring at, a short orientation, a Traps section that dominates the file, and verification commands you have actually run. Use when authoring or reviewing a SKILL.md, when a skill reads like documentation instead of hard-won advice, or when review keeps finding claims the source repository does not support.
---

# Writing an agent skill in this house style

A skill is not a tutorial and not an API reference. It is the note you would leave for the next
person about to lose two days to the same thing. Everything in the format follows from that.

**The shape.** Frontmatter, a short orientation, a **Traps** section taking most of the file, then
**Verifying it**. Roughly 60–140 lines. Orientation exists only to make the traps legible.

**The description does two jobs** — when to load the skill, and what symptom the reader is
staring at, so the match happens on the error rather than the topic. The exemplar in the mined
repository ends its description "…or hitting ImageVector/Painter type errors": that last clause
is the one that fires when somebody is confused rather than curious.

**Teach how to verify a value, never list values that go stale.** The same exemplar sends readers
to the upstream code-point list rather than listing names. A list goes stale; a procedure does not.

**The Traps section is the product.** Each trap opens with the wrong move in bold, then what
happens, then what to do instead — so a reader scanning bold lines finds their own situation.

## What review actually catches

Across four closed review batches, adversarial review kept finding a different character of error
each time — which is the order your own drafts will fail in:

1. **Content errors** — claims the source repository does not support. Caught by opening the file
   the skill cites.
2. **Prose-versus-artifact errors** — a claim sourced from a comment or a changelog entry, where
   the code beside it had already moved on. Caught by re-deriving from the artifact.
3. **Unrunnable verification commands** — plausible but never executed: wrong flag order, a glob
   the shell ate, an anchored pattern that silently matched nothing.
4. **Mechanism not re-derived** — the trap was real, the stated reason a guess. Caught by asking
   "how do you know *that* is why?" of every rationale.

Round 3 is the cheapest to prevent: **run every command in the Verifying section, verbatim,
against the real repository, before shipping.** A command never run is a claim, not a check.

## Traps

**A description that names only the topic.** "Icons in this project" matches nothing a confused
reader would type. Include the trigger *and* the symptom they are staring at.

**Frontmatter `name` that does not match the folder.** Two separate strings, and nothing in a
text editor compares them. A mismatch makes the skill unloadable while looking perfect.

**Orientation that grows into a tutorial.** If the first third could have been read in the
framework's own docs, stop. Assume the reader knows the technology and does not know this trap.

**Counts written from memory.** "There are 59 icons" is wrong a week later and cannot be checked
by a reader. Give the command that produces it — likewise file, call-site and version counts.

**Marking an excerpt "adapted" when it is verbatim, or the reverse.** Load bearing: a reader who
believes an excerpt is real will grep for it. Renamed anything → `// adapted`; recheck after edits.

**Sourcing a claim from a comment.** A comment records what somebody believed then. In the mined
repository a control stayed hidden on one platform under a comment saying the media engine lacked
support — true when written, false months later. Such prose is a *lead*; confirm against artifact.

**Stating a rationale you have not re-derived.** "It fails because X" written from plausibility
survives longest: it reads exactly like the version that was checked. Trace every "because".

**Unquoted globs and bare `find` predicates.** `grep -r *.kt` is expanded by the shell before
grep sees it; `find . -name *.kt` fails the same way. Quote every glob.

**A Verifying section made of prose.** "Check that the configuration is correct" is not a check.
Every step is a command with a stated pass condition, or an artifact plus what you expect in it.

## Verifying it

Run these from the root of the skills collection.

1. **Frontmatter name matches the folder, for every skill:**

   ```bash
   for f in skills/*/SKILL.md; do
     n=$(awk -F': ' '/^name: /{print $2; exit}' "$f")
     d=$(basename "$(dirname "$f")")
     [ "$n" = "$d" ] || echo "MISMATCH folder=$d name=$n"
   done
   ```

   Pass condition: no output.

2. **Every description carries a trigger clause** — match the clause, not one spelling of it.
   Anchoring on a single phrasing measures house style, not the property you care about:

   ```bash
   awk '/^description:/ && !/[Uu]se when/ && !/[Rr]each for (it|this) when/ {print FILENAME}' \
     skills/*/SKILL.md
   ```

   Pass condition: open every file printed. Dropping the second alternation — the narrow check
   this replaced — reports 29 of these 140 as untriggered, every one of them a false positive.

3. **Length is inside the band:**

   ```bash
   wc -l skills/*/SKILL.md | sort -n | awk '$1<60 || ($1>140 && $2!="total")'
   ```

4. **The Traps section dominates.** Report the share of each file that sits at or after the traps
   heading:

   ```bash
   for f in skills/*/SKILL.md; do
     t=$(wc -l < "$f")
     s=$(grep -n '^## Traps' "$f" | cut -d: -f1)
     [ -n "$s" ] && printf '%3d%%  %s\n' $(( (t - s) * 100 / t )) "$f"
   done | sort -n | head -20
   ```

   A file well under half is usually an orientation that outgrew its job.

5. **Every skill ends in a verification section.** `## Verifying it` is the canonical heading, not
   a universal fact — a file printed here may use a variant heading or truly lack the section:

   ```bash
   grep -L '^## Verifying it' skills/*/SKILL.md
   ```

6. **Run each fenced command yourself** — the round-3 check. The leading `[[:space:]]*` is not
   optional: list fences are indented, and an anchored `^` extracts almost nothing, looking fine.

   ```bash
   awk '/^[[:space:]]*```bash/{f=1;next} /^[[:space:]]*```/{f=0} f' skills/*/SKILL.md | sed '/^\s*$/d'
   ```

7. **Confirm every cross-referenced skill exists on disk**, by name, before shipping:

   ```bash
   grep -ho '`[a-z0-9]\+\(-[a-z0-9]\+\)\{1,\}`' skills/*/SKILL.md | tr -d '`' | sort -u \
     | while read -r n; do [ -d "skills/$n" ] || echo "MISSING $n"; done
   ```

   Not a clean zero: the pattern also catches hyphenated non-skill tokens, so the pass condition
   is that every line printed is visibly not a skill name. A real one here is a broken reference.
