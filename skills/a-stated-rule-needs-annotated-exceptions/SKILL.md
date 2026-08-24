---
name: a-stated-rule-needs-annotated-exceptions
description: A design rule with legitimate exceptions survives only if every exception carries its reason at the call site and the rule itself is greppable — otherwise nothing distinguishes an exception from a violation and the rule silently rots. Covers where the rule statement goes, where the reasons go, scoping the audit to the code the rule actually governs, and the limits of a comment-based check. Use when a stated convention is drifting, when reviewers cannot tell deliberate from careless, or before writing a rule into a file header and assuming it will hold.
---

# A stated rule needs annotated exceptions

"No hardcoded whites on semantic surfaces" is a good rule with real exceptions: a control floating
over a photo or a video legitimately stays white. That combination — enforceable, but not
absolutely — is the one that decays, because after a few months nobody can tell which of the
remaining hardcoded colours were decisions.

The fix is cheap and mechanical: state the rule where it is established, write one line of reason
where it is broken, and keep a command that lists both.

## Traps

**A rule you cannot grep for will not be enforced.** "No hardcoded whites on semantic surfaces" is
enforceable because the violation is a literal token. "Use semantic colours" is not, because the
compliant form is the absence of something. Write rules in terms of what appears in the file.

**The reason belongs at the call site, on the line above.** A file-header note saying "the whites in
this file are all over video" is true on the day it is written and false the first time somebody adds
a block below. It also cannot be read at the point where the reviewer is looking.

**A block annotation covers a run of siblings only while they stay siblings.** Four icons in one
overlay row under one comment is reasonable; the moment one is moved or copied elsewhere it arrives
with no reason attached and looks exactly like a violation. If a group is likely to be split, annotate
each member.

**Do not annotate the compliant lines.** Comments on code that follows the rule dilute the audit
until the exceptions are unfindable, which is the same end state as annotating nothing.

**Scope the audit to the code the rule governs, or it drowns.** The rule here applies to one look;
the other look on the same screen predates it and never adopted it. Auditing the whole package
returns dozens of hits from code the rule never covered, and an audit that always fails is an audit
nobody runs. Derive the file list from something structural — the files that read theme roles, say —
and say what the list means.

**Distinguish "exception" from "out of scope".** A colour on a surface that is not themed at all is
not an exception to the theming rule; it is simply outside it. Recording it as an exception makes the
exception list meaningless.

**Expect the audit to find unannotated hits, and treat that as the mechanism working.** Run step 3
here and the tally comes back as a couple of dozen bare against a handful annotated inside the
governed subtree. That ratio is only useful to whoever re-derives it and then annotates or fixes each
one — quoting a number somebody else printed is the same rot the rule exists to prevent.

**A comment-window heuristic over-reports compliance.** Checking "is there a `//` within two lines"
counts any nearby comment, including one about something else entirely — read the `ok` hits here and
some are a comparison against a colour, or a comment merely naming the token, rather than a painted
colour. That inaccuracy is the argument for codifying the rule as a lint or static-analysis check
once the exception rate is low enough; the comment convention is the fallback for rules a tool
cannot evaluate, such as "is this drawn over video?".

**State the rule once, where it is established.** The KDoc of the file that sets up the themed
subtree is the right place — it is what a reader hits before writing the code the rule governs. Two
copies of a rule drift like any other duplicate.

## Verifying it

1. The rule statement exists and is findable:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "no hardcoded whites\|hardcoded white" .
   ```

2. Run the audit. The file list is derived, not typed — change the two greps to match your own rule's
   scope and token:

   ```bash
   D=$(dirname "$(grep -rl --include='*.kt' --exclude-dir=build '^class .*ContentState(' .)")
   grep -rl "MaterialTheme.colorScheme" $(find "$D" -name '*.kt') | while read -r f; do
     awk -v F="$(basename "$f")" '/Color\.(White|Black)/ {
            print (p1 ~ /\/\// || p2 ~ /\/\// ? "  ok " : "BARE ") F ":" NR
          } { p2=p1; p1=$0 }' "$f"
   done
   ```

3. The tally, which is the number to watch over time:

   ```bash
   D=$(dirname "$(grep -rl --include='*.kt' --exclude-dir=build '^class .*ContentState(' .)")
   grep -rl "MaterialTheme.colorScheme" $(find "$D" -name '*.kt') | while read -r f; do
     awk '/Color\.(White|Black)/ { print (p1 ~ /\/\// || p2 ~ /\/\// ? "ok" : "BARE") } { p2=p1; p1=$0 }' "$f"
   done | sort | uniq -c
   ```

4. Spot-check three `ok` hits by reading them. If any of the three turns out to have a nearby comment
   about something unrelated, the heuristic is over-reporting and the real annotated count is lower
   than the tally claims.
