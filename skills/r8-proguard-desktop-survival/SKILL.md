---
name: r8-proguard-desktop-survival
description: Running a bytecode shrinker over a JVM desktop app — which optimization families must stay off and why, why obfuscation breaks the rendering and reflection layers, the keep-rule families a native-binding plus coroutines plus HTTP-client app needs, and how to feed the shrunk jars to the packager. Reach for it when the release build starts with a verification error, renders a see-through or blank surface, or fails only in the packaged installer while the development run is fine.
---

# Surviving a shrinker on desktop

Shrinking a desktop JVM app is not the same job as shrinking a mobile one. Three differences drive
everything below: the desktop JVM's **class-file verifier is strict and runs at load time**, the UI
stack reaches its **rendering backend reflectively and by name**, and the **packager builds its
classpath from your build output**, so a shrink step that nothing consumes is invisible.

The policy this skill assumes: shrinking and obfuscation stay **on**, permanently. Runtime breakage
is fixed with additional keep rules, never by turning a pass off. `optimize = false` as a "quick
test" is how a temporary workaround becomes the permanent configuration.

## Traps

**Three optimization families must be disabled; everything else stays on.** Each was found by a
crash in a release build that the development run could not reproduce:

```proguard
-optimizations !method/specialization/*,!code/allocation/variable,!method/inlining/*
```

`-optimizations` is honoured by only one of the two shrinkers that read this rule dialect — the one
this was mined on, and the one pinned here. The other parses the file and ignores the directive
**silently**, so confirm your shrinker actually consumes it before believing these families are off;
otherwise the rule reads as protection while the optimizations still run.

- *Return-type specialization* narrows a method's declared return type from an interface down to its
  single implementation. The call site's bytecode still pushes the interface-typed value, so the
  verifier rejects it with a bad-return-type error — hit the first time any text renders.
- *Local-variable re-allocation* and *method inlining* together re-pack local slots after inlining
  and emit a stack-map frame that disagrees with the real frame on two-slot values (`long`,
  `double`). Symptom: an inconsistent-stack-map error the moment a large generated UI class loads —
  recorded here at startup on the Windows release build. Both are long-standing upstream shrinker
  bugs; check whether they are fixed before re-enabling, do not assume.

Note the shape: **all three fail at class load, not at build time**, and only in the shrunk build.

**Obfuscation breaks anything resolved by name — and it usually fails silently.** Two distinct
symptoms seen here, neither of which throws:

- Renaming the **rendering backend** and the **UI/AWT interop** classes breaks the window
  interop-blending path: canvases and video surfaces render see-through, showing the desktop behind
  them. Nothing is logged.
- Renaming a **vector-animation renderer**'s internals leaves it running but painting nothing — the
  animation area stays blank, no crash, no warning.

Keep those packages un-obfuscated wholesale. "Runs but draws nothing" is the fingerprint of an
obfuscation problem; "throws at startup" is the fingerprint of an optimization problem.

**Keep rules come in families, not one-offs.** For a desktop app with a native binding, coroutines
and an HTTP client, budget for all of these:

```proguard
# adapted — substitute your own packages for the <bracketed> names
# 1. native binding: the JNI/foreign-function layer and anything mapping a native struct
-keepclasseswithmembers class * { native <methods>; }
-keep class <native-binding>.** { *; }
-keep class * implements <native-binding>.** { *; }
-keepclassmembers class * extends <native-binding>.Structure { public *; }

# 2. coroutines runtime — whole package. The optimizer flattens the job type hierarchy and
#    emits an illegal special-invoke for a method reached through an indirect superinterface,
#    which the strict verifier rejects. Narrow rules do not hold here.
-keep class <coroutines-runtime>.** { *; }
-keepclassmembernames class <coroutines-runtime>.** { volatile <fields>; }

# 3. HTTP client + the engine you actually select, including its volatile state fields
-keep class <http-client>.** { *; }
-keepclassmembers class <http-client>.** { volatile <fields>; }

# 4. reflective serialization: companions and generated serializers
-if @<serialization>.Serializable class **
-keepclassmembers class <1> { static <1>$Companion Companion; }
-keepattributes RuntimeVisibleAnnotations,AnnotationDefault

# 5. database runtime + driver, whose generated code delegates into coroutines
-keep class <db-runtime>.** { *; }
-keep class * extends <db-runtime>.RoomDatabase { <init>(); }

# 6. service-loader discovery — the interface name, the implementations, and the resource
-keepnames class <spi-interface>
-keep class * implements <spi-interface> { *; }
-adaptresourcefilecontents META-INF/services/**

# 7. anything reflecting on generic signatures
-keepattributes Signature, InnerClasses, EnclosingMethod
```

**`-dontwarn` is a claim that the code path is unreachable — write down why.** A library compiled
against a different version of a shared rendering or native backend leaves references the shrinker
cannot resolve, and it aborts rather than guessing. Suppressing that warning is correct *only* when
the path genuinely never runs on this platform (a UI effect that platform never renders, a fallback
engine you do not ship) — put that reason in the comment, or the next person's options are "suppress
it too" and "spend a day proving it is safe". If the path *is* reachable, the real fix is a version
alignment; see `transitive-version-pinning`.

**Pin the shrinker version to one that can read your newest class file.** A dependency compiled at a
newer Java release aborts an older shrinker outright — a version bump, not a missing keep rule.

**Feed the shrunk jars to the packager, or you ship the unshrunk ones.** The packaging plugin
auto-detects the classpath from the build, which is the *raw* dependency set. The shrink task's
output has to replace it explicitly, and the config-writing task has to depend on the shrink task:

```kotlin
// adapted — the packager's config-writing task, overriding its auto-detected classpath
tasks.named<WriteConveyorConfigTask>("writeConveyorConfig") {
    dependsOn(tasks.named("proguardReleaseJars"))
    val shrunkJars = layout.buildDirectory.dir("compose/tmp/main-release/proguard")
    doLast {
        destination.get().asFile.appendText(
            "\napp.inputs = [ \"${shrunkJars.get().asFile.absolutePath}\" ]\n",
        )
    }
}
```

The packager expands a directory entry to every file inside it, so one line replaces the whole raw
jar list. Measure the difference — if the installer size did not move, the override did not take.

## Verifying it

The shrunk build only fails in the shrunk build, so a development run proves nothing. After any rule
change, package a release and exercise, in one session: **text rendering** (catches the verifier
issues), **an animation** (catches obfuscation of the animation renderer), a **transparent or video
surface** (catches interop renaming), **one network call**, **opening the database**, and **the
native binding**. Everything on that list has been broken by a shrinker at some point here, each
with its own silent signature.

When something does break, add the keep rule for the **whole package** of the offending library
rather than the single class named in the stack trace — optimization passes reshape neighbouring
classes, so a narrow rule usually just moves the failure one class over.
