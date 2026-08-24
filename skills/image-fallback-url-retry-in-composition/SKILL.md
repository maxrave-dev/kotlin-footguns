---
name: image-fallback-url-retry-in-composition
description: Retry a record's image at a variant the source guarantees when the high-resolution one is missing, by holding the URL in composition state and swapping it once in onError. Covers making the disk-cache key follow the mutated URL, resetting the state per record, keeping the swap a no-op the second time so it cannot loop, and the invisible cost — everything hanging off onSuccess (a palette, and the page theme derived from it) silently never runs. Use when a page keeps its fallback colour for particular records, when a retried image is re-fetched on every visit, or when an image request appears to retry forever.
---

# Retrying an image at a variant that exists

Some sources publish several renditions of the same picture under predictable URLs, and only some
of them are guaranteed. Point at the high-resolution one and a minority of records answer with a
404. The image itself degrades gracefully — a placeholder appears. Everything *derived* from the
image does not.

```kotlin
// adapted — the URL is composition state, keyed on the record, and both the request and its
// cache key read that same state
var imageUrl by remember(record.id) { mutableStateOf(record.imageUrl) }

AsyncImage(
    model = ImageRequest.Builder(LocalPlatformContext.current)
        .data(imageUrl)
        .diskCachePolicy(CachePolicy.ENABLED)
        .diskCacheKey(imageUrl + "BIGGER")     // follows the mutation, not the record
        .crossfade(550)
        .build(),
    contentDescription = "",
    onSuccess = { actions.onArtworkBitmap(it.result.image.toImageBitmap()) },
    onError = {
        val fallback = imageUrl?.replace(HI_RES_VARIANT, GUARANTEED_VARIANT)
        if (fallback != null && fallback != imageUrl) imageUrl = fallback
    },
    …
)
```

## Traps

**The expensive failure is invisible, and it is not the image.** A missing image shows a
placeholder — annoying, obvious, low stakes. But `onSuccess` is also where the bitmap is handed to
palette extraction, and the palette is what colours the page: background, accents, sometimes an
entire generated scheme. When the request fails, that callback never fires, the palette never
generates, and the page silently keeps its neutral fallback. Nobody files a bug titled "the
background is the wrong colour for this one record" — it just looks slightly dead, for some records
and not others. That is the actual reason to add the retry.

**The cache key must read the mutated URL, not the record.** Key the request off `record.imageUrl`
and the retry loads the good variant while writing it into the cache entry for the *dead* one. Next
visit reads that entry back for a URL that 404s, or re-fetches every time depending on which layer
you keyed. `.data(x)` and `.diskCacheKey(x…)` must name the same state — check both lines together,
because the bug only exists in the mismatch and each line looks fine on its own.

**`remember(key)` — never a bare `remember`.** Without the record key, the first record that falls
back leaves its substituted URL sitting in state, and the next record renders with the previous
record's URL until something else recomposes. With the key, the state resets exactly when the
record changes, which is also the only moment the initial value is meaningful.

**The swap must be a no-op the second time.** `onError` fires again when the fallback itself fails.
The guard is that applying the same rewrite to an already-rewritten URL yields the identical string
— so `fallback != imageUrl` is false and nothing is written. Get that wrong (a rewrite that keeps
producing a different string, or an unconditional assignment) and you have an infinite
request/error/request cycle burning the network. Prefer a rewrite that is idempotent by
construction over a `var retried by remember` flag, which is one more thing to reset per record.

**A rewrite that does not match is a free no-op, and that is the point.** Records whose images come
from a different host never contain the variant token, so `replace` returns the identical string,
the guard is false, and nothing happens. No host sniffing, no `when`, no per-source branch — one
line that is inert everywhere except where it is needed.

**Keep the image composed when it is hidden, or you lose the callback with it.** Where the artwork
is covered by a video or a full-bleed animation, the temptation is `if (!covered) { AsyncImage(…) }`.
That removes the node, so the load is cancelled and `onSuccess` never fires — and the palette that
the covering layer's own colours depend on never resolves. Hide it with `alpha(0f)` and let it keep
its layout slot and its request.

**The retry belongs in composition, not in the repository.** Nothing below the UI knows the request
failed; the image loader's error callback is where that fact exists. Pushing a "verify this URL"
probe into the data layer costs an extra network round-trip per record for a problem that resolves
itself in the loader, and the fix would still have to reach the cache key that lives up here.

**A palette that is never fed and a palette that is still loading look the same on screen.** If the
page is black or neutral, decide which one you have before adding a retry — see
`palette-state-parks-on-loading` for the extraction state that reports no colour while it works,
and `artwork-palette-theming` for choosing the swatch once it does arrive. Where the image seeds a
whole generated scheme rather than one background, the blast radius is every token on the page:
`artwork-seeded-dynamic-scheme` covers what falls back to the app seed when this callback is
missed.

## Verifying it

```bash
# 1. every retry that rewrites a URL in onError
grep -rn --include='*.kt' -A3 'onError = {' . | grep -E 'replace\('

# 2. for each of those requests, the data() and the key that must read the same state
grep -rn --include='*.kt' -B14 'onError = {' . | grep -E '\.data\(|diskCacheKey\('

# 3. images wrapped in a conditional — the branch going false cancels the load, so any
#    callback on them never fires. The window has to be wide: the guard that matters is rarely
#    adjacent, and a two-line window returns a tidy list with every real instance missing from it
grep -rn --include='*.kt' -B30 'AsyncImage(' . | grep -E 'if \(.*\) \{$'
```

1. → observed: the retry sites, each computing the fallback with a plain `replace` of one variant
   token and each guarded by `fallback != <state>`. An unguarded assignment here is the loop.
2. → observed: for every retry site, `.data(<state>)` and `.diskCacheKey(<state> + …)` name the
   **same** mutable value. A `.data(mutableState)` sitting above a `.diskCacheKey(record.field)` is
   the mismatch described above, and it will not show up until the second visit to that record.
3. → observed: a few dozen hits, most of them decorative images or plain null guards — and, at the
   far end of the window, the guards that really do wrap a palette-feeding image, with a comment
   block, a `remember` and sometimes a `Box` sitting between them and their `AsyncImage(`. That
   distance is the point: those are the hits to open. A conditional around a *decorative* image is
   fine, while the one whose success feeds the palette must stay composed and be hidden with
   `alpha(0f)`. Read the block under each hit; the grep finds candidates, not verdicts.

Then, by hand: find a record whose high-resolution variant is missing and open it twice. First
visit — the image resolves after a brief placeholder and the page picks up its colour. Second
visit — no network request for it at all (the fallback is cached under its own key), and the colour
appears immediately. Watch the network log rather than the screen: a retry loop is quiet on screen
and loud there.
