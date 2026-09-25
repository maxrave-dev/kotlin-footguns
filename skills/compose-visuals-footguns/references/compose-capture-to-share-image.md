---
name: compose-capture-to-share-image
description: Render a composable off-screen into an ImageBitmap so a button can save or share it as a picture — a capture primitive ported into common code rather than pulled in as a platform-only dependency, a max-width ceiling standing in for a fixed output size, artwork that has to already be resolved before the button is even reachable, and an Android MediaStore save gated behind a permission that the same feature's Desktop save never needs. Use when a "share as image" feature exports a blank or half-drawn picture, when the exported picture comes out a different size on every device, or when saving works on some Android versions and fails silently on others.
---

# Capturing a composable to a shareable image

Three pieces, each an expect/actual pair except the capture itself:

1. A `capturable()` modifier plus `CaptureController` — common code, no platform split — that
   records a composable's own draw pass into a `GraphicsLayer` and hands it back as an `ImageBitmap`
   on demand.
2. `ImageBitmap.toPngByteArray()` — PNG, not whatever format the app's existing bitmap-to-bytes
   function already produces.
3. `saveImageToDevice()` / `shareImage()` — MediaStore plus a share sheet on Android, a downloads
   write plus "reveal in the file manager" on Desktop.

```kotlin
fun Modifier.capturable(controller: CaptureController): Modifier = this then CapturableModifierNodeElement(controller)

// inside the modifier node
override fun ContentDrawScope.draw() {
    currentGraphicsLayer.record { this@draw.drawContent() }
    drawLayer(currentGraphicsLayer)
}
```

The content draws exactly as before — the layer is recorded, then drawn straight onto the visible
canvas — so attaching this to a node changes nothing about how it looks until something actually
calls `captureAsync()`.

## Traps

**A capture library with no Kotlin Multiplatform metadata may still be portable — check what it
imports before ruling it out.** A well-known capture library for this exact job ships a single
Android `.aar` with no KMP metadata, so a KMP build's non-Android target cannot resolve it as a
dependency — yet its code is one dead Android import on a KDoc reference and nothing else; every call
that runs is `androidx.compose.ui.graphics.layer`, already common-code-safe. Reading the small number
of files it takes to port a rejected dependency beats assuming "Android-only artifact" means
"Android-only code" and writing the mechanism from scratch.

**The capture request travels through a `Channel`, not a hot `Flow`.** A request fired the instant a
controller is created can arrive before the drawing node attaches and starts collecting; a hot
`SharedFlow` drops that emission and the caller's `Deferred` never completes — it hangs, silently,
with no exception to grep for. An unbounded `Channel` buffers it instead, so whichever comes first —
the attach or the request — the other still gets served:

```kotlin
private val requests = Channel<CaptureRequest>(capacity = Channel.UNLIMITED)
```

**Assuming the capture needs a fixed pixel size is backwards — a max-width ceiling is what makes the
image legible on every device.** A literal fixed width clips on a phone smaller than it and wastes
space on one larger. Give the captured composable a ceiling (`Modifier.widthIn(max = ...)`) instead
and let the capture take whatever width composition produced. The ceiling's job is capping wide
windows, not scaling every device differently: this codebase's own `ShareLyricsCardMaxWidth = 340.dp`
KDoc notes 340dp does not fit a 360dp phone's 20dp gutters, so a phone and a tablet alike land on the
identical 340dp card once the window clears ceiling-plus-gutters — dp size stops moving there, and
only density varies further. Only a window narrower than that actually shrinks the card.

**The image handed to the captured subtree must already be resolved before the share button is even
reachable.** A capture fires synchronously off a click; a `Painter` or async image loader that is
still fetching over the network at that instant gets captured as whatever it draws while empty — a
blank square, not a retry. The fix is not "await the load inside the capture flow": it is structural.
Pass the composable an `ImageBitmap` that some other part of the same screen already resolved for a
different purpose (a blurred backdrop, a dominant-color scan) — the capture entry point does not
exist on a screen where nothing has decoded the artwork yet, so there is nothing left to wait for.

**A capture is the card, never the chrome around it.** The composable wrapped in `capturable()` must
be exactly the surface you intend to hand someone — a progress bar or a save/share row rendered above
or below it is not part of the picture the user meant to send. Apply the modifier to the innermost
content node, not to a container that also lays out controls.

**Convert to PNG through a new function, not by changing what the existing one returns.** Flat colour
behind crisp text is exactly what JPEG's block-based encoding ring-artifacts hardest, and JPEG has no
transparency — a rounded corner comes out filled black instead of clipped. If an existing
`toByteArray()` already returns JPEG bytes and something else in the app still calls it, redefining
its format silently changes every existing caller's output. Add `toPngByteArray()` alongside it.

**Saving to shared storage and sharing through the app's own cache are different trust boundaries, and
only one of them can be refused.** Android's share path writes to the app's cache directory and hands
a `FileProvider` URI to the system chooser — no permission involved, because nothing left app-private
storage. Saving inserts a row into `MediaStore.Images`, which needs a runtime-granted
`WRITE_EXTERNAL_STORAGE` only below API 29; scoped storage from API 29 on lets an app insert its own
new image with no permission at all. Cap the manifest declaration to match
(`android:maxSdkVersion="28"`) — an uncapped permission next to code that only ever requests it below
29 is a declaration nothing in the app can still trigger, and one a permission review answers for on
every OS version regardless. `app-backup-to-zip-mediastore` writes the same zero-permission MediaStore
path on API 29+; this feature is the one that also has to carry the pre-29 half.

**Desktop has no share sheet and no reliable "reveal and select this exact file."** The honest
substitute is: write the file to the downloads folder, then open its containing folder. `Desktop.open`
is tried first but is not guaranteed to work even when correctly probed at start-up — see
`compose-desktop-runtime-hardening` for why that probe has to run before any native library load — so
a per-OS command fallback belongs behind it: `open -R <file>` on macOS, `explorer /select,<file>` on
Windows, and on Linux just the containing folder via `xdg-open`/`gio open`, because no Linux file
manager agrees on a flag for "open this folder with that one file selected."

## Verifying it

Run these from the app repository root — paths below are this codebase's; adapt them to your layout.

1. **The shared capture code has no platform import** — the "ported, not Android-only" claim:

   ```bash
   grep -n "^import android\.\|^import java\.awt" composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/capture/Capturable.kt
   ```

   Pass condition: no output. The escaped dot matters — `android` without it also matches every
   `androidx.*` import, which is common-code-safe and not what this check is for.

2. **The composable inside the capture region never loads its own image:**

   ```bash
   grep -n "AsyncImage\|rememberAsyncImagePainter\|SubcomposeAsyncImage" composeApp/src/commonMain/kotlin/com/maxrave/simpmusic/ui/component/lyrics/ShareLyricsCard.kt
   ```

   Pass condition: no output — artwork must arrive as an already-decoded bitmap parameter.

3. **The manifest permission and the runtime gate agree** (cwd `androidApp/src/main` for this one):

   ```bash
   grep -A1 "WRITE_EXTERNAL_STORAGE" AndroidManifest.xml
   ```

   Pass condition: `android:maxSdkVersion` appears in that tag, at the same API level your runtime
   check branches on — a bare declaration with no ceiling is the two drifting apart.

4. **PNG and the app's existing byte-array function are two functions, not one that changed shape:**

   ```bash
   grep -rn "toByteArray()\|toPngByteArray()" --include="*.kt" . | grep -v '/build/'
   ```

   Pass condition: call sites for both names exist somewhere in the tree — a caller still on the old
   name depends on the old format, which is why it has to keep working.

5. Capture the same screen at a window narrower than the ceiling plus its own gutters (a 360dp phone)
   and one wider (a tablet). The narrow capture's dp width must come in under the ceiling; the wide
   one must land exactly on it — two wide captures differing only by density is correct, not a bug.
