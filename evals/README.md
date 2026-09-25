# Evals

Thirteen cases for `claude plugin eval`: twelve questions a Kotlin developer might ask, each written
from one trap file, plus one unrelated Python task that checks the plugin stays out of work that is
not its own. Every case runs twice, with the plugin and without it, and the difference is the
measure of what the corpus adds.

```bash
claude plugin eval . --runs 3 -j 6 --judge-model claude-sonnet-5
claude plugin eval . --case vacuum-readonly --runs 1     # one case, one run per arm
```

Each trap case carries one scored grader and two indicators:

- `names-the-mechanism-and-fix` (scored, both arms): an LLM judge checks that the answer names the
  mechanism the trap describes and prescribes its fix. The criteria come from the trap file.
- `plugin-fired` and `opened-the-trap` (plugin arm only, not scored): did the agent load the area
  skill, and did it open the right trap file?

Use a Sonnet judge. In the first trial the default judge failed a baseline answer that was
substantially correct, which would have inflated the difference.

## Results

Run on 2026-09-24 with Claude Code 2.1.281, three runs per arm and a `claude-sonnet-5` judge. The
agent under test was the session's default model. Cost: about $11 for the whole suite.

| Case | Trap | With | Without | Δ |
|---|---|---|---|---|
| `joiner-starts-behind` | `joiner-catches-up-by-asking` | 1.00 | 0.00 | +1.00 |
| `spinner-over-playing-audio` | `stateflow-conflation-inverts-state` | 1.00 | 0.00 | +1.00 |
| `vacuum-readonly` | `room-rawquery-readonly-vacuum` | 1.00 | 0.00 | +1.00 |
| `format-specifier-verbatim` | `string-resource-format-limits` | 1.00 | 0.00 | +1.00 |
| `service-stops-between-tracks` | `fgs-state-ended-trap` | 1.00 | 0.33 | +0.67 |
| `finder-path-lost` | `macos-lsenvironment-path-pin` | 1.00 | 0.67 | +0.33 |
| `slide-in-pops` | `slide-transition-defaults-to-half-a-height` | 1.00 | 0.67 | +0.33 |
| `double-inset-band` | `stacked-bars-double-consume-window-insets` | 1.00 | 1.00 | 0 |
| `first-period-delta` | `delta-absent-not-infinite` | 1.00 | 1.00 | 0 |
| `not-in-null-control` | `sql-not-in-nullable-trap` | 1.00 | 1.00 | 0 |
| `ok-but-discarded` | `api-ok-but-ignored` | 1.00 | 1.00 | 0 |
| `slider-thumb-pinned` | `control-range-must-cover-stored-values` | 1.00 | 1.00 | 0 |
| `unrelated-python-task` | none | 1.00 | 1.00 | 0 |

With the plugin, every trap case passed all three runs, the agent opened the right trap file in 36
of 36 runs, and the plugin stayed out of the Python task in 3 of 3. Without it, the mean score on the
twelve trap cases was 0.56.

What the table says, and what it does not:

- Five traps are ones the model already knows: its answers there are as good without the plugin.
  `not-in-null-control` was chosen as such a control.
- The four +1.00 cases are where the model, unaided, is confidently wrong. Its answers name a
  plausible but false mechanism: Room routing raw queries by return type, for example, or a
  compose-resources formatter that handles `%02d` and `%%`. The library's own source says
  otherwise. Its `StringResourcesUtils.kt` replaces only `Regex("""%(\d+)\$[ds]""")`.
- The cases were written from the traps, so they measure whether the corpus delivers its own
  lessons. They are not a sample of everyday Kotlin questions. Three runs per arm and an LLM judge
  make each score a signal, not a benchmark.
- `format-specifier-verbatim` and `slide-in-pops` were rerun after fixes: the area description had
  lost the words that route string-resource questions to it, and a criterion demanded the exact
  default lambda. The table shows the rerun.
