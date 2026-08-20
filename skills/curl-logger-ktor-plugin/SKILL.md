---
name: curl-logger-ktor-plugin
description: A client plugin that logs every outgoing request as one paste-ready curl command — POSIX single-quoting so a body full of quotes, dollars or newlines survives the shell, the whole command in a single log call, a redaction list, and a body read that does not consume a one-shot channel. Use when you want to replay a failing request outside the app, when a logged command will not run when pasted, or when reproducing a bug means rebuilding a request by hand from a log.
---

# Log the request as a command you can run

The cheapest reproduction tool there is: intercept the request on its way out, print the equivalent
`curl`, paste it into a terminal. No proxy, no capture tool, works on a user's device log.

```kotlin
// adapted — the package is the reader's; the config class's KDoc is condensed to one line on each
// of the two settings that carry a decision. Its three members, the plugin body, the escaping and
// the header loop are the source's own.
class CurlLoggerConfig {
    var logger: (String) -> Unit = { println(it) }
    /** Header names (case-insensitive) shown as `<redacted>`. Empty by default. */
    var redactHeaders: Set<String> = emptySet()
    /** Drop `Accept-Encoding` and append `--compressed` so curl decodes the response itself. */
    var handleCompression: Boolean = true
}

val CurlLogger = createClientPlugin("CurlLogger", ::CurlLoggerConfig) {
    val log = pluginConfig.logger
    val redactHeaders = pluginConfig.redactHeaders.mapTo(mutableSetOf()) { it.lowercase() }
    val handleCompression = pluginConfig.handleCompression

    on(SendingRequest) { request, content ->
        try {
            log(buildCurlCommand(request, content, redactHeaders, handleCompression))
        } catch (e: CancellationException) {
            throw e
        } catch (_: Throwable) {
            // Logging must never break the actual request.
        }
    }
}

/** POSIX shell single-quoting: safe even when the value itself contains single quotes. */
private fun String.shellQuote(): String = "'" + replace("'", "'\\''") + "'"
```

The builder walks the request and joins one list with spaces — never a newline, never a `\`:

```kotlin
val parts = mutableListOf<String>()
parts += "curl -X ${request.method.value}"
parts += request.url.buildString().shellQuote()
val seenHeaders = mutableSetOf<String>()
request.headers.entries().forEach { (name, values) ->
    val lower = name.lowercase()
    if (lower == contentLengthName) return@forEach                     // let curl recompute it
    if (handleCompression && lower == acceptEncodingName) return@forEach
    seenHeaders += lower
    values.forEach { value ->
        val shown = if (lower in redactHeaders) "<redacted>" else value
        parts += "-H " + "$name: $shown".shellQuote()
    }
}
if ("content-type" !in seenHeaders) {
    content.contentType?.let { parts += "-H " + "${HttpHeaders.ContentType}: $it".shellQuote() }
}
if (handleCompression) parts += "--compressed"
content.readBodyOrNull()?.takeIf { it.isNotEmpty() }?.let { parts += "--data-raw " + it.shellQuote() }

return parts.joinToString(" ")
```

## Traps

**Double quotes are not escaping.** Inside `"…"` a shell still expands `$var`, backticks and `\`,
so a JSON body containing `$` or a token starting with a backtick becomes a different request when
pasted — sometimes a *valid* different request, which is worse than a broken one. Single quotes
suppress everything, and the one character they cannot contain is handled by closing, escaping,
reopening: `'` → `'\''`. That five-character sequence is the entire trick and it must be applied to
**every** dynamic part — URL, each header line, and the body — never only to the body.

**One command, one log call, one line.** Splitting across `log()` calls or emitting `\`
continuations reads beautifully in a terminal and is useless in a log: entries interleave with other
threads, get truncated per entry, and arrive out of order in a crash report. Build the whole string
first and hand it over once. This is also why the URL goes in as one quoted argument rather than
being reassembled from parts.

**The default redaction list is empty, which is a decision, not an oversight.** It keeps the command
runnable as printed — a redacted authorization header produces a command that fails, and a developer
then edits it by hand and mistypes it. The cost is that a session cookie or bearer token goes into
the log verbatim, and logs get attached to bug reports. Two rules follow: never ship a release build
with this plugin's sink pointing anywhere persistent, and check what each install site actually
passes rather than trusting the default. The audit is one grep and it very often finds *no* install
site setting a list at all.

**Never let logging fail the request — but do not swallow cancellation with it.** A bare
`catch (Throwable)` around the log call also catches the cancellation signal that structured
concurrency uses to unwind a coroutine, so a request cancelled while the command was being built
would be reported as "logged fine" and the cancellation lost. Re-throw it first, then swallow the
rest. The same pair guards the body read.

**The request body is often a one-shot channel, and reading it is how you break the request you were
trying to observe.** Branch on the content kind instead of calling one generic read: a byte-array
body can be decoded directly; a body that writes itself to a channel can be given a *fresh* channel
to write into, in a scope of its own, so the real one is untouched; a body that *is* a channel — and
anything exotic — must be skipped, returning null. Skipping is the correct outcome, not a gap:
printing a command with no `--data-raw` is honest, whereas consuming the channel sends an empty body
to the server.

**Drop the content-length header, and mean it.** curl computes its own from `--data-raw`, so a
carried-over one is a duplicate at best. The real damage is on the branch above: when the body could
not be read the command has no `--data-raw` at all, and a stale content-length then describes a body
that is not there — the server waits for bytes that never arrive and the pasted command hangs, which
looks like a server problem and is not one.

**Content type frequently is not in the request headers.** It rides on the body object, which is why
the builder tracks which headers it has emitted and adds the body's own type only when missing. Skip
this and the pasted command posts a JSON body the server reads as form data.

**Attach it to the instrumented client only.** It reads request bodies into strings; on a client that
uploads or streams large payloads that is the same mistake as verbose response logging — see
`ktor-kmp-client-architecture` for the two-client split this belongs on the API side of.

## Verifying it

The only verification that counts is the round trip: take one logged line, paste it into a terminal,
confirm the response matches what the app got. Do it with a request whose body contains a single
quote *and* a `$` — that is the one that reveals broken quoting; a body of plain alphanumerics passes
on a broken implementation.

Then check the wiring across the codebase:

```bash
grep -rn 'createClientPlugin' --include='*.kt' . | grep -v '/build/'
grep -rn 'shellQuote' --include='*.kt' . | grep -v '/build/'
grep -rn 'redactHeaders' --include='*.kt' . | grep -v '/build/'
```

The second should hit the URL, the header line, the body **and** the function itself — a hit list
missing any one of those three call sites is the escaping gap. The third is the secrets audit: if
every hit is inside the plugin file, no install site overrides the empty default and every build logs
its headers in full. `createClientPlugin` and the sending-request hook are Ktor 3.x; the escaping and
the one-line rule are not tied to any library.
