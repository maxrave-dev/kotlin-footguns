# Raw mining report — Lane 8: core/common + core/domain + shared extensions

> Mined 2026-08-19. 20 candidates. Neutral vocabulary. Format: name / trigger / core / evidence / audience / generality.
> Scope note: core/common commonMain = only Logger.kt + Config.kt (covered). Platform.android.kt/Platform.ios.kt are EMPTY package stubs. No connectivity/Result/Either beyond Resource. Real material is in core/domain + composeApp/extension.

**1. kmp-player-abstraction-generic-models** — wrap a platform/3rd-party player behind a shared interface so domain/UI never import the library.
- `MediaPlayerInterface` (play/seek/queue/modes/listeners) + `MediaPlayerListener`, ZERO platform types; platform modules implement.
- Payloads plain data classes: `GenericMediaItem/MediaMetadata/PlaybackParameters/CastState`, `PlayerError`, sealed `GenericCommandButton`.
- Same ViewModel/queue logic runs Android + iOS/JVM; swapping engines touches only platform impl.
- Sub-idea: separate gain factors (`volume` = user level, `sleepFadeFactor`, focus-duck) owned independently, multiplied only at the sink — a fade never drags the user's slider (`MediaPlayerInterface.kt:100-122`).
- Evidence: `core/domain/.../mediaservice/player/MediaPlayerInterface.kt`, `MediaPlayerListener.kt`, `.../data/player/*.kt`. Generality: A (concept) / B (fields).

**2. bitmask-event-wrapper-predicates** — platform hands an int flag-set; want `contains()`/`containsAny()` over raw `and`.
- `PlayerEvents(flags: Int)` → `contains(e) = flags and e != 0`, `containsAny(vararg)`.
- Generalizes to any Int/Long bitmask (permissions, dirty-flags, capabilities).
- Evidence: `core/domain/.../data/player/PlayerEvents.kt` (9 lines). Generality: A.

**3. empty-sentinel-instance-convention** — avoid nullable model fields via a canonical empty value.
- `companion object { val EMPTY = ... }` on the Generic* models; pairs with Resource; kills `?:` noise.
- Evidence: `GenericMediaItem.kt:12-19`, `GenericCastState.kt:10`, `GenericMediaMetadata.kt:13`, `GenericPlaybackParameters.kt:10`. Generality: B.

**4. repository-interface-conventions** — how to shape repo signatures in clean-arch Kotlin.
- Convention across ~18 repos: observable reads → `Flow<T?>`; one-shot writes → `suspend`; network fetches → `Flow<Resource<T>>`. Interfaces in domain, no framework imports.
- Ship WITH an anti-pattern example: `StreamRepository.getStream(dataStoreManager, ...)` leaks infra into the interface — a "don't do this".
- Evidence: `core/domain/.../repository/StreamRepository.kt` + 17 siblings. Generality: B.

**5. no-use-case-layer-decision** — do I need UseCase/Interactor classes?
- VERIFIED: core/domain has ZERO use-case/interactor classes (grep clean). Domain = repo interfaces + mappers + player abstraction + models; callers depend on repo interfaces directly.
- Lesson: a mid-size app can skip the interactor tier and still keep a clean boundary via interfaces + mapping functions; document the tradeoff.
- Evidence: absence across `core/domain/src/**`. Generality: B.

**6. marker-interface-nested-enum-polymorphism** — one list/shelf renders mixed item types reused across screens.
- `HomeContentType`/`LibraryType`/`SearchResultType`/`RecentlyType` marker interfaces; `PlaylistType` multiply-inherits so one shelf Composable is reused on Home + Library; each exposes `objectType(): Type` enum for exhaustive `when`.
- Evidence: `core/domain/.../data/type/TypeInteface.kt:19-23`, `ChartItem.kt`. Generality: B.

**7. documented-id-classification-helpers** — classify opaque provider ids in one place.
- `String.isRadioPlaylistId()/isRadioQueueId()/isRadioMix()` — one-liners wrapped in WHY comments about edge cases. Lesson = the DISCIPLINE (centralize + document external-id semantics so paging/UX can't drift).
- Evidence: `core/domain/.../utils/PlaylistId.kt` (38 lines). Generality: B concept / C code.

**8. model-entity-mapping-extension-layer** — keep DTO↔entity↔domain conversions out of both DTOs and DAOs.
- One `ModelToEntity.kt` holds `toTrack()/toSongEntity()/toAlbumEntity()/...` as pure, testable functions.
- Evidence: `core/domain/.../utils/ModelToEntity.kt` (464 lines). Generality: B.

**9. jvmname-disambiguate-erased-overloads** — two extensions differ only by generic receiver, won't compile (erasure).
- `@JvmName("...")` on same-named `toListTrack()` over `ArrayList<SongsResult>` vs `ArrayList<VideosResult>`.
- Evidence: `ModelToEntity.kt:167-174, 198-205`. Generality: A.

**10. levenshtein-fuzzy-match-pure-kmp** — fuzzy-match a string vs a candidate list without a library.
- Two-row DP `levenshtein()`; `bestMatchingIndex()` (distance threshold); `get3MatchingIndex()` top-N. Pure Kotlin → commonMain.
- Caveats: threshold `< 20` and case-sensitivity baked in.
- Evidence: `composeApp/.../extension/StringMatcher.kt` (72 lines). Generality: A.

**11. external-link-to-deep-link-translation** — handle pasted 3rd-party URLs by rewriting into your own scheme.
- `String.toAppDeepLinkOrNull(): Uri?` rewrites into the app's own scheme, hands to the EXISTING intent flow; `null` → treat as search query. Lesson: translate don't duplicate; graceful null not throw.
- Evidence: `composeApp/.../extension/YouTubeLinkExt.kt:7-17`. Generality: B concept / C code.

**12. tolerant-timestamped-token-parse-serialize** — parse `<MM:SS.mm> word` timed tokens AND write them back.
- Find all timestamps first, slice text BETWEEN matches; disambiguate centis vs millis by digit count (`len==2 → *10`); `null` on failure → caller falls back. Reverse serializers give parse/serialize symmetry.
- Evidence: `composeApp/.../extension/RichSyncParser.kt`, `ModelToEntity.kt:373-450`. Generality: B concept / C format.

**13. kmp-html-entity-decoder** — decode `&amp;`, `&#39;`, `&#x27;` without android.text.Html in commonMain.
- Named + hex + decimal numeric entities (with/without trailing `;`) via map + two regexes.
- Evidence: `core/domain/.../extension/AllExt.kt:154-204`. Generality: A.

**14. kotlinx-datetime-helper-kit** — wrap the verbose Instant↔LocalDateTime↔TimeZone dance.
- Domain: `now()`, `epochMillisToLocalDateTime()`, `plusSeconds()`, `isBefore/isAfter`, `beforeXDays()`, `startTimestampOfThisYear()`. UI: `formatTimeAgo()` via `periodUntil` + string resources, `formatDuration()` mm:ss, `parseTimestampToMilliseconds()`.
- Evidence: `core/domain/.../extension/AllExt.kt:23-43`, `composeApp/.../extension/AllExt.kt:68-102`. Generality: A/B.

**15. small-collection-utilities** — `symmetricDifference`, `indexMap`.
- `infix Collection<E>.symmetricDifference(other)` = `(a-b) ∪ (b-a)`; `Iterable<T>.indexMap(): Map<T,Int>`.
- Evidence: `composeApp/.../extension/AllExt.kt:54-66`, `ModelToEntity.kt:452-463`. Generality: A.

**16. compose-scroll-direction-visibility-kit** — hide a bar on scroll-down, center an item, know item visibility.
- `LazyListState/LazyGridState.isScrollingUp()` (derivedStateOf), `animateScrollAndCentralizeItem()` (uses `withFrameNanos {}` to wait one layout pass), `visibilityPercent()`, `Modifier.isElementVisible()` (viewport overlap via `onGloballyPositioned` + `boundsInWindow`).
- Caveat: `isScrollingUp` mutates `previous*` inside `derivedStateOf`.
- Evidence: `composeApp/.../extension/UIExt.kt:126-131, 350-434, 535-546`. Generality: A/B.

**17. angled-gradient-and-smoothstep-scrim** — draw a gradient at any degree, or a scrim that fades with no visible edge.
- `Modifier.angledGradientBackground(colors, degrees)` — geometry derivation keeps the gradient vector inside the rect. `smoothScrimBrush()/artworkScrimBrush()`: (a) smoothstep easing so both ends are flat (a linear ramp's corner IS the visible edge); (b) interpolate colors in Kotlin not Skia (Transparent = black-alpha-0, un-premultiplied interp drags RGB toward black → dirty grey band).
- Evidence: `composeApp/.../extension/UIExt.kt:135-229, 488-533`. Generality: A.

**18. color-manipulation-kit** — parse hex, convert HSV, derive readable bg from artwork.
- `String.hexToColorOrNull()` (6/8-digit, #-tolerant, null on bad), `hsvToColor()`, `Color.rgbFactor()`, `Palette?.toImmersiveBackground()` (dominant swatch + luminance-adaptive darken). NEW parts = hex/HSV/luminance (palette-swatch part overlaps covered work).
- Evidence: `composeApp/.../extension/UIExt.kt:436-486, 548-646`. Generality: A (hex/HSV) / B.

**19. expect-actual-composable-capability** — expose device capabilities (screen size, keep-screen-on, PiP) to shared Compose.
- `@Composable expect fun getScreenSizeInfo()/KeepScreenOn()/rememberIsInPipMode()`; Android actual (WindowMetrics + DisposableEffect; `Context.findActivity()` walks ContextWrapper), JVM stub actual. The project's REAL expect/actual example (vs empty core/common stubs) — teaches "full impl vs graceful no-op stub".
- Evidence: `UIExt.kt:310-311,371-372,576-577`, `UIExt.android.kt`, `UIExt.jvm.kt`. Generality: A/B.

**20. generic-kmp-intent-uri-model** — express navigation/deep-links in shared code without android.content.Intent.
- `GenericIntent(action, data: Uri?, type)` using multiplatform `com.eygraber.uri.Uri`.
- Evidence: `core/domain/.../data/model/intent/GenericIntent.kt`. Generality: B.

## Duplicates / overlaps
- Resource Flow collectors (`collectResource` etc.) — part of covered Resource pattern.
- Palette swatch extraction — overlaps covered; only hex/HSV/luminance math is new (#18).
- `DownloadState` object of Int consts — mild anti-pattern vs enum; not proposed.

## Not reached (out of scope / lower value)
- Large `data/model/**` DTO trees (third-party-shaped) — skipped per scope.
- `mediaservice/handler/DownloadHandler.kt`, `MediaPlayerHandler.kt` internals (orchestration-specific).
- Data-module repository IMPLEMENTATIONS (only interface conventions characterized) — being covered by scan-handlers lane.
- Entity classes (persistence schemas, not idioms).
