---
slug: CLI-COMMAND-MODULES
goal: "Split CLI command handlers into focused modules while preserving the existing argparse and console-script entry points."
risk: medium
risk_note: "Behavior-preserving refactor across many CLI handlers; risk is mostly import cycles, broken monkeypatch seams, and changed argparse/exit behavior."
files:
  - path: mempalace_code/cli.py
    change: "Keep the public main()/main_alias() entry points and argparse wiring stable while importing command handlers from cli_commands modules; re-export legacy helpers used by tests and callers."
  - path: mempalace_code/cli_commands/__init__.py
    change: "Create the command-handler package and expose focused module groups without importing heavy runtime dependencies."
  - path: mempalace_code/cli_commands/common.py
    change: "Add small shared helpers for palace path resolution, include-ignored parsing, and byte formatting used by multiple command modules."
  - path: mempalace_code/cli_commands/alias.py
    change: "Move mempalace-code-alias helpers and install-alias command handling while preserving symlink conflict behavior."
  - path: mempalace_code/cli_commands/model.py
    change: "Move fetch_model() and the fetch-model command handler while preserving HF_HOME/cache behavior."
  - path: mempalace_code/cli_commands/ingest.py
    change: "Move init, onboarding, mine, mine-all, split, status, and spellcheck resolution handlers."
  - path: mempalace_code/cli_commands/query.py
    change: "Move search, wake-up, and compress handlers."
  - path: mempalace_code/cli_commands/maintenance.py
    change: "Move health, cleanup, repair, migrate-storage, and shared maintenance output handling while keeping migrate's lazy `from .migrate import` seam."
  - path: mempalace_code/cli_commands/watch.py
    change: "Move watch, watch schedule, and watch status handlers while keeping lazy watcher imports."
  - path: mempalace_code/cli_commands/backup_restore.py
    change: "Move backup create/list/schedule dispatch plus restore handling."
  - path: mempalace_code/cli_commands/diary.py
    change: "Move diary write and diary dispatch handlers."
  - path: mempalace_code/cli_commands/export_import.py
    change: "Move export and import command handlers."
  - path: tests/test_cli_command_modules.py
    change: "Add command-module import contract tests for stable re-exports, dispatch mapping, and no eager heavy imports during CLI import."
  - path: tests/test_cli.py
    change: "Update command-level tests and monkeypatch targets to the new module owners without narrowing existing behavior coverage."
  - path: tests/test_backup_cli.py
    change: "Update backup/restore CLI tests if handler patch/import seams move; preserve no-verb backup and restore failure coverage."
  - path: tests/test_watcher.py
    change: "Update watch-related CLI dispatch tests if cmd_mine/cmd_watch move; preserve watcher lazy import and incompatible-flag coverage."
  - path: tests/test_packaging_namespace.py
    change: "Add or keep assertions that console-script targets remain mempalace_code:main and mempalace_code.cli:main_alias."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_cli_command_modules.py::test_cli_module_exports_stable_entry_points tests/test_packaging_namespace.py::test_console_scripts_use_mempalace_code_namespace -q` is run"
    then: "mempalace_code.cli still exports main, main_alias, install_legacy_alias, and fetch_model, and pyproject console scripts still point to mempalace_code:main and mempalace_code.cli:main_alias."
  - id: AC-2
    when: "`python -m pytest tests/test_cli.py::TestLegacyAlias::test_install_alias_subcommand_dispatches -q` is run"
    then: "mempalace-code install-alias creates the mempalace symlink through the moved alias handler with the same target-dir behavior."
  - id: AC-3
    when: "`python -m pytest tests/test_cli.py::TestMineSpellcheckFlags::test_project_mode_defaults_spellcheck_false tests/test_cli.py::TestMineSpellcheckFlags::test_convos_mode_defaults_spellcheck_true tests/test_cli.py::TestMineGeneralEmotionalFlag::test_mine_convos_general_include_emotional_dispatches_categories -q` is run"
    then: "the moved mine handler keeps project/conversation spellcheck defaults and the general emotional extraction category wiring."
  - id: AC-4
    when: "`python -m pytest tests/test_watcher.py::TestCliWatchDispatch::test_cli_watch_dispatches_to_watcher_module tests/test_watcher.py::TestWatchFlagValidation::test_watch_rejects_dry_run -q` is run"
    then: "mine --watch still lazy-imports mempalace_code.watcher.watch_and_mine, passes the same arguments, and exits 2 for the incompatible --dry-run boundary."
  - id: AC-5
    when: "`python -m pytest tests/test_backup_cli.py::test_backup_cli_default_out tests/test_backup_cli.py::test_restore_cli_error_exit tests/test_cli.py::TestBackupCommand::test_backup_list_empty -q` is run"
    then: "backup with no verb still creates an archive, restore without --force on a non-empty target still exits 1 with Use --force, and backup list with no backups still exits 0 with No backups found."
  - id: AC-6
    when: "`python -m pytest tests/test_cli.py::TestDiaryWrite::test_diary_write_success tests/test_cli.py::TestDiaryWrite::test_diary_bare_subcommand tests/test_cli.py::TestHealthCommand::test_health_command_json_output tests/test_cli.py::TestCleanupCommand::test_cleanup_dependency_error_exits_cleanly -q` is run"
    then: "diary, health, and cleanup handlers keep their success output, missing-subcommand exit code, JSON output, and clean dependency-error path after moving modules."
  - id: AC-7
    when: "`python -m pytest tests/test_cli.py::TestMigrateStorageCommand::test_migrate_storage_cli_happy_path tests/test_cli.py::TestMigrateStorageCommand::test_migrate_storage_cli_verify_fail tests/test_cli.py::TestMigrateStorageCommand::test_migrate_storage_cli_runtime_error_exits_1 -q` is run"
    then: "migrate-storage still dispatches to the moved handler, calls mempalace_code.migrate.migrate_chroma_to_lance with the same kwargs, and exits 1 on VerificationError or RuntimeError with the same stderr prefixes."
out_of_scope:
  - "Changing command names, flags, help text semantics, console-script targets, or exit codes."
  - "Changing storage, mining, backup, watcher, search, KG, export/import, or model-download behavior."
  - "Replacing argparse or adding a new CLI framework."
  - "Renaming mempalace-code, mempalace-code-alias, or the optional mempalace legacy alias."
  - "Backlog metadata edits, release/publish work, or broad documentation updates beyond tests needed for the refactor."
contract_policy:
  flow: full_spdd
  reason: "Standard refactor of a public CLI surface with many command handlers and packaging entry-point compatibility requirements."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The public CLI entry points and helper exports must remain compatible for mempalace-code and mempalace-code-alias."
      source: "backlog scope and AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Command handlers must move out of cli.py into focused modules without changing observable command behavior."
      source: "backlog scope"
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
    - id: REQ-3
      statement: "Parser dispatch must keep existing command names, nested command defaults, and boundary error handling."
      source: "backlog public command stability"
      acceptance_ids: [AC-3, AC-4, AC-5, AC-6, AC-7]
    - id: REQ-4
      statement: "Tests must align monkeypatch/import seams with the new command-module owners without reducing behavior coverage."
      source: "backlog test alignment scope"
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
  surfaces:
    - name: "Argparse entry point"
      kind: cli
      paths: ["mempalace_code/cli.py"]
      expected_behavior: "main() builds the same parser, applies the same validation gates, and dispatches to moved handlers."
    - name: "Command handler modules"
      kind: internal
      paths: ["mempalace_code/cli_commands/__init__.py", "mempalace_code/cli_commands/common.py", "mempalace_code/cli_commands/alias.py", "mempalace_code/cli_commands/model.py", "mempalace_code/cli_commands/ingest.py", "mempalace_code/cli_commands/query.py", "mempalace_code/cli_commands/maintenance.py", "mempalace_code/cli_commands/watch.py", "mempalace_code/cli_commands/backup_restore.py", "mempalace_code/cli_commands/diary.py", "mempalace_code/cli_commands/export_import.py"]
      expected_behavior: "Focused modules own command logic (including migrate-storage under maintenance.py) while preserving lazy imports and existing stdout/stderr/sys.exit behavior."
    - name: "Alias and packaging compatibility"
      kind: cli
      paths: ["mempalace_code/cli.py", "mempalace_code/cli_commands/alias.py", "tests/test_packaging_namespace.py"]
      expected_behavior: "mempalace-code-alias still calls mempalace_code.cli:main_alias and install-alias keeps symlink safety behavior."
    - name: "CLI regression tests"
      kind: internal
      paths: ["tests/test_cli_command_modules.py", "tests/test_cli.py", "tests/test_backup_cli.py", "tests/test_watcher.py", "tests/test_packaging_namespace.py"]
      expected_behavior: "Tests cover the moved module boundaries and key command success, failure, and boundary cases."
  invariants:
    - id: INV-1
      statement: "The pyproject console-script targets remain `mempalace-code = mempalace_code:main` and `mempalace-code-alias = mempalace_code.cli:main_alias`."
      applies_to: ["mempalace_code/cli.py", "tests/test_packaging_namespace.py"]
    - id: INV-2
      statement: "mempalace_code.cli continues exporting main, main_alias, install_legacy_alias, and fetch_model for current tests and downstream direct imports."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/cli_commands/alias.py", "mempalace_code/cli_commands/model.py"]
    - id: INV-3
      statement: "Importing mempalace_code.cli must not eagerly import watcher, sentence-transformers, LanceDB stores, or mining backends beyond the current lazy points."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/cli_commands/"]
    - id: INV-4
      statement: "Command stdout/stderr strings and sys.exit codes for covered boundaries remain unchanged unless an existing test explicitly updates only an import seam."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/cli_commands/"]
    - id: INV-5
      statement: "Argparse validation for nested commands and incompatible flags remains in the entry-point path before handler dispatch where it is today."
      applies_to: ["mempalace_code/cli.py"]
  risks:
    - id: RISK-1
      risk: "Moving handlers breaks direct imports from mempalace_code.cli used by tests or external callers."
      mitigation: "Keep cli.py as a compatibility facade that re-exports main, main_alias, install_legacy_alias, and fetch_model; add an import-contract test."
    - id: RISK-2
      risk: "Heavy dependencies load on CLI import because moved modules import storage, watcher, or sentence-transformers at module import time."
      mitigation: "Keep command modules using function-local imports for heavy dependencies and test CLI import does not populate those modules."
    - id: RISK-3
      risk: "Parser validation drifts when dispatch logic moves away from cli.py."
      mitigation: "Leave parser construction and validation gates in cli.py for this task; only move command handler bodies."
    - id: RISK-4
      risk: "Existing monkeypatches stop intercepting behavior after handler ownership changes."
      mitigation: "Update tests to patch the real owner modules while keeping behavior assertions unchanged."
    - id: RISK-5
      risk: "Shared helper moves introduce circular imports between cli.py and command modules."
      mitigation: "Put neutral helpers in cli_commands.common and keep command modules independent of cli.py except for public facade re-exports from cli.py."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_cli_command_modules.py::test_cli_module_exports_stable_entry_points tests/test_packaging_namespace.py::test_console_scripts_use_mempalace_code_namespace -q"
      proves: "Public CLI exports and console-script targets remain stable."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_cli.py::TestLegacyAlias::test_install_alias_subcommand_dispatches -q"
      proves: "The moved alias handler still creates the legacy mempalace symlink through the install-alias command."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_cli.py::TestMineSpellcheckFlags::test_project_mode_defaults_spellcheck_false tests/test_cli.py::TestMineSpellcheckFlags::test_convos_mode_defaults_spellcheck_true tests/test_cli.py::TestMineGeneralEmotionalFlag::test_mine_convos_general_include_emotional_dispatches_categories -q"
      proves: "The moved mine handler preserves ingest-mode defaults and category wiring."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_watcher.py::TestCliWatchDispatch::test_cli_watch_dispatches_to_watcher_module tests/test_watcher.py::TestWatchFlagValidation::test_watch_rejects_dry_run -q"
      proves: "mine --watch keeps lazy watcher dispatch and incompatible-flag exit behavior."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_backup_cli.py::test_backup_cli_default_out tests/test_backup_cli.py::test_restore_cli_error_exit tests/test_cli.py::TestBackupCommand::test_backup_list_empty -q"
      proves: "Backup and restore command defaults and failure paths survive handler moves."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_cli.py::TestDiaryWrite::test_diary_write_success tests/test_cli.py::TestDiaryWrite::test_diary_bare_subcommand tests/test_cli.py::TestHealthCommand::test_health_command_json_output tests/test_cli.py::TestCleanupCommand::test_cleanup_dependency_error_exits_cleanly -q"
      proves: "Diary, health, and cleanup success/failure outputs remain stable."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_cli.py::TestMigrateStorageCommand -q"
      proves: "migrate-storage dispatch wiring, kwarg passthrough, and VerificationError/RuntimeError exit paths survive the handler move into maintenance.py."
      acceptance_ids: [AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_cli_command_modules.py tests/test_cli.py tests/test_backup_cli.py tests/test_watcher.py::TestCliWatchDispatch tests/test_watcher.py::TestWatchFlagValidation tests/test_packaging_namespace.py -q"
        proves: "Focused CLI, alias, backup, watcher, and packaging regressions remain green after the split."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-2
        command: "python -m pytest tests/test_e2e.py::test_mine_search_export_nuke_import tests/test_export.py -q"
        proves: "High-level mine/search and export/import flows still work through the public CLI-facing modules."
        acceptance_ids: [AC-3]
      - id: REG-3
        command: "ruff check mempalace_code/ tests/ && ruff format --check mempalace_code/ tests/"
        proves: "Moved modules and updated imports satisfy project lint and formatting gates."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
---

## Design Notes

- Keep `mempalace_code/cli.py` as the compatibility facade. It should retain `main()` and parser construction, import handlers from `mempalace_code.cli_commands.*`, and re-export `main_alias`, `install_legacy_alias`, and `fetch_model`.
- Use a new `mempalace_code/cli_commands/` package rather than a `mempalace_code/cli/` package, because `cli.py` already owns the public module name used by console scripts and direct imports.
- Move handler bodies mechanically first. Avoid changing argparse option definitions, help strings, print text, `sys.exit(...)` codes, or command names while moving code.
- Suggested ownership:
  - `alias.py`: `CANONICAL_CLI_COMMAND`, `LEGACY_CLI_ALIAS`, `_same_command_path`, `_resolve_canonical_cli`, `install_legacy_alias`, `cmd_install_alias`, `main_alias`.
  - `model.py`: `fetch_model`, `cmd_fetch_model`.
  - `ingest.py`: `cmd_init`, `cmd_onboarding`, `cmd_mine`, `_resolve_spellcheck`, `cmd_mine_all`, `cmd_split`, `cmd_status`.
  - `query.py`: `cmd_search`, `cmd_wakeup`, `cmd_compress`.
  - `maintenance.py`: `cmd_health`, `cmd_cleanup`, `cmd_repair`, `cmd_migrate_storage`. Keep the handler-local `from .migrate import VerificationError, migrate_chroma_to_lance` lazy import in place after the move so importing `mempalace_code.cli_commands.maintenance` does not pull in the migrator at CLI load time, and so existing `patch("mempalace_code.migrate.migrate_chroma_to_lance", ...)` test seams in `tests/test_cli.py::TestMigrateStorageCommand` continue to intercept the call.
  - `watch.py`: `cmd_watch`, `cmd_watch_schedule`, `cmd_watch_status`.
  - `backup_restore.py`: `cmd_backup_create`, `cmd_backup_list`, `cmd_backup_schedule`, `cmd_backup`, `cmd_restore`.
  - `diary.py`: `cmd_diary_write`, `cmd_diary`.
  - `export_import.py`: `cmd_export`, `cmd_import`.
- Keep heavy imports inside handler functions. `tests/test_cli_command_modules.py` should guard that importing `mempalace_code.cli` does not import `sentence_transformers`, `watchfiles`, `lancedb`, or the mining orchestrator unless a command path invokes them.
- Tests should update monkeypatch targets only where ownership changes. For example, handler-local imports of `mempalace_code.watcher.watch_and_mine`, `mempalace_code.convo_miner.mine_convos`, and `mempalace_code.mining.orchestrator.mine` should remain patchable at the dependency module, not through `cli.py`.
- Prefer one new command-module contract test over broad test rewrites. Existing CLI tests already cover alias, init, mine, diary, health, cleanup, backup, restore, and watcher behavior; keep those assertions intact.
- After implementation, run focused CLI tests first, then lint/format checks. Do not use full-suite success as the only evidence; report which command behavior groups were exercised.
