---
name: transitive-version-pinning
description: Handling a transitive dependency whose strict version constraint overrides the version you chose, dragging a shared lower-level library up or down for the whole build — how to find who pinned what, when to force a version back versus align everything with the pin, and how to document a pin so nobody upgrades it back into the breakage. Reach for it when adding one unrelated library produces a missing-method failure at runtime, inside a rendering pass, in a component you did not touch.
---

# A transitive pin beats your version choice

You declared a version. A library you added declares a **strict** constraint on some shared
lower-level artifact — a rendering backend, a serialization core, a native binding — and strict
wins: it overrides a plain version, and it overrides the platform/BOM you thought was in charge.
Nothing warns you. The build compiles, because every module still compiles against whatever headers
it was built with.

The failure arrives later and somewhere else.

## The shape of the failure

A concrete run of it: adding a glass-effect UI library pinned the rendering backend strictly several
minor versions up. The UI runtime, a vector-animation renderer and the image loader had all been
built against the older one, and the newer backend had **removed** a matrix helper method. Result: a
missing-method failure at runtime, thrown inside the animation renderer's draw pass — a component
with no relationship to the library that had been added, and only when an animation actually
rendered.

Note every property that made this hard:

- **Not a build failure.** Compilation and packaging were green.
- **Not near the cause.** The stack trace names the victim, never the pinner.
- **Not deterministic on startup.** It fires when that draw path first runs.
- **Not visible on the platform that mattered.** At the time, the library that forced the bump was
  never rendered on the affected target at all, so the cost of the constraint was pure.

Three versions of the shared backend appear below, and keeping them apart is the whole point:
`A.B.C` is the older one the app had been built against, `A.D.E` is the newer one the strict
constraint demanded, and `A.D.F` is the one a later alignment settled on — newer than `A.B.C`, but
not the version the constraint had asked for.

## Traps

**Find out who pinned it before doing anything else.** Guessing costs build cycles; the resolution
report answers in one command and names the constraint *and* the module that declared it:

```bash
./gradlew :<module>:dependencyInsight \
  --configuration <runtimeClasspathConfiguration> \
  --dependency <group>:<artifact>
```

Read the selection-reason lines it prints for the artifact. A strict constraint shows up as a
constraint from a specific module rather than as a plain requested version, and that module is your
culprit — check your build's own report wording rather than grepping for a fixed heading. Run it per
configuration — desktop, Android and test configurations resolve independently, and a pin can be
present in one and absent in another, which is exactly why "it works on the other platform" is not
evidence of anything.

**Force back when the pinning library is not exercised on that target — and say so in the comment.**
Justify by scope, not by preference: if the feature that wanted the newer version never renders on
this platform, pinning back costs nothing and that fact is the whole argument. When the shared
artifact is not a direct dependency (so a version-catalog entry cannot reach it), rewrite it during
resolution:

```kotlin
// adapted — <glass-lib> pins <render-backend> `strictly A.D.E`, dragging the whole desktop tree
// up. The UI runtime, the animation renderer and the image loader all compile against A.B.C, and
// A.D.E removed Matrix33.makeTranslate(float, float) — the animation renderer dies with a
// missing-method failure. Desktop did not render the glass effect at the time, so pin the backend
// back to what the UI runtime actually ships with.
configurations.configureEach {
    resolutionStrategy.eachDependency {
        if (requested.group == "<render-backend-group>") useVersion("A.B.C")
    }
}
```

For the simpler case — two libraries depending on different builds of the *same* artifact — a
project-wide `force` is enough:

```kotlin
// adapted
subprojects {
    configurations.all {
        resolutionStrategy { force("<group>:<artifact>:<version>") }
    }
}
```

**Align instead of forcing when your own UI runtime genuinely needs the newer version.** Forcing
back is a holding action; it becomes wrong the moment you upgrade the runtime for an unrelated
reason. That is exactly what happened here — the effect later did reach the target that had been
assumed never to render it, and the force had to be replaced by an alignment. Aligning means choosing
the runtime build whose transitive backend version every other library can also live with — which in
practice can mean taking a pre-release or snapshot build of one of the *other* libraries, because it
is the first one compiled against the new backend. Note where that landed: the force-back had pinned
`A.B.C`, while the alignment settled on `A.D.F`, a third version that satisfies everyone without
being the one the strict constraint demanded. Then delete the force, or it will silently drag you
back down.

**The pin runs in both directions.** Once the runtime version is fixed, a library compiled against a
*different* signature of the same backend fails the same way — a call inside its effect path throws
a missing-method failure. If that effect is optional, guard the call site by platform and let that
target lose the effect; if it is not, you are back to alignment. Either way the guard needs a
comment saying which version pair it is protecting, or it looks like dead code.

**The shrinker sees this before your users do.** An unresolvable method reference makes a bytecode
shrinker abort the build with an unresolved-reference error. That abort is a *free early warning* for
exactly this class of mismatch — treat it as a version-alignment signal first. Suppressing it is
correct only when the code path is genuinely unreachable on that target, which is the same judgement
call as forcing back, and it deserves the same written reason.

**Document why the version is pinned, on the line with the pin, including what the next version
breaks.** A commit message does not survive contact with a dependency-update bot; a comment in the
version catalog does. Say the version, the transitive consequence, and the failure the next version
causes:

```toml
# adapted
ui-runtime = "1.12.0-alpha01"  # alpha01 → <render-backend> A.D.F (still has Matrix33.makeTranslate);
                               # alpha02 bumps to A.D.E which removed it → animation renderer crashes
anim-renderer = "2.2.2-ui-1.12-SNAPSHOT"  # snapshot built against A.D.F; the stable build needs the
                                          # old A.B.C and crashes against the runtime pinned above
```

Without those two comments, the pair reads as "someone was lazy and left a snapshot in", and the
first tidy-up upgrade reintroduces the crash.

## Verifying it

After any change to a pin or an alignment:

1. Re-run `dependencyInsight` for the shared artifact in **every configuration you ship** — the
   desktop runtime classpath and the mobile one resolve separately.
2. Build a **release/shrunk** artifact, not a development run: the shrinker's unresolved-reference
   pass is one of the few checks that catches a signature mismatch statically.
3. Exercise the drawing paths by hand — an animation, a blurred or layered surface, an image load.
   These are the ones that only fail when they paint, so no automated smoke test that skips
   rendering will tell you anything.
