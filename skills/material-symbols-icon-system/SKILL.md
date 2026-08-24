---
name: material-symbols-icon-system
description: Ship every icon as a generated ImageVector extension property on one receiver object, fetched from the icon font's own Compose generator, so the bytecode shrinker can drop the ones you never reference. Covers the generator request and its axis parameters, the edits that turn a generated file into an extension property, the filled/unfilled pairing for state icons, and which icons must stay as drawable resources. Use when adding or replacing an icon, when a set has drifted into mismatched weights and corner styles, or when a type error reports an ImageVector where a Painter was expected.
---

# A generated icon set as extension properties

One file per icon, one extension property per file, all hanging off a single empty receiver
object you own:

```kotlin
// adapted — this is the generated file, after the four edits below
package com.example.app.ui.icon

@Suppress("CheckReturnValue")
val AppIcons.ArrowForwardIos: ImageVector
  get() {
    if (_ArrowForwardIos != null) return _ArrowForwardIos!!
    _ArrowForwardIos = ImageVector.Builder(
        name = "ArrowForwardIos",
        defaultWidth = 24.dp, defaultHeight = 24.dp,
        viewportWidth = 24f, viewportHeight = 24f,
        autoMirror = true,
      ).apply { path(fill = SolidColor(Color.Black), …) { … } }.build()
    return _ArrowForwardIos!!
  }

private var _ArrowForwardIos: ImageVector? = null
```

`AppIcons` is yours to name; it is an `object` with no members. Call sites read
`AppIcons.ArrowForwardIos`, mirroring how the framework exposes `Icons.Rounded.*` — but nothing is
pulled in that you did not ask for. Note the generated fill: **opaque black**, which is what makes
the tinting trap below unavoidable rather than stylistic.

## Fetching one

The font's own service renders the Compose source directly, so there is no SVG-to-vector step:

```bash
curl -sfL --compressed \
  "https://fonts.gstatic.com/render/v1/Material+Symbols+Rounded/24dp/<symbol_name>.kt?var=opsz,wght,FILL,GRAD,ROND@24,400,1,0,50" \
  -o <PascalName>.kt
```

Then four edits: repoint the `package`; change `public val <symbol_name>` to
`val AppIcons.<PascalName>`; rename the backing field `_<symbol_name>` and the `name =` string to
match; add `autoMirror = true` inside the builder for glyphs that must flip in a right-to-left layout
(arrows, sort, ordered lists).

Keep the axis values byte-identical across the whole set — optical size, weight, grade, roundness.
They are what makes a hundred unrelated glyphs read as one family, and one icon fetched at a
different weight is visible at a glance beside its neighbours.

## Traps

**The extension property is what lets the shrinker drop unused icons — never aggregate them.** Each
`val AppIcons.X` compiles to its own static accessor, reachable only through direct references to
*that* accessor, so an icon no call site names is referenced by nothing and R8/ProGuard drops it,
vector data included. A `mapOf("play" to …)` or a `when (name) { … }` returning icons references
*every* accessor from one live method, so the whole set becomes reachable and ships. This is the one
refactor that looks like tidying and is not.

**Every icon needs its own import.** An extension property is resolved by import, not by receiver —
importing the `AppIcons` object alone leaves `AppIcons.PlayArrow` unresolved. That is a compile-time
resolution rule, distinct from the shrinker's reachability rule above, and it happens to push the
same way: naming each icon at each call site is what an aggregate would take away.

**`Image` does not tint; `Icon` does.** Both accept an `ImageVector` and both compile, so the choice
looks like taste. It is not: `Icon` tints from `LocalContentColor`, while `Image` draws the authored
colour — opaque black, as the generated file above shows — so on a dark surface it is an invisible
icon with no warning anywhere. This is the migration's characteristic late defect: a drawable carried
its own fill, so `Image` was correct for it, and swapping in a monochrome vector removes the colour
while nothing else on the line changes. Expect them in batches — one sweep found a whole sheet file's
worth in a single commit — and expect them to pass review, since the diff only replaced an argument.
Step 5 below counts yours. Default to `Icon`; where `Image` is genuinely wanted, name the tint:

```kotlin
Image(imageVector = AppIcons.Delete, contentDescription = "Delete",   // adapted
      colorFilter = ColorFilter.tint(surfaceColors().content))
```

**`ImageVector` is not a `Painter`.** `Icon` and `Image` have overloads for both, which is why the
common cases compile and hide the distinction. These do not, and each needs `rememberVectorPainter`:

- an async image loader's `placeholder =` / `error =` slots
- anything drawn inside a `DrawScope` (`with(painter) { draw(size) }`)
- any composable of your own whose parameter is typed `Painter`

**Do not bulk-replace `painterResource(Res.drawable.X)` with a regex.** The same pattern appears
inside `Painter`-typed arguments, which then fail to type-check, and a multi-line
`painterResource(\n  Res.drawable.X,\n)` becomes the valid-but-wrong `painterResource(AppIcons.X)`.

**Use the unfilled variant only for the "off" half of a state pair.** Fetch with `FILL=1` by default;
refetch with `FILL=0` for the outline member of a pair (`FavoriteBorder`, `AddCircleOutline`,
`DownloadForOfflineOutlined`). At `FILL=1` both halves render identically and the distinction goes.

**Do not convert an icon whose colour carries meaning.** A generated symbol is monochrome and gets
tinted by the caller; a resource whose fill colour *is* the state — a blue "downloaded" tick, a red
"liked" heart — has none. Those stay drawable resources, as do logos and bitmap placeholders.

**Confirm the symbol name before assuming a mapping.** The authority is the codepoint list shipped
beside the variable font — for Material Symbols, `google/material-design-icons`, file
`variablefont/MaterialSymbolsRounded[…].codepoints` (the bracket spells the axes), one
`name codepoint` pair per line, so `grep` answers it. Legacy names such as `favorite_border` still
resolve; plausible ones like `person_add_alt_1` do not.

**The response is gzip-encoded even when the request asks for identity.** Use `curl --compressed`, or
sniff the `\x1f\x8b` magic bytes and inflate in a script — otherwise the `.kt` on disk is binary.

## Verifying it

All read-only; run from the repository root, substituting your icon package path and receiver-object
name for `ui/icon` and `AppIcons`.

1. **One extension property per file.** Only the receiver-object declaration should be listed:
   `find . -path '*/ui/icon/*.kt' -exec grep -L '^val AppIcons\.' {} +`
   → observed: a single hit, the object declaration file.
2. **No axis drift.** Every generated icon carries the same nominal size:
   `find . -path '*/ui/icon/*.kt' -exec grep -Hn 'defaultWidth\|defaultHeight' {} + | grep -v '24\.dp'`
   → observed: empty.
3. **Nothing aggregates the set.**
   `find . -path '*/ui/icon/*.kt' -exec grep -Hn 'mapOf(\|when (' {} +`
   → observed: empty. A hit here means the shrinker is now keeping every icon.
4. **No `ImageVector` in a `Painter` slot.**
   `grep -rn 'placeholder = AppIcons\.\|error = AppIcons\.\|painterResource(AppIcons\.' --include='*.kt' .`
   → observed: empty.
5. **Every `Image` carrying a vector names its tint.** Count the calls, and how many omit one:
   ```bash
   grep -rn -A6 'Image($' --include='*.kt' . | grep -v '/build/' | awk '
     /imageVector/ { v=1 } /colorFilter/ { f=1 }
     /^--$/ { if (v) { n++; if (!f) u++ }; v=0; f=0 }
     END { if (v) { n++; if (!f) u++ }; printf "Image(vector): %d, untinted: %d\n", n+0, u+0 }'
   ```
   Read each untinted one against the surface it sits on; it is fine only where that surface is
   light. A non-zero count right after a migration is where the invisible icons are.

To confirm the shrinker actually benefits, build with shrinking on and list the retained icon
classes in the mapping output — see `r8-proguard-desktop-survival` for reading that output.
