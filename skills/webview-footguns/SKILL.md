---
name: webview-footguns
description: "WebView traps across device classes: startup that freezes low-RAM phones, a killed renderer that takes the app with it, devices with no usable provider, AndroidView lifecycle and cookies. Use when a web screen freezes, vanishes or crashes only on some devices."
---

# WebView footguns

3 traps mined from a production Kotlin and Compose Multiplatform app, one short file each
under `references/`. Every file gives the working pattern, the **Traps** (the specific ways it
fails in practice, and why), and a **Verifying it** section with commands to run against the
user's own tree.

**How to use this index.** Match the code about to be written, or the symptom being chased,
against the entries below: each names its topic and the symptom that should send you to it. Read
every file that plausibly applies with the Read tool before proposing code or a fix; each is under
150 lines. Where a Verifying command names the source project's paths, substitute the equivalent
paths in the user's tree.

**Cross-references.** A backticked trap name inside a file that is not listed here lives in a
sibling area skill: glob `../*/references/<name>.md` to open it.

## Low-RAM phones: startup and renderer death

- [`webview-startup-off-the-main-thread`](references/webview-startup-off-the-main-thread.md) — The first WebView in a process — or the first call to almost any android.webkit API — pays for WebView startup on the calling thread, and even the cookie store loads the provider and its native library before it returns; on a 3–4 GB phone already short of memory that blocked the UI for seconds and ended in an ANR or a kill. Covers starting it on a background executor behind a placeholder, the executor the library does not guard, cookie calls made before the gate, and what still runs on the main thread afterwards. Android only. Use when a screen hosting a WebView freezes for seconds on open on budget phones only, when ANR stacks end inside the WebView constructor, or when the app dies on entering a web sign-in screen while a development phone never reproduces it.
- [`webview-renderer-gone-takes-the-app`](references/webview-renderer-gone-takes-the-app.md) — When the system kills a WebView's renderer process to reclaim memory, a WebView whose client does not handle the renderer-gone callback kills or crashes the whole app to match — from native code, so no Kotlin exception is thrown, a crash reporter that only hooks the JVM records nothing, in the low-memory case nothing records it at all, and users just see the app vanish. Covers returning true from every client the app creates, why the dead instance is replaced rather than reloaded, a Retry that builds a fresh one, and how to kill the renderer on purpose to test it. Android only. Use when users on low-memory phones report the app disappearing from a web screen while the crash dashboard is empty, when the system force-closes the app together with other apps, or when a web screen is blank after the app returns from the background.

## Hosting a WebView in Compose

- [`webview-in-androidview-lifecycle`](references/webview-in-androidview-lifecycle.md) — A WebView hosted in a Compose AndroidView needs four things a bare factory does not give it — a fallback when the constructor throws on a device with no usable WebView provider, an explicit destroy when it leaves composition, a destroy for a WebView whose own setup threw, and side effects keyed to the visit rather than to the view, because the view can be rebuilt. Also the cookie store's blocking flush and its getter that returns null although the store has cookies. Android only. Use when opening a web screen crashes the app on watches or on phones whose WebView provider fails to load, when memory stays high after leaving a web screen, when a Retry signs the user out, when an ANR stack ends inside the cookie store's flush, or when reading a cookie crashes with a null-pointer error — `getCookie(...) must not be null` in a debug build, a call to `Object.getClass()` on a null object reference in a minified release build.
