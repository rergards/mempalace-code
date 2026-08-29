---
slug: RELEASE-DIRECT-INSTALLED-WORKFLOW-HAPPY-PATH
status: completed
authority: non_authoritative
goal: "Move the composite CLI happy path into the existing direct exact-wheel release owner while retaining one thin source pytest consumer."
risk: medium
risk_note: "The change is localized to release qualification, but it moves a multi-process storage and watcher scenario across owners and must preserve semantic post-state, isolation, and fail-closed cleanup."
files:
  - path: scripts/release_readiness_gate.py
    change: "Own and directly execute the composite init/mine/compress/status/search/read/export/import/backup/restore/health/unsafe-restore/watch scenario in the exact-wheel environment, emit one bounded row, and deselect its thin pytest consumer."
  - path: tests/test_cli_golden_scenarios.py
    change: "Replace the composite scenario body with a thin source-mode consumer of the release-gate-owned scenario while preserving its public test name."
  - path: tests/test_release_readiness_gate.py
    change: "Cover direct composite orchestration, semantic post-state, failure containment, cleanup, exact-wheel row ordering, and the exact transitional pytest selector change."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable metrics after scenario ownership and collected test structure change."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable metrics after scenario ownership and collected test structure change."
acceptance:
  - id: AC-1
    when: "the installed-golden command receives one exact candidate wheel and runs from its disposable neutral working directory"
    then: "the dedicated composite row invokes only the wheel's absolute mempalace-code console inside the existing offline, credential-free, socket-denied environment and rejects provenance or isolation drift"
  - id: AC-2
    when: "the composite row executes its success and unsafe-archive branches"
    then: "observable output and post-state prove init, mine, correct compress dry-run totals, no-op retry without backup growth, status, search/read, export/import, backup/restore, healthy restored storage, unsafe archive refusal without traversal, and one watch-on-save re-mine cycle"
  - id: AC-3
    when: "any composite step fails, hangs, emits malformed or forbidden output, leaves a watcher alive, records a socket attempt, or changes repository or non-disposable state"
    then: "the watcher and reader are bounded and owned cleanup completes, readiness returns one sanitized public-safe FAIL row with one recovery command, and no repository or non-disposable artifact remains"
  - id: AC-4
    when: "the named source pytest and the exact-wheel installed-golden command are exercised"
    then: "test_cli_golden_workflow_happy_path delegates to the one release-owned scenario, the transitional pytest selector adds only its exact negative clause, and output proves the composite body executes once per path"
  - id: AC-5
    when: "focused source evidence, full non-network regression, static/public gates, fresh exact-wheel qualification, and independent Rule Zero, correctness, and security reviews are collected"
    then: "all command outputs and review verdicts pass for the same implementation, the exact-wheel JSON contains the dedicated composite PASS row, and no release, publication, remote mutation, credential access, or AI-client invocation occurs"
out_of_scope:
  - "Diary/path behavior, recovery matrices, non-regular sources, fixture-shape contracts, inventory expansion, Linux hosted update behavior, and adjacent installed scenarios."
  - "Changing CLI, storage, backup, restore, watcher, compression, search, export/import, or health product behavior."
  - "Adding another runner, helper framework, gate row, dependency, service, persisted state owner, public interface, or architecture boundary."
  - "Editing backlog metadata or performing runner-owned staging, commit, push, tag, release, publication, source verification, or finalization."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task moves ownership of a release-blocking installed-process composite scenario and its failure/cleanup evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact candidate wheel console must execute the composite scenario from the existing neutral, offline, credential-free, socket-denied contour."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The moved scenario must retain every listed success, round-trip, no-op, unsafe-archive, and watch-on-save behavior."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Every mutation and process boundary must have semantic post-state, bounded output, owned cleanup, and disposable artifact proof."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The source pytest must become a thin consumer of the release-owned scenario and only its exact name may be added to transitional installed pytest deselection."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused, regression, static/public, exact-wheel, and independent review evidence must qualify the same bounded implementation."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "direct installed composite workflow gate"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Run the complete composite workflow through the supplied exact installed console, validate semantic post-state and cleanup, and return one stable sanitized PASS or FAIL row."
  invariants:
    - id: INV-1
      statement: "The installed-golden owner continues to validate one exact wheel, absolute console and module provenance, watch-extra installation, offline model cache, socket denial, credential-free environment, neutral cwd, shared timeouts, and disposable roots before the composite scenario runs."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "The composite scenario preserves the current fixture content and all current command output and semantic post-state predicates, including summed compression totals, no-op backup stability, round-trip search/read, unsafe traversal refusal, and one watch re-mine cycle."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "test_cli_golden_workflow_happy_path remains callable by its existing name and contains no copied workflow, watcher, round-trip, or artifact assertion body."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-4
      statement: "All adjacent direct rows, transitional pytest cases, fixture-shape coverage, inventory, workflows, Linux behavior, product code, release documentation, and gate modes remain unchanged except for the one required deselection clause."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-5
      statement: "Qualification performs no external AI-client call, authentication, credential access, release, publication, remote mutation, or non-disposable product-data mutation."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "The composite pytest body could remain beside the release-gate implementation, creating two owners and duplicate execution."
      mitigation: "Move the whole body into one gate function, leave only row assertions in the source test, add its exact name to the existing selector, and assert one direct invocation and row."
    - id: RISK-2
      risk: "A late workflow failure or watch timeout could leak a child process, reader thread, or disposable path and escape the evidence-row contract."
      mitigation: "Reuse bounded subprocess helpers, keep unconditional watcher and reader cleanup around the direct scenario, snapshot repository artifacts, and normalize expected execution, parsing, and filesystem failures into one sanitized row."
    - id: RISK-3
      risk: "A shallow success check could miss lossy compression totals, backup growth, broken round trips, unsafe archive extraction, or stale watcher state."
      mitigation: "Move the existing semantic predicates intact and add focused hostile seams for incorrect totals, altered post-state, traversal output, network attempts, forbidden output, and incomplete watcher cleanup."
    - id: RISK-4
      risk: "Moving source and test lines can stale deterministic scorecard metrics."
      mitigation: "Regenerate only the two existing scorecard artifacts when the canonical writer reports changed metrics and require the scorecard check."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_workflow_happy_path_fails_closed tests/test_release_readiness_gate.py::test_installed_golden_uses_watch_extra_provenance_neutral_cwd_and_safe_env tests/test_cli_golden_scenarios.py::test_cli_golden_workflow_happy_path -q"
      proves: "One gate-owned composite scenario serves direct and source seams, preserves the full semantic workflow, contains hostile failures and cleanup, and is invoked and deselected exactly once."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel command executes the dedicated composite row through the installed console with provenance, neutral-cwd, offline, socket-denied, semantic post-state, and cleanup evidence."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-3
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite preserves source golden behavior, release orchestration, storage round trips, watcher lifecycle, and unrelated behavior after ownership moves."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The canonical gate inventory and public command surfaces remain unchanged while the existing installed-golden command gains internal composite evidence."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The bounded diff contains no private path, credential-shaped, authenticated-provider, remote-mutation, or publication material."
      acceptance_ids: [AC-1, AC-3, AC-5]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the moved scenario without a new module, runner, dependency, or product change."
      acceptance_ids: [AC-4, AC-5]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the bounded implementation and tests."
      acceptance_ids: [AC-5]
    - id: VER-8
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts composite subprocess results, watcher lifecycle state, parsed output, and evidence-row flow."
      acceptance_ids: [AC-2, AC-3, AC-5]
    - id: VER-9
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict type slice remains green across the moved release and test ownership."
      acceptance_ids: [AC-5]
    - id: VER-10
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
        proves: "The canonical repository regression gate preserves the complete composite workflow and unrelated non-network behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "No second gate command, inventory row, public runner, or adjacent scenario registration is introduced."
        acceptance_ids: [AC-4, AC-5]
---

## Design Notes

- Rule Zero outcome: extend `scripts/release_readiness_gate.py`, which already owns exact-wheel installation, provenance, environment isolation, socket denial, direct scenario rows, shared fixture creation, and the transitional pytest subprocess. Acceptance is the existing composite behavior executed once by this owner with one thin source consumer. A new module, runner, framework, gate row, or copied body increases owners and removal cost.
- Existing behavior owners: `scripts/release_readiness_gate.py::_write_fixture_project` already owns the shared four-file fixture; `_run_installed_golden_wheel` owns direct row order and fail-fast propagation; `tests/test_cli_golden_scenarios.py::test_cli_golden_workflow_happy_path` currently owns the remaining composite body; `tests/test_release_readiness_gate.py` owns injected orchestration and failure seams. Keep these boundaries.
- Options compared: deleting the source test loses source-mode evidence; retaining pytest as the installed executor fails direct qualification; adding a shared runner or product module creates another boundary; moving the body into the current gate and delegating from pytest changes three code/test files and rolls back as localized hunks. The cheapest falsifier is structural and behavioral: the source test contains only one helper call plus row assertions, its exact selector clause appears once, and the exact-wheel JSON contains one executed composite row.
- Add one stable composite command label and one `_run_installed_workflow_happy_path_scenario(command_prefix, env, scenario_root, neutral_cwd, *, repository_root, network_attempts=None, run_subprocess=subprocess.run)` beside the current direct scenarios. Reuse `_write_fixture_project`, `_run_installed_cli`, `_run_golden_subprocess`, `_installed_output_is_clean`, `_make_row`, shared timeouts, artifact snapshots, the installed command prefix, and the outer disposable root. Add only the bounded streaming helper state required for watch-on-save.
- Move the existing sequence and predicates without retaining a copy: initialize the fixture; mine a nonempty palace; compare displayed compression totals with displayed drawer rows; retry unchanged mining with identical backup archive set and palace-plus-backup bytes; verify status; search and read the unique marker; export/import and search/read the imported palace; backup/restore and search/read the restored palace; require healthy restored storage; reject the crafted traversal archive without target or escaped-file creation; then prove one watch-on-save re-mine cycle and clean exit.
- Preserve observable stdout/stderr expectations and extend the direct owner with `_installed_output_is_clean` on every subprocess. Return one deterministic public-safe row containing stable labels and booleans/counts only. Sanitize disposable paths and forbidden output, cap detail through `_make_row`, and include exactly one `rerun: <installed-golden command>` instruction on failure.
- Treat nonzero exit, timeout, launch error, malformed or incomplete totals/JSON, wrong post-state, unexpected backup growth, failed search/read round trip, unsafe extraction evidence, watch readiness/cycle/stop timeout, network-attempt evidence, or repository artifact drift as FAIL. Catch only expected subprocess, parsing, filesystem, queue, and timeout errors at the scenario boundary. Always stop/kill the owned watcher, join/drain its reader, and inspect cleanup before returning.
- Invoke the composite row once after exact-wheel provenance and prerequisite environment setup, stop immediately on non-pass, include its PASS row in the ordered result list, and retain the outer socket-attempt check. Add only `and not test_cli_golden_workflow_happy_path` to the existing transitional pytest `-k` expression.
- Keep `test_cli_golden_workflow_happy_path` at its existing public name. It should construct the current source-mode environment/command, call the release-owned helper with disposable paths, and assert the row ID/status/detail. Remove the local workflow sequence and only those helper/import definitions that become unowned; preserve helpers still used by adjacent source tests.
- Extend `_stub_direct_golden_scenarios` and the existing successful exact-wheel orchestration test with the new row, count, ordering, absolute console, neutral cwd, environment, socket log, and exact selector expectation. Add one focused hostile matrix for failed/malformed commands, wrong totals and post-state, backup growth, traversal residue, watch launch/readiness/cycle/stop failure, forbidden output, network attempts, repository drift, and cleanup after partial launch. Tests may model subprocess boundaries; they must not recreate the workflow body.
- Preserve all adjacent direct scenario ordering and behavior, fixture-shape coverage, installed `[watch]` extra, gate inventory, workflows, Linux update contour, product modules, docs, dependencies, and release modes. This residual creates no architecture delta or incident-class surface.
- Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` if the existing scorecard writer reports changed metrics after the move; retain no generated or smoke-test residue.
- Command context basis: `pyproject.toml` declares the three console scripts, pytest/Ruff/Pyright dev tools, and watch extra; `scripts/gate_inventory.py` owns the exact configured commands in VER-2 through VER-10; `.github/workflows/ci.yml` confirms the public/static command surfaces. Commands run from the repository root. PLAN inspected metadata only and did not execute tests, builds, gates, wrappers, generated-plan validation, reviews, or finalization.
- Independent Rule Zero, correctness, and security reviews remain runner-owned next phases. They must evaluate the same diff and exact-wheel evidence; they are not represented as fake shell verification rows.
