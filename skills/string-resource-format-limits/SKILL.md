---
name: string-resource-format-limits
description: "The multiplatform resource formatter substitutes plain positional placeholders and nothing else — no flags, no width, no escaped percent — so padding, rounding, units and symbols belong in code and the resource only ever joins already-formatted pieces. Covers the same omission in its other two shapes: a raw stored number printed straight to screen, and a date-time library's month names that are constants rather than locale lookups. Use when a format specifier renders verbatim on screen, when a label appears in English regardless of language, or when a screen prints a number in the unit the database happens to store."
---

# The resource joins pieces; it does not format them

The multiplatform resource lookup understands `%1$s` and `%1$d`. It does not understand the flag and
width part of a specifier, it has no escape for a literal percent sign, and it will not round,
truncate or pad anything. Write `%1$02d:00` in a resource and the specifier reaches the screen as
text.

So the split is fixed: **every value is finished in code, and the resource only concatenates.**

```kotlin
// adapted — zero-padded here, because the resource cannot do it
private fun hourLabel(hour: Int): String = "${hour.toString().padStart(2, '0')}:00"

// the resource is literally "%1$s – %2$s"
stringResource(Res.string.hour_span, hourLabel(peak), hourLabel((peak + 1) % 24))
```

The same rule is why a percentage is built as `"$coverage%"` in Kotlin and handed in as a string: the
`%` sign cannot survive in the resource, so it travels inside the argument.

## Traps

**The failure is silent and cosmetic-looking.** A specifier that renders verbatim looks like a
templating glitch rather than a formatting bug, and it only appears once the branch that uses it
runs. Nothing throws.

**Translators are the ones who break specifiers, and they break them in one locale.** A scan of 26
translations here found exactly one file where the trailing type character had been dropped from a
placeholder, leaving a bare `%1$` followed by a space. The base language is fine, every review is
done in the base language, and that one locale renders the specifier instead of the number. This is
the strongest argument for keeping resources to plain `%1$s` joins: the simpler the resource, the
less there is for a translation round trip to lose.

**A number printed in the unit it is stored in is not a formatting nicety.** A total kept as seconds
and rendered as `"$seconds seconds"` puts a five-digit number on screen that nobody converts to
"just over thirteen hours" at a glance. Convert at the boundary, and drop the unit as soon as it
stops carrying information — past an hour the seconds are noise:

```kotlin
// adapted
@Composable fun formatDuration(totalSeconds: Long): String {
    val safe = totalSeconds.coerceAtLeast(0)
    val hours = safe / 3600
    val minutes = (safe % 3600) / 60
    return when {
        hours > 0 -> stringResource(Res.string.time_hours_minutes, hours, minutes)
        minutes > 0 -> stringResource(Res.string.time_minutes, minutes)
        else -> stringResource(Res.string.time_seconds, safe)
    }
}
```

**A hardcoded literal is the same omission, one step earlier.** `Text("Listened time")` is a string
no translation can reach — it will not appear in any export, no translator will ever see it, and it
is invisible to every check that reads the resource files. It ships alongside the raw-number bug for
the same reason: both are "the value went to the screen without passing through the layer that was
supposed to prepare it".

**A date-time library's English month names are constants, not locale lookups.** The multiplatform
one ships `MonthNames.ENGLISH_FULL` and `ENGLISH_ABBREVIATED` and no localized alternative, so a date
formatted with either reads English in every language. The name contains the word ENGLISH and it is
still reached for, because it is the only thing on offer. There is no clever fix: the twelve names
become string resources like everything else the user reads, selected by a `when`.

**That `when` needs an `else`, and the obvious `else` is a silent wrong answer.** Where the month type
is not an exhaustive enum from shared code, the compiler demands a fallback — and returning January
means an unexpected value renders as a plausible date rather than as an error. Pick a fallback the
reader can recognise as broken, or fail loudly; see `unknown-not-a-valid-score`.

**Fixing one screen does not fix the rule.** Three live call sites elsewhere in this tree still format
dates with the English constants, and they will keep doing so until someone greps for them — the same
shape as `guard-on-every-trigger-path`, where a rule applied in one of its homes produces no error in
the others.

**Wrapping the lookup makes every formatter composition-only.** A `@Composable fun formatX()` cannot
be unit-tested without a composition and cannot be called from a view model, a notification or a
widget. That is usually the right trade for a display helper and the wrong one for anything a
background path also needs — `kotlinx-datetime-helper-kit` covers splitting it.

## Verifying it

1. **Scan every locale, not just the base one.** This is the check that found the broken translation
   above:

   ```bash
   find . -path '*composeResources/values*' -name 'strings.xml' -not -path '*/build/*' \
     -exec grep -noE '%[0-9]+\$[^sd<]|%%' {} +
   ```

   The expected result is **no output**; any hit is either a flag/width specifier that will render
   verbatim or a placeholder a translator truncated. Across 26 locales here it returned exactly one:
   a translation that had dropped the trailing type character, leaving a bare `%1$` and a space.

2. **Find date formatting that hardcodes a language:**

   ```bash
   grep -rn --include='*.kt' "MonthNames.ENGLISH" . | grep -v '/build/'
   ```

   Five hits here — two are the comments recording the fix, three are live call sites still shipping
   English month names on non-English devices.

3. **Find user-visible literals that never reach a translator** — one hit here, and treat that as a
   floor rather than a count: the pattern only catches a literal passed directly as the first
   argument, not one built into a variable or interpolated first.

   ```bash
   grep -rn --include='*.kt' -E 'Text\(\s*"[A-Z]' . | grep -v '/build/'
   ```

4. **Switch the device language to one you cannot read, and walk the screen.** Anything still legible
   to you is either a hardcoded literal or a constant-backed date. This catches all three shapes at
   once, and it is the only check that needs no grep to be right.
