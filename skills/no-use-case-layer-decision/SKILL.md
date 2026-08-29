---
name: no-use-case-layer-decision
description: Decide whether a mid-size app needs an interactor or use-case tier at all, how a clean boundary survives without one (repository interfaces plus pure mapping functions), how to prove an absence rather than assume it, and the specific signal that says it is finally time to add the tier back. Use when the tier feels like typing with no payoff, when reviewing an architecture that has none, or when the same orchestration has been pasted into a third view model.
---

# Shipping without a use-case tier

The textbook stack puts an interactor between the presentation layer and the repository. A
mid-size, feature-broad app can ship with **zero** of them and still have a boundary worth the
name, because the boundary was never the interactor — it was the interface.

What holds it up instead:

- **Repository interfaces in the domain module.** The view model's constructor names
  `AlbumRepository`, never `AlbumRepositoryImpl`, which is `internal` to the data module
  (`clean-arch-kmp-readiness`).
- **Pure mapping functions, internal to the data module.** `internal fun ServiceDto.toTrack(): Track`
  — extension functions, no class, no injection, no lifecycle. This is where a DTO becomes a domain
  model, and it is the one piece of "business logic in a layer" that a use case would otherwise host.
- **A result envelope the repository returns.** So the view model branches on states, not on
  transport failures (`repository-resource-flow-pattern`).
- **Repositories split by aggregate, not one per app.** Roughly one per top-level concept, each in
  the tens of methods. Check the shape before deciding anything:
  ```bash
  DOMAIN_SRC=core/domain/src   # your equivalent of :domain
  find "$DOMAIN_SRC" -path '*/repository/*.kt' | while read -r f; do
    echo "$(grep -cE '^    (suspend )?fun ' "$f") $(basename "$f")"
  done | sort -rn
  ```
  A long tail of small interfaces is healthy. One interface with hundreds of methods means the tier
  did not disappear — it was poured into a single repository.

## Proving an absence

"There are no use cases" is a claim that decays silently, so make it a command. A use-case tier
hides under at least five spellings, and one grep misses four of them:

```bash
# 1. the obvious names
grep -rn "class .*UseCase\|interface .*UseCase\|class .*Interactor" --include="*.kt" .

# 2. the file naming, in case the class is named something else
find . -name "*UseCase*.kt" -o -name "*Interactor*.kt"

# 3. the package, which is often the only marker
grep -rn "^package .*\.\(usecase\|usecases\|interactor\|interactors\)$" --include="*.kt" .

# 4. the invoke-operator shape — a single-method class used as a function
grep -rn "operator fun invoke" --include="*.kt" .

# 5. the folder, for a tier that exists but is empty
find . -type d \( -name usecase -o -name usecases -o -name interactor \)
```

Exclude generated output (`--exclude-dir=build`) or the results are noise. All five returning
nothing is the evidence; anything else means the tier exists and the real question is whether it is
consistent. Put this in a review checklist rather than a comment — a comment claiming an absence
ages badly, and a comment is not evidence for a structural property.

## What the tier would have bought

Be specific about what is being given up, because it is not nothing:

- **Composition across repositories.** A flow that reads two repositories and merges them has no
  natural owner and lands in the view model.
- **A test seam without the presentation framework.** Orchestration tested through a use case needs
  no view model harness, no main-thread dispatcher rule, no lifecycle owner.
- **A name for the operation.** `AddSongToPlaylist` is greppable in a way that "the block inside
  `fun onAddClicked`" is not.
- **Reuse across presentation surfaces.** A widget, a background job and a screen wanting the same
  operation each re-implement it otherwise.

## The tell for adding it back

**The same orchestration pasted into a third view model.** Two is a coincidence and a shared private
function is enough; three is a structural signal that the operation exists independently of any
screen. Reintroduce it for *that operation only* — a single class, injected where the repositories
were, returning the same envelope type. A tier introduced wholesale, one wrapper per repository
method, buys none of the four benefits above and doubles the call chain.

The second, weaker tell: a background component (a widget, a scheduled job, a notification handler)
needs an operation that currently lives in a view model. Rather than injecting a view model into it
— see `koin-viewmodel-scoping-traps` for why that goes wrong — lift just that operation out.

## Traps

**Dropping the tier does not license logic in the view model — it relocates the ceiling.** Without
the tier the session-scoped view model is the one that absorbs orchestration, and it grows without
any single change looking unreasonable. Watch it by size, not by feel:
```bash
APP_SRC=composeApp/src   # your equivalent of :app
find "$APP_SRC" -path '*/viewModel/*.kt' -exec wc -l {} + | sort -rn | head
```
When one file is an order of magnitude larger than its siblings, the tier came back — unnamed,
untestable and bound to the presentation lifecycle.

**"No use cases" is not "no domain layer".** The domain module still owns the interfaces, the
models and the capability ports. An architecture with repository implementations injected directly
into view models has no boundary at all, and it looks identical in a folder listing.

**Do not let a repository return transport types to skip a mapper.** The moment
`fun search(q: String): Flow<ServiceSearchResponse>` exists, every consumer imports the service's
model and the missing tier stops being the problem. The mapping functions are the load-bearing
part; the interactor was optional.

**The pure-function alternative is only pure if it stays a function.** A mapper that starts taking
a repository, a dispatcher or a clock has become a use case wearing a `fun` keyword — with none of
the discoverability. At that point name it and inject it.

**A "clean" review still has to check the direction of dependencies**, not the presence of folders.
Run the grep from `clean-arch-kmp-readiness` that lists what the app module imports out of the data
module. A stack with no use cases and no leaks is clean; a stack with a full interactor tier and a
repository implementation imported into a screen is not.

## Verifying it

`## Proving an absence`, above, is this skill's main check — run it before trusting anything else
here. These three cover the claims that hold the boundary up in its place:

1. **No view model imports a `RepositoryImpl`, only the interface:**
   ```bash
   VM_DIR=composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/viewModel   # your equivalent
   grep -rln "RepositoryImpl" --include="*.kt" "$VM_DIR"
   ```
   Pass condition: no output. A hit means a screen is constructing (or naming) the implementation directly, and the interface boundary is decorative for that one class.

2. **The pure mapping functions this skill leans on for "where did the use case's logic go" exist,
   and stay `internal`:**
   ```bash
   grep -rn "internal fun .*\.to[A-Z][A-Za-z]*(" --include="*.kt" core/data/src | wc -l
   ```
   Pass condition: nonzero — here, 19 — and each one only reachable from inside the data module. A
   public one is a mapper the app module could call directly, skipping the repository.

3. **No repository interface imports an integration's transport types — checked by inverting the whitelist instead of naming one:**
   ```bash
   DOMAIN_REPO=core/domain/src/commonMain/kotlin/com/maxrave/domain/repository   # your equivalent
   grep -rh "^import " "$DOMAIN_REPO"/*.kt | grep -v "^import com.maxrave.domain\|^import kotlin" | sort -u
   ```
   Pass condition: nothing printed belongs to an integration module — here it prints one line, `import androidx.paging.PagingData`. A hit is the "do not let a repository return transport types" trap, caught structurally instead of in review.
