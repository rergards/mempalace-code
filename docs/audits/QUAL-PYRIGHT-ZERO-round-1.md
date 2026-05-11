slug: QUAL-PYRIGHT-ZERO
round: 1
date: 2026-05-11
commit_range: 6841c7a..HEAD
findings:
  - id: F-1
    title: "assert-based Pyright narrowing in miner.py is stripped by Python -O"
    severity: info
    location: "mempalace_code/miner.py:3559,3626"
    claim: >
      Two `assert collection is not None` guards were added for Pyright type
      narrowing inside the non-dry-run branch of `mine()`. Since `assert`
      statements are stripped when Python is invoked with `-O`, these guards do
      not execute under optimized builds. However, control flow already
      guarantees `collection` is non-None in the non-dry-run branch (set at
      line 3506 via `get_collection(palace_path)`), so the asserts are
      truthful and no runtime regression is possible. Python -O is not used
      in this project's CI or runtime paths.
    decision: dismissed
  - id: F-2
    title: "_RoomData TypedDict uses bare `set` without type parameters"
    severity: low
    location: "mempalace_code/palace_graph.py:20-25"
    claim: >
      The `_RoomData` TypedDict declares `wings: set`, `halls: set`, and
      `dates: set` without type parameters. More precise annotations would be
      `set[str]`. Pyright accepts bare `set` in basic mode and all tests pass.
      This is a minor type-precision gap with no functional impact.
    decision: dismissed
  - id: F-3
    title: "No test covers ChromaStore methods when self._col is None (create=False path)"
    severity: low
    location: "mempalace_code/_chroma_store.py:51-91"
    claim: >
      The implementation added `if self._col is None: raise RuntimeError(...)` guards
      to `add`, `upsert`, `get`, `query`, and `delete`. This improves error
      reporting versus the prior `AttributeError`. No test exercises these guards
      (the path requires `create=False` with a missing collection). The Chroma
      backend is deprecated; the gap is acceptable.
    decision: dismissed
  - id: F-4
    title: "Suppression scanner operates on raw text; string literals with ignore patterns not misclassified"
    severity: info
    location: "tests/test_type_suppressions.py:19-41"
    claim: >
      `_violations()` matches `SUPPRESSION_RE` against raw line text without
      parsing Python AST. String literals or docstrings containing `# type: ignore`
      could in theory produce false positives. Analysis of all 82 suppressions and
      the scanner file itself shows no false positives: string literals in
      `test_type_suppressions.py` that contain the accepted form are also matched
      by `ACCEPTED_RE` (so not violations), and patterns in docstrings lack the `#`
      prefix required by `SUPPRESSION_RE`. No action required.
    decision: dismissed
totals:
  fixed: 0
  backlogged: 0
  dismissed: 4
fixes_applied: []
new_backlog: []
