---
slug: REL-QUALITY-SCORECARD-FINAL-TREE-SYNC
goal: "Regenerate the checked-in quality scorecard so both formats match the final release tree."
risk: low
risk_note: "The existing deterministic, public-safe generator rewrites two documentation artifacts with no runtime behavior change."
files:
  - path: docs/quality/scorecard.md
    change: "Regenerate the human-readable scorecard from the final tracked release tree."
  - path: docs/quality/scorecard.json
    change: "Regenerate the machine-readable scorecard from the same final tracked release tree."
acceptance:
  - id: AC-1
    when: "`python scripts/quality_scorecard.py --write` is run from the repository root and then `python scripts/quality_scorecard.py --check` is run"
    then: "Both commands exit zero, the write command reports both scorecard paths, and the check command reports `quality-scorecard: OK`."
  - id: AC-2
    when: "Either generated scorecard is temporarily removed or changed and `python scripts/quality_scorecard.py --check` is run"
    then: "The check exits non-zero and reports the affected path as missing or stale with the `stale-artifact` diagnostic."
  - id: AC-3
    when: "The generator is run twice without any intervening tracked-tree change"
    then: "The second run leaves `docs/quality/scorecard.md` and `docs/quality/scorecard.json` byte-identical to the first run, and JSON parsing succeeds."
out_of_scope:
  - "Changes to scripts/quality_scorecard.py or its metric definitions."
  - "Changes to tests, backlog metadata, release logic, or verification pipelines."
contract_policy:
  flow: lite_compact
  reason: "Scope, behavior, data, operations, and reversibility are all low: the existing owner deterministically refreshes two derived docs, with no auth, data, migration, provider, or pipeline boundary touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Use the existing owner command: `python scripts/quality_scorecard.py --write`.
- Keep one generation owner and one source tree: do not hand-edit metrics or introduce another script, module, dependency, or state owner.
- Expected implementation diff is limited to the two generated artifacts; the Markdown and JSON must describe the same generator snapshot.
- Validate freshness through `python scripts/quality_scorecard.py --check`; it already checks schema shape, determinism, public safety, and exact committed-artifact bytes.
- Exercise the stale-artifact guard using a disposable copy or a reversible temporary edit, then restore by rerunning `--write` before final validation.
- Cheapest decisive falsifier: a non-zero `--check` after regeneration means the final tree still differs from the checked-in artifacts and blocks completion.
- Rollback is the prior versions of the two generated files; no migration or operational cleanup is required.
