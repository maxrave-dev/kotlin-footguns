---
name: empty-sentinel-instance
description: Give a model a canonical empty instance on its companion object so its holders can declare the field non-null, instead of threading a nullable through every layer. Covers when this genuinely removes a whole family of null checks and when it only adds a second check beside the one already there, the emptiness predicate that has to ship with it, keeping the sentinel out of persistence and out of rendered lists, and where a nullable is the honest signal. Use when call sites test both for null and for the sentinel, when an empty-keyed row appears in storage, or when a list renders one blank entry at startup.
---

# A canonical empty instance instead of a nullable field

A state holder that starts before its data arrives has to represent "nothing yet". The nullable
version pushes that decision into every consumer; a sentinel answers it once, at the model:

```kotlin
// adapted
data class Item(
    val id: String,
    val uri: String?,
    val metadata: Metadata,
) {
    companion object {
        val EMPTY = Item(id = "", uri = null, metadata = Metadata.EMPTY)
    }
}
```

The payoff arrives one level up, where the holder can now declare the field non-null and every
reader of it stops writing a null branch:

```kotlin
// adapted — the predicate and `INITIAL` here are the corrected shape; the source compares the whole
// holder via a `fun initial()`, and inverts the polarity — both are traps below
data class CurrentItemState(
    val item: Item,          // never null — this is what the sentinel bought
    val detail: Detail?,
    val record: Record?,
) {
    fun isEmpty(): Boolean = item == Item.EMPTY

    companion object {
        val INITIAL = CurrentItemState(item = Item.EMPTY, detail = null, record = null)
    }
}
```

Note what the sentinel does *not* do: the sibling fields are still nullable, because nothing gave
them an empty value. The sentinel removes a null-check family only for the specific field it
covers, and only where the *holder* of that field is itself non-null.

## Traps

**If the holder is nullable, the sentinel added a check instead of removing one.** This is the
failure that undoes the whole pattern, and it is visible in one line at the call site:

```kotlin
val show = !(state?.item == null || state?.item == Item.EMPTY)
```

Two questions where there was one, both of which have to be right, and a reader has to know that
`EMPTY` even exists to write the second. If a nullable holder is unavoidable, give the *holder* an
initial value too, so the flow starts at `INITIAL` rather than at null, and the call site is one
comparison. If the holder must stay nullable, the sentinel underneath it is buying nothing.

**The emptiness predicate has to ship with the sentinel, and call sites have to use it.** A model
with `EMPTY` and no `isEmpty()` guarantees the comparison gets written by hand at every consumer —
and then drifts, because each author picks a slightly different question. Check for hand-rolled
comparisons directly; if they exist, the predicate either does not exist or is not discoverable.

**A predicate that compares the whole holder answers a different question than it appears to.**

```kotlin
fun isNotEmpty(): Boolean = this != INITIAL   // any field differing flips this
```

This turns true as soon as *any* field moves, including a sibling arriving while the sentinel field
is still empty — which is precisely the interval a loading screen exists to cover. Compare the field
the sentinel is for.

**Equality must be structural, and the sentinel must be a single value.** The comparison works
because the model is a data class; on a class without generated equality, `== EMPTY` is an identity
check and fails for any instance built independently. Two related shapes to keep straight: a
`val EMPTY` is one shared instance and is correct; a `fun initial()` builds a fresh instance per
call, which is still correct under structural equality and silently wrong the moment anyone
"optimizes" a comparison to `===`. Prefer the `val`.

**The sentinel is not data, and nothing downstream knows that.** Two places it escapes:
- **Persistence.** A mapper from the model to a storage row is normally unconditional, so mapping
  the sentinel writes a row whose primary key is the empty string. It inserts cleanly, it collides
  with the *next* sentinel write, and it is invisible until someone reads the table. Guard at the
  mapper — `if (item == Item.EMPTY) return null` — not at each caller.
- **Rendering.** A list built from a state that begins at the sentinel shows one blank row, and a
  detail screen bound to it shows empty text where a placeholder was intended. Filter at the point
  the list is assembled, and let the empty case pick a different composable rather than rendering
  the sentinel's blank fields.

**The sentinel's fields must be inert, not plausible.** An empty string identifier is inert because
nothing can match it. A `-1`, a `0`, or a default timestamp is not: those are legal values that
arithmetic and comparisons accept. If the model has numeric fields, the sentinel is a weaker
guarantee than it looks, and the emptiness predicate must not be written against them.

**Where a nullable is the honest signal.** The sentinel says "nothing here yet", which is a fine
answer for a state holder that will be filled. It is the wrong answer for:
- **a lookup that can legitimately find nothing.** "Absent" is information the caller must handle;
  a sentinel lets it be handled by accident.
- **anything that can fail.** A sentinel returned on error is indistinguishable from a sentinel
  returned before loading, and the caller cannot retry what it cannot detect. Use a result type.
- **a field genuinely optional in the domain.** An item that may have no cover image *has* no cover
  image; an empty-string URL is a value that some code will try to fetch.

The general form of the third case is worth internalizing: a failure or unknown must never be
encoded as a value that is legal on the success path — see `unknown-not-a-valid-score`.

## Verifying it

1. **Find hand-rolled emptiness comparisons**, which is the drift this pattern produces:
   ```sh
   grep -rnE "== *[A-Za-z]+\.EMPTY|!= *[A-Za-z]+\.EMPTY" --include='*.kt' .
   ```
   Every hit outside the model's own file should be calling the predicate instead. A hit whose line
   also mentions `null` is the doubled-check trap.
2. **Confirm the predicate exists and is used**:
   ```sh
   grep -rn "fun isEmpty()\|fun isNotEmpty()" --include='*.kt' .
   ```
   Cross-check each declaration against call sites; a declared predicate with none is why the
   comparisons in step 1 exist.
3. **Check the mappers out of the model guard the sentinel**:
   ```sh
   grep -rn "fun .*\.to[A-Z][A-Za-z]*Entity()" --include='*.kt' .
   ```
   Read each body: an unconditional mapper will happily write the sentinel to storage.
4. **Query storage for empty-keyed rows.** `SELECT * FROM <table> WHERE <id_column> = ''` on a
   database from a real session. One row is the leak; zero means the guard is holding.
5. **Launch cold and look at the first frame.** A blank row, or a detail view with empty fields
   before data arrives, is the sentinel being rendered as data.
