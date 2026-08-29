---
slug: UPSTREAM-COMPARISON-A9F345CC
goal: "Refresh the canonical upstream comparison from dfba59b0 to a9f345cc with complete, evidence-linked disposition of the intervening upstream changes."
risk: low
risk_note: "The change is limited to the existing comparison manifest and document; release risk comes from an incomplete or stale classification, which the existing static and live guards fail closed on."
files:
  - path: docs/quality/upstream-comparison.json
    change: "Advance the reviewed develop pin and dates, refresh pinned source and compare URLs, and record every dfba59b0..a9f345cc change group with its source, release-critical flag, decision, rationale, and any required local predicate."
  - path: docs/UPSTREAM_COMPARISON.md
    change: "Mirror the refreshed snapshot, sources, exact change categories, and adopted, already-covered, and not-applicable dispositions, including evidence that no release-critical drift remains."
acceptance:
  - id: AC-1
    when: "python scripts/upstream_comparison_guard.py --check-live --json is run against the refreshed files while upstream develop heads at a9f345cc63254eb4dea7abad36963b85c9f8453a"
    then: "the JSON reports ok=true and live_checked=true, with both pinned_commit and live_head equal to a9f345cc63254eb4dea7abad36963b85c9f8453a and no errors"
  - id: AC-2
    when: "python scripts/upstream_comparison_guard.py --json is run after the refresh"
    then: "the JSON reports ok=true, the document and manifest expose the same complete delta-decision IDs and stances, adopted or equivalent-local decisions name valid local predicates, and release_critical_decisions contains no unresolved drift"
  - id: AC-3
    when: "the focused live-mismatch behavior test in tests/test_upstream_comparison_guard.py is run with a fetched SHA different from the pin"
    then: "the guard fails closed with an upstream-drift error naming the stale-to-live compare range and the recovery command"
  - id: AC-4
    when: "the refreshed decision output is inspected for the dfba59b0..a9f345cc range"
    then: "the config unreadable-write change is classified adopted and links to the completed CONFIG-PEOPLE-MAP-MALFORMED-PRESERVE predicate, C and C++ scanning is classified already covered, and legacy backend, task, plugin, notification, logstream, replication, and shared-brain changes are classified not applicable without adding those capabilities"
  - id: AC-5
    when: "python scripts/docs_drift_guard.py, python scripts/public_safety_scan.py, python scripts/quality_scorecard.py, and python scripts/release_preflight.py are run after the refresh"
    then: "each command exits successfully and reports no documentation drift, public-safety violation, scorecard regression, or preflight blocker attributable to the comparison refresh"
out_of_scope:
  - "Restoring the retired notification workflow or adding task, logstream, replication, shared-brain, or live-hub runtime code"
  - "Importing or re-enabling legacy ChromaDB, SQLite, Qdrant, or other server-vector backend implementations"
  - "Changing the comparison guard, its tests, README ownership, backlog metadata, or introducing a second comparison owner"
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: scope is two existing documentation artifacts, behavior is declarative classification, dependencies are unchanged, rollout is a reversible pin refresh, and operations use existing guards; no auth, data, migration, provider, or pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Treat `docs/quality/upstream-comparison.json` as the machine-readable owner and keep `docs/UPSTREAM_COMPARISON.md` as its exact human-readable projection. Do not create another manifest, generator, or comparison path.
- Move `previous_commit` to `dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0`, pin `commit` to `a9f345cc63254eb4dea7abad36963b85c9f8453a`, and regenerate the compare link and every pinned upstream source URL from those exact SHAs.
- Inventory the full Git range, then group merge commits with their constituent commits so each behavioral change appears once. Record the mapping explicitly in the document; do not infer completeness from changed filenames alone.
- Preserve the guard's closed stance vocabulary: use `adopted` for behavior brought into the fork, `equivalent-local` for the task's already-covered category, and `irrelevant` for the task's not-applicable category. Use `deferred` only for an intentionally retained future scope and `migration-only` only for a genuine supported migration surface.
- Classify upstream's refusal to overwrite unreadable configuration as `adopted`, cite a tracked upstream source plus the local completed `CONFIG-PEOPLE-MAP-MALFORMED-PRESERVE` regression predicate, and mark it release-critical because it is the applicable reproduced data-loss behavior.
- Classify upstream C/C++ readable-extension support as `equivalent-local` only after naming the existing local scanning predicate. Keep the comparison factual about supported suffixes and avoid importing upstream miner code.
- Classify Qdrant and SQLite fixes, shared-brain rules and coordination, task skills and plugin packaging, and notification/logstream/replication surfaces as `irrelevant` where the fork has no matching supported owner. Apply the same evidence-based check to the remaining search, graph, MCP, config-path, encoding, repair, and drawer changes instead of bulk-labeling the range.
- Every `adopted` or `equivalent-local` row must name an existing repository-relative module or pytest node. Every release-critical row must cite a tracked upstream file rather than only the compare range. Add tracked source paths only when needed for primary evidence at the reviewed commit.
- Keep the LanceDB-only, local-first capability inventory unchanged unless the pinned public sources require a factual upstream-side wording update. Do not advertise ChromaDB, SQLite, Qdrant, remote embeddings, shared-brain coordination, task orchestration, or notification compatibility for this fork.
- The decisive falsifier is the existing guard: static failure means the two artifacts or predicates disagree; live failure means the pin is already stale. Recovery remains `python scripts/upstream_comparison_guard.py --check-live --json` after re-reviewing the reported range.
