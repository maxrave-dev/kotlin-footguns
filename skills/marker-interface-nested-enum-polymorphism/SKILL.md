---
name: marker-interface-nested-enum-polymorphism
description: Render one heterogeneous list with one composable by tagging unrelated classes with an empty interface, plus a nested enum each implementor answers where the renderer has to branch. Covers when a tag beats a sealed hierarchy, the exhaustiveness you give up in exchange, and the ways an item silently stops rendering. Use when the items come from modules that cannot be sealed into one file, when a newly added item type appears as a blank row nobody noticed, or when two tags want the same accessor name and one class needs both.
---

# A tag interface plus a runtime discriminator

A tag carries no members. It exists so that unrelated classes — persistence rows, search results,
locally created records — can appear in one list and be accepted by one renderer:

```kotlin
interface HomeContentType
interface LibraryType
```

Where the renderer genuinely has to branch, the tag adds a nested enum and one accessor:

```kotlin
interface PlaylistType : HomeContentType, LibraryType {
    enum class Type { REMOTE, RADIO, LOCAL, ALBUM, SERIES }
    fun playlistType(): Type
}
```

```kotlin
@Composable fun ContentTile(data: HomeContentType) { … }   // one renderer, two screens
```

Multiple inheritance is the mechanism, and it is the reason to reach for a tag at all: a tag that
extends two other tags makes each of its implementors renderable by both screens' renderers, without
either screen's list type learning about the other's.

**Choose a tag over a sealed hierarchy when the implementors cannot all live in one module.** A
sealed interface buys exhaustive `when` and costs a closed world — every implementor compiled
together, in one module. When the members are persistence entities, transport results and rows
created by feature code, forcing them into one module inverts the dependency direction the layering
already fixed. When they *can* live together, seal them; the checking is worth more than the reach.

## Traps

**You gave up exhaustiveness, and the price is paid once per field.** A `when (data)` over a tag can
never be exhaustive, so it needs an `else`, and the renderer needs one such `when` for every field it
reads — one composable inspected here branches over the same tag once per field it renders: the
image, its placeholder, its error image, and each line of text. Add an implementor and every one of
them falls to `else` together: it compiles, it renders, and the tile is blank. Keep the branches
adjacent in one `when` returning a small carrier, so an omission is one hole and not one per field.

**The discriminator must be total, or an implementor will answer wrongly.** One tag here declares
`SONG, ALBUM, ARTIST, PLAYLIST`. A series entity implements it, has no member of its own, and so its
accessor returns `PLAYLIST` — compiling, silent, permanent, and unrecoverable downstream. The proof
that this is the enum's fault and not the entity's: that same class also implements a second tag
whose enum *does* have a member for it, and there it answers accurately. **Every new implementor is
a reason to re-check the enum**; adding a member is cheap, and the compiler then points at the `when`
branches that need it.

**Two tags cannot both name their accessor the same.** Each tag's enum is its own nested type, so
`fun objectType(): Type` on two tags means two functions with the same name and parameter list and
different return types. One class can implement at most one of them. The set inspected here only
works because the tag most often combined with the others names its accessor differently — a
constraint nobody wrote down, which the next tag added will break. Give each tag's accessor a name
derived from the tag.

**The tag's name will collide with something.** A tag named for a concept and an unrelated enum
named for the same concept both end up imported in the same file, and every consumer needs an
`import … as` alias. Aliases are fine; discovering the need at the fifth call site is not. Name tags
for their *role in the list* rather than for the concept.

**Cast-and-skip is where items disappear.** `item as? Something ?: return@items` inside a list
builder produces no row, no log and no failure. It is the shape that turns "this type is not handled
yet" into "the list is one shorter than the data". Prefer a branch that renders a visible fallback,
or at minimum reports the unhandled type once.

**`filterIsInstance<Tag>()` narrows a mixed list by silently discarding.** It is the right tool when
the list is genuinely mixed and one section renders one tag — but the discarded remainder is invisible
by construction. Compare the sizes before and after when the list is supposed to be homogeneous.

**A tag pulls same-named types from independent packages into one `when`.** Three classes named
`Content`, from three packages, cannot all be imported, so their branches read as fully qualified
`is some.package.Content ->` lines. That is not a smell to fix — it is the tag doing its job — but it
makes the `when` unreadable at a glance, so keep those branches in the same order everywhere.

## Verifying it

List a tag's implementors together with what each one answers:

```bash
TAG=YourTagInterface
grep -rnE "(:|,)[[:space:]]*$TAG" --include="*.kt" . | grep -w "$TAG"
```

Read every hit that is a *property declaration* rather than a supertype as a finding in itself —
that is the name collision above, an unrelated type wearing the tag's name.

Then check the discriminator is total, and that every member it declares can be reached. Ask the two
questions separately — one grep for who *answers* a member, one for who *branches* on it:

```bash
echo "-- answered by:"
grep -rn -A6 "override fun " --include="*.kt" . | grep -E "$TAG\.Type\.[A-Z_]+" \
  | sed -E "s|.*/([A-Za-z0-9_]+)\.kt[-:][0-9]+[-:].*$TAG\.Type\.([A-Z_]+).*|\2  \1|" | sort -u
echo "-- branched on:"
grep -rnE "$TAG\.Type\.[A-Z_]+ *->" --include="*.kt" . \
  | grep -oE "$TAG\.Type\.[A-Z_]+" | sed -E "s|$TAG\.Type\.||" | sort -u
```

The window on the first grep is what catches an accessor that picks between members over several
lines; widen it if an implementor decides over more. Several implementors answering one member is
**normal** — a persistence row and a search result are both legitimately albums, and unifying them is
what the tag is for. The findings are narrower: a member answered by a class that is *not* that
concept — the series entity answering `PLAYLIST` — and a member that appears in the first list but
never in the second, which renders through `else`.

Finally, make sure no two tags are competing for one accessor name:

```bash
grep -rhoE "fun [a-zA-Z][A-Za-z0-9_]*\(\): Type" --include="*.kt" . | sort | uniq -c | sort -rn
```

Any count above one is a pair of tags that no single class will ever be able to implement together.
