---
name: glance-widget-over-existing-state
description: Build a home-screen widget that renders the app's existing state holder rather than a parallel copy of it, by injecting the same shared state object and the same long-lived scope the app already uses and re-issuing the widget update whenever that state changes. Covers dispatching the app's own UI events from widget buttons, why the injection target must be a singleton rather than a screen-scoped definition, making the whole widget a tap target, turning off hardware bitmaps for artwork the widget must read, and the leak to avoid when starting those collectors from the widget's provide-glance callback. Android only. Use when a widget shows stale playback or session state, when its artwork is blank, when a tap on it opens the launcher's menu or does nothing at all, or when its buttons need their own duplicate logic.
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

class AppWidgetReceiver : GlanceAppWidgetReceiver() {          // the receiver is a one-liner
    override val glanceAppWidget: GlanceAppWidget = MainAppWidget()
}
```

Two consequences worth being explicit about:

- **No parallel data path.** The widget reads the same flows the app's screens read, so it can never
  disagree with the app about what is playing.
- **Buttons dispatch the app's own events**, not widget-specific ones:
  `onClick = { playerStateHolder.onUIEvent(UIEvent.PlayPause) }` — no widget branch to keep in sync.

## Rendering state is not enough — you must re-issue the update

Collecting a flow inside the widget's content block updates the *composition*, but a widget is drawn
out of process: the host only redraws what you push to it. So a state change has to end in an
explicit update for every placed instance:

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

**The collectors must not be on the composition's scope.** The content callback's composition is torn
down between updates; a collector started there dies with it and the widget freezes at whatever it
last drew. The injected long-lived scope — the playback service's — is what keeps them alive.

## Traps

**Inject singletons, and query in the provide pass.** A `viewModel { }` definition resolves against
a store the platform provides, and a widget has none — so a definition that works everywhere else
fails at its first resolve here. Reach for the repositories that view model would have used
(`koin-viewmodel-scoping-traps` covers the consequences). Read them **once**, above
`provideContent`: a query in the content block re-fires on every redraw the host provokes. Set the
update period to what the data is worth — for a summary, deliberately long.

**Make the whole widget the tap target, and give the launch the new-task flag.** A widget is mostly
surface belonging to no control: press the title, a label or any gap and it falls through to the
launcher's own long-press menu. Click the outermost container and let inner controls override it —
then note where that click runs. In a non-Activity context a start without `FLAG_ACTIVITY_NEW_TASK`
is dropped with no error, no crash and nothing in your log, exactly like a handler that never fired:

```kotlin
// adapted — the deep-link scheme is a placeholder
Column(GlanceModifier.fillMaxSize().clickable(actionStartActivity<MainActivity>())) { … }
Intent(Intent.ACTION_VIEW, "<app-scheme>://<host>?<args>".toUri())
    .setClass(this, MainActivity::class.java)
    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
```

Reserve that deep link for taps that need a **screen**. The widget runs in the app's own process, so
an action that only changes state calls the singleton directly, as the transport buttons do —
routing it through a link starts an activity, parses a URI and navigates only to call that method.
Where a screen *is* the destination the link is right: it behaves the same cold and warm.

**Starting the collectors from `provideGlance` leaks them.** The launch above sits in
`provideGlance` itself, *outside* `provideContent` — being outside the composition is the point, but
`provideGlance` runs again on every re-provision, and the launch neither cancels its predecessor nor
is tied to anything that will. Each re-provision adds another pair, all calling `update` for the
same change. Hold them in one nullable job on the widget and cancel before relaunching, or start
them once from the component owning the scope. Assume inherited code has this bug until you find the
cancel.

**Turn off hardware bitmaps for anything the widget must read.** A hardware-backed bitmap has no
pixel data your process can read, and this widget needs exactly that twice: it hands the bitmap to
the host as an image provider, and derives the background colour from the bitmap's own palette. Both
return a blank image or a default colour, with no error in the log.

**Widget images travel as bitmaps or resources, never as URLs.** Load the artwork yourself, `await`
the result, pass the decoded bitmap through the image provider — and render *something* for a null
result, an indicator or a placeholder, because the widget is on screen during the load.

**A derived background colour is a third state to push.** It settles *after* the image does, so it
needs its own trigger (`LaunchedEffect(bgColor) { updateWidget(context) }`) — otherwise the widget
shows the new artwork on the old colour until something else updates it.

**Pick flat glyphs for circular icon buttons.** An icon drawing its own filled disc sits on top of the
button's background colour and reads as a dark blob, not a button. Use the bare glyph and let the
button supply its own circle and colours.

**A greyed button that still fires is the bug, not the fix — and it is the state you will inherit.**
The button in this pattern has no `enabled` parameter: it takes a tint and a click handler, so an
unavailable action is drawn `Color.Gray` and *still dispatches* — worse than looking available,
because the user gets feedback that the tap registered and nothing happens. Add the missing half: an
`enabled: Boolean = true` driving the tint *and* gating the `clickable` from the same state object.

**Two flows fanning into one update call is a burst at every track change.** The documented rate
limit is not the thing to cite — that floor governs the periodic interval in the widget's metadata,
not explicit `update()` calls. But each update is a full out-of-process redraw and hosts differ in
how gracefully they take a burst: conflate at the source, `distinctUntilChanged` on what you render.

## Verifying it

1. **Change state from the app and watch the widget follow** — play/pause, skip, shuffle, repeat. A
   widget that only updates when you tap it is missing the re-issue loop.
2. **Change state from the widget and watch the app follow.** If it does not, the widget grew its own
   path into the player instead of dispatching a shared event. Then tap every *dead* area — title,
   labels, gaps — from a cold start: the launcher's menu opening means unclaimed surface, and nothing
   at all means a missing `FLAG_ACTIVITY_NEW_TASK`, one of which every started intent needs.
3. **Place two copies of the widget.** Both must update — that is what iterating every glance id buys
   you, and a single-instance test never catches its absence.
4. **Kill the app's foreground UI, leave the service running, then change tracks.** The collectors
   must still be alive; this is the test that fails when they were started from the composition.
5. **Confirm the artwork path**: `grep -rn "allowHardware" --include='*.kt' <widget-src>` — every
   request whose bitmap the widget renders or samples must pass `false`.
6. Re-add the widget several times and check the log line inside `updateWidget` does not start
   appearing two, three, four times per change — that count is the collector leak.
