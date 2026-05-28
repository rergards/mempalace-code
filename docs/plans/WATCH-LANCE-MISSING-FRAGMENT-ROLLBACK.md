---
slug: WATCH-LANCE-MISSING-FRAGMENT-ROLLBACK
goal: "Make watcher startup preserve a backup, fail closed, and recover from Lance missing-fragment initial-mine writes"
risk: medium
risk_note: "Changes watcher startup behavior and managed backup taxonomy, but keeps steady-state watch event handling and storage schema unchanged."
files:
  - path: mempalace_code/watcher.py
    change: "Add shared initial-mine startup guard for watch_and_mine and watch_all: create a pre_watch backup for existing palaces, fail before mining if backup creation fails, catch missing-fragment write errors, attempt rollback recovery, retry initial mine once, and otherwise exit with operator-safe recovery commands."
  - path: mempalace_code/backup.py
    change: "Add managed pre_watch archive kind/prefix and classify it in backup listing so watcher pre-run archives are visible and separable from manual/scheduled/pre_optimize archives."
  - path: mempalace_code/config.py
    change: "Add a bounded implicit retention default for pre_watch archives while preserving explicit backup_retain_count semantics."
  - path: tests/test_watcher.py
    change: "Cover watcher startup backup ordering, backup failure fail-closed behavior, missing-fragment rollback retry, no-candidate recovery-command output, first-ever palace boundary, and watch_all initial batch behavior."
  - path: tests/test_backup.py
    change: "Cover pre_watch archive prefix/list kind and default/explicit retention boundaries."
  - path: docs/BACKUP_RESTORE.md
    change: "Document automatic watch pre-run backups, their retention class, and the operator recovery commands printed on degraded startup."
  - path: CHANGELOG.md
    change: "Add an Unreleased fixed entry for watcher pre-run backup and Lance missing-fragment startup recovery."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_initial_mine_creates_pre_watch_backup_before_mining -q` is run"
    then: "watch_and_mine creates a pre_watch archive before the initial mine touches an existing palace, reports the archive path, runs the initial mine, and only then starts the watch loop"
  - id: AC-2
    when: "`python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_initial_backup_failure_exits_before_mine -q` is run"
    then: "a pre-watch backup failure exits non-zero before _quiet_mine or watchfiles.watch is called, and output says the watcher did not start"
  - id: AC-3
    when: "`python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_missing_fragment_initial_mine_rolls_back_and_retries_once -q` is run"
    then: "a missing-fragment error from the first initial mine prints DEGRADED, performs one live rollback, retries the initial mine once, and enters the watch loop only after the retry succeeds"
  - id: AC-4
    when: "`python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_missing_fragment_without_candidate_exits_with_recovery_commands -q` is run"
    then: "when rollback has no candidate, watcher exits before watching and prints health, repair --rollback --dry-run, and restore --force commands that include the configured palace path and pre-watch archive path"
  - id: AC-5
    when: "`python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_first_ever_watch_without_existing_lance_data_skips_pre_watch_backup -q` is run"
    then: "a first-ever watch with no existing lance data does not require a pre-run backup and still runs the initial mine normally"
  - id: AC-6
    when: "`python -m pytest tests/test_watcher.py::TestWatchAllInitialMineRecovery::test_watch_all_initial_batch_uses_one_pre_watch_backup_and_fails_closed -q` is run"
    then: "watch_all creates one pre_watch archive before the initial multi-project batch and exits before watching if any initial project mine cannot be recovered"
  - id: AC-7
    when: "`python -m pytest tests/test_backup.py::TestPreWatchBackups::test_pre_watch_kind_uses_prefix_and_list_kind tests/test_backup.py::TestPreWatchBackups::test_pre_watch_default_retention_is_bounded tests/test_backup.py::TestPreWatchBackups::test_explicit_zero_retention_keeps_all_pre_watch_archives -q` is run"
    then: "pre_watch archives use the pre_watch_ prefix, backup list reports kind=pre_watch, the absent-config default keeps only the bounded newest set, and explicit backup_retain_count=0 keeps all"
  - id: AC-8
    when: "`rg 'pre_watch|watch pre-run|repair --rollback --dry-run|restore .*--force' docs/BACKUP_RESTORE.md CHANGELOG.md` is run"
    then: "operator-facing docs and changelog mention watch pre-run backups and the recovery commands for degraded watcher startup"
out_of_scope:
  - "Changing LanceDB storage schema, embedder behavior, or merge_insert retry semantics outside watcher startup recovery."
  - "Automatically restoring from tar backups without operator confirmation; automatic recovery is limited to Lance version rollback."
  - "Changing steady-state watch event filtering, debounce timing, disk-budget thresholds, or optimize behavior after successful change batches."
  - "Backlog completion, archive metadata, or any docs/BACKLOG.yaml changes."
contract_policy:
  flow: full_spdd
  reason: "Standard reliability task for watcher/storage recovery with data-safety and operator-recovery behavior."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Watcher startup must preserve a recoverable pre-run backup before writing to an existing palace."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-6, AC-7]
    - id: REQ-2
      statement: "Watcher startup must fail closed when the pre-run backup cannot be created."
      source: "backlog description"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "A Lance missing-fragment write error during initial mine must produce a clear degraded state and attempt automatic Lance rollback recovery."
      source: "backlog description"
      acceptance_ids: [AC-3, AC-4]
    - id: REQ-4
      statement: "Watcher startup must still support first-ever palaces with no existing Lance data."
      source: "edge-case acceptance"
      acceptance_ids: [AC-5]
    - id: REQ-5
      statement: "Operator-facing docs must explain the backup and recovery command path."
      source: "backlog description"
      acceptance_ids: [AC-8]
  surfaces:
    - name: "Single-project watcher startup"
      kind: internal
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "watch_and_mine uses the startup guard before entering watchfiles.watch, preserving a backup and handling missing-fragment failures before any steady-state watch loop starts."
    - name: "Multi-project watcher startup"
      kind: internal
      paths: ["mempalace_code/watcher.py"]
      expected_behavior: "watch_all uses the same startup guard once around the initial multi-project batch, including project/wing context when a mine fails."
    - name: "Managed pre-watch backups"
      kind: store
      paths: ["mempalace_code/backup.py", "mempalace_code/config.py"]
      expected_behavior: "pre_watch archives are managed, listed as their own kind, bounded by default, and still respect explicit global retention settings."
    - name: "Watcher recovery tests"
      kind: internal
      paths: ["tests/test_watcher.py"]
      expected_behavior: "Focused tests prove backup ordering, fail-closed exits, rollback retry, recovery-command output, first-ever palace boundary, and watch_all coverage."
    - name: "Backup taxonomy tests"
      kind: store
      paths: ["tests/test_backup.py"]
      expected_behavior: "Backup tests prove the pre_watch prefix/listing and retention boundaries."
    - name: "Operator guidance"
      kind: cli
      paths: ["docs/BACKUP_RESTORE.md", "CHANGELOG.md"]
      expected_behavior: "Docs and changelog describe automatic watch pre-run backups and degraded-startup recovery commands."
  invariants:
    - id: INV-1
      statement: "Successful steady-state watch re-mine batches keep the existing filtering, debounce, disk-budget, skip_optimize, and optimize-on-filed behavior."
      applies_to: ["mempalace_code/watcher.py"]
    - id: INV-2
      statement: "Backup creation must remain atomic and must not prune archives until after a successful archive write."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-3
      statement: "Explicit backup_retain_count values, including 0 keep-all, continue to apply across all managed backup kinds."
      applies_to: ["mempalace_code/config.py", "mempalace_code/backup.py"]
    - id: INV-4
      statement: "Tar backup restore remains an operator command, not an automatic watcher action."
      applies_to: ["mempalace_code/watcher.py", "mempalace_code/backup.py"]
  risks:
    - id: RISK-1
      risk: "Watcher restarts could create unbounded startup backups."
      mitigation: "Use a dedicated pre_watch kind with bounded implicit retention and explicit keep-all override tests."
    - id: RISK-2
      risk: "A backup failure could be logged but the initial mine could still mutate the degraded palace."
      mitigation: "Make backup creation a gate and assert _quiet_mine and watchfiles.watch are not called on backup failure."
    - id: RISK-3
      risk: "Automatic recovery could mask an unrecoverable palace and let the watcher run against partial data."
      mitigation: "Only continue after successful rollback plus one successful initial-mine retry; otherwise exit before watching with commands."
    - id: RISK-4
      risk: "Missing-fragment matching could catch unrelated errors."
      mitigation: "Limit auto-rollback to the same missing-fragment string family already used by storage upsert retry and let other exceptions propagate through the fail-closed path without retry."
    - id: RISK-5
      risk: "watch_all could back up repeatedly per project and increase disk pressure."
      mitigation: "Create one pre_watch archive before the initial multi-project batch and reuse that path in any recovery output."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_initial_mine_creates_pre_watch_backup_before_mining -q"
      proves: "Single-project watcher startup creates the pre_watch backup before initial mining and starts watching only after success."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_initial_backup_failure_exits_before_mine -q"
      proves: "Backup failure is a fail-closed gate before initial mine or watch loop entry."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_missing_fragment_initial_mine_rolls_back_and_retries_once -q"
      proves: "Missing-fragment initial-mine failures become DEGRADED output, live rollback, and one successful retry before watching."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_missing_fragment_without_candidate_exits_with_recovery_commands -q"
      proves: "Unrecoverable missing-fragment startup exits before watching and prints operator-safe health, repair, and restore commands."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_watcher.py::TestWatchInitialMineRecovery::test_first_ever_watch_without_existing_lance_data_skips_pre_watch_backup -q"
      proves: "No existing Lance data is a first-run boundary that does not require a backup before initial mining."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_watcher.py::TestWatchAllInitialMineRecovery::test_watch_all_initial_batch_uses_one_pre_watch_backup_and_fails_closed -q"
      proves: "Multi-project watcher startup uses one pre_watch backup and fail-closes before watch loop entry on unrecovered initial-mine failure."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_backup.py::TestPreWatchBackups::test_pre_watch_kind_uses_prefix_and_list_kind tests/test_backup.py::TestPreWatchBackups::test_pre_watch_default_retention_is_bounded tests/test_backup.py::TestPreWatchBackups::test_explicit_zero_retention_keeps_all_pre_watch_archives -q"
      proves: "pre_watch backup taxonomy and retention behavior are correct."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "rg 'pre_watch|watch pre-run|repair --rollback --dry-run|restore .*--force' docs/BACKUP_RESTORE.md CHANGELOG.md"
      proves: "Docs and changelog expose the automatic backup and recovery-command behavior."
      acceptance_ids: [AC-8]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_watcher.py::TestWatchAndMineDiskBudget tests/test_watcher.py::TestOptimizeOnce -q"
        proves: "Existing disk-budget and optimize routing behavior remains intact around the new startup guard."
        acceptance_ids: [AC-1, AC-2]
      - id: REG-2
        command: "python -m pytest tests/test_watcher.py::TestWatchAndMine tests/test_watcher.py::TestWatchAll -q"
        proves: "Existing single-project and multi-project watch event behavior still works."
        acceptance_ids: [AC-1, AC-6]
      - id: REG-3
        command: "python -m pytest tests/test_storage.py::TestLanceHealth tests/test_storage.py::TestWriteOpenNoEmbedder::test_upsert_missing_fragment_reopens_and_retries_once -q"
        proves: "Existing Lance health/rollback and merge_insert retry behavior remains available to watcher recovery."
        acceptance_ids: [AC-3, AC-4]
      - id: REG-4
        command: "python -m pytest tests/test_backup.py::TestManagedRetention tests/test_backup.py::TestListBackupsAnnotations -q"
        proves: "Adding pre_watch does not regress scheduled/pre_optimize/manual retention and list behavior."
        acceptance_ids: [AC-7]
      - id: REG-5
        command: "rg 'pre_watch|watch pre-run|repair --rollback --dry-run|restore .*--force' docs/BACKUP_RESTORE.md CHANGELOG.md"
        proves: "Operator documentation for degraded startup recovery remains present."
        acceptance_ids: [AC-8]
---

## Design Notes

- Add one startup helper in `watcher.py` and route both `watch_and_mine()` and `watch_all()` through it. Keep the existing steady-state watch loops unchanged after startup succeeds.
- Treat a pre-run backup as required only when `<palace>/lance` exists and contains data. A first-ever watch has nothing to preserve, so it should not be blocked by backup creation.
- Create the backup with `create_backup(palace_path, kind="pre_watch")`; print the archive path before mining. If backup creation raises, print a clear fail-closed message and exit before `_quiet_mine()` or `watchfiles.watch()` runs.
- Use the existing storage missing-fragment string family (`no such file`, `object not found`, `io error`, `not found`) to identify Lance fragment failures. Non-matching initial-mine exceptions should still stop startup and report the failure, but should not trigger rollback.
- On a missing-fragment initial-mine failure, print `DEGRADED`, the failed project/wing when known, the pre-watch archive path, and the recovery attempt. Open the Lance store with `create=False`, call `recover_to_last_working_version(dry_run=False)`, then retry the initial mine exactly once if recovery reports `recovered: true`.
- Continue into the watch loop only after the original initial mine succeeds or the single retry after successful rollback succeeds. If rollback has no candidate, rollback raises, or the retry fails, exit before watching.
- Recovery output should include exact commands using the configured palace path:
  - `mempalace-code --palace <palace> health`
  - `mempalace-code --palace <palace> repair --rollback --dry-run`
  - `mempalace-code --palace <palace> restore <pre_watch_archive> --force`
- Do not automatically restore from the tar archive in watcher code. The archive is the operator safety net if Lance version rollback cannot recover or the retry still fails.
- Add `pre_watch` as a managed backup kind with prefix `pre_watch_`. Use the same implicit default bound as `pre_optimize` unless implementation finds an existing config pattern that is more appropriate; explicit `backup_retain_count` must still override it, including `0` keep-all.
- Keep tests mostly mocked in `tests/test_watcher.py` so they prove ordering and exit behavior without running real watchfiles loops or embedding-heavy mining. Use existing Lance health/storage tests as regressions rather than duplicating Lance corruption setup in watcher tests.
