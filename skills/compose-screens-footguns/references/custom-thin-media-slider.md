---
name: custom-thin-media-slider
description: A slim seek bar with a buffered-progress track behind it, built from Material3's Slider with custom track and thumb slots — including the fraction-not-your-own-scale rule that keeps the thumb from pinning at the end, and the state gate that stops incoming playback position from fighting the drag. Use when a seek bar renders full or empty regardless of position, when the thumb snaps back while dragging, when a thin control refuses to get thinner, or when stray dots and ticks appear on the track.
---

# A thin seek bar with a buffered track

Two layers in one `Box`: a progress indicator showing how much is buffered, and on top of it a
`Slider` whose `track` and `thumb` slots you fill with `SliderDefaults.Track` and
`SliderDefaults.Thumb` — "custom" here means passing sizes and turning decorations off, not redrawing.

```kotlin
// adapted: dimensions kept; view-model calls became callbacks, the shared bar modifier was
// hoisted, and the source's two CompositionLocalProvider wrappers were merged into one
CompositionLocalProvider(LocalMinimumInteractiveComponentSize provides Dp.Unspecified) {
    Box {
        Box(Modifier.fillMaxWidth().height(24.dp), contentAlignment = Alignment.Center) {
            val bar = Modifier.fillMaxWidth().height(4.dp)
                .padding(horizontal = 3.dp).clip(RoundedCornerShape(8.dp))  // unequal on purpose
            Crossfade(isLoading) { loading ->
                if (loading) {
                    LinearProgressIndicator(bar, strokeCap = StrokeCap.Round)  // still resolving
                } else {
                    LinearProgressIndicator(
                        progress = { bufferedPercent / 100f }, modifier = bar,
                        strokeCap = StrokeCap.Round, drawStopIndicator = {},  // no far-end dot
                    )
                }
            }
        }
        Slider(
            value = sliderValue / 100f,                            // a fraction, always
            onValueChange = { isSliding = true; sliderValue = it * 100f },
            onValueChangeFinished = { isSliding = false; onSeek(sliderValue) },
            modifier = Modifier.fillMaxWidth().padding(top = 3.dp).align(Alignment.TopCenter),
            track = { state ->
                SliderDefaults.Track(
                    modifier = Modifier.height(5.dp), sliderState = state,
                    colors = SliderDefaults.colors().copy(inactiveTrackColor = Color.Transparent),
                    thumbTrackGapSize = 0.dp, drawTick = { _, _ -> }, drawStopIndicator = null,
                )
            },
            thumb = {
                SliderDefaults.Thumb(
                    modifier = Modifier.height(18.dp).width(8.dp).padding(vertical = 4.dp),
                    thumbSize = DpSize(8.dp, 8.dp),
                    interactionSource = remember { MutableInteractionSource() },
                )
            },
        )
    }
}
```

The inactive track is transparent because the buffered indicator underneath *is* the inactive track.

## Keeping the drag and the playback position apart

```kotlin
// adapted — one flag decides who owns the value
var isSliding by rememberSaveable { mutableStateOf(false) }
var sliderValue by rememberSaveable { mutableFloatStateOf(0f) }

LaunchedEffect(timeline, isSliding) {
    if (!isSliding) sliderValue =
        if (timeline.total > 0L) timeline.current * 100f / timeline.total else 0f
}
// and the elapsed label follows the thumb, not the player:
formatDuration((timeline.total * (sliderValue / 100f)).roundToLong())
```

## Traps

**Hand the slider a `0f..1f` fraction; never hand it your own scale.** The symptom that sends you
here is a bar pinned at the full track, thumb parked at the end and never moving, on a call that
passed `valueRange = 0f..100f` beside a 0..100 value; deleting the range and normalising fixes it.
Carry that fix for a bigger reason than one build: `Slider` ships three overloads and the range sits
somewhere different in each — fifth parameter in the plain one, *last* (after both slot lambdas) in
the customisable one, and **absent** from the `SliderState` one, where it has moved inside the state
object you construct yourself. A value on one scale meeting a range on another is a whole class of
defect; a fraction has no scale to mismatch. Be careful about the *cause*, though: on the artifact
this was seen against (Compose Multiplatform Material3 1.12.0-alpha01, tracking
`androidx.compose.material3` 1.5.0-alpha25) the customisable overload provably *does* forward its
range into the `SliderState` constructor. "The range was ignored" is a suspicion about that build,
not an established mechanism — the symptom and the fix are real, the explanation is not.

**Incoming position and the drag both write the same value.** Without the flag, every position
update snaps the thumb back to where playback actually is while the finger is still moving — worst
at the end of the drag, where the seek has been issued but the position has not caught up. Gate the
state write, and read the *label* off the slider value too. Anything else on a timer nearby (an
auto-hiding overlay) needs the same flag, or the controls vanish mid-drag.

**Material3 draws more than a line by default.** In this version family the track paints a stop
indicator at the far end and leaves a gap around the thumb, and a stepped slider paints ticks — on a
5dp white line all three read as artefacts. Each switches off separately (`drawStopIndicator = null`,
`drawTick = { _, _ -> }`, `thumbTrackGapSize = 0.dp`); the progress indicator has its own `= {}`.

**The minimum interactive size is the reason a thin control will not get thin.** Material3 enforces
a floor on touch targets, so a 5dp track still lays out around 48dp tall. Providing
`LocalMinimumInteractiveComponentSize` as `Dp.Unspecified` removes the floor — and with it the
guaranteed target, which you now owe by hand. Keep the gesture area larger than the paint: an 18dp
thumb slot painting an 8dp shape is a deliberate 2.25×, not a rounding error.

**Nothing keeps the two tracks aligned, and equal padding is the wrong instinct.** They are separate
composables in a stack and they do not measure alike: the slider reserves room for the thumb's
travel at both ends while a `LinearProgressIndicator` runs edge to edge, so identical horizontal
padding leaves the tracks different lengths and visibly out of line. The paddings above are unequal
on purpose — `horizontal = 3.dp` on the indicator gives back what the slider is already holding;
`top = 3.dp` on the slider only seats the thinner bar under the thumb. Match the corner radius too,
and the loading and buffered variants to each other in height, or the row jumps the moment playback
resolves. If that compensation will not hold, let the slider's own inactive track carry it instead.

**A `Crossfade` over the whole control fades the thumb too.** Fade only the layer that changes and
leave the slider mounted, or the seek bar is untouchable for the length of the animation.

Related: `nowplaying-pager-no-feedback-loop` is the same class of problem one level up — a gesture
and a player state writing the same value, where the fix is again "one owner at a time".

## Verifying it

```bash
# which Slider overloads your resolved artifact actually has, and which declare a range
jar=$(find "$HOME/.gradle/caches/modules-2" -name "material3-*.jar" | head -1)
javap -classpath "$jar" androidx.compose.material3.SliderKt | grep "void Slider"

# whether a declared range is forwarded: it should reach the SliderState constructor
javap -c -classpath "$jar" androidx.compose.material3.SliderKt | grep -B8 'SliderState."<init>"'

# every explicit range in app code — a media slider on a 0..100 range is the defect
grep -rn "valueRange" --include="*.kt" .

# every control that opted out of the touch-target floor: each one owes a hand-made target
grep -rln "LocalMinimumInteractiveComponentSize" --include="*.kt" .
```

`ClosedFloatingPointRange` in a signature means that overload accepts a range; an overload *without*
one has not dropped the feature — that is the `SliderState` overload, where the range moved into the
state object. Do not stop at the signature: the second command shows the customisable overload
loading its own range parameter into `SliderState.<init>`. Then, by hand: drag to the middle of a
long track and hold — the thumb must stay under the finger — and release near the end.
