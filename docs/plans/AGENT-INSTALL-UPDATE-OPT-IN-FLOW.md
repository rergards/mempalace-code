---
slug: AGENT-INSTALL-UPDATE-OPT-IN-FLOW
status: completed
authority: non_authoritative
goal: "Make agent installs explicitly choose version notifications and supported scheduled package updates, then report the resulting states."
risk: medium
risk_note: "Touches the public agent install runbook, update/version-check user guidance, installed-artifact smokes, and drift guards around opt-in package mutation."
files:
  - path: docs/AGENT_INSTALL.md
    change: "Restructure the agent runbook so every install asks an explicit periodic-notification choice, gates Linux systemd-user scheduled package updates behind read-only status/preflight, uses executable-based post-install verification, and ends with a compact state report."
  - path: README.md
    change: "Align public version-check and update guidance with the guarded updater commands and the clarified notification-versus-package-update boundary."
  - path: docs/UPDATES.md
    change: "Keep the update runbook aligned with the agent-install wording for status, apply --yes, scheduler render/install/status, unsupported environments, and rollback/manual-update guidance."
  - path: mempalace_code/version_check.py
    change: "Replace automatic and explicit newer-version hints so they recommend mempalace-code update status followed by mempalace-code update apply --yes instead of raw pip upgrade."
  - path: mempalace_code/cli.py
    change: "Keep CLI help text aligned with the explicit update and version-check wording without changing first-run prompt fallback semantics."
  - path: mempalace_code/cli_commands/update.py
    change: "Render scheduler support and enabled state clearly in human update status output while preserving --yes mutation gates and JSON shape."
  - path: tests/test_version_check.py
    change: "Update and extend focused version-check tests for guarded update hints, no-network defaults, prompt persistence, explicit check-now output, and stdout/stderr separation."
  - path: tests/test_cli.py
    change: "Add focused CLI integration coverage for first-run fallback behavior, version-check status output, update hint routing, and help text alignment."
  - path: tests/test_updater.py
    change: "Add focused scheduler/status coverage proving disabled-by-default behavior, support/enabled reporting, unsupported installer/environment outcomes, and retained --yes gates."
  - path: scripts/release_install_metadata_smoke.py
    change: "Extend installed-artifact smoke coverage for disposable pipx, uv-tool when available, and bootstrap-style venv installs from a neutral directory, using the installed mempalace-code executable for version-check/status probes."
  - path: tests/test_release_install_metadata_smoke.py
    change: "Add mocked smoke tests for uv-tool availability/skip behavior, bootstrap-venv layout, executable-based version reporting, notification-choice probes, scheduler routing probes, and no source-checkout shadowing."
  - path: tests/test_installed_artifact_behavior.py
    change: "Add neutral-directory installed-artifact tests for notification state, update status/scheduler status, and CLI provenance independent of ambient system python imports."
  - path: scripts/release_readiness_gate.py
    change: "Route release readiness install-smoke rows through every supported smoke API, including uv-tool when available and bootstrap venv, without touching operator tool installs."
  - path: tests/test_release_readiness_gate.py
    change: "Update readiness-gate tests so wheel install-smoke forwarding covers venv, pipx, uv-tool where available, and bootstrap venv rows."
  - path: scripts/docs_drift_guard.py
    change: "Guard alignment across README, docs/AGENT_INSTALL.md, docs/UPDATES.md, CLI help strings, and version-check hint commands."
  - path: tests/test_docs_drift_guard.py
    change: "Add fixture tests that fail on missing explicit update choices, stale raw-pip upgrade hints, missing final report fields, and docs/CLI/help drift."
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_update_choice_sequence -q is run"
    then: "docs/AGENT_INSTALL.md has a numbered decision sequence that asks separately about periodic version notifications and scheduled package updates, and states that notifications inspect only PyPI metadata without installing packages."
  - id: AC-2
    when: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_notification_choice_records_safe_defaults -q is run"
    then: "affirmative notification wording runs mempalace-code version-check --enable, while negative, empty, EOF, or unclear wording follows a safe No path that records mempalace-code version-check --disable."
  - id: AC-3
    when: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_scheduler_choice_is_readonly_gated -q is run"
    then: "the scheduled-update question appears only after Linux, systemd-user, supported isolated installer, and scheduler-support checks; affirmative wording renders units, installs with --yes, and verifies status."
  - id: AC-4
    when: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_unsupported_update_outcomes_are_manual_only -q is run"
    then: "macOS, Windows, unavailable systemd-user, project pip, editable/source, distro-managed, and ambiguous environments produce an unsupported/manual-update result without a scheduler prompt or fallback mutation."
  - id: AC-5
    when: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_uses_installed_executable_verification -q is run"
    then: "post-install verification uses the resolved mempalace-code executable and version-check --status for pipx, uv-tool, and bootstrap-venv paths without requiring ambient system python3 to import mempalace_code."
  - id: AC-6
    when: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_final_report_fields -q is run"
    then: "the final install report always includes installed version, notification enabled/disabled state, updater installer/support result, scheduler supported/enabled state, and exact commands for later opt-in changes."
  - id: AC-7
    when: "python -m pytest tests/test_version_check.py::test_newer_version_hints_recommend_guarded_update_commands -q is run"
    then: "automatic and --check-now newer-version hints recommend mempalace-code update status and mempalace-code update apply --yes, and no first-party hint recommends pip install --upgrade mempalace-code."
  - id: AC-8
    when: "python -m pytest tests/test_version_check.py::test_fresh_non_tty_cli_skips_prompt_and_network tests/test_version_check.py::test_fresh_interactive_prompt_no_records_opt_out tests/test_cli.py::TestVersionCheckCLIHook::test_health_json_stdout_unchanged_with_opt_in -q is run"
    then: "existing first-run fallback, non-TTY suppression, no-network-by-default, weekly rate limiting, stdout/stderr separation, explicit --check-now, updater fail-closed gates, retained extras, watcher coordination, and rollback behavior remain unchanged."
  - id: AC-9
    when: "python -m pytest tests/test_release_install_metadata_smoke.py tests/test_installed_artifact_behavior.py tests/test_release_readiness_gate.py -q is run"
    then: "fresh installed-artifact smokes cover pipx, uv-tool where available, and bootstrap venv from a neutral directory, proving executable version reporting, explicit notification choices, conditional scheduler routing, safe defaults, and guarded update hints without source-checkout shadowing or real operator package mutation."
  - id: AC-10
    when: "python scripts/docs_drift_guard.py and the canonical Ruff, format, Pyright, and complete non-network pytest checks are run"
    then: "README, docs/AGENT_INSTALL.md, docs/UPDATES.md, CLI help, and version-check hint commands are aligned, and focused version-check, updater, install-smoke, docs-guard, Ruff, format, Pyright, and complete non-network tests pass."
out_of_scope:
  - "Creating a second updater, scheduler, installer detector, or version-check preference store."
  - "Changing updater package mutation semantics, rollback behavior, retained extras policy, watcher coordination, or --yes requirements."
  - "Enabling notifications or scheduled updates by default."
  - "Adding cron, launchd, Windows Task Scheduler, machine-wide systemd units, or distro-package update support."
  - "Changing model download behavior, palace storage, MCP protocol, release publishing, package version, or backlog metadata."
contract_policy:
  flow: full_spdd
  reason: "Standard task that crosses onboarding docs, persisted opt-in preferences, supported updater gates, installed-artifact smokes, and public drift guards."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Every agent-driven install must make the periodic version-notification choice explicit and persist either opt-in or opt-out."
      source: "backlog contract AC-1, AC-2, AC-6"
      acceptance_ids: [AC-1, AC-2, AC-6]
    - id: REQ-2
      statement: "Supported Linux scheduled package updates must be a separate opt-in choice after read-only eligibility checks and must mutate only after an affirmative answer plus the existing --yes gate."
      source: "backlog contract AC-1, AC-3, AC-4, AC-6"
      acceptance_ids: [AC-1, AC-3, AC-4, AC-6]
    - id: REQ-3
      statement: "Agent install verification must use the resolved installed executable and must not depend on ambient system python imports for isolated installs."
      source: "backlog contract AC-5, AC-9"
      acceptance_ids: [AC-5, AC-9]
    - id: REQ-4
      statement: "Newer-version hints must route through the guarded updater status/apply commands instead of raw pip upgrade guidance."
      source: "backlog contract AC-7"
      acceptance_ids: [AC-7]
    - id: REQ-5
      statement: "Existing CLI first-run prompting and updater safety semantics remain fallback behavior outside the agent runbook."
      source: "backlog contract AC-8"
      acceptance_ids: [AC-8]
    - id: REQ-6
      statement: "Installed-artifact smokes and documentation drift guards must cover the install/update choice flow and public documentation surfaces."
      source: "backlog contract AC-9, AC-10"
      acceptance_ids: [AC-9, AC-10]
  surfaces:
    - name: "Agent install runbook"
      kind: cli
      paths: ["docs/AGENT_INSTALL.md"]
      expected_behavior: "Provide the canonical agent decision sequence: preflight, install, explicit notification opt-in/out, read-only updater status, conditional scheduled-update prompt, executable verification, and compact final report."
    - name: "Public update and version guidance"
      kind: cli
      paths: ["README.md", "docs/UPDATES.md", "mempalace_code/cli.py"]
      expected_behavior: "Keep notification wording separate from package update wording and align user-facing update commands with status followed by apply --yes."
    - name: "Version-check hints"
      kind: cli
      paths: ["mempalace_code/version_check.py", "tests/test_version_check.py"]
      expected_behavior: "Automatic stderr hints and explicit --check-now output recommend the guarded updater path and preserve opt-in, rate-limit, and no-network-default behavior."
    - name: "Update status and scheduler rendering"
      kind: cli
      paths: ["mempalace_code/cli_commands/update.py", "tests/test_updater.py"]
      expected_behavior: "Human status output exposes installer support plus scheduler supported/enabled state; scheduler mutation remains reachable only through install --yes."
    - name: "CLI fallback and help"
      kind: cli
      paths: ["mempalace_code/cli.py", "tests/test_cli.py"]
      expected_behavior: "CLI help strings and first-run hook behavior stay compatible while documenting explicit notification/update commands."
    - name: "Installed-artifact smokes"
      kind: cli
      paths:
        - "scripts/release_install_metadata_smoke.py"
        - "tests/test_release_install_metadata_smoke.py"
        - "tests/test_installed_artifact_behavior.py"
        - "scripts/release_readiness_gate.py"
        - "tests/test_release_readiness_gate.py"
      expected_behavior: "Disposable neutral-directory smokes cover pipx, uv-tool where available, and bootstrap venv without touching operator installs or importing from the source checkout."
    - name: "Documentation drift guard"
      kind: internal
      paths: ["scripts/docs_drift_guard.py", "tests/test_docs_drift_guard.py"]
      expected_behavior: "Guard README, AGENT_INSTALL, UPDATES, CLI help, and version-check hints against stale raw-pip upgrade commands or missing opt-in/report fields."
  invariants:
    - id: INV-1
      statement: "No installer path enables periodic notifications or scheduled updates by default."
      applies_to: ["docs/AGENT_INSTALL.md", "mempalace_code/version_check.py", "mempalace_code/updater.py"]
    - id: INV-2
      statement: "Non-TTY CLI behavior, no-network-by-default behavior, weekly rate limiting, and stderr-only automatic hints remain unchanged."
      applies_to: ["mempalace_code/version_check.py", "mempalace_code/cli.py", "tests/test_version_check.py", "tests/test_cli.py"]
    - id: INV-3
      statement: "Updater package/service/scheduler mutation remains fail-closed and requires the existing --yes gates."
      applies_to: ["mempalace_code/updater.py", "mempalace_code/cli_commands/update.py", "tests/test_updater.py"]
    - id: INV-4
      statement: "Supported installer detection remains owned by mempalace_code/updater.py; the agent runbook must not duplicate detection logic beyond read-only command checks and result interpretation."
      applies_to: ["docs/AGENT_INSTALL.md", "mempalace_code/updater.py"]
    - id: INV-5
      statement: "Installed-artifact smokes must use disposable environments and neutral working directories, never the operator's real pipx/uv tool installation or checkout imports."
      applies_to: ["scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py", "tests/test_installed_artifact_behavior.py"]
  risks:
    - id: RISK-1
      risk: "Runbook wording could make metadata notifications sound like package auto-update."
      mitigation: "Use separate questions and docs-guard assertions that notification wording states PyPI metadata only and no package install."
    - id: RISK-2
      risk: "An unclear or absent human answer could leave the CLI fallback prompt surprising the user later."
      mitigation: "Document negative, empty, EOF, and unclear answers as the safe No path and persist mempalace-code version-check --disable."
    - id: RISK-3
      risk: "Scheduler setup could mutate unsupported environments or bypass updater gates."
      mitigation: "Gate the scheduler question behind read-only OS/systemd/installer/scheduler checks and retain scheduler install --yes plus status verification."
    - id: RISK-4
      risk: "Post-install checks could falsely fail isolated installs because system python3 cannot import mempalace_code."
      mitigation: "Verify through the resolved mempalace-code executable and version-check --status, and cover neutral-directory install smokes."
    - id: RISK-5
      risk: "Docs and CLI hints could drift back to raw pip upgrade commands."
      mitigation: "Change version_check hints and add docs-drift tests covering README, AGENT_INSTALL, UPDATES, CLI help, and hint text."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_update_choice_sequence -q"
      proves: "The runbook has separate, numbered notification and scheduled-update choices and distinguishes metadata-only notifications from package updates."
      acceptance_ids: [AC-1]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_notification_choice_records_safe_defaults -q"
      proves: "Notification yes runs version-check --enable; no, empty, EOF, and unclear answers record version-check --disable."
      acceptance_ids: [AC-2]
    - id: VER-3
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_scheduler_choice_is_readonly_gated tests/test_docs_drift_guard.py::test_agent_install_unsupported_update_outcomes_are_manual_only -q"
      proves: "Scheduled package updates are prompted only after read-only eligibility checks, and unsupported environments produce manual-update output without mutation."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-4
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_agent_install_uses_installed_executable_verification tests/test_docs_drift_guard.py::test_agent_install_final_report_fields -q"
      proves: "Post-install verification uses the installed executable and the final report includes version, notification, updater, and scheduler states plus later-change commands."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-5
      owner: provider
      command: "python -m pytest tests/test_version_check.py::test_newer_version_hints_recommend_guarded_update_commands -q"
      proves: "Automatic and explicit newer-version hints use update status and update apply --yes, with no raw pip upgrade hint."
      acceptance_ids: [AC-7]
    - id: VER-6
      owner: provider
      command: "python -m pytest tests/test_version_check.py::test_fresh_non_tty_cli_skips_prompt_and_network tests/test_version_check.py::test_fresh_interactive_prompt_no_records_opt_out tests/test_cli.py::TestVersionCheckCLIHook::test_health_json_stdout_unchanged_with_opt_in tests/test_updater.py::TestScheduling::test_scheduler_is_disabled_by_default_and_refuses_overlap -q"
      proves: "Existing first-run fallback, no-network default, opt-out persistence, stdout/stderr separation, and disabled scheduler defaults remain intact."
      acceptance_ids: [AC-8]
    - id: VER-7
      owner: provider
      command: "python -m pytest tests/test_release_install_metadata_smoke.py tests/test_installed_artifact_behavior.py tests/test_release_readiness_gate.py -q"
      proves: "Installed-artifact smoke logic covers pipx, uv-tool where available, bootstrap venv, neutral cwd, executable version reporting, notification choices, and scheduler routing."
      acceptance_ids: [AC-9]
    - id: VER-8
      owner: provider
      command: "python -m pytest tests/test_docs_drift_guard.py::test_update_docs_and_cli_hint_commands_stay_aligned -q"
      proves: "The drift guard fails if README, AGENT_INSTALL, UPDATES, CLI help, or version-check hints lose the guarded update-command alignment."
      acceptance_ids: [AC-10]
    - id: VER-9
      owner: provider
      command: "python scripts/docs_drift_guard.py"
      proves: "The live repository documentation and CLI source pass the public docs drift guard after the change."
      acceptance_ids: [AC-10]
    - id: VER-10
      owner: configured_runner
      command: "python -m pytest tests/ -x -q -m \"not needs_network\""
      proves: "The configured complete non-network pytest gate passes with the new docs, CLI, updater, version-check, and installed-smoke tests."
      acceptance_ids: [AC-10]
    - id: VER-11
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate passes for changed package, tests, and scripts."
      acceptance_ids: [AC-10]
    - id: VER-12
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate passes for changed package, tests, and scripts."
      acceptance_ids: [AC-10]
    - id: VER-13
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate passes after CLI/update/smoke changes."
      acceptance_ids: [AC-10]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_version_check.py -q"
        proves: "Focused version-check behavior remains covered for prompt persistence, no-network defaults, interval behavior, stderr routing, explicit check-now, and guarded update hints."
        acceptance_ids: [AC-2, AC-7, AC-8]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_updater.py -q"
        proves: "Updater status, scheduler, installer support, watcher coordination, retained extras, fail-closed gates, and rollback behavior remain covered."
        acceptance_ids: [AC-3, AC-4, AC-6, AC-8]
      - id: REG-3
        owner: provider
        command: "python -m pytest tests/test_release_install_metadata_smoke.py tests/test_installed_artifact_behavior.py tests/test_release_readiness_gate.py -q"
        proves: "Installed-artifact smoke behavior and release-readiness forwarding remain covered across supported install contours."
        acceptance_ids: [AC-5, AC-9]
      - id: REG-4
        owner: provider
        command: "python -m pytest tests/test_docs_drift_guard.py -q"
        proves: "Docs drift guard fixtures continue to protect the install decision sequence, final report, docs alignment, and guarded hint commands."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-10]
      - id: REG-5
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The configured complete non-network suite remains green."
        acceptance_ids: [AC-8, AC-10]
      - id: REG-6
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The configured Ruff check remains green."
        acceptance_ids: [AC-10]
      - id: REG-7
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The configured format check remains green."
        acceptance_ids: [AC-10]
      - id: REG-8
        owner: configured_runner
        command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
        proves: "The configured Pyright gate remains green."
        acceptance_ids: [AC-10]
---

## Design Notes

- Treat `docs/AGENT_INSTALL.md` as the primary artifact. Add the update-choice sequence after install verification and before ordinary MCP/usage-rule wrap-up so every agent-driven path reaches the choices.
- Keep the notification prompt default at No. For negative, empty, EOF, and unclear answers, run `mempalace-code version-check --disable` so the later interactive CLI fallback does not ask unexpectedly.
- Phrase notification behavior as PyPI package metadata inspection only. It must never be described as package installation, dependency update, or scheduler setup.
- Scheduled package updates are a separate Linux-only choice. Use read-only checks first: OS is Linux, systemd-user manager is available, `mempalace-code update status --json` reports a supported isolated installer, and scheduler status is supported.
- On an affirmative scheduler answer, show `mempalace-code update scheduler render` before mutation, then run `mempalace-code update scheduler install --yes`, then verify with `mempalace-code update scheduler status`. Any other answer or unsupported status leaves scheduler state unchanged.
- For macOS, Windows, unavailable systemd-user, project pip, editable/source, distro-managed, and ambiguous environments, report manual update commands only: `mempalace-code update status` and, when supported, `mempalace-code update apply --yes`.
- Replace ambient `python3 -c "import mempalace_code"` install verification in the runbook with resolved executable checks such as `command -v mempalace-code`, `mempalace-code version-check --status`, and `mempalace-code update status --json`.
- Keep CLI first-run prompting as a fallback for installs that did not follow the agent runbook. Do not change the non-TTY prompt suppression guard or the automatic check opt-in requirement.
- Update both automatic and explicit newer-version hints in `mempalace_code/version_check.py` so the first-party path is `mempalace-code update status` then `mempalace-code update apply --yes`.
- Extend installed-artifact smokes through existing seams. Add uv-tool coverage only when a uv executable is available, and report a skip/diagnostic without failing environments where uv is absent unless the caller explicitly requires it.
- The bootstrap-venv smoke should mimic the supported `~/.mempalace/venv` topology under a disposable HOME, then probe from a neutral working directory.
- The PLAN phase inspected source only. The listed verification commands are implementation-phase evidence and were not executed during planning.
