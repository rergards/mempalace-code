---
slug: MINE-LUA
goal: "Add first-class Lua mining, chunking, symbol metadata, and code_search support"
risk: medium
risk_note: "Touches shared miner/catalog/search contracts and adds regex boundaries where false positives are possible."
files:
  - path: mempalace_code/language_catalog.py
    change: "Add .lua to extension detection, readable extensions, detected languages, and searchable languages."
  - path: mempalace_code/miner.py
    change: "Add regex Lua structural boundaries, Lua symbol extraction, .lua chunk routing, and comment/annotation handling for Lua comments."
  - path: mempalace_code/searcher.py
    change: "Accept Lua-specific symbol metadata by adding local_function to valid code_search symbol types."
  - path: mempalace_code/mcp_server.py
    change: "Expose local_function in the mempalace_code_search symbol_type schema hint; rely on catalog-generated language hints for lua."
  - path: tests/test_language_catalog.py
    change: "Assert lua is preserved by the shared catalog and stays readable/searchable."
  - path: tests/test_lang_detect.py
    change: "Assert detect_language() returns lua for .lua files."
  - path: tests/test_chunking.py
    change: "Cover Lua regex chunking for global functions, local functions, table/member methods, module/table declarations, and adaptive fallback."
  - path: tests/test_miner.py
    change: "Add an end-to-end Lua mine roundtrip that verifies stored language and symbol metadata."
  - path: tests/test_searcher.py
    change: "Cover code_search(language='lua') filtering, supported-language hints, and local_function symbol-type validation."
  - path: tests/test_mcp_server.py
    change: "Verify MCP language and symbol_type descriptions expose lua/local_function through the public tool schema."
  - path: README.md
    change: "Update user-facing language-support notes if any Lua-unsupported caveat or language example needs alignment."
  - path: docs/AGENT_INSTALL.md
    change: "Update agent-facing setup/search notes if any Lua-unsupported caveat is present."
  - path: docs/HOW_SEARCH_WORKS.md
    change: "Update search documentation if language examples or caveats need Lua alignment."
acceptance:
  - id: AC-1
    when: "A Python smoke calls detect_language(Path('widget.lua'), '-- lua') and inspects catalog helpers."
    then: "detect_language returns 'lua', '.lua' appears in readable_extensions(), and 'lua' appears in searchable_languages()."
  - id: AC-2
    when: "A temp project containing a .lua file is mined with default scan settings."
    then: "At least one drawer is stored for the file with metadata language='lua'."
  - id: AC-3
    when: "Lua source containing function spawn_enemy(...), local function clamp(...), function Player:move(...), function M.render(...), and local M = {} is chunked/mined."
    then: "Stored metadata includes symbol_type/symbol_name pairs for function/spawn_enemy, local_function/clamp, method/Player:move or Player.move, method/M.render, and module/M."
  - id: AC-4
    when: "code_search is run against a palace seeded or mined with Lua drawers using language='lua'."
    then: "The result has no unsupported-language error, filters.language is 'lua', and returned hits all have language='lua'."
  - id: AC-5
    when: "code_search is called with language='notareallangnnn' after the change."
    then: "The unsupported-language response includes 'lua' in supported_languages."
  - id: AC-6
    when: "code_search is called with symbol_type='local_function' and with symbol_type='notarealtype'."
    then: "local_function is accepted, and the invalid-symbol response includes 'local_function' in valid_symbol_types."
  - id: AC-7
    when: "A Lua DSL/anonymous-function-only file with no supported declaration boundary is chunked."
    then: "The miner keeps adaptive merge/split fallback behavior and does not emit fake function/local_function/method/module symbols."
  - id: AC-8
    when: "The MCP tools/list schema is inspected for mempalace_code_search."
    then: "The language description includes lua exactly once via the catalog-generated list, and symbol_type description includes local_function."
out_of_scope:
  - "Adding tree-sitter Lua or any mandatory Lua parser dependency."
  - "Changing embedding model, reranking behavior, or LanceDB schema."
  - "Adding Lua knowledge-graph relationship extraction."
  - "Broad documentation rewrites unrelated to Lua support."
---

## Design Notes

- Keep `mempalace_code/language_catalog.py` the source of truth. Add `.lua -> lua` once there so miner detection, readable scan filtering, `code_search(language=...)`, and MCP language hints stay aligned.
- Route `language == "lua"` through `chunk_code()` in `chunk_file()`. Do not add a tree-sitter branch; the first pass should use regex structural chunking and preserve adaptive fallback when no boundary matches.
- Add a dedicated `LUA_BOUNDARY` and `LUA_EXTRACT` near the existing regex language blocks in `miner.py`.
- Match these first-pass Lua boundaries:
  - `function name(...)`
  - `local function name(...)`
  - `function M.foo(...)`
  - `function obj:method(...)`
  - practical top-level table/module declarations such as `M = {}` and `local M = {}`.
- Symbol extraction should distinguish:
  - `function` for global named functions.
  - `local_function` for `local function name(...)`.
  - `method` for dotted/colon member declarations, preserving a useful qualified name.
  - `module` for matched top-level table/module declarations.
- Add `local_function` to `searcher.VALID_SYMBOL_TYPES` and the MCP symbol_type description. `function`, `method`, and `module` already exist.
- Lua comments start with `--`; long comments use `--[[ ... ]]`. Include `--`/`--[[` in Lua lookback prefixes so immediately adjacent comments stay with declarations, but avoid changing comment handling for other languages.
- False-positive guard: avoid treating `local x = function(...)`, anonymous callbacks, and DSL calls as structural declarations in the first pass. They should fall through to adaptive chunks unless a later task adds deeper parsing.
- Keep tests focused and behavior-facing. Existing tests already assert the MCP language description mirrors the sorted catalog, so Lua should appear there without duplicating language-list construction.
