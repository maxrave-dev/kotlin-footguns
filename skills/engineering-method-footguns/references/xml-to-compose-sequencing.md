---
name: xml-to-compose-sequencing
description: Sequence a large XML-to-Compose migration — hardest screen first, expect the real work to be consolidating scattered state rather than swapping widgets, and plan for navigation to drag a route-serialization migration in with it. Use when planning a multi-release UI migration, when the layout file count refuses to go down despite screens "being migrated", or when deciding which screen to convert next.
---

# Sequencing an XML-to-Compose migration

A large migration is not N independent screen conversions. It has a critical path, and the
ordering decision that matters most is made in week one, before anybody has learned anything.

The version that works: **hardest screen first**, because the hardest screen surfaces the
architectural blockers while there is still budget to solve them properly. Easiest-first looks
safer, shows progress for months, then meets every blocker at once with the least schedule left.

Two consequences surprised the project this was mined from:

- **The widget swap is the small half.** The large half is consolidating state the old screens
  scattered across host classes, adapters and listeners into something a declarative UI can read.
- **Nothing gets deleted until navigation moves.** Screens render in the new toolkit long before
  the old artifacts can go, because the old navigation graph still owns the screen identities.

## What the history actually shows

Sampling the layout-file count at each release tag across one app's migration gives a shape that
contradicts the usual progress narrative:

| phase | layout XML files |
|---|---|
| pre-migration feature growth — no screen hosts Compose yet | 51 → 72 |
| the long middle — screens converting, sixteen months | 72 → 60 |
| the last burst of screen migrations, one release | 60 → 2 |
| the navigation release, a month later | 2 → 1 |
| after | 1 → 0 |

Two readings of that curve are tempting and both are wrong. **The rise is not the migration**:
the toolkit is not in the build at 51, and at the peak of 72 not one host class yet embeds a
Compose view. It is ordinary feature growth, and a count that climbs for reasons unrelated to
your migration has you planning around hosts nobody added. **The collapse is not the navigation
release**: it is the last burst of ordinary screen conversions — three commits over two days,
one deleting 49 layouts alone. Navigation lands a month later, in the *next* release, as the
2 → 1 step: one commit deleting the graph, the last host layout and all twenty host classes.

The other tell is in the commit that migrated the player screen — the hardest one, done early.
Its diff is 26 files, about 5,000 added and 2,700 removed lines, and per-file it goes:

- the old host class: **+1984 / −2025** — rewritten end to end, ending essentially the same size,
  and not deleted: it became a host for a Compose view and survived another year.
- the new screen: **+1259 / −0**; the shared state holder: **+678 / −403**, the largest non-UI file.

So the visible half of that change is the host class churning itself into a shell, and the
durable half is state moving into one holder. The screen file is the smallest story in it.

## Traps

**Easiest screens first.** It buys a burndown chart and defers every blocker to the end. The
blockers are the same size either way; only the remaining schedule differs.

**Counting migrated screens as progress.** A screen can render entirely in the new toolkit while
its old host class, layout and navigation entry all still exist. Count deleted artifacts: above,
sixteen months of conversion added no layout at all and removed only twelve, while host classes
rendering Compose went 0 → 8 → 16. The old world was not growing — it was being held alive.

**Treating navigation as one more screen.** It is a separate migration with its own dependency,
and in a type-safe navigation model it drags a **serialization** migration in with it: every
destination becomes a serializable type, with argument-passing rewritten at every call site. In
the recorded case that was one commit touching 139 files and removing about twice what it added.
Budget it as its own release, and expect the dependency catalog to move at the same time.

**Leaving the old host classes in place "for now".** They are cheap to keep and they are exactly
what stops the old layouts, navigation graph and argument plumbing from being deleted — which is
why all twenty surviving ones could only go in the navigation commit, and all twenty did.

**Migrating a screen whose state is still spread across listeners.** That is the tell for a
screen that should wait: if its data arrives through several callbacks that mutate fields,
converting the UI first means writing the same consolidation twice. Consolidate first, then convert.

**Doing the container or reactive-state migration mid-flight.** Both landed inside this migration
window — a dependency-container swap and a move from observable holders to state flows — and both
are cross-cutting. Land them before or after the UI phase, or every conversion carries stray risk.

**Assuming the shared state holder will stay reasonable.** Consolidating scattered state into one
holder is the right first move and it produces a very large class: the recorded one went from
about 1,790 to about 2,060 lines in the player-screen commit alone, having already absorbed
earlier screens. Plan the split as follow-up; do not let "it got big" argue against consolidating.

**Believing the last few files are nearly free.** The tail crept 63 → 62 → 60 over several
releases; of the last two, one waited on the navigation migration and the other on the old module
being deleted outright, months later. Each was held alive by a structural change, not by inertia.

## Verifying it

Run these read-only against the repository being migrated.

1. **Plot the real progress curve** — deleted artifacts per release tag, not screens converted:

   ```bash
   for t in $(git tag | sort -V); do
     printf '%-14s %s\n' "$t" "$(git ls-tree -r --name-only "$t" | grep -c '/res/layout/.*\.xml$')"
   done
   ```

   Flat means the old world is kept alive while screens convert; rising means hosts are being
   added — or that the rise predates the migration entirely. Date the two before reading either.

2. **Find the navigation commit, then check which release it actually landed in.** It is not
   necessarily the release where the count collapses — in the mined history it is the one after:

   ```bash
   git log --all --no-merges --diff-filter=D --format='%h %ad %s' --date=short --name-only \
     -- '*/res/navigation/*.xml' '*/res/layout/activity_*.xml'
   git tag --contains <that-commit> | sort -V | head -1
   ```

   Pass condition: the tag named here is the one whose curve step the navigation commit explains.
   If that is not the collapse tag, the collapse was screen work and the two events are separate.

3. **Confirm the serialization migration rode along with it:**

   ```bash
   NAV=$(git log --all --no-merges --format=%h --diff-filter=D -- '*/res/navigation/*.xml' | head -1)
   git show --format='' "$NAV" -- '*.kt' | grep -cE '^\+.*Serializable'
   ```

4. **Find host classes that are already just shells**, so you know what the navigation change
   will delete. Empty on the current tree once the migration finished; pass a migration-era tag:

   ```bash
   git grep -l 'ComposeView' -- '*Fragment.kt'
   git grep -l 'ComposeView' <migration-era-commit> -- '*Fragment.kt'
   ```

5. **Check where the weight of a "screen migration" commit really went.** Rank its files by lines
   added and removed *separately* — a host class churning into a shell is huge on both and net-zero:

   ```bash
   git show --numstat --format='' <screen-migration-commit> | sort -k1 -rn | head
   ```

6. **Before picking the next screen**, count the separate callbacks that mutate the state it
   renders. More than a couple means: consolidate first, convert second.
