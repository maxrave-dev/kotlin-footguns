---
name: deterministic-title-placeholder-painter
description: Give items with no artwork a cover of their own by hashing the title into a stable gradient and packaging it, plus measured text and a badge, as a custom Painter you can hand straight to an image loader's placeholder, error and fallback slots — covering what makes the hash actually deterministic, measuring text outside a layout pass, and reporting an intrinsic size. Use when coverless rows all look identical, when a generated colour changes between runs or platforms, when placeholder text spills outside its tile, or when a null image model leaves a blank square.
---

# Deterministic title placeholder painter

Items without artwork need better than a shared grey square: something unique per item, identical
every time, and available synchronously — before, during and instead of a network load. Hashing the
title into a gradient gives all three; a `Painter` lets the loader treat it as an image.

```kotlin
// adapted
private fun gradientFromTitle(title: String): List<Color> {
    val hash = title.hashCode()
    val hue1 = ((hash and 0xFF) / 255f) * 360f
    val hue2 = (((hash shr 8) and 0xFF) / 255f) * 360f
    return listOf(hsvToColor(hue1, 0.7f, 0.9f), hsvToColor(hue2, 0.7f, 0.85f))
}

private class TitlePlaceholderPainter(
    private val size: Size,
    private val title: String,
    private val textLayoutResult: TextLayoutResult,
    private val badge: Painter,
) : Painter() {
    override val intrinsicSize: Size get() = size

    override fun DrawScope.onDraw() {
        drawRoundRect(Brush.linearGradient(gradientFromTitle(title)), size = size,
                      cornerRadius = CornerRadius(16f, 16f))   // this `size` is DrawScope's
        drawText(textLayoutResult, topLeft = bottomStartWithInset(textLayoutResult.size, size))
        val centre = Offset(size.width * 0.9f, size.height * 0.1f)
        drawCircle(center = centre, color = Color.White, radius = size.width * 0.05f)
        translate(left = centre.x - size.width * 0.075f, top = centre.y - size.height * 0.075f) {
            with(badge) { draw(size * 0.15f, alpha = 0.2f) }
        }
    }
}
```

The factory is where the work that must not happen per frame goes:

```kotlin
// adapted; the `remember` around the painter is the fix described under Traps
@Composable
fun rememberTitlePlaceholder(title: String, style: TextStyle, sizeDp: Pair<Dp, Dp>): Painter {
    val density = LocalDensity.current
    val measurer = rememberTextMeasurer()
    val layout = remember(title, style, sizeDp) {
        measurer.measure(
            title,
            style.copy(color = Color.White, textAlign = TextAlign.Start),
            maxLines = 2, softWrap = true, overflow = TextOverflow.Ellipsis,
            layoutDirection = LayoutDirection.Ltr,
            constraints = with(density) {           // tile size MINUS its padding; names required
                Constraints(maxWidth = (sizeDp.first - 32.dp).roundToPx(),
                            maxHeight = (sizeDp.second - 32.dp).roundToPx())
            },
        )
    }
    val badge = painterResource(Res.drawable.badge)
    val px = with(density) { Size(sizeDp.first.toPx(), sizeDp.second.toPx()) }
    return remember(title, layout, badge, px) { TitlePlaceholderPainter(px, title, layout, badge) }
}
```

## Traps

**Determinism is the whole feature, so check what your hash actually promises.** On Kotlin/JVM,
`String.hashCode()` delegates to the JDK's, whose algorithm is written into the platform
specification — stable across runs, machines and JDK versions, which is why it is safe here. That
guarantee is a JVM one: unspecified for Kotlin/Native and Kotlin/JS, silent about non-`String` types.
Add a Native or web target, or persist the colour, and hash the bytes yourself.

**Mask the hash, do not take a remainder of it.** A hash is signed, and `hash % 256` is negative for
roughly half of all inputs — a negative hue that falls out of every branch of an HSV conversion.
`hash and 0xFF` is correct for negative values because it works on the two's-complement bits. Two
hues taken from *adjacent* bytes can also land next to each other and read as flat; for guaranteed
contrast, derive the second hue from the first plus a fixed rotation.

**Measure text in composition; draw in `onDraw`.** `Painter.onDraw` runs every frame it is visible,
so a measurement there allocates and lays out per frame. Measure once, keyed on title, style and
size, and pass the immutable result in. Constrain it to the tile *minus its padding*, or the text is
laid out for the full width and drawn overlapping the edges. There is no layout pass, so positioning
is arithmetic: compute the top-left yourself and add back the inset.

**A `Painter` has no density, so convert before you construct it.** Take `LocalDensity` in the
composable, turn the `Dp` size into pixels there, and hand the painter pixels — reporting that as
`intrinsicSize`, since `Size.Unspecified` gives an image composable nothing to size itself from.

**Inside `onDraw`, `size` is not your `size`.** `onDraw` is declared `DrawScope.onDraw()`, so the
*extension* receiver outranks the dispatch receiver: every unqualified `size` above resolves to
`DrawScope.size`, the size the painter is actually being drawn at — never the constructor property of
the same name. The sample already honours the draw size; the stored one survives only in
`intrinsicSize` (decompile it — the compiled `onDraw` never touches the field). Drawing at the
*stored* size means writing `this@TitlePlaceholderPainter.size`, and mixing the two is the bug: a
`drawRoundRect` at the stored size beside a `drawCircle` centred on `DrawScope.size` comes apart the
first time a caller draws at anything but the intrinsic size.

**Fill all three image slots, because they are three different states.** `placeholder` is "loading",
`error` is "the request failed", `fallback` is "the model was null" — the coverless case this painter
exists for. Setting only `placeholder` leaves those items blank.

**Remember the painter, not just the measurement.** Rebuilding it per composition hands the image
composable a new instance every time, defeating skipping for that call. The originating code
remembers the layout but not the painter, harmless only because that painter holds no state.

**Reuse one generator everywhere the colour must agree.** A detail page tinting its background for a
coverless item must call the same function its tile calls — see `artwork-palette-theming` and
`overflow-tilted-browse-card`.

## Verifying it

1. Each image call site with whichever of the three slots it names, interleaved in file order — an
   `AsyncImage(` line followed by fewer than three slot lines before the next one is missing a state.
   `-[0-9]+-` anchors to a context line, so a bare `error =` in a data class cannot inflate it; widen
   `-A16` where a long `model =` block pushes a call's slots out of the window.

   ```bash
   grep -rn -A16 --include='*.kt' --exclude-dir=build "AsyncImage(" . \
     | grep -E "AsyncImage\(|-[0-9]+-[[:space:]]*(placeholder|error|fallback) ="
   ```

2. Painters constructed in composition without being remembered:

   ```bash
   grep -rn --include='*.kt' -B4 "^\s*return [A-Z][A-Za-z]*Painter(" . | grep -v '/build/'
   ```

3. Signed-hash remainders, the negative-hue bug. Expect **no output**; every hit is a colour that
   is wrong for about half of all inputs:

   ```bash
   grep -rn --include='*.kt' -E "hashCode\(\) *%" . | grep -v '/build/'
   ```

4. Determinism itself, which no grep can check: render the same list twice in one session and across
   a restart, and confirm the colours match both times. Then render a title differing by one
   character — a generator that ignores part of its input passes the first test and fails this one.
