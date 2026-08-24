---
name: dont-pre-animate-a-self-animating-property
description: Pass the raw target to a component that animates a property itself — an externally tweened value is a stream of new targets, and such components typically ignore new targets while their own animation is still running, which freezes the effect part-way. Covers how to recognise a self-animating property, why a hard flip between endpoints is the fix, and how to prove ownership from the compiled artifact. Use when an animated component sticks near its starting value, when a transition plays once and never again, or before wrapping a component's input in `animateFloatAsState`.
---

# Do not pre-animate what the component already animates

Some components take a property that they animate internally: they hold their own directional specs
and drive the value themselves. The correct input is the destination. Handing them a smoothed path to
that destination is not "smoother" — it is a new instruction every frame.

```kotlin
// as written — a raw 0f/1f flip, deliberately not animateFloatAsState
val targetAmplitude = if (isPlaying && !isInteracting) 1f else 0f
```

## Traps

**The component's update guard drops targets that arrive mid-animation, so the first one wins.** An
external tween delivers roughly sixty slightly different values per second. The first frame starts an
internal animation towards something very close to the old value — 0.97 rather than 0 — and every
smaller target after it is swallowed while that animation is still in flight. The visible result is a
property frozen just short of its start: here, a wave stuck near full ripple after the audio paused.
Nothing errors, and it reproduces on device far more readily than in a preview.

**A hard flip between the two endpoints is the fix, and it is one recomposition.** The new value
recomposes the caller once, the fresh lambda invalidates the node's draw cache, and the component's
own directional spec renders the change with the timing its designers chose. That timing is usually
what you were trying to build by hand anyway.

**Recognise the shape before you wrap anything.** Two tells: the parameter's documentation says the
value *animates* rather than *is*, and the component exposes no `animationSpec` for it. If you cannot
give it a spec, it owns one — so an external animation is competing, not cooperating.

**Shortening your own tween does not help.** It changes when the first target lands, not whether the
rest are dropped. Neither does `snapTo` on an `Animatable` you own; the point is to stop owning the
value, not to reach the end sooner.

**Pass it as the lambda the component asked for.** These parameters are commonly `() -> Float` so the
component can read them without recomposing. Reading the value into a local and closing over it is
still fine — a new lambda per recomposition is what invalidates the draw cache — but hoisting the
lambda into a `remember` with the wrong keys reintroduces the stale-target problem from the other
side.

**Compose the endpoints, do not smooth them.** Combining conditions (`playing && !scrubbing`) into a
single boolean, then mapping that boolean to two constants, keeps the input a step function. Any
arithmetic that produces intermediate values — a fraction, a fade multiplier, an eased curve — puts
you back in the stream-of-targets case.

**Gate the value on the lambda's own argument, not on your copy of it.** These parameters are
commonly handed the value the component is *currently drawing* — so a decoration that must vanish at
zero should read that argument (`{ p -> if (p > 0f) target else 0f }`), not the fraction you last
computed. During a scrub the two differ, and reading your own copy re-introduces the fight the
component's internal animation was avoiding.

**The same trap lives in every component with an internal `Animatable` plus a guard**: progress
indicators, expanding surfaces, morphing container shapes, indeterminate loaders. When a component's
behaviour appears to "stick" after the first change, suspect ownership before suspecting your state.

## Verifying it

1. Enumerate the components in your design-system artifact that own their animation. Read-only, no
   build; every hit is a component whose animated parameters must be passed raw:

   ```bash
   JAR=$(find ~/.gradle/caches/modules-2 -name '*material3*.jar' ! -name '*sources*' | sort -V | tail -1)
   echo "$JAR"; D=$(mktemp -d); unzip -oq "$JAR" -d "$D"
   for C in "$D"/androidx/compose/material3/*Kt.class; do B=$(basename "$C" .class)
     javap -p -cp "$D" "androidx.compose.material3.$B" 2>/dev/null \
       | grep "private static final androidx.compose.animation.core.AnimationSpec" | sed "s|^|$B: |"
   done
   ```

   A pair of *directional* specs (one increasing, one decreasing) is the strongest signal: the
   component is choosing a spec per direction, which it can only do if it owns the transition.
   `sort -V` picks the newest *cached* artifact, not necessarily the one your build resolves — read
   the echoed path.

2. List every binding of an animated-looking parameter together with the component receiving it —
   step 1 decides which of them matter:

   ```bash
   grep -rnE --include='*.kt' --exclude-dir=build -B1 "^ +(amplitude|progress) = " .
   ```

   The same parameter name is safe on one component and not on another: a plain progress indicator
   does not appear in step 1's census, so feeding *it* an `animateFloatAsState` value is the normal
   way to smooth a jumpy position — and that binding will sit in this listing looking identical to
   the dangerous one.

3. By hand: trigger the transition, then trigger it again immediately, then leave it alone for a few
   seconds and trigger it once more. A pre-animated input typically works exactly once — the isolated
   third attempt is the one that exposes it.
