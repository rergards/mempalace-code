slug: AUTOPILOT-DEMO-SCORECARD-METRIC-EXPANSION
round: 1
date: 2026-06-19
commit_range: f918a9e..HEAD
findings:
  - id: F-1
    title: "Stale committed scorecard artifacts after verify-fix commits added test lines"
    severity: medium
    location: "docs/quality/scorecard.md, docs/quality/scorecard.json"
    claim: >
      The verify-fix commits (attempt 1 and 2) added 167 lines to
      tests/test_quality_scorecard.py, which changed the test_total_lines count
      tracked in scorecard.json/scorecard.md. The committed artifacts were not
      regenerated after those commits, causing --check to report stale-artifact
      errors and three tests to fail: test_main_check_returns_zero,
      test_run_check_returns_zero_on_live_repo, and test_committed_artifacts_are_fresh.
    decision: fixed
    fix: "Ran `python scripts/quality_scorecard.py --write` to regenerate scorecard.md and scorecard.json with the correct test_total_lines (43595) and schema_version 2."

  - id: F-2
    title: "_count_test_functions lacks OSError guard unlike _count_class_test_methods"
    severity: low
    location: "scripts/quality_scorecard.py:280"
    claim: >
      In collect_demo_gates, cli_golden_count calls _count_test_functions(cli_golden_path)
      when cli_golden_present is True, but _count_test_functions has no OSError guard
      (only a SyntaxError guard via regex fallback). _count_class_test_methods does
      handle OSError. If the file exists but becomes unreadable between the .exists()
      check and read_text(), an OSError would propagate uncaught. In practice this
      path is unreachable today since test_cli_golden_scenarios.py does not exist,
      but the asymmetry is a latent hazard for when the file lands.
    decision: dismissed
    fix: ""

totals:
  fixed: 1
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "Regenerated docs/quality/scorecard.md and docs/quality/scorecard.json with `python scripts/quality_scorecard.py --write` to clear stale-artifact failures."

new_backlog: []
