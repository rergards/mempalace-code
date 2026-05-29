---
slug: MIRROR-PREFLIGHT-SUDO-COMBINED-OPTS
goal: "Detect sudo combined-option mirror wrapper forms in preflight classification"
risk: low
risk_note: "Narrow parser extension only for sudo wrapper tokenization; no subprocess, storage, or network boundaries are touched."
files:
  - path: mempalace_code/mirror_preflight.py
    change: "Extend sudo wrapper normalization to recognize compact and combined sudo option forms before resolving the effective rsync argv."
  - path: tests/test_cli.py
    change: "Add focused CLI coverage for a sudo combined-option destructive state mirror and a safe sudo control case."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_sudo_combined_option_delete_mode_state_mirror_missing_excludes_exits_nonzero -q` is run"
    then: "a destructive state-dir mirror wrapped as compact sudo options is blocked, exits nonzero, and reports the existing dangerous mirror pattern plus the missing exclude families"
  - id: AC-2
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_sudo_combined_option_safe_mirror_remains_ok -q` is run"
    then: "a sudo-wrapped rsync mirror that does not delete state data still exits 0 and prints `OK`"
  - id: AC-3
    when: "`python -m pytest tests/test_cli.py::TestMirrorPreflightCommand::test_sudo_wrapped_delete_mode_state_mirror_missing_excludes_exits_nonzero tests/test_cli.py::TestMirrorPreflightCommand::test_wrapped_non_state_or_no_delete_commands_remain_ok -q` is run"
    then: "the existing direct sudo regressions still behave the same after compact-option support is added"
out_of_scope:
  - "Changing direct rsync classification, delete-excluded handling, or non-sudo wrapper parsing."
  - "Parsing arbitrary shell scripts, pipelines, redirects, or remote SSH command strings."
  - "Editing backlog metadata, docs guides, or unrelated CLI surfaces."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: this is a small pure-parser change, limited CLI tests, no auth/data/migration/provider/pipeline boundary, and no release or host integration impact."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated

## Design Notes

- Keep the change narrow: teach the sudo prefix resolver to consume compact short-option bundles such as `-nE` and argument-attached forms such as `-uroot` until the effective `rsync` token is reached.
- Preserve current behavior for direct `rsync`, existing safe sudo-wrapped commands, and non-rsync command strings that merely mention `rsync`.
- Treat malformed sudo wrapper tokenization as a parse failure only when the compact form prevents unambiguous wrapper resolution; do not broaden shell parsing.
- Reuse the existing delete-semantic, state-dir target, delete-excluded, and exclude-family checks after normalization so pattern IDs and CLI output stay stable.
- Add one destructive combined-option sudo regression and one safe combined-option sudo control case through the public `mempalace preflight mirror --command` path.
