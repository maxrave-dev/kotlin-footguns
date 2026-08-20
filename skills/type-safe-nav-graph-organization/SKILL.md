---
name: type-safe-nav-graph-organization
description: Lay out a type-safe Navigation-Compose graph so it stays readable as the destination list grows — one serializable route object per file grouped by area, area graphs as extension functions on the graph builder, a single transition set on the host, and per-route theming applied by wrapping the screen inside its own entry. Use when a navigation file has grown to hundreds of lines, when route arguments start needing custom types, or when transitions or theming differ between destinations for no stated reason.
---

# Organizing a type-safe navigation graph

Type-safe routes replace string paths with serializable objects. Each one is its own file, grouped
into a package per area of the app, and holds nothing but its arguments:

```kotlin
@Serializable
data object HomeDestination

@Serializable
data class AlbumDestination(val browseId: String)
```

The host declares the transitions once and then does almost nothing else. What it registers directly
is not "whatever was left over" — it is the five bottom-bar tabs plus the fullscreen player, which
its own comment says out loud, and four of those six sit in packages that *do* have an area graph.
The rule is how a destination is entered — from the app chrome, or from another screen:

```kotlin
NavHost(
    navController,
    startDestination = startDestination,
    enterTransition = { fadeIn() + slideInHorizontally { -it } },
    exitTransition = { fadeOut() + slideOutHorizontally { it } },
    popEnterTransition = { fadeIn() + slideInHorizontally { -it } },
    popExitTransition = { fadeOut() + slideOutHorizontally { it } },
) {
    // Bottom bar destinations
    composable<HomeDestination> { HomeScreen(navController = navController, /* … */) }
    // … the other four tabs, then the fullscreen player
    listScreenGraph(innerPadding = innerPadding, navController = navController)
    loginScreenGraph(innerPadding, navController, hideBottomBar = hideNavBar, showBottomBar = { showNavBar(false) })
    // … one call per remaining area
}
```

An area graph is an ordinary extension function on the builder, reading arguments off the entry:

```kotlin
fun NavGraphBuilder.listScreenGraph(innerPadding: PaddingValues, navController: NavController) {
    composable<AlbumDestination> { entry ->
        val data = entry.toRoute<AlbumDestination>()
        ForceDarkContent { AlbumScreen(browseId = data.browseId, navController = navController) }
    }
    // …
}
```

## Traps

**These are not nested navigation graphs, and the difference matters.** The extension functions are
a *file-level* grouping: each calls `composable<…>` directly, so every destination lands flat in the
one host graph. No `navigation<…>` call exists anywhere, and therefore no per-area start destination,
no nested back stack, no scoping of a view model to an area. Want any of those and you want a real
nested graph; want none of them and this buys readability with no extra semantics to reason about.

**Cross-cutting values arrive as function parameters, not through navigation.** Window padding, the
controller and the callbacks that hide or show the bottom bar are plain arguments on the area
function, threaded from the host — which is why the login area's signature is the longest, being the
only one needing the bar callbacks. Resist putting these on the route: a route is serialized into the
back stack and restored across process death, so anything in it must still mean something an hour
later. A lambda does not.

**Theming is a property of the route, applied by wrapping the screen inside its own entry.** Screens
that sit over dark artwork are wrapped where they are registered:

```kotlin
composable<PlaylistDestination> { entry ->
    val data = entry.toRoute<PlaylistDestination>()
    ForceDarkContent { PlaylistScreen(playlistId = data.playlistId, /* … */) }
}
```

Wrapping the whole host instead forces the theme on every destination; putting the wrapper inside
the screen makes the screen un-reusable anywhere that does not want it. Note which destinations get
it and which do not — here the immersive list screens and the fullscreen player do, the plain list
screen beside them does not — because that asymmetry is invisible from inside the screens.

**One transition set, on the host.** No destination overrides it: `composable<X> { … }` everywhere,
never the overload taking its own `enterTransition`. Once one destination takes a private transition
the next reviewer cannot tell whether the rest were deliberate or forgotten, so say why at any override.

**Argument types stay serializable primitives; conversion is documented at the route.** A route
carrying what is conceptually an enum stores its string form and names the converter in KDoc, rather
than registering a custom `NavType`:

```kotlin
/**
 * @param type Using LibraryDynamicPlaylistType.toStringParams
 */
@Serializable
data class LibraryDynamicPlaylistDestination(val type: String)
```
Constants that belong to a route live in that route's own companion object, next to the parameter
they constrain, rather than in a shared constants file every screen imports.

**A route may deliberately carry nothing, and that has to be written down.** One login route is an
argument-less object whose KDoc explains that the callback token reaches a view model instead —
routing it would push a *second* copy of the login screen over the one the user started from.
Without that note the empty route reads as an oversight and the next person adds the argument back.

**Deep links are not on the destinations here.** No `composable<…>(deepLinks = …)` exists; incoming
links are parsed outside the graph and dispatched as an app-level intent. A fork in the road, not a
default — deciding it explicitly is what stops half the links living on routes and half in a view model.

**A route with no entry compiles.** Nothing links a route to the graph until a `composable<…>` block
names it, so a destination file plus a navigation call builds clean and fails at the tap — step 2.

## Verifying it

```bash
# 1. Any route file that is not serializable — no output is the expected result.
find . -path "*/navigation/destination/*" -name "*.kt" -not -path "*/build/*" -exec grep -L "@Serializable" {} +

# 2. Declared routes that no graph registers — no output is the expected result. Count the left set
#    first (`| wc -l`, 22 here) and check it against the file count: a route declared as a plain
#    `object` rather than `data object` is legal and exists here exactly once, and a pattern that
#    matched only `data class|data object` dropped it — reaching "no output" by not looking.
comm -23 \
  <(find . -path "*/navigation/destination/*" -name "*.kt" -not -path "*/build/*" -exec sed -n 's/^\(data \)\?\(class\|object\) \([A-Za-z0-9_]*\).*/\3/p' {} + | sort -u) \
  <(grep -rho --include="*.kt" "composable<[A-Za-z0-9_]*>" . | sed 's/composable<\(.*\)>/\1/' | sort -u)

# 3. The area graphs, and the hosts. One host, and one extension function per area.
grep -rn --include="*.kt" "fun NavGraphBuilder\." . | grep -v "/build/"
grep -rn --include="*.kt" "NavHost(" . | grep -v "/build/"

# 4. Destinations that took a private transition — no output means the host's set is the only one.
grep -rn --include="*.kt" -E "composable<[A-Za-z0-9_]*> *\(" . | grep -v "/build/"
```

Then navigate deep, background the app, let the process be killed, and return: the back stack is
rebuilt from the serialized routes, so an argument that was not really a value surfaces here and
nowhere earlier. Watch the transitions in and out of one destination per area — a route that
animates differently from its neighbours is an override step 4 missed.
