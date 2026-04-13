---
slug: CODE-TREESITTER-INFRA
goal: "Add tree-sitter as an optional dependency with grammar loading, parser factory, and automatic regex fallback"
risk: low
risk_note: "Purely additive optional module. Zero impact when tree-sitter is not installed — existing regex chunking path is unchanged."
files:
  - path: pyproject.toml
    change: "Add [treesitter] optional extra with tree-sitter, tree-sitter-python (3.10+ only), and tree-sitter-typescript"
  - path: mempalace/treesitter.py
    change: "New module: availability flag, grammar loading from wheel packages, parser factory with caching, language-to-grammar mapping"
  - path: mempalace/miner.py
    change: "Import treesitter module; add get_parser() call in chunk_code() with fallback to regex when parser unavailable"
  - path: tests/test_treesitter.py
    change: "New test file: parser creation, AST generation, fallback when tree-sitter missing, fallback when grammar missing, chunk_code parity when tree-sitter installed"
  - path: .github/workflows/ci.yml
    change: "Add treesitter-compat job on Python 3.11, add treesitter-py39 job on Python 3.9 to verify env marker behavior"
  - path: README.md
    change: "Add [treesitter] to the optional extras table"
acceptance:
  - id: AC-1
    when: "pip install mempalace-code[treesitter] on Python 3.10+"
    then: "tree-sitter, tree-sitter-python, and tree-sitter-typescript are installed"
  - id: AC-2
    when: "pip install mempalace-code[treesitter] on Python 3.9"
    then: "tree-sitter and tree-sitter-typescript install; tree-sitter-python is skipped (env marker)"
  - id: AC-3
    when: "get_parser('python') called with tree-sitter[treesitter] installed on 3.10+"
    then: "returns a Parser that produces a valid Tree from Python source bytes"
  - id: AC-4
    when: "get_parser('typescript') called with [treesitter] installed"
    then: "returns a Parser that produces a valid Tree from TypeScript source bytes"
  - id: AC-5
    when: "get_parser('python') called without tree-sitter installed"
    then: "returns None (no ImportError raised)"
  - id: AC-6
    when: "get_parser('java') called (unsupported grammar)"
    then: "returns None"
  - id: AC-7
    when: "chunk_code() processes a Python file with tree-sitter unavailable"
    then: "uses regex chunking unchanged; chunker_strategy metadata is 'regex_structural_v1'"
  - id: AC-7b
    when: "chunk_code() processes a Python file with tree-sitter installed (but AST chunking not yet wired)"
    then: "produces identical chunks to the no-tree-sitter path; chunker_strategy is still 'regex_structural_v1'"
  - id: AC-8
    when: "ruff check mempalace/ tests/ and ruff format --check mempalace/ tests/"
    then: "both pass with no violations"
  - id: AC-9
    when: "python -m pytest tests/ -x -q"
    then: "all existing tests pass; new tests in test_treesitter.py pass"
out_of_scope:
  - "AST-based chunking logic (walking the tree to extract functions/classes) — separate task CODE-TREESITTER-CHUNK"
  - "Grammars beyond Python and TypeScript (Go, Rust, etc.) — incremental additions later"
  - "Custom grammar download or compilation — modern tree-sitter (0.22+) uses pre-built wheels"
  - "Changes to chunk_code() output when tree-sitter IS available — this task only wires the parser; actual AST chunking is future work"
  - "Bumping the Python floor from 3.9 to 3.10"
---

## Design Notes

- **Modern tree-sitter API (0.22+) eliminates grammar download/cache.** Grammars ship as
  pre-built wheel packages (`tree-sitter-python`, `tree-sitter-typescript`) installed via pip
  alongside `tree-sitter`. No git cloning, no `Language.build_library()`, no `.so` management.
  The "caching" aspect is a module-level `dict[str, Parser]` that avoids re-creating parsers.

- **Python 3.9 constraint.** `tree-sitter` dropped 3.9 in v0.24.0, so pin `>=0.22,<0.24`.
  `tree-sitter-python` wheels require 3.10+ (cp310-abi3); use an environment marker
  `python_version >= "3.10"` so the extra installs cleanly on 3.9. On 3.9, Python grammar
  is unavailable → regex fallback. TypeScript grammar (`tree-sitter-typescript>=0.23`)
  supports 3.9 natively.

- **New module `mempalace/treesitter.py`** — keeps all tree-sitter logic isolated:
  ```python
  TREE_SITTER_AVAILABLE: bool  # set at import time via try/except
  _parser_cache: dict[str, Parser]  # language → Parser, lazily populated
  
  def get_parser(language: str) -> Optional[Parser]:
      """Return a cached Parser for the language, or None if unavailable."""
  ```
  Grammar loading per language:
  ```python
  _GRAMMAR_LOADERS = {
      "python": lambda: __import__("tree_sitter_python").language(),
      "typescript": lambda: __import__("tree_sitter_typescript").language_typescript(),
      "tsx": lambda: __import__("tree_sitter_typescript").language_tsx(),
  }
  ```
  Each loader is wrapped in try/except — a missing grammar package returns None, not an error.

- **Integration point in `miner.py`** — `chunk_code()` gains a try-tree-sitter-first path:
  ```python
  from .treesitter import get_parser  # always importable, returns None when unavailable
  
  def chunk_code(content, language, source_file):
      parser = get_parser(language)
      if parser is not None:
          # Future: AST-based chunking goes here (CODE-TREESITTER-CHUNK)
          # For now, fall through to regex
          pass
      # existing regex chunking follows unchanged
  ```
  The `chunker_strategy` metadata field already exists (`"regex_structural_v1"`) — the future
  AST chunking task will set it to `"treesitter_v1"` when the AST path is used.

- **Test strategy (`tests/test_treesitter.py`)**:
  - Module-level `pytest.importorskip("tree_sitter")` for tests that need tree-sitter installed,
    matching the repo convention in `tests/test_migrate.py`. The entire file is skipped when
    tree-sitter is not installed, so the base `.[dev]` CI stays green.
  - Fallback tests live in a separate file or section that monkeypatches `treesitter.TREE_SITTER_AVAILABLE = False`
    and verifies `get_parser()` returns None. These run in all CI jobs (no importorskip).
  - Parse round-trip: call `parser.parse(b"def foo(): pass")`, assert `root_node.type == "module"`
    and first child is `function_definition`.
  - Grammar-missing test: monkeypatch the grammar loader to raise ImportError, verify None return.
  - **Chunk parity test (AC-7b)**: with tree-sitter installed, call `chunk_code()` on a Python
    file and assert the output chunks and `chunker_strategy = "regex_structural_v1"` are identical
    to the regex-only path. This proves the installed-but-deferred path is truly no-op.

- **CI verification (`ci.yml`)**:
  - Add a `treesitter-compat` job on Python 3.11 that installs `.[dev,treesitter]` and runs the
    full test suite. This mirrors the existing `chroma-compat` pattern and ensures AC-1/AC-3/AC-4
    are exercised in CI.
  - Add a `treesitter-py39` job on Python 3.9 that installs `.[dev,treesitter]` and runs the
    full test suite. This verifies AC-2 (tree-sitter-python skipped via env marker) and AC-5
    (get_parser('python') returns None on 3.9).

- **pyproject.toml extra**:
  ```toml
  treesitter = [
      "tree-sitter>=0.22,<0.24",
      "tree-sitter-python>=0.23,<0.24; python_version >= '3.10'",
      "tree-sitter-typescript>=0.23,<0.24",
  ]
  ```
  (Validation finding: `tree-sitter-python` is only available from 0.23.0 on PyPI;
  0.25.0 requires language version 15 which tree-sitter <0.24 does not support.
  Upper bound `<0.24` added to both grammar packages for coherence.)

- **Implementation-time validation** (before merging):
  The following assumptions must be smoke-tested during implementation. If any fail, update
  the version pins or grammar loaders accordingly:
  1. `tree-sitter>=0.22,<0.24` installs cleanly on Python 3.9 and 3.11.
  2. `tree-sitter-python` is skipped on 3.9 via the env marker (no install error).
  3. `tree-sitter-typescript>=0.23` installs on 3.9.
  4. Runtime API entry points: `tree_sitter_python.language()`,
     `tree_sitter_typescript.language_typescript()`, `tree_sitter_typescript.language_tsx()`
     all return valid Language objects compatible with the pinned tree-sitter version.
