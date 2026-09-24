---
name: ci-flaky-timing-luck
description: Find and fix CI steps that only ever passed by timing luck — an asynchronous detach of a same-name mounted volume colliding with the next iteration's mount, and a downloader that quietly saves an error page as the artifact; reach for it when a step that ran green for months starts failing after a runner image update, or when a job succeeds and something minutes later fails on a corrupt or empty file it was handed.
---

# Steps that passed by timing luck

Two failures with the same shape, both from a release pipeline:

- A loop wrapped one disk image per architecture. Each iteration mounted a volume under the **same
  name**. Releasing a volume is asynchronous, so the next mount either failed as busy or — worse —
  quietly mounted under a suffixed name while the script kept writing to the hardcoded path.
- A build step downloaded a native archive through the standard library's URL stream. The download
  answered with a redirect to a mirror; on a cross-protocol redirect the stream API saved the
  **error page body** as the target file and returned normally.

Neither is a race you introduced. Both are steps that were **always wrong** and were being covered
by how fast the machine happened to be. A runner image update changes the timing, and they start
failing — which is why the commit that "breaks" them is usually unrelated.

**The expensive shape is not "fails intermittently", it is "succeeds while producing the wrong
artifact."** A hard failure costs one re-run. A step that reports success and hands the next job a
zero-byte file, an error page, or an empty mount point costs an afternoon, and the traceback points
somewhere it did not come from.

## Traps

**Never hardcode a mount point — capture the one the tool reports.** The tool tells you where it
actually mounted; a name collision changes that answer and nothing else warns you:

```bash
# adapted — condensed from the wrapping script, names genericised
MOUNT_POINT="$(hdiutil attach -nobrowse -noautoopen "$RW_DMG" 2>/dev/null \
  | grep -Eo '/Volumes/.*$' | tail -1 || true)"
[[ -d "$MOUNT_POINT" ]] || { echo "Could not mount $RW_DMG" >&2; exit 1; }
VOL_NAME="$(basename "$MOUNT_POINT")"
```

Everything downstream then derives from `$MOUNT_POINT` and `$VOL_NAME`. A script that writes to
`/Volumes/<Name>` after a silent remount to `/Volumes/<Name> 1` writes into the *previous*
iteration's volume and produces an output missing whatever it thought it added.

**Clean up before you start, not only after you finish.** The previous iteration's cleanup may not
have completed, and a cleanup you run only at the end never runs at all if the body failed:

```bash
# adapted — condensed from the wrapping script, names genericised
detach_stale_volumes() {
  for v in /Volumes/<Name> /Volumes/<Name>\ *; do
    [[ -e "$v" ]] && hdiutil detach -force "$v" >/dev/null 2>&1 || true
  done
}
detach_stale_volumes
for attempt in 1 2 3 4 5; do
  MOUNT_POINT="$(hdiutil attach … | grep -Eo '/Volumes/.*$' | tail -1 || true)"
  [[ -d "$MOUNT_POINT" ]] && break
  detach_stale_volumes; sleep 3
done
```

Note the glob covers the suffixed names too — those are exactly the leftovers a previous collision
created.

**Force and retry the release as well.** The next iteration starts from whatever this one left
behind, so a best-effort detach at the end of the body is worth a short retry loop.

**Prefer a downloader that fails loudly on HTTP errors.** The stdlib stream API does not follow a
redirect that switches protocol — it hands back the redirect response itself, and copying that
stream saves the redirect's own HTML page to disk under the artifact's filename. The download looks
like it worked; the checksum is the only thing left to catch it. An external downloader with
explicit flags fails instead:

```kotlin
// adapted
ProcessBuilder(
    "curl", "-fsSL",          // --fail: non-zero on HTTP errors instead of saving the error body
                              // -L: follows redirects across protocols and mirrors
    "--retry", "5", "--retry-delay", "5",
    "--retry-all-errors",     // plain --retry does NOT cover a mid-transfer receive failure;
                              // it retries only HTTP 5xx/408/429 and connection errors
    "-o", target.absolutePath, url,
).inheritIO().start().waitFor()
```

**Check the result even after a zero exit, and delete the partial file.** Otherwise an empty or
truncated download is cached and every retry reproduces it:

```kotlin
check(exit == 0 && target.exists() && target.length() > 0) {
    if (target.exists()) target.delete()
    "download failed (exit $exit) for $url"
}
```

**Mirrors are a lottery, so verify content rather than trusting the source.** A release URL can
redirect to a different mirror on every request. Pair the download with a digest check against a
value pinned in your source — that is the only assertion that survives a mirror serving something
else.

**A cached artifact is a cached failure.** Any caching layer in front of a download will happily
preserve a bad file forever. Make the failure path delete, and make the cache key include whatever
identifies the *publication*, not just the version.

## Verifying it

Timing-luck steps have tells you can grep for. In shell steps and build scripts, look for:

```bash
grep -rn 'Volumes/\|/mnt/\|/tmp/[a-z-]*/' --include='*.sh' --include='*.yml' scripts .github
grep -rn 'openStream\|URL(\|readBytes()' --include='*.kts' --include='*.gradle' .
grep -rn 'sleep ' --include='*.sh' --include='*.yml' scripts .github
```

- a fixed path where a tool reports its own,
- a stdlib fetch where an HTTP error is possible,
- a bare `sleep` standing in for a condition — it is a timing assumption with a comment missing.

Then ask of each: **if this step did the wrong thing, would the job still be green?** Every yes is
a place to add an assertion on the artifact — its existence, its size, its type, its digest — right
where it is produced, rather than letting a later job discover it.
