slug: CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER
phase: polish
date: 2026-05-24
commit_range: 6e594c1..HEAD
reverted: false
findings:
  - id: P-1
    title: "Module docstring in test_layers.py references task slug and plan IDs"
    category: verbal
    location: "tests/test_layers.py:1-6"
    evidence: |
      """
      test_layers.py — No-embedder regression tests for Layer1/Layer2/MemoryStack read paths.

      Covers VER-1 (wake_up, recall, status, CLI smoke) and VER-4 (missing and empty palace
      boundaries) from the CLI-LAYERS-GRAPH-READONLY-NO-EMBEDDER plan.
      """
    decision: fixed
    fix: "Replaced multi-line docstring with single-line description; removed task-slug and VER-N plan ID references."

  - id: P-2
    title: "Class docstrings carry VER-N/AC-N task-plan ID prefixes across three test files"
    category: verbal
    location: "tests/test_layers.py, tests/test_palace_graph.py, tests/test_mcp_server.py"
    evidence: |
      Nine class docstrings prefixed with patterns like:
        """VER-1/AC-1: wake_up and recall work on a populated palace without embedder startup."""
        """VER-4/AC-3: graph helpers on a missing palace return empty results, no dir created."""
        """VER-3/AC-2: MCP graph tool calls use runtime read-only store without embedder startup."""
      These task-specific plan IDs will be orphaned once the task is archived.
      Existing test classes in the repo (test_storage.py, test_knowledge_graph.py) do not use this pattern.
    decision: fixed
    fix: "Stripped 'VER-N/AC-N: ' prefix from all nine affected class docstrings; descriptions kept intact."

totals:
  fixed: 2
  dismissed: 0
fixes_applied:
  - "tests/test_layers.py: collapsed module docstring to one line, removing task-slug and VER-N plan ID references"
  - "tests/test_layers.py: stripped VER-1/AC-1 and VER-4/AC-3/AC-4 prefixes from five class docstrings"
  - "tests/test_palace_graph.py: stripped VER-2/AC-2 and VER-4/AC-3/AC-4 prefixes from three class docstrings"
  - "tests/test_mcp_server.py: stripped VER-3/AC-2 prefix from one class docstring"
