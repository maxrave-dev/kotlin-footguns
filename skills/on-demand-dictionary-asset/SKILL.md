---
name: on-demand-dictionary-asset
description: A tokenizer, spellchecker or analyzer needs a multi-megabyte dictionary that would bloat every install for a feature most users leave off — fetch it once, on opt-in, into a plain directory, and make every consumer ask the filesystem "am I ready" rather than trust a flag. Use when a per-language asset inflates a package on only one target, when a half-downloaded asset must never look installed, or when a feature stays broken even after its download reports success.
---

# On-demand dictionary asset

A ~13 MB Japanese tokenizer dictionary (eight `.bin` files) is worth excluding from the Android
APK and fetching on demand; the same code on desktop keeps shipping it on the classpath, because a
desktop install is not counted in megabytes the same way. One expect/actual seam carries the whole
feature across that split:

```kotlin
// adapted — each function's KDoc is elided; the three signatures are verbatim
expect object RomanizationDictionaryPack {
    fun configure(directoryPath: String)
    fun isReady(): Boolean
    suspend fun download(): Result<Unit>
}
```

Android's actual does real work against a directory under `filesDir`. Desktop's and iOS's actuals
are one-liners — `isReady() = true`, `download() = Result.success(Unit)` — because neither platform
ever has anything to fetch. Modeling "nothing to do" as a trivially-true actual, rather than never
calling the pack on those platforms, is what lets the repository above it stay free of platform
branches.

## Traps

**Readiness is re-derived from disk, never cached as a flag.** `isReady()` checks that all eight
expected files exist and are non-empty — `File.length() > 0` covers "missing" and "empty" in the
same call — instead of consulting a persisted "did the download succeed" bit. A stored flag can
desync from disk (a user clears app storage, an install is restored without app-private files); a
filesystem check cannot.

**Never let a half-installed directory answer `isReady()` as true.** The eight files are streamed
into a `.staging` directory *beside* the final one — same parent, so the same filesystem — verified
complete, then the old directory (if any) is deleted and the staging one takes its place with a
single `renameTo`. The real directory is therefore never *observed* partially populated — absent,
the previous install, or the new one, never three of eight files — so `isReady` can never lie about
it. A crash or a kill between the delete and the rename does leave the directory absent rather than
restored, but `download()` re-runs cleanly from there: nothing about the next attempt is confused by
the one that died mid-swap.

**Integrity has two tiers, cheapest first.** The archive's URL, expected byte count and SHA-256 are
three constants declared together — "the one place the pack's identity lives." A declared
`Content-Length` that disagrees with the expected size aborts *before* the transfer, because at a
pinned URL a different size already proves it is the wrong file; only then does the code pay for
streaming the bytes and hashing them, never buffering the whole archive in memory to do it.

**A whitelist-only archive reader, even for an archive you publish yourself.** Every entry name has
its directory part stripped to a basename first, and only a basename on the eight-name whitelist is
ever opened for writing — so an entry whose name encodes a path elsewhere is written safely, confined
to the staging directory, not skipped; only a basename that isn't one of the eight (a pax header, a
directory, a platform sidecar file) is skipped by size, never opened for writing. Trusting the
archive's own shape because you control the publish step is the assumption that stops holding the day
a build step changes what goes into it. `parallel-chunked-download` covers the adjacent large-download
ground — many chunks and resumability, where this skill stops at one archive, verified once.

**A lazily-built consumer must not memoize a swallowed failure as a permanent one.** Building the
tokenizer from the installed files can fail (mid-download, a corrupted file), and the naive
`by lazy { runCatching { build() }.getOrNull() }` gets this wrong: Kotlin's `lazy` only re-runs its
initializer if that initializer *throws*. A block that catches its own exception and returns `null`
completes normally, so `lazy` stores that `null` exactly as it would store a real `Tokenizer` —
forever, for the rest of the process. The fix is a manual cache that only assigns on success:

```kotlin
// adapted — the comment explaining why only success is cached is elided (it is above, in prose)
@Volatile
private var tokenizer: Tokenizer? = null

private fun tokenizerOrNull(): Tokenizer? {
    tokenizer?.let { return it }
    val directory = RomanizationDictionaryPack.dictionaryDirectory ?: return null
    if (!KuromojiDictionary.isReady(directory)) return null
    return synchronized(this) {
        tokenizer ?: runCatching { KuromojiDictionary.buildTokenizer(directory) }
            .getOrNull()
            ?.also { tokenizer = it }
    }
}
```

Without this, a feature that fails once during a slow first download stays failed after the
download finishes — until the process restarts and `by lazy` gets a fresh, unpoisoned instance.

**Gate the feature, not the selection.** The setting lets a user pick the language immediately;
nothing blocks the choice on the download finishing. The romanizer call itself answers `null` while
the pack is missing, which the rendering pipeline already treats as "show nothing extra" — so no
call site needs a special case for "not downloaded yet". Settings only *decorates* its own row with
the pack's state (downloading / failed) for the one language that has one to report.

**One download in flight, guarded where the download actually happens, not where it is requested.**
The repository wraps the fetch in a `Mutex`, and re-checks "already READY?" *after* acquiring it. A
cheap check before launching a coroutine avoids doing pointless work on a double-tap, but it is not
what makes concurrent calls safe — two coroutines can both pass that check before either updates
state. The lock, plus the re-check inside it, is what turns a second caller into a no-op instead of
a second fetch racing the first over the same staging path.

## Verifying it

Run from the `core` submodule root.

Confirm the identity constants travel together, so nobody edits one without the others:

```bash
grep -n "DOWNLOAD_URL\|ARCHIVE_SHA_256\|ARCHIVE_SIZE_BYTES" \
  service/lyricsService/src/androidMain/kotlin/org/simpmusic/lyrics/romanization/KuromojiDictionary.kt
```

Pass condition: all three are `private const val` declarations within a few lines of each other.

Confirm every platform answers the pack's three functions — a missing actual is a compile error, but
confirm none of them is a stub that silently does the wrong thing for its platform:

```bash
grep -rnE "actual (suspend )?fun (isReady|download|configure)\(" \
  --include="*.kt" service/lyricsService/src
```

Pass condition: the android file's bodies call into a real installer; the ios and jvm files each
return a constant `true` / `Result.success(Unit)` with a comment saying why nothing is needed there.

Confirm the lazy-cache trap does not regress: a plain `by lazy` around a `runCatching { }.getOrNull()`
is the shape to reject in review.

```bash
grep -rn "by lazy" --include="*.kt" service/lyricsService/src/androidMain | grep -i "getOrNull\|runCatching"
```

Pass condition: no output. Any hit is a consumer that will cache its own failure forever.
