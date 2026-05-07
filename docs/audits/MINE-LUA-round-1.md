slug: MINE-LUA
round: 1
date: 2026-05-07
commit_range: 44d300d..HEAD
findings:
  - id: F-1
    title: "LUA_BOUNDARY matches any `local x = {}` as a module declaration, splitting function bodies"
    severity: medium
    location: "mempalace_code/miner.py:801"
    claim: >
      The module-table boundary pattern `(?:local\s+)?\w+\s*=\s*\{\}` is too broad: it
      matches any identifier assigned to `{}`, not just top-level module tables. In large
      Lua functions, common locals like `local opts = {}`, `local result = {}`, or
      `local t = {}` trigger a false structural boundary mid-function. The resulting
      second chunk starts with the local variable line and is classified by `extract_symbol`
      as `symbol_name="opts"`, `symbol_type="module"` — wrong metadata that pollutes the
      semantic index and causes incorrect code_search results. Confirmed with a >6 KB
      Lua function: chunk_code produced 2 chunks where the second started with
      `local opts = {}` and was classified as a module named "opts".
    decision: fixed
    fix: >
      Changed the module-table alternative in LUA_BOUNDARY from
      `(?:local\s+)?\w+\s*=\s*\{\}` to `(?:local\s+)?[A-Z]\w*\s*=\s*\{\}`, requiring
      the table name to start with an uppercase letter (Lua convention for module tables:
      M, MyModule, Renderer). Applied the same constraint to the _LUA_EXTRACT module
      pattern. Added regression test
      `test_chunk_code_lua_lowercase_table_not_a_module_boundary` in test_chunking.py that
      confirms `local opts = {}` inside a large function body does not create a false chunk
      boundary. Updated LUA_BOUNDARY comment to document the uppercase constraint.

  - id: F-2
    title: "test_chunk_code_lua_anonymous_function_not_a_boundary has a trivially-true assertion"
    severity: low
    location: "tests/test_chunking.py:2801"
    claim: >
      The assertion `assert len(chunks) >= 1` is trivially true for any non-empty input and
      provides no signal about whether the anonymous function pattern was correctly excluded
      from structural boundary detection. If the implementation regressed and treated
      `local handler = function(event)` as a boundary (producing 2 chunks), this test would
      still pass.
    decision: fixed
    fix: >
      Replaced `assert len(chunks) >= 1` with `assert len(chunks) == 1` with an
      explanatory message. Since no LUA_BOUNDARY alternative matches
      `local handler = function(event)`, chunk_code falls back to adaptive chunking and
      must return exactly 1 chunk. If a regression introduces a false boundary here, the
      test now catches it.

  - id: F-3
    title: "No test covering multi-level dot notation (function A.B.name) graceful degradation"
    severity: info
    location: "mempalace_code/miner.py:1570"
    claim: >
      The extract pattern `r"^function\s+(\w+\.\w+)\s*\("` only captures one level of dot
      notation (e.g. `M.render`). For deeper nesting like `function A.B.name(`, the boundary
      matches (via `\w[\w.]*`) but the extract pattern does not match, so no symbol metadata
      is emitted. This is graceful degradation, not a bug, since deeply nested module paths
      are uncommon in Lua. Observation only — no action needed.
    decision: dismissed

totals:
  fixed: 2
  backlogged: 0
  dismissed: 1

fixes_applied:
  - "Restricted LUA_BOUNDARY and _LUA_EXTRACT module-table detection to uppercase-starting names to eliminate false chunk boundaries on common lowercase locals like `local opts = {}`"
  - "Strengthened test_chunk_code_lua_anonymous_function_not_a_boundary assertion from trivially-true `>= 1` to `== 1`"
  - "Added regression test test_chunk_code_lua_lowercase_table_not_a_module_boundary"

new_backlog: []
