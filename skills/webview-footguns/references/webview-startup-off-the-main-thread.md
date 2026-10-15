---
name: webview-startup-off-the-main-thread
description: The first WebView in a process — or the first call to almost any android.webkit API — pays for WebView startup on the calling thread, and even the cookie store loads the provider and its native library before it returns; on a 3–4 GB phone already short of memory that blocked the UI for seconds and ended in an ANR or a kill. Covers starting it on a background executor behind a placeholder, the executor the library does not guard, cookie calls made before the gate, and what still runs on the main thread afterwards. Android only. Use when a screen hosting a WebView freezes for seconds on open on budget phones only, when ANR stacks end inside the WebView constructor, or when the app dies on entering a web sign-in screen while a development phone never reproduces it.
---

# The first WebView pays for startup, on whichever thread asks first

Android only. Creating a `WebView` costs twice. Once per process, the provider is loaded and its
browser engine started; once per instance, that view's native contents are built. Both run on the
thread that asks — and the thread that asks is nearly always the main thread, inside a view
factory or a `setContentView`.

Users on 3–4 GB phones reported the sign-in screen freezing for **3–4 seconds** — touches ignored
— and then the app gone, closed by the system together with another app at the same moment
(user reports). That points at the low-memory killer; a renderer-gone kill
(`webview-renderer-gone-takes-the-app`) would look the same from the outside. The main ANR stack,
from a 3 GB phone, ended in `WebView.<init>` → `WebViewChromium.init` → `AwContents.<init>` → a
native wait. A second ANR on the same screen ended in the cookie store's `flush()`
(`webview-in-androidview-lifecycle`).

## The pattern: start it in the background, build the view after

`androidx.webkit` 1.16.0 and later expose `WebViewCompat.startUpWebView`, which runs startup work
on an executor you supply and calls back on the UI thread when it is done. Show a placeholder
until then, and only compose the view afterwards:

```kotlin
// adapted — the gate every login WebView in the app sits behind
var ready by remember { mutableStateOf(false) }
var startupFailed by remember { mutableStateOf(false) }

LaunchedEffect(Unit) {
    val executor = Executor { task ->
        Dispatchers.IO.asExecutor().execute {
            try { task.run() } catch (e: Throwable) { startupFailed = true }   // see Traps
        }
    }
    WebViewCompat.startUpWebView(
        appContext,
        WebViewStartUpConfig.Builder(executor).build(),
        object : WebViewOutcomeReceiver<WebViewStartUpResult, WebViewStartupException> {
            override fun onResult(result: WebViewStartUpResult) { ready = true }
            override fun onError(error: WebViewStartupException) { startupFailed = true }
        },
    )
}

when {
    startupFailed -> UnavailableMessage()
    !ready -> CircularProgressIndicator()
    else -> AndroidView(factory = { ctx -> WebView(ctx).apply { /* configure, then loadUrl */ } })
}
```

Calling it again later in the same process is safe; a second screen just gets its callback sooner.

**Field status (user report, 2026-10-15):** a user who had reported the freeze tested a build
carrying this gate together with `webview-renderer-gone-takes-the-app` and
`webview-in-androidview-lifecycle`, and reported the sign-in screen working. That is one phone,
whose model and WebView version are not recorded, and it confirms the three changes together —
not this gate on its own.

## Traps

**Touch no webkit API before the gate calls back.** Not only the constructor. The library's own
documentation says `android.webkit` and `androidx.webkit` APIs must only be called after the
callback, and the startup guide names the user-agent getter and inflating a layout with a
`<WebView>` tag as triggers. `CookieManager.getInstance()` is the quiet one: it loads the WebView
provider and its native library on the calling thread before it returns — part of the work the
gate exists to move — though in the current engine it does not wait for the full engine start. A
screen that clears cookies in a `LaunchedEffect` on entry pays that part on the main thread, or
blocks there while the background task loads the same provider. The startup guide warns of the
same shape: start up, then touch WebView on the main thread, and the main thread waits for startup
to catch up. Move such calls behind `onResult` — the view factory or a callback of the WebView
itself — with the caveat in `webview-in-androidview-lifecycle`.

**The executor you hand the library runs its task unguarded.** The library submits its startup
task to your executor with no `try`/`catch` around it, and on a device with no usable provider the
provider lookup inside that task throws. On `Dispatchers.IO` an uncaught throwable goes straight to
the default handler: the process dies from a background thread, on exactly the devices the gate
was meant to protect. Wrap the task yourself and route the throwable to the same state as
`onError`.

**A failure is final for this visit.** After `onError`, or after your executor caught a
throwable, do not fall through to constructing a `WebView` "to see if it works". The library's
documentation says any other WebView call after a failed startup is likely to throw or crash
immediately, and a crash inside native code is beyond any `runCatching`. Show an unavailable
message. Calling `startUpWebView` again is allowed, but the startup guide advises against a naive
retry loop; tie any retry to a user action.

**The gate hides the per-process cost, not the per-view one.** Each `WebView` instance still builds
its native contents on the main thread, and nothing moves that. In the startup guide's words the
API shifts "a significant amount" of startup to a background thread and does the remaining UI-thread
work in chunks. The main ANR stack above ends in exactly that per-instance construction, so do not
assume the gate alone removed it: keep the hosting screen otherwise idle while the view is
created, and measure on the phone that froze.

**On a WebView too old for asynchronous startup, the library falls back, and the fallback is only
as good as the provider.** When neither version of the async-startup feature is present, the
library — with the default config — calls the default-user-agent getter on your executor to force
startup there. Whether the engine honours a background caller or hands its work back to the UI
thread is the provider's business, so the freeze may return after the placeholder appears. **Not
yet verified on a device:** test on the oldest WebView version your crash reports show, not on a
phone that auto-updates it.

**It reproduces only under memory pressure, which a development phone never has.** A 4 GB
development phone with few background apps never reproduced it, while 3–4 GB phones in the field
did (user reports). A fix tested on an idle phone has not been tested.

## Verifying it

1. **Every construction, inflation and webkit entry point, with its context:**

   ```bash
   grep -rnE '(^|[^A-Za-z])WebView\(|CookieManager\.getInstance|getDefaultUserAgent|WebViewFeature\.|WebStorage\.getInstance|WebViewDatabase\.getInstance|setWebContentsDebuggingEnabled' \
     --include='*.kt' --exclude-dir=build .
   grep -rnE '<(android\.webkit\.)?WebView[[:space:]/>]' --include='*.xml' --exclude-dir=build .
   ```

   Pass condition: each hit is inside the view factory that runs after `onResult`, inside a
   WebView callback such as `onPageFinished` (which only runs once a WebView exists), inside a
   function only called from those, or on a background dispatcher. A call reached on the main
   thread from a `LaunchedEffect`, a ViewModel `init` or `Application.onCreate` pays startup there.
   If the cookie manager sits behind a wrapper, follow the wrapper's callers the same way.

2. **The startup executor is guarded:**

   ```bash
   grep -rn -B14 'startUpWebView(' --include='*.kt' --exclude-dir=build . | grep -E 'Executor|try \{|catch \('
   ```

   Pass condition: an `Executor { … }` whose body has a `try {` and a `catch (e: Throwable)`. A
   bare `Executors.newSingleThreadExecutor()` or `Dispatchers.IO.asExecutor()` passed straight in
   is the crash on provider-less devices.

3. **Recreate the field condition, then watch for the freeze:**

   ```bash
   adb shell am force-stop <package> && adb logcat -c
   # on the phone: open three or four heavy apps, then open the app cold and go to the WebView screen
   adb logcat -d | grep -E 'ANR in|lowmemorykiller|lmkd'
   ```

   Pass condition: no `ANR in <package>` line, and no low-memory-killer line naming `<package>`.
   Use the lowest-RAM phone you can get, with the WebView version it shipped with; passing on a
   flagship or an emulator proves nothing about this trap.

Companions: `webview-renderer-gone-takes-the-app` for the other way a low-RAM phone ends the
process from a web screen, and `webview-in-androidview-lifecycle` for the view the gate guards.
