---
name: slide-transition-defaults-to-half-a-height
description: A vertical slide transition defaults to HALF the element's height, so it appears already halfway through its own movement and the first part is missing — which reads as a pop, not a slide. Covers passing the full height, the sign that decides which edge it comes from, pairing a shorter fade with a longer slide so the element is opaque before it settles, making exit quicker than enter, and publishing the pair as shared values so every screen matches. Use when a bar or panel seems to snap into place instead of sliding, when enter and exit feel mismatched, or when the same control animates differently on two screens.
---

# Half a height is the default, and it looks like a bug

`slideInVertically()` with no offset lambda does not slide in from off-screen. It slides in from
half its own height — so the element is already halfway to its resting place on the first frame,
and the eye reads the missing half as a jump. The same default sits on the exit.

```kotlin
// adapted — one pair, imported by every screen that has this control
val BarEnter: EnterTransition =
    fadeIn(tween(durationMillis = 180, easing = FastOutSlowInEasing)) +
        slideInVertically(tween(durationMillis = 260, easing = FastOutSlowInEasing)) { -it }

/** Leaving is quicker than arriving: a control being dismissed should not hold the eye. */
val BarExit: ExitTransition =
    fadeOut(tween(durationMillis = 140, easing = FastOutSlowInEasing)) +
        slideOutVertically(tween(durationMillis = 200, easing = FastOutSlowInEasing)) { -it }
```

## Traps

**The default is `-it / 2`, and it is easy to read as "off-screen".** The lambda receives the
element's full height; the default halves it and negates it. Half of a 56dp bar is 28dp of travel —
enough to be an animation, not enough to be a slide, and short enough that the easing curve never
gets to do anything. Passing `{ -it }` is the whole fix and it changes one character in most call
sites.

**The default already carries the sign, so "fixing" it by passing `{ it }` reverses the
direction.** Negative means "starts above its slot". A bare `slideInVertically()` therefore comes
from above; write `{ it }` and it now comes from below — a real change of design, made by accident,
while chasing a travel-distance problem. Decide the edge deliberately: `{ -it }` for something
descending from the top of the screen, `{ it }` for something rising from the bottom.

**Slide does not reserve space, and that is why you chose it.** A slide is a translation: the
element occupies its final slot for the entire animation, so nothing around it moves. The
transition family's *own* default enter is a fade plus an expand — a size animation that grows the
element from nothing and reflows every neighbour as it goes. Writing `fadeIn() + slideInVertically()`
does not add a slide on top of the default; it *replaces* the expand. That is normally what you
want, but it means the layout behaviour changes too, and a caller who was relying on the reflow
will notice.

**Give the fade a shorter duration than the slide.** With equal durations the element is still
translucent as it arrives and finishes fading after it has stopped — it looks like it settles
twice. Opaque before it stops moving (here 180ms against 260ms) reads as one motion. The ratio
matters more than the absolute numbers; roughly two-thirds is a good starting point.

**Make the exit quicker than the enter.** Arriving deserves the user's attention; leaving does not,
and a slow exit blocks whatever the user just asked for. Cutting both durations by a quarter or so
(140/200 against 180/260) is enough — a symmetric pair feels sluggish on dismissal even though
nothing is technically wrong with it.

**Publish the pair as shared values, or the same control animates differently per screen.** These
transitions are written inline, in a screen file, by whoever added the control there — and the
third screen to get it copies the second, which had already drifted. Two top-level `val`s in a
shared file cost nothing, make a change land everywhere at once, and turn "does this match?" into a
grep. They are plain values, not composables, so there is no state to hoist.

**The bare form is not an error, so a linter will not find these for you.** Every bare call
compiles, runs, and produces a plausible-looking animation. The only way to find them is to grep
for the call and look at whether an offset lambda follows — in every spelling the call has, since a
trailing lambda with no parentheses sits where a parenthesised pattern cannot see it. That is why
the counts below are worth running on any tree several people have added transitions to.

**Fix the transition where it belongs, not by moving the element.** Padding or an offset added to
"make the slide look longer" changes the resting layout too, and will be spotted later as a spacing
bug by someone who cannot see why it is there.

## Verifying it

```bash
# 1. the default offset, straight out of the artifact: negate, then divide by two
AN=$(find ~/.gradle/caches -name 'animation-desktop-*.jar' | head -1)
javap -p -c -classpath "$AN" androidx.compose.animation.EnterExitTransitionKt \
  | sed -n '/int slideInVertically\$lambda\$0/,/ireturn/p'

# 2. what the visibility wrapper does when you pass no transition at all
javap -c -p -classpath "$AN" androidx.compose.animation.AnimatedVisibilityKt \
  | sed -n '/AnimatedVisibility(boolean, androidx.compose.ui.Modifier/,/RowScope/p' \
  | grep -oE '(fadeIn|expandIn|shrinkOut|fadeOut)\$default'

# 3. vertical slides left on the default, versus those that pass an offset — in all THREE
#    spellings: a trailing lambda written without parentheses matches neither of the first two, so a
#    two-pattern audit drops those call sites without saying so. Print the third rather than count it
grep -rn --include='*.kt' -E 'slide(In|Out)Vertically\(\)' . | wc -l
grep -rn --include='*.kt' -E 'slide(In|Out)Vertically\(.*\) *\{' . | wc -l
grep -rn --include='*.kt' -E 'slide(In|Out)Vertically *\{' .

# 4. the total those three have to account for: every occurrence, less the imports
grep -rn --include='*.kt' -E 'slide(In|Out)Vertically' . | wc -l
grep -rn --include='*.kt' -E '^import .*slide(In|Out)Vertically' . | wc -l
```

1. → observed: `iload_0 / ineg / iconst_2 / idiv / ireturn` — exactly `-it / 2`. The outward
   version has the identical body, so an element that entered from half a height above also exits
   to half a height above.
2. → observed: `fadeIn$default`, `expandIn$default`, `shrinkOut$default`, `fadeOut$default` — the
   defaults are a fade **plus a size animation**, which is the reflow described above.
3. → observed: many bare calls against a couple that pass `{ -it }`. Every bare one is an element
   entering from half its own height; each is a one-character fix, and the ones worth doing first
   are the tall elements, where half a height is the largest absolute error. The third pattern is
   the one to read line by line: it is where a call passing the height **unnegated** was hiding —
   the sign reversal of the second trap, live, and invisible to the two counts above it.
4. → observed: two numbers whose difference is the call-site total. The three patterns above must
   add up to exactly that; if they fall short, there is a fourth spelling and it is hiding call
   sites the same way.

Then, by hand: record the control appearing and step through the recording. The first visible frame
must be the element fully outside its slot, not straddling it. Watch the opacity as well — if the
element is still translucent once it has stopped moving, the fade is longer than the slide.
