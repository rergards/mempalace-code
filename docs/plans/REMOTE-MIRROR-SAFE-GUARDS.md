---
slug: REMOTE-MIRROR-SAFE-GUARDS
goal: "Add remote mirror safety guidance and a CLI preflight for destructive MemPalace state syncs"
risk: medium
risk_note: "Adds a new operator-facing CLI guard around data-loss-prone rsync command shapes while documenting backup/mirror boundaries."
files:
  - path: mempalace_code/mirror_preflight.py
    change: "Add pure rsync command inspection helpers that detect delete-mode MemPalace state mirrors and required exclude families (palace, KG, config, backups; logs is advisory only)."
  - path: mempalace_code/cli_commands/preflight.py
    change: "Add a non-executing preflight command handler with human and JSON output plus exit codes for safe, blocked, and parse-error cases."
  - path: mempalace_code/cli.py
    change: "Register `mempalace-code preflight mirror --command ...` and route it to the preflight handler."
  - path: tests/test_cli.py
    change: "Cover safe mirror commands, dangerous delete-mode state mirrors, non-state/no-delete boundaries, JSON output, a no-subprocess assertion for the dangerous path (TestMirrorPreflightCommand::test_preflight_never_executes_inspected_command), and a TestMirrorDocs class asserting the new mirror-safety guidance is present in BOTH README.md and docs/BACKUP_RESTORE.md."
  - path: README.md
    change: "Add concise backup-vs-file-mirror guidance and a safe rsync/preflight example near backup and health docs."
  - path: docs/BACKUP_RESTORE.md
    change: "Document that managed backups/cleanup do not protect independent-host delete-mode mirrors and list recommended rsync excludes."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_safe_mirror_with_required_excludes_exits_zero -q` is run"
    then: "an rsync command using --delete against ~/.mempalace with explicit palace, KG, config, and backups excludes exits 0 and reports the command as safe (a logs exclude is advisory and not required for the safe verdict)"
  - id: AC-2
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_delete_mode_state_mirror_missing_excludes_exits_nonzero -q` is run"
    then: "a bare `rsync -a --delete ~/.mempalace/ host:.mempalace/` exits nonzero and reports missing excludes for live palace, KG, config, and managed backups"
  - id: AC-3
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_non_state_or_no_delete_commands_remain_ok -q` is run"
    then: "non-MemPalace rsync --delete commands and MemPalace rsync commands without delete semantics do not trigger the destructive mirror guard"
  - id: AC-4
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_mirror_preflight_json_reports_missing_excludes -q` is run"
    then: "`--json` output is valid JSON that includes ok=false, the dangerous pattern id, and the missing exclude families"
  - id: AC-5
    when: "`python -m pytest tests/test_cli.py::TestMirrorDocs -q` is run"
    then: "per-file assertions confirm that BOTH README.md and docs/BACKUP_RESTORE.md each contain the new backup-vs-mirror distinction (sentinel phrase `remote-owned`, absent on HEAD) and a safe `rsync --delete` example whose `--exclude` entries cover palace, KG, config, and backups; the tests fail on the pre-implementation tree and pass only after both docs are updated"
  - id: AC-6
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_preflight_never_executes_inspected_command -q` is run"
    then: "inspecting a dangerous delete-mode mirror command produces only classification output and never spawns a subprocess or shells out (subprocess.run/Popen and os.system/os.popen are patched and asserted not called)"
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
      statement: "Recommended rsync examples must exclude live palace directories, KG databases, configs, and managed backups (and logs when the operator routes logging into the state dir) unless the operator is intentionally restoring from a known-good source."
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
    - id: REQ-5
      statement: "The preflight must classify command strings only and must never execute, shell out to, or install the inspected command."
      source: "safety invariant (INV-1)"
      acceptance_ids: [AC-6]
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
      expected_behavior: "Exercise safe, blocked, boundary, JSON, and no-subprocess preflight behavior through the public CLI entry point, and assert (TestMirrorDocs) that the new mirror-safety guidance exists in both README.md and docs/BACKUP_RESTORE.md."
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
      command: "python -m pytest tests/test_cli.py::TestMirrorDocs -q"
      proves: "Both docs were actually updated with the backup-vs-mirror distinction (new `remote-owned` sentinel) and safe rsync excludes for palace, KG, config, and backups; the assertions fail on HEAD before implementation, so a green result proves the guidance was written."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_preflight_never_executes_inspected_command -q"
      proves: "Inspecting a dangerous mirror command never spawns a subprocess or shells out, directly asserting INV-1."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand -q"
        proves: "All mirror preflight behavior remains stable across safe, blocked, boundary, JSON, and no-subprocess cases."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-6]
      - id: REG-2
        command: "python -m pytest tests/test_cli.py::TestHealthCommand tests/test_cli.py::TestBackupCommand -q"
        proves: "Existing health and backup CLI surfaces still run after adding the preflight command registration."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-3
        command: "python -m pytest tests/test_cli.py::TestMirrorDocs -q"
        proves: "Future docs edits cannot drop the backup/mirror distinction or any required exclude family (palace, KG, config, backups) from either document without failing the suite."
        acceptance_ids: [AC-5]
---

## Design Notes

- Add a dedicated `preflight mirror` command instead of overloading `health`: `health` reads storage state, while this guard inspects an operator command string before a mirror job exists.
- The preflight command must be non-executing. Use `shlex.split` to tokenize the supplied command and return a parse error on malformed shell text.
- Dangerous pattern: command resolves to `rsync`, contains `--delete` or an rsync delete variant, and references a MemPalace state directory such as `~/.mempalace`, `$HOME/.mempalace`, the configured palace path, or the configured palace parent.
- Required exclude families for a delete-mode state mirror to be classified safe: live palace directories (`palace/`, configured palace basename, or `palace*/`), KG databases (`knowledge_graph.sqlite3` or matching SQLite KG glob), config (`config.json`), and managed backups (`backups/`). Logs are an **advisory** family only: by default logs are written to `/tmp/mempalace-watch.log` (see `mempalace_code/watcher.py`), not under the state dir, so a missing logs exclude must not by itself produce a BLOCKED verdict — surface it as a non-fatal `warnings` entry, and have docs note logs need excluding only if an operator has routed logging into the state dir.
- Human output should be terse: `OK` for safe commands, `BLOCKED` with a pattern id and missing exclude family names for dangerous commands. JSON output should include `ok`, `dangerous`, `pattern_id`, `missing_excludes`, and `warnings`.
- Keep docs public-safe and generic. Do not mention private hosts, machine-local launch agents, or incident paths. The useful public message is that backups/cleanup manage local archives/storage, while `rsync --delete` between independent hosts can delete remote-owned live state.
- Doc verification is enforced by a `TestMirrorDocs` pytest class, not an `rg` token scan. The earlier `rg` OR-alternation passed against the unmodified tree because `config.json`, `backups/`, `knowledge_graph.sqlite3`, and `.log` already appear in both docs (e.g. README.md:296/543, docs/BACKUP_RESTORE.md:15), so it could not prove new guidance was written and did not require both files or all families. The test instead asserts, per file (so both must be updated), a mirror-specific sentinel (`remote-owned`) plus a `rsync --delete` example whose `--exclude` entries cover palace, KG, config, and backups. These anchors were verified absent from README.md and docs/BACKUP_RESTORE.md on HEAD during planning (`rsync`/`--delete`/`remote-owned` = 0 matches in both; README's only `--exclude` hits are unrelated MCP tool-profile flags), so `TestMirrorDocs` fails before implementation and passes only once BOTH docs carry the guidance.
- INV-1 (never execute the inspected command) gets a direct assertion via `TestMirrorPreflightCommand::test_preflight_never_executes_inspected_command`: patch `subprocess.run`/`subprocess.Popen` and `os.system`/`os.popen`, inspect a dangerous delete-mode command string, and assert none were called and only classification output was produced.
