# Raw mining report — Lane 1: Docs (CLAUDE.md, repo *.md, memory folder, simpmusic.org index + architecture, GitHub releases)

> Mined 2026-08-19. 48 candidates. Format: name / trigger / core knowledge / evidence / audience / generality (A = fully generic, B = generic after adaptation, C = SimpMusic-specific).

**Sweep completed:** CLAUDE.md (656 lines, incl. the full "Changelog Summary (post-1.0.4)" war-story section), all repo `*.md`, all 20 memory files, simpmusic.org + its `/docs` and `/docs/dev/architecture` pages, and 10 GitHub release bodies via authenticated `gh`.

---

## Cluster A — Native code in the JVM (JNA, dynamic linking, native bundling)

**1. `jna-native-library-loading-traps`**
- Trigger: Binding a C library into a JVM/Kotlin app with JNA and hitting crashes that are not in your code.
- Core knowledge:
  - The JVM calls `setlocale(LC_ALL, "")` at startup; libraries that parse floats (mpv, many C libs) fail under a non-C `LC_NUMERIC`. Fix by binding `setlocale` through JNA and forcing `LC_NUMERIC=C`. The category *constant* is not portable: glibc = 1, macOS/Windows = 4.
  - JNA loads with `RTLD_GLOBAL` by default; the library's transitive symbols (ffmpeg, libass, libsixel) leak into the global namespace and other consumers (Skia/AWT) resolve against them — producing a hard native abort inside a library your code never calls.
  - `OPTION_OPEN_FLAGS = 2` (RTLD_NOW without RTLD_GLOBAL) fixes POSIX **and breaks Windows**: JNA forwards the integer verbatim to `LoadLibraryEx`, where `2` = `LOAD_LIBRARY_AS_DATAFILE`. Symptom is the misleading `Error looking up function '<x>': The specified module could not be found`.
  - Rule that generalizes: every constant handed to JNA must be asked "what does this number mean on Windows?"
  - Always log the *resolved* path (`NativeLibrary.getInstance(name).file`) — it is the only thing distinguishing "using my bundle" from "silently using /usr/lib".
  - When a hard native abort is in play, `Logger`/`System.err` are unreliable (still in the pipe); write to a file with `fd.sync()`. Isolate with a minimal C / ctypes reproducer.
- Evidence: memory `mpv-desktop-backend-jvm-pitfalls.md`; CLAUDE.md (JNA open flags entry, 2026-07-28)
- Audience: Anyone embedding a native lib (mpv, VLC, ffmpeg, ONNX, SQLite extensions) into JVM/Kotlin/Desktop apps.
- Generality: **A**

**2. `choosing-native-artifacts-for-jvm-embedding`**
- Trigger: Picking or building a `.so`/`.dylib`/`.dll` to bundle with a JVM app, especially on Linux.
- Core knowledge:
  - Artifact *kind* matters more than version. An AppImage packages a library to run as its own process: it ships its own glibc + `ld-linux`, and its "libmpv.so.2" was actually the `mpv` **PIE executable** — glibc refuses to `dlopen` a PIE (`DF_1_PIE`), and patched past that its glibc collides with the one the JVM already mapped.
  - Contrast with artifacts packaged *for embedding* (a Maven-published `.so`, an old-glibc build) — those work.
  - The working answer was a from-source container build (Ubuntu 22.04 → glibc 2.34 floor, runs on Debian 11+), disabling features you don't use (Vulkan/shaderc/glslang when you render in software) — which also deleted the transitive libs causing unrelated aborts.
  - Deliberately do **not** bundle `libc`/`libm`/`libstdc++`/`ld-linux` — the JVM already mapped the host's.
  - `DT_RUNPATH` is **not** inherited by transitive dependencies (`lib → dep → dep-of-dep` breaks at hop two); `DT_RPATH` is. Use `patchelf --force-rpath`.
  - Gate the build on a `dlopen` + init smoke test so a broken slice never publishes.
- Evidence: memory `mpv-desktop-backend-jvm-pitfalls.md`; CLAUDE.md "Linux libmpv built from source (2026-07-28)"
- Audience: Desktop JVM/Electron/Python devs shipping native deps cross-distro.
- Generality: **A**

**3. `bundled-native-libs-soname-conflicts`**
- Trigger: A feature unrelated to your native library breaks after you start bundling it.
- Core knowledge:
  - Bundling a common transitive lib (here glib 2.72) makes it claim the soname the moment your loader runs, so the *system* consumer of that soname can no longer load. AWT's `XDesktopPeer.init()` then failed with `undefined symbol: g_dir_unref` and the JDK reported the whole `java.awt.Desktop` API unsupported for the rest of the process.
  - Blast radius is invisible in review: 23 external-link call sites broke at once. `openUrl()` was an `if` with no `else` so it failed *silently*; Compose's `LocalUriHandler` calls `Desktop.getDesktop()` and threw straight out of the click handler.
  - Ordering workaround: probe the API early (`Desktop.isDesktopSupported()` before loading the native lib) — the peer caches the probe, letting the system lib win the race.
  - Real cure is to add the lib to your staging script's `SYSTEM_LIBS` exclusion list, not to work around it.
  - Add a per-OS fallback launcher (`xdg-open` → `gio open` → `$BROWSER`) plus a visible toast so this class of failure can never be silent again.
- Evidence: CLAUDE.md "Bundled glib disabled `java.awt.Desktop` on Linux (2026-07-31)"
- Audience: Anyone shipping bundled `.so` trees alongside a runtime that also uses system libraries.
- Generality: **A**

**4. `macos-codesign-appledouble-sidecars`**
- Trigger: macOS reports "app is damaged and can't be opened" / `codesign --strict`: "a sealed resource is missing or invalid".
- Core knowledge:
  - `tar`ring files **on a Mac** writes each file's xattrs out as a companion `._name` (AppleDouble) sidecar.
  - A signer running on Linux sees them as ordinary bundle members, signs them, and seals them into `_CodeSignature/CodeResources`.
  - macOS then folds `._name` back into the xattrs of `name` and deletes the sidecar the first time Finder touches the app — unzipping it **or dragging it out of a DMG**. The bundle is now missing every file the seal expects.
  - Only macOS is affected: it alone seals the whole app directory and re-checks at launch, and it alone deletes the sidecars.
  - Fix at the unpack step (`strip ._*`), which retro-fixes already-published tarballs without republishing.
  - Process lesson recorded alongside: hard evidence was abandoned because "DMG isn't unzipped, so sidecars survive" — wrong, Finder copy folds xattrs too. **Anything inside a signed bundle must be assumed to affect the signature until proven otherwise.**
- Evidence: memory `mpv-desktop-backend-jvm-pitfalls.md` §5; CLAUDE.md "Bundled libmpv (2026-07-27)"
- Audience: Anyone shipping signed/notarized macOS apps built on Linux CI.
- Generality: **A**

**5. `jvm-desktop-memory-footprint-tuning`**
- Trigger: A desktop JVM app sits at ~1 GB RSS and climbs over a session, but the Java heap is small.
- Core knowledge:
  - The number that matters is **heap-to-RSS ratio**, not RSS. Heap 121 MB inside a 512 MB cap while RSS is 1.9 GB means native memory, and `-Xmx` is irrelevant.
  - Diagnose fragmentation vs leak with one decisive test: call `malloc_trim(0)` on the live process. 167 MB returned instantly = memory was already free = fragmentation, not a leak.
  - glibc per-thread arenas are the Linux amplifier: ceiling is `8 × nproc`, never returned. 20 cores → 160 arenas holding 1451 MB. **RAM use scales with the user's core count.** `MALLOC_ARENA_MAX=2` took arenas 161 → 5 and RSS 1.90 GB → 0.93 GB.
  - Every allocator can be asked to return pages; only the spelling differs: Linux `malloc_trim(0)`, Windows `HeapSetInformation(NULL, HeapOptimizeResources, …)`. **Trim only while idle** — it walks the heap holding the allocator lock, so it would be audible during playback.
  - macOS's `malloc_zone_pressure_relief(NULL, 0)` with a NULL zone hits *every registered zone* including Metal/QuartzCore/Skia; it landed inside a `CATransaction` commit and hard-crashed. Documented as "do not re-add".
  - G1 free-ratio flags are a **no-op without `-XX:G1PeriodicGCInterval`**: G1 only uncommits at the end of a concurrent cycle, and a low-allocation app never triggers one.
  - Falsified hypotheses are documented so nobody re-investigates them (unbounded heap; leaked native handles — counted via their event-pump threads, flat at 3 over 60 samples).
- Evidence: `desktopApp/MEMORY_TUNING.md` (full doc, with measurement commands per OS and a symptom→suspect rollback table)
- Audience: Any JVM desktop app (Compose Desktop, JavaFX, Swing, IntelliJ plugins) with native media/graphics.
- Generality: **A** — this file is close to publishable as-is.

**6. `macos-lsenvironment-side-effects`**
- Trigger: Setting env vars for a macOS `.app` via `Info.plist`.
- Core knowledge:
  - `LSEnvironment` is applied by LaunchServices, so it covers Finder/Dock/Spotlight/`open` launches but **not** running `Contents/MacOS/…` from a shell — your terminal testing won't reflect production.
  - Declaring it **pins `PATH`** to the bare `/usr/bin:/bin:/usr/sbin:/sbin`. Audit every `ProcessBuilder`/shell-out on the macOS path before adding it.
  - Symptom mapping: "command not found" or a helper failing to launch after adding `LSEnvironment` = the pinned PATH.
  - If you need both, add `PATH` explicitly to the same dict rather than dropping the setting.
- Evidence: `desktopApp/MEMORY_TUNING.md` §3
- Audience: macOS app packagers.
- Generality: **A**

---

## Cluster B — Desktop packaging, Gradle, KMP structure

**7. `conveyor-config-key-placement`**
- Trigger: A packaging config key appears to have no effect; the packaged build behaves as if you never set it.
- Core knowledge:
  - `url-schemes` binds on Conveyor's `AppConfig` (top level of `app`), **not** on `mac`/`windows`/`linux`. Written as `mac.url-schemes` it sat inert for ~3 months and **every packaged build shipped with no `CFBundleURLTypes` at all**.
  - HOCON accepts unknown keys silently — misplacement is not an error, ever.
  - Verify by reading the packager's own source for which config object the accessor reads (`MacConfigAccess.getUrlSchemes()` reads `appConfig`, while `getFileAssociations()` beside it reads `mac`).
  - Proof technique: diff two builds that differ *only* in where the key is written.
  - Same misplacement class hit `desktop-file.Categories`/`Comment[en]`/`StartupWMClass` parked *beside* the `"Desktop Entry"` group instead of inside it.
- Evidence: CLAUDE.md "Desktop URL schemes were never actually registered (2026-07-31)"
- Audience: Conveyor / jpackage / electron-builder / Tauri users; anyone with HOCON/YAML config that fails open.
- Generality: **B** (Conveyor-specific example, fully generic principle)

**8. `desktop-deep-link-plumbing-checklist`**
- Trigger: A custom URL scheme works on one OS but not others, or works in dev but not packaged.
- Core knowledge:
  - Registration is only link one. The argv filter in the app's entry point matched a *fixed list* of prefixes and discarded a valid third-party callback scheme on Windows and Linux — match any `scheme://` instead.
  - On Linux, the `.desktop` that actually reaches users is the one AppRun installs into `~/.local/share/applications` — it needs every `x-scheme-handler/<scheme>` declared, not just your primary one.
  - Windows needs an explicit protocol registrar; macOS needs `CFBundleURLTypes` from correct config placement; Android needs an intent-filter.
  - Always provide a manual paste-the-URL fallback for hosts where no scheme handler exists.
- Evidence: CLAUDE.md (2026-07-31 entry, Last.fm module section)
- Audience: Desktop app devs adding OAuth callbacks or deep links.
- Generality: **A**

**9. `gradle-configuration-observed-too-early`**
- Trigger: `Cannot mutate the dependencies of configuration ':x' after the configuration's child configuration ':runtimeClasspath' was resolved.`
- Core knowledge:
  - Root cause shape: a plugin registers a task with **constructor arguments**, which forces eager instantiation during `apply`, and that `init {}` block resolves the runtime classpath. Any configuration upstream of `implementation` is then frozen.
  - Symptom is reported at *your* dependency declaration, not at the offending plugin — the blame is misdirected by construction.
  - Documented non-fixes (so nobody repeats them): separate `dependencies {}` block, `configurations.named(…) { dependencies.add(…) }`, direct Maven coordinates instead of accessors, disabling one suspect plugin, removing `jvmToolchain`.
  - Correct method is **plugin bisection** against a known-good minimal template, then compare plugin sets.
- Evidence: `.omc/plans/conveyor-migration.md` (with the causal chain and a line-level link into the plugin source)
- Audience: Gradle plugin authors and anyone debugging multi-plugin build failures.
- Generality: **A**

**10. `kmp-module-split-for-app-packaging`**
- Trigger: A KMP `composeApp` module is simultaneously the shared library, the JVM app entry point, and the packaging host — and build plugins keep conflicting.
- Core knowledge:
  - The retiring arrangement: one KMP module doing three jobs. The 2026 JetBrains default splits into `composeApp` (KMP library, `android.kotlin.multiplatform.library` + `jvm()`), `androidApp`, and a dedicated `desktopApp` on plain `kotlin("jvm")`.
  - Forcing factor is external: **AGP 9+ removes support for the Android application plugin inside KMP modules** — the split is coming regardless of your packager.
  - Every JVM-friendly tool (Conveyor, jpackage extensions, Compose Hot Reload, the classic application plugin) lands more cleanly on a real `kotlin("jvm")` module than on a KMP `jvm()` target.
  - Migration shape: move `main.kt` into the library as `runDesktopApp(args)`, leave a 1-line `fun main(args) = runDesktopApp(args)` in the entry module.
  - Verification ladder used: compile each module, then `:desktopApp:run` end-to-end with real playback and auth before declaring done.
- Evidence: `.omc/plans/conveyor-migration.md`; release v1.0.2 ("Migrate to new KMP best practice", PR #1601); simpmusic.org `/docs/dev/architecture` ("thin shell architecture")
- Audience: Every Compose Multiplatform team shipping desktop.
- Generality: **A**

**11. `foss-vs-proprietary-module-gating`**
- Trigger: You need an F-Droid-clean / GMS-free / telemetry-free build variant without `#ifdef`-style code rot.
- Core knowledge:
  - Pattern: paired modules `x` and `x-empty` with an **identical public API**; the empty twin's availability probe returns `false`, which hides the entire settings block. Selected by a Gradle property (`isFullBuild`), not by Android product flavors — so it works for KMP/desktop too.
  - Applied uniformly across three unrelated concerns: crash reporting (Sentry), Google Cast (GMS), Last.fm (API secret). "A FOSS build ships no API secret, so it ships no code that needs one."
  - The gate must be applied in **every** consuming module's build file (playback module *and* UI module), or a GMS import leaks into a shared source set.
  - Secrets come from `local.properties` → BuildKonfig → a `configX(key, secret)` call at startup, so the no-op twin needs no secret at all.
  - Historical driver: an earlier F-Droid compliance issue (#158/#322/#189) — this pattern is what let a previously-rejected feature (Cast) finally ship.
- Evidence: CLAUDE.md module sections 4-7; memory `google_cast_integration_decision.md`; simpmusic.org `/docs/dev/architecture` (FOSS vs Full table)
- Audience: Any OSS Android/KMP app that wants an F-Droid build, or any app separating proprietary SDKs.
- Generality: **A**

**12. `r8-keep-rules-not-disable`**
- Trigger: A release build crashes with `VerifyError` / `ClassNotFoundException` / reflection `NoSuchMethodError` and someone proposes turning off optimization.
- Core knowledge:
  - Policy stance: `optimize` and `obfuscate` stay on permanently; disabling is a permanent quality regression, not a workaround — not even as a "quick test".
  - Fix additively with `-keep` / `-keepclassmembers` / `-dontwarn`.
  - Cover the **whole package** of the offending library (`kotlinx.coroutines.**`, `androidx.room.**`) rather than one class — optimization passes reshape adjacent classes.
  - Iterate: release rebuild, add rules for whatever surfaces next.
  - Applies to Compose **Desktop** release builds too (`compose.desktop.application.buildTypes.release.proguard {}`), which people forget has R8 at all.
- Evidence: memory `feedback_never_disable_proguard.md`
- Audience: Android and Compose Desktop release engineers.
- Generality: **A**

---

## Cluster C — Media player architecture

**13. `crossfade-dual-player-architecture`**
- Trigger: Implementing crossfade / gapless / DJ-style transitions in a media app.
- Core knowledge:
  - Model is one player handle **per media item**, two alive during a transition, with an adapter implementing a common `MediaPlayerInterface`.
  - Consequence to plan for: the queue no longer lives in the player's timeline, it lives in a handler layer — which breaks anything reading the player timeline (Android Auto's native queue showed 1 track).
  - Crossfade owns the audio filter chain and clears it after each transition, so any other filter-based feature (pitch shifting) must be mutually exclusive with it, and the UI must lock the control.
  - Transport commands must all handle "currently crossfading": `seekTo` was the only one that didn't, causing two bugs at once — the outgoing track kept playing, and the seek landed on the wrong track (position was read from the secondary player while the seek went to the current one). Fix: commit the incoming track as current first.
  - Playback settings (speed, pitch, volume, fade) must reach **every live handle** — current + secondary + precached. The secondary is the easy miss: it's removed from the precache collection before promotion, so it belongs to neither.
- Evidence: CLAUDE.md entries 2026-08-14 (×4); `core/media/media3/.../CrossfadeExoPlayerAdapter.kt` and `core/media/media-jvm/.../mpv/MpvPlayerAdapter.kt`
- Audience: Music/podcast app developers on Media3, mpv, AVFoundation, or web audio.
- Generality: **A**

**14. `guard-conditions-on-every-trigger-path`**
- Trigger: A feature flag/guard "does nothing" with no error and no crash.
- Core knowledge:
  - Crossfade starts from **two** independent paths: a position-polling job (`timeRemaining in 1..duration+prep`, polled every 200 ms) *and* an end-of-stream callback.
  - The EOF path returns early when the transition is already running, so a guard added only there is **dead code with no symptom** — the feature silently does nothing.
  - The general shape: before adding a condition, enumerate every entry point into the state you're guarding. Follow whatever existing guard is known-correct (here, the video checks were already on both paths).
  - This is explicitly cross-referenced in the codebase to the SQL `NOT IN`-over-nullable bug as "the same failure shape": a change that is silently inert.
- Evidence: CLAUDE.md "Every crossfade guard belongs on BOTH trigger paths (2026-08-14)"
- Audience: Anyone maintaining event-driven/state-machine code.
- Generality: **A**

**15. `crossfade-exclusion-heuristics`**
- Trigger: Deciding *when not to* crossfade — the product-design half of the feature.
- Core knowledge:
  - Skip when the next **or** current track plays as video: the merged audio+video source is error-prone to prepare mid-fade and cut songs short / jumped to 0:00.
  - Skip when the current track is shorter than `max(20s, crossfadeDuration × 3)` — at a 5 s fade, a 20 s track spends half its length fading. With an "Auto" duration setting, compute the bar from the resolved value, never a hardcoded default.
  - Opt-in (default **off**) skip between tracks of the same album, so continuously-sequenced albums still run.
  - Implement album membership as a **set of ids snapshotted at load**, not a count — shuffle reorders the queue including appended radio tracks. Skip only when *both* current and next are in the set, which automatically keeps the album→radio edge fading.
  - That only works because endless-queue appends bypass the setter that would rewrite the snapshot; routing them through it would swallow radio tracks into the album set.
  - Known limitation documented honestly: the album tag doesn't survive restart because the persisted queue entity has no column for it.
- Evidence: CLAUDE.md "Crossfade exclusions: short tracks and albums (2026-08-14)"
- Audience: Music player product engineers.
- Generality: **B**

**16. `audio-fade-out-separate-gain-line`**
- Trigger: Implementing a sleep timer, ducking, or any programmatic fade on top of user volume.
- Core knowledge:
  - **Never ramp the user's volume variable.** It's reported back to the UI (slider visibly slides down) and if the process dies mid-fade you leave a permanently silent app. Add a dedicated attenuation field; the two multiply.
  - Use an equal-power (cosine) curve, not linear.
  - A **tail of silence is required because gain sits ahead of the sink**: AudioTrack buffers 250–750 ms, so pausing the instant the ramp hits zero still cuts at roughly −12 dBFS. ~800 ms tail after the ramp.
  - Clamp fade + tail to fit inside the remaining track time, or the timer overruns and pauses inside the *next* track.
  - **The restore must not be queued by the caller.** `pause()` is async *and* suspends partway through, so even a single-thread dispatcher does not order "pause then restore" — the suspension releases the thread and the restore runs first, re-opening the mixer over the last of the audio. Each adapter restores its own factor in a `finally`. Any early-return branch (e.g. the cast path) must clear it inline, or every sample is multiplied by ~0 for the rest of the process.
- Evidence: CLAUDE.md "Sleep timer fade-out, and a second volume line to carry it (2026-08-14, issue #2330)"
- Audience: Audio app developers on any platform.
- Generality: **A**

**17. `mpv-embedded-in-compose-desktop`**
- Trigger: Using libmpv as a playback engine inside a JVM/Compose app.
- Core knowledge:
  - Bind the C client API by hand with JNA against a known client-API major; struct layouts read by raw offset need re-verification on a MAJOR bump.
  - `vo=libmpv` + software render context; publish finished frames as immutable `BufferedImage` snapshots on a `StateFlow` and draw with a plain Compose `Image` (convert with `toComposeImageBitmap()` **off** the UI thread; the UI reports its size via `setTargetSize()`).
  - Separate audio/video URLs merge into ONE source with an `edl://…;!new_stream;…` URL — mpv's equivalent of Media3's `MergingMediaSource`.
  - **mpv decides the video's fit, not Compose.** mpv scales *and letterboxes* into the target size you report, so the black bars are already pixels before Compose sees them — no `ContentScale` can remove them. Cropping is mpv's `panscan` property (0.0 letterbox … 1.0 cover), applied from a `LaunchedEffect` so flipping the flag re-scales the running video instead of re-creating the handle.
  - **Confine every property write to the player thread.** `release()` flips a released-flag synchronously and *then* spawns termination, so a caller that passed the flag check can still be inside `mpv_set_property` when the core dies (released-handle bug).
  - Feature-detect options: a build with `-Dlua=disabled` has no `ytdl_hook`, so the `ytdl` option genuinely doesn't exist — treat `MPV_ERROR_OPTION_NOT_FOUND` as success via an `optionalOption()` helper.
  - Blind spot flagged: nothing called `mpv_request_log_messages()`, so libmpv's own warnings (including failed audio init) never surfaced anywhere.
- Evidence: CLAUDE.md "Desktop Player (libmpv)" section + 2026-08-01 / 2026-08-14 / 2026-08-17 entries
- Audience: Desktop media app devs (Compose Desktop, JavaFX, Swing) needing video.
- Generality: **B**

**18. `replace-swingpanel-with-compose-frames`**
- Trigger: Embedding an AWT/Swing surface into Compose Desktop for video or native rendering.
- Core knowledge:
  - `SwingPanel` embedding brings a whole bug *class*: always-on-top z-order fights, one-frame-late repositioning while scrolling (flicker that exposes transparent windows), and AWT's **single-parent rule** — multiple screens fight over the one panel, producing "video randomly missing until next/prev".
  - Publishing immutable frame snapshots on a `StateFlow` and drawing them with a plain `Image` kills all of it at once; the underlying render loop is unchanged.
  - The UI reports its own size back down (`setTargetSize`) instead of the native surface dictating layout.
  - Related fix in the same change: the surface `StateFlow` must be set **unconditionally** during a transition — a null-guard kept a dead panel from a released player on screen (the "black video" bug).
- Evidence: CLAUDE.md "Desktop video renders through Compose, SwingPanel removed (2026-08-01)"
- Audience: Compose Desktop developers doing interop.
- Generality: **A**

**19. `upstream-bug-workaround-with-exit-criteria`**
- Trigger: You've traced a crash into a third-party/OS library you cannot patch.
- Core knowledge:
  - Worked example: mpv's `ao_coreaudio` registers a system-wide `AudioObjectAddPropertyListener` in `init()` but its failure label is bare; a later-step failure leaves the listener registered on a `struct ao` that is then freed. `ao_uninit()` only calls `driver->uninit()` when a flag set *after* successful init is present — so unregistration never runs. Crash arrives later, on any device hotplug (reproduced by plugging in headphones).
  - **Why this app hit it and plain mpv didn't:** mpv initializes one audio output per session; this app creates one handle per media item and runs two at once during crossfade — so a single failed audio init anywhere in a session arms the crash. *Usage pattern, not code, is what exposed the upstream bug.*
  - Diagnostic tell: the crash address decoded as ASCII (`0x65636e6174736e49` = `"Instance"`) — the signature of a freed allocation already reused by another object. No thread was tearing down at crash time, which ruled out a teardown race and pointed at a much earlier leak.
  - Write the workaround with (a) named accepted trade-offs with upstream issue numbers, (b) a graceful-degradation escape hatch (`"avfoundation,"` — the trailing comma keeps mpv's auto-probe as fallback so a failure degrades audio instead of silencing it), and (c) an explicit removal condition.
  - Scope it: Windows and Linux backends untouched.
- Evidence: CLAUDE.md "macOS desktop audio moved to `ao=avfoundation` (2026-08-01)" (Sentry-visible `a bad-memory-access fault` on the `HALC_ProxyNotification Call Listener Queue`)
- Audience: Anyone debugging native crashes reported by crash-reporting SaaS; a strong "how to write a workaround" template.
- Generality: **A**

**20. `google-cast-integration-decision`**
- Trigger: Adding Cast/remote playback to an app that streams resolved URLs.
- Core knowledge:
  - Route chosen: Media3 `media3-cast` with `CastPlayer.Builder().setLocalPlayer(forwardingPlayer).build()` (1.9+ rewrite handles local↔remote switching and `TransferCallback`), Full build only, gated behind the no-op-twin module pattern.
  - Stream URLs are resolved **up front at the MediaItem level** (reusing the existing new-format/403/expiry logic) rather than through a `ResolvingDataSource`, because the receiver fetches the URL itself.
  - Explicitly rejected alternatives with reasons: a self-written HTTP proxy (network layer to maintain), AirPlay (no Android sender SDK; OSS libs dead or GPLv3-incompatible), FCast (nobody installs the receiver).
  - **Degrade deliberately while casting** (as YouTube Music/Spotify do): crossfade/DJ, equalizer (needs an audioSessionId), skip-silence, volume normalization all force-disabled with grayed-out UI and a note; queue/shuffle/SponsorBlock/synced lyrics survive because they live above the player interface.
  - Risk handling worth copying: the biggest unknown (token/403 on the receiver) was made **milestone 1** ("play one song to a Chromecast, week 1") rather than a separate spike, with a named pivot (passthrough proxy) whose prior work is a strict superset.
  - Needs real hardware on the same WiFi at the test milestone.
- Evidence: memory `google_cast_integration_decision.md`; CLAUDE.md cast module section; release v1.6.0
- Audience: Media app teams evaluating Cast; also a template for writing a technical decision record.
- Generality: **B**

**21. `android-auto-custom-ui-car-app-library`**
- Trigger: You want custom Android Auto UI (custom header, custom actions, your own queue screen) and Media3 can't do it.
- Core knowledge:
  - Custom AA UI is **not achievable with Media3** — it requires Car App Library **media templates** (beta, announced Google I/O 2026). Spotify/YouTube Music got there via early access, not a hidden Media3 API. A Media3 maintainer couldn't answer because the question was filed on the wrong surface.
  - Architectural driver that generalizes: with a **multi-player** design the real queue lives in a handler layer, not in the MediaSession player's timeline — so AA's native queue shows one item. CAL is the right fix precisely because a custom queue screen reads the domain queue directly, with no `ForwardingPlayer` fake-timeline hack.
  - Mapping: header title + custom actions → `MediaPlaybackTemplate` `Header`; queue → `SectionedItemTemplate`/`ListTemplate`; return-to-playback → `Action.MEDIA_PLAYBACK` (required: playback reachable from every browse screen).
  - Coexistence: **keep** the Media3 `MediaLibraryService` as data plane + legacy fallback; add a `CarAppService` with category `androidx.car.app.category.MEDIA`, permission `androidx.car.app.MEDIA_TEMPLATES`, `minCarApiLevel 8`.
  - Token bridging: `MediaPlaybackManager.registerMediaPlaybackToken()`; Media3's PlatformToken needs `MediaSessionCompat.Token.fromToken()`.
  - Single-APK fallback: declare `android.software.car.templates_host.media` with `required=false`.
  - Beta gating is Play-track-limited — **sideloaded/F-Droid apps are unaffected**, which is a real distribution advantage worth knowing.
- Evidence: memory `android_auto_cal_media_templates.md`; release v1.6.0 ("All-new Android Auto experience")
- Audience: Any Android media app wanting AA beyond the default browse/playback templates.
- Generality: **B**

**22. `mediasession-foreground-service-state-ended`**
- Trigger: Background music pauses or stops on its own between tracks.
- Core knowledge:
  - With a multi-player/forwarding-player design, an inner player reaching `STATE_ENDED` **leaks through** to the MediaSession, the system treats playback as finished, and the foreground service is cancelled mid-queue.
  - Fix shape: suppress `STATE_ENDED` at the `ForwardingPlayer.getPlaybackState()` boundary and don't fire an ENDED transition while a next track exists.
  - Long-lived regression signature: users bisecting to "downgrading to vN-1 fixes it" across two duplicate issues (#2022, #1965) is strong evidence of a single state-machine root cause, not device fragmentation.
  - Related: at end of queue, `play()` called into a handle parked at EOF and did nothing — the button looked ignored; adapters must rewind first.
- Evidence: memory `project_issues_post_v130.md`; release v1.4.0 ("Fix music pausing or stopping on its own between tracks, present since 1.0.4")
- Audience: Android background-playback developers.
- Generality: **B**

**23. `queue-index-spaces-and-shuffle`**
- Trigger: The "now playing" highlight in a queue UI lands on the wrong row, or on all duplicates.
- Core knowledge:
  - Three separate defects stack: (1) the index StateFlow is written only by reorder/remove handlers and **never by the track-transition callback**, so it's frozen while playback advances; (2) the player's `currentMediaItemIndex` is in *timeline* space while the displayed list has been reordered into *shuffle* space — two different index spaces; (3) the compensating helper matched by `indexOfLast { videoId == … }`, which cannot distinguish duplicate tracks.
  - Correct fix is in the player layer, not the UI: expose the inverse mapping (`getShuffledIndex(unshuffledIndex)`) — every adapter already holds the shuffle order privately — and reduce the helper to pure position, removing id matching entirely.
  - Maintainer lesson attached: a contributor PR fixing the UI symptom was closed in favor of the layer fix, because the surface bug was real but the index functions were wrong.
- Evidence: memory `queue_playing_icon_index_bug.md` (PR #2290)
- Audience: Anyone building a queue/playlist UI over a shuffling player.
- Generality: **A**

**24. `stateflow-conflation-hides-write-order`**
- Trigger: A UI state (spinner, badge, playing indicator) shows the exact opposite of reality.
- Core knowledge:
  - A callback wrote to a `StateFlow` **2–3 times in a row** (Loading unconditionally, maybe Ready, then Loading again from a teardown helper). `StateFlow` conflates, and a collector on another thread settles on the **last** write — so the UI showed Loading right when buffering *finished*.
  - Result: a spinner over playing audio on every track start and every resume. Identical on both platforms; predated a full playback-engine migration (blame pointed at the previous engine's handler).
  - Compounding leak: the periodic update job didn't cancel its predecessor, so every track leaked another 500 ms emitter — the *sibling* progress job had already been fixed for exactly this (#2152), a strong signal to grep for the same shape.
  - Unit-mismatch trap in the same family: comparing `bufferedPercentage * duration` (percent × ms) against `currentPosition` (ms) — off by ~100×.
  - Sentinel values leak into formatters: pinning `current = -1L` on Ended rendered as `NA:NA` next to a correct duration, because one branch ignored negatives and another restored only `total`.
- Evidence: CLAUDE.md "Playback state was published inverted on both platforms (2026-08-16)"
- Audience: Every Kotlin Flow / reactive UI developer.
- Generality: **A**

---

## Cluster D — Databases and SQL

**25. `cascading-cleanup-delete-ordering`**
- Trigger: Writing a "clear history" / "free up space" / GDPR-erasure sweep over a relational cache.
- Core knowledge:
  - **Order is the feature: containers first, leaves last.** Sweeping songs alone deleted **0** rows, because 11,322 of 12,221 were held alive by playlists nothing pruned.
  - Worked chain: pin the live working set → events → artists (unfollowed) → their satellites → podcasts (cascades to episodes) → albums → playlists → songs → satellites orphaned only *by this run* → checkpoint + VACUUM → unpin. Measured result: 57 MB DB → ~12 MB.
  - **The live/in-use record must be pinned to disk first.** The currently-playing item was only persisted on pause/track-change/exit and only when a setting was on — so the song audibly playing looked orphaned and was eligible for deletion. Remove the pin afterwards.
  - **Re-check the orphan conditions inside the DELETE** rather than trusting a precomputed id list: users keep acting during the sweep, and cascade rules can pull a row back out from under you.
  - Report counts per table; they are the only way to notice a sweep that silently matched nothing.
- Evidence: CLAUDE.md "Clear listening history sweeps the whole cached library (2026-08-16)"
- Audience: Anyone shipping cache-clearing, data-retention, or account-deletion features over SQLite/Postgres.
- Generality: **A**

**26. `state-columns-are-implicit-foreign-keys`**
- Trigger: Deciding what "unreferenced" means before deleting rows.
- Core knowledge:
  - "Referenced by nothing" read literally deletes user data. A `liked` boolean **is** the entire Favorites feature; a `downloadState` column is the **only** link between a downloaded file on disk and its row. Neither is a foreign key.
  - Also spare in-flight state (`downloadState = 0` spares a download still running).
  - Propagate one level up: parents (albums/artists) backing a liked or downloaded child are spared so their pages still render offline.
  - General rule: before writing an orphan predicate, enumerate every *feature* that reads the table, not every *constraint* on it.
- Evidence: CLAUDE.md, same entry
- Audience: Backend and mobile data-layer engineers.
- Generality: **A**

**27. `sql-not-in-nullable-column-trap`**
- Trigger: A `DELETE`/`SELECT` with a `NOT IN` subquery returns nothing and reports no error.
- Core knowledge:
  - If the subquery column is nullable and contains any NULL, `x NOT IN (…, NULL, …)` evaluates to NULL — never TRUE. The statement matches **zero rows and succeeds**.
  - Fix: add `WHERE <col> IS NOT NULL` to every such subquery (or use `NOT EXISTS`).
  - Real cost recorded: a playlist sweep deleted 0 rows silently in production.
  - Failure *class* to internalize: changes that are silently inert. The codebase explicitly cross-links this to a guard added on only one of two trigger paths — same shape, different technology.
- Evidence: CLAUDE.md, same entry
- Audience: Every SQL author.
- Generality: **A**

**28. `like-wildcard-escaping-for-ids`**
- Trigger: Matching identifiers inside JSON/text columns with `LIKE`.
- Core knowledge:
  - `_` is a single-character LIKE wildcard, and real-world ids are full of it — 1,748 of the ids in this dataset contained `_`.
  - Escape `\`, `_`, `%` via nested `replace()` and declare `ESCAPE '\'`.
  - Match ids as **quoted tokens** (`'%"' || id || '"%'`) rather than bare substrings, which stays sound across JSON shapes including `List<Map<String,String>>` columns where the id is still a quoted value.
  - Better still: don't LIKE-match into JSON if you can normalize; this is documented as a deliberate trade-off, not a recommendation.
- Evidence: CLAUDE.md, same entry
- Audience: SQL / Room / mobile persistence developers.
- Generality: **A**

**29. `room-rawquery-readonly-connection`**
- Trigger: `VACUUM` (or any write via `@RawQuery`) fails with "attempt to write a readonly database".
- Core knowledge:
  - KSP generates `@RawQuery` as `performSuspending(__db, isReadOnly = true, …)`; Room takes a **reader** connection, and readers open with `PRAGMA query_only = 1`.
  - Confusingly, `PRAGMA wal_checkpoint` **is** accepted on that same connection — which is why a long-standing `checkpoint()` DAO method worked and hid the problem for a long time.
  - Correct placement: put `vacuum()` on the database class using `useWriterConnection { it.execSQL("VACUUM") }`. `execSQL` opens no transaction, which SQLite requires for VACUUM.
  - Call `checkpoint()` immediately before, so the WAL that the deletes just filled is folded back in first.
  - A VACUUM failure must **not** surface as an error to the user — every delete already committed; the reclaim is opportunistic.
- Evidence: CLAUDE.md "`@RawQuery` cannot VACUUM (2026-08-16)"
- Audience: Android/KMP Room users; generalizes to any ORM with reader/writer connection splitting.
- Generality: **A**

**30. `clean-up-satellite-rows-at-the-state-transition`**
- Trigger: Rows accumulate forever because cleanup only happens in a bulk sweep.
- Core knowledge:
  - Flipping a `followed` flag left that entity's notification and release-tracking rows stranded forever; once the parent row is later swept, those rows lose any path back to a parent and become unreachable garbage.
  - Fix at the transition (delete dependents on the unfollow path), and **keep** the bulk sweep for rows stranded before the fix shipped — both are needed, and that's not redundancy.
- Evidence: CLAUDE.md "Unfollowing an artist now cleans up immediately (2026-08-16)"
- Audience: Data-layer engineers.
- Generality: **A**

**31. `import-file-format-contract-design`**
- Trigger: Designing a JSON interchange format between two systems you control (converter → app, exporter → importer).
- Core knowledge:
  - Write down what the *consumer* refuses to do: "the app does no matching of its own; if a track has no id by the time the file is written, it must not appear in the file at all."
  - Deliberately **no `version` and no `source` field**, with the reason stated: the parser uses `ignoreUnknownKeys = true`, so extra keys are silently dropped and a producer relying on them fails silently.
  - Reject the empty-but-valid file explicitly, so picking the wrong file produces an error instead of "imported 0 songs".
  - **Positionally-aligned parallel arrays need a stated length rule**: `artistId` must be absent/null or exactly the same length as `artistName`. The consumer defends itself by dropping the whole list on mismatch — which silently loses data, so the producer must never emit a partial one.
  - Document caps (10,000 songs / 500 playlists) *and* say who enforces them, because the consumer parses in one pass with no streaming decoder and relies on them.
  - Enumerate "what the consumer fills in itself" so producers don't try to supply it, and state write behaviour on re-import (existing rows not overwritten; playlists always created fresh → importing twice duplicates).
  - Name known-bad legacy values ("do not emit the literal string `\"Album\"`").
- Evidence: `docs/import-format-v1.md`
- Audience: Anyone specifying an import/export or plugin data contract. Excellent worked template.
- Generality: **A**

---

## Cluster E — Consuming undocumented / unstable web APIs

**32. `wrapper-renderer-parsing-undocumented-apis`**
- Trigger: A response parser silently drops most of a list from an unofficial API.
- Core knowledge:
  - The parser read only the bare renderer type, so every row shipped as a `…WrapperRenderer` resolved to null and vanished inside a `mapNotNull`. Measured: **161 of 197 rows across four pages were wrapped** — a 50-track page arrived as 6.
  - Fix shape: a resolver that returns the bare renderer *else* the primary renderer inside the wrapper.
  - `mapNotNull` over a parsed response is a silent data-loss primitive. Count what you dropped.
  - The wrapper also carried a `counterpart` (the other rendition of the same recording) — the thing that powers the official client's Song/Video switch. Wrappers often contain *more*, not less.
  - Housekeeping finding: a near-duplicate legacy method with hardcoded params was dead code — nothing called it.
- Evidence: CLAUDE.md "Wrapped queue rows were being dropped — 82% of a logged-in radio (2026-08-16)"
- Audience: Anyone scraping or wrapping an undocumented API (YouTube, TikTok, internal partner APIs).
- Generality: **A**

**33. `auth-state-changes-response-shape`**
- Trigger: A bug that only reproduces for logged-in users, or only in production.
- Core knowledge:
  - **The wrapper only appeared when authenticated.** Six anonymous requests eliminated the other variables one at a time — same seed, both client versions, and both body shapes — every one returned zero wrappers, while the authenticated capture returned 48/50.
  - That is the reusable method: hold the response shape as the dependent variable and vary one request attribute at a time; auth state is a variable people forget to include.
  - Test fixtures captured while logged out can be *systematically* unrepresentative — not merely incomplete.
  - Also record where a config **moved** between API versions: the same field now rides the overlay play button on search rows and the title column on playlist rows, so the parser must check all three places — and must fall through on the **value**, not on the endpoint (falling through on the endpoint stops at the first row carrying a bare endpoint, which is exactly the migrated shape).
- Evidence: CLAUDE.md, same entry + the `videoType` entry
- Audience: API integrators, QA engineers, anyone writing golden-file tests against a third-party API.
- Generality: **A**

**34. `normalize-enums-over-legacy-written-data`**
- Trigger: A column holds values invented by whichever screen wrote the row.
- Core knowledge:
  - Nobody ever read the API's own type field; every call site invented a label, and one mapper **smuggled the view count into the type column** — which a UI screen then depended on to render "432K views". So the field held `"Song"`, `"video"`, or a number depending on provenance, and nothing could ask "is this a video?" truthfully.
  - Fix: read the real value from the API everywhere, carry it on the shared models, and back-fill through **existing update paths rather than a migration**.
  - Put the comparison enum in the module both consumers already depend on — putting it in either one would invert an existing dependency edge. (Clean-architecture rule applied concretely.)
  - **Normalize first**: keep only real `PREFIX_*` values, because rows written by older builds hold the invented labels; comparing raw would misclassify all of them.
  - **`null` means "the source did not say", never a default.** Two well-known clients resolve the same unknown in *opposite* directions — expose `isKnown` and make callers branch.
  - Give the smuggled data a real home (a proper `views` field) so the abuse can't return.
- Evidence: CLAUDE.md "`videoType` was never read from the API (2026-08-16)"
- Audience: Anyone maintaining a schema that predates its own discipline.
- Generality: **A**

**35. `lastfm-scrobbling-api-integration`**
- Trigger: Integrating Last.fm (or any MD5-signed, XML-translated-to-JSON web API).
- Core knowledge:
  - **`status="ok"` does not mean accepted.** Last.fm answers OK while discarding the scrobble and says so only in `ignoredMessage`: 1 = artist filtered, 2 = track filtered, 3/4 = timestamp too far past/future, 5 = daily limit. Codes 1 and 2 are how bad metadata surfaces — log them loudly rather than dropping them.
  - Signature: sort params by name, concatenate `<name><value>`, append secret, MD5 — but **exclude `format` and `callback`**, or every request fails with "Invalid method signature supplied" (code 13).
  - `toSortedMap()` does not exist in common Kotlin (JDK collection) — use `entries.sortedBy { it.key }`.
  - Parse as loose `JsonObject`s, not `@Serializable` classes: the JSON is a translation of XML, so numbers arrive as strings, attributes hide under `@attr`, and a field is an object with one entry but an array with several.
  - Error codes to branch on: `9` invalid session → clear stored session and force re-login; `11`/`16`/`29` transient/retryable; everything else is a malformed request.
  - Where the docs contradict themselves, follow the ecosystem: `timestamp` = track **start** (every scrobbler in the wild), and always send `duration`.
  - Scrobble threshold: >30 s track scrobbles at half its length or 4 minutes, whichever comes first — ride an existing periodic tick rather than adding a timer.
- Evidence: CLAUDE.md "Last.fm scrobbling (2026-07-30)" section
- Audience: Music app developers; more broadly, a case study in "OK-but-ignored" API semantics.
- Generality: **B** (Last.fm-specific, but the `status ok ≠ accepted` and XML-shaped-JSON lessons are A)

**36. `oauth-web-flow-vs-desktop-flow`**
- Trigger: A third-party auth callback never fires and it looks like a broken redirect.
- Core knowledge:
  - Two flows exist and they are **not interchangeable**. Web flow: send the user to the auth URL with **no token**; the provider mints one and redirects to your registered callback with `?token=`. Desktop flow: fetch a token first, then open the same URL with `&token=` already on it — the provider then knows you hold the token and renders a "return to the application" page, and **the callback is never called**. Symptom is indistinguishable from a broken deep link.
  - Pick web flow whenever you have a registered callback + scheme handlers on every platform.
  - **The callback token must not travel through navigation.** Handing it to the app root → shared view model, with the login screen closing itself by observing the stored session key, is correct. Navigating *to* the login screen with the token pushes a **second** copy on top of the one the user started from, so `navigateUp()` after success peels off only that copy and lands back on a login screen — looking exactly like "logged in but stuck on login".
  - Why only this provider hit it: the app's other three logins embed a WebView and never leave the app. Desktop has no real WebView, which is why the system browser is used at all — platform capability drives auth architecture.
  - Never handle passwords: the app only ever sees the redirect token.
- Evidence: CLAUDE.md Last.fm sections
- Audience: Any app doing third-party OAuth/token auth on desktop or across platforms.
- Generality: **A**

---

## Cluster F — Compose / Compose Multiplatform UI

**37. `compose-material-symbols-icon-system`**
- Trigger: Removing `material-icons-extended`, or standardizing an app's icon set as generated `ImageVector`s.
- Core knowledge:
  - Google's font service returns a ready Compose `.kt` file directly — no conversion tool: `https://fonts.gstatic.com/render/v1/Material+Symbols+Rounded/24dp/<symbol>.kt?var=opsz,wght,FILL,GRAD,ROND@24,400,1,0,50`. **The response is gzipped even when you ask for `identity`** — use `--compressed` or sniff magic bytes.
  - Keep the variable-font axes identical across the whole set or it stops looking like one set. Use `FILL=0` **only** for the "off" half of a state pair, otherwise on/off render identically.
  - Declare each icon as an **extension property** on a single object (`val SimpIcons.X: ImageVector`). Each icon then needs its own import — and that is exactly what lets R8 strip unused icons. Never "simplify" the set into a `map` or `when`; that ships all of them.
  - **`ImageVector` is not a `Painter`.** `Icon`/`Image` have both overloads so those look fine; `AsyncImage(placeholder/error)`, anything inside a `DrawScope`, and any composable typed `Painter` need `rememberVectorPainter(...)`.
  - **Do not migrate icons whose colour carries meaning** (a blue "downloaded", a red "liked", brand logos, bitmap placeholders) — a tinted neutral symbol is not equivalent. Pass the colour explicitly instead.
  - Migration hazard with a number attached: a regex swap of `Res.drawable.X` → `SimpIcons.X` produced **40 compile errors in one pass** — it hit `Painter` parameters and landed *inside* multi-line `painterResource(...)` calls, leaving syntactically valid but wrong code.
  - Verify a symbol name exists against `google/material-design-icons` codepoints before assuming; legacy names like `favorite_border` survive, `person_add_alt_1` does not.
  - Scale reference: 59 icons / 117 call sites, then 25 more / 167 call sites, 44 XML files deleted.
- Evidence: `.claude/skills/simpmusic-icons/SKILL.md` (**the house skill template**); CLAUDE.md "Add a New Icon"; release v1.7.0
- Audience: Every Compose / CMP team; especially those cutting APK size.
- Generality: **B** (naming is project-specific; mechanism and traps are A)

**38. `liquid-glass-backdrop-in-compose`**
- Trigger: Implementing a glass/blur/backdrop effect in Compose, or one that renders on some widgets but not others.
- Core knowledge:
  - **The rim is a `Highlight`, and its default is DIRECTIONAL, not an outline.** `Highlight.Default` lights along a single angle (45°, falloff 1). An elongated pill catches that sweep along its long edge and reads as glass; a 48 dp circle catches a short arc and reads as **nothing at all**. `HighlightStyle.Plain` is the uniform one. Expose `highlight` as a parameter defaulting to the library's behaviour, and pass `Plain` for small round buttons.
  - The backdrop **source must be a sibling** of the glass widgets (e.g. a `matchParentSize()` box carrying a palette colour that takes part in no measurement). Nesting the buttons inside the source is a render-feedback loop that crashes the RuntimeShader.
  - Press/hold interaction rides `pointerInput` + `awaitFirstDown`, so it works with a mouse — no touch-specific API needed.
  - Documented dead ends (four burned builds): hand-rolling the button as `Row + liquidGlass` — widening it to 96 dp *does* make glass appear, which is a **symptom, not a fix**; shrinking lens radii; moving the backdrop source; painting cover art into the source at low alpha (visible, but silently changes the design). The one useful experiment was **swapping the two widgets' positions** — the glass followed the *widget*, proving geometry not position.
  - Desktop/skiko is the first suspect if glass crashes: the same shader neighbourhood as the haze crash.
- Evidence: CLAUDE.md "Liquid glass reaches Desktop (2026-08-17)"; memory `feedback_run_the_discriminating_test_early.md`
- Audience: Compose/CMP developers doing glassmorphism or custom shader effects.
- Generality: **B**

**39. `compose-multiplatform-version-pinning-shader-crashes`**
- Trigger: A Compose Multiplatform library throws `NoSuchMethodError` inside the draw pass on Desktop.
- Core knowledge:
  - haze 1.7.2's progressive path calls `ShaderBrush.createShader(Size)` whose **mangled signature** doesn't match the pinned Compose (`material3-multiplatform 1.12.0-alpha01` / skiko 0.148.1) — `NoSuchMethodError` from inside `RenderEffect.skiko.kt`. Non-Android targets surface binary-compat breaks that Android never sees.
  - It stayed latent because that branch was only ever rendered on the platform that worked. **Enabling an existing feature on a new target is a new integration surface.**
  - Guard the single call site by platform and lose only the effect (the colour scrim was already a separate box) rather than chasing the upgrade.
  - Upgrade math is transitive: alpha02 bumps skiko to 0.148.2, which removes `Matrix33.makeTranslate` and crashes a *different* library (compottie). Document the pin's reason at the pin.
  - Plain (non-progressive) variants of the same effect are fine — narrow the guard to what actually breaks.
- Evidence: CLAUDE.md (2026-08-17 entries ×2)
- Audience: Compose Multiplatform / skiko users; generally, anyone pinning a fast-moving alpha stack.
- Generality: **A**

**40. `responsive-layout-gate-on-size-not-platform`**
- Trigger: A layout branch keyed on `isAndroid` / `isMobile` that should be keyed on window size.
- Core knowledge:
  - A gate written as `platform == Android && width < height` locks the layout out of desktop *and* out of tablets. The correct gate is `width < height` and nothing else: a narrow desktop window is portrait, a landscape phone is not.
  - **One boolean was answering two questions** — "use the immersive treatment" (palette background, dividers, blurred bar) and "which header". That's why forcing it to `true` broke the header while looking harmless; everything else it gated genuinely applied to both orientations, so those conditions should simply be deleted.
  - `aspectRatio(1f)` is a phone-only assumption: on a 1400 dp-wide window it makes a 1400 dp-tall block that swallows the page. Use `height(screenHeight / 2)`.
  - Two values must change *with* it or the result is worse: `ContentScale.FillWidth` → `Crop` (FillWidth scales a square source to the frame's **width** and shows only its top slice), and a scrim measured as `width × 0.7` → `height × 0.35` (both are 70% of the frame's *own* height — that's why the numbers differ).
  - When a "temporarily forced open so we can judge it on desktop" flag also **replaces the body of the other branch**, it ships as a regression on the platform that was working. Force flags must not delete the alternative.
  - Buttons that floated as overlays on edge-to-edge artwork have nothing to overlay in a side-by-side layout — plan for them becoming a plain top row, and **move the code verbatim** rather than rewriting (each is wired to its own view model).
- Evidence: CLAUDE.md "Apple Music header reaches Desktop (2026-08-17)" and "The header gate is orientation, not platform (2026-08-17)"; memory `artist_screen_apple_music_redesign.md`
- Audience: Every adaptive-UI developer (Compose, SwiftUI, Flutter, web).
- Generality: **A**

**41. `navigation-tab-registration-drift`**
- Trigger: Adding a navigation destination that "exists but never renders".
- Core knowledge:
  - Three navigation components carried the tab list independently (bottom bar, navigation rail for wide screens, and a decorative glass bar) — and the glass bar kept **two** lists of its own (one for selection, one for the sliding capsule). All must be updated or the tab silently never appears.
  - **An enum `ordinal` is an identity, not a position.** One component compared `selectedIndex == index` in one place and `screen.ordinal` in another; it only worked while the two numbers coincided, and reordering exposed it.
  - Feature-gate tabs on the setting that makes them meaningful rather than shipping an empty screen.
  - Discoverability tell worth recording: a "NEW" badge on a 24 dp icon buried in a top app bar is the signal that the feature is in the wrong place.
- Evidence: CLAUDE.md "Analytics is a nav tab, gated on local tracking (2026-08-16)"
- Audience: App developers with more than one navigation surface (phone/tablet/TV/desktop).
- Generality: **A**

**42. `nested-flag-settings-bug-family`**
- Trigger: A settings toggle stays on after the thing it depends on is gone (logout, revoked token, removed permission).
- Core knowledge:
  - Three defects compound, and you need all three fixes:
    1. The **consumer** (a service reading preferences directly) enables the feature from the child flag without re-checking the dependency — e.g. an empty token producing `Client("")` and an infinite reconnect loop that drains battery and heats the device.
    2. **Logout clears the credential but not the dependent flags**, so they stick TRUE — and because the UI greys the toggle out when the gate is false, the user *cannot* turn it off themselves. Perfect trap.
    3. The shared settings component auto-disabled the child flag in `LaunchedEffect(Unit)` — which runs **once at composition** and never reacts when the gate flips false mid-session. `LaunchedEffect(isEnable)` is the fix.
  - Gate at the consumer with `combine(flagFlow, credentialFlow)`, not with an `if` at the call site.
  - Stop retry loops on non-recoverable close/auth codes (a named constant set, e.g. 4004/4010–4014) instead of reconnecting forever.
  - Audit the whole family at once: several sibling flows already gated correctly / failed soft, and knowing which is part of the finding.
- Evidence: memory `nested_flag_settings_bug.md` (issues #2157, #2064); releases v1.5.0 and v1.6.0
- Audience: Any app with settings that depend on login state, permissions, or entitlements.
- Generality: **A**

**43. `compose-hot-reload-agent-workflow`**
- Trigger: Iterating on Compose Desktop UI with hot reload, especially with an AI agent driving it.
- Core knowledge:
  - `org.jetbrains.compose.hot-reload` is applied in the entry module (root `apply false`); a foojay resolver convention provisions the JBR. Run `:desktopApp:hotRunJvm --auto` — **plain `jvmRun` does NOT hot-reload**, the plugin creates separate tasks.
  - `ComposeHotRun` extends `JavaExec`, so an existing `tasks.withType<JavaExec>` block already covers it (system properties for native lib paths reach hot runs for free).
  - **Measure UI with the semantic tree, not screenshots.** The tree returns exact bounds (it is how a 2 px column overflow was found); a screenshot captures the window's *screen rect*, so an occluded window photographs whatever is covering it.
  - No hover tool exists — to inspect hover-only UI, temporarily force the state in code, reload, measure, revert.
  - **CHR cannot invalidate global state** (DI singletons, player adapters) — restart after touching those.
- Evidence: CLAUDE.md "Compose Hot Reload + MCP (2026-08-17)"
- Audience: Compose Desktop developers; directly relevant to agentic UI workflows.
- Generality: **B**

---

## Cluster G — Engineering method / debugging discipline

**44. `run-the-discriminating-experiment-first`**
- Trigger: Two near-identical components, one works and one doesn't.
- Core knowledge:
  - Do not fix by strongest hypothesis. **Count the variables still differing between the two sides; if more than one, design a test that eliminates at least half.**
  - Worked case: a back button had no glass while an adjacent pill did. Four build cycles were burned guessing (change the shape, remove the wrapper, feed the backdrop real content, copy the working structure) — all wrong. **Swapping the two widgets' positions** settled it in one build: the effect followed the widget, not the position, so the cause was the widget's own geometry.
  - When each experiment costs someone else a build, put **multiple variants in one build** (one per screen) and label them.
  - **Never delete a running experiment before you have its result** — "tidying up" removed one variant and wasted an entire build cycle.
  - Human cost is part of the record: the collaborator had visibly given up before the answer arrived.
- Evidence: memory `feedback_run_the_discriminating_test_early.md`
- Audience: Every engineer; especially strong material for an AI-agent debugging skill.
- Generality: **A**

**45. `noop-implementation-is-not-a-platform-limit`**
- Trigger: You find an empty `actual` / stub / `#ifdef` and are about to conclude "platform X can't do this".
- Core knowledge:
  - An empty `actual` (returns the receiver unchanged, empty class, empty body) means **nobody wrote it**, not that the platform lacks support.
  - Real cost: a library was declared in `commonMain.dependencies`, Gradle had been resolving and caching the `-desktop` variant all along with an identical API — and the reported conclusion was "Desktop can't have this feature, no matter what". It nearly killed a shippable feature.
  - Before saying "platform X can't": (a) `ls ~/.gradle/caches/modules-2/files-2.1/<group>` for `-desktop`/`-jvm`/`-iosArm64` variants; (b) `unzip -l` + `javap` to compare the API surface; (c) check **which source set** declares the dependency.
  - Corollary that reshaped the code: once the library exists on both targets, **the `expect`/`actual` abstraction has nothing left to abstract** — and the `expect class` was itself the blocker, since it has no relationship to the library's type, so the 200-line effect was stranded in `androidMain`. Deleting the abstraction (keeping a `typealias` so ~20 call sites don't change) is what let the code move to common.
- Evidence: memory `feedback_noop_actual_is_not_platform_limit.md`; CLAUDE.md 2026-08-17 liquid-glass entry
- Audience: KMP developers; generalizes to any platform-abstraction layer.
- Generality: **A**

**46. `read-build-logs-bottom-up-and-whole`**
- Trigger: Reporting the result of a long build/test run.
- Core knowledge:
  - Gradle prints `e: …` error lines **near the top**, then the task list, then `BUILD FAILED` at the bottom. A fixed `tail -20` shows only "compileX FAILED" and loses every error message — forcing a full rebuild to learn what broke.
  - **Never infer "no errors" from an empty filter.** A grep that matches nothing looks exactly like a clean build; this nearly produced a false success report.
  - If filtering, always keep `^e: `, `^w: `, `BUILD `, and the install/summary lines simultaneously — and still read the `BUILD SUCCESSFUL/FAILED` line before concluding.
  - Read the whole log, from the bottom up.
- Evidence: memory `feedback_read_build_log_bottom_up.md`
- Audience: CI engineers and anyone driving builds through an agent.
- Generality: **A**

**47. `changelog-as-war-story-knowledge-base`**
- Trigger: Deciding what to write down after a hard bug, and where.
- Core knowledge:
  - The high-value pattern observed here: each entry is dated, states the **symptom as users saw it**, the mechanism, **why this project hit it when others don't**, the fix, the accepted trade-offs, and an explicit removal/exit condition. Several carry hard numbers (161/197 rows, 11,322 of 12,221, 1,748 ids, 82%, four burned builds).
  - Entries record **disproved hypotheses** in a dedicated section so nobody re-investigates them (the memory-tuning doc has a "What it was NOT" table).
  - Entries carry **negative instructions with reasons**: "do not lift IINA's frameworks", "do not re-add the macOS branch", "do not switch to the desktop auth flow", "the actual cure is to stop bundling glib".
  - Cross-link failure *shapes* across technologies — the dead-code guard, the `NOT IN` NULL, and the no-op `actual` are all explicitly linked as "changes that are silently inert".
  - A stated auto-update rule defines what triggers an entry and what does **not** — otherwise the file becomes a commit log.
  - Documented failure mode of the practice itself: this repo has both `CLAUDE.md` (656 lines) and `AGENTS.md` (502 lines), and AGENTS.md has silently drifted — it still says the desktop player is VLCJ and is missing the cast/lastfm/icons sections entirely. **Duplicated agent-instruction files rot; generate or symlink one from the other.**
- Evidence: CLAUDE.md §"Changelog Summary" + §"Auto-Update Rule"; drift measured against `AGENTS.md`
- Audience: Every team writing `CLAUDE.md`/`AGENTS.md`/ADRs or onboarding docs.
- Generality: **A**

**48. `writing-an-agent-skill-house-style`**
- Trigger: Turning a repeated procedure into a reusable skill/runbook.
- Core knowledge:
  - Observed template (from the one hand-written skill in this repo): YAML frontmatter with `name` + a `description` that states **when to use it, including the error symptom** ("…or hitting ImageVector/Painter type errors"); a two-line orientation paragraph; an explicit "**two things are deliberately absent and must not come back**" list; the happy path as a copy-pasteable command; then a **Traps** section that dominates the document.
  - Traps are written as bolded claim + consequence + fix, with a **table for exceptions** (which items must NOT be migrated and why), and at least one trap carrying a measured cost ("produced 40 compile errors in one pass").
  - It tells you how to *verify* a value exists before assuming (pointing at the upstream source of truth), rather than listing values that will go stale.
  - Length target: ~90 lines. Everything not a trap is compressed to make room for traps.
- Evidence: `.claude/skills/simpmusic-icons/SKILL.md`
- Audience: Anyone authoring Agent Skills — this is the format the other candidates should be written in.
- Generality: **A**

---

## Gaps noted by this lane
- 5 dev-docs pages on simpmusic.org were not fetched by this lane (slugs unknown at the time) — **covered later by the web lane** (`raw-web.md`).
- Per-release blog posts deferred — **covered later by the web lane**.
- `core/` submodule docs beyond CLAUDE.md — thin (2-line README).
- No CONTRIBUTING.md / FAQ.md exists in the repo; CODE_OF_CONDUCT.md is boilerplate.
- 7 of 20 memory files are Vietnamese; originals at `~/.claude/projects/-home-minh-AndroidStudioProjects-SimpMusic/memory/`.
- Excluded as non-generalizable (workflow preferences for this human/agent pair): context-1m-model-suffix, as_commit_signing_op_ssh_sign, feedback_sign_commits_ssh, feedback_estimate_in_claude_hours, feedback-do-small-work-yourself, feedback_complete_code_not_todo_human, feedback_problem_must_come_with_fix, feedback_trust_user_root_cause.
