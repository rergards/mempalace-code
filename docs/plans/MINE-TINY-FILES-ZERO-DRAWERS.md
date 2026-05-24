---
slug: MINE-TINY-FILES-ZERO-DRAWERS
goal: "Make tiny non-empty source files mine as explicit tiny-file results instead of inflating skipped-file counts."
risk: low
risk_note: "Limited to miner summary classification and a regression smoke; no storage format, auth, or migration behavior changes."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: local miner summary logic only, no auth/data migration/provider/pipeline boundary, no sensitive surfaces, and verification is a small automated regression smoke."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/mining/orchestrator.py
    change: "Distinguish unchanged-file skips from tiny/non-empty files that yield no chunks, and print/report an explicit tiny-file outcome instead of counting it as already filed."
  - path: tests/test_miner.py
    change: "Add a regression smoke with several tiny Python files that verifies the mine summary and stored drawers reflect tiny-file handling correctly."
acceptance:
  - id: AC-1
    when: "Run `mempalace-code mine --full` on a project containing only tiny but non-empty Python files."
    then: "The run files at least one drawer or reports a specific tiny-file outcome, and the summary no longer claims all of those files were skipped as `already filed`."
  - id: AC-2
    when: "Run an incremental mine twice on the same project, where the second run sees unchanged files plus one tiny file that still produces no chunks."
    then: "Only the unchanged files contribute to `Files skipped (already filed)`; the tiny-file edge case is reported separately and does not inflate the skipped count."
  - id: AC-3
    when: "Inspect `status` or `search` after mining the tiny-file fixture."
    then: "The visible palace state is consistent with the mine summary: real drawers are present for filed content, and empty results are not mislabeled as already-filed skips."
out_of_scope:
  - "Changing chunk-size thresholds or the chunking heuristics themselves."
  - "Altering storage schema, embeddings, or metadata fields."
  - "Backlog bookkeeping or archive file updates."

## Design Notes

- Keep the fix in the mine/orchestrator layer so summary accounting reflects the actual reason a file produced no drawers.
- Preserve the existing incremental skip path for unchanged hashes; only tiny/non-empty no-chunk cases should get special handling.
- Use a fixture with several very small Python files so the regression covers the misleading summary wording and the zero-drawer edge case together.
- Avoid changing the meaning of `files_processed` for genuine unchanged-file skips.
