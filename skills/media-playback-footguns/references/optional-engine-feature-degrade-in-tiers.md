---
name: optional-engine-feature-degrade-in-tiers
description: An optional build-time dependency of a media engine may be missing from another platform's bundle, and the engine rejects the WHOLE chain string when one stage in it is unknown — so retry without the optional stage rather than losing the mandatory one, and return which tiers were accepted so callers never drive a stage that is not there. Use when a feature works on one platform's bundle and silently does nothing on another.
---

# Degrade an optional stage in tiers, and report what survived

Engines that take their processing graph as a **string** validate the whole string at once: one
unknown stage name and nothing installs — not "that stage is skipped", the entire graph is rejected.
So a chain mixing a stage that ships everywhere with one that is an optional build-time dependency
has a failure mode where the *mandatory* half disappears because of the optional half. Attempt, fall
back by tiers, and hand the caller a record rather than a boolean:

```kotlin
/** What the install actually got past the engine. Callers must not drive a stage that is false. */
data class Chain(val sweep: Boolean, val pitchShift: Boolean) {
    companion object { val NONE = Chain(sweep = false, pitchShift = false) }
}

fun installChain(sweep: Sweep?, startHz: Float, pitchShift: Boolean): Chain {
    if (sweep == null && !pitchShift) { clearChain(); return Chain.NONE }
    if (apply(sweep, startHz, pitchShift)) return Chain(sweep != null, pitchShift)
    // The pitch stage is an OPTIONAL build-time dependency; the filter stages ship with every build
    // of the underlying codec library. Drop the optional one rather than lose the sweep too.
    if (pitchShift && sweep != null && apply(sweep, startHz, pitchShift = false)) {
        log.w(TAG, "pitch stage unavailable; keeping the sweep without the pitch match")
        return Chain(sweep = true, pitchShift = false)
    }
    log.w(TAG, "could not install the chain; falling back to a plain volume fade")
    clearChain(); return Chain.NONE
}
```

## Traps

**A boolean return cannot express the interesting outcome.** "Did the install land" has three
answers here, not two, and the middle one — partial — is the one the caller has to behave
differently for. A boolean forces the caller to re-derive which stages exist, usually by re-checking
the same condition that was already wrong.

**Per-step commands against a stage that is not there fail on every frame.** The reason the record
matters is that the follow-up updates — retuning a live filter as an animation advances — are
addressed to a stage by name. Against a missing stage they fail at animation frame rate: a log
flood, an animation that visibly does nothing, and nothing that looks like an error to the user.
Gate every per-step call on the tier flag, at the caller.

**Install the stages at a neutral setting, so the install itself is inaudible.** A sweep armed at its
own start frequency and a pitch stage armed at ratio 1.0 change nothing until the first per-step
command arrives — which is what lets you build the graph once, up front, and pay the expensive
rebuild outside the animation. It also means "present" and "doing something" are different
questions: the record answers the first, and a caller that treats it as the second will report a
feature as active before it has ever been given a target.

**Do not probe by asking the engine what it was built with.** A capability or feature list answers a
different question from "will this exact graph build" — the stage can be present but reject your
parameters, or be listed under a name your string does not use. Attempt the real string and read the
real result; the attempt is the probe. This is the same discipline as
`upstream-lib-bug-workaround-template`: pin the behaviour you observed, not the version you think
has it.

**Order the tiers by what is lost, and make the last tier a real fallback.** Optional stage first,
mandatory stage second, no chain third — and the third must actually *clear*, not leave whatever the
failed attempt deposited. A half-built graph that nobody clears is worse than no graph, because the
next feature to write the property inherits it.

**Log the degradation once, at install, and never per step.** One warning naming the tier that was
lost is diagnosable; the same warning at frame rate is what makes the log unusable in exactly the
session you need it. Callers gated on the tier flag will not produce the per-step lines at all.

**A degraded tier is not an error to surface to the user.** The feature still works, with less. A
dialog here trains users to dismiss dialogs; the log line plus the disabled sub-control is the
right pair. Do surface it if the *mandatory* tier fails, because that is a behaviour change.

**Clearing a stage also clears whatever that stage was holding.** The optional stage usually carries
state of its own — a pitch ratio, a wet/dry mix, a filter cutoff — and dropping it from the chain
resets that silently. Say so where `clearChain()` is defined, and enumerate what callers must
re-assert afterwards; otherwise the reset shows up two features away, as "the speed reverts when the
transition ends".

**Remember that this composes with the other owner of the chain property.** Retrying a tier means
writing the chain string more than once, and if a second feature also has entries in there, every
one of those writes has to carry both. See `filter-chain-two-owners-one-writer` — a tiered install
that writes the property directly is the fastest way to discover that skill the hard way.

**The optional stage's absence is platform-shaped, not user-shaped.** It depends on how the native
bundle for that platform was built, so it is stable per build and invisible on the developer's own
machine — the classic "works here, silently does nothing in the shipped artifact". Record which
bundle you verified the stage in, next to the fallback.

## Verifying it

The fallback path never runs on a machine where the stage is present, so force it:

```bash
# what the shipped bundle actually contains — run against the artifact, not the dev machine
# usage: bash probe.sh <optional-stage-name>
LIB=$(find natives -type f \( -name 'lib*.so*' -o -name '*.dll' -o -name '*.dylib' \) 2>/dev/null | head -1)
[ -n "$LIB" ] || { echo "no native bundle staged under natives/"; exit 1; }
STAGE="${1:?name the optional stage, e.g. the pitch-shift filter}"
strings "$LIB" | grep -i "$STAGE" | head -3
```

Many builds embed their own configure line, so this often answers outright — a hit reading
`-Dsomestage=disabled` is the whole diagnosis, and it is the case a developer's machine never shows.

Then exercise all three tiers deliberately:

- install with a **deliberately misspelt** optional stage name and assert the mandatory stage is
  still installed and the returned record says `optional = false`;
- misspell **both** and assert the record is `NONE` **and** that the chain property is empty
  afterwards — the clear on the last tier is the half that gets forgotten;
- with the optional stage reported absent, run the animation and assert **zero** per-step commands
  were issued. A test that only checks the install return value passes while the caller still
  hammers a stage that is not there.
