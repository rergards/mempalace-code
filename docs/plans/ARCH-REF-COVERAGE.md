---
slug: ARCH-REF-COVERAGE
status: completed
authority: non_authoritative
goal: "Add find_references coverage for incoming depends_on and references_project categories"
risk: low
risk_note: "Test-only change covering existing category_map behavior in the MCP architecture tools."
files:
  - path: tests/test_mcp_server.py
    change: "Add two TestArchTools unit tests for depended_by and referenced_by find_references categories."
acceptance:
  - id: AC-1
    when: "a KG triple X depends_on MyApp exists and tool_find_references('MyApp') is called"
    then: "result['references']['depended_by'] contains an entry with type X"
  - id: AC-2
    when: "a KG triple X references_project MyApp exists and tool_find_references('MyApp') is called"
    then: "result['references']['referenced_by'] contains an entry with type X"
  - id: AC-3
    when: "tool_find_references('MyApp') is called with only unrelated or outgoing project dependency edges"
    then: "incoming-only categories not backed by matching current incoming facts are absent from result['references']"
out_of_scope:
  - "Changing tool_find_references implementation or category names"
  - "Adding broader architecture-tool integration coverage"
---

## Design Notes

- Add the tests inside `TestArchTools` near the existing `test_find_references_*` cases.
- Use the existing `kg` fixture for isolated, minimal triples so each new test proves one incoming predicate path directly.
- Patch `mempalace.mcp_server` with `_patch_mcp_server(monkeypatch, config, palace_path, kg)` before importing `tool_find_references`, matching the existing test pattern.
- Keep assertions on both category presence and returned `type` values; this catches regressions in the category map and in incoming subject selection.
- Do not mutate the shared `dotnet_kg` fixture for these cases; its existing outgoing `MyApp depends_on ...` and `MyApp references_project ...` edges exercise different category names.
