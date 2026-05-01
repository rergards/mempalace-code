---
slug: CODE-TREESITTER-PYTHON-DETACH-TEST
goal: "Add a Python AST chunking regression test proving blank-line-separated comments are not attached to the following def"
risk: low
risk_note: "Test-only change covering existing behavior in _chunk_python_treesitter; no production code changes planned"
files:
  - path: tests/test_chunking.py
    change: "Add a padded detached-comment Python fixture and test_ast_detached_comment_not_absorbed near the existing Python AST comment-attachment test"
acceptance:
  - id: AC-1
    when: "A Python source fixture has a comment immediately adjacent to def process"
    then: "the chunk containing def process includes the adjacent leading comment text"
  - id: AC-2
    when: "A Python source fixture has '# A detached comment...' followed by a blank line before def standalone"
    then: "the chunk containing def standalone excludes the detached comment text"
  - id: AC-3
    when: "test_ast_detached_comment_not_absorbed runs with tree-sitter-python available"
    then: "the test observes def standalone in a separate final chunk despite adaptive_merge_split post-processing"
  - id: AC-4
    when: "test_ast_detached_comment_not_absorbed runs without tree-sitter-python, or on Python < 3.10"
    then: "pytest reports the test as skipped via _skip_if_no_ast rather than failed"
  - id: AC-5
    when: "the b'\\n\\n' gap check in _chunk_python_treesitter is temporarily removed and the new test is run"
    then: "the new test fails because the def standalone chunk contains the detached comment text"
out_of_scope:
  - "Changes to mempalace_code/miner.py or _chunk_python_treesitter behavior"
  - "Go, Rust, or other tree-sitter detached-comment coverage"
  - "Broad chunking fixture refactors outside the Python AST comment-attachment area"
---

## Design Notes

- Place the new test immediately after `test_ast_leading_comment_attached_to_def` so the positive and negative Python comment-attachment cases stay together.
- Reuse `_skip_if_no_ast()` and `chunk_code(..., \".py\", \"test.py\")` like the neighboring Python AST tests.
- Prefer a new dedicated fixture, for example `PYTHON_COMMENT_DETACHED_PADDED`, over stretching `PYTHON_COMMENT_ATTACHED`; the existing fixture is still useful for the positive adjacency case.
- The fixture should keep three behaviors visible:
  - an adjacent comment directly above `def process`;
  - a detached comment separated from `def standalone` by a blank line;
  - enough body text inside `def standalone` to prevent final merging from hiding the boundary being tested.
- `adaptive_merge_split` currently merges adjacent raw chunks while their combined length stays at or below `TARGET_MAX` (2500 chars). To make the assertion robust, make the `def standalone` raw chunk large enough that it cannot merge back into the previous buffer; padding above `TARGET_MAX` and below `HARD_MAX` is the simplest shape.
- Assertion pattern: find the chunk containing `def standalone`; fail explicitly if absent; assert the detached comment string is not in that chunk.
- Run focused verification with `python -m pytest tests/test_chunking.py -k \"test_ast_leading_comment_attached_to_def or test_ast_detached_comment_not_absorbed\" -q`, then run `ruff check tests/test_chunking.py` and `ruff format --check tests/test_chunking.py`.
