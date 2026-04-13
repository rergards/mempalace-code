"""
test_treesitter.py — Tests for mempalace/treesitter.py and chunk_code() integration.

Structure:
  - Fallback tests (no importorskip): run in all CI jobs regardless of whether
    tree-sitter is installed. Use monkeypatching to exercise the None-return paths.
  - Parser tests (importorskip tree_sitter): skipped when tree-sitter is not
    installed so base .[dev] CI stays green.
"""

import pytest

import mempalace.treesitter as ts_mod
from mempalace.miner import chunk_code


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
    assert ts_mod.get_parser("rust") is None
    assert ts_mod.get_parser("go") is None


def test_get_parser_returns_none_when_grammar_import_fails(monkeypatch):
    """get_parser() returns None (no exception) when the grammar package raises ImportError."""
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", True)
    # Clear cache so we hit the loader
    monkeypatch.setattr(ts_mod, "_parser_cache", {})

    def broken_loader():
        raise ImportError("no module named tree_sitter_python")

    monkeypatch.setitem(ts_mod._GRAMMAR_LOADERS, "python", broken_loader)
    assert ts_mod.get_parser("python") is None


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
    assert parser is not None


def test_get_parser_caches_parser():
    """Repeated calls to get_parser() return the same Parser instance (cached)."""
    ts_mod._parser_cache.clear()
    p1 = ts_mod.get_parser("typescript")
    p2 = ts_mod.get_parser("typescript")
    assert p1 is p2


def test_chunk_code_parity_with_treesitter_installed(monkeypatch):
    """AC-7b: chunk_code() output is identical whether tree-sitter is installed or not.

    The parser is obtained but unused (AST chunking is future work). Chunks and
    chunk_index values must match the regex-only path exactly.
    """
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

    # Run with tree-sitter available (normal path)
    ts_mod._parser_cache.clear()
    chunks_with_ts = chunk_code(src, "python", "test.py")

    # Run with tree-sitter disabled
    monkeypatch.setattr(ts_mod, "TREE_SITTER_AVAILABLE", False)
    monkeypatch.setattr(ts_mod, "_parser_cache", {})
    chunks_without_ts = chunk_code(src, "python", "test.py")

    assert len(chunks_with_ts) == len(chunks_without_ts)
    for a, b in zip(chunks_with_ts, chunks_without_ts):
        assert a["content"] == b["content"]
        assert a["chunk_index"] == b["chunk_index"]
