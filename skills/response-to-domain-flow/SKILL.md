---
name: response-to-domain-flow
description: The five stages a remote response passes through — transport model in a per-integration service module, a pure parser layer, a domain model, a result envelope, then collection — with the rule that each integration is its own module so one source's breakage cannot spread, and the placement rules that keep transport types out of screens. Use when adding a second remote source, when a UI file has started importing response classes, or when a screen shows a spinner forever after a response shape changed.
---

# Where each stage of the pipeline lives

Five stages, each in exactly one module:

| Stage | Lives in | Visibility |
|---|---|---|
| Transport model — the response as sent | the integration's own service module | public to the data module |
| Parser — response object → domain model | the data module, `parser/` package | `internal` |
| Domain model, repository interface, envelope | the domain module | public |
| Repository implementation — calls, wraps, maps | the data module | `internal` |
| Collection — envelope → screen state | the presentation module | — |

The repository method is where four of the five meet, and it stays this short because the parsing is
somewhere else:

```kotlin
// adapted — the service, model and parser names are generalized. The body is the source's own
// shape; see the first trap for the defect it carries.
override fun getReleaseData(id: String): Flow<Resource<ReleaseBrowse>> =
    flow {
        runCatching {
            catalog.release(id, withTracks = true)
                .onSuccess { result -> emit(Resource.Success(parseReleaseData(result))) }
                .onFailure { e -> emit(Resource.Error(e.message.toString())) }
        }
    }.flowOn(Dispatchers.IO)

// data module, parser/ReleaseParser.kt — pure, not suspend, no I/O
internal fun parseReleaseData(data: ReleasePage): ReleaseBrowse { … }
```

**One service module per integration**, each depending only on the shared HTTP module and the domain
module — never on a sibling integration. That is the whole containment story: when a source changes
its response shape, the compile errors and the runtime failures are confined to one module and the
repository methods that call it, and every other source keeps working.

## Traps

**Wrapping the whole body in a catch-all turns a parser crash into a permanent spinner.** In the
method above, the outer `runCatching` has no failure handler of its own *and the parser call sits
inside it* — so when the parser throws on a shape it did not expect, neither `emit` runs, the
throwable is discarded, and the flow completes normally having emitted nothing. The collector's
branch over the envelope never executes, the screen keeps its loading state, and there is no crash
and no log line. This is the single most expensive shape in this pipeline because the parser is
exactly the layer that throws when a source changes. Either drop the outer catch and let the
exception reach the collector, or give it an `onFailure` that emits an error. `repository-flow-conventions`
covers the method shapes this one belongs to.

**The parser belongs in the data module — not in the service module, and never in the view model.**
The service module owns the transport shape and must not know the domain model; the domain module
must not know the transport shape. The parser is the one place both are legitimately visible, which
is what makes the data module the only correct home. Putting it in the service module inverts the
dependency; putting it in the view model puts transport classes on screen state.

**A parser that returns a transport type has achieved nothing.** If an envelope of a response class
exists anywhere, every screen that unwraps it imports the response class, and the next shape change
is a UI change. The boundary is enforceable and worth enforcing: mark the parsers `internal`, and
check that no presentation file imports the parser or transport package.

**Service-module parsers are a different, laxer population — know which you are looking at.**
Helpers that live inside a service module cannot be `internal` to the data module and are usually
public, so they can be called from anywhere that depends on that module. That is not automatically
wrong, but it means the visibility guarantee above covers only the data-module layer, and a
duplicate helper on the service side can drift from its data-side twin. Grepping for one and finding
one proves nothing about the other.

**Keep the parser pure — no `suspend`, no I/O, no clock, no dispatcher.** Then a captured payload
plus an assertion is a complete test, with no network and no fakes, and a response shape change is
reproducible from a saved file. A parser that fetches "just one more thing" mid-parse loses that
property permanently and drags a dispatcher decision into a layer that should have none.

**One parser file per response kind, and watch the line count.** These files grow: a shared home or
feed response accumulates a branch per section type until one file is several hundred lines and a
failure in any section is a failure of the whole parse. Split by section, and let each section's
parse fail independently so one unrecognised shelf does not empty the screen.

**Mapping to the domain model is where "not stated" quietly becomes a value.** The parser is under
pressure to fill every field of a non-nullable domain model, so a missing marker becomes a default
and a missing name becomes a placeholder — both indistinguishable from real data thereafter. Make
the domain field nullable instead. `enum-normalize-over-legacy-data` is the discipline for the marker
case; `structural-defensive-parsing` is the one for the reading itself.

**Two integrations that must not know about each other will find a way if you let them.** The moment
one service module depends on another — to reuse a model, a client, or a helper — a shape change in
the second breaks the first, and the containment the module split bought is gone. Extract the shared
piece downward into the HTTP or domain module instead; the dependency direction is the point.

## Verifying it

The pipeline is a set of cross-module claims, so check it with commands rather than by reading one
file. Use `find … -path` rather than a `**` glob — with globstar unset, `**` fails before the search
runs, and a failed command produces no output, which reads exactly like a clean result:

```bash
find . -path '*/service/*' -name 'build.gradle.kts' -not -path '*/build/*' -exec grep -Hn 'projects\.' {} +
find . -path '*/parser/*' -name '*.kt' -not -path '*/build/*' -exec grep -cH 'suspend fun' {} +
find . -path '*/ui/*' -name '*.kt' -not -path '*/build/*' -exec grep -ln 'import .*\.parser\.' {} +
find . -path '*/parser/*' -name '*.kt' -not -path '*/build/*' -exec wc -l {} + | sort -n | tail
```

The first is the containment check: read the dependency list of each integration and confirm none of
them names another integration — only the shared HTTP module and the domain/common modules should
appear. The second should print **`:0` for every parser file**; a single non-zero is a parser that
does I/O and is no longer testable from a captured payload. The third should print nothing at all
and exit non-zero — that non-zero is the *good* outcome here, meaning no presentation file imports a
parser package, so do not read it as a broken command. The fourth ranks the parser files by size and
shows you which one has become a catch-all.

For the silent-completion trap, the test is specific: collect a remote read with a deliberately
broken parser and assert that *something* was emitted. A test that only asserts "no exception
thrown" passes on the broken version, which is precisely how that shape survives review.

Related: `repository-resource-flow-pattern` for the envelope this pipeline ends in, and
`repository-flow-conventions` for which repository methods get one.
