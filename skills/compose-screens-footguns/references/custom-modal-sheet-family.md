---
name: custom-modal-sheet-family
description: A house style over Material3's ModalBottomSheet — transparent container plus your own surface, zeroed window insets with an explicit end spacer, a hand-rolled drag handle, and hide-then-dismiss so the sheet animates closed before it leaves composition. Use when a sheet snaps shut instead of sliding, when its last row sits under the navigation bar, when text inside it is invisible, or when a family of sheets has drifted into a family of slightly different sheets.
---

# Sheets that keep the platform behaviour and none of the platform paint

`ModalBottomSheet` is worth keeping for what it does off screen — drag-to-dismiss, the scrim, back
handling, staying above the keyboard. What it paints is worth replacing wholesale, and once a
codebase has a dozen sheets the replacement has to be one shape, not twelve.

```kotlin
// adapted: colour tokens renamed, content elided
val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

ModalBottomSheet(
    onDismissRequest = onDismiss,                       // scrim tap and swipe land here
    sheetState = sheetState,
    containerColor = Color.Transparent,                 // the sheet paints nothing
    contentColor = Color.Transparent,
    dragHandle = null,                                  // ... and no handle either
    scrimColor = Color.Black.copy(alpha = .5f),
    contentWindowInsets = { WindowInsets(0, 0, 0, 0) }, // insets are now your problem
) {
    Card(                                               // your surface: shape, colour, elevation
        modifier = Modifier.fillMaxWidth().wrapContentHeight(),
        shape = RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp),
        colors = CardDefaults.cardColors().copy(containerColor = colors.container),
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(5.dp))
            Card(                                       // your handle
                modifier = Modifier.width(60.dp).height(4.dp),
                colors = CardDefaults.cardColors().copy(containerColor = colors.handle),
                shape = RoundedCornerShape(50),
            ) {}
            // ... rows ...
            EndOfModalBottomSheet()                     // the inset you zeroed, paid back
        }
    }
}
```

```kotlin
// adapted: the original reads the padding out as a raw value, which drops the fraction
@Composable
fun EndOfModalBottomSheet() {
    Box(
        Modifier
            .fillMaxWidth()
            .height(WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding() + 8.dp),
    )
}
```

A **full-height** variant is the same call with `modifier = Modifier.fillMaxHeight()` and
`shape = RectangleShape` — and, because the insets are zeroed, an explicit top padding taken from
`WindowInsets.systemBars.getTop(density)` so the content clears the status bar.

## Closing it

`hide()` suspends until the sheet has animated down. Removing the sheet from composition first
means there is nothing left to animate, so it vanishes. One helper per sheet keeps every exit on
the same path:

```kotlin
// adapted from the one sheet in the family that has this helper; everywhere else the pair is
// inlined per button (`hide(); onDismiss()` inside a launch, with the action written around it).
// Hoisting it to this parameterised form at every call site is this skill's recommendation,
// not yet the codebase's shape.
val hideThen: (() -> Unit) -> Unit = { action ->
    coroutineScope.launch {
        sheetState.hide()   // animate closed ...
        onDismiss()         // ... then let the caller drop it from composition
        action()            // ... and only then navigate, or open the next sheet
    }
}
```

## Traps

**Dismissing and hiding are not the same event, and both must flip the same flag.** The button
inside your content goes through `hideThen`; the scrim tap and the swipe go through
`onDismissRequest`. If only one of them clears the boolean that gates the sheet, the sheet either
snaps back open or refuses to reopen — and it will always be the path you did not test.

**`hide()` can be cancelled.** It is a suspending animation: if the scope goes away, or something
re-shows the sheet mid-animation, the code after it never runs and the gate boolean stays true.
Where that matters, check the sheet's own visibility after the animation instead of assuming it
finished.

**A transparent content colour is inherited by everything you put inside.** Passing
`contentColor = Color.Transparent` sets that as the default colour for the sheet's content; the only
reason the text is readable is that the surface *inside* re-provides a content colour of its own.
Anything placed between the sheet and that surface — a divider, a lone icon, a header — is drawn in
nothing. Either give the sheet a real content colour, or make the inner surface non-negotiable.

**Zeroing the insets is a debt, and the payment goes in the right place.** The bottom inset belongs
at the end of the *content*, as the last item of the scrolling container, so the list scrolls all
the way past the navigation bar; as padding on the container it eats the scroll range instead. The
top inset only surfaces on the full-height variant, which is the one that reaches the status bar.

**Deleting the drag handle deletes whatever the sheet attaches to that slot.** It is a composable
slot, but versions of Material3 have hung the sheet's expand/collapse affordances on it. Before
replacing it with a decorative bar, check what your version puts there, and make sure a sheet with
`dragHandle = null` is still dismissible without a gesture.

**Opening a sheet from a sheet needs the first one gone.** Two sheets alive at once means two
scrims, and the second inherits the first's dimming. That is what the `action()` *after* `onDismiss()`
in the helper is for: hide, drop, then open the next one or navigate.

**Without `skipPartiallyExpanded` a tall sheet opens half-way.** Your own full-height surface then
fights the sheet's half-expanded state, and the result looks like a layout bug rather than a state
one.

**A dozen sheets is a component, not a convention.** Once `containerColor`, `contentColor`,
`dragHandle`, `scrimColor` and `contentWindowInsets` are repeated by hand at every call site, one
will be missed — usually `contentWindowInsets`, whose symptom (a row under the navigation bar) only
appears on some devices. Wrap the whole thing once and pass content in.

## Verifying it

```bash
# every sheet that zeroed its insets — each one owes an end spacer
grep -rln "contentWindowInsets" --include="*.kt" .

# every close path: the line after hide() must be the one that drops the sheet
grep -rn -A1 "\.hide()$" --include="*.kt" .

# every transparent content colour: the next surface inside must re-provide one
grep -rn "contentColor = Color.Transparent" --include="*.kt" .
```

Then, by hand: close each sheet three ways — its own button, a swipe down, and a tap on the scrim —
and confirm all three animate and all three let the sheet reopen; open one on a device with gesture
navigation and check the last row clears the bar; and open a sheet from inside a sheet, watching the
scrim for a double dim.
