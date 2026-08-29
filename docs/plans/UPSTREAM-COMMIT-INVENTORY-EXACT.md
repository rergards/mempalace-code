---
slug: UPSTREAM-COMMIT-INVENTORY-EXACT
goal: "Make the canonical upstream comparison account for exactly every commit in its pinned Git range."
risk: low
risk_note: "The change extends one existing read-only quality guard, corrects one manifest inventory, and adds focused tests; it has no runtime or release mutation path."
files:
  - path: docs/quality/upstream-comparison.json
    change: "Add nested merge 7641e63741908ac2c5772e7b52a82efa57e9a826 to the constituent inventory of its owning merge group."
  - path: scripts/upstream_comparison_guard.py
    change: "Compare the full previous_commit..commit Git revision set with the union of every delta decision merge_group and constituent_commits, and fail closed with actionable missing/extra commit diagnostics."
  - path: tests/test_upstream_comparison_guard.py
    change: "Cover exact inventory success, the omitted nested-merge regression, extra inventory entries, and unavailable or invalid Git range evidence."
acceptance:
  - id: AC-1
    when: "`python scripts/upstream_comparison_guard.py --json` runs in the repository at the corrected manifest"
    then: "it exits 0 and reports equal 43-commit Git-range and manifest-inventory counts with no missing or extra commits"
  - id: AC-2
    when: "the focused guard fixture supplies a Git range containing 7641e63741908ac2c5772e7b52a82efa57e9a826 while omitting that SHA from all merge_group and constituent_commits fields"
    then: "the guard rejects the manifest and its observable diagnostic identifies 7641e63741908ac2c5772e7b52a82efa57e9a826 as missing"
  - id: AC-3
    when: "the focused guard fixture adds a well-formed 40-hex SHA to the manifest inventory that is absent from the pinned Git range"
    then: "the guard rejects the manifest and identifies the SHA as an extra inventory entry"
  - id: AC-4
    when: "the guard cannot resolve previous_commit..commit or receives malformed revision output"
    then: "it exits nonzero with a commit-inventory diagnostic and never reports exact coverage"
out_of_scope:
  - "Changing the reviewed upstream pins, comparison prose, capability decisions, or release state."
  - "Adding a second inventory tool, remote API call, or GitHub workflow."
contract_policy:
  flow: lite_compact
  reason: "Scope, blast radius, reversibility, operational burden, and validation complexity are all low; no auth, runtime data, migration, provider, or CI pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Extend `scripts/upstream_comparison_guard.py`, the existing behavioral owner of upstream-comparison validity. A new script, service, schema owner, or network path would add lifecycle cost without improving acceptance.
- Define the expected set from the complete Git revision walk `previous_commit..commit`; do not use first-parent traversal, because nested merge commit `7641e63741908ac2c5772e7b52a82efa57e9a826` is part of the canonical 43-commit range.
- Define the accounted set as the union of every `delta_decisions[*].merge_group` and `delta_decisions[*].constituent_commits`. Validate both fields as full lowercase 40-hex SHAs before comparing sets.
- Require set equality and sort missing/extra SHAs in diagnostics so output is deterministic. A missing Git executable, non-repository checkout, unknown pin, or failed revision walk is decision-critical UNKNOWN and must fail only this guard with one recovery command: `python scripts/upstream_comparison_guard.py --json` from a checkout containing the pinned history.
- Keep revision collection injectable or otherwise isolated from the pure set comparison so tests can supply bounded deterministic commit lists without network access or constructing upstream history.
- Preserve existing static document/capability checks and the opt-in single-request live-head behavior. The new inventory check remains local and read-only.
- Verify implementation behavior with `python -m pytest tests/test_upstream_comparison_guard.py -q`, then exercise the public CLI command from AC-1; broader suite execution remains runner-owned.
