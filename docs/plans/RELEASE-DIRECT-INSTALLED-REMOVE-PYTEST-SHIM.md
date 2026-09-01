---
slug: RELEASE-DIRECT-INSTALLED-REMOVE-PYTEST-SHIM
status: completed
authority: non_authoritative
goal: "Remove the transitional source-pytest subprocess from installed_golden while preserving its 26-row exact-wheel contract and the source-owned fixture-shape test."
risk: low
risk_note: "The change deletes one transitional release-test invocation inside an existing owner; focused orchestration and network-failure regressions protect the unchanged gate contract."
files:
  - path: scripts/release_readiness_gate.py
    change: "Delete the source pytest subprocess and derive the terminal suite row solely from the completed direct exact-wheel scenarios and existing network-attempt guard."
  - path: tests/test_release_readiness_gate.py
    change: "Assert that installed_golden launches no pytest or test path, retains all 26 ordered rows, and preserves the terminal network-failure boundary."
  - path: docs/RELEASING.md
    change: "Update only the existing installed-golden owning paragraph to describe direct release-owned scenarios and the retained aggregate result truthfully, removing the transitional-selector claim."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable scorecard after the bounded source and test edits."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable scorecard after the bounded source and test edits."
acceptance:
  - id: AC-1
    when: "installed_golden runs against one exact candidate wheel from the established neutral, offline contour"
    then: "its observed subprocess list contains no pytest launcher or source-test path, and no test module is loaded by the gate"
  - id: AC-2
    when: "the source fixture-shape check is invoked directly from tests/test_cli_golden_scenarios.py"
    then: "test_cli_golden_fixture_shape accepts the representative fixture with its Python, Markdown, TOML, and Go files below the existing size bound"
  - id: AC-3
    when: "the direct exact-wheel scenarios succeed or a socket-network attempt is recorded"
    then: "installed_golden preserves the exact 26-row success order and gate count, while the network attempt still returns the single sanitized installed_golden_suite failure row and disposable cleanup completes"
  - id: AC-4
    when: "focused source checks, configured static/public gates, a fresh exact-wheel direct run, the full non-network suite, and independent correctness, security, and Rule Zero reviews are collected for one candidate"
    then: "every required command and review reports success with provenance, failure boundaries, cleanup, and public-release shape unchanged"
out_of_scope:
  - "Changes to tests/test_cli_golden_scenarios.py, test_cli_golden_fixture_shape, its fixture writer, or any source-owned CLI scenario."
  - "Changes to the 26 direct scenario implementations, row IDs, row order, row details, provenance, isolation, timeouts, socket guard, cleanup, inventory, or public release commands."
  - "Product code, declared inventory, supported Linux hosted updates, adjacent release surfaces, dependencies, workflows, or architecture boundaries. In docs/RELEASING.md, everything outside the single installed-golden owning paragraph."
  - "Backlog metadata, publication, remote mutation, credentials, external AI-client invocation, staging, commits, and runner finalization."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task changes a release-blocking installed-wheel provider pipeline while preserving its public and failure contracts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The installed-golden owner must execute only direct exact-wheel scenarios and must not invoke pytest or load a test module."
      source: "Current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "test_cli_golden_fixture_shape must remain source-owned, unchanged, and independently executable."
      source: "Current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "All 26 direct exact-wheel rows, provenance, order, gate count, failure boundaries, and cleanup must remain unchanged after shim removal."
      source: "Current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Focused, configured, fresh-wheel, full-suite, and independent review evidence must qualify the same bounded change."
      source: "Current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "Exact-wheel installed golden orchestration"
      kind: internal
      paths: [scripts/release_readiness_gate.py]
      expected_behavior: "Return the existing 26 ordered direct-result rows without launching source pytest, while retaining the terminal network-attempt failure guard."
  invariants:
    - id: INV-1
      statement: "Exact-wheel installation, watch extra, metadata/module/executable provenance, neutral cwd, offline flags, credential removal, socket denial, and disposable cleanup remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-2
      statement: "Every direct scenario call, early failure boundary, row ID, result order, gate count of 26, success detail, and sanitized network-failure detail remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-3
      statement: "tests/test_cli_golden_scenarios.py and test_cli_golden_fixture_shape remain source-owned and unedited."
      applies_to: [scripts/release_readiness_gate.py, tests/test_cli_golden_scenarios.py]
    - id: INV-4
      statement: "Gate inventory, workflows, product modules, public commands, dependencies, and adjacent release surfaces are not edited; in docs/RELEASING.md only the existing installed-golden owning paragraph changes, and no public instruction may still claim the installed-golden owner invokes pytest, a selector, or a source test module."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py, docs/RELEASING.md]
    - id: INV-5
      statement: "Qualification performs no external AI-client call, credential access, publication, remote mutation, or non-disposable product-data mutation."
      applies_to: [scripts/release_readiness_gate.py]
  risks:
    - id: RISK-1
      risk: "Deleting the whole terminal suite block could also remove the socket-attempt failure boundary or the final installed_golden_suite row."
      mitigation: "Delete only the pytest invocation and returncode dependency; keep the attempts-log check, sanitized failure row, success row, and list position under focused regression."
    - id: RISK-2
      risk: "Updating the orchestration test around its former last pytest call could weaken provenance, environment, order, or call-count assertions."
      mitigation: "Retain every existing direct-row and environment assertion, replace only suite-command expectations with explicit absence checks across the complete recorded subprocess list."
    - id: RISK-3
      risk: "Removing the old synthetic pytest-failure test could leave the terminal failure row untested."
      mitigation: "Replace it with an injected socket-attempt regression that asserts the same single sanitized installed_golden_suite failure boundary."
    - id: RISK-4
      risk: "Source and test line-count changes can stale deterministic quality artifacts."
      mitigation: "Regenerate only the two existing scorecard outputs and require the configured scorecard check."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_golden_uses_watch_extra_provenance_neutral_cwd_and_safe_env tests/test_release_readiness_gate.py::test_installed_golden_propagates_network_failure_with_sanitized_detail tests/test_cli_golden_scenarios.py::test_cli_golden_fixture_shape -q"
      proves: "The gate records no pytest or test-module launch, retains 26 ordered direct rows and the terminal network failure, and keeps the source fixture-shape behavior green."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "A fresh exact wheel exercises the unchanged provenance, direct rows, result order, failure guards, and cleanup without the transitional source-suite process."
      acceptance_ids: [AC-1, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The bounded orchestration and regression edits satisfy the configured lint gate."
      acceptance_ids: [AC-4]
    - id: VER-4
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The bounded orchestration and regression edits satisfy the configured format gate."
      acceptance_ids: [AC-4]
    - id: VER-5
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The simplified release-gate control flow satisfies the configured basic type gate."
      acceptance_ids: [AC-1, AC-3, AC-4]
    - id: VER-6
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict type slice remains green after the release-gate-only change."
      acceptance_ids: [AC-4]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The implementation and regenerated scorecards retain the public-safe release shape."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The installed_golden command and single canonical gate count remain synchronized across public surfaces."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Public release documentation remains consistent after the truthful installed-golden paragraph update, with no public command or release-shape change."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-10
      owner: configured_runner
      command: "python scripts/architecture_guard.py --root ."
      proves: "Shim removal stays inside the existing release-gate owner and adds no architecture boundary."
      acceptance_ids: [AC-1, AC-4]
    - id: VER-11
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The regenerated deterministic quality artifacts match the final source and test inventory."
      acceptance_ids: [AC-2, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The configured full suite preserves source-owned golden coverage, all direct release scenarios, and unrelated non-network product behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- Current HEAD `5ca65142` has one remaining transitional ownership path: after all direct exact-wheel scenarios pass, `_run_installed_golden_wheel` launches source Python as `python -m pytest --noconftest tests/test_cli_golden_scenarios.py` with nineteen negative selectors. The direct owner then converts that subprocess result or a socket-attempt log into `installed_golden_suite`.
- Rule Zero selects deletion inside the existing owner. The 26 direct rows already own installed qualification, while `test_cli_golden_fixture_shape` is a source-only fixture contract. Moving fixture code, importing the test module, adding a new runner, or copying the fixture check into the release gate creates a second owner and is outside acceptance.
- Remove the `suite = _run_golden_subprocess(...)` block and the `suite.returncode` branch only. Read `socket-attempts.log` after the last direct scenario as today; on content, return the existing single `installed_golden_suite` failure row with the existing bounded network-attempt detail. On empty content, return the exact existing 26-row list, including the final `installed_golden_suite` PASS row in the same position with the same detail.
- Update `test_installed_golden_uses_watch_extra_provenance_neutral_cwd_and_safe_env` without weakening its exact wheel-extra, provenance, 26-status, row-order, neutral-cwd, environment, credential-removal, scenario-call, socket-log, and setup-root assertions. Replace the former final pytest-command assertions with complete-call-list predicates that reject `-m pytest`, `tests/test_cli_golden_scenarios.py`, and any test-module loader call.
- Replace `test_installed_golden_propagates_suite_failure_with_sanitized_detail`, whose failure source disappears with the shim, with a terminal socket-attempt regression. Inject one bounded socket-attempt record after otherwise successful direct scenarios, require exactly one failed `installed_golden_suite` row, require sanitized detail with no disposable absolute path, and verify temporary-root cleanup after return.
- Leave `tests/test_cli_golden_scenarios.py::test_cli_golden_fixture_shape` byte-for-byte unchanged. VER-1 invokes it directly so source ownership remains observable independently of installed-golden execution.
- `docs/RELEASING.md` contains one installed-golden owning paragraph (currently "The installed-golden owner creates one disposable venv ... runs direct release-owned scenarios plus a bounded transitional selector from `tests/test_cli_golden_scenarios.py` ...", docs/RELEASING.md:109-120). Update only that paragraph so it truthfully describes direct release-owned scenarios and the retained aggregate `installed_golden_suite` result, with no selector, pytest, or source-test-module claim. No other public documentation, command block, or release instruction changes. Cheapest doc falsifier: after the shim deletion, any public instruction that still says the installed-golden owner invokes pytest, a selector, or a source test module is untruthful; VER-9 (`docs_drift_guard.py`) and review of the single paragraph close it.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` through the existing scorecard writer after implementation. Do not hand-edit metrics or change canonical commands.
- Cheapest decisive falsifier: the focused orchestration test records every subprocess and rejects any pytest launcher or source-test path. It fails on current HEAD because the last call is the transitional pytest process; after the change it must pass alongside the 26-row and network-failure assertions.
- Command context basis: `pyproject.toml` declares Python 3.11+ plus pytest, Ruff, and Pyright development dependencies; `scripts/gate_inventory.py` provides the exact configured full-suite, static/public, scorecard, architecture, and installed-wheel commands. All commands run from the repository root. PLAN read manifests and existing source only; no tests, builds, gates, wrappers, reviews, or validation scripts were executed.
- Independent correctness, security, and Rule Zero review verdicts remain runner-owned evidence for AC-4. They are observable next-phase outputs and are not represented as shell pseudo-commands or new repository artifacts.
- `docs/quality/incident-class-registry.yaml` is absent, and this bounded release-test shim deletion changes no runtime provider, routing/profile, budget minimum, recovery state, or verify-fix authority. No `incident_proof` block applies.
- Implementation stops after the two localized source/test edits, the single truthful `docs/RELEASING.md` paragraph update, deterministic scorecard regeneration, and declared qualification. Backlog bookkeeping, staging, commit, source verification, publication, and finalization remain runner-owned.
