---
name: webview-in-androidview-lifecycle
description: A WebView hosted in a Compose AndroidView needs four things a bare factory does not give it — a fallback when the constructor throws on a device with no usable WebView provider, an explicit destroy when it leaves composition, a destroy for a WebView whose own setup threw, and side effects keyed to the visit rather than to the view, because the view can be rebuilt. Also the cookie store's blocking flush and its getter that returns null although the store has cookies. Android only. Use when opening a web screen crashes the app on watches or on phones whose WebView provider fails to load, when memory stays high after leaving a web screen, when a Retry signs the user out, when an ANR stack ends inside the cookie store's flush, or when reading a cookie crashes with a null-pointer error — `getCookie(...) must not be null` in a debug build, a call to `Object.getClass()` on a null object reference in a minified release build.
---

# Build it defensively, destroy it explicitly, and key side effects to the visit

Android only. `AndroidView(factory = { WebView(it) })` compiles and works on a development phone.
On the wider device population it has four holes: the constructor can throw, nothing ever destroys
the view, a failed setup leaks a live WebView, and anything put in the factory runs once per *view*
rather than once per *visit*.

## The pattern

```kotlin
// adapted
AndroidView(
    factory = { ctx -> webViewOrFallback(ctx) { configure() } },
    onRelease = { view -> (view as? WebView)?.run { stopLoading(); destroy() } },
    modifier = Modifier.fillMaxSize(),
)

private fun webViewOrFallback(context: Context, setup: WebView.() -> Unit): View {
    val webView = runCatching { WebView(context) }.getOrElse { return unavailableView(context) }
    return runCatching { webView.apply(setup) }.getOrElse {
        runCatching { webView.destroy() }   // onRelease will only ever see the fallback view
        unavailableView(context)
    }
}
```

`onRelease` casts because the factory may hand back the fallback `TextView` instead of a WebView.

## Traps

**The constructor throws on devices with no usable provider.** The source project's crash reports
hold two shapes, each from around thirty users and both thrown from the factory: a watch with no
provider at all (`UnsupportedOperationException`), and phones whose provider failed to load its
resources (`AndroidRuntimeException`). An exception from `WebView(context)` inside the factory
crashes the app. Catch it and show a
message. This is one of the few places a broad catch is right — there is nothing to recover except
telling the user. Do the same for the startup gate in `webview-startup-off-the-main-thread`, which
fails on the same devices.

**Without `onRelease`, the page outlives the screen.** `AndroidView`'s default release does nothing
to the view. A WebView that ended on a heavy single-page web app keeps its page alive in the
renderer until the object is garbage-collected — on a low-RAM phone, exactly the memory the next
screen needed, and the memory the system reclaims by killing the renderer
(`webview-renderer-gone-takes-the-app`). Call `stopLoading()` then `destroy()` in `onRelease`.

**A WebView whose setup threw never reaches `onRelease`.** `onRelease` receives what the factory
returned. If construction succeeded, configuration threw, and the factory returned a fallback view,
the half-configured WebView is orphaned with its native side alive. Split construction from setup
so you know which one failed, and destroy the WebView before returning the fallback. One
`runCatching { WebView(ctx).apply(setup) }` cannot tell the two apart.

**Moving a side effect into the factory changes how often it runs.** A `LaunchedEffect(Unit)` runs
once per visit to the screen; a factory runs once per view. There is a reason to move cookie work
into the factory — before the startup gate calls back, touching the cookie store loads the provider
on the main thread (`webview-startup-off-the-main-thread`) — but once the screen can rebuild its view (a Retry after the renderer died),
"clear cookies before loading the sign-in page" runs again on every Retry and wipes the session
the user just completed. Guard it with a flag remembered at screen level, outside the factory:

```kotlin
// adapted
val cookiesCleared = remember { AtomicBoolean(false) }
// … inside configure(), after startup has finished:
if (clearCookies && cookiesCleared.compareAndSet(false, true)) {
    CookieManager.getInstance().removeAllCookies(null)   // asynchronous; no flush() here, it blocks
}
```

**`flush()` blocks the thread that calls it.** The cookie store's `flush()` writes every cookie to
persistent storage, and its documentation says the call blocks the caller until done and may
perform I/O. On a phone short of memory and I/O that is a main-thread stall of its own: the source
project's second ANR on the sign-in screen ends in `flush` → native, separate from the constructor
one in `webview-startup-off-the-main-thread`. `removeAllCookies(callback)` is already asynchronous. If the result must be on disk before the
next step, call `flush()` from a background dispatcher after the gate — never from a click
handler, a view factory or a page callback, all of which run on the main thread.

**`getCookie(url)` returns null when no cookie matches *that* URL, even when the store has
cookies.** `hasCookies()` answers for the whole store, so `if (hasCookies()) getCookie(url)` still
returns a platform-typed `null` — as it does for a URL the engine cannot parse. Returned from a
function declared `String`, Kotlin's null check throws there. A debug build names the call:
`getCookie(...) must not be null`. A minified release build does not: the check is rewritten, and
the crash reads `Attempt to invoke virtual method 'java.lang.Class java.lang.Object.getClass()' on
a null object reference`, with your own wrapper as the top frame — in the source project, over
1,800 users' worth before it was fixed. Use `getCookie(url).orEmpty()` and drop the `hasCookies()`
guard.

## Verifying it

1. **Every `AndroidView` hosting a WebView destroys it on release:**

   ```bash
   grep -rl 'android.webkit.WebView' --include='*.kt' --exclude-dir=build . \
     | xargs -r grep -Hn -A12 'AndroidView(' | grep -iE 'AndroidView\(|webview|onRelease|destroy\(\)'
   ```

   Pass condition: each `AndroidView(` line is followed by an `onRelease` with `destroy()`. An
   `AndroidView(` with no `onRelease` after it is the leak.

2. **Construction is guarded and split from setup:**

   ```bash
   grep -rnE 'runCatching \{ *WebView\(|webView\.destroy\(\)' --include='*.kt' --exclude-dir=build .
   ```

   Pass condition: the constructor in its own `runCatching`, and a `destroy()` on the path where
   setup failed.

3. **Every cookie read tolerates null:**

   ```bash
   grep -rn 'getCookie(' --include='*.kt' --exclude-dir=build .
   ```

   Pass condition: every call on the platform `CookieManager` ends in `.orEmpty()` or `?:`; calls on
   a wrapper of your own are fine once the wrapper does. A `hasCookies()` beside it is the old guard
   that does not work.

4. **Side effects in the factory are once per visit:**

   ```bash
   grep -rn -B2 'removeAllCookies(' --include='*.kt' --exclude-dir=build .
   ```

   Pass condition: a call reached from inside a factory sits behind `compareAndSet(false, true)` on
   a flag remembered outside it. On a device: sign in, trigger a Retry (`chrome://kill`, see
   `webview-renderer-gone-takes-the-app`), and confirm the session survives.

5. **No cookie flush on the main thread:**

   ```bash
   grep -rnE 'CookieManager\.getInstance\(\)\.flush\(' --include='*.kt' --exclude-dir=build .
   ```

   Pass condition: each hit runs only on a background dispatcher — follow a wrapper's callers to
   check. At the time of writing the source project fails this: its cookie wrapper flushes after
   `removeAllCookies` and is called from the view factory and from page callbacks.
