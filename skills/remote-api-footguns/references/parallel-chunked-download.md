---
name: parallel-chunked-download
description: Splitting one file into N byte-range requests issued in parallel over a bare HTTP client, each chunk to its own temp file, merged in order, with progress reported through a channel-backed flow — plus when ranges are actually safe, how big a chunk should be, and why a failure retries one chunk rather than the file. Use when a large download is slower than the link allows, when a download restarts from zero after a hiccup, or when a progress bar sticks just short of full.
---

# N ranges, one file

Three decisions in order: *may* I range this, *should* I, and then the ranges themselves.

```kotlin
// adapted — the flow's value type is spelled out as a named `Progress` class in place of the
// source's positional triple; the two callback arguments and the single-threaded fallback are
// elided to one line each. The probe test, the threshold and the branch are the source's own.
fun download(url: String, target: Path, maxRetries: Int = 3, parallel: Int = 4): Flow<Progress> =
    channelFlow {
        with(bareDownloadClient()) {                       // no logging, no negotiation
            val supportsRange = try {
                val probe = head(url) { header("Range", "bytes=0-0") }
                probe.headers["Content-Range"] != null || probe.status.value in 200..299
            } catch (e: Exception) { false }
            val fileSize = try {
                head(url).headers[HttpHeaders.ContentLength]?.toLong() ?: 0L
            } catch (e: Exception) { 0L }

            // both callbacks push through the same channel — trySend(Progress.running(p)) for
            // ticks, trySend(Progress.done(ok)) for the terminal one; see the progress trap
            if (supportsRange && fileSize > CHUNK_SIZE * 2) {
                parallelDownload(url, target, fileSize, parallel, maxRetries, /* callbacks */)
            } else {
                singleThreadedDownload(url, target, maxRetries, /* callbacks */)
            }
        }
    }
```

Each chunk is an independent job with its own attempt counter, writing to its own temp file:

```kotlin
val chunkSize = fileSize / parallel
coroutineScope {
    val jobs = (0 until parallel).map { index ->
        val startByte = index * chunkSize
        val endByte = if (index == parallel - 1) fileSize - 1L else (index + 1L) * chunkSize - 1L
        launch {
            var attempt = 0; var success = false
            while (attempt <= maxRetries && !success) {
                try {
                    if (attempt > 0) delay(500L * (1L shl (attempt - 1)).coerceAtMost(10_000L))
                    prepareRequest { url(url); header("Range", "bytes=$startByte-$endByte") }
                        .execute { res ->
                            if (res.status.value != 206) throw IllegalStateException("not 206")
                            // stream res.bodyAsChannel() into tempFiles[index], truncating
                        }
                    success = true
                } catch (e: Exception) {
                    attempt++
                    if (attempt > maxRetries) throw e
                }
            }
        }
    }
    jobs.forEach { it.join() }
}
// then: concatenate tempFiles in index order into `target`, delete the temp directory
```

## Traps

**A 2xx on the probe does not mean the server honoured the range — it usually means it ignored
it.** A server that supports ranges answers `Range: bytes=0-0` with **206** and a `Content-Range`
header; one that does not answers **200** with the entire file. Accepting any 2xx therefore reads
"ignored my range" as "supports ranges", and the mistake is only caught per-chunk, after the loop has
burned its retries on a server that was never going to comply. Gate on 206 or on `Content-Range`.

**Keep the per-chunk 206 check anyway.** Probe and real requests can disagree behind a cache or a
redirect, and without the check a server replying 200 to a ranged request hands each of the N jobs
the *whole* file — every job writes it in full and the merge produces a file N times too long, with
no error anywhere.

**One chunk failing must retry that chunk, not the file.** That is the entire reason to keep each
range in its own temp file: at 90% of a large download a dropped connection costs one chunk's worth
of bytes. The fallback path — a single request into the destination file — has the opposite property,
and its retry deletes the partial file and starts over: correct *there*, disastrous here.

**A chunk retry must rewrite from the chunk's first byte.** Reopen the temp file truncating, never
appending. If a first attempt wrote half a chunk and the retry appends the whole thing on top, that
chunk is one and a half chunks long — and the merge is a blind concatenation, so everything after it
shifts and the file is corrupt with no failed request anywhere. Inspect the sink call; watching a
download succeed proves nothing.

**Integer division loses the remainder, so the last chunk is special.** `fileSize / parallel`
truncates; the final range must end at `fileSize - 1`, not `parallel * chunkSize - 1`. Get it wrong
and trailing bytes go missing — a decode error at the very end of a media or archive file, long after
the download reported success.

**A progress send whose result is discarded is not a delivery.** `trySend` reports whether the value
was accepted; on a full buffer it is not. Dropping a progress tick is harmless — dropping the
**terminal** one is not, and a slow collector then misses the only signal that the download finished
while the file sits complete on disk. Express completion through the flow's own completion, and keep
the channel for progress alone.

**Chunk-granularity progress moves in N steps and does not reach the end.** Reporting
`completedChunks * chunkSize / fileSize` jumps in quarters and, because `chunkSize` was truncated,
tops out just below 1.0 — the "sticks at 99%" symptom, usually patched by rounding instead of fixed.
Count bytes across chunks if the bar matters, and make the counter atomic or two chunks finishing
together count once.

**Parallelism has a floor and a ceiling, both worth a constant.** Below the threshold the two probe
round trips cost more than the concurrency saves — and the gate is twice a *fixed* floor constant,
not twice the per-chunk size the code derives from the file. Above it, more connections stop helping
once the link is saturated and start hurting on mobile networks and hosts that throttle per connection.

**The failure path owes you two things: a clean temp directory and the throwable.** Clean the
directory in the catch as well as after the merge, or a cancelled download leaves chunks behind on
every attempt. And do not capture the exception into a variable, emit a terminal "finished, progress
0", then never read the variable again — the collector cannot distinguish a failure from a zero-byte
success, and the log is empty because the exception went nowhere. Note also what this design does
*not* buy: the temp directory is created and removed inside one call, so nothing resumes across a
process restart — resume means keying it to the URL and re-probing, a different feature.

## Verifying it

```bash
grep -rn 'header("Range"' --include='*.kt' . | grep -v '/build/'
grep -rn 'PartialContent\|!= 206\|== 206' --include='*.kt' . | grep -v '/build/'
grep -rn 'trySend(' --include='*.kt' . | grep -v '/build/'
grep -rn 'trySend(' --include='*.kt' . | grep -v '/build/' | grep -cE 'isSuccess|isFailure|getOrNull'
```

The first two go together: expect one `Range` hit for the probe and one for the chunk request, plus
at least one 206 comparison. A probe with no matching 206 check anywhere is the false-positive trap
above, unguarded. The third lists every progress send; the fourth counts how many inspect the result
— **0** against a non-empty third list means no send is checked anywhere, so find the terminal one in
that list and confirm completion does not depend on it.

For the chunk-boundary trap the cheap test is arithmetic, not a download: pick a file size not
divisible by the chunk count, compute every `startByte`/`endByte` pair, assert they tile
`0..fileSize-1` with no gap and no overlap. The bare client this runs on is described in
`ktor-kmp-client-architecture` — attaching a verbose logging plugin here is that skill's first trap.
