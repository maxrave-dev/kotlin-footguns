---
name: remoteviews-bitmap-budget
description: Every bitmap a home-screen widget draws is copied into the RemoteViews payload handed across a process boundary, and the platform rejects an update whose bitmaps exceed a fixed budget — so decoding each image at the size it is drawn is not an optimisation, it is what keeps the widget on screen. Covers the pixel arithmetic that decides how many images fit, why the failure is invisible outside the system log, and why every surface reading the same image must agree on both its cache key and its decode size. Android only. Use when a widget shows the framework's error placeholder, when it renders on one device and not another, or when adding one more tile empties the whole widget.
---

# A widget's images travel by value, and the trip is capped

Android only. A widget is drawn out of process: your code builds a `RemoteViews` tree, the system
hands it to the launcher, and the launcher inflates it. Anything that is not a resource id — which
means every decoded bitmap — is **copied into that payload**. The platform enforces a ceiling on the
bitmap memory one widget update may carry, and an update over it is rejected outright.

Rejected means the widget stops showing your layout and starts showing the framework's error
placeholder. It does not throw where you can catch it, and the real cause appears only in the
system log.

## The arithmetic, which is the whole decision

A decoded bitmap costs `width × height × 4` bytes at eight bits per channel. Nothing about the
source file matters — not its byte size, not its compression. Only its pixel dimensions.

```bash
# adapted — substitute your own tile count and source dimension
python3 -c 's=1145; n=10; print(f"{n} tiles at {s}px = {n*s*s*4/1e6:.1f} MB")'
# 10 tiles at 1145px = 52.4 MB
python3 -c 's=256; n=10; print(f"{n} tiles at {s}px = {n*s*s*4/1e6:.1f} MB")'
# 10 tiles at 256px = 2.6 MB
```

Against a budget in the region of 20 MB, that is the difference between *rejected* and *four percent
used*. Put the other way round: one image at ~1145 px costs 5.2 MB, so **fewer than four of them fit
in the whole budget** — a widget showing a row of five is already over before you add a second row.

Decode at draw size and the same widget is nowhere near the ceiling:

```kotlin
// adapted — the decode size is a constant next to the tile size it serves, not a magic number
private val TILE_SIZE = 58.dp
private const val TILE_DECODE_PX = 256   // still oversamples a 58dp tile at 3x; see the note below

suspend fun Context.loadTile(url: String?, cacheKey: String, sizePx: Int): Bitmap? { … }
```

256 px is chosen to *oversample* deliberately: a 58 dp tile is 174 px on a 3x screen, and launchers
scale widget cells. Sizing exactly to the nominal dp is the one direction that produces a visibly
soft tile.

## Traps

**The failure looks like a layout bug, not a memory bug.** The widget goes blank or shows a generic
"can't load" plate — the same thing a crash in the composition produces, and the same thing a
missing permission produces. Reach for the system log before re-reading the layout; nothing in your
own logging will mention size.

**It is device-dependent, so "it works here" proves nothing.** The budget is derived from the
display, and the same widget can pass on a small screen and fail on a large one, or pass in one
launcher's cell size and fail in another's. A widget that renders on the development device has not
been tested.

**Count every bitmap in the tree, including the ones you forgot are bitmaps.** The large hero image,
each tile, and any background you drew as a bitmap rather than a resource all land in the same
payload. Adding one tile to a row is a budget change.

**A bitmap you decode but never draw is free — and that is a trap in the other direction.** An image
loaded only to sample a colour from never enters the payload, so it does not count against the
budget. It is also the one place a *larger* decode is defensible. Do not "optimise" it into the same
constant as the drawn tiles without deciding that separately.

**One key *and* one decode size per logical image, travelling together.** The key names the entry on
disk — the *encoded* bytes. The pixels come from the request's `size(...)`, and the in-memory
identity already includes that size, so the two are not interchangeable: one key with two sizes still
produces **two bitmaps**, and a surface deriving a colour from one samples different pixels and hands
back a **different colour** — two widgets on one home screen tinting themselves differently from the
same source. Two keys at the *same* size drift not at all; they only duplicate a disk entry. Sharing
the key is necessary and not sufficient. Name the pair, and pass both together, everywhere:

```kotlin
// adapted — every surface wanting the large decode of this image asks by the same name AND size
loadTile(url, cacheKey = url + "BIGGER", sizePx = TILE_DECODE_PX)
```

**Hardware-backed bitmaps are unusable here for two separate reasons.** They cannot be serialised
into the payload, and their pixels cannot be read for palette extraction. Turn the option off on
every request whose result the widget draws or samples — the failure is a blank image and a default
colour, with nothing in your log.

**Decoding at draw size is not a substitute for limiting the count.** Halving the decode buys a
factor of four; adding tiles costs linearly. A design that wants twenty tiles needs a smaller decode
*and* an argument about why twenty tiles are legible at that size.

## Verifying it

1. **Count the bitmaps the widget actually draws, and the decode size of each.** Every call that
   produces a bitmap for the tree, plus the constants feeding it:

   ```bash
   grep -rn 'loadBitmap(\|_DECODE_PX' --include='*.kt' <widget-source-dir>
   ```

   Multiply out with the snippet above using your own count. Any total in the tens of MB is already
   broken on some device.

2. **Every drawn bitmap must come from a sized request.** A call with no size argument decodes at
   the source's native dimensions. Give it a generous context window — the size call is often the
   last line of a builder chain:

   ```bash
   grep -rn -A16 'ImageRequest' --include='*.kt' <widget-source-dir> \
     | grep -E '\bsize\(|allowHardware\('
   ```

   Pass condition: one `size(...)` and one `allowHardware(false)` per request whose bitmap is drawn
   or sampled. Expect this to find at least one request with the hardware flag and **no** size —
   that shape survives only while it is a single image, and it is the one that breaks the day a
   second is added beside it.

3. **Confirm key and decode size agree across surfaces.** List both in one pass — the key alone
   tells you nothing (`-v` drops layout sizing, which is in `dp`, not pixels):

   ```bash
   grep -rnE 'diskCacheKey|_DECODE_PX|\.size\(' --include='*.kt' <widget-source-dir> | grep -v '\.dp)'
   ```

   One logical image read by two surfaces must show the same key **and** the same size on both. One
   key against two sizes — or against a size and no size at all, which decodes natively — is the
   colour drift already happening, and it is what a comment saying "shared key, so every surface
   reads the identical bitmap" hides: the sizes live in other files and nobody lines them up.

4. **Watch the system log while placing the widget**, filtering for the widget service rather than
   your own tag. A rejected update is reported there and nowhere else; if the widget renders and the
   log is silent, you are inside the budget on *this* device.

5. **Place every widget you ship on one home screen at the largest cell size the launcher offers,
   on the largest screen you support.** That is the configuration the budget is tightest in, and it
   is the one nobody sets up by accident.

Layout-side companions: `glance-layout-vocabulary` for sizing the tiles this budget pays for, and
`glance-widget-over-existing-state` for where the decode belongs in the update cycle.
