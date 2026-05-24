verdict: READY

gaps: []

## Notes

- `task_contract:` present with all required sub-keys (requirements, surfaces, invariants, risks, verification, regression_plan). ✓
- `contract_policy.sync_gate: required` and `verification_path: automated`. ✓
- Each acceptance ID (AC-1..AC-4) is linked to at least one `verification:` row and at least one `regression_plan.checks` row. ✓
- All verification and regression commands are runnable shell invocations (`python -m pytest …`, `ruff check …`), no manual or prose-only entries. ✓
- File scope is consistent with the codebase:
  - `mempalace_code/layers.py` is the right place to flip `Layer1.generate`, `Layer2.retrieve`, and `MemoryStack.status` to `read_only=True` while leaving `Layer3.search`/`search_raw` (which need a query vector and therefore the embedder) alone — confirmed by reading the module.
  - `mempalace_code/palace_graph.py._get_store` is the single entry point for direct (non-MCP) graph reads; switching it to `read_only=True` is sufficient.
  - MCP graph tools (`mempalace_code/mcp/tools/graph.py`) already obtain stores through `runtime._get_store()` which sets `read_only=True` for `create=False` — the plan correctly limits MCP scope to adding regression coverage in `tests/test_mcp_server.py`.
- Storage contract check: `LanceStore(read_only=True)` skips directory creation and `_ensure_embedder()`, and `count()`/`get()` return empty when `_table is None`. The plan's "missing palace → empty graph / no-palace message" behavior is consistent with this stub. The `os.makedirs` skip in `open_store` (storage.py:1416-1417) supports REQ-3's "no directory creation" requirement.
- `mempalace_show_project_graph` / `mempalace_show_type_dependencies` use `runtime._get_kg()`, not the drawer store, so they are correctly excluded from scope.
- `cli_commands/query.py::cmd_wakeup` invokes `MemoryStack(...).wake_up(...)`, so the wake-up CLI subprocess smoke (VER-1) inherits the layers.py change without requiring a touched_files entry for the CLI handler.
- `tests/test_layers.py` does not yet exist; the plan files list signals it will be created by the implementer. Acceptable for new test scaffolding.
- Out-of-scope items are explicit (Layer3 semantic search, searcher.py, mutation paths, schema, MCP runtime caching). No backlog file is listed as a provider-owned/touched file.
- No hidden TBDs or deferred design work; design notes give concrete guidance on where to keep missing-palace messaging vs initialized-empty-palace messaging.
