---
slug: CLI-OPT-IN-VERSION-CHECK
status: completed
authority: non_authoritative
goal: "Honor the process-level version-check kill switch on explicit --check-now calls without changing persisted opt-out override behavior."
risk: medium
risk_note: "The implementation is a narrow handler guard, but it changes CLI exit behavior and enforces a pre-release no-network guarantee."
files:
  - path: mempalace_code/cli_commands/version_check.py
    change: "Resolve effective configuration before --check-now and exit 2 without fetching when an environment-sourced value disables checks."
  - path: tests/test_version_check.py
    change: "Add handler-level kill-switch, recovery-output, persisted-disable, allowed-flow, and public-document contract coverage."
  - path: tests/test_cli.py
    change: "Exercise parsed --check-now behavior through main() and prove blocked process overrides never reach the fetch seam."
  - path: README.md
    change: "Clarify that --check-now bypasses interval and persisted preference only; the environment kill switch retains precedence."
  - path: docs/OFFLINE_USAGE.md
    change: "State that the process environment kill switch also blocks explicit --check-now version-check networking."
  - path: docs/AGENT_INSTALL.md
    change: "Document environment kill-switch precedence and the recovery required before an explicit check."
  - path: docs/UPDATES.md
    change: "Explain how to recover before using --check-now for the ordinary-pip update hint when the kill switch is active."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable quality scorecard after the planned documentation changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable quality scorecard from the same canonical generator."
acceptance:
  - id: AC-1
    when: "MEMPALACE_VERSION_CHECK is 0 or an invalid value and version-check --check-now runs with a recording fetch seam"
    then: "the command exits 2 and the fetch seam records zero calls"
  - id: AC-2
    when: "a process-level override blocks version-check --check-now and its output is captured"
    then: "stderr contains one fixed bounded reason and the recovery command 'unset MEMPALACE_VERSION_CHECK', while stdout contains no raw environment value or traceback"
  - id: AC-3
    when: "persisted version-check state is disabled, MEMPALACE_VERSION_CHECK is absent, and --check-now runs with a recording fetch seam"
    then: "the explicit command completes without the kill-switch exit and calls the fetch seam exactly once"
  - id: AC-4
    when: "enable, disable, status, automatic-check, allowed check-now, and parsed blocked check-now scenarios are exercised after the change"
    then: "their existing output, state, and network-call contracts remain unchanged except for the specified environment refusal, and all four public documents state the same precedence"
out_of_scope:
  - "Changing resolve_config parsing, precedence, persisted state format, or automatic-check scheduling."
  - "Blocking explicit --check-now solely because config or persisted state is disabled."
  - "Changing version comparison, admitted PyPI request handling, updater hints, or network-error output."
  - "Changing EntityRegistry.research or any non-version-check network surface."
  - "Editing backlog metadata, release metadata, package versions, or runner-owned Git state."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release CLI runtime work enforces a documented process-level network boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "An environment-sourced disabled effective setting must prevent explicit --check-now network access and return exit code 2."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "A blocked explicit check must give bounded context-free recovery output without exposing the raw environment value or a traceback."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Explicit --check-now must continue to override disabled persisted state when no environment override exists."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Existing version-check controls and allowed behavior must remain compatible, with consistent public kill-switch precedence."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Explicit version-check command"
      kind: cli
      paths: ["mempalace_code/cli_commands/version_check.py"]
      expected_behavior: "Reject only environment-sourced disabled effective configuration before the existing --check-now fetch; preserve all admitted handler behavior."
    - name: "Version-check public contract"
      kind: cli
      paths: ["README.md", "docs/OFFLINE_USAGE.md", "docs/AGENT_INSTALL.md", "docs/UPDATES.md"]
      expected_behavior: "Describe the process environment override as having precedence over explicit --check-now, including invalid-value fail-closed behavior and recovery."
    - name: "Generated quality scorecard"
      kind: artifact
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "Remain byte-current with the existing quality_scorecard.py generator after documentation changes."
  invariants:
    - id: INV-1
      statement: "resolve_config remains the sole authority for environment, config, state, and default precedence, including invalid-value fail-closed behavior."
      applies_to: ["mempalace_code/cli_commands/version_check.py"]
    - id: INV-2
      statement: "A disabled config or persisted state without an environment override does not block explicit --check-now."
      applies_to: ["mempalace_code/cli_commands/version_check.py", "tests/test_version_check.py"]
    - id: INV-3
      statement: "Enable, disable, status, automatic checks, admitted check-now output, and PyPI error handling retain their current behavior."
      applies_to: ["mempalace_code/cli_commands/version_check.py", "tests/test_version_check.py", "tests/test_cli.py"]
    - id: INV-4
      statement: "The kill switch affects version-check network calls only and leaves direct EntityRegistry.research behavior unchanged."
      applies_to: ["docs/OFFLINE_USAGE.md"]
  risks:
    - id: RISK-1
      risk: "Treating every disabled effective setting as a process kill switch would break explicit override of persisted opt-out."
      mitigation: "Gate on both source == 'env' and enabled is False, with a persisted-state regression."
    - id: RISK-2
      risk: "The handler could print a refusal yet still reach the fetch or return success."
      mitigation: "Assert SystemExit code 2 and zero fetch calls through direct-handler and parsed-main paths."
    - id: RISK-3
      risk: "Echoing malformed environment content could permit unbounded or multiline output injection."
      mitigation: "Use fixed text, never interpolate the raw value, and cover long and newline-containing invalid values."
    - id: RISK-4
      risk: "Public instructions could continue to imply that --check-now always contacts PyPI."
      mitigation: "Replace the four contradictory passages and enforce their shared precedence in the existing version-check test owner."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python -m pytest tests/test_version_check.py::TestCheckNowEnvironmentKillSwitch tests/test_cli.py::TestVersionCheckCLIHook::test_check_now_honors_environment_kill_switch -q"
      proves: "Direct-handler and parsed-main cases cover 0, malformed values, bounded recovery output, persisted-disable override, unchanged admitted flows, and synchronized public documentation."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The required generated scorecard pair is current after the planned documentation changes."
      acceptance_ids: [AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The repository's configured non-network suite preserves existing CLI, automatic-check, state, updater-hint, and documentation behavior."
        acceptance_ids: [AC-4]
---

## Design Notes

- In the existing `check_now` branch, call `resolve_config(config_dir)` before `run_check_now` and block only when `source == "env"` and `enabled is False`. This directly reuses environment precedence and invalid-value fail-closed parsing.
- Emit fixed refusal text to stderr, include `unset MEMPALACE_VERSION_CHECK` as the single recovery command, and raise `SystemExit(2)` before printing current-version/PyPI details or calling the fetch seam. Never interpolate the raw environment value.
- Keep `run_check_now`, `fetch_latest_version`, state storage, parser wiring, and automatic-check dispatch unchanged. No helper, duplicate parser, config key, or state field is needed.
- Add a focused `TestCheckNowEnvironmentKillSwitch` owner in `tests/test_version_check.py`. Patch the handler module's imported `fetch_latest_version`; isolate `HOME`; cover `"0"`, ordinary invalid input, long input, multiline input, persisted disabled state with no env, admitted checks, and all four documentation statements.
- Extend `TestVersionCheckCLIHook` in `tests/test_cli.py` with a parsed `main()` case that asserts exit 2, zero handler-fetch calls, fixed stderr recovery, clean stdout, and no traceback for disabled and malformed overrides.
- Update README.md, docs/OFFLINE_USAGE.md, docs/AGENT_INSTALL.md, and docs/UPDATES.md wherever current wording says or implies that explicit `--check-now` always fetches. Preserve the separate `EntityRegistry.research()` offline exception.
- Command context basis: commands run from the repository root; `pyproject.toml` declares `tests` for pytest and excludes `needs_network` and `slow` by default. VER-1 and VER-2 are focused configured-runner checks; REG-1 is the exact configured non-network suite from AGENTS.md.
- The public documentation change makes the existing scorecard artifacts stale by contract. Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with `python scripts/quality_scorecard.py --write`; do not change scorecard logic.
- `docs/quality/incident-class-registry.yaml` is absent in this worktree, so no incident-class proof block applies.
