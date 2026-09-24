---
name: macos-codesign-sidecar-strip
description: Strip the `._*` companion files that macOS archiving writes beside files carrying extended attributes, after unpacking anything into a macOS app bundle and before the bundle is signed, because the signer seals those companions as ordinary bundle members and the OS deletes them the first time the file manager touches the app. Use when a signed macOS app launches fine on the build machine but users are told it is damaged and can't be opened, or when signature verification reports a sealed resource missing.
---

# Strip the `._*` companions before signing a macOS bundle

macOS stores extended attributes on files. When a file with attributes is written into an archive
format that has no place for them, macOS writes them out as a **companion file named `._<name>`**
sitting next to `<name>`. Unpack that archive and both files land on disk.

If they land inside an app bundle **before** it is signed, the chain that follows is unavoidable:

1. The signer walks the bundle and treats each `._name` as an ordinary bundle member — it signs
   them and lists them in the bundle's signature manifest (`_CodeSignature/CodeResources`).
2. The user unzips the app, or drags it out of a disk image. The moment the file manager touches
   it, macOS folds each `._name` back into the extended attributes of `name` and **deletes the
   companion**.
3. The launched bundle is now missing members its own seal still expects. macOS reports the app
   as damaged and refuses to open it; strict signature verification says a sealed resource is
   missing or invalid.

The build machine never sees step 2, because the freshly built `.app` was never archived and
re-expanded. This is why the app that shipped is broken while the identical app on the builder
launches.

macOS is the only platform affected: it is the one that seals the whole app directory and
re-checks that seal at launch. The same companion files inside a Linux or Windows payload are
inert clutter.

## Where the strip goes

In the task that **unpacks** third-party or prebuilt payloads into the tree the packager will
sign — after the unpack, before the packaging step runs:

```kotlin
// adapted — after unpacking a prebuilt native slice into `target`
val companions = target.walkTopDown()
    .filter { it.isFile && it.name.startsWith("._") }
    .toList()
companions.forEach { it.delete() }
if (companions.isNotEmpty()) {
    logger.lifecycle("stripped ${companions.size} attribute companions from $slice")
}
```

Strip **unconditionally, on every payload**, not just the macOS ones. What creates the companions
is the machine that *packed* the archive, not the platform it targets: a Linux or Windows payload
packed on a Mac carries them too, and will be unpacked into a macOS bundle by whichever build
happens to need it.

## Traps

**It reads as tidiness, so it gets deleted in cleanup passes.** A `filter { name.startsWith("._") }`
with no comment looks like housekeeping. Say in the comment that it is a correctness fix and name
the symptom it prevents, or the next cleanup removes it and the failure returns three releases
later, on user machines only.

**Stripping after signing does not fix it — it causes the same failure.** The seal is a list of
members. Removing a sealed member by hand is indistinguishable, to the verifier, from macOS
removing it. The strip must happen before anything signs the tree.

**The build-machine test proves nothing.** Launching the `.app` straight out of the build
directory skips the only step that triggers the deletion. A real test has to include the round
trip: archive it or attach the disk image, expand or drag the app out **in the file manager**,
then launch.

**Preventing them at pack time is not a substitute.** The archiver on the packing machine may
offer a way to omit them, but the payload you unpack is often built elsewhere, by someone else,
on unknown settings. Strip at unpack time regardless — it costs a directory walk.

**The companions usually carry nothing you want.** In the case above they held only provenance
attributes. Confirm rather than assume for your own payload before deleting: read the attributes
of one file (`xattr -l <file>`) and decide whether anything there has to survive. If something
does, it belongs in your build inputs, not in a sidecar the OS will delete.

**The user-facing error blames the app, not the archive.** "Damaged and can't be opened" reads
like a corrupt download, so it is usually chased as a notarization or transfer problem. The
distinguishing evidence is that verification names a *missing sealed resource*, not an invalid
signature.

## Verifying it

1. **Before signing**, the staged tree must be clean:
   `find <staged-tree> -name '._*'` → prints nothing. Wire this as a hard check in the build if
   the payloads come from outside your repo.
2. **On the built bundle:**
   `codesign --verify --deep --strict --verbose=2 <App>.app`
3. **On a round-tripped copy** — the test that matters: archive the app, expand it in the file
   manager, run the same verification, then launch it. A pass on the build directory and a
   failure here is exactly this bug.
4. If it fails, list what the seal expects against what is on disk; every difference will be a
   `._*` path.
