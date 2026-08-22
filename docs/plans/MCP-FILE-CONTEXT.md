---
slug: MCP-FILE-CONTEXT
status: completed
authority: non_authoritative
goal: "Add mempalace_file_context MCP tool — return all indexed chunks for a source file, ordered by chunk_index"
risk: low
risk_note: "Pure additive change — new handler + TOOLS entry + tests; no existing code or schema altered"
files:
  - path: mempalace/mcp_server.py
    change: "Add tool_file_context() handler and register mempalace_file_context in TOOLS dict"
  - path: tests/test_mcp_server.py
    change: "Add TestFileContextTool class covering happy path, missing file, wing filter, ordering"
acceptance:
  - id: AC-1
    when: "mempalace_file_context is called with a source_file that has 3 indexed chunks"
    then: "returns {total: 3, chunks: [...]} with each chunk containing chunk_index, content, symbol_name, symbol_type, wing, room, language, line_range"
  - id: AC-2
    when: "mempalace_file_context is called with a source_file that does not exist in the palace"
    then: "returns {total: 0, chunks: []} (no error key)"
  - id: AC-3
    when: "mempalace_file_context is called with a source_file present in two wings and wing=<one of them>"
    then: "returns only the chunks from the specified wing (total matches that wing's count, not the combined count)"
  - id: AC-4
    when: "mempalace_file_context is called for a file whose chunks were inserted in reverse chunk_index order"
    then: "chunks in the response are sorted ascending by chunk_index (0, 1, 2, …)"
  - id: AC-5
    when: "mempalace_file_context is called when no palace exists"
    then: "returns the standard no-palace error dict (contains 'error' key and 'hint' key)"
  - id: AC-6
    when: "tools/list MCP request is made"
    then: "mempalace_file_context appears in the tool list with source_file as a required parameter"
out_of_scope:
  - "Adding line_start/line_end fields to the storage schema (not stored by the miner; line_range returns null)"
  - "Pagination — limit parameter is out of scope; all chunks for a file are returned in one call"
  - "Fuzzy/glob source_file matching — only exact equality match"
  - "Any changes to searcher.py, storage.py, or the miner"
---

## Design Notes

- **Query pattern**: `col.get(where={"source_file": source_file}, include=["documents", "metadatas"], limit=10000)`. Wing filter uses `$and` compound: `{"$and": [{"source_file": source_file}, {"wing": wing}]}`. Both patterns are already exercised by existing tools (e.g., `tool_diary_read`, `delete_by_source_file`).

- **Sorting**: LanceDB does not guarantee insertion order. Sort the result list in Python by `meta.get("chunk_index", 0)` after retrieval before building the response.

- **`line_range` field**: The storage schema (`_META_FIELD_SPEC` in `storage.py`) has no `line_start`/`line_end` columns. The searcher already returns `"line_range": None` for the same reason. Return `"line_range": null` per chunk so the shape is consistent with `code_search` output — agents can rely on the field being present.

- **Response shape**:
  ```json
  {
    "source_file": "<input>",
    "wing": "<wing filter or null>",
    "total": 3,
    "chunks": [
      {
        "chunk_index": 0,
        "content": "...",
        "symbol_name": "...",
        "symbol_type": "...",
        "wing": "...",
        "room": "...",
        "language": "...",
        "line_range": null
      }
    ]
  }
  ```

- **TOOLS registration**: Follow the existing pattern — add a `"mempalace_file_context"` key to the `TOOLS` dict with `description`, `input_schema` (source_file required, wing optional), and `handler`. No changes to the MCP dispatch loop are needed.

- **Test fixture**: The `TestFileContextTool` tests should seed a small store directly with `col.add()` (not through `tool_add_drawer`, which de-dupes) so chunk_index values can be controlled. Mirror the pattern in `TestCodeSearchTool` — use the `monkeypatch`, `config`, `palace_path`, `kg` fixtures.

- **Empty-palace path**: `_get_store()` returns `None` when the palace is absent. Return `_no_palace()` in that case (consistent with every other read tool).
