---
slug: RELEASE-DIRECT-INSTALLED-ROLLBACK-NO-CANDIDATE
status: completed
authority: non_authoritative
goal: "Run rollback-without-candidate directly in the exact-wheel installed gate while retaining a thin source-mode pytest consumer."
risk: medium
risk_note: "The change is localized, but it moves release-blocking four-mode process and storage-state proof into direct exact-wheel orchestration and must fail closed on incomplete subprocess evidence."
files:
  - path: scripts/release_readiness_gate.py
    change: "Own the rollback no-candidate fixture and scenario, emit one direct installed PASS/FAIL row, invoke it for the exact wheel, and deselect its thin pytest consumer from the transitional suite."
  - path: tests/test_cli_golden_scenarios.py
    change: "Replace the rollback no-candidate body with a thin source-mode consumer of the release-gate-owned direct scenario."
  - path: tests/test_release_readiness_gate.py
    change: "Cover the four-mode contract, health and filesystem invariants, bounded failure classes, direct-row orchestration, sanitization, and pytest deselection."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable metrics after removing the duplicate pytest-owned body."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable metrics after removing the duplicate pytest-owned body."
acceptance:
  - id: AC-1
    when: "the exact candidate wheel installed-golden command runs from its neutral working directory"
    then: "it executes rollback without a candidate through the absolute installed console and emits one executed installed_golden_rollback_no_candidate PASS or FAIL evidence row"
  - id: AC-2
    when: "the rollback no-candidate scenario is exercised through focused source-mode and installed-gate checks"
    then: "one release-gate-owned fixture and scenario body serve both paths, the pytest test only consumes the returned row, and the transitional installed pytest command deselects that test"
  - id: AC-3
    when: "dry-run separate-stream, dry-run merged-stream, live separate-stream, and live merged-stream rollback cases run against a one-version disposable palace"
    then: "each case preserves the existing ordered summary, three separated delimiters, mode-specific exit status and active stream, recovery command, and absence of restore or rebuild output"
  - id: AC-4
    when: "health is sampled before and after every rollback mode and the repository root is inspected"
    then: "every mode preserves the total_rows, current_version, and storage.version_count tuple and no .mempalace, backups, or tar archive artifact appears at the repository root"
  - id: AC-5
    when: "a subprocess has a nonzero or unexpected exit, semantic output is missing or reordered, the inactive stream is nonempty, health JSON is malformed, launch or timeout fails, or repository inspection fails"
    then: "the direct scenario returns one bounded sanitized installed_golden_rollback_no_candidate FAIL row containing exactly one concrete installed-golden rerun command and no uncaught traceback"
  - id: AC-6
    when: "focused behavior, gate inventory, public safety, full non-network pytest, Ruff lint and format, Pyright, scorecard freshness, and exact-wheel qualification commands inspect the implementation"
    then: "each command exits zero and exact-wheel JSON contains the executed rollback no-candidate evidence row"
  - id: AC-7
    when: "the implementation diff and qualification effects are inspected"
    then: "only the existing readiness owner, its two existing pytest consumers, truthful plan evidence, and existing deterministic scorecard artifacts change; all state stays disposable and no adjacent repair, watcher, inventory, Linux workflow, product documentation, dependency, public mode, release, push, publication, authenticated AI-client, credential, or non-disposable product-data action occurs"
out_of_scope:
  - "Changing repair, rollback, cleanup, health, mining, storage, watcher, systemd, or public CLI behavior."
  - "Changing adjacent golden scenarios, canonical inventory behavior, Linux coverage, CI workflows, product or release documentation, dependencies, or public gate modes."
  - "Completing or closing RELEASE-DIRECT-INSTALLED-APP-GATE or any other staged residual."
  - "Editing backlog metadata or runner-owned finalization artifacts; deterministic scorecard artifacts may change only to record the reviewed implementation honestly."
  - "Release, tag, push, publication, authenticated provider-client, authentication, credential, or non-disposable product-data operations."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task changes which owner directly executes a release-blocking installed-process recovery scenario and must preserve fail-closed four-mode evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact-wheel installed gate directly executes rollback without a candidate and emits one dedicated evidence row."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The scenario fixture and body have one release-gate owner while pytest remains a deselected thin consumer."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "All four dry-run/live and separate/merged stream modes preserve their ordered output and no-rebuild contracts."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Every mode leaves the palace health tuple and repository-root artifact boundary unchanged."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Every specified process, output, health, timeout, launch, and filesystem failure returns one bounded sanitized row with one rerun command."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "All focused, repository-quality, freshness, inventory, safety, and exact-wheel qualification evidence remains green."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "The implementation remains narrow, disposable, credential-free, local, non-publishing, and independent of the broader installed-app residual."
      source: "current backlog contract AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "direct installed rollback no-candidate gate"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Build one disposable single-version palace, run the four rollback modes through the supplied installed console from the supplied neutral cwd, validate output and unchanged health, and return one stable PASS or FAIL row."
  invariants:
    - id: INV-1
      statement: "The installed-golden owner continues to validate one exact wheel, absolute console provenance, offline model cache, socket denial, credential-free environment, neutral cwd, shared timeout, and disposable root before direct scenarios run."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "Dry-run exits zero on stdout, live mode exits one on stderr, merged mode places output on stdout, and every case keeps marker ordering, delimiter shape, recovery guidance, and no-rebuild output unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "The health tuple total_rows, current_version, and storage.version_count remains identical after each mode and repository-root artifact absence remains enforced."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-4
      statement: "The existing source-mode pytest remains callable by name and delegates to the release-gate scenario without retaining a second fixture, loop, parser, or assertion body."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-5
      statement: "Existing cleanup, split, import-missing, palace-argument, search-results, version, transitional pytest, inventory, watcher, Linux/systemd, workflow, documentation, and public-mode behavior remains unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-6
      statement: "No release gate invokes external AI clients, authentication, credentials, tags, pushes, publication, package-index mutation, or non-disposable product data."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "The helper could still import or execute the pytest-owned body, leaving exact-wheel qualification dependent on transitional pytest ownership."
      mitigation: "Put fixture creation, process execution, output parsing, health checks, and filesystem inspection in one release-gate function; let pytest only supply its source command/environment and assert the row."
    - id: RISK-2
      risk: "Adding merged-stream support could change existing callers of the shared installed-process helper."
      mitigation: "Extend the existing helper with a default-preserving merge option and cover both capture shapes while leaving every current call unchanged."
    - id: RISK-3
      risk: "A partial process, malformed health payload, missing marker, or local path in diagnostics could escape as an exception or ambiguous evidence."
      mitigation: "Reuse launch/timeout conversion and row sanitization, validate one condition at a time, catch only expected parsing and filesystem failures, and append exactly one canonical rerun command."
    - id: RISK-4
      risk: "The scenario could execute twice for the exact wheel or shift an adjacent direct scenario."
      mitigation: "Invoke it once beside existing direct rows, stop on its non-pass row, return its PASS row once, and add only its test name to the existing transitional pytest deselection expression."
    - id: RISK-5
      risk: "Moving test lines into scripts can stale committed scorecard metrics."
      mitigation: "Regenerate only the two existing deterministic scorecard artifacts and require their check command to pass."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_rollback_no_candidate_fails_closed tests/test_cli_golden_scenarios.py::test_cli_golden_rollback_no_candidate_output -q"
      proves: "The single gate-owned scenario serves source and installed seams, preserves all four output and health contracts, and contains nonzero, marker, stream, malformed-health, launch, timeout, and filesystem failures in one stable row."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-7]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel command runs the direct rollback scenario through the installed console from the existing isolated contour and emits its executed evidence row."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The canonical gate catalog and command surfaces remain unchanged while the existing installed-golden command gains internal rollback evidence."
      acceptance_ids: [AC-6, AC-7]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The bounded readiness and pytest diff contains no private, credential-shaped, authentication, provider-client, or publication material."
      acceptance_ids: [AC-6, AC-7]
    - id: VER-5
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the moved scenario and consumer changes without a new module or dependency."
      acceptance_ids: [AC-6, AC-7]
    - id: VER-6
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured formatting gate accepts the three implementation files."
      acceptance_ids: [AC-6, AC-7]
    - id: VER-7
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts the direct scenario, merged-stream option, parsed health tuple, and evidence-row flow."
      acceptance_ids: [AC-5, AC-6, AC-7]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The committed scorecard matches the reviewed tree after the duplicate scenario body is removed."
      acceptance_ids: [AC-2, AC-6, AC-7]
    - id: VER-9
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite retains rollback, repair, health, golden source mode, installed readiness, adjacent scenarios, and unrelated behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves rollback output, recovery, health, and all unrelated non-network behavior after execution ownership moves."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "The existing installed-golden registration remains canonical and no inventory behavior is added or removed."
        acceptance_ids: [AC-6, AC-7]
---

## Design Notes

- Add one `INSTALLED_ROLLBACK_NO_CANDIDATE_COMMAND` label and one `_run_installed_rollback_no_candidate_scenario(command_prefix, env, scenario_root, neutral_cwd, *, repository_root, run_subprocess=subprocess.run)` beside the current direct installed scenarios. Keep every path explicit so the gate and thin source-mode consumer call the same owner.
- Build a minimal representative project inside `scenario_root`, then execute `init --skip-model-download`, `mine`, and `cleanup --unsafe-now --json` through `_run_installed_cli`. Require the existing success markers and cleanup `version_count_after == 1` before rollback proof begins.
- Extend `_run_installed_cli` only as needed with a default-false merged-stream option. Continue to route all calls through `_run_golden_subprocess`, `DEFAULT_TIMEOUT`, the supplied command prefix/environment, and `neutral_cwd`; preserve every current caller's separate-stream behavior.
- Parse health through the same installed process before rollback and after every mode. Require an object with integer `total_rows`, `current_version`, and `storage.version_count`, and compare the exact tuple to the baseline.
- Run exactly four cases in stable order: dry-run separate streams, dry-run merged streams, live separate streams, and live merged streams. Dry-run requires exit 0 and active stdout; live requires exit 1 and active stderr; merged output is active stdout. Separate mode requires an empty inactive stream.
- Preserve the moved semantic assertions: ordered title, mode, no-candidate, mutation, exit-status, and recovery markers; exactly three 55-character separators with no adjacent pair and a final separator; and absence of `Extracting drawers`, `Backing up to`, and `Rebuilding palace`.
- Treat unexpected exit, forbidden output, missing or reordered marker, wrong separator shape, inactive-stream output, malformed or wrong-shaped health JSON, launch error, timeout, or repository-root inspection failure as one `installed_golden_rollback_no_candidate` failure. Route the detail through `_make_row` sanitization and include exactly one `rerun: ${INSTALLED_GOLDEN_COMMAND}` recovery string.
- Inspect only the established repository-root artifact boundary: names ending in `.tar.gz` plus `.mempalace` and `backups`. Keep all scenario state under the supplied disposable root and expose no disposable absolute path in row detail.
- Invoke the rollback helper once in `_run_installed_golden_wheel` after provenance and alongside current direct installed scenarios. Stop immediately on its non-pass row, include its PASS row once in final output, and preserve adjacent scenario ordering.
- Add `not test_cli_golden_rollback_no_candidate_output` to the existing transitional `-k` expression. Keep that pytest name, import the release-gate helper, build the existing source-mode env/command, call the helper with disposable paths, and assert only row status/detail.
- Extend `_stub_direct_golden_scenarios` and the existing successful exact-wheel orchestration test so the new row is counted, emitted before the transitional suite, and its pytest consumer is deselected. Add one parametrized focused test covering the four success modes and every AC-5 failure class through the injected subprocess runner; keep expected call order, cwd, environment, and timeout explicit.
- Preserve scorecard freshness with the existing generator. Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` when the honest function or line metrics change.
- Command context basis: `pyproject.toml` declares the `mempalace-code` console plus pytest, Ruff, and Pyright development tools; the existing cleanup direct-gate plan records the current required inventory, safety, scorecard, full-suite, and exact-wheel command forms. Commands run from the repository root. PLAN inspected metadata only and did not execute them.
- Filename discovery found no `docs/quality/incident-class-registry.yaml`, so this task has no registry-matched incident-proof block.
- PLAN does not run tests, builds, release gates, verification wrappers, generated-plan validation, source verification, or runner finalization.
