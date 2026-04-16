---
slug: CODE-TREESITTER-RUST-CONST-STATIC
goal: "Add const_item and static_item to _chunk_rust_treesitter DEFINITION_TYPES so module-level constants and statics become chunk boundaries"
risk: low
risk_note: "Two-element frozenset addition with mirrored Go precedent; no logic changes needed"
files:
  - path: mempalace/miner.py
    change: "Add 'const_item' and 'static_item' to DEFINITION_TYPES in _chunk_rust_treesitter; update docstring to name them"
  - path: tests/test_chunking.py
    change: "Add RUST_AST_CONST_STATIC fixture; add test_ast_rust_const_detected and test_ast_rust_static_detected"
acceptance:
  - id: AC-1
    when: "A .rs file contains 'pub const MAX_SIZE: usize = 1024;'"
    then: "chunk_code() produces a chunk boundary at that constant, not absorbed into an adjacent chunk"
  - id: AC-2
    when: "A .rs file contains 'pub static DEFAULT_HOST: &str = \"localhost\";'"
    then: "chunk_code() produces a chunk boundary at that static, not absorbed into an adjacent chunk"
  - id: AC-3
    when: "test_ast_rust_const_detected and test_ast_rust_static_detected run (with tree-sitter-rust installed)"
    then: "Both tests pass; existing Rust AST tests are unaffected"
  - id: AC-4
    when: "ruff check + ruff format --check on modified files"
    then: "No lint or format errors"
out_of_scope:
  - "const_item / static_item inside function bodies (not top-level) — tree-sitter surfaces these as children of function_item, not root; the chunker only iterates root children"
  - "Symbol extraction (_RUST_EXTRACT) — no regex patterns for const/static needed in this task"
  - "Updating RUST_AST_ALL_BOUNDARIES fixture to include const/static (use dedicated fixture instead)"
---

## Design Notes

- `_chunk_rust_treesitter` iterates `tree.root_node.children` only, so adding `const_item`/`static_item` to DEFINITION_TYPES only affects top-level declarations. Inlined constants inside function bodies are already children of `function_item` and will not be split.
- The Go chunker (`_chunk_go_treesitter`) includes `const_declaration` and `var_declaration` as the direct precedent. This change brings Rust to parity.
- `LEADING_TYPES` already includes `attribute_item` and comment types; a `const` with `#[doc = "..."]` above it will automatically have the doc-comment attached to the same chunk. No changes to `LEADING_TYPES` needed.
- New fixture `RUST_AST_CONST_STATIC` should be a standalone snippet (not appended to `RUST_AST_ALL_BOUNDARIES`) to keep each fixture focused. Pattern follows `RUST_AST_ATTRIBUTE_ATTACHED`.
- Tests follow the established pattern: call `_skip_if_no_rust_ast()`, then assert the declaration text appears in some chunk's content.
- Docstring update: replace the enumeration line "Extracts function_item, struct_item, enum_item, trait_item, impl_item, mod_item, and type_item" with the updated list including `const_item` and `static_item`.
