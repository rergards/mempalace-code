verdict: READY

gaps: []

notes:
  - task_contract present (version 1, mode standard) with requirements, surfaces, invariants, risks, verification, regression_plan.
  - contract_policy set to full_spdd with sync_gate=required and verification_path=automated, matching the behavior-changing API output scope.
  - All five acceptance criteria (AC-1..AC-5) are observable and have corresponding verification commands (VER-1..VER-5) and are all covered by REG-1.
  - Verification commands are runnable pytest invocations against specific test node IDs in tests/test_mcp_server.py; no manual/prose placeholders.
  - File list covers the actual change points: knowledge_graph.py (query_entity, query_relationship, timeline already select t.* — source_file column at index 8 is available), mcp/tools/kg.py (pass-through wrappers), mcp/tools/architecture.py (tool_find_implementations, tool_find_references, tool_show_project_graph build relationship entries from KG fact rows), and tests/test_mcp_server.py.
  - Out-of-scope list correctly excludes schema/migration/input changes and symbol_graph string-only summaries.
  - No backlog metadata (docs/BACKLOG.yaml or archives) is listed as provider-owned or touched; backlog edits are correctly outside the implementation scope.
  - Invariants protect storage schema, KG add input contract, temporal filtering semantics, and project graph solution-filter behavior.
  - Plan accounts for legacy NULL-source_file triples (AC-5, RISK-3, INV in design notes) so query and timeline tools will not regress on unsourced rows.
