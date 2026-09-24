---
name: fullscreen-video-gesture-overlay
description: The gesture and chrome layers of a fullscreen video screen — tap anywhere to toggle the controls, double-tap either half to seek, an auto-hide timer that every interaction postpones, and a picture-in-picture (PiP) guard that removes both layers. Use when single taps work on only half the screen, when the controls vanish while the user is dragging the seek bar, when the seek thumb snaps back under the finger, when a double-tap produces no ripple or a ripple that never fades, or when app chrome is still drawn over the video inside a small floating window.
---

# Fullscreen video gesture overlay

A fullscreen video screen is three siblings in one box, in this order:

```kotlin
// adapted
Box {
    VideoSurface(Modifier.fillMaxSize(), isInPipMode = isInPipMode)   // always on
    if (!isInPipMode) {
        Row(Modifier.fillMaxSize()) {          // gesture layer: two seek zones
            SeekZone(Modifier.weight(1f), onSeek = { seekBack() })
            SeekZone(Modifier.weight(1f), onSeek = { seekForward() })
        }
        Crossfade(chromeVisible) { if (it) Chrome(...) }               // chrome, on top
    }
}
```

Two equal-weight zones fill the whole surface — no dead strip down the middle, so every tap lands
in a zone and the toggle is never lost. The chrome composes **nothing** while hidden, so hit
testing falls straight through to the zones; while shown, its buttons are on top and take their
own taps.

## Traps

**Every zone needs the single-tap toggle, not just the double-tap.** The tap detector is written
once per zone, so the toggle is duplicated by construction, and a zone that grew an `onDoubleTap`
and never got an `onTap` swallows single taps on its half of the screen — the controls appear when
you tap the left of the video and do nothing on the right. Same two-entry-point shape as
`guard-on-every-trigger-path`.

**A tap detector gives no press feedback — wire the ripple by hand.** `clickable` would supply one,
but it also claims the pointer and offers no double-tap, so the zone drives the indication itself:

```kotlin
// adapted
Box(
    Modifier
        .fillMaxHeight()
        .weight(1f)
        .clip(RoundedCornerShape(topEndPercent = 10, bottomEndPercent = 10))
        .indication(interactionSource = interactionSource, indication = ripple())
        .pointerInput(Unit) {
            detectTapGestures(
                onTap = { chromeVisible = !chromeVisible },
                onDoubleTap = { offset ->
                    scope.launch {
                        val press = PressInteraction.Press(offset)
                        interactionSource.emit(press)
                        onSeek()
                        interactionSource.emit(PressInteraction.Release(press))
                    }
                },
            )
        },
)
```

Three things that are easy to get wrong here: the release must carry the **same press instance**
that was emitted, or the indication never clears and the zone stays lit; `emit` suspends, so it
needs a scope, not the gesture callback's own frame; and the ripple is bounded by the modifier
chain's clip, so **clipping the zone's inner corners is what makes it read as a rounded half of the
screen** instead of a rectangle meeting its twin at a hard seam.

**The auto-hide timer is a `LaunchedEffect` whose keys are the postponement list.**

```kotlin
// adapted
LaunchedEffect(key1 = chromeVisible, key2 = isSliding) {
    if (chromeVisible && !isSliding) {
        delay(AUTO_HIDE_MS)
        chromeVisible = false
    }
}
```

Keying on the visibility flag is what **restarts** the countdown on each toggle — a
`LaunchedEffect(Unit)` looping over a delay keeps its own clock and hides the chrome moments after
the user opened it. Keying on the scrub flag is what **pauses** it: the effect is cancelled when
the drag begins and relaunched when it ends, so the user gets a full window afterwards rather than
the remainder of one. Every future interaction that must hold the chrome open is another key, never
another branch inside the body — a branch runs once, on the keys you already had.

**The scrub value must stop following the player while the thumb is down**, same flag again:

```kotlin
// adapted
LaunchedEffect(key1 = timelineState, key2 = isSliding) {
    if (!isSliding) sliderValue = fractionOf(timelineState)
}
```

Without the guard, each incoming position update overwrites the value the drag is producing and the
thumb snaps back under the finger. Set the flag in `onValueChange` and clear it in
`onValueChangeFinished`, dispatching the seek there — one seek per gesture, not one per frame.

**Both the gesture and the button must dispatch the same seek command, and it should be the
engine's own relative seek.** Sending "current position ± N" from the UI puts a second copy of the
increment in the screen; the engine's seek-back / seek-forward command keeps one. The label you
draw next to the arrows is then a **claim about the engine's configured increment** — change the
increment without the label and the UI lies in the one place the user is watching.

**Gate the gesture layer on picture-in-picture (PiP) too, not just the chrome.** In a
thumbnail-sized floating window the transport controls belong to the system, and a stray double-tap
seek there is worse than no gesture at all. The flag is platform-observed state — a subscription to
the mode-change callback where the concept exists, a constant `false` where it does not — so it
must be read as state the composition recomposes on, never sampled once into a plain variable. The
video surface itself stays *outside* the guard, or the window goes black as it shrinks.

**A dispose block that restores a value twice restores the second one.** Entering fullscreen
typically locks orientation, hides the system bars and holds the screen awake; leaving must undo
all three. Capture the original orientation *before* forcing landscape — after, you save your own
value and "restore" is a no-op. Then check it is written **once**: computing the saved orientation
into a `when` and following it with an unconditional "unspecified" makes the whole `when` dead, and
the bug hides because simply unlocking the orientation also looks plausible.

## Verifying it

1. `grep -rn --include="*.kt" "onDoubleTap" .` — expect **one per seek zone**. Any other hit must
   live somewhere that cannot sit over the video (a window title bar, for instance); one handler on
   a screen that has two zones is the bug.
2. `grep -rn --include="*.kt" -B 8 "delay(" . | grep "LaunchedEffect"` — one per timer, each a
   `LaunchedEffect(...)` header with keys inline. Keep the window wide — a hide-timer's `delay` sits
   in an `else` branch below its header, so `-B 3` drops exactly those (9 of 11 here; the misses
   include a volume popup whose keys *are* its postponement list). A timer whose chrome holds a
   scrub control and whose keys are only the visibility flag is this bug.
3. `grep -rn --include="*.kt" "PressInteraction.Press(" .` — each hit must be bound to a local and
   released with that same value a few lines below.
4. `grep -rn --include="*.kt" "rememberIsInPipMode\|isInPictureInPictureMode" .` — one declaration,
   one implementation per platform, one read per screen that draws chrome over video.
5. By hand, in this order: tap the right half (controls appear); double-tap each half (seek, plus a
   ripple centred on the finger that fades); start a scrub and hold still past the auto-hide window
   (controls stay), then release (they stay a full window longer); shrink to a floating window (no
   chrome, no gesture) and restore it. Leave the screen last and confirm the device orientation and
   system bars are as they were before you entered.
