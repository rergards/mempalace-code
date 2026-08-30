---
slug: REL-CI-UPSTREAM-INVENTORY-CLEAN-CHECKOUT
status: active
authority: non_authoritative
goal: "Make exact upstream inventory and release preflight pass from a one-parent squash candidate using one reviewed static trust anchor."
risk: medium
risk_note: "The change repairs a release-blocking CI gate; weak anchor coverage could admit stale inventory, while a history or network dependency would keep squash candidates broken."
files:
  - path: scripts/upstream_comparison_guard.py
    change: "Validate a versioned SHA-256 trust anchor over canonical repository, branch, full endpoint pins, count, and the sorted full manifest inventory without resolving local Git history."
  - path: docs/quality/upstream-comparison.json
    change: "Record the reviewed anchor algorithm, version, count, and digest for the current pinned upstream inventory."
  - path: .github/workflows/ci.yml
    change: "Keep the package release-preflight step as the sole workflow owner of the static upstream gate and remove the duplicate lint-job invocation."
  - path: tests/test_upstream_comparison_guard.py
    change: "Cover valid anchors, squash-checkout independence, field and inventory substitutions, malformed anchors, duplicate inventory ownership, and bounded recovery output."
  - path: tests/test_release_preflight.py
    change: "Prove release preflight delegates to the static guard and propagates its squash-candidate success and fail-closed result without network or credentials."
  - path: tests/test_gate_inventory.py
    change: "Assert the CI workflow has exactly one upstream gate owner through the package release-preflight step."
  - path: docs/quality/scorecard.json
    change: "Regenerate the machine-readable quality scorecard after the focused test and workflow inventory changes."
  - path: docs/quality/scorecard.md
    change: "Regenerate the human-readable quality scorecard from the same canonical generator."
acceptance:
  - id: AC-1
    when: "the static upstream guard and release preflight run in a clean fixture checkout whose sole parent is public main and whose tree contains the reviewed release data"
    then: "both commands exit 0 with exact inventory reported, without requiring either pinned upstream commit as a local Git object."
  - id: AC-2
    when: "the shipped reviewed trust anchor is inspected through guard JSON output and focused fixtures"
    then: "it covers the canonical repository, branch, previous and current full pins, algorithm, version, count, and the lexically sorted set of full inventory SHAs."
  - id: AC-3
    when: "a fixture substitutes the repository, branch, either endpoint pin, count, or one inventory SHA while leaving the other reviewed fields and anchor unchanged"
    then: "the static guard exits nonzero and identifies the trust-anchor mismatch."
  - id: AC-4
    when: "a fixture declares the same full inventory SHA more than once"
    then: "the static guard exits nonzero, reports the duplicate ownership, and prints exactly one recovery command."
  - id: AC-5
    when: "the guard, release-preflight path, and CI workflow inventory are exercised with recording seams and workflow-shape assertions"
    then: "there is one static guard implementation and one package/preflight workflow owner, with zero credential, token, external AI client, network, or hidden authenticated calls."
  - id: AC-6
    when: "the focused upstream/preflight/workflow checks and configured repository quality commands run after implementation"
    then: "the focused checks, full non-network suite, documentation drift, public safety, Ruff lint and format, and actionlint all exit 0."
out_of_scope:
  - "Live upstream refresh or branch-head lookup behavior behind --check-live."
  - "Adding a second guard, workflow gate owner, network fallback, credential path, external AI client, or authenticated dependency."
  - "Changing the reviewed upstream endpoints, delta decisions, or release documentation beyond recording the derived static anchor."
  - "Adopting the broader release_public_read.py and documentation changes from 371e22f0."
  - "Editing backlog metadata or runner-owned Git state."
contract_policy:
  flow: full_spdd
  reason: "Strict release-blocking CI work changes a fail-closed static trust boundary and its workflow ownership."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "A clean one-parent squash candidate must pass exact static upstream inventory and release preflight without the upstream range in local Git history."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The reviewed anchor must bind repository, branch, both full pins, algorithm, version, count, and sorted full inventory SHAs."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Changing any bound identity, endpoint, count, or inventory SHA without refreshing the anchor must fail closed."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Duplicate inventory declarations must fail closed with one recovery command."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The release path must retain one static guard and one workflow owner with no credential, AI-client, network, or authenticated dependency."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "Focused behavior checks and every named repository quality gate must pass."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
  surfaces:
    - name: "Static upstream comparison gate"
      kind: cli
      paths: ["scripts/upstream_comparison_guard.py", "docs/quality/upstream-comparison.json"]
      expected_behavior: "Validate the reviewed inventory anchor entirely from checked-out files and emit deterministic success, failure, facts, and recovery output."
    - name: "Package release-preflight workflow owner"
      kind: internal
      paths: [".github/workflows/ci.yml"]
      expected_behavior: "Run the existing release_preflight.py package step as the sole CI owner that reaches the static upstream guard."
    - name: "Upstream gate regression evidence"
      kind: internal
      paths: ["tests/test_upstream_comparison_guard.py", "tests/test_release_preflight.py", "tests/test_gate_inventory.py"]
      expected_behavior: "Exercise squash-candidate success, anchor tampering and duplicate failures, credential-free delegation, and single workflow ownership."
    - name: "Generated quality scorecard"
      kind: internal
      paths: ["docs/quality/scorecard.json", "docs/quality/scorecard.md"]
      expected_behavior: "Remain current with the canonical scorecard generator after test and workflow inventory changes."
  invariants:
    - id: INV-1
      statement: "Default upstream comparison remains stdlib-only, deterministic, network-free, credential-free, and non-mutating."
      applies_to: ["scripts/upstream_comparison_guard.py", "docs/quality/upstream-comparison.json"]
    - id: INV-2
      statement: "The existing --check-live opt-in remains the only upstream network path and keeps its current read-only branch-head contract."
      applies_to: ["scripts/upstream_comparison_guard.py", "tests/test_upstream_comparison_guard.py"]
    - id: INV-3
      statement: "scripts/release_preflight.py remains the existing package workflow owner and continues to aggregate the static guard result with the other local release checks."
      applies_to: [".github/workflows/ci.yml", "tests/test_release_preflight.py"]
    - id: INV-4
      statement: "Inventory declarations continue to require full lowercase 40-hex SHAs with unique ownership across merge-group and constituent entries."
      applies_to: ["scripts/upstream_comparison_guard.py", "tests/test_upstream_comparison_guard.py"]
  risks:
    - id: RISK-1
      risk: "Hashing only the inventory would allow stale or mistaken repository, branch, or range metadata to retain a passing digest."
      mitigation: "Define one canonical payload that includes algorithm/version, canonical repository, branch, both full pins, declared count, and sorted full SHAs before SHA-256 comparison."
    - id: RISK-2
      risk: "Converting inventory collection to a public API call would restore candidate failures when the network or API is unavailable."
      mitigation: "Reject the 371e22f0 public-read approach and keep default evaluation limited to checked-out manifest and document bytes."
    - id: RISK-3
      risk: "Set conversion could hide duplicate SHA declarations before the anchor is evaluated."
      mitigation: "Run existing occurrence validation before canonicalization and cover duplicates within and across inventory owners."
    - id: RISK-4
      risk: "Leaving both the lint guard step and package preflight would create two workflow owners with divergent future behavior."
      mitigation: "Remove the lint-job invocation and assert exactly one workflow path reaches the guard through release_preflight.py."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python -m pytest tests/test_upstream_comparison_guard.py -q"
      proves: "Static happy path, full anchor coverage, every bound-field substitution, malformed data, duplicate ownership, and one-command recovery behavior."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: configured_runner
      command: "python -m pytest tests/test_release_preflight.py tests/test_gate_inventory.py -q"
      proves: "Release preflight propagates static guard results and CI retains exactly one package/preflight workflow owner without hidden network or credential setup."
      acceptance_ids: [AC-1, AC-5]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/upstream_comparison_guard.py --json"
      proves: "The repository's shipped reviewed manifest passes the default static guard from the current checkout without upstream Git history or network access."
      acceptance_ids: [AC-1, AC-2, AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/release_preflight.py"
      proves: "The existing package preflight owner accepts the shipped static upstream anchor along with its other local release checks."
      acceptance_ids: [AC-1, AC-5]
    - id: VER-5
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The configured full non-network suite preserves package and release behavior after the static gate change."
      acceptance_ids: [AC-6]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "Canonical public verification and release documentation remain synchronized."
      acceptance_ids: [AC-6]
    - id: VER-7
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "Changed tracked and staged artifacts contain no private path, secret-like token, or local-only release evidence."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-8
      owner: configured_runner
      command: "ruff check mempalace_code/ tests/ scripts/"
      proves: "Python source and tests satisfy the configured Ruff lint gate."
      acceptance_ids: [AC-6]
    - id: VER-9
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "Python source and tests satisfy the configured Ruff formatting gate."
      acceptance_ids: [AC-6]
    - id: VER-10
      owner: configured_runner
      command: "actionlint .github/workflows/*.yml"
      proves: "The CI workflow remains syntactically valid after consolidating upstream gate ownership."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-11
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The generated scorecard pair is current after focused tests and workflow ownership change."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python -m pytest tests/test_upstream_comparison_guard.py tests/test_release_preflight.py tests/test_gate_inventory.py -q"
        proves: "The complete focused regression slice preserves static guard output, release-preflight aggregation, and single CI ownership across success and failure cases."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Extend the existing manifest and `scripts/upstream_comparison_guard.py`; do not add a helper service, second guard, state store, or network fallback.
- Use an anchor object with an explicit algorithm name, format version, declared inventory count, and lowercase hexadecimal digest. Build the canonical digest payload from the algorithm/version plus `canonical_repository`, `branch`, `previous_commit`, `commit`, `count`, and the lexically sorted full inventory returned from validated delta decisions. Serialize with fixed JSON separators and sorted keys before SHA-256 hashing.
- Validate SHA shape and duplicate ownership before constructing the sorted inventory. Validate the anchor object strictly: exact supported algorithm/version, integer count excluding booleans, count equality, lowercase full digest, and constant-time digest equality. Unknown or malformed anchor fields fail closed.
- Keep `manifest_commit_inventory()` as the sole inventory owner. Replace default `git rev-list previous..current` comparison with the checked-in reviewed anchor comparison so a one-parent squash checkout does not need unreachable upstream objects. Remove the obsolete local-history collector and its subprocess dependency if no remaining live path uses them.
- Keep JSON facts explicit: report algorithm, version, declared and derived count, computed digest, and `commit_inventory_exact`. Do not emit credentials, environment state, or live-provider data.
- Preserve one context-free recovery line through the existing CLI footer. Anchor mismatch and duplicate failures should name the same canonical recovery command once; JSON output should carry the error and recovery fact without duplicating command text across errors.
- Keep `scripts/release_preflight.py` unchanged unless a focused test exposes an actual propagation gap. Its existing static subprocess call is the behavioral owner; `.github/workflows/ci.yml` should remove only the separate lint-job guard step and retain the package `Release metadata preflight` step.
- Add a temporary Git-repository fixture for the one-parent boundary only where needed to prove the checkout shape; the guard success itself must derive solely from checked-out content, so deleting or omitting the pinned Git objects must not affect the result.
- Compare result: 371e22f0 is unsuitable because it makes the default guard perform a public GitHub compare request, changes static release semantics, and adds unrelated public-read/docs surfaces. Reuse none of that network path; retain only its useful failure-shape lesson that malformed or duplicate inventory evidence must fail closed.
- Command context basis: all commands run from repository root. `pyproject.toml` provides pytest and Ruff development dependencies; `.github/workflows/ci.yml` establishes `python scripts/release_preflight.py` as the package owner and the exact actionlint invocation; `.claude/skills/verify/INSTRUCTIONS.md` and `docs/quality/scorecard.json` record the configured full non-network, Ruff, and public-safety commands. No incident-class registry exists in this checkout, so no incident proof block applies.
