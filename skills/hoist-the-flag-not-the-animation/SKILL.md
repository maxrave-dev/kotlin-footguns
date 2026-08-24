---
name: hoist-the-flag-not-the-animation
description: Share the boolean that drives a fade, never the tween that runs it — each look derives its own curve, so one can go asymmetric (fast in, slow out) without changing how the other feels; covers why a symmetric linear fade over a bright backdrop makes container-backed controls read as the wrong colour, and why the shared animated value must stay published anyway. Use when buttons look lighter or darker than their neighbours only while something is fading, when one visual style needs a different timing from another, or before pulling an `animateFloatAsState` up into a shared state holder.
---

# Hoist the flag, not the animation

A shell that owns "are the overlay controls showing?" is right. A shell that owns "…and here is the
alpha, already tweened" has quietly made a design decision on behalf of every look that will ever
render.

```kotlin
// adapted — derived inside the look, from the shell's boolean
val controlsAlpha by animateFloatAsState(
    targetValue = if (state.showControls) 1f else 0f,
    animationSpec = tween(durationMillis = if (state.showControls) 180 else 500, easing = LinearEasing),
)
```

## Traps

**A symmetric linear fade has a long half-blended phase, and half-blended is a colour, not a
fade.** Over a bright backdrop, a control with a filled container composites the backdrop *through*
its own container for hundreds of milliseconds. Next to a row that never fades — a header, say — it
reads as a lighter button rather than an appearing one, and it is reported as a colour bug: "the top
bar buttons are darker than the ones below". Foreground-only elements (plain text, untinted icons)
do not show this, which is why one look can ship the shared curve happily and the next cannot.

**Fix it with an asymmetric curve, not a different colour.** Fading *in* fast (here 180 ms) makes the
blended frames effectively invisible; fading *out* keeps the original relaxed duration so nothing
about the dismissal changes. Both steady states are untouched, so nothing else in the look moves.

**One animation, duration chosen from the target — not two animations.** Write the direction into
the spec of the single `animateFloatAsState`, as above. Two `animateFloatAsState` calls swapped by an
`if` is a different thing: the one that takes over starts from *its* current value, not from what was
on screen, so the swap jumps.

**Keep publishing the shared tweened value.** The look that wanted the original curve still reads it;
a look that derives its own simply ignores it. Deleting the field because "the new style does not use
it" breaks the old style, and a doc comment claiming a field is unused is not evidence — grep for the
consumers (`screen-shell-content-split`).

**Publish the flag as a plain boolean, not as a flow or an animation state.** It has to be readable
by both looks in the same recomposition and comparable in an `if`; anything richer makes the second
look's derivation depend on the first look's mechanism.

**Do not "fix" it by editing the shared curve.** Changing 500 ms to 180 ms in the shell changes how
the original look feels, which nobody asked for, and the change is invisible in review because the
diff is one number in a file neither look owns. The asymmetric curve belongs to the look that needs
it.

**The same rule covers easing, delay and spring stiffness.** Anything that decides *how* a change is
perceived is presentation. What the shell may own is the state machine around the flag — the
auto-hide timer, the tap that toggles it, whether a scroll cancels it — because those must behave
identically no matter which look renders.

## Verifying it

1. The shell publishes both a boolean and its own tweened value, and only one look reads the tween:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "controlLayoutAlpha\|showControlLayout" . \
     | grep -v "^.*: \* "
   ```

   Expect the shell to compute and hand over both, the state holder to declare both, and the counts
   of consumers to differ — that asymmetry is the pattern, not a leak.

2. Every locally derived fade, so each one can be checked for a reason:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -A6 "animateFloatAsState(" . \
     | grep -B2 "durationMillis = if"
   ```

3. By eye, and this is the test the symmetric curve fails: put a filled-container button and a
   never-fading one side by side over a bright moving backdrop, then toggle the controls repeatedly
   while watching the *middle* of the transition rather than its ends. If the fading button passes
   through a lighter shade of its own container colour, the curve is exposing the composite.
