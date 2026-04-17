---
slug: PYPROJECT-CHROMA-VERSION
goal: "Raise chromadb ceiling from <0.7 to <2 so .[chroma] installs succeed with chromadb 1.x"
risk: low
risk_note: "ChromaStore uses only high-level chromadb APIs (PersistentClient, collection CRUD) that have been stable across 0.5.x → 1.x; backend is deprecated so blast radius is small"
files:
  - path: pyproject.toml
    change: "Line 51: chromadb>=0.5.0,<0.7 → chromadb>=0.5.0,<2"
  - path: tests/test_chroma_compat.py
    change: "Create new file — smoke tests for ChromaStore import, instantiation, and empty-count; skipped automatically when chromadb not installed (pytest.importorskip)"
acceptance:
  - id: AC-1
    when: "pip install -e '.[chroma]' is run in a clean venv"
    then: "Resolves successfully; pip reports chromadb>=1.0 installed (no dependency conflict)"
  - id: AC-2
    when: "python3 -m pytest tests/test_chroma_compat.py -v is run with .[chroma] installed"
    then: "All tests pass; no test is skipped due to missing chromadb"
  - id: AC-3
    when: "chroma-compat CI job runs"
    then: "pip install -e '.[dev,chroma]' succeeds and the full test suite (including test_chroma_compat.py) passes"
out_of_scope:
  - "Testing ChromaDB query() semantic search (requires model download; not suitable for CI without needs_network marker)"
  - "Migrating existing ChromaDB 0.5.x palace databases to 1.x format"
  - "Removing the deprecated ChromaDB backend (tracked separately as STORE-REMOVE-CHROMA-DEFAULT)"
  - "Upgrading the lower bound above 0.5.0 (backward compat preserved for existing chroma installs)"
---

## Design Notes

- **ChromaDB skipped 0.7**: The package went from 0.5.11 directly to 1.0.0. There is no 0.6.x or 0.7.x release. The current ceiling `<0.7` therefore blocks ALL chromadb 1.x versions (latest: 1.5.8).

- **New ceiling `<2`**: Gives headroom through the entire 1.x series while protecting against a future 2.x breaking change. Lower bound stays at `>=0.5.0` to avoid breaking users with existing 0.5.x installs.

- **API compatibility (0.5.x → 1.x)**: All five APIs used in `_chroma_store.py` are confirmed stable:
  - `chromadb.PersistentClient(path=...)` — unchanged
  - `client.get_or_create_collection(name)` — unchanged
  - `client.get_collection(name)` — unchanged
  - `collection.count() / add() / upsert() / get() / delete()` — unchanged
  - The only 1.x breaking change relevant to us is the default `EmbeddingFunction` (switched from onnx to a new default), but `ChromaStore` never configures an embedding function — it passes `query_texts` raw and lets chromadb handle embedding. This is the same behaviour as 0.5.x.

- **`tests/test_chroma_compat.py` must be created**: The task AC references it, but it does not exist. The CI `chroma-compat` job already runs the full test suite; adding this file makes the smoke tests discoverable and meaningful.

- **What to test (no model download)**: Use `pytest.importorskip("chromadb")` at module level so tests self-skip when chromadb is absent (main CI). Test only:
  1. `ChromaStore` is importable from `mempalace._chroma_store`
  2. Instantiation with a `tmp_path` succeeds (exercises `PersistentClient` + `get_or_create_collection`)
  3. `count()` on an empty store returns 0 (exercises the Collection API)
  4. `delete_wing()` on an empty store returns 0 (exercises the where-filter path)
  These four operations require no embedding computation and therefore no network access.

- **`add()` not tested here**: `ChromaStore.add(documents=...)` without explicit embeddings triggers chromadb's default embedding model download (~80 MB). Omit from this file; the migration path (ChromaDB → LanceDB) is tested elsewhere.
