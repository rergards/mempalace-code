---
slug: RELEASE-DIRECT-INSTALLED-CONVO-FULL-REPLACE
status: completed
authority: non_authoritative
goal: "Make the existing direct installed conversation replacement gate compare valid exports by canonical chunk_index instead of LanceDB row order."
risk: low
risk_note: "The behavior change is confined to release-gate evidence normalization and its existing focused test; product export and storage behavior remain unchanged."
files:
  - path: scripts/release_readiness_gate.py
    change: "Validate unique nonnegative integer chunk_index values, canonicalize conversation drawer records by that index, and retain exact semantic and fail-closed comparisons."
  - path: tests/test_release_readiness_gate.py
    change: "Extend the existing parametrized direct-conversation gate regression with valid row permutations and malformed-index, record, ID, text, provenance, and wing cases."
  - path: docs/quality/scorecard.md
    change: "Regenerate the existing deterministic human-readable metrics after the focused regression changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the existing deterministic machine-readable metrics after the focused regression changes."
acceptance:
  - id: AC-1
    when: "the direct conversation scenario receives the same valid drawer records in storage-dependent permutations across its exports"
    then: "it canonicalizes each export by unique nonnegative integer chunk_index and returns PASS with exact per-index semantics"
  - id: AC-2
    when: "any drawer has a duplicate, missing, boolean, negative, or otherwise malformed chunk_index"
    then: "the scenario returns the existing bounded installed_golden_convo_full_replace FAIL row with one canonical rerun recovery command"
  - id: AC-3
    when: "an export has a missing or duplicate record, or changes an expected ID, text, source provenance, or wing"
    then: "the scenario still returns FAIL after canonicalization"
  - id: AC-4
    when: "the focused direct-conversation regression is inspected and executed"
    then: "coverage remains in the existing release-gate test owner with no new helper module, runner, script, mode, or gate"
  - id: AC-5
    when: "qualification runs the focused scenario across multiple disposable path names, the full non-network suite, and the exact candidate wheel direct gate"
    then: "all three checks exit zero and the exact-wheel installed_golden_convo_full_replace row remains required"
  - id: AC-6
    when: "the implementation and its automated verification execute"
    then: "they use only disposable local scenario data and perform no authenticated AI-client call, credential access, push, tag, release, publication, or live product-data mutation"
out_of_scope:
  - "Changing product export ordering, LanceDB iteration, storage, conversation mining, or any public contract."
  - "Changing gate inventory, adjacent installed scenarios, the thin source-mode consumer, dependencies, workflows, or release commands."
  - "Adding a helper module, runner, script, mode, gate, schema, persisted state, or architecture boundary."
  - "Editing backlog metadata or performing Git finalization, push, tag, release, publication, authenticated AI-client operation, credential access, or live product-data mutation."
contract_policy:
  flow: full_spdd
  reason: "This strict pre-release blocker changes fail-closed qualification semantics at the exact-wheel provider pipeline boundary."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "Valid conversation exports are compared in ascending unique nonnegative integer chunk_index order."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Malformed chunk_index metadata fails through the existing bounded recovery row."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Canonicalization does not weaken exact record, ID, text, provenance, wing, retry, replacement, stream, count, or recovery checks."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The regression extends the existing release-gate owner without adding another implementation or gate surface."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Focused path variants, the full non-network suite, and exact-wheel direct qualification all remain green and required."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Qualification remains credential-free, local, disposable, and non-publishing."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "direct installed conversation export comparison"
      kind: internal
      paths: ["scripts/release_readiness_gate.py"]
      expected_behavior: "Reject malformed index metadata, sort valid drawer records by chunk_index, and run the existing exact semantic comparisons on the canonical sequence."
  invariants:
    - id: INV-1
      statement: "The direct scenario preserves exact nonempty unique IDs, text, canonically resolved source_file provenance, conversations wing, retry equality, replacement state, streams, counts, and one bounded rerun recovery command."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-2
      statement: "Product export order, storage iteration, conversation mining, public interfaces, gate inventory, and adjacent direct scenarios do not change."
      applies_to: ["scripts/release_readiness_gate.py"]
    - id: INV-3
      statement: "Boolean values are rejected as chunk indexes even though bool is an int subclass in Python; accepted indexes are integers, nonnegative, and unique within one export."
      applies_to: ["scripts/release_readiness_gate.py", "tests/test_release_readiness_gate.py"]
    - id: INV-4
      statement: "The release gate executes without external AI clients, authentication, credential inspection, publication, or non-disposable product data."
      applies_to: ["scripts/release_readiness_gate.py"]
  risks:
    - id: RISK-1
      risk: "Sorting before validation could hide duplicate or malformed indexes and admit ambiguous evidence."
      mitigation: "Require type(value) is int, value >= 0, and uniqueness before sorting; route every violation through the existing failure row."
    - id: RISK-2
      risk: "Canonicalization could accidentally weaken semantic comparisons to text-only checks."
      mitigation: "Retain complete retry equality and explicit per-index ID, text, resolved provenance, wing, replacement, count, stream, and stale-record assertions; add mutations for each semantic field."
    - id: RISK-3
      risk: "A broad fix in export or storage could alter public ordering or mask another consumer's assumptions."
      mitigation: "Change only the scenario-local read_drawers owner and its existing parametrized regression; keep product modules untouched."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_readiness_gate.py::test_installed_convo_full_replace_fails_closed -q"
      proves: "The existing direct-gate owner accepts valid per-export row permutations across disposable path variants and rejects malformed indexes plus missing, duplicate, or changed semantic records with bounded recovery."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-2
      owner: configured_runner
      command: 'python scripts/release_readiness_gate.py --installed-golden-wheel "$WHEEL" --json'
      proves: "The configured exact-candidate-wheel gate still executes the direct conversation scenario and requires its installed_golden_convo_full_replace PASS row from a disposable local contour."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-5, AC-6]
    - id: VER-3
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured full non-network gate preserves direct conversation evidence, product export/storage/mining behavior, and adjacent scenarios."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The planned narrow gate and test diff introduces no credential-shaped, authenticated-provider, publication, or private operational material."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: 'python -m pytest tests/ -x -q -m "not needs_network"'
        proves: "The canonical repository regression gate preserves conversation replacement and unrelated non-network behavior after scenario-local canonicalization."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
---

## Design Notes

- Rule Zero outcome: extend `read_drawers` inside `_run_installed_convo_full_replace_scenario`; acceptance is satisfied when valid order permutations pass and malformed or semantically changed exports still fail through the same row.
- Reuse ledger: `scripts/release_readiness_gate.py` owns the direct installed process, export parser, semantic comparison, sanitization, and recovery row; `tests/test_release_readiness_gate.py::test_installed_convo_full_replace_fails_closed` owns its injected-process matrix. The thin consumer and product export/storage/miner are already complete and remain unchanged.
- Options: deletion cannot prove semantic state; product export/storage sorting changes a broader owner and public behavior; a new helper/module creates a duplicate lifecycle; extending the scenario-local parser changes two paths, no interface or persisted state, and rolls back as one local hunk plus test cases. Selected: extend the existing owner.
- DRY/KISS/YAGNI verdict: one parser remains authoritative, no abstraction or dependency is added, and only current qualification acceptance is implemented. The cheapest falsifier is a focused injected export with records ordered `0,2,1` or `2,0,1`; either must return PASS after canonicalization.
- Validate each drawer before sorting: `id` is a nonempty unique string; `text`, `source_file`, and `wing` retain their current string checks; `chunk_index` uses exact integer type, is nonnegative, and is unique. Do not require storage order or add a contiguity rule beyond the current contract.
- Return drawers sorted ascending by `chunk_index` from the existing local parser. Keep retry whole-record equality after canonicalization. Compare initial, changed, and shorter states by canonical index while retaining exact IDs, expected texts, resolved source paths, wing, counts, stale-record absence, streams, and health checks.
- Extend the existing parametrized fixture records with deterministic IDs and chunk indexes. Add valid permutations at more than one disposable scenario path name and negative cases for missing, duplicate, boolean, negative, string/non-integer indexes; missing/duplicate records; and changed ID, text, source, or wing. Preserve the established sanitized detail and exactly one rerun assertion.
- Do not modify `mempalace_code/export.py`, `mempalace_code/convo_miner.py`, storage code, `tests/test_cli_golden_scenarios.py`, inventory, commands, or gate orchestration.
- Command context basis: `pyproject.toml` declares the test root and excludes network/slow tests by default; `scripts/gate_inventory.py` records the exact full non-network and exact-wheel commands; `.github/workflows/ci.yml` confirms repository-root pytest and installed-wheel execution. PLAN inspected these files without executing tests, builds, or wrappers.
- No `docs/quality/incident-class-registry.yaml` exists in the discovered repository filenames, so no incident-class proof block applies.
