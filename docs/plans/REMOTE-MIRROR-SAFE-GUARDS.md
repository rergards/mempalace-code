---
slug: REMOTE-MIRROR-SAFE-GUARDS
goal: "Add remote mirror safety guidance and a CLI preflight for destructive MemPalace state syncs"
risk: medium
risk_note: "Adds a new operator-facing CLI guard around data-loss-prone rsync command shapes while documenting backup/mirror boundaries."
files:
  - path: mempalace_code/mirror_preflight.py
    change: "Add pure rsync command inspection helpers that detect delete-mode MemPalace state mirrors and required exclude families."
  - path: mempalace_code/cli_commands/preflight.py
    change: "Add a non-executing preflight command handler with human and JSON output plus exit codes for safe, blocked, and parse-error cases."
  - path: mempalace_code/cli.py
    change: "Register `mempalace-code preflight mirror --command ...` and route it to the preflight handler."
  - path: tests/test_cli.py
    change: "Cover safe mirror commands, dangerous delete-mode state mirrors, non-state/no-delete boundaries, and JSON output."
  - path: README.md
    change: "Add concise backup-vs-file-mirror guidance and a safe rsync/preflight example near backup and health docs."
  - path: docs/BACKUP_RESTORE.md
    change: "Document that managed backups/cleanup do not protect independent-host delete-mode mirrors and list recommended rsync excludes."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_safe_mirror_with_required_excludes_exits_zero -q` is run"
    then: "an rsync command using --delete against ~/.mempalace with explicit palace, KG, config, log, and backups excludes exits 0 and reports the command as safe"
  - id: AC-2
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_delete_mode_state_mirror_missing_excludes_exits_nonzero -q` is run"
    then: "a bare `rsync -a --delete ~/.mempalace/ host:.mempalace/` exits nonzero and reports missing excludes for live palace, KG, config, logs, and managed backups"
  - id: AC-3
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_non_state_or_no_delete_commands_remain_ok -q` is run"
    then: "non-MemPalace rsync --delete commands and MemPalace rsync commands without delete semantics do not trigger the destructive mirror guard"
  - id: AC-4
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_mirror_preflight_json_reports_missing_excludes -q` is run"
    then: "`--json` output is valid JSON that includes ok=false, the dangerous pattern id, and the missing exclude families"
  - id: AC-5
    when: "`rg -n 'file mirroring|rsync --delete|knowledge_graph.sqlite3|backups/|config.json|\\.log' README.md docs/BACKUP_RESTORE.md` is run"
    then: "both docs distinguish managed backups from file mirroring and show safe exclude guidance for palace, KG, config, logs, and backups"
out_of_scope:
  - "Executing, installing, scheduling, or auto-rewriting rsync/launchd/cron mirror jobs."
  - "Inspecting live remote hosts or machine-local operator scripts during implementation."
  - "Changing backup creation, restore behavior, Lance cleanup, or destructive MCP delete tools."
  - "Editing backlog metadata, archive files, or bookkeep-owned task state."
contract_policy:
  flow: full_spdd
  reason: "Standard data-safety task with operator-facing CLI behavior and destructive mirror risk."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Operators must have public guidance that managed backups/cleanup are separate from cross-host file mirroring risk."
      source: "backlog acceptance"
      acceptance_ids: [AC-5]
    - id: REQ-2
      statement: "Recommended rsync examples must exclude live palace directories, KG databases, configs, logs, and managed backups unless the operator is intentionally restoring from a known-good source."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-5]
    - id: REQ-3
      statement: "A preflight path must flag delete-mode MemPalace state directory mirrors that lack explicit excludes."
      source: "backlog acceptance"
      acceptance_ids: [AC-2, AC-4]
    - id: REQ-4
      statement: "The preflight guard must avoid false positives for rsync commands that are not delete-mode MemPalace state mirrors."
      source: "boundary behavior"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "Mirror command classifier"
      kind: internal
      paths: ["mempalace_code/mirror_preflight.py"]
      expected_behavior: "Parse an rsync command string without executing it, detect --delete semantics, identify MemPalace state-dir targets, and compute missing exclude families."
    - name: "Preflight CLI"
      kind: cli
      paths: ["mempalace_code/cli.py", "mempalace_code/cli_commands/preflight.py"]
      expected_behavior: "Expose `mempalace-code preflight mirror --command ...` with exit 0 for safe commands, exit 1 for blocked dangerous mirrors, exit 2 for malformed inputs, and JSON output for automation."
    - name: "CLI tests"
      kind: internal
      paths: ["tests/test_cli.py"]
      expected_behavior: "Exercise safe, blocked, boundary, and JSON preflight behavior through the public CLI entry point."
    - name: "Operator docs"
      kind: cli
      paths: ["README.md", "docs/BACKUP_RESTORE.md"]
      expected_behavior: "Explain backup versus file-mirror semantics and show rsync excludes plus the preflight check operators can run before installing mirror jobs."
  invariants:
    - id: INV-1
      statement: "The preflight command must never execute, shell out to, or install the command string it inspects."
      applies_to: ["mempalace_code/mirror_preflight.py", "mempalace_code/cli_commands/preflight.py"]
    - id: INV-2
      statement: "Existing `health`, `cleanup`, `backup`, and `restore` command behavior and exit codes remain unchanged."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/cli_commands/preflight.py", "tests/test_cli.py"]
    - id: INV-3
      statement: "Managed backup retention and Lance cleanup must remain scoped to their current storage paths and must not try to manage remote mirrors."
      applies_to: ["README.md", "docs/BACKUP_RESTORE.md"]
    - id: INV-4
      statement: "The guard should classify only command text and explicit excludes; it must not assume absence of remote data from a local state scan."
      applies_to: ["mempalace_code/mirror_preflight.py"]
  risks:
    - id: RISK-1
      risk: "A broad string heuristic could block unrelated rsync commands."
      mitigation: "Require both rsync delete semantics and a MemPalace state-dir target before warning or failing."
    - id: RISK-2
      risk: "A narrow exclude matcher could reject reasonable safe patterns such as `--exclude=palace*/`."
      mitigation: "Implement exclude-family matching with accepted concrete and wildcard patterns, and cover the recommended examples in tests."
    - id: RISK-3
      risk: "Docs could imply backups protect against remote-owned data deletion."
      mitigation: "State explicitly that managed backups/cleanup do not protect independent hosts from `rsync --delete`; recommend backup/export restore flows instead of whole-state mirrors."
    - id: RISK-4
      risk: "Operators may want to inspect scripts instead of pasting a command string."
      mitigation: "Keep script discovery out of scope; document the command-string preflight as the supported first guard and leave host/job inventory to operator runbooks."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_safe_mirror_with_required_excludes_exits_zero -q"
      proves: "A delete-mode MemPalace state mirror with required excludes is accepted."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_delete_mode_state_mirror_missing_excludes_exits_nonzero -q"
      proves: "The dangerous bare rsync --delete state mirror is blocked and reports missing exclude families."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_non_state_or_no_delete_commands_remain_ok -q"
      proves: "The guard does not fail on non-state delete rsyncs or MemPalace rsyncs without delete semantics."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_mirror_preflight_json_reports_missing_excludes -q"
      proves: "Automation gets valid JSON with the dangerous pattern id and missing exclude families."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "rg -n 'file mirroring|rsync --delete|knowledge_graph.sqlite3|backups/|config.json|\\.log' README.md docs/BACKUP_RESTORE.md"
      proves: "Docs expose backup/mirror distinction and all required safe rsync exclude categories."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand -q"
        proves: "All mirror preflight behavior remains stable across safe, blocked, boundary, and JSON cases."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        command: "python -m pytest tests/test_cli.py::TestHealthCommand tests/test_cli.py::TestBackupCommand -q"
        proves: "Existing health and backup CLI surfaces still run after adding the preflight command registration."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-3
        command: "rg -n 'file mirroring|rsync --delete|knowledge_graph.sqlite3|backups/|config.json|\\.log' README.md docs/BACKUP_RESTORE.md"
        proves: "Future docs edits do not drop the backup/mirror warning or required exclude categories."
        acceptance_ids: [AC-5]
---

## Design Notes

- Add a dedicated `preflight mirror` command instead of overloading `health`: `health` reads storage state, while this guard inspects an operator command string before a mirror job exists.
- The preflight command must be non-executing. Use `shlex.split` to tokenize the supplied command and return a parse error on malformed shell text.
- Dangerous pattern: command resolves to `rsync`, contains `--delete` or an rsync delete variant, and references a MemPalace state directory such as `~/.mempalace`, `$HOME/.mempalace`, the configured palace path, or the configured palace parent.
- Required exclude families for delete-mode state mirrors: live palace directories (`palace/`, configured palace basename, or `palace*/`), KG databases (`knowledge_graph.sqlite3` or matching SQLite KG glob), config (`config.json`), logs (`*.log` or `logs/`), and managed backups (`backups/`).
- Human output should be terse: `OK` for safe commands, `BLOCKED` with a pattern id and missing exclude family names for dangerous commands. JSON output should include `ok`, `dangerous`, `pattern_id`, `missing_excludes`, and `warnings`.
- Keep docs public-safe and generic. Do not mention private hosts, machine-local launch agents, or incident paths. The useful public message is that backups/cleanup manage local archives/storage, while `rsync --delete` between independent hosts can delete remote-owned live state.
