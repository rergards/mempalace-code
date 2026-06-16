---
slug: WATCH-RUN-READINESS-DIAGNOSTICS
goal: "Add grep-friendly watch startup run markers and readiness states so fresh daemon starts are distinguishable from stale appended failures"
risk: medium
risk_note: "Changes operator-facing daemon startup output on a reliability path, but leaves storage writes, watcher event filtering, and scheduler config unchanged."
files:
  - path: mempalace_code/watcher.py
    change: "Add a watch startup run id plus stable key-value state lines for watch_and_mine and watch_all startup transitions: run started, pre-watch backup failed, initial mine started/completed/skipped, optimize completed, and watch-ready."
  - path: tests/test_watcher.py
    change: "Add focused diagnostics tests for successful startup states, backup-failure states, stale appended log disambiguation, low-disk startup boundary behavior, and watch_all parity."
  - path: README.md
    change: "Document a short daemon health check combining launchd process state, palace health, the current run marker, and the latest watch-ready line from the appended daemon log."
  - path: docs/BACKUP_RESTORE.md
    change: "Document the startup state markers near watch pre-run backup and degraded recovery guidance, including how to separate a new run from older disk-budget or backup failures in the same log file."
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_successful_watch_startup_emits_run_marker_and_ready_states -q is run"
    then: "a successful single-project startup emits one run id and grep-friendly states for initial-mine-started, initial-mine-completed, optimize-completed, and watch-ready before entering the watch loop"
  - id: AC-2
    when: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_pre_watch_backup_failure_emits_failed_state_for_same_run -q is run"
    then: "a pre-watch backup failure exits before mine or watchfiles.watch, emits pre-watch-backup-failed with the same run id, and does not emit watch-ready"
  - id: AC-3
    when: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_latest_successful_run_is_distinguishable_from_stale_appended_failures -q is run"
    then: "a synthetic appended log containing older disk-budget and backup-failure lines plus a newer success can identify the latest watch-ready run id without treating stale failures as current"
  - id: AC-4
    when: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_low_disk_startup_skip_keeps_run_id_and_ready_boundary -q is run"
    then: "when disk budget blocks the initial mine, the skipped state is tied to the current run id and the later watch-ready line remains tied to that same startup attempt"
  - id: AC-5
    when: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_watch_all_startup_uses_same_run_state_format -q is run"
    then: "mempalace-code watch via watch_all uses the same run id and state format for multi-project startup readiness"
  - id: AC-6
    when: "rg 'WATCH_RUN|watch-ready|mempalace-code .*health|mempalace-watch.log|launchctl print' README.md docs/BACKUP_RESTORE.md is run"
    then: "operator docs show the stable log marker, latest watch-ready lookup, palace health check, daemon process-state check, and default appended log path"
out_of_scope:
  - "Changing LanceDB storage schema, backup retention, rollback mechanics, or disk-budget thresholds."
  - "Adding a new JSON status API or changing the existing watch status command beyond documentation that composes it with log and health checks."
  - "Changing launchd or cron scheduler snippets, including the default /tmp/mempalace-watch.log path."
  - "Backlog completion, archive metadata, or any docs/BACKLOG.yaml changes."
contract_policy:
  flow: full_spdd
  reason: "Standard reliability task for daemon startup diagnostics and operator recovery evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  approved_scope_expansions:
    - path: docs/quality/scorecard.json
      phase: polish
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      reason: "Generated quality scorecard refresh after task-owned watcher.py and tests/test_watcher.py changes; the JSON artifact is enforced by scripts/quality_scorecard.py --check and stays paired with docs/quality/scorecard.md."
    - path: docs/quality/scorecard.md
      phase: polish
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      reason: "Generated quality scorecard refresh after task-owned watcher.py and tests/test_watcher.py changes; the Markdown artifact mirrors docs/quality/scorecard.json."
  requirements:
    - id: REQ-1
      statement: "Every watch startup attempt must have a stable run marker that appears in emitted startup output and therefore in appended daemon logs."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: REQ-2
      statement: "Startup transitions must expose grep-friendly state names for backup failure, initial mine start/completion, optimize completion, and watch readiness."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-2, AC-4, AC-5]
    - id: REQ-3
      statement: "A newer successful startup must be identifiable in a log file that still contains older disk-budget or backup-failure output."
      source: "backlog acceptance"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Operators must have a documented health check that combines daemon process state, palace health, current run marker, and latest watch-ready evidence."
      source: "backlog acceptance"
      acceptance_ids: [AC-6]
    - id: REQ-5
      statement: "Failure output must remain useful and public-safe, with no new secrets, tokens, or private incident data in docs or tests."
      source: "backlog acceptance"
      acceptance_ids: [AC-2, AC-6]
  surfaces:
    - name: "Watcher startup diagnostics"
      kind: internal
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "watch_and_mine and watch_all emit stable WATCH_RUN key-value lines around startup only, so stdout/stderr and launchd's appended log identify the current startup attempt and readiness boundary."
    - name: "Watcher diagnostics tests"
      kind: internal
      paths: ["tests/test_watcher.py"]
      expected_behavior: "Mocked watcher tests prove success, fail-closed, stale-log, low-disk, and watch_all run-marker behavior without running a real daemon."
    - name: "Daemon operator docs"
      kind: cli
      paths: ["README.md", "docs/BACKUP_RESTORE.md"]
      expected_behavior: "Docs show how to combine watch status, mempalace-code health, and log grep/tail commands to determine whether the latest run reached watch-ready."
  invariants:
    - id: INV-1
      statement: "Steady-state watch event filtering, debounce timing, gitignore handling, scan-rule refresh, and re-mine behavior must not change."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-2
      statement: "Existing fail-closed startup behavior for pre-watch backup failure and unrecovered missing-fragment startup failures must remain intact."
      applies_to: ["mempalace_code/watcher.py", "tests/test_watcher.py"]
    - id: INV-3
      statement: "The scheduler's stdout/stderr routing to /tmp/mempalace-watch.log remains unchanged."
      applies_to: ["mempalace_code/watcher.py", "README.md"]
    - id: INV-4
      statement: "Docs and tests must use public-safe sample paths and must not add private hostnames, tokens, local user paths, or non-public incident details."
      applies_to: ["README.md", "docs/BACKUP_RESTORE.md", "tests/test_watcher.py"]
  risks:
    - id: RISK-1
      risk: "Free-form status prose could still be hard to parse reliably in appended logs."
      mitigation: "Use a stable prefix and key-value fields such as WATCH_RUN run_id=<id> state=<state>."
    - id: RISK-2
      risk: "A readiness marker could be emitted too early and hide a startup failure."
      mitigation: "Emit watch-ready only immediately before the watchfiles.watch loop would be entered, after backup and initial-mine gates complete or are explicitly skipped by disk budget."
    - id: RISK-3
      risk: "Run ids based on time or pid could make tests flaky."
      mitigation: "Isolate run id generation behind a small helper that tests can patch to deterministic values."
    - id: RISK-4
      risk: "Adding diagnostic output could make normal watch logs noisy."
      mitigation: "Emit only startup transition lines, not per-file or per-batch run metadata."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_successful_watch_startup_emits_run_marker_and_ready_states -q"
      proves: "Successful single-project startup emits the current run id and required readiness states before watching."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_pre_watch_backup_failure_emits_failed_state_for_same_run -q"
      proves: "Pre-watch backup failure is tied to the current run id and cannot be confused with a ready run."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_latest_successful_run_is_distinguishable_from_stale_appended_failures -q"
      proves: "A newer watch-ready line can be selected from an appended log even when older failures remain earlier in the file."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_low_disk_startup_skip_keeps_run_id_and_ready_boundary -q"
      proves: "The low-disk initial-mine skip boundary remains observable and associated with the same startup attempt that later enters watch mode."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_watch_all_startup_uses_same_run_state_format -q"
      proves: "The daemon-facing watch_all path uses the same startup marker and state vocabulary."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "rg 'WATCH_RUN|watch-ready|mempalace-code .*health|mempalace-watch.log|launchctl print' README.md docs/BACKUP_RESTORE.md"
      proves: "Operator docs include the run marker, latest ready-line lookup, palace health command, process-state command, and log path."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_initial_backup_failure_exits_before_mine tests/test_watcher.py::TestWatchInitialMineRecovery::test_missing_fragment_initial_mine_rolls_back_and_retries_once tests/test_watcher.py::TestWatchInitialMineRecovery::test_missing_fragment_without_candidate_exits_with_recovery_commands -q"
        proves: "Existing fail-closed backup and degraded rollback behavior remains intact while diagnostics are added."
        acceptance_ids: [AC-2]
      - id: REG-2
        command: "python -m pytest tests/test_watcher.py::TestWatchAndMineDiskBudget::test_ac2_low_disk_skips_mine_and_prints_message tests/test_watcher.py::TestWatchAndMineDiskBudget::test_low_disk_message_throttled -q"
        proves: "Existing disk-budget skip and throttling behavior remains intact around the new low-disk startup state."
        acceptance_ids: [AC-4]
      - id: REG-3
        command: "python -m pytest tests/test_watcher.py::TestWatchStatusCli::test_ac5_macos_loaded_prints_required_fields tests/test_watcher.py::TestWatchStatusCli::test_status_reports_last_exit_code_and_runs -q"
        proves: "The existing process-state surface used by the documented health check still reports daemon state, runs, and last exit code."
        acceptance_ids: [AC-6]
      - id: REG-4
        command: "python -m pytest tests/test_watcher.py::TestWatchAllInitializedRoot::test_initialized_root_is_watched_as_single_project tests/test_watcher.py::TestWatchAllInitializedRoot::test_parent_directory_still_watches_initialized_children -q"
        proves: "watch_all still supports initialized project roots and initialized children while adding the shared state format."
        acceptance_ids: [AC-5]
      - id: REG-5
        command: "python -m pytest tests/test_watcher.py::TestWatchAndMine::test_watch_detects_file_change tests/test_watcher.py::TestWatchAndMineDiskBudget::test_ac1_budget_ok_mine_is_called -q"
        proves: "The successful initial-mine -> watch-loop entry path that AC-1 instruments still holds, so adding readiness markers does not change when a healthy startup runs the initial mine and reaches the watch loop."
        acceptance_ids: [AC-1]
      - id: REG-6
        command: "python -m pytest tests/test_watcher.py::TestWatchRunReadinessDiagnostics::test_latest_successful_run_is_distinguishable_from_stale_appended_failures -q"
        proves: "Locks the stale-appended-log disambiguation contract for AC-3, which has no pre-existing analog, so later watcher startup changes cannot reintroduce ambiguity between stale disk-budget/backup failures and the current watch-ready run."
        acceptance_ids: [AC-3]
---

## Design Notes

- Use one startup helper in `watcher.py` for both `watch_and_mine()` and `watch_all()`. The helper should generate or carry a `run_id`, emit lines with a stable prefix such as `WATCH_RUN`, and keep fields shell-grep-friendly: `run_id=<id> state=<state> ...`.
- Prefer a run id derived from UTC time plus pid, for example `20260616T120102Z-p12345`; tests should patch the helper so assertions are deterministic. The id is an identifier, not a secret.
- Emit `state=watch-ready` only after startup gates have completed and immediately before entering `watchfiles.watch`. This makes the latest ready line a reliable boundary in an appended launchd log.
- Keep existing prose output such as `Watching:`, `Palace:`, `Pre-watch backup:`, `DEGRADED`, and recovery commands. Add machine-readable state lines alongside it so existing users still see familiar messages.
- On low disk before initial mine, preserve current behavior: skip the mine, print the disk-budget message, and still enter the watch loop so future cycles can recover. Add a `state=initial-mine-skipped reason=disk-budget` line with the current run id before `watch-ready`.
- For optimize, the emitted state must reflect the actual optimize outcome, not merely that the call returned. `_optimize_once()` (`watcher.py:413-428`) returns normally on its skip paths too — it prints `skipped (backup gate failed)` when the backup gate rejects and `skipped (<exc>)` on exception — so emitting `optimize-completed` unconditionally after the call would mislabel a skipped/failed optimize as completed, the exact confusion this task removes. Emit `state=optimize-completed` only when the optimize pass genuinely succeeded, and emit `state=optimize-skipped reason=<backup-gate|error>` when it short-circuits. This requires `_optimize_once()` to surface its success/skip outcome to the caller; do not change the optimize algorithm or backup gate themselves.
- Treat launchd logs as the existing stdout/stderr sink. `render_watch_schedule()` already routes both streams to `/tmp/mempalace-watch.log`, so no new log file writer is needed.
- Documentation should show a compact health check sequence: `mempalace-code watch <dir> status` or `launchctl print ...` for process state, `mempalace-code --palace <path> health` for storage health, and a log command that finds the latest `WATCH_RUN ... state=watch-ready` line plus its `run_id`.
- Verification commands are rooted at the repo root. `pyproject.toml` sets pytest testpaths to `tests`, skips `needs_network` and `slow` by default, and the dev/watch extras include `pytest` and `watchfiles`, so the planned focused `python -m pytest tests/test_watcher.py::... -q` commands are the correct automated evidence path.
