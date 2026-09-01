---
slug: UPDATE-UNSUPPORTED-PLATFORM-DIAGNOSTICS
status: completed
authority: non_authoritative
superseded_by: UPDATE-MACOS-MANUAL-APPLY-RESTORE
goal: "Return a stable unsupported-platform diagnosis before confirmed update mutations can invoke systemctl."
risk: medium
risk_note: "The change is small but sits before package, watcher, and scheduler mutations in a pre-release CLI; ordering mistakes could weaken Linux behavior or confirmation guards."
files:
  - path: mempalace_code/updater.py
    change: "Extend UpdateManager's existing eligibility and UpdateResult boundaries with one Linux systemd-user platform preflight used by apply and scheduler mutations, while keeping read-only status diagnostic."
  - path: tests/test_updater.py
    change: "Add focused macOS platform-boundary and JSON-contract regressions plus Linux and confirmation-preservation controls."
  - path: scripts/release_install_metadata_smoke.py
    change: "Extend the existing disposable installed-console smoke to invoke update status and all three confirmed mutations directly on unsupported host platforms and validate their structured results."
  - path: tests/test_release_install_metadata_smoke.py
    change: "Add subprocess-seam coverage for the installed-console unsupported-platform probe, command set, JSON assertions, and failure propagation."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing human-readable quality scorecard after the accepted test additions."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing machine-readable quality scorecard after the accepted test additions."
acceptance:
  - id: AC-1
    when: "update apply --yes --json, update scheduler install --yes --json, and update scheduler remove --yes --json run with sys.platform set to darwin and a runner that records every command"
    then: "each exits 2 with stage unsupported-platform before any systemctl call, package command, scheduler file write, update state write, or service mutation"
  - id: AC-2
    when: "any confirmed update mutation is refused on macOS in JSON mode"
    then: "the single JSON object names darwin, the required Linux systemd-user boundary, and recovery_command=mempalace-code update status --json"
  - id: AC-3
    when: "unsupported-platform tests use a runner that would raise FileNotFoundError for systemctl and the three confirmed mutations execute"
    then: "the stable unsupported-platform message is the primary diagnosis and output contains no FileNotFoundError, Errno, or missing-systemctl detail"
  - id: AC-4
    when: "the existing Linux apply and scheduler success controls run and each guarded mutation is invoked without --yes in human and JSON modes"
    then: "Linux keeps its existing systemctl transaction behavior, while every unconfirmed mutation exits 2 before UpdateManager mutation methods are called"
  - id: AC-5
    when: "the disposable venv smoke installs the candidate on macOS and invokes its absolute mempalace-code executable from a neutral directory"
    then: "update status --json exits 0 with useful platform, installation, provenance, watcher, and scheduler data, and confirmed apply, scheduler install, and scheduler remove each satisfy the unsupported-platform JSON contract"
out_of_scope:
  - "Adding launchd, cron, Windows Task Scheduler, machine-wide services, or any non-Linux scheduled-update implementation."
  - "Changing supported installer detection, release selection, package mutation, rollback, watcher attribution, or systemd unit rendering."
  - "Weakening or reordering the explicit --yes confirmation guard."
  - "Changing public install documentation that already declares the Linux systemd-user boundary, release workflows, provider clients, credentials, publication, or backlog metadata."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release runtime bug changes mutation preflight and installed-executable release evidence at a platform boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Confirmed update and scheduler mutations must reject macOS before invoking systemctl or writing mutation state."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Unsupported-platform JSON must identify the host, Linux systemd-user requirement, and one safe read-only recovery command."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Raw executable and operating-system exceptions must not become the primary unsupported-platform diagnosis."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Linux update behavior and explicit confirmation guards must remain unchanged."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "A freshly installed macOS executable must directly exercise status and all confirmed update mutation commands."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Update platform and mutation owner"
      kind: cli
      paths: ["mempalace_code/updater.py"]
      expected_behavior: "UpdateManager reports one structured unsupported-platform result before apply or scheduler mutation effects, while status remains read-only and useful."
    - name: "Installed update boundary smoke"
      kind: internal
      paths: ["scripts/release_install_metadata_smoke.py"]
      expected_behavior: "The existing disposable install harness directly proves status and confirmed mutation behavior through the installed console on unsupported hosts."
  invariants:
    - id: INV-1
      statement: "The CLI confirmation guard remains the first boundary for apply, scheduler install, and scheduler remove when --yes is absent."
      applies_to: ["mempalace_code/cli_commands/update.py", "mempalace_code/updater.py", "tests/test_updater.py"]
    - id: INV-2
      statement: "On Linux, apply keeps watcher discovery, installer transaction, validation, rollback, and service restoration behavior, and scheduler mutations keep their current systemctl commands and file ownership."
      applies_to: ["mempalace_code/updater.py", "tests/test_updater.py"]
    - id: INV-3
      statement: "Status and scheduler status remain read-only, and scheduler render remains available without writing units or invoking systemctl."
      applies_to: ["mempalace_code/updater.py", "tests/test_updater.py"]
    - id: INV-4
      statement: "UpdateResult.as_dict and the existing CLI renderer remain the sole machine-readable and human result renderers."
      applies_to: ["mempalace_code/updater.py", "mempalace_code/cli_commands/update.py"]
    - id: INV-5
      statement: "The installed smoke retains disposable HOME, neutral cwd, absolute installed executable provenance, credential-free execution, and zero provider-client or publication behavior."
      applies_to: ["scripts/release_install_metadata_smoke.py", "tests/test_release_install_metadata_smoke.py"]
  risks:
    - id: RISK-1
      risk: "A platform check placed after provenance or service discovery could still expose systemctl failures or create partial mutation state."
      mitigation: "Call the shared platform eligibility check at the start of each confirmed mutation and assert zero runner calls and unchanged filesystem snapshots on darwin."
    - id: RISK-2
      risk: "Platform handling added to status could turn a useful read-only command into a failure or hide installer and provenance information."
      mitigation: "Keep status successful, bypass only systemd probes on unsupported hosts, and return explicit watcher and scheduler diagnostic objects alongside existing installation and provenance fields."
    - id: RISK-3
      risk: "A broad platform guard could suppress the existing Linux transaction or move ahead of the --yes guard."
      mitigation: "Treat linux as the pass-through case inside UpdateManager and retain the CLI-level confirmation tests plus existing Linux success nodes."
    - id: RISK-4
      risk: "Unit seams could pass while the packaged console still renders a different result."
      mitigation: "Extend the existing installed-artifact smoke rather than creating a second harness, and invoke the absolute disposable console for all four commands on macOS."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_updater.py::TestUnsupportedPlatformDiagnostics -q"
      proves: "Focused manager and CLI cases prove macOS preflight ordering, stable JSON fields, exception suppression, useful read-only status, and Linux pass-through behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_release_install_metadata_smoke.py::TestUnsupportedPlatformUpdateProbe -q"
      proves: "The installed-smoke subprocess seam invokes the exact status/apply/install/remove command set and rejects missing, malformed, raw-exception, or inconsistent results."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-5]
    - id: VER-3
      owner: provider
      command: "python scripts/release_install_metadata_smoke.py --install-spec . --json"
      proves: "On the macOS implementation host, a fresh disposable install invokes the absolute installed executable from a neutral directory and records passing status plus confirmed unsupported-platform mutation evidence."
      acceptance_ids: [AC-2, AC-3, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/release_install_metadata_smoke.py --all-installers --install-spec . --json"
      proves: "The existing required all-installer smoke remains intact on Linux and automatically carries the unsupported-platform installed-console proof when run on macOS."
      acceptance_ids: [AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: provider
        command: "python -m pytest tests/test_updater.py::TestUpdateCommand::test_guarded_mutations_require_yes_without_invoking_updater -q"
        proves: "All guarded mutation variants still refuse before updater methods when --yes is absent."
        acceptance_ids: [AC-4]
      - id: REG-2
        owner: provider
        command: "python -m pytest tests/test_updater.py::TestApplyUpdate::test_apply_stops_active_watcher_preserves_extras_and_restarts_after_validation -q"
        proves: "The supported Linux apply transaction still coordinates the watcher, retains extras, installs, validates, and persists success."
        acceptance_ids: [AC-4]
      - id: REG-3
        owner: provider
        command: "python -m pytest tests/test_updater.py::TestScheduling::test_scheduler_remove_disables_and_removes_owned_units -q"
        proves: "The supported Linux scheduler removal still disables the timer, removes owned units, and reloads systemd-user."
        acceptance_ids: [AC-4]
---

## Superseded Notice

This plan is a historical record and no longer describes current behavior. Its Darwin-wide manual
apply refusal was superseded by UPDATE-MACOS-MANUAL-APPLY-RESTORE in v1.13.6, which admits macOS
manual apply with launchd watcher coordination. Only the scheduler refusal remains Linux-only. The
current contract is docs/UPDATES.md; the plan body below is preserved unchanged as history.

## Design Notes

- Reuse `UpdateManager` as the platform-eligibility owner and `UpdateResult` as the response owner. Add no platform service, response subclass, CLI branch, or second mutation route.
- Normalize support as `sys.platform.startswith("linux")`. Preserve the exact observed platform string in JSON so `darwin`, `win32`, and future unsupported identifiers remain diagnostic without being admitted.
- Use one stable mutation result for apply, scheduler install, and scheduler remove: `ok=false`, `stage=unsupported-platform`, `exit_code=2`, `platform=<sys.platform>`, `required_platform=linux`, `service_manager=systemd-user`, and `recovery_command=mempalace-code update status --json`. The message states that update mutations require Linux systemd-user and does not include caught executable exception text.
- Evaluate that result at the start of each `UpdateManager` mutation method. For apply, this precedes provenance resolution and watcher discovery; for scheduler install it precedes unit rendering or directory creation; for scheduler remove it precedes disable, unlink, and reload.
- Keep `_require_yes` in `mempalace_code/cli_commands/update.py` unchanged. Calls without `--yes` continue to return the confirmation-stage recovery for the requested mutation before constructing a mutation result.
- On unsupported hosts, `status()` still detects installation, resolves provenance, reads cached update state, and exits 0. It bypasses watcher and timer subprocesses and returns explicit inactive/unsupported watcher and scheduler diagnostics using the same platform/boundary fields. `scheduler_status()` returns that read-only diagnostic directly; `render_scheduler_units()` remains deterministic and non-mutating.
- Add one `TestUnsupportedPlatformDiagnostics` class. Patch the updater module's `sys.platform`, use a runner that records or raises on every call, snapshot the temporary state/home roots, and exercise manager results plus JSON CLI rendering. Include a Linux pass-through case so the guard predicate cannot accidentally reject supported hosts.
- Extend the existing installed smoke with one update-platform surface on non-Linux hosts. Resolve and invoke the same absolute disposable console already provenance-checked, from the neutral probe cwd and isolated environment. Run `update status --json`, then the three mutation commands with `--yes --json`; require empty stderr, exact exit codes/stages/fields, useful status objects, and unchanged mutable-state snapshots.
- Keep the existing no-`--yes` recovery probe unchanged and separate from confirmed unsupported-platform proof. This preserves the distinction between confirmation authority and platform eligibility.
- Command context basis: `pyproject.toml` declares Python 3.11+, the console entry point, pytest dev dependency, and repository-root package layout. `scripts/gate_inventory.py` declares the exact all-installer configured command used by VER-4; the other rows are bounded provider-owned test nodes or the single-installer installed smoke.
- `docs/quality/incident-class-registry.yaml` is absent in this checkout, so this runtime fix has no registry-matched incident-proof block.
- PLAN did not run tests, builds, installed smokes, verification wrappers, or generated-plan validation.
