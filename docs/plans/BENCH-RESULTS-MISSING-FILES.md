---
slug: BENCH-RESULTS-MISSING-FILES
goal: "Make benchmark documentation honest about absent historical raw result files."
risk: low
risk_note: "Docs-only update that qualifies file-availability claims; no benchmark scripts, result data, or scores change."
files:
  - path: benchmarks/BENCHMARKS.md
    change: "Replace claims that all historical raw result JSONL files are committed with an explicit availability note; qualify the Results Files table so absent LongMemEval/LoCoMo artifacts are marked unavailable or regenerable; remove path-like evidence claims for missing files such as results_aaak_full500.jsonl."
  - path: benchmarks/README.md
    change: "Mirror the availability wording so the quick benchmark overview no longer states that results_*.jsonl files are present when none are committed."
acceptance:
  - id: AC-1
    when: "running `find benchmarks -maxdepth 1 -type f -name 'results_*.jsonl' -print` in the repo"
    then: "`benchmarks/BENCHMARKS.md` and `benchmarks/README.md` state that historical JSONL raw results are not currently committed and must be regenerated or sourced separately; neither doc claims all raw JSONL results are committed"
  - id: AC-2
    when: "running `rg -n 'All raw results are committed|Every result JSONL file in .*results_\\*.jsonl|Full results: .*results_aaak_full500\\.jsonl' benchmarks/BENCHMARKS.md benchmarks/README.md`"
    then: "the command returns no matches"
  - id: AC-3
    when: "running `find benchmarks -maxdepth 1 -type f \\( -name 'results_*.json' -o -name 'results_*.jsonl' \\) -print | sort`"
    then: "each committed result file listed by the command is either named in the docs as committed/auditable, or explicitly outside the historical LongMemEval/LoCoMo raw-result set"
  - id: AC-4
    when: "inspecting the Results Files table in `benchmarks/BENCHMARKS.md`"
    then: "wildcard rows such as `results_locomo_hybrid_session_top10_*.json` are not presented as existing committed files unless matching files are present"
out_of_scope:
  - "Regenerating or committing historical LongMemEval/LoCoMo raw result files"
  - "Changing benchmark scripts, benchmark scores, or methodology caveats other than file-availability wording"
  - "Re-running benchmarks or validating numeric claims"
---

## Design Notes

- Choose option B from the backlog task: document the missing artifacts instead of fabricating or regenerating historical result files during a small docs task.
- Treat `benchmarks/BENCHMARKS.md` as the canonical benchmark narrative and `benchmarks/README.md` as the short overview that must not contradict it.
- Keep the existing benchmark score tables, but add artifact availability semantics: committed files get exact paths; historical missing artifacts are labeled as unavailable/not committed; wildcard rows are qualified unless a matching file exists.
- The AAAK caveat can keep the 84.2% regression statement, but it must not cite `benchmarks/results_aaak_full500.jsonl` as an inspectable committed artifact while that file is absent.
- Do not add empty placeholder result files. Empty or synthetic JSONL artifacts would make the audit trail worse than an explicit availability note.
