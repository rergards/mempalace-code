slug: CODE-TREESITTER-PYTHON-DETACH-TEST
round: 1
date: 2026-05-01
commit_range: 583c396..7287bb2
findings:
  - id: F-1
    title: "Negative-only assertion does not verify the detached comment is preserved"
    severity: low
    location: "tests/test_chunking.py:1120-1126"
    claim: "The original test asserted only that 'A detached comment' was absent from standalone's chunk. A bug that silently dropped the detached comment entirely (or routed it to no chunk) would still pass. Hardening the test to assert the comment lands in the previous (process) chunk both verifies preservation and makes the boundary's intent explicit — the comment should ride with the preceding boundary, not vanish."
    decision: fixed
    fix: "Added assertions that the chunk containing 'def process' is found, contains 'A detached comment', and is a different object from the standalone chunk."
totals:
  fixed: 1
  backlogged: 0
  dismissed: 0
fixes_applied:
  - "Strengthened test_ast_detached_comment_not_absorbed with positive assertions on the previous chunk to detect hypothetical comment-loss regressions."
new_backlog: []
