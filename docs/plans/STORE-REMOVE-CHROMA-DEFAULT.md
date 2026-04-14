---
slug: STORE-REMOVE-CHROMA-DEFAULT
goal: "Move ChromaStore into a guarded _chroma_store.py module so it is only importable when the [chroma] extra is installed"
risk: low
risk_note: "Additive new file; only two callers of ChromaStore in the package (migrate.py and test_migrate.py); no logic changes; backwards compat shim in storage.__getattr__"
files:
  - path: mempalace/_chroma_store.py
    change: "New module — move ChromaStore class from storage.py here; add top-level `import chromadb` so importing this file fails fast if chromadb is not installed"
  - path: mempalace/storage.py
    change: "Remove ChromaStore class body (lines ~700-777); add module-level __getattr__ for backwards-compat lazy re-export; update open_store() to lazily import ChromaStore from ._chroma_store inside the `elif backend == 'chroma'` branch; update module docstring"
  - path: mempalace/migrate.py
    change: "Update lazy import inside migrate_chroma_to_lance(): split `from .storage import ChromaStore, LanceStore` into `from .storage import LanceStore` + `from ._chroma_store import ChromaStore` (keep inside function; wrap in try/except ImportError)"
  - path: tests/test_migrate.py
    change: "Update `from mempalace.storage import ChromaStore, LanceStore` to `from mempalace._chroma_store import ChromaStore` and `from mempalace.storage import LanceStore`"
acceptance:
  - id: AC-1
    when: "chromadb is NOT installed: `python -c 'from mempalace.storage import ChromaStore'`"
    then: "Raises ImportError with a message mentioning 'mempalace[chroma]'"
  - id: AC-2
    when: "chromadb is NOT installed: `python -c 'from mempalace import storage'`"
    then: "Import succeeds without error (LanceStore remains fully usable)"
  - id: AC-3
    when: "chromadb is NOT installed: `python -c 'from mempalace.storage import open_store; open_store(\"/tmp/x\", \"chroma\")'`"
    then: "Raises ImportError with a message mentioning 'mempalace[chroma]'"
  - id: AC-4
    when: "chromadb IS installed: `from mempalace.storage import ChromaStore`"
    then: "Import succeeds; ChromaStore can be instantiated normally"
  - id: AC-5
    when: "chromadb IS installed: `from mempalace._chroma_store import ChromaStore`"
    then: "Import succeeds; ChromaStore can be instantiated normally"
  - id: AC-6
    when: "`python -m pytest tests/test_migrate.py -v` with chromadb installed"
    then: "All tests pass"
  - id: AC-7
    when: "`python -m pytest tests/test_storage_lance.py -v`"
    then: "All tests pass (no regressions; _detect_backend chroma test unaffected)"
  - id: AC-8
    when: "`ruff check mempalace/ tests/` and `ruff format --check mempalace/ tests/`"
    then: "No errors"
out_of_scope:
  - "benchmarks/ — they import chromadb directly and are not part of the main package"
  - "Removing the [chroma] extra from pyproject.toml (ChromaDB is still supported, just optional)"
  - "Deprecation warnings when ChromaStore is used"
  - "Removing migrate.py or the migrate-storage CLI subcommand"
  - "Modifying CLI output or user-facing migration workflow"
---

## Design Notes

- **Why a new file instead of an in-module guard**: Python's `try/except ImportError` class-body tricks are fragile. A separate `_chroma_store.py` with a top-level `import chromadb` gives a clean, explicit failure surface: importing the file fails immediately if chromadb is absent. The leading `_` marks it as internal.

- **Backwards-compat `__getattr__` in storage.py**: Existing code that does `from mempalace.storage import ChromaStore` keeps working when chromadb is installed. When chromadb is absent it raises `ImportError` with a helpful message instead of `AttributeError`. This avoids a hard break for any external callers.

  ```python
  def __getattr__(name: str):
      if name == "ChromaStore":
          try:
              from ._chroma_store import ChromaStore
              return ChromaStore
          except ImportError as exc:
              raise ImportError(
                  "ChromaStore requires the [chroma] extra: "
                  "pip install 'mempalace[chroma]'"
              ) from exc
      raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  ```

- **`open_store` lazy import**: Move the `ChromaStore` construction inside the `elif backend == "chroma"` branch:

  ```python
  elif backend == "chroma":
      try:
          from ._chroma_store import ChromaStore
      except ImportError as exc:
          raise ImportError(
              "ChromaDB backend requires the [chroma] extra: "
              "pip install 'mempalace[chroma]'"
          ) from exc
      return ChromaStore(palace_path, collection_name=collection_name, create=create)
  ```

- **`migrate.py` import update**: The existing `try/except ImportError` wraps instantiation (`ChromaStore(...)`). After this change the ImportError fires at the `from ._chroma_store import ChromaStore` line (top-level import in `_chroma_store.py`). Wrap the import statement instead:

  ```python
  from .storage import LanceStore
  try:
      from ._chroma_store import ChromaStore
  except ImportError:
      raise RuntimeError("chromadb not installed — run: pip install mempalace[chroma]")
  ```

- **`_chroma_store.py` imports `DrawerStore` from `storage`**: To avoid a circular import, `_chroma_store.py` imports `DrawerStore` from `.storage`. This is safe because `storage.py`'s module-level code does not import from `_chroma_store`.

- **`test_migrate.py`**: The `pytest.importorskip("chromadb")` guard at the top already handles the skip case. Updating the import from `mempalace.storage` to `mempalace._chroma_store` is the only change needed.
