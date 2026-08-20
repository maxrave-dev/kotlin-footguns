---
name: artwork-palette-theming
description: Drive a screen's colours from its artwork — which extracted swatch to use for an accent versus for a large page background, luminance-adaptive darkening so overlaid text stays readable on any image, the hex parsing helper this needs, and what to do when extraction returns nothing or there is no artwork at all. Use when a page background comes out lurid or unreadably light, when it flashes or changes while scrolling a list, or when a screen renders transparent or invisible instead of tinted.
---

# Artwork palette theming

Palette extraction gives a handful of swatches per image (vibrant, muted, dominant, and light/dark
variants). Choosing between them decides whether a screen looks designed or broken, and the right
choice differs between a small accent and the page behind the text.

## Accent versus background

An **accent** — a section tint, a chip, a stripe, a shadow colour — wants a *vivid* swatch, and a
priority walk so something is always returned:

```kotlin
// adapted: the real code nests these. `const val NONE = 0` — the "absent" default every getter takes
var argb = palette.getDarkVibrantColor(NONE)
if (argb == NONE) argb = palette.getDarkMutedColor(NONE)
if (argb == NONE) argb = palette.getVibrantColor(NONE)
if (argb == NONE) argb = palette.getMutedColor(NONE)
if (argb == NONE) argb = palette.getLightVibrantColor(NONE)
if (argb == NONE) argb = palette.getLightMutedColor(NONE)
```

A **page background** wants the opposite: the *dominant* swatch, which is the image's overall tone by
pixel area. A vivid swatch can be a tiny saturated patch — hair, lipstick, a logo — and using it
turns a whole page that colour, which is where "why is this portrait's page brick red" comes from.

```kotlin
// adapted
fun Palette.toImmersiveBackground(): Color {
    val rgb = getDominantColor(NONE).takeIf { it != NONE }
        ?: getMutedColor(NONE).takeIf { it != NONE }
        ?: getVibrantColor(NONE).takeIf { it != NONE }
        ?: return Color.Black
    val base = Color(rgb)
    val luminance = 0.299f * base.red + 0.587f * base.green + 0.114f * base.blue
    return lerp(base, Color.Black, 0.35f + 0.45f * luminance)
}
```

The darkening is what makes it work on *any* image rather than on the images you tested. Read the two
constants as a floor and a slope: darken every background at least this much, and a light one this
much more again, so light artwork cannot produce a page white text disappears on. Tune them against
your two extremes — the lightest and darkest cover you can find — no single constant satisfies both.

## Traps

**The "no swatch" sentinel is whatever you passed in, and it is a real colour.** Absence has no
representation of its own — `getDominantColor(NONE)` hands your own `NONE` straight back — so "no
swatch" and "the colour `0x00000000`" arrive as the same 32 bits. Zero is the right choice *because*
swatches are always opaque (androidx `palette`'s quantizer builds them through `Color.rgb`, which ORs
`0xFF000000`), so it cannot collide with a real swatch, whereas the tempting "safer" opaque black
collides with every genuinely black one. What zero does not escape is the trap below: it still draws.

**That same sentinel handed to a colour constructor is transparent, not black.** `Color(argb: Int)`
packs the whole 32-bit value as ARGB and supplies no alpha of its own, so `Color(0)` has alpha 0 and
draws nothing. Return an explicit `Color.Black` on the everything-failed path — the one nobody tests.

**Extraction returning nothing is normal, not an error.** Near-monochrome art, flat art and very
small images produce no swatch for a given profile, for a meaningful slice of any library — which is
the whole reason the walk above exists. Do not log it as a failure.

**No artwork means the palette never even runs.** With no image the success callback that feeds the
extractor never fires, so the palette stays null forever. Deriving the fallback from the same
generator that drew the placeholder keeps the two in agreement — `deterministic-title-placeholder-painter`:

```kotlin
// adapted
val background = palette?.toImmersiveBackground() ?: run {
    val titleColors = gradientFromTitle(title)
    val base = if (titleColors.size >= 2) lerp(titleColors[0], titleColors[1], 0.5f)
               else titleColors.firstOrNull() ?: Color.Black
    lerp(base, Color.Black, 0.3f)
}
```

**Regenerate on the image's identity, not on the bitmap.** In a lazy list the header scrolls out, is
recycled, re-mounts and fires its callback again — re-running extraction and flashing the page to a
slightly different colour. Keep the key you already have and skip when it is unchanged:

```kotlin
// adapted
var paletteGeneratedFor by remember { mutableStateOf<String?>(null) }
LaunchedEffect(bitmap) {
    val bm = bitmap
    if (bm != null && paletteGeneratedFor != currentImageKey) {
        paletteState.generate(bm)
        paletteGeneratedFor = currentImageKey
    }
}
```

**Clamp to `0f..1f`, not to 255.** Compose colour components are floats, so `min(red * factor, 255f)`
looks like a clamp and never fires — a leftover from integer colour APIs. Use `coerceIn(0f, 1f)`.

**Parsing hex needs the alpha byte added, and needs to survive garbage.** Colours arrive from remote
metadata and user settings, so parse to a nullable — and six digits must be OR-ed with an opaque
alpha or you get an invisible colour, while eight already carry one:

```kotlin
// adapted
fun String.hexToColorOrNull(): Color? = runCatching {
    val clean = removePrefix("#")
    val argb = when (clean.length) {
        6 -> 0xFF000000L or clean.toLong(16)
        8 -> clean.toLong(16)
        else -> return null
    }
    Color(argb)
}.getOrNull()
```

## Verifying it

1. Every extraction call site, to check each keys its regeneration on the image identity:

   ```bash
   grep -rn --include='*.kt' -A6 "\.generate(" . | grep -v '/build/' | grep -E "generate\(|GeneratedFor|LaunchedEffect"
   ```

2. Zero sentinels around colour APIs. Deliberately unanchored, so it catches a literal `Color(0)`
   and any `…Color(0)` getter given a zero default — every hit is a place where "no colour" and
   "transparent black" are the same value:

   ```bash
   grep -rn --include='*.kt' -E "Color\(0x?0+\)|Color\(0\)" . | grep -v '/build/'
   ```

3. Clamps against integer colour ranges in float colour code:

   ```bash
   grep -rn --include='*.kt' -E "(min|coerceAtMost|coerceIn)\([^)]*25[56]f" . | grep -v '/build/'
   ```

4. By eye, against the two extremes rather than an average cover: a near-white artwork and a
   near-black one. Overlay the smallest body text you ship; readable on both means the floor and
   slope are right.
