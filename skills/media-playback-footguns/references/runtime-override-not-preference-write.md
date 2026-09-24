---
name: runtime-override-not-preference-write
description: Turn a user-facing feature off for the duration of a mode with a runtime override on the component, never by writing the stored preference — a process death mid-mode would leave the user's real setting permanently changed. Use when entering a mode has to disable an existing feature, when a setting mysteriously turned itself off and stayed off, or when a mode's cleanup is the only thing standing between a user and a lost preference.
---

# A mode is temporary; the stored setting is not

Entering some mode — a shared session, a call, a low-power state — often requires a feature to stop.
The one-line way to do that is to write the stored preference off and write it back on the way out.
Do not: the way out is not guaranteed to run. A crash, a task kill, a battery death, an unhandled
exception in the teardown — any of them leaves the user's real setting silently rewritten, with no
event they could connect it to.

Give the component a second, in-memory line instead, and let the two compose:

```kotlin
// adapted — names generalized
/**
 * Suppresses the feature without touching the user's setting.
 *
 * Overwriting the stored preference instead would lose the user's real choice if the process
 * died mid-mode.
 */
var featureSuppressed: Boolean
```

The mode sets it on the way in and clears it on the way out; the stored preference is never read or
written by the mode at all. This is the same principle as putting a programmatic fade on its own
gain line rather than on the user's volume — `audio-fade-separate-gain-line` is that case in full,
including why the restore must come from the component's own completion path.

## Traps

**The override has to be honoured at every place the feature can start, not at the one you found
first.** Features that run from a polling loop *and* from an end-of-item callback are the common
shape, and a condition added to only one path is dead code with no error and no log — the feature
simply keeps firing on the other path some of the time. `guard-on-every-trigger-path` is the whole
lesson; the census below is how you check.

**"It cannot crash there" is not an argument.** The preference-writing version is not wrong because
the teardown is buggy; it is wrong because the teardown is *optional* from the operating system's
point of view. Process death is not an error path you handle, it is a thing that happens.

**Compose, do not replace.** The check reads `enabled && !suppressed`. Writing the override into the
same field the preference feeds means the next preference read clobbers it, and the mode silently
stops suppressing anything from that moment on.

**Default the override to off in the field initialiser.** It is in-memory state, so it starts fresh
on every process — which is exactly the property you wanted. Persisting it "so the mode survives a
restart" reintroduces the original bug with extra steps.

**Clear it on *leaving*, driven by the same signal that set it.** One collector on the "am I in the
mode" flag, writing the override to match, is the whole lifecycle — and it self-corrects, because a
mode that ends for any reason at all emits the flag. Setting it at the entry call site and clearing
it at the exit call site is two places that must agree, and they eventually will not.

**One collector on the flag also covers "the mode was already on when we started".** A state stream
emits its current value to a new collector, so the same single collector that handles entering and
leaving also handles a bridge started while the mode is already active — which is otherwise a whole
extra initialisation path, and the one that gets forgotten because it only happens after a restart.

**Clear the mode's other carried state on the same signal.** A mode that suppresses a feature
usually also accumulates a little state of its own — a remembered intent, a last-seen id. Resetting
those in the same collector, on the same "left the mode" emission, keeps the lifecycle to one place;
scattering them across the exit call sites is how one of them survives into the next session.

**Apply it on the thread the component requires.** The mode flag usually arrives on a background
scope while the component is confined to a UI thread, so the write needs an explicit context switch.
This is the kind of line that looks like tidiness and is actually a crash.

**Two modes wanting the same suppression turn the boolean into a count.** A single flag means
whichever mode exits first re-enables the feature underneath the other one. As long as there is
exactly one mode a boolean is right and a counter is over-engineering — but note the constraint in
the field's comment, because the second mode arrives without warning and the failure it causes is a
feature that comes back on halfway through.

**Log both transitions.** "Why is this feature off?" is otherwise unanswerable from a log: the
setting says on, the feature does nothing, and the override is in-memory so nothing persists to
inspect. One line each way, naming the mode, turns a support thread into a grep.

**The override belongs on the component's own interface, next to the settings it modifies.** Putting
it on the mode's manager means every component needs to know the mode exists. Putting it on the
component means the mode needs to know only that a suppression line is available — and it documents
itself for the next feature that needs one.

**Say in one line why it is not the preference.** Without that comment, the next reader sees a
redundant boolean beside an existing setting and simplifies it away. That is the single most likely
future of this pattern.

## Verifying it

Find the override, its declaration, and every place it is honoured:

```bash
grep -rniE "\b[a-z][A-Za-z]*(Suppressed|Overridden|ForcedOff|TemporarilyDisabled)\b" \
  --include="*.kt" . | grep -v "/build/"
```

Expect one declaration on the component interface, one implementation per backend, one writer, and
**two or more** honouring sites per backend — one per backend is the trigger-path bug. Then confirm
the composition:

```bash
grep -rn -B3 -A3 -E "Suppressed" --include="*.kt" . | grep -v "/build/" \
  | grep -E "Enabled|enabled" | head
```

Every honouring site must read the enabled flag *and* the override in one condition — only the
override loses the user's setting, only the enabled flag loses the mode.

Finally, prove the mode never writes the stored preference. The pattern matches an assignment rather
than a declaration, because a typed declaration puts the type between the name and the `=`:

```bash
for f in $(grep -rlE "(Suppressed|Overridden|ForcedOff|TemporarilyDisabled) *=" --include="*.kt" . \
             | grep -v "/build/"); do
  echo "== $f"; grep -nE "dataStore|DataStore|preference|\.edit\(|put[A-Z][a-z]+\(" "$f" \
    || echo "   (no preference write)"
done
```

The writer file should show no preference write at all — a comment mentioning the word is fine, an
`edit`/`put` call on the store is the bug. Behaviourally: enter the mode, confirm the feature is
off, force-stop the process from outside the app, relaunch. The setting must read as the user left
it and the feature must work again immediately.
