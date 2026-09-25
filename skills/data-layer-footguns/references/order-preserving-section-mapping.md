---
name: order-preserving-section-mapping
description: Map a sectioned API response as a list of (title, items) in the order it arrived, never by reading result[0] and result[1] into named fields — a signed-in account is recorded here as getting an extra section pushed in front, and any such shift mislabels every section after it and drops the last one with no error. Assume the set and order may also vary by locale or region, and capture two responses to find out. Use when modelling a home feed or browse screen made of shelves, or when a screen shows the right content under the wrong headings for some users only.
---

# Map every section, in the order it arrived

The response is a list of shelves. The domain model must be a list of shelves too — the moment it
becomes a record with named fields, the mapping has to guess which index is which, and that guess is
the bug:

```kotlin
// adapted: names generalized
@Serializable
data class Catalog(val sections: List<CatalogSection>)

@Serializable
data class CatalogSection(
    /** Section heading exactly as the service returned it. */
    val title: String,
    val items: List<CatalogItem>,
)
```

The mapping is then the obvious one, and there is nowhere for a positional assumption to hide:

```kotlin
// adapted: item field names generalized; mapping as written
val sections = result.map { section ->
    CatalogSection(
        title = section.title,
        items = section.items.map { CatalogItem(it.title, it.endpoint.params.orEmpty(), it.stripeColor) },
    )
}
emit(Resource.Success(Catalog(sections)))
```

Consumers iterate rather than index:

```kotlin
// adapted — compressed to one line; the source spends a screen's worth of UI inside this forEach
catalog.sections.forEach { section -> SectionHeader(section.title); Row(section.items) }
```

## Traps

**Positional mapping fails by relabelling, not by throwing.** Read `result[0]` as one thing and
`result[1]` as another, and the day the response gains a leading shelf every mapping shifts by one:
the new shelf is rendered under the first name, the real first shelf under the second name, and the
last real shelf is never read at all. Every access is in range, so nothing throws, nothing is
logged, and the screen looks populated. The report that comes back is "the categories are wrong",
which nobody can reproduce — because the extra shelf only appears for signed-in accounts, or in one
locale, or in one region.

**The model shape decides this, not the mapping code.** A record with fixed named fields cannot be
filled from the response without picking indices, so the positional read is not a mistake someone
made — it is the only way to satisfy the type. Fixing the mapper without fixing the model puts the
same code back within a release. Make the list the model.

**A count assumption is the same bug in a different shape.** Destructuring, `require(size == 2)`,
`zip` against a fixed list of names, or a `when (index)` all encode "there are exactly N sections in
this order". They break on precisely the same event, and the ones that throw are the lucky ones.

**Check whether the heading is localized before treating it as a key.** The title is whatever the
service sent, and services that vary their sections by account and region generally vary the
wording too. Capture the same request under two locales and compare: if the strings differ, the
title is display text and must never be used to *find* a section in code. When some section needs
special handling, look for a stable discriminator in the payload — an endpoint parameter, a
renderer type — and if there isn't one, handle every section identically and let the server decide
the order.

**`forEachIndexed` in a consumer can quietly reintroduce the coupling.** Using the index as a list
key or to decide spacing between shelves is fine. Using it to decide *what a shelf is* — a special
layout for the first one, a divider before "the genres section" — puts the positional assumption
back in the UI, where it is even harder to spot than in the mapper.

**Empty sections pass straight through.** `map` keeps a shelf that arrived with zero items, which
renders as a heading with nothing under it. That is a legitimate choice — an empty shelf is
information — but make it deliberately, with a `filter` you can point at, rather than discovering it
in a screenshot.

**If the mapped list is cached, the cached order is the order that was current when it was
written.** A section that moved server-side stays in its old position for anyone holding a stored
copy until the refresh lands. That is correct behaviour for the caching pattern (see
`cache-then-network`) and worth knowing before you spend an afternoon on a reordering that has
already shipped.

## Verifying it

Positional mapping is correct on the response you developed against — that is why it survives review.
The only useful test compares two responses that differ in exactly the way production varies:

1. Capture the same request **signed out and signed in**, and again in **two locales**.
2. Diff the section titles and the section count across those captures. If either moves, positional
   mapping is already wrong for some users today.
3. Assert `mapped.sections.size == response.size` in a test with a fixture that has a section
   inserted at the front. A fixture that only ever has the sections in the original order passes on
   the broken version, which makes it worse than no test.

Do not settle this from the model's comments or from the shape of one saved response body — both
describe the arrangement someone saw once.
