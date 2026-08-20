---
name: run-discriminating-experiment-first
description: When two nearly identical things behave differently, count the variables that still differ and run one swap-or-trade test that eliminates at least half of them, before writing any fix. Use when the same symptom has survived two or more attempted fixes, when one widget or screen or platform works and its near-twin sitting beside it does not, or when every attempt costs a slow build and somebody else's attention.
---

# Run the discriminating experiment first

Two things are almost the same. One behaves, the other does not. The instinct is to fix by the
strongest hypothesis, verify, and if that fails move to the next hypothesis. That loop has a
terrible payoff curve: a guess costs one full verification round and returns information only when
it happens to be right.

A **discriminating experiment** costs the same round and returns information either way, because
you decide *before* running it what each outcome rules out. Swap the two things' positions. Trade
one attribute between them. Run both variants side by side in one build. Whatever comes back,
half the candidate causes are gone.

The rule of thumb: **count the variables that still differ between the working and the broken
side. If that count is greater than one, you are not allowed to write a fix yet.**

## The recorded case

In a multiplatform media app, a header carried two controls using the same visual-effect helper:
a 48dp round icon button on the leading edge and an elongated multi-icon pill on the trailing
edge. The pill showed the glass rim. The button showed nothing.

Four verification rounds went to hypotheses — change the button's shape, remove a wrapper layer,
feed the effect real content instead of a flat colour, copy the structure from the other
orientation. All four were wrong, and the person running the builds had lost patience before any
result arrived.

The fifth round swapped the two controls between the leading and trailing edges. The effect
followed the **pill**, not the position. Position was eliminated in one round, and what remained
was the widget's own geometry: the rim style in use was lit along a single direction, so a long
edge catches the sweep and a small circle catches almost none of it. Recorded history for that
area now says the four guesses were burned "before anyone read the library source".

## Traps

**Fixing while more than one variable differs.** This is the whole failure. Two controls that
differ in shape, size, nesting depth, sampled surface and position give you five candidates; a
fix aimed at any one of them has a one-in-five prior and tells you nothing when it fails. Write
the list down first — the act of listing is usually what reveals that you have five and not two.

**Designing a test whose outcomes you cannot tell apart in advance.** Before running anything,
finish both sentences: "if the effect moves with the widget, then ___" and "if it stays at that
position, then ___". If either sentence is hard to finish, the experiment does not discriminate
and you are about to spend a round on nothing.

**Changing two things inside the "swap".** A swap that also re-indents, renames or tidies is no
longer a swap. Move the two call sites and change nothing else, even things that look obviously
wrong on the way past. Fix those in a separate change after the result is in.

**Deleting a live experiment during a tidy-up pass.** Recorded in the same episode: one screen's
variant was removed while "making things consistent", and the build it was riding in came back
useless. An experiment is not untidy code — it is an instrument with a reading pending. Mark it
so a cleanup pass can see it, and do not remove it until somebody has read the result.

**Running one variant per round when the round is expensive.** If a build is the bottleneck, put
several variants in the *same* build — one per screen, one per row, one per flag — and label
them. Four hypotheses in one round beats four rounds. This only works if the previous trap is
respected.

**Treating a partial improvement as confirmation.** In the recorded case, widening the round
button to roughly twice its size did make the effect appear. That looks like a solved bug and is
not: the longer edge simply caught more of the directional sweep. A change that improves the
symptom without your being able to say *why* is a second observation to explain, not a fix to
ship.

**Believing a comment or a changelog entry about which variable matters.** Prose in the
repository records what somebody concluded at the time, and the code beside it may have moved on.
Treat it as a hypothesis to test, in exactly the same queue as your own.

**Asking a human for a verification round you could have run yourself.** Each round you delegate
costs someone else's attention and arrives minutes-to-hours later. Before requesting one, check
whether the question can be settled by reading an artifact instead — the dependency's own source,
the resolved artifact list, the generated output. The four wasted rounds above were all
answerable from the library source without a build.

## Verifying it

1. **List the differing variables and check the count.** Pull both call sites of the shared
   helper into one view and diff them; every surviving line is a candidate:

   ```bash
   HELPER=TheSharedComposable          # the widget or function both sides call
   grep -rn "$HELPER(" --include='*.kt' .
   ```

   More than one difference means: design an experiment, do not write a fix.

2. **State the outcomes before you run it.** Write the two "if … then …" sentences into the
   change description or the ticket. If you cannot, redesign.

3. **Confirm the experiment is still alive before the result is read.** Tag every variant with a
   marker word and check that no cleanup pass has quietly removed one. Bare `git diff` compares
   the working tree to the index only, so a cleanup that was staged — or committed, the ordinary
   case once somebody has tidied and moved on — passes it silently:

   ```bash
   grep -rn 'EXPERIMENT' --include='*.kt' . | wc -l
   git diff HEAD -- '*.kt'                   | grep -E '^-[^-].*EXPERIMENT'
   git log -p <branch-point>..HEAD -- '*.kt' | grep -E '^-[^-].*EXPERIMENT'
   ```

   Pass condition: the count matches the number of variants you planted, and both greps print
   nothing. `^-[^-]` rather than `^-`, so the `--- a/path` diff header cannot match instead.

4. **After the result, prune the hypothesis list explicitly.** Name which candidates the outcome
   eliminated. If it eliminated none, the test did not discriminate — that is the finding, and
   the next step is a better test, not another fix.

5. **Remove the markers in their own change**, once the cause is known, so the diff that proves
   the fix is not tangled with the instruments that found it.
