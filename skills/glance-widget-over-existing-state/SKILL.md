---
name: glance-widget-over-existing-state
description: Build a home-screen widget that renders the app's existing state holder rather than a parallel copy of it, by injecting the same shared state object and the same long-lived scope the app already uses and re-issuing the widget update whenever that state changes. Covers dispatching the app's own UI events from widget buttons, turning off hardware bitmaps for artwork the widget must read, and the leak to avoid when starting those collectors from the widget's provide-glance callback. Android only. Use when a widget shows stale playback or session state, when its artwork is blank, or when its buttons need their own duplicate logic.
---

# A widget over the state the app already has

Android only. The widget is not a second app. It is a second renderer of the same state, and it
gets there by being a dependency-injection component itself:

```kotlin
// adapted — the widget itself is a dependency-injection component
class MainAppWidget : GlanceAppWidget(), DiComponent {
    val playerStateHolder: PlayerStateHolder by inject()
    val serviceScope: CoroutineScope by inject(named(SERVICE_SCOPE))
    …
}

// The receiver is a one-liner holding one widget instance.
class AppWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = MainAppWidget()
}
```

Two consequences worth being explicit about:

- **No parallel data path.** The widget reads the same flows the app's screens read, so it can
  never disagree with the app about what is playing.
- **Buttons dispatch the app's own events**, not widget-specific ones:
  `onClick = { playerStateHolder.onUIEvent(UIEvent.PlayPause) }`. There is no widget branch in the
  handler to keep in sync.

## Rendering state is not enough — you must re-issue the update

Collecting a flow inside the widget's content block updates the *composition*, but a widget is
drawn out of process: the host only redraws what you push to it. So a state change has to end in
an explicit update for every placed instance of the widget:

```kotlin
// adapted
private suspend fun updateWidget(context: Context) {
    val manager = GlanceAppWidgetManager(context)
    manager.getGlanceIds(this@MainAppWidget.javaClass).forEach { glanceId ->
        this@MainAppWidget.update(context, glanceId)
    }
}
```

and something long-lived has to call it:

```kotlin
// adapted — inside provideGlance(), above and outside the provideContent block
serviceScope.launch {
    launch { playerStateHolder.controllerState.collectLatest { updateWidget(context) } }
    launch { playerStateHolder.nowPlayingScreenData.collectLatest { updateWidget(context) } }
}
```

**The collectors must not be on the composition's scope.** The content callback's composition is
torn down between updates; a collector started there dies with it and the widget freezes at
whatever it last drew. The injected long-lived scope — the same one the playback service uses —
is what keeps them alive.

## Traps

**Starting the collectors from `provideGlance` leaks them.** Note where the launch above sits: in
`provideGlance` itself, *outside* `provideContent`. Being outside the composition is the point —
but `provideGlance` runs again on every re-provision, and the launch neither cancels a previous
run nor is tied to anything that will. Each re-provision adds another pair of collectors, all
calling `update` for the same change. Hold them in a single nullable job on the widget object and
cancel before relaunching, or start them once from the component that owns the scope. Assume the
code you inherited has this bug until you find the cancel.

**Turn off hardware bitmaps for anything the widget must read.**
`ImageRequest.Builder(context).…​.allowHardware(false)` — a hardware-backed bitmap has no
pixel data your process can read, and this widget does two things that need exactly that: it
hands the bitmap to the widget host as an image provider, and it derives the background colour
from the bitmap's own palette. Both come back as a blank image or a default colour with no error
in the log.

**Widget images travel as bitmaps or resources, never as URLs.** Load the artwork yourself,
`await` the result, and pass the decoded bitmap through the image provider. A null result must
render *something* — a progress indicator or a placeholder — because the widget will be on
screen during the load.

**A derived background colour is a third state to push.** Deriving the colour from the artwork
means the colour settles *after* the image does, so it needs its own update trigger
(`LaunchedEffect(bgColor) { updateWidget(context) }`). Otherwise the widget shows the new artwork
on the old colour until something else happens to update it.

**Pick flat glyphs for circular icon buttons.** An icon that draws its own filled disc sits on
top of the button's background colour and reads as a dark blob rather than as a button. Use the
bare glyph and let the button supply its own circle and colours.

**A greyed button that still fires is the bug, not the fix — and it is the state you will
inherit.** The button in this pattern has no `enabled` parameter at all — it takes a tint and a
click handler, so an unavailable action is drawn `Color.Gray` and *still dispatches* when tapped,
which is worse than a button that
looks available: the user gets feedback that the tap registered and nothing happens. Add the
missing half yourself — an `enabled: Boolean = true` parameter that drives the tint *and* gates
the `clickable`, fed from the same state object (`enabled = controllerState.isNextAvailable`), so
the two can never disagree.

**Two flows fanning into one update call is a burst at every track change.** The platform's
documented rate limit is not the thing to cite here — that floor governs the periodic update
interval declared in the widget's own metadata, not explicit `update()` calls. But each update is
still a full out-of-process redraw, and hosts differ in how gracefully they take a burst of them.
Conflate at the source — `distinctUntilChanged` on just the fields you render — rather than
pushing more often.

## Verifying it

1. **Change state from the app and watch the widget follow** — play/pause, skip, shuffle, repeat.
   A widget that only updates when you tap it is missing the re-issue loop.
2. **Change state from the widget and watch the app follow.** If it does not, the widget grew its
   own path into the player instead of dispatching a shared event.
3. **Place two copies of the widget.** Both must update — that is what iterating every glance id
   buys you, and a single-instance test never catches its absence.
4. **Kill the app's foreground UI, leave the service running, then change tracks.** The collectors
   must still be alive; this is the test that fails when they were started from the composition.
5. **Confirm the artwork path**: `grep -rn "allowHardware" --include='*.kt' <widget-src>` — every
   request whose bitmap the widget renders or samples must pass `false`.
6. Re-add the widget several times and check the log line inside `updateWidget` does not start
   appearing two, three, four times per change — that count is the collector leak.
