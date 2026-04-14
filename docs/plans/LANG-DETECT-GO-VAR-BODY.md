---
slug: LANG-DETECT-GO-VAR-BODY
goal: "Remove var\\s+\\w+ from GO_BOUNDARY; replace with var\\s+\\( so only grouped var blocks create chunk boundaries"
risk: low
risk_note: "Single-change regex edit to a rarely-hit fallback path; tree-sitter path is unaffected"
files:
  - path: mempalace/miner.py
    change: "Replace r\"|var\\s+\\w+\" with r\"|var\\s+\\(\" in GO_BOUNDARY (line ~452)"
  - path: tests/test_chunking.py
    change: "Add regression test: Go function body with var declarations does not split mid-function"
acceptance:
  - id: AC-1
    when: "chunk_code() (regex path, tree-sitter disabled) is called on a Go function body containing indented var declarations"
    then: "The function body is not split at the var line; the var line and surrounding code appear in the same chunk"
  - id: AC-2
    when: "chunk_code() processes Go code with func and type declarations"
    then: "Existing tests test_go_func_boundaries and test_go_no_split_across_func continue to pass"
  - id: AC-3
    when: "chunk_code() (regex path) processes a Go file with a top-level var (...) block"
    then: "The var block creates a new chunk boundary"
  - id: AC-4
    when: "ruff check mempalace/ tests/ is run after the change"
    then: "No lint errors in modified files"
out_of_scope:
  - "Tree-sitter path (_chunk_go_treesitter) — already correct; var_declaration in root_node.children is top-level only"
  - "const\\s+\\( in GO_BOUNDARY — no change needed; already a block-style pattern"
  - "Single-line top-level var declarations (var foo int) — will fall through to adaptive_merge_split, acceptable"
  - "TS_BOUNDARY changes (separate backlog item CODE-SMART-CHUNK-VAR-BOUNDARY)"
---

## Design Notes

- The regex fallback in `chunk_code()` uses `stripped = line.strip()` as the match target for Go (and Python/Rust), unlike TS/JS which match the original line to guard against indented constructs. This means `    var result int` inside a function body becomes `var result int` after stripping and fires the `var\s+\w+` arm.

- The tree-sitter path (`_chunk_go_treesitter`) is **not affected** — it iterates `tree.root_node.children`, which only includes top-level AST nodes. Body-local var declarations are nested under a `function_declaration` node and never appear as root children.

- Replacing `var\s+\w+` with `var\s+\(` is the minimal fix: it keeps boundary detection for grouped var blocks (`var (\n  a int\n)`) while eliminating false positives from inline vars in function bodies. Consistent with `const\s+\(` which already uses the block-only pattern.

- Top-level single-line `var foo int` will no longer be a chunk boundary on the regex path. In practice these are tiny and `adaptive_merge_split` will merge them into adjacent chunks; this is acceptable since tree-sitter is the primary path for any installation that has `tree-sitter-go` installed.

- The regression test must force the regex path by monkeypatching `TREE_SITTER_AVAILABLE = False` (see `test_chunk_code_regex_fallback_when_treesitter_unavailable` for the pattern).
