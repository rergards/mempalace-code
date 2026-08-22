---
slug: MIRROR-PREFLIGHT-WRAPPER-DETECTION
status: completed
authority: non_authoritative
goal: "Detect wrapper-prefixed destructive MemPalace rsync mirrors in preflight mirror"
risk: medium
risk_note: "Changes data-loss guard classification logic; risk is contained by a narrow wrapper allowlist and CLI regression coverage for direct and wrapped command shapes."
files:
  - path: mempalace_code/mirror_preflight.py
    change: "Add a pure token-normalization helper that resolves direct rsync and narrowly supported wrapper prefixes before applying the existing delete/state/exclude classifier."
  - path: tests/test_cli.py
    change: "Add CLI coverage for sudo/env/simple shell-wrapper destructive mirrors, wrapped safe mirrors, direct-command regressions, malformed shell text, and non-state/no-delete false-positive boundaries."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_wrapped_safe_mirror_with_required_excludes_exits_zero -q` is run"
    then: "a wrapper-prefixed `rsync --delete` MemPalace state mirror with palace, KG, config, and backups excludes exits 0 and prints `OK`"
  - id: AC-2
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_sudo_wrapped_delete_mode_state_mirror_missing_excludes_exits_nonzero -q` is run"
    then: "`sudo rsync -a --delete ~/.mempalace/ user@host:.mempalace/` exits nonzero and reports the existing dangerous mirror pattern plus all required missing exclude families"
  - id: AC-3
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_env_wrapped_delete_excluded_state_mirror_exits_nonzero -q` is run"
    then: "`env VAR=value rsync -a --delete-excluded ~/.mempalace/ user@host:.mempalace/` exits nonzero with `delete-excluded-state-mirror`"
  - id: AC-4
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_simple_shell_wrapped_delete_mode_state_mirror_is_classified -q` is run"
    then: "`sh -c 'rsync -a --delete ~/.mempalace/ user@host:.mempalace/'` is classified through the same mirror guard and exits nonzero"
  - id: AC-5
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_wrapped_non_state_or_no_delete_commands_remain_ok -q` is run"
    then: "wrapper-prefixed rsync commands that either do not target `.mempalace` or do not use delete semantics still exit 0 and print `OK`"
  - id: AC-6
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_malformed_wrapper_shell_text_reports_parse_error -q` is run"
    then: "malformed shell text in a supported wrapper path exits 2 and reports a parse error instead of being treated as safe"
  - id: AC-7
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_non_state_or_no_delete_commands_remain_ok tests/test_cli.py::TestMirrorPreflightCommand::test_delete_mode_state_mirror_missing_excludes_exits_nonzero tests/test_cli.py::TestMirrorDocs -q` is run"
    then: "existing direct safe/dangerous/boundary behavior and the backup-vs-mirror documentation sentinels remain intact"
out_of_scope:
  - "Executing, installing, scheduling, or rewriting rsync, launchd, cron, shell, or sudo commands."
  - "Parsing arbitrary shell scripts, pipelines, redirects, SSH remote commands, or wrapper command strings that are not represented as a simple supported argv chain."
  - "Changing backup, restore, cleanup, LanceDB storage, or MemPalace delete APIs."
  - "Editing README.md, docs/BACKUP_RESTORE.md, backlog metadata, archive files, or bookkeep-owned task state."
contract_policy:
  flow: full_spdd
  reason: "Standard data-safety task affecting operator-facing CLI classification of destructive mirror commands."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Wrapper-prefixed rsync invocations using delete semantics against a MemPalace state directory must be classified by the same guard as direct rsync commands."
      source: "backlog description"
      acceptance_ids: [AC-2, AC-3, AC-4]
    - id: REQ-2
      statement: "Wrapped rsync commands with all required exclude families must remain accepted."
      source: "backlog acceptance"
      acceptance_ids: [AC-1]
    - id: REQ-3
      statement: "Wrapped commands that are not delete-mode MemPalace state mirrors must not be blocked."
      source: "backlog acceptance"
      acceptance_ids: [AC-5]
    - id: REQ-4
      statement: "Malformed wrapper shell text must produce an explicit parse error instead of bypassing the guard as safe."
      source: "safety boundary"
      acceptance_ids: [AC-6]
    - id: REQ-5
      statement: "Existing direct rsync behavior and remote mirror documentation guards must remain unchanged."
      source: "backlog acceptance"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "Mirror command classifier"
      kind: internal
      paths: ["mempalace_code/mirror_preflight.py"]
      expected_behavior: "Normalize direct rsync and a small supported wrapper set to the effective rsync argv before reusing existing delete semantics, state-dir targeting, delete-excluded, exclude-family, and parse-error logic."
    - name: "Preflight CLI tests"
      kind: internal
      paths: ["tests/test_cli.py"]
      expected_behavior: "Exercise wrapper classification through the public `mempalace-code preflight mirror --command` path and preserve direct-command and docs regressions."
  invariants:
    - id: INV-1
      statement: "The preflight path must only inspect command text; it must never execute, shell out to, install, or rewrite the inspected command."
      applies_to: ["mempalace_code/mirror_preflight.py", "tests/test_cli.py"]
    - id: INV-2
      statement: "Direct rsync commands keep their current safe, blocked, JSON, delete-excluded, parse-error, and no-subprocess behavior."
      applies_to: ["mempalace_code/mirror_preflight.py", "tests/test_cli.py"]
    - id: INV-3
      statement: "Non-rsync commands and rsync commands that do not combine delete semantics with a MemPalace state-dir target remain non-dangerous."
      applies_to: ["mempalace_code/mirror_preflight.py", "tests/test_cli.py"]
    - id: INV-4
      statement: "Backup-vs-mirror guidance in README.md and docs/BACKUP_RESTORE.md remains covered by the existing docs sentinel tests."
      applies_to: ["tests/test_cli.py"]
  risks:
    - id: RISK-1
      risk: "Over-broad token scanning could flag unrelated commands that merely mention `rsync` or `.mempalace`."
      mitigation: "Resolve only direct rsync or supported argv-style wrappers to an effective rsync token list; do not search arbitrary token positions."
    - id: RISK-2
      risk: "Wrapper option parsing could skip the wrong token and classify wrapper flags as rsync arguments."
      mitigation: "Keep the supported wrapper set small, encode option arity explicitly where needed, and cover sudo/env/simple-shell variants in CLI tests."
    - id: RISK-3
      risk: "Simple `sh -c` support could drift into unreliable shell-script parsing."
      mitigation: "Only recursively parse a single shell command payload with `shlex.split`; leave pipelines, redirects, compound commands, and remote SSH command discovery out of scope."
    - id: RISK-4
      risk: "A parse failure inside a wrapper could continue to return OK and preserve the bypass."
      mitigation: "Surface nested wrapper tokenization failures as `PreflightResult(parse_error=...)` and assert exit code 2."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_wrapped_safe_mirror_with_required_excludes_exits_zero -q"
      proves: "Wrapped delete-mode MemPalace state mirrors with all required excludes are accepted."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_sudo_wrapped_delete_mode_state_mirror_missing_excludes_exits_nonzero -q"
      proves: "A sudo-prefixed destructive state mirror no longer bypasses command-shape detection."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_env_wrapped_delete_excluded_state_mirror_exits_nonzero -q"
      proves: "An env-prefixed delete-excluded state mirror is blocked with the delete-excluded pattern."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_simple_shell_wrapped_delete_mode_state_mirror_is_classified -q"
      proves: "A simple shell `-c` wrapper around a destructive rsync command is classified through the guard."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_wrapped_non_state_or_no_delete_commands_remain_ok -q"
      proves: "Wrapper support does not block non-state delete rsyncs or state-dir rsyncs without delete semantics."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_malformed_wrapper_shell_text_reports_parse_error -q"
      proves: "Malformed supported-wrapper shell text fails with a parse error instead of being accepted as safe."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_non_state_or_no_delete_commands_remain_ok tests/test_cli.py::TestMirrorPreflightCommand::test_delete_mode_state_mirror_missing_excludes_exits_nonzero tests/test_cli.py::TestMirrorDocs -q"
      proves: "Direct rsync behavior and existing mirror documentation guards are preserved."
      acceptance_ids: [AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_cli.py::TestMirrorPreflightCommand -q"
        proves: "All mirror preflight CLI behavior remains stable across direct, wrapped, safe, blocked, JSON, parse-error, and no-subprocess cases."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-2
        command: "python -m pytest tests/test_cli.py::TestMirrorDocs -q"
        proves: "Backup-vs-mirror docs from REMOTE-MIRROR-SAFE-GUARDS remain present."
        acceptance_ids: [AC-7]
      - id: REG-3
        command: "python -m pytest tests/test_cli.py::TestHealthCommand tests/test_cli.py::TestBackupCommand -q"
        proves: "Unrelated health and backup CLI surfaces still run after classifier changes."
        acceptance_ids: [AC-7]
---

## Design Notes

- Keep classification pure: continue using `shlex.split` and return `PreflightResult(parse_error=...)` for malformed command text; do not introduce subprocess, filesystem, sudo, env, or shell execution.
- Add a helper such as `_effective_rsync_tokens(tokens: list[str]) -> tuple[list[str], str]` where the returned token list starts at the effective rsync executable and the error string is non-empty only for malformed supported wrapper payloads.
- Preserve current direct-command behavior by making direct `rsync` and `/path/to/rsync` the first accepted shape.
- Support only narrow argv-style wrappers that exec a following command without changing its argument meaning:
  - `sudo` and `/path/to/sudo`, including common non-command options and `--` before `rsync`.
  - `env` and `/path/to/env`, including simple `NAME=value` assignments and `--` before `rsync`.
  - `sh -c 'rsync ...'` / `bash -c 'rsync ...'` only when the `-c` payload tokenizes as one simple command. Do not attempt to interpret compound shell syntax.
- After normalization, run the existing `_has_delete_semantics`, `_targets_state_dir`, `--delete-excluded`, and exclude-family checks against the effective rsync token list so existing pattern IDs and output remain stable.
- Do not broad-scan for any `rsync` token in the command. For example, `echo rsync --delete ~/.mempalace/` must remain OK because it is not an rsync invocation.
- Keep documentation unchanged for this task. The existing `TestMirrorDocs` class is the preservation guard for backup-vs-mirror guidance from `REMOTE-MIRROR-SAFE-GUARDS`.
