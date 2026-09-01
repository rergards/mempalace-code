---
slug: RELEASE-DIRECT-INSTALLED-CLEANUP-POSTSTATE
status: completed
authority: non_authoritative
goal: "Run cleanup post-state directly in the exact-wheel installed gate while retaining a thin source-mode pytest consumer."
risk: medium
risk_note: "The change is localized, but it moves release-blocking storage post-state proof across process orchestration and must fail closed on malformed or incomplete subprocess evidence."
files:
  - path: scripts/release_readiness_gate.py
    change: "Move the cleanup fixture and post-state scenario into the existing installed-golden owner, emit a dedicated PASS/FAIL row, invoke it for the exact wheel, and deselect its thin pytest consumer from the transitional suite."
  - path: tests/test_cli_golden_scenarios.py
    change: "Replace the cleanup scenario body with a thin source-mode consumer of the release-gate-owned direct scenario."
  - path: tests/test_release_readiness_gate.py
    change: "Extend focused installed-golden orchestration coverage for cleanup success, exact post-state, malformed/non-pass output, launch failure, timeout, exception containment, row propagation, and pytest deselection."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable metrics after removing the duplicate pytest collection."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable metrics after removing the duplicate pytest collection."
acceptance:
  - id: AC-1
    when: "the exact candidate wheel installed-golden command runs from its neutral working directory"
    then: "it executes cleanup post-state through the absolute installed console and emits an executed installed_golden_cleanup_poststate PASS or FAIL evidence row"
  - id: AC-2
    when: "the cleanup scenario is exercised through focused source-mode and installed-gate checks"
    then: "one release-gate-owned fixture and scenario body serve both paths, the pytest test only consumes the returned row, and the transitional installed pytest command deselects that test"
  - id: AC-3
    when: "first and repeated default cleanup complete for the disposable mined palace"
    then: "cleanup and health JSON agree on row count, version count, and reclaimable bytes; freed bytes stay zero; repeated cleanup and storage post-state are identical; and no repository artifact appears"
  - id: AC-4
    when: "a cleanup subprocess returns nonzero or malformed output, cannot launch, times out, or the direct scenario raises an expected execution or parsing exception"
    then: "readiness returns one bounded installed_golden_cleanup_poststate FAIL row with one concrete recovery diagnostic and no uncaught traceback"
  - id: AC-5
    when: "the focused checks, gate-inventory, public-safety, full non-network suite, lint, format, type, scorecard-freshness, and exact-wheel qualification commands inspect the implementation"
    then: "each command exits zero and the exact-wheel JSON contains the executed cleanup post-state evidence row"
  - id: AC-6
    when: "the implementation diff and canonical gate inventory are inspected"
    then: "only the existing readiness owner, its two existing pytest consumers, truthful task evidence, and the two existing deterministic scorecard artifacts change; script, runner, catalog, dependency, inventory behavior, Linux/systemd, workflow, product/release documentation, adjacent scenarios, and existing gate modes remain unchanged"
  - id: AC-7
    when: "focused and release qualification run against the implementation"
    then: "all product data and generated state stay under disposable roots and no release, tag, push, package-index, GitHub, authenticated AI-client, authentication, or credential operation occurs"
out_of_scope:
  - "Changing cleanup, health, mining, storage, or public CLI behavior."
  - "Changing adjacent golden scenarios, canonical inventory behavior, Linux/systemd coverage, CI workflows, documentation, dependencies, or public gate modes."
  - "Completing or closing RELEASE-DIRECT-INSTALLED-APP-GATE or any other staged residual."
  - "Editing release bookkeeping or runner-owned finalization artifacts; task plan/backlog evidence and deterministic scorecard artifacts may change only to record the reviewed implementation honestly."
  - "Release, tag, push, publication, authenticated provider-client, authentication, credential, or non-disposable product-data operations."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task changes which owner directly executes a release-blocking installed-process storage post-state scenario and must preserve fail-closed evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact-wheel gate must directly execute cleanup post-state and emit a dedicated evidence row."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The cleanup fixture and scenario body must have one release-gate owner while pytest remains a thin consumer and is deselected from the transitional installed suite."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The moved scenario must preserve every cleanup, health, idempotence, storage, and repository-artifact post-state assertion."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Every incomplete, malformed, failed, timed-out, or exceptional direct execution must fail readiness closed with bounded recovery evidence."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "All required focused, repository-quality, freshness, inventory, safety, and exact-wheel qualification evidence must remain green."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "No adjacent release, inventory, workflow, documentation, platform, dependency, scenario, or public-mode surface may change."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "Qualification must remain disposable, credential-free, local, and non-publishing."
      source: "current backlog contract AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "direct installed cleanup post-state gate"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Create one disposable cleanup fixture, execute init/mine/cleanup/health through the supplied installed command from the supplied neutral cwd, validate exact repeated post-state, and return one stable PASS or FAIL row."
  invariants:
    - id: INV-1
      statement: "The installed-golden owner continues to validate one exact wheel, its absolute console provenance, offline model cache, socket denial, credential-free environment, neutral cwd, shared timeouts, and disposable root before direct scenarios run."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "Cleanup and health JSON assertions preserve row-count stability, version and reclaimable-byte agreement, zero freed bytes, repeat idempotence, identical storage post-state, and repository-artifact absence."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "The existing source-mode pytest remains callable by name and delegates to the same scenario without retaining a second fixture or assertion body."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-4
      statement: "Existing split, import-missing, palace-argument, search-results, version, transitional pytest, inventory, Linux/systemd, workflow, documentation, and public-mode behavior remains unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-5
      statement: "No release gate invokes external AI clients, authentication, credentials, tags, pushes, GitHub mutation, package-index mutation, or non-disposable product data."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "The helper could still import or execute the pytest-owned scenario, leaving release qualification dependent on the transitional pytest path."
      mitigation: "Put fixture creation, process calls, parsing, and post-state assertions in one release-gate function; let pytest only supply its existing source command/environment and assert the returned row."
    - id: RISK-2
      risk: "Malformed JSON or a launch/timeout exception could bypass ordinary row evaluation and abort readiness without bounded evidence."
      mitigation: "Reuse _run_installed_cli and its timeout/launch conversion, catch only expected parsing/filesystem failures at the scenario boundary, and normalize every mismatch into one stable fail row with a concrete rerun command."
    - id: RISK-3
      risk: "The moved direct scenario could accidentally run twice for the exact wheel or alter another scenario's sequencing."
      mitigation: "Invoke the cleanup row once beside existing direct rows, stop on its non-pass status, and add its test name only to the existing transitional pytest deselection expression."
    - id: RISK-4
      risk: "Moving test lines from pytest into scripts can stale committed scorecard metrics."
      mitigation: "Keep one canonical pytest collection, regenerate only the two existing deterministic scorecard artifacts when honest metrics change, and require --check to pass."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_cleanup_poststate_fails_closed tests/test_cli_golden_scenarios.py::test_cli_golden_cleanup_poststate -q"
      proves: "The single gate-owned scenario serves source and installed seams, preserves exact repeated cleanup/health post-state, emits one stable row, and contains nonzero, malformed, launch-error, timeout, and expected-exception failures."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-7]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel command runs the direct cleanup scenario through the installed console from the existing isolated contour and emits its executed evidence row."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-7]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The canonical gate catalog and command surfaces remain unchanged while the existing installed-golden command gains internal cleanup evidence."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The bounded readiness and pytest diff contains no private, credential-shaped, authentication, provider-client, or publication material."
      acceptance_ids: [AC-5, AC-6, AC-7]
    - id: VER-5
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the moved scenario and consumer changes without a new module or dependency."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-6
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured formatting gate accepts the three-file implementation."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-7
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts the direct scenario, subprocess injection seam, parsed JSON values, and evidence-row flow."
      acceptance_ids: [AC-4, AC-5, AC-6]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The committed scorecard matches the reviewed tree and contains no artificial duplicate test symbol."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-9
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite retains cleanup, health, golden source mode, installed readiness, adjacent scenarios, and release orchestration behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves cleanup post-state and all unrelated non-network behavior after execution ownership moves."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "The existing installed-golden registration remains canonical and no inventory behavior is added or removed."
        acceptance_ids: [AC-5, AC-6]
---

## Design Notes

- Add one `INSTALLED_CLEANUP_POSTSTATE_COMMAND` label and one `_run_installed_cleanup_poststate_scenario(command_prefix, env, scenario_root, neutral_cwd, *, repository_root, run_subprocess=subprocess.run)` beside the current direct installed scenarios. Keep all paths explicit so the function is independently callable by the gate and the thin source-mode pytest consumer.
- Create the cleanup fixture inside `scenario_root`; use a minimal representative source file sufficient for the existing `init --skip-model-download` and `mine` path. Do not copy the broad pytest `_write_fixture_project` helper or move that shared helper away from adjacent tests.
- Reuse `_run_installed_cli`, `DEFAULT_TIMEOUT`, `_installed_output_is_clean`, `_make_row`, the installed command prefix, `_installed_golden_env`, `neutral_cwd`, and the `temp_root` subtree. Add no process wrapper, environment builder, timeout, temporary-root manager, or alternate row schema.
- Execute `init`, `mine`, then two `cleanup --json` and matching `health --json` calls. Treat nonzero exit, forbidden output, missing output, malformed JSON, wrong JSON shape, missing keys, type mismatch, filesystem inspection failure, or any post-state mismatch as one `installed_golden_cleanup_poststate` failure.
- Preserve the moved assertions exactly: `cleanup.ok is True`; `rows_before == rows_after == health.total_rows`; cleanup after-values equal health storage version and reclaimable-byte values; both freed-byte values are zero; before and after version/reclaimable values agree; first and second cleanup JSON are identical; and first and second health storage objects are identical.
- Inspect repository-root artifact absence inside the direct owner with the current `.tar.gz`, `.mempalace`, and `backups` boundary. Scenario state itself must remain under the supplied disposable root. The failure detail must be sanitized by the existing row path and end with one concrete rerun of the installed-golden command; do not expose disposable absolute paths.
- Invoke the cleanup scenario once in `_run_installed_golden_wheel` after provenance and before the transitional pytest suite. Return immediately on its non-pass row, include its PASS row in the final row list, and preserve existing direct-scenario ordering unless the smallest focused test requires placing cleanup adjacent to another storage-dependent row.
- Add `not test_cli_golden_cleanup_poststate` to the existing `-k` expression. Keep `test_cli_golden_cleanup_poststate` at its current public test name, import the new helper from `_RELEASE_GATE`, build the existing source-mode env/command, call the helper with disposable paths, and assert only row status/detail.
- Extend `_stub_direct_golden_scenarios` and the existing successful installed-golden test so the cleanup row is counted, appears before the transitional suite, and its pytest name is deselected. Reuse the injected subprocess runner to test successful JSON sequences and a single parametrized failure test for nonzero, malformed JSON, launch error, timeout, and expected exception containment; do not add a second scenario implementation to tests.
- Preserve quality-scorecard freshness with the existing generator. Keep one canonical pytest collection; when honest coverage changes counted lines or functions, regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` with `python scripts/quality_scorecard.py --write`.
- Command context basis: `pyproject.toml` declares the `mempalace-code` console and pytest/Ruff/Pyright dev tools; `scripts/gate_inventory.py` owns VER-2 through VER-9 command text; `.github/workflows/ci.yml` confirms the public-safety, scorecard, format, and type commands. Commands run from the repository root. PLAN inspected metadata only and did not execute them.
- `docs/quality/incident-class-registry.yaml` is absent, so this task has no registry-matched incident-proof block.
- PLAN does not run tests, builds, release gates, verification wrappers, generated-plan validation, source verification, or finalization.
