---
slug: CLI-OPT-IN-VERSION-CHECK
status: completed
authority: non_authoritative
goal: "Add strictly opt-in PyPI new-version checks for the public CLI without default network calls."
risk: medium
risk_note: "Touches global CLI startup behavior, user config/state persistence, network error handling, and offline/privacy documentation."
files:
  - path: mempalace_code/version_check.py
    change: "Add version-check policy, state persistence, PyPI metadata fetch, version comparison, interval throttling, prompt gating, automatic stderr hints, and explicit check-now result handling."
  - path: mempalace_code/config.py
    change: "Expose read-only version-check config/env resolution for enabled state and interval overrides without changing existing config defaults or malformed-config fallback behavior."
  - path: mempalace_code/cli_commands/version_check.py
    change: "Add the version-check command handler for --enable, --disable, --status, and --check-now, including clear explicit network-error output."
  - path: mempalace_code/cli.py
    change: "Wire the version-check parser/dispatch and invoke the automatic opt-in prompt/check hook around normal commands while preserving no-command/help behavior."
  - path: pyproject.toml
    change: "Add a direct packaging dependency if the implementation uses packaging.version for PEP 440 comparison."
  - path: uv.lock
    change: "Refresh the lock metadata if pyproject.toml adds packaging as a direct runtime dependency."
  - path: tests/test_version_check.py
    change: "Cover state/config/env precedence, TTY prompt gating, enable/disable/status/check-now behavior, throttling, PyPI comparison, network errors, and stderr-only automatic hints."
  - path: tests/test_cli.py
    change: "Add focused CLI integration coverage for parser wiring and automatic hook behavior that must preserve existing command stdout."
  - path: README.md
    change: "Document version-check commands, opt-in behavior, PyPI metadata scope, stderr-only automatic hints, env overrides, and offline guarantees."
  - path: docs/OFFLINE_USAGE.md
    change: "Clarify that default CLI operation remains offline and PyPI metadata is contacted only after opt-in or explicit --check-now."
  - path: docs/AGENT_INSTALL.md
    change: "Update agent install/runbook steps so installers do not prompt, agents know how to opt in or stay disabled, and non-interactive automation remains no-network by default."
  - path: scripts/bootstrap.sh
    change: "Update bootstrap output/comments to state that install does not enable version checks and users may opt in later with mempalace-code version-check --enable."
acceptance:
  - id: AC-1
    when: "`python -m pytest tests/test_version_check.py::test_fresh_non_tty_cli_skips_prompt_and_network -q` is run"
    then: "a fresh non-interactive CLI invocation neither prompts nor calls the PyPI fetch seam."
  - id: AC-2
    when: "`python -m pytest tests/test_version_check.py::test_fresh_interactive_prompt_yes_enables_checks tests/test_version_check.py::test_fresh_interactive_prompt_no_records_opt_out -q` is run"
    then: "a fresh interactive TTY asks once; yes persists enabled state and no persists disabled state so the next CLI run does not ask again."
  - id: AC-3
    when: "`python -m pytest tests/test_version_check.py::test_version_check_enable_disable_status_and_env_override -q` is run"
    then: "`mempalace-code version-check --enable`, `--disable`, and `--status` report the effective setting, and MEMPALACE_VERSION_CHECK=1/0 overrides persisted state."
  - id: AC-4
    when: "`python -m pytest tests/test_version_check.py::test_check_now_reports_current_latest_and_upgrade_command -q` is run"
    then: "`mempalace-code version-check --check-now` reports current and latest versions from PyPI metadata and includes the upgrade command when latest is newer."
  - id: AC-5
    when: "`python -m pytest tests/test_version_check.py::test_automatic_check_is_interval_throttled_and_stderr_only -q` is run"
    then: "an opted-in automatic check runs only when the interval is due, prints any update hint only to stderr, and leaves the wrapped command stdout unchanged."
  - id: AC-6
    when: "`python -m pytest tests/test_version_check.py::test_check_now_reports_network_error tests/test_version_check.py::test_automatic_network_error_is_quiet_and_rate_limited -q` is run"
    then: "explicit --check-now shows a clear PyPI/network error, while automatic checks suppress transient errors and do not retry on every command."
  - id: AC-7
    when: "`python -m pytest tests/test_version_check.py::test_version_check_state_preserves_existing_config_and_malformed_config_is_safe -q` is run"
    then: "version-check persistence does not clobber existing config keys, and malformed ~/.mempalace/config.json keeps the existing safe fallback behavior."
  - id: AC-8
    when: "`rg 'version-check|MEMPALACE_VERSION_CHECK|pypi.org/pypi/mempalace-code/json|opt-in' README.md docs/OFFLINE_USAGE.md docs/AGENT_INSTALL.md scripts/bootstrap.sh` is run"
    then: "the docs and bootstrap wording state that version checks are opt-in and contact PyPI only for package metadata."
out_of_scope:
  - "Any pip install-time hook, installer prompt, post-install script, or package-manager integration."
  - "Automatic package upgrade or invoking pip/uv/pipx on the user's behalf."
  - "Telemetry, analytics, user identifiers, dependency update checks, or non-PyPI endpoints."
  - "Changing model download behavior, LanceDB storage, MCP server protocol, or existing CLI command semantics beyond the optional stderr hint after opt-in."
  - "Backlog metadata edits, release publishing, or bumping the mempalace-code package version."
contract_policy:
  flow: full_spdd
  reason: "Standard public CLI feature with privacy/offline guarantees, network behavior, persisted user preference, and documentation changes."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Default CLI execution must not prompt or contact the network on fresh non-interactive installs."
      source: "backlog acceptance criteria"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Interactive first-run prompting must ask once and persist either opt-in or opt-out."
      source: "backlog acceptance criteria"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Users must have explicit CLI and environment controls for enable, disable, status, check-now, and interval behavior."
      source: "backlog scope and acceptance criteria"
      acceptance_ids: [AC-3, AC-5]
    - id: REQ-4
      statement: "Version checks must use PyPI package metadata only and handle newer-version and network-error outcomes distinctly."
      source: "backlog scope and acceptance criteria"
      acceptance_ids: [AC-4, AC-6]
    - id: REQ-5
      statement: "Automatic checks must preserve machine-parseable stdout and keep offline/privacy documentation precise."
      source: "backlog acceptance criteria"
      acceptance_ids: [AC-5, AC-8]
    - id: REQ-6
      statement: "Preference/state writes must preserve existing user settings and fail safe when existing config is malformed."
      source: "backlog acceptance criteria"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "Version-check policy and state"
      kind: internal
      paths: ["mempalace_code/version_check.py", "mempalace_code/config.py"]
      expected_behavior: "Resolve env/config/state precedence, store opt-in choice and last-check timestamps under ~/.mempalace without overwriting unrelated config, fetch PyPI metadata only when allowed, and throttle automatic checks."
    - name: "Version-check CLI command"
      kind: cli
      paths: ["mempalace_code/cli_commands/version_check.py", "mempalace_code/cli.py"]
      expected_behavior: "Expose --enable, --disable, --status, and --check-now; explicit check-now may contact PyPI and prints clear current/latest/error output."
    - name: "Automatic CLI hook"
      kind: cli
      paths: ["mempalace_code/cli.py", "mempalace_code/version_check.py", "tests/test_cli.py"]
      expected_behavior: "After normal command dispatch, prompt only when stdin/stdout/stderr are TTYs and no choice exists, and run periodic checks only after opt-in while writing hints to stderr."
    - name: "Version-check tests"
      kind: internal
      paths: ["tests/test_version_check.py", "tests/test_cli.py"]
      expected_behavior: "Focused tests exercise prompt gating, controls, PyPI fetch/compare, interval boundaries, error handling, state/config safety, and stdout preservation."
    - name: "Dependency metadata"
      kind: internal
      paths: ["pyproject.toml", "uv.lock"]
      expected_behavior: "If packaging.version is used for PEP 440 comparison, packaging is declared directly and the lock metadata reflects it."
    - name: "Offline/install documentation"
      kind: cli
      paths: ["README.md", "docs/OFFLINE_USAGE.md", "docs/AGENT_INSTALL.md", "scripts/bootstrap.sh"]
      expected_behavior: "User and agent docs explain opt-in commands, PyPI metadata scope, env overrides, installer non-prompt behavior, and default offline/no-network semantics."
  invariants:
    - id: INV-1
      statement: "Fresh installs, pip/uv/pipx installs, bootstrap installs, and non-interactive CLI commands must not prompt or perform version-check network calls by default."
      applies_to: ["mempalace_code/version_check.py", "mempalace_code/cli.py", "scripts/bootstrap.sh"]
    - id: INV-2
      statement: "Automatic version-check output must go to stderr only and must not mutate existing command stdout."
      applies_to: ["mempalace_code/version_check.py", "mempalace_code/cli.py", "tests/test_cli.py"]
    - id: INV-3
      statement: "Existing ~/.mempalace/config.json keys, config precedence, and malformed-config fallback behavior remain compatible."
      applies_to: ["mempalace_code/config.py", "mempalace_code/version_check.py"]
    - id: INV-4
      statement: "No telemetry, analytics payloads, user identifiers, dependency inventory, or non-PyPI network endpoints are introduced."
      applies_to: ["mempalace_code/version_check.py", "README.md", "docs/OFFLINE_USAGE.md"]
    - id: INV-5
      statement: "Existing command names, exit codes, and parser behavior stay unchanged except for the new version-check subcommand and opted-in stderr hint."
      applies_to: ["mempalace_code/cli.py", "mempalace_code/cli_commands/version_check.py", "tests/test_cli.py"]
  risks:
    - id: RISK-1
      risk: "The automatic hook could surprise automation with prompts or network calls."
      mitigation: "Require explicit opt-in before network checks and require stdin/stdout/stderr TTYs before any first-run prompt; cover non-TTY no-op in tests."
    - id: RISK-2
      risk: "Persisting choices could overwrite user config or make malformed config worse."
      mitigation: "Prefer a separate version-check state file for writes, keep config keys read-only, use atomic JSON writes, and add config-preservation/malformed-config tests."
    - id: RISK-3
      risk: "PyPI outage or captive portal errors could add noisy stderr to normal commands."
      mitigation: "Explicit --check-now reports errors, but automatic checks are quiet and update last-check/error state so failures are rate-limited."
    - id: RISK-4
      risk: "Automatic hints could corrupt JSON or scripted stdout from commands such as health --json."
      mitigation: "Print automatic hints only to stderr and add CLI integration coverage that asserts wrapped command stdout is byte-for-byte unchanged."
    - id: RISK-5
      risk: "Version comparison could be wrong for PEP 440 versions."
      mitigation: "Use packaging.version with a direct dependency or a well-tested local comparator, and add tests for equal, older, newer, and prerelease-like versions."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_version_check.py::test_fresh_non_tty_cli_skips_prompt_and_network -q"
      proves: "Fresh non-interactive CLI execution does not prompt or call the PyPI fetch seam."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_version_check.py::test_fresh_interactive_prompt_yes_enables_checks tests/test_version_check.py::test_fresh_interactive_prompt_no_records_opt_out -q"
      proves: "TTY first-run prompting persists yes/no decisions and does not repeat after a decision exists."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_version_check.py::test_version_check_enable_disable_status_and_env_override -q"
      proves: "Explicit CLI controls and MEMPALACE_VERSION_CHECK env precedence work."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_version_check.py::test_check_now_reports_current_latest_and_upgrade_command -q"
      proves: "Explicit check-now fetches PyPI metadata, compares current/latest, and reports an upgrade command for newer releases."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_version_check.py::test_automatic_check_is_interval_throttled_and_stderr_only -q"
      proves: "Automatic checks obey the interval and route upgrade hints to stderr without changing command stdout."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_version_check.py::test_check_now_reports_network_error tests/test_version_check.py::test_automatic_network_error_is_quiet_and_rate_limited -q"
      proves: "Explicit network failures are visible while automatic failures are quiet and not retried every command."
      acceptance_ids: [AC-6]
    - id: VER-7
      command: "python -m pytest tests/test_version_check.py::test_version_check_state_preserves_existing_config_and_malformed_config_is_safe -q"
      proves: "Version-check state writes preserve user config and malformed config remains safe."
      acceptance_ids: [AC-7]
    - id: VER-8
      command: "rg 'version-check|MEMPALACE_VERSION_CHECK|pypi.org/pypi/mempalace-code/json|opt-in' README.md docs/OFFLINE_USAGE.md docs/AGENT_INSTALL.md scripts/bootstrap.sh"
      proves: "Docs and bootstrap wording expose the opt-in controls and PyPI metadata-only network scope."
      acceptance_ids: [AC-8]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_version_check.py -q"
        proves: "All version-check policy, state, network, prompt, interval, and error-handling behavior stays covered as a focused suite."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-2
        command: "python -m pytest tests/test_cli.py::TestHealthCommand::test_health_command_json_output tests/test_cli.py::TestLegacyAlias::test_install_alias_subcommand_dispatches -q"
        proves: "Existing parser/dispatch paths keep JSON stdout and alias behavior after the automatic hook and new subcommand are added."
        acceptance_ids: [AC-5]
      - id: REG-3
        command: "ruff check mempalace_code/ tests/ && ruff format --check mempalace_code/ tests/"
        proves: "New version-check code and tests meet project lint and formatting gates."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-4
        command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
        proves: "New config/state types and CLI wiring satisfy the project type gate."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-5
        command: "rg 'version-check|MEMPALACE_VERSION_CHECK|pypi.org/pypi/mempalace-code/json|opt-in' README.md docs/OFFLINE_USAGE.md docs/AGENT_INSTALL.md scripts/bootstrap.sh"
        proves: "Future docs edits continue to surface opt-in and PyPI metadata-only behavior."
        acceptance_ids: [AC-8]
---

## Design Notes

- Keep all network behavior behind `version-check --check-now` or an effective enabled setting. A fresh non-interactive run should return before any prompt or fetch seam is reachable.
- Use `https://pypi.org/pypi/mempalace-code/json` and read only `info.version`. Do not send custom identifiers, installed package lists, palace paths, Python environment data, or telemetry.
- Prefer a new `mempalace_code/version_check.py` module with injectable clock, TTY, input, output, and fetch seams. The CLI should stay thin enough for tests to simulate prompt/no-prompt paths without real network access.
- Store mutable prompt choice and last-check timestamps in a separate state file such as `~/.mempalace/version_check.json`. Read optional config keys such as `version_check_enabled` and `version_check_interval_hours`, but avoid rewriting `config.json` for version-check state.
- Precedence: `MEMPALACE_VERSION_CHECK=1/0` overrides config and state. `MEMPALACE_VERSION_CHECK_INTERVAL_HOURS` overrides config/state interval. Invalid env/config values should fail closed to disabled or the default interval, not raise during normal CLI startup.
- Default interval should be conservative, e.g. 168 hours. Explicit `--check-now` ignores throttling and reports errors; automatic checks update last-check/error state so failures are not retried on every command.
- First-run prompt guard should require stdin, stdout, and stderr to be TTYs, no explicit env/config/state choice, and a real subcommand. Do not prompt for `--help`, parser errors, no-command help, or the `version-check` command itself.
- Automatic checks should run after successful normal command dispatch when possible so primary command behavior happens first. If a command exits via `SystemExit`, do not mask its exit code; the implementation may skip the automatic check on error exits.
- `version-check --status` should show effective enabled/disabled state, source (`env`, `config`, `state`, or `default`), interval, last checked time when present, and PyPI URL. Keep it local-only unless `--check-now` is also provided.
- `--enable` and `--disable` should write state and print concise confirmation. If env/config overrides persisted state, status should make that override visible so users understand why the effective value differs.
- Use `packaging.version.Version` if available as a direct dependency; otherwise implement and test a narrow comparator before using it. Avoid relying on an undeclared transitive dependency.
- Documentation should explicitly say installers do not prompt, `mempalace-code init/mine/search/status` remain no-network by default, and the version check contacts PyPI only for package metadata after opt-in or explicit `--check-now`.
