---
name: webview-renderer-gone-takes-the-app
description: When the system kills a WebView's renderer process to reclaim memory, a WebView whose client does not handle the renderer-gone callback kills or crashes the whole app to match — from native code, so no Kotlin exception is thrown, a crash reporter that only hooks the JVM records nothing, in the low-memory case nothing records it at all, and users just see the app vanish. Covers returning true from every client the app creates, why the dead instance is replaced rather than reloaded, a Retry that builds a fresh one, and how to kill the renderer on purpose to test it. Android only. Use when users on low-memory phones report the app disappearing from a web screen while the crash dashboard is empty, when the system force-closes the app together with other apps, or when a web screen is blank after the app returns from the background.
---

# A dead renderer takes the app with it, unless every client says otherwise

Android only. A WebView's page runs in a separate renderer process, and under memory pressure the
system may kill that process before it touches yours. What happens next is decided by
`WebViewClient.onRenderProcessGone`. Its default returns `false`, and the documentation is direct
about the result: if any WebView using that renderer does not return `true`, WebView kills or
crashes the app, matching how the renderer exited. "Any" means every WebView alive on that
renderer at the moment it dies.

Either way the process ends from native code: no Kotlin exception is thrown and no
uncaught-exception handler runs. A crashed renderer ends in a native abort of your process, which a
reporter with native crash handling can catch; a renderer killed for memory ends in a kill of your
process, which nothing sees. The field report is "the app closes on that screen on my 3 GB phone", sometimes with
"and the system closed another app at the same moment", against a crash dashboard with nothing in it.

## The pattern

One handler, shared by every client the app creates:

```kotlin
// adapted — every WebViewClient in the app routes through this
private fun handleRendererGone(detail: RenderProcessGoneDetail, onRendererGone: () -> Unit): Boolean {
    log.w("renderer gone, crashed=${detail.didCrash()}")   // false: most likely reclaimed for memory
    onRendererGone()                                       // flip the screen to a Retry state
    return true                                            // keep the app alive
}

override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean =
    handleRendererGone(detail) { rendererGone = true }
```

In Compose, replace the view rather than reviving it:

```kotlin
// adapted
when {
    rendererGone -> Button(onClick = { rendererGone = false }) { Text(retryLabel) }
    else -> AndroidView(
        factory = { ctx -> WebView(ctx).apply { configure() } },
        onRelease = { it.stopLoading(); it.destroy() },
    )
}
```

Switching to the Retry branch removes the `AndroidView`, which runs `onRelease` and destroys the
dead instance; tapping Retry composes a new `AndroidView`, whose factory builds a new WebView with
a new renderer.

## Traps

**Every WebView on that renderer must return true, not just the one you were looking at.** The
rule in the documentation is about *any* WebView using the renderer. One screen built with a plain
`WebViewClient()`, or with no client at all, takes the process down when the renderer dies,
however carefully the other screens handle it. Route every client through one helper and grep for
the ones that bypass it.

**Do not reload the dead instance.** The documentation says that object is useless: remove it from
the hierarchy, destroy it, drop every reference, and create a new instance to show web content
again. A new navigation on the old object has been observed to work on some WebView versions, but
that is outside the documented contract — a Retry that calls `reload()` on the old view is relying
on luck.

**Returning true is the start of the fix, not the fix.** It keeps the process alive; the screen
still has a hole in it. Unless the callback flips visible state, the user is left looking at a
blank rectangle where the page was, with no way back except leaving the screen.

**A rebuilt view re-runs its factory, and so re-runs every side effect in it.** If the factory
clears cookies or restarts a sign-in, Retry undoes progress the user made before the renderer died.
The once-per-visit guard is in `webview-in-androidview-lifecycle`.

**The crash reporter's silence is not evidence.** A reporter that only hooks the JVM gets nothing in
either case, and in the low-memory case nothing gets anything, so the dashboard cannot rank this. What it does show — ANRs whose stacks end inside WebView construction — can be the same field
problem seen from its other end (`webview-startup-off-the-main-thread`). Ask affected users for the
phone's RAM and what else was open, not for a stack trace they cannot have.

**`didCrash()` tells you which bug you have.** `false` means the renderer was killed rather than
crashing — most likely by the system for memory, possibly by a WebView update: the fix is surviving
it, plus using less. `true` means the renderer itself crashed: that
is usually the page or the engine, and surviving it is still right, but expect it to come back on
the next load.

## Verifying it

1. **Every client the app creates, and every renderer-gone override:**

   ```bash
   grep -rnE 'WebViewClient\(\)|override fun onRenderProcessGone' --include='*.kt' --exclude-dir=build .
   ```

   Pass condition: one `override fun onRenderProcessGone` per `WebViewClient()`. Then check each override
   returns `true`, or calls the shared helper that does:

   ```bash
   grep -rn -A3 'override fun onRenderProcessGone' --include='*.kt' --exclude-dir=build .
   ```

2. **No WebView is built without a client.** Every construction site from
   `webview-startup-off-the-main-thread`'s first grep must reach a `webViewClient =` assignment
   that overrides the callback; a view that never sets one uses the default.

3. **Kill the renderer on purpose.** From a debug-only button, load these into the live
   WebView and watch the callback and the screen:

   ```kotlin
   // debug builds only
   webView.loadUrl("chrome://kill")    // didCrash() == false — the low-memory case
   webView.loadUrl("chrome://crash")   // didCrash() == true
   ```

   Pass condition: the app stays up, the Retry state shows, and Retry loads the page in a new
   WebView. Remove the handler and run it again to see the field symptom — the app disappears with
   nothing in the crash reporter. `chrome://crash` was reported working on an API 34 emulator with
   WebView 131; `chrome://kill` goes through the same debug-URL handling in the engine but has not
   been run on a device for this file. Check both on your oldest supported WebView first.

4. **In the field condition**, with the screen open, switch to several heavy apps and back:

   ```bash
   adb logcat -d | grep -E 'Render(er)? process|sandboxed_process|lowmemorykiller'
   ```

   A renderer exit followed by your process staying alive is the pass.
