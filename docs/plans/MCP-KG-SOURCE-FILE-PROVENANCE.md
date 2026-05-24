---
slug: MCP-KG-SOURCE-FILE-PROVENANCE
goal: "Expose stored KG source_file provenance in MCP query, timeline, and relationship graph outputs."
risk: low
risk_note: "Additive result metadata only; storage schema, writers, temporal filtering, and tool inputs stay unchanged."
files:
  - path: mempalace_code/knowledge_graph.py
    change: "Include source_file in query_entity(), query_relationship(), and timeline() row dictionaries alongside existing temporal and source_closet metadata."
  - path: mempalace_code/mcp/tools/kg.py
    change: "Keep KG MCP wrappers pass-through and update tool descriptions if needed so returned fact rows document source_file provenance."
  - path: mempalace_code/mcp/tools/architecture.py
    change: "Preserve source_file on architecture relationship entries that expose KG fact rows, including project graph and reference/implementation helpers."
  - path: tests/test_mcp_server.py
    change: "Add focused MCP handler regressions for sourced rows, unsourced legacy rows, invalid temporal guards, and architecture graph provenance."
acceptance:
  - id: AC-1
    when: "tool_kg_add() stores AuthService implements IAuthService with source_file=src/auth.py and tool_kg_query(entity='IAuthService', direction='incoming') is called"
    then: "the returned AuthService fact includes source_file=src/auth.py while preserving the existing source_closet field when present."
  - id: AC-2
    when: "tool_kg_timeline(entity='AuthService') is called after a sourced AuthService fact is added"
    then: "the matching timeline row includes source_file=src/auth.py with the same subject, predicate, object, valid_from, valid_to, and current values."
  - id: AC-3
    when: "tool_show_project_graph() and tool_find_references() return current KG relationship rows seeded with source_file=src/app.csproj"
    then: "their relationship entries include source_file=src/app.csproj instead of dropping provenance during grouping or filtering."
  - id: AC-4
    when: "tool_kg_query(entity='Alice', as_of='two weeks ago') is called"
    then: "it still raises the existing invalid temporal ValueError before returning any result rows."
  - id: AC-5
    when: "KG query and timeline tools read legacy triples that were stored without source_file"
    then: "the triples are still returned with source_file null and no exception is raised."
out_of_scope:
  - "Changing KG storage schema, migrations, or add_triple()/tool_kg_add() write semantics."
  - "Backfilling source_file into existing KG rows that do not already have it."
  - "Changing MCP tool input schemas or adding source_file filters."
  - "Changing summarized architecture outputs that do not expose relationship entries, such as string-only symbol_graph summaries."
contract_policy:
  flow: full_spdd
  reason: "Standard behavior-changing MCP API output contract change across KG and architecture query surfaces."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "mempalace_kg_query must expose stored source_file provenance on returned fact rows when it exists."
      source: "backlog description"
      acceptance_ids: [AC-1]
    - id: REQ-2
      statement: "mempalace_kg_timeline must expose stored source_file provenance on returned timeline rows when it exists."
      source: "backlog description"
      acceptance_ids: [AC-2]
    - id: REQ-3
      statement: "Architecture relationship/project graph outputs must preserve source_file when they expose KG relationship entries."
      source: "backlog description"
      acceptance_ids: [AC-3]
    - id: REQ-4
      statement: "Invalid temporal arguments and legacy rows without source_file must keep their current behavior except for additive provenance metadata."
      source: "backlog acceptance criteria"
      acceptance_ids: [AC-4, AC-5]
  surfaces:
    - name: "KG query row shaping"
      kind: "internal"
      paths: ["mempalace_code/knowledge_graph.py"]
      expected_behavior: "query_entity(), query_relationship(), and timeline() return source_file from stored triples without changing filters, ordering, or temporal fields."
    - name: "KG MCP tools"
      kind: "api"
      paths: ["mempalace_code/mcp/tools/kg.py"]
      expected_behavior: "mempalace_kg_query and mempalace_kg_timeline expose the KG row metadata pass-through in normal MCP results."
    - name: "Architecture relationship tools"
      kind: "api"
      paths: ["mempalace_code/mcp/tools/architecture.py"]
      expected_behavior: "project graph and relationship helper outputs retain source_file for fact-derived entries while preserving existing grouping and filters."
    - name: "MCP provenance regression tests"
      kind: "internal"
      paths: ["tests/test_mcp_server.py"]
      expected_behavior: "focused handler tests exercise sourced facts, unsourced legacy facts, invalid temporal guards, and architecture graph provenance."
  invariants:
    - id: INV-1
      statement: "The triples table schema and stored source_file values remain unchanged."
      applies_to: ["mempalace_code/knowledge_graph.py"]
    - id: INV-2
      statement: "tool_kg_add() continues accepting optional source_file and source_closet without changing input names or validation."
      applies_to: ["mempalace_code/mcp/tools/kg.py", "mempalace_code/knowledge_graph.py"]
    - id: INV-3
      statement: "as_of filtering, valid_from/valid_to values, current calculation, and invalid temporal errors remain unchanged."
      applies_to: ["mempalace_code/knowledge_graph.py", "mempalace_code/mcp/tools/kg.py"]
    - id: INV-4
      statement: "tool_show_project_graph(solution=...) keeps the existing solution filter and empty-graph behavior for unknown solutions."
      applies_to: ["mempalace_code/mcp/tools/architecture.py"]
  risks:
    - id: RISK-1
      risk: "Adding source_file only in MCP wrappers could leave project graph and other internal KG callers without provenance."
      mitigation: "Shape source_file in KnowledgeGraph query methods, then keep MCP wrappers pass-through."
    - id: RISK-2
      risk: "query_relationship() could keep dropping provenance, leaving tool_show_project_graph incomplete."
      mitigation: "Add source_file to query_relationship() rows and cover project graph with a focused architecture test."
    - id: RISK-3
      risk: "Legacy triples with NULL source_file could be filtered out or trigger key errors."
      mitigation: "Add query and timeline coverage for unsourced triples and keep source_file null on those result rows."
    - id: RISK-4
      risk: "Architecture helpers that rebuild entries from fact rows could accidentally discard source_file."
      mitigation: "Copy provenance fields when building relationship entries and test grouped helper output."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_query_returns_source_file_provenance -q"
      proves: "mempalace_kg_query exposes source_file for a sourced KG fact and preserves source_closet."
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_timeline_returns_source_file_provenance -q"
      proves: "mempalace_kg_timeline exposes source_file on timeline rows without changing temporal fields."
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_mcp_server.py::TestArchTools::test_arch_relationship_outputs_include_source_file_provenance -q"
      proves: "project graph and reference helper rows retain source_file from KG relationship facts."
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_tools_reject_invalid_temporal_arguments_before_write -q"
      proves: "invalid as_of still raises the existing temporal validation error."
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_query_and_timeline_keep_legacy_unsourced_rows -q"
      proves: "legacy triples without source_file remain queryable through query and timeline tools."
      acceptance_ids: [AC-5]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_mcp_server.py::TestKGTools tests/test_mcp_server.py::TestArchTools -q"
        proves: "KG MCP and architecture tool behavior remains intact while provenance fields are added."
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
---

## Design Notes

- Keep the change at the KG row-construction layer first: `query_entity()`, `query_relationship()`, and `timeline()` already select `t.*`, so `source_file` is available as the stored triple column.
- Preserve `source_closet` behavior and add `source_file` beside it. Do not rename `source_closet` or convert stored paths to basenames.
- `tool_kg_query()` and `tool_kg_timeline()` should remain thin wrappers unless the tool descriptions need updated wording.
- `tool_show_project_graph()` depends on `query_relationship()`, so project graph provenance should flow from the shared KG method.
- For architecture helpers that transform fact rows into smaller entries, copy `source_file` only when it is present, matching the current conditional `source_closet` pattern.
- Treat old rows with `NULL` source_file as valid facts. They must stay visible in both query and timeline results.
