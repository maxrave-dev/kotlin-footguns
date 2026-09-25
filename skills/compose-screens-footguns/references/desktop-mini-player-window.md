---
name: desktop-mini-player-window
description: A second always-on-top, frameless desktop window for playback controls — its existence held as one boolean outside the composition, the same state object as the main window, a hand-rolled drag that anchors to absolute pointer coordinates, a native minimum size in device pixels, and geometry persisted without flooding the store. Use when the small window drifts or jitters while being dragged, when it cannot be resized past a corner, when it collapses below its content, when it disappears the moment the main window is closed, when it opens invisible, or when its state disagrees with the main window's.
---

# Desktop mini-player window

The mini player is **not** a second application. It is one more window in the same application
composition, whose existence is a boolean and whose contents read the same state holder the main
window reads:

```kotlin
// adapted
application {
    Window(onCloseRequest = { isVisible = false }, visible = isVisible, …) { App() }
    if (MiniPlayerManager.isOpen) {
        MiniPlayerWindow(
            stateHolder = playerStateHolder,
            onCloseRequest = { MiniPlayerManager.isOpen = false },
        )
    }
}
```

That boolean lives outside the composition so anything can flip it — the tray menu, an in-app
button reached through a platform hook, the window's own close button — with no window handle and
no message passing:

```kotlin
// as written
object MiniPlayerManager {
    var isOpen by mutableStateOf(false)
}
```

## Traps

**Pass the state holder in; never build a second graph.** The temptation with a second window is a
second dependency scope and a second view model "for the small one" — then both windows must be
told about each other, and in a media app a second graph means a second engine handle. Handing the
existing instance down means both collect the same flows and cannot disagree.

**Closing the main window must not end the application.** Route its close request to
`visible = false` and keep exactly one exit path — typically a tray "quit" item that releases the
player first. Otherwise the small window, the whole point of the feature, is destroyed by the
gesture users perform to get to it.

**If the main window falls back to a decorated, opaque window anywhere, the second one needs the
same fallback.** Transparent undecorated windows fail to render under some drivers, notably in
virtual machines, and the process stays healthy while nothing appears — the failure mode covered by
`compose-desktop-runtime-hardening`. A main window written `undecorated = !isVM, transparent =
!isVM` beside a second written `undecorated = true, transparent = true` can come up invisible on
exactly the machines where the first one was fixed.

**Undecorated means you own the drag — and a local drag delta is measured in a moving frame.** The
handle travels with the window, so each frame's delta is relative to a position that already
changed; accumulating it drifts and jitters. Anchor to the OS pointer position captured at drag
start, together with the window position, and compute from absolutes every frame:

```kotlin
// adapted — the gesture's own dragAmount is deliberately ignored
detectDragGestures(
    onDragStart = {
        val mouse = MouseInfo.getPointerInfo().location
        dragStartMouse = mouse.x to mouse.y
        val pos = windowState.position
        if (pos is WindowPosition.Absolute) dragStartWindow = pos.x.value to pos.y.value
    },
    onDrag = { change, _ ->
        change.consume()
        val startMouse = dragStartMouse
        val startWindow = dragStartWindow
        if (startMouse != null && startWindow != null) {
            val now = MouseInfo.getPointerInfo().location
            windowState.position = WindowPosition(
                (startWindow.first + (now.x - startMouse.first)).dp,
                (startWindow.second + (now.y - startMouse.second)).dp,
            )
        }
    },
    onDragEnd = { dragStartMouse = null; dragStartWindow = null },
)
```

**Keep the drag handle off the resize edges.** A handle spanning the full top edge covers both top
resize corners, so the window cannot be resized from them at all; give it the middle portion of the
top edge and a fixed height. With no title bar, also set a move cursor on it — that is the only
signal the strip is draggable.

**The minimum size belongs on the native window, and it is in device pixels.** Window state sizes
are density-independent; the toolkit's minimum is not, so multiply by the display's scale transform
or the floor is off by that factor. Set it from inside the window's content, once it exists:

```kotlin
// adapted
LaunchedEffect(Unit) {
    (window as? java.awt.Window)?.minimumSize = Dimension(
        (minWidth * window.graphicsConfiguration.defaultTransform.scaleX).toInt(),
        (minHeight * window.graphicsConfiguration.defaultTransform.scaleY).toInt(),
    )
}
```

Enforcing the floor only in Compose lets the native resize go smaller and be corrected on the next
frame, which is visible as flicker at the edge of the drag.

**Persisted geometry has three separate hazards.** Only an *absolute* position can be written — the
sensible default is an alignment (bottom-right of the screen), which has no coordinates, so guard
the write on the position's type. Use a sentinel that cannot be a real coordinate for "never saved",
because zero is a legitimate position; a not-a-number float works. And clamp the restored size up to
the current minimum on read, since a size stored by an older build can be below it. Persist on drag
end or debounce, because **an effect keyed on the window position runs on every step of a drag** —
it writes the store continuously while the window moves, and any log line there goes at that rate.

**Choose the control set by measured size; let hover do feedback only.** The window resizes down to
a strip, so branch the layout on its constraints — an aspect-ratio test for a square or tall
window, then width thresholds for compact / medium / full — and drop optional buttons below a
width. Hover is right for affordances (a cover that scales a little, a panel that goes opaque) and
wrong as the only way to reach a control: it has no keyboard equivalent and no touch equivalent.

**Wire transport keys on the window, and consume only what you handle** — a frameless window with no
menu bar has nowhere else to put them. Match on key-down plus the key, act, return `true`; every
other event returns `false`, or tab focus and every shortcut you did not think of stop working.

## Verifying it

1. `grep -rn --include="*.kt" "isOpen" .` — every write of the open flag in one listing: the tray
   items, the shared toggle hook, the window's own close request. Any of them holding a window
   handle or posting an event instead is the path that will disagree with the tray label.
2. `grep -rn --include="*.kt" "exitApplication()" .` — one hit, not in the main window's close.
3. `grep -rn --include="*.kt" -A 3 "alwaysOnTop\|undecorated\|transparent =\|MouseInfo.getPointerInfo\|minimumSize" .`
   — `transparent =` puts both window declarations in the listing; `-A 3` carries the minimum body
   to the scale multiply. Side by side: the fallback on both; the pointer read in the drag *body*
   as well as at start (only at start means local deltas); the minimum scaled by display transform.
4. `grep -rn --include="*.kt" -A 3 "LaunchedEffect(windowState" .` — anything writing to disk or
   logging inside an effect keyed on position runs per drag step.
5. By hand: drag slowly across the screen and check it tracks the cursor exactly with no drift;
   resize from all four corners; shrink to the floor and confirm no flicker; close the main window
   and confirm the mini player and the audio survive; relaunch and confirm it reopens where and how
   you left it; delete the stored preferences and confirm the first-run default position is used.
