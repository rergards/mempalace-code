---
slug: UPSTREAM-COMPARISON-E8098348
goal: "Refresh the canonical upstream comparison through e8098348 with an exact, evidence-backed 47-commit review that restores truthful release admission."
risk: medium
risk_note: "The change is documentation and snapshot data only, but that data is a release-admission authority; an omitted commit, false equivalence, or stale assertion can incorrectly block or admit v1.13.5."
files:
  - path: docs/quality/upstream-comparison.json
    change: "Advance the machine-readable pin, exact inventory anchor, source-local capability claims, and dispositions for a9f345cc...e8098348."
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Synchronize the reviewed snapshot, 12-group inventory, source links, 3.9.0 capability wording, classifications, and evidence limits."
  - path: tests/test_upstream_comparison_guard.py
    change: "Move only the canonical inventory snapshot expectations from 43 commits and 16 groups to 47 commits and 12 groups, preserving the existing helper and guard behavior coverage."
  - path: tests/test_release_preflight.py
    change: "Move the existing static release-preflight detail assertion from manifest_inventory_commits=43 to manifest_inventory_commits=47."
acceptance:
  - id: AC-1
    when: "the refreshed manifest is emitted by the static or live upstream guard"
    then: "it pins e8098348ddfce59964fe536e5deffb81da579e6b, records a9f345cc63254eb4dea7abad36963b85c9f8453a as previous_commit, and reports review date 2026-08-31."
  - id: AC-2
    when: "the guard and focused inventory snapshot output reconcile the immutable a9f345cc...e8098348 range"
    then: "the manifest and document account for all 47 commits exactly once across 12 first-parent merge groups, with matching pinned links, SHA-256 anchor, release-critical flags, capability/version/count claims, and required local predicates; missing, duplicate, or substituted commits fail."
  - id: AC-3
    when: "the update-awareness disposition and its local predicates are inspected through the focused guard output"
    then: "update awareness is equivalent-local through disabled-by-default version checks, explicit status/check/apply paths, safe install defaults, and existing focused predicates, while no upstream runtime implementation or MCP cached-status compatibility claim is introduced."
  - id: AC-4
    when: "the pinned capability sources and rendered comparison are inspected"
    then: "README and Claude wording report 45 upstream MCP tools, Codex wording reports 44, and the fork remains independently described as 29 full-profile and four minimal-profile tools."
  - id: AC-5
    when: "the focused comparison-guard test diff and test output are inspected"
    then: "tests/test_upstream_comparison_guard.py changes only canonical 43-to-47 and 16-to-12 snapshot expectations, with no new helper, guard, or test owner."
  - id: AC-6
    when: "the static/live guards, focused upstream and release-preflight tests, docs drift, public safety, formatting, and diff checks run"
    then: "every check exits zero against the synchronized e8098348 snapshot."
  - id: AC-7
    when: "independent review inspects the exact-range classifications and machine-readable guard evidence"
    then: "it confirms zero unresolved release-critical drift or reports the exact blocking commit, affected local owner, and failed predicate."
out_of_scope:
  - "Importing upstream update, hub, HTTP MCP, logstream, Qdrant, sqlite_exact, alternate-backend, or EmbeddingGemma runtime behavior."
  - "Adding a capability, guard, helper, schema, service, test owner, or release behavior."
  - "Normalizing the upstream 45-versus-44 source discrepancy or changing the fork's 29/full and four/minimal contracts."
  - "Editing unrelated documentation or tests, backlog metadata, release tooling, runtime source, or generated quality artifacts."
  - "Cherry-picking rejected draft commit 5360b2227d3acb8544af59f2627eab9105b705e1 wholesale."
  - "Staging, committing, tagging, publishing, pushing, or accessing release credentials."
contract_policy:
  flow: full_spdd
  reason: "A standard release-blocker refresh changes the evidence consumed by fail-closed upstream and pre-tag admission gates."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "The canonical manifest must advance to the requested immutable upstream pin, previous pin, and review date."
      source: "current backlog contract AC-1"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "The manifest and document must own one exact 47-commit inventory across 12 first-parent groups with synchronized evidence and classifications."
      source: "current backlog contract AC-2"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Upstream update awareness must be classified as equivalent-local using existing opt-in version-check and guarded update owners without claiming MCP shape compatibility."
      source: "current backlog contract AC-3"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Pinned upstream tool-count claims must preserve the README/Claude 45 versus Codex 44 discrepancy and the fork's independent 29/four counts."
      source: "current backlog contract AC-4"
      acceptance_ids: [AC-4]
    - id: REQ-5
      statement: "Existing comparison-guard snapshot coverage must advance without a new helper or test owner."
      source: "current backlog contract AC-5"
      acceptance_ids: [AC-5]
    - id: REQ-6
      statement: "All existing comparison, release, documentation, public-safety, formatting, and diff gates must remain green."
      source: "current backlog contract AC-6"
      acceptance_ids: [AC-6]
    - id: REQ-7
      statement: "Independent review must close every release-critical classification or identify the exact blocker."
      source: "current backlog contract AC-7"
      acceptance_ids: [AC-7]
  surfaces:
    - name: "upstream comparison manifest"
      kind: store
      paths: ["docs/quality/upstream-comparison.json"]
      expected_behavior: "Stores the e8098348 pin, immutable source references, exact inventory anchor, source-local capabilities, and one closed-set disposition for every merge group."
    - name: "canonical upstream comparison"
      kind: internal
      paths: ["docs/UPSTREAM_COMPARISON.md"]
      expected_behavior: "Renders the same snapshot, inventory, capability claims, local boundaries, and recovery evidence for release review."
  invariants:
    - id: INV-1
      statement: "No upstream runtime code, release behavior, or new local capability is imported by this comparison refresh."
      applies_to: ["docs/quality/upstream-comparison.json", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-2
      statement: "The fork's full profile remains 29 tools and its portable minimal profile remains exactly four tools."
      applies_to: ["docs/quality/upstream-comparison.json", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-3
      statement: "The upstream README/Claude 45-tool wording and Codex 44-tool wording remain distinct pinned source-local claims."
      applies_to: ["docs/quality/upstream-comparison.json", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-4
      statement: "Hub, HTTP MCP, logstream, Qdrant, sqlite_exact, alternate-backend, and EmbeddingGemma surfaces remain architecturally absent and cannot receive local compatibility predicates."
      applies_to: ["docs/quality/upstream-comparison.json", "docs/UPSTREAM_COMPARISON.md"]
    - id: INV-5
      statement: "The existing guard implementation, test helpers, release-preflight behavior, and release tooling remain unchanged."
      applies_to: ["tests/test_upstream_comparison_guard.py", "tests/test_release_preflight.py"]
  risks:
    - id: RISK-1
      risk: "A merge or constituent commit is omitted, duplicated, or assigned to multiple dispositions."
      mitigation: "Reconcile the immutable public range into 12 first-parent groups, derive the 47-SHA set once, and regenerate the versioned SHA-256 anchor from that exact manifest inventory."
    - id: RISK-2
      risk: "Update awareness is repeated from the rejected draft as irrelevant despite established local owners."
      mitigation: "Use equivalent-local and cite focused predicates from tests/test_version_check.py and tests/test_updater.py for opt-in, fail-closed, read-only status/check, confirmation, and disabled scheduler behavior."
    - id: RISK-3
      risk: "Upstream MCP cached-status or tool-count wording is overstated as a local compatibility contract."
      mitigation: "Separate update outcomes from protocol shape, keep MCP cached status outside the equivalence claim, and preserve each pinned source's 45 or 44 count verbatim."
    - id: RISK-4
      risk: "Backend, model, hub, or logstream changes are treated as local gaps despite having no matching owner."
      mitigation: "Classify them as irrelevant with an explicit absent-architecture rationale and no local predicates."
    - id: RISK-5
      risk: "The manifest count changes while a release-preflight snapshot remains at 43."
      mitigation: "Update the directly coupled tests/test_release_preflight.py detail assertion to 47 alongside the comparison guard's canonical snapshot expectations."
  verification:
    - id: VER-1
      owner: configured_runner
      command: "python scripts/upstream_comparison_guard.py --check-live --json"
      proves: "Static document/manifest agreement and the live develop pin resolve to e8098348 with the exact anchored inventory, source claims, dispositions, and release-critical evidence required for independent review."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-6, AC-7]
    - id: VER-2
      owner: provider
      command: "python -m pytest tests/test_upstream_comparison_guard.py tests/test_release_preflight.py -q"
      proves: "Focused upstream and release-preflight behavior accepts the 47-commit canonical snapshot and retains fail-closed coverage for stale, malformed, missing, duplicate, and substituted inventory evidence."
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6]
    - id: VER-3
      owner: configured_runner
      command: "python scripts/docs_drift_guard.py"
      proves: "The refreshed comparison introduces no cross-document contract drift."
      acceptance_ids: [AC-3, AC-4, AC-6]
    - id: VER-4
      owner: configured_runner
      command: "python scripts/public_safety_scan.py --committed --tracked --staged"
      proves: "Tracked, staged, and committed artifacts contain no credential-shaped values, private paths, or orchestration residue."
      acceptance_ids: [AC-6]
    - id: VER-5
      owner: configured_runner
      command: "ruff format --check mempalace_code/ tests/ scripts/"
      proves: "The modified Python snapshot assertions preserve repository formatting."
      acceptance_ids: [AC-5, AC-6]
    - id: VER-6
      owner: configured_runner
      command: "git diff --check"
      proves: "The implementation diff has no whitespace errors."
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        owner: configured_runner
        command: "python scripts/upstream_comparison_guard.py"
        proves: "The network-free release-preflight data contract still accepts the synchronized manifest/document pair and emits the reviewed 47-commit inventory."
        acceptance_ids: [AC-1, AC-2, AC-5, AC-6]
---

## Design Notes

- Review exactly `a9f345cc63254eb4dea7abad36963b85c9f8453a...e8098348ddfce59964fe536e5deffb81da579e6b` from immutable public sources. The local worktree contains the old endpoint but not the new upstream object, so the implementation must use the bounded public compare/source reads rather than infer commit contents locally.
- Replace the prior-range delta inventory with the new range's 12 first-parent merge groups. Assign every merge and constituent commit to exactly one `delta_decisions` row, then derive the 47-entry anchor with the guard's existing inventory ordering and `sha256` version 1 contract. Do not carry prior-range commits into the new anchor.
- Set `commit` to `e8098348ddfce59964fe536e5deffb81da579e6b`, `previous_commit` to `a9f345cc63254eb4dea7abad36963b85c9f8453a`, `reviewed_date` to `2026-08-31`, and advance the compare ref, tree/blob URLs, changelog release wording, plugin metadata version, capability IDs/sources, and document snapshot in one synchronized edit.
- Treat commit `5360b2227d3acb8544af59f2627eab9105b705e1` only as rejected historical evidence. Re-review its grouping against the immutable range; do not reuse its classifications or patch wholesale.
- Classify upstream update awareness as `equivalent-local`. Reuse the existing version-check and updater owners and cite focused predicates such as `tests/test_version_check.py::test_fresh_non_tty_automatic_check_does_not_run`, `tests/test_version_check.py::test_invalid_env_var_fails_closed`, `tests/test_updater.py::TestUpdaterCli::test_status_reports_eligibility_provenance_and_next_run_without_mutation` or the exact owning class-qualified node, `tests/test_updater.py::TestUpdaterCli::test_confirmed_mutations_refuse_before_effects`, and `tests/test_updater.py::TestUpdaterCli::test_scheduler_is_disabled_by_default_and_refuses_overlap`. Resolve exact pytest node IDs from the live file before recording them in `local_predicates`.
- Limit update equivalence to outcomes already owned locally: disabled-by-default background/version checks, explicit read-only `update status` and `update check`, confirmed `update apply --yes`, supported-installer selection, and safe refusal defaults. State that upstream's MCP cached-status response shape has no local MCP compatibility claim.
- Track the source-local discrepancy explicitly: pinned upstream README and Claude-facing wording advertise 45 MCP tools while the pinned Codex plugin description advertises 44. Keep separate capability identifiers or source rows where needed so the guard and document do not normalize the claims. Retain the fork's tested 29-tool full and four-tool minimal profiles.
- Classify hub search/read concurrency, HTTP MCP, logstream topics, Qdrant, `sqlite_exact`, alternate-backend, and EmbeddingGemma changes as `irrelevant` only after each row names the absent local architecture owner and carries no local predicate. Apply the same explicit boundary to benchmark, dependency, and release-metadata groups that do not change a supported fork behavior.
- Mark a row release-critical only when the changed upstream surface can affect a current fork correctness or release contract. The cheapest decisive falsifier is any commit in the 47-SHA inventory that exposes such a gap without an existing local predicate; if found, stop the documentation-only implementation and report that commit, owner, and missing predicate for plan revision.
- Keep tests/test_upstream_comparison_guard.py changes to the canonical inventory assertions: 16 groups to 12, 43 commits to 47, and any directly coupled inventory prose/constituent-count expectation established by the reviewed range. Preserve fixtures, helpers, and fail-closed behavior tests.
- Update tests/test_release_preflight.py because its live-root static preflight assertion currently requires `manifest_inventory_commits=43`; leaving it unchanged deterministically breaks the focused release test after the manifest advances. Change only that expected count.
- Command context basis: all commands run from the repository root. The stdlib guard owns static/live comparison output, the two focused pytest files own canonical and release-preflight snapshots, scripts/gate_inventory.py supplies the exact docs/public-safety/format gate commands, and runner finalization owns the configured diff check. No package subdirectory or container workdir applies.
