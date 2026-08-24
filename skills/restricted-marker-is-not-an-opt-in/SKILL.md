---
name: restricted-marker-is-not-an-opt-in
description: Tell an opt-in marker from a restricted-to marker before adding suppressions — the first is enforced by the compiler and demands acknowledgement, the second demands nothing and means something different and worse; includes how to read which one an API carries straight out of the cached artifact, and why both conventions coexist in one library. Use when an `@OptIn` looks necessary but the same API compiles without it elsewhere, when the IDE offers a suppression for an annotation you have not read, or when deciding whether a library call is safe to depend on.
---

# A restricted-to marker is not an opt-in

Two annotations in one library package, differing by a prefix, are enforced by completely different
machinery. One is `@RequiresOptIn`: the compiler refuses the call until you acknowledge it. The other
is `@RestrictTo`: the compiler does not care at all — it is a lint-visible statement that the API is
internal to the library's own group.

Guessing between them produces two opposite mistakes: suppressions that do nothing, and a
false sense that an API is public because it compiled.

## Traps

**Compiling without a suppression proves the marker is *not* an opt-in — nothing more.** In this tree
two such APIs are called with no acknowledgement at all, while a sibling file wraps two further calls
to one of them in an `@OptIn` naming the similarly-spelled *experimental* marker — which acknowledges
nothing, because that is not the marker either API carries. All of it ships, so the suppression is
not what makes any of it compile; the file that has one is a live specimen of the trap below.

**An unnecessary `@OptIn` is a warning, and warnings do not survive review.** Once written it looks
exactly like a needed one. Worse, it names a real marker, so a genuinely experimental API added to
that file later is silently pre-suppressed and nobody is asked the question the mechanism exists to
ask.

**"The file next door has one" is not evidence, because both conventions coexist inside one
artifact.** Here the design-system artifact declares both markers, and different components carry
different ones — a loading component is genuinely experimental and *does* require the opt-in, while
the theme wrapper and the wavy indicator carry only the restricted-to marker. A per-file convention
cannot be inferred from a neighbour; it has to be read per API.

**Check the build files before concluding anything from an absent `@OptIn`.** A module-wide
`optIn(...)` in the Kotlin compiler options makes every file look clean and destroys the evidence.
Confirm there is none before reasoning from file-level annotations.

**Restricted-to is the more serious finding, not the lesser one.** An experimental API is public and
expected to change with a deprecation path. A restricted-to API is not public at all: the library
group reserves the right to rename or delete it in a patch release, and no deprecation cycle is
promised. "It compiles and needs no opt-in" therefore reads as *safer* while meaning *less* stable.
Decide deliberately, and leave a comment at the call site saying you did.

**Whether lint enforces it depends on the module.** The restricted-to check is a lint rule, so a
multiplatform or non-Android module frequently never runs it — which is why such a call can sit in a
codebase for months with no diagnostic anywhere.

**These facts are per version, not permanent.** APIs graduate: a marker that is restricted-to today
becomes public tomorrow, and an experimental one loses its marker when it stabilises. Everything
above is true as of the versions currently pinned in this tree — re-run the census below after any
bump rather than trusting a note like this one.

**An acknowledgement covers a marker, not an API.** Every experimental API sharing that marker inside
the annotated scope is silenced at once, including ones added later. That is why an unnecessary
acknowledgement is worse than noise and why the scope should be as small as the call.

**Prefer a function-level acknowledgement to a file-level one.** A `@file:OptIn` covers everything in
the file forever, including code added months later that nobody meant to exempt — the same disease as
an unnecessary suppression, spread across a whole file. Annotate the function that makes the call.

**Do not "fix" it by opting in to both — and expect no help from the compiler if you do.**
Acknowledging a marker that is not an opt-in marker **compiles**. It raises
`OPT_IN_ARGUMENT_IS_NOT_MARKER`, a *warning* whose own text says the annotation is ignored, so the
line fixes nothing, stops nothing, and then sits in the file looking exactly like a real
acknowledgement — this skill's own trap, arriving through the door you assumed was locked. Only the
wrong-*target*, wrong-*retention* and subclass-argument variants are errors; the plain one is not,
unless the build promotes warnings. Acknowledging the experimental marker to silence a restricted-to
lint warning suppresses nothing either. If lint objects, the honest options are to stop using the API
or to suppress the specific lint check with a reason.

## Verifying it

1. Every marker the tree currently acknowledges, with counts — the list you are about to audit:

   ```bash
   grep -rhoE "@(file:)?OptIn\([^)]*\)" --include='*.kt' --exclude-dir=build . \
     | tr ',' '\n' | grep -oE "[A-Za-z0-9_]+::class" | sort | uniq -c | sort -rn
   ```

   The `file:` alternation is not optional: a regex anchored on `@OptIn(` misses every file-level
   acknowledgement, which is the broadest kind and therefore the one you most want in the census.

2. Which kind each marker in the library actually is. Read-only, no build required — the annotation
   class carries its own answer:

   ```bash
   JAR=$(find ~/.gradle/caches/modules-2 -name '*material3*.jar' ! -name '*sources*' | sort -V | tail -1)
   echo "$JAR"; D=$(mktemp -d); unzip -oq "$JAR" -d "$D"
   for C in "$D"/androidx/compose/material3/*Api.class; do B=$(basename "$C" .class)
     printf '%-42s %s\n' "$B" "$(javap -v -p -cp "$D" "androidx.compose.material3.$B" 2>/dev/null \
       | grep -oE 'kotlin/RequiresOptIn|androidx/annotation/RestrictTo' | head -1)"
   done
   ```

   Expect a mixed listing: several `kotlin/RequiresOptIn` markers and at least one
   `androidx/annotation/RestrictTo`. That mix is the point — find both before deciding anything.
   `sort -V` picks the newest *cached* artifact, not necessarily the one your build resolves; read
   the echoed path, and swap the artifact name to audit a different library.

3. Which marker specific APIs carry — reusing `$D` from step 2, run against the file classes that
   declare them (top-level Kotlin functions live in a `…Kt` class named after their source file).
   Pick components you actually call; two of these three differ from the third:

   ```bash
   for K in WavyProgressIndicatorKt MaterialThemeKt LoadingIndicatorKt; do
     printf '%-26s %s\n' "$K" "$(javap -v -p -cp "$D" "androidx.compose.material3.$K" 2>/dev/null \
       | grep -oE 'androidx[/.]compose[/.]material3[/.][A-Za-z0-9]*Api' | sed 's|.*[/.]||' | sort -u | paste -sd' ')"
   done
   ```

4. No module-wide opt-in is hiding the evidence. Every hit needs reading:

   ```bash
   grep -rn "optIn\|freeCompilerArgs" --include="build.gradle.kts" --exclude-dir=build .
   ```

5. That a wrong acknowledgement really is only a warning here — the claim above rests on it, and it
   is a property of your compiler and your build, not of the language. Same technique as step 2: the
   diagnostic table is a class in the compiler artifact, and each entry names its own severity.

   ```bash
   J=$(find ~/.gradle/caches/modules-2 -name 'kotlin-compiler-embeddable*.jar' ! -name '*sources*' | sort -V | tail -1)
   echo "$J"; C=$(mktemp -d); unzip -oq "$J" -d "$C"
   javap -c -p -cp "$C" org.jetbrains.kotlin.fir.analysis.diagnostics.FirErrors \
     | awk '/ldc(_w)? +#[0-9]+ +\/\/ String OPT_IN/ {n=$NF; getline
            if ($0 ~ /Severity\./) {split($0,a,"Severity."); split(a[2],b,":"); printf "%-52s %s\n", n, b[1]}}'
   grep -rn "allWarningsAsErrors\|-Werror" --include='*.gradle.kts' --exclude-dir=build .
   ```

   Expect a mixed listing: the argument-is-not-marker row `WARNING`, the wrong-target and
   wrong-retention rows `ERROR`. The second command must print nothing — a build that promotes
   warnings turns the whole family into errors and the reasoning above no longer applies.
