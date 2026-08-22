---
slug: FIND-IMPL-INHERITS
status: completed
authority: non_authoritative
goal: "Fix tool_find_implementations to return Python subclasses of ABCs by also matching incoming inherits edges when the interface is itself an ABC/Protocol"
risk: low
risk_note: "Single-function change in mcp_server.py; existing implements path unchanged; heuristic is guarded by KG self-check so false positives only possible if non-ABC classes happen to have an implements-ABC triple"
files:
  - path: mempalace/mcp_server.py
    change: "Add _PY_ABC_BASES constant; extend tool_find_implementations to also include incoming inherits edges when the interface has an outgoing implements-to-ABC/Protocol edge"
  - path: tests/test_mcp_server.py
    change: "Add test_find_implementations_includes_inherits_for_abc and test_find_implementations_concrete_class_still_empty to TestArchTools"
acceptance:
  - id: AC-1
    when: "KG has (DrawerStore, implements, ABC), (LanceStore, inherits, DrawerStore), (ChromaStore, inherits, DrawerStore)"
    then: "find_implementations('DrawerStore') returns LanceStore and ChromaStore"
  - id: AC-2
    when: "KG has (SomeConcreteClass, inherits, BaseClass) but SomeConcreteClass has no outgoing implements-ABC edge"
    then: "find_implementations('BaseClass') returns empty (no false positives for non-abstract bases)"
  - id: AC-3
    when: "KG has (MyService, implements, IService)"
    then: "find_implementations('IService') still returns MyService (existing implements path unbroken)"
  - id: AC-4
    when: "KG has (MyService, implements, IService) and (AnotherService, inherits, IService) and IService has no implements-ABC edge"
    then: "find_implementations('IService') returns only MyService, not AnotherService"
out_of_scope:
  - "Transitive ABC detection (e.g., class Foo(Bar) where Bar(ABC) — checking two hops)"
  - "Changes to miner.py or extract_type_relationships (predicate assignment is correct as-is)"
  - "Changes to _PY_ABC_BASES in miner.py (each module holds its own copy of this tiny constant)"
  - "Updating tool description string in TOOL_REGISTRY (doc change, can be follow-up)"
---

## Design Notes

- **Root cause**: `tool_find_implementations` (mcp_server.py:460) filters on `predicate == "implements"` only. Python subclasses of user-defined ABCs are stored as `inherits` triples (e.g. `(LanceStore, inherits, DrawerStore)`) because only the built-in bases `ABC`, `ABCMeta`, `Protocol` produce `implements` predicates in the miner.

- **Heuristic**: To distinguish abstract bases from concrete bases, check whether the query target itself has an outgoing `(interface, implements, X)` edge where `X in {"ABC", "ABCMeta", "Protocol"}`. If yes, the interface is abstract and incoming `inherits` edges are also implementations.

- **Implementation sketch** for `tool_find_implementations`:
  1. Query incoming facts (direction="incoming") — same as today.
  2. Collect `implements` matches into `implementations` (unchanged).
  3. Query outgoing facts for `interface` (direction="outgoing").
  4. If any outgoing fact has `predicate == "implements"` and `object in _PY_ABC_BASES` and `current` → set `is_abc = True`.
  5. If `is_abc`, also loop over incoming facts and collect `inherits` matches.
  6. Deduplicate by type name (edge case: a subclass that both implements and inherits the same interface).

- **Constant placement**: Define `_PY_ABC_BASES = frozenset({"ABC", "ABCMeta", "Protocol"})` at module level in `mcp_server.py`. Do not import from `miner.py` — the miner owns its mining-side copy; the MCP layer owns its query-side copy. They happen to be equal but serve different concerns.

- **Test approach**: Add two tests inside `TestArchTools`:
  - `test_find_implementations_includes_inherits_for_abc`: seed KG with `(DrawerStore, implements, ABC)`, `(LanceStore, inherits, DrawerStore)`, `(ChromaStore, inherits, DrawerStore)`; assert both LanceStore and ChromaStore appear in result.
  - `test_find_implementations_concrete_class_still_empty`: seed KG with `(Child, inherits, BaseClass)` only (no implements-ABC triple); assert `find_implementations("BaseClass")` returns empty.

- **No change to response schema**: output keys (`interface`, `implementations`, `count`) remain identical.
