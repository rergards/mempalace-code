---
slug: RELEASE-DIRECT-INSTALLED-ALIAS-CONTAINMENT
status: completed
authority: non_authoritative
goal: "Make the direct exact-wheel installed gate own alias target-containment qualification while the source pytest remains a thin consumer."
risk: medium
risk_note: "The ownership move is localized, but it changes release-blocking subprocess evidence for a filesystem mutation boundary and must preserve fail-closed, idempotent, provenance, output, and cleanup predicates."
files:
  - path: scripts/release_readiness_gate.py
    change: "Own and directly execute the alias target-containment scenario through the exact installed console, emit one bounded evidence row, and deselect only its thin source consumer from transitional pytest."
  - path: tests/test_cli_golden_scenarios.py
    change: "Replace the named alias-containment scenario body with a thin source-mode consumer of the release-gate-owned scenario."
  - path: tests/test_release_readiness_gate.py
    change: "Cover direct alias scenario success, refusal, retry, provenance, output and cleanup failures, exact-wheel orchestration, row propagation, and transitional pytest deselection."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable metrics only if the ownership move changes measured script or test metrics."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable metrics only if the ownership move changes measured script or test metrics."
acceptance:
  - id: AC-1
    when: "the exact candidate wheel installed-golden command runs from its neutral working directory while PATH contains an unrelated ambient mempalace alias"
    then: "it invokes the absolute candidate-wheel console and directly emits an installed alias-containment PASS or bounded FAIL row"
  - id: AC-2
    when: "the direct scenario exercises first install, a conflicting target entry, and an identical retry inside its disposable root"
    then: "the explicit target receives only the candidate alias, the unrelated ambient alias is preserved, overwrite is refused without mutation, retry is idempotent, output is bounded and sanitized, provenance points to the invoked console, and the disposable scenario root is removed"
  - id: AC-3
    when: "source-mode pytest and exact-wheel qualification exercise the named alias-containment scenario"
    then: "both consume one release-gate-owned scenario, the source test retains only setup plus returned-row assertion, and only that test is deselected from transitional installed pytest"
  - id: AC-4
    when: "the configured non-network suite, static and public release gates, fresh exact-wheel installed rows, implementation diff checks, and independent reviews complete"
    then: "all required evidence passes within the credential-free, non-publishing, disposable-data boundary"
out_of_scope:
  - "Changing install-alias product behavior, parser options, console entry points, fixture shape, or alias symlink semantics."
  - "Changing schedule behavior, composite workflow, diary or path behavior, recovery matrices, non-regular sources, inventory behavior, Linux hosted behavior, dependencies, publication, or adjacent golden scenarios."
  - "Adding a helper module, second scenario body, runner, gate mode, service, store, durable contract, or public command surface."
  - "Editing backlog metadata or runner-owned finalization artifacts; deterministic scorecard files may change only when their canonical freshness check requires regeneration."
  - "Push, tag, release, publication, remote mutation, credential access, authentication, external AI-client invocation, or non-disposable product-data mutation."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task moves release-blocking installed-process evidence into the direct exact-wheel provider owner under filesystem-mutation, provenance, and credential-free constraints."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact-wheel installed gate must invoke the absolute candidate console from a neutral cwd with an unrelated ambient PATH alias."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "One direct scenario must prove explicit-target containment, unrelated-alias preservation, overwrite refusal, retry idempotence, bounded sanitized output, candidate provenance, and disposable-root cleanup."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The release gate must be the single scenario owner while the named source test remains a thin consumer and is the only newly deselected transitional test."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Configured regression, static, public-safety, scorecard, exact-wheel, diff, and independent review evidence must remain green inside the release credential boundary."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
  surfaces:
    - name: "direct installed alias target-containment gate"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Run one canonical alias-containment scenario through a supplied source or installed command prefix and return one stable PASS or sanitized FAIL row."
  invariants:
    - id: INV-1
      statement: "The installed-golden owner continues to validate one exact wheel, its absolute console and module provenance, the existing cache preflight, credential-free environment, socket guard, neutral cwd, shared timeouts, and disposable outer root before the scenario runs."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "Explicit target installation never mutates or accepts an unrelated PATH alias and never overwrites a conflicting target entry; a correct target retry remains idempotent."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-3
      statement: "The existing source test remains callable by the same name, uses its established fake-package or installed-console environment, delegates to the shared scenario, and retains no second transition or predicate body."
      applies_to: ["tests/test_cli_golden_scenarios.py", "scripts/release_readiness_gate.py"]
    - id: INV-4
      statement: "All existing transitional pytest deselection clauses remain byte-for-byte equivalent except for excluding test_install_alias_explicit_target_containment_from_neutral_directory."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-5
      statement: "Product alias implementation, fixtures, inventory, workflows, adjacent scenarios, public commands, dependencies, and hosted platform behavior remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py", "tests/test_release_readiness_gate.py"]
    - id: INV-6
      statement: "Release qualification never reads credentials, authenticates, invokes external AI clients, mutates Git history or remotes, publishes artifacts, or writes product data outside disposable roots."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "Copying the pytest body could leave two scenario authorities that drift or execute twice in exact-wheel qualification."
      mitigation: "Move all setup, transitions, and predicates into one release-gate function, reduce pytest to one call and row assertion, and add only its stable name to the existing deselection expression."
    - id: RISK-2
      risk: "A PATH lookup could silently select the ambient command and produce false candidate provenance."
      mitigation: "Pass the exact canonical target separately, invoke the absolute installed console, keep the ambient alias pointed at an unrelated executable, and require the created target alias to resolve only to the supplied canonical target."
    - id: RISK-3
      risk: "A nonzero subprocess, unsafe output, collision mutation, cleanup failure, or filesystem exception could escape as a traceback or ambiguous release result."
      mitigation: "Reuse the installed subprocess and clean-output seams, catch bounded expected failures, snapshot collision and ambient entries, verify cleanup after the inner disposable context, and return one sanitized row with one canonical rerun command."
    - id: RISK-4
      risk: "Moving executable lines between script and test owners can stale committed scorecard metrics."
      mitigation: "Regenerate only the two existing deterministic scorecard artifacts when the canonical freshness check requires it."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_alias_target_containment_fails_closed tests/test_cli_golden_scenarios.py::test_install_alias_explicit_target_containment_from_neutral_directory -q"
      proves: "The single release-gate scenario serves both consumers and covers target creation, ambient preservation, collision refusal, retry, provenance, bounded output, cleanup, and fail-closed seams."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The configured exact-wheel owner invokes the absolute installed console from its neutral contour, executes the alias scenario directly, and requires its dedicated evidence row."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The existing installed-golden command remains canonical and no runner, inventory entry, mode, or public gate surface is added."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Tracked release command declarations remain synchronized after the internal scenario ownership move."
      acceptance_ids: [AC-4]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The bounded implementation and evidence diff contains no private, credential-shaped, authenticated-provider, or publication material."
      acceptance_ids: [AC-4]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the existing-owner extension and thin consumer without a new module or dependency."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the three implementation surfaces."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-8
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured type gate accepts the direct scenario, subprocess injection seam, path snapshots, and row flow."
      acceptance_ids: [AC-1, AC-2, AC-4]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The committed deterministic scorecard matches the reviewed ownership move."
      acceptance_ids: [AC-3, AC-4]
    - id: VER-10
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured non-network suite preserves source alias behavior, direct installed orchestration, adjacent scenarios, and unrelated repository behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves alias containment and unrelated non-network behavior after execution ownership moves."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "The direct scenario remains inside the existing installed-golden owner with no inventory, runner, or command-surface duplication."
        acceptance_ids: [AC-3, AC-4]
---

## Design Notes

- Rule Zero outcome: extend `scripts/release_readiness_gate.py`, the current exact-wheel installed-golden owner. Deletion loses release evidence; changing product alias code exceeds this ownership-only task; a helper module or second runner adds lifecycle cost. Moving the body into one same-owner function changes three implementation paths, adds no interface or state, and rolls back as local source/test hunks plus optional scorecard regeneration.
- Reuse `_run_installed_cli`, `_run_golden_subprocess`, `_installed_output_is_clean`, `INSTALLED_GOLDEN_FORBIDDEN_OUTPUT`, `_make_row`, `DEFAULT_TIMEOUT`, `INSTALLED_GOLDEN_COMMAND`, the exact installed console, neutral cwd, credential-free environment, socket-attempt log, temporary root, and established row ordering. Do not add an environment builder, subprocess wrapper, sanitizer module, scenario runner, or gate mode.
- Give `_run_installed_alias_target_containment_scenario` a command prefix, explicit expected canonical executable, environment, scenario-root parent, neutral cwd, repository root, and injectable `run_subprocess`. Source pytest supplies `_CLI`, its existing `_make_env`, and the fake or installed expected canonical target; exact-wheel qualification supplies `[str(console)]`, `console`, and `golden_env`.
- Inside one inner disposable context, create a conflicting ambient canonical executable plus `mempalace` alias, an empty requested target directory, and a separate collision target. Snapshot the ambient entry by path kind, literal symlink target, and resolved target before invocation.
- Run the explicit-target command through the supplied command prefix from the supplied neutral cwd. Require exit zero, exact bounded success markers, clean stdout/stderr, a symlink only under the requested target, and resolution to the explicit expected canonical executable. Require the ambient alias snapshot to remain identical.
- Run the same request again and require identical successful output and unchanged filesystem state. For refusal, pre-create an unrelated regular file or symlink at a separate requested target, require exit 1 with empty stdout and the existing `already exists; not overwriting` diagnostic, and compare its exact bytes or literal link target before and after.
- Exit the inner disposable context before returning PASS and require its path to be absent. Compare the repository-root semantic snapshot before and after so cleanup proof cannot hide a write into the checkout. A missing cleanup, repository drift, unexpected extra alias, wrong provenance, polluted or oversized output, nonzero success/retry, zero refusal, changed ambient/collision entry, launch failure, timeout, or expected filesystem evaluation error returns one `installed_golden_alias_containment` FAIL row.
- Bound failure detail to the established direct-scenario limit, replace transient scenario and repository paths, suppress forbidden output, and append exactly one `rerun: python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json` recovery action. The PASS detail names the contained target, preserved ambient alias, refusal, retry, provenance, and cleanup without embedding transient paths.
- Invoke the scenario once in `_run_installed_golden_wheel` after wheel install, site guard, and provenance succeed. Fail fast on its non-pass row and retain its row in the stable success result order. Update orchestration expectations and direct-scenario stubs for the one additional row.
- Keep `test_install_alias_explicit_target_containment_from_neutral_directory` at its current name. Bind it through the existing `runpy.run_path` release-owner seam, retain `_make_env`, and reduce its body to expected-canonical setup, one scenario call, and `row["status"]` assertion.
- Add only `not test_install_alias_explicit_target_containment_from_neutral_directory` to the existing transitional pytest `-k` expression. Extend the orchestration test to prove the direct row executes before transitional pytest, propagates failure without launching that suite, and leaves every pre-existing deselection clause unchanged.
- Extend `tests/test_release_readiness_gate.py` with one parametrized injected-runner matrix covering success plus wrong target provenance, missing alias, ambient mutation, overwrite, non-refusal, retry mutation, polluted or oversized output, launch error, timeout, expected filesystem exception, repository drift, and cleanup failure. Assert row ID/status, one recovery command on failure, bounded path-free detail, absolute installed command, neutral cwd, shared timeout, exact call order, and no duplicate source-test execution.
- Preserve scorecard freshness through its current generator. Regenerate only `docs/quality/scorecard.md` and `docs/quality/scorecard.json` when `python scripts/quality_scorecard.py --check` reports changed metrics.
- Cheapest decisive falsifier: VER-1 exercises the shared source consumer and injected direct-scenario matrix. Any duplicate body, ambient selection, overwrite, non-idempotent retry, unsafe output, wrong cwd or timeout, residual disposable root, or ambiguous failure breaks this focused check before exact-wheel qualification.
- Implementation diff inspection and independent Rule Zero and correctness reviews remain runner-owned phase evidence. They confirm the five declared paths, one scenario owner, the single selector delta, and the forbidden-action boundary; they are not represented as fake shell verification rows.
- Command context basis: `pyproject.toml` declares Python 3.11+, repository-root pytest, Ruff, and Pyright; current direct-installed plans record the required effective full-suite, inventory, docs-drift, public-safety, scorecard, type, and exact-wheel command forms; `.github/workflows/ci.yml` invokes the exact-wheel command after selecting one built wheel. PLAN inspected metadata and source only and did not execute any command above.
- Filename discovery found no `docs/quality/incident-class-registry.yaml`, so no registry-matched `incident_proof` block applies.
- PLAN does not run tests, builds, verification wrappers, exact-wheel qualification, generated-plan validation, independent reviews, source verification, Git finalization, or publication.
