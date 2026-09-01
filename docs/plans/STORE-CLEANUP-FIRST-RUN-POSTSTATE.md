---
slug: STORE-CLEANUP-FIRST-RUN-POSTSTATE
status: completed
authority: non_authoritative
goal: "Make default Lance cleanup skip a fresh no-stale store and report stable, truthful poststate across repeated and installed-CLI runs."
risk: medium
risk_note: "The fix changes a persistent-store maintenance decision and its CLI result contract; an incorrect eligibility check could skip reclaimable versions or misreport disk state."
files:
  - path: mempalace_code/storage.py
    change: "Teach LanceStore.cleanup_stale_fragments to detect the default no-eligible-version case before optimize, return unchanged poststate for that no-op, and report reclaimable bytes before and after supported cleanup."
  - path: mempalace_code/cli_commands/maintenance.py
    change: "Render the storage-owned reclaimable-byte before/after values without adding another cleanup decision path."
  - path: tests/test_storage.py
    change: "Add focused fake and real LanceStore regressions for eligibility, fresh and repeated default cleanup, eligible reclamation, truthful metrics, row preservation, unsafe behavior, and failures."
  - path: tests/test_cli_golden_scenarios.py
    change: "Add a subprocess cleanup scenario that compares first and repeated cleanup JSON with health JSON and therefore runs unchanged through source and exact-wheel installed executables."
acceptance:
  - id: AC-1
    when: "default cleanup runs on a freshly created palace whose non-current versions are all newer than the seven-day threshold"
    then: "it exits successfully, preserves every row, and leaves version_count and estimated_reclaimable_bytes unchanged with freed_bytes equal to zero"
  - id: AC-2
    when: "the identical default cleanup is run again against that palace"
    then: "its row, version, reclaimable-byte, and freed-byte poststate is identical to the first result and the palace remains readable"
  - id: AC-3
    when: "cleanup runs against a real palace with a non-current version eligible for the selected threshold"
    then: "the supported LanceDB optimize API is invoked, rows remain readable, and returned version, freed-byte, and reclaimable-byte before/after values equal the observed store poststate"
  - id: AC-4
    when: "--unsafe-now is explicitly selected or the supported cleanup call fails"
    then: "the existing zero-threshold/delete-unverified behavior and no-writer warning remain explicit, while failures stay nonzero with the existing recovery action and no traceback"
  - id: AC-5
    when: "release readiness builds the candidate wheel and runs the cleanup golden scenario through its absolute installed mempalace-code executable"
    then: "first and repeated cleanup succeed and each JSON poststate matches the immediately observed health storage status for the same palace"
out_of_scope:
  - "Direct deletion of Lance manifests, fragments, data files, or deletion files."
  - "A second cleanup API, helper module, CLI command, option, confirmation gate, or maintenance mode."
  - "Changes to safe_optimize, health/storage metric definitions, backup, repair, mining, watching, or non-Lance backends."
  - "Changing the default seven-day threshold or the --unsafe-now safety contract."
  - "Release publication, backlog bookkeeping, or changes to release-readiness orchestration."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release bug work changes a persistent-store cleanup boundary and installed CLI poststate reporting."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Default cleanup must preserve fresh no-stale storage and report unchanged poststate."
      source: "backlog AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Repeated default cleanup must be idempotent."
      source: "backlog AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Eligible stale versions must still reclaim through LanceDB and expose truthful before/after metrics."
      source: "backlog AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Unsafe-now selection and cleanup failure handling must remain explicit and compatible."
      source: "backlog AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The exact-wheel installed executable must prove cleanup JSON against independently observed storage status."
      source: "backlog AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "Lance stale-fragment cleanup"
      kind: store
      paths: ["mempalace_code/storage.py"]
      expected_behavior: "Use version timestamps to skip only the safe default no-eligible-version case, otherwise retain the supported optimize call and return verified before/after storage metrics."
    - name: "cleanup CLI result"
      kind: cli
      paths: ["mempalace_code/cli_commands/maintenance.py"]
      expected_behavior: "Expose the storage-owned version, freed-byte, and reclaimable-byte transition consistently in human and JSON modes."
  invariants:
    - id: INV-1
      statement: "Table.optimize(cleanup_older_than=..., delete_unverified=...) remains the only mutating stale-version cleanup mechanism."
      applies_to: ["mempalace_code/storage.py"]
    - id: INV-2
      statement: "Cleanup preserves row count and verifies a freshly reopened table, a readable row, and the wing/room scan after every optimize call."
      applies_to: ["mempalace_code/storage.py"]
    - id: INV-3
      statement: "--unsafe-now continues to use timedelta(0), delete_unverified=True, and the existing no-writer warning."
      applies_to: ["mempalace_code/storage.py", "mempalace_code/cli_commands/maintenance.py"]
    - id: INV-4
      statement: "Existing cleanup result keys, nonzero failure exits, dependency guidance, and recovery text remain compatible."
      applies_to: ["mempalace_code/storage.py", "mempalace_code/cli_commands/maintenance.py"]
  risks:
    - id: RISK-1
      risk: "A malformed or unavailable version timestamp could cause a false no-op and leave eligible stale state unreclaimed."
      mitigation: "Skip optimize only when every non-current version has a supported timestamp and all are newer than the cutoff; fall back to the existing supported optimize path when eligibility is unknown."
    - id: RISK-2
      risk: "Computing the cutoff with naive and timezone-aware values could misclassify a version at the threshold."
      mitigation: "Normalize supported LanceDB timestamps to one UTC-aware comparison and cover exact-boundary, fresh, and stale cases with deterministic fake-table tests."
    - id: RISK-3
      risk: "In-memory before/after values could differ from the store reopened by a later command."
      mitigation: "Retain fresh-handle verification after optimize and compare cleanup JSON with a separate health --json subprocess in the golden scenario."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_storage.py::TestCleanupStaleFragments tests/test_cli.py::TestCleanupCommand -q"
      proves: "Focused storage and CLI behavior covers fresh and repeated no-op cleanup, eligible reclamation, exact-threshold and unknown-timestamp boundaries, row preservation, unsafe mapping, dependency errors, and actionable failures."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_cli_golden_scenarios.py::test_cli_golden_cleanup_poststate -q"
      proves: "The public subprocess CLI produces cleanup JSON that agrees with independently reopened health storage status on first and repeated calls."
      acceptance_ids: [AC-1, AC-2, AC-5]
    - id: VER-3
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --check --candidate-sha "$CANDIDATE_SHA" --json'
      proves: "The configured release gate builds the candidate wheel and executes the golden cleanup scenario through the provenance-checked absolute installed executable."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/ -x -q -m \"not needs_network\""
        proves: "The exact configured non-network suite preserves storage, optimize, health, CLI, and release-golden behavior around the cleanup change."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- `LanceStore.cleanup_stale_fragments` currently calls `Table.optimize` unconditionally. In the locked LanceDB 0.33 contour, that supported maintenance call may commit maintenance versions even when the seven-day cleanup threshold selects nothing. The no-stale decision therefore belongs before `optimize`; no direct filesystem mutation is introduced.
- Reuse `table.list_versions()` as the eligibility source. Exclude the current version, compare each supported timestamp with the UTC cutoff, and return a verified no-op only when every remaining version is known to be newer than the cutoff. An empty non-current set is also a no-op.
- Preserve conservative behavior for missing, malformed, or unrecognized timestamps: call the existing supported `optimize` path. Uncertain metadata must never suppress cleanup.
- Keep `unsafe_now=True` on the existing optimize path regardless of timestamps. Its zero threshold and `delete_unverified=True` contract intentionally differs from the safe default.
- On a no-op, reuse the single preflight `storage_stats()` snapshot for both before and after values, set `freed_bytes=0`, preserve `rows_before == rows_after`, and do not reopen or rewrite the table because no mutation occurred.
- After optimize, retain the current reopen/read/column-scan verification, then compute `estimated_reclaimable_bytes_before` and `estimated_reclaimable_bytes_after` from the same before and verified-after snapshots that own version counts and `freed_bytes`.
- Add the two reclaimable-byte fields without renaming or removing existing result keys. Human output should render the same before/after values; JSON remains the direct storage result.
- Extend `_OptimizableTable` only as needed to supply deterministic version timestamps and assert whether optimize was called. Keep the real-store regression in `TestCleanupStaleFragments`: first and second default calls must preserve rows, versions, and reclaimable bytes; a zero-threshold eligible case must still reclaim and match a fresh `storage_stats()` observation.
- Add `test_cli_golden_cleanup_poststate` beside the existing subprocess scenarios. Create the palace through `_CLI`, run default `cleanup --json` twice, run `health --json` after each call, and compare cleanup `version_count_after` and `estimated_reclaimable_bytes_after` with `health.storage`; assert row preservation and identical repeated poststate. Reuse `_assert_installed_cli_provenance`, `_make_env`, `_run_cli`, and `_assert_clean` so the same test runs in source mode and in the configured exact-wheel installed mode.
- Command context basis: `pyproject.toml` configures pytest from the repository root; `scripts/gate_inventory.py` owns the exact non-network suite and release-readiness command; `scripts/release_readiness_gate.py` builds one wheel and runs `tests/test_cli_golden_scenarios.py` through a provenance-checked absolute installed executable.
- No incident proof block applies because `docs/quality/incident-class-registry.yaml` is absent and this storage cleanup bug does not change an Autopilot provider, routing, budget, recovery, or verify-fix authority class.
- PLAN does not execute tests, builds, release gates, or validation wrappers.
