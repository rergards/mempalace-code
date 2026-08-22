---
slug: UPSTREAM-DELTA-REVIEW-3E56979F
status: completed
authority: non_authoritative
goal: "Refresh the evidence-backed upstream develop comparison through 3e56979f and keep its public document and manifest synchronized for v1.13.5 admission."
risk: medium
risk_note: "An incomplete or weakly evidenced delta classification could admit a release while missing an upstream security or reliability behavior."
files:
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Advance the reviewed snapshot, pinned source links, exact-range delta inventory, and fork dispositions through upstream commit 3e56979f."
  - path: docs/quality/upstream-comparison.json
    change: "Advance the machine-readable pin and synchronized source, capability, and delta-decision evidence for the same exact range."
acceptance:
  - id: AC-1
    when: "the canonical comparison snapshot and manifest are inspected after the refresh"
    then: "both pin upstream develop at 3e56979fb456c7478a4b57414027873bd78f2d37 and record 639c69a1d6be41a04964ceb72a3d29d6f45629e9 as the previous commit."
  - id: AC-2
    when: "the immutable 639c69a1d6be41a04964ceb72a3d29d6f45629e9...3e56979fb456c7478a4b57414027873bd78f2d37 compare output is reconciled with the manifest"
    then: "every relevant changed behavior has exactly one evidence-backed adopted, equivalent-local, migration-only, deferred, or irrelevant disposition."
  - id: AC-3
    when: "the refreshed delta decisions and fork stance are inspected"
    then: "FIFO and irregular-file handling, indexing behavior, Chroma migration-only support, and signal or lease behavior are each explicitly evaluated without weakening existing fork protections."
  - id: AC-4
    when: "python scripts/upstream_comparison_guard.py --check-live --json is run against a matching live head, a mismatching head, or an unusable response"
    then: "it exits zero only for the matching 3e56979f pin and fails closed with bounded drift or response evidence otherwise."
  - id: AC-5
    when: "the static comparison guard, documentation drift guard, and configured public-safety scan inspect the refreshed artifacts"
    then: "the document and manifest agree on pins, links, capabilities, and dispositions and contain no private or machine-local data."
out_of_scope:
  - "Speculative runtime changes without a concrete release-critical gap proven by the exact upstream range; a proven gap requires a revised plan naming its owner and regression tests."
  - "Running upstream code, claiming upstream runtime compatibility, or benchmarking upstream behavior."
  - "Changing the historical April 2026 audit in docs/UPSTREAM_HARDENING.md."
  - "Editing backlog metadata, release bookkeeping, or runner-owned finalization artifacts."
contract_policy:
  flow: full_spdd
  reason: "Strict pre-release review governs security-sensitive upstream drift and release admission evidence."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: strict
  requirements:
    - id: REQ-1
      statement: "The canonical snapshot must pin upstream develop at the exact requested commit and preserve the replaced pin."
      source: "AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "Every relevant behavior in the exact upstream range must have one closed-set disposition with public upstream evidence and local evidence when the fork claims equivalent or adopted protection."
      source: "AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "The review must explicitly retain the named file-safety, indexing, Chroma, and signal or lease boundaries."
      source: "AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "The live guard must accept the exact reviewed head and fail closed on drift or an untrusted response."
      source: "AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "The public document and manifest must remain synchronized and public-safe."
      source: "AC-5"
      acceptance_ids: [AC-5]
  surfaces:
    - name: "canonical upstream comparison"
      kind: internal
      paths: ["docs/UPSTREAM_COMPARISON.md"]
      expected_behavior: "Publishes the exact reviewed range, pinned primary sources, complete delta disposition table, fork stance, and evidence limits."
    - name: "upstream comparison manifest"
      kind: store
      paths: ["docs/quality/upstream-comparison.json"]
      expected_behavior: "Machine-checkably mirrors the snapshot, source links, capability inventory, and one closed-set decision per relevant delta behavior."
  invariants:
    - id: INV-1
      statement: "LanceDB remains the sole runtime backend and ChromaDB remains migration input only."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-2
      statement: "Existing fork protections may be reused as equivalent local evidence only when the named module or test exists; no protection is weakened to match upstream implementation details."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
    - id: INV-3
      statement: "All upstream claims remain limited to immutable pinned public sources and repository review; the snapshot makes no runtime, benchmark, or interoperability claim."
      applies_to: ["docs/UPSTREAM_COMPARISON.md"]
    - id: INV-4
      statement: "The manifest and document advance together, with every tracked source URL pinned to the same full reviewed SHA and the compare URL spanning previous_commit through commit."
      applies_to: ["docs/UPSTREAM_COMPARISON.md", "docs/quality/upstream-comparison.json"]
  risks:
    - id: RISK-1
      risk: "A file-only inventory could miss a meaningful behavior change inside a previously tracked source."
      mitigation: "Review the complete immutable compare range at commit and path level, then account for each relevant behavior in a delta-decision row."
    - id: RISK-2
      risk: "An equivalent-local stance could overstate protection after a local predicate was renamed or removed."
      mitigation: "Name concrete repository-relative modules or pytest nodes; the existing guard rejects missing files and missing named tests."
    - id: RISK-3
      risk: "Moving only the pin could hide source-link, capability, or disposition drift."
      mitigation: "Update both canonical artifacts atomically and retain the existing static consistency guard plus focused fail-closed tests."
    - id: RISK-4
      risk: "Public review artifacts could capture local paths, private remotes, credentials, or non-public incident details."
      mitigation: "Use only public GitHub sources and run the configured tracked/staged public-safety scan before handoff."
  verification:
    - id: VER-1
      owner: provider
      command: "python scripts/upstream_comparison_guard.py --check-live --json"
      proves: "The refreshed manifest and document are structurally synchronized, current, pinned to the live develop head, and expose the expected exact-range facts and dispositions."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-2
      owner: provider
      command: "PYTHONPATH=. pytest tests/test_upstream_comparison_guard.py -q"
      proves: "Focused hermetic coverage accepts a synchronized snapshot and rejects unchanged pins, broken compare ranges, stale source links, missing or duplicate dispositions, unsupported Chroma runtime claims, live drift, malformed replies, and fetch failure."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The configured documentation gate reports no cross-document contract drift after the canonical snapshot refresh."
      acceptance_ids: [AC-5]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --tracked --staged"
      proves: "The configured repository scanner rejects private paths, credential-shaped values, and orchestration residue in the refreshed public artifacts."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: false
    no_behavior_change_exception: "The planned repository changes are comparison data and documentation only; the focused guard test and unchanged configured gates cover their fail-closed contract."
    checks: []
---

## Design Notes

- Start from the immutable compare range `639c69a1d6be41a04964ceb72a3d29d6f45629e9...3e56979fb456c7478a4b57414027873bd78f2d37`. Record commit-level and changed-path evidence before classifying behavior; neither upstream object is available in the fork worktree's current object database.
- Preserve the existing closed set: `adopted`, `equivalent-local`, `migration-only`, `deferred`, and `irrelevant`. Release-critical rows must cite a tracked public upstream file. `adopted` and `equivalent-local` rows must name an existing repository-relative module or pytest node.
- Advance `previous_commit` to `639c69a1d6be41a04964ceb72a3d29d6f45629e9`, `commit` to `3e56979fb456c7478a4b57414027873bd78f2d37`, and update both review dates, the compare URL, every pinned source URL, capability sources, and delta decisions as one synchronized change.
- Explicitly check changed upstream paths and behavior for FIFO or other non-regular inputs and outputs, indexing or transcript-discovery semantics, Chroma runtime versus migration-only boundaries, and SIGTERM, SIGHUP, signal, lease, or retry behavior. Preserve a row or stance paragraph for each named boundary even when the range does not change the fork decision.
- Reuse `mempalace_code/source_io.py`, split-output guards, migration smoke/error tests, watcher ownership tests, and existing signal or lease predicates only after confirming the exact named evidence still matches the upstream behavior being classified.
- If the range proves a release-critical fork gap, stop before editing runtime code. Revise this plan with the exact runtime owner, test files, behavioral AC, and regression commands; do not hide a behavior change inside a documentation-only review.
- Keep `docs/UPSTREAM_HARDENING.md` historical. Refresh only the canonical current snapshot and its manifest.
- Command context basis: `.github/workflows/upstream-drift.yml` and `.github/workflows/publish.yml` use the exact live guard; `.github/workflows/ci.yml` owns the exact static comparison, documentation-drift, and tracked/staged public-safety commands; `tests/test_upstream_comparison_guard.py` already covers matching, drift, malformed-response, missing-disposition, source-link, and Chroma-boundary cases.
