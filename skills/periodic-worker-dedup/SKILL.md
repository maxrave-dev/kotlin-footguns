---
name: periodic-worker-dedup
description: Build a periodic notifier that never misses an item when a run is delayed, and whose only way to repeat one is a kill inside a single narrow window. Covers keeping the "already handled" record in the database rather than in the worker, scanning a time window deliberately wider than the scheduling interval so a skipped run catches up, and processing oldest-first so an interrupted run loses the newest item rather than a random slice. Android only. Use when users report duplicate notifications after a device restart, when items are missed while the device is idle, or when a first run floods the user with the whole back catalogue.
---

# A periodic notifier that misses nothing and repeats at most one item

Android only. A periodic worker gets two guarantees from the platform and neither is the one you
want: it will run *eventually*, and it will run *again*. It may also be killed halfway. So the
worker itself can hold no memory of what it has done.

Two independent conditions gate each item, and you need both:

```kotlin
// adapted
val items = parseFeed(fetch(FEED_URL))
val now = System.currentTimeMillis()

// Oldest first, so notifications arrive in the order the items were published.
items.sortedBy { it.publishedAt }.forEach { item ->
    val withinWindow = item.publishedAt > 0L && (now - item.publishedAt) <= WINDOW_MS
    if (withinWindow && !repository.isNotificationExists(item.link)) {
        notify(item)
        repository.insertNotification(item.toEntity())
    }
}
```

- **The window** bounds how far back you are willing to look.
- **The database check** is the only thing that keeps a run from re-notifying. It buys
  at-least-once delivery with one narrow duplicate window, not exactly-once — see the traps.

## Why both, and why the window is wider than the interval

```kotlin
// adapted — scheduled at 24h; the window is 48h
private const val WINDOW_MS = 48L * 60L * 60L * 1000L
```

Scheduling is best-effort. Doze, unmet constraints, a reboot, a user who left the device off —
any of these push a run past its slot, and the next run is then looking at a feed containing
items published while nobody was watching. Give the window room for at least one fully missed
run. Widening it costs nothing, because the database check is what prevents a second push.

Take the window away and a first install fires a notification for every item ever published.
Take the database check away and every run re-notifies everything still inside the window —
which, at a window twice the interval, means every item gets notified twice.

## Traps

**Worker state is not state.** The worker object is constructed fresh for each run, its process
can be killed between runs, and "last seen id" held in memory is gone. Anything that must survive
belongs in the database — which also means it survives the app being force-stopped, and can be
read by the screen that lists the same notifications.

**Key the dedup on a stable identifier, not on display text.** The link is the identity here, and
it is treated as such all the way up: an entry that parses with an empty link is dropped at parse
time rather than notified with a blank key. A title is what you show, and a title can be edited
upstream between two runs.

**Oldest-first is not cosmetic.** Two reasons, both real: notifications arrive in publication
order, and — because the loop notifies and records item-by-item — a run killed partway through
has handled the *oldest* items. The unhandled remainder is the newest, which is still inside the
window at the next run and gets picked up. Sort newest-first and an interruption strands the
oldest items right at the far edge of the window, where they may age out before the retry.

**Notify-then-record leaves a narrow duplicate window.** The record is written immediately after
the notification is posted; a kill between the two re-notifies that one item next run. Recording
*first* trades that for silently losing an item instead. Pick knowingly; do not assume the code
you inherited is exactly-once.

**An unparseable date must not become "now".** A failed date parse yields `0L`, and the window
test starts with `publishedAt > 0L`, so those items are skipped rather than treated as brand
new. Defaulting a bad timestamp to the current time is how a malformed feed entry notifies on
every single run forever.

**Retry the whole fetch, not individual items.** On an exception the worker returns retry and the
next attempt reprocesses the entire feed — which is safe precisely because of the database check.
This is the payoff for keeping dedup out of the control flow.

**The notification channel is created inside the loop, right before posting.** Channel creation
is idempotent, and doing it at the post site means a fresh process that starts inside the worker
(rather than in the launcher activity) still has a channel to post into.

## Verifying it

1. **Run the worker twice back-to-back** with no feed change. The second run must post nothing.
   Force it rather than waiting for the schedule.
2. **Delete the recorded rows and re-run.** Everything inside the window should re-post — that
   proves the database is genuinely the source of truth and the worker is not deduping some other
   way by accident.
3. **Set the device clock forward past one interval, or skip a run**, and confirm items published
   in the gap still arrive.
4. **Confirm the window really is wider than the interval**: the schedule lives at the enqueue
   site, not next to the constant. `grep -rn "PeriodicWorkRequestBuilder" --include='*.kt' <src>`
   and compare the period there against the worker's window constant. These two numbers are
   edited by different people at different times and drift apart silently.
5. Feed the parser an entry with a malformed date and an entry with no link, and confirm neither
   notifies.
