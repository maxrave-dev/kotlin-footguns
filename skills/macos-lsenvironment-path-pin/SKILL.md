---
name: macos-lsenvironment-path-pin
description: Declaring a Launch Services environment dictionary (`LSEnvironment`) in a packaged macOS app's property list pins the process `PATH` to the four bare system directories, so every external process the app spawns loses everything installed elsewhere. Use before adding any environment variable to a macOS app bundle, when a helper the app shells out to reports "command not found" only for installed users, or when a feature that works from a terminal launch silently does nothing from the Dock.
---

# The environment dictionary pins `PATH`

A packaged macOS app can carry environment variables in its property list under `LSEnvironment` —
the **Launch Services** environment dictionary. It is the normal way to set an allocator flag, a
runtime toggle or a debug switch for a shipped app.

It has one side effect that is easy to miss and expensive to find:

> **Declaring the dictionary at all pins the process `PATH` to `/usr/bin:/bin:/usr/sbin:/sbin`.**

Not any particular key — the presence of the dictionary. Anything the app then starts as an
external process sees only those four directories. Tools installed by a package manager, in the
user's home, or anywhere under `/usr/local` are simply not found.

Two properties of the dictionary decide when it applies:

- It is applied by **Launch Services**, so it covers file-manager, Dock, Spotlight and `open`
  launches — every normal launch of an installed app.
- It is **not** applied when you run `Contents/MacOS/<binary>` directly from a shell. That
  invocation inherits your shell environment instead.

Which means: **you cannot reproduce this from a terminal.** The way you test a desktop app during
development is precisely the launch path that does not have the pin.

```hocon
# adapted — packaging config, macOS section
mac {
  # Declaring this dict pins PATH to /usr/bin:/bin:/usr/sbin:/sbin.
  # Audited before adding — see the note in the audit section below.
  info-plist.LSEnvironment.<KEY> = "<value>"
}
```

## Traps

**The audit is a precondition, not a follow-up.** Before adding the key, find every external
process the app can start on the macOS path and record, for each, why it is safe. That note is
the artefact — it is what stops the next person redoing the audit, and what tells them when the
answer has changed.

**Platform-gated spawns still belong in the audit.** In the case above the only spawn on the
macOS code path was a probe gated to another OS, so the answer was "unreachable here". Write that
down rather than leaving the call site unexplained; a later change that removes the gate is
otherwise invisible.

**Some platform APIs never consult `PATH`, and flagging them wastes the audit.** Opening a URL or
a file through the desktop-integration API goes through Launch Services, which resolves the
handler without `PATH`. Those hits are false positives — but only if you have confirmed the call
really goes through that API and not through a spawned launcher command as a fallback. A
per-OS fallback chain that shells out is exactly the kind of code that gets added later.

**The symptom does not name `PATH`.** It arrives as "command not found" from a helper, a feature
that quietly does nothing, or a launch that fails only for users who installed the app normally.
If the spawn failure is swallowed — a `runCatching` with no log — there is no symptom at all,
just a dead feature.

**Removing the key is the wrong rollback if you still want its effect.** Dropping the dictionary
restores normal `PATH` inheritance and loses whatever you added it for. Prefer adding `PATH`
explicitly to the same dictionary, with the directories your helpers actually live in appended to
the four bare ones.

**Absolute paths are the durable fix.** For anything you ship or can locate deterministically,
spawn it by absolute path or pass an explicit environment to the process builder, so the app does
not depend on `PATH` at all. Then the pin costs nothing.

**This is macOS-specific.** The Windows and Linux packaging paths have their own environment
mechanisms with their own rules; do not carry this conclusion across.

## Verifying it

1. **Find every spawn site** and record a verdict for each:

   ```bash
   grep -rn "ProcessBuilder\|Runtime.getRuntime().exec\|exec(" \
     --include='*.kt' --include='*.java' <src>
   ```

2. **Resolve each command on a clean machine** — `command -v <tool>` — and check the answer is
   inside `/usr/bin`, `/bin`, `/usr/sbin` or `/sbin`. Anything else will not be found once the
   dictionary is declared.

3. **Confirm the key reached the packaged app.** Read the property list out of the built bundle
   rather than trusting the packaging config; a key written at the wrong nesting level is
   accepted silently by many config formats and never appears in the output.

4. **Test from the file manager, not the terminal.** Launch the installed app the way a user
   would, then print the running process's environment (`ps eww -p <pid>`) and confirm both that
   your variable is present and what `PATH` became.

5. **Re-run step 1 whenever a feature adds an external process**, and keep the audit note beside
   the config key so the connection is discoverable from either end.
