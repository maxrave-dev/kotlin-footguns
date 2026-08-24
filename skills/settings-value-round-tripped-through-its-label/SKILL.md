---
name: settings-value-round-tripped-through-its-label
description: A selection dialog that maps the chosen localized label back to a stored value breaks the day two labels translate identically — the write is skipped or lands on the wrong option, with no error; covers carrying the id instead of the text, making the miss loud, and the sibling hazard of a default declared both in the store and as the collector's initial value. Use when a settings choice does not stick in one language only, when a picker writes a neighbouring option, or when a screen renders the wrong variant for a moment on entry.
---

# Do not round-trip a setting through its own label

The shape is everywhere: pair each stored value with its translated caption, show the captions, get
back the chosen caption, look the value up again by string equality.

```kotlin
// adapted — the reverse lookup that is the bug; list and setter renamed, body inlined
styleLabels.firstOrNull { it.second == selected }?.first?.let { setStyle(it) }
```

Forward is fine — value to caption, for the subtitle under the row. It is the return trip that
depends on every caption being unique in every language, which is not a property anyone maintains.

## Traps

**Two identical translations silently disable the write.** Many languages have no distinct wording
for two neighbouring options, and translators are not shown the constraint. When it happens the
lookup either fails — the `?.let` swallows it, the dialog closes, the setting is unchanged, nothing
is logged — or, worse, matches the *first* pair with that caption and writes the wrong value. The
same failure arrives from a stray trailing space, a differing apostrophe, or a caption that renders
one way in the list and another in the dialog.

**Carry the id, not the text.** The selection API should hand back an index or the value itself. If
the dialog is yours, that is a small change and it removes the whole class. If it is not, map by
position against the *same list instance* you built the captions from.

**Positional mapping only works if the list is built once.** Option lists are frequently conditional
— an entry added only on a platform that supports it — so a list rebuilt in the dialog callback can
have different indices from the one that was displayed. One `val` built once, read by both the
display and the callback.

**Make the miss loud.** `?.let { }` is the wrong terminator for a lookup that must succeed. Log a
warning, or throw in debug builds. A settings write that quietly does nothing is reported months
later as "it doesn't save", by one user, in one language.

**A default declared in the store and again at the collector is two places to drift.** The store
falls back to a default when the key is absent; the screen collecting that flow supplies an initial
value for the frames before the first emission. When they disagree, the screen renders the *other*
option for a beat on every entry — and a "reset to defaults" path can write the value the store
believes while the UI showed the collector's. Reference one named constant from both, and prefer a
store API that never needs a second default (a flow with a start value, or a state flow).

**The boolean version of that drift is the same bug, just cheaper to spot.** A screen full of `false`
collector defaults is a list of duplicated defaults; each is a wrong first frame if the store's
fallback is `true`. Audit them the same way — but note that a store keeping its flags as named string
constants writes its false as a dotted name, not as a literal, so the two halves of one screen are
spelled differently and a filter that knows only `false` silently keeps every one of the others.

**The forward direction has its own quiet failure.** The row's subtitle looks the caption up from the
stored value and falls back to an empty string when nothing matches — so a value written by an older
build, or by the wrong-option bug above, renders as a settings row with a blank subtitle rather than
as an error. Fall back to the default option's caption instead, and log the miss.

**Watch what else that click lambda does.** Dialog titles and buttons in this pattern are frequently
fetched with a blocking resource read. Inside an event handler that is tolerable; the same call from
composition is not — see `compose-multiplatform-viewmodel-base`.

## Verifying it

1. Every reverse lookup by caption. Each hit is either a bug or needs a comment explaining why the
   captions are guaranteed unique:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "it.second == \|\.second == selected" .
   ```

2. Every lookup that ends in a silent `?.let`, which is how the miss stays invisible:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "firstOrNull {.*}?\..*?\.let {" .
   ```

3. Collector defaults that are not plain booleans — these are the ones whose drift is visible as a
   wrong first frame. Each hit must name the same constant the store falls back to in step 4:

   ```bash
   grep -rnE --include='*.kt' --exclude-dir=build \
     "collectAsState[A-Za-z]*\((initialValue *= *)?[A-Za-z_][A-Za-z0-9_.]*\)" . \
     | grep -vE "\((initialValue *= *)?(true|false|null|[A-Za-z0-9_.]*\.(TRUE|FALSE))\)"
   ```

   Both halves of that pattern are load-bearing. The argument position has to be optional, because
   the default is as legally passed positionally as by name — and a codebase mixes the two, so an
   audit anchored on `initialValue = ` reports a clean screen while the twin declaration of the very
   setting you are auditing sits in another file, in the other spelling. The exclusion has to cover
   both spellings of a boolean for the reason in the trap above, or widening the match simply refills
   the listing with the flags it was meant to drop. `null` is excluded on different grounds: it is a
   not-yet-loaded sentinel rather than a default anyone declared twice.

4. The store's own fallbacks, to compare against step 3:

   ```bash
   grep -rn --include='*.kt' --exclude-dir=build "preferences\[.*\] ?: " .
   ```

5. By hand, and this is the test that finds it: switch the app to a language where two options of one
   setting read the same, choose the second of them, reopen the dialog. If the first is ticked — or
   the old value is — the round trip is going through the caption.
