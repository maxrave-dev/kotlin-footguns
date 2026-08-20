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
`AppIcons.ArrowForwardIos`, mirroring how the framework exposes `Icons.Rounded.*` — but nothing
is pulled in that you did not ask for.

## Fetching one

The font's own service renders the Compose source directly, so there is no SVG-to-vector
conversion step:

```bash
curl -sfL --compressed \
  "https://fonts.gstatic.com/render/v1/Material+Symbols+Rounded/24dp/<symbol_name>.kt?var=opsz,wght,FILL,GRAD,ROND@24,400,1,0,50" \
  -o <PascalName>.kt
```

Then four edits: repoint the `package`; change `public val <symbol_name>` to
`val AppIcons.<PascalName>`; rename the backing field `_<symbol_name>` and the `name =` string to
match; add `autoMirror = true` inside the builder for glyphs that must flip in a right-to-left
layout (arrows, sort, ordered lists).

Keep the axis values byte-identical across the whole set — optical size, weight, grade, roundness.
They are what makes a hundred unrelated glyphs read as one family, and a single icon fetched at a
different weight is visible at a glance next to its neighbours.

## Traps

**The extension property is what lets the shrinker drop unused icons — never aggregate them.**
Each `val AppIcons.X` compiles to its own static accessor, reachable only through direct references
to *that* accessor. An icon no call site names is therefore referenced by nothing and R8/ProGuard
drops it, vector data included. A `mapOf("play" to …, "pause" to …)` or a `when (name) { … }`
returning icons references *every* accessor from one live method, so the whole set becomes reachable
and the whole set ships. This is the one refactor that looks like tidying and is not.

**Every icon needs its own import.** An extension property is resolved by import, not by receiver —
importing the `AppIcons` object alone leaves `AppIcons.PlayArrow` unresolved. That is a compile-time
resolution rule, distinct from the shrinker's reachability rule above; it happens to push the same
way, since naming each icon at each call site is exactly what an aggregate would take away.

**`ImageVector` is not a `Painter`.** `Icon` and `Image` have overloads for both, which is why the
common cases compile and hide the distinction. These do not, and each needs
`rememberVectorPainter(AppIcons.X)`:

- an async image loader's `placeholder =` / `error =` slots
- anything drawn inside a `DrawScope` (`with(painter) { draw(size) }`)
- any composable of your own whose parameter is typed `Painter`

**Do not bulk-replace `painterResource(Res.drawable.X)` with a regex.** The same pattern appears
inside `Painter`-typed arguments, which then fail to type-check, and a multi-line
`painterResource(\n  Res.drawable.X,\n)` call becomes the syntactically valid but wrong
`painterResource(AppIcons.X)`. Convert call sites in reviewed batches.

**Use the unfilled variant only for the "off" half of a state pair.** Fetch with `FILL=1` by
default; refetch with `FILL=0` for the outline member of a pair (`FavoriteBorder`,
`AddCircleOutline`, `DownloadForOfflineOutlined`). At `FILL=1` both halves render identically and
the state distinction disappears, silently.

**Do not convert an icon whose colour carries meaning.** A generated symbol is monochrome and gets
tinted by the caller; a resource whose fill colour *is* the state — a blue "downloaded" tick, a red
"liked" heart — has no equivalent. Those stay as drawable resources, as do your logos and any
bitmap placeholder. If a shared symbol must carry that colour, pass it explicitly at the call site.

**Confirm the symbol name before assuming a mapping.** The authority is the codepoint list shipped
beside the variable font — for Material Symbols, the `google/material-design-icons` repository, file
`variablefont/MaterialSymbolsRounded[…].codepoints` (the bracket spells out the axes). It is one
`name codepoint` pair per line, so `grep` answers the question. Legacy names such as
`favorite_border` and `thumb_up_alt` do still resolve; plausible ones like `person_add_alt_1` do not.

**The response is gzip-encoded even when the request asks for identity.** Use `curl --compressed`,
or sniff the `\x1f\x8b` magic bytes and inflate when fetching from a script — otherwise the `.kt`
file on disk is binary.

## Verifying it

All four are read-only greps; run them from the repository root, substituting your icon package
path and your receiver-object name for `ui/icon` and `AppIcons`.

1. **One extension property per file.** Only the file declaring the receiver object should be
   listed:
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

To confirm the shrinker actually benefits, build with shrinking on and list the retained icon
classes in the mapping output — see `r8-proguard-desktop-survival` for reading that output.
