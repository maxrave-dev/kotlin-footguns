# Raw mining report — Lane 2: Git history (1408 commits main + ~250 core submodule, 2023-04-15 → 2026-08-17)

> Mined 2026-08-19. 48 candidates. Key structural finding: the `docs: record ...` commits have EMPTY bodies — the long-form write-ups live in tracked files (CLAUDE.md changelog section, desktopApp/MEMORY_TUNING.md, .omc/plans/conveyor-migration.md, docs/import-format-v1.md). ~46 commits (33 main + 13 core) have genuinely long bodies, concentrated in 2026.

### 1. `jna-native-library-bundling`
**Trigger:** Bundling a native `.so`/`.dll`/`.dylib` with a JVM/desktop app and loading it via JNA.
- **JNA silently falls back to a system-wide library.** The bundle can be entirely broken and it still "works" on your dev machine. **Always log `NativeLibrary.getInstance(name).file`.**
- **JNA's `OPTION_OPEN_FLAGS` is POSIX-only.** Passing `2` (RTLD_NOW) is forwarded verbatim to `LoadLibraryEx` on Windows, where `2` = `LOAD_LIBRARY_AS_DATAFILE`: the DLL maps as inert data, imports never resolve. Surfaces as the misleading `Error looking up function 'X': The specified module could not be found`. Gate the flag on non-Windows.
- **Prebuilt "portable" bundles are usually PIE executables, not shared libraries.** glibc refuses to `dlopen` a PIE (`DF_1_PIE`); patch past it and the bundled glibc collides with the one the JVM already mapped.
- Resolve by absolute path with an explicit fallback chain (system property → app resources dir → walk up from JAR → conventional dir).
- Set `DT_RPATH`, **not** `DT_RUNPATH` — RUNPATH is not inherited by transitive dependencies.
- Gate the build on a `dlopen` + init smoke test; a bundle that links but won't initialize is the common failure.
**Evidence:** core `95836d4`; `88be088b`; `e027443c`; CLAUDE.md.
**Generality:** A

### 2. `macos-codesign-appledouble-sidecars`
**Trigger:** macOS app is signed and notarized, passes locally, but users get "X is damaged and can't be opened."
- Tarring files **on macOS** writes each file's xattrs out as a companion `._name` AppleDouble sidecar.
- The packager signs those sidecars as ordinary bundle members and seals them into `_CodeSignature/CodeResources`.
- macOS **folds `._name` back into the xattrs of `name` and deletes the sidecar** the moment Finder touches the app — unzipping it *or* dragging it out of a DMG.
- `codesign --strict` reports *"a sealed resource is missing or invalid"*; the user sees "damaged".
- **Fix: strip every `._*` after unpacking, before packaging.** Only macOS is affected.
**Evidence:** `e027443c`; CLAUDE.md.
**Generality:** A

### 3. `proguard-r8-jvm-desktop-survival-guide`
**Trigger:** Desktop JVM release build fails at runtime with `VerifyError`, or renders wrong, while the debug build is fine.
- **`method/specialization` narrows a declared return type to its only impl.** ProGuard rewrote `ActualParagraph()`'s return from the `Paragraph` interface to `SkiaParagraph`; bytecode still pushes an interface-typed value → JVM 21 verifier throws `VerifyError: Bad return type` the moment *any* `Text()` renders. Disable with `-optimizations !method/specialization/*`.
- **`method/inlining` + `code/allocation/variable` emit a StackMapTable that disagrees with the real frame on 2-slot longs/doubles** — `VerifyError: Inconsistent stackmap frames ... top not assignable to long`, fired when a large Composable class loads at startup. Known unfixed upstream (Guardsquare/proguard#443, #302).
- **`kotlinx.coroutines` needs a full keep under `optimize`:** R8 flattens the Job hierarchy and emits illegal `invokespecial` for `Job.cancel()` reached via indirect superinterface. Keep the package plus its `volatile <fields>` (compiler-generated state machines).
- **Obfuscating Skiko/Skia/`compose.ui.awt`/`compose.ui.interop` breaks transparent-window blending** — Canvas and video render see-through onto the desktop. Symptom is visual, not a crash.
- Disable *narrowly*. Shrinking, obfuscation and class-merging stay on.
- Pin your ProGuard version to one that can **read your bytecode level** (7.8.1 for Java 25 class files).
**Evidence:** `3a4d0fca`, `240b7536`, `5d3685f7`, `fe011d46`, `c3b9f0e5`, `5c2c71bd`, `5a3e692c`, `a84c4877`.
**Generality:** A

### 4. `jvm-desktop-memory-fragmentation`
**Trigger:** Desktop JVM app sits at ~1 GB RSS, or RSS climbs for hours, and the heap is provably small.
- **Rule out the heap first, with evidence.** `jcmd GC.heap_info` showed 121 MB used of a 512 MB cap while RSS was 1.90 GB.
- **Rule out handle leaks by counting a thing you can count.** Each native player handle owned one named event-pump thread; a 60-sample / 30-minute run showed the count flat at 3.
- **The decisive test:** call `malloc_trim(0)` on the live process. 920 MB → 753 MB. *Memory that can be returned on demand was already free — fragmentation, not a leak.*
- **glibc's per-thread arenas are the amplifier.** Ceiling `8 × nproc`, spawned on allocator lock contention, never given back. 20-core box: 161 anon mappings on 64 MB boundaries holding 1451 MB. **RSS depends on the user's core count.**
- Four independent fixes, each individually revertible: `MemoryTrimmer` via JNA (`malloc_trim(0)` Linux / `HeapSetInformation(HeapOptimizeResources)` Windows 8.1+), G1 heap uncommit flags, `MallocNanoZone=0` on macOS, `MALLOC_ARENA_MAX=2` on Linux. Ship a symptom→suspect→undo table.
- **The macOS branch is a trap.** `malloc_zone_pressure_relief(NULL, 0)` with a null zone means *every registered zone* — including Metal, QuartzCore and Skia. Off a background dispatcher it lands inside a main-thread `CATransaction` commit; uncaught NSException in `-[MTLLayer blitCallback]`, hard crash on macOS 26+. The window is so narrow that attaching `log stream` hid it — it only reproduced on a real Finder/Dock launch.
**Evidence:** `desktopApp/MEMORY_TUNING.md`; `11f59269`; core `15b9ba2`.
**Generality:** A — one of the strongest standalone skills in the repo.

### 5. `conveyor-desktop-packaging`
**Trigger:** Packaging a Compose Desktop / JVM app with Hydraulic Conveyor.
- **`-K` overrides take HOCON list syntax, not CSV.** `-Kapp.machines=mac.amd64,mac.aarch64` parses as one machine spec and dies with `Unrecognized machine attribute 'amd64,mac'`. Use `-Kapp.machines=[a,b,c]`.
- **Key placement is silently load-bearing.** `url-schemes` binds on `AppConfig` — top level of `app`, not `app.mac`/`app.windows`/`app.linux`. HOCON accepts unknown keys without complaint; every packaged build shipped with **no `CFBundleURLTypes` at all** for ~3 months. Same bug parked `desktop-file.Categories` beside the `"Desktop Entry"` group. **Prove placement by diffing two builds that differ only in where the key is written.**
- **The stdlib JDK preset does not cover every machine.** Temurin ships no `windows.aarch64`; `make site` fails with "JAR files were imported but no JVM inputs were supplied". Override that one machine surgically (Microsoft Build of OpenJDK).
- **Conveyor wipes `output/` on the next `make`** — stage cross-OS artifacts out of it between runs.
- The Gradle plugin creates per-machine configurations and chains `implementation.extendsFrom(machineConfig)`; a plugin that eagerly resolves `runtimeClasspath` during apply makes those configurations immutable → *"Cannot mutate the dependencies of configuration ..."*. Bisect plugins; minimal plugin sets in the official starter templates work.
**Evidence:** `21d016fa`, `ebe15774`, `5d8e84ec`, `d291ffe8`, `33f0925f`; `.omc/plans/conveyor-migration.md`.
**Generality:** B

### 6. `packaging-config-silent-unknown-keys`
**Trigger:** A config-driven feature "is implemented" but demonstrably never happens in the shipped artifact.
- HOCON, YAML and JSON configs commonly accept unknown keys silently. A key written one level too deep is not an error — it is a no-op that survives code review indefinitely.
- Verify against the **generated artifact**, not the config: diff two builds; inspect `Info.plist`, `.desktop`, manifest.
- Check the library's own source for which config class a property binds to.
- A whole feature chain can be dead at several links at once: config key misplaced **and** argv filter matching a hardcoded scheme list **and** the AppImage's `.desktop` lacking the handler. Fixing one link changes nothing observable.
**Evidence:** `d291ffe8`, CLAUDE.md.
**Generality:** A

### 7. `lastfm-api-integration`
**Trigger:** Implementing Last.fm scrobbling or auth in any client.
- **`status="ok"` does not mean accepted** — `ignoredMessage` codes: 1 artist filtered, 2 track filtered, 3/4 timestamp past/future, 5 daily limit. Log 1/2 loudly.
- **Two auth flows, not interchangeable**: web flow (no token → provider mints + redirects to callback) vs desktop flow (`auth.getToken` then `&token=` → "return to the application" page, never redirects). Registered callback ⇒ use web flow.
- **`format`/`callback` must be excluded from `api_sig`** (sort by name, concat `<name><value>`, append secret, MD5) — else code 13 on every request.
- **Parse as loose `JsonObject`** — XML-translated JSON: numbers as strings, attributes under `@attr`, object-or-array fields.
- Docs contradict themselves: `timestamp` = track **start**; always send `duration`.
- Error codes: `9` → clear session + re-auth; `11`/`16`/`29` transient; else malformed.
- Threshold: >30 s, at half length or 4 min.
**Evidence:** `81914386`, `48cff135`, `9c6c6414`; CLAUDE.md.
**Generality:** A

### 8. `oauth-callback-token-must-not-travel-through-navigation`
**Trigger:** "Login succeeded but the app is still on the login screen."
- Handing a deep-link callback token to the **navigation layer** pushes a *second* copy of the login screen; post-login `navigateUp()` peels off only that copy.
- Deliver the token **straight to the shared/session view model**; the login screen closes itself by observing the stored session key.
- WebView-embedded logins never hit this; the bug is specific to **system-browser** auth.
- Corollary: argv/intent filter must match **any** `scheme://`, not a hardcoded list.
**Evidence:** CLAUDE.md; `48cff135`.
**Generality:** A

### 9. `media3-crossfade-dual-player`
**Trigger:** Implementing gapless/DJ crossfade with two ExoPlayer (or any dual-player) instances.
- **Every guard belongs on BOTH trigger paths** (position-polling job + EOF callback; EOF path early-returns when `isCrossfading` → guard added only there is dead code with no symptom).
- **`seekTo()` is the transport command everyone forgets** — cancel/commit the crossfade first, or the seek lands on the wrong player.
- **Equal-power (cos/sin), not linear** — linear dips perceived loudness at the midpoint.
- **Front-load the tempo/pitch ramp:** reach target within the first ~20% and hold; a linear ramp only matches BPM when the outgoing track is already silent.
- **BPM ratio direction:** applied to the *outgoing* player → `nextBpm/currentBpm`.
- Exclusions: track shorter than `max(20 s, duration × 3)`; either track is video; optionally same-album. **Album membership = set of ids, not a count** (shuffle + radio appends).
**Evidence:** core `4ed55eb`, `10f4c54`, `b79a51f`, `f9f1fb5`, `e98a95e`, `13c81b9`; `c8714719`/`e8913f7d`; CLAUDE.md.
**Generality:** A

### 10. `media3-foreground-service-state-ended-trap`
**Trigger:** Playback dies between tracks on Xiaomi/Samsung ROMs, or the notification vanishes mid-queue.
- When you swap players, the outgoing ExoPlayer fires `STATE_ENDED` before the next is swapped in.
- Media3's `MediaLibraryService` reads that as "playback ended" and **detaches the foreground-service notification**.
- On aggressive ROMs (HyperOS, OneUI) a **~25 ms gap** is enough for the OS to freeze the process.
- Fix: a `suppressPlaybackEnded` flag on the forwarding player remapping `STATE_ENDED → STATE_BUFFERING` in `getPlaybackState()` during the transition window.
**Evidence:** core `5b45954` (fixes #2022, #1965).
**Generality:** A

### 11. `android-audio-focus-across-player-swaps`
**Trigger:** Background playback pauses between tracks; autoplay stalls.
- Per-player `handleAudioFocus` means **releasing the outgoing player abandons audio focus** for the whole app.
- Manage a **single app-level `AudioFocusRequest`** in the adapter that owns the swap (cf. androidx/media#2100).
- Related, same commit: persist position to DataStore **every 5 s while playing**; **cancel the previous progress loop** or every track leaks another save loop.
**Evidence:** core `f293309` (#2155, #2152).
**Generality:** A

### 12. `stateflow-conflation-hides-write-order-bugs`
**Trigger:** UI shows a spinner over playing audio, or any state reliably the *opposite* of reality.
- Handler wrote 2-3 values in a row; StateFlow conflates; collector on another thread sees only the **last**. Loading shown when buffering just *finished*.
- Emitter job didn't cancel its predecessor → leaked 500 ms emitter per track (sibling job already fixed for this, #2152 — nobody generalized).
- **A conflating flow makes "how many times and in what order do I write?" a correctness question.** Write once, at the end, from one place.
- Neighbours: `position = -1L` sentinel rendering `NA:NA`; `bufferedPercentage × duration` vs `currentPosition` unit mismatch (~100×).
**Evidence:** core `ff53da7`; CLAUDE.md.
**Generality:** A

### 13. `room-rawquery-cannot-vacuum`
(As docs lane #29 — KSP `isReadOnly = true`, readers `PRAGMA query_only = 1`, checkpoint accepted on same connection hides it, `useWriterConnection { execSQL("VACUUM") }`, checkpoint first, failure must not surface.)
**Evidence:** `9155f673`; CLAUDE.md.
**Generality:** A

### 14. `sql-not-in-nullable-column-matches-nothing`
(As docs lane #27 — `x NOT IN (a, NULL, c)` = NULL never TRUE; playlist sweep deleted 0 rows silently; add `IS NOT NULL`; treat "0 rows affected" as a failure signal.)
**Evidence:** `9155f673`; CLAUDE.md.
**Generality:** A

### 15. `sqlite-like-wildcard-escaping`
(As docs lane #28 — `_` wildcard, 1,748 ids contained it; quoted-token matching; nested replace + `ESCAPE '\'`.)
**Evidence:** `9155f673`; CLAUDE.md.
**Generality:** A

### 16. `cascading-delete-sweep-design`
(As docs lane #25/26 — containers first leaves last (songs alone deleted 0; 11,322/12,221 held by playlists); kept-by-state columns (`liked`, `downloadState`); DELETE re-checks conditions; pin live queue; checkpoint+VACUUM; 57→12 MB; fix the source too: unfollow now cleans satellites — core `ac87824`.)
**Evidence:** `9155f673`; core `ac87824`; CLAUDE.md.
**Generality:** A

### 17. `innertube-youtube-music-parsing`
**Trigger:** Scraping/parsing YouTube (Music) InnerTube responses.
- **Renderers get wrapped, and only when authenticated.** 161/197 rows wrapped; 50-track page arrived as 6. Read bare renderer, else `primaryRenderer`.
- **Prove the auth dependency by elimination:** six anonymous requests varying one factor each → zero wrappers; authenticated capture → 48/50.
- **Config fields move between response shapes** (`musicVideoType` rides overlay play button on search rows, title column on playlist rows) — read all locations, **fall through on the value, not the endpoint**.
- **Identify columns by `pageType`, not fixed index.**
- `counterpart` = the other rendition (Song/Video switch).
- Only the first subtitle group is artists.
**Evidence:** core `45a2a96`, `7e50040`, `385f69b`, `6b1c073`; CLAUDE.md.
**Generality:** B

### 18. `dont-invent-enum-values-read-the-api`
(As docs lane #34 — invented labels, view count smuggled into type column, fix via existing update paths not migration, normalize on read, enum in the module both consumers depend on, null = "API didn't say" + `isKnown`.)
**Evidence:** `9155f673`; CLAUDE.md.
**Generality:** A

### 19. `foss-vs-proprietary-build-variants-via-module-pairs`
(As docs lane #11 + details: stub's availability probe hides settings; "FOSS ships no API secret so no code that needs one"; `local.properties` → BuildKonfig → `configX(...)`; select in EVERY consuming module; `f83e4080` temp hotfix for F-Droid Sentry properties.)
**Evidence:** `81914386`, `621dc7e8`, `f83e4080`; CLAUDE.md.
**Generality:** A

### 20. `bundled-native-lib-claims-system-soname`
(As docs lane #3 — glib 2.72 claimed soname; `XDesktopPeer` died `g_dir_unref`; whole `java.awt.Desktop` unsupported for process lifetime; 23 call sites broke; probe `Desktop.isDesktopSupported()` before native load; real cure = `SYSTEM_LIBS` exclusion; `xdg-open` → `gio open` → `$BROWSER` fallback + toast.)
**Evidence:** CLAUDE.md; `e027443c`.
**Generality:** A

### 21. `coreaudio-hotplug-released-handle bug`
(As docs lane #19 with the full upstream chain: bare failure label leaves system listener registered; `driver_initialized` flag set only after success so uninit never runs; one-handle-per-item + crossfade arms it; ASCII crash address `"Instance"`; `ao=avfoundation,` with trailing comma; wire `mpv_request_log_messages()` before you need it.)
**Evidence:** core `09c43e1`; CLAUDE.md.
**Generality:** A

### 22. `library-usage-outside-its-design-envelope`
**Trigger:** A stable, widely-used native library crashes only in your app.
- mpv, VLC and most media libraries assume **one instance, one process, one lifetime**. Precaching and crossfade break all three simultaneously.
- Error paths that are harmless when init happens once become **latent process-wide instability** when init happens per item.
- Ask explicitly: *how many times does this library expect to be initialized, and does anything it registers outlive the handle?*
- Same envelope question explains the AppImage failure, the JNA fallback masking, and the glib soname collision.
**Evidence:** CLAUDE.md; core `09c43e1`, `95836d4`, `ccaa2d1`.
**Generality:** A

### 23. `native-property-writes-must-be-thread-confined`
**Trigger:** Rare released-handle bug when a native handle is released concurrently with a property write.
- `release()` flipped `isReleased` **synchronously** then spawned destruction — check-then-act race with a several-ms window.
- Confine **every** property write to the one thread that also performs the release; "released" and "writing" become mutually exclusive by construction.
- Threads that cannot hop (native event pump handling `AUDIO_RECONFIG`) need a lock — the only path a dispatcher can't cover.
- **Settings must reach every live handle** — the "secondary" handle during a transition belongs to neither collection; process-wide properties mean a missed handle *undoes* the others.
**Evidence:** core `f9f7f93`, `e855222`, `3329b1a`; CLAUDE.md.
**Generality:** A

### 24. `replace-swingpanel-with-compose-frame-streaming`
(As docs lane #18 + `StateFlow<FrameSource?>` set **unconditionally** during transitions; native renderer letterboxes into reported size — crop via renderer's own property (mpv `panscan`) from a `LaunchedEffect`.)
**Evidence:** core `f9f7f93`; CLAUDE.md.
**Generality:** A

### 25. `compose-multiplatform-delete-the-expect-actual`
**Trigger:** An `expect`/`actual` abstraction is blocking you from sharing code.
- A **KMP artifact declared in `commonMain.dependencies` is already resolving for every target** — the JVM `actual` was simply never written, so every glass surface on Desktop was silently a plain rounded box.
- **The `expect class` was itself the blocker** — no relationship to the library's type, so the library's API could not be called from `commonMain`; a 200-line effect stayed stuck in `androidMain`.
- Once the library exists on both targets, **the abstraction has nothing left to abstract.** Delete it; keep a `typealias` so ~20 call sites don't change.
- Check whether your `actual` is a real implementation or an empty stub before assuming a feature works cross-platform.
**Evidence:** `04c62b09`, `ff10e20f`; CLAUDE.md.
**Generality:** A

### 26. `kmp-module-structure-migration-2026`
**Trigger:** Your `composeApp` module is a KMP library *and* the JVM app entry *and* the desktop packaging host.
- AGP 9+ **removes the Android application plugin inside KMP modules** — the split is coming regardless.
- Target shape: `composeApp` = KMP library (`android.kotlin.multiplatform.library` + `jvm()`), `androidApp`, `desktopApp` = plain `kotlin("jvm")` holding `compose.desktop` + packaging. Entry: `fun main(args) = runDesktopApp(args)`.
- **Packagers, Compose Hot Reload and the application plugin all land more cleanly on a `kotlin("jvm")` module.**
- Sequencing lesson: a Conveyor migration hit KMP-specific Gradle incompatibilities; correct move was to pivot to the structure migration first, land it, verify, defer packaging.
- Verify with `compileKotlinJvm` → `desktopApp:compileKotlin` → `desktopApp:run` + end-to-end playback/auth.
**Evidence:** `36eb81ef`, `33f0925f`, `d291ffe8`, `cb4967f0`; `.omc/plans/conveyor-migration.md`.
**Generality:** A

### 27. `gradle-plugin-eager-configuration-resolution`
**Trigger:** *"Cannot mutate the dependencies of configuration ':X' after ... ':runtimeClasspath' was resolved."*
- Chain: plugin creates per-variant configurations + `implementation.extendsFrom(variantConfig)` → a task registered with **constructor args** forces eager instantiation during apply → `init {}` resolves `runtimeClasspath` → `implementation` and parents frozen.
- **The error names the wrong culprit** — it points at the configuration you're mutating.
- **Bisect plugins, not syntax.** Documented non-fixes: separate `dependencies {}` blocks, `configurations.named { }`, direct coordinates, disabling one plugin, changing toolchain.
- Compare against a minimal working template; diff the plugin list.
- Gradle 9 strict validation: plugin not declaring generated output as input to consuming tasks → pin back + explicit `dependsOn`.
**Evidence:** `.omc/plans/conveyor-migration.md`; `9892117c`.
**Generality:** A

### 28. `transitive-version-pinning-nosuchmethoderror`
**Trigger:** `NoSuchMethodError` at runtime after adding an unrelated UI library.
- A new dependency pinned `skiko` with Gradle `strictly`, dragging the desktop tree up — that version had **removed** `Matrix33.makeTranslate(float,float)`, crashing compottie.
- **`strictly` from a transitive dependency silently overrides your BOM.** Counter with `resolutionStrategy.eachDependency { useVersion(...) }`.
- Justify by scope: the library wanting the newer version was never rendered on that platform → pinning back cost nothing.
- Forward direction: `HazeProgressive` calls `ShaderBrush.createShader(Size)` with a mangled signature not matching pinned Compose — `NoSuchMethodError` inside the draw pass. Guard the call site by platform.
- **Document why a version is pinned, including what the next version breaks.**
- When the platform library removes an API, migrate call sites to your own `expect/actual` wrapper.
**Evidence:** `bf850feb`, `9892117c`; CLAUDE.md.
**Generality:** A

### 29. `windows-vm-detection-post-wmic`
**Trigger:** Windows 11 detection code returns empty; app renders nothing or eats clicks in a VM.
- **`wmic` was deprecated in Win10 21H1 and is not installed on Win11 by default.** Probes built on it return empty silently.
- Consequence chain: `isVM = false` → undecorated + transparent window → Parallels Win 11 ARM rendered nothing / clicks eaten.
- Replacement: PowerShell `Get-CimInstance Win32_ComputerSystem`, wmic as fallback.
- **Probe BOTH `Manufacturer` and `Model`** — Parallels-on-ARM puts the brand only in Manufacturer.
- Vendor tokens: Parallels, VirtualBox, VMware, QEMU, KVM, Xen, Hyper-V.
**Evidence:** `067f2b2e`.
**Generality:** A

### 30. `windows-msix-offline-sideload-installer`
**Trigger:** CI produces MSIX output end users cannot actually install.
- Raw packager output is **unusable offline**: wrapper + `.appinstaller` fetch cert/manifest from `${site.base-url}` on GitHub `/latest/download/`, 404 until a release carries those exact files; cert was missing from the upload.
- Ship a self-contained zip: `install.bat` (UAC self-elevate → `certutil` add cert → `Add-AppxPackage`) + `.crt` + `.msix`.
- Keep the self-signed cert **stable across builds** by pinning the signing key.
- Verify architecture on a real host.
**Evidence:** `15b9814a`, `bd641bf4`.
**Generality:** A

### 31. `arm64-native-dependency-gap-audit`
**Trigger:** Deciding whether to ship a Windows/Linux ARM64 build.
- **Audit every native dependency for ARM64 before promising the target.** Skiko, VLC, Microsoft JDK all had ARM64 — but `androidx.sqlite:sqlite-bundled-jvm` ships **no `windows_arm64` sqliteJni.dll**; Room fails at first connection.
- **One missing native kills the whole target.**
- Correct call: drop the target; let users run x64 under emulation (Windows Prism works).
- **Preserve the plumbing in git history and say so in the commit.**
- VideoLAN ships no Linux ARM binary at all.
**Evidence:** `bd641bf4`, `16872e1c`, `ebe15774`.
**Generality:** A

### 32. `ci-flaky-by-timing-luck`
**Trigger:** A CI step that passed for months starts failing after a runner image update.
- Two jobs mounted a volume with the **same name**; `hdiutil detach` releases **asynchronously** → second `attach` hits `EBUSY` — or silently remounts as `"SimpMusic 1"`, which *succeeds with the wrong path*. **It only ever passed by timing luck.**
- Fixes: detach stale resources first; **capture the tool's reported mount point instead of hardcoding**; retry + force-detach.
- **Download mirrors are a lottery.** `get.videolan.org` 302s to a different mirror per request. Java's `URL.openStream()` **silently saves the 302 HTML body** on cross-protocol redirect — surfacing later as "Cannot expand ZIP". Use `curl -fsSL` with retry.
- Both bugs share a shape: **a step that "succeeds" while producing the wrong artifact** is far more expensive than one that fails.
**Evidence:** `ed524090`, `76229820`.
**Generality:** A

### 33. `reproducible-native-bundling-two-task-split`
**Trigger:** You need native artifacts on CI runners that can't host the build toolchain.
- **Split into two entry points:** `bundleAll` on a dev machine once per version bump (slices → tarballs → SHA-256); `setupAll` on CI (download → verify against digests pinned in source → unpack).
- Publish tarballs to a dedicated release repo; pin digests in the build file.
- **Both workflows must invoke `setupAll` explicitly** — an external packaging action never triggers Gradle `dependsOn`.
- From-source container build pinned to old glibc beats extracting prebuilt bundles (deleted ~186 lines of DwarFS extraction/rpath rewriting).
- **Disable everything you don't use** — dropped shaderc/glslang/SPIRV (bundle bulk) and libsixel (JVM aborts).
- Version-skewed source warning: IINA's libmpv needs `_pl_log_create_349`, its bundled libplacebo exports `_338` — fails `dlopen` under both RTLD modes.
**Evidence:** `88be088b`, `e027443c`; CLAUDE.md.
**Generality:** A

### 34. `material-symbols-imagevector-migration`
(As docs lane #37; scale reference 59+25 icons / 117+167 call sites / 44 XML deleted; component signatures `DrawableResource`/`Painter` → `ImageVector`.)
**Evidence:** `b130623b`, `3f0f7a18`; CLAUDE.md.
**Generality:** A

### 35. `liquid-glass-highlight-directional-default`
(As docs lane #38 — Highlight directional default, 4 burned builds, ruled-out non-fixes, sibling backdrop source, swap experiment, `highlight` parameter threading.)
**Evidence:** `ff10e20f`, `04c62b09`, `8540ff90`; CLAUDE.md.
**Generality:** B

### 36. `one-boolean-two-questions`
**Trigger:** A layout flag was forced to a constant "temporarily" and broke something unrelated.
- One `isMobilePortrait` answered **two questions** (immersive treatment + which header); forcing `true` broke only the header — looked harmless.
- The temporary force **replaced the body of one branch** → shipped as a regression on the working platform. Force flags must not delete the alternative.
- **Gate layout on the actual question — `wDP < hDP` — not platform.**
- **`enum.ordinal` is an identity, not a position** (three nav components, mixed comparisons, reordering exposed it).
- Duplicated tab lists across components all must be updated or the item never renders.
- Phone→desktop audit list: `aspectRatio(1f)`, `ContentScale.FillWidth`, scrim sized off width.
**Evidence:** `ff10e20f`, `73c7bf95`; CLAUDE.md.
**Generality:** A

### 37. `sleep-timer-fade-needs-its-own-gain-line`
(As docs lane #16 — separate `sleepFadeFactor`, tail because gain sits ahead of the sink, restore in adapter's own `finally` not queued by caller, cast early-return clears inline, equal-power curve.)
**Evidence:** CLAUDE.md (issue #2330).
**Generality:** A

### 38. `discord-rpc-and-third-party-session-hygiene`
**Trigger:** Rich presence flickers, races on auth, or blocks your media thread.
- Presence updates **event-driven**, not polled — polling broke the media thread.
- Fix the **gateway auth race**: writes before handshake completes are dropped silently.
- **Gate on login state**; **reset login-gated toggles on logout** (else a switch stays "on" for a service the user is no longer authenticated to; every call fails invisibly).
- Same pattern applied to Spotify; "user logged out" must fan out to every dependent setting.
**Evidence:** core `b920f2c`, `9301975`; `54dee13a`, `d0831728` (#2157, #2064).
**Generality:** B

### 39. `third-party-login-url-matching`
**Trigger:** WebView-based third-party login works for you and fails for users in other locales.
- Success-detection regexes over redirect URLs break on **locale path segments** — match with and without the segment, tolerate query strings.
- Three separate fix commits over six months; write the matcher permissive the first time.
- Don't ask users for data you can derive (Netscape cookie field removed once derived from the WebView cookie store).
**Evidence:** `f7b4f290`, `54fce50d`, `0496a435`, `4da72476`, `c9616233`.
**Generality:** A

### 40. `third-party-endpoint-resilience`
**Trigger:** A feature silently stops working because a community-hosted endpoint died.
- A dynamic uptime-checker worker went offline → **silently disabled** a downstream feature with no error surfaced.
- Replace with a **hard-coded priority list + sequential probing**, cache first reachable instance with short TTL (5-10 min), mutex-guarded, honour user override.
- **Leave the dynamic path in the code** but don't depend on it.
- Prefer streaming-capable list, fall back to metadata-only, **skip the call entirely if both empty**.
- Meta-lesson: **any feature whose failure mode is "silently does nothing" needs an explicit health signal.**
**Evidence:** core `65a280c`, `316ad8d`; `904acb4d`.
**Generality:** A

### 41. `desktop-single-instance-before-di-init`
**Trigger:** Launching a second copy of a desktop app crashes with a file-rename IOException.
- DataStore singleton was `createdAtStart` in the DI graph → second instance touched `settings.preferences_pb` and crashed **before** the in-Compose single-instance check ran.
- **The single-instance guard must run before `startKoin`** — before anything touches shared on-disk state.
- Second instance: forward the deep link to the running instance, then exit, touching nothing.
- Generalizes to lock files, sockets, SQLite, log files.
**Evidence:** `0f878947` (#2044).
**Generality:** A

### 42. `compose-hot-reload-and-mcp-driven-ui-measurement`
(As docs lane #43.)
**Evidence:** `73c7bf95`; CLAUDE.md.
**Generality:** A

### 43. `compose-lyrics-wall-clock-animation`
**Trigger:** Per-word/karaoke animation stutters because it's driven by a low-rate data timeline.
- **Decouple animation from emit rate.** Pre-plan each word's trajectory in **wall-clock** time: active word snaps to current percentage then `animateTo(1f)` over the remaining ms → 60 fps regardless of a 50 ms emit rate. Past words snap to 1; future words hold.
- **Minimum wipe duration** (~150 ms) so short words still show motion.
- One `Animatable` per word, not per frame.
- Replace `LaunchedEffect`-keyed scans with `derivedStateOf` + `indexOfLast`.
- **Hoist per-frame `Color` allocations to constants.**
- Precompute cross-timeline lookups (translated lines) as `Map<Int,String>` via **two-pointer nearest match** with threshold.
- Drop redundant effects (`blur(1.dp)` on already-dimmed text costs a render pass).
- Key infinite transitions on the state that should stop them.
**Evidence:** `94eba106`, `89fbbdfd`, `9eb2698e`, `24e2dd1b`.
**Generality:** A

### 44. `compose-nowplaying-pager`
**Trigger:** Building a Spotify-style swipeable now-playing screen.
- Replace manual drag gestures with **one `HorizontalPager`** wrapping *all* layers (backdrop video + artwork) so they slide in lockstep.
- **Derive the page index from your own stable id**, not the player's `mediaId` (type prefixes). **Composite key (id + index)** to survive duplicates.
- **Prevent feedback loops** with `isScrollInProgress` + an `isAnimating` guard around `animateScrollToPage`.
- Dispatch by distance: ±1 reuses Next/Previous (keeps crossfade); longer jumps take the direct path that handles unshuffling.
- `clipToBounds()` per page or 9:16 video bleeds into neighbours.
- **Remove the competing sibling clickable** — an overlay steals drags from the pager.
- **Per-page derived colors hoisted into the page scope**, fed from the same bitmap actually painted.
- Extract dispatch logic into pure functions (`deriveOrderIndex`, `computeSeekAction`).
- Add a transport method that **bypasses the 3-second seek-to-start rule** for swipes.
**Evidence:** `37620916`, `95a6c80d`; core `7be578f`.
**Generality:** A

### 45. `media3-cast-handoff`
(As docs/code lanes — unified `CastPlayer.Builder().setLocalPlayer()`, resolved-URL queue window, force-disable crossfade/EQ/precache while casting, 403/expiry retry, repeat-all forwarding guard, module pair for FOSS.)
**Evidence:** `621dc7e8`; core `745f8e1`; `b4931309`, `759d97d7`; CLAUDE.md.
**Generality:** B

### 46. `offline-first-cache-and-download-correctness`
**Trigger:** Cached/downloaded media still hits the network, or serves a partial file.
- **Serve from cache directly only when the *whole* track is on disk** — partial cache served as complete = truncated playback.
- **Stop re-resolving stream URLs for fully downloaded tracks** — the resolve is the expensive, rate-limited, failure-prone step.
- **Resume from saved position instead of restarting on stream retry.**
- **Cache browse/section responses on disk keyed by a stable field (title), not index.**
- Repair rows written by an older parse with an explicit refresh path, not a schema migration, when the value is re-derivable.
**Evidence:** core `f28f56b`, `52c8edc`, `3ecd15f`, `4a11e13`, `dfd2997`, `0754978`.
**Generality:** A

### 47. `data-import-json-contract-design`
(As docs lane #31.)
**Evidence:** `docs/import-format-v1.md`.
**Generality:** A

### 48. `agent-maintained-engineering-journal`
**Trigger:** Wanting institutional knowledge to survive in a fast-moving repo.
- The most valuable artifact is **not the commit log** — it's CLAUDE.md's changelog section (~120 lines of dated, root-caused post-mortems), updated by commits titled `docs: record ...`.
- **A mandatory auto-update rule encoded in the file itself** (what triggers an update; what does not).
- Entry shape: dated headline → what was wrong → why invisible → what was ruled out → the fix → the constraint for the next person.
- Deep investigations get their **own file** (`MEMORY_TUNING.md`) with measured numbers, symptom→suspect→undo table, "do not re-add" warnings.
- **For skill-mining generally: in agent-assisted repos, search tracked markdown before commit messages** (the three most promising commits had empty bodies).
**Evidence:** `73c7bf95`, `ff10e20f`, `9155f673`, `5412bd19`, `9c6c6414`, `e027443c`; CLAUDE.md.
**Generality:** A

---

## Coverage notes
- Scanned: all 1408 main-repo subjects + ~250 core submodule subjects. Read in full: 33 main + 13 core long-bodied commits + 12 thin-but-valuable at diff level. Primary sources read whole: CLAUDE.md, MEMORY_TUNING.md, conveyor-migration.md, import-format-v1.md, AGENTS.md (drifted vs CLAUDE.md).
- Value concentrated 2026-02 → 2026-08.
- NOT covered in depth (→ later covered by raw-git-deep.md): 2023-04→2024-12 (~500 terse commits; Hilt→Koin `e05f218d`; XML→Compose wave), 2025 (~350; cipher/throttling `f6fca165` `40feea23` `6fc2b514` `0891adcd` `c77f927e`; yt-dlp cycle `2065a6b8`→`9da099af`→`11cc51a7`→`e131a793`).
- core submodule commits from 2026-07 onward have empty bodies — knowledge migrated into parent CLAUDE.md.
- External assertions (ProGuard issue numbers, mpv code paths, Last.fm docs) are as the repo's authors recorded them — verify before publishing.
