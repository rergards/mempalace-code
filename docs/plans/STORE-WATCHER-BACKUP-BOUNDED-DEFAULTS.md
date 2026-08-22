---
slug: STORE-WATCHER-BACKUP-BOUNDED-DEFAULTS
status: completed
authority: non_authoritative
goal: "Bound implicit watcher pre-optimize backup retention while preserving explicit keep-all semantics"
risk: medium
risk_note: "Changes default retention behavior for automated pre-optimize archives, but leaves manual backups and explicit retention settings unchanged."
files:
  - path: mempalace_code/config.py
    change: "Add a bounded implicit retain count for pre-optimize backups and a kind-aware retention resolver that can distinguish absent retention config from explicit keep-all."
  - path: mempalace_code/backup.py
    change: "Use the kind-aware retention resolver for managed backups so implicit pre_optimize archives prune by default. This task intentionally left scheduled behavior unchanged; BACKUP-AUTOMATED-RETENTION-DEFAULTS later bounded managed scheduled archives to newest 14 while manual stayed unbounded."
  - path: tests/test_config.py
    change: "Cover fresh-config pre_optimize bounded retention, unchanged global/manual default, explicit zero keep-all, and env/file override precedence."
  - path: tests/test_storage.py
    change: "Update safe_optimize retention tests to assert the new implicit pre_optimize bound and the explicit zero keep-all boundary. Rename/rewrite the legacy `test_retention_default_zero_keeps_all_archives` (and any sibling whose docstring still claims `default backup_retain_count=0 disables pruning`) so naming and docstrings reflect the new implicit bound, or replace it outright with the new `test_default_pre_optimize_retention_prunes_to_bound` and `test_explicit_zero_retention_keeps_all_pre_optimize_archives` methods."
  - path: tests/test_backup.py
    change: "Add backup-level regression tests that manual/explicit archives are unaffected and disk-budget refusal happens before any retention prune."
  - path: README.md
    change: "Document the bounded implicit pre-optimize default, explicit keep-all opt-out, and unchanged explicit --out/manual archive behavior."
  - path: docs/BACKUP_RESTORE.md
    change: "Update backup/restore guidance for pre-optimize default retention, disk-budget-before-prune behavior, and opt-out syntax."
  - path: docs/AGENT_INSTALL.md
    change: "Update install/onboarding safety text so new watcher users see the bounded pre-optimize backup default and deliberate opt-out."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_config.py::test_pre_optimize_retain_count_default_bounded tests/test_config.py::test_backup_retain_count_default_remains_zero_for_manual -q` is run"
    then: "a fresh config resolves pre_optimize retention to the bounded default and still reports the global/manual backup_retain_count default as 0"
  - id: AC-2
    when: "`python -m pytest tests/test_storage.py::TestSafeOptimize::test_default_pre_optimize_retention_prunes_to_bound -q` is run"
    then: "six default safe_optimize(..., backup_first=True) cycles leave only the newest five pre_optimize_*.tar.gz archives"
  - id: AC-3
    when: "`python -m pytest tests/test_config.py::test_explicit_zero_backup_retain_count_keeps_pre_optimize_unbounded tests/test_storage.py::TestSafeOptimize::test_explicit_zero_retention_keeps_all_pre_optimize_archives -q` is run"
    then: "an explicit backup_retain_count value of 0 keeps all pre_optimize archives instead of applying the implicit bound"
  - id: AC-4
    when: "`python -m pytest tests/test_backup.py::test_pre_optimize_default_retention_does_not_prune_manual_or_explicit_out -q` is run"
    then: "implicit pre_optimize pruning does not delete manual, scheduled, unrelated, or explicit --out archives"
  - id: AC-5
    when: "`python -m pytest tests/test_backup.py::test_pre_optimize_budget_refusal_does_not_prune_existing_archives -q` is run"
    then: "a projected free-space violation raises DiskBudgetError before writing a new archive or pruning any existing archives"
  - id: AC-6
    when: "`rg 'pre-optimize|backup_retain_count|MEMPALACE_BACKUP_RETAIN_COUNT' README.md docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md` is run"
    then: "the docs show the bounded implicit pre-optimize default, explicit 0 keep-all opt-out, and unchanged explicit --out/manual backup behavior"
out_of_scope:
  - "Changing the LanceDB optimize algorithm, post-optimize verification, or storage schema."
  - "Pruning explicit --out archives or unmanaged files outside the managed backups directory."
  - "Changing the meaning of explicit backup_retain_count: 0 or MEMPALACE_BACKUP_RETAIN_COUNT=0."
  - "Deleting existing user backups during install, init, or onboarding."
contract_policy:
  flow: full_spdd
  reason: "Standard storage reliability task with default-behavior changes and disk-safety guards."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Implicit pre-optimize backups created by watcher/safe_optimize must be bounded by default."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Explicit backup_retain_count: 0 must continue to mean keep all backups, including pre_optimize archives."
      source: "backlog description"
      acceptance_ids: [AC-3]
    - id: REQ-3
      statement: "Manual backups, scheduled backups, explicit --out archives, and unrelated files must not be pruned by the implicit pre_optimize default."
      source: "backlog description"
      acceptance_ids: [AC-4]
    - id: REQ-4
      statement: "Backup creation must refuse before writing or pruning when projected free space would cross the configured floor."
      source: "backlog description"
      acceptance_ids: [AC-5]
    - id: REQ-5
      statement: "User-facing docs must show the safe default and deliberate opt-out path."
      source: "backlog description"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Retention config resolution"
      kind: internal
      paths: ["mempalace_code/config.py"]
      expected_behavior: "Expose kind-aware retention so missing config bounds pre_optimize archives while explicit backup_retain_count values keep their current meaning."
    - name: "Managed backup pruning"
      kind: store
      paths: ["mempalace_code/backup.py"]
      expected_behavior: "Apply the pre_optimize implicit bound only to managed pre_optimize archives after a successful backup and only inside the managed backups directory."
    - name: "Safe optimize backup path"
      kind: store
      paths: ["tests/test_storage.py", "tests/test_backup.py"]
      expected_behavior: "Regression tests exercise the watcher/safe_optimize backup path, explicit keep-all, manual/archive boundaries, and disk-budget refusal."
    - name: "Install and backup docs"
      kind: cli
      paths: ["README.md", "docs/BACKUP_RESTORE.md", "docs/AGENT_INSTALL.md"]
      expected_behavior: "Docs describe the bounded implicit pre-optimize default, how to opt out, and what archive classes remain unaffected."
  invariants:
    - id: INV-1
      statement: "Explicit backup_retain_count: 0 and MEMPALACE_BACKUP_RETAIN_COUNT=0 continue to disable pruning."
      applies_to: ["mempalace_code/config.py", "mempalace_code/backup.py"]
    - id: INV-2
      statement: "Explicit --out archives never participate in managed retention pruning."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-3
      statement: "Manual and scheduled managed backups keep the current implicit default of no pruning unless backup_retain_count is explicitly set."
      applies_to: ["mempalace_code/config.py", "mempalace_code/backup.py"]
    - id: INV-4
      statement: "Disk-budget checks run before temp archive creation and before retention pruning."
      applies_to: ["mempalace_code/backup.py"]
  risks:
    - id: RISK-1
      risk: "Changing the global backup_retain_count default would unexpectedly prune manual user backups."
      mitigation: "Keep the global default at 0 and add a kind-aware implicit default only for pre_optimize when no explicit retention config exists."
    - id: RISK-2
      risk: "The code may not distinguish missing config from explicit backup_retain_count: 0."
      mitigation: "Add tests for absent, explicit file zero, and env zero paths before wiring backup.py to the resolver."
    - id: RISK-3
      risk: "Retention tests can be flaky if archive timestamps collide."
      mitigation: "Patch backup.datetime or otherwise force stable timestamp ordering in tests."
    - id: RISK-4
      risk: "Retention could prune old archives even when the new backup is refused for disk space."
      mitigation: "Keep pruning after successful os.replace only and add a failure-path regression test with old archives present."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_config.py::test_pre_optimize_retain_count_default_bounded tests/test_config.py::test_backup_retain_count_default_remains_zero_for_manual -q"
      proves: "Fresh config gets a bounded pre_optimize retention default without changing global/manual default semantics."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_storage.py::TestSafeOptimize::test_default_pre_optimize_retention_prunes_to_bound -q"
      proves: "The safe_optimize pre-backup path prunes implicit pre_optimize archives to the bounded default."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_config.py::test_explicit_zero_backup_retain_count_keeps_pre_optimize_unbounded tests/test_storage.py::TestSafeOptimize::test_explicit_zero_retention_keeps_all_pre_optimize_archives -q"
      proves: "Explicit zero retention remains a keep-all boundary."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_backup.py::test_pre_optimize_default_retention_does_not_prune_manual_or_explicit_out -q"
      proves: "The implicit pre_optimize bound does not prune manual, scheduled, unrelated, or explicit --out archives."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_backup.py::test_pre_optimize_budget_refusal_does_not_prune_existing_archives -q"
      proves: "Disk-budget refusal happens before archive writes and before retention pruning."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "rg 'pre-optimize|backup_retain_count|MEMPALACE_BACKUP_RETAIN_COUNT' README.md docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md"
      proves: "User-facing docs expose the safe default, deliberate opt-out, and unaffected archive classes."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_config.py::test_pre_optimize_retain_count_default_bounded tests/test_config.py::test_explicit_zero_backup_retain_count_keeps_pre_optimize_unbounded -q"
        proves: "Default bounded retention and explicit keep-all semantics stay separated."
        acceptance_ids: [AC-1, AC-3]
      - id: REG-2
        command: "python -m pytest tests/test_storage.py::TestSafeOptimize::test_default_pre_optimize_retention_prunes_to_bound tests/test_storage.py::TestSafeOptimize::test_explicit_zero_retention_keeps_all_pre_optimize_archives -q"
        proves: "The actual safe_optimize backup path keeps both bounded-default and explicit-keep-all behavior."
        acceptance_ids: [AC-2, AC-3]
      - id: REG-3
        command: "python -m pytest tests/test_backup.py::test_pre_optimize_default_retention_does_not_prune_manual_or_explicit_out tests/test_backup.py::test_pre_optimize_budget_refusal_does_not_prune_existing_archives -q"
        proves: "Archive-class boundaries and disk-budget fail-closed behavior do not regress."
        acceptance_ids: [AC-4, AC-5]
      - id: REG-4
        command: "rg 'pre-optimize|backup_retain_count|MEMPALACE_BACKUP_RETAIN_COUNT' README.md docs/BACKUP_RESTORE.md docs/AGENT_INSTALL.md"
        proves: "Docs continue to surface the bounded implicit pre-optimize default and the explicit keep-all opt-out, so future doc edits cannot silently regress the user-facing safety guidance."
        acceptance_ids: [AC-6]
---

## Design Notes

- Keep `DEFAULT_BACKUP_RETAIN_COUNT = 0` and the public `backup_retain_count` property semantics unchanged. The new bounded behavior should be a kind-aware implicit default for `pre_optimize` only.
- Use `5` as the implicit default for pre-optimize managed archives. It matches existing documentation examples and gives watcher users recovery history without unbounded disk growth.
- Add a small resolver in `MempalaceConfig` instead of changing call sites to parse raw config. It should be able to answer: "what retain count applies to this backup kind?" and "was `backup_retain_count` explicitly configured by env or file?"
- In `backup.py`, choose the retain count after a successful managed backup is written. This task used the kind-aware implicit resolver for `pre_optimize` only and intentionally left `manual` and `scheduled` on the existing behavior. Current code is superseded for `scheduled` by BACKUP-AUTOMATED-RETENTION-DEFAULTS: absent config keeps newest 14 scheduled archives; `manual` remains unbounded.
- Do not prune anything before `check_backup_budget()` passes and the temp archive is atomically moved into place. The disk-budget regression should place old `pre_optimize_*.tar.gz` files in `backups/`, force projected free space below the floor, and assert all old files remain.
- The default-bound tests should patch `mempalace_code.backup.datetime` to produce six unique archive names in stable order. Keep the existing explicit-zero keep-all coverage by setting `MEMPALACE_BACKUP_RETAIN_COUNT=0` or a file config with `backup_retain_count: 0`.
- Documentation should phrase this as "implicit pre-optimize retention is bounded; explicit `backup_retain_count: 0` is a deliberate keep-all opt-out." Avoid implying that manual `backup create` archives are now pruned by default.
- Disk floor scope: keep the existing 1 GiB `DEFAULT_DISK_MIN_FREE_BYTES` in `mempalace_code/config.py` and the `backup_disk_min_free_bytes` fallback to `disk_min_free_bytes` unchanged. The backlog item "default disk floors leave enough room for a temporary backup before prune" is satisfied by the existing floor plus the fail-closed budget check; AC-5/VER-5/REG-3 are the regressions that prove projected free-space violations refuse before any write or prune. Do not bump the floor or add an install-time `backup_disk_min_free_bytes` write in this task — raising the floor is out of scope and would be a separate change.
