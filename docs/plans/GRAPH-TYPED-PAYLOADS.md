---
slug: GRAPH-TYPED-PAYLOADS
status: completed
authority: non_authoritative
goal: "Type the palace graph payload internals without changing public graph helper outputs."
risk: low
risk_note: "The change is confined to one helper module and its regression tests; return shapes stay JSON-compatible and no storage or API boundaries move."
contract_policy:
  flow: lite_compact
  reason: "All five axes are low: single-module typing cleanup, no auth/data/migration/provider/pipeline boundary, and no behavioral expansion beyond preserving existing helper outputs."
  sync_gate: may_skip_when_existing_checks_cover
  verification_path: automated
files:
  - path: mempalace_code/palace_graph.py
    change: "Replace the mixed defaultdict payload with a small typed structure for per-room graph state and use it to build nodes, edges, traversal, and stats with explicit typed access."
  - path: tests/test_palace_graph.py
    change: "Add regression coverage for the typed payload behavior while asserting the existing public node, edge, traverse, tunnel, and stats shapes remain unchanged."
acceptance:
  - id: AC-1
    when: "the graph helpers are exercised on a store with valid rows spanning multiple wings"
    then: "build_graph() still returns JSON-friendly node and edge payloads with the same keys and values, including sorted list fields and tunnel edges."
  - id: AC-2
    when: "the graph helpers are exercised on rows with repeated rooms and mixed wings"
    then: "traverse(), find_tunnels(), and graph_stats() still return the same observable public shapes and counts for hop paths, tunnel summaries, and wing totals."
  - id: AC-3
    when: "the graph helper processes None metadata rows and empty stores"
    then: "the helpers still skip invalid rows and return empty graph outputs without raising."
  - id: AC-4
    when: "pyright is run against the repo after the change"
    then: "the graph payload diagnostics related to mixed defaultdict shapes are gone or reduced by the typed structure, with no new type errors introduced in palace_graph.py."
out_of_scope:
  - "Changing graph traversal semantics, ranking, or result limits."
  - "Changing storage backends, metadata schema, or public MCP tool schemas."
  - "Editing backlog/archive bookkeeping files."

## Design Notes

- Keep the public return shapes as plain `dict`/`list` payloads so callers and tests do not need to change.
- Use one typed internal room-state object for the mutable accumulation phase, then convert to JSON-safe payloads at the boundary.
- Prefer explicit typed helpers over casts so Pyright can infer the room aggregation path without suppressions.
- Keep the fix narrow to `palace_graph.py` and only extend tests where they verify the preserved output contract.
