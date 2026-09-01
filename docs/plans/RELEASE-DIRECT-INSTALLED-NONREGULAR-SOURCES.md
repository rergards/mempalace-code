---
slug: RELEASE-DIRECT-INSTALLED-NONREGULAR-SOURCES
status: completed
authority: non_authoritative
goal: "Preserve a pre-existing empty watcher lease directory while retaining the single direct exact-wheel non-regular source owner and its thin source consumer."
risk: medium
risk_note: "The code change is one cleanup deletion, but the release-blocking scenario must still remove only scenario-created lease artifacts and preserve every pre-existing disposable-root entry."
files:
  - path: scripts/release_readiness_gate.py
    change: "Stop cleanup_new_lease_artifacts from removing the lease root after deleting only scenario-created lease files."
  - path: tests/test_release_readiness_gate.py
    change: "Extend the successful non-regular source scenario regression to pre-create an empty HOME/.mempalace directory and prove it survives unchanged."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable scorecard after the focused test changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable scorecard after the focused test changes."
acceptance:
  - id: AC-1
    when: "The installed-golden gate receives the exact candidate wheel in its populated offline model-cache contour."
    then: "It invokes that wheel's absolute console from a neutral cwd in the existing offline, credential-free, socket-denied environment."
  - id: AC-2
    when: "Project mine, stale-source remine, mine-all, watcher startup/shutdown, and conversation mining run through the release-owned scenario."
    then: "Each path rejects same-extension symlink, FIFO, directory, and platform-supported Unix socket nodes within hard bounds without opening or blocking on them."
  - id: AC-3
    when: "The direct scenario starts with an empty HOME/.mempalace lease directory that existed before execution."
    then: "Regular indexing/search, exact diagnostics, stale drawer removal, watcher lease cleanup, output/time bounds, socket cleanup, and all disposable-root post-state pass while the pre-existing empty lease directory remains present and unchanged."
  - id: AC-4
    when: "Source and exact-wheel qualification collect the non-regular source behavior."
    then: "test_cli_non_regular_source_guard remains a thin source consumer of one release-owned scenario, the transitional selector retains its exact negative clause, and the direct installed owner emits one executed result row."
  - id: AC-5
    when: "The focused source command, configured full non-network suite, static/public gates, fresh exact-wheel run, and independent Rule Zero, correctness, and security reviews complete for one candidate."
    then: "Every required command and review reports success for the same candidate without publication, credential access, or external AI-client execution."
out_of_scope:
  - "Changing fixture shape, declared inventory, Linux hosted behavior, product source-I/O behavior, or adjacent direct-installed scenarios."
  - "Changing tests/test_cli_golden_scenarios.py, the established direct scenario body, row ordering, selector clauses, or gate inventory."
  - "Adding a runner, helper framework, dependency, service, state owner, persisted contract, or product interface."
  - "Publication, remote mutation, AI-client invocation, credential access, backlog metadata, and release bookkeeping."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release work corrects a release-gate cleanup ownership violation while preserving filesystem, watcher, isolation, and exact-wheel guarantees."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The established installed-golden contour continues to invoke only the exact candidate console from its neutral, offline, credential-free, socket-denied environment."
      source: "Current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The one release-owned scenario continues to exercise every required mining and watcher path against every supported non-regular source kind without blocking."
      source: "Current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Cleanup removes scenario-created lease files and sockets while preserving a pre-existing empty lease directory and all established behavioral evidence."
      source: "Current backlog contract AC-3 and final review residual"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The existing direct owner, thin source consumer, exact negative selector, and single result row remain the only ownership path."
      source: "Current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused, configured repository, static/public, fresh-wheel, and independent review evidence qualifies the final residual."
      source: "Current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Direct installed non-regular source cleanup"
      kind: internal
      paths: [scripts/release_readiness_gate.py]
      expected_behavior: "Remove only lease artifacts absent at scenario entry; never remove their pre-existing parent directory."
  invariants:
    - id: INV-1
      statement: "The exact-wheel command, absolute console provenance, neutral cwd, offline flags, credential removal, socket denial, timeouts, and sanitized recovery row remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-2
      statement: "Project mine, remine, mine-all, watcher, conversation, diagnostic, search, stale-removal, lease-token, output-bound, and socket-path predicates remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-3
      statement: "tests/test_cli_golden_scenarios.py remains an unchanged thin consumer and its exact transitional negative selector remains present once."
      applies_to: [scripts/release_readiness_gate.py, tests/test_cli_golden_scenarios.py]
    - id: INV-4
      statement: "No product module, workflow, inventory row, dependency, public interface, persisted state owner, or adjacent scenario changes."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
  risks:
    - id: RISK-1
      risk: "Retaining the unconditional rmdir deletes pre-existing empty state and makes a valid scenario fail its own boundary check."
      mitigation: "Delete only the rmdir block; the existing artifact-existence map continues to unlink only files created by the scenario."
    - id: RISK-2
      risk: "Removing broader cleanup could retain scenario-created owner files or sockets."
      mitigation: "Keep the per-artifact unlink loop and socket cleanup unchanged, and run the successful direct scenario plus the fresh exact-wheel gate."
    - id: RISK-3
      risk: "A broad test rewrite could disturb the already-reviewed fault matrix or recreate duplicate scenario ownership."
      mitigation: "Pre-create the empty directory only for the existing success case and assert its post-state; leave the source consumer and scenario matrix untouched."
    - id: RISK-4
      risk: "The focused test edit can stale generated quality metrics."
      mitigation: "Regenerate the two existing scorecard artifacts and require the configured scorecard check."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest 'tests/test_release_readiness_gate.py::test_installed_non_regular_source_scenario[success]' tests/test_cli_golden_scenarios.py::test_cli_non_regular_source_guard -q"
      proves: "The pre-existing empty lease root survives the successful release-owned scenario, and the thin source consumer still delegates to the same owner."
      acceptance_ids: [AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The fresh exact candidate wheel executes the direct non-regular source row once through its absolute console in the established isolated contour."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-3
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The bounded cleanup and regression edits satisfy the configured lint gate."
      acceptance_ids: [AC-5]
    - id: VER-4
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The bounded cleanup and regression edits satisfy the configured format gate."
      acceptance_ids: [AC-5]
    - id: VER-5
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The unchanged function contract and focused test setup satisfy the configured basic type gate."
      acceptance_ids: [AC-3, AC-5]
    - id: VER-6
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict type slice remains green."
      acceptance_ids: [AC-5]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The implementation and regenerated scorecards contain no private or credential-shaped material."
      acceptance_ids: [AC-1, AC-5]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The deterministic scorecard artifacts match the final source and test inventory."
      acceptance_ids: [AC-5]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/architecture_guard.py --root ."
      proves: "The cleanup correction stays within the existing release-gate owner and adds no architecture boundary."
      acceptance_ids: [AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The configured full suite preserves all product, watcher, mining, conversation, CLI, storage, and release-gate behavior around the cleanup correction."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Current HEAD already has the desired ownership shape: `_run_installed_non_regular_source_scenario` owns the node matrix and direct row, `_run_installed_golden_wheel` invokes it before transitional pytest, and `test_cli_non_regular_source_guard` delegates as a thin source consumer. Preserve those completed paths.
- The live defect is confined to `cleanup_new_lease_artifacts()`: its per-path loop correctly unlinks only artifacts that did not exist at scenario entry, then an unconditional best-effort `lease_root.rmdir()` can remove a directory that existed before the scenario. Remove the directory-removal block and retain the loop unchanged.
- The outer disposable environment owner already owns final directory cleanup. The scenario owns only the lease files and socket nodes it created, so retaining the empty parent restores ownership alignment without adding state or cleanup machinery.
- Extend the existing `success` parameter setup in `test_installed_non_regular_source_scenario`: create `HOME/.mempalace` before calling the scenario, require the row to remain PASS, and assert that exact directory still exists afterward. This setup fails on the current implementation because boundary validation observes the removed directory.
- Keep every existing failure parameter, watcher stub, lease descriptor assertion, socket-path assertion, scenario call, source consumer, selector clause, and row-order test byte-for-byte unless formatting requires movement.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with the existing scorecard writer after the test edit; do not hand-edit generated metrics.
- Rule Zero comparison: deleting the rmdir block has the lowest lifecycle and rollback cost. Deleting the scenario loses release evidence, retaining the block preserves the reproduced ownership violation, and a new directory-ownership flag or helper duplicates the existing `lease_artifacts_existed` authority.
- Cheapest decisive falsifier: pre-create an empty `HOME/.mempalace`, run the successful injected scenario, and require PASS plus the directory's continued existence. The current rmdir block makes that exact case fail.
- Command context basis: `pyproject.toml` declares pytest, Ruff, and Pyright from the repository root; `scripts/gate_inventory.py` provides the exact configured full-suite, static/public, scorecard, architecture, and installed-wheel commands used above. PLAN inspected these sources without running any command row.
- Independent Rule Zero, correctness, and security verdicts remain runner-owned review evidence for AC-5. They are not represented as shell pseudo-commands or new repository artifacts.
- No `incident_proof` block applies: `docs/quality/incident-class-registry.yaml` is absent, and this release-test cleanup correction does not change an Autopilot provider, routing profile, budget minimum, recovery state, or verify-fix authority.
- Implementation stops after the two localized source/test edits, deterministic scorecard regeneration, and declared qualification. Publication, backlog bookkeeping, staging, commit, and finalization remain runner-owned.
