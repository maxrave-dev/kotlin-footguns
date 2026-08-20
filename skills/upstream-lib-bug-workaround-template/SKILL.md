---
name: upstream-lib-bug-workaround-template
description: The shape a workaround should take when the bug is in a library you cannot patch — trace the mechanism as far as you actually got, name the tradeoffs you accepted, leave an escape hatch so a failure degrades instead of going silent, write the explicit condition for removing it, and record why your usage pattern exposes a bug the library's own users never hit. Use when you are about to pin a setting, avoid a code path or add a defensive branch because of someone else's bug, or when reviewing a workaround whose comment does not say when it may be deleted.
---

# Writing a workaround you can delete later

A workaround is a debt with no due date unless you write one. Five parts, all of them in the
comment next to the code:

1. **The mechanism, as far as you traced it.** Where you stopped is part of the finding. Correct
   advice justified by a wrong "why" is an error, not a rounding error — the next person acts on
   the "why".
2. **The tradeoffs you accepted**, named individually. Anything you knowingly gave up.
3. **An escape hatch**, so that if the workaround itself fails the behaviour degrades instead of
   going silent.
4. **The removal condition**, phrased as something an outsider could check: *remove once upstream
   does X.*
5. **Why your usage exposes it.** Almost always the reason upstream cannot reproduce it.

## Worked example

**Symptom.** On one OS only, the app stops at an unpredictable moment — often an hour into a
session, reliably reproduced by plugging in or unplugging headphones. Nothing was being torn down
at that moment, which is what ruled out a teardown race and pointed much further back in the
session.

**Mechanism, traced in the library's source.** Initialising an audio output registers a
process-wide device-change listener that points back at the audio object being initialised. The
error path of that init returns without unregistering it. The caller then abandons the object —
and the teardown that *would* unregister the listener only runs when a flag is present that the
caller sets after a **successful** init. So a failed init leaves a listener aimed at an object
that has since been released, and it outlives that object for the rest of the process. The next
device change calls into the listener, which reads the released object: a hard native stop, at a
time entirely unrelated to the failure that caused it.

**Why this app and not the library's own tools.** The library's standalone use creates one audio
output per session. This app creates one per media item, and runs two at once during a
transition — so one failed audio init anywhere in a session arms the fault, and it then waits for
an unrelated device change. That difference is the whole reason it never appeared upstream, and
it is the sentence a bug report needs most.

**Fix.** Pin the audio backend to a different one that registers no such listeners at all:

```kotlin
// adapted
if (Platform.isMac()) {
    // Trailing comma: keeps the library's normal auto-probe as a fallback, so a failure
    // here degrades to different audio rather than to silence.
    option("ao", "avfoundation,")
}
```

**Tradeoffs, both filed upstream and both accepted:** a delayed mute, and audio drifting out of
sync when playback speed changes. Neither reproduced on the current OS release.

**Removal condition:** remove the whole branch once upstream unregisters the listener on the
error path.

## Traps

**A workaround with no removal condition becomes permanent.** Years later it reads as a
deliberate design choice and nobody dares touch it. A branch that says "hidden because library X
does not support this" outlives the migration off library X by default — the check is a search
for the *justification*, not for the code.

**The escape hatch is not a retry.** The point is that when the workaround's own assumption
fails, the feature reaches a working alternative instead of nothing. A trailing separator that
re-enables auto-probe, a fallback chain, a default value — cheap, and it converts "silently
broken" into "slightly worse".

**Distinguish "not present" from "failed".** A setting that genuinely does not exist in some
builds of the library must be treated as success, not warned about on every object you create:

```kotlin
// adapted
val rc = lib.set_option(ctx, name, value)
if (rc == ERROR_OPTION_NOT_FOUND) {
    Logger.d(TAG, "option '$name' absent in this build — already off, nothing to do")
} else if (rc < 0) {
    Logger.w(TAG, "set_option($name=$value) failed: ${lib.error_string(rc)}")
}
```

Collapsing both into one warning trains everyone to ignore the line, which is how the real
failure gets missed.

**Do not infer the mechanism from the symptom.** The symptom here pointed at teardown; the cause
was an init that had failed much earlier. Read the library's source for the error path, not just
the happy path — the bug lives in the branch nobody looks at.

**If the library has a log channel, subscribe to it.** Nothing in this app ever requested the
library's own log messages, so its warnings — including the failed audio init that arms the whole
problem — surfaced nowhere at all. That blind spot is a bigger finding than the workaround
itself.

**Check upstream's current state before writing the comment.** "Still present in the library's
main branch as of version N" ages into a checkable claim; "known bug" does not.

**Keep the workaround at the narrowest scope that fixes it.** One platform branch, one option,
one call site. A workaround that changes behaviour on platforms that never had the bug is a new
bug with a good excuse.

## Verifying it

1. **Reproduce the trigger deliberately**, not the crash. Here that is a device change while the
   app runs — not waiting an hour.
2. **Verify the mechanism, not the disappearance of the symptom.** A timing-dependent fault stops
   reproducing for many reasons. Confirm the specific behaviour you claimed: the listener is no
   longer registered, the option was accepted, the path is not taken.
3. **Confirm the escape hatch works** by breaking the workaround on purpose — set the option to
   something invalid and check you get degraded behaviour plus a log line, not a dead feature.
4. **Re-read the removal condition at every dependency bump.**
   `grep -rn "remove once\|revert when\|upstream" --include='*.kt' <src>` should return a short,
   readable list. If it does not, the comments are not written in a form anyone can act on.
