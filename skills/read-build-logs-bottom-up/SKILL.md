---
name: read-build-logs-bottom-up
description: Read a build log by going to the bottom for the verdict and then to the FIRST error marker for the cause — never a fixed-size window from either end, because the causal message and the failure banner sit at opposite ends of the output. Use when a background build finishes and you are about to summarise it, when a log says only "task X FAILED" with no reason, or when a filter came back empty and you are about to call that a clean build.
---

# Read build logs bottom-up, then jump to the first error

Build tools print in causal order and report in reverse. A Kotlin/Gradle-style run puts the
compiler's own diagnostics (`e: file.kt:42:9 Unresolved reference`) near the **top**, then the
task list, then the summary banner (`BUILD FAILED in 2m 31s`) at the **bottom**. The two pieces
you need are therefore as far apart as they can be, and no fixed-size window from either end
contains both.

`tail -40` on that log shows `> Task :app:compileKotlin FAILED` and the banner. It does not show
what failed to compile. The usual result is a second full build, purely to see a message that was
already on disk.

The reading order that works: **bottom for the verdict, then the first error marker for the
cause.** Never a fixed N.

## The recorded case

In a multiplatform media app, this was raised repeatedly with the same automated assistant and
kept recurring. Two distinct failures were recorded:

- `tail -20` on a finished background build showed `compileAndroidMain FAILED` and nothing else.
  The `e:` lines naming the file and the reason were hundreds of lines above the window. Cost: one
  more full build.
- A narrow filter matched nothing. Empty output from a filter and empty output from a clean build
  are the same bytes on the terminal, and a success was very nearly reported for a failed run.

The second one is the more dangerous of the two, because it produces a confident wrong answer
instead of a slow right one.

## Traps

**`tail -N` with any fixed N.** There is no N that is correct, because the distance between the
banner and the first diagnostic depends on how many tasks ran. Use the verdict line to decide
whether to read further, then search for the marker — do not scroll.

**Concluding "no errors" from an empty filter.** A filter can return nothing because the log is
clean, because the pattern is wrong, because the tool uses a different marker (`error:` rather
than `e:`), because the log path was wrong, or because the file is empty since the process was
killed before writing. Four of those five are failures. Always read the verdict line explicitly
before drawing any conclusion from a filter.

**Reading only the last error.** The compiler often reports one real problem and then a cascade
of consequences. The **first** error marker in file order is usually the cause; the last is
usually the echo. Fixing the echo produces a rebuild that fails identically.

**Filtering for errors and dropping the warnings.** Warnings are where deprecations, version
skews and "this will be an error in the next release" notices live, and a run can succeed while
telling you it is about to stop succeeding. When you filter, keep the error marker, the warning
marker, and the verdict line in the *same* pattern, so one pass gives you all three.

**Trusting the process exit status through a pipe.** A pipeline reports the status of its last
stage, so `build | tee log` and `build | grep …` both return the status of `tee` or `grep`, not of
the build. Two facilities keep the build's own: the pipeline-status array (`${PIPESTATUS[0]}` in
bash, `$pipestatus[1]` in zsh) read immediately after it, or `set -o pipefail`, which fails the
pipeline itself — and which inverts the behaviour above for anyone who already has it set.

**Believing the last line is the summary.** Wrappers, daemons, notifiers and shell hooks append
their own output after the banner, so "the last line" may be a daemon notice. Search for the
verdict, do not assume its position.

**Reading a stale log.** A log path reused between runs looks fine and describes the previous
attempt. Check the file's modification time against when the run started before you read a word
of it.

**Summarising a log you only filtered.** If you are about to tell someone what happened, you need
to have seen the verdict line yourself. A summary assembled from grep hits is a summary of the
pattern, not of the run.

## Verifying it

Set `LOG` to the file the run wrote, then work down this list in order. Every command below is
runnable as written once `LOG` is set.

```bash
LOG=build.log
```

1. **Confirm the log belongs to this run**, not the previous one:

   ```bash
   ls -l --time-style=full-iso "$LOG"; wc -l "$LOG"
   ```

2. **Read the verdict — from the bottom, but searched, not sliced:**

   ```bash
   grep -nE 'BUILD (SUCCESSFUL|FAILED)|FAILURE:|Execution failed' "$LOG" | tail -5
   ```

   No match at all means the run did not finish. That is a third outcome, distinct from success
   and from failure, and it must not be reported as either.

3. **Jump to the first cause, not the last symptom** — errors *only*, so that warnings cannot
   crowd the cause out of the window:

   ```bash
   grep -nE '^e: |^error:|Caused by:' "$LOG" | head -5
   ```

   Pass condition: the first line printed is the cause. `head -5` is safe only because this
   stream holds nothing but error markers — fold the warning markers in and a run carrying
   twenty deprecations above its first `e:` fills the window with them and shows no error at
   all, under a heading promising the cause. No match is **not** "no errors": it means this tool
   marks them differently, so return to step 2's verdict and search for the marker it used.

4. **Sweep the warnings as their own pass**, deliberately separate from the cause:

   ```bash
   grep -nE '^w: |^warning:' "$LOG" | head -20
   ```

   This is the deprecation and version-skew pass — the one that tells you a build which succeeded
   today is about to stop succeeding. It is not where the failure is.

5. **Read around that first marker with real context** — line numbers from step 3, then:

   ```bash
   sed -n '1,120p' "$LOG"
   ```

   adjusting the range to bracket the first marker. If the log is small enough to read whole,
   read it whole; that is always the safe option.

6. **One pass that keeps all three signal families together**, for when you want a single
   command. Both spellings of each marker are in the pattern, for the same reason step 3 warns
   about — and it is uncapped, so nothing can push the cause off the end:

   ```bash
   grep -nE '^(e|w): |^error:|^warning:|FAILED|BUILD (SUCCESSFUL|FAILED)|Caused by:' "$LOG"
   ```

7. **Before claiming success**, confirm you actually saw the verdict line in step 2 with your own
   eyes. An empty result from steps 3, 4 or 6 is not evidence of anything on its own.
