---
name: nowplaying-pager-no-feedback-loop
description: A now-playing artwork pager that both follows the player and drives it, without the two writing to each other in a loop — the in-progress-scroll flag covers programmatic animation as well as drags, the seek is dispatched from the settled page only, and the page-difference decision is a pure function outside the UI runtime. Use when a swipe bounces back to the page it came from, when one swipe skips two tracks, when the pager stops following the player after a fast swipe, when swiping backwards restarts the current track instead of going back one, or when a far swipe under shuffle lands on the wrong song.
---

# Now-playing pager without a feedback loop

The pager is a **two-way** binding: it slides when the player advances, and it seeks when the user
settles on another page. Each direction writes what the other watches — keep one quiet at a time.

## Traps

**The in-progress-scroll flag is true for programmatic animation too.** It is the obvious way to mean
"the user is dragging" and it is wrong: the pager sets it identically for a drag and for the
animate-to-page call your own follow effect just made, so it blocks the follow while it runs. Use a
flag you own:

```kotlin
// adapted
var isAnimatingFromPlayer by remember { mutableStateOf(false) }
var isUserDraggingActive by remember { mutableStateOf(false) }
LaunchedEffect(pagerState) {
    snapshotFlow { pagerState.isScrollInProgress to isAnimatingFromPlayer }
        .collect { (scrolling, animating) -> isUserDraggingActive = scrolling && !animating }
}
```

**Bracket every programmatic scroll with that flag in a `try`/`finally`.** Not tidiness — the effect
is cancelled whenever its keys change, which is what happens when the track advances again
mid-animation, and a flag left `true` by that cancellation blocks every later write permanently.

```kotlin
// adapted
LaunchedEffect(currentIndex, queue.size) {
    val target = currentIndex
    if (!isUserDraggingActive && target in queue.indices && target != pagerState.currentPage) {
        isAnimatingFromPlayer = true
        try { pagerState.animateScrollToPage(target) } finally { isAnimatingFromPlayer = false }
    }
}
```

**Dispatch from the settled page, never the current or target page.** The current page flips as soon
as a drag crosses the halfway point and can flip back inside one gesture; the target page changes
with the fling. Either one sends a seek per crossing — "one swipe skipped two tracks":

```kotlin
// adapted
LaunchedEffect(pagerState, currentIndex, queue.size) {
    snapshotFlow { pagerState.settledPage }
        .distinctUntilChanged()
        .collect { settled ->
            if (isAnimatingFromPlayer) return@collect
            if (settled !in queue.indices) return@collect
            if (settled == currentIndex) return@collect
            dispatch(computeSeekAction(settled, currentIndex))
        }
}
```

The last guard is the loop-breaker: after the player moves and the follow effect slides the pager to
match, the pager settles and emits — without it, that emission goes back at the player as a seek it
has already done.

**Keep the decision a pure function, outside the composition** — four outcomes from one subtraction,
in a file importing a domain model and nothing from the UI toolkit, so it is exercisable with no UI:

```kotlin
// as written
internal fun computeSeekAction(
    newPage: Int,
    currentOrderIndex: Int,
): ArtworkSeekAction =
    when (newPage - currentOrderIndex) {
        0 -> ArtworkSeekAction.NoOp
        1 -> ArtworkSeekAction.Next
        -1 -> ArtworkSeekAction.Previous
        else -> ArtworkSeekAction.Skip(newPage)
    }
```

The branch exists because adjacent and far moves are different commands: a ±1 move reuses the
player's own next/previous, preserving whatever transition machinery the adapter runs between
neighbouring items (see `crossfade-dual-player`); a longer jump goes through seek-by-index.

**Use the skip-to-previous-*item* command for a backwards swipe.** Plain previous implements the
standard "restart the current track if the playhead is past a few seconds" rule — a literal position
threshold in the desktop adapter, a configurable maximum-seek-to-previous-position on the mobile
engine. Swipe backwards half a minute in and the player restarts that song, leaving the pager a page
away; the follow effect slides it back and the swipe bounces. Every other caller of "previous" still
wants the restart rule, so this is a second command, not a changed one.

**The page index is in play order; the engine's seek-by-index is in timeline order.** The pages are
the queue the user can see, which under shuffle is a permutation of the engine's list — full
treatment in `queue-index-vs-shuffle-space`. Route the far skip through the handler entry point that
converts (`if (shuffleModeEnabled) getUnshuffledIndex(index) else index`), or a far swipe under
shuffle plays a different song than the one under the finger. The ±1 branch is unaffected.

**Derive the page from the queue using the id the queue actually stores.** Engines are commonly
handed a decorated media id — a prefix naming which rendition is loaded, or a cache key — and
comparing that against the plain queue ids fails for exactly the decorated entries, so the pager
sits on page 0 whenever one of them plays.

```kotlin
// as written
internal fun deriveOrderIndex(
    queue: List<Track>,
    nowPlayingVideoId: String?,
): Int {
    if (queue.isEmpty() || nowPlayingVideoId.isNullOrEmpty()) return 0
    return queue
        .indexOfLast { it.videoId == nowPlayingVideoId }
        .coerceAtLeast(0)
}
```

The coercion keeps the pager on a valid page while the queue has been replaced and the now-playing
state has not caught up. Matching by id cannot tell two copies of one track apart, so read
`queue-index-vs-shuffle-space` first — and for the same reason **page keys must stay unique when the
queue is not**: build the key from the id **and** the index, or a repeat collides.

**Two edge states need explicit handling.** A queue that shrinks below the current page leaves the
pager past the end — watch the size and scroll to the last index. And with repeat-one on,
next/previous do not move, so a settled swipe is dragged straight back: disable scrolling
(`userScrollEnabled = !isRepeatOne && queue.isNotEmpty()`) instead of letting the user fight it.

## Verifying it

1. `grep -rn --include="*.kt" "isScrollInProgress\|animateScrollToPage\|settledPage\|scrollToPage(" .`
   — the four sync points together. Every *animated* scroll must sit inside the owned flag's
   `try`/`finally`; an instant `scrollToPage` snaps, so it emits no intermediate pages — but its one
   settled destination still reads as a swipe, so bracket it too unless the guards already drop it.
2. `grep -rn "^import" $(grep -rl --include="*.kt" "fun computeSeekAction" .)` — the decision file
   must import no UI-toolkit package at all; a domain model and nothing else is the expected listing.
3. `grep -rn --include="*.kt" "seekToPrevious()\|seekToPreviousMediaItem()" .` — both must exist on
   the player interface and every adapter, and the backwards branch must reach the media-item one.
4. By hand, in order: swipe forward one page (one advance, no bounce); let a track end on its own
   (the pager slides, no seek goes back); swipe backwards well past the restart threshold (previous
   track, not a restart); swipe several pages quickly (one jump, landing where you released); repeat
   with shuffle on, checking the audible track against the artwork; then turn repeat-one on.
