slug: CI-CHROMA-COMPAT-TESTS
round: 1
date: 2026-05-01
commit_range: cc292b9..HEAD
findings:
  - id: F-1
    title: "Lifecycle test would pass even if the where filter were silently dropped"
    severity: medium
    location: "tests/test_chroma_compat.py:172-200"
    claim: >
      `test_chroma_store_lifecycle` seeded two docs, both with `wing=mempalace`,
      then queried with `where={"wing": "mempalace"}` and asserted only that
      `len(results["ids"][0]) == 2`. If the wrapper at `mempalace/_chroma_store.py:69-78`
      regressed to never forward `where`, the same two docs would still come back
      and the test would still pass — exactly the bug the test is meant to catch.
      The job's whole purpose is to validate ChromaStore wrapper behavior, so a
      filter test that does not actually filter is dead coverage.
    decision: fixed
    fix: >
      Added a third doc in a different wing (`wing=other`), increased `n_results`
      to 5, and asserted `sorted(results["ids"][0]) == ["d1", "d2"]`. If `where`
      forwarding regressed, the third id would leak into the result and the
      assertion would fail.

  - id: F-2
    title: "Lifecycle test verified that count dropped after delete but not which row was deleted"
    severity: low
    location: "tests/test_chroma_compat.py:198-200"
    claim: >
      `store.delete(ids=["d1"])` was followed only by `assert store.count() == 1`.
      A regression that deleted the wrong row (e.g. swapped `ids` for `where`)
      would still drop the count by one and pass the assertion.
    decision: fixed
    fix: >
      After delete, the test now calls `store.get()` and asserts
      `sorted(remaining["ids"]) == ["d2", "d3"]`, locking in identity of the
      surviving rows.

  - id: F-3
    title: "get() assertion checked the id but not the document body"
    severity: low
    location: "tests/test_chroma_compat.py:194-196"
    claim: >
      `assert fetched["ids"] == ["d1"]` proves the wrapper round-trips an id but
      says nothing about whether the document content was preserved or returned
      under the right include set. A get() that returned the right id but a
      mangled or empty document would slip through.
    decision: fixed
    fix: >
      Added `assert fetched["documents"] == [docs[0]]` so the test fails if the
      document text is dropped or substituted.

  - id: F-4
    title: "_make_store_with_ef patches a private Chroma attribute (_embedding_function)"
    severity: info
    location: "tests/test_chroma_compat.py:46-56"
    claim: >
      The lifecycle helpers rely on `store._col._embedding_function = _DeterministicEF()`
      to avoid a model download. `_embedding_function` is an undocumented
      Chroma 1.x internal — a Chroma upgrade could rename it and silently break
      the offline path, falling back to the default model and either downloading
      or failing with a network error in CI. Mitigations already in place:
      chromadb is pinned in pyproject.toml, the docstring explicitly names
      Chroma 1.x, and the chroma-compat job is the only consumer. Worth flagging,
      not worth working around.
    decision: dismissed

  - id: F-5
    title: "chroma-compat job runs the full pytest suite on top of the focused module"
    severity: info
    location: ".github/workflows/ci.yml:28-30"
    claim: >
      After running `tests/test_chroma_compat.py`, the job runs
      `pytest tests/ -v -m "not needs_network"` which re-runs the same module
      plus the rest of the suite. The duplication is intentional — it confirms
      that having chromadb installed does not break other tests, and the
      focused run gives clear failure signal when ChromaStore itself is the
      problem. CI minutes cost is small, so leaving as-is.
    decision: dismissed

totals:
  fixed: 3
  backlogged: 0
  dismissed: 2
fixes_applied:
  - "Lifecycle test now uses three docs across two wings so the where filter has something to filter out, with sorted-id assertion catching any forwarding regression."
  - "Post-delete assertion verifies remaining ids (d2, d3) instead of just count, catching a wrong-row delete."
  - "get() assertion now also checks documents content roundtrip."
new_backlog: []
