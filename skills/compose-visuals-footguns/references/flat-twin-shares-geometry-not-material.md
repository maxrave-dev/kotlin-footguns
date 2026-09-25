---
name: flat-twin-shares-geometry-not-material
description: When a user setting picks between two renderings of the same control — an expensive decorative one and a plain twin — every geometry decision has to be mirrored between them (item width, bar height, indicator size, inset, and the rule that computes the width budget) so toggling changes the material and never the layout; the compiler cannot pair two constants declared in two files. Also covers recolouring an icon that arrives as a slot lambda, which only CompositionLocalProvider(LocalContentColor) can reach. Use when switching a visual setting also moves things, when the plain variant's indicator sits off its item, or when a slot-lambda icon ignores every tint you pass.
---

# The flat twin shares the geometry, not the material

Two renderings of one control — one drawing an expensive decorative surface, one drawing flat theme
surfaces — are a single form in two materials. The setting is allowed to change what the pixels are
made of. It is not allowed to change where anything is.

```kotlin
// adapted — the flat twin's constants, named to say what they mirror
// Mirrors the decorative bar's geometry (TabWidth / BarHeight / BlobHeight / BarInset) so the two
// bars are one form in two materials.
private val FlatTabWidth = 96.dp
private val FlatBarHeight = 64.dp
private val FlatIndicatorHeight = 56.dp
private val CapsuleInset = 6.dp
```

Five things are mirrored here, and the fifth is the one people forget — not just the four numbers
but the **rule that consumes them**: both bars size a item as
`((available - inset * 2) / count).coerceAtMost(cap)`. Copy the constants without the rule and the
twins agree until the tab count changes, then diverge exactly where it is hardest to notice.

## Traps

**Two constants in two files cannot drift *loudly*.** `FlatTabWidth = 96.dp` and `TabWidth = 96.dp`
have no relationship the compiler can check; renaming one, or nudging it by 2 dp during a visual
tweak, produces two bars that are subtly different heights and nothing at all to read. Keep the
comment that names the twin on **both** declaration blocks — it is the only link that exists — and
when the numbers genuinely want to be shared, hoist them rather than pairing them by eye.

**Splits are geometry too.** If one item renders outside the container in one twin (a search button
beside the capsule rather than inside it), it must render outside in the other, and both must filter
the list the same way. Get this wrong and the twins have different item counts, so the width budget
divides differently and every position shifts — see `nav-tab-registration-drift` for what a list
maintained in more than one place does next.

**An icon handed in as `@Composable () -> Unit` cannot be tinted from the outside.** The slot is
opaque: there is no colour parameter to reach, and wrapping it in something that draws does not
recolour it. The only handle is the ambient one:

```kotlin
// adapted — the twin's per-item colour, in both bars, applied the same way
CompositionLocalProvider(LocalContentColor provides contentColor) {
    screen.icon()          // an Icon() inside reads LocalContentColor and tints
}
```

This works only because the slot's body uses `Icon`. `Image` does not read `LocalContentColor` and
will draw the vector in its authored colour — invisible on the wrong surface
(`material-symbols-icon-system`).

**Colour roles are material and may differ — but check that they differ on purpose.** In this tree
the two bars use the same `primary` for a selected item and *different* tokens for an unselected one
(`onSurfaceVariant` flat, `onSurface` decorative). That is legal under this rule and is also exactly
how an unintended divergence looks. Diff the two colour blocks deliberately whenever you touch
either, because nothing else will.

**Guard the position lookup before you offset anything.** The indicator's position comes from
`indexOfFirst { it.ordinal == selected }`, which returns **-1** whenever the selection is an item
that lives outside the container. Both twins must hide the indicator on -1
(`if (selectedPosition >= 0)`); an unguarded `width * position` slams it a full item to the left of
the container and reads as a rendering glitch rather than a selection state. Coercing the -1 away is
**not** hiding — it parks the indicator on the previously selected item, which looks like a correct
selection state for the wrong item. In this tree only the flat twin does both, and step 3 below is
what catches that.

**Centring is a mirrored decision as well.** Both twins hold the container in a weighted slot beside
a sibling button, and both need `weight(1f, fill = false)` plus `Arrangement.Center` so the leftover
width goes *around* the cluster instead of between its halves
(`weight-fill-false-to-center-a-cluster`). Give one twin `fill = true` and it is centred while the
other is edge-pinned — a difference the setting appears to cause.

**Translucency tints the control, never a strip behind it.** The flat twin's translucent mode applies
alpha to the container's own colour; painting a translucent band across the full width instead would
make the flat twin occupy a different area than the decorative one, which floats.

**The twins may not live in the same source set — check before you tune.** Here the flat twin is
common code while the decorative bar is Android-only, so every other target renders the flat geometry
unconditionally. Tune only the platform-specific constants and the shared twin silently keeps the old
numbers on every other platform, where nobody is looking; and a preview of the decorative twin simply
does not exist there to compare against.

**Do not "temporarily" build the twin from the original's leftovers.** The plain variant is not the
old pre-effect widget kept around — it was rebuilt into the new form deliberately. A twin that is
actually the previous design is how a setting ends up switching between two *eras* of the UI.

## Verifying it

```bash
# 1. The mirrored constants, side by side. Names differ by prefix, values must not differ at all.
grep -rn --include='*.kt' -E '^private val [A-Za-z]*(Tab|Bar|Blob|Indicator|Inset)[A-Za-z]* = [0-9]+\.dp' . | grep -v '/build/'
```

→ observed: eight declarations in two files, pairing 96 / 64 / 56 / 6 exactly. A pair that does not
line up, or a constant with no partner, is the drift.

```bash
# 2. Slot-lambda icons being recoloured. Every twin that renders the slot needs one of these;
#    a twin rendering `screen.icon()` with no provider around it draws in the default content colour.
grep -rn --include='*.kt' 'LocalContentColor provides' . | grep -v '/build/'
```

→ observed: five hits, and they are not symmetrical. Count the *item* bodies, not the hits: two hits
are theme-level providers; of the five slot renderings in the two bars, the flat twin wraps **both**
of its own (its outside-the-container button is a second body) and the decorative twin wraps **one**
of its three, leaving its outside-the-container button and its collapsed-toolbar icon bare. Four
wrapped out of five, and the gap is visible: the flat button tints for selected-vs-unselected while
the decorative one inherits whatever the theme left in scope and so never shows a selected state.

```bash
# 3. The position lookup, which must be guarded in both twins.
grep -rn -A2 --include='*.kt' 'indexOfFirst { it.ordinal ==' . | grep -v '/build/'
```

→ observed: one per twin, and they disagree — which is the divergence this step exists to find. The
flat twin coerces the -1 away for the offset (`selectedPosition.coerceAtLeast(0)`) **and** hides the
indicator a few lines later with `if (selectedPosition >= 0)`. The decorative one passes the raw -1
into its widget, which only coerces: the widget seeds an internal index from the same
`coerceAtLeast(0)` and syncs it under a `if (selectedTab >= 0)` guard, so a -1 changes nothing and
the indicator draws unconditionally, parked on the tab you were on. There is no visibility branch
anywhere in that file. Select the outside-the-container item and one bar's indicator disappears while
the other's stays lit.

4. By eye: put the two renderings on screen back to back at the same window size and flip the
   setting with a screenshot before and after. Overlay them — the container outline, the item
   centres and the sibling button must land on the same pixels. Then drop to two items and grow to
   five: the twins must stay aligned at every count, which is what tests the shared width rule
   rather than the shared constants.
