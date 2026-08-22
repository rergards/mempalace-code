---
slug: UPSTREAM-KG-TEMPORAL-VALIDATION
status: completed
authority: non_authoritative
goal: "Validate KG temporal inputs and preserve full MCP validity windows."
risk: medium
risk_note: "Small surface area, but it changes write-time validation and query filtering for temporal KG facts that may already contain mixed date/datetime strings."
files:
  - path: mempalace_code/knowledge_graph.py
    change: "Add central temporal parsing/window validation for KG API inputs, reject invalid or inverted windows before mutation, and use parsed values for as_of filtering."
  - path: mempalace_code/mcp/tools/kg.py
    change: "Extend mempalace_kg_add handler and input schema to accept and forward valid_to and source_file while relying on KG validation for all temporal arguments."
  - path: tests/test_knowledge_graph.py
    change: "Add focused temporal validation tests for ISO dates, UTC datetimes, natural-language rejection, inverted-window rejection, inclusive boundary windows, and query/invalidate guards."
  - path: tests/test_mcp_server.py
    change: "Add MCP KG handler tests proving full-window/source metadata persistence and validation failures before rows are written."
acceptance:
  - id: AC-1
    when: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_add_triple_accepts_iso_dates_and_utc_datetimes -q is run"
    then: "KG add/query accepts YYYY-MM-DD dates and explicit UTC datetimes and returns the expected valid facts."
  - id: AC-2
    when: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_add_triple_rejects_natural_language_temporal_inputs_before_write -q is run"
    then: "natural-language temporal values raise ValueError and the KG triple count remains unchanged."
  - id: AC-3
    when: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_inverted_windows_are_rejected_before_mutation -q is run"
    then: "add_triple and invalidate reject valid_to/ended values before valid_from and leave existing rows unmodified."
  - id: AC-4
    when: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_equal_window_endpoints_remain_valid_and_inclusive -q is run"
    then: "a fact whose valid_to equals valid_from is stored and remains visible for as_of at that exact boundary."
  - id: AC-5
    when: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_add_stores_full_window_and_source_metadata -q is run"
    then: "mempalace_kg_add stores valid_from, valid_to, source_closet, and source_file on the created triple."
  - id: AC-6
    when: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_tools_reject_invalid_temporal_arguments_before_write -q is run"
    then: "MCP KG add/query/invalidate handlers reject invalid temporal arguments and do not create or corrupt triples."
out_of_scope:
  - "Changing the KG SQLite schema or migrating existing rows."
  - "Changing export/import JSONL format, backup format, or CLI flags."
  - "Changing non-KG drawer storage, search, mining, diary, or graph tools."
  - "Adding fuzzy or natural-language date parsing."
contract_policy:
  flow: full_spdd
  reason: "Standard behavior-changing data-integrity task for temporal KG writes and MCP mutation inputs."
  sync_gate: required
  verification_path: automated
task_contract:
  version: 1
  mode: standard
  requirements:
    - id: REQ-1
      statement: "KG Python API inputs for as_of, valid_from, valid_to, and ended must reject invalid temporal strings instead of storing or comparing them."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-2, AC-6]
    - id: REQ-2
      statement: "KG writes and invalidations must reject inverted validity windows before any row is inserted or updated."
      source: "backlog acceptance"
      acceptance_ids: [AC-3, AC-4]
    - id: REQ-3
      statement: "mempalace_kg_add must preserve the full validity window and source provenance available on the KG store."
      source: "backlog acceptance"
      acceptance_ids: [AC-5]
    - id: REQ-4
      statement: "Existing valid temporal query and timeline behavior must remain stable for valid date rows."
      source: "backlog acceptance"
      acceptance_ids: [AC-1, AC-4]
  surfaces:
    - name: "Temporal KG store API"
      kind: "store"
      paths: ["mempalace_code/knowledge_graph.py"]
      expected_behavior: "All KG temporal write/query parameters are parsed through one helper, invalid strings raise ValueError, and valid_to/ended cannot precede the stored or supplied valid_from."
    - name: "MCP KG mutation tool"
      kind: "api"
      paths: ["mempalace_code/mcp/tools/kg.py"]
      expected_behavior: "mempalace_kg_add declares valid_to and source_file in its schema, forwards them to KnowledgeGraph.add_triple(), and surfaces KG validation consistently with existing handler behavior."
    - name: "KG temporal regression tests"
      kind: "internal"
      paths: ["tests/test_knowledge_graph.py"]
      expected_behavior: "Focused tests prove accepted ISO dates/datetimes, rejected invalid inputs, rejected inverted windows, inclusive boundaries, and unchanged valid query behavior."
    - name: "MCP KG regression tests"
      kind: "internal"
      paths: ["tests/test_mcp_server.py"]
      expected_behavior: "Focused handler tests prove MCP full-window persistence and pre-write temporal validation."
  invariants:
    - id: INV-1
      statement: "KnowledgeGraph public method names, positional argument order, and return shapes remain compatible."
      applies_to: ["mempalace_code/knowledge_graph.py"]
    - id: INV-2
      statement: "Existing NULL temporal values still mean unbounded validity."
      applies_to: ["mempalace_code/knowledge_graph.py"]
    - id: INV-3
      statement: "as_of filtering remains inclusive of valid_from and valid_to boundaries."
      applies_to: ["mempalace_code/knowledge_graph.py"]
    - id: INV-4
      statement: "mempalace_kg_add still requires only subject, predicate, and object; new temporal/provenance fields are optional."
      applies_to: ["mempalace_code/mcp/tools/kg.py"]
    - id: INV-5
      statement: "Tests continue to use isolated temp KG fixtures and must not touch the user's real ~/.mempalace data."
      applies_to: ["tests/test_knowledge_graph.py", "tests/test_mcp_server.py"]
  risks:
    - id: RISK-1
      risk: "Continuing to rely on raw string comparisons could still mishandle valid UTC datetimes or mixed date/datetime rows."
      mitigation: "Parse temporal strings once and compare parsed date/datetime values in validation and as_of filtering; keep SQL filtering only as an optimization if it cannot change results."
    - id: RISK-2
      risk: "Rejecting invalid ended values after an UPDATE would corrupt active facts."
      mitigation: "Validate ended first, load matching active rows when needed, check each existing valid_from before UPDATE, then mutate."
    - id: RISK-3
      risk: "Extending the MCP schema without forwarding arguments would expose dead parameters."
      mitigation: "Add a direct handler test that inspects the stored triple via iter_all_triples() or SQLite metadata."
    - id: RISK-4
      risk: "Strict datetime parsing could accidentally reject the intended upstream-compatible UTC format."
      mitigation: "Cover both YYYY-MM-DD and explicit UTC datetime input in focused KG and MCP tests."
  verification:
    - id: VER-1
      command: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_add_triple_accepts_iso_dates_and_utc_datetimes -q"
      proves: "KG accepts valid dates and UTC datetimes and returns the expected as_of facts"
      acceptance_ids: [AC-1]
    - id: VER-2
      command: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_add_triple_rejects_natural_language_temporal_inputs_before_write -q"
      proves: "invalid natural-language temporal values fail before insertion"
      acceptance_ids: [AC-2]
    - id: VER-3
      command: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_inverted_windows_are_rejected_before_mutation -q"
      proves: "both insert-time and invalidate-time inverted windows are rejected before mutation"
      acceptance_ids: [AC-3]
    - id: VER-4
      command: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation::test_equal_window_endpoints_remain_valid_and_inclusive -q"
      proves: "validity endpoints remain inclusive and equal endpoints are not treated as inverted"
      acceptance_ids: [AC-4]
    - id: VER-5
      command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_add_stores_full_window_and_source_metadata -q"
      proves: "MCP add forwards and stores valid_to plus source provenance fields"
      acceptance_ids: [AC-5]
    - id: VER-6
      command: "python -m pytest tests/test_mcp_server.py::TestKGTools::test_kg_tools_reject_invalid_temporal_arguments_before_write -q"
      proves: "MCP KG handlers enforce temporal validation before writing"
      acceptance_ids: [AC-6]
  regression_plan:
    applies: true
    no_behavior_change_exception: ""
    checks:
      - id: REG-1
        command: "python -m pytest tests/test_knowledge_graph.py::TestTemporalValidation tests/test_knowledge_graph.py::TestQueries tests/test_knowledge_graph.py::TestInvalidation tests/test_knowledge_graph.py::TestTimeline -q"
        proves: "new temporal validation and existing KG query/invalidation/timeline behavior remain coherent"
        acceptance_ids: [AC-1, AC-2, AC-3, AC-4]
      - id: REG-2
        command: "python -m pytest tests/test_mcp_server.py::TestKGTools tests/test_mcp_registry.py -q"
        proves: "MCP KG handler behavior and tool registration/schema exposure stay compatible"
        acceptance_ids: [AC-5, AC-6]
      - id: REG-3
        command: "python -m pytest tests/test_export.py::TestExportWithKG -q"
        proves: "valid KG triples with validity windows still round-trip through the existing export/import path"
        acceptance_ids: [AC-1, AC-4]
---

## Design Notes

- Add a private temporal helper in `mempalace_code/knowledge_graph.py`; keep it local unless another module already imports a suitable parser during implementation.
- Accept only blank/`None`, `YYYY-MM-DD`, and explicit UTC ISO datetimes such as `2026-01-01T12:30:00Z` or the equivalent `+00:00` form. Reject natural-language dates and naive datetimes.
- Keep stored values as the caller-supplied valid ISO text where possible so export/import and existing rows remain readable; use parsed values for comparisons instead of relying on lexicographic ordering.
- Validate `valid_from` and `valid_to` before opening or mutating the write transaction in `add_triple()`.
- For `invalidate()` and related `ended` helpers, validate the supplied or default `ended` value before UPDATE. For subject/predicate/object invalidation, compare `ended` against matching active rows' `valid_from` values and raise before updating if any would become inverted.
- For `query_entity()` and `query_relationship()`, validate `as_of` up front and filter rows with parsed comparisons so date/datetime rows are handled consistently. Preserve inclusive `valid_from <= as_of <= valid_to` semantics.
- Extend `tool_kg_add()` with optional `valid_to` and `source_file` parameters and add both fields to the MCP input schema. Leave `subject`, `predicate`, and `object` as the only required fields.
- Let existing MCP dispatch error handling keep wrapping handler exceptions; focused handler-level tests can assert the validation raises and no row is written.
