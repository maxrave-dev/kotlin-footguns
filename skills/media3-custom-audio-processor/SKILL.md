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

The four members that matter: `onConfigure` (negotiate the format), `isActive` (am I in the chain at
all), `queueInput` (do the work), `onFlush` / `onReset` (drop state). Build the chain inside a
`DefaultRenderersFactory` subclass's `buildAudioSink` override (the member is `protected` there) so
the instances are created **per player** — as soon as more than one is alive (a crossfade, a preroll,
a precache) that matters, because a processor carries per-stream state and cannot be shared.

## Traps

**`isActive()` is asked when the chain is built, not per buffer** — so a parameter you flip at
runtime must **not** ride it. A processor answering `false` while "disabled" is left out of the
chain and is not consulted again until the next configure or flush, which from outside looks like
"the feature works, but only from the next track on". Stay active and branch inside `queueInput`:

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
already answers it from the format `onConfigure` just returned:

```
public boolean isActive();               // BaseAudioProcessor, decompiled
   0: aload_0
   1: getfield  pendingOutputAudioFormat
   4: getstatic AudioProcessor$AudioFormat.NOT_SET
   7: if_acmpeq …                        // active ⇔ pendingOutputAudioFormat !== NOT_SET
```

`configure()` is `final`: it assigns `pendingOutputAudioFormat = onConfigure(format)` and *then*
asks `isActive()`. The default therefore already means "active iff I accepted the format" — active
for the whole stream once accepted, correctly absent for one you decline — which is exactly what a
runtime-toggled processor wants, for free. Forcing `true` claims membership while handing back a
format you cannot read, and `AudioProcessingPipeline` catches you at configure time:

```java
AudioFormat out = p.configure(f);
if (p.isActive()) { Preconditions.checkState(!out.equals(NOT_SET)); f = out; }
```

That is an `IllegalStateException` on the first stream in an encoding you decline — latent for as
long as everything happens to be PCM 16-bit, which is why forced overrides survive in codebases.
Activity is about the *format*, never about the setting: a neutral curve, a fade at 1.0 or a filter
at pass-through all stay active and take the bulk-copy path below.

**Trust the code over the comment on this one.** It is common to find a KDoc promising "when
disabled, `isActive` returns false and the pipeline skips this processor entirely" sitting directly
above `override fun isActive(): Boolean = true`. Both are wrong — read the override, then delete it.

**Always consume the whole input buffer.** Leaving even one byte behind makes the pipeline offer the
same buffer again, forever, having made no progress — silence with no error, no exception and no log
line. A `while (remaining() >= 2)` loop over 16-bit samples is fine only because PCM16 frames are an
even number of bytes; add the drain anyway, because it is the difference between a wedge and a click:

```kotlin
while (inputBuffer.remaining() >= 2) { output.putShort(…) }
while (inputBuffer.hasRemaining()) { output.put(inputBuffer.get()) }  // never fires; keeps the contract
```

To verify: assert `inputBuffer.remaining() == 0` at the end of `queueInput` in a debug build.

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

**One instance per player; share the *parameter*, not the processor.** The state that forbids
sharing is the negotiated format and the output buffer, not your logic. Give each player its own
processor and let them all read one field:

```kotlin
@Volatile private var fadeFactor = 1.0f              // written once, anywhere
val sleepFade = SleepFadeAudioProcessor { fadeFactor } // per player, same source
```

Passing a `() -> Float` rather than a value is the whole point: a single write covers both players
of a transition without either knowing the other exists.

**Read the parameter fresh on every buffer.** Capturing it in `onConfigure` or at stream start is the
same failure as the `isActive` one, one layer down: a fade that begins — or keeps advancing — in the
middle of an already-configured stream never reaches the output.

**The pass-through branch runs for the entire life of the app.** Its "nothing to do" path executes on
every buffer of every track whether the feature is in use or not. Make it a bulk
`output.put(inputBuffer)`, never a per-byte loop.

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

**`onFlush` and `onReset` are not the same event.** Flush happens on every seek and format change —
and it is the other point where the pipeline rebuilds its active list from `isActive()` — so clear
the *history* (filter delay lines) there, and nothing else. Reset happens at teardown: restore
defaults too. Clearing user-facing parameters in `onFlush` makes settings reset themselves on seek.

**Byte order is not free.** Call `inputBuffer.order(ByteOrder.nativeOrder())` before reading
shorts. `ByteBuffer` defaults to big-endian; PCM in the pipeline is native-endian. Getting it wrong
sounds like loud noise, not like a subtle bug — which is the one merciful thing about it.
