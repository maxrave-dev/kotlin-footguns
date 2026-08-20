---
name: media3-custom-audio-processor
description: Write a custom audio processor for a Media3/ExoPlayer audio pipeline — a filter, a fade, a gain stage — that is toggled at runtime and shared across several concurrent players. Use when a processor you added does nothing until the next track, when playback wedges with no error, when `put(ByteBuffer)` throws on your own output buffer, or when two simultaneous players need one parameter to reach both.
---

# Custom audio processors in a Media3 pipeline

A processor is a `BaseAudioProcessor` subclass installed in the sink's processor chain:

```kotlin
DefaultAudioSink.Builder(context)
    .setAudioProcessorChain(
        DefaultAudioSink.DefaultAudioProcessorChain(
            arrayOf(myFilter, myGain),   // yours, in order
            SilenceSkippingAudioProcessor(...),
            SonicAudioProcessor(),
        ),
    ).build()
```

The four members that matter: `onConfigure` (negotiate the format), `isActive` (am I in the
chain at all), `queueInput` (do the work), `onFlush` / `onReset` (drop state).

Build the chain inside a `DefaultRenderersFactory` subclass's `buildAudioSink` override (the
member is `protected` there) so the instances are created **per player**. That matters as soon as more than one player is alive — a crossfade, a preroll, a
precache — because a processor carries per-stream state and cannot be shared.

## Traps

**`isActive()` is asked when the chain is built, not per buffer.** A processor that answers `false`
is left out of the chain and is not consulted again until the next configure or flush. So a
parameter you flip at runtime — a fade that starts mid-track, a filter you enable when a transition
begins — must **not** ride `isActive`. Return `true` permanently and branch inside `queueInput`:

```kotlin
override fun isActive(): Boolean = true

override fun queueInput(inputBuffer: ByteBuffer) {
    val remaining = inputBuffer.remaining()
    if (remaining == 0) return
    val output = replaceOutputBuffer(remaining)
    if (!enabled) { output.put(inputBuffer); output.flip(); return }  // alias-safe? see the put() trap below
    …
}
```

From outside, getting this wrong looks like "the feature works, but only from the next track on".
Reserve a `false` answer for things fixed for the whole stream — an unsupported channel count, a
format you decline.

**Trust the code over the comment on this one.** It is common to find a KDoc block promising
"when disabled, `isActive` returns false and the pipeline skips this processor entirely" sitting
directly above `override fun isActive(): Boolean = true`. The comment describes a first draft; the
override is what shipped. Read the override.

**Always consume the whole input buffer.** Leaving even one byte behind makes the pipeline offer
the same buffer again, forever, having made no progress — silence with no error, no exception and
no log line. A `while (remaining() >= 2)` loop over 16-bit samples is fine only because PCM16
frames are an even number of bytes; add the drain anyway, because it costs nothing and it is the
difference between a wedge and a click:

```kotlin
while (inputBuffer.remaining() >= 2) { output.putShort(…) }
while (inputBuffer.hasRemaining()) { output.put(inputBuffer.get()) }  // never fires; keeps the contract
```

To verify: assert `inputBuffer.remaining() == 0` at the end of `queueInput` in a debug build.

**`ByteBuffer.put(ByteBuffer)` throws when source and destination are the same object.**
`replaceOutputBuffer()` normally hands back this processor's own buffer while the input belongs to
the previous stage, so they are distinct — but a chain where your processor is first, or a pipeline
that hands buffers through unchanged, can alias them. Either prove they cannot alias in your chain
or guard the copy:

```kotlin
private fun copyBuffer(src: ByteBuffer, dst: ByteBuffer, size: Int) {
    if (src === dst) { dst.position(0); dst.limit(size); return }
    val pos = src.position()
    for (i in 0 until size) dst.put(src.get(pos + i))
    src.position(pos + size)
}
```

**One instance per player; share the *parameter*, not the processor.** The state that forbids
sharing is the negotiated format and the output buffer, not your logic. Give each player its own
processor and let them all read one field:

```kotlin
@Volatile private var fadeFactor = 1.0f              // written once, anywhere
val sleepFade = SleepFadeAudioProcessor { fadeFactor } // per player, same source
```

Passing a `() -> Float` rather than a value is the whole point: a single write covers both players
of a transition without either knowing the other exists.

**Read the parameter fresh on every buffer.** Capturing it in `onConfigure` or at stream start is
the same failure as the `isActive` one, one layer down: a fade that begins — or keeps advancing —
in the middle of an already-configured stream never reaches the output.

**The pass-through branch runs for the entire life of the app.** If your processor is permanently
active, its "nothing to do" path executes on every buffer of every track whether the feature is in
use or not. Make it a bulk `output.put(inputBuffer)`, never a per-byte loop.

**Decline formats in `onConfigure`, and re-derive everything from it.** Return
`AudioProcessor.AudioFormat.NOT_SET` for encodings you do not handle, and cache `sampleRate` /
`channelCount` there — coefficients computed against last stream's sample rate are silently wrong,
not obviously broken:

```kotlin
override fun onConfigure(f: AudioProcessor.AudioFormat): AudioProcessor.AudioFormat {
    if (f.encoding != C.ENCODING_PCM_16BIT) return AudioProcessor.AudioFormat.NOT_SET
    sampleRate = f.sampleRate; channelCount = f.channelCount
    coefficientsDirty = true
    return f
}
```

**`onFlush` and `onReset` are not the same event.** Flush happens on every seek and format change:
clear the *history* (filter delay lines) so the previous stream does not bleed in. Reset happens
when the processor is torn down: restore defaults as well. Clearing user-facing parameters in
`onFlush` makes settings appear to reset themselves on every seek.

**Byte order is not free.** Call `inputBuffer.order(ByteOrder.nativeOrder())` before reading
shorts. `ByteBuffer` defaults to big-endian; PCM in the pipeline is native-endian. Getting it wrong
sounds like loud noise, not like a subtle bug — which is the one merciful thing about it.
