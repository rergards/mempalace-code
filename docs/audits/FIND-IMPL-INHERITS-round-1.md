slug: FIND-IMPL-INHERITS
round: 1
date: 2026-04-18
commit_range: 83a1bec..HEAD
findings:
  - id: F-1
    title: "Protocol base class untested — only ABC covered"
    severity: low
    location: "tests/test_mcp_server.py:959"
    claim: "_PY_ABC_BASES includes ABC, ABCMeta, and Protocol, but the only test for the heuristic uses ABC. Protocol is equally common in Python type-hint–driven code and its code path was not exercised."
    decision: fixed
    fix: "Added test_find_implementations_protocol_base: sets Runnable implements Protocol, TaskRunner inherits Runnable, asserts TaskRunner appears in find_implementations('Runnable')."

  - id: F-2
    title: "Deduplication untested — class with both implements and inherits edges"
    severity: low
    location: "mempalace/mcp_server.py:464"
    claim: "The seen set guards against double-counting a class that carries both an implements edge and an inherits edge to the same ABC. That invariant had no regression test, leaving it unverifiable under future refactors."
    decision: fixed
    fix: "Added test_find_implementations_no_duplicates_when_both_edges: ConcreteA implements MyABC and inherits MyABC; asserts count==1 and the type appears exactly once."

  - id: F-3
    title: "Expired inherits edges not specifically tested in ABC path"
    severity: info
    location: "mempalace/mcp_server.py:486"
    claim: "The f['current'] guard filters triples with a valid_to date, but there is no test exercising an expired inherits edge in the ABC heuristic code path specifically."
    decision: dismissed
    fix: ~

totals:
  fixed: 2
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "Added test_find_implementations_protocol_base to cover Protocol branch of _PY_ABC_BASES"
  - "Added test_find_implementations_no_duplicates_when_both_edges to cover seen-set deduplication"

new_backlog: []
