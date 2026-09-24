---
name: engineering-method-footguns
description: "Debugging-method traps: run the discriminating experiment first, read build logs bottom-up, treat an empty actual as unwritten, audit shared handles before removing a feature, read commit history critically. Use when a fix is not converging."
---

# Engineering method footguns

9 traps mined from a production Kotlin and Compose Multiplatform app, one short file each
under `references/`. Every file gives the working pattern, the **Traps** (the specific ways it
fails in practice, and why), and a **Verifying it** section with commands to run against the
user's own tree.

**How to use this index.** Match the code about to be written, or the symptom being chased,
against the entries below: each names its topic and the symptom that should send you to it. Read
every file that plausibly applies with the Read tool before proposing code or a fix; each is under
150 lines. Where a Verifying command names the source project's paths, substitute the equivalent
paths in the user's tree.

**Cross-references.** A backticked trap name inside a file that is not listed here lives in a
sibling area skill: glob `../*/references/<name>.md` to open it.

## Engineering method

- [`run-discriminating-experiment-first`](references/run-discriminating-experiment-first.md) — When two nearly identical things behave differently, count the variables that still differ and run one swap-or-trade test that eliminates at least half of them, before writing any fix. Use when the same symptom has survived two or more attempted fixes, when one widget or screen or platform works and its near-twin sitting beside it does not, or when every attempt costs a slow build and somebody else's attention.
- [`noop-actual-not-platform-limit`](references/noop-actual-not-platform-limit.md) — An empty or pass-through platform implementation in a multiplatform project means nobody wrote it, not that the platform cannot do it — check the dependency's resolved variants and the source set that declares it before telling anyone a feature is impossible there. Use when a feature "doesn't work on desktop/iOS", when a platform file returns its input unchanged or has an empty body, or before writing off a feature as a platform limit.
- [`read-build-logs-bottom-up`](references/read-build-logs-bottom-up.md) — Read a build log by going to the bottom for the verdict and then to the FIRST error marker for the cause — never a fixed-size window from either end, because the causal message and the failure banner sit at opposite ends of the output. Use when a background build finishes and you are about to summarise it, when a log says only "task X FAILED" with no reason, or when a filter came back empty and you are about to call that a clean build.
- [`changelog-as-war-story`](references/changelog-as-war-story.md) — Keep a tracked markdown file of dated entries that record symptom, mechanism, what was ruled out and the condition for removing the workaround — and enforce it with a rule that the entry lands with the change. Use when a fix rests on non-obvious behaviour someone will later "clean up", when the same investigation keeps being repeated, or when onboarding a human or an agent into an area with expensive traps.
- [`writing-agent-skill-house-style`](references/writing-agent-skill-house-style.md) — Write an agent skill that survives an adversarial review — a description carrying both the trigger and the error symptom the reader is staring at, a short orientation, a Traps section that dominates the file, and verification commands you have actually run. Use when authoring or reviewing a SKILL.md, when a skill reads like documentation instead of hard-won advice, or when review keeps finding claims the source repository does not support.
- [`xml-to-compose-sequencing`](references/xml-to-compose-sequencing.md) — Sequence a large XML-to-Compose migration — hardest screen first, expect the real work to be consolidating scattered state rather than swapping widgets, and plan for navigation to drag a route-serialization migration in with it. Use when planning a multi-release UI migration, when the layout file count refuses to go down despite screens "being migrated", or when deciding which screen to convert next.
- [`commit-archaeology-red-flags`](references/commit-archaeology-red-flags.md) — Mine a repository's history without being misled by it — an empty-bodied commit's file statistics are its real abstract, a nested-repository bump hides its entire content behind a one-line pointer change, and a merge flattens a branch's decision trail into a single subject. Use when reconstructing why something is the way it is, when a blame lands on a commit whose message explains nothing, or when a change appears to touch one line and cannot possibly be that small.
- [`removing-a-feature-audit-shared-handles`](references/removing-a-feature-audit-shared-handles.md) — Delete a feature that duplicates a newer one — two effects on one output multiply — after auditing what else uses the handle the removed feature appeared to own, deleting the no-op stubs on the other platforms, and force-stopping before judging whether the removal worked, because an already-attached external effect outlives the change. Use when replacing a delegating integration with an in-app one, or when a removed feature still seems to be running.
- [`a-stated-rule-needs-annotated-exceptions`](references/a-stated-rule-needs-annotated-exceptions.md) — A design rule with legitimate exceptions survives only if every exception carries its reason at the call site and the rule itself is greppable — otherwise nothing distinguishes an exception from a violation and the rule silently rots. Covers where the rule statement goes, where the reasons go, scoping the audit to the code the rule actually governs, and the limits of a comment-based check. Use when a stated convention is drifting, when reviewers cannot tell deliberate from careless, or before writing a rule into a file header and assuming it will hold.
