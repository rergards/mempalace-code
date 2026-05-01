---
slug: MCP-LAZY-STARTUP
goal: "Make MCP initialize/tools-list and metadata read tools start without miner imports, embedding model loads, or store writes"
risk: medium
risk_note: "Touches MCP module import boundaries and LanceStore open semantics; write-path cache upgrade needs explicit regression coverage"
files:
  - path: mempalace_code/mcp_server.py
    change: "Move miner, searcher, palace_graph, and KnowledgeGraph imports behind tool-specific lazy helpers; open read tools with a read-only store and avoid reusing that handle for writes"
  - path: mempalace_code/storage.py
    change: "Add read-only Lance open support that skips directory creation, schema migration, table creation, and embedder initialization until an embedding operation is actually requested"
  - path: mempalace_code/miner.py
    change: "Replace import-time BATCH_SIZE device probing with a cached lazy batch-size helper used when mining flush thresholds are evaluated"
  - path: mempalace_code/convo_miner.py
    change: "Use the miner lazy batch-size helper instead of importing a precomputed BATCH_SIZE value"
  - path: tests/test_mcp_server.py
    change: "Add startup/read/write-cache regression tests for lazy imports, read-only metadata tools, no-palace behavior, and mempalace_mine invalid-input handling"
  - path: tests/test_storage_lance.py
    change: "Add LanceStore read-only open tests proving metadata reads skip embedder loads and missing palaces are not created"
  - path: tests/test_miner.py
    change: "Update batch-size tests for lazy cached detection and import-without-torch behavior"
acceptance:
  - id: AC-1
    when: "a subprocess blocks imports of torch, sentence_transformers, and mempalace_code.miner, then imports mempalace_code.mcp_server and sends initialize plus tools/list requests"
    then: "both JSON-RPC responses are returned successfully and tools/list still includes mempalace_mine"
  - id: AC-2
    when: "mempalace_status, mempalace_list_wings, and mempalace_get_taxonomy run against a seeded Lance palace while LanceStore._get_embedder is patched to raise"
    then: "each tool returns the expected counts without calling the embedder"
  - id: AC-3
    when: "mempalace_status opens and caches the store first, then mempalace_add_drawer is called in the same MCP module instance"
    then: "the add succeeds and a subsequent status call reports the new drawer count"
  - id: AC-4
    when: "mempalace_status runs with palace_path pointing to a missing directory"
    then: "it returns the standard No palace found response and the missing directory is still absent on disk"
  - id: AC-5
    when: "mempalace_mine is called with a non-existent directory while miner import is patched to fail"
    then: "it returns {success: false, error: ...} without importing miner or raising through the MCP dispatcher"
  - id: AC-6
    when: "mempalace_code.miner is imported while torch import is patched to fail, then the lazy batch-size helper is invoked"
    then: "module import succeeds and the helper returns the documented fallback batch size"
out_of_scope:
  - "Changing the default embedding model or benchmark gates"
  - "Optimizing semantic search latency after the search tool is actually invoked"
  - "Changing ChromaDB legacy backend behavior beyond accepting the new open_store keyword safely"
  - "Removing existing MCP tools or changing their public schemas"
---

## Design Notes

- Keep `initialize` and `tools/list` as pure metadata paths. They should not import `miner`, create `KnowledgeGraph`, open LanceDB, or initialize sentence-transformers.
- In `mcp_server.py`, replace eager imports with small private helpers:
  - `_get_kg()` imports and caches `KnowledgeGraph` only for KG/architecture/mining calls. Preserve the existing `_kg` monkeypatch seam by returning a patched non-None `_kg`.
  - `_search_memories()` and `_code_search()` import from `searcher` only inside search/subsystem handlers.
  - `_graph_helpers()` imports `traverse`, `find_tunnels`, and `graph_stats` only for graph tools.
  - `_mine_quiet()` imports `mine` inside the fd-suppressed block or immediately before it, so startup and invalid `mempalace_mine` inputs do not import the miner.
- Extend `_get_store(create=False)` to request `open_store(..., create=False, read_only=True)` for read tools. Track whether the cached handle is read-only; if a later write path calls `_get_store(create=True)`, reopen a write-capable store instead of returning the read-only handle.
- In `storage.py`, add `read_only: bool = False` to `open_store()` and `LanceStore`. For `read_only=True`:
  - Do not `os.makedirs(palace_path)`.
  - If the Lance directory/table is absent, return a store with `_table is None` or raise a handled missing-palace exception before creating files; MCP should still surface `_no_palace()`.
  - Open existing tables without schema migration and without `_get_embedder()`.
  - Initialize the embedder lazily in `_embed()` and `warmup()` via `_ensure_embedder()`.
  - Make write methods fail clearly if called on a read-only handle; MCP should normally avoid this by reopening on `create=True`.
- Preserve existing default behavior for callers that do not pass `read_only=True`: create/migration semantics and Chroma backend behavior should remain compatible with current tests.
- In `miner.py`, replace `BATCH_SIZE = _detect_batch_size()` with a cached helper such as `get_batch_size()`. Use it at flush-threshold points so importing `miner` no longer imports `torch`. Keep a simple compatibility constant if needed, but do not make it perform device probing at import time.
- Update `convo_miner.py` to call the helper when comparing `len(batch_buffer)` so conversation mining keeps the same adaptive batch-size intent without import-time probing.
- Prefer subprocess/import-hook tests for startup assertions because ordinary in-process tests can be polluted by earlier imports. Use isolated subprocesses where necessary to prove modules were not imported before `initialize` or `tools/list`.
- Run targeted checks after implementation:
  - `python -m pytest tests/test_mcp_server.py -q`
  - `python -m pytest tests/test_storage_lance.py -q`
  - `python -m pytest tests/test_miner.py tests/test_convo_miner.py -q`
