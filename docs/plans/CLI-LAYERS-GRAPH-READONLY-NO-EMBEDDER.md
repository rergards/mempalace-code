---
slug: CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER
goal: "Make layer wake-up/recall and palace graph read-only flows avoid embedding model startup"
risk: low
risk_note: "Small read-path changes use existing LanceStore read_only support; main risk is changing missing or empty palace output."
files:
  - path: mempalace_code/layers.py
    change: "Open metadata-only Layer1.generate, Layer2.retrieve, and MemoryStack.status paths with read_only=True while preserving missing and empty palace messages; leave Layer3 semantic search unchanged."
  - path: mempalace_code/palace_graph.py
    change: "Open direct graph store access with read_only=True and keep missing or uninitialized palaces as empty/no-palace graph results without creating directories."
  - path: tests/test_layers.py
    change: "Add focused no-embedder regressions for wake-up, recall, layer status, CLI wake-up smoke output, missing palaces, and empty palaces."
  - path: tests/test_palace_graph.py
    change: "Add direct graph no-embedder regressions for populated, missing, and empty LanceDB palaces when build_graph/traverse/find_tunnels/graph_stats open their own store."
  - path: tests/test_mcp_server.py
    change: "Extend MCP graph tool smoke coverage so graph_stats/find_tunnels/traverse fail if read-only graph tools initialize the embedder or leak model-loading output."
acceptance:
  - id: AC-1
    when: "a populated LanceDB palace is used by MemoryStack.wake_up(), Layer2.retrieve(), MemoryStack.status(), and a real wake-up CLI subprocess while LanceStore._get_embedder is guarded to fail after seeding"
    then: "the layer outputs include the seeded drawer content/counts, the CLI exits 0, and captured stdout/stderr contain no model-loading markers"
  - id: AC-2
    when: "direct palace_graph functions and MCP graph tools read a populated LanceDB palace while LanceStore._get_embedder is guarded to fail after seeding"
    then: "graph_stats, find_tunnels, and traverse return the expected room/tunnel payloads without embedder errors or model-loading output"
  - id: AC-3
    when: "wake-up/recall/status and graph reads are pointed at a missing palace path with the embedder guarded to fail"
    then: "the user-visible no-palace or empty-graph responses are returned, the missing directory is not created, and no embedder/model-loading output appears"
  - id: AC-4
    when: "wake-up/recall/status and graph reads are pointed at an initialized but empty LanceDB palace with the embedder guarded to fail"
    then: "layers report no memories or zero drawers, graph stats return zero counts, and no embedder/model-loading output appears"
out_of_scope:
  - "Changing Layer3.search or Layer3.search_raw semantic-search behavior; query vector generation may still need the embedder."
  - "Changing searcher.py, code search, duplicate check, mining, import/export, cleanup, repair, migration, backup, or other mutation/maintenance paths."
  - "Changing the embedding model, LanceDB schema, schema migration behavior, or read_only semantics in storage.py."
  - "Changing MCP runtime store caching; runtime._get_store already requests read_only=True for create=False and only needs graph-tool regression coverage here."
contract_policy:
  flow: full_spdd
  reason: "Standard bug task touching CLI/MCP storage behavior and model-startup side effects"
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Layer wake-up, recall, and layer status reads must not initialize the LanceDB embedding model when only metadata/documents are needed."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-3, AC-4]
    - id: REQ-2
      statement: "Direct palace graph reads and graph-style MCP tools must not initialize the embedding model when building graph metadata from an existing palace."
      source: "backlog acceptance"
      acceptance_ids: [AC-2, AC-3, AC-4]
    - id: REQ-3
      statement: "Missing and empty palace boundaries must remain observable and must not create palace directories as a side effect of read-only flows."
      source: "failure and boundary acceptance"
      acceptance_ids: [AC-3, AC-4]
  surfaces:
    - name: "layer read paths"
      kind: "cli"
      paths: ["mempalace_code/layers.py", "tests/test_layers.py"]
      expected_behavior: "wake-up, recall, and layer status use read_only=True for metadata/document reads and preserve existing user-facing messages for absent or empty palaces."
    - name: "direct graph read paths"
      kind: "internal"
      paths: ["mempalace_code/palace_graph.py", "tests/test_palace_graph.py"]
      expected_behavior: "graph helpers that open their own store use read_only=True and return existing empty/error graph shapes without model startup."
    - name: "MCP graph regression coverage"
      kind: "api"
      paths: ["tests/test_mcp_server.py"]
      expected_behavior: "MCP graph tool calls prove the existing runtime read-only store path covers graph_stats, find_tunnels, and traverse without model startup."
  invariants:
    - id: INV-1
      statement: "Layer3 semantic search paths must keep their current search behavior and may initialize embeddings to compute query vectors."
      applies_to: ["mempalace_code/layers.py"]
    - id: INV-2
      statement: "Graph payload shapes, sorting, hop limits, tunnel filters, and fuzzy suggestions must remain compatible with existing tests."
      applies_to: ["mempalace_code/palace_graph.py", "tests/test_palace_graph.py"]
    - id: INV-3
      statement: "MCP read-to-write cache upgrade behavior must remain owned by runtime._get_store and must not be changed in this task."
      applies_to: ["tests/test_mcp_server.py"]
    - id: INV-4
      statement: "Write-capable store opens must still create or migrate schema when commands need mutation."
      applies_to: ["mempalace_code/layers.py", "mempalace_code/palace_graph.py"]
  risks:
    - id: RISK-1
      risk: "A read_only=True missing-table stub could turn a missing palace into a misleading empty-memory message."
      mitigation: "Keep explicit missing-palace handling before or after read-only open and cover missing and empty palaces separately."
    - id: RISK-2
      risk: "Changing all layer opens mechanically could break Layer3 semantic search by preventing query-vector generation."
      mitigation: "Change only metadata/document reads; list Layer3 search as out of scope and run the existing layer search E2E regression."
    - id: RISK-3
      risk: "Autouse deterministic embedder fixtures could hide real subprocess model-loading output."
      mitigation: "Add real CLI and MCP subprocess/dispatch smoke coverage that captures stdout and stderr and checks for common HF/model-loading markers."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_layers.py -k 'wake_up_recall_no_embedder or layer_status_no_embedder or wakeup_cli_smoke_no_model_output' -q"
      proves: "populated layer wake-up, recall, status, and real CLI wake-up reads avoid embedder startup and preserve seeded output"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_palace_graph.py -k 'read_only_no_embedder' -q"
      proves: "direct graph helpers open existing LanceDB graph metadata read-only and avoid embedder startup"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_mcp_server.py -k 'graph_tools_no_embedder' -q"
      proves: "MCP graph tool calls use the read-only runtime store and do not emit model-loading output"
      acceptance_ids: [AC-2]
    - id: VER-4
      command: "python -m pytest tests/test_layers.py tests/test_palace_graph.py -k 'missing_palace_no_embedder or empty_palace_no_embedder' -q"
      proves: "missing and empty palace boundaries do not create directories, do not initialize the embedder, and keep observable empty/no-palace results"
      acceptance_ids: [AC-3, AC-4]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_palace_graph.py -q"
        proves: "existing graph payload shapes, tunnel filters, traversal behavior, and empty-store output remain stable"
        acceptance_ids: [AC-2, AC-3, AC-4]
      - id: REG-2
        command: "python -m pytest tests/test_e2e.py -k 'layers_wake_up_recall_search_e2e or palace_graph_tunnels_e2e' -q"
        proves: "existing layer wake-up/recall/search and graph tunnel E2E behavior continues after read-only opens"
        acceptance_ids: [AC-1, AC-2]
      - id: REG-3
        command: "ruff check mempalace_code/layers.py mempalace_code/palace_graph.py tests/test_layers.py tests/test_palace_graph.py tests/test_mcp_server.py"
        proves: "changed source and focused regression tests remain lint-clean"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
---

## Design Notes

- `LanceStore(read_only=True)` already skips directory creation, schema migration, and `_ensure_embedder()` while allowing `count()` and `get()` metadata/document reads.
- In `layers.py`, change only non-semantic reads:
  - `Layer1.generate()` for L1 wake-up document/metadata scans.
  - `Layer2.retrieve()` for wing/room filtered document/metadata recall.
  - `MemoryStack.status()` for drawer counts.
- Keep `Layer3.search()` and `Layer3.search_raw()` on the existing `open_store(..., create=False)` path because `query()` computes a query embedding by design.
- Preserve missing-palace messaging separately from initialized-empty-palace messaging. A read-only Lance stub returns zero rows, so tests must distinguish a nonexistent palace path from a created empty Lance table.
- In `palace_graph.py`, update `_get_store()` to request `read_only=True`. If the read-only open returns a missing/uninitialized Lance table stub, the existing graph helpers should continue to return empty graph stats, empty tunnel lists, or the current traverse error shape.
- MCP graph handlers already obtain stores through `runtime._get_store()`, which uses `read_only=True` for `create=False`. Do not alter runtime caching in this task; add graph-tool coverage so the existing read-only path is protected.
- For no-embedder tests, seed any populated palace before patching `LanceStore._get_embedder` to raise. Keep the guard active only around read-only behavior under test.
- Capture both stdout and stderr in CLI/MCP smoke tests and assert common model-loading markers are absent: `Loading embedding model`, `Loading weights`, `huggingface`, and `sentence-transformers`.
