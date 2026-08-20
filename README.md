# kotlin-footguns

140 battle-tested agent skills mapping the footguns of Kotlin, Compose Multiplatform and
desktop JVM development. Mined from a production codebase, not written from documentation.

Each skill is a standalone `SKILL.md` in the open agent-skills format, readable by Claude Code
and any coding agent that understands the format — and just as readable by a human. The corpus
is 17,000+ lines across 140 files, and in most of them the largest section is **Traps**: the
specific ways a technique fails in practice, each paired with a way to verify the failure and
the fix on your own tree.

## Why this repository exists

Most agent-skill collections for Kotlin and Android are written from official documentation.
They tell an agent what the API is supposed to do. This repository records what happened when
one team shipped against those APIs for years: the API that reports success while discarding
your data, the build flag that means something different on one platform, the verification
step that passes on broken code, the migration that deleted the wrong thing first.

None of it is theory. Every lesson here is older than the document that describes it — each
one had already been paid for in crash reports, failed releases, review rounds and user-filed
issues before it was written down.

## Where the lessons come from

The source is [SimpMusic](https://github.com/maxrave-dev/SimpMusic), a cross-platform music
client built with Kotlin and Compose Multiplatform, in continuous production since April 2023.
As of this writing it has earned more than 10,500 GitHub stars and 540 forks, and ships to
real users on Android, Windows, macOS and Linux through GitHub releases, F-Droid, IzzyOnDroid
and OpenAPK.

That codebase spans territory most sample projects never touch: a native media engine bound
over JNA, dual-player crossfade and DSP chains, a Room database at real-user scale, desktop
packaging and code-signing for three operating systems, CI that builds all of it, and a UI
written entirely in Compose. The skills are the distillation of that surface area.

The corpus itself is deliberately service-neutral. Skills teach architecture and failure
modes, never the mechanics of any third-party service; no service names or vendor field names
appear in any skill body. What was learned integrating specific services survives here as the
generic core that applies to whichever API you are consuming.

## What is inside

| Group | Skills | Focus |
|---|---|---|
| A | 11 | Native code on the desktop JVM: bindings, bundling, loading, memory |
| B | 13 | Desktop packaging, code signing, CI and build infrastructure |
| C | 9 | Multiplatform module structure, dependency injection, architecture |
| D | 18 | Media playback engine internals: players, crossfade, DSP, queues |
| E | 11 | Databases and SQL: sweeps, migrations, query traps at scale |
| F | 7 | Compose theming, palette extraction, gradients and scrims |
| G | 11 | Compose components and interaction patterns |
| H | 8 | Screens, navigation and adaptive layout |
| I | 8 | Reactive state: Flow, StateFlow, ViewModel lifecycles |
| J | 7 | Repository and data-layer patterns |
| K | 8 | Background work, services and platform runtime behavior |
| L | 12 | Consuming remote APIs: clients, parsing, auth flows, retries |
| M | 10 | Kotlin and multiplatform utilities and language traps |
| N | 7 | Engineering method: experiments, logs, changelogs, migrations |

The full annotated index, with one line per skill and its primary evidence, is in
[CATALOG.md](CATALOG.md).

## Anatomy of a skill

Every file follows the same discipline:

- **Frontmatter** — a `name` matching its folder and a `description` that states coverage,
  the trigger for reaching for it, and the symptom it explains.
- **A short orientation** — the working pattern, with code where code is clearer than prose.
- **Traps** — the dominant section: concrete failure modes, why each happens mechanically,
  and what to do instead.
- **Verifying it** — commands to run against your own codebase to confirm or rule out each
  claim. Quantities are expressed as commands you run rather than numbers that go stale.

Files are kept between 60 and 140 lines. A skill you cannot read in two minutes is a skill
an agent will not load in context.

## How the corpus was verified

Extraction ran as a five-batch pipeline, and no file shipped as first drafted. Each batch was
reviewed by independent adversarial lanes that received only the files and the source tree —
never the author's reasoning — and were instructed to refute, not confirm. Findings were
repaired in separate fix lanes, and a repair was accepted only with the re-run evidence
attached.

The bar tightened as the project ran. By the final batches, every command in every
"Verifying it" section had to be executed verbatim against the source tree before shipping —
a stated outcome that could not be reproduced was itself a defect. Mechanism claims were
re-derived rather than trusted: bytecode disassembly against the pinned artifacts, Kotlin
stdlib sources, Python simulations of ported logic, and re-runs of the git history behind
every historical claim. Code comments, changelogs and commit messages were excluded as
evidence throughout; anything sourced only from prose is marked as such in the file.

In the final two batches alone this review raised close to thirty blocking findings — among
them verification steps that passed on defective code and prescribed fixes that did not fix
the case they named — every one repaired or refuted with recorded evidence before release. A
closing sweep re-checked all 140 files for identifier leaks, structural consistency and
cross-reference integrity, and confirmed the catalog matches the folders one to one in both
directions.

## Installation

Two ways in, two philosophies. The Claude Code plugin installs the whole set as a managed,
read-only bundle that updates when this repository does — you subscribe rather than fork. The
skills CLI copies editable skill files into your own project, for any agent, so you can prune
and rewrite them. Pick one; installing both leaves you with every skill twice.

### Claude Code, as a plugin

```
/plugin marketplace add maxrave-dev/kotlin-footguns
/plugin install kotlin-footguns@maxrave
```

Updates arrive with `/plugin marketplace update maxrave`.

### Any agent, as editable files

```bash
npx skills@latest add maxrave-dev/kotlin-footguns
```

The installer lets you pick which of the 140 skills to take and which agents to install them
for — Claude Code, Cursor, Codex, Copilot, Windsurf, Gemini and others. The files land in
your repository as ordinary markdown you own and can edit; nothing updates behind your back.
Pull newer versions when you want them with `npx skills update`.

Either way, each skill's `description` tells the agent when to load it, so installing many is
cheap: a skill enters context only when its trigger matches the work at hand. And because
every file is plain markdown built around traps and verification commands, the corpus reads
as an engineering reference without any agent at all.

## License

GPL-3.0 for the whole repository, matching the source project. One skill,
`custom-shuffle-order`, adapts a design from Auxio's GPL-3.0 shuffle implementation and
carries its provenance note in the file.

## Related

- [SimpMusic](https://github.com/maxrave-dev/SimpMusic) — the source codebase
- [simpmusic.org](https://simpmusic.org) — the project site
