# SimpMusic → Agent Skills — Master Catalog

> Built 2026-08-19 from 10 mining lanes (~282 raw candidates) in this folder: `raw-docs.md`, `raw-git.md`, `raw-git-deep`, `raw-code` (media/mpv/room/compose), `raw-code-gaps`, `raw-web`, `raw-blog`, `raw-core.md`, `raw-handlers.md`, `raw-ui.md`.
> Deduped to the clean set below. **Scope (owner decision 2026-08-19):** ship the *architecture / how / pattern*, NOT any specific third-party service mechanics. Everything YT-Music / Spotify / Discord / Last.fm / Tidal / SponsorBlock / AI-provider specific is CUT (listed at the end); the generic core of each was salvaged into group L with neutral wording (no service names, no real field names).
> Generality: A = fully generic as-is · B = generic after neutral rewrite · C = mostly SimpMusic-specific (generic core only).
> Vocabulary is deliberately neutral (behavioral, not low-level jargon).

Legend per row: `skill-name` — one-line gloss — primary evidence — A/B/C — [raw lane]

---

## A · Native code in the JVM / desktop (11)
1. `jna-native-binding-traps` — open-flag means something else on Windows; struct read by offset; log the resolved path so a broken bundle can't pass as working — MpvLibrary.kt — A [code,git,docs]
2. `native-artifact-for-embedding` — a prebuilt AppImage is a PIE not a shared lib; build from source on old glibc; DT_RPATH not DT_RUNPATH; gate on a load+init smoke test — scripts/mpv-linux — A [git,docs,code]
3. `bundled-native-soname-conflict` — a bundled common lib claims the soname and breaks a *system* API; probe the API before loading the native; real cure is a SYSTEM_LIBS exclusion — CLAUDE.md 2026-07-31 — A [docs,git]
4. `macos-codesign-sidecar-strip` — strip `._*` AppleDouble files before signing or macOS reports "app is damaged" — CLAUDE.md — A [docs,git]
5. `jvm-desktop-memory-footprint` — heap-to-RSS ratio not RSS; the decisive on-demand-return test; per-thread arenas scale with core count; the macOS zone trap — desktopApp/MEMORY_TUNING.md — A [docs,git,blog]
6. `embed-media-engine-desktop` — one handle per item, a dedicated event thread, render-context ordering, every property write on the player thread, feature-detect optional options, locale-independent number formatting — MpvPlayer.kt — B [docs,code]
7. `merge-split-av-streams-desktop` — play a separate audio-only + video-only pair as one source (the desktop engine's merge URL) — MpvPlayerAdapter.kt — B [code]
8. `compose-desktop-video-no-swingpanel` — publish frames as immutable snapshots on a StateFlow, draw with a plain Image; pixel byte-order; TYPE_INT_RGB not ARGB; the renderer letterboxes into the size you report — MpvVideoFrameSource.kt — A [docs,git,code,blog]
9. `desktop-system-media-integration` — SMTC/MPRIS/macOS now-playing behind one facade; null-safe init; ObjC runtime via JNA; init on the main thread; hold callback refs — MacOSMediaIntegration.kt — A [code,gaps]
10. `upstream-lib-bug-workaround-template` — how to write a workaround for a bug in a lib you can't patch: named tradeoffs, a graceful escape hatch, an explicit removal condition; usage-pattern (not code) is what exposes it — CLAUDE.md — A [docs,git]
11. `macos-lsenvironment-path-pin` — env via Info.plist pins PATH to the bare four dirs; audit ProcessBuilder first — MEMORY_TUNING.md — A [docs]

## B · Desktop packaging / CI / build (13)
12. `conveyor-desktop-packaging` — HOCON swallows a misplaced key silently; url-schemes binds at AppConfig level; `-K<dotted.key>=<value>` overrides (brackets are for LIST values, not dotted keys; spaced keys need HOCON quoting); per-machine JDK; LSEnvironment PATH — conveyor.conf — A [git,docs,code]
13. `config-fails-open-verify-artifact` — verify a config-driven feature against the *generated artifact*, diff two builds that differ only in key placement — CLAUDE.md — A [git,docs]
14. `desktop-deep-link-plumbing` — argv filter must match any `scheme://`; `.desktop` needs every handler; manual paste fallback — App.kt/DesktopApp.kt — A [docs,code]
15. `r8-proguard-desktop-survival` — the exact optimizations to disable, obfuscation breaks render, JNA/coroutines/ktor keeps, wire shrunk jars to the packager; policy: additive keeps, never disable R8 — proguard-desktop-rules.pro — A [git,code,docs]
16. `gradle-config-resolved-too-early` — the error names the wrong culprit; bisect plugins against a minimal template — .omc/plans/conveyor-migration.md — A [git,docs]
17. `transitive-version-pinning` — a transitive `strictly` overrides your BOM; NoSuchMethodError in the draw pass; document why a version is pinned — build.gradle.kts — A [git]
18. `reproducible-native-bundling-two-tasks` — a dev task produces + prints digests, a CI task downloads + verifies against pinned digests — composeApp/build.gradle.kts — A [git,code]
19. `windows-vm-detection-post-wmic` — wmic is gone from Win11; PowerShell CIM; probe both Manufacturer and Model — DesktopApp.kt — A [git]
20. `windows-msix-offline-installer` — raw MSIX is unusable offline; ship install.bat + cert + a stable signing key — scripts/windows — A [git]
21. `arm64-native-gap-audit` — audit every native dep for the arch before promising the target; one missing native kills it — build.gradle.kts — A [git]
22. `ci-flaky-timing-luck` — async detach of a same-name volume; capture the tool's reported mount point; curl (fails loud) not URL.openStream (saves error body) — .github/workflows — A [git]
23. `github-actions-multiplatform-release` — cross-build everything on Linux, a fast mac job only wraps the dmg; the Gatekeeper reason — .github/workflows/desktop-package.yml — A [code]
24. `buildkonfig-secrets-flavors` — KMP BuildConfig, empty strings for the FOSS branch, Gradle-9 prepare*ArtProfile dependsOn — composeApp/build.gradle.kts — A [code]

## C · KMP structure / DI / architecture (9)
25. `kmp-module-split-for-packaging` — AGP 9 forces it; composeApp lib + androidApp + desktopApp jvm; `runDesktopApp(args)` — settings.gradle.kts — A [docs,git,web]
26. `foss-vs-proprietary-module-pairs` — x / x-empty with identical API, chosen by a Gradle property not flavors, gated in every consuming module; the stub hides its settings — cast/cast-empty — A [docs,git,code,web]
27. `clean-arch-kmp-readiness` — module layers; skip the use-case tier when it's just a repo wrapper; internal repository impls; domain is clean of platform/UI types (it DOES carry persistence annotations across ~23 files — the "no annotations" premise was refuted in verify) — blog:clean-architecture — B [blog,core]
28. `no-use-case-layer-decision` — a mid-size app can drop the interactor tier and keep a clean boundary via interfaces + mapping functions (verified: zero use-cases here) — core/domain — B [core]
29. `hilt-to-koin-migration` — motive is KMP not ergonomics; the mechanical mapping; assisted injection vanishes; the runBlocking-in-a-module-definition trap — di/*Module.kt — A [git-deep]
30. `koin-viewmodel-scoping-traps` — base-VM-as-service-locator tradeoff; koin-annotations inert silently for months; `activityViewModels` vs `activityViewModel` (one char, two instances); VM-as-single needs manual lifecycle — di/ViewModelModule.kt — A [git-deep]
31. `repository-resource-flow-pattern` — Resource/LocalResource/NoResponse envelopes + wrap/collect helpers so VMs never write `when` — core/domain/utils/Resource.kt — A [code,core]
32. `kmp-gradle-settings-catalog` — submodule → flat module mapping, typesafe accessors, resolutionStrategy force for a runtime-only conflict (the force lives in the ROOT build script's subprojects block, not in settings) — settings.gradle.kts + build.gradle.kts — A [code]
33. `kmp-git-submodule-module-mapping` — recursive clone, Gradle path ≠ disk path, CI submodule checkout — settings.gradle.kts — A [web]

## D · Media playback engine — no third-party (18)
34. `crossfade-dual-player` — one player per item; every guard on BOTH trigger paths; seekTo commits the incoming track first; settings reach every live handle; equal-power curve — CrossfadeExoPlayerAdapter.kt — A [docs,git,code]
35. `guard-on-every-trigger-path` — a feature fed from two entry points needs the guard on both, or it's dead code with no symptom — CLAUDE.md — A [docs,git]
36. `crossfade-exclusion-heuristics` — skip on video / short track (max(20s,3x)) / same album (id-set snapshot) — CLAUDE.md — B [docs]
37. `media3-custom-audio-processor` — always-active + branch inside queueInput (the "isActive bypass" was a stale comment, not what ships), per-stream state via a shared volatile field, consume the whole buffer, read a fresh gain per buffer — CrossfadeFilterAudioProcessor.kt — A [code]
38. `realtime-biquad-dsp` — RBJ cookbook coeffs, cascaded identical-Q sections (Linkwitz–Riley-shaped response, NOT a 4th-order Butterworth), per-channel state, lazy recompute — BiquadFilter.kt — A [code]
39. `beatmatched-automix` — duration derived from tempo/key gap, halftime normalize, front-loaded ramp, quantize to avoid pops — CrossfadeExoPlayerAdapter.kt — A [code,git]
40. `audio-fade-separate-gain-line` — never ramp the user's volume; a tail because gain sits ahead of the sink; restore in the adapter's own finally, not queued by the caller — CLAUDE.md #2330 — A [docs,git,gaps]
41. `forwarding-player-hot-swap` — swap the delegate by reflection + re-add listeners; a navigation provider for the buttons a 1-item timeline hides; seekToPreviousMediaItem bypasses the 3s rule — DelegatingForwardingPlayer.kt — A [code]
42. `fgs-state-ended-trap` — suppress STATE_ENDED at the forwarding boundary during a swap or the service is dropped mid-queue (a ~25ms gap on aggressive ROMs) — core `5b45954` — A [docs,git]
43. `audio-focus-multiplayer` — a single app-level focus request; duck vs crossfade fight over the volume line — CrossfadeExoPlayerAdapter.kt — A [git,code]
44. `per-track-loudness-normalization` — recreate the enhancer per track (bound to the released session otherwise), skip on cast/unset-session, clamp gain — MediaServiceHandlerImpl.kt — B [gaps]
45. `queue-index-vs-shuffle-space` — the index flow freezes; timeline-space vs shuffle-space; expose the shuffled-index accessor (only the reverse direction exists in code; the forward one was agreed on paper and never written); no id-match for duplicates — PR #2290 — A [docs]
46. `custom-shuffle-order` — the default scatters an insert; insert contiguously at the pivot with an index map — BetterShuffleOrder.kt — A [code]
47. `endless-queue-management` — one StateFlow, two write paths on purpose (appends bypass the setter that would reset a snapshot) — MediaPlayerHandler.kt — B [code,docs]
48. `queue-rebuild-state-machine` — a two-state source flag guards re-entrancy and blocks a mid-rebuild snapshot — MediaServiceHandlerImpl.kt — B [handlers]
49. `dual-source-queue-sync` — re-derive the UI list from the engine timeline by mediaId; bail if sizes differ; user moves mutate both — MediaServiceHandlerImpl.kt — B [handlers]
50. `polymorphic-load-media-entry-point` — one generic loadMediaItem normalizes types; a discriminator routes the seed strategy; pre-enqueue policy gates here — MediaServiceHandlerImpl.kt — B [handlers]
51. `playback-position-persist-restore` — heavy save vs a cheap 5s tick on the existing loop; skip while re-cataloging; snapshot before touching the player — MediaServiceHandlerImpl.kt — A [gaps,handlers]

## E · Database / SQL — generic (11)
52. `cascading-delete-ordering` — containers first / leaves last; kept-by-state columns; re-check conditions inside the DELETE; pin the live record — DatabaseDao.kt — A [docs,git,code]
53. `sql-not-in-nullable-trap` — `NOT IN` over a nullable column matches 0 rows and reports success — CLAUDE.md — A [docs,git,code]
54. `like-wildcard-escaping-ids` — `_` is a wildcard; escape + match as a quoted token — DatabaseDao.kt — A [docs,git,code]
55. `room-rawquery-readonly-vacuum` — @RawQuery takes a reader connection (query_only); VACUUM via useWriterConnection; checkpoint first; a failure must not surface — MusicDatabase.kt — A [docs,git,code]
56. `clean-satellite-at-transition` — delete dependent rows at the state change, not only in a bulk sweep — ArtistRepositoryImpl — A [docs]
57. `room-kmp-setup` — expect builder, bundled driver, per-arch audit of the driver jar (the arch gap lives in the artifact, not the database class; windows_arm64 missing at the audited version) — MusicDatabase.kt — A [code]
58. `room-migrations-at-scale` — consecutive edges carry reachability (the walker chains single steps; fan-in edges only shorten the walk); direct edges over gaps; recreate triggers idempotently in onOpen — MusicDatabase.android.kt — A [code]
59. `datastore-kmp-manager` — expect instance, flow + suspend-setter per key, interface in domain — DataStoreManagerImpl.kt — A [code]
60. `local-listening-analytics` — event + event_artist (denormalized timestamp), 20%/80% thresholds, enrich ids at read time — PlaybackEventEntity.kt — A [gaps]
61. `import-format-contract-design` — no version field, reject the empty-parse file, parallel arrays same-length rule, name known-bad legacy values — docs/import-format-v1.md — A [docs,git]
62. `bulk-json-import-progress` — chunk + emit progress, reject a parse that yields nothing, filter to FK-satisfying ids — ImportRepositoryImpl.kt — A [gaps]

## F · Compose/CMP UI — theming, color, scrim (7)
63. `smooth-scrim-gradient` — smoothstep both ends; interpolate colors in Kotlin; Transparent = black-alpha-0 so pass copy(alpha=0f) — UIExt.kt:465 — A [ui,core]
64. `angled-gradient-modifier` — a linear gradient at any angle staying inside the box — UIExt.kt:135 — A [ui,core]
65. `artwork-palette-theming` — accent vs dominant swatch, luminance-adaptive darken, hex/HSV kit — UIExt.kt:436 — A [code,core,ui]
66. `force-dark-immersive-subtree` — keep a subtree dark over dark artwork even in light theme; sheets in a Popup inherit the locals — theme/Theme.kt — A [ui]
67. `semantic-color-tokens-compositionlocal` — @Immutable AppColors via staticCompositionLocalOf for colors outside the M3 scheme — theme/Theme.kt — B [ui]
68. `deterministic-title-placeholder-painter` — hash a title → gradient + measured text as a custom Painter usable as a Coil placeholder — PlaylistThumbnail.kt — A [ui]
69. `overflow-tilted-browse-card` — offset-then-rotate a cover off a clipped tile edge; rotated bbox growth math — MoodCategoryCard.kt — B [ui]

## G · Compose/CMP UI — components & interaction (11)
70. `material-symbols-icon-system` — (house skill) generated ImageVector extension props for R8 stripping; not a Painter — ui/icon — B [docs,git]
71. `liquid-glass-backdrop` — Highlight default is directional (small round buttons read as nothing); the backdrop source must be a sibling; the discriminating swap experiment — LiquidGlassContainer.kt — A [docs,git,code]
72. `lazy-list-drag-reorder` — a full drag/drop state holder with animateItem + edge auto-scroll — RememberDragDropState.kt — A [ui]
73. `shimmer-skeleton-loaders` — a self-measuring shimmer modifier + skeleton boxes in a non-scrolling lazy list — Shimmer.kt — A [ui]
74. `swipe-action-list-row` — swipe for an action + long-press select; key pointerInput on the mode flag or the detector keeps a stale flag — FullWidthItems.kt — A [ui]
75. `selection-mode-state-holder` — @Stable multi-select by stable id with a single choke-point cap — SongSelectionState.kt — A [ui]
76. `expandable-and-linkified-text` — clamp with more/less via overflow detection; tappable timestamp/URL spans — ExpandableText.kt — A [ui]
77. `animated-gradient-border-ring` — a masked rotating sweepGradient ring via Offscreen + SrcIn — AnimationComponents.kt — B [ui]
78. `lazy-scroll-helper-kit` — isScrollingUp, centralize-item (withFrameNanos), visibilityPercent — UIExt.kt:126 — A [ui,core]
79. `custom-thin-media-slider` — thin track + buffered indicator; the M3-alpha valueRange overload gotcha (use 0..1) — FullscreenPlayer.kt:536 — B [ui]
80. `custom-modal-sheet-family` — transparent container, zeroed insets + end spacer, hide-then-dismiss — ModalBottomSheet.kt — B [gaps]

## H · Compose/CMP UI — screens, navigation, adaptive (8)
81. `responsive-gate-size-not-platform` — gate on wDP<hDP; one boolean must not answer two questions; aspectRatio/ContentScale/scrim all change together — Album/Artist screens — A [docs,git,code]
82. `nav-tab-registration-drift` — several nav surfaces each hold the tab list; enum ordinal is identity not position — AppBottomNavigationBar.kt — A [docs,code]
83. `type-safe-nav-graph-organization` — @Serializable route files, nested graphs as extension fns, one transition set, route-level theming wrap — AppNavigationGraph.kt — B [ui]
84. `collapsing-parallax-toolbar` — parallax header + two-segment title interpolation + pinned-toolbar flip — CollapsingToolbar.kt — B [ui]
85. `fullscreen-video-gesture-overlay` — tap-toggle chrome + double-tap seek zones + auto-hide + PiP-aware — FullscreenPlayer.kt — B [ui]
86. `nowplaying-pager-no-feedback-loop` — isScrollingInProgress covers both drag and animate; settledPage; pure computeSeekAction; SkipToPrevious not Previous — NowPlayingScreen.kt — A [code,git,ui]
87. `layered-video-backdrop-pager` — one pager wraps all layers; clipToBounds; per-page palette from the painted bitmap; full-height scrim — NowPlayingScreen.kt — B [gaps]
88. `desktop-mini-player-window` — a separate always-on-top Window driven by a plain object; drag/resize/hover — MiniPlayerWindow.kt — A [code]

## I · Reactive state — Flow / StateFlow / ViewModel (8)
89. `stateflow-conflation-inverts-state` — a handler writing N times per event; a conflating flow makes write-order a correctness question; write once at the end — MediaServiceHandlerImpl.kt — A [docs,git]
90. `named-job-lifecycle-discipline` — one `var xJob: Job?` per concern, cancel-before-relaunch, NonCancellable teardown — MediaServiceHandlerImpl.kt — A [gaps]
91. `readonly-stateflow-cold-to-hot` — expose asStateFlow only; stateIn + WhileSubscribed(5000) survives churn without leaking — SharedViewModel.kt — A [handlers]
92. `flatmaplatest-resubscribe-composite-key` — re-subscribe on a key change; distinctUntilChanged on a composite key before firing expensive one-shot work — SharedViewModel.kt — A [handlers]
93. `distinct-by-key-reset-cancel-per-item` — distinctUntilChangedBy(id); cancel the previous per-item job first; reset then fill — SharedViewModel.kt — B [handlers]
94. `combine-two-flags-to-gate` — an AND of independent flows into one on/off; collectLatest cancels; each start idempotent — BaseViewModel.kt — A [handlers,git]
95. `compose-multiplatform-viewmodel-base` — KoinComponent base, shared loading state, the runBlocking getString hazard — BaseViewModel.kt — A [code]
96. `dual-mode-persist-blocking-or-async` — one suspend body, a runBlocking flag for shutdown vs launch for background — MediaServiceHandlerImpl.kt — A [handlers]

## J · Repository / data-layer patterns (7)
97. `repository-flow-conventions` — local read = flow{emit}.flowOn(IO); remote read = Resource envelope; write = withContext(IO) — AlbumRepositoryImpl.kt — A [handlers,core]
98. `cache-then-network` — emit cache then fresh; only emit Error when nothing was cached — HomeRepositoryImpl.kt — A [handlers]
99. `ttl-keyed-json-cache-lenient-decode` — timestamped entries + isStale + a keyed map serialized as JSON + ignoreUnknownKeys — HomeRepositoryImpl.kt — A [handlers]
100. `generic-paged-db-accumulator` — read a whole table through a (limit,offset) DAO in a bounded loop — DatabaseExt.kt — A [handlers]
101. `continuation-token-pagination-contract` — page + next-token as Flow<Resource<Pair<items,token?>>>; bounded prefetch to start — MediaServiceHandlerImpl.kt — A [handlers]
102. `encoded-continuation-tokens-local-sort` — carry local sort/shuffle paging through the same token slot with a mode prefix + cursor — MediaServiceHandlerImpl.kt — B [handlers]
103. `order-preserving-section-mapping` — map all sections in received order, never result[0]/result[1] — HomeRepositoryImpl.kt — B [handlers]

## K · Background work / runtime / platform (8)
104. `app-backup-to-zip-mediastore` — WAL checkpoint BEFORE copying the DB; MediaStore.Downloads; a retention query — AutoBackupWorker.kt — A [gaps]
105. `datastore-driven-workmanager` — observeAndSchedule combine; ExistingPeriodicWorkPolicy.UPDATE; cancel on disable — AutoBackupScheduler.kt — A [gaps]
106. `periodic-worker-dedup` — the DB is the source of truth for "already pushed", a window wider than the interval, oldest-first — RssFeedNotifyWork.kt — A [gaps]
107. `desktop-single-instance-before-di` — the single-instance guard must run before startKoin (before anything touches on-disk state) — DesktopApp.kt — A [git]
108. `compose-desktop-runtime-hardening` — probe Desktop before loading the native; skiko vsync off; VM detect; WM_CLASS by reflection — DesktopApp.kt — A [code]
109. `swappable-crash-reporting-and-dialog` — three top-level functions not an interface; a Swing crash dialog for when Compose may be dead; EDT marshalling — Crashlytics.kt/CrashDialog.kt — A [gaps]
110. `kmp-logger-facade` — one object over the log lib + muted-tags set (the "config-driven verbosity" half was refuted in verify — no severity gate exists; the skill teaches the honest gap) — Logger.kt — B [code,core]
111. `glance-widget-over-existing-state` — inject the same VM/scope, re-issue update(), allowHardware(false) — MainAppWidget.kt — A [gaps]

## L · Consuming APIs the right way — architecture, neutral, NO service names (12)
112. `ktor-kmp-client-architecture` — expect engine per platform; a log-heavy client vs a bare download client; ContentNegotiation with json/xml/protobuf; a proxy change rebuilds the client — ktorExt — A [code]
113. `curl-logger-ktor-plugin` — createClientPlugin, shell-safe single-quote escaping, one command per log line — CurlLoggerPlugin.kt — A [code]
114. `parallel-chunked-download` — N range requests, a bare client, channelFlow progress — Ytmusic.kt (download fn) — A [code]
115. `structural-defensive-parsing` — classify a field by the payload's own declared type, not by index; mapNotNull is silent data loss (count what you drop); never invent a placeholder; parse duration right-to-left — SongRunParser.kt — A [gaps,docs,git]
116. `response-to-domain-flow` — network → parser layer → domain model → Resource → collect; one service module per integration so a break can't spread — core/data/parser — A [code,core,web]
117. `api-ok-but-ignored` — an OK status can still mean rejected; read the ignored-reason field; log filtered metadata loudly — (neutralized) — A [docs,git]
118. `unknown-not-a-valid-score` — a parse-failure fallback must be a sentinel, never a value that is legal in the success domain — (neutralized) — A [web,blog]
119. `enum-normalize-over-legacy-data` — read the source's own type field; normalize first (older rows hold invented labels); null means "not stated", expose isKnown — MusicVideoType.kt — A [docs,git,gaps]
120. `oauth-callback-not-through-nav` — hand the callback token straight to the session VM; the screen closes on observed state; routing it through navigation strands a second login screen — (neutralized) — A [docs,git]
121. `retry-needs-backoff-and-cap` — an unbounded auth retry loop heats the device; gate on idle; a fail-silent feature needs an explicit health signal — (neutralized) — A [blog,web,git]
122. `login-state-fans-out-to-settings` — reset dependent toggles on logout, or a gated switch stays on for a service you're no longer authenticated to — (neutralized) — A [git]
123. `nested-flag-settings-auto-disable` — LaunchedEffect(isEnable) not Unit; gate at the consumer with combine; the UI greys out a stuck toggle so only code can clear it — SettingItem.kt — A [docs,gaps]

## M · Kotlin / KMP utilities (10)
124. `levenshtein-fuzzy-match-pure-kmp` — two-row DP + best/top-N selection, no library — StringMatcher.kt — A [core]
125. `kmp-html-entity-decoder` — named + hex + decimal entities without android.text.Html — AllExt.kt:154 — A [core]
126. `kotlinx-datetime-helper-kit` — named wrappers over the Instant/LocalDateTime dance + a time-ago formatter — AllExt.kt — A [core]
127. `bitmask-event-wrapper` — contains()/containsAny() over an int flag-set — PlayerEvents.kt — A [core]
128. `empty-sentinel-instance` — companion EMPTY to avoid nullable model fields — GenericMediaItem.kt — B [core]
129. `jvmname-disambiguate-erased-overloads` — @JvmName for two extensions differing only by generic receiver — ModelToEntity.kt — A [core]
130. `model-entity-mapping-extension-layer` — pure conversion functions isolated from DTOs and DAOs — ModelToEntity.kt — B [core]
131. `marker-interface-nested-enum-polymorphism` — reuse one shelf composable across screens via a tag interface + a runtime discriminator — TypeInteface.kt — B [core]
132. `expect-actual-composable-capability` — screen-size/keep-screen-on/PiP behind @Composable expect + full-vs-stub actual — UIExt.android.kt/jvm.kt — A [core]
133. `small-collection-utilities` — symmetricDifference, indexMap, tolerant timestamped-token parse/serialize, external-link→deep-link translation — AllExt.kt/RichSyncParser.kt — A/B [core]

## N · Engineering method / discipline (7)
134. `run-discriminating-experiment-first` — count the differing variables; design a test that halves them; never delete a running experiment before its result — memory — A [docs]
135. `noop-actual-not-platform-limit` — an empty actual means nobody wrote it; check the cached KMP variant + source set before saying "platform can't" — memory — A [docs,git]
136. `read-build-logs-bottom-up` — Gradle prints errors near the top; an empty grep is not a clean build — memory — A [docs]
137. `changelog-as-war-story` — dated entries: symptom, mechanism, what was ruled out, the exit condition; an auto-update rule; search tracked markdown before commit messages — CLAUDE.md — A [docs,git]
138. `writing-agent-skill-house-style` — frontmatter description that includes the error symptom; a Traps section that dominates; tell how to verify a value not list stale ones — simpmusic-icons/SKILL.md — A [docs]
139. `xml-to-compose-sequencing` — hardest screen first; consolidating scattered state is the real bridge; navigation drags a serialization migration with it — git-deep — B [git-deep]
140. `commit-archaeology-red-flags` — empty-bodied commits: the --stat is the abstract, the subject lies; a submodule bump hides its real content — git-deep — C [git-deep]

---

## CUT for scope (third-party service mechanics) — generic core salvaged into group L
- YouTube Music / InnerTube response parsing (wrapper renderers, pageType classification, videoType, auth-dependent shapes) → generic core in `structural-defensive-parsing`, `enum-normalize-over-legacy-data`
- YouTube stream extraction (signature/n-param deciphering, the extractor-lifecycle add/remove, SAPISIDHASH auth)
- Last.fm (signature signing, status-ok-but-ignored, web-vs-desktop auth flow) → core in `api-ok-but-ignored`, `oauth-callback-not-through-nav`
- Discord gateway (opcode state machine, rate-limited presence, session hygiene) → core in `retry-needs-backoff-and-cap`, `login-state-fans-out-to-settings`
- Spotify (TOTP derivation, Canvas fuzzy match + protobuf, login-URL matching, cookie handoff)
- Lyrics providers fallback chain; AI provider (BYOK) client; Tidal endpoint resilience + key normalization → `unknown-not-a-valid-score`
- SponsorBlock segment skipping (generic "auto-skip timed segments off the progress flow" could be salvaged if wanted — currently CUT)
- Local↔YouTube playlist sync (setVideoId membership) → generic `two-way-sync-state-machine-delta-diff` kept? (currently folded, mark if wanted)
- Google Cast handoff — BORDERLINE (uses Google SDK); CUT by default, can return as neutral "remote-playback handoff architecture"

## Not yet mined (potential future lanes)
- Notion SecondBrains (owner's second brain) — connector not yet authorized
- AdapterItems.kt home-feed item catalog; dialog family; AnalyticsScreen chart rendering
- SharedViewModel ~320-2057; Artist/Song/Stream repository bodies

## Batch 6 — delta mined 2026-08-24 (76 new · 20 updated)

> Mined from the source project's continued development after the original 140 shipped: 10 write lanes → 10 adversarial verify lanes → 7 fix lanes, same quality bar and the same anonymity rules. Grouped below by mining cluster; the trailing letter is the A–N taxonomy above.

**Shared sessions — bridge, roles and intent (10)**
141. `sync-room-bridge-echo-guard` — one bridge, direction decided by role; a flag held across the apply stops a remote command's local side effect being published straight back — D
142. `play-intent-decided-before-load` — decide whether and where the item starts before building it, instead of loading with a hardcoded "start playing" and correcting a moment later — D
143. `intent-flag-not-observed-state` — a component committed to running still reports "not running"; anything meaning intent reads the intent flag, and waits for it with a timeout rather than sampling inline — D
144. `server-default-overrides-client-intent` — a relay stamps its own default onto fields your command left unset, so a follower obeying it verbatim stops the thing it just loaded — D
145. `position-based-group-sync` — publish the playhead with every command, correct for flight time, seek only past a tolerance — never make everyone wait for the slowest member — D
146. `joiner-catches-up-by-asking` — pushed state is the source's last command replayed, so its position is however old that command is; ask for the live position on arrival — D
147. `follower-transport-stays-local` — a follower owns its own stop button: pausing is local and silent, and resuming asks where the group is now rather than restoring where this device stopped — D
148. `runtime-override-not-preference-write` — disable a feature for the duration of a mode with a runtime override, never by writing the stored preference a process death would make permanent — D
149. `derive-seek-from-progress-flow` — detect a scrub as a playhead that moved further than wall-clock time allows; the platform's own discontinuity callback exists on one backend only — D
150. `follower-item-built-from-shared-payload` — build the follower's item from the payload the session carries, not by re-resolving locally: a shape-based guess picks the wrong rendition and a per-item round trip wedges the collector — D

**Wire protocol, clocks and session lifecycle (7)**
151. `monotonic-clock-offset-sync` — take the peer's processing time out before halving the round trip, weight samples against the best trip seen, and insist the local source is monotonic — L
152. `readiness-barrier-needs-every-answer` — answer a group barrier on bufferedness rather than on playing, answer only when actually named, and accept that one member who never answers freezes everyone — D
153. `protobuf-without-codegen-kmp` — annotate ordinary data classes with field numbers instead of generating a JVM-only code layer; one encoder setting decides whether the bytes match — L
154. `borrowed-wire-protocol-discipline` — a protocol someone else defined is not yours to improve: no renaming, no reordering, omitted constants read off the counterpart, unknown types decoded to null — L
155. `websocket-session-handshake-lifecycle` — reader started before the first message because the answer returns through it, handshake settled on a deferred with a timeout, close frame sent non-cancellable — L
156. `publish-a-snapshot-on-taking-the-role` — every publisher is edge-triggered, so whoever was already running when they took the role emits nothing; publish a full snapshot on becoming the source — L
157. `pending-state-makes-waiting-legible` — model "asked, and not yet answered" as its own field, or a refusal and a peer who never looked are indistinguishable — I

**One curve, two engines — filters, presets and profile import (10)**
158. `filter-chain-two-owners-one-writer` — two features wanting entries in one whole-chain property need per-feature fields, a single writer, and a clear that drops only its own tier — D
159. `identity-compare-immutable-setting` — bundle a multi-field setting into one immutable value behind a supplier, so a hot consumer asks "changed?" once and can never see the fields half-updated — M
160. `sampled-supplier-vs-per-handle-reapply` — one backend samples a shared field per buffer and needs no push; the other starts every handle blank and needs an explicit re-apply at each creation site — D
161. `one-setting-two-backends` — define the centres, width and range once and verify both backends against a reference implementation rather than by ear — D
162. `preset-identity-read-back-from-value` — derive "which preset is this" by comparing against the value in force instead of storing a label, so editing drops to Custom and returning re-selects — I
163. `remote-index-cached-as-rows-with-validator` — parse a large published index into indexed rows once and re-check with the server's own validator; a 200 that parses to nothing is a failure, not a refresh — J
164. `control-range-must-cover-stored-values` — size a slider from the real distribution it will be handed, because an out-of-range value parks the thumb at the end while the readout shows a different number — G
165. `removing-a-feature-audit-shared-handles` — before deleting a feature, audit what else uses the handle it appeared to own, delete the other platforms' no-op stubs, and force-stop before judging the result — N
166. `edit-a-shape-as-a-shape` — when the value is a curve, draw a draggable curve rather than N sliders: raw pointer loop, one commit per gesture, smoothing that never overshoots a placed handle — G
167. `optional-engine-feature-degrade-in-tiers` — an engine rejects the whole chain when one stage is unknown, so retry without the optional stage and report which tiers were accepted — D

**A screen with two looks — shell, content and the rules between them (11)**
168. `screen-shell-content-split` — split a screen into a shell owning every cross-look concern and a content layer that only renders, connected by a state snapshot and an actions bag — H
169. `variant-layout-math-stays-in-the-variant` — keep a fit-one-screen measurement per look instead of hoisting one, and mirror the invisible spacer to the ratio actually drawn — H
170. `hoist-the-flag-not-the-animation` — share the boolean that drives a fade, never the tween that runs it, so one look can go asymmetric without changing how the other feels — G
171. `dont-pre-animate-a-self-animating-property` — a component that animates a property itself ignores new targets mid-flight, so an externally tweened value freezes it part-way — G
172. `progress-indicator-as-scrubber` — build a seek control from an indicator plus a transparent pointer layer: taller hit box, drags consumed so an ancestor pager cannot steal the scrub — G
173. `restricted-marker-is-not-an-opt-in` — tell an opt-in marker from a restricted-to marker before adding suppressions; only the first is compiler-enforced, and both coexist in one library — M
174. `artwork-seeded-dynamic-scheme` — derive a whole tonal scheme from one extracted seed and wrap only that subtree, tweening the seed rather than the scheme — F
175. `a-stated-rule-needs-annotated-exceptions` — a rule with legitimate exceptions rots unless every exception carries its reason at the call site and the rule itself is greppable — N
176. `scoped-composable-shadows-the-top-level-one` — inside a layout scope a same-named scope extension wins silently, so a call written for the plain version gets the scoped one's defaults — G
177. `settings-value-round-tripped-through-its-label` — mapping a chosen localized label back to a stored value breaks the day two labels translate identically; carry the id, and make the miss loud — G
178. `self-hiding-child-cannot-hide-its-slot` — a component that renders nothing cannot remove the container someone else wrapped it in; gate the slot on the same published predicate — G

**Charts that refuse to lie (7)**
179. `self-normalised-axes-need-a-second-shape` — self-normalised axes need one guarded denominator each and a second polygon, because a lone shape on them says nothing — G
180. `dont-slice-one-circle-between-unrelated-measures` — measures sharing no whole go on concentric arcs, capped short of 360°, drawn over a full-ring track — G
181. `delta-absent-not-infinite` — render a change against an empty baseline as nothing at all: never +100%, never an infinity, never a saturated integer — G
182. `partial-chart-must-say-so` — print the share of input the distribution could classify, computed with the same predicates that built the buckets, and keep that line reachable at zero coverage — G
183. `equal-buckets-or-no-buckets` — buckets of exactly equal width with the remainder falling outside; a partial newest bucket must never be drawn at full width — G
184. `mosaic-arrangements-must-be-hole-free` — a ranked mosaic needs an arm for every count, so no entry is silently dropped and no arrangement leaves an empty rectangle — G
185. `empty-state-must-keep-its-navigation` — replacing a populated header with an empty-state message must not delete the controls that header owned, or the user cannot get back out — H

**Time, windows and shares in the query layer (8)**
186. `stored-timestamp-is-a-local-wall-clock` — a converter-written timestamp can hold local time encoded as UTC; declaring a projection field as a raw number opts out of the converter and applies the offset twice — E
187. `bucket-local-time-in-code-not-in-sql` — the engine's local-time modifier answers from the process time zone, and four local-time aggregates mean four scans that can disagree — E
188. `one-snapshot-per-period-not-many-flows` — return a period's figures as one immutable snapshot from a single suspend call; separate emissions let this period's count render beside last period's total — I
189. `unbounded-for-shares-capped-for-lists` — a top-N query is right for a list and wrong for a share of the whole, because the cut tail shrinks the denominator invisibly — E
190. `first-ever-not-first-in-window` — take MIN over the entity's whole history and ask whether it lands inside the window; filtering first and grouping after calls every entity new — E
191. `palette-state-parks-on-loading` — a generator that flips to Loading before its own suspension point reports no colour for the whole generation, and a cancelled one never restarts — F
192. `string-resource-format-limits` — the multiplatform formatter substitutes plain positional placeholders and nothing else, so padding, rounding and units belong in code — M
193. `inclusive-period-boundaries-and-offset-reset` — hold one boundary convention everywhere, and reset the step offset whenever the granularity changes — E

**Effects, indication and transitions (8)**
194. `event-not-state-edge-for-one-shot-effects` — fire a one-shot effect from the click that caused it; an effect watching a boolean edge cannot tell a tap from data arriving a beat later — G
195. `draw-outside-bounds-particle-modifier` — draw modifiers are unclipped by default, so the modifier must sit before every clip in the chain, and reach scales off the host's measured size — G
196. `image-fallback-url-retry-in-composition` — hold the URL in composition state and swap it once in onError; the cache key must follow the mutated URL and the swap must be a no-op the second time — G
197. `text-brush-shimmer-sweep` — put the moving gradient on the text style itself so glyphs are painted by the brush; declare the infinite transition unconditionally or it restarts on every appearance — G
198. `touch-indication-bounds-and-alpha` — soften a ripple by alpha alone and give it the right bounds; clip must precede clickable, and a card and its clip need one shape value — G
199. `crossfade-container-sizes-to-the-visible-child` — the container is a top-start Box sized to the largest composed child, so a thin child pins to the top mid-transition and drops when the tall one leaves — G
200. `slide-transition-defaults-to-half-a-height` — a vertical slide defaults to half the element's height, so it starts already halfway and reads as a pop — G
201. `transparent-chip-selection-signals` — a shadow under a transparent shape shows through as a dark ring, and zeroing resting elevation does not remove it: each interaction state carries its own token — G

**Measurement, insets and commit points (5)**
202. `weight-fill-false-to-center-a-cluster` — a weighted child occupies its whole slot even when narrower, pinning its sibling to the far edge; releasing the unused width is two edits, not one — G
203. `stacked-bars-double-consume-window-insets` — inset consumption reaches descendants and never siblings, so two stacked inset-aware bars each reserve the system bar — H
204. `lazy-item-grouping-beats-arrangement-gap` — a list's spacing applies between every pair and compounds with each item's own padding, so a block that reads as one unit belongs in one item — G
205. `floating-overlay-reserves-its-own-strip` — a floated control takes part in no measurement, so every scrolling branch must reserve the strip it covers explicitly — H
206. `commit-a-text-field-on-an-explicit-action` — writing on focus loss stores whatever was half-typed when a dialog or a stray tap took focus; keep the draft keyed on the stored value — G

**Theming a shell that is not the default (5)**
207. `gate-optional-effect-at-the-shared-primitive` — put the on/off setting inside the one primitive that draws the effect; the off path keeps the shape and hit target and changes only the paint — F
208. `shell-background-is-not-scheme-background` — the moment panels stop using the scheme background, every gradient and scrim converging on it ends on a hard seam — F
209. `flat-twin-shares-geometry-not-material` — when a setting picks between an expensive rendering and a plain twin, every geometry decision must be mirrored: the compiler cannot pair two constants in two files — F
210. `chrome-drawn-outside-the-theme-scope` — a title bar, splash or crash dialog composed as a sibling of the theme reads the framework default scheme, light always, and nothing errors — F
211. `ambient-tone-layer-behind-flat-pages` — a reusable top-glow emitted as the first sibling of a destination's content; a null tone must collapse into the page colour, not substitute a theme colour — F

**Platform surfaces and data-layer reach (5)**
212. `two-vendors-one-package-kmp-api-skew` — two vendors shipping one package name at different versions into different source sets make an import that compiles for one target and fails for the other — C
213. `remoteviews-bitmap-budget` — every bitmap crosses a process boundary against a fixed budget, so decoding at draw size is what keeps the widget on screen, not an optimisation — K
214. `glance-layout-vocabulary` — the widget toolkit has no aspect ratio, weight is always 1, corner radius applies only from a later API, and the cell's spare height must be spent deliberately — K
215. `search-over-a-paged-list-queries-the-source` — filtering a paging stream only searches the pages already loaded; the search must query the store and render as a sibling overlay — J
216. `mirror-local-state-to-a-remote-account` — an opt-in mirror back-fills on enable, deliberately does not undo on disable, and reports three values so "not attempted" differs from "failed" — J

**Updated in batch 6 (20):** `changelog-as-war-story` · `commit-archaeology-red-flags` · `compose-multiplatform-viewmodel-base` · `expect-actual-composable-capability` · `flatmaplatest-resubscribe-composite-key` · `force-dark-immersive-subtree` · `glance-widget-over-existing-state` · `import-format-contract-design` · `koin-viewmodel-scoping-traps` · `liquid-glass-backdrop` · `local-listening-analytics` · `material-symbols-icon-system` · `media3-custom-audio-processor` · `nav-tab-registration-drift` · `nested-flag-settings-auto-disable` · `realtime-biquad-dsp` · `response-to-domain-flow` · `responsive-gate-size-not-platform` · `retry-needs-backoff-and-cap` · `unknown-not-a-valid-score`
