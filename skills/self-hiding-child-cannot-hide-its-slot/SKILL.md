---
name: self-hiding-child-cannot-hide-its-slot
description: A component that renders nothing when its feature is unavailable cannot remove the container someone else wrapped it in — gate the slot on the same availability predicate, publish that predicate beside the component, and branch the slot's clickable and non-clickable forms properly. Use when an empty cell, gap or stray divider appears where an optional control should be, when a group's rounded end caps land on the wrong item, or when a wrapper swallows the taps meant for the control inside it.
---

# A self-hiding child cannot hide its slot

Optional controls commonly hide themselves: no platform support, no permission, nothing to connect
to — render nothing. That is correct and it is not enough. A caller that gave the control a
container, a weight or a divider still draws all three around an empty box.

The component's own contract has to say so, in the same file that declares it:

```kotlin
// adapted
/**
 * Whether [OptionalControl] would render anything. Layouts that give it a container of its own
 * must hide the container too when this is false — the control hides itself, but it cannot hide
 * a wrapper it does not own.
 */
expect fun isOptionalControlAvailable(): Boolean
```

## Traps

**Publish the predicate next to the component, not at the call sites.** Two call sites re-deriving
"is this available" from platform checks will disagree eventually — and the one that disagrees is the
one drawing the empty box. One exported predicate, backed by the same platform code the component
uses, is the whole fix.

**The gate is needed exactly when the caller adds a container, and not otherwise.** In this tree the
same control appears twice: inside a segmented group it is wrapped in `if (available)`, and in a
plain row it is called bare, because there the control's own emptiness is invisible. Both are right.
Auditing for "every call site must be gated" would produce a wrong finding.

**Removing a slot from a segmented group changes its neighbours' shapes.** End caps, corner radii and
dividers are assigned by position. Drop a middle slot and the arithmetic still works; drop the first
or last and the cap has to move, or the group ends up with two square outer corners. Derive the
shapes from the built list rather than hardcoding them per index.

**A slot with no click of its own needs a real branch, not a no-op lambda.** The clickable and
non-clickable forms of a container are different composables with different semantics. Passing
`onClick = {}` keeps the ripple, keeps the accessibility click action and keeps consuming the tap —
so the control inside, which owns its own click, never receives it. Branch on `onClick != null` and
emit the plain container in the else.

**Declare the predicate and the component as one platform pair, in one file.** A target that stubs
the control to draw nothing must stub the predicate to `false` in the same edit; split across files
they drift, and the drift is invisible until someone builds that target. Declaring both together
also puts the contract — "callers with a container must gate it" — where both implementers read it.

**Keep the predicate cheap and pure.** It is called during composition, on every recomposition, from
inside a layout loop. A constant-returning platform function is fine; anything doing I/O, reading a
store or touching a service must be hoisted into state and passed down, or the group stutters.

**Decide whether the slot disappears or reserves space, and say which.** In a weighted row a removed
slot redistributes width to its siblings, which visibly resizes every remaining control. That is
usually right for a permanently unavailable feature and wrong for a transiently unavailable one,
where the group would twitch each time. Reserve for transient, remove for permanent.

**"It renders nothing, so it costs nothing" is false for anything with a weight or a background.** An
empty container with `weight(1f)` still claims its share of the row and still paints its container
colour; that is precisely the artefact this rule exists to prevent.

## Verifying it

1. The availability predicate exists and is declared beside the component it describes:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "expect fun is[A-Za-z]*Available(): Boolean" .
   ```

2. Every call site of that component, each shown with the gate above it if there is one. Read the
   ungated ones and confirm the caller adds no container:

   ```bash
   F=$(grep -rl --include='*.kt' --exclude-dir=build "expect fun is[A-Za-z]*Available(): Boolean" .)
   C=$(grep -oE "^expect fun [A-Za-z]+" "$F" | awk '{print $3}' | head -1)
   grep -rn --include='*.kt' --exclude-dir=build -B8 "^ *$C(" . | grep -E "$C\(|Available\(\)"
   ```

3. The slot really branches instead of taking a no-op click — expect two container emissions in the
   helper, one with a click parameter and one without:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build -A6 "onClick: (() -> Unit)?" .
   ```

4. On a device or target where the feature is unavailable: open the screen and count the cells in the
   group. An extra one, a wider gap, or an outer corner that is square instead of rounded all mean
   the slot outlived the control.
