slug: STORE-CHROMA-IMPORT-ERROR-TESTS
round: 1
date: 2026-05-01
commit_range: 6060625..HEAD
findings:
  - id: F-1
    title: "Two of the four tests duplicate the substring assertion of the others"
    severity: low
    location: "tests/test_chroma_import_errors.py:36-57"
    claim: >
      `test_storage_chroma_store_import_error_message_detail` and
      `test_open_store_chroma_import_error_message_detail` re-exercised the same code paths
      as the first two tests and asserted `"mempalace[chroma]" in str(exc_info.value)`,
      which is exactly what `pytest.raises(ImportError, match=r"mempalace\[chroma\]")`
      already verifies. The duplicates added no new coverage and inflated the test count
      without strengthening the gate.
    decision: fixed
    fix: >
      Removed the two `*_message_detail` tests and folded a stronger assertion (see F-2)
      into the remaining two tests so each test now verifies both the user-facing message
      and the exception chain in a single arrange-act-assert pass.

  - id: F-2
    title: "No assertion that the original ImportError is preserved as __cause__"
    severity: low
    location: "tests/test_chroma_import_errors.py:14-33 (new)"
    claim: >
      Production code at `mempalace/storage.py:1026` and `mempalace/storage.py:1077` uses
      `raise ImportError(...) from exc` so the underlying chromadb-missing failure is
      visible via the exception chain. If a future refactor changed this to a bare
      `raise ImportError(...)`, the chain would silently disappear and debuggers would
      lose the original cause — but no test would fail. This is exactly the kind of
      regression-prevention gap the task was created to close.
    decision: fixed
    fix: >
      Each of the two remaining tests now asserts
      `isinstance(exc_info.value.__cause__, ImportError)` after the raise, locking in
      the `from exc` behaviour for both the `storage.__getattr__` and the
      `open_store(backend="chroma")` paths.

  - id: F-3
    title: "Tests pop mempalace._chroma_store from sys.modules without restoring it"
    severity: info
    location: "tests/test_chroma_import_errors.py:21,38"
    claim: >
      `sys.modules.pop("mempalace._chroma_store", None)` is intentionally outside the
      `patch.dict` context, which means a previously cached `_chroma_store` module is
      not restored when the test exits. In practice this is harmless: any later test
      that needs it will re-import and Python will repopulate `sys.modules`. The
      alternative — wrapping the pop in another patch.dict — adds noise without
      materially improving isolation. Documented here for completeness.
    decision: dismissed

totals:
  fixed: 2
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "Consolidated four tests into two, each asserting both the user-facing ImportError message and __cause__ preservation."
  - "Added isinstance(exc_info.value.__cause__, ImportError) check so a future drop of `from exc` would fail the suite."

new_backlog: []
