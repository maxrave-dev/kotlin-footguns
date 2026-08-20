---
name: nav-tab-registration-drift
description: A top-level tab has to be registered in every navigation surface that holds its own copy of the tab list — bottom bar, rail, and a stylized bar that keeps two lists — plus the graph and the flag that gates it, or the tab exists in code and never renders. Covers why a tab's ordinal is an identity rather than a position, and what a conditional tab needs when it disappears under the user. Use when a newly added tab shows on one form factor but not another, when selection highlights the wrong tab after reordering, or when a tab bar overflows once one more tab appears.
---

# Navigation tab registration drift

An app with more than one form factor grows more than one navigation surface: a bottom bar for a
compact window, a rail for a wide one, often a stylized bar behind a setting. Each builds its own list:

```kotlin
val bottomNavScreens = listOfNotNull(
    BottomNavScreen.Home,
    BottomNavScreen.MixForYou.takeIf { showMixForYouTab },
    BottomNavScreen.Analytics.takeIf { showAnalyticsTab },
    BottomNavScreen.Library,
    BottomNavScreen.Search,
)
```

That literal appears once per surface, and the host picks between them on window width and on a user
setting — so the surface you happened to be looking at while testing is the only one you tested.

The tab type is a sealed hierarchy whose `ordinal` is **declared, not derived**:

```kotlin
sealed class BottomNavScreen(val ordinal: Int, val destination: Any, /* title, icon */) {
    data object Home : BottomNavScreen(ordinal = 0, destination = HomeDestination, /* … */)
    data object Search : BottomNavScreen(ordinal = 1, /* … */)
    data object Library : BottomNavScreen(ordinal = 2, /* … */)
    data object Analytics : BottomNavScreen(ordinal = 3, /* … */)   // only while tracking is on
    data object MixForYou : BottomNavScreen(ordinal = 4, /* … */)   // only while signed in
}
```

Compare with the list above: the declared numbers run 0,1,2,3,4 while the rendered order is 0,4,3,2,1,
and since two tabs are conditional the rendered *length* changes too. The number is not a position in
anything. Nor is hand-declaring it about today's values — the declarations happen to run in ordinal
order, so an enum would derive these same five numbers; it pays off on the *next* edit instead. The
selection is **persisted as this number**, once per surface, in a `rememberSaveable` int — so it
outlives a configuration change and a process death and is restored into whatever build is running by
then, which may not be this one. A derived ordinal renumbers itself the moment someone reorders a
declaration or inserts a tab in the middle, and the restored value then selects a *different* tab
than the user left; declared, a reorder is a no-op and an insertion takes the next free number. Once
a value is written to saved state it is an identity, and an identity must not be derived from source
order.

## Traps

**Registering in fewer surfaces than exist.** The symptom is not an error: the tab is fully built,
its route resolves, and it never appears on the surface you did not edit. Enumerate before editing —
step 1 below — but count **list literals**, not files and not surfaces; none of the three numbers
agree. Four files here: one declares the type, one is the indicator widget that merely accepts a list,
and the other two hold four `listOfNotNull` literals between them (bottom bar and rail in the first,
the stylized bar's two lists in the second) feeding three rendered surfaces — four is the edit count.
Same shape as `guard-on-every-trigger-path`: a list updated in some of its homes, silent in the rest.

**One surface keeps two lists, and they are not the same list.** The stylized bar splits the tabs,
because one of them renders as a floating button beside the capsule rather than inside it:

```kotlin
val bottomNavScreens = listOfNotNull(/* … all five … */)   // selection + routing
val barTabs = listOfNotNull(/* … all but Search … */)      // what the capsule draws
```

Update only `barTabs` and the tab draws, and tapping it does nothing whatsoever: the selection handler
resolves the tapped ordinal against the *other* list — `bottomNavScreens.find { it.ordinal == index }
?: return` — and returns without navigating, without moving the highlight, without logging or
throwing. Update only the full list and the tab is routable but never drawn. The sliding indicator is
what forces the split — it needs contiguous, evenly sized slots, and the floating button is neither.

**The ordinal is an identity; the widget wants a position.** Every conversion lives at one boundary
— the call into the indicator widget, which speaks positions in its own `tabs` list:

```kotlin
LiquidGlassTabBar(
    tabs = barTabs,
    selectedTab = barTabs.indexOfFirst { it.ordinal == selectedIndex },   // identity → position
    onTabSelected = { position -> selectTab(barTabs[position].ordinal) }, // position → identity
)
```

Comparing a stored selection against a loop index (`selected == index`) instead works only while the
two numbering systems coincide, and reordering the list is what exposes it — the same defect family
as `queue-index-vs-shuffle-space`: two index spaces over the same items, one comparison that
silently assumes they are one space.

**A variable named `index` that holds an identity.** The stylized bar's selection function takes
`index: Int` and resolves it as an ordinal, so the `selectedIndex == index` inside it is correct
despite reading exactly like the bug above. Rename these: `selectedOrdinal` / `tabPosition` costs
nothing and removes the only reason to trace a call chain to learn which space a number is in.

**A conditional tab needs a fallback in every surface *and* at the host.** Switching the feature off
removes the tab from the list and leaves two things dangling. The selection highlight, per surface:

```kotlin
LaunchedEffect(showAnalyticsTab, showMixForYouTab) {
    if ((!showAnalyticsTab && selectedIndex == BottomNavScreen.Analytics.ordinal) ||
        (!showMixForYouTab && selectedIndex == BottomNavScreen.MixForYou.ordinal)
    ) { selectedIndex = BottomNavScreen.Home.ordinal }
}
```

And the user, who may be standing on that screen right now — handled once at the host, which
navigates away when the flag drops and the back-stack entry still matches that route. Neither
substitutes for the other: fix only the highlight and someone is left on a screen no tab points at,
fix only the navigation and nothing is highlighted.

**A bar that sizes itself per tab breaks when the count grows.** The capsule divides the width it is
actually given — `((availableWidth - inset * 2) / tabsCount)`, capped so a two-tab bar on a wide
window does not stretch into slabs — and its row fills its parent rather than wrapping its content.
Recorded history for both: a fixed per-tab width plus a wrapping row let the bar grow past the window
once an extra tab appeared, and what fell off the edge was the sibling button beside it. A fixed item
width, a fixed total width or a wrapping container each make a surface a new tab can overflow.

**The graph entry is a separate registration.** The tab's `destination` is just an object, so a tab
with no `composable<ThatDestination>` block in the graph compiles clean and fails at the tap.

## Verifying it

```bash
# 1. Which files know about the tab type at all — four here, and that is not the edit count. Read
#    each: one declares the type, one merely accepts a list and is the indicator widget, and the
#    rest BUILD lists. Count the `listOfNotNull` literals inside those, since one file holds two.
grep -rln --include="*.kt" "BottomNavScreen" . | grep -v "/build/"

# 2. One tab's destination type, everywhere: the route file, the graph entry, the tab declaration,
#    every surface's start-destination mapping, and — for a conditional tab — the host effect that
#    navigates away when the flag drops. A surface missing here never renders the tab.
grep -rn --include="*.kt" "AnalyticsDestination" . | grep -v "/build/"

# 3. Comparisons that mix the two numbering systems. Read each hit and confirm which space the
#    right-hand side is in.
grep -rn --include="*.kt" -E "selected(Index|Tab) == (index|it)\b" . | grep -v "/build/"
```

Then exercise both form factors — they render different surfaces: launch narrow, launch wide, resize
across the breakpoint with the new tab selected. Turn the conditional tab's feature off *while
standing on its screen*: the app must move you and leave a different tab highlighted, on each surface.
Then add a throwaway sixth tab — anything falling off the edge is a surface with a hardcoded count.
