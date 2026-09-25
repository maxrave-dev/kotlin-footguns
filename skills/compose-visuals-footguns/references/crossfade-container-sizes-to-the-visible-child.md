---
name: crossfade-container-sizes-to-the-visible-child
description: A crossfade's container is a Box aligned to the top-start corner and sized to the largest child currently composed, so swapping a thin child for a taller one pins the thin one to the top mid-transition and drops it when the tall one leaves. Covers boxing both branches into one fixed frame with an explicit alignment, replacing rather than stacking two progress renderers whose track lengths differ, and why fading a whole interactive control makes it untouchable. Use when a bar visibly falls into place after a state change, when two stacked tracks are different lengths, or when a control stops responding for the length of a fade.
---

# What a crossfade measures

`Crossfade` composes both children while it runs. The container it puts them in is an ordinary
`Box` with the default alignment, which means: **size = the largest child on screen right now**,
**position = top-start**. Both defaults are invisible while the children are the same size — an
icon swapping for another icon — and both bite the moment they are not.

```kotlin
// adapted — the parent owns the frame; each branch fills it and centres inside it
Box(modifier = modifier.height(16.dp), contentAlignment = Alignment.Center) {
    Crossfade(targetState = loading, label = "trackState") { isLoading ->
        // Both branches are boxed to the full height and centred, so the crossfade's own Box
        // never changes size and neither child can be pinned to the top of it.
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            if (isLoading) {
                LinearProgressIndicator(
                    Modifier.fillMaxWidth().height(trackHeight).clip(RoundedCornerShape(8.dp)),
                    color = progressColor, trackColor = idleColor, strokeCap = StrokeCap.Round,
                )
            } else {
                Slider(…)                       // taller: it reserves room for its thumb
            }
        }
    }
}
```

## Traps

**The symptom is "the bar falls into place", and it happens on the way out, not the way in.** Fade
a 2dp indicator in over a taller slider: while both are composed the container is as tall as the
slider, and the indicator — top-aligned — sits at the top of that space. When the slider finally
leaves composition the container shrinks to the indicator's own height and the parent re-centres
it, so the bar drops a few pixels *after* the fade has finished. It reads as a layout glitch, which
is why nobody looks at the crossfade.

**Fix it with a frame, not with an alignment.** Passing `Alignment.Center` to the crossfade's own
`Box` only centres within a box that is still changing size, so the drop becomes a smaller drop.
Give the crossfade a parent with a fixed height and make *each branch* fill it — then the container
measures the same in every state and there is nothing to animate.

**Replace the two renderers; do not stack them.** The instinct for "show buffered progress under
the seek position" is a progress indicator behind a slider. They do not measure alike: a slider
reserves room for its thumb's travel at both ends while a bare indicator runs edge to edge, so with
identical horizontal padding the two tracks are visibly different lengths and out of line. Either
compensate with deliberately unequal padding (see `custom-thin-media-slider`, which does exactly
that and explains the numbers) or accept that only one of them is ever on screen and crossfade
between them — which is also what makes the sizing trap above appear.

**Never crossfade a control the user is trying to touch.** Both copies exist during the fade and
the outgoing one is still hit-testable, so a tap can land on the control that is disappearing;
worse, if the incoming branch is the interactive one, the control is unusable for the whole
duration. Fade only the layer that changes and leave the interactive one mounted.

**Same-sized children are the harmless case, and that is most of them.** A tree can hold a hundred
crossfades — icon-for-icon, label-for-label — and none of them needs a frame, because the container
never changes size and top-start is indistinguishable from anything else. That is exactly why the
handful that *do* swap different-sized children never get noticed: the pattern has a long track
record of working. Audit by size difference, not by count.

**A crossfade animates on the value, not on the content.** The default treats the state value
itself as the key, so two different-looking children produced from equal values do not cross-fade
at all — they swap on the next frame. If a branch is chosen by something other than the value you
passed (a captured flag, a size class), pass *that* as the state or the animation silently never
runs.

**Both branches are alive for the whole transition, side effects included.** The outgoing child is
still composed while it fades, so its `LaunchedEffect`s keep running, its requests keep going, and
its disposal is deferred until the fade ends. On cheap content this is invisible; on a branch that
starts work when it enters composition it means the work runs twice, overlapping. If a branch owns
something expensive, start that work above the crossfade and pass the result in.

**Boxing both branches is also what makes the colours land.** Once the branches share a frame they
can share the same width and corner radius, so the two states line up pixel for pixel. A track that
changes length or radius across the fade reads as two different controls swapping, not as one
control changing state — see `progress-indicator-as-scrubber` for the pair of renderers this
usually is.

## Verifying it

```bash
# 1. the container's alignment and measure policy, straight out of the artifact
AN=$(find ~/.gradle/caches -name 'animation-desktop-*.jar' | head -1)
javap -c -p -classpath "$AN" androidx.compose.animation.CrossfadeKt \
  | grep -E 'Alignment\$Companion.getTopStart|maybeCachedBoxMeasurePolicy' | head -4

# 2. every crossfade in the tree
grep -rn --include='*.kt' 'Crossfade(' . | wc -l

# 3. ...and how many box their branch to a frame
grep -rn --include='*.kt' -A2 'Crossfade(' . | grep -cE 'fillMaxSize\(\)|contentAlignment'
```

1. → observed: `Alignment$Companion.getTopStart` followed by `maybeCachedBoxMeasurePolicy`, twice —
   once in the transition overload's body and once in its own `Crossfade$lambda$7$0` content lambda.
   The plain overload has neither: it calls `updateTransition` and delegates to the transition
   overload, which is why no entry point escapes the policy. A box measure policy takes the maximum
   of its children's sizes; the alignment is where a smaller child lands inside that. Neither is
   configurable through `Crossfade` — the only lever you have is the children.
2. → observed: on the order of a hundred sites.
3. → observed: a small handful. The gap is not a bug list: go through it looking only for branches
   whose *intrinsic heights differ*, and frame those. Everything swapping equal-sized content can
   stay as it is.

Then, by hand: put the control into the state whose child is **shorter**, and watch the moment the
transition ends rather than the moment it starts. A settle, a hop, or a few pixels of vertical
movement after the fade completes is this bug; a clean fade with nothing moving afterwards is the
frame doing its job. Do it once at a small window size too — a frame that is only tall enough in
one layout hides the same problem.
