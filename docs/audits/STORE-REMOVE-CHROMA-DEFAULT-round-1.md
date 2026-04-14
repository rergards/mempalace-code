slug: STORE-REMOVE-CHROMA-DEFAULT
round: 1
date: 2026-04-14
commit_range: ac14105..aee3b5e
findings:
  - id: F-1
    title: "noqa: F401 on `import chromadb` is unnecessary and misleading"
    severity: info
    location: "mempalace/_chroma_store.py:18"
    claim: >
      The `noqa: F401` suppression on `import chromadb` is incorrect — `chromadb` is directly
      referenced on line 36 (`chromadb.PersistentClient(path=palace_path)`), so ruff F401 would
      never fire here. The inline comment implied the import is otherwise unused, which could confuse
      future readers into thinking the import exists only for side effects.
    decision: fixed
    fix: "Removed `noqa: F401`; updated comment to `# top-level import: fails fast with ImportError if [chroma] extra not installed`"

  - id: F-2
    title: "No test coverage for __getattr__ ImportError path when chromadb absent"
    severity: medium
    location: "mempalace/storage.py:708-718"
    claim: >
      `storage.__getattr__("ChromaStore")` raises ImportError with a helpful message when chromadb
      is not installed, but there is no test for this. If the guard is removed or the error message
      changed, no test catches the regression. The chromadb dev install means this path is never
      exercised in the default test run.
    decision: backlogged
    backlog_slug: STORE-CHROMA-IMPORT-ERROR-TESTS

  - id: F-3
    title: "No test coverage for open_store(backend='chroma') ImportError when chromadb absent"
    severity: medium
    location: "mempalace/storage.py:759-766"
    claim: >
      `open_store(path, backend='chroma')` guards against missing chromadb with a clear ImportError,
      but no test verifies this path. Bundled into STORE-CHROMA-IMPORT-ERROR-TESTS backlog item.
    decision: backlogged
    backlog_slug: STORE-CHROMA-IMPORT-ERROR-TESTS

  - id: F-4
    title: "Circular import risk between _chroma_store.py and storage.py"
    severity: info
    location: "mempalace/_chroma_store.py:22"
    claim: >
      `_chroma_store.py` imports `DrawerStore` from `storage.py` at module level. `storage.py`
      lazily imports from `_chroma_store.py` inside `__getattr__` and `open_store`. Analysis
      confirms no circular import: by the time `__getattr__` fires, `storage.py` is fully loaded
      in `sys.modules`, so the back-import in `_chroma_store.py` resolves cleanly. Dismissed.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 2
  dismissed: 1

fixes_applied:
  - "Removed misleading `noqa: F401` from `import chromadb` in _chroma_store.py:18; chromadb is used directly on line 36"

new_backlog:
  - slug: STORE-CHROMA-IMPORT-ERROR-TESTS
    summary: "Add tests for storage.__getattr__ and open_store ImportError paths when chromadb extra absent"
