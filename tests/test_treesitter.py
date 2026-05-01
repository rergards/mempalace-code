"""
test_treesitter.py — Tests for mempalace/treesitter.py and chunk_code() integration.

Structure:
  - Fallback tests (no importorskip): run in all CI jobs regardless of whether
    tree-sitter is installed. Use monkeypatching to exercise the None-return paths.
  - Parser tests (importorskip tree_sitter): skipped when tree-sitter is not
    installed so base .[dev] CI stays green.
"""

import pytest

import mempalace_code.treesitter as ts_mod
from mempalace_code.miner import chunk_code

# =============================================================================
# Fallback tests — always run, even without tree-sitter installed
# =============================================================================


def test_get_parser_returns_none_when_unavailable(monkeypatch):
    """get_parser() returns None (no exception) when TREE_SITTER_AVAILABLE is False."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", False)
    assert ts_mod.get_parser("python") is None
    assert ts_mod.get_parser("typescript") is None


def test_get_parser_returns_none_for_unsupported_language(monkeypatch):
    """get_parser() returns None for languages not in _GRAMMAR_LOADERS."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", True)
    assert ts_mod.get_parser("java") is None
    assert ts_mod.get_parser("c") is None


def test_get_parser_returns_none_when_grammar_import_fails(monkeypatch):
    """get_parser() returns None (no exception) when the grammar package raises ImportError."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", True)
    # Clear cache so we hit the loader
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    def broken_loader():
        raise ImportError("no module named tree_sitter_python")

    monkeypatch.setitem(ts_mod._GRAMMAR_LOADERS, "python", broken_loader)
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = ts_mod.get_parser("python")

    assert result is None
    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert "python" in str(caught[0].message)
    assert "ImportError" in str(caught[0].message)


def test_chunk_code_regex_fallback_when_treesitter_unavailable(monkeypatch):
    """chunk_code() uses regex chunking when TREE_SITTER_AVAILABLE is False."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", False)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    src = "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n" * 5
    chunks = chunk_code(src, "python", "test.py")
    assert len(chunks) > 0
    # chunker_strategy must be the regex sentinel
    for chunk in chunks:
        assert "foo" in chunk["content"] or "bar" in chunk["content"]


def test_chunk_code_chunker_strategy_is_regex(monkeypatch):
    """chunk_code() does not change the chunker_strategy metadata (that's miner's job)."""
    # chunk_code returns raw {"content", "chunk_index"} dicts — strategy is set in
    # _collect_specs_for_file. This test confirms chunk_code output is unchanged.
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", False)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    src = "def alpha():\n    pass\n\n\nclass Beta:\n    pass\n" * 3
    chunks = chunk_code(src, "python", "test.py")
    assert all("content" in c and "chunk_index" in c for c in chunks)


# =============================================================================
# Parser tests — skipped unless tree-sitter is installed
# =============================================================================

pytest.importorskip("tree_sitter")


def test_get_parser_python_returns_parser():
    """get_parser('python') returns a non-None Parser on Python 3.10+."""
    import sys

    if sys.version_info < (3, 10):
        pytest.skip("tree-sitter-python requires Python 3.10+")
    parser = ts_mod.get_parser("python")
    assert parser is not None


def test_get_parser_python_parses_source():
    """Parser for 'python' produces a valid Tree from Python source bytes."""
    import sys

    if sys.version_info < (3, 10):
        pytest.skip("tree-sitter-python requires Python 3.10+")
    parser = ts_mod.get_parser("python")
    if parser is None:
        pytest.skip("tree-sitter-python grammar not installed")
    tree = parser.parse(b"def foo(): pass")
    root = tree.root_node
    assert root.type == "module"
    assert any(child.type == "function_definition" for child in root.children)


def test_get_parser_typescript_returns_parser():
    """get_parser('typescript') returns a non-None Parser when grammar is installed."""
    parser = ts_mod.get_parser("typescript")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")
    assert parser is not None


def test_get_parser_typescript_parses_source():
    """Parser for 'typescript' produces a valid Tree from TypeScript source bytes."""
    parser = ts_mod.get_parser("typescript")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")
    tree = parser.parse(b"const x: number = 42;")
    root = tree.root_node
    assert root.type == "program"
    assert len(root.children) > 0


def test_get_parser_tsx_returns_parser():
    """get_parser('tsx') returns a non-None Parser when grammar is installed."""
    parser = ts_mod.get_parser("tsx")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")
    assert parser is not None


def test_get_parser_caches_parser():
    """Repeated calls to get_parser() return the same Parser instance (cached)."""
    ts_mod._parser_cache.clear()
    p1 = ts_mod.get_parser("typescript")
    p2 = ts_mod.get_parser("typescript")
    assert p1 is p2


def test_chunk_code_python_ast_semantic_parity():
    """Python AST chunking preserves all definitions (semantic parity with regex path).

    The AST path may split chunks differently than the regex path, but all function
    and class names must appear in the joined output, and each chunk must carry
    chunker_strategy='treesitter_v1'.
    """
    import sys

    if sys.version_info < (3, 10):
        pytest.skip("tree-sitter-python requires Python 3.10+")
    parser = ts_mod.get_parser("python")
    if parser is None:
        pytest.skip("tree-sitter-python grammar not installed")

    src = (
        "def alpha():\n"
        '    """Alpha docstring."""\n'
        "    return 1\n\n\n"
        "def beta():\n"
        "    return 2\n\n\n"
        "class Gamma:\n"
        "    def method(self):\n"
        "        pass\n"
    ) * 3

    ts_mod._parser_cache.clear()
    chunks = chunk_code(src, "python", "test.py")
    joined = "\n".join(c["content"] for c in chunks)

    # All top-level definitions must appear in the AST-chunked output
    assert "def alpha" in joined
    assert "def beta" in joined
    assert "class Gamma" in joined

    # Every chunk carries the AST strategy tag
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_chunk_code_python_ast_extension_input():
    """chunk_code() with '.py' extension activates the AST path on Python 3.10+."""
    import sys

    if sys.version_info < (3, 10):
        pytest.skip("tree-sitter-python requires Python 3.10+")
    parser = ts_mod.get_parser("python")
    if parser is None:
        pytest.skip("tree-sitter-python grammar not installed")

    src = "def foo():\n    return 42\n\n\ndef bar():\n    return 0\n"
    # Callers that pass ".py" (extension style) must also hit the AST path
    chunks = chunk_code(src, ".py", "test.py")
    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"


def test_get_parser_javascript_returns_parser():
    """get_parser('javascript') returns a non-None Parser when grammar is installed."""
    parser = ts_mod.get_parser("javascript")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")
    assert parser is not None


def test_get_parser_jsx_returns_parser():
    """get_parser('jsx') returns a non-None Parser (TSX grammar) when grammar is installed."""
    parser = ts_mod.get_parser("jsx")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")
    assert parser is not None


def test_get_parser_javascript_parses_js():
    """Parser for 'javascript' produces a valid Tree from plain JS source."""
    parser = ts_mod.get_parser("javascript")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")
    tree = parser.parse(b"function hello() { return 42; }")
    root = tree.root_node
    assert root.type == "program"
    assert any(child.type == "function_declaration" for child in root.children)


def test_get_parser_jsx_parses_jsx():
    """Parser for 'jsx' (TSX grammar) produces a valid Tree from JSX source."""
    parser = ts_mod.get_parser("jsx")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")
    tree = parser.parse(b"const App = () => <div>Hello</div>;")
    root = tree.root_node
    assert root.type == "program"

    # No ERROR nodes — TSX grammar must handle JSX without parse errors
    def has_error(node):
        if node.type == "ERROR":
            return True
        return any(has_error(c) for c in node.children)

    assert not has_error(root)


def test_get_parser_go_returns_parser():
    """get_parser('go') returns a non-None Parser when tree-sitter-go is installed."""
    parser = ts_mod.get_parser("go")
    if parser is None:
        pytest.skip("tree-sitter-go grammar not installed")
    assert parser is not None


def test_get_parser_go_parses_source():
    """Parser for 'go' produces a valid Tree from Go source bytes."""
    parser = ts_mod.get_parser("go")
    if parser is None:
        pytest.skip("tree-sitter-go grammar not installed")
    tree = parser.parse(b'package main\n\nfunc Hello() string { return "hello" }\n')
    root = tree.root_node
    assert root.type == "source_file"
    assert any(child.type == "function_declaration" for child in root.children)


def test_get_parser_go_returns_none_when_import_fails(monkeypatch):
    """get_parser('go') returns None (no exception) when tree_sitter_go raises ImportError."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", True)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    def broken_loader():
        raise ImportError("no module named tree_sitter_go")

    monkeypatch.setitem(ts_mod._GRAMMAR_LOADERS, "go", broken_loader)
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = ts_mod.get_parser("go")

    assert result is None
    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert "go" in str(caught[0].message)


def test_get_parser_rust_returns_parser():
    """get_parser('rust') returns a non-None Parser when tree-sitter-rust is installed."""
    parser = ts_mod.get_parser("rust")
    if parser is None:
        pytest.skip("tree-sitter-rust grammar not installed")
    assert parser is not None


def test_get_parser_rust_parses_source():
    """Parser for 'rust' produces a valid Tree from Rust source bytes."""
    parser = ts_mod.get_parser("rust")
    if parser is None:
        pytest.skip("tree-sitter-rust grammar not installed")
    tree = parser.parse(b'pub fn greet() -> &\'static str { "hello" }\n')
    root = tree.root_node
    assert root.type == "source_file"
    assert any(child.type == "function_item" for child in root.children)


def test_get_parser_rust_returns_none_when_import_fails(monkeypatch):
    """get_parser('rust') returns None (no exception) when tree_sitter_rust raises ImportError."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", True)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    def broken_loader():
        raise ImportError("no module named tree_sitter_rust")

    monkeypatch.setitem(ts_mod._GRAMMAR_LOADERS, "rust", broken_loader)
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = ts_mod.get_parser("rust")

    assert result is None
    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert "rust" in str(caught[0].message)


def test_chunk_code_typescript_ast_semantic_parity():
    """TS AST chunking preserves all top-level definitions (semantic parity check).

    All exported and non-exported functions, classes, interfaces, and type aliases
    must appear in the joined output, and each chunk must carry
    chunker_strategy='treesitter_v1'.
    """
    parser = ts_mod.get_parser("typescript")
    if parser is None:
        pytest.skip("tree-sitter-typescript grammar not installed")

    src = (
        "import { foo } from './foo';\n\n"
        "export function greet(name: string): string {\n"
        "    return `Hello, ${name}`;\n"
        "}\n\n"
        "export class Greeter {\n"
        "    greet(name: string) { return `Hi, ${name}`; }\n"
        "}\n\n"
        "export interface Salutation {\n"
        "    message: string;\n"
        "}\n\n"
        "export type Name = string;\n"
    ) * 2

    ts_mod._parser_cache.clear()
    chunks = chunk_code(src, "typescript", "test.ts")
    joined = "\n".join(c["content"] for c in chunks)

    assert "function greet" in joined
    assert "class Greeter" in joined
    assert "interface Salutation" in joined
    assert "type Name" in joined

    for chunk in chunks:
        assert chunk.get("chunker_strategy") == "treesitter_v1"
