---
slug: CODE-TREESITTER-TS
goal: "Replace regex TS/JS/TSX/JSX chunking in chunk_code() with tree-sitter AST-based boundary detection"
risk: low
risk_note: "Follows proven pattern from CODE-TREESITTER-PYTHON. Regex fallback preserved. Grammar infra already wired (treesitter.py). No new dependencies — tree-sitter-typescript already in [treesitter] extra."
files:
  - path: mempalace/treesitter.py
    change: "Add 'javascript' and 'jsx' grammar loaders mapping to language_typescript() and language_tsx() respectively"
  - path: mempalace/miner.py
    change: "Add _chunk_typescript_treesitter() function (~60 lines); wire it into chunk_code() for canonical languages typescript/javascript/tsx/jsx; update EXTENSION_LANG_MAP for .jsx→jsx"
  - path: tests/test_chunking.py
    change: "Add AST-specific TS/JS tests: export function, arrow const, class, interface, type alias, enum, test blocks (describe/it), JSDoc attachment, import grouping, JSX component"
  - path: tests/test_treesitter.py
    change: "Add TS/JS AST integration tests: parser round-trip for JS, JSX grammar selection, chunk_code semantic parity for TypeScript"
acceptance:
  - id: AC-1
    when: "tree-sitter + tree-sitter-typescript installed, chunk_code() called with TypeScript source containing exports, classes, interfaces"
    then: "Returns chunks split at export_statement, function_declaration, class_declaration, and other top-level AST node boundaries with chunker_strategy='treesitter_v1'"
  - id: AC-2
    when: "chunk_code() called with .js file (no JSX)"
    then: "Parsed with TypeScript grammar; function_declaration, class_declaration, lexical_declaration boundaries detected"
  - id: AC-3
    when: "chunk_code() called with .jsx or .tsx file containing JSX syntax"
    then: "Parsed with TSX grammar (no parse errors); components chunked correctly"
  - id: AC-4
    when: "tree-sitter not installed (or grammar unavailable)"
    then: "chunk_code() falls through to regex path unchanged — existing regex tests still pass"
  - id: AC-5
    when: "TS/JS source has leading imports"
    then: "Import statements grouped into preamble chunk (matching regex-path behavior)"
  - id: AC-6
    when: "TS/JS source has JSDoc or line comments immediately above a declaration"
    then: "Leading comment nodes attached to the declaration chunk (not split off)"
  - id: AC-7
    when: "ruff check mempalace/ tests/ && ruff format --check mempalace/ tests/"
    then: "Clean exit (0 violations)"
out_of_scope:
  - "Go/Rust AST chunking (CODE-TREESITTER-EXPAND)"
  - "Changes to chunk size constants (MIN_CHUNK, TARGET_MAX, HARD_MAX)"
  - "Changes to adaptive_merge_split() post-processing"
  - "Embedding model changes"
  - "extract_symbol() changes (symbol extraction remains regex-based)"
  - "Benchmark gate (no embed_ab_bench run required — TS/JS files are not in the benchmark corpus)"
---

## Design Notes

- **New function `_chunk_typescript_treesitter(parser, content, source_file)`** in `miner.py` (~60 lines). Follows the same structure as `_chunk_python_treesitter()`: parse → collect boundaries → extract preamble → slice chunks → `adaptive_merge_split()` → tag strategy.

- **Grammar-to-extension mapping requires a new indirection layer.** `EXTENSION_LANG_MAP` currently maps `.js`/`.jsx` → `"javascript"` and `.ts`/`.tsx` → `"typescript"`. But `_GRAMMAR_LOADERS` only has `"typescript"` and `"tsx"` keys. The solution:
  - Add `"javascript"` loader in `treesitter.py` → `language_typescript()` (TS grammar is a superset of JS).
  - Add `"jsx"` loader in `treesitter.py` → `language_tsx()` (TSX grammar handles JSX syntax).
  - Update `EXTENSION_LANG_MAP` in `miner.py`: change `.jsx` from `"javascript"` to `"jsx"`, and `.tsx` from `"typescript"` to `"tsx"`. This way `get_parser(canonical)` returns the correct grammar for each extension.
  - **Verified experimentally**: TS grammar parses plain JS without errors. TSX grammar parses JSX without errors. TS grammar on JSX produces parse errors — so the distinct JSX/TSX mapping is required.

- **AST node types that start chunk boundaries** (all are top-level `root.children`):
  - `export_statement` — covers `export function`, `export class`, `export interface`, `export type`, `export enum`, `export const`, `export default`
  - `function_declaration` — non-exported functions
  - `class_declaration` — non-exported classes
  - `interface_declaration` — non-exported interfaces (TS grammar)
  - `type_alias_declaration` — non-exported type aliases (TS grammar)
  - `enum_declaration` — non-exported enums (TS grammar)
  - `lexical_declaration` — `const`/`let`/`var` at top level (arrow functions, config objects)
  - `expression_statement` — catches `describe()`, `it()`, `test()` calls and `module.exports = ...`
  - `import_statement` — **not** a boundary; imports are collected into the preamble

- **Import handling differs from Python.** In TypeScript/JS, imports are almost always at the top of the file. Rather than treating each `import_statement` as a separate boundary, collect all consecutive leading `import_statement` nodes into the preamble chunk. This matches the regex path's import-grouping behavior. Non-leading imports (rare but legal) are treated as preamble content between definitions.

- **Boundary definition set** (as a frozenset for O(1) lookup):
  ```python
  DEFINITION_TYPES = frozenset({
      "export_statement",
      "function_declaration",
      "class_declaration",
      "interface_declaration",
      "type_alias_declaration",
      "enum_declaration",
      "lexical_declaration",
      "expression_statement",
  })
  ```

- **Comment attachment**: Same algorithm as Python — walk backwards from a definition node collecting consecutive `comment` siblings with no `\n\n` gap. In the TS grammar, JSDoc `/** ... */` appears as a single `comment` node, so it gets attached naturally.

- **Preamble**: everything before the first `DEFINITION_TYPES` node (imports, shebang, license headers, standalone comments). Sliced via byte offsets, stripped, added as the first raw chunk if non-empty.

- **Fallback for no-definition files**: When the file has no `DEFINITION_TYPES` nodes (e.g. a JSON-like config or a pure-import barrel file), fall back to `chunk_adaptive_lines()` and tag as `"treesitter_adaptive_v1"` — same pattern as Python.

- **Wiring in `chunk_code()`**: Extend the parser dispatch block:
  ```python
  if parser is not None:
      if canonical == "python":
          return _chunk_python_treesitter(parser, content, source_file)
      if canonical in ("typescript", "javascript", "tsx", "jsx"):
          return _chunk_typescript_treesitter(parser, content, source_file)
  ```
  The function works identically for all four variants because grammar selection already happened in `get_parser(canonical)`.

- **`extract_symbol()` is unchanged.** It scans chunk text for `function`, `class`, `interface`, `type`, `const`, `export` patterns via regex. Since AST chunks contain the same source text (just with better boundaries), `extract_symbol()` continues to work. Out of scope.

- **Test plan**:
  - `test_chunking.py` — new tests gated behind `_skip_if_no_ts_ast()` (importorskip `tree_sitter` + `tree_sitter_typescript`):
    - `test_ast_ts_exports_detected` — export function, const, class all appear in chunks
    - `test_ast_ts_interface_boundary` — interface gets its own chunk
    - `test_ast_ts_type_alias_boundary` — `type X = ...` gets its own chunk
    - `test_ast_ts_enum_boundary` — enum declaration detected
    - `test_ast_ts_test_blocks_detected` — `describe()`/`it()` expression_statement nodes
    - `test_ast_ts_jsdoc_attached` — JSDoc comment attached to declaration
    - `test_ast_ts_imports_in_preamble` — imports grouped before first definition
    - `test_ast_ts_chunker_strategy_tag` — all chunks tagged `treesitter_v1`
    - `test_ast_tsx_jsx_parsed` — TSX file with JSX syntax parses without errors
    - `test_ast_js_extension_handled` — `.js` files routed through AST path
    - `test_ast_jsx_extension_handled` — `.jsx` files routed through TSX grammar
    - `test_ast_ts_no_definitions_falls_back` — barrel/config file gets `treesitter_adaptive_v1`
  - `test_treesitter.py` — add:
    - `test_get_parser_javascript_returns_parser` — verifies the new `"javascript"` loader
    - `test_get_parser_jsx_returns_parser` — verifies the new `"jsx"` loader
    - `test_chunk_code_typescript_ast_semantic_parity` — TS file chunks contain expected symbols

- **No benchmark gate needed.** The embed_ab_bench corpus is Python-only (mempalace repo). TS/JS files aren't in the benchmark set, so there's no R@5 to regress. If a TS/JS benchmark corpus is added later (CODE-BENCH-TS), it can validate retroactively.
