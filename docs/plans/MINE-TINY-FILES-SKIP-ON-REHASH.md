---
slug: MINE-TINY-FILES-SKIP-ON-REHASH
goal: "Skip unchanged tiny files during incremental mining without losing tiny-file reporting"
risk: low
risk_note: "Touching the incremental mine hash path is localized, but it changes skip semantics for zero-drawer files and must preserve existing tiny-file reporting."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: one local mining path, one local test file, no auth/data/migration/provider/pipeline boundary touched, and no external service dependencies."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/mining/orchestrator.py
    change: "Teach incremental mining to treat unchanged tiny files as already processed even when they produced no drawers on the prior run."
  - path: tests/test_miner.py
    change: "Add regression coverage for unchanged tiny files, changed tiny files, and preserved tiny-file reporting across incremental runs."
acceptance:
  - id: AC-1
    when: "Run a full mine on a project made only of tiny files, then run an incremental mine again without modifying any file"
    then: "The second run reports the tiny files as skipped/unchanged, does not file any drawers, and leaves the palace empty."
  - id: AC-2
    when: "Run an incremental mine after changing exactly one previously tiny file"
    then: "Only the changed tiny file is reprocessed, the unchanged tiny files remain skipped, and the result reflects one changed file rather than reprocessing the whole tiny set."
  - id: AC-3
    when: "Inspect the incremental mine summary after the no-change rerun"
    then: "Tiny-file reporting is still present and distinct from normal drawer-backed skip reporting, with no delete/rechunk churn for unchanged tiny files."
out_of_scope:
  - "Backlog archive updates or task bookkeeping files"
  - "Any change to chunking thresholds or tiny-file size rules"
  - "Any storage backend migration or schema redesign"
  - "Any CLI surface change"

## Design Notes

- Reuse the existing incremental hash path so unchanged tiny files can be recognized before the delete/rechunk branch runs.
- Preserve the tiny-file counter/summary behavior so reporting still distinguishes tiny outcomes from normal unchanged-file skips.
- Keep the regression focused on the zero-drawer path and one changed-file edge case so the fix cannot silently regress into always reprocessing tiny files.
- Avoid changing full-rebuild semantics; only the incremental branch should consult the new tiny-file state.
