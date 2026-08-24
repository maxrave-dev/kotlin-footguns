---
name: commit-a-text-field-on-an-explicit-action
description: An editable value that is written on focus loss stores whatever was half-typed when a dialog, a rotation or a stray tap took the focus away; keep the draft in its own state keyed on the stored value and write only when the user asks for it. Covers why the dirty check that shows the confirm button gets stuck when the commit normalises, where the draft should live, and what a second commit path has to agree with. Use when a setting holds a truncated value nobody typed, when a Save button never goes away after saving, or when an externally changed value does not reach the field.
---

# Write when the user asks, not when the focus moves

A draft that lives beside the stored value, and a commit that is a button:

```kotlin
// Keyed on the stored value: a change from anywhere else re-seeds the field.
var draft by remember(storedEndpoint) { mutableStateOf(storedEndpoint) }

BasicTextField(
    value = draft,
    onValueChange = { draft = it },
    /* decorationBox shows a "wss://…" placeholder while draft is empty */
)

// The confirm action exists only while there is something to confirm — it is the dirty
// indicator and the commit in one expression.
if (draft != storedEndpoint) {
    SmallAction(text = stringResource(Res.string.save)) { viewModel.setEndpoint(draft) }
}
```

Nothing durable is written while typing. The field edits a copy; the copy becomes the stored value at
one place, on one gesture, and the button disappearing is the receipt.

## Traps

**Focus loss is not consent.** Focus goes away when a dialog opens, when the keyboard is dismissed,
when the window is rotated, when another field is tapped, when the user navigates away mid-thought —
and a commit hung on that event stores whatever was on screen at the time. For an address, that is a
scheme and three characters; the app then fails to reach it and the user's next visit shows a value
they never finished typing, with nothing to suggest where it came from. An IME "Done" action is the
opposite case and is fine: the user pressed it.

**The dirty comparison is the button, so normalisation at commit strands it.** A setter that trims —
`putString(key, url.trim())` — writes a value that may equal what is already stored. A conflating
holder does not re-emit an equal value, so the keyed draft never re-seeds, `draft != stored` stays
true, and the button sits there doing nothing each time it is pressed. Normalise at the **edit**
boundary instead, or compare normalised forms; then what the user sees is what will be stored, and
the receipt is honest. Same family as `stateflow-conflation-inverts-state`: what the holder does with
an equal write is part of the contract, not an implementation detail.

**`remember(source)` and `remember { }` are different features.** The key is what lets a value changed
elsewhere — a preset button, a reset, another screen — reach the field; without it the draft is seeded
once and the dirty check then compares against something the user never typed, so the button appears
on a field they have not touched. The price is that an in-flight edit is discarded when the source
moves under it. Take that trade: a lost half-typed draft is recoverable, a field showing a value the
app no longer holds is not.

**A second commit path has to agree with the draft.** Any other control that writes the same value —
picking the option this field belongs to, a preset, an import — must commit *the draft* rather than
its own idea of it, and must not fire when it is already selected. Otherwise re-selecting an active
option writes a draft the user is only halfway through typing.

**Seeding a commit with a placeholder commits a non-working value.** Where "stored is blank" means
"use the default", writing a bare scheme like `wss://` to mark the custom option as chosen switches
the app onto a custom endpoint that cannot resolve, and the store now says configured. Either keep
the marker separate from the value, or treat a value that is only a scheme as not configured — one of
the two, decided explicitly.

**A placeholder is not a value.** The `wss://…` shown while the field is empty belongs in the
decoration box. Seeding the draft with it makes an empty field look filled, makes the dirty check
true before a keystroke, and eventually gets committed by someone who does not know it was a hint.

**Where the draft lives is a separate question from when it commits.** A value with a durable store
drafts into local `remember`; a value that only has to survive until a button — a name typed before
pressing Create — can draft in the state holder, where it also gets clamped in one place. Neither is
a write: putting the draft in a holder is not the same as persisting it, and a holder field that a
repository reads on every change is a commit-on-keystroke wearing a draft's name.

**Key the draft on the value, never on the object holding it.** `remember(uiState)` re-seeds every
time any unrelated field of that state changes — a poll result, a connection flag — and the user's
half-typed value disappears under their hands, at a moment that has nothing to do with them. The key
is the single stored value this field edits.

**`remember` versus `rememberSaveable` for the draft is a decision, not a default.** A plain
`remember` discards the draft on a configuration change or process death, which is acceptable only
because the stored value is intact and the user can see it come back. If losing several sentences of
typing is not acceptable, the draft belongs in `rememberSaveable(source)` — and it is still a draft,
still uncommitted, just one that survives a rotation.

**A field whose text is rewritten by the holder must carry its own selection.** When the holder caps
the length, uppercases, or filters characters, the value coming back is not the value the user typed,
and a plain `String`-valued field carries no caret with it, so the caret does not follow the rewrite.
Pass a `TextFieldValue` with an explicit selection for those fields — this is the one case where
hoisting the value all the way out is not free.

## Verifying it

```bash
# 1. Every editable field and what feeds it. For each, answer: is this a draft or the stored value?
grep -rn --include="*.kt" -A2 -E "(Basic|Outlined)?TextField\(" . | grep -v "/build/" \
  | grep -E "value = |onValueChange"

# 2. Drafts keyed on their source — the shape this covers, in **both** spellings, since a saveable
#    draft is still a draft and a regex closed on `remember(` reads one as a defect. The pattern is
#    used for non-text state too, so read for the ones sitting next to a field: a field whose value
#    comes from a store but whose draft is NOT in this list never re-seeds, and will keep showing a
#    stale value.
grep -rn --include="*.kt" -E "remember(Saveable)?\([a-zA-Z_.]+\) *\{ *mutableStateOf" . \
  | grep -v "/build/"

# 3. Commits hung on focus. Expect no output; every hit is a field that writes without being asked.
grep -rn --include="*.kt" -A4 "onFocusChanged" . | grep -v "/build/" \
  | grep -E "viewModel\.|set[A-Z][a-z]+\("

# 4. Setters that normalise. Each hit is a stuck-dirty candidate: pair it with the field that feeds
#    it and check whether the same rule is applied at the edit boundary.
grep -rn --include="*.kt" -A2 -E "fun set[A-Za-z]+\(" . | grep -v "/build/" \
  | grep -E "\.trim\(\)|\.take\(|\.uppercase\(\)|\.lowercase\(\)"
```

Then type a partial value and leave without confirming — rotate the window, open a dialog, press
back — and come back: the field must show the stored value, not the fragment. Type a value that
differs from the stored one **only** by what the setter normalises away (a trailing space is enough),
press the confirm action, and watch the button: it has to disappear. If it stays, the commit
normalised into a no-op write and nothing downstream noticed. Last, change the same value from its
other entry point while the field is on screen; the field must follow, and the confirm action must
not appear on a field nobody typed into.

Related: `identity-compare-immutable-setting` (comparing a stored setting against a candidate),
`nested-flag-settings-auto-disable` (the neighbouring rows that gate on the value this field writes).
