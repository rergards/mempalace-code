---
slug: MCP-ARCH-TOOLS
goal: "Add 4 architecture-oriented MCP tools (find_implementations, find_references, show_project_graph, show_type_dependencies) that query mined .NET type relationships and project dependencies from the KG"
risk: low
risk_note: "All 4 tools compose existing KG query primitives (query_entity, query_relationship) — no schema changes, no storage changes, no new dependencies. Type relationships and project dependencies are already mined and stored. Only risk is the recursive graph walk in show_type_dependencies hitting cycles, mitigated by visited-set + max_depth. Note: KG entity identity uses short (unqualified) type names — same-named types from different namespaces/projects coalesce into one entity node (per DOTNET-SYMBOL-GRAPH). Tools surface all matches; callers must disambiguate if needed."
files:
  - path: mempalace/knowledge_graph.py
    change: "Add type_dependency_chain(type_name, max_depth) method — recursive graph walk following inherits/implements/extends predicates up (ancestors) and down (descendants) with cycle detection via visited set"
  - path: mempalace/mcp_server.py
    change: "Add 4 tool handler functions (tool_find_implementations, tool_find_references, tool_show_project_graph, tool_show_type_dependencies) and their TOOLS dict entries with input schemas. Also update mempalace_code_search description strings to list the new .NET languages and symbol types."
  - path: mempalace/searcher.py
    change: "Add csharp, fsharp, vbnet, xaml, dotnet-solution to SUPPORTED_LANGUAGES; add record, enum, property, event, module, union, type, view, exception to VALID_SYMBOL_TYPES (view is emitted for XAML x:Class elements)"
  - path: tests/test_mcp_server.py
    change: "Add TestArchTools class with tests for all 4 tools: find_implementations returns implementers, find_references returns categorized relationships, show_project_graph returns project-level triples, show_type_dependencies returns ancestor/descendant flat lists with depth. Tests use seeded KG with .NET-style type relationships."
  - path: tests/test_searcher.py
    change: "Add tests for code_search() with .NET language filters (language='csharp') and new symbol_type filters (symbol_type='record', symbol_type='view') to verify the whitelist additions in searcher.py"
acceptance:
  - id: AC-1
    when: "KG contains (MyService, implements, IService) and mempalace_find_implementations is called with interface='IService'"
    then: "Returns {implementations: [{type: 'MyService', ...}], count: 1}"
  - id: AC-2
    when: "mempalace_find_implementations is called with an interface that has no implementers"
    then: "Returns {implementations: [], count: 0} — no error"
  - id: AC-3
    when: "KG contains multiple types implementing IDisposable and mempalace_find_implementations is called with interface='IDisposable'"
    then: "All implementers are returned"
  - id: AC-4
    when: "mempalace_find_references is called with type_name='MyService'"
    then: "Returns categorized relationships with canonical keys: implementors (incoming implements), subclasses (incoming inherits), sub_interfaces (incoming extends), implements (outgoing implements), inherits (outgoing inherits), extends (outgoing extends), depended_by (incoming depends_on), referenced_by (incoming references_project), depends_on (outgoing depends_on), references_project (outgoing references_project). Empty categories are omitted."
  - id: AC-5
    when: "mempalace_show_project_graph is called after mining a .NET solution"
    then: "Returns project-level triples grouped by predicate: depends_on, references_project, targets_framework, has_output_type, contains_project"
  - id: AC-6
    when: "mempalace_show_project_graph is called with solution='MySolution'"
    then: "Returns only projects contained in MySolution and their dependencies"
  - id: AC-7
    when: "mempalace_show_type_dependencies is called with type_name='MyService' and KG has MyService implements IService, MyService inherits BaseService, SpecialService inherits MyService"
    then: "Returns ancestors: [{type: IService, relationship: implements}, {type: BaseService, relationship: inherits}] and descendants: [{type: SpecialService, relationship: inherits}]"
  - id: AC-8
    when: "mempalace_show_type_dependencies encounters a circular reference in the KG"
    then: "Does not infinite-loop — visited set prevents re-traversal"
  - id: AC-9
    when: "mempalace_show_type_dependencies is called with max_depth=1"
    then: "Returns only direct parents and children, not transitive relationships"
  - id: AC-10
    when: "code_search is called with language='csharp'"
    then: "Returns results filtered to csharp language — no 'unsupported language' error"
  - id: AC-11
    when: "code_search is called with symbol_type='record' or symbol_type='view'"
    then: "Returns results filtered to that symbol type — no 'invalid symbol_type' error"
  - id: AC-12
    when: "All 4 new tools appear in tools/list MCP response"
    then: "Each has name, description, and inputSchema"
  - id: AC-13
    when: "Running `python -m pytest tests/ -x -q` and `ruff check mempalace/ tests/`"
    then: "All tests pass and lint is clean"
out_of_scope:
  - "Graphviz/DOT/Mermaid visualization output — tools return structured JSON, rendering is the caller's job"
  - "Cross-project type resolution (types from NuGet packages) — only mined source types are queryable"
  - "Method-level reference tracking (call graphs, parameter/return type usage) — only type-level relationships from KG"
  - "Real-time source parsing at query time — tools query pre-mined KG data only"
  - "New CLI commands — these are MCP-only tools"
  - "Namespace-qualified entity disambiguation — KG entities use short type names (per DOTNET-SYMBOL-GRAPH); same-named types from different namespaces coalesce. A future task can add namespace-qualified subjects if disambiguation is needed."
---

## Design Notes

### Tool implementations are thin KG query compositions

All 4 tools use existing `KnowledgeGraph.query_entity()` and `query_relationship()` methods.
No new storage, no new embedding, no new mining. The data is already there from DOTNET-SYMBOL-GRAPH
and MINE-DOTNET — these tools just provide purpose-built query interfaces.

### find_implementations

- Calls `_kg.query_entity(interface, direction="incoming")`
- Post-filters to `predicate == "implements"` and `current == True`
  (note: `query_entity()` returns all facts including expired; caller must filter)
- Returns flat list of implementing type names with source info

### find_references

- Calls `_kg.query_entity(type_name, direction="both")`
- Post-filters to `current == True` (excludes expired/invalidated triples by default)
- Groups results by (direction, predicate) into canonical categories:
  - `implementors` (incoming `implements`)
  - `subclasses` (incoming `inherits`)
  - `sub_interfaces` (incoming `extends`)
  - `implements` (outgoing `implements`)
  - `inherits` (outgoing `inherits`)
  - `extends` (outgoing `extends`)
  - `depended_by` (incoming `depends_on`) — project-level
  - `referenced_by` (incoming `references_project`) — project-level
  - `depends_on` (outgoing `depends_on`) — project-level
  - `references_project` (outgoing `references_project`) — project-level
- Empty categories are omitted from the response
- Single KG round-trip, post-filter in Python

### show_project_graph

- Calls `_kg.query_relationship(predicate)` for each project-level predicate:
  `depends_on`, `references_project`, `targets_framework`, `has_output_type`, `contains_project`
- Post-filters all results to `current == True` (excludes expired triples)
- Optional `solution` param: first resolves the solution's `contains_project` triples to get
  project names, then filters all other predicate results to only those whose subject is a
  contained project. Outgoing edges to external packages/projects ARE included (e.g. NuGet deps)
  because the caller needs to see what the solution depends on.
- 5 KG queries total (fast — SQLite indexed on predicate)

### show_type_dependencies (recursive walk)

- New method `KnowledgeGraph.type_dependency_chain(type_name, max_depth=3)` handles the recursion
- Only follows `current == True` triples (expired relationships excluded)
- Walk up: from the type, follow outgoing `inherits`/`implements`/`extends` predicates
- Walk down: from the type, follow incoming `inherits`/`implements`/`extends` predicates
- Cycle detection via `visited: set` — prevents infinite loops on malformed KG data
- `max_depth` caps traversal (default 3, matches typical .NET inheritance depth)
- Returns flat lists with depth metadata, not a recursive tree:
  ```json
  {
    "type": "MyService",
    "ancestors": [
      {"type": "IService", "relationship": "implements", "depth": 1},
      {"type": "IDisposable", "relationship": "extends", "depth": 2}
    ],
    "descendants": [
      {"type": "SpecialService", "relationship": "inherits", "depth": 1}
    ]
  }
  ```
- Ancestors and descendants use separate visited sets so the same intermediate type
  can appear in both directions

### SUPPORTED_LANGUAGES / VALID_SYMBOL_TYPES fix

Prerequisite for code_search to work with .NET languages. The miner already tags drawers
with `language='csharp'` etc., but `code_search()` rejects these as unsupported.

Add to `SUPPORTED_LANGUAGES`: `csharp`, `fsharp`, `vbnet`, `xaml`, `dotnet-solution`
Add to `VALID_SYMBOL_TYPES`: `record`, `enum`, `property`, `event`, `module`, `union`, `type`, `view`, `exception`
(Note: `view` is already emitted for XAML x:Class elements — tests/test_miner.py:1659)

Also update the `mempalace_code_search` tool description in `mcp_server.py` to list the new
languages and symbol types in the schema description strings, so callers know they're available.

### Test fixtures

Tests use the existing `seeded_kg` pattern from `conftest.py` but need .NET-specific triples.
Create a `dotnet_kg` fixture (or inline setup) that seeds:
- `(MyService, implements, IService)`
- `(MyService, inherits, BaseService)`
- `(SpecialService, inherits, MyService)`
- `(IService, extends, IDisposable)`
- `(MyApp, depends_on, Newtonsoft.Json@13.0.3)`
- `(MyApp, references_project, Shared)`
- `(MyApp, targets_framework, net8.0)`
- `(MySolution, contains_project, MyApp)`

This covers all predicates and provides enough graph depth for chain-walk tests.

### MCP tool count

After this task: 24 existing + 4 new = 28 tools. Verify current count from `mcp_server.py`
TOOLS dict and update the module docstring accordingly. Current tests assert tool presence
by name (not count), so no count assertion needs updating.
