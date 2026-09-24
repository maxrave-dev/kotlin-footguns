---
name: desktop-deep-link-plumbing
description: Wiring a custom URL scheme end to end on a JVM desktop app — per-OS registration, the argument filter at startup, single-instance forwarding, and delivering a callback's token to app state. Reach for it when clicking a link or returning from a browser redirect merely brings the app to the front and the flow it was supposed to complete just sits there.
---

# Desktop deep links, end to end

A desktop deep link has to survive four independent hops, and each one can drop it silently:

1. **Registration** — the OS must know your scheme belongs to your executable.
2. **Launch/delivery** — the OS hands the URL to the process, differently on every platform.
3. **The app's own filter** — startup code decides which argument is a link.
4. **App state** — the URL has to reach the piece of state that was waiting for it.

A dropped link almost never produces an error. The app comes to the foreground and looks fine, which
is why these bugs get filed as "the redirect doesn't work" and looked for in the browser.

## Registration, per platform

Three different mechanisms; **every scheme you support must be present in all three**, and adding a
second scheme later is exactly when one gets forgotten.

- **macOS** — a `CFBundleURLTypes` array in the bundle's property list, produced by the packager.
- **Windows** — a per-user registry key (no admin rights needed): `HKCU\Software\Classes\<scheme>`
  with a `URL Protocol` value and `shell\open\command` = `"<exe>" "%1"`. Registering at first run
  from inside the app is reasonable; re-check the stored path each launch, since the executable
  moves when the user reinstalls elsewhere.
- **Linux** — `MimeType=x-scheme-handler/<scheme>;` in the `.desktop` file, plus
  `update-desktop-database` so the handler is indexed.

## Traps

**On Linux the `.desktop` file that reaches users is often not the one you configured.** If the
packager emits a directory tree that a later step wraps into a portable single-file bundle, that
bundle's startup script typically writes its *own* launcher file into the user's applications
directory and indexes it. That copy is the handler the desktop consults. A scheme added to the
packager config and not to the wrapper's file is registered nowhere. Update both, then verify by
grepping the installed file under the user applications directory — not the source.

**macOS does not pass the URL in `argv`.** It arrives as an application event, so a
`main(args)`-only implementation is deaf on macOS while working on Windows and Linux. Register an
open-URI handler at startup, and route it into the same entry point the argument path uses. While
you are there: clicking the dock icon of a running app is a *reopen* event, not a second launch, so
whatever restore logic your second-instance path uses will never fire for it — handle it explicitly.

**The startup filter must match any `scheme://`, never a fixed list.** A list like
`{"yourapp://", "http://", "https://"}` works until the day you register a second scheme — then the
OS launches the process with the URL, this line discards it, the window comes to the front, and the
flow that was waiting never completes. Match by shape instead (RFC 3986 §3.1: a letter, then letters
/ digits / `+` / `-` / `.`):

```kotlin
private val DEEP_LINK_ARG = Regex("^[A-Za-z][A-Za-z0-9+.\\-]*://.+")

val deepLinkArg = args.firstOrNull()?.takeIf { DEEP_LINK_ARG.matches(it) }
```

**Forward from the second instance before it touches shared state.** With a single-instance guard,
the OS still starts a whole new process for the link. That process must hand the URL over and exit
*before* initializing anything that writes to a shared on-disk file. What was actually observed: a
preferences store created eagerly at startup, touched by the second process, failing to rename its
temporary file over the live one and taking the launch down with an I/O error (Windows, where this
was seen — the two processes race on the same file). Anything else opened eagerly and exclusively,
an embedded database being the obvious one, is worth checking for the same shape. A temp file plus a
restore signal is enough:

```kotlin
// adapted
if (!isSingleInstance(onRestoreRequest = { RestoreSignal.request() })) {
    deepLinkArg?.let { DeepLinkHandler.writePendingUri(it) }   // hand off
    return                                                     // before any store opens
}
```

The surviving instance consumes the pending file when it handles the restore request.

**Cache the URL until a listener exists.** A cold launch delivers the link long before any screen is
composed. The handler should hold the most recent URL and replay it the moment a listener is
attached, then clear it — otherwise every cold-start deep link is lost and only warm ones work,
which reads as "it works sometimes".

**Hand an auth callback's token straight to app state — do not route it through navigation.** When a
login redirect comes back from the system browser, the screen the user started from is *still on the
navigation stack*: the browser was opened from it and the app never left. Navigating to that screen
again pushes a **second copy**, and the "close myself when login succeeds" step then pops only the
copy, landing the user back on an identical login screen. It looks exactly like "logged in, but
stuck on the login page". Instead:

- deliver the token directly to the shared state holder from the link handler;
- let the screen close itself by observing the *stored result* (a session record appearing), not its
  own local state — the redirect never passes through the screen at all.

Screens that embed a web view never hit this, because the flow never leaves the app. This is
specific to flows that hand off to the system browser, which is the normal shape on desktop, where a
real embedded browser is usually not available.

**Keep the callback URL's shape intact.** If your link handler normalizes app links into a canonical
internal URL, exclude the callback scheme from that rewrite — the code that reads the token matches
on the original scheme and host, and a rewritten URL silently stops matching.

**Offer a paste-the-callback fallback.** On hosts with no scheme handler at all (a stripped desktop
session, a remote shell, a locked-down machine), the browser lands on the callback URL and shows it
in the address bar with nothing to hand it to. A text field on the login screen that accepts that
pasted URL and extracts the token turns a dead end into a two-second workaround, and costs one
parser you already have.

## Verifying it

```bash
# Linux: does a handler exist, and is it yours?
xdg-mime query default x-scheme-handler/yourapp
xdg-open 'yourapp://open?x=1'

# macOS: is the scheme in the built bundle at all?
grep -A6 CFBundleURLSchemes /Applications/YourApp.app/Contents/Info.plist

# Windows (PowerShell): the per-user registration
reg query 'HKCU\Software\Classes\yourapp\shell\open\command'
```

Test each scheme separately, with the app **closed** and again with it **running** — those are two
different code paths (cold launch argument versus second-instance forwarding or application event),
and each has its own way of dropping the link.
