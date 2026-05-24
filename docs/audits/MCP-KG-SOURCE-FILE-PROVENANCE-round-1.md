slug: MCP-KG-SOURCE-FILE-PROVENANCE
round: 1
date: 2026-05-24
commit_range: 9e5d11c..e04c5f3
findings:
  - id: F-1
    title: "tool_find_implementations source_file provenance has no dedicated test"
    severity: info
    location: "mempalace_code/mcp/tools/architecture.py:81-106"
    claim: >
      The new conditional source_file copy in tool_find_implementations (both the direct
      implements branch and the ABC inherits heuristic branch) is not covered by a focused
      provenance regression test. AC-3 in the plan explicitly names project graph and
      find_references only; find_implementations is not listed in VER-3.
    decision: dismissed
    fix: ""

totals:
  fixed: 0
  backlogged: 0
  dismissed: 1

fixes_applied: []

new_backlog: []

verification_evidence:
  - id: VER-1
    status: passed
    acceptance_ids: [AC-1]
    command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_query_returns_source_file_provenance -q"
    slug: MCP-KG-SOURCE-FILE-PROVENANCE
    phase: harden
  - id: VER-2
    status: passed
    acceptance_ids: [AC-2]
    command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_timeline_returns_source_file_provenance -q"
    slug: MCP-KG-SOURCE-FILE-PROVENANCE
    phase: harden
  - id: VER-3
    status: passed
    acceptance_ids: [AC-3]
    command: "python -m pytest tests/test_mcp_server.py::TestArchTools::test_arch_relationship_outputs_include_source_file_provenance -q"
    slug: MCP-KG-SOURCE-FILE-PROVENANCE
    phase: harden
  - id: VER-4
    status: passed
    acceptance_ids: [AC-4]
    command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_tools_reject_invalid_temporal_arguments_before_write -q"
    slug: MCP-KG-SOURCE-FILE-PROVENANCE
    phase: harden
  - id: VER-5
    status: passed
    acceptance_ids: [AC-5]
    command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_query_and_timeline_keep_legacy_unsourced_rows -q"
    slug: MCP-KG-SOURCE-FILE-PROVENANCE
    phase: harden
  - id: REG-1
    status: passed
    acceptance_ids: [AC-1, AC-2, AC-3, AC-4, AC-5]
    command: "python -m pytest tests/test_mcp_server.py::TestKGTools tests/test_mcp_server.py::TestArchTools -q"
    slug: MCP-KG-SOURCE-FILE-PROVENANCE
    phase: harden
