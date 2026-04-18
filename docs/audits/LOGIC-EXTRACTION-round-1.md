slug: LOGIC-EXTRACTION
round: 1
date: 2026-04-18
commit_range: 08e018f..HEAD
findings:
  - id: F-1
    title: "BFS queue uses list.pop(0) — O(n) per dequeue"
    severity: low
    location: "mempalace/mcp_server.py:662"
    claim: >
      tool_extract_reusable initialised its BFS frontier as a plain list and dequeued via
      list.pop(0), which is O(n) in the list length. For large dependency graphs (hundreds of
      nodes) this degrades to O(n²) total traversal cost. collections.deque provides O(1)
      popleft() at no API cost.
    decision: fixed
    fix: >
      Added `from collections import deque` to imports. Changed `queue = [(entity, 0, None)]`
      to `queue = deque([(entity, 0, None)])` and `queue.pop(0)` to `queue.popleft()`.
      All 12 TestExtractReusable tests pass unchanged.

  - id: F-2
    title: "Glue promotion ignores references_project to platform projects"
    severity: medium
    location: "mempalace/mcp_server.py:736-741"
    claim: >
      Step 3 (glue promotion) only checks `depends_on` predicates when looking for platform
      dependencies. An entity that `implements` a core interface AND `references_project` a
      platform-classified project (e.g., a WPF project targeting net8.0-windows) will be
      incorrectly classified as core rather than glue. In .NET solutions, project references
      (`references_project`) are first-class coupling signals just like NuGet package references
      (`depends_on`).
    decision: backlogged
    backlog_slug: EXTRACT-REUSABLE-REFERENCES-PROJECT-GLUE

  - id: F-3
    title: "Root entity glue status visible in boundary_interfaces but absent from graph.glue"
    severity: info
    location: "mempalace/mcp_server.py:770-772"
    claim: >
      If the root (query subject) entity is classified as glue, it appears in
      boundary_interfaces.implemented_by but not in graph.glue (root is intentionally excluded
      from all graph lists). This asymmetry could confuse callers who assume boundary_interfaces
      implementors are a subset of graph.glue. Tests confirm this is intentional design.
    decision: dismissed

totals:
  fixed: 1
  backlogged: 1
  dismissed: 1

fixes_applied:
  - "Replace list.pop(0) with deque.popleft() in BFS traversal of tool_extract_reusable (O(n²) → O(n))"

new_backlog:
  - slug: EXTRACT-REUSABLE-REFERENCES-PROJECT-GLUE
    summary: >
      Extend glue promotion in mempalace_extract_reusable to treat references_project to a
      platform-classified project as a platform dependency signal, matching depends_on behaviour.
