---
name: sampled-supplier-vs-per-handle-reapply
description: Two playback backends need opposite plumbing for the same setting — one whose per-stream consumers sample a shared field needs no push at all, one whose every new handle starts blank needs an explicit re-apply at each creation site. Use when a setting reaches the current track but not the next one, when it survives on one platform and not the other, or when a level set on several handles keeps reverting.
---

# Sampled supplier, or re-apply per handle

A playback-wide setting — volume, speed, a fade factor, a filter curve — has to reach every player
object that is alive right now *and* every one created later. There are two backend shapes, and
they want opposite code.

**Sampling backend.** Each stream gets its own consumer, and every consumer closes over one shared
field. Correctness comes from the *factory*, not from any push:

```kotlin
@Volatile private var currentCurve: EqualizerCurve = EqualizerCurve.FLAT

private fun createPlayer(): Player {
    val equalizer = EqualizerAudioProcessor { currentCurve }   // sampled per buffer
    …
}

override fun setEqualizer(bands: List<Float>, preampDb: Float) {
    currentCurve = EqualizerCurve(bands, preampDb)             // that is the whole setter
}
```

**Handle-per-item backend.** A fresh handle starts at the engine's defaults — full volume, 1.0×
speed, empty filter chain — so anything in force has to be re-asserted on the handle, at every site
that creates one:

```kotlin
private fun Handle.applyPlaybackLevels() {
    setVolumeLevels(master = (volume * 100).toInt(), sleep = (fadeFactor * 100).toInt())
    setRate(speed)
    if (bands.isNotEmpty() || preamp != 0f) setEqualizer(bands, preamp)
}
```

## Traps

**The handle being promoted belongs to neither collection.** Enumerating live handles as "current +
precached" misses the incoming track of a crossfade: it is removed from the precached map *before*
it is installed as current, so for the length of the transition it is in no collection at all. It is
also the handle the user is about to hear. Write the enumerator once, name the third slot in it, and
never enumerate inline again:

```kotlin
private fun forEachLiveHandle(action: (Handle) -> Unit) {
    currentHandle?.let(action)
    secondaryHandle?.let(action)          // the easy one to miss
    precached.values.forEach { action(it.handle) }
}
```

**Where a level is process-wide, a missed handle does not stay wrong — it undoes the others.** Some
engines expose "device volume" as one shared session rather than one per handle. A handle left
holding an older level re-asserts it on its own device-reconfigure event and overwrites everyone
else's. So the failure is not "one player is quiet", it is "the whole app randomly reverts", with no
correlation to the handle you forgot.

**Set the levels that interact in one call.** Two levels that multiply into one output — a user
volume and a fade attenuation — must go down together. Setting them separately publishes a
full-volume master onto a shared line for the instant before the fade lands, and on a shared line
every other handle hears it.

**Creation sites outnumber the ones you remember.** Count them before believing you covered them —
then confirm the pairing with the check under *Verifying it*, which is the one that discriminates:

```bash
# substitute your own two names; the second number must never exceed the first. Excluding the
# declaration is what makes that invariant true — counted with it, the push side is inflated by
# one and the comparison passes with exactly one creation site left uncovered.
grep -rn --include='*.kt' 'applyPlaybackLevels()' . \
  | grep -v 'fun .*applyPlaybackLevels' | wc -l                      # push sites
grep -rn --include='*.kt' 'Handle.create(\|createPlayer(' . | wc -l  # creation sites
```

Initial load, next-track preparation, crossfade promotion, a settings change while paused, and
precache are five different call sites in practice, and precache is the one that produces "the
setting works until you skip".

**On the sampling backend, resist adding a push "to be safe".** It cannot help — the consumers
already read the live field — and it costs you the property that makes the design work: that a
player created by any path is correct without anything having to find it. A push there is dead code
that will later be *trusted*, and someone will add a creation path that skips it.

**A remote sink is not a handle you push to.** When playback is handed to another device the audio
is decoded there and never passes through the local chain, so forwarding the setting is at best a
no-op and at worst a wrong claim. Skip it deliberately, and make the UI say so — greying the
control out is the honest signal that the setting has nowhere to go.

**The push must hop to the thread that owns the handle.** Property writes from the caller's thread
race the release path: a handle can pass its liveness check and then be destroyed before the write
lands. Post the whole `forEachLiveHandle` block onto the handle-owning thread rather than each
individual write, or you have merely narrowed the window.

**Guard the re-apply on "is there anything to apply".** `if (bands.isNotEmpty() || preamp != 0f)`
skips installing a neutral stage on every single handle for the majority of users who never touched
the setting — and on an engine that rebuilds its whole graph per write, that is a real cost at
every track change.

## Verifying it

Both failures are "the next one is wrong", so verify across a transition rather than in place. Start
here rather than with the two counts above — this one pairs each creation with its re-apply, so an
uncovered site shows up as a shortfall instead of hiding inside a matching total:

```bash
# no creation path may bypass the re-apply — this count must equal the creation-site count
grep -rn --include='*.kt' -A6 'Handle.create(' . | grep -c 'applyPlaybackLevels'
```

Then, at runtime: change the setting **during** a crossfade, let it complete, and assert the value
on the promoted handle. Changing it while a single track plays passes on a version that only ever
touches `currentHandle`. On the sampling backend, assert the opposite — that the setter touches no
player object at all — by asserting a player created *after* the write already reports the setting.
