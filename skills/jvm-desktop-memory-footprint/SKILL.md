---
name: jvm-desktop-memory-footprint
description: Judge and reduce a desktop JVM application's memory honestly — read the heap-to-footprint ratio rather than the resident figure, run the one experiment that separates a leak from an allocator holding idle pages, and understand why per-thread allocator arenas make the footprint depend on the user's core count. Use when a desktop app settles near a gigabyte or keeps climbing over a long session, when users on big machines report far worse memory than you can reproduce, or before tuning any allocator or garbage-collector flag.
---

# Desktop JVM memory: what the number means before you tune anything

A desktop JVM app that "uses 1 GB" is telling you almost nothing. The number to act on is the
**ratio of Java heap to total footprint**, and there is one experiment that decides which half of
the problem you have.

```
Heap small (say ~150 MB) but footprint large   -> native memory dominates; allocator territory.
Heap large, close to its cap                   -> a Java-side problem; start from heap info
                                                  and a heap dump. Allocator tuning will not help.
```

Take the reading **after a real session** — half an hour of ordinary use — not at startup. The
whole question is behaviour over time.

## The decisive experiment

Ask the allocator to hand idle memory back to the OS and measure the footprint on both sides.
One run, on one machine — the *shape* is the result, not the figures:

```
footprint before : 920 MB
malloc_trim(0)   : returns 1     <- the allocator says it released memory
footprint after  : 753 MB        <- handed straight back to the OS
```

**Memory that can be returned on demand was already free.** That result rules out a leak: nothing
was still referencing those pages; the allocator was simply keeping them. A leak would return
nothing.

Rule the obvious things out first, and write down how, so nobody re-investigates:

| Suspicion | How to disprove it |
| --- | --- |
| Java heap growing unbounded | Heap info while the footprint is high. A heap sitting far below its cap is not the cause. |
| Leaked native handles | Make them countable — if each handle owns a named thread, sample the thread names over 30 minutes. A flat count means they are released. |

## Why the footprint depends on the user's machine

The C library on Linux gives each contending thread its own allocator **arena**, up to a ceiling
of **8 × core count**, and never gives one back. A native media/decode path that allocates and
frees large buffers on every item, in a process with a hundred-plus threads, spreads those
allocations across every arena available. A four-core machine tops out at 32 arenas; a twenty-core
machine at 160. The other platforms cache per core too, they just scale less aggressively — and
the same symptom was reported on all three OSes (measured in detail only on one). **A symptom
identical on three platforms is itself the clue**: a bug in one platform's code would not present
that way.

## The levers, and what each actually does

| Lever | Where | Platforms |
| --- | --- | --- |
| Return idle pages when the app goes idle | app code, at the pause/idle transition | Linux, Windows |
| Let the collector uncommit unused heap | JVM options in the packaging config | all |
| Turn off the small-allocation zone | app property list / environment | macOS |
| Cap allocator arenas | launcher environment (`MALLOC_ARENA_MAX`) | Linux |

Every desktop allocator can be asked to return free pages; only the spelling differs
(`malloc_trim(0)` on Linux, the heap-optimize call on Windows). Bind them through the same
native-access layer you already use.

## Traps

**A heap cap bounds growth, not return.** Setting a maximum heap says nothing about handing
committed pages back. Measured mid-session, a collector held roughly twice as much committed as
was live.

**Free-ratio bounds without a periodic collection are a no-op.** The collector only uncommits at
the end of a concurrent cycle or a full collection, and an app that allocates very little never
runs either — the heap ratchets to its high-water mark and stays. The periodic-interval flag is
the load-bearing half, not decoration.

**Returning idle memory must only run while idle.** The call walks the heap holding the allocator
lock, so every thread that allocates — decoder threads included — blocks until it returns. Called
during playback or animation it is audible or visible. Trigger it on the pause/idle transition,
throttle it (once a minute is plenty), and dispatch it off the thread that services the UI.

**Do not aim the return-memory call at every registered zone on macOS.** Passing "all zones" also
asks the zones behind the graphics and compositing stack to give pages back. Run from a background
thread it can land inside a UI-transaction commit on the main thread, and on current macOS
releases (26 and later, where this was traced) the process stops hard. The window is narrow
enough that attaching a log stream hides it, so it only reproduces on a real file-manager launch. The macOS lever is the zone setting instead, so nothing is lost.

**A ceiling is not an allocation.** A large per-handle buffer limit looks like free savings.
Measure what is actually prefetched before lowering it — a limit that is never approached costs
nothing and lowering it only risks underruns.

**Relax an arena cap before removing it.** The cap trades memory for allocator lock contention.
Even a value several times the aggressive setting stays far below the default ceiling on a big
machine and keeps most of the benefit.

**Adding an environment dictionary to a packaged macOS app has a side effect on `PATH`.** If you
take the macOS lever, audit every external process the app spawns first.

## Verifying it

Read **heap and footprint together**, after ~30 minutes of use, and record the machine's core
count with them.

```bash
# Linux — footprint, heap, and the arena count
pid=$(pgrep -f <your-app> | head -1)
grep VmRSS /proc/$pid/status
jcmd $pid GC.heap_info
# arenas show up as anonymous mappings aligned to a 64 MB boundary
awk '/^[0-9a-f]/{split($1,a,"-"); if ($6=="") print a[1]}' /proc/$pid/maps |
  while read x; do python3 -c "print(1 if int('$x',16)%(64*1024*1024)==0 else 0)"; done | grep -c 1
```

```bash
# macOS
pid=$(pgrep -f <your-app> | head -1); ps -o rss= -p $pid; vmmap -summary $pid | head -25
jcmd $pid GC.heap_info
```

Then re-run the decisive experiment after each change: if the footprint still drops when idle
memory is requested, there is more to reclaim; if it no longer drops, the remaining footprint is
genuinely in use and further allocator tuning is wasted effort.
