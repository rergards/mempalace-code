---
slug: RELEASE-DIRECT-INSTALLED-PATH-CONTRACTS
status: completed
authority: non_authoritative
goal: "Move init, mine-all, diary recovery, and update-refusal contracts into the existing direct exact-wheel release owner while retaining one thin source consumer."
risk: medium
risk_note: "The change is confined to release qualification, but a false PASS could admit an exact wheel that mutates update state, leaks artifacts, or bypasses installed-console provenance."
files:
  - path: scripts/release_readiness_gate.py
    change: "Own and directly execute the path-contract scenario in the exact-wheel contour, emit one bounded row, and add only its thin source test to transitional pytest deselection."
  - path: tests/test_cli_golden_scenarios.py
    change: "Replace the existing path-contract body with a thin source-mode consumer of the release-owned scenario while preserving the test name."
  - path: tests/test_release_readiness_gate.py
    change: "Cover direct orchestration, success and fail-closed post-state, row ordering, cleanup, and the exact selector delta."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable scorecard after scenario ownership and test structure change."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable scorecard after scenario ownership and test structure change."
acceptance:
  - id: AC-1
    when: "the installed-golden command receives one exact candidate wheel and starts the path-contract scenario from its neutral cwd"
    then: "every scenario subprocess uses only the wheel's absolute mempalace-code console inside the existing offline, credential-free, socket-denied environment"
  - id: AC-2
    when: "the direct scenario runs init, mine-all dry-run, diary write and recovery search, then the three update confirmation paths"
    then: "init creates only mempalace.yaml, mine-all discovers the initialized project without mutation, diary acknowledgement is bounded while search returns the full entry, and update apply plus scheduler install/remove each refuse without --yes"
  - id: AC-3
    when: "a scenario command fails, emits malformed or forbidden output, violates semantic post-state, records a socket attempt, or changes repository or non-disposable state"
    then: "the installed gate returns one bounded sanitized FAIL row with one recovery command, preserves zero update artifacts after refusals, and leaves no repository or non-disposable artifact"
  - id: AC-4
    when: "the named source pytest and exact-wheel orchestration are inspected and exercised"
    then: "test_installed_cli_paths_are_self_consistent_and_reconcilable delegates to the single release-owned scenario, its exact negative selector clause is the only transitional pytest selector addition, and the direct row executes once"
  - id: AC-5
    when: "focused source evidence, the full non-network suite, static/public gates, a fresh exact-wheel run, and independent Rule Zero, correctness, and security reviews are collected for one implementation"
    then: "all required outputs and review verdicts pass, the exact-wheel JSON contains the dedicated path-contract PASS row, and qualification performs no publication, remote mutation, credential access, or AI-client invocation"
out_of_scope:
  - "Blank diary inputs, recovery matrices, non-regular sources, fixture shape, inventory expansion, Linux hosted update behavior, and adjacent scenarios."
  - "Changing init, mine-all, diary, search, updater, or scheduler product behavior."
  - "Adding a second runner, helper framework, gate row, dependency, service, state owner, public interface, or architecture boundary."
  - "Editing backlog metadata or performing staging, commit, push, tag, release, publication, remote mutation, credential access, authentication, or external AI-client invocation."
contract_policy:
  flow: full_spdd
  reason: "This standard pre-release task moves ownership of release-blocking installed-process mutation and refusal evidence under strict isolation and cleanup contracts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The exact candidate wheel console must execute the scenario from the existing neutral, offline, credential-free, socket-denied contour."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The moved scenario must preserve init isolation, mine-all discovery, bounded diary acknowledgement, diary recovery, and all three update confirmation refusals."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Every mutation and refusal must have semantic post-state, bounded public-safe output, disposable artifacts, and zero repository drift."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The stable source test must become a thin consumer and only its exact name may be added to transitional installed pytest deselection."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused, regression, static/public, fresh exact-wheel, and independent review evidence must qualify the same bounded implementation."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "direct installed path-contract qualification"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Run the complete init, discovery, diary recovery, and update-refusal scenario through the supplied exact installed console and return one sanitized PASS or FAIL row."
  invariants:
    - id: INV-1
      statement: "Exact-wheel installation, absolute console and module provenance, offline model cache, socket denial, credential-free environment, neutral cwd, shared timeouts, and outer disposable root remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "Init still avoids implicit Git and pyproject creation; mine-all stays dry-run; diary content remains recoverable without full acknowledgement echo; update actions still require explicit --yes."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-3
      statement: "test_installed_cli_paths_are_self_consistent_and_reconcilable retains its name and contains no copied scenario command or post-state body."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-4
      statement: "All adjacent direct rows, transitional pytest clauses and cases, fixture-shape coverage, inventory, Linux behavior, product code, dependencies, and release modes remain unchanged except for the one required deselection clause."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-5
      statement: "Qualification performs no update apply, scheduler install or removal, external AI-client call, authentication, credential access, release, publication, remote mutation, or non-disposable product-data mutation."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "The original pytest body could remain beside the release-gate implementation, creating duplicate owners and execution."
      mitigation: "Move the complete body, leave one helper call plus row assertions, add the exact selector clause, and assert one direct invocation and row."
    - id: RISK-2
      risk: "A shallow update refusal check could accept return code 2 while an updater or scheduler artifact was created."
      mitigation: "Require the confirmation-stage JSON contract and a content-sensitive recursive snapshot before and after all three refusals."
    - id: RISK-3
      risk: "A permissive init, discovery, or diary assertion could pass despite implicit project files, dry-run mutation, unbounded acknowledgement, or unrecoverable content."
      mitigation: "Retain the existing command outputs and add explicit path and semantic snapshots around each boundary."
    - id: RISK-4
      risk: "Failure detail or moved test metrics could expose transient paths or stale the deterministic scorecard."
      mitigation: "Reuse bounded sanitization and forbidden-output checks, assert no disposable path in FAIL detail, and regenerate only the two scorecard artifacts."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_path_contract_scenario_fails_closed tests/test_release_readiness_gate.py::test_installed_golden_uses_watch_extra_provenance_neutral_cwd_and_safe_env tests/test_cli_golden_scenarios.py::test_installed_cli_paths_are_self_consistent_and_reconcilable -q"
      proves: "One release-owned scenario serves direct and source seams, preserves success and hostile post-state predicates, and is directly invoked and deselected exactly once."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical fresh exact-wheel command executes the dedicated path-contract row with installed provenance, neutral cwd, offline socket denial, semantic post-state, and cleanup evidence."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-3
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite preserves source golden, release orchestration, init, mining, diary, updater, scheduler, and unrelated behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The scenario remains inside the existing installed-golden gate with no inventory, command, or runner duplication."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Tracked release command declarations remain synchronized after the internal ownership move."
      acceptance_ids: [AC-5]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The bounded diff contains no private path, credential-shaped, authenticated-provider, remote-mutation, or publication material."
      acceptance_ids: [AC-1, AC-3, AC-5]
    - id: VER-7
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the moved owner and deleted duplicate without a new module or dependency."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-8
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the bounded implementation and tests."
      acceptance_ids: [AC-5]
    - id: VER-9
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts subprocess results, parsed refusal JSON, path snapshots, and evidence-row flow."
      acceptance_ids: [AC-2, AC-3, AC-5]
    - id: VER-10
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict slice remains green across the ownership move."
      acceptance_ids: [AC-5]
    - id: VER-11
      owner: configured_runner
      command: "python scripts/architecture_guard.py --root ."
      proves: "The implementation introduces no service, store, helper framework, durable contract, or ownership boundary."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-12
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The deterministic scorecard matches the reviewed tree after the scenario body moves and duplicate installed collection is removed."
      acceptance_ids: [AC-4, AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves every moved path contract and unrelated non-network behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "No second gate command, inventory row, public runner, or adjacent scenario registration is introduced."
        acceptance_ids: [AC-4, AC-5]
---

## Design Notes

- Rule Zero selects `scripts/release_readiness_gate.py`, which already owns exact-wheel installation, provenance, environment isolation, socket denial, direct scenario rows, shared fixture creation, bounded evidence, and transitional pytest. Moving the current body into this owner changes three code/test files and rolls back as localized hunks. Deleting the source test loses source-mode evidence; retaining pytest as installed owner misses the direct gate; a new module, runner, or framework creates a parallel owner.
- Add one stable command label and one `_run_installed_path_contract_scenario(command_prefix, env, scenario_root, neutral_cwd, *, repository_root, network_attempts=None, run_subprocess=subprocess.run)` beside the current direct scenarios. Reuse `_write_fixture_project`, `_run_installed_cli`, `_run_golden_subprocess`, `_installed_output_is_clean`, `_make_row`, shared timeouts, repository artifact snapshots, the supplied console prefix, and the outer disposable root.
- Move the current sequence and predicates without retaining a copy: initialize the shared fixture; require only `mempalace.yaml` and absence of `.git` and `pyproject.toml`; run `mine-all --dry-run`, require discovery of `initialized-only`, and prove no palace or project mutation; write the long diary entry, require the bounded acknowledgement fields without full entry echo, then search the bounded prefix and require the complete stored entry.
- Before update commands, capture a recursive content-sensitive snapshot of the scenario root and repository boundary. Run update apply, scheduler install, and scheduler remove without `--yes`; each must exit 2, keep stderr empty, emit clean JSON with `ok=false`, `stage=confirmation`, `exit_code=2`, and a recovery command ending in `--yes --json`. Require byte-equivalent semantic state after each refusal, zero socket attempts, and no repository drift.
- Apply `_installed_output_is_clean` to every subprocess. Convert expected launch, timeout, JSON, filesystem, output, provenance, and post-state failures into one `installed_golden_path_contracts` FAIL row. Sanitize and cap detail through the established row contract, exclude transient absolute paths and forbidden markers, and include exactly one `rerun: python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json` recovery action.
- Invoke the scenario once after exact-wheel provenance and prerequisite environment setup, fail fast on its non-pass result, and include its PASS row in the existing ordered list. Add only `and not test_installed_cli_paths_are_self_consistent_and_reconcilable` to the transitional pytest `-k` expression.
- Keep `test_installed_cli_paths_are_self_consistent_and_reconcilable` at its current name. Bind it through the existing `runpy.run_path` owner seam, construct the source environment and disposable paths, call the release-owned helper, and assert its stable row ID/status/detail. Remove the local command and post-state body; retain shared helpers still consumed elsewhere.
- Extend `_stub_direct_golden_scenarios` and the successful exact-wheel orchestration test with the new row, count, order, absolute console, neutral cwd, socket-log argument, and exact selector expectation. Add one injected-runner failure matrix for nonzero/timeout results, malformed refusal JSON, wrong confirmation contract, forbidden or unbounded output, implicit init artifacts, dry-run mutation, diary echo or failed recovery, update residue, socket attempts, repository drift, and filesystem-evaluation failure. Tests may model boundaries but must not reproduce the scenario body.
- Preserve all adjacent direct scenario ordering and behavior, transitional cases and clauses, fixture-shape coverage, inventory, Linux hosted update contour, product modules, release docs, dependencies, and gate modes. This residual creates no architecture delta, runtime routing change, migration, persisted contract, or incident-class surface.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` if the canonical writer reports changed metrics. Retain no generated wheel, environment, palace, scheduler, or smoke artifact.
- Cheapest decisive falsifier: VER-1 must show one thin source consumer, one direct orchestration call, one exact deselection clause, and fail-closed semantic snapshots. Any copied body, duplicate execution, shallow return-code-only refusal, wrong cwd/console, or leaked artifact fails before fresh-wheel qualification.
- Command context basis: `pyproject.toml` declares Python 3.11+, the three console scripts, pytest, Ruff, Pyright, and the watch extra; `docs/quality/scorecard.json`, `.claude/skills/verify/INSTRUCTIONS.md`, `scripts/gate_inventory.py`, and the existing direct-installed plans expose the exact configured full-suite, static/public, scorecard, and exact-wheel command forms. Commands run from the repository root. PLAN inspected metadata only and did not execute them.
- Filename discovery found no `docs/quality/incident-class-registry.yaml`; this release-test ownership move changes no runtime routing or registry-class surface, so no `incident_proof` block applies.
- Independent Rule Zero, correctness, and security reviews are runner-owned next-phase evidence for AC-5. PLAN does not represent them as fake shell rows and does not run tests, builds, gates, wrappers, exact-wheel qualification, reviews, generated-plan validation, source verification, Git finalization, or publication.
