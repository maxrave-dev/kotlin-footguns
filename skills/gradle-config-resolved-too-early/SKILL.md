---
name: gradle-config-resolved-too-early
description: Diagnosing Gradle failures of the form "cannot mutate a configuration after its child configuration was resolved" — why the message names the configuration you touched rather than the plugin that resolved it, how to bisect plugins against a minimal working template, and which fixes are documented dead ends. Reach for it when adding a perfectly ordinary dependency line makes the build refuse to configure, and rewriting that line every possible way changes nothing.
---

# "Resolved before it was meant to be"

The error reads roughly:

```
Cannot mutate the dependencies of configuration ':<module>:<someVariant>'
after the configuration's child configuration ':<module>:runtimeClasspath'
was resolved. After a configuration has been observed, it should not be modified.
```

You get it from a line as ordinary as `dependencies { someVariant("group:artifact:1.2.3") }`. The
build worked yesterday; the only change is that one line, or one newly applied plugin.

## What is actually happening

A plugin creates extra configurations (per variant, per architecture, per flavour) and chains them
into the main graph with `implementation.extendsFrom(variantConfig)`. Somewhere during
`apply()`, something **resolves** `runtimeClasspath`. Resolution freezes that configuration *and
every ancestor it extends* — which now includes your variant configuration. Your dependency line
then arrives too late.

The usual way a plugin resolves at apply time is a task registered with **constructor arguments**:
Gradle must instantiate the task eagerly to pass them, the task's `init` block runs during apply,
and something on that path walks the runtime classpath (typically to locate a jar task's output).

## Traps

**The message names the wrong culprit.** It names the configuration *you* mutated and the child that
was already observed. Neither is the plugin that did the resolving. There is no field in that
message for "who resolved it", so the natural reading — "my dependency line is wrong" — sends you
into rewriting syntax, which is exactly the loop to avoid.

**These are documented dead ends. Do not re-run them.** Every one was tried against this failure and
changed nothing:

- moving the per-variant dependencies into their own earlier `dependencies { }` block;
- `configurations.named("someVariant") { dependencies.add(...) }` instead of the DSL accessor;
- direct Maven coordinates instead of a plugin-provided accessor;
- disabling *one* of the two suspect plugins;
- changing or removing the toolchain declaration — different message, same family.

The pattern in the first three: variations on *how you write the mutation* — and the mutation was
never the problem. The last two probe elsewhere and still change nothing, which is what points the
finger away from your build file entirely.

Note what is *not* in that list. Disabling both suspects together was written down as the next
experiment and never run, so nothing here says the failure needs both out at once — that stayed an
open question. What shipped instead was plugin application order plus a sibling configuration, both
below.

**Bisect plugins, not syntax.** Start from a minimal template that is known to work — the packaging
or framework vendor almost always publishes one — and add your plugins back one at a time until the
error appears. Two published templates worked here; diffing their plugin lists against the failing
module pointed straight at two extra plugins that neither template had, both of which inspect the
runtime classpath eagerly. Treat that diff as a strong hint at the culprit — it is what makes the
bisection short, not a finished diagnosis, and here the diagnosis was never actually closed.

```bash
# adapted — bisection loop, one plugin per iteration
git checkout -b bisect-plugins
# edit <module>/build.gradle.kts: comment out every plugin except the minimal set
./gradlew :<module>:tasks --no-configuration-cache   # configuration phase alone reproduces it
# uncomment one plugin, re-run, repeat until it fails
```

Configuration-phase-only tasks (`tasks`, `help`, `dependencies`) reproduce this without compiling
anything, so each iteration is seconds rather than minutes.

**Plugin application order can be the entire fix.** Some plugins do their task creation at apply
time and only succeed when an artifact-producing task already exists. Applying the packaging plugin
*after* the plugin that provides a plain `jar` task, but *before* a plugin that would later replace
that task with a target-specific one, is a real and load-bearing ordering:

```kotlin
// adapted — one further plugin dropped, comments rewritten
plugins {
    alias(libs.plugins.compose.multiplatform)   // provides `jar`
    alias(libs.plugins.conveyor)                // must see `jar` at apply time
    alias(libs.plugins.compose.compiler)
    alias(libs.plugins.kotlin.multiplatform)    // would otherwise replace `jar`
}
```

Reordering the `plugins { }` block is cheap and worth trying before anything structural.

**A sibling configuration is the escape hatch when order is not enough.** Create your own
configuration that extends the runtime classpath, and let the eager consumer resolve *that* instead;
the lock then lands on a configuration nobody needs to mutate afterwards:

```kotlin
// adapted
configurations.create("desktopRuntimeClasspath") {
    extendsFrom(configurations.getByName("jvmRuntimeClasspath"))
}
```

**Keep the reproduction.** A one-module repro against the vendor's minimal template is what you send
upstream, and it is also what tells you a later plugin release fixed the problem — without it you
will re-derive the whole chain on the next version bump. Record the non-fixes with it; the list is
worth more than the fix, because it is what stops the next person burning an afternoon.

**Related family: strict input/output validation.** Modern Gradle also aborts when a plugin produces
a file that a consuming task uses without declaring it as an input. Same shape — the error names the
consuming task, not the producing plugin. Fix by pinning the producing plugin back to a version that
declares it and adding an explicit `dependsOn` from the consumer as defence in depth.

## Verifying it

Run the configuration phase only (`./gradlew :<module>:tasks`) — if it fails there, nothing about
compilation or your source is involved, which already rules out half of what people check first.

Verify a fix with `--no-configuration-cache`, and treat a green run *with* the configuration cache
as no evidence at all until you have seen it miss: on a cache hit Gradle replays a stored
configuration result instead of re-running the phase that was failing, so the run can be green while
the problem is untouched. Watch the build output for "Configuration cache entry reused" versus
"stored", and force a re-run before drawing a conclusion.
