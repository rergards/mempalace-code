---
slug: CODE-SYMBOL-META-GO-TYPES
goal: "Add catch-all Go type pattern to _GO_EXTRACT so scalar, func-type, and alias declarations return correct symbol names"
risk: low
risk_note: "Additive change — new pattern appended at end of ordered list, existing struct/interface patterns unchanged and still win first"
files:
  - path: mempalace/miner.py
    change: "Append catch-all (^type\\s+(\\w+)\\b, 'type') to _GO_EXTRACT; broaden GO_BOUNDARY to match all 'type X' declarations, not just struct/interface"
  - path: tests/test_symbol_extract.py
    change: "Add test_go_type_scalar, test_go_type_func, test_go_type_alias under the Go section"
acceptance:
  - id: AC-1
    when: "extract_symbol('type MyInt int\\n', 'go') called"
    then: "returns ('MyInt', 'type')"
  - id: AC-2
    when: "extract_symbol('type Handler func(http.ResponseWriter, *http.Request)\\n', 'go') called"
    then: "returns ('Handler', 'type')"
  - id: AC-3
    when: "extract_symbol('type Alias = Original\\n', 'go') called"
    then: "returns ('Alias', 'type')"
  - id: AC-4
    when: "existing Go tests (test_go_type_struct, test_go_type_interface, test_go_method_value_receiver, etc.) run"
    then: "all pass unchanged — struct/interface/func patterns still win because they precede the catch-all"
out_of_scope:
  - "Updating GO_BOUNDARY to split on all top-level type declarations for chunking purposes (noted below as a recommended companion change but not required for AC)"
  - "Tree-sitter-based Go extraction (separate CODE-TREESITTER-* track)"
  - "Handling multi-type blocks: 'type ( ... )' grouped declarations"
---

## Design Notes

- `extract_symbol` iterates `_GO_EXTRACT` and returns on the **first match** (`miner.py:603–606`). Order is critical.
- Current `_GO_EXTRACT` (lines 558–563) has four entries: method, function, struct, interface.
- Append a fifth entry at position [4]:
  ```python
  (re.compile(r"^type\s+(\w+)\b", re.MULTILINE), "type"),
  ```
  - Matches `type MyInt int`, `type Handler func(...)`, `type Alias = Original`.
  - Does **not** conflict with struct/interface — those patterns come first and are more specific.
  - The `\b` word boundary prevents false matches if some pathological line starts `type` but the name is empty (defensive).

- **GO_BOUNDARY companion change** (recommended, not AC-blocking): The current boundary regex (`miner.py:452`) only splits chunks at `type X struct` and `type X interface`. Without updating it, scalar/func/alias type declarations are never emitted as standalone chunks by `chunk_file`, so `extract_symbol` would never see them in practice. Change:
  ```
  |type\s+\w+\s+(?:struct|interface)
  ```
  to:
  ```
  |type\s+\w+
  ```
  This is safe — `type\s+\w+` is a prefix match that broadens the split set without removing existing splits.

- **Test placement**: Add the three new tests immediately after `test_go_type_interface` in `tests/test_symbol_extract.py`, inside the Go section.

- **No import changes** needed in either file.
