slug: WATCH-RUN-READINESS-DIAGNOSTICS
round: 1
date: 2026-06-16
commit_range: 1b9b3e5..HEAD
findings:
  - id: F-1
    title: "UP017 lint: use datetime.UTC alias instead of timezone.utc in _make_run_id"
    severity: low
    location: "mempalace_code/watcher.py:211"
    claim: >
      _make_run_id imported `timezone` and used `timezone.utc`. ruff UP017 requires the
      Python 3.11+ `UTC` alias (`from datetime import UTC, datetime`) since pyproject.toml
      targets py311. This causes `ruff check` to exit non-zero, failing the CI lint gate.
    decision: fixed
    fix: "Changed `from datetime import datetime, timezone` and `datetime.now(timezone.utc)` to `from datetime import UTC, datetime` and `datetime.now(UTC)`."

  - id: F-2
    title: "No test coverage for watch_all backup-failure state path"
    severity: low
    location: "mempalace_code/watcher.py:786-793"
    claim: >
      The `pre-watch-backup-failed` state in `watch_all` is structurally identical to the
      `watch_and_mine` path, but only the `watch_and_mine` path is tested (AC-2 / VER-2).
      A regression in the `watch_all` backup-gate branch would go undetected by the current
      test suite.
    decision: backlogged
    backlog_slug: WATCH-ALL-BACKUP-FAIL-TEST

  - id: F-3
    title: "optimize-skipped state paths (reason=backup-gate, reason=error) have no direct tests"
    severity: info
    location: "mempalace_code/watcher.py:336-340"
    claim: >
      Only the `optimize-completed` state is covered by `test_successful_watch_startup_emits_run_marker_and_ready_states`.
      The `optimize-skipped reason=backup-gate` and `optimize-skipped reason=error` branches
      rely entirely on the existing `TestOptimizeOnce` unit tests (which verify the text output
      of `_optimize_once` but not the state string it returns to the startup caller). If the
      `elif outcome == "skipped:backup-gate":` branch were broken, no test would catch it.
    decision: dismissed
    fix: ""

  - id: F-4
    title: "initial-mine-failed state not emitted when _run_initial_mine_with_recovery returns None"
    severity: info
    location: "mempalace_code/watcher.py:320-322"
    claim: >
      When the initial mine fails unrecoverably, `sys.exit(1)` is called without emitting
      a machine-readable failure state. An operator grepping the log cannot distinguish
      "mine still in progress" from "mine failed and daemon exited" — both leave the log
      with `state=initial-mine-started` but no completion state. Per plan design notes and
      BACKUP_RESTORE.md, absence of `watch-ready` is the intended signal; no `initial-mine-failed`
      state was specified.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 1
  dismissed: 2

fixes_applied:
  - "Fixed UP017 lint error in _make_run_id: replaced `from datetime import datetime, timezone` / `datetime.now(timezone.utc)` with `from datetime import UTC, datetime` / `datetime.now(UTC)`."

new_backlog:
  - slug: WATCH-ALL-BACKUP-FAIL-TEST
    summary: "Add test for watch_all pre-watch-backup-failed state path"
