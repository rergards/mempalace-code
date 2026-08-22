---
slug: STORE-SEARCH-SOURCE-FILE-FULL-PATH
status: completed
authority: non_authoritative
goal: "Return the full stored source_file path from search_memories, matching code_search."
risk: low
risk_note: "Single-field output change in a narrow API path; callers relying on basename-only values may need adjustment."
files:
  - path: mempalace/searcher.py
    change: "Remove basename stripping from search_memories() source_file result construction while preserving the existing fallback for missing metadata."
  - path: tests/test_searcher.py
    change: "Add regression coverage for full-path search_memories() output, missing source_file fallback, and unchanged code_search() full-path behavior."
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_searcher.py -k search_memories_full_source_file_path -q is run against a store seeded with source_file=/project/src/auth.py"
    then: "the search_memories() hit reports source_file=/project/src/auth.py rather than auth.py"
  - id: AC-2
    when: "python -m pytest tests/test_searcher.py -k search_memories_missing_source_file_fallback -q is run against a store seeded without source_file metadata"
    then: "the search_memories() hit reports source_file=? and does not raise an exception"
  - id: AC-3
    when: "python -m pytest tests/test_searcher.py -k code_search_full_source_file_path_unchanged -q is run against a code-search store seeded with source_file=/project/src/auth.py"
    then: "the code_search() hit still reports source_file=/project/src/auth.py"
  - id: AC-4
    when: "python -m pytest tests/test_mcp_server.py -k tool_search_full_source_file_path -q is run with the MCP palace seeded with source_file=/project/src/auth.py"
    then: "tool_search returns the same full source_file path from search_memories()"
out_of_scope:
  - "Changing the human-readable CLI search() output, which currently prints only the basename for display."
  - "Changing storage metadata schema, mining behavior, or code_search filtering semantics."
---

## Design Notes

- The implementation should replace `Path(meta.get("source_file", "?")).name` in `search_memories()` with a direct metadata read such as `meta.get("source_file", "?")`.
- Preserve the missing-metadata fallback value of `"?"`; this is the edge case that avoids turning absent optional metadata into an exception or an empty path.
- Leave the printable `search()` function unchanged unless implementation discovery proves it shares the same programmatic contract; the task scope names `search_memories()` and API consistency with `code_search()`.
- `tool_search()` in `mempalace/mcp_server.py` delegates directly to `search_memories()`, so MCP behavior should change through the searcher fix rather than through separate result rewriting.
- Existing `code_search()` already reads `meta.get("source_file", "") or ""`; keep it as the baseline behavior and add regression coverage only if the test setup can do so without broad fixture churn.
