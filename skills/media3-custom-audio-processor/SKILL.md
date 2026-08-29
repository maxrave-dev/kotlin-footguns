---
name: media3-custom-audio-processor
description: Write a custom audio processor for a Media3/ExoPlayer audio pipeline — a filter, a fade, a gain stage — that is toggled at runtime and shared across several concurrent players. Use when a processor you added does nothing until the next track, when playback wedges with no error, when `put(ByteBuffer)` throws on your own output buffer, or when two simultaneous players need one parameter to reach both.
---

# Custom audio processors in a Media3 pipeline

A processor is a `BaseAudioProcessor` subclass installed in the sink's processor chain:

```kotlin
DefaultAudioSink.Builder(context).setAudioProcessorChain(
    DefaultAudioSink.DefaultAudioProcessorChain(
        arrayOf(myFilter, myGain),   // yours, in order
        SilenceSkippingAudioProcessor(...), SonicAudioProcessor(),
    ),
).build()
```

Four members matter: `onConfigure` (negotiate the format), `isActive` (in the chain or not),
`queueInput` (do the work), `onFlush`/`onReset` (drop state). Build the chain inside a
`DefaultRenderersFactory` subclass's `buildAudioSink` override (`protected` there), so instances are
created **per player** — once more than one is alive (a crossfade, a preroll, a precache), it matters,
because a processor carries per-stream state and cannot be shared.

## Traps

**`isActive()` is asked when the chain is built, not per buffer** — a parameter you flip at runtime
must **not** ride it. A processor answering `false` while "disabled" is dropped from the chain until
the next configure or flush — from outside, "works, but only from the next track on." Stay active
and branch inside `queueInput`:

```kotlin
override fun queueInput(inputBuffer: ByteBuffer) {
    val remaining = inputBuffer.remaining()
    if (remaining == 0) return
    val output = replaceOutputBuffer(remaining)
    if (!enabled) { output.put(inputBuffer); output.flip(); return }  // alias-safe? see the put() trap below
    …
}
```

**Do not get that by overriding `isActive()` to `true` — do not override it at all.** The base class
already answers it from the format `onConfigure` just returned (confirmed by decompiling it, below).

`configure()` is `final`: it sets `pendingOutputAudioFormat = onConfigure(format)`, *then* asks
`isActive()`. The default already means "active iff I accepted the format" — exactly what a
runtime-toggled processor wants, for free. Forcing `true` claims membership while handing back a
format you cannot read, and `AudioProcessingPipeline` catches it at configure time:

```java
AudioFormat out = p.configure(f);
if (p.isActive()) { Preconditions.checkState(!out.equals(NOT_SET)); f = out; }
```

That throws `IllegalStateException` in an encoding you decline — latent until then, which is why
forced overrides survive. Activity is about the *format*, not the setting: a neutral curve or
pass-through filter stays active and takes the bulk-copy path below.

**Trust the code over the comment on this one.** It is common to find a KDoc promising "when
disabled, `isActive` returns false and the pipeline skips this processor entirely" sitting directly
above `override fun isActive(): Boolean = true`. Both are wrong — read the override, then delete it.

**Always consume the whole input buffer.** Leaving even one byte behind makes the pipeline offer the
same buffer again forever, having made no progress — silence with no error or log line. A
`while (remaining() >= 2)` loop is fine only because PCM16 frames are an even byte count; add the
drain anyway, because it is the difference between a wedge and a click:

```kotlin
while (inputBuffer.remaining() >= 2) { output.putShort(…) }
while (inputBuffer.hasRemaining()) { output.put(inputBuffer.get()) }  // never fires; keeps the contract
```
To verify: assert `inputBuffer.remaining() == 0` at the end of `queueInput`, in a debug build.

**`ByteBuffer.put(ByteBuffer)` throws when source and destination are the same object.**
`replaceOutputBuffer()` normally hands back this processor's own buffer while the input belongs to
the previous stage, so they are distinct — but a chain where your processor is first, or one that
hands buffers through unchanged, can alias them. Prove they cannot, or guard the copy:

```kotlin
private fun copyBuffer(src: ByteBuffer, dst: ByteBuffer, size: Int) {
    if (src === dst) { dst.position(0); dst.limit(size); return }
    val pos = src.position()
    for (i in 0 until size) dst.put(src.get(pos + i))
    src.position(pos + size)
}
```

**One instance per player; share the *parameter*, not the processor.** The state that forbids sharing is
the format and output buffer, not your logic — give each player its own processor, all reading one field:

```kotlin
@Volatile private var fadeFactor = 1.0f              // written once, anywhere
val sleepFade = SleepFadeAudioProcessor { fadeFactor } // per player, same source
```

Passing a `() -> Float` rather than a value is the point: one write covers both transition players.

**Read the parameter fresh on every buffer.** Capturing it in `onConfigure` or at stream start repeats the
`isActive` failure one layer down: a fade that starts, or keeps advancing, mid-stream never reaches the output.

**The pass-through branch runs for the entire life of the app.** Its "nothing to do" path executes on
every buffer of every track whether the feature is in use or not. Make it a bulk
`output.put(inputBuffer)`, never a per-byte loop.

**Decline formats in `onConfigure`, and re-derive everything from it.** Return `NOT_SET` for
encodings you don't handle, and cache `sampleRate`/`channelCount` there — coefficients built from
the last stream's rate are silently wrong, not obviously broken:

```kotlin
override fun onConfigure(f: AudioProcessor.AudioFormat): AudioProcessor.AudioFormat {
    if (f.encoding != C.ENCODING_PCM_16BIT) return AudioProcessor.AudioFormat.NOT_SET
    sampleRate = f.sampleRate; channelCount = f.channelCount
    coefficientsDirty = true
    return f
}
```

**`onFlush` and `onReset` are not the same event.** Flush fires on every seek and format change, and
is the other point where the pipeline rebuilds its active list from `isActive()` — clear only the
*history* (filter delay lines) there. Reset fires at teardown: restore defaults too. Clearing
user-facing parameters in `onFlush` makes settings reset themselves on seek.

**Byte order is not free.** Call `inputBuffer.order(ByteOrder.nativeOrder())` before reading
shorts. `ByteBuffer` defaults to big-endian; PCM in the pipeline is native-endian. Getting it wrong
sounds like loud noise, not like a subtle bug — which is the one merciful thing about it.

## Verifying it

1. **`isActive()`'s default reads the format, not a hardcoded value — decompile it yourself:**

   ```bash
   JAR=$(find ~/.gradle/caches -name "media3-common-1.11.0-runtime.jar" | head -1)  # AAR→jar transform cache
   [ -z "$JAR" ] && { JAR=/tmp/media3-common.jar; unzip -p "$(find ~/.gradle/caches/modules-2 -name 'media3-common-1.11.0.aar' | head -1)" classes.jar > "$JAR"; }
   javap -c -p -classpath "$JAR" androidx.media3.common.audio.BaseAudioProcessor | grep -A6 isActive
   ```

   Pass condition: `if_acmpeq` compares `pendingOutputAudioFormat` against `NOT_SET` — no flag read.

2. **By hand:** flip a runtime toggle mid-track. Correct: audible within the current track, not
   only from the next one — otherwise a parameter or `isActive()` is read once, not per buffer.
