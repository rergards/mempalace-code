---
slug: CODE-TREESITTER-EXPAND
goal: "Add tree-sitter AST chunking for Go and Rust, following the Python/TS pattern"
risk: low
risk_note: "Follows proven CODE-TREESITTER-PYTHON / CODE-TREESITTER-TS patterns. Regex fallback paths for Go/Rust already exist and are tested. New grammar packages follow the same PyCapsule API as existing ones. No structural changes to chunk_file(), EXTENSION_LANG_MAP, or get_boundary_pattern()."
files:
  - path: mempalace/treesitter.py
    change: "Add 'go' and 'rust' entries to _GRAMMAR_LOADERS; each imports tree_sitter_go.language() / tree_sitter_rust.language()"
  - path: mempalace/miner.py
    change: "Add _chunk_go_treesitter() (~60 lines) and _chunk_rust_treesitter() (~65 lines); update chunk_code() dispatch to route 'go' and 'rust' to these functions when parser is available; update docstring for chunk_code()"
  - path: pyproject.toml
    change: "Add 'tree-sitter-go>=0.23,<0.24' and 'tree-sitter-rust>=0.23,<0.24' to the [treesitter] optional-dependencies group"
  - path: tests/test_chunking.py
    change: "Add AST-specific Go and Rust test sections with skip guards, fixture sources, and per-boundary-type assertions analogous to the Python/TS AST sections (lines 837–1197)"
  - path: tests/test_treesitter.py
    change: "Add get_parser() smoke tests for 'go' and 'rust': returns Parser when grammar installed, returns None when not installed (mock ImportError)"
acceptance:
  - id: AC-1
    when: "tree-sitter + tree-sitter-go installed, chunk_code() called with Go source containing func, type struct, type interface, const block, var declaration"
    then: "Returns chunks split at function_declaration, method_declaration, type_declaration, const_declaration, var_declaration boundaries with chunker_strategy='treesitter_v1'"
  - id: AC-2
    when: "tree-sitter + tree-sitter-rust installed, chunk_code() called with Rust source containing fn, struct, enum, trait, impl, mod, type items"
    then: "Returns chunks split at function_item, struct_item, enum_item, trait_item, impl_item, mod_item, type_item boundaries with chunker_strategy='treesitter_v1'"
  - id: AC-3
    when: "tree-sitter not installed or grammar package missing"
    then: "chunk_code() falls through to GO_BOUNDARY / RUST_BOUNDARY regex path unchanged; existing Go/Rust regex tests still pass"
  - id: AC-4
    when: "Go or Rust source has leading comments immediately above a declaration (no blank line)"
    then: "Comment nodes attached to the declaration chunk (not split off). For Rust, attribute_item nodes (#[...]) are also attached to the item that follows"
  - id: AC-5
    when: "ruff check mempalace/ tests/ && ruff format --check mempalace/ tests/"
    then: "Clean exit (0 violations)"
out_of_scope:
  - "Changes to GO_BOUNDARY or RUST_BOUNDARY regex patterns"
  - "Changes to EXTENSION_LANG_MAP (.go→go, .rs→rust already correct)"
  - "Changes to chunk_file() dispatch (go/rust already in the language set)"
  - "Changes to get_boundary_pattern() (GO_BOUNDARY/RUST_BOUNDARY already wired)"
  - "Changes to extract_symbol() (symbol extraction remains regex-based)"
  - "Changes to chunk size constants or adaptive_merge_split()"
  - "Support for additional languages beyond Go and Rust"
  - "Benchmark gate — no embed_ab_bench run required"
---

## Design Notes

- **Two new private functions in `miner.py`** following the exact template of `_chunk_python_treesitter()` (lines 628–702):
  - `_chunk_go_treesitter(parser, content, source_file)` — Go boundary nodes
  - `_chunk_rust_treesitter(parser, content, source_file)` — Rust boundary nodes
  Both: parse → collect boundaries with leading-sibling attachment → extract preamble → slice raw chunks → `adaptive_merge_split()` → tag `treesitter_v1`.

- **Go AST node types** (top-level `root.children` in tree-sitter-go grammar):
  - `function_declaration` — bare functions: `func Foo()`
  - `method_declaration` — methods: `func (r *Receiver) Foo()`
  - `type_declaration` — type definitions: `type Foo struct {}`, `type Bar interface {}`
  - `const_declaration` — `const x = ...` and grouped `const ( ... )`
  - `var_declaration` — `var x ...` and grouped `var ( ... )`
  - Leading-sibling walkback: stop on `comment` nodes with no blank-line gap (same logic as Python). Go has no decorators.

- **Rust AST node types** (top-level `root.children` in tree-sitter-rust grammar):
  - `function_item` — any function/method: bare `fn`, `pub fn`, `pub(crate) fn`, `async fn`, `pub async fn`
  - `struct_item` — `struct Foo`
  - `enum_item` — `enum Foo`
  - `trait_item` — `trait Foo`
  - `impl_item` — `impl Foo` and `impl Bar for Foo`
  - `mod_item` — `mod foo` (both declaration and inline)
  - `type_item` — `type Foo = Bar`
  - Leading-sibling walkback: attach both `attribute_item` (`#[...]`) **and** `line_comment` / `block_comment` nodes (no blank-line gap). Unlike Python's `decorated_definition`, tree-sitter-rust keeps `#[derive(...)]` as a separate `attribute_item` sibling node rather than wrapping it with the item, so the walkback is critical for Rust attribute attachment.

- **`chunk_code()` dispatch update** (currently lines 806–810 in `miner.py`):
  ```python
  if parser is not None:
      if canonical == "python":
          return _chunk_python_treesitter(parser, content, source_file)
      if canonical in ("typescript", "javascript", "tsx", "jsx"):
          return _chunk_typescript_treesitter(parser, content, source_file)
      if canonical == "go":
          return _chunk_go_treesitter(parser, content, source_file)
      if canonical == "rust":
          return _chunk_rust_treesitter(parser, content, source_file)
  ```

- **Grammar loader entries in `treesitter.py`** (add to `_GRAMMAR_LOADERS` dict, lines 30–36):
  ```python
  "go":   lambda: __import__("tree_sitter_go").language(),
  "rust": lambda: __import__("tree_sitter_rust").language(),
  ```
  Both packages expose `.language()` returning a PyCapsule — the same API as `tree_sitter_python`. Verify exact callable name against installed package if pinned version differs.

- **pyproject.toml version constraint**: use `>=0.23,<0.24` to match existing grammar pins. If `tree-sitter-go` or `tree-sitter-rust` are only available at `>=0.24`, widen the constraint to `>=0.23,<0.25` and verify the PyCapsule API is still compatible with `tree-sitter>=0.22,<0.24` — if not, align all grammar pins together.

- **Test skip guards** — add a per-language helper analogous to `_skip_if_no_ast()` in `test_chunking.py`:
  ```python
  def _skip_if_no_go_ast():
      try:
          import tree_sitter; import tree_sitter_go  # noqa: F401
      except ImportError:
          pytest.skip("tree-sitter-go not installed")

  def _skip_if_no_rust_ast():
      try:
          import tree_sitter; import tree_sitter_rust  # noqa: F401
      except ImportError:
          pytest.skip("tree-sitter-rust not installed")
  ```
  No Python version restriction for Go or Rust (unlike Python grammar which requires 3.10+).

- **Go test coverage**: fixture with `func`, `method`, `type struct`, `type interface`, `const (`, `var`; assert each boundary type produces a separate chunk, `chunker_strategy='treesitter_v1'`, preamble preserved, comment attached, fallback to adaptive when no top-level definitions.

- **Rust test coverage**: fixture with `fn`, `pub fn`, `pub(crate) fn`, `struct`, `enum`, `trait`, `impl`, `mod`, `type`, `#[derive(...)]`; assert each boundary type produces a separate chunk, attribute_item attached to its item, `chunker_strategy='treesitter_v1'`, preamble preserved, fallback to adaptive when no items.

- **No changes to `tests/test_miner.py`**: integration-level mining tests for Go/Rust are considered out of scope. The per-chunker unit tests in `test_chunking.py` are sufficient for AC coverage.
