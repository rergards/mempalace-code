---
slug: ARCH-RETRIEVAL
goal: "Add MCP tool mempalace_explain_subsystem that combines semantic code search with KG traversal to answer 'how does this subsystem work?' queries"
risk: low
risk_note: "Composes two existing, well-tested primitives (code_search from searcher.py and query_entity from KnowledgeGraph). No schema changes, no new storage, no new dependencies. The only new code is orchestration logic in mcp_server.py. Note: KG entity identity uses short (unqualified) type names — same-named symbols from different namespaces/projects coalesce into one entity node (inherited from MCP-ARCH-TOOLS / DOTNET-SYMBOL-GRAPH). This tool surfaces all matches; callers must disambiguate if needed. A future task can add qualified subjects if disambiguation is needed."
files:
  - path: mempalace/mcp_server.py
    change: "Add tool_explain_subsystem() handler that (1) calls code_search() to find entry point chunks, (2) post-filters to code-shaped hits only (non-empty symbol_name), (3) extracts unique symbol_name values from filtered results, (4) expands each symbol via _kg.query_entity(direction='both') with relationship categorization filtering to current facts only, (5) returns structured {entry_points, symbol_graph, summary}. Add TOOLS dict entry for mempalace_explain_subsystem with input_schema. Update module docstring tool inventory to include the new tool."
  - path: tests/test_mcp_server.py
    change: "Add TestExplainSubsystem class with tests: basic query returns entry_points + symbol_graph; symbols from search results are expanded via KG; empty KG returns valid response; wing/language filters narrow results; no search results returns empty response; expired KG relationships excluded from symbol_graph; mixed palace (code + non-code drawers) returns only code-shaped entry_points. Tests use code_seeded_collection + KG fixtures; mixed-palace test adds non-code drawers alongside code drawers."
acceptance:
  - id: AC-1
    when: "mempalace_explain_subsystem is called with query='vector storage backend'"
    then: "Returns entry_points list containing matched code chunks with text, source_file, symbol_name, symbol_type, language, and similarity fields"
  - id: AC-2
    when: "Search results contain symbol 'LanceStore' and KG has (LanceStore, implements, IStore)"
    then: "symbol_graph contains 'LanceStore' key with 'implements' relationship listing 'IStore'"
  - id: AC-3
    when: "Search results contain symbols but KG has no relationships for them"
    then: "Returns valid response with entry_points populated and symbol_graph entries having empty relationship categories"
  - id: AC-4
    when: "mempalace_explain_subsystem is called with wing='mempalace'"
    then: "Only entry points from the 'mempalace' wing are returned"
  - id: AC-5
    when: "mempalace_explain_subsystem is called with language='python'"
    then: "Only Python-language entry points are returned"
  - id: AC-6
    when: "Query matches no code chunks in the palace"
    then: "Returns {entry_points: [], symbol_graph: {}, summary: {symbols_found: 0, relationships_found: 0, entry_point_count: 0}} — no error"
  - id: AC-7
    when: "Palace does not exist (no store)"
    then: "Returns standard error dict with hint to run init + mine"
  - id: AC-8
    when: "mempalace_explain_subsystem appears in tools/list MCP response"
    then: "Has name, description, and inputSchema with query (required), wing, language, n_results"
  - id: AC-9
    when: "Running `python -m pytest tests/ -x -q` and `ruff check mempalace/ tests/`"
    then: "All tests pass and lint is clean"
  - id: AC-10
    when: "KG has (LanceStore, implements, IStore) with valid_until in the past (expired)"
    then: "symbol_graph for LanceStore does not include the expired 'implements' relationship"
  - id: AC-11
    when: "Palace contains both code drawers (with symbol_name) and non-code drawers (prose, no symbol metadata) and a subsystem query matches both"
    then: "entry_points contains only code-shaped hits (non-empty symbol_name); non-code drawers are excluded"
out_of_scope:
  - "Second-round search for KG-discovered symbols not in original results — only symbols found via semantic search are expanded"
  - "Recursive graph expansion (type_dependency_chain) — tool uses single-hop KG queries, not multi-depth walks. Use show_type_dependencies for deep chains."
  - "Visualization output (Mermaid, DOT) — returns structured JSON, rendering is the caller's job"
  - "New CLI command — MCP-only tool"
  - "Changes to searcher.py — code_search() already returns symbol metadata; the tool handler post-filters to code-shaped hits (non-empty symbol_name) rather than modifying the searcher itself"
  - "Extracting shared category_map with tool_find_references — same dict is small and stable; premature abstraction"
---

## Design Notes

### Composition pattern: search + KG expansion in mcp_server.py

The handler `tool_explain_subsystem()` lives in `mcp_server.py` alongside the other arch tools. It composes two existing primitives:
- `code_search()` from `searcher.py` (called via the existing import) for semantic retrieval
- `_kg.query_entity()` from the KG singleton for relationship expansion

This follows the established pattern: arch tools are thin compositions over existing query primitives, with no new storage or schema changes. The difference from the 4 existing arch tools is that this one touches both the vector store (search) and the KG (expansion), making it the first "bridge" tool.

### Algorithm

```
tool_explain_subsystem(query, wing=None, language=None, n_results=5):
  1. store = _get_store() — fail with hint if no palace
  2. raw = code_search(palace_path, query, wing=wing, language=language,
                       n_results=n_results * 2)   # over-fetch to compensate for post-filter
  3. entry_points = [r for r in raw["results"] if r.get("symbol_name")]  # code-shaped only
  4. entry_points = entry_points[:n_results]  # trim to requested count
  5. symbols = {ep["symbol_name"] for ep in entry_points}
  6. For each symbol in symbols:
     a. facts = _kg.query_entity(symbol, direction="both")
     b. Filter to current facts (f["current"] == True)
     c. Categorize using same (direction, predicate) → category mapping as tool_find_references
     d. Store in symbol_graph[symbol] = {category: [type_names]}
  7. Return {query, entry_points, symbol_graph, summary}
```

**Note on over-fetching (step 2):** `code_search()` does not filter by `symbol_name` presence, so a mixed palace can return prose drawers that lack symbol metadata. We request `n_results * 2` from `code_search()` so that after discarding non-code hits in step 3, we still return up to `n_results` code-shaped entry points. The `* 2` heuristic is simple and sufficient — in code-heavy palaces almost nothing is discarded; in mixed palaces the overfetch compensates.

### Filter scoping: wing/language apply to retrieval only

`wing` and `language` parameters constrain the initial `code_search()` call (step 2) — they determine which entry points are returned. The KG expansion (step 6) is **unconstrained**: all current relationships for a discovered symbol are surfaced regardless of wing. This is intentional — a type's inheritance chain and dependencies are architectural facts that cross project boundaries. The existing arch tools (`find_references`, `show_type_dependencies`) follow the same pattern.

### Relationship categorization reuses find_references logic

The `(direction, predicate) → category` mapping is identical to `tool_find_references`:
- incoming implements → implementors
- incoming inherits → subclasses
- incoming extends → sub_interfaces
- outgoing implements/inherits/extends → implements/inherits/extends
- incoming/outgoing depends_on/references_project → depended_by/referenced_by/depends_on/references_project

The map is inlined (not extracted to a shared constant) because it's small, stable, and the cost of duplication is lower than the coupling of a shared abstraction.

### Return format

```json
{
  "query": "vector storage backend",
  "entry_points": [
    {
      "text": "class LanceStore: vector storage backend...",
      "source_file": "/project/mempalace/storage.py",
      "symbol_name": "LanceStore",
      "symbol_type": "class",
      "language": "python",
      "similarity": 0.85
    }
  ],
  "symbol_graph": {
    "LanceStore": {
      "implements": ["IStore"],
      "inherits": ["BaseStore"],
      "subclasses": ["MockStore"]
    }
  },
  "summary": {
    "entry_point_count": 1,
    "symbols_found": 1,
    "relationships_found": 3
  }
}
```

- `entry_points` preserves the full code_search result format (text, source_file, symbol_name, symbol_type, language, similarity). Only **code-shaped** hits are included — defined as results with a non-empty `symbol_name`. Prose drawers, documentation, and other non-code content from `code_search()` are filtered out.
- `symbol_graph` maps each symbol to its categorized relationships — values are flat type name lists (not dicts), keeping the response concise for LLM consumption
- `summary` provides counts for quick assessment without scanning the full response
- Empty categories are omitted from each symbol's entry (same as find_references)
- Symbols with no KG relationships still appear in symbol_graph with an empty dict

### Test strategy

Tests use the existing `code_seeded_collection` fixture (which has code drawers with symbol metadata) combined with KG triples. The `_patch_mcp_server` helper patches `_config`, `_kg`, and `_store` as usual.

Test fixture needs: `code_seeded_collection` creates drawers with symbols like `LanceStore` (class, python) and `detect_language` (function, python). Add KG triples for those symbols (e.g. `LanceStore implements DrawerStore`) to test the search->KG expansion pipeline end-to-end.

**Additional test scenarios (from review):**

1. **Expired KG relationships (AC-10):** Seed a KG triple with `valid_until` in the past for a symbol that appears in search results. Assert the expired relationship is absent from `symbol_graph`. This mirrors the pattern established in MCP-ARCH-TOOLS where `current == True` filtering is the caller's responsibility.

2. **Mixed-palace code-only filtering (AC-11):** Seed the collection with both code drawers (having `symbol_name`) and non-code drawers (prose, empty `symbol_name`). Use a query that semantically matches both. Assert `entry_points` contains only the code-shaped hits. This validates the post-filter in step 3 of the algorithm.

### Tool count

After this task: 28 existing + 1 new = 29 tools. No count assertions need updating (tests assert by tool name, not count).
