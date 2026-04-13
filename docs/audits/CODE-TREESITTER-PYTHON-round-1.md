slug: CODE-TREESITTER-PYTHON
round: 1
date: 2026-04-14
commit_range: 9bfab62..HEAD
findings:
  - id: F-1
    title: "Misleading chunker_strategy='regex_structural_v1' on no-definition fallback path"
    severity: low
    location: "mempalace/miner.py:665"
    claim: >
      When tree-sitter is available but a Python file has no top-level function or class
      definitions (e.g. a pure constants/data module), _chunk_python_treesitter falls back
      to chunk_adaptive_lines() and returns chunks without a chunker_strategy key.
      _collect_specs_for_file applies the default "regex_structural_v1", which is wrong:
      neither the regex structural path nor the AST boundary extraction was actually used.
      This misleads observability tooling — a user checking chunker_strategy to confirm
      AST chunking is active would see "regex_structural_v1" and incorrectly conclude the
      fallback occurred due to tree-sitter being absent, when in fact it was active but
      found no boundaries.
    decision: fixed
    fix: >
      In _chunk_python_treesitter(), the no-definition fallback now explicitly tags every
      returned chunk with chunker_strategy='treesitter_adaptive_v1' before returning.
      Added test test_ast_no_definitions_strategy_tag() to tests/test_chunking.py to
      assert this tag is present.

  - id: F-2
    title: "No negative assertion for detached-comment gap detection"
    severity: low
    location: "tests/test_chunking.py:889"
    claim: >
      test_ast_leading_comment_attached_to_def verifies the positive case (attached
      comment IS in the same chunk as def process) but contains no negative assertion
      that a comment separated from the following def by a blank line is NOT absorbed.
      The gap check (b'\n\n' in source_bytes[prev.end_byte:children[j+1].start_byte])
      could be silently removed without any test catching the regression. The current
      PYTHON_COMMENT_ATTACHED fixture is too small (<TARGET_MIN=400 chars per chunk) for
      adaptive_merge_split to keep def standalone in a separate chunk, so a meaningful
      negative assertion requires either a larger fixture or inspecting raw_chunks
      (a private API).
    decision: backlogged
    backlog_slug: CODE-TREESITTER-PYTHON-DETACH-TEST

  - id: F-3
    title: "CRLF line endings not handled in blank-line gap detection"
    severity: info
    location: "mempalace/miner.py:657"
    claim: >
      The gap check uses b'\n\n' which would not match b'\r\n\r\n' Windows line endings.
      In practice the project targets macOS/Linux and Python's text-mode file reading
      normalizes CRLF to LF, so source bytes passed to _chunk_python_treesitter are
      already LF-normalized. No real-world impact expected.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 1
  dismissed: 1

fixes_applied:
  - "In _chunk_python_treesitter(), tag no-definition fallback chunks with chunker_strategy='treesitter_adaptive_v1' instead of leaving the key absent (miner.py:665-671)"
  - "Added test test_ast_no_definitions_strategy_tag() to tests/test_chunking.py to cover F-1"

new_backlog:
  - slug: CODE-TREESITTER-PYTHON-DETACH-TEST
    summary: "Add negative test for detached-comment gap detection in _chunk_python_treesitter with a large-enough fixture so the detached comment chunk stays separate after adaptive_merge_split"
