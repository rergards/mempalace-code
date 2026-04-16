---
slug: STORE-WHERE-ARROW-IN
goal: "Add $in support to _where_to_arrow_mask so iter_all() correctly filters rows by list membership"
risk: low
risk_note: "Additive elif branch in a pure static method; no storage or protocol changes. pc.is_in is a stable pyarrow.compute function."
files:
  - path: mempalace/storage.py
    change: "Add elif op == '$in' branch inside _where_to_arrow_mask's operator-dict loop; add import pyarrow as pa alongside existing import pyarrow.compute as pc"
  - path: tests/test_storage_lance.py
    change: "Add 3 tests to TestIterAll: multi-element $in on strings, empty $in (zero results), single-element $in"
acceptance:
  - id: AC-1
    when: "iter_all(where={'wing': {'$in': ['alpha', 'beta']}}) on a store with rows for wings 'alpha', 'beta', 'gamma'"
    then: "Returns only the 2 rows whose wing is 'alpha' or 'beta'; 'gamma' row is excluded"
  - id: AC-2
    when: "iter_all(where={'wing': {'$in': []}}) on any non-empty store"
    then: "Returns zero rows (empty list matches nothing)"
  - id: AC-3
    when: "iter_all(where={'wing': {'$in': ['alpha']}}) on a store with rows for 'alpha' and 'beta'"
    then: "Returns only the 'alpha' row"
  - id: AC-4
    when: "iter_all(where={'wing': 'alpha'}) (existing string equality path)"
    then: "Still returns only alpha rows — no regression"
  - id: AC-5
    when: "ruff check mempalace/ tests/ and ruff format --check mempalace/ tests/"
    then: "Both pass with no violations"
out_of_scope:
  - "$nin operator"
  - "$in against numeric columns (str is the only real use case from callers; pc.is_in handles numerics identically but no test required)"
  - "Changes to _where_to_sql (already has $in support)"
  - "ChromaStore / legacy Chroma backend"
---

## Design Notes

- **Where to add the branch**: inside `_where_to_arrow_mask`'s `elif isinstance(value, dict)` loop (storage.py ~line 603), after the existing `if fn is not None: parts.append(fn(col, operand))` block. The new branch is `elif op == "$in":`.

- **PyArrow function**: `pc.is_in(col, value_set=pa.array(operand, type=col.type))`.
  - `pc.is_in` returns a boolean ChunkedArray of the same length as `col`, True where the element appears in `value_set`.
  - Empty `operand` list → `pa.array([], type=col.type)` → `pc.is_in` returns all-False. This correctly matches `_where_to_sql`'s `1 = 0` semantics.
  - `col.type` (ChunkedArray attribute) gives the Arrow data type; using it for `pa.array(operand)` ensures type compatibility (e.g. `pa.large_string()` for string columns, `pa.int32()` for chunk_index).

- **Import**: add `import pyarrow as pa` alongside the existing `import pyarrow.compute as pc` at the top of `_where_to_arrow_mask`. Both are local imports (inside the function body) — keep that pattern.

- **No single-element optimization needed**: `pc.is_in` with a one-element value_set is functionally correct and simpler than a special-case `pc.equal`. Unlike `_where_to_sql` which needs the optimization to avoid `IN ('a')` SQL, the Arrow path has no such constraint.

- **Test placement**: `tests/test_storage_lance.py`, class `TestIterAll` — consistent with all other `iter_all()` operator tests added in STORE-WHERE-ARROW-OPS.

- **Semantic divergence closed**: before this fix, `_where_to_sql` supported `$in` but `_where_to_arrow_mask` silently skipped it. After this fix, both code paths handle `$in` identically.
