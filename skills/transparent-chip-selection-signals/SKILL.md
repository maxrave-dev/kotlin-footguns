---
name: transparent-chip-selection-signals
description: A see-through selection chip — a drop shadow under a transparent shape shows THROUGH it as a dark ring, and zeroing the resting elevation does NOT remove it, because each interaction state carries its own independent token default. Covers dropping the selection-only leading icon that widens the chip by 26dp and reflows a scrolling row under the finger that just tapped it, switching the outline off when the fill arrives, and pairing a role colour with its own "on" token. Use when a transparent chip has a dark halo that comes back on press or hover, when tapping a chip shifts its neighbours sideways, or when a selected chip's label is unreadable on one of the two themes.
---

# A chip with nothing in it

Filter chips over artwork look wrong with a solid unselected fill — a slab punched over the image.
Making the idle state fully transparent is one line; keeping it *looking* transparent is the rest
of this file.

```kotlin
// adapted — outline carries the idle shape, a solid fill carries selection, nothing else
ElevatedFilterChip(
    shape = CircleShape,
    elevation = FilterChipDefaults.elevatedFilterChipElevation(
        elevation = 0.dp, pressedElevation = 0.dp, focusedElevation = 0.dp,
        hoveredElevation = 0.dp, draggedElevation = 0.dp,      // each state is its own default
    ),
    colors = FilterChipDefaults.elevatedFilterChipColors(
        containerColor = Color.Transparent,
        selectedContainerColor = MaterialTheme.colorScheme.primary,
        labelColor = MaterialTheme.colorScheme.onSurfaceVariant,
        selectedLabelColor = MaterialTheme.colorScheme.onPrimary,   // the matching `on` token
    ),
    border = FilterChipDefaults.filterChipBorder(
        enabled = true, selected = isSelected,
        borderColor = MaterialTheme.colorScheme.outline,
        selectedBorderColor = Color.Transparent,                    // the fill IS the shape now
    ),
    selected = isSelected,
    label = { Text(text, maxLines = 1) },
    // no leadingIcon — see below
)
```

## Traps

**A shadow under a transparent shape is drawn *inside* it.** Elevation paints a soft dark shape
behind the container; when the container has no fill, that shape is visible straight through it as
a grey ring following the outline. The chip looks like it has a halo, or a second, blurrier border.
Nothing about the colour set hints at this — the fix lives in the elevation argument.

**Zeroing `elevation` alone does NOT zero the shadow, and this is the trap that survives review.**
The elevation factory takes six values, and every one of them falls back to its *own* design token,
not to the value you passed: resting and pressed and focused each resolve to level 1, hovered to
level 2, dragged to level 4, disabled to level 0 — 1dp, 1dp, 1dp, 3dp, 8dp, 0dp respectively. So
`elevatedFilterChipElevation(elevation = 0.dp)` gives you a clean chip at rest and puts the ring
back the instant a finger touches it or a pointer moves over it. It reviews as correct because the
screenshot is taken at rest. Pass every state explicitly, or use the plain (non-elevated) chip,
which has no shadow to argue with.

**A selection-only leading icon changes the chip's width, and the row moves under the finger.** The
stock pattern puts a tick in the selected chip. The icon is 18dp and the spacing beside it is 8dp,
so selecting a chip makes it exactly 26dp wider — in a horizontally scrolling row, every chip after
it slides 26dp sideways at the moment of the tap, under the finger that is still on the screen. The
tick exists because the framework's own default selected fill is a faint container colour that
cannot stand alone; once selection is a solid role colour against a *fully transparent* idle state,
the contrast is already the strongest available and the second signal only costs.

**Animating the icon in does not fix the reflow — it spreads it over the animation.** The version
this replaced wrapped the tick in an animated-content block whose unselected branch was empty, so
the chip grew from its own width to 26dp wider over a couple of hundred milliseconds and the row
slid under the finger the whole time. A width change is a width change; the only fix is not to
change the width.

**Filled-versus-empty is what earns the right to drop the tick.** Selection here is not one hue
against another — it is "has a fill" against "has no fill", which survives colour blindness and
survives a greyscale screenshot. If you keep an idle fill (even a subtle one), that argument
disappears and you need the icon back, or a border weight change, or something else non-chromatic.

**Switch the border off when the fill arrives.** An outline plus a solid fill gives the selected
chip a rim in a colour that was chosen to read against the *background*, not against the fill —
usually a dark halo on a light chip. `selectedBorderColor = Color.Transparent` is the pair to
`selectedContainerColor`; changing one without the other is where selected chips start looking
heavier than unselected ones.

**Pair a role colour with its own `on` token — never a hand-picked white.** A role like `primary`
is not a fixed colour: on a dark scheme it resolves to a pale tint, on a light one to a saturated
one. A literal white label reads on the light scheme and disappears on the dark one (or the other
way round, depending which you developed on). `onPrimary` is defined as "the thing that reads on
`primary`" for both, and it is one token away from the fill you already chose.

**Opting out of the minimum interactive size hands you the touch target.** Chips are often shrunk
by providing an unspecified minimum interactive component size, which removes the framework's
guaranteed target along with the extra height. Whatever you take away there you now owe by hand —
see `custom-thin-media-slider` for the same opt-out on a different control and what it costs.

**A decorative wrapper around the chip is a separate surface with separate colours.** Where the
selected chip also carries an animated outline drawn by a wrapper, that ring is painted outside the
chip and knows nothing about `selectedBorderColor` — so the chip can end up with the wrapper's ring
*and* its own. See `animated-gradient-border-ring` for that layer; decide there which of the two
outlines exists in the selected state.

## Verifying it

```bash
M3=$(find ~/.gradle/caches -name 'material3-desktop-*.jar' | head -1)

# 1. what each elevation parameter falls back to when you do not pass it
javap -c -p -classpath "$M3" androidx.compose.material3.FilterChipDefaults \
  | sed -n '/SelectableChipElevation elevatedFilterChipElevation-/,/traceEventStart/p' \
  | grep -o 'FilterChipTokens\."get[A-Za-z]*'

# 2. the level behind each of those tokens (level 0/1/2/3/4/5 = 0/1/3/6/8/12 dp)
javap -c -p -classpath "$M3" androidx.compose.material3.tokens.FilterChipTokens \
  | grep -B1 -E 'putstatic .*(Elevated[A-Za-z]*ContainerElevation|DraggedContainerElevation):F'

# 3. what a leading icon adds: the icon size, then the spacing beside it
javap -c -p -classpath "$M3" androidx.compose.material3.tokens.FilterChipTokens \
  | grep -B8 'putstatic .*Field IconSize:F' | grep -E 'ldc2_w|dconst'
javap -c -p -classpath "$M3" androidx.compose.material3.ChipKt \
  | grep -B8 'HorizontalElementsPadding:F' | grep -E 'bipush|iconst_|ldc' | head -1

# 4. every chip elevation and border call in your own tree
grep -rn --include='*.kt' -E 'elevatedFilterChipElevation|filterChipBorder' .
```

1. → observed: six distinct getters — container, pressed, focus, hover, dragged, disabled. Six
   independent defaults, one per parameter. Nothing inherits the value you passed.
2. → observed: level 1 for resting, pressed and focus; level 2 for hover; level 4 for dragged;
   level 0 for disabled. So a chip with only `elevation = 0.dp` still lifts 1dp under a press and
   3dp under a hover — which is the ring coming back.
3. → observed: `18.0d` and `8` — 26dp of width appears the moment a leading icon does.
4. → observed: the chip's own elevation and border calls. Read the argument list of each: an
   elevation call naming fewer than five states is the defect above, and a border call without a
   `selectedBorderColor` leaves the outline on under the fill.

Then, by hand, on both themes: press and hold an unselected chip and look for a halo appearing
around it. On a pointer device, hover it — that is the 3dp case and the most visible one. Then tap
a chip near the left of a scrolling row and watch the chips to its right: they must not move.
