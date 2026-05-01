slug: BENCH-DOTNET-CI-GATE
round: 1
date: 2026-05-01
commit_range: b11efe4..HEAD
findings:
  - id: F-1
    title: "JSON report is written before the gate triggers SystemExit"
    severity: info
    location: "benchmarks/dotnet_bench.py:476-490"
    claim: >
      The threshold gate (sys.exit(1) when R@5 < --fail-under-r5) runs AFTER
      json.dump writes the report. This is a load-bearing ordering choice: the
      workflow's `Upload benchmark report` step uses `if: always()` and depends
      on benchmarks/results_dotnet_bench_ci.json existing on disk even when the
      gate fails. Reordering to fail-fast before write would silently break the
      artifact path on regressions — exactly the case where the artifact is most
      valuable for diagnosis. Verified by tests/test_dotnet_bench.py:79
      (test_threshold_fail asserts out_path.exists() after SystemExit).
    decision: dismissed

  - id: F-2
    title: "argparse accepts negative or >1.0 thresholds for --fail-under-r5"
    severity: low
    location: "benchmarks/dotnet_bench.py:430-436"
    claim: >
      `type=float` lets `--fail-under-r5 -0.1` (gate never fires, silently
      disabling regression detection) or `--fail-under-r5 2.0` (gate always
      fires) pass without diagnostic. Realistically the value comes from the
      workflow's pinned `R5_THRESHOLD: "0.800"` env var, so misuse is bounded
      to direct CLI users — a misconfiguration there would be quickly caught
      by the gate output. Adding range validation is validation for a scenario
      that does not occur on the CI path; left as plain `float` per the
      project's "validate at system boundaries only when realistic" rule.
    decision: dismissed

  - id: F-3
    title: "Workflow lacks timeout-minutes and explicit permissions block"
    severity: info
    location: ".github/workflows/dotnet-bench.yml:11-18"
    claim: >
      The job has no `timeout-minutes:` (defaults to 360) and no `permissions:`
      block (defaults to repo-level token scope). The repo's existing
      `.github/workflows/ci.yml` also omits both — adding them only here would
      break style symmetry with the other workflows. The benchmark completes
      in ~5–10 minutes on a warm cache so the default timeout is acceptable
      headroom; the workflow only reads the repo and uploads an artifact, which
      the default token already covers.
    decision: dismissed

  - id: F-4
    title: "Test stub sets R@5 directly rather than deriving it from per_query hits"
    severity: info
    location: "tests/test_dotnet_bench.py:14-43"
    claim: >
      `_make_bench_results` writes `R@5: r5` literally and constructs per_query
      with `round(r5 * 20)` hits. The two are independent: a regression in
      run_bench's hit-counting arithmetic (sum / len) would not be caught by
      these tests because they monkeypatch run_bench entirely. This is the
      correct trade-off for a CLI/gate unit test (which is what's new in this
      task) — aggregation correctness is exercised by the live benchmark on
      the pinned CleanArchitecture corpus, which is a separate concern from
      the threshold-gate behavior these tests pin.
    decision: dismissed

totals:
  fixed: 0
  backlogged: 0
  dismissed: 4

fixes_applied: []

new_backlog: []
