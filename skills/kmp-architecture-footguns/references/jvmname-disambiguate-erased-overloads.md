---
name: jvmname-disambiguate-erased-overloads
description: Resolve two extension functions that differ only in their generic receiver's type argument and so compile to a single JVM method, using @JvmName on one of them. Covers what the annotation changes, why it beats renaming the Kotlin function, and what non-Kotlin callers see afterwards. Use when the compiler reports a platform declaration clash between declarations you can plainly see are different, when adding a second converter over the same collection type breaks a file that compiled yesterday, or when a Java caller cannot find a function every Kotlin caller uses.
---

# Two extensions, one JVM method

Kotlin sees two functions here. The JVM sees one:

```kotlin
fun ArrayList<SongsResult>.toListTrack(): ArrayList<Track> { … }
fun ArrayList<VideosResult>.toListTrack(): ArrayList<Track> { … }
```

An extension function compiles to a static method whose first parameter is the receiver, and a
generic type's argument is erased on the way down. Both become `toListTrack(ArrayList)`, and the
compiler stops with a **platform declaration clash**, naming both declarations and the one signature
they share.

One annotation on one of the two ends it:

```kotlin
import kotlin.jvm.JvmName

@JvmName("songsResultToListTrack")
fun ArrayList<SongsResult>.toListTrack(): ArrayList<Track> { … }

fun ArrayList<VideosResult>.toListTrack(): ArrayList<Track> { … }
```

Kotlin call sites are untouched — `results.toListTrack()` still resolves on the receiver's static
type, exactly as it did before the second overload existed.

## Traps

**Rename the JVM name, not the Kotlin one.** The Kotlin name is the API, and overload resolution
already knows the element type; spelling it again as `toListTrackFromSongs()` /
`toListTrackFromVideos()` moves that knowledge into every call site. In the file inspected here,
functions named `toTrack()` sit on seven unrelated classes with no annotation at all — distinct
classes have distinct erasures and never collided. The annotation is only paying for the one place
erasure removed information.

**Only an identical erasure clashes, so widening a receiver "fixes" it by changing the API.**
`List<A>` and `ArrayList<B>` erase to different descriptors and coexist untouched. Declaring one of
the pair as `List<…>` therefore compiles — and quietly makes that function accept every list
implementation, which is a different promise than the one it was reviewed under. Change the JVM
name; leave the receiver alone.

**The clash is scoped to the class the declarations land in, not to the module.** Top-level
functions land in a file class named after their file, so two different files can each hold a
`List<X>.toListTrack()` with the same erased signature and never clash — and moving one of a
clashing pair into another file is a genuine fix. The corollary matters more: **a repository-wide
duplicate-name search is mostly false positives.** Group by file before believing it.

**The JVM name is invisible to Kotlin, so nothing keeps it honest.** In the pair inspected here one
annotation reads `"VideoResulttoTrack"` while the function it sits on is `toListTrack`. Kotlin never
mentions the string, so the mismatch has no symptom at all — until a Java call site, a reflection
lookup or a stack frame shows a name nobody chose. Write the name you would want to read there.

**Non-Kotlin callers must spell the JVM name, and only that.** From Java the annotated function is
`ModelToEntityKt.songsResultToListTrack(list)`; the Kotlin name no longer exists on that class. If
the module is consumed from Java, annotation-shaped renames are a source-compatible change for
Kotlin and a breaking one for everyone else — so pick the JVM names once, when the clash first
appears, rather than tidying them later.

**`@JvmName` is refused on open, override and abstract members.** The annotation is only applicable
where the compiler knows no subclass can be affected by the renaming, so a clash between two members
of an open class, or between interface implementations, has no annotation-shaped exit — rename, or
change a parameter type, instead. On a property, the annotation goes on the accessor:
`@get:JvmName(…)` / `@set:JvmName(…)`.

**In a multiplatform module this is a JVM-only constraint written into shared code.** The annotation
is imported from `kotlin.jvm` and compiles in the common source set, which is what makes the pattern
usable at all. But the constraint that forces it exists on one target, so the annotation reads as
unmotivated to anyone looking at the others. Leave a one-line reason next to it, or the next person
removes it and rediscovers the clash.

## Verifying it

Find the real candidates — same function name, same **erased** receiver, **same file**:

```bash
grep -rlE "fun [A-Za-z_][A-Za-z0-9_]*<[^>]*>\??\.[a-zA-Z_]" --include="*.kt" . | while read -r f; do
  dup=$(grep -hoE "fun [A-Za-z_][A-Za-z0-9_]*<[^>]*>\??\.[a-zA-Z_][A-Za-z0-9_]*\(" "$f" \
    | sed -E 's/^fun ([A-Za-z_][A-Za-z0-9_]*)<[^>]*>\??\.([a-zA-Z_][A-Za-z0-9_]*)\($/\1.\2/' \
    | sort | uniq -d)
  [ -n "$dup" ] && printf '%s: %s\n' "$f" "$dup"
done || :
```

Each line is a file plus a `Receiver.functionName` pair declared in it more than once. Drop the
per-file loop and the same pipeline over the whole tree reports pairs that live in different files
and cannot clash — which is why the loop is there. The pattern needs a *generic* receiver, so it is
blind to the other clash class — two extensions on a plain receiver differing only in nullability;
those surface only in the annotation sweep below. When that pair *is* generic the detector does list
it, because the normalization drops the `?`.

Then check that every annotation is carrying its weight, and that its string is the name you want
Java to see:

```bash
grep -rn -A1 "@JvmName" --include="*.kt" .
```

An annotation on a declaration the detector above does not list is defensive, left over from a clash
that has since moved, or guarding the one other clash class — two same-named extensions whose
receivers differ only in nullability, since `T` and `T?` erase to the same descriptor. All three are
worth a comment or a deletion. One of the unlisted annotations here names the opposite direction of
the function it sits on, and a second names a function that does exist in the same file but is not
the one it is on. Neither has a symptom until something outside Kotlin reads it.
