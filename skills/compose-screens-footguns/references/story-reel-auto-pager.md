---
name: story-reel-auto-pager
description: A story-style reel — a pager that advances itself on a per-card timer, with a segmented progress bar, tap zones to skip forward or back, and a press-and-hold that pauses it — where every card's data is computed once before the first frame instead of card by card, and the segmented bar's count comes from a card list some years never fill completely. Covers a frame-delta timer that a long hold cannot bank progress against, why an empty onLongPress callback is what makes hold-then-release resume instead of navigate, reading the pager's target page rather than its current one inside a tap handler, and pinning a captured card's colour scheme so it renders the same regardless of the viewer's own theme. Use when a reel's progress bar jumps to the wrong segment, when releasing a paused hold immediately skips a card instead of resuming it, when a loading spinner appears mid-story instead of only before the first card, or when a shared card looks different depending on which theme the device was in.
---

# A self-advancing story reel

One `HorizontalPager` holds every card; a single `LaunchedEffect` keyed on the current page runs the
timer for whichever card is showing. Nothing about the reel is per-card except the cards themselves —
the progress bar, the timer, the tap zones and the close button all live in the shell, so ten cards
can be ten different layouts without ten copies of that chrome drifting apart. The pager's own
`currentPage` is the only place "which card" is recorded; a second counter anywhere else is a second
answer waiting to disagree with it.

## Traps

**The timer counts frame deltas, not elapsed wall time, so a long hold cannot bank progress.**
Sampling a clock across a pause and using the raw difference lets whatever accumulated while paused
land in one jump the instant it resumes. Take the delta from the *previous frame* every frame, paused
or not, and only add it to the running total when nothing is holding the card back:

```kotlin
while (elapsed < holdMs) {
    withFrameMillis { frame ->
        val delta = if (lastFrame == 0L) 0L else frame - lastFrame
        lastFrame = frame
        if (!pressed && !busy && !pagerState.isScrollInProgress) elapsed += delta
    }
    progress = (elapsed.toFloat() / holdMs).coerceIn(0f, 1f)
}
```

All three gates matter for different reasons: `pressed` is the read-longer hold, `busy` is a save or
share in flight (advancing under a share sheet would hand the *next* card's image to whatever the user
picked), and `isScrollInProgress` covers a manual swipe already carrying the reel to the next card on
its own. Missing any one of them is a pause that only sometimes pauses.

**An empty `onLongPress` is not a no-op — it is what makes releasing a hold resume instead of
navigate.** `detectTapGestures` behaves differently depending on whether `onLongPress` is `null`:
with it `null`, every release — however long the finger was down — resolves as an ordinary tap and
fires `onTap`. Passed a non-null callback, even one that does nothing, a hold that outlasts the
long-press timeout consumes the gesture *before* release and `onTap` never fires for it:

```kotlin
onLongPress = { },   // deliberately empty, deliberately not omitted
onTap = { offset ->
    val from = pagerState.targetPage
    goTo(if (offset.x > size.width / 2f) from + 1 else from - 1)
},
```

Delete the seemingly-dead lambda and a press held to read a line carefully still fires `onTap` the
moment the finger lifts — the exact skip the hold was supposed to prevent. Verified against
`androidx.compose.foundation:foundation`'s `TapGestureDetector.kt`: the plain up-event wait
(`waitForUpOrCancellation()`) only runs when `onLongPress` is `null`; passed a callback, the detector
waits on `waitForLongPress()` instead, and a successful long press consumes to up and returns before
`onTap` is ever reached.

**A tap handler that can fire again before the last animation lands must read the target page, not
the current one.** `pagerState.currentPage` is the page actually on screen; `pagerState.targetPage` is
where an in-flight `animateScrollToPage` is headed. A second tap arriving mid-animation, read off
`currentPage`, re-issues a scroll to the page that is already being left — read off `targetPage`, it
steps one further from wherever the first tap is already going. This isn't in tension with
`nowplaying-pager-no-feedback-loop` reading `currentPage` on purpose — that skill syncs external state
once a scroll has *settled*; this one decides where a tap goes *mid*-animation, a different question.

**The segmented bar's count is the filtered card list's size, never the full set of card kinds.** A
year with no biggest day or too few dated plays for a decade breakdown drops those cards entirely
(`WrappedCard.entries.filter { ... }`), and every index downstream — the pager's page count, the
close-vs-advance decision, the segment row — reads that filtered list's size, not the enum's. Sizing
the segment row off the enum instead prints empty trailing segments for cards this particular year
was never going to show.

**Resolve every card's data before the first frame mounts, not card-by-card as the user pages
through.** The whole year is computed in one function that returns a single immutable result, gated
behind a three-state holder — loading, not-enough-data, or ready — and the pager only exists inside
the ready state. A spinner appearing between two cards mid-story, instead of only once before the
first one, means some card's data is being fetched lazily on arrival; move it into the same upfront
computation everything else went through.

**A card meant to be captured cannot take its colour from the viewer's current theme.** The reel
builds its whole scheme from the year's own artwork with `isDark` fixed to `true`, regardless of the
device's light/dark setting, because the same card is captured as a share image — a picture that came
out light-mode on one phone and dark-mode on another is not the same object, even though both are
"correct" renders of the same screen. Anything captured for export needs its inputs pinned the same
way; the device's ambient settings are exactly the kind of input that must not leak in.

**The capture region is the poster inside the card, not the card's own slot.** Every other card hands
its whole slot to `capturable()` (see `compose-capture-to-share-image`), but the one card with its own
Save and Share buttons passes the capture modifier to its inner panel only — the eyebrow above it and
the two buttons below it are how you ask for the image, not part of it. The same slot composable also
applies its bottom chrome padding *before* backgrounding and capturing, so the capture sees the same
bounds a plain card gets; reversing that order bakes the padding into the exported picture as empty
ground along one edge.

## Verifying it

Run from the Kotlin source root holding your `ui/` and `viewModel/` packages — here,
`ui/screen/home/wrapped/WrappedScreen.kt` is the reel screen and `viewModel/WrappedUiState.kt` is the
state it reads; adjust both paths to your own layout.

1. **All three pause gates are on the timer's own condition, not just one of them:**

   ```bash
   grep -n "!pressed && !busy && !pagerState.isScrollInProgress" ui/screen/home/wrapped/WrappedScreen.kt
   ```

   Pass condition: found. Missing any name here is a case that no longer pauses.

2. **The empty long-press callback exists and is not simply absent:**

   ```bash
   grep -n "onLongPress = { }" ui/screen/home/wrapped/WrappedScreen.kt
   ```

   Pass condition: found. Absent, a hold-then-release will fire `onTap` on release regardless of how
   long the hold was.

3. **The tap handler reads `targetPage`, the header reads `currentPage`:**

   ```bash
   grep -n "pagerState.targetPage\|pagerState.currentPage" ui/screen/home/wrapped/WrappedScreen.kt
   ```

   Pass condition: `targetPage` appears inside the tap-gesture block; `currentPage` appears where the
   currently-shown card is read for display.

4. **The segment count and the pager's page count both trace back to the filtered list:**

   ```bash
   grep -n "cards.size" ui/screen/home/wrapped/WrappedScreen.kt
   grep -n "WrappedCard.entries.filter" viewModel/WrappedUiState.kt
   ```

   Pass condition: every on-screen count uses `cards.size`; the filter exists exactly once, upstream
   of all of them.

5. **Export the same card twice: once with the device in light mode, once in dark.** The two exported
   files must be pixel-identical — two exports taken in the same device theme prove nothing here.
   Any difference means the device's own theme setting reached a value inside the capture.
