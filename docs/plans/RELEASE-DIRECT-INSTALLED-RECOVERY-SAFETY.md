---
slug: RELEASE-DIRECT-INSTALLED-RECOVERY-SAFETY
status: completed
authority: non_authoritative
goal: "Close the direct installed recovery row's false PASS by proving every disposable execution root remains byte-for-byte unchanged across read-only and refusal boundaries."
risk: medium
risk_note: "The product is unchanged, but incomplete root snapshots can admit a mutating exact-wheel recovery scenario as release-safe."
files:
  - path: scripts/release_readiness_gate.py
    change: "Reuse one same-owner disposable-root collector in the recovery and path-contract rows, then enforce boundary-specific snapshots across neutral cwd and HOME/XDG roots."
  - path: tests/test_release_readiness_gate.py
    change: "Add focused false-PASS regressions for arbitrary neutral-cwd and disposable environment-root mutation while preserving existing recovery orchestration coverage."
acceptance:
  - id: AC-1
    when: "the installed-golden recovery row is invoked with one exact candidate wheel from its neutral cwd"
    then: "all seven scenario processes use only the absolute wheel console in the existing offline, credential-free, socket-denied environment"
  - id: AC-2
    when: "import --dry-run runs twice against an absent palace"
    then: "both attempts report imported=1, skipped=0, KG=1 and every disposable root matches its byte-for-byte pre-attempt snapshot after each run"
  - id: AC-3
    when: "malformed JSONL dry-run and status --palace --summary are invoked"
    then: "both fail with the expected bounded status and guidance, no --summary path appears, and every disposable root remains unchanged"
  - id: AC-4
    when: "backup setup completes and restore without --force targets a colliding sentinel destination"
    then: "restore is refused, sentinel and archive bytes are preserved, no destination residue appears, and restore refusal plus --version leave the complete post-setup root boundary unchanged"
  - id: AC-5
    when: "source and exact-wheel recovery qualification are collected"
    then: "test_cli_recovery_safety_matrix remains a thin consumer of the single release-owned scenario, its exact transitional negative selector remains present once, and the direct row executes once"
  - id: AC-6
    when: "qualification evidence is produced for the final implementation"
    then: "the focused source regression, full non-network suite, static/public gates, fresh exact-wheel direct row, and independent Rule Zero, correctness, and security reviews all report success for the same change"
out_of_scope:
  - "Non-regular sources, fixture shape, inventory expansion, Linux hosted updates, and adjacent direct-installed scenarios."
  - "Changes to import, backup, restore, argument parsing, version reporting, storage, or other product behavior."
  - "A new runner, module, dependency, service, state owner, public interface, or architecture boundary."
  - "Changes to the already-thin source consumer, existing exact negative selector, scorecard artifacts, release docs, backlog metadata, publication, remote mutation, credentials, or AI-client invocation."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release task closes a false-PASS path in release-blocking installed-process recovery evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The exact candidate wheel console executes the recovery scenario from the established neutral, offline, credential-free, socket-denied contour."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Two absent-palace dry runs return deterministic counts without mutating any disposable execution root."
      source: "current backlog contract AC-2 and review residual"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Malformed JSONL and missing --palace value failures preserve every disposable execution root and emit bounded recovery guidance."
      source: "current backlog contract AC-3 and review residual"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Restore collision and launcher recovery preserve the complete post-backup setup boundary, sentinel, and archive."
      source: "current backlog contract AC-4 and review residual"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The existing source consumer and transitional selector continue to bind one release-owned recovery scenario without duplicated ownership or execution."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Focused, full-suite, static/public, fresh-wheel, and independent review evidence qualifies the bounded false-PASS closure."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "direct installed recovery root-integrity qualification"
      kind: internal
      paths: [scripts/release_readiness_gate.py]
      expected_behavior: "Fail the recovery row when any scenario, neutral cwd, HOME, USERPROFILE, or XDG root changes outside an explicitly rebaselined setup boundary."
  invariants:
    - id: INV-1
      statement: "Exact-wheel installation, absolute console provenance, neutral cwd, socket denial, credential removal, shared subprocess timeout, and disposable cleanup remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-2
      statement: "The recovery command sequence, fixture records, deterministic counts, failure guidance, sentinel, archive, launcher-version predicate, row ID, row order, and bounded detail remain unchanged."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-3
      statement: "The adjacent path-contract row keeps its current root validation and refusal-state semantics when it adopts the shared same-owner collector."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-4
      statement: "The thin source consumer, exact transitional selector, adjacent scenarios, gate inventory, product modules, dependencies, workflows, and release modes are not edited."
      applies_to: [scripts/release_readiness_gate.py, tests/test_release_readiness_gate.py]
    - id: INV-5
      statement: "Qualification performs no external AI-client call, authentication, credential access, publication, remote mutation, or non-disposable product-data mutation."
      applies_to: [scripts/release_readiness_gate.py]
  risks:
    - id: RISK-1
      risk: "Snapshotting only scenario_root repeats the observed false PASS when neutral_cwd or an environment root mutates."
      mitigation: "Collect and deduplicate the same seven required roots already enforced by the adjacent path-contract owner, then compare content-sensitive snapshots at each read-only boundary."
    - id: RISK-2
      risk: "One global baseline would reject intended backup setup mutations or miss restore/version drift after setup."
      mitigation: "Keep the initial fixture baseline for dry-run and malformed-argument checks, then explicitly rebaseline all roots after backup, restore-target, and sentinel setup before restore refusal and launcher recovery."
    - id: RISK-3
      risk: "Copying the root list into recovery creates divergent validation policy."
      mitigation: "Extract one small private collector beside the existing scenarios and reuse it from both recovery and path-contract owners without changing their subprocess orchestration."
    - id: RISK-4
      risk: "A synthetic mutation test could fail for output or status reasons and never prove root-integrity detection."
      mitigation: "Inject each unexpected file during an otherwise successful dry-run and assert the dedicated recovery row changes from PASS to FAIL with bounded detail."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_recovery_safety_scenario_fails_closed -q"
      proves: "The focused owner rejects neutral-cwd and environment-root mutation while retaining success, deterministic-count, refusal, collision, launcher, socket, and repository failure coverage."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The canonical fresh exact-wheel command executes the single direct recovery row through the installed console and all established isolation guards."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-3
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "The same-owner collector and focused regression satisfy the configured lint gate."
      acceptance_ids: [AC-6]
    - id: VER-4
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The bounded implementation satisfies the configured format gate."
      acceptance_ids: [AC-6]
    - id: VER-5
      owner: configured_runner
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "The root collector and snapshot maps satisfy the configured basic type gate."
      acceptance_ids: [AC-2, AC-3, AC-4, AC-6]
    - id: VER-6
      owner: configured_runner
      command: "python -m pyright -p pyrightconfig.strict.json"
      proves: "The configured strict slice remains green after the internal refactor."
      acceptance_ids: [AC-6]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The changed release evidence and tests contain no private, credential-shaped, provider, remote-mutation, or publication material."
      acceptance_ids: [AC-1, AC-6]
    - id: VER-8
      owner: configured_runner
      command: "python scripts/gate_inventory.py --check"
      proves: "The recovery correction remains within the existing installed-golden owner without a second gate or inventory row."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-9
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Canonical release command declarations remain synchronized without a release-doc change."
      acceptance_ids: [AC-6]
    - id: VER-10
      owner: configured_runner
      command: "python scripts/architecture_guard.py --root ."
      proves: "The correction introduces no service, store, durable contract, or architecture boundary."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-11
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The unchanged test inventory leaves the deterministic scorecard current."
      acceptance_ids: [AC-5, AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical full regression suite preserves the recovery source consumer, adjacent path-contract semantics, product recovery behavior, and unrelated non-network behavior."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Current HEAD already contains the ownership move: `scripts/release_readiness_gate.py` owns `installed_golden_recovery_safety`, `tests/test_cli_golden_scenarios.py::test_cli_recovery_safety_matrix` delegates to it, and transitional installed pytest contains the exact negative selector once. The implementation residual is the review-proven root-snapshot false PASS, so those completed surfaces remain unchanged.
- Rule Zero selects the existing release-gate owner and its adjacent path-contract policy. Deleting the recovery row loses required direct evidence; restoring the source-test body recreates duplicate ownership; a second module or framework adds lifecycle cost. One private same-owner collector removes the duplicated seven-root validation and is rolled back with two localized hunks.
- Extract a collector that accepts `env`, `scenario_root`, and `neutral_cwd`; require absolute `HOME`, `USERPROFILE`, `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_CACHE_HOME`; return the exact deduplicated tuple containing those roots plus scenario_root and neutral_cwd. Reuse it in `_run_installed_path_contract_scenario` without changing that row's actions or predicates.
- In `_run_installed_recovery_safety_scenario`, collect the roots before execution and retain the repository and socket-log guards. After creating neutral_cwd, import fixtures, and malformed fixture, snapshot every collected root. Compare every root after each dry-run, malformed import, and missing-value refusal; any missing, added, changed, symlinked, or unsupported entry fails closed through `_semantic_tree_snapshot`.
- Backup creation is intentional state mutation. After the backup archive, restore target, and sentinel exist, capture a second complete-root baseline plus the explicit archive bytes and sentinel state. Require restore refusal and the following `--version` call to leave every root at that post-setup baseline. Retain the explicit destination-inventory and archive/sentinel checks as readable contract evidence.
- Extend only the existing focused failure matrix. Build absolute disposable HOME/USERPROFILE/XDG paths in its environment, inject `neutral_cwd/unexpected-state` and one environment-root `unexpected-state` during an otherwise successful dry-run, and require FAIL. Keep the success case at seven subprocesses and preserve all existing failure parameters.
- Cheapest decisive falsifier: the two injected mutations currently return PASS at commit `8281bce4`; VER-1 must make both return FAIL while its success parameter remains PASS. A change that catches only scenario_root drift, rejects intended backup setup, duplicates the root list, edits the source consumer/selector, or adds another runner fails review.
- Command context basis: `pyproject.toml` declares Python 3.11+, pytest/Ruff/Pyright development dependencies, and the `mempalace-code` console; `scripts/gate_inventory.py` is the repository command source and supplies the exact full-suite, static/public, architecture, scorecard, and installed-wheel commands. Commands run from the repository root. PLAN inspected metadata only and ran no tests, builds, gates, wrappers, exact-wheel qualification, reviews, or validation scripts.
- The repository has no `docs/quality/incident-class-registry.yaml`, and this change affects release-test evidence rather than runtime behavior or routing. No incident-class proof block applies.
- Independent Rule Zero, correctness, and security review verdicts remain runner-owned evidence for AC-6. They are observable next-phase outputs and are not represented as shell pseudo-commands or repository artifacts.
