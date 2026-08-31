---
slug: REL-QUALITY-SCORECARD-FINAL-TREE-SYNC
goal: "Regenerate the committed Markdown and JSON quality scorecards from the final release tree."
risk: low
risk_note: "The existing deterministic generator owns both artifacts; the change updates generated documentation only and is reversible by regeneration from any tree."
files:
  - path: docs/quality/scorecard.md
    change: "Replace the stale Markdown snapshot with output generated from the final release tree."
  - path: docs/quality/scorecard.json
    change: "Replace the stale machine-readable snapshot with output generated from the same final release tree."
acceptance:
  - id: AC-1
    when: "`python scripts/quality_scorecard.py --write` is run from the final release tree"
    then: "The command exits zero, reports both `docs/quality/scorecard.md` and `docs/quality/scorecard.json` as written, and both files contain the freshly rendered scorecard."
  - id: AC-2
    when: "`python scripts/quality_scorecard.py --check` is run after regeneration"
    then: "The command exits zero and prints `quality-scorecard: OK`, confirming schema validity, determinism, public safety, and byte-for-byte freshness of both committed artifacts."
  - id: AC-3
    when: "The focused stale-artifact failure-path test injects a committed-artifact mismatch into `run_check`"
    then: "`run_check` returns exit code 1, preserving the CI guard that rejects an out-of-sync scorecard."
  - id: AC-4
    when: "The scorecard generator is run a second time without any intervening source-tree change"
    then: "The SHA-256 hashes of both generated artifacts remain unchanged, demonstrating byte-identical regeneration at the unchanged-tree boundary."
out_of_scope:
  - "Changes to scorecard metrics, schema, rendering, or generator behavior."
  - "Changes to tests, verification commands, release workflows, or backlog metadata."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: scope and complexity are two existing generated files, risk and reversibility are bounded by deterministic regeneration, verification uses existing local checks, and operations are unchanged; no auth, data, migration, provider, or pipeline boundary is touched."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
---

## Design Notes

- Keep `scripts/quality_scorecard.py` as the sole owner: run its existing `--write` path once against the final tree and commit exactly the resulting Markdown and JSON artifacts.
- Review the generated diff for tree-derived metric changes only. Do not hand-edit either artifact or change the generator to fit prior values.
- Run `python scripts/quality_scorecard.py --check`; its existing contract compares both checked-in files byte-for-byte with fresh renderings and also checks schema, determinism, and public safety.
- Exercise the specific failure contract with `python -m pytest tests/test_quality_scorecard.py::test_run_check_fails_on_stale_committed_artifacts -q`.
- Verify the unchanged-tree boundary by recording `shasum -a 256 docs/quality/scorecard.md docs/quality/scorecard.json`, rerunning `python scripts/quality_scorecard.py --write`, and confirming the hashes are identical.
- The parent runner owns the broader non-network suite, staging, commit, and release finalization.
