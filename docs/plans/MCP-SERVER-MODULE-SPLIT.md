---
slug: MCP-SERVER-MODULE-SPLIT
status: completed
authority: non_authoritative
goal: "Split the MCP server monolith into tool-family modules with one stable registry and dispatch entrypoint"
risk: medium
risk_note: "Large no-behavior-change refactor of the MCP import graph, mutable test seams, registry assembly, and stdio entrypoint; risk is controlled by preserving the 28-tool registry shape, profile filtering, lazy startup, and compatibility imports"
files:
  - path: mempalace_code/mcp_server.py
    change: "Replace the monolithic implementation with a thin compatibility/entrypoint shim that re-exports TOOLS, handle_request, main, runtime helpers, and existing tool_* handler names"
  - path: mempalace_code/mcp/__init__.py
    change: "Add the internal MCP package and export the stable registry/dispatch surface for package-local imports"
  - path: mempalace_code/mcp/runtime.py
    change: "Move shared mutable MCP runtime state and helpers: config, store singleton, KG singleton, no-palace/degraded responses, logger, and quiet mining wrapper"
  - path: mempalace_code/mcp/protocol_text.py
    change: "Move PALACE_PROTOCOL and AAAK_SPEC text away from handler/dispatch code without changing returned text"
  - path: mempalace_code/mcp/registry.py
    change: "Build the authoritative ordered TOOLS registry from family-local tool specs, reject duplicate names, and expose the same dict shape used by profiles and dispatch"
  - path: mempalace_code/mcp/dispatch.py
    change: "Move JSON-RPC handle_request, active registry handling, CLI flag parsing, selector resolution wiring, and the stdio main loop"
  - path: mempalace_code/mcp/tools/__init__.py
    change: "Add the tool-family package and define family import conventions"
  - path: mempalace_code/mcp/tools/read.py
    change: "Move status, wing/room/taxonomy, and AAAK spec read handlers plus their registry specs"
  - path: mempalace_code/mcp/tools/search.py
    change: "Move semantic search, code search, duplicate check, and file context handlers plus their registry specs"
  - path: mempalace_code/mcp/tools/write.py
    change: "Move add/delete drawer, delete wing, and mine handlers plus their registry specs"
  - path: mempalace_code/mcp/tools/kg.py
    change: "Move knowledge-graph query/add/invalidate/timeline/stats handlers plus their registry specs"
  - path: mempalace_code/mcp/tools/graph.py
    change: "Move palace graph traversal, tunnel, and graph stats handlers plus their registry specs"
  - path: mempalace_code/mcp/tools/architecture.py
    change: "Move architecture/KG code tools, expansion constants, reusable-extraction logic, and their registry specs"
  - path: mempalace_code/mcp/tools/diary.py
    change: "Move diary write/read handlers plus their registry specs"
  - path: tests/test_mcp_registry.py
    change: "Add focused registry tests for exact 28-tool order, family disjointness, duplicate-name rejection, schema shape, and mcp_server compatibility re-exports"
  - path: tests/test_mcp_server.py
    change: "Update MCP handler tests to patch the new runtime module, keep existing direct-handler and JSON-RPC behavior coverage, and add representative family dispatch checks"
  - path: tests/test_mcp_tool_profiles.py
    change: "Point profile tests at the new stable registry surface while preserving existing profile content and selector expectations"
  - path: tests/test_e2e.py
    change: "Update MCP E2E patch helpers to configure the shared runtime module instead of mcp_server module globals"
  - path: tests/test_packaging_namespace.py
    change: "Keep legacy mempalace.mcp_server shim and mempalace_code.mcp_server imports identity-compatible for handle_request/main"
  - path: mempalace_code/README.md
    change: "Update the package module summary so contributors know MCP implementation now lives under mempalace_code/mcp with mcp_server.py as the public entrypoint"
acceptance:
  - id: AC-1
    when: "a Python command imports mempalace_code.mcp.registry.TOOLS and prints its keys"
    then: "the output is exactly the current 28 tool names in the current order from mempalace_status through mempalace_diary_read"
  - id: AC-2
    when: "a client sends initialize followed by tools/list through mempalace_code.mcp_server.handle_request with no active_registry override"
    then: "the initialize serverInfo is unchanged and tools/list exposes exactly the same 28 names and inputSchema payloads as the registry"
  - id: AC-3
    when: "a seeded test palace calls representative handlers from each family through the mempalace_code.mcp_server compatibility imports"
    then: "status, code_search, kg_query, find_implementations, traverse, add_drawer, diary_write/read, and file_context return their existing success payload keys"
  - id: AC-4
    when: "an active minimal profile registry handles tools/list and then tools/call for mempalace_delete_wing"
    then: "tools/list contains only the minimal profile tools and the hidden delete_wing call returns JSON-RPC code -32601 with the active-profile-disabled message"
  - id: AC-5
    when: "tools/call receives arguments as a non-object value for any enabled tool"
    then: "dispatch still returns JSON-RPC code -32602 with the existing 'arguments must be an object' message"
  - id: AC-6
    when: "tools/call names a truly unknown tool while using a filtered active registry"
    then: "dispatch still returns JSON-RPC code -32601 with the 'Unknown tool' message, distinct from the hidden-profile-tool message"
  - id: AC-7
    when: "a subprocess blocks imports of torch, sentence_transformers, and mempalace_code.miner, then imports mempalace_code.mcp_server and sends initialize plus tools/list"
    then: "both JSON-RPC responses succeed and the blocked modules are absent from sys.modules after the calls"
  - id: AC-8
    when: "mempalace_status opens a seeded palace read-only, then mempalace_add_drawer is called in the same process"
    then: "the add succeeds and a subsequent status call reports the new drawer without read-only cache reuse failures"
  - id: AC-9
    when: "mempalace_status is called with a missing palace_path"
    then: "it returns the existing No palace found response and the missing directory is not created on disk"
  - id: AC-10
    when: "legacy import compatibility is checked via import mempalace.mcp_server and python -m mempalace_code.mcp_server"
    then: "both entrypoints resolve to the same handle_request/main behavior and initialize returns serverInfo.name='mempalace-code'"
out_of_scope:
  - "Adding, removing, renaming, or rewording MCP tools, schemas, descriptions, or handler response payloads"
  - "Changing MCP tool profile names, selector grammar, precedence, or startup flag semantics"
  - "Changing storage, embedding, search, mining, knowledge-graph persistence, diary persistence, or cleanup behavior"
  - "Dynamic runtime tool negotiation or per-client tool discovery beyond the existing startup registry filter"
  - "Broad README/user-facing MCP documentation rewrites beyond the internal package summary"
---

## Design Notes

- Keep `mempalace_code.mcp_server` as the public executable module: `python -m mempalace_code.mcp_server` and legacy `mempalace.mcp_server` must keep working. The implementation moves behind it; external MCP command examples do not change.
- Use `mempalace_code/mcp/runtime.py` as the only owner of mutable MCP globals. Tool modules should import runtime helpers instead of importing `mcp_server`, avoiding circular dependencies and making tests patch one state module.
- Update test helpers to monkeypatch `mempalace_code.mcp.runtime._config`, `_kg`, `_store`, and `_store_read_only`. Do not preserve assignment-to-`mcp_server._config` as a supported test seam; keep `_get_store` and `_get_kg` re-exported only for direct compatibility imports.
- Registry shape stays identical:
  - Each entry remains `{"description": str, "input_schema": dict, "handler": callable}`.
  - `tools/list` still serializes `input_schema` as `inputSchema`.
  - Registry order is the current `TOOLS` insertion order so tool-profile results and clients that display ordered tools stay stable.
- Family modules own both handlers and their registry specs:
  - `read.py`: status/list/taxonomy/AAAK.
  - `search.py`: semantic search, code search, duplicate check, file context.
  - `write.py`: add/delete/mine. `tool_add_drawer` can import or call `search.tool_check_duplicate`; do not duplicate duplicate-check logic.
  - `kg.py`: temporal KG CRUD/read tools.
  - `graph.py`: palace graph traversal/tunnel/stats tools.
  - `architecture.py`: architecture query tools and reusable-extraction constants.
  - `diary.py`: diary write/read.
- `registry.py` should assemble families in the exact current order and validate duplicates at import time. Prefer a tiny helper like `build_tools(*families)` over a dataclass-heavy abstraction; the existing dict contract is the public surface.
- `dispatch.py` should contain only protocol and startup mechanics: `handle_request`, `_parse_comma_list`, `_active_registry`, `main`, argument noise stripping, schema-based int/float coercion, profile filtering, and stdio loop.
- Preserve lazy startup from `MCP-LAZY-STARTUP`: registry import and `initialize`/`tools/list` must not import miner, torch, sentence-transformers, open LanceDB, or instantiate `KnowledgeGraph`.
- Keep `mempalace_code.mcp_tool_profiles` behavior unchanged. It should continue receiving a set of registry names; profile tests can import `TOOLS` through `mempalace_code.mcp.registry` or the `mcp_server` shim, but the semantics are not part of this refactor.
- Verification commands after implementation:
  - `python -m pytest tests/test_mcp_registry.py tests/test_mcp_tool_profiles.py tests/test_mcp_server.py -q`
  - `python -m pytest tests/test_e2e.py::test_mcp_session_lifecycle tests/test_packaging_namespace.py -q`
  - `ruff check mempalace_code/ tests/`
  - `ruff format --check mempalace_code/ tests/`
