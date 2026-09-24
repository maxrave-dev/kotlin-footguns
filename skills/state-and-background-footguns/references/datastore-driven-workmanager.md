---
name: datastore-driven-workmanager
description: Drive periodic background work straight from the settings store, so a toggle or an interval change takes effect immediately without a restart. Covers combining several preference flows into one scheduling decision, the update-in-place enqueue policy that lets a changed interval actually change, cancelling by unique name on disable, and why the worker must re-read the same settings itself. Android only. Use when changing a backup or sync interval does nothing until reinstall, when work keeps running after the user turned it off, or when two schedules end up stacked.
---

# Settings flows as the scheduler

Android only. The settings store is the source of truth; the work queue is a projection of it.
One long-lived collector watches the preferences and (re)enqueues or cancels.

That is the shape to aim for, and it is worth knowing that the reference does *not* have it
everywhere: alongside the scheduler below, the launcher activity enqueues two more periodic works
of its own, one of them from a second settings collector on the activity's own lifecycle scope.
That second one is exactly the anti-pattern named just below the sample — a live example rather
than a hypothetical, and the first thing to look for in a codebase that already has a scheduler.

```kotlin
// adapted
suspend fun observeAndSchedule() {
    combine(
        settings.autoBackupEnabled,
        settings.autoBackupFrequency,
    ) { enabled, frequency -> enabled to frequency }
        .distinctUntilChanged()
        .collect { (enabled, frequency) ->
            if (enabled == TRUE) scheduleBackup(frequency) else cancelBackup()
        }
}
```

`collect` never returns, so this belongs on a scope that lives as long as the process — the
application object's own scope, launched once in `onCreate`. A screen-scoped or view-model
scope silently stops rescheduling the moment that screen goes away.

## The enqueue policy is the feature

```kotlin
// adapted
val request = PeriodicWorkRequestBuilder<BackupWorker>(intervalValue, intervalUnit)
    .setConstraints(
        Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .setRequiresBatteryNotLow(true)
            .build(),
    )
    .addTag(WORK_TAG)
    .build()

workManager.enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
```

The interval is a settings value, so every collect emission can carry a *different* period.
`UPDATE` replaces the enqueued request's parameters in place, keeping the same unique name.

Disable is the mirror image, by the same name:

```kotlin
private fun cancelBackup() = workManager.cancelUniqueWork(WORK_NAME)
```

## Traps

**`KEEP` silently ignores your new interval.** With the keep policy an already-enqueued unique
work wins and the request you just built is discarded — no error, no log, and the user's new
"weekly" setting keeps running daily. It stays wrong until something cancels that unique name or
the app's data is cleared — changing the setting again will not do it. Use keep only where the
request is a constant that never varies; use update wherever any field comes from settings. Both
policies legitimately appear in one app, so read the policy argument at every call site rather
than assuming the codebase is consistent:
`grep -rn "enqueueUniquePeriodicWork" --include='*.kt' <src>`

**Unique work is identified by the name string, not by the worker class.** The schedule call and
the cancel call must use the *same* constant. Two nearby features that reuse one name will fight
over a single slot; two spellings of one name leak a schedule that nothing can cancel.

**Combine fires on either flow, including on re-emission of an unchanged value.** Without
`distinctUntilChanged` over the whole tuple, an unrelated write to the settings store re-enqueues
the work, and with some policies that resets the period — the run you were waiting for slides
into the future every time. Put the operator on the combined pair, not on each input.

**The worker must re-read the settings itself.** Cancellation is not retroactive against a run
already dispatched, and a periodic run can fire long after it was enqueued. The first thing the
worker does is read the same enabled flag and return success if it is off:

```kotlin
// adapted — first lines of doWork()
val enabled = settings.autoBackupEnabled.first()
if (enabled != TRUE) return@withContext Result.success()
```

Returning *success* here matters: this is "nothing to do", not a failure, so it must not consume
the retry budget. Reserve retry for a genuine failure of the work itself.

**Reading a setting inside the worker means the worker needs the settings store.** A worker is
constructed by the framework, so it gets its dependencies from a service-locator lookup or an
injected factory, not through its constructor.

**The platform enforces a minimum period.** A request below the documented floor is clamped, not
rejected — a "every 5 minutes" option in your settings screen becomes a lie at runtime. Validate
the settings values against the platform minimum where you build the request, or offer only
intervals above it.

**Constraints are part of the schedule, not of the work.** Requiring connectivity and
not-low-battery means the run is *deferred*, sometimes for a long time. Anything downstream that
assumes "it runs every 24 hours" is wrong; see `periodic-worker-dedup` for how to make a
notifier survive that.

## Verifying it

1. **Change the interval in the running app and confirm the enqueued request changed** — inspect
   the work by its unique name, or log the interval you built next to the policy you used.
   A schedule that never changes is the keep-policy trap.
2. **Toggle off, then force a run.** The worker's own re-read is what you are testing: with the
   feature off it must return success and do nothing.
3. **Check the collector's scope outlives everything**:
   `grep -rn "observeAndSchedule" --include='*.kt' <src>` — the launching scope should be the
   application's, created once.
4. Re-emit an unrelated preference and confirm no re-enqueue happens (log inside the collect).
5. Confirm schedule and cancel quote the identical name constant, not two string literals.
