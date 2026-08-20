---
name: compose-desktop-video-no-swingpanel
description: Rendering video frames from a native media engine in Compose Desktop without embedding a heavyweight AWT panel — publish finished frames as immutable snapshots on a StateFlow and draw them with a plain Image, convert off the UI thread, match the engine's pixel byte order, and let the engine decide the fit. Reach for it when embedded video sits on top of everything regardless of z-order, lags a frame behind while scrolling, goes black on one screen the moment a second screen shows the player, comes out with red and blue swapped, or shows black bars that no content-scale can remove.
---

# Compose Desktop video without an embedded panel

Most native media engines expose a **software render path**: you hand it a pixel buffer and a size,
it decodes, scales and letterboxes a frame into that buffer, and you copy it out. The obvious way
to show the result in Compose Desktop is to blit it onto an AWT/Swing component and embed that.
Do not. Publish finished frames as immutable images on a `StateFlow` and draw them with a plain
`Image`; the engine side is identical and the whole embedding bug class disappears.

## Why the embedded-panel route fails

Three separate failures, all structural rather than fixable:

- A heavyweight embedded component is an **overlay**: it draws above every Compose node regardless
  of z-order, so nothing can be placed on top of the video.
- It **repositions one frame late** while the page scrolls — visible as a flicker that exposes
  whatever is behind the window, and worse on a transparent window.
- The toolkit gives a component exactly **one parent**. Two screens that both compose the player
  fight over the single instance and the loser renders black — the "video randomly missing until
  next/previous" report.

An `Image` participates in normal Compose rendering, and any number of screens can collect the same
frame source at once.

## Traps

**Pick the engine pixel format that already matches your image type.** The engine this was mined
from names formats by **byte order at increasing addresses** (a `bgr0`-style name means B at offset
0, G at 1, R at 2, unused at 3) — but that is its convention, not a norm: other render APIs name
packed formats most-significant-byte-first, so check your engine's documentation before trusting
any name. The JVM's packed-integer RGB image type stores a pixel as `0x00RRGGBB`, which on a
little-endian host — every platform desktop Java ships on — occupies memory as B, G, R, unused:
identical to the `bgr0`-style layout, so a bulk read needs no per-pixel fixup. Picking the name
with the opposite convention is exactly what produces the classic red/blue-swapped video.

**Use the packed-integer type WITHOUT alpha.** Engines document the fourth component as
uninitialized — often zero, but not guaranteed. In an ARGB image that byte *is* the alpha channel,
so a garbage zero makes every frame fully transparent. The non-alpha type ignores the high byte.

**Honour the stride alignment the engine asks for, and make the staging buffer stride-wide.**
Padding the row stride up to the requested alignment (commonly 64 bytes) keeps the engine on its
fast path; making the staging array *stride*-wide as well keeps the whole frame one contiguous run,
so it comes out of native memory in a single bulk read. Publish only the leftmost `width` columns —
the padding between the end of one row and the start of the next is explicitly unspecified.

**Publish a new image per frame.** A `StateFlow` conflates equal values, so re-emitting a mutated
image is dropped and the picture freezes. Allocating a fresh snapshot per frame also makes every
published frame immutable, which is what lets any collector convert or draw it on any thread with
no tearing — and it replaces the per-frame blit the UI thread used to do, so the total copy work is
unchanged.

```kotlin
// adapted
val snapshot = BufferedImage(target.width, target.height, BufferedImage.TYPE_INT_RGB)
val out = (snapshot.raster.dataBuffer as DataBufferInt).data
for (y in 0 until target.height) {
    System.arraycopy(target.pixels, y * target.bufferWidth, out, y * target.width, target.width)
}
_frames.value = snapshot
```

**Convert off the UI thread**, and report the box's size back to the source:

```kotlin
var frame by remember(source) { mutableStateOf<ImageBitmap?>(null) }
LaunchedEffect(source) {
    withContext(Dispatchers.Default) {          // the conversion copies pixels
        source.frames.collect { image -> frame = image?.toComposeImageBitmap() }
    }
}
Box(modifier.onSizeChanged { source.setTargetSize(it.width, it.height) }) {
    frame?.let { Image(bitmap = it, contentDescription = null, contentScale = ContentScale.Fit) }
}
```

**The engine decides the fit, not Compose.** It scales *and letterboxes* into exactly the size you
reported, so the black bars are already pixels by the time Compose sees the frame — no
`ContentScale` can remove them. Cropping is the engine's own pan-scan property, and applying it
from a `LaunchedEffect` keyed on the handle **and** the flag re-scales the running video instead of
tearing down and recreating the handle:

```kotlin
// adapted
LaunchedEffect(player, cropToBounds) { player?.setPanscan(if (cropToBounds) 1.0 else 0.0) }
```

`ContentScale` on the `Image` then only matters for the moment after a resize, while the next
correctly-sized frame is still being rendered.

**The engine's update callback fires on a foreign thread and may only signal.** Render APIs
typically forbid calling any of their functions from inside it. Signal a semaphore, and do all
rendering on a thread you own that calls nothing but the render functions. In that loop: use a
**bounded** wait so a stop flag is noticed promptly, then drain the permits — a backlog should
collapse to the newest frame rather than run the loop once per missed frame — and skip the render
call entirely unless the engine reports a new frame or a resize invalidated the buffer, since
software rendering is processor-bound.

**Swap the published source unconditionally, and clear it on detach.** A null-guard around "set the
frame source for the new handle" keeps the *outgoing* handle's source on screen whenever the
incoming track has no video, leaving a dead surface belonging to a handle about to be released —
that is the "black video until next/previous" symptom in its second form. Setting it to null on
detach lets the UI fall back to artwork instead of holding a stale frame.

**Allocate and reallocate on the render thread.** Size changes arrive from Compose layout; keeping
the allocation itself on the render thread keeps native allocation off the UI, and swapping the
whole target object wholesale (rather than mutating width/height in place) means the render loop
and the teardown path can never disagree about dimensions mid-copy.

**Keep the native memory the render parameters point into alive.** The parameter block usually
stores raw pointers into small allocations holding the size, the stride and the format string; the
engine dereferences them on every render call. Fields that look unused are load-bearing — losing
the reference lets the binding free them out from under native code.
