# Raw mining report — Lane 10: UI screens, theme, reusable components

> Mined 2026-08-19. 24 candidates (+1 note). Neutral vocabulary. commonMain uses java.* → CMP targets are JVM-family (Android + Desktop), not iOS/Native.

**1. smooth-scrim-gradient** — fade artwork edges into bg without seam/grey band. Smoothstep easing (flat at both ends); interpolate colors in Kotlin, callers pass `color.copy(alpha=0f)` not `Color.Transparent` (Skia un-premultiplied stop interp → dirty grey). Evidence: `extension/UIExt.kt:465-533`. A.

**2. angled-gradient-modifier** — linear gradient at arbitrary angle staying inside the box. `Modifier.angledGradientBackground(colors,degrees)` computes vector length per-quadrant via atan2/cos/sin; `GradientOffset` presets. Evidence: `extension/UIExt.kt:135-308`. A.

**3. shimmer-skeleton-loaders** — placeholder skeletons. `Modifier.shimmer()` = `composed{}` measuring own size, animating gradient sweep via `rememberInfiniteTransition`; skeletons are sized Boxes in `LazyRow/Column(userScrollEnabled=false)`; theme-aware tokens. Evidence: `UIExt.kt:76-108`, `ui/component/Shimmer.kt`, `theme/Theme.kt:34-49`. A.

**4. lazy-list-drag-reorder** — drag-to-reorder in LazyColumn. `rememberDragDropState` + `DraggableItem` + `DragDropState`: dragged index/offset, `onSwap(from,to)`, `animateItem(placementSpec)`; `getVisibleItemInfoFor`, `offsetEnd`, `checkForOverScroll()` auto-scroll delta near edges; lifted item via `graphicsLayer{translationY}`+`zIndex(1f)`. Evidence: `ui/component/RememberDragDropState.kt` (whole). A.

**5. collapsing-parallax-toolbar** (partial dup of adaptive headers) — NEW: header `graphicsLayer{translationY=-scroll/2;alpha=ramp}` parallax+fade; two-segment `lerp` of title X/Y/scale across collapse; `derivedStateOf{scroll>=toolbarBottom}` flips pinned toolbar; title self-measures via `onGloballyPositioned`. Evidence: `ui/component/CollapsingToolbar.kt:90-464`. B.

**6. force-dark-immersive-subtree** — screens over dark artwork stay dark even in light theme. `ForceDarkContent` re-provides dark ColorScheme + `LocalContentColor` + `LocalForceDarkText` + `LocalAppColors`; dark scheme resolved once in AppTheme. KEY: Compose sheets/dialogs render in a Popup keeping parent CompositionLocals, so force-dark flows in automatically. Evidence: `theme/Theme.kt:44-199`, `theme/Typo.kt:29-41`, `component/SurfaceDarkColors.kt`, `component/HolderPainter.kt`. A.

**7. semantic-color-tokens-via-compositionlocal** (partial dup palette) — colors outside M3 ColorScheme (favorite, lyric-active, shimmer, overlays). `@Immutable AppColors` via `staticCompositionLocalOf`, light/dark instances; overlays stay dark in both (cover artwork); `LocalIsDarkTheme` for glass. Evidence: `theme/Theme.kt:20-54`, `theme/Color.kt`. B.

**8. dynamic-seed-theming** (DUP palette) — whole ColorScheme from seed/wallpaper via materialkolor `rememberDynamicColorScheme`; `withNeutralLightSurfaces()` documents pure-grey ramp + `#FAFAFA` rationale. Evidence: `theme/Theme.kt:62-171`. B (mostly covered).

**9. deterministic-title-placeholder-painter** — artwork-less items need a stable unique cover. `generateGradientFromTitle` hashes title→two hues→gradient; `PlaylistThumbnailPainter` custom `Painter` drawing gradient + measured text (`TextMeasurer`) + badge; usable as Coil placeholder/error. Evidence: `ui/component/PlaylistThumbnail.kt`, `hsvToColor` `UIExt.kt:622-645`. A.

**10. overflow-tilted-browse-card** — tile with a tilted cover peeking off the corner. `angledGradientBackground` + `drawBehind` badge; cover `.offset(...)` THEN `.rotate(25f)` runs off clipped tile edge (parent clips children); documents rotated-square bbox growth `size*(cos+sin)`. Evidence: `ui/component/MoodCategoryCard.kt`. B.

**11. swipe-action-list-row** — swipe row sideways for an action + long-press selection. `Animatable` offsetX + `detectHorizontalDragGestures` (snapTo drag, animateTo(0) end, fire at maxOffset); `Crossfade` reveals action past half-threshold. GOTCHA: `pointerInput(selectionMode)` keyed on the flag so the swipe detector tears down when selection starts — keyed on `Unit` it keeps a stale flag. Evidence: `ui/component/FullWidthItems.kt:119-268`. A.

**12. selection-mode-state-holder** — multi-select with a hard cap. `@Stable class SongSelectionState`: track by stable id (videoId) not index (lists paged/reorderable); `mutableStateListOf`; single private `add()` choke-point enforces cap (25); `toggleSelectAll` = deselect-all; auto-exit when last deselected. Evidence: `ui/component/selection/SongSelectionState.kt`. A.

**13. expandable-and-linkified-text** — clamp long text with more/less + tappable timestamps/URLs. `ExpandableText`: `onTextLayout{hasVisualOverflow}` detects truncation, `buildAnnotatedString` + re-clamp at `getLineEnd`. `DescriptionView`: regex-tag `mm:ss`/URLs with `pushStringAnnotation`, resolve tap via `getOffsetForPosition`→`getStringAnnotations`. Evidence: `ui/component/ExpandableText.kt`, `ui/component/DescriptionView.kt`. A.

**14. animated-gradient-border-ring** — rotating glowing border. `InfiniteBorderAnimationView`: rotating `sweepGradient` circle behind content with `CompositingStrategy.Offscreen`+`BlendMode.SrcIn` masking it into a ring; `LimitedBorderAnimationView` runs N cycles then stops. Evidence: `ui/component/AnimationComponents.kt`, `ChipGroup.kt`. B.

**15. lazy-scroll-helper-kit** — `isScrollingUp()` (List+Grid, derivedStateOf) for hide-on-scroll; `animateScrollAndCentralizeItem` (withFrameNanos to wait a layout pass); `visibilityPercent`, `getVisibleItemInfoFor`. Evidence: `UIExt.kt:126-131,350-434`, `RememberDragDropState.kt:46-58`. A.

**16. fullscreen-video-gesture-overlay** — landscape video: tap-toggle chrome + double-tap seek zones. Two weighted zones `detectTapGestures(onTap,onDoubleTap=±5s)`; ripple at tap point via `MutableInteractionSource`+`PressInteraction.Press(offset)`; auto-hide `LaunchedEffect(showOverlay,isSliding){delay(3000);hide}`; `rememberIsInPipMode()`; `FullScreenRotationImmersive` expect/actual. Evidence: `ui/screen/player/FullscreenPlayer.kt:155-306`. B.

**17. custom-thin-media-slider (+valueRange gotcha)** — slim seek bar + buffered track. Custom `SliderDefaults.Track/Thumb` (thin, suppressed ticks, transparent inactive); `LinearProgressIndicator` behind shows buffered %. GOTCHA: material3 1.5.0-alpha25 keeps a binary-compat `Slider` overload accepting `valueRange` then DROPS it → drive with 0..1 fraction not 0..100. Evidence: `FullscreenPlayer.kt:536-648`, note `NowPlayingScreen.kt:~1691`. B.

**18. cmp-platform-ui-abstraction-catalog** — what UI concerns to push behind expect/actual (JVM-family CMP). Clean set: dynamic color scheme, `SystemBarAppearanceEffect`, `MediaPlayerView`, WebView/cookies, `HorizontalScrollBar`, pickers, `PlatformCastButton`, `rememberIsInPipMode`, `KeepScreenOn`, `ImageBitmap↔bytes`, clipboard/open-url/share, orientation. Note: an `expect class` (LiquidGlass) with real Android + no-op JVM actual was replaced → prefer expect funs / runtime checks over expect class. Evidence: `expect/**`. B.

**19. progressive-blur-artwork-edge (+per-platform guard)** (adjacent liquid glass) — melt header bottom into page. Haze `hazeSource`/`hazeEffect` + `HazeProgressive.verticalGradient`; blur box capped at fixed height (cost cap), separate taller color-scrim box does the long ramp; backdrop source must be a SIBLING not child (render feedback loop crashes draw); progressive path guarded Android-only (skiko signature mismatch crashes the draw); negative `Arrangement.spacedBy((-36).dp)` pulls row up AND shrinks layout. Evidence: `ui/screen/other/ArtistScreen.kt:240-380`. B.

**20. type-safe-nav-graph-organization** — Navigation-Compose type-safe routes + shared transitions. `composable<Destination>` each a tiny `@Serializable` file; nested graphs as extension fns; one enter/exit/pop transition set on NavHost; a destination wrappable (`ForceDarkContent{ ... }`) to theme a route. Evidence: `ui/navigation/graph/AppNavigationGraph.kt`, `ui/navigation/destination/**`. B.

**21. adaptive-transport-control-bar** — one transport row across mini/full/desktop at different sizes. Size-tier Dp pairs by `isSmallSize`; `Crossfade` per toggle driven by `ControlState`; equal `weight(1f)`; `plainPlayPause`/`activeColor`/`contentColor` params so callers restyle without forking. Evidence: `ui/component/PlayerControlLayout.kt`. B.

**22. reusable-modifier-and-color-helpers** — `PaddingValues.copy(...)` (LTR-aware), `animateAlignmentAsState` (decompose BiasAlignment), `Modifier.greyScale()` (ColorMatrix saturation-0 via saveLayer), `Modifier.isElementVisible` (boundsInWindow overlap), `Color.rgbFactor`, `hexToColorOrNull`, `hsvToColor`, `NonLazyGrid` (fixed-col grid nestable in a scroll). Evidence: `UIExt.kt:110-133,313-348,535-645`. A.

**23. debounced-search-with-suggestions** — search-as-you-type + history + rotating hint. `LaunchedEffect(searchText){delay();suggest}` debounce; history LazyColumn clear/tap-to-run; placeholder rotates every 3s. Evidence: `ui/screen/other/SearchScreen.kt:201-290,471-520`. B.

**24. expressive-morphing-loader & auto-sizing-badge** (niche) — `CenterLoadingBox` morphs `containerShape` among polygons every 500ms; `AIBadge` `BasicText(autoSize=TextAutoSize.StepBased(min=6.sp))`. Evidence: `ui/component/CenterLoadingBox.kt`, `Badge.kt`. C.

**25. keep-pager-player-sync-logic-testable** — pure unit-testable `deriveOrderIndex`/`computeSeekAction` extracted out of the Compose pager settle callback. Evidence: `ui/screen/player/ArtworkPagerLogic.kt`. B.

## Duplicates (covered): dynamic-seed-theming/semantic-tokens ↔ palette; progressive-blur ↔ liquid glass; collapsing-toolbar ↔ adaptive headers; LiquidGlassContainer, MiniPlayer Layout, NowPlaying pager/backdrop, LyricsView, ModalBottomSheet, SettingItem, SimpIcons — all covered.
## Not reached: AdapterItems.kt (1339 lines, home-feed item catalog), GridLibraryPlaylist/LibraryItem/PodcastEpisodeItem layouts, dialog family (VoteLyrics/Review/BlogPromo/Loading), AnalyticsScreen+SimpMusicChart (chart wrapper, likely out of scope).
