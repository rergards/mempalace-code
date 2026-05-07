slug: MINE-LUA
phase: polish
date: 2026-05-07
commit_range: 8881316..HEAD
reverted: false
findings:
  - id: P-1
    title: "LUA_BOUNDARY comment enumerates the regex alternatives verbatim"
    category: verbal
    location: "mempalace_code/miner.py:787"
    evidence: >
      6-line "Matches:" block (local function name(, function name(, function M.name(,
      function obj:method(, local M = {}, M = {}) mirrors the 3 regex alternations below
      it word-for-word. The non-obvious constraints (exclusions, uppercase rule) were in
      separate lines already.
    decision: fixed
    fix: >
      Removed the "Matches:" enumeration (lines 788-794). Kept the two WHY lines
      explaining the intentional exclusion of anonymous assignments and the uppercase
      constraint for module table detection.

  - id: P-2
    title: "_LUA_EXTRACT comment enumerates all 5 patterns by name and symbol type"
    category: verbal
    location: "mempalace_code/miner.py:1562"
    evidence: >
      7-line numbered block ("Order (most-specific first): 1. local function name( —
      local_function … 5. local M = {} / M = {} — module/table declaration") exactly
      restates the 5 compact one-liner tuples that follow. The "most-specific first"
      ordering rationale was the only useful information.
    decision: fixed
    fix: >
      Collapsed the 7-line block to a single line:
      "# Lua extraction patterns (.lua files) — most-specific first (colon/dot before plain function)."

  - id: P-3
    title: "chunk_code Lua comment mentions --[[ redundantly"
    category: verbal
    location: "mempalace_code/miner.py:2141"
    evidence: >
      Comment says "Lua uses -- for line comments and --[[ for long comments." The --[[
      mention is redundant since the -- prefix already matches lines starting with --[[.
      However the two-sentence structure (syntax name → why we're adding it) is the
      established local style for every language-specific comment_prefixes branch in this
      block (Swift, PHP, Scala, Dart all follow the same pattern).
    decision: dismissed
    reason: Follows established local comment style; the imprecision is minor and the WHY clause is present.

  - id: P-4
    title: "_LUA_FILLER is a module-level constant used only in Lua chunk tests"
    category: structural
    location: "tests/test_chunking.py:2698"
    evidence: "_LUA_FILLER is referenced in 6 test functions — not single-use."
    decision: dismissed
    reason: Used in 6 tests; the constant prevents duplication of the MIN_CHUNK padding rationale.

totals:
  fixed: 2
  dismissed: 2
fixes_applied:
  - "Removed LUA_BOUNDARY 'Matches:' enumeration (6 lines); kept WHY comments for exclusions and uppercase constraint"
  - "Collapsed _LUA_EXTRACT 7-line numbered block to a single-line ordering note"
