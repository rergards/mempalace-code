---
slug: QUAL-OPTIONAL-ANNOTATIONS
goal: "Normalize default-None annotations so optional contracts are explicit without runtime behavior changes."
risk: medium
risk_note: "The edits are mechanical annotations, but many public CLI/MCP/search signatures expose optional filters and omitted-argument defaults."
files:
  - path: mempalace_code/convo_miner.py
    change: "Annotate conversation mining optional wing/category inputs with explicit None-aware types while preserving default wing derivation."
  - path: mempalace_code/layers.py
    change: "Annotate layer stack constructor and lookup filters that accept omitted palace, identity, wing, and room values."
  - path: mempalace_code/searcher.py
    change: "Annotate search and code_search optional filters and rerank mode without changing result formatting or validation."
  - path: mempalace_code/knowledge_graph.py
    change: "Annotate knowledge graph optional DB path, entity properties, temporal bounds, source metadata, sentinels, and query filters."
  - path: mempalace_code/palace_graph.py
    change: "Annotate optional tunnel wing filters while preserving all-wings behavior when filters are omitted."
  - path: mempalace_code/miner.py
    change: "Annotate optional scan, room-map, language, wing override, and include-ignored parameters used by mining and room detection."
  - path: mempalace_code/watcher.py
    change: "Annotate optional watch wing override and include-ignored inputs while preserving forwarding to mine()."
  - path: mempalace_code/onboarding.py
    change: "Annotate optional config path, projects, and alias inputs used by onboarding defaults."
  - path: mempalace_code/dialect.py
    change: "Annotate optional encoder maps, metadata, output paths, and identity sections used by AAAK compression helpers."
  - path: mempalace_code/entity_registry.py
    change: "Annotate optional registry config and alias inputs."
  - path: mempalace_code/mcp/tools/search.py
    change: "Annotate MCP search/code_search/file_context optional filters and rerank mode."
  - path: mempalace_code/mcp/tools/read.py
    change: "Annotate optional list_rooms wing filter."
  - path: mempalace_code/mcp/tools/graph.py
    change: "Annotate optional tunnel wing filters."
  - path: mempalace_code/mcp/tools/kg.py
    change: "Annotate MCP knowledge graph optional temporal and source inputs."
  - path: mempalace_code/mcp/tools/architecture.py
    change: "Annotate optional architecture solution, wing, and language filters."
  - path: mempalace_code/mcp/tools/write.py
    change: "Annotate optional source file and mine wing inputs."
  - path: tests/test_cli.py
    change: "Annotate the mine-all test helper optional extra args so tests remain Pyright-clean."
acceptance:
  - id: AC-1
    when: "MCP search and code-search are called with omitted optional filters and with explicit wing/language/symbol filters"
    then: "Results retain the existing filter semantics and response field shapes."
  - id: AC-2
    when: "Search APIs receive None metadata/document rows and post-filters that require metadata fields"
    then: "They return fallback values or filtered hits without raising."
  - id: AC-3
    when: "Knowledge graph calls omit temporal optional arguments, provide as_of dates, or invalidate with an ended date"
    then: "Open-ended facts, date-filtered facts, and invalidated facts match existing query results."
  - id: AC-4
    when: "Mining, watcher, and CLI helpers are invoked with omitted optional include, room-map, and extra-arg parameters"
    then: "Default discovery, mine-all argv construction, watch forwarding, and room fallback behavior remain unchanged."
  - id: AC-5
    when: "The codebase is type-checked after cleanup"
    then: "Pyright reports no diagnostics caused by annotated parameters or attributes defaulting to None."
out_of_scope:
  - "Do not remove Pyright CI continue-on-error or otherwise change CI gating; that belongs to the broader Pyright cleanup task."
  - "Do not rewrite already-correct Optional[...] annotations unless the same declaration is being touched for this task."
  - "Do not introduce Pyright suppressions or weaken pyproject.toml typing settings to hide remaining diagnostics."
  - "Do not change public CLI/MCP argument names, defaults, schemas, or return payloads."
contract_policy:
  flow: full_spdd
  reason: "Standard quality task touching public CLI/MCP/API signatures and Pyright-facing typing contracts."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "Every touched declaration that accepts None as a default or state must expose that in its annotation."
      source: "backlog description"
      acceptance_ids: [AC-5]
    - id: REQ-2
      statement: "Search, MCP, knowledge graph, mining, watcher, and CLI behavior must remain compatible for omitted optional arguments."
      source: "backlog scope and compatibility requirement"
      acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
    - id: REQ-3
      statement: "Type widening must not replace runtime guards or invariants when None is not a valid value."
      source: "backlog scope"
      acceptance_ids: [AC-2, AC-5]
  surfaces:
    - name: "Search and MCP filters"
      kind: api
      paths:
        - mempalace_code/searcher.py
        - mempalace_code/mcp/tools/search.py
        - mempalace_code/mcp/tools/read.py
        - mempalace_code/mcp/tools/graph.py
        - mempalace_code/mcp/tools/kg.py
        - mempalace_code/mcp/tools/architecture.py
        - mempalace_code/mcp/tools/write.py
      expected_behavior: "Optional filters keep omitted-argument defaults and explicit-filter semantics while annotations become None-aware."
    - name: "Knowledge graph temporal API"
      kind: internal
      paths:
        - mempalace_code/knowledge_graph.py
      expected_behavior: "Open-ended temporal bounds, source fields, properties, and query filters continue to accept omitted values."
    - name: "Mining, watcher, and ingestion helpers"
      kind: cli
      paths:
        - mempalace_code/convo_miner.py
        - mempalace_code/miner.py
        - mempalace_code/watcher.py
        - tests/test_cli.py
      expected_behavior: "Omitted wing, include, room-map, language, and extra-argument values keep existing default behavior."
    - name: "Layer, graph, onboarding, dialect, and registry helpers"
      kind: internal
      paths:
        - mempalace_code/layers.py
        - mempalace_code/palace_graph.py
        - mempalace_code/onboarding.py
        - mempalace_code/dialect.py
        - mempalace_code/entity_registry.py
      expected_behavior: "Helper defaults continue to derive configured paths, all-wing/all-room queries, and empty maps/lists from None."
  invariants:
    - id: INV-1
      statement: "Function names, parameter order, defaults, and MCP schemas remain unchanged."
      applies_to:
        - mempalace_code/mcp/tools/search.py
        - mempalace_code/mcp/tools/read.py
        - mempalace_code/mcp/tools/graph.py
        - mempalace_code/mcp/tools/kg.py
        - mempalace_code/mcp/tools/architecture.py
        - mempalace_code/mcp/tools/write.py
        - mempalace_code/searcher.py
    - id: INV-2
      statement: "None continues to mean omitted/default for filters, paths, temporal bounds, metadata maps, and include lists."
      applies_to:
        - mempalace_code/convo_miner.py
        - mempalace_code/layers.py
        - mempalace_code/searcher.py
        - mempalace_code/knowledge_graph.py
        - mempalace_code/miner.py
        - mempalace_code/watcher.py
        - mempalace_code/onboarding.py
        - mempalace_code/dialect.py
        - mempalace_code/entity_registry.py
    - id: INV-3
      statement: "Typing cleanup must not add suppressions, weaken Pyright settings, or broaden invalid required parameters to optional."
      applies_to:
        - pyproject.toml
        - mempalace_code
  risks:
    - id: RISK-1
      risk: "A mechanical annotation edit could accidentally change a default value or public MCP signature."
      mitigation: "Keep edits annotation-only and cover MCP search/code-search/list/read/write wrappers with focused tests."
    - id: RISK-2
      risk: "Broad optionalization could hide a real invariant where None should not be accepted."
      mitigation: "Only annotate declarations that already default to None or already store None; leave required parameters required."
    - id: RISK-3
      risk: "Modern union syntax may leave stale typing imports or format issues."
      mitigation: "Run Ruff check/format checks on touched files after implementation and remove only imports made unused by touched edits."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_mcp_server.py::TestSearchTool::test_search_with_wing_filter tests/test_mcp_server.py::TestCodeSearchTool::test_code_search_combined_filters -q"
      proves: "MCP search and code-search keep optional filter semantics and response shapes."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_searcher.py::TestNoneMetadataRobustness -q"
      proves: "Search APIs tolerate None document/metadata rows and post-filter boundary cases."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_knowledge_graph.py::TestTripleOperations::test_add_triple_with_dates tests/test_knowledge_graph.py::TestQueries::test_query_as_of_filters_expired tests/test_knowledge_graph.py::TestInvalidation::test_invalidate_sets_valid_to -q"
      proves: "Knowledge graph optional temporal arguments retain open-ended, as-of, and invalidation behavior."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_miner.py::TestDetectRoomCsprojMap::test_no_csproj_map_unchanged tests/test_watcher.py::TestWatchAndMine::test_watch_passes_respect_gitignore_and_include_ignored tests/test_cli.py::TestMineAllCommand::test_mine_all_basic -q"
      proves: "Mining, watcher, and CLI omitted-optional defaults remain compatible."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
      proves: "Pyright no longer reports diagnostics from non-optional annotations defaulting to None."
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "ruff check mempalace_code/convo_miner.py mempalace_code/layers.py mempalace_code/searcher.py mempalace_code/knowledge_graph.py mempalace_code/palace_graph.py mempalace_code/miner.py mempalace_code/watcher.py mempalace_code/onboarding.py mempalace_code/dialect.py mempalace_code/entity_registry.py mempalace_code/mcp/tools/search.py mempalace_code/mcp/tools/read.py mempalace_code/mcp/tools/graph.py mempalace_code/mcp/tools/kg.py mempalace_code/mcp/tools/architecture.py mempalace_code/mcp/tools/write.py tests/test_cli.py"
      proves: "Touched files remain lint-clean after annotation modernization."
      acceptance_ids: [AC-5]
    - id: VER-7
      command: "ruff format --check mempalace_code/convo_miner.py mempalace_code/layers.py mempalace_code/searcher.py mempalace_code/knowledge_graph.py mempalace_code/palace_graph.py mempalace_code/miner.py mempalace_code/watcher.py mempalace_code/onboarding.py mempalace_code/dialect.py mempalace_code/entity_registry.py mempalace_code/mcp/tools/search.py mempalace_code/mcp/tools/read.py mempalace_code/mcp/tools/graph.py mempalace_code/mcp/tools/kg.py mempalace_code/mcp/tools/architecture.py mempalace_code/mcp/tools/write.py tests/test_cli.py"
      proves: "Touched files retain repository formatting after annotation modernization."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_mcp_server.py::TestSearchTool::test_search_with_wing_filter tests/test_mcp_server.py::TestCodeSearchTool::test_code_search_combined_filters -q"
        proves: "Public MCP optional filter behavior did not regress."
        acceptance_ids: [AC-1]
      - id: REG-2
        command: "python -m pytest tests/test_searcher.py::TestNoneMetadataRobustness -q"
        proves: "Search None-boundary behavior did not regress."
        acceptance_ids: [AC-2]
      - id: REG-3
        command: "python -m pytest tests/test_knowledge_graph.py::TestTripleOperations::test_add_triple_with_dates tests/test_knowledge_graph.py::TestQueries::test_query_as_of_filters_expired tests/test_knowledge_graph.py::TestInvalidation::test_invalidate_sets_valid_to -q"
        proves: "Knowledge graph optional temporal behavior did not regress."
        acceptance_ids: [AC-3]
      - id: REG-4
        command: "python -m pytest tests/test_miner.py::TestDetectRoomCsprojMap::test_no_csproj_map_unchanged tests/test_watcher.py::TestWatchAndMine::test_watch_passes_respect_gitignore_and_include_ignored tests/test_cli.py::TestMineAllCommand::test_mine_all_basic -q"
        proves: "Mining, watcher, and CLI omitted-optional behavior did not regress."
        acceptance_ids: [AC-4]
      - id: REG-5
        command: "python -m pyright --pythonpath \"$(python -c 'import sys; print(sys.executable)')\""
        proves: "No new non-optional default-None annotations were reintroduced; Pyright diagnostics from the touched declarations remain resolved."
        acceptance_ids: [AC-5]
---

## Design Notes

- Use `T | None` for newly touched annotations because the package targets Python 3.11+.
- Prefer exact narrow unions such as `str | None`, `Path | None`, `list | None`, and `dict | None`; use imported generic shapes only where they are already local and narrow.
- Do not convert unannotated local sentinel assignments like `where = None`, `lang = None`, or `_fix = None`; the task is about misleading declared contracts.
- Do not turn required public parameters optional unless the declaration already defaults to `None`.
- Remove `Optional` imports only when this cleanup makes them unused in the touched file.
- Treat `Any = None` protocol placeholders as out of scope unless Pyright reports them as part of the default-`None` diagnostic family.
