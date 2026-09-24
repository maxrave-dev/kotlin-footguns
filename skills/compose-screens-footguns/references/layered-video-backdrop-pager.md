---
name: layered-video-backdrop-pager
description: Building a swipeable now-playing page whose layers — a colour backdrop, a full-bleed looping video or image, and a centred square cover — all belong to one pager, with per-page colours taken from the bitmap that page actually painted and a scrim spanning the whole page. Use when a swipe makes the background and the cover slide out of step, when video from one track bleeds into the neighbouring page mid-swipe, when the backdrop colour belongs to the wrong track or flashes black between pages, when the bottom of the video shows through the controls, or when a tap overlay stops the pager from being dragged at all.
---

# One pager, layered pages

A now-playing screen stacks three things over the same rectangle: a colour backdrop, a full-bleed
video or image for tracks that have one, and the centred square cover. Making that swipeable, the
tempting shape is one pager per layer with their states kept in sync. Don't. **One pager, and each
page composes all three layers**, so a swipe moves them as a unit because they are a unit.

```kotlin
// adapted
HorizontalPager(
    state = pagerState,
    modifier = Modifier.height(screenHeight.dp).fillMaxWidth(),
    beyondViewportPageCount = 1,
    userScrollEnabled = !isRepeatOne && queue.isNotEmpty(),
    key = { idx -> "artwork_${queue.getOrNull(idx)?.videoId.orEmpty()}_$idx" },
) { page ->
    val pageTrack = queue.getOrNull(page)
    val isCurrentPage = page == currentIndex
    val pageHasVideo = isCurrentPage && videoBackdrop != null

    Box(Modifier.fillMaxSize().clipToBounds(), contentAlignment = Alignment.Center) {
        if (!isCurrentPage && pageTrack != null) PageColourBackdrop(...)   // layer 0
        if (pageHasVideo) { VideoBackdrop(...); Scrim(...) }               // layer 1
        CoverSlot(alpha = if (pageHasVideo) 0f else 1f, ...)               // layer 2
    }
}
```

Two pagers would mean two fling animations and two settling points, with nothing constraining them
to agree frame by frame — the drift is worst exactly during the gesture, which is when the user is
looking. The state sharing this avoids is not one variable; it is a whole synchronisation problem.
The other half of this design — how the one pager and the player avoid writing to each other in a
loop — is `nowplaying-pager-no-feedback-loop`.

## Traps

**Clip every page.** A full-bleed video is usually scaled to fill the page's *height*, and a
portrait-shaped source then comes out wider than the page — some layouts even opt into that
explicitly, letting the video exceed its width constraint and centre the overflow. Without
`clipToBounds()` on the page root, that overflow paints over the neighbouring page throughout the
swipe, so the outgoing track's video is visible on top of the incoming track's cover.

**Give the current page a different backdrop from its neighbours, on purpose.** The current page
should fall through to whatever the screen already draws behind the pager — its palette gradient,
its scrim; the *adjacent* pages have none of that, so each needs its own colour fill or the swipe
reveals a flat black void on the way in. `isCurrentPage` therefore reaches three layers, not one:
the per-page fill is drawn only where it is **false**, the video layer only where it is true
(`pageHasVideo`), and the cover's alpha with it. What stays unconditional is the cover *slot*
itself — present on every page, hidden by alpha alone — and the screen's own gradient and scrim,
which are drawn outside the pager and so need no flag.

**Extract each page's colour from the bitmap that page painted.** The colour must come from the
same image the user is looking at, not from a second fetch of "the artwork for track N" — a
different size or a different cache entry gives a visibly different swatch, and the backdrop then
disagrees with the cover sitting on it. Create the palette state *inside* the page lambda so there
is one per page, key the animatable on the page's track id so a recycled page starts from a known
colour rather than the previous track's, and feed it from the image's own success callback:

```kotlin
// adapted
val pagePaletteState = rememberPaletteState()
val pageColour = remember(pageTrack?.videoId) { Animatable(Color.Black) }
LaunchedEffect(pagePaletteState, pageTrack?.videoId) {
    snapshotFlow { pagePaletteState.palette }
        .distinctUntilChanged()
        .collectLatest { pageColour.animateTo(it.dominantOrAccent()) }
}
// …and in the adjacent-page image:
AsyncImage(
    model = staticThumb,
    onSuccess = { state -> scope.launch { pagePaletteState.generate(state.result.image.toBitmap()) } },
    …
)
```

`collectLatest` matters: palette extraction can produce a second result while the first colour is
still animating, and a plain `collect` queues the animations so the backdrop walks through stale
colours instead of jumping to the current one.

**Compose the neighbours before they are needed.** A pager that composes only the visible page has
to fetch the neighbour's image, decode it and extract its palette *during* the swipe, so the page
arrives grey and colours in afterwards. One page of look-ahead is enough and is the cheap fix.

**Keep the cover slot in the layout even when the video hides it.** Hide it with alpha, not by
removing it: the slot is what places the cover at the same vertical position on every page, and a
page that omits it lays out differently, so the covers on either side of a video page sit at
different heights while sliding past.

**Make the scrim span the whole page and express its stops as fractions of it.** The page is
usually taller than the visible area, or offset by a parent that scrolls or drags — so a
fixed-height box pinned to the page's bottom edge is pinned to a line the user cannot see, and the
video shows through underneath the controls. A full-page box whose gradient reaches full opacity
before the visible bottom is anchored to the one quantity you know. Expect two of them, crossfaded:
a heavy one while the controls are up (they have to be readable), and a light one while they are
hidden (the video should be visible) — same geometry, different stops.

**Wire the tap onto the page, not onto a sibling overlay.** A transparent clickable box laid over
the pager competes with it for the pointer and swallows the drag, which is the "the pager cannot be
swiped" report. Putting a `clickable(enabled = …, indication = null)` on the page root leaves the
gesture inside the pager's own subtree, where the drag reaches the pager normally. Enable it only
where the tap means something — over the video, not over a plain cover.

**What *reserves* space over the pager must be pointer-inert.** The chrome itself may take taps — a
top bar is supposed to. The screen's top bar and its info column typically sit above the pager in
the same box and reserve the cover's space with a spacer, and that works only as long as those
reservations really are inert: a spacer has no pointer input and drags fall through it, but a
background with a clickable, a card, or anything with its own gesture modifier becomes a hole in
the swipe area that is very hard to see in a screenshot.

**On desktop the video layer is a different problem entirely.** A native engine's frames should not
be blitted onto an embedded heavyweight component inside the page — that component draws above
every node regardless of z-order, so the scrim and cover disappear behind it, and it repositions a
frame late while the pager slides. `compose-desktop-video-no-swingpanel` covers the shape that
works.

## Verifying it

1. `grep -rn --include="*.kt" "HorizontalPager(\|VerticalPager(" .` — the artwork stack must show
   **one** pager. A second one on the same screen is the desync.
2. `grep -rn --include="*.kt" "clipToBounds()\|beyondViewportPageCount" .` — expect the clip on the
   page root and the look-ahead count on the pager itself; a clip further out (on the screen, say)
   does not stop page-to-page bleed.
3. `grep -rn --include="*.kt" "rememberPaletteState()" .` — indentation tells you which ones are
   per-screen and which is inside the page lambda. A screen with a pager and only a screen-level
   palette state is drawing every page in the current track's colour.
4. By hand, and slowly — drag to about a third of a page and hold there, which is where all of
   these show: the backdrop, video and cover must move as one; no part of the outgoing page may
   appear over the incoming one; the incoming backdrop must already carry its own colour; and the
   bottom edge of the screen must stay opaque behind the controls throughout. Then let go and
   confirm the swipe still drags at all after any overlay is added above the pager.
