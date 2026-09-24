---
name: clean-arch-kmp-readiness
description: Lay out a Kotlin Multiplatform app in layers that actually hold — a domain module carrying interfaces and models, repository implementations kept internal to the data module, and one module per external integration so a breaking service cannot spread — plus how to verify each boundary with a grep instead of trusting the diagram. Use when starting a multiplatform app, when splitting a monolithic module, or when platform types have started appearing in shared feature code.
---

# Layering a multiplatform app so the boundaries survive

Six kinds of module, and the direction of every arrow is checkable:

| Module | Holds | Depends on |
|---|---|---|
| `:common` | constants, logging facade | nothing |
| `:domain` | repository **interfaces**, models, capability ports | `:common` |
| `:data` | repository **implementations**, database, mappers | `:domain`, every integration, and each engine from the source set that needs it |
| `:<integration>` | one external service client, one per module | `:domain`, `:common`, the shared HTTP module |
| `:<engine>-<platform>` | one playback/native engine per platform | `:domain` |
| `:app` | screens, view models, container wiring | `api(:domain)`, `implementation(:data)` |

The `:data → :<engine>-<platform>` arrows are per source set, not global: the common source set
names the integrations, while each platform source set adds only its own engine. That is what keeps
one engine off the other platform's compile classpath.
The asymmetry in the last row is the whole trick. The app module takes `:domain` as `api` — it
names those interfaces constantly — and `:data` as `implementation`, purely so the container has
something to construct. Every **repository** implementation inside `:data` is then declared
`internal` (other classes there are public where a platform entry point or the database needs them):

```kotlin
// adapted — interface trimmed to two members, remote client renamed
// :domain
interface AlbumRepository {
    fun getAllAlbums(limit: Int): Flow<List<AlbumEntity>>
    fun getAlbumData(browseId: String): Flow<Resource<AlbumBrowse>>
}

// :data — internal, so nothing outside this module can name it
internal class AlbumRepositoryImpl(
    private val localDataSource: LocalDataSource,
    private val remote: <ServiceClient>,
) : AlbumRepository { /* … */ }
```

Confirm it, don't assume it — two greps, Verifying it #1, both of which should come back nearly
empty: the app module's surviving imports out of the data module are glue, never a repository name.

## One module per integration

Each external service gets its own module whose build file names only `:domain`, `:common` and the
shared HTTP module — never another integration, never `:data`. Verify the whole set at once with
Verifying it, #2. The payoff is blast radius: when one provider changes its response shape
overnight — the normal condition for an endpoint you do not control — the break is confined to one
module, and a build flavour can swap a whole integration for a no-op twin with the same public
surface (see `buildkonfig-secrets-flavors`).

## The domain module owns the ports, not just the data

Anything the app needs but a platform provides gets an interface in `:domain`, expressed in types
`:domain` also owns:

```kotlin
// adapted — renamed, trimmed from a much wider transport interface
// :domain — no engine types anywhere in this signature
interface MediaEngineInterface {
    fun play()
    fun seekTo(positionMs: Long)
    fun setMediaItems(items: List<GenericMediaItem>)   // Generic* declared in :domain
}
```

Without the `Generic*` models the interface would have to name the platform engine's own item type,
and that single import drags the engine into shared code on every target. Each platform module then
supplies the implementation. Same pattern for preferences (`datastore-kmp-manager`) and for the
database (`room-kmp-setup`).

## Traps

**"The domain has no framework annotations" is a claim, not a property — measure it.**

```bash
DOMAIN_SRC=core/domain/src   # your equivalent of :domain
grep -rn "^import android\.\|^import androidx\." --include="*.kt" "$DOMAIN_SRC" \
  | sed 's/.*import /import /' | sort | uniq -c | sort -rn
```

Run it before writing the sentence in your own architecture document. A common, load-bearing
result is that the domain is clean of UI and platform imports but **does** carry the persistence
library's entity annotations, because the entity classes sit there so both the database and the
interfaces can name them — a real trade (the alternative is a parallel set of domain models plus
mappers for every table), but know it: the domain now depends on the persistence library, and
swapping libraries later touches everything else. Say "no platform or UI types in the domain," not
"no annotations."

**A layer that only forwards is a layer you are paying for.** Before adding an orchestration tier
between view models and repositories, read `no-use-case-layer-decision` — a mid-size app can hold
the boundary with interfaces plus pure mapping functions, and this whole module graph works without
that tier.

**Mapping belongs in `:data`, `internal`, as extension functions.** `internal fun
ServiceDto.toDomainModel(): DomainModel` sits next to the repository that calls it. Put it in
`:domain` and the domain must import the service's transport types — the exact coupling the layer
exists to prevent. Put it in the app module and every screen re-derives it slightly differently.

**`implementation` between layers is what makes the boundary enforceable.** Declaring `:domain` as
`api` from `:data` re-exports it to everything downstream, and then a module that never asked for
the domain still compiles against it — so an accidental dependency never fails the build. Use
`api` only where a module genuinely re-exports a type in its own public signatures.

**Modules created for symmetry cost real build time.** A module per architectural noun sounds tidy
and produces a graph nobody can hold in their head. The split that pays here is by *reason to
change*: one per external service, one per platform engine, one for storage. Layers with no
independent reason to change stay together.

**A capability port with a platform type in one signature is not a port.** One `fun
setSurface(view: <PlatformView>)` on an otherwise clean interface pulls the platform into every
target's compile classpath. Grep the port's own file for platform imports before calling it shared.

## Verifying it

1. **Repository implementations are internal, and nothing has exploited the cases that are not:**
   ```bash
   DATA_SRC=core/data/src      # your equivalent of :data
   APP_SRC=composeApp/src      # your equivalent of :app
   grep -rn "^class .*RepositoryImpl" --include="*.kt" "$DATA_SRC"
   # No -n: line numbers survive sort -u, so the same import at two line numbers counts twice.
   grep -rh "^import com.maxrave.data" --include="*.kt" "$APP_SRC" | sort -u
   ```
   Pass condition for the first: no output — here it finds 2 real leaks (`LyricsRomanizerRepositoryImpl`, `ListenTogetherRepositoryImpl`). The second prints five imports here: three are glue (`Converters`, `loadAllModules`, `getHomeFolderPath`), and two are listentogether types (`ListenTogetherPlaybackBridge`, a playback bridge, and `ListenTogetherPrefs`, a prefs table) that need a reader's judgment call — what holds regardless is that neither leaked `RepositoryImpl` is imported by name.

2. **No service module points sideways, at another integration or at `:data`:**
   ```bash
   for m in core/service/*/; do echo "--- $m"; grep -n "projects\." "$m/build.gradle.kts"; done
   ```
   Pass condition: only `domain`, `common`, or the shared HTTP module — never each other or `data`, holds for all 8 modules here.

3. **The last two table rows, in the build files — `:app`'s api/implementation split, and the
   per-platform engine arrows into `:data`:**
   ```bash
   grep -n "api(projects.domain)\|implementation(projects.data)" composeApp/build.gradle.kts
   grep -n -B8 "projects\.media3\b\|projects\.mediaJvm\b" core/data/build.gradle.kts
   ```
   Pass condition: first shows both lines; second shows each engine under its own platform block only — `media3` in `androidMain`, `mediaJvm` in `jvmMain` — never `commonMain`.
