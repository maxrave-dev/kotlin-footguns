---
name: scoped-composable-shadows-the-top-level-one
description: Inside a layout scope, a scope-extension composable of the same name wins over the top-level one — silently, since both compile — so a call written for the plain version gets the scoped version's defaults and layout behaviour; covers fully qualifying to force the top-level one, `this@Scope.` to force the scoped one, and why outer scopes still apply from inside a nested layout. Use when an appear/disappear animation expands or collapses its parent instead of fading in place, when a composable behaves differently after being moved into a column or row, or when a call resolves to an overload you did not choose.
---

# The scoped overload shadows the top-level one

Several toolkit composables ship as a top-level function *and* as extensions on the layout scopes.
The extensions differ in their default transitions and in how the element participates in the parent
layout. Kotlin prefers an extension on an implicit receiver over a plain top-level function, so
inside a column or a row the scoped one wins by default — with no warning, because the call compiles.

```kotlin
// adapted — forcing the top-level overload; the visibility condition is shortened
androidx.compose.animation.AnimatedVisibility(
    visible = isVideo && watchVideo,
    modifier = Modifier.align(Alignment.Center),
) { … }
```

## Traps

**Outer scopes are still implicit receivers inside a nested layout.** The shadowed call above sits in
a `Box` — but that box is inside a column, and the column's scope is still in scope, so the column
extension is what an unqualified call resolves to. Being "inside a Box" is not protection; there is
no box-scoped overload to take precedence.

**The symptom is a layout behaviour, not an error.** The scoped variants default to expanding and
shrinking along the parent's axis, so the element pushes its siblings while it appears instead of
fading in place. Read as an animation bug ("the column jumps when the video starts"), it sends people
looking at the transition parameters rather than at which function ran.

**Fully qualify to force the top-level one; `this@Scope.` to force a scoped one.** Both directions
occur in the same tree, a few hundred lines apart: one call is written
`androidx.compose.animation.AnimatedVisibility(…)` and another `this@Column.AnimatedVisibility(…)`,
the second because the nearest receiver was something else and the column's behaviour was wanted.
Import aliasing is the third option and the worst — it hides which overload is in play at the call
site, which is the exact information the reader needs.

**Passing the transitions explicitly fixes the animation but not the layout.** Supplying
`enter = fadeIn(), exit = fadeOut()` removes the visible expand, so the bug looks solved; the element
is still going through the scoped overload and still measured by it. Fix the resolution, not the
symptom.

**Expect to hit it again in every parallel implementation.** When a screen has two interchangeable
looks (`screen-shell-content-split`), each look meets this independently — the workaround is in both
here — and so does every new one. Add a line of comment at the call site saying *why* it is
qualified, or the next reader will "simplify" it back.

**Wrapping working code in a new layout silently changes which overload runs.** The call is not
edited; a `Column {` appears above it, and from that commit on the element expands its siblings
instead of fading. The diff shows an added container and nothing else, so review has no reason to
look at the untouched line — which is the strongest argument for qualifying these calls up front
rather than when they misbehave.

**A named-argument call can shift which overload is selected.** Some scoped variants take the visible
flag positionally after the receiver while other overloads take a transition state; changing a call
from positional to named, or swapping `Boolean` for a mutable transition state, can quietly move you
to a different overload of the same name. Check the resolved signature after any such edit.

## Verifying it

1. Every deliberately fully-qualified call — each one is a place where the scoped overload was in the
   way, and each should carry a reason:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -B2 "androidx\.compose\.[a-z.]*\.[A-Z][A-Za-z]*(" .
   ```

2. Every deliberate scope selection, which is the same problem from the other side:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "this@[A-Za-z]*\.[A-Z][A-Za-z]*(" .
   ```

3. The overload set you are resolving against, read from the cached artifact rather than the docs.
   Extension overloads compile to static functions whose *first parameter* is the scope, which is
   what makes them beat a top-level function:

   ```bash
   J=$(find ~/.gradle/caches/modules-2 -path '*animation*' -name '*.jar' ! -name '*sources*' \
        | grep -vE 'core|graphics' | sort -V | tail -1)
   echo "$J"; D=$(mktemp -d); unzip -oq "$J" -d "$D"
   javap -p -cp "$D" androidx.compose.animation.AnimatedVisibilityKt | grep " AnimatedVisibility("
   ```

   Expect several signatures differing only in a leading `RowScope` / `ColumnScope` parameter.

4. By eye: put the element inside a column, remove the qualification, and watch its siblings while it
   appears. If they move, the scoped overload is running.
