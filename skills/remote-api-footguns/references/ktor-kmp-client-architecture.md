---
name: ktor-kmp-client-architecture
description: A multiplatform HTTP stack where one expect/actual hands back the engine and each integration builds its own client from it — an instrumented client for API calls next to a deliberately bare one for bulk downloads, content negotiation registered per format, and a settings change that rebuilds the client rather than mutating it. Use when standing up networking in a Kotlin Multiplatform module, when a proxy setting appears to be ignored by some requests but not others, or when downloading a large file crawls and floods the log.
---

# One engine, several clients

The only platform-specific thing about an HTTP client is the engine, so that is the only thing
behind `expect`/`actual`:

```kotlin
// commonMain
expect fun getEngine(): HttpClientEngineFactory<HttpClientEngineConfig>
// androidMain and jvmMain — the same JVM-backed engine
actual fun getEngine(): HttpClientEngineFactory<HttpClientEngineConfig> = OkHttp
// iosMain
actual fun getEngine(): HttpClientEngineFactory<HttpClientEngineConfig> = Darwin
```

Everything above it — plugins, serialization, defaults — is common code. Each integration then
builds its own client, and an integration that also downloads bytes builds a **second** one:

```kotlin
// adapted — the class name and its base URL are placeholders; `httpClient`/`createClient` renamed
// to `apiClient`/`createApiClient`; the credential and locale fields between them are trimmed, as
// are the API client's log sink and its two serializer configs. Both client bodies are otherwise
// the source's own, as are the lazy-cache shape and the proxy setter.
class CatalogService {
    private var apiClient = createApiClient()
    private var downloadClient: HttpClient? = null

    /** Bulk transfer: no logging, no negotiation, no encoding. Redirects only. */
    private fun getDownloadClient(): HttpClient =
        downloadClient ?: HttpClient(getEngine()) {
            expectSuccess = true
            install(HttpRedirect) { checkHttpMethod = false; allowHttpsDowngrade = true }
        }.also { downloadClient = it }

    var proxy: ProxyConfig? = null
        set(value) {
            field = value
            apiClient.close()
            apiClient = createApiClient()      // rebuilt, not reconfigured
        }

    private fun createApiClient() =
        HttpClient(getEngine()) {
            expectSuccess = true
            install(CurlLogger) { logger = { Logger.d(TAG, it) } }
            install(HttpRedirect) { checkHttpMethod = false; allowHttpsDowngrade = true }
            install(Logging) { level = LogLevel.ALL }
            install(ContentNegotiation) {
                protobuf()
                json(Json { ignoreUnknownKeys = true; explicitNulls = false })
                xml(contentType = ContentType.Text.Xml)
            }
            install(ContentEncoding) { brotli(1.0F); gzip(0.9F); deflate(0.8F) }
            if (proxy != null) { engine { proxy = this@CatalogService.proxy } }
            defaultRequest { url(BASE_URL) }
        }
}
```

## Traps

**The verbose client is what makes a download unusable, and the reason is not "overhead".** A
logging plugin at its most verbose level writes the *response body* to the log, so streaming a large
file materialises it a second time as text — plus whatever the log sink then does with it. Write
down that the two clients differ *on purpose*, because a well-meant "why does only one client have
logging?" cleanup puts it back. Attach the instrumented plugins to the client that talks to an API in
small request/response pairs, and nothing to the one that moves bytes.

**A configuration change means a new client. The config block runs once, at construction.** Note
where the proxy check sits: *inside* the builder lambda. Reading `proxy` later changes nothing that
was already built, which is why the setter closes the client and constructs a replacement. Reach for
that shape whenever a setting is baked into the client rather than into a request.

**…and rebuilding one client leaves its siblings on the old configuration.** The setter above
touches `apiClient` only. `downloadClient` was cached on first use and is never rebuilt, so it keeps
going direct after a proxy change — and is never closed either, so its connection pool outlives the
setting that was supposed to replace it. Any service holding two or more clients needs the setter to
walk **all** of them; the shape to write is a list of clients and a `rebuildAll()`, not a second
copy-pasted setter. Verify this one by reading every setter, because nothing fails — the requests
succeed, just not through the thing you configured.

**`expectSuccess` is a per-client decision that changes what a caller's error handling means.** With
it on, a non-2xx status throws and a `runCatching` around the call catches it; with it off, the same
`runCatching` succeeds and hands back a response nobody checked the status of. Opposite settings in
one codebase are legitimate, but then "did this call fail?" is answered per client — make it visible
at the call site.

**Content negotiation matches on the response's declared content type, not on what the bytes look
like.** A host that serves JSON as plain text is not decoded by a `json()` registration, and the
symptom is a "no transformation found" style failure rather than a parse error. Two honest answers,
both in use here: register the converter against the content type the host actually sends, or read
the body as text and decode it explicitly. Pick per endpoint; do not widen a global registration to
cover one misbehaving host, or every genuinely-text response starts going to a deserializer.

**An engine artifact declared in commonMain that no `actual` returns still ships.** The dependency
block and the `actual` functions are edited in different files, so one can name an engine the other
never selects — costing binary size on every platform and misleading the next reader into thinking
that engine is in play. Check the two against each other, not each on its own.

**Count the `actual` files against the declared targets.** A source set that no declared target maps
to is never compiled: the file neither works nor fails, it simply is not there, and it rots quietly
across engine and API changes. The mirror-image mistake is declaring the `actual` in both a shared
parent source set *and* its children, which is a redeclaration for every target that inherits both.
Neither is visible by reading one file.

**A client constructed anywhere other than the factory bypasses all of it.** One built inline — in a
UI function, or with the default engine and no configuration — gets no shared plugins, no proxy, no
negotiation, and on a platform whose engine artifact is not on that source set's classpath it fails
at runtime rather than at compile time. Inside a composable it is also rebuilt on every recomposition
unless remembered. The first grep below is the whole audit, and it covers both call shapes.

## Verifying it

Every claim above is a cross-file one, so read them across files:

```bash
grep -rnE '\bHttpClient[[:space:]]*[({]' --include='*.kt' . | grep -v '/build/'
grep -rln 'install(Logging)' --include='*.kt' . | grep -v '/build/'
grep -rn -A4 'var proxy' --include='*.kt' . | grep -v '/build/'
grep -rn 'actual fun getEngine' --include='*.kt' . | grep -v '/build/'
```

The first is the census: every construction site in both call shapes, including the ones that did
not come from the factory. Expect one line per client-owning integration plus one more for each
download client, and treat any hit under a UI source set, or any construction with no engine
argument — `HttpClient()` or a bare `HttpClient { … }` — as a finding on sight. The second lists
*files*, not clients, so a file holding both clients still appears; confirm the logging install sits
in the API client's builder, not the download one's. The third shows each settings-setter with the
lines that follow — where you see it rebuild one client and leave the sibling alone. The fourth is
the `actual` census: compare it against the targets declared in that module's build script, since
more declarations than targets means some are dead or duplicated.

Library behaviour named here (plugin ids, the negotiation-by-content-type rule) is Ktor 3.x; the
architecture is not version-specific. Related: `curl-logger-ktor-plugin` is the instrumented client's
other plugin, and `parallel-chunked-download` is what the bare client exists for.
