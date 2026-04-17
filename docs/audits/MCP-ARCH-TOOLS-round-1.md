slug: MCP-ARCH-TOOLS
round: 1
date: "2026-04-18"
commit_range: 827e67f..7889c55
findings:
  - id: F-1
    title: "tool_find_implementations includes source_closet: null for all entries without a closet reference"
    severity: low
    location: "mempalace/mcp_server.py:412-416"
    claim: >
      The list comprehension unconditionally set source_closet on every result entry, even when the
      triple has no source_closet (the common case for manually-added triples). Callers receive
      {"type": "MyService", "source_closet": null} instead of {"type": "MyService"}, adding noise
      to every MCP response.
    decision: fixed
    fix: >
      Rewrote the list comprehension as a for-loop that only adds source_closet to the entry dict
      when the value is truthy. Zero behavior change for entries that have a closet reference.

  - id: F-2
    title: "No test for show_project_graph with a nonexistent solution"
    severity: low
    location: "tests/test_mcp_server.py:TestArchTools"
    claim: >
      The solution= filter path builds contained_projects from contains_project triples. When
      solution does not exist in the KG, contained_projects is empty and the graph collapses to
      {}, which is the correct behavior. This path had no test, so a regression here would be
      silent.
    decision: fixed
    fix: >
      Added test_show_project_graph_unknown_solution: verifies that solution="NoSuchSolution"
      returns {"solution": "NoSuchSolution", "graph": {}} without error.

  - id: F-3
    title: "tool_show_project_graph accesses private _kg._entity_id method"
    severity: info
    location: "mempalace/mcp_server.py:475,480,486"
    claim: >
      The solution filter calls _kg._entity_id() directly, accessing a private method. Within the
      same package this is acceptable, but it couples the tool to the internal KG API surface.
    decision: dismissed
    fix: ~

  - id: F-4
    title: "type_dependency_chain uses list.pop(0) — O(n) per dequeue"
    severity: info
    location: "mempalace/knowledge_graph.py:404,428"
    claim: >
      BFS uses list.pop(0) which shifts all elements on each call (O(n)). collections.deque with
      popleft() would be O(1). For type hierarchies (typically <50 nodes) this difference is
      immeasurable, making the fix unnecessary churn.
    decision: dismissed
    fix: ~

  - id: F-5
    title: "find_references depended_by and referenced_by categories have no test coverage"
    severity: low
    location: "tests/test_mcp_server.py:TestArchTools"
    claim: >
      The category_map in tool_find_references maps (incoming, depends_on)→depended_by and
      (incoming, references_project)→referenced_by, but no test exercises either path. A bug
      that broke these mappings would not be caught by the existing suite.
    decision: backlogged
    backlog_slug: ARCH-REF-COVERAGE

totals:
  fixed: 2
  backlogged: 1
  dismissed: 2

fixes_applied:
  - "tool_find_implementations: omit source_closet key when value is None/falsy"
  - "tests: add test_show_project_graph_unknown_solution for the empty-graph edge case"

new_backlog:
  - slug: ARCH-REF-COVERAGE
    summary: "Add find_references test coverage for depended_by and referenced_by categories"
