---
slug: RESTORE-KG-PATH-SCOPING
status: completed
authority: non_authoritative
goal: "Make CLI tarball restore send KG data to an explicit palace-scoped destination instead of silently overwriting the default global KG"
risk: medium
risk_note: "The change affects restore data placement for an existing CLI command. Risk is contained by leaving restore_backup() defaults intact, scoping only explicit CLI --palace restores, and adding regression tests for default behavior."
files:
  - path: mempalace_code/cli.py
    change: "Add a restore --kg-path PATH option and help text explaining that explicit --palace restores default KG output to <palace>/knowledge_graph.sqlite3."
  - path: mempalace_code/cli_commands/backup_restore.py
    change: "Resolve the CLI restore KG destination: --kg-path wins; otherwise an explicit top-level --palace restores KG to <palace>/knowledge_graph.sqlite3; no explicit palace preserves restore_backup() default behavior."
  - path: tests/test_backup_cli.py
    change: "Add CLI restore regression tests for explicit palace KG scoping, refusal without --force not touching KG files, --kg-path override, and no-palace default behavior."
  - path: docs/BACKUP_RESTORE.md
    change: "Document tarball restore KG destination behavior for default restores, explicit --palace restores, and --kg-path overrides."
acceptance:
  - id: AC-1
    when: "`mempalace-code --palace <custom> restore <archive>` restores an archive that contains `knowledge_graph.sqlite3` while the default KG path contains a sentinel database"
    then: "`<custom>/knowledge_graph.sqlite3` contains the restored KG data and the default KG sentinel remains unchanged"
  - id: AC-2
    when: "`mempalace-code --palace <custom> restore <archive>` is run against a non-empty target without `--force`"
    then: "the command exits 1 with the existing `Use --force` error and neither the custom KG file nor the default KG file is modified"
  - id: AC-3
    when: "`mempalace-code --palace <custom> restore <archive> --kg-path <explicit>` restores an archive that contains KG data"
    then: "the KG data is written to `<explicit>`, not to `<custom>/knowledge_graph.sqlite3` and not to the default KG path"
  - id: AC-4
    when: "`mempalace-code restore <archive>` is run without top-level `--palace` or `--kg-path`"
    then: "existing default behavior is preserved: the KG data is written to `knowledge_graph.DEFAULT_KG_PATH`"
out_of_scope:
  - "Changing `restore_backup()` library defaults or removing its `kg_path=None` default"
  - "Changing backup creation KG source scoping"
  - "Changing mining, import/export, MCP, or watcher KG paths"
  - "Migrating existing user KG files or modifying config schema"
contract_policy:
  flow: full_spdd
  reason: "Standard task changes restore data destination semantics for a CLI that can overwrite local KG state."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "An explicit CLI --palace restore must not write archived KG data to the default global KG path unless the user explicitly requests that path."
      source: "backlog description"
      acceptance_ids: [AC-1, AC-2]
    - id: REQ-2
      statement: "The CLI must provide an explicit KG destination override for restore."
      source: "safer explicit restore scoping"
      acceptance_ids: [AC-3]
    - id: REQ-3
      statement: "Users who restore without --palace must keep the existing default KG restore behavior."
      source: "backward compatibility"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "restore parser"
      kind: cli
      paths: ["mempalace_code/cli.py"]
      expected_behavior: "The restore command accepts --kg-path and its help text describes the palace-scoped default for explicit --palace restores."
    - name: "restore command handler"
      kind: cli
      paths: ["mempalace_code/cli_commands/backup_restore.py"]
      expected_behavior: "The handler passes a resolved kg_path into restore_backup() only when CLI inputs require a scoped or explicit KG destination."
    - name: "restore CLI regression tests"
      kind: internal
      paths: ["tests/test_backup_cli.py"]
      expected_behavior: "Tests exercise the public CLI behavior and verify KG file placement by querying SQLite-backed KnowledgeGraph instances."
    - name: "backup restore documentation"
      kind: internal
      paths: ["docs/BACKUP_RESTORE.md"]
      expected_behavior: "Documentation states where tarball restore writes KG data for default, --palace, and --kg-path modes."
  invariants:
    - id: INV-1
      statement: "restore_backup(archive, palace, kg_path=None) continues to default to knowledge_graph.DEFAULT_KG_PATH for direct library callers."
      applies_to: ["mempalace_code/backup.py"]
    - id: INV-2
      statement: "A restore refusal for a non-empty palace without --force must occur before any Lance or KG mutation."
      applies_to: ["mempalace_code/cli_commands/backup_restore.py", "mempalace_code/backup.py"]
    - id: INV-3
      statement: "The top-level --palace option continues to select the Lance restore target exactly as before."
      applies_to: ["mempalace_code/cli_commands/backup_restore.py"]
  risks:
    - id: RISK-1
      risk: "Changing restore KG placement could surprise users who intentionally relied on --palace restoring KG into the global default."
      mitigation: "Preserve default behavior when --palace is absent and document --kg-path for intentional global or custom destinations."
    - id: RISK-2
      risk: "The restore handler could create or overwrite a KG file even after the existing non-empty-palace refusal path."
      mitigation: "Keep restore_backup() refusal ordering unchanged and add a CLI failure-path test that checks both scoped and default KG sentinels."
    - id: RISK-3
      risk: "A scoped KG destination could be ambiguous when both --palace and --kg-path are supplied."
      mitigation: "Define --kg-path as the explicit override and verify it wins over the palace-scoped default."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_backup_cli.py -k restore_cli_explicit_palace_scopes_kg -q"
      proves: "Explicit --palace restore writes archived KG data under the palace and leaves DEFAULT_KG_PATH untouched."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_backup_cli.py -k restore_cli_refusal_does_not_touch_kg -q"
      proves: "Non-forced restore refusal exits before mutating scoped or default KG files."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_backup_cli.py -k restore_cli_kg_path_overrides_palace_scope -q"
      proves: "--kg-path is the explicit restore destination and wins over --palace scoping."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_backup_cli.py -k restore_cli_default_without_palace_keeps_default_kg -q"
      proves: "No-palace restore keeps the existing DEFAULT_KG_PATH behavior."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_backup_cli.py tests/test_backup.py -q"
        proves: "The focused CLI change and existing low-level backup/restore behaviors remain compatible."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Keep `restore_backup()` as the low-level API compatibility boundary. It already accepts `kg_path`; the bug is that `cmd_restore()` never supplies one for explicit CLI palace restores.
- Add `restore --kg-path PATH` as an escape hatch for intentional global, shared, or otherwise custom KG restore destinations.
- Use `args.palace is not None` as the signal for explicit palace scoping. If the user relies on config or env defaults and does not pass top-level `--palace`, CLI restore keeps the historical `DEFAULT_KG_PATH` behavior.
- Resolve `--kg-path` with `os.path.expanduser()`. For the palace-scoped default, join the already-expanded `palace_path` with `knowledge_graph.sqlite3`.
- Do not add KG existence checks to the CLI handler. `restore_backup()` already copies the KG only when the archive contains `mempalace_backup/knowledge_graph.sqlite3`.
- In tests, patch `mempalace_code.knowledge_graph.DEFAULT_KG_PATH` before invoking CLI restore as needed, create archives with isolated KG files, and query restored KG files through `KnowledgeGraph(db_path=...)` rather than relying on raw SQLite implementation details.
- Failure-path tests should seed both default and scoped KG sentinels before the refusing restore and then query them afterward, so a partial mutation is caught.
- Documentation should distinguish JSONL import/export KG behavior from tarball restore KG behavior; this task only changes the tarball restore section.
