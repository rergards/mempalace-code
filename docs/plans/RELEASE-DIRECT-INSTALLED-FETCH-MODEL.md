---
slug: RELEASE-DIRECT-INSTALLED-FETCH-MODEL
status: completed
authority: non_authoritative
goal: "Make the exact-wheel installed release gate own and directly execute the fetch-model golden scenario while source pytest remains its thin consumer."
risk: medium
risk_note: "The ownership move is localized, but it changes release-blocking subprocess evidence across cached, local, forced, offline-failure, and retry paths and must preserve isolation and fail-closed output."
files:
  - path: scripts/release_readiness_gate.py
    change: "Own the fetch-model scenario, execute it directly through the exact installed wheel before transitional pytest, emit one bounded evidence row, and deselect the thin source consumer from the transitional suite."
  - path: tests/test_cli_golden_scenarios.py
    change: "Replace the fetch-model scenario body with a thin source-mode consumer of the release-gate-owned scenario without changing the test name or source fixture environment."
  - path: tests/test_release_readiness_gate.py
    change: "Cover the direct scenario success and failure matrix, exact-wheel orchestration, row ordering and propagation, shared isolation, and transitional pytest deselection."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable metrics if moving the scenario changes measured script or test metrics."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable metrics if moving the scenario changes measured script or test metrics."
acceptance:
  - id: AC-1
    when: "the exact candidate wheel installed-golden command runs with a validated MiniLM cache from its neutral working directory"
    then: "one production-owned direct scenario proves the cached default model, explicit local model, forced local refresh, offline missing-model failure without false Done output or residual target, successful retry, unchanged source cache and repository boundary, exact-wheel provenance, bounded output, and zero socket attempts"
  - id: AC-2
    when: "the source fetch-model pytest and exact-wheel installed gate exercise fetch-model qualification"
    then: "both consume the one release-gate-owned scenario, the source pytest contains only setup plus returned-row assertion, and the transitional installed pytest selection excludes that source test so no duplicate scenario or second runner executes"
  - id: AC-3
    when: "focused source checks, exact-wheel qualification, the full non-network regression, static gates, implementation diff checks, and independent Rule Zero and correctness reviews complete"
    then: "all required evidence passes; every failure path emits one bounded installed_golden_fetch_model row with one concrete retry command; and no push, tag, release, publication, credential access, authentication, external AI-client invocation, or non-disposable product-data action occurs"
out_of_scope:
  - "Changing fetch-model product behavior, model selection, model-cache layout, or fixture shape."
  - "Changing watcher signals, the composite workflow, gate inventory, Linux update behavior, dependencies, public release modes, or adjacent golden scenarios."
  - "Adding a helper module, second scenario implementation, second runner, new gate mode, service, store, or durable contract."
  - "Editing backlog metadata or runner-owned finalization artifacts; deterministic scorecard files may change only to reflect the implementation."
  - "Push, tag, release, publication, credential or authentication access, external AI-client invocation, and non-disposable product-data operations."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task moves release-blocking provider and subprocess evidence into the direct exact-wheel owner under credential-free and offline execution constraints."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact-wheel installed gate must directly execute the complete fetch-model success, failure, retry, isolation, provenance, and network-guard scenario."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The release gate must be the single scenario owner while the named source pytest remains a thin consumer and is excluded from transitional installed pytest."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Focused, exact-wheel, non-network, static, diff, Rule Zero, and correctness evidence must pass inside the non-publishing and credential-free boundary."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "direct installed fetch-model golden gate"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Run one canonical fetch-model scenario through a supplied installed or source command prefix and return one stable PASS or sanitized FAIL row."
  invariants:
    - id: INV-1
      statement: "The installed-golden owner continues to validate one exact wheel, its absolute console and module provenance, the existing model-cache preflight, credential-free environment, socket guard, neutral cwd, shared subprocess timeouts, and disposable root before the scenario runs."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "Cached default, explicit local, forced local, offline missing-target, and successful retry behavior retain their current output, exit-code, target-state, and socket-attempt predicates, with source-cache immutability proven by a content-sensitive and race-aware comparison, the successful-retry target proven to still exist with unchanged expected content after the retry completes, and pre-existing repository artifacts compared by semantic recursive post-state (path, kind, symlink target, and file content)."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "The existing source pytest remains callable by name, uses the existing fake-package and installed-provenance setup, delegates to the shared scenario, and retains no second transition or assertion body."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-4
      statement: "Watcher signals, workflow composition, fixture shape, inventory, Linux update behavior, adjacent scenarios, product CLI behavior, and public release modes remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-5
      statement: "Release qualification never reads credentials, authenticates, invokes external AI clients, mutates Git history or remotes, publishes artifacts, or writes product data outside disposable roots."
      applies_to: ["scripts/release_readiness_gate.py"]
    - id: INV-6
      statement: "The scenario's disposable cache copy and local-model fixture select the snapshot directory named by the validated cache's refs/main revision — never lexical iteration order — and every copied or compared tree explicitly rejects or safely snapshots symlinks by their literal link target, failing closed when either guarantee cannot be established."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "Copying the pytest body into the release gate could leave two scenario authorities that drift."
      mitigation: "Move the whole transition and predicate sequence into one release-gate function, delete the pytest-owned body, and keep pytest limited to environment setup, one function call, and row assertion."
    - id: RISK-2
      risk: "The direct gate could execute the scenario and then execute the same source test again inside transitional pytest."
      mitigation: "Invoke the scenario once before the transitional suite and add its stable test name to the existing deselection expression with orchestration coverage for the exact command."
    - id: RISK-3
      risk: "A missing cache, subprocess failure, unsafe output, residual target, filesystem error, repository drift, or socket attempt could escape as an exception or ambiguous release result."
      mitigation: "Reuse the existing cache preflight, subprocess and socket seams, normalize expected failures into one bounded row, sanitize transient paths and forbidden output, and append exactly one canonical rerun command."
    - id: RISK-4
      risk: "Moving behavior between script and tests can stale deterministic scorecard metrics."
      mitigation: "Regenerate only the two existing scorecard artifacts when their canonical freshness check requires it."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_fetch_model_scenario_fails_closed tests/test_cli_golden_scenarios.py::test_cli_golden_fetch_model_buffering_failure_and_retry -q"
      proves: "The single gate-owned scenario serves source and direct seams, covers happy paths plus the fail-closed matrix, preserves isolation, and emits the stable row and recovery detail."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel command uses the installed console from a neutral cwd, directly executes fetch-model under the existing cache, provenance, environment, output, and socket guards, and emits its evidence row."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The existing installed-golden registration and canonical command remain unchanged and no parallel gate is introduced."
      acceptance_ids: [AC-2, AC-3]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Tracked release command declarations remain synchronized after the internal ownership move."
      acceptance_ids: [AC-3]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The bounded implementation and evidence diff contains no private, credential-shaped, authentication, provider-client, or publication material."
      acceptance_ids: [AC-3]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The canonical lint gate accepts the moved owner and deleted duplicate without a new module or dependency."
      acceptance_ids: [AC-2, AC-3]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The canonical format gate accepts the release-gate and source-test ownership edits."
      acceptance_ids: [AC-2, AC-3]
    - id: VER-8
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The canonical type gate accepts the scenario, injectable subprocess seam, environment maps, path snapshots, and evidence-row flow."
      acceptance_ids: [AC-1, AC-3]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The committed scorecard matches the reviewed tree after the scenario body moves from pytest into the script owner."
      acceptance_ids: [AC-2, AC-3]
    - id: VER-10
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full canonical regression preserves source fetch-model behavior, installed readiness orchestration, adjacent scenarios, and unrelated non-network contracts."
      acceptance_ids: [AC-1, AC-2, AC-3]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves fetch-model behavior and all unrelated non-network behavior after execution ownership moves."
        acceptance_ids: [AC-1, AC-2, AC-3]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "The direct scenario remains inside the existing installed-golden owner with no inventory, runner, or command-surface duplication."
        acceptance_ids: [AC-2, AC-3]
---

## Design Notes

- Rule Zero outcome: extend `scripts/release_readiness_gate.py`, the existing exact-wheel installed-golden owner. Move the test's transition sequence and predicates into one `_run_installed_fetch_model_scenario` and delete the original body. A new module, runner, mode, or service adds ownership and lifecycle cost without satisfying any additional acceptance criterion.
- Reuse `_validated_model_cache`, `_installed_golden_env`, `_run_installed_cli`, `_run_golden_subprocess`, `_installed_output_is_clean`, `_make_row`, `DEFAULT_TIMEOUT`, `INSTALLED_GOLDEN_COMMAND`, the exact installed console, neutral cwd, socket-attempt log, temporary root, and repository-root artifact snapshot. Do not add another environment builder, cache preflight, subprocess wrapper, socket guard, row schema, or scenario runner.
- Give the shared scenario a command prefix, environment, scenario root, neutral cwd, repository root, and injectable `run_subprocess`. Source pytest supplies its existing `_CLI` and fake package environment; exact-wheel qualification supplies the absolute installed console and credential-free golden environment.
- In installed mode, copy the preflight-validated MiniLM cache into a disposable `HF_HOME`, take a content-sensitive snapshot of the source cache, and derive the local-model fixture from the snapshot directory named by the validated cache's `refs/main` revision — never from lexical iteration order — failing closed with a bounded row when that named snapshot is absent or escapes the snapshots root. Snapshot entries record path, kind, size, and a content hash for regular files, and the literal link target for symlinks; the cache copy must not follow symlinks, and any symlink that cannot be safely captured by its link target is rejected. Make the immutability comparison race-aware: detect metadata change during hashing, re-read the unstable entry, and convert unresolved instability into a bounded FAIL rather than a pass. Reading model file bytes for hashing is required; mutating the validated source cache remains forbidden. Source mode retains its existing fake sentence-transformers failure seam.
- Preserve the five ordered calls: cached default model, explicit local model, forced local refresh, missing offline target failure, and successful retry after provisioning that target. Preserve current stdout/stderr markers, return codes, absence of false `Done`, absence of residual failed target, cache existence, and empty socket-attempt evidence. Strengthen the isolation predicates to the review-blocker level: content-sensitive and race-aware source-cache equality; proof after the retry completes that the retry target still exists and its content equals the provisioned expected content; and semantic recursive post-state comparison of pre-existing repository artifacts by path, kind, symlink target, and file content — not a name-list or metadata-only comparison.
- Convert expected launch, timeout, filesystem, encoding, type, value, output, and state failures into one `installed_golden_fetch_model` FAIL row. Bound and sanitize detail, suppress forbidden subprocess markers and transient absolute paths, and end with exactly one `rerun: python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json` recovery action.
- Invoke the scenario once in `_run_installed_golden_wheel` after candidate installation, cache validation, socket-guard setup, and exact provenance succeed. Fail fast with that single row; on success retain the row in the established installed-golden result order.
- Keep `test_cli_golden_fetch_model_buffering_failure_and_retry` at its current name. Bind it to the gate function through the existing `runpy.run_path` owner seam, retain `_make_env` and `_assert_installed_cli_provenance`, and reduce the test body to one scenario call plus `row["status"]` assertion.
- Add the stable source test name to the existing transitional pytest `-k` deselection. Extend the current installed-golden orchestration test to prove the direct row runs before the transitional suite, propagates failure without launching that suite, and leaves only one fetch-model execution owner.
- Extend `tests/test_release_readiness_gate.py` with one parametrized injected-runner matrix covering cached, local, force, offline, retry, unsafe success output, residual target, source-cache content drift (including drift invisible to size-and-mtime metadata), missing or escaping `refs/main`-named snapshot selection, symlink entries in copied and compared trees, retry-target deletion and retry-target content drift after the retry, race-detected snapshot instability, recursive repository post-state drift in nested pre-existing artifacts, socket attempts, launch/timeout conversion, and expected filesystem evaluation failures. Assertions must cover row ID/status, one recovery command on failure, bounded path-free detail, neutral cwd, shared timeout, and removed `PYTHONUNBUFFERED`.
- Independent review blockers (2026-08-26) are repaired inside the one scenario owner itself, each with its hostile falsifier in the VER-1 matrix: content-sensitive and race-aware source-cache immutability; symlink reject-or-safe-snapshot policy for every copied or compared tree; `refs/main`-named snapshot selection replacing lexical order; retry-target existence-and-content proof after retry; and semantic recursive repository post-state comparison. No helper module, cache owner, gate mode, or dependency is added for these repairs.
- Preserve scorecard freshness with its existing generator. Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` when the canonical check reports changed metrics.
- Rollback is a direct reversal of the three source/test edits plus regenerated scorecard artifacts. There is no migration, compatibility shim, persisted-state change, live rollout, or public interface delta.
- Cheapest decisive falsifier: VER-1 exercises both consumers and the injected failure matrix. Any copied scenario body, missing transition, unsafe false success, unbounded failure, wrong cwd/timeout, or weakened isolation fails before exact-wheel qualification.
- Implementation diff inspection and independent Rule Zero and correctness reviews remain runner-owned phase evidence. They must confirm only the five declared paths change, one scenario owner remains, and no forbidden release or credential action appears; they are not represented as fake shell verification rows.
- Command context basis: `pyproject.toml` declares Python 3.11+, pytest, Ruff, and Pyright; `scripts/gate_inventory.py` owns the exact full-suite, inventory, docs-drift, public-safety, scorecard, type, and exact-wheel command forms; `.github/workflows/ci.yml` runs the exact-wheel command after building one wheel and provisioning the MiniLM cache. Commands run from the repository root. PLAN inspected metadata only and did not execute them.
- Filename discovery found no `docs/quality/incident-class-registry.yaml`, so this task has no registry-matched `incident_proof` block.
- PLAN does not run tests, builds, verification wrappers, exact-wheel qualification, independent reviews, generated-plan validation, source verification, Git finalization, or publication.
