slug: BENCH-RESULTS-MISSING-FILES
round: 1
date: "2026-05-01"
commit_range: 514ee01..HEAD
findings:
  - id: F-1
    title: "Inline 'Result file:' references in subsections are not individually qualified"
    severity: info
    location: "benchmarks/BENCHMARKS.md:623,683,709"
    claim: "Three subsections (LongMemEval held-out 450, LoCoMo palace mode, MemBench) still phrase historical result filenames as `Result file: <name>` without an inline note that the file must be regenerated. The fix added clear 'not committed; regenerate via scripts' disclaimers in the Notes on Reproducibility (line 552), Results Files table (line 564), and trailing line 768, which globally cover these inline references. A reader who jumps directly to a specific subsection via the TOC could miss the disclaimers, but the acceptance criterion ('the doc accurately states results are not committed') is satisfied at the document level."
    decision: dismissed
  - id: F-2
    title: "Results Files table mixes hardcoded historical timestamps with one `<timestamp>` placeholder"
    severity: info
    location: "benchmarks/BENCHMARKS.md:566-583"
    claim: "Table rows for the original runs use specific dated filenames (e.g. `results_locomo_palace_session_top5_20260326_0031.json`) while row 578 uses `<timestamp>`. This is internally consistent — the dated rows document the exact filenames produced by the historical runs, and row 578 was the one previously using a `*` glob — but the mixed style could read as inconsistent on a quick skim. Header text above the table explicitly frames these as 'files produced during those runs', which resolves the ambiguity."
    decision: dismissed
totals:
  fixed: 0
  backlogged: 0
  dismissed: 2
fixes_applied: []
new_backlog: []
