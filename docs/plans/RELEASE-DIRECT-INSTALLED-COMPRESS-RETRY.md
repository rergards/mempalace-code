---
slug: RELEASE-DIRECT-INSTALLED-COMPRESS-RETRY
status: completed
authority: non_authoritative
goal: "Give the existing direct compression scenario and source golden suite one release-gate-owned project fixture without changing their behavior or fixture shape."
risk: medium
risk_note: "The edit is a bounded ownership move, but the shared four-file fixture feeds multiple source golden scenarios and the exact-wheel release blocker, so shape or import drift could weaken both contours."
files:
  - path: scripts/release_readiness_gate.py
    change: "Move the existing four-file golden project writer and its Python source lines into this established release-gate owner, and make the direct compression scenario call that shared writer instead of its inline copy."
  - path: tests/test_cli_golden_scenarios.py
    change: "Consume the release-gate-owned fixture writer and Python lines, delete the test-owned fixture body, and preserve the existing source scenarios, read-range expectations, fixture-shape test, and thin compression consumer."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable metrics if moving the fixture owner changes measured script or test metrics."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable metrics if moving the fixture owner changes measured script or test metrics."
acceptance:
  - id: AC-1
    when: "the exact candidate wheel installed-golden command runs from its neutral working directory"
    then: "it initializes and mines a disposable shared fixture project, directly runs compression dry-run, first apply, unchanged retry, unknown-wing refusal, mixed-state second apply, export snapshots, and post-compression search through the installed console, and emits one compression PASS or FAIL row"
  - id: AC-2
    when: "the source fixture-shape test, source compression consumer, and installed-gate orchestration execute"
    then: "one release-gate-owned fixture writer and one release-gate-owned compression body serve both contours, pytest remains a thin consumer, and the transitional installed pytest command deselects the compression test"
  - id: AC-3
    when: "dry-run and first live compression execute against the initially mined shared fixture"
    then: "dry-run creates no backup or mutation, while first apply creates exactly one recovery archive, reports stored-and-verified output, and emits the exact restore --force argv for the canonically resolved palace and created archive"
  - id: AC-4
    when: "first compression and an unchanged retry export and compare the fixture drawers"
    then: "drawer IDs are preserved, compressed records have positive original_tokens, retry reports zero pending and skips every completed drawer, exported records remain byte-semantically equal, and retry creates no backup"
  - id: AC-5
    when: "compression targets the named unknown wing after initial compression"
    then: "the process exits 2 with the named wing and one status recovery command while palace bytes, sibling backup bytes, and the archive set remain unchanged"
  - id: AC-6
    when: "a new source is mined into the mixed compressed and pending fixture state and compression runs again"
    then: "only pending drawers change, previously compressed records remain exactly equal, one backup is created, and the original search sentinel remains searchable"
  - id: AC-7
    when: "a subprocess, stream, export, count, record, recovery argv, backup, post-state, launch, timeout, or filesystem contract fails"
    then: "the scenario emits one bounded sanitized FAIL row with one exact-wheel rerun command, keeps all product data disposable, and preserves the repository-root artifact boundary"
  - id: AC-8
    when: "the focused, configured repository-quality, exact-wheel, and independent Rule Zero evidence inspect the completed ownership move"
    then: "focused behavior, full non-network pytest, Ruff lint and format, both Pyright modes, gate inventory, docs drift, scorecard freshness, public safety, exact-wheel qualification, and Rule Zero review pass without a new script, runner, catalog, dependency, release, push, publication, credential access, authenticated AI-client call, or non-disposable product-data action"
out_of_scope:
  - "Changing the four fixture filenames, their contents, marker text, source line ranges, or any golden scenario behavior."
  - "Changing compression product behavior, watcher or signal scenarios, the happy-path workflow composite, inventory, Linux or systemd, install or update, dependencies, public mode, or any adjacent scenario."
  - "Adding a second fixture helper, script, module, runner, catalog entry, gate mode, dependency, or parallel scenario owner."
  - "Completing or closing RELEASE-DIRECT-INSTALLED-APP-GATE or any later staged residual."
  - "Editing backlog metadata or runner-owned finalization artifacts; deterministic scorecard artifacts may change only to reflect the implementation."
  - "Release, tag, push, publication, authenticated provider-client, authentication, credential, or non-disposable product-data operations."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release ownership move changes a shared fixture used by source and direct exact-wheel qualification under rules-heavy release boundaries."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact-wheel installed gate must continue to execute the complete compression retry and recovery sequence from a neutral cwd against the shared fixture."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The four-file golden fixture and compression scenario must each have one release-gate owner while pytest consumes both without retaining a copied body."
      source: "current backlog contract AC-2 and fixture ownership blocker"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Dry-run and first apply must retain their zero-mutation and exact recovery archive and argv contracts after fixture ownership moves."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "First compression and unchanged retry must preserve IDs, positive completion provenance, exact exported records, skip counts, and backup idempotence."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Unknown-wing refusal must preserve the palace and sibling backup state and emit its bounded recovery action."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Mixed-state compression must change only zero-sentinel pending drawers and retain searchability."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "All existing failure classes must continue to collapse into one bounded sanitized compression row with one exact-wheel rerun command."
      source: "current backlog contract AC-7"
      acceptance_ids: [AC-7]
    - id: REQ-8
      statement: "All configured release, repository-quality, safety, freshness, and independent review evidence must remain green within the non-publishing boundary."
      source: "current backlog contract AC-8"
      acceptance_ids: [AC-8]
  surfaces:
    - name: "direct installed compression retry gate"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Own the canonical four-file golden fixture and the existing direct compression retry sequence, then return one stable PASS or sanitized FAIL row when invoked with an installed or source command prefix."
  invariants:
    - id: INV-1
      statement: "The shared fixture retains app.py, NOTES.md, settings.toml, service.go, the xylophonic_glyph_9182 marker, exact contents, and the current sub-20KB shape."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-2
      statement: "All existing source golden consumers continue to use the same fixture writer and Python source lines for read-range and snippet assertions."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-3
      statement: "The compression source test remains callable by its current name, delegates to the release-gate scenario, and stays deselected from the transitional installed pytest remainder."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-4
      statement: "Installed process, environment, timeout, neutral-cwd, output sanitization, export parsing, backup discovery, canonical recovery paths, disposable roots, and repository-boundary seams remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py"]
    - id: INV-5
      statement: "Watcher, signal, workflow, inventory, Linux, systemd, install, update, dependency, public-mode, and adjacent scenario behavior remain unchanged."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_cli_golden_scenarios.py"]
    - id: INV-6
      statement: "No release gate invokes external AI clients, authentication, credentials, tags, pushes, publication, package-index mutation, or non-disposable product data."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "Moving only the fixture writer while leaving Python lines or expected snippets test-owned could preserve parallel ownership and allow silent shape drift."
      mitigation: "Move the writer and canonical Python line sequence together, bind the source test module to those release-gate objects, and delete the original definitions."
    - id: RISK-2
      risk: "The direct compression scenario could retain its inline four-file copy after a shared helper is introduced."
      mitigation: "Replace the entire inline project construction with one call to the moved writer and retain no second fixture-writing branch."
    - id: RISK-3
      risk: "Other source golden scenarios or read-range assertions could change after the owner move."
      mitigation: "Preserve the helper signature, returned root, exact bytes, and shared Python lines; run the existing fixture-shape, source compression, and full non-network consumers."
    - id: RISK-4
      risk: "The ownership edit could weaken already-landed stream, export, compression-state, recovery-path, or failure-row hardening."
      mitigation: "Leave scenario transitions and predicates unchanged and retain the existing injected-runner failure matrix plus exact-wheel qualification."
    - id: RISK-5
      risk: "Moving code between script and test surfaces can stale deterministic scorecard metrics."
      mitigation: "Regenerate only the two existing scorecard artifacts when their configured freshness check requires it."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_cli_golden_fixture_shape tests/test_cli_golden_scenarios.py::test_cli_golden_compress_retry_idempotent_recovery tests/test_release_readiness_gate.py::test_installed_compress_retry_fails_closed tests/test_release_readiness_gate.py::test_installed_compress_retry_accepts_canonical_recovery_path_alias -q"
      proves: "The moved fixture retains its multiformat shape, the thin source consumer exercises the shared direct scenario, and every established compression failure and canonical recovery alias remains fail closed or accepted as appropriate."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical exact-wheel owner uses the same fixture and direct scenario through the installed console and emits its executed compression row."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The existing installed-golden registration remains canonical and no inventory surface is added or removed."
      acceptance_ids: [AC-2, AC-8]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Canonical documentation and release command declarations remain synchronized after the internal ownership move."
      acceptance_ids: [AC-8]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The changed release, test, plan, and scorecard surfaces contain no private, credential-shaped, authentication, provider-client, or publication material."
      acceptance_ids: [AC-7, AC-8]
    - id: VER-6
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The configured lint gate accepts the moved fixture owner and deleted duplicate."
      acceptance_ids: [AC-2, AC-8]
    - id: VER-7
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The configured format gate accepts the release-gate and source-test ownership edits."
      acceptance_ids: [AC-2, AC-8]
    - id: VER-8
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The configured basic type gate accepts the shared fixture objects and existing direct scenario flow."
      acceptance_ids: [AC-2, AC-7, AC-8]
    - id: VER-9
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict slice remains green and no product type surface changes."
      acceptance_ids: [AC-8]
    - id: VER-10
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The committed scorecard matches the reviewed tree after fixture ownership moves between script and test surfaces."
      acceptance_ids: [AC-2, AC-8]
    - id: VER-11
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The full configured non-network suite preserves every source fixture consumer, compression behavior, release gate, adjacent scenario, and unrelated runtime contract."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves the shared fixture shape, all its source consumers, direct compression recovery, and unrelated non-network behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8]
      - id: REG-2
        owner: configured_runner
        command: "python scripts/gate_inventory.py --check"
        proves: "The existing installed-golden registration and command remain unchanged while fixture ownership is consolidated internally."
        acceptance_ids: [AC-2, AC-8]
---

## Design Notes

- Rule Zero outcome: keep `scripts/release_readiness_gate.py` as the sole direct installed owner, move the existing `_write_fixture_project` behavior and canonical Python lines into it, delete the test-owned definitions and the compression scenario's inline copy, and change no runtime product surface.
- Reuse evidence: `tests/test_cli_golden_scenarios.py::_write_fixture_project` currently owns the standard app.py, NOTES.md, settings.toml, and service.go fixture used by five source scenarios plus `test_cli_golden_fixture_shape`; `_run_installed_compress_retry_scenario` independently writes the same four files and marker. The release gate already owns the direct scenario and is loaded by the source test module through `runpy.run_path`.
- Delete/simplify wins over extension with another copy: move the existing writer and Python-line sequence to the current release-gate module, bind the source test module to those returned objects, remove `_PY_LINES` and the local writer body, and replace the direct scenario's four inline writes with one shared call.
- A new module or architecture boundary loses the comparison: it would add a third owner surface and lifecycle for one small fixture already shared across the existing release-gate/test boundary. No new service, store, public contract, dependency, or durable state is justified.
- Preserve the writer signature, returned project root, directory creation behavior, exact UTF-8 bytes, trailing newlines, four filenames, marker, and Python line list. This keeps the existing read range, expected snippets, mining counts, search sentinel, and fixture-shape regression unchanged.
- Bind `tests/test_cli_golden_scenarios.py` to the release-gate-owned writer and Python lines beside its existing bindings for direct scenario functions. The test module must not import the release gate as a package or make the release gate import test code.
- Keep `test_cli_golden_compress_retry_idempotent_recovery` as the existing thin row consumer. Keep its name in the transitional installed pytest deselection and retain the direct row's current placement and fail-fast behavior in `_run_installed_golden_wheel`.
- Preserve the already-landed exact stream contracts, non-boolean non-negative `original_tokens` validation, explicit zero pending sentinel, six-token recovery argv with canonical path provenance, archive counting, byte-semantic exports, mixed-state assertions, and bounded sanitized failure row. This residual changes ownership only.
- Preserve scorecard freshness with its existing generator. Regenerate only docs/quality/scorecard.md and docs/quality/scorecard.json when the configured check detects changed metrics.
- Rollback is a direct reversal of the two source edits plus regenerated scorecard artifacts; there is no migration, live rollout, persisted state, or compatibility shim.
- Cheapest decisive falsifier: the focused command runs the shared fixture-shape test, thin source compression consumer, and existing fail-closed matrix; any changed fixture byte, lost consumer, duplicated transition, or weakened recovery contract fails before the exact-wheel gate.
- Independent Rule Zero review is runner-owned phase evidence. It must confirm one fixture writer remains by behavior and that the diff introduces no new helper/module/runner; it is not represented by a fake shell verification row.
- Command context basis: pyproject.toml declares Python 3.11+, pytest, Ruff, and basic Pyright; pyrightconfig.strict.json owns the strict slice; scripts/gate_inventory.py contains the exact full-suite, Pyright, inventory, docs-drift, public-safety, scorecard, and exact-wheel command forms. Commands run from the repository root.
- Filename discovery found no docs/quality/incident-class-registry.yaml, so this task has no registry-matched incident_proof block.
- PLAN did not run tests, builds, verification wrappers, exact-wheel qualification, independent review, generated-plan validation, source verification, or runner finalization.
