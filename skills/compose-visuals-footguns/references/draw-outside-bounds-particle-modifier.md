---
name: draw-outside-bounds-particle-modifier
description: A celebration burst drawn by a plain draw modifier that paints past its host's own bounds — draw modifiers are unclipped by default, so the modifier must sit before every .clip(...) in the chain, and any clipping ancestor still trims whatever leaves its edge. Covers scaling origin and reach off the host's measured size so one effect reads the same at 28dp and at 48dp, keeping the per-frame lambda cheap, and why pure drawing beats an animation library here. Use when a burst renders cut to the button's outline, when it vanishes inside a rounded card or list row, or before adding a vector-animation dependency to draw one.
---

# Drawing outside your own bounds

Sparks shooting up out of a 48dp button need no overlay, no popup, no extra layout node — a
`drawWithContent` modifier draws the content, then keeps drawing. Nothing stops it at the edge.

```kotlin
// adapted — one modifier, applied BEFORE any clip; the state holder decides when to draw
@Composable
fun Modifier.celebrationBurst(state: BurstState): Modifier {
    val starPath = remember { buildUnitStarPath() }          // built once, not per frame
    return this.drawWithContent {
        drawContent()
        if (state.bursts.isEmpty()) return@drawWithContent   // cheapest possible resting cost
        // Launch point sits above the host's centre; reach scales with the host, so the same
        // effect reads correctly on a 28dp row control and a 48dp detail control.
        val origin = Offset(size.width / 2f, size.height * 0.3f)
        val reach = size.height * 2.2f
        state.bursts.forEach { burst ->
            val p = burst.progress.value
            val flight = 1f - (1f - p) * (1f - p)          // decelerating outward
            val fall = p * p * reach * 0.35f               // quadratic gravity
            burst.sparks.forEach { spark ->                // angle/speed/spin fixed at creation
                val d = spark.speed * flight * reach
                withTransform({
                    translate(origin.x + cos(spark.angleRad) * d,
                              origin.y + sin(spark.angleRad) * d + fall)
                    rotate(spark.spin * p * 360f, pivot = Offset.Zero)
                }) { drawSpark(spark, size.height * spark.relativeSize, alpha = 1f - p) }
            }
        }
    }
}
```

## Traps

**Modifier order decides whether the effect exists.** `Modifier.celebrationBurst(state).clip(shape)`
draws; `Modifier.clip(shape).celebrationBurst(state)` does not. A modifier chain nests outer to
inner, so a clip placed earlier wraps everything after it — including your draw. The symptom is not
a crash or a warning: you get a burst neatly trimmed to the host's own outline, which reads as
"the animation is broken" rather than "the modifier is in the wrong place".

**A clipping ancestor still wins, and you cannot fix that from inside.** Getting your own chain
right buys nothing if the row, card or capsule above you clips. Two ways out, both structural:
move the modifier onto a node outside that clip, or check whether the component clips *internally*
rather than through your chain — a Material button clips on its own surface, several layers below
the modifier you passed in, so a burst fired from that outer modifier is never trimmed by it.

**Scale every distance off `size`, never off dp constants.** Origin at `height * 0.3f`, travel at
`height * 2.2f`, spark size at `height * 0.12f..0.22f`. Hard-coded dp makes the effect a firework
on a small control and a twitch on a large one, and you will not notice because you only ever look
at one of them. The live sizes here differ by half again to nearly double, and the same numbers
serve all of them — measure that spread across the actual call sites, not off the host's default
size parameter, which every caller may well be overriding.

**The draw lambda runs every frame of every redraw, for every host it is attached to.** Build the
`Path` in a `remember` outside it, and return early when nothing is live — otherwise a screen with
a dozen list controls pays for a dozen empty particle loops on every scroll frame. Everything
inside the lambda should be arithmetic on values the lambda already has.

**Randomness belongs to spark creation, not to drawing.** Each spark's angle, speed, size, spin and
colour are drawn once when the burst is constructed and stored on it. Calling `Random` inside the
draw lambda re-rolls every frame and the burst becomes static noise, which looks like a rendering
fault rather than a shuffle.

**Read `size` from the draw scope, not from an `onSizeChanged` you cached.** A cached size is one
frame stale during any resize or shared-element transition, and the effect visibly detaches from
its host. The draw scope already has the current one.

**Drawing outside your bounds does not enlarge them — and must not.** Nothing about this reserves
space, changes measurement, or moves a neighbour, which is exactly why it can be dropped onto an
existing control without redesigning the row. The cost is that a sibling drawn *later* paints over
your sparks: draw order follows composition order, so a burst from a control early in a `Row` goes
under the ones after it. If that matters, raise the host's `zIndex` rather than reaching for a
popup — a popup brings its own window, its own dismissal rules and its own insets.

**A per-frame `Animatable` per burst is the right granularity.** One shared clock forces every live
burst to the same phase, so a second tap either restarts the first or renders on top of it in
lockstep. Each burst owning its own progress is what makes overlapping taps look like two events.

**Do not reach for an animation library for this.** Everything above is `Path`, `drawRect`,
`withTransform` and one `Animatable` per burst — no asset pipeline, no per-platform renderer, and
identical output on every target the UI toolkit runs on. A vector-animation dependency buys a
designer-authored file and costs you a runtime that behaves differently per platform, plus an asset
whose colours cannot follow the theme.

**Anything the modifier pushes into the holder is a write during composition.** A parameter the
draw lambda needs but the holder owns — a colour list, a size multiplier — is typically assigned
at the top of the modifier function, which runs in the composition phase. That is only safe while
the field is a plain `var` read exclusively at draw time: make it observable state and you have a
snapshot write during composition, which is a recomposition loop waiting to happen. Keep such
fields ordinary, and keep the list of live effects the only observable thing on the holder.

**The modifier draws; something else decides when.** Keep the live-effect list in a hoisted holder
and give the modifier only a read of it — see `event-not-state-edge-for-one-shot-effects` for why
the trigger must come from the gesture, and what happens when it comes from the flag instead.

## Verifying it

The first two read the resolved toolkit artifact out of the dependency cache — no build needed.
They establish that nothing is clipped unless something asks for it:

```bash
UI=$(find ~/.gradle/caches -name 'ui-desktop-*.jar' | head -1)

# 1. clipToBounds() is nothing but a layer with clip switched ON
javap -c -p -classpath "$UI" androidx.compose.ui.draw.ClipKt | sed -n '/clipToBounds/,/areturn/p'

# 2. ...and the layer's own clip parameter defaults to OFF (mask bit 4096 -> iconst_0)
javap -c -p -classpath "$UI" androidx.compose.ui.graphics.GraphicsLayerModifierKt \
  | grep -A4 'sipush        4096' | head -5

# 3. no draw modifier in this tree sits behind a clip in its own chain
grep -rn --include='*.kt' -A2 '\.clip(' . | grep -E 'draw(Behind|WithContent|WithCache)'

# 4. every custom draw modifier, so you can check each one's chain position by eye
grep -rn --include='*.kt' 'drawWithContent\b' .
```

1. → observed: the body is a single `graphicsLayer` call whose boolean argument is `iconst_1`.
   Clipping is opt-in, delivered by a layer; a draw modifier on its own never installs one.
2. → observed: `sipush 4096 / iand / ifeq / iconst_0 / istore 14` — the default is `false`.
3. → observed: **no output**. Any hit is a draw modifier that will be trimmed by the clip above it
   in the same chain, which is the exact defect this skill is about.
4. → observed: a handful of definitions and their `Modifier.drawWithContent {` call sites. For each
   one that is meant to paint past its host, confirm no `.clip(` precedes it in that chain and that
   no ancestor clips.

Then, by hand: fire the effect on the smallest and the largest host you ship. The spark size, the
travel distance and the arc must look like the same effect at both, and sparks must cross the
host's outline in both.
