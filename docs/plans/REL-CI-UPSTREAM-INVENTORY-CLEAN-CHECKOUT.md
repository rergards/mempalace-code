---
slug: REL-CI-UPSTREAM-INVENTORY-CLEAN-CHECKOUT
status: completed
authority: non_authoritative
goal: "Verify the pinned exact upstream commit inventory from any public clean checkout without relying on developer-local Git objects."
risk: medium
risk_note: "The change moves a release-blocking static check onto a bounded public network read; incomplete, malformed, or unavailable evidence must remain a hard failure."
files:
  - path: scripts/release_public_read.py
    change: "Add one fixed, credential-free GitHub compare-range query that returns a bounded, normalized, complete commit inventory for the manifest-owned upstream pins."
  - path: scripts/upstream_comparison_guard.py
    change: "Replace the checkout-local rev-list dependency with the shared public compare-range reader while preserving exact set equality, 43-commit facts, live-head validation, and fail-closed output."
  - path: scripts/release_preflight.py
    change: "Correct its user-facing network-boundary contract for the default compare read and the optional live branch-head read."
  - path: .github/workflows/ci.yml
    change: "Correct the existing lint-step label to describe the credential-free public read without changing workflow behavior or topology."
  - path: tests/test_release_public_read.py
    change: "Cover the fixed compare endpoint, complete pagination/count proof, normalized unique SHAs, target rejection, and malformed or truncated response failures."
  - path: tests/test_upstream_comparison_guard.py
    change: "Cover clean-checkout inventory success through injected public evidence plus missing, extra, unavailable, malformed, duplicate, and live-head drift failures."
  - path: tests/test_release_preflight.py
    change: "Exercise default preflight delegation through the shared upstream guard for successful public inventory evidence and fail-closed inventory-read errors."
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Document the default compare-range network boundary, exact inventory proof, failure semantics, and one canonical recovery command while retaining the separate live-head request."
  - path: docs/RELEASING.md
    change: "Correct the preflight network-boundary wording and name the same bounded recovery path used by the comparison documentation."
  - path: docs/quality/scorecard.md
    change: "Regenerate the deterministic quality scorecard after focused test changes."
  - path: docs/quality/scorecard.json
    change: "Regenerate the machine-readable deterministic quality scorecard after focused test changes."
acceptance:
  - id: AC-1
    when: "the default upstream guard and release preflight run from a fresh depth-1 public checkout that contains neither pinned upstream Git object"
    then: "both exit successfully after the credential-free compare read proves exact equality with all 43 manifest commits, and the guard reports commit_inventory_exact=true without fetching into or mutating the checkout"
  - id: AC-2
    when: "the focused guard/public-read/preflight checks and the configured hosted Tests workflow run at the implementation SHA"
    then: "the focused checks pass, Python 3.11-3.14 and lint complete past upstream inventory validation, and package completes release preflight before reaching its build and inspection steps"
  - id: AC-3
    when: "the compare read is unavailable, malformed, incomplete, duplicated, or differs from the manifest, or the explicit live-head check reports drift"
    then: "the owning command exits nonzero, never treats missing Git objects or untrusted public evidence as PASS, emits bounded diagnostics, and the public documentation names the request boundary plus one concrete recovery command"
out_of_scope:
  - "Changing the reviewed upstream pins, 43-commit inventory, delta dispositions, source links, capability claims, or live-head acceptance semantics."
  - "Adding fetch-depth settings or repeated upstream Git fetch setup to individual CI jobs, mutating a checkout, caching Git objects, or requiring credentials."
  - "Changing workflow topology, Python versions, package build behavior, release publication, backlog metadata, or runner-owned finalization."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release CI repair changes a release-blocking evidence provider and must preserve bounded credential-free transport and fail-closed inventory semantics."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "A public shallow checkout must prove the exact 43-commit pinned upstream range without possessing upstream Git objects."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Focused checks and every affected hosted test, lint, and package path must proceed beyond upstream inventory validation."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The network boundary, fail-closed behavior, and one recovery command must be accurate and public."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
  surfaces:
    - name: "credential-free upstream compare read"
      kind: internal
      paths: ["scripts/release_public_read.py"]
      expected_behavior: "Allow only the fixed reviewed upstream repository and two full manifest-owned SHAs, perform a bounded HTTPS GET with no ambient credentials, proxies, cookies, redirects, or retries, and normalize only a complete unique commit set."
    - name: "exact upstream comparison guard"
      kind: cli
      paths: ["scripts/upstream_comparison_guard.py"]
      expected_behavior: "Use the shared public compare evidence in default mode, require exact set equality with the manifest inventory, preserve explicit live-head checking, and fail closed with bounded recovery output."
    - name: "upstream evidence documentation"
      kind: internal
      paths: ["docs/UPSTREAM_COMPARISON.md", "docs/RELEASING.md"]
      expected_behavior: "State which default and live checks access GitHub, what they prove, what failures block, and the single operator recovery command."
    - name: "quality scorecard"
      kind: store
      paths: ["docs/quality/scorecard.md", "docs/quality/scorecard.json"]
      expected_behavior: "Remain a deterministic generated reflection of the changed focused test inventory."
  invariants:
    - id: INV-1
      statement: "The manifest and canonical document retain the existing previous/current pins and the exact 43 unique merge-plus-constituent commit inventory."
      applies_to: ["scripts/upstream_comparison_guard.py", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-2
      statement: "Unavailable, incomplete, malformed, duplicated, missing, or extra compare evidence remains a hard failure and never becomes an offline skip or warning-only result."
      applies_to: ["scripts/release_public_read.py", "scripts/upstream_comparison_guard.py"]
    - id: INV-3
      statement: "The explicit live check continues to compare the same pinned commit with the reviewed upstream branch head and fails closed on drift or untrusted responses."
      applies_to: ["scripts/release_public_read.py", "scripts/upstream_comparison_guard.py"]
    - id: INV-4
      statement: "Public reads remain fixed-target, credential-free, proxy-free, cookie-free, redirect-free, bounded, read-only, and non-retrying; neither guard nor preflight mutates Git state."
      applies_to: ["scripts/release_public_read.py", "scripts/upstream_comparison_guard.py"]
    - id: INV-5
      statement: "CI workflow topology and per-job checkout configuration remain unchanged; all callers reuse the existing guard and public-read owners."
      applies_to: ["scripts/release_public_read.py", "scripts/upstream_comparison_guard.py"]
  risks:
    - id: RISK-1
      risk: "GitHub compare responses can be truncated or paginated, allowing an incomplete set to look exact."
      mitigation: "Require an exact integer total, bounded page completeness, unique full SHAs, expected base/head identity, and equality between normalized count and returned commit rows before the guard compares sets."
    - id: RISK-2
      risk: "A new network call could inherit credentials, proxies, redirects, or arbitrary target input."
      mitigation: "Extend the existing closed-set release_public_read transport and its hostile fixtures instead of introducing a second HTTP or Git-fetch owner."
    - id: RISK-3
      risk: "Unit fixtures could mask the same clean-checkout failure while hosted jobs still stop early."
      mitigation: "Exercise the real guard and default preflight commands after implementation, retain the complete configured suite, and require a hosted Tests run at the exact implementation SHA before release evidence is accepted."
    - id: RISK-4
      risk: "Documentation could continue describing default preflight as local and network-free."
      mitigation: "Update both canonical upstream and release documents together and retain documentation-drift verification."
  verification:
    - id: VER-1
      owner: provider
      command: "python -m pytest tests/test_release_public_read.py tests/test_upstream_comparison_guard.py tests/test_release_preflight.py -q"
      proves: "Focused local fixtures cover clean-checkout success, exact inventory equality, fixed-target transport, default preflight delegation, and all decision-changing failure cases without requiring live network access."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-2
      owner: provider
      command: "python scripts/upstream_comparison_guard.py --json"
      proves: "The real default CLI obtains bounded public compare evidence from a checkout-independent source and reports exact 43-commit equality or fails with the documented recovery."
      acceptance_ids: [AC-1, AC-3]
    - id: VER-3
      owner: provider
      command: "python scripts/release_preflight.py"
      proves: "The real default package preflight reuses the corrected guard and reaches a passing upstream_comparison row without local upstream Git objects."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-4
      owner: configured_runner
      command: 'python -m pytest tests/ -x -q -m "not needs_network"'
      proves: "The exact configured non-network suite no longer depends on developer-local upstream objects and matches the Python matrix test surface."
      acceptance_ids: [AC-1, AC-2, AC-3]
    - id: VER-5
      owner: configured_runner
      command: "python scripts/quality_scorecard.py --check"
      proves: "The canonical generated scorecard matches the changed focused-test inventory."
      acceptance_ids: [AC-2]
    - id: VER-6
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The canonical comparison and release documentation retain synchronized commands and accurately expose the network and recovery boundary."
      acceptance_ids: [AC-3]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "ruff check mempalace_code/ tests/ scripts/"
        proves: "The exact configured lint gate accepts the public-read, guard, and focused test changes used by the hosted lint job."
        acceptance_ids: [AC-2]
      - id: REG-2
        owner: configured_runner
        command: "ruff format --check mempalace_code/ tests/ scripts/"
        proves: "The exact configured format gate accepts the changed Python surfaces used by the hosted lint job."
        acceptance_ids: [AC-2]
---

## Design Notes

- Rule Zero comparison: changing `fetch-depth` on fork checkouts cannot supply commits that exist only in the separate upstream repository. Adding `git fetch` to each test, lint, and package job duplicates setup and mutates every checkout. A second direct HTTP client duplicates transport policy. Extend `scripts/release_public_read.py`, the existing fixed-target credential-free network owner, and let every current caller continue through `scripts/upstream_comparison_guard.py`.
- Add one reviewed-upstream compare query keyed by the fixed repository and two validated full SHAs. Normalize the GitHub compare response into a unique commit set only after proving the response base/head, exact total, complete bounded pagination, row shape, and absence of duplicates. The cheapest decisive falsifier is a fixture whose declared total exceeds the returned unique rows; it must fail before inventory comparison.
- Replace checkout-local `git rev-list previous..current` as the production evidence source. Do not retain local-object success as an alternate authority because it would keep developer and clean-checkout behavior divergent. Tests may inject normalized public results; production always uses the shared public reader.
- Preserve the manifest as the grouped decision owner and compare the flattened merge-group plus constituent set with the independently returned upstream set. Exact success remains 43 unique SHAs with zero missing and zero extra commits; no missing-object, offline, cached, warning-only, or count-only success path is permitted.
- Keep live-head validation separate. Default guard/preflight performs the compare-range request needed for exact inventory. `--check-live` additionally performs the existing reviewed-branch head request. Each request stays fixed-target, bounded, credential-free, proxy-free, redirect-free, non-retrying, and read-only.
- Document the changed boundary in both public owners: default guard/preflight now requires the bounded compare read; live mode adds the branch-head read. Retain one concrete recovery command, `python scripts/upstream_comparison_guard.py --check-live --json`, and state that network or evidence failure blocks rather than passes.
- Do not change `.github/workflows/ci.yml` topology, checkout configuration, or runtime behavior: its test, lint, and package jobs already invoke the owning test/guard/preflight surfaces. Correcting the stale step label is documentation-only. Hosted completion at the exact implementation SHA is required release evidence; local commands prove behavior and workflow prerequisites but do not claim an unobserved hosted result.
- Regenerate only the two canonical quality scorecard artifacts after focused test changes. Preserve all unrelated scorecard fields and do not hand-edit generated counts.
- Command context basis: `pyproject.toml` declares Python 3.11+ and the repository-root pytest/Ruff tools; `scripts/gate_inventory.py` and `.claude/skills/verify/INSTRUCTIONS.md` publish the exact full non-network suite, Ruff, format, scorecard, and docs-drift commands; `.github/workflows/ci.yml` runs the same source surfaces in Python 3.11-3.14, lint, and package jobs.
- No `docs/quality/incident-class-registry.yaml` exists in this tree. This CI evidence-provider repair matches no declared incident class, so no top-level `incident_proof` block applies.
- PLAN did not run tests, builds, validation wrappers, live guard/preflight requests, Git fetches, external AI clients, Git finalization, source verification, or publication.
