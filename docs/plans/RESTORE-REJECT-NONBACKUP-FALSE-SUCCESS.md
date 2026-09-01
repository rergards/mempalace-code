---
slug: RESTORE-REJECT-NONBACKUP-FALSE-SUCCESS
status: completed
authority: non_authoritative
goal: "Reject non-backup archives before mutation and report restore success only after the archive's declared managed state is verified."
risk: high
risk_note: "Restore can replace Lance and KG state under --force; adding post-publication verification requires transactionally preserving both prior destinations until success is proven."
files:
  - path: mempalace_code/backup.py
    change: "Require and parse canonical metadata before mutation, validate canonical payload combinations, verify restored Lance/KG post-state, and roll back owned or replaced destinations on failure."
  - path: mempalace_code/cli_commands/backup_restore.py
    change: "Keep success output behind verified restore completion and print a bounded valid-backup recovery command for archive-shape failures."
  - path: tests/test_backup.py
    change: "Extend the restore owner matrix for missing/unsafe/malformed shapes, valid empty/Lance/KG/combined backups, post-state verification, and rollback of prior destinations."
  - path: tests/test_backup_cli.py
    change: "Cover non-backup exit/output behavior, empty-backup truthfulness, recovery guidance, and absence or preservation of destination state."
  - path: tests/test_cli_golden_scenarios.py
    change: "Extend the existing installed-capable subprocess scenario with healthy valid restore and non-backup rejection plus destination and escape post-state assertions."
acceptance:
  - id: AC-1
    when: "Restore receives an archive with no canonical mempalace_backup/metadata.json member, including an archive containing only an out-of-root traversal member."
    then: "The command exits nonzero before destination mutation and does not print Restored palace to:."
  - id: AC-2
    when: "The focused restore matrix exercises traversal, absolute, link, device, malformed metadata, metadata-only empty-backup, Lance-only, KG-only, and normal backup shapes."
    then: "Unsafe or malformed shapes are rejected before mutation, while canonical empty and payload-bearing shapes produce their explicitly declared restore outcomes."
  - id: AC-3
    when: "A canonical archive declares Lance or KG payload state and restore reaches publication, including --force over existing managed state."
    then: "Exit 0 occurs only after the expected managed destinations and Lance health/count are verified; verification failure removes newly owned state or restores the prior destinations."
  - id: AC-4
    when: "The configured exact-wheel installed golden scenario restores a valid archive and then submits a tar.gz containing only ../../mempalace-direct-escaped.txt."
    then: "The valid restore is healthy; the non-backup restore exits nonzero without a success message and leaves both the destination and escaped file absent."
  - id: AC-5
    when: "CLI restore rejects an archive that lacks the canonical MemPalace backup shape."
    then: "The diagnostic contains exactly one concrete mempalace-code backup create command for producing a valid backup."
out_of_scope:
  - "Changing the create_backup archive format, metadata filename, backup listing format, or adding a manifest/schema version."
  - "Adding a helper module, dependency, CLI flag, release gate, or second restore path."
  - "Changing collision policy, KG destination scoping, backup retention, or unrelated health behavior."
  - "Editing backlog metadata or performing staging, commits, release qualification, publication, or deployment."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release bug fix changes validation and transaction semantics at a destructive restore boundary and requires installed-artifact proof."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Every accepted restore archive has one usable canonical metadata member before destination checks or mutation begin."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-1 and AC-2"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "Canonical empty, Lance-only, KG-only, and combined backups have explicit outcomes consistent with create_backup output."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Payload-bearing restore success is conditional on verified managed post-state, and verification failure preserves or restores prior state."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The exact candidate wheel proves both healthy valid restore and side-effect-free rejection of the observed non-backup archive."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Archive-shape rejection tells the operator how to create a canonical backup without implying success."
      source: "CURRENT BACKLOG PLAN CONTRACT AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Backup archive restore owner"
      kind: internal
      paths: ["mempalace_code/backup.py"]
      expected_behavior: "Validate canonical shape before mutation, publish only declared managed payloads, verify their final state, and retain rollback ownership until verification succeeds."
    - name: "Restore CLI result contract"
      kind: cli
      paths: ["mempalace_code/cli_commands/backup_restore.py"]
      expected_behavior: "Exit and print success only after restore_backup returns verified state; archive-shape failures exit nonzero with one concrete backup creation command."
  invariants:
    - id: INV-1
      statement: "Managed traversal, absolute-looking components, symlinks, hardlinks, FIFOs, and device members remain rejected before extraction or destination mutation."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-2
      statement: "create_backup output remains the canonical accepted format, including metadata-only empty, Lance-only, KG-only, and combined archives."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-3
      statement: "Non-forced collision refusal and explicit --palace/--kg-path destination selection remain unchanged."
      applies_to: ["mempalace_code/backup.py", "mempalace_code/cli_commands/backup_restore.py"]
    - id: INV-4
      statement: "Restore never follows archive links or palace/KG destination symlinks and never removes paths it cannot prove it owns."
      applies_to: ["mempalace_code/backup.py"]
  risks:
    - id: RISK-1
      risk: "Post-state verification can fail after --force has published Lance or KG data, losing the operator's previous destination."
      mitigation: "Extend the current staged publication and inode-ownership rollback pattern to retain both prior managed destinations until all declared post-state checks pass."
    - id: RISK-2
      risk: "Treating every archive without Lance as invalid would reject canonical KG-only and metadata-only backups produced by create_backup."
      mitigation: "Derive expected state from canonical metadata plus managed payload members and test all four create_backup shapes explicitly."
    - id: RISK-3
      risk: "A path-extraction guard can remain safe while the CLI still reports a successful no-op."
      mitigation: "Require metadata before collision checks and cover exit code, success text, destination absence, and escaped-file absence at CLI and installed-wheel boundaries."
    - id: RISK-4
      risk: "A fabricated Lance directory can exist while remaining unreadable or contradicting metadata."
      mitigation: "Open the final store read-only, require a healthy report, and compare its count with the canonical metadata before returning success."
  verification:
    - id: VER-1
      owner: provider_owned
      command: "python -m pytest tests/test_backup.py tests/test_backup_cli.py -q"
      proves: "The complete focused restore owner covers canonical shape classification, pre-mutation refusal, valid empty and payload restore, final-state verification, rollback, CLI streams, and recovery guidance without filtering sibling restore cases."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-5]
    - id: VER-2
      owner: configured_runner_owned
      command: "python scripts/release_readiness_gate.py --installed-golden-wheel \"$WHEEL\" --json"
      proves: "The canonical installed-golden gate invokes the exact candidate console script from a neutral directory and proves valid restore health plus non-backup exit, streams, and filesystem post-state."
      acceptance_ids: [AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner_owned
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The configured non-network suite preserves backup creation, collision, KG scoping, force rollback, health, CLI, and other repository behavior around the restore change."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Keep `_validate_archive_members()` and `restore_backup()` as the single archive trust boundary. Require the canonical metadata file immediately after member safety validation and before collision checks, staging, palace-directory creation, or KG temp-file creation.
- Parse metadata once. Treat invalid UTF-8/JSON, a non-object root, or an invalid canonical `drawer_count` declaration as `BackupArchiveError` with a stable archive-shape code. Retain the offending canonical member name in the error contract.
- Classify canonical shapes from safe managed members: metadata-only with `drawer_count: 0` is a valid declared empty backup; Lance-only, KG-only, and combined payloads are valid; a positive drawer count without Lance payload is contradictory and fails before mutation.
- For a declared empty backup, return its metadata without creating palace or KG state and make CLI output explicitly describe the empty restore result. Do not claim that an absent palace path was restored.
- Stage and validate readable Lance data before publication where possible. After publication, open the final Lance store read-only, require its existing `health_check()` result to be healthy, and require `count()` to equal metadata `drawer_count`. For an archived KG payload, require the selected final KG path to be a regular file.
- Preserve transaction ownership through final verification. Non-force failure removes only the Lance/KG paths created by the current restore. Force failure restores the prior Lance and KG destinations from retained same-filesystem staging/backup paths; ownership mismatch fails closed with the existing concrete manual-recovery style.
- Add a low-level shape matrix using archives produced by `create_backup()` for accepted cases. Keep handcrafted tar members only for missing metadata, unsafe member types/paths, malformed declarations, and injected post-state failure.
- Extend `cmd_restore()` with a specific archive-shape failure branch so stderr includes one `mempalace-code backup create` command and stdout contains no restore-success line. Preserve the existing collision-specific backup-first/`--force` guidance.
- Extend the existing installed-capable golden scenario rather than adding a gate or standalone wheel harness. Build the observed out-of-root traversal tar in its disposable root, assert no escaped file or destination appears, then run `health --json` against the valid restored target.
- Command context comes from `pyproject.toml` (pytest dev dependency and default markers), `scripts/gate_inventory.py` (exact configured non-network and installed-golden commands), and `scripts/release_readiness_gate.py`/`tests/test_cli_golden_scenarios.py` (candidate-wheel execution from a neutral directory).
