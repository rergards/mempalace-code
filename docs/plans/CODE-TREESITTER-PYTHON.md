---
slug: CODE-TREESITTER-PYTHON
goal: "Replace regex Python chunking in chunk_code() with tree-sitter AST-based boundary detection"
risk: low
risk_note: "Regex fallback is preserved unchanged; AST path only activates when tree-sitter + python grammar are installed. Benchmark gate ensures no R@5 regression."
files:
  - path: mempalace/miner.py
    change: "Add _chunk_python_treesitter() function; wire it into chunk_code() when parser is available and language is python; propagate chunker_strategy from chunk dicts in _collect_specs_for_file()"
  - path: tests/test_chunking.py
    change: "Add AST-specific Python chunking tests: function, class, decorated, nested class, preamble handling"
  - path: tests/test_treesitter.py
    change: "Update parity test to expect AST-path divergence for Python; add integration tests for AST chunking output shape"
  - path: tests/test_miner.py
    change: "Add integration test: mine a Python file through process_file() with tree-sitter active, assert stored drawer metadata contains chunker_strategy='treesitter_v1'"
acceptance:
  - id: AC-1
    when: "tree-sitter + tree-sitter-python installed, chunk_code() called with a Python source containing functions and classes"
    then: "Returns chunks split at function_definition, class_definition, and decorated_definition AST node boundaries"
  - id: AC-2
    when: "tree-sitter not installed (or grammar unavailable)"
    then: "chunk_code() falls through to regex path unchanged — existing regex tests still pass"
  - id: AC-3
    when: "embed_ab_bench.py run with AST chunking active"
    then: "R@5 >= 0.950 (no regression from baseline)"
  - id: AC-4
    when: "A Python file is mined through process_file() or mine() with tree-sitter active"
    then: "Stored drawer metadata contains chunker_strategy='treesitter_v1' (verified via mining-path integration test in test_miner.py, not just raw chunk_code() output)"
  - id: AC-5
    when: "Python source has leading imports, module docstring, or license header before the first definition"
    then: "Preamble text is detected as a separate raw chunk before the first definition boundary; it may remain separate or be merged with the next chunk by adaptive_merge_split() post-processing (matching regex-path behavior)"
  - id: AC-6
    when: "Python source has comments immediately above a function/class"
    then: "Leading comment nodes are attached to the definition chunk (not split off)"
  - id: AC-7
    when: "ruff check mempalace/ tests/ && ruff format --check mempalace/ tests/"
    then: "Clean exit (0 violations)"
out_of_scope:
  - "TypeScript/JS AST chunking (CODE-TREESITTER-TS)"
  - "Go/Rust AST chunking (CODE-TREESITTER-EXPAND)"
  - "Changes to chunk size constants (MIN_CHUNK, TARGET_MAX, HARD_MAX)"
  - "Changes to adaptive_merge_split() post-processing"
  - "Embedding model changes"
  - "extract_symbol() changes (symbol extraction remains regex-based)"
---

## Design Notes

- **New function `_chunk_python_treesitter(parser, content, source_file)`** in `miner.py` (~50 lines). All chunking logic lives in `miner.py`; `treesitter.py` stays a parser factory only.

- **AST walk strategy**: iterate `root.children` (top-level nodes only, do NOT recurse into class bodies). This matches regex behavior where a class + its methods form one chunk. Node types that start a chunk boundary:
  - `function_definition`
  - `class_definition`
  - `decorated_definition` (wraps decorator + def/class, so decorators are included automatically)

- **Comment attachment**: in the Python tree-sitter grammar, comments are sibling `comment` nodes at the same tree level. Walk backwards from a definition node to collect consecutive `comment` siblings with no gap (no blank lines between them). This mirrors the regex lookback logic at `miner.py:672-681`.

- **Preamble handling**: all nodes before the first definition boundary (imports, module docstring `expression_statement`, comments, etc.) are joined into a preamble chunk. Identical to the regex path's preamble extraction at `miner.py:689-693`.

- **Text extraction**: use `node.start_byte` / `node.end_byte` on the source bytes to slice chunk text. Convert back to str. This avoids line-based indexing and is exact.

- **Post-processing**: raw text chunks are fed through the existing `adaptive_merge_split()` — same merge/split behavior as regex path.

- **Strategy propagation**: `_chunk_python_treesitter()` returns dicts `{"content": str, "chunk_index": int, "chunker_strategy": "treesitter_v1"}`. `_collect_specs_for_file()` at line 965 changes from hardcoded `"regex_structural_v1"` to `chunk.get("chunker_strategy", "regex_structural_v1")`.

- **Language normalization in `chunk_code()`**: before calling `get_parser()`, normalize extension-style inputs to canonical names using the existing `EXTENSION_LANG_MAP` (`miner.py:25`). This ensures callers passing `".py"` (as all existing tests do) get the AST path:
  ```python
  canonical = EXTENSION_LANG_MAP.get(language, language)
  parser = get_parser(canonical)
  ```
  The rest of `chunk_code()` continues using the original `language` variable for backward-compatible checks (e.g. `is_ts_js`, `get_boundary_pattern()`).

- **Wiring in `chunk_code()`**: replace the `pass` block (lines 638-641) with:
  ```python
  if parser is not None:
      if canonical == "python":
          return _chunk_python_treesitter(parser, content, source_file)
  ```
  Non-Python languages still fall through to regex (until CODE-TREESITTER-TS / CODE-TREESITTER-EXPAND).

- **Test updates**:
  - `test_treesitter.py:test_chunk_code_parity_with_treesitter_installed` must be updated — Python AST chunks will now differ from regex chunks. Replace with a test that verifies AST chunks contain the same functions/classes (semantic parity, not byte-identical).
  - New tests in `test_chunking.py`: decorated functions, nested classes, standalone functions, preamble with imports, empty file, and the comment-attachment edge case.
  - Tests requiring tree-sitter use `pytest.importorskip("tree_sitter")` + Python 3.10+ version guard (matching existing pattern).

- **Python version note**: the AST path only activates when `tree-sitter-python` is installed, which `pyproject.toml` constrains to Python >= 3.10. On Python 3.9, `get_parser()` returns `None` and the regex path runs as before. This is the existing gating pattern from CODE-TREESITTER-INFRA.

- **`extract_symbol()` assumption**: `extract_symbol()` remains regex-based (out of scope). When the AST path produces chunks starting with attached comment lines, `extract_symbol()` still works correctly because it scans for `def `/ `class ` patterns anywhere in the chunk text, not just at the first line. No changes needed.

- **Benchmark validation**: run `python benchmarks/embed_ab_bench.py --models minilm --out results_treesitter_python.json` after implementation. Compare R@5 against baseline 0.950. The 20-query set includes `"chunk code at structural boundaries for Python TypeScript Go"` which directly tests Python chunking quality.
