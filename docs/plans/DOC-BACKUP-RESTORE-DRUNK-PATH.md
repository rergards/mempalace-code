---
slug: DOC-BACKUP-RESTORE-DRUNK-PATH
status: completed
authority: non_authoritative
goal: "Replace unsafe backup and recovery guidance with a verified, reversible, explicit-target runbook enforced by the existing documentation drift guard."
risk: high
risk_note: "This release-blocking public guidance controls destructive recovery of user data; stale ordering, targets, or CLI syntax can cause irreversible loss."
files:
  - path: README.md
    change: "Make the concise backup, export, restore, and repair examples match the safe runbook and current CLI requirements."
  - path: docs/BACKUP_RESTORE.md
    change: "Replace destructive rebuild and inaccurate restore guidance with verified export plus tar backup, timestamped quarantine, explicit-target recovery, and poststate checks."
  - path: scripts/docs_drift_guard.py
    change: "Extend the existing public-documentation owner with ordered required markers and prohibited unsafe or invalid backup/recovery forms."
  - path: tests/test_docs_drift_guard.py
    change: "Add focused live-document and synthetic negative-matrix coverage for the backup/recovery contract."
acceptance:
  - id: AC-1
    when: "The focused documentation-contract checks inspect the recommended rebuild path."
    then: "They observe verified explicit JSONL export and full tar backup before an explicit timestamped quarantine move, followed by health, search, and import poststate checks before quarantine disposal is permitted."
  - id: AC-2
    when: "The drift guard scans every recommended recovery path and the documented storage layout."
    then: "It finds no executable recursive deletion of the active palace and confirms that the separate global knowledge graph is described independently from palace-local restore scoping."
  - id: AC-3
    when: "The restore guidance is checked against non-empty-target and force-restore scenarios."
    then: "It states that a non-empty target is refused without prompting and presents --force only after explicit archive, target, and current-backup inspection."
  - id: AC-4
    when: "The guard scans export and repair examples in both public owners."
    then: "Every export command has --out and every repair dry run uses repair --rollback --dry-run."
  - id: AC-5
    when: "The focused drift-guard matrix and named existing CLI backup/restore regressions run."
    then: "Wrong targets, malformed input, duplicate retry, reordered steps, and partial execution fail closed while the unchanged export, repair, restore-refusal, force, and KG-scoping runtime contracts remain green."
out_of_scope:
  - "Runtime, argparse, backup, storage, import/export, and knowledge-graph behavior changes."
  - "Changes to tests/test_cli.py or tests/test_backup_cli.py; they remain regression evidence."
  - "A new lifecycle test module, validator script, command, option, or recovery mode."
  - "Backlog metadata, Git finalization, release, deployment, and publication."
contract_policy:
  flow: full_spdd
  reason: "Strict release-blocker documentation changes a rules-heavy human and agent recovery boundary where wrong commands can destroy stored data."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The rebuild sequence preserves two independently usable artifacts, quarantines the selected palace, and retains recovery state until observable poststate succeeds."
      source: "Backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Recommended recovery guidance contains no executable active-palace recursive deletion and states KG locations accurately."
      source: "Backlog AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Restore guidance matches implemented non-empty refusal and gates explicit --force behind target and backup inspection."
      source: "Backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Export and repair examples use parser-valid required arguments and flag combinations."
      source: "Backlog AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The existing guard owns focused degraded-state coverage while current runtime suites remain unchanged regression evidence."
      source: "Backlog AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Detailed backup and recovery runbook"
      kind: cli
      paths: ["docs/BACKUP_RESTORE.md"]
      expected_behavior: "Readers receive one ordered, explicit-target, reversible rebuild and restore path with concrete artifact and poststate checks."
    - name: "README recovery summary"
      kind: cli
      paths: ["README.md"]
      expected_behavior: "Concise examples match current export, restore, KG, and repair contracts and route detailed recovery to the canonical runbook."
    - name: "Public documentation drift contract"
      kind: internal
      paths: ["scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "The existing guard accepts the canonical ordered path and rejects destructive, invalid, ambiguous, reordered, duplicated, and partial variants."
  invariants:
    - id: INV-1
      statement: "Documentation and guard changes do not alter CLI parsing or backup, restore, repair, export, import, storage, or KG runtime behavior."
      applies_to: ["README.md", "docs/BACKUP_RESTORE.md", "scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
    - id: INV-2
      statement: "docs/BACKUP_RESTORE.md remains the detailed owner and README.md remains a concise synchronized surface rather than a second runbook."
      applies_to: ["README.md", "docs/BACKUP_RESTORE.md"]
    - id: INV-3
      statement: "A refused non-forced restore remains non-mutating for both the selected palace and KG destinations."
      applies_to: ["scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
  risks:
    - id: RISK-1
      risk: "A reader quarantines or restores the wrong palace because examples depend on implicit defaults or stale conversational context."
      mitigation: "Require one explicit palace target throughout, echo or inspect it before mutation, and reject wrong-target or reordered synthetic variants."
    - id: RISK-2
      risk: "An artifact exists but is empty, malformed, or unrelated, leaving no viable rollback after the palace move."
      mitigation: "Require `mempalace-code --palace \"$PALACE\" import \"$EXPORT_JSONL\" --dry-run` and tar archive inspection before quarantine; retain the quarantine through poststate."
    - id: RISK-3
      risk: "Force restore overwrites live data based on a nonexistent confirmation-prompt assumption."
      mitigation: "Document fail-closed non-empty refusal and place --force only after explicit archive, target, and current-backup inspection."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_backup_restore_runbook_contract -q"
      proves: "The two public owners carry the complete ordered rebuild, explicit-target import dry-run, restore-refusal, KG-location, export --out, and valid repair dry-run contract."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_backup_restore_guard_rejects_degraded_paths -q"
      proves: "Synthetic wrong-target, malformed, duplicate-retry, reordered, partial-execution, destructive-delete, prompt-promise, unsafe-force, missing-output, and invalid-repair variants fail closed."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_cli.py::TestRepairRollbackCommand::test_repair_dry_run_without_rollback_exits_2 tests/test_cli.py::TestExportStdoutClean::test_export_file_writes_valid_jsonl tests/test_cli.py::TestExportStdoutClean::test_export_stdout_pipe_to_import_dry_run tests/test_backup_cli.py::test_backup_cli_explicit_out tests/test_backup_cli.py::test_restore_cli_force_flag tests/test_backup_cli.py::test_restore_cli_error_exit tests/test_backup_cli.py::test_restore_cli_explicit_palace_scopes_kg tests/test_backup_cli.py::test_restore_cli_refusal_does_not_touch_kg -q"
        proves: "Existing parser and backup/restore tests still prove required export output, parser-valid explicit-palace import dry-run, valid repair dry-run gating, explicit backups, non-empty refusal, force restore, and KG preservation without runtime test edits."
        acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Extend `evaluate()` through the existing docs-drift validation structure. Keep backup/recovery constants and checks beside the other public-surface contracts; do not create a new script or parser.
- Make `docs/BACKUP_RESTORE.md` the only complete recovery sequence. Keep `README.md` concise, parser-valid, and linked to that owner.
- Carry one explicit palace path through export, backup, quarantine, rebuild, import, health, and search commands. Use an explicit timestamped sibling quarantine path and stop on a pre-existing quarantine target.
- Verify the JSONL before quarantine with the parser-valid `mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run` form; the global `--palace` option precedes the `import` subcommand. Verify the tarball by inspecting its archive contents before moving the palace. File existence alone is insufficient evidence.
- Move the selected palace atomically to quarantine; do not publish executable recursive deletion for the active palace. Keep the quarantine until import output, `health`, and a bounded known-result `search` establish the rebuilt poststate.
- State the storage boundary precisely: default invocations use the separate global KG; an explicit `--palace` backup/restore scopes archived KG to that palace when present; `--kg-path` is the explicit override.
- Describe restore as refusing a non-empty destination and returning the recovery direction. The CLI has no overwrite prompt. Show `--force` only after archive inspection, explicit destination inspection, and a fresh explicit backup of the current target.
- Enforce sequence and uniqueness, not only token presence. The synthetic matrix must reject moved quarantine steps, import or restore before verification, repeated mutation steps, mismatched palace variables, malformed or empty artifact paths, and partial sequences that omit recovery retention or poststate.
- Preserve `tests/test_cli.py` and `tests/test_backup_cli.py` byte-for-byte. Their focused existing cases are regression evidence for parser and runtime behavior; implementation adds coverage only to `tests/test_docs_drift_guard.py`.
- Verification commands use the repository's Python/pytest context from `pyproject.toml`; PLAN does not execute them.
