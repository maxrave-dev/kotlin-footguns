---
name: compose-desktop-runtime-hardening
description: The ordered list of probes, system properties and platform gates a Compose desktop entry point must run before its first window exists. Covers warming the JDK's desktop-integration API ahead of any native load, renderer and interop properties that are read once at start-up, turning off vsync where the wait can park the UI thread, gating transparency and a custom titlebar on virtual-machine detection, and setting the Linux window-class name reflectively so the desktop entry binds. Use when the UI freezes while audio keeps playing after moving the window to another monitor, when the window never appears in a virtual machine, or when the Linux dock shows a class name instead of your app.
---

# The desktop entry point is an ordered list

Desktop. Most of what follows is only correct *because* of where it sits — treat the entry
function as a sequence, not a bag of setup calls.

```kotlin
// adapted — order is load-bearing top to bottom
fun main(args: Array<String>) {
    forceLinuxWmClass()      // 5. the launcher's first statement — it builds the toolkit itself
    runDesktopApp(args)
}

fun runDesktopApp(args: Array<String>) {
    CrashDialog.install()                    // 1. catch everything from here on

    java.awt.Desktop.isDesktopSupported()    // 2. probe BEFORE any native loads

    System.setProperty("compose.swing.render.on.graphics", "true")   // 3. read once
    System.setProperty("compose.interop.blending", "true")
    System.setProperty("compose.layers.type", "COMPONENT")
    if (!isWindows) System.setProperty("skiko.vsync.enabled", "false")

    …                                        // then the guard, the container, the window (§4)
}
```

The numbers are the sections below; §5 is numbered last but *runs* first, from the launcher module.

## 1. Install the crash handler first

First statement, so everything below is covered — including the failures this file is about, which
all happen before there is a UI to report them. The handler, its dialog and the build-time swap
behind its reporting call are their own subject: `swappable-crash-reporting-and-dialog`.

## 2. Probe the desktop-integration API before any native load

`java.awt.Desktop` caches whether it is supported on the first call. If a bundled native library
has already claimed a shared-object name the JDK's backing implementation also needs, that call
fails and the JDK reports the *entire* desktop API unsupported for the life of the process — every
"open link" breaks at once. Probing at the top, while only system libraries are mapped, pins it.

This is a workaround; the cure lives in the native bundle. The mechanism, the cure and how to tell
which copy actually loaded are in `bundled-native-soname-conflict` — write that removal condition
beside the probe.

## 3. Renderer properties are read once

Treat every `compose.*` / renderer property as read at rendering start-up: set them at the top of
the entry function, because a value written after the first window exists changes nothing and
fails as "the flag did nothing" rather than as an error.

**Vsync off on the platforms where the wait has no timeout.** The entry point's comment records
the mechanism: frame pacing waits on a display-provided signal, and when the display arrangement
changes — the window dragged to another monitor, a monitor unplugged — that wait can stop being
signalled and the UI thread parks indefinitely. The user sees a frozen window while audio keeps
playing, which reads as a hang and is not; with vsync off the renderer paces frames itself.
**Scoped** to everything *except* Windows, which the same comment records as rendering through a
different path and showing no such freeze — a check that names what it means, as does §5's.

## 4. Virtual-machine gate on transparency and the custom titlebar

The entry point's comment records this one too: a transparent, undecorated window does not render
on typical virtual-machine (VM) graphics drivers — the process runs, the window never appears.
Detect the environment once and fall back to an ordinary decorated window, gating the whole
treatment together:

```kotlin
// adapted — one flag, four decisions
Window(undecorated = !isVM, transparent = !isVM, …) {
    Column(Modifier.fillMaxSize().then(if (!isVM) Modifier.clip(RoundedCornerShape(12.dp)) else Modifier)) {
        if (!isVM) CustomTitleBar(…)
        App()
    }
}
```

The detection is computed once and remembered, because it shells out to a system query. What that
query must be — and why the obvious command-line tool no longer exists on current Windows, which
made every VM look like bare metal — is `windows-vm-detection-post-wmic`. Keep a manual override
property alongside it so a user on an undetected hypervisor can force the fallback.

**Check what the probe actually covers.** The one mined here returns false on every non-Windows
platform *before* querying anything, so a Linux or macOS guest still gets the transparent window
— a deliberate scope the flag's name does not admit to. Widen it, or rename the flag.

## 5. The Linux window-class name, set reflectively

The shell binds a launcher icon to a window by its class name. The JDK derives that from a field
on its X11 toolkit, read lazily at the first window, and exposes no property to set it — so with a
native launcher the dock shows whichever internal thread first touched the toolkit, not your app.

```kotlin
private fun forceLinuxWmClass(appName: String = APP_NAME) {   // adapted
    if (!isLinux) return
    runCatching {
        val toolkit = Toolkit.getDefaultToolkit()
        // Only the X11 toolkit exposes this field; skip the Wayland toolkit and headless.
        if (toolkit.javaClass.name != "sun.awt.X11.XToolkit") return
        toolkit.javaClass.getDeclaredField("awtAppClassName").apply {
            isAccessible = true
            set(null, appName)
        }
    }.onFailure { System.err.println("window-class override failed: ${it.message}") }
}
```

Three conditions, all necessary: **after** the toolkit is constructed (so the value is used
verbatim), **before** the first window, and the packaging must pass the module-open flag or the
access is denied. The function gets the first for free by constructing the toolkit itself on its
own first line — which is what lets it be the launcher's opening statement. The value must equal
the class name in the generated desktop entry, or the shell has two identities and binds neither.

## Traps

**Every item here fails silently.** A property set too late, a probe run too late, a reflective
field access denied — none throws where you can see it. Each needs its own log line; "the app
started" is not evidence. And a guarded reflective hack must degrade rather than crash: a wrong
dock label is not worth a failed launch.

**The visual fallback is a set, not a switch.** Keep the custom titlebar while falling back to a
decorated window and you get two title bars.

## Verifying it

1. **Test the packaged app**, not a plain Gradle run — launcher, thread ownership and module flags
   all differ, and this whole file is about start-up ordering.
2. **Move the window between monitors, and unplug one**, then interact with the UI. A frozen
   window with audio still playing is the vsync symptom.
3. **Run once in a virtual machine.** An invisible window with a healthy process is the
   transparency symptom.
4. **On Linux, read the window's class name from the shell** and compare it to the desktop
   entry's declared class; they must be identical strings.
5. **Check the order by grep, not by memory** —
   `grep -n "isDesktopSupported\|System.setProperty" <entry-file>`: probe first, every property
   above the window construction, each commented with what reads it.
