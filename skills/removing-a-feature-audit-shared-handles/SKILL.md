---
name: removing-a-feature-audit-shared-handles
description: Delete a feature that duplicates a newer one — two effects on one output multiply — after auditing what else uses the handle the removed feature appeared to own, deleting the no-op stubs on the other platforms, and force-stopping before judging whether the removal worked, because an already-attached external effect outlives the change. Use when replacing a delegating integration with an in-app one, or when a removed feature still seems to be running.
---

# Removing a feature that shares a handle

When an in-app implementation replaces one that handed the work to something outside the process,
the old one has to go rather than merely being hidden. Two effects on one output **multiply**: a
user with both engaged gets the product of the two and blames whichever one they can see. Hiding
the entry point leaves the other one attached.

The delete itself is easy. The audit around it is the work, and it has three parts: what else uses
the handle, what the other platforms were doing with the same calls, and what is still attached
when you go to check.

## Traps

**The handle that looks like part of the removed feature usually is not.** An audio session
identifier exists on the interface *because* the old integration announced it — that is why it was
added — but by the time you remove that integration its real user is something else entirely
(volume normalisation attaches to the same session). Deleting it takes an unrelated feature with it,
and the compile error lands in a file nobody associates with the change. Find the real users before
deciding, and when you keep it, **name the real user in a comment on the declaration** — otherwise
the next removal pass makes exactly the same judgement call with exactly as little information.

**An external effect already attached outlives the removal.** Whatever was listening is bound to
the session, not to your code path, and it stays bound until the process ends. So the first run
after the change still behaves like the old build, which reads as "the removal didn't work" and
sends you looking for a call site that no longer exists. Force-stop the app before judging, every
time.

**The other platforms were firing into empty stubs, and those stubs are part of the feature.** A
cross-platform integration usually has one real implementation and N no-ops. Removing the real one
and leaving the no-op trio — the declaration, the platform actuals, the interface method they
satisfy — leaves a shape that reads as "supported here, unsupported there" for a feature that no
longer exists anywhere. Delete the whole trio in the same change.

**A settings row that outlives its action is worse than the feature was.** It is the one artefact
users can see, and it now either does nothing or throws. Grep the settings screen, the strings, and
the preference keys as part of the removal — the string resource in particular survives every
compiler check there is.

**"No references" is not the same as "not reachable".** Broadcast actions, intent filters, manifest
entries, reflection and DI module registrations are all reachable without a Kotlin reference. A
removal verified by the compiler alone leaves the manifest advertising a capability the app dropped.

**Migrate the stored preference, or leave it as litter.** The old feature's toggle is still in the
store, still `true` for existing users, and now reads to nobody. Decide explicitly: delete the key
on next launch, or leave it and record why. Silently orphaning it is what makes a later "why is
this key here?" unanswerable.

**Do not keep the removed path behind a flag "just in case".** The multiplication problem returns
the moment anyone turns it on, and a flag with no UI is a flag nobody tests. If the old integration
must survive for a release, keep it *visible* and make the two mutually exclusive.

## Verifying it

Removal is verified by absence, so make the absence a command with an expected count of zero — and
the retention a command with an expected count above zero:

```bash
# every name in the removed chain — call sites, listener callbacks, constants, stubs, settings row
for sym in notifyEffectIntent shouldOpenEffectSession openExternalEffect EFFECT_SESSION_ACTION; do
  printf '%-32s %s\n' "$sym" "$(grep -rn --include='*.kt' --include='*.xml' "$sym" . | wc -l)"
done            # every line must print 0

# the handle you deliberately KEPT, and its real user — both must be non-zero
grep -rn --include='*.kt' 'audioSessionId' . | wc -l
grep -rn --include='*.kt' 'LoudnessEnhancer' . | wc -l
```

Include `--include='*.xml'` and a pass over the manifest: a Kotlin-only grep reports a clean removal
while an intent filter still advertises the feature.

Then the runtime check, in this order, because the order is what makes it valid: force-stop the app,
relaunch, engage the new implementation, and confirm the response matches the new implementation
alone. Skipping the force-stop measures the previous process.
