slug: QUAL-E2E-REMAINING-MODULES
round: 1
date: 2026-05-01
commit_range: 3d3d594..2eb6153
findings:
  - id: F-1
    title: "Tautological assertion `wakeup_tokens < wakeup_tokens + recall_tokens` adds no signal"
    severity: low
    location: "tests/test_e2e.py:674-676"
    claim: >
      The expression `wakeup_tokens < wakeup_tokens + recall_tokens` is mathematically true
      whenever `recall_tokens > 0`, which is the precondition asserted on the immediately
      preceding line. The check duplicates the prior `recall_tokens > 0` assertion under a
      misleading message ("recall tokens are zero — L2 returned no content") and could
      mislead reviewers into thinking we verify a layered-growth invariant. Real growth is
      already covered by the L0 < wake_up assertion above and by the recall_tokens > 0 check.
    decision: fixed
    fix: "Removed the redundant comparison; kept the meaningful `recall_tokens > 0` guard."
  - id: F-2
    title: "Idempotency assertion only covers drawer count, not content stability"
    severity: info
    location: "tests/test_e2e.py:603-608"
    claim: >
      The convo_miner idempotency check compares `count_after_first == count_after_second`.
      Strictly meets AC-11. A stronger check would also confirm drawer IDs and `filed_at`
      are unchanged across the second mine — but that introduces fragility around timestamp
      precision and is already covered by `file_already_mined` short-circuit logic in
      mine_convos. Recording as info; no action.
    decision: dismissed
  - id: F-3
    title: "Pyright reports import-not-resolved for lancedb / pyarrow / pytest"
    severity: info
    location: "tests/test_e2e.py:15-17"
    claim: >
      Diagnostics reported missing imports for lancedb, pyarrow, pytest. These are runtime
      dependencies installed via `pip install -e .[dev]`; pyright's environment differs
      from pytest's. Same diagnostic exists for unmodified imports above the diff range.
      Not introduced by this task.
    decision: dismissed
  - id: F-4
    title: "Pre-existing pyright reportArgumentType warnings on diary `topic` indexing"
    severity: info
    location: "tests/test_e2e.py:417-427"
    claim: >
      Pyright flags `e[\"topic\"]` indexing in `test_diary_write_read_continuity` because
      the return-type stub of `tool_diary_read` likely declares entries as a generic
      sequence. This test was added by an earlier task (QUAL-E2E-USER-SCENARIOS), not in
      this hardening scope. Out of scope for this round.
    decision: dismissed
totals:
  fixed: 1
  backlogged: 0
  dismissed: 3
fixes_applied:
  - "Removed tautological `wakeup_tokens < wakeup_tokens + recall_tokens` assertion in test_layers_wake_up_recall_search_e2e."
new_backlog: []
