---
slug: BACKUP-AUTOMATED-RETENTION-DEFAULTS
goal: "Bound managed scheduled backup retention by default while preserving keep-all escape hatches"
risk: medium
risk_note: "Changes default pruning behavior for managed scheduled archives, with explicit keep-all and manual backup boundaries preserved."
files:
  - path: mempalace_code/config.py
    change: "Add a DEFAULT_SCHEDULED_RETAIN_COUNT of 14 and update kind-aware retention resolution so missing retention config maps scheduled -> 14, pre_optimize -> 5, and manual -> 0."
  - path: mempalace_code/backup.py
    change: "Apply the kind-aware resolver consistently for managed backup pruning and backup-list stale annotations, including scheduled defaults."
  - path: tests/test_config.py
    change: "Cover fresh-config kind defaults, explicit zero keep-all, explicit nonzero override, and invalid retention config that must not suppress implicit scheduled/pre_optimize bounds."
  - path: tests/test_backup.py
    change: "Add managed scheduled-retention behavior tests for default pruning, explicit keep-all, explicit nonzero override, explicit --out isolation, stale flags, and disk-budget refusal before prune."
  - path: tests/test_cli.py
    change: "Strengthen backup schedule CLI assertions so generated snippets use managed scheduled backups and never include explicit --out."
  - path: README.md
    change: "Document the scheduled newest-14 implicit default alongside pre_optimize newest-5, manual keep-all, explicit overrides, and explicit --out isolation."
  - path: docs/BACKUP_RESTORE.md
    change: "Update backup/restore retention guidance so scheduled backups are no longer described as unbounded by default."
  - path: docs/AGENT_INSTALL.md
    change: "Update install troubleshooting safety text to mention bounded scheduled and pre-optimize defaults plus explicit keep-all opt-out."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_config.py::test_default_kind_retention_counts -q` is run"
    then: "a fresh config resolves scheduled retention to 14, pre_optimize retention to 5, manual retention to 0, and global backup_retain_count remains 0"
  - id: AC-2
    when: "`python -m pytest tests/test_config.py::test_explicit_zero_backup_retain_count_keeps_all_kinds tests/test_backup.py::TestManagedRetention::test_default_scheduled_retain_0_keeps_all -q` is run"
    then: "explicit backup_retain_count=0 keeps scheduled, pre_optimize, and manual backups unbounded instead of applying implicit defaults"
  - id: AC-3
    when: "`python -m pytest tests/test_config.py::test_explicit_nonzero_retain_count_overrides_all_implicit_bounds tests/test_backup.py::TestManagedRetention::test_explicit_scheduled_retain_3_keeps_three -q` is run"
    then: "explicit nonzero backup_retain_count overrides scheduled, pre_optimize, and manual retain counts"
  - id: AC-4
    when: "`python -m pytest tests/test_backup.py::TestManagedRetention::test_default_scheduled_retention_prunes_to_bound -q` is run"
    then: "fifteen managed `backup create --kind scheduled` calls leave only the newest fourteen scheduled_*.tar.gz archives"
  - id: AC-5
    when: "`python -m pytest tests/test_backup.py::TestDiskPreflight::test_scheduled_budget_refusal_does_not_prune_existing_archives -q` is run"
    then: "a disk-budget refusal raises DiskBudgetError before writing a new scheduled archive or pruning old scheduled archives"
  - id: AC-6
    when: "`python -m pytest tests/test_backup.py::TestManagedRetention::test_explicit_out_path_does_not_trigger_scheduled_default_retention -q` is run"
    then: "scheduled archives written through explicit out_path are not pruned by the managed scheduled default"
  - id: AC-7
    when: "`python -m pytest tests/test_backup.py::TestListBackups::test_stale_flags_use_kind_aware_retention_defaults -q` is run"
    then: "`backup list` marks stale scheduled and pre_optimize archives using their implicit per-kind defaults without marking manual archives stale by default"
  - id: AC-8
    when: "`python -m pytest tests/test_backup.py::TestRenderSchedule::test_render_schedule_kind_scheduled_darwin tests/test_backup.py::TestRenderSchedule::test_render_schedule_kind_scheduled_linux tests/test_cli.py::test_backup_schedule_daily_darwin tests/test_cli.py::test_backup_schedule_daily_linux -q` is run"
    then: "generated launchd and cron snippets use `backup create --kind scheduled --palace ...` and do not include `--out`"
  - id: AC-9
    when: "`rg 'newest 14|scheduled.*bounded|manual.*unbounded|backup_retain_count|MEMPALACE_BACKUP_RETAIN_COUNT|--out' README.md docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md` is run"
    then: "the docs describe scheduled newest-14 retention, pre_optimize newest-5 retention, manual keep-all behavior, explicit override/keep-all semantics, and explicit --out isolation"
out_of_scope:
  - "Pruning manual user-created backups by default."
  - "Deleting existing backups during install, init, or schedule generation."
  - "Age-based retention, disk-quota retention, or changing disk floor defaults."
  - "Changing explicit --out archive behavior or pruning unmanaged directories."
  - "Changing scheduler installation behavior; backup schedule still prints snippets only."
contract_policy:
  flow: full_spdd
  reason: "Standard storage reliability task with default-behavior changes and backup safety guards."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Fresh config must bound managed scheduled backups to the newest 14 by default while keeping pre_optimize at 5 and manual at 0."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-4]
    - id: REQ-2
      statement: "Explicit backup_retain_count=0 must remain a deliberate keep-all opt-out for every backup kind."
      source: "backlog description"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Explicit nonzero backup_retain_count and MEMPALACE_BACKUP_RETAIN_COUNT must override all implicit per-kind defaults."
      source: "backlog description"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Managed scheduled retention must not prune explicit --out archives or manual archives by default."
      source: "backlog description"
      acceptance_ids: [AC-6, AC-7]
    - id: REQ-5
      statement: "Disk-budget refusal must happen before archive writes and before retention pruning."
      source: "backlog description"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Generated schedule snippets must remain managed-retention-safe by using scheduled kind without explicit --out."
      source: "backlog description"
      acceptance_ids: [AC-8]
    - id: REQ-7
      statement: "User-facing docs must no longer describe scheduled backups as unbounded by default."
      source: "backlog description"
      acceptance_ids: [AC-9]
  surfaces:
    - name: "Retention config resolution"
      kind: internal
      paths: ["mempalace_code/config.py"]
      expected_behavior: "Return per-kind retain counts where absent config means scheduled=14, pre_optimize=5, manual=0, and only valid explicit values override those defaults."
    - name: "Managed backup prune and list"
      kind: store
      paths: ["mempalace_code/backup.py"]
      expected_behavior: "Use retain_count_for_kind(kind) after a successful managed backup and when computing stale flags in backup list."
    - name: "Schedule generation"
      kind: cli
      paths: ["mempalace_code/backup.py", "tests/test_cli.py"]
      expected_behavior: "Printed launchd/cron snippets keep using managed scheduled backups with --kind scheduled and no --out."
    - name: "User-facing backup docs"
      kind: cli
      paths: ["README.md", "docs/BACKUP_RESTORE.md", "docs/AGENT_INSTALL.md"]
      expected_behavior: "Document scheduled newest-14 default, pre_optimize newest-5 default, manual keep-all default, explicit override/opt-out, and explicit --out isolation."
  invariants:
    - id: INV-1
      statement: "DEFAULT_BACKUP_RETAIN_COUNT and the public backup_retain_count property remain 0 by default."
      applies_to: ["mempalace_code/config.py"]
    - id: INV-2
      statement: "Explicit backup_retain_count=0 and MEMPALACE_BACKUP_RETAIN_COUNT=0 disable pruning for every backup kind."
      applies_to: ["mempalace_code/config.py", "mempalace_code/backup.py"]
    - id: INV-3
      statement: "Explicit positive backup_retain_count applies uniformly to scheduled, pre_optimize, manual, and listed archive kinds."
      applies_to: ["mempalace_code/config.py", "mempalace_code/backup.py"]
    - id: INV-4
      statement: "Manual managed backups are unbounded by default and must not be pruned by scheduled or pre_optimize implicit defaults."
      applies_to: ["mempalace_code/config.py", "mempalace_code/backup.py"]
    - id: INV-5
      statement: "Explicit --out archives never participate in managed retention pruning."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-6
      statement: "Disk-budget checks run before temp archive creation and before retention pruning."
      applies_to: ["mempalace_code/backup.py"]
  risks:
    - id: RISK-1
      risk: "Changing the global retain default would unexpectedly prune manual user backups."
      mitigation: "Keep DEFAULT_BACKUP_RETAIN_COUNT at 0 and implement scheduled retention only through retain_count_for_kind."
    - id: RISK-2
      risk: "Invalid or negative explicit config could accidentally suppress implicit scheduled/pre_optimize bounds."
      mitigation: "Parse explicit retention through one helper and treat only valid nonnegative values as explicit for kind-aware defaults."
    - id: RISK-3
      risk: "Retention tests can be flaky when multiple archives share a timestamp."
      mitigation: "Patch mempalace_code.backup.datetime or otherwise force unique sortable timestamps in focused tests."
    - id: RISK-4
      risk: "backup list may disagree with pruning behavior if it keeps using the global retain count."
      mitigation: "Update stale flag calculation to ask retain_count_for_kind for each archive kind and add list_backups coverage."
    - id: RISK-5
      risk: "A failed scheduled backup could still prune older archives if pruning happens too early."
      mitigation: "Keep pruning after successful os.replace only and add a DiskBudgetError regression with existing scheduled archives."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_config.py::test_default_kind_retention_counts -q"
      proves: "Fresh config maps scheduled, pre_optimize, and manual kinds to the intended implicit retain counts."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_config.py::test_explicit_zero_backup_retain_count_keeps_all_kinds tests/test_backup.py::TestManagedRetention::test_default_scheduled_retain_0_keeps_all -q"
      proves: "Explicit zero remains keep-all for all kinds and real scheduled backups."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_config.py::test_explicit_nonzero_retain_count_overrides_all_implicit_bounds tests/test_backup.py::TestManagedRetention::test_explicit_scheduled_retain_3_keeps_three -q"
      proves: "Explicit positive retain count overrides scheduled and pre_optimize implicit defaults."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_backup.py::TestManagedRetention::test_default_scheduled_retention_prunes_to_bound -q"
      proves: "Managed scheduled backups prune to newest fourteen by default."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_backup.py::TestDiskPreflight::test_scheduled_budget_refusal_does_not_prune_existing_archives -q"
      proves: "Disk-budget refusal prevents both new scheduled archive creation and scheduled retention pruning."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_backup.py::TestManagedRetention::test_explicit_out_path_does_not_trigger_scheduled_default_retention -q"
      proves: "Explicit scheduled out_path archives remain outside managed retention."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_backup.py::TestListBackups::test_stale_flags_use_kind_aware_retention_defaults -q"
      proves: "backup list stale flags match scheduled/pre_optimize defaults and manual keep-all."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "python -m pytest tests/test_backup.py::TestRenderSchedule::test_render_schedule_kind_scheduled_darwin tests/test_backup.py::TestRenderSchedule::test_render_schedule_kind_scheduled_linux tests/test_cli.py::test_backup_schedule_daily_darwin tests/test_cli.py::test_backup_schedule_daily_linux -q"
      proves: "Both render_schedule and CLI schedule output use managed scheduled backups without --out."
      acceptance_ids: [AC-8]
    - id: VER-9
      command: "rg 'newest 14|scheduled.*bounded|manual.*unbounded|backup_retain_count|MEMPALACE_BACKUP_RETAIN_COUNT|--out' README.md docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md"
      proves: "Backup docs expose scheduled/default/manual/explicit-out retention semantics."
      acceptance_ids: [AC-9]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_config.py::test_default_kind_retention_counts tests/test_config.py::test_explicit_zero_backup_retain_count_keeps_all_kinds tests/test_config.py::test_explicit_nonzero_retain_count_overrides_all_implicit_bounds -q"
        proves: "Kind defaults, explicit zero, and explicit positive overrides remain separated at config level."
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-2
        command: "python -m pytest tests/test_backup.py::TestManagedRetention::test_default_scheduled_retention_prunes_to_bound tests/test_backup.py::TestManagedRetention::test_default_scheduled_retain_0_keeps_all tests/test_backup.py::TestManagedRetention::test_explicit_scheduled_retain_3_keeps_three tests/test_backup.py::TestManagedRetention::test_explicit_out_path_does_not_trigger_scheduled_default_retention -q"
        proves: "Real managed scheduled backup creation honors default pruning, keep-all, explicit override, and explicit-out boundaries."
        acceptance_ids: [AC-2, AC-3, AC-4, AC-6]
      - id: REG-3
        command: "python -m pytest tests/test_backup.py::TestDiskPreflight::test_scheduled_budget_refusal_does_not_prune_existing_archives tests/test_backup.py::TestListBackups::test_stale_flags_use_kind_aware_retention_defaults -q"
        proves: "Failure-path ordering and backup-list stale reporting stay aligned with retention policy."
        acceptance_ids: [AC-5, AC-7]
      - id: REG-4
        command: "python -m pytest tests/test_backup.py::TestRenderSchedule::test_render_schedule_kind_scheduled_darwin tests/test_backup.py::TestRenderSchedule::test_render_schedule_kind_scheduled_linux tests/test_cli.py::test_backup_schedule_daily_darwin tests/test_cli.py::test_backup_schedule_daily_linux -q"
        proves: "Schedule snippets remain managed-retention-safe across direct renderer and CLI surfaces."
        acceptance_ids: [AC-8]
      - id: REG-5
        command: "rg 'newest 14|scheduled.*bounded|manual.*unbounded|backup_retain_count|MEMPALACE_BACKUP_RETAIN_COUNT|--out' README.md docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md"
        proves: "Docs continue to describe scheduled bounded defaults and keep-all/explicit-out boundaries."
        acceptance_ids: [AC-9]
---

## Design Notes

- Add `DEFAULT_SCHEDULED_RETAIN_COUNT = 14` next to `DEFAULT_PRE_OPTIMIZE_RETAIN_COUNT = 5`; keep `DEFAULT_BACKUP_RETAIN_COUNT = 0`.
- Keep `backup_retain_count` as the global public property. Put per-kind behavior behind `retain_count_for_kind(kind)` so call sites do not parse env/file config.
- Replace the current boolean-only explicit detector with a helper that validates env/file `backup_retain_count` once. Treat valid nonnegative values as explicit; treat empty, nonnumeric, and negative values as absent for implicit scheduled/pre_optimize defaults while preserving `backup_retain_count` fallback to 0.
- `retain_count_for_kind("scheduled")` should return 14 only when no valid explicit retain count is set. `pre_optimize` keeps returning 5 in the same absent-config case. `manual` remains 0.
- In `create_backup`, keep retention after the archive is atomically written with `os.replace`; do not move pruning before disk-budget checks or archive creation.
- In `list_backups`, compute stale status per archive kind with `retain_count_for_kind(e["kind"])`; this keeps the UI/reporting contract aligned with actual pruning for scheduled and pre_optimize defaults.
- Scheduled-retention tests should patch `mempalace_code.backup.datetime` so 15 created archives have stable, unique names. Assert the oldest `scheduled_*.tar.gz` is gone and the newest 14 remain.
- Disk-budget failure coverage should pre-create more than 14 scheduled archives, force `DiskBudgetError`, and assert neither a new archive nor any prune happened.
- Update docs in one pass: scheduled newest 14, pre_optimize newest 5, manual unbounded, explicit nonzero override all kinds, explicit 0 keep-all, and explicit `--out` unmanaged.
