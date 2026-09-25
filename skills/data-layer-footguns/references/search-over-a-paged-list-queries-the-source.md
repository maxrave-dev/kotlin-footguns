---
name: search-over-a-paged-list-queries-the-source
description: Filtering a paging stream only ever searches the pages already loaded, so whether an item is findable depends on how far the user happened to scroll — the search must query the store and render as a sibling overlay, leaving the paged reader and its drag-reorder, in-place removal and scroll position untouched. Covers the debounce and minimum-length gate, why the escaping belongs one layer above the query, and the one case where filtering in memory is correct. Use when search misses items that are definitely there, when results change after scrolling, or before threading a second data source through a paged list.
---

# Search queries the store, not the window

A paging stream is a *window* onto a collection. Filtering it — `pagingData.filter { … }`, or a
`derivedStateOf` over the loaded snapshot — only inspects the pages that have already been fetched.
Everything past the load boundary is not absent from the results; it was never asked.

The symptom is what makes this expensive: the feature **works**. On a short collection every page is
loaded immediately and the filter is indistinguishable from a real search. It degrades with length
and with scroll position, so the bug report is "search sometimes misses things", and the reproduction
is "scroll down first, then search".

The correct shape is two independent readers of the same store:

```kotlin
// adapted — the paged reader, unchanged
val itemsPaging: StateFlow<PagingData<Row>> = …

// adapted — a separate flow that asks the store the question
@OptIn(FlowPreview::class, ExperimentalCoroutinesApi::class)
val searchResults: StateFlow<List<Row>> =
    searchQuery
        .debounce(250)
        .distinctUntilChanged()
        .flatMapLatest { raw ->
            val q = raw.trim()
            if (q.length < 2) flowOf(emptyList()) else repository.search(collectionId, q)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())
```

and, in the UI, a **sibling** of the paged list rather than a branch inside it:

```kotlin
// adapted — draws over the list; the list underneath keeps its scroll position and its gestures
AnimatedVisibility(visible = searchOpen, enter = …, exit = …) {
    Column(Modifier.fillMaxSize().background(pageBackground)) {
        SearchField(query, onQueryChange = viewModel::setSearchQuery)
        LazyColumn { items(searchResults, key = { it.stableKey }) { Row(it) } }
    }
}
```

## Traps

**Threading a second data source through the paged list costs everything attached to it.** A paged
reader in a mature screen is not just a list: it carries drag reordering, in-place removal,
selection, and a scroll position the user expects back when they close the search. Making it accept
"either paged items or search results" puts all of that inside a branch, and the search half needs
none of it. A sibling overlay puts the flat list where a flat list belongs and leaves the complicated
reader entirely alone.

**Reuse the same row composable, and check its defaults.** The overlay renders the same rows, so the
two views agree on how an item looks. Watch for parameters the paged path was supplying implicitly —
a row taking a required `modifier` with no default, because the paged path always passed one down,
will not compile in the overlay until it is passed explicitly. That is the good outcome; the bad one
is a parameter with a *default* that the paged path was overriding, which compiles and renders
differently in the two places.

**A one-character query is not a search.** It matches most of the collection, which is neither
useful to read nor cheap to fetch, and it fires on the first keystroke of every search. Gate on
length before the query, not after: `if (q.length < 2) flowOf(emptyList())`.

**`debounce` without `flatMapLatest` still runs every query to completion.** Debounce drops
keystrokes; `flatMapLatest` cancels the request already in flight when a new term arrives. With
`flatMapConcat` or a plain `map`, a slow query for `"be"` can land after the one for `"beacon"` and
overwrite it. Both operators are needed, and they solve different halves.

**Escape the pattern one layer above the query, not inside it.** The term is a bind parameter, so
the store passes it through untouched and its wildcard characters are still wildcards — a user
typing the *match-anything* character gets the entire collection back. Wrap and escape in the data
source that owns the call, so the query text stays readable and every caller is escaped by
construction. See `like-wildcard-escaping-ids` for the escaping itself.

**Two round trips, not a join into the display type.** The store's natural query narrows the
membership rows; the display rows are then fetched by id — and come back in whatever order the store
found them. Re-sort by the first result's ordering afterwards or the search list is in an arbitrary
order while the paged list is in the collection's order, which reads as a bug in the search.

**Closing the search must clear the query.** Leaving the last term in the state means reopening the
box shows stale results for a fraction of a second before the debounce fires, and — worse — the
results flow stays subscribed, holding a query nobody is looking at.

**In-memory filtering is correct when the whole collection is already in memory.** Automatic
collections built from a bounded query — favourites, most-played, a top-N chart — are fully loaded
by construction, and filtering those *is* the right implementation. The rule is not "never filter";
it is "never filter a **paged** source". When both kinds of section sit on one screen, expect the
two implementations side by side and label which is which.

## Verifying it

1. **Find every filter applied to a paged source.** These are the ones that search a window:

   ```bash
   grep -rn 'PagingData\|LazyPagingItems' --include='*.kt' . | grep -v '/build/' | grep -iE 'filter|search'
   ```

   Any hit is either this bug or a deliberate in-memory case that must be justified in a comment.

2. **Confirm the search flow has all three guards** — debounce, latest-wins, and a length gate:

   ```bash
   grep -rn -A10 'debounce(' --include='*.kt' . | grep -v '/build/' \
     | grep -E 'flatMapLatest|length <|isBlank|distinctUntilChanged'
   ```

   A `debounce` with no `flatMapLatest` nearby is the out-of-order-results bug.

3. **Confirm the pattern is escaped where it is built, not in the query string:**

   ```bash
   grep -rn "ESCAPE" --include='*.kt' . | grep -v '/build/'
   grep -rn 'escapeForLike\|escapeLike' --include='*.kt' . | grep -v '/build/'
   ```

   Every query declaring an escape character needs a caller that applies one, and vice versa. One
   without the other is a pattern that either does not escape or escapes into a literal backslash.

4. **The behavioural test is the whole point, and it has two halves.** With a collection long enough
   to need several pages: search for an item near the **end** without scrolling — it must be found.
   Then scroll to the bottom, search for an item near the start, and close the search — the list
   must be exactly where you left it, and drag-reorder must still work.

5. **Type fast and then delete back to one character.** Results must settle on the final term, and
   the one-character state must show nothing rather than a full-collection dump.

Paging companions: `continuation-token-pagination-contract` for the reader itself, and
`generic-paged-db-accumulator` for the case where reading everything is legitimate.
