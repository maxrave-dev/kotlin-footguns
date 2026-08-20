---
name: native-artifact-for-embedding
description: Producing a native shared library a JVM app can actually load and ship — why a prebuilt portable bundle usually is not a loadable library at all, building on the oldest base system you support, run-path choice, which libraries to deliberately leave out of the bundle, and gating the build on a load-and-initialize smoke test. Reach for it when the bundled native works on every developer machine and fails on a clean one, or when you discover the app has been quietly using a system-wide copy instead of yours.
---

# Building a native artifact you can embed

Embedding is not the same job as running a program. A prebuilt native distribution is built to be
its own process; you need something that opens **inside a JVM that has already mapped the host's
system libraries**. Most prebuilt bundles cannot do that, and the failure is invisible on any
machine that also has the library installed system-wide — the loader silently uses that one
instead. Build the artifact yourself, in a container, and make the build refuse to produce a
slice that cannot load.

## Traps

**A prebuilt portable bundle is usually not a library.** Two independent reasons, and both are
easy to check before you spend a day on it:

- The file named like a shared library is often the **player executable itself** — a
  position-independent executable, which the Linux loader refuses outright to open as a library
  (a per-OS fact: on macOS the same kind of file *can* be loaded as one).
  `readelf -h <file> | grep Type` and `readelf -d <file> | grep FLAGS_1` (a `PIE` flag there is
  the tell).
- Portable bundles ship their own C runtime and program loader, because that is how they stay
  portable. Two C runtimes in one process is not a thing you can have; the JVM already mapped the
  host's. `readelf -d <file> | grep NEEDED` shows what it expects to bring with it.

**Build on the oldest base system you intend to support, and read the floor off the artifact.**
The minimum system-library version a compiled object requires is set by the machine that compiled
it, and it is a floor: build on something new and the artifact simply will not start on anything
older. Do not trust the base image's name in your build file — that number drifts from reality as
the image is bumped. Read it back:

```bash
objdump -T lib<name>.so.N | grep -o 'GLIBC_[0-9.]*' | sort -u -V | tail -1
```

Record what that value maps to for the distributions you claim to support, in the same file as
the base image, so the two are updated together.

**Set the run path as RPATH, not RUNPATH.** RUNPATH applies only to the object that carries it,
so a dependency-of-a-dependency is not found through it; RPATH is inherited down the whole chain,
which is what lets one entry cover the entire closure. The top-level library points at the
subdirectory, and the siblings point at themselves:

```bash
patchelf --force-rpath --set-rpath '$ORIGIN/lib' "$OUT/lib<name>.so.N"
for so in "$OUT"/lib/*.so*; do patchelf --force-rpath --set-rpath '$ORIGIN' "$so"; done
```

Verify with `readelf -d <file> | grep -E 'RPATH|RUNPATH'` — some `patchelf` versions default to
RUNPATH, which is why `--force-rpath` is not optional.

**Exclude the base-system libraries on purpose, by name.** "Everything `ldd` printed" is the
wrong closure: shipping a second C runtime, math library, C++ runtime or program loader is the
failure that ruled out the portable bundle in the first place. Keep the exclusion list explicit
and near the copy loop, so adding a library to the bundle is a decision someone made rather than
a side effect.

```bash
# adapted — compressed from the staging script
SYSTEM_LIBS="libc.so.6 libm.so.6 libdl.so.2 libpthread.so.0 librt.so.1 libutil.so.1
ld-linux-x86-64.so.2 libgcc_s.so.1 libstdc++.so.6 libresolv.so.2
libz.so.1 libbz2.so.1.0 liblzma.so.5"

is_system() { local n="$1"; for s in $SYSTEM_LIBS; do [[ "$n" == "$s" ]] && return 0; done; return 1; }
```

Widely-shared libraries that are *not* strictly base-system belong on this list too if the host
application uses them independently — a bundled copy that wins the name can break an unrelated
part of the host process. Prefer removing such a library from the bundle over working around it
in application code.

**Libraries installed outside the loader cache vanish from the closure silently.** Anything you
built into a local prefix is not in the cache on a bare image, so `ldd` reports it "not found",
the copy loop skips it, and the staged slice looks complete but cannot load. Register the prefix
and refresh the cache *before* walking dependencies:

```bash
# adapted
echo "/usr/local/lib" > /etc/ld.so.conf.d/local.conf
ldconfig
```

**Copy through symlinks** (`cp -L`) when staging — the entries `ldd` prints are usually links into
a versioned file, and a link with nothing behind it is a load failure at the user's end.

**Trim what the embedding path can never reach.** If you drive the engine through its software
render path, the whole GPU/shader stack is unreachable code that still has to be shipped and
signed; disabling it at configure time removed the single largest chunk of the closure here. The
same for encoders in a playback-only app. Two cautions: a subsystem you disable takes its
*options* with it (a build without the scripting layer genuinely has no option to turn scripting
off — see the feature-detection rule in the sibling skill `embed-media-engine-desktop`), and an optional audio filter you
disable is one your runtime code must be able to do without.

**Gate the build on load-and-initialize, in the builder.** Two gates, both failing the build:

1. Resolution check — `ldd` every staged object and fail on any `not found`.
2. A tiny program that opens the staged file **by absolute path, with local scope**, resolves the
   symbols you actually call, and runs the library's init:

```c
void *h = dlopen("/out/lib<name>.so.N", RTLD_NOW | RTLD_LOCAL);
if (!h) { printf("dlopen FAILED: %s\n", dlerror()); return 1; }
void *ctx = create();                 // adapted: engine's own create/init pair
if (!ctx) { printf("create returned NULL\n"); return 1; }
int rc = init(ctx);
return rc == 0 ? 0 : 1;
```

Run it under the numeric-locale state the app will actually enforce. The JVM adopts the *user's*
locale at startup (it calls the set-locale routine with an empty name), which is why an embedding
app must force the numeric category back to C itself before initializing an engine that parses
numbers in the C locale — and why the smoke test sets `LC_NUMERIC=C` too: it exercises the
artifact under the same state the app guarantees at runtime. A slice that resolves everything and still fails to initialize is
exactly what ships when the only gate is "the files are present".
