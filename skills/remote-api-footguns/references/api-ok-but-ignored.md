---
name: api-ok-but-ignored
description: A remote write can answer "ok" and still have discarded what you sent, saying so only in a secondary field riding along with the success. Model accepted-but-discarded as its own outcome, read that field on every write, and log a discard loudly. Reach for it when a submission reports success on every call and the data never appears on the other side.
---

# "ok" is a transport answer, not a semantic one

A write to a remote service has two independent verdicts, and most clients only read the first:

1. **Did the request arrive and parse?** — the HTTP status, the top-level `ok`/`error` field.
2. **Did the service keep what you sent?** — reported separately, or not at all.

Services that accept high write volumes routinely answer the first question with success while
answering the second with silence: the record is filtered, deduplicated, clamped, or dropped, and
the only trace is a small object nested inside the success body. A client that branches on the
status alone reports a perfect success rate while the other side stays empty.

Model the two verdicts as three outcomes, not as a boolean:

```kotlin
// adapted — names generalized
sealed interface WriteOutcome {
    data object Ok : WriteOutcome
    data class Ignored(val code: Int, val message: String) : WriteOutcome  // accepted, then discarded
    data class Error(val code: Int, val message: String) : WriteOutcome    // never accepted
}
```

Three states means a caller physically cannot collapse "kept" and "discarded" into one branch: the
`when` does not compile until it handles both.

## Traps

**The discard reason is nested under the item, not at the top level.** It rides *inside* the
per-record part of the success body, so a reader that stops at the envelope never sees it. Reach in
explicitly, and treat a missing field as "nothing reported":

```kotlin
// adapted — names generalized
private fun JsonObject.ignoredOrNull(): WriteOutcome.Ignored? {
    val ignored = this["<discard-field>"]?.jsonObject ?: return null
    val code = ignored.intOrNull("code") ?: return null
    if (code == 0) return null          // the service's "nothing was ignored" value
    return WriteOutcome.Ignored(code, ignored.stringOrNull("<text-field>").orEmpty())
}
```

**Zero usually means "fine", not "discarded for reason zero".** These fields are almost always
present on every response, carrying a neutral value on the happy path. Branching on presence rather
than on value turns every successful write into a false alarm, and the noise is what gets the check
deleted a month later.

**One record comes back as an object, several as an array.** Bodies translated from a
document format collapse a one-element list into a bare object. Read whichever arrived, or the
single-item case — the common one — silently skips the check:

```kotlin
// adapted — names generalized
val first = when (val entry = body["<items>"]) {
    is JsonArray -> entry.firstOrNull()?.jsonObject
    is JsonObject -> entry
    else -> null
}
return first?.ignoredOrNull() ?: WriteOutcome.Ok
```

**A discard is a metadata bug wearing a network bug's clothes.** The discard codes that matter are
the ones meaning "we did not like the name/identifier you sent" — those fire because *your* record
is malformed, on every submission of that record, forever. That makes the discard log the only place
a metadata defect ever becomes visible, so it belongs at warning level with the code and message in
it, next to the values that were sent:

```kotlin
// adapted — names generalized
is WriteOutcome.Ignored ->
    // A filtered name is how bad metadata surfaces — worth a loud log rather than a silent drop.
    Logger.w(TAG, "Write ignored (${outcome.code}): ${outcome.message}")
```

**Not every non-`Ok` outcome deserves the same handling.** Separate the three groups before writing
the branch, because they need opposite responses: *retryable* (rate limit, temporary outage — back
off and try again, see `retry-needs-backoff-and-cap`), *terminal for this credential* (the stored
session is dead — clear it and put the user back in front of the login entry), and *terminal for
this record* (filtered name, timestamp out of the accepted window — never retry, log and move on).
Retrying the third group is how a client earns a rate limit.

**Mint your own code for "the call never happened".** A request that failed before reaching the
service has no service code, and reusing `0` or a legal code makes the local failure indistinguishable
from a remote one. Use a value outside the range the service can produce — a negative code, where the
service's own are positive — and see `unknown-not-a-valid-score` for why that matters.

**Recorded history:** the source project's changelog records this as a finding from a live
integration — the reporting endpoint answered with a success status while discarding the submission,
and named the reason only in a side field, with the two metadata-filter codes logged loudly rather
than dropped. The record claims no rework beyond that, and in that client the check sits inside each
write method separately, which is the shape hazard worth carrying away: a write method added later
does not inherit it.

## Verifying it

Find every place success is decided from the envelope alone, then check each one against the
service's own documentation for a per-record verdict:

```bash
grep -rn "isSuccess\|== 200\|status ==\|\"ok\"" --include="*.kt" . | grep -v "/build/"
grep -rniE "ignored|rejected|discarded|partial(ly)?[ _]?accept" --include="*.kt" . | grep -v "/build/"
```

The second command is case-insensitive on purpose: the outcome type is capitalised and the log line
is not, so a case-sensitive pattern finds the log and misses the very type this skill tells you to
declare. It should hit both. If it hits neither, every write path in the tree is reporting transport
success as semantic success.

Then verify against the service, not against your own logs: submit a record with a deliberately
malformed name, confirm the client logs a discard rather than a success, and confirm the record is
absent on the other side. A client that logs success for that submission is the exact failure this
skill exists to catch, and no amount of local testing will show it.
