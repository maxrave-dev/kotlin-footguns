---
name: nav-tab-registration-drift
description: A top-level tab has to be registered in every navigation surface that holds its own copy of the tab list — bottom bar, rail, and a stylized bar that keeps two lists — plus the graph and the flag that gates it, or the tab exists in code and never renders. The same drift catches a status entry point carried by more than one top app bar, where the missing badge reads as "nothing is running" rather than as a bug. Covers why a tab's ordinal is an identity rather than a position, what a conditional tab needs when it disappears under the user, and why a badge dot needs a ring of the page colour. Use when a newly added tab or badge shows on one surface but not another, when selection highlights the wrong tab after reordering, or when a tab bar overflows once one more tab appears.
---

# Navigation tab registration drift

An app with more than one form factor grows more than one navigation surface: a bottom bar for a
compact window, a rail for a wide one, often a stylized bar behind a setting. Each builds its own:

```kotlin
val bottomNavScreens = listOfNotNull(
    BottomNavScreen.Home,
    BottomNavScreen.MixForYou.takeIf { showMixForYouTab },   // conditional
    BottomNavScreen.Analytics.takeIf { showAnalyticsTab },   // conditional
    BottomNavScreen.Library, BottomNavScreen.Search,
)
```

That literal appears once per surface, and the host picks between them on window width and on a user
setting — so the surface you tested is the one you happened to be looking at.

The tab type is a sealed hierarchy whose `ordinal` is **declared, not derived**:

```kotlin
sealed class BottomNavScreen(val ordinal: Int, val destination: Any, /* title, icon */) {
    data object Home : BottomNavScreen(ordinal = 0, destination = HomeDestination, /* … */)
    data object Search : BottomNavScreen(1, /* … */); data object Library : BottomNavScreen(2, /* … */)
    data object Analytics : BottomNavScreen(3); data object MixForYou : BottomNavScreen(4)  // gated
}
```

Compare with the list: declared they run 0,1,2,3,4 while the rendered order is 0,4,3,2,1, and two
conditional tabs change the rendered *length* too — the number is not a position in anything. An
enum would derive these same five today; declaring pays off on the *next* edit. The selection is
**persisted as this number**, per surface, in a `rememberSaveable` int, outliving a config change
and a process death and restored into whatever build is running by then — so a derived ordinal,
which renumbers on any reorder or insertion, would select a *different* tab than the user left,
while a declared one makes a reorder a no-op and an insertion take the next free number. In saved
state the value is an identity, and an identity must not be derived from source order.

## Traps

**Registering in fewer surfaces than exist.** The symptom is not an error: the tab is fully built,
its route resolves, and it never appears on the surface you did not edit. Enumerate first — step 1
below — but count **list literals**, not files and not surfaces; none of the three numbers agree.
Four files here: one declares the type, one is the indicator widget, and two hold four
`listOfNotNull` literals between them (bottom bar and rail; the stylized bar's two) feeding three
surfaces — four is the edit count. Same shape as `guard-on-every-trigger-path`.

**One surface keeps two lists, and they are not the same list.** The stylized bar splits the tabs:
one renders as a floating button beside the capsule rather than inside it:

```kotlin
val bottomNavScreens = listOfNotNull(/* … all five … */)   // selection + routing
val barTabs = listOfNotNull(/* … all but Search … */)      // what the capsule draws
```

Update only `barTabs` and the tab draws while tapping does nothing whatsoever: the handler resolves
the tapped ordinal against the *other* list — `bottomNavScreens.find { it.ordinal == index } ?:
return` — and returns without navigating, moving the highlight, logging or throwing. Update only the
full list and it is routable but never drawn. The sliding indicator forces the split: it needs
contiguous, evenly sized slots, and the floating button is neither.

**The ordinal is an identity; the widget wants a position.** Every conversion lives at one boundary
— the call into the indicator widget, which speaks positions in its own `tabs` list:

```kotlin
LiquidGlassTabBar(
    tabs = barTabs,                                                       // identity → position
    selectedTab = barTabs.indexOfFirst { it.ordinal == selectedIndex },
    onTabSelected = { position -> selectTab(barTabs[position].ordinal) }, // position → identity
)
```

Comparing a stored selection against a loop index (`selected == index`) works only while the two
systems coincide; reordering exposes it — the family of `queue-index-vs-shuffle-space`.

**A variable named `index` that holds an identity.** The stylized bar's selection function takes
`index: Int` and resolves it as an ordinal, so its `selectedIndex == index` is correct despite reading
like the bug above — `selectedOrdinal` / `tabPosition` removes the only reason to trace a call chain.

**A conditional tab needs a fallback in every surface *and* at the host.** Switching the feature off
removes the tab from the list and leaves two things dangling. The selection highlight, per surface:

```kotlin
LaunchedEffect(showAnalyticsTab, showMixForYouTab) {
    if ((!showAnalyticsTab && selectedIndex == BottomNavScreen.Analytics.ordinal) ||
        (!showMixForYouTab && selectedIndex == BottomNavScreen.MixForYou.ordinal)
    ) { selectedIndex = BottomNavScreen.Home.ordinal }
}
```

And the user, who may be standing on that screen — handled once at the host, which navigates away
when the flag drops and the back-stack entry still matches. Neither substitutes: fix only the
highlight and someone is stranded where no tab points; fix only the navigation and nothing is
highlighted.

**A bar that sizes itself per tab breaks when the count grows.** The capsule divides the width it is
actually given — `((availableWidth - inset * 2) / tabsCount)`, capped so a two-tab bar on a wide
window does not stretch into slabs — and its row fills its parent rather than wrapping. History for
both: a fixed per-tab width plus a wrapping row grew the bar past the window once an extra tab
appeared, and the sibling button fell off. A fixed item width, total width or wrapping container
each make a surface a new tab can overflow.

**The graph entry is a separate registration.** The tab's `destination` is just an object, so a tab
with no `composable<ThatDestination>` block in the graph compiles clean and fails at the tap.

**A status entry point drifts exactly like a tab, and it is worse when it does.** An icon carried by
more than one top app bar — into a running session, a sync, a download queue — hits the same
silence: badge one bar and the other keeps a plain icon. That badge is often the *only* sign the
session is still live once the user navigates away, so the bar missing it looks like nothing is
running. Give every bar one shared composable owning icon, click and badge — never its parts —
reading the repository directly (one boolean off a flow: `koin-viewmodel-scoping-traps`).

**A badge dot needs a ring of the page colour.** Bare on a glyph, a 7 dp dot merges with the icon's
own dark shapes; an 11 dp circle of `colorScheme.background` behind it survives any glyph and theme.

## Verifying it

```bash
# 1. Which files know about the tab type — four here, and that is NOT the edit count. One declares
#    it, one merely accepts a list (the indicator widget), the rest BUILD lists: count literals.
grep -rln --include="*.kt" "BottomNavScreen" . | grep -v "/build/"

# 2. One tab's destination everywhere: route file, graph entry, tab declaration, every surface's
#    start-destination map, and the host effect that navigates away when a gating flag drops.
grep -rn --include="*.kt" "AnalyticsDestination" . | grep -v "/build/"

# 3. Comparisons mixing the two numbering systems — read each and name the right-hand side's space.
grep -rn --include="*.kt" -E "selected(Index|Tab) == (index|it)\b" . | grep -v "/build/"

# 4. Status entry points in a top app bar — every hit must name the SAME shared composable.
grep -rnE --include="*.kt" "[A-Za-z]+IconButton \{ navController\.navigate" . | grep -v "/build/"
```

Then exercise both form factors — launch narrow, launch wide, resize across the breakpoint with the
new tab selected. Turn the conditional tab's feature off *while standing on its screen*: the app
must move you and highlight a different tab, on every surface. Then add a throwaway sixth tab —
anything falling off the edge has a hardcoded count.
