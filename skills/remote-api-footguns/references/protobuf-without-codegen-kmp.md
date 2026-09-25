---
name: protobuf-without-codegen-kmp
description: Speak protobuf from shared Kotlin by annotating ordinary data classes with field numbers instead of generating a code layer — with the encoder setting that makes the bytes match a generated encoder, the equality override a byte-array field needs, and the conformance test that pins the equivalence. Use when a schema-driven protocol has to work on every target rather than only the JVM, when encoding a message with an absent nested field throws, or when round-trip tests pass while real peers reject the frames.
---

# Field numbers on plain data classes, no generated layer

A schema compiler emits code for one platform. In a multiplatform module that is fatal: the
generated types compile on the JVM and strand every other target, so the whole protocol layer ends
up behind `expect`/`actual` or duplicated. The alternative is to write the messages by hand and
carry the field numbers as annotations, letting the serialization library produce the same bytes:

```kotlin
// adapted — the message names, field names and numbering are placeholders; the mechanism is real
@Serializable
data class Frame(
    @ProtoNumber(1) val kind: String = "",
    @ProtoNumber(2) val body: ByteArray = ByteArray(0),
    @ProtoNumber(3) val packed: Boolean = false,
)

@OptIn(ExperimentalSerializationApi::class)
private val proto = ProtoBuf { encodeDefaults = false }
```

That deletes the entire adapter tier a generated layer needs — the `toProto` / `fromProto` functions
that bridge hand-written Kotlin models to generated builders — because there is now only one model.

## Traps

**`encodeDefaults = false` is not a preference, it is what the wire format means.** A field holding
its default is *absent* from a protobuf frame; that is what a generated encoder emits and what the
counterpart's decoder expects. Leave the flag at its default `true` and two things go wrong at once:
the bytes stop matching, and encoding any message with a null nested field fails outright with a
"null is not supported for optional properties" error. That second one is not an edge case — a
transport command with no attached item is the common shape, so *no* command can be sent at all and
the feature looks completely dead rather than subtly wrong.

**A byte-array property gives you identity equality, and your round-trip tests will lie about it.**
`data class` generates `equals` from the properties, and array properties compare by reference — so
two frames carrying identical bytes are unequal, and `assertEquals(frame, decode(encode(frame)))`
fails for a codec that is perfectly correct. Override `equals`/`hashCode` with `contentEquals` /
`contentHashCode` on that one property. The inverse mistake is worse and quieter: a test that
compares only the non-array fields passes while the payload is being dropped.

**Pin the byte-level equivalence with a conformance test, not a round-trip test.** A round trip
proves your encoder and your decoder agree with *each other*, which they will even if both are
wrong. What needs pinning is that the bytes match what the other implementation produces, so assert
on the tags: field 1 as a string starts the frame with `0x0A`, field 2 as bytes is `0x12`, field 3 as
a bool is `0x18`. A reordered number or a retyped field then fails a test instead of failing as
"cannot connect".

**Build one side of the test the way the peer builds it.** Encode the answer frame directly with the
serializer — envelope first, payload nested inside — rather than through your own `encode()`. Both
halves going through your own codec is how a decode path that is simply *missing* stays green: the
test never exercises it because the test never needs it. A message type your client only ever
receives is exactly the one with no encoding path, so it is exactly the one this catches.

**Compression below a threshold makes frames larger, so measure before enabling it.** A gzip header
alone is ten bytes and most protocol messages are a handful of fields; compressing everything costs
bytes and CPU on the majority of traffic. Gate it on a size threshold and negotiate it, and make
decompression failure fall back to the raw payload rather than throwing — the compressed flag is set
by the sender, so a frame you cannot inflate is more likely mislabelled than fatal.

**The annotation and the format are experimental API, and that opt-in is a real statement.** The
`@OptIn(ExperimentalSerializationApi::class)` on the codec is not boilerplate: the byte-level
behaviour this whole approach depends on is not covered by the library's compatibility promise. The
conformance test above is what turns a future library change from a silent wire break into a build
failure, which is the only reason the trade is safe to make.

**Sort out where the schema types are allowed to travel before the first one is written.** These are
ordinary Kotlin classes with no generated-code smell to warn people off, so they spread further than
generated types would — straight into view models if nothing stops them. Keep them behind the module
boundary and map at the data layer; `response-to-domain-flow` is the shape, and
`borrowed-wire-protocol-discipline` is why renaming one of them later is not an option.

## Verifying it

Everything above is checkable statically, and the checks are cheap enough to run on every schema
change:

```bash
grep -rl 'ProtoNumber' --include='*.kt' . | grep -v '/build/'
grep -rn 'encodeDefaults' --include='*.kt' . | grep -v '/build/' | grep -i proto
grep -rl 'ProtoNumber' --include='*.kt' . | grep -v '/build/' | xargs -r grep -l 'ProtoNumber.*ByteArray' | xargs -r grep -L 'contentEquals'
```

The first is the schema census. More than one file may appear — a response model elsewhere can use
the same annotation for an unrelated wire format — so read the list and know which file is the
protocol. The second isolates the protobuf encoder configuration from every JSON one in the tree
(those legitimately set the opposite value); the production encoder must read `false`. A **test**
encoder set to `true` is not a generated encoder imitating anything — a generated one *omits*
defaults, which is precisely what `false` means — so the only honest reason for such an instance is
exercising the decoder against frames that deliberately carry explicit defaults, and that reason
belongs in a comment beside it. If it is instead what builds the peer-shaped frame the trap above
asks for, that frame is not byte-faithful to anything the peer sends and establishes **no**
conformance, while still reading green. The third prints **nothing** when every schema class
carrying a byte-array field also overrides equality; a filename in that output is the round-trip
test that lies. Keep both `-r` flags — without them, a tree whose schema classes have no byte-array
field yet leaves the final `grep` with no file operand, so it prints the literal `(standard input)`,
which under the rule just given reads as a defect that is not there, and then blocks.

Then read the test file for two specific assertions: a raw tag byte, and one frame constructed
without going through your own encoder. A test suite with neither is a round-trip suite, and a
round-trip suite cannot fail for any of the reasons this skill exists.
