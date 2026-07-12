---
slug: AUTO-UPDATE-CUSTOM-WATCHER-UNIT-DISCOVERY
goal: "Coordinate explicit package updates with one safely attributable active systemd-user watcher unit."
risk: medium
risk_note: "The updater can stop watchers and install packages, so discovery mistakes must block mutation rather than target the wrong systemd-user unit."
files:
  - path: mempalace_code/updater.py
    change: "Add injectable systemd-user watcher discovery, surface its safe selection status, and use the selected unit through update stop, restart validation, and rollback."
  - path: mempalace_code/cli_commands/update.py
    change: "Print the selected watcher unit together with its discovery detail in human update status output."
  - path: tests/test_updater.py
    change: "Add focused runner-backed cases for named watcher selection, legacy fallback, ambiguous or invalid discovery refusal, transaction restart, and rollback restart."
  - path: docs/UPDATES.md
    change: "Document attributable named watcher discovery, safe refusal details, and the unchanged explicit scheduler-install boundary."
  - path: docs/AGENT_INSTALL.md
    change: "Align supported-install update guidance with named watcher discovery and the explicit systemd-user timer opt-in."
  - path: docs/quality/scorecard.md
    change: "Regenerate the committed deterministic quality scorecard after updater test coverage changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the committed deterministic quality scorecard JSON after updater test coverage changes."
acceptance:
  - id: AC-1
    when: "a systemd-user manager reports exactly one active `mempalace-watch-<root>.service` whose ExecStart begins the MemPalace `watch` command"
    then: "`update status` selects that exact unit and reports its active state and name in both human and JSON output"
  - id: AC-2
    when: "`update apply --yes` runs with an eligible update and the selected named watcher active"
    then: "the transaction stops, restarts, and validates that exact named unit, without addressing the legacy default unit"
  - id: AC-3
    when: "a staged package, CLI, palace, or watcher validation failure occurs after a selected named watcher was stopped"
    then: "rollback restores the prior package version and restarts then validates the same selected named watcher"
  - id: AC-4
    when: "the legacy `mempalace-watch.service` is the active or only attributable watcher"
    then: "status and update coordination retain the existing default-unit behavior"
  - id: AC-5
    when: "systemd-user discovery is ambiguous, unavailable, malformed, or finds a matching unit name with a non-MemPalace ExecStart"
    then: "status gives an actionable safe reason and `update apply --yes` performs no package installation or service stop/start"
  - id: AC-6
    when: "an operator reads the supported update guidance"
    then: "it explains named watcher discovery and states that the systemd-user update timer remains disabled until explicit installation"
out_of_scope:
  - "Creating, renaming, enabling, or migrating watcher systemd-user units."
  - "Changing scheduler cadence, timer service contents, installer ownership rules, or PyPI provenance policy."
  - "Adding automatic update execution outside the existing explicit scheduler-install flow."
contract_policy:
  flow: full_spdd
  reason: "Strict reliability task changes package-update coordination with user services and requires fail-closed mutation behavior."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The updater must discover and identify one active named MemPalace watcher unit when it is uniquely attributable."
      source: "backlog description"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Update apply and compensating rollback must coordinate the selected watcher unit for every service action."
      source: "backlog description"
      acceptance_ids: [AC-2, AC-3]
    - id: REQ-3
      statement: "Legacy default behavior remains available, while ambiguous, unrelated, malformed, or unavailable service-manager data blocks mutation."
      source: "backlog description"
      acceptance_ids: [AC-4, AC-5]
    - id: REQ-4
      statement: "Operator documentation must describe discovery and retain the explicit update-timer opt-in boundary."
      source: "backlog description"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Systemd-user watcher adapter and update transaction"
      kind: "internal"
      paths: ["mempalace_code/updater.py"]
      expected_behavior: "A narrow runner-backed adapter selects exactly one attributable active watcher, exposes refusal detail, and preserves that selection for all transaction service operations."
    - name: "Update status CLI"
      kind: "cli"
      paths: ["mempalace_code/cli_commands/update.py"]
      expected_behavior: "Human status output names the selected unit; the existing JSON watcher object carries the same selected unit and safe detail."
    - name: "Focused updater regression coverage"
      kind: "internal"
      paths: ["tests/test_updater.py"]
      expected_behavior: "Runner fixtures prove named selection, default fallback, fail-closed discovery, exact-unit transaction coordination, and rollback recovery."
    - name: "Operator update guidance"
      kind: "internal"
      paths: ["docs/UPDATES.md", "docs/AGENT_INSTALL.md", "docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "Guidance describes safe named-unit discovery and explicit scheduler opt-in; committed quality artifacts match the changed test tree."
  invariants:
    - id: INV-1
      statement: "`update status` and `update check` remain read-only and never stop or start a service."
      applies_to: ["mempalace_code/updater.py", "mempalace_code/cli_commands/update.py"]
    - id: INV-2
      statement: "An update may stop, start, or validate only the single watcher unit selected by successful discovery."
      applies_to: ["mempalace_code/updater.py"]
    - id: INV-3
      statement: "The legacy default unit remains the fallback when it is the sole attributable watcher."
      applies_to: ["mempalace_code/updater.py"]
    - id: INV-4
      statement: "Discovery uncertainty blocks package and service mutation before the update transaction acquires its lease or invokes an installer."
      applies_to: ["mempalace_code/updater.py"]
    - id: INV-5
      statement: "The update timer remains disabled unless the operator explicitly runs scheduler installation with `--yes`."
      applies_to: ["mempalace_code/updater.py", "docs/UPDATES.md", "docs/AGENT_INSTALL.md"]
  risks:
    - id: RISK-1
      risk: "Loose unit-name or ExecStart parsing could stop an unrelated systemd-user service."
      mitigation: "Accept only exact watcher-name candidates with a parseable MemPalace watch command and reject every ambiguous, malformed, or unrelated result."
    - id: RISK-2
      risk: "Unavailable systemd-user manager output could be mistaken for an inactive watcher and permit an uncoordinated package update."
      mitigation: "Carry discovery availability into preflight and return a non-mutating refusal with the manager detail."
    - id: RISK-3
      risk: "Selection could be lost between preflight, rollback, and restart paths."
      mitigation: "Keep the selected adapter instance as transaction state and assert the exact unit in success and rollback tests."
    - id: RISK-4
      risk: "New updater tests make committed quality scorecard artifacts stale."
      mitigation: "Regenerate both scorecard formats and check their deterministic freshness after focused tests."
  verification:
    - id: VER-1
      command: "./.venv/bin/python -m pytest tests/test_updater.py -q"
      proves: "named-unit selection appears in JSON and human status, the exact selected unit is coordinated on success and rollback, default fallback remains compatible, and unsafe discovery refuses without mutation"
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      command: "rg -q 'mempalace-watch-.*service' docs/UPDATES.md docs/AGENT_INSTALL.md && rg -q 'disabled until.*install' docs/UPDATES.md docs/AGENT_INSTALL.md"
      proves: "both operator guides expose named-unit discovery and the explicit disabled-by-default scheduler boundary"
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "./.venv/bin/python -m pytest tests/test_updater.py -q"
        proves: "existing installer eligibility, default watcher coordination, lock handling, scheduler status, and rollback behavior remain covered with the discovery change"
        acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
      - id: REG-2
        command: "./.venv/bin/python -m ruff check mempalace_code/updater.py mempalace_code/cli_commands/update.py tests/test_updater.py"
        proves: "changed updater, CLI rendering, and focused tests satisfy the repository lint rules"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-3
        command: "./.venv/bin/python scripts/quality_scorecard.py --check"
        proves: "committed quality scorecard artifacts are deterministic and fresh for the changed test tree"
        acceptance_ids: [AC-6]
---

## Design Notes

- Extend `SystemdUserService` rather than adding a second service-control path. Keep its command runner injectable so discovery and transaction behavior remain hermetic in `tests/test_updater.py`.
- Ask the systemd user manager only for active service units. Treat `mempalace-watch.service` and valid `mempalace-watch-<root>.service` names as candidate units; reject malformed names and non-MemPalace `ExecStart` definitions rather than falling through to package mutation.
- Parse the selected unit's service definition as command tokens, not substring text. Accept only a command beginning with the supported MemPalace `watch` invocation, including the documented console-script and module forms.
- Selection is deterministic and fail-closed: use the unique attributable active named unit; retain the legacy default unit when it is the sole attributable watcher or no custom candidate is active; surface ambiguity, manager failure, malformed data, or an unrelated matching candidate as an unsafe discovery result.
- Preserve the discovery result on the service adapter used by `UpdateManager`. `status` exposes its unit, active state, and detail; `apply` converts an unsafe result into preflight refusal before lock, stop/start, state write, or installer command; rollback reuses the same selected adapter.
- Render the human watcher line with the selected unit and detail. Keep the existing `watcher` JSON object compatible while ensuring its `unit` field names the selected unit and its detail explains safe refusals.
- Update both update guides where the legacy default unit is currently named. State that named discovery does not install or enable the update timer; timer activation remains the explicit `scheduler install --yes` action.
- Verification commands use `./.venv/bin/python`: this plan observed a local `.venv` and `pyproject.toml` configures pytest's `tests` path and development dependencies, while the project guide requires the repository virtualenv rather than the shell's Python.
- Regenerate `docs/quality/scorecard.md` and `docs/quality/scorecard.json` after adding tests because CI checks their deterministic freshness with `scripts/quality_scorecard.py --check`.
