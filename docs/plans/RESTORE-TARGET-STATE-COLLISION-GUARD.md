---
slug: RESTORE-TARGET-STATE-COLLISION-GUARD
status: completed
authority: non_authoritative
goal: "Make non-force restore fail before mutation whenever the selected palace or KG destination already contains state"
risk: high
risk_note: "Restore can replace persistent Lance and KG state; the change strengthens its default collision boundary while preserving the explicitly destructive force path."
files:
  - path: mempalace_code/backup.py
    change: "Extend restore_backup collision handling to detect existing palace and selected KG state, claim the exact Lance root exclusively, publish non-force KG with atomic no-replace semantics, and retain validated explicit-force replacement."
  - path: mempalace_code/cli_commands/backup_restore.py
    change: "Keep the existing restore error adapter and make its recovery instruction apply to every reported destination."
  - path: tests/test_backup_cli.py
    change: "Add public-CLI collision-matrix regressions for immutable refusals, post-preflight races and rollback, absent destinations, repeated restore, explicit/default KG selection, force replacement, and symlink safety."
  - path: README.md
    change: "Replace the obsolete restore-overwrite summary with the fail-closed destination boundary."
  - path: docs/BACKUP_RESTORE.md
    change: "Document non-force refusal, force scope, late-collision rollback, and backup-first recovery for the selected destinations."
  - path: scripts/docs_drift_guard.py
    change: "Replace obsolete restore-overwrite markers in the existing public documentation contract with the fail-closed behavior and recovery boundary."
  - path: tests/test_docs_drift_guard.py
    change: "Update the existing documentation-contract fixture and degradation cases for refusal, rollback, force scope, symlink safety, and backup-first recovery."
acceptance:
  - id: AC-1
    when: "the focused restore collision tests invoke restore without --force and palace or selected KG state exists at preflight or the exact Lance/KG publication name is raced in"
    then: "an initial collision exits 1 before extraction, an exact-name publication collision exits 1 without replacing raced state, invocation-owned Lance is rolled back after KG publication failure, and the CLI reports the backup-first force recovery path"
  - id: AC-2
    when: "the non-force collision matrix covers a KG-only target, regular-file palace target, symlink palace target, non-empty Lance state, explicit --kg-path, default-global KG selection, a repeated invocation, and deterministic palace/KG state injected after preflight"
    then: "every invocation is refused and byte-for-byte snapshots of the palace entry and selected KG destination remain unchanged"
  - id: AC-3
    when: "restore is invoked without --force using a valid archive and genuinely absent palace and selected KG destinations"
    then: "the command succeeds and the restored Lance store and KG contain the archived records"
  - id: AC-4
    when: "the force collision tests restore the same valid archive across the collision shapes and exercise malformed or unsafe archive members"
    then: "--force replaces the selected managed state only after archive validation, KG replacement remains atomic, and malformed or unsafe archives leave existing target and KG bytes unchanged"
out_of_scope:
  - "Changing CLI KG destination precedence, DEFAULT_KG_PATH compatibility, or adding restore options."
  - "Changing backup creation, archive format, managed-member validation rules, or metadata parsing."
  - "Changing non-restore storage, migration, watcher, import/export, or KnowledgeGraph behavior."
  - "Deleting unrelated entries from an existing palace directory during --force restore."
  - "Backlog completion, archive bookkeeping, commits, publication, or release operations."
contract_policy:
  flow: full_spdd
  reason: "Standard release-blocking data-safety fix at the persistent restore boundary requires explicit state, authority, and mutation-order contracts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Non-force restore must reject initial palace or selected KG state before extraction and use no-clobber publication for the exact Lance and selected KG names."
      source: "backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Collision refusal must cover every listed palace and KG shape and preserve all existing bytes across retries."
      source: "backlog AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Restore to absent palace and KG destinations must continue to succeed."
      source: "backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Explicit force restore must retain archive validation and atomic KG replacement for the collision matrix."
      source: "backlog AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "restore state boundary"
      kind: store
      paths: ["mempalace_code/backup.py"]
      expected_behavior: "restore_backup inventories validated archive members, rejects initial non-force collisions before extraction, uses exclusive Lance-root creation and atomic no-replace KG publication, and lets explicit force replace validated managed Lance/KG objects without modifying symlink referents."
    - name: "restore CLI regression coverage"
      kind: cli
      paths: ["tests/test_backup_cli.py"]
      expected_behavior: "CLI tests prove initial and post-preflight refusal ordering and immutability, absent-destination success, explicit/default KG routing, repeated invocation, force behavior, and archive-validation safety."
  invariants:
    - id: INV-1
      statement: "Explicit --kg-path continues to win over palace scoping, explicit --palace continues to scope KG under that palace, and an omitted palace/--kg-path continues to select DEFAULT_KG_PATH."
      applies_to: ["mempalace_code/backup.py", "tests/test_backup_cli.py"]
    - id: INV-2
      statement: "Managed archive members and metadata are fully validated before force removes or replaces any destination state."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-3
      statement: "KG restoration copies to a randomized sibling temporary file; non-force publishes it with atomic no-replace hard-link creation, while force uses atomic replacement."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-4
      statement: "Force restore of a palace directory replaces managed Lance/KG state without deleting unrelated palace entries."
      applies_to: ["mempalace_code/backup.py", "tests/test_backup_cli.py"]
    - id: INV-5
      statement: "An existing empty palace directory remains a valid non-force destination when its selected KG destination is absent."
      applies_to: ["mempalace_code/backup.py", "tests/test_backup_cli.py"]
    - id: INV-6
      statement: "Non-force publication claims the exact Lance root exclusively and atomically refuses an existing selected KG publication name; arbitrary concurrent edits elsewhere under the palace are outside the transaction boundary."
      applies_to: ["mempalace_code/backup.py", "tests/test_backup_cli.py"]
  risks:
    - id: RISK-1
      risk: "A late KG collision check could leave newly extracted Lance state beside the untouched KG."
      mitigation: "Publish non-force KG with atomic no-replace creation and remove only the Lance root still owned by this invocation when KG publication fails."
    - id: RISK-2
      risk: "Filesystem type checks could follow a palace symlink and mutate state outside the selected path."
      mitigation: "Use non-following existence/type handling for the palace root; non-force rejects it and force removes only the link before creating the restore directory."
    - id: RISK-3
      risk: "Broad force cleanup could remove unrelated files in an existing palace directory."
      mitigation: "Keep force cleanup scoped to the selected non-directory root when necessary, the managed lance directory, and the selected KG destination."
    - id: RISK-4
      risk: "Strengthening collision detection could reject the historical empty-directory restore path."
      mitigation: "Define palace state as a non-directory/symlink root or a directory with entries and retain an explicit empty-directory regression."
    - id: RISK-5
      risk: "Lance or KG state can appear after preflight and be replaced by a check-then-publish sequence."
      mitigation: "Use exclusive Lance-root creation and atomic no-replace KG hard-link publication; fail closed when the filesystem cannot provide the KG primitive."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_backup_cli.py::TestRestoreTargetStateCollisionGuard -q"
      owner: provider
      proves: "The public CLI refuses initial and deterministically raced-in palace/KG collisions, preserves collided bytes across retries, and still restores to absent or empty destinations."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      command: "python -m pytest tests/test_backup_cli.py::TestRestoreForceCollisionGuard -q"
      owner: provider
      proves: "Explicit force handles the collision matrix while preserving validation-before-mutation, unrelated entries, and atomic KG replacement."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_backup.py -q"
        owner: provider
        proves: "Existing low-level backup round trips, archive/member rejection, force restore, and KG atomic-replacement behavior remain compatible."
        acceptance_ids: [AC-3, AC-4]
      - id: REG-2
        command: "python -m pytest tests/test_docs_drift_guard.py::test_backup_restore_runbook_contract -q"
        owner: provider
        proves: "The existing public documentation contract rejects regression to unsafe overwrite guidance or omission of the reviewed recovery boundaries."
        acceptance_ids: [AC-1, AC-4]
---

## Design Notes

- Keep `restore_backup()` as the sole owner. Do not add collision logic to `cmd_restore()` or create a second restore helper.
- Preserve the current order that opens the archive, validates all managed members, and parses metadata before any destructive action. After that validation, compute the destination collision decision before extraction, then use exact-name no-clobber primitives at non-force Lance and KG publication.
- For non-force palace detection, treat an existing symlink or non-directory root as state and treat a real directory as state when it has any entry, including a KG-only file, an empty `lance/` entry, or an unrelated file. A real empty palace directory remains usable.
- Treat an existing selected KG path as a collision using non-following existence semantics so regular files, SQLite databases, and symlinks cannot be replaced without `--force`. Apply the check to the destination resolved by the existing CLI precedence, including explicit `--kg-path`, palace-scoped KG, and `DEFAULT_KG_PATH`.
- Raise `FileExistsError` before extraction for an initial collision and when an exact managed publication name is raced in. Include concrete collided destinations when available and direct the user to back up reported state before intentional force.
- Under explicit force, unlink a palace root that is a file or symlink without following it; for a real palace directory, remove only its managed `lance/` subtree. Preserve unrelated directory entries. Publish an archived KG through an exclusively created randomized sibling temporary file plus `os.replace`, leaving legacy predictable `.tmp` paths and their referents untouched.
- In non-force mode, claim `lance/` with exclusive directory creation and publish the completed KG temporary file with `os.link`. Fail closed without a fallback when hard links are unavailable. On copy or KG publication failure, remove only a Lance root whose recorded device/inode identity still belongs to this invocation; remove its newly created palace root only when empty.
- Treat exact Lance and selected-KG names as the cross-platform no-clobber boundary. Do not claim a transaction for hostile ancestor replacement or arbitrary concurrent entries elsewhere under the palace.
- If validated archive extraction or copy fails, remove temporary artifacts through the existing temporary-directory lifecycle and leave pre-existing managed state unchanged whenever replacement has not started. Do not broaden this task into transactional Lance replacement.
- Build the CLI matrix with isolated paths and byte snapshots. Include KG-only palace content, regular-file and symlink palace roots, non-empty Lance, explicit and default-global KG destinations, first restore followed by a refused repeat, absent destinations, an existing empty palace directory, and deterministic hooks that create palace or selected KG state after initial preflight but before publication.
- Add force cases for the same palace/KG shapes. Assert that links themselves are replaced without modifying their referents, unrelated palace entries survive, the restored store/KG are readable, and malformed/traversal archives cannot change sentinels even with force.
- Verification commands run from the repository root. `pyproject.toml` declares `tests` as the pytest root and excludes `needs_network` and `slow` by default; the two new test classes are bounded provider-owned checks, while the existing low-level backup module is the focused regression owner.
