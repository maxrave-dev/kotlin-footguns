---
name: conveyor-desktop-packaging
description: Packaging a JVM desktop app with a config-driven packager whose HOCON config silently ignores unknown keys — which keys bind at the app level versus a per-OS section versus a nested group, command-line key overrides, pinning the packaging JDK, and the environment block that quietly pins PATH. Reach for it when a key you wrote is having no effect on the built installer and nothing in the build log complains.
---

# Config-driven desktop packaging

A packager of this class reads one declarative config (a HOCON dialect) describing the app once,
and emits a per-OS installer for every machine you list. A build-tool plugin generates a companion
config file holding the classpath, the version, the entry point and the JDK; your hand-written file
`include`s it and adds everything the plugin cannot know.

The format **fails open**: an unknown key is not an error, not a warning, not a note. A key written
at the wrong nesting level is therefore indistinguishable from a key that works — until you open the
built artifact. Read `config-fails-open-verify-artifact` alongside this.

```hocon
# adapted — key names real, values generic
app {
  // Binds on the app-level config object. NOT under mac/windows/linux.
  url-schemes = [ "yourapp", "authcb" ]

  machines = [ "windows.amd64", "mac.amd64", "mac.aarch64", "linux.amd64.glibc" ]

  // Per-machine inputs: each installer carries only the native slice it needs.
  mac.aarch64.inputs += { from = "natives/macos-arm64", to = "runtime-natives" }

  // Genuinely per-OS.
  mac.info-plist.LSApplicationCategoryType = "public.app-category.music"
  windows.start-menu.group = "YourApp"
  linux.desktop-file."Desktop Entry" {   // quoted: the key contains a space
    Categories     = "AudioVideo;Audio;Player;"
    StartupWMClass = "YourApp"
  }

  jvm {
    modules  = "ALL-MODULE-PATH"
    options += "-Xmx512m"
  }
}
```

## Traps

**The nesting level is part of the key, and the per-OS sections are not a free-for-all.** URL-scheme
registration binds on the *app-level* config object; the per-OS objects expose no such key. Writing
`mac.url-schemes` / `windows.url-schemes` / `linux.url-schemes` parses fine and registers **no scheme
at all**, on any platform — silently, so the misplacement persists; in the case this was mined from
it sat inert from the release that first carried the key until moved. Per-OS sections do own genuinely
per-OS keys (the plist entry, the start-menu group, the desktop-file group above), which is exactly
why the wrong placement looks plausible. Tell them apart by building one machine and reading the
generated metadata below, not by intuition.

**A nested group's fields must be *inside* the group.** Desktop-entry keys written as
`desktop-file.Categories` land beside the `"Desktop Entry"` group instead of in it, so they never
reach the generated file — same silent shape as above, different key. Quote any key with a space or
a bracket: `"Desktop Entry"`, `"Comment[en]"`.

**Command-line overrides use `-K<dotted.key>=<value>`, and list values need brackets plus shell
quoting.** This is how you build one slice of the matrix without editing the config:

```bash
conveyor -Kapp.machines=linux.amd64.glibc make linux-app
conveyor '-Kapp.machines=[mac.amd64,mac.aarch64,windows.amd64]' make site
```

Restricting the machine list is also how you keep a target you deliberately do not ship from being
re-entered as an intermediate step and failing the whole run.

**Generate the plugin's config file as its own step, before invoking the packager.** Some packagers
support an include form that executes the build tool and parses its stdout as config. Any plugin in
your build that prints a line during the configuration phase then corrupts the parse, with an error
naming your own log text as a config key. Run the config-writing task first, commit to the static
file:

```bash
./gradlew :<desktop-module>:writeConveyorConfig --no-configuration-cache
conveyor ... make ...
```

**The packaging JDK comes from your build's Java toolchain, not from the packager.** The generated
config carries an `include` of a JDK definition matching the toolchain the plugin observed. Set the
toolchain explicitly in the desktop module, and set the CI runner's JDK to the same major version —
otherwise you package a runtime you never tested against.

**The generated launcher packs its own arguments into a fixed-size buffer, and a full one fails the
build, loudly, not silently.** Every `jvm.options` entry plus the classpath and other "constant app
arguments" the packager computes are packed together into one buffer inside the launcher it
generates — reported as 16384 bytes in this project's own config comment recording the incident;
treat the number as version-specific and read whatever your own build prints instead of trusting it.
This is the opposite failure mode from the rest of this skill: nothing here is ignored, the build
simply refuses to finish, with a message naming neither a byte count nor the buffer — quoted from
that same comment: `Your JVM arguments and constant app arguments together are too large`. A
dependency that ships several per-platform jars can push the classpath alone close enough to the
limit that *any* added option is what finally tips it over — the options themselves are rarely the
real growth. Cut the ones with no functional behavior riding on them first: three flags here existed
only to trim idle heap back to the OS, with nothing in the app depending on them, unlike the
`--add-opens` module opens a few lines up, which reflection at runtime genuinely needs — `-Xmx512m`
itself is only a footprint cap, per that same comment, so losing the trio costs a higher idle RSS and
nothing else. Leave the removed lines in a comment, with the reason — the next person adding an
option here needs to know the margin is already thin:

```hocon
// adapted — own summary of a longer in-file comment; the three removed lines are verbatim
// removed to fit under the launcher's argument buffer, NOT because they stopped being right:
// options += "-XX:MinHeapFreeRatio=20"
// options += "-XX:MaxHeapFreeRatio=40"
// options += "-XX:G1PeriodicGCInterval=60000"
```

**Declaring an environment block on macOS pins `PATH` to the bare system directories**
(`/usr/bin:/bin:/usr/sbin:/sbin`), because the launch services layer applies it instead of inheriting
the user's environment. Before adding one for an allocator or locale setting, audit every place the
app spawns a subprocess: anything resolved by bare name outside those four directories stops being
found, and only when launched from the desktop — the same block never applies to a direct shell
launch, so it looks intermittent and is absent in exactly the configuration you debug in.

**Every scheme, association and category you declare here must also survive the layers after the
packager.** If you re-wrap the packager's output (a directory tree into a single-file portable
bundle, for instance), the wrapper's own generated metadata is what reaches users. See
`desktop-deep-link-plumbing`.

**Dropping an architecture is a native-dependency decision, not a config decision.** A machine you
list must have every native your dependency graph loads — the database driver and the media backend
are the usual gaps. Audit the natives per architecture before adding the machine; one missing slice
fails at first use, not at package time.

## Verifying it

Never trust the config for a claim about the artifact:

```bash
conveyor -Kapp.machines=mac.aarch64 make mac-app     # or your smallest machine
# then grep the produced tree for the feature's fingerprint, e.g.
grep -R 'CFBundleURLSchemes' -A4 output/*.app/Contents/Info.plist
grep -R 'MimeType\|Categories' output/*.desktop
```

Do this once per config key that has no other observable effect, and again whenever you move a key.
Wire the same grep into CI as a hard assertion for the keys you cannot afford to lose.
