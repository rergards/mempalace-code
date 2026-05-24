"""
test_migrate_storage_smoke.py — Tests for scripts/migrate_storage_smoke.py.

Covers: [chroma] extra gate, deterministic embedding helper, count-line parser,
fixture-generation row count (chroma-gated), and cleanup semantics.

These tests do NOT require a committed Chroma database; fixtures are generated
in temporary directories and removed after each test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

# ── Load the smoke module from scripts/ without installing it ──────────────────

_smoke_path = Path(__file__).parent.parent / "scripts" / "migrate_storage_smoke.py"
_spec = importlib.util.spec_from_file_location("migrate_storage_smoke", _smoke_path)
_smoke_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]  # reason: spec_from_file_location can return None but we assert above
_spec.loader.exec_module(_smoke_mod)  # type: ignore[union-attr]  # reason: loader is ModuleLoader at runtime but typed as Optional


# ── [chroma] gate ─────────────────────────────────────────────────────────────


def test_missing_chroma_reports_chroma_extra(monkeypatch, capsys):
    """When chromadb is absent, _check_chroma() prints the install hint and exits 1.

    The exit must happen before any fixture data is created or the CLI is invoked
    (AC-4: missing-Chroma path).
    """
    monkeypatch.setitem(sys.modules, "chromadb", None)

    with pytest.raises(SystemExit) as exc_info:
        _smoke_mod._check_chroma()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "[chroma]" in captured.err, f"install hint missing from stderr: {captured.err!r}"


def test_missing_chroma_exits_before_fixture_creation(monkeypatch):
    """main() with chromadb absent exits 1 before entering the TemporaryDirectory block."""
    monkeypatch.setitem(sys.modules, "chromadb", None)
    monkeypatch.setattr(sys, "argv", ["smoke", "--rows", "3"])

    with pytest.raises(SystemExit) as exc_info:
        _smoke_mod.main()

    assert exc_info.value.code == 1


def test_rows_zero_rejected_by_argparse(monkeypatch, capsys):
    """--rows 0 must exit with a non-zero code before fixture creation or CLI invocation."""
    monkeypatch.setattr(_smoke_mod, "_check_chroma", lambda: None)
    monkeypatch.setattr(sys, "argv", ["smoke", "--rows", "0"])

    with pytest.raises(SystemExit) as exc_info:
        _smoke_mod.main()

    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert "0" in captured.err or "positive" in captured.err.lower()


# ── Deterministic embedder ─────────────────────────────────────────────────────


def test_det_embed_is_deterministic():
    """_det_embed returns identical vectors on repeated calls for the same text."""
    text = "hello world smoke test"
    v1 = _smoke_mod._det_embed(text)
    v2 = _smoke_mod._det_embed(text)
    assert v1 == v2, "embedding must be deterministic"


def test_det_embed_dimension():
    """_det_embed output length must equal _EMBED_DIM (384)."""
    v = _smoke_mod._det_embed("some text")
    assert len(v) == _smoke_mod._EMBED_DIM


def test_det_embed_different_texts_differ():
    """Two distinct texts should not produce identical vectors."""
    v1 = _smoke_mod._det_embed("apple pie for dessert")
    v2 = _smoke_mod._det_embed("vector database migration")
    assert v1 != v2, "different texts should produce different embeddings"


# ── Count-line parser ─────────────────────────────────────────────────────────


def test_parse_counts_happy_path():
    """_parse_counts extracts (src, dst) from the standard CLI output line."""
    line = "Source drawers: 3  Destination drawers: 5\n"
    result = _smoke_mod._parse_counts(line)
    assert result == (3, 5)


def test_parse_counts_single_values():
    """_parse_counts handles single-digit boundary values correctly."""
    line = "Migration complete: 1 drawers migrated.\nSource drawers: 1  Destination drawers: 1"
    result = _smoke_mod._parse_counts(line)
    assert result == (1, 1)


def test_parse_counts_returns_none_on_missing_line():
    """_parse_counts returns None when the count line is absent from the output."""
    output = "Migration complete: 3 drawers migrated.\n"
    result = _smoke_mod._parse_counts(output)
    assert result is None


def test_parse_counts_returns_none_on_empty_string():
    """_parse_counts returns None for empty output."""
    assert _smoke_mod._parse_counts("") is None


# ── Chroma-gated fixture-generation test ─────────────────────────────────────


@pytest.mark.skipif(
    importlib.util.find_spec("chromadb") is None,
    reason="requires mempalace-code[chroma]",
)
def test_seed_chroma_source_creates_n_rows(tmp_path):
    """_seed_chroma_source creates exactly N rows in the ChromaDB collection."""
    import chromadb

    src_path = str(tmp_path / "chroma_src")
    _smoke_mod._seed_chroma_source(src_path, 3)

    client = chromadb.PersistentClient(path=src_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() == 3


@pytest.mark.skipif(
    importlib.util.find_spec("chromadb") is None,
    reason="requires mempalace-code[chroma]",
)
def test_seed_chroma_source_single_row(tmp_path):
    """_seed_chroma_source with n_rows=1 creates exactly 1 row (boundary)."""
    import chromadb

    src_path = str(tmp_path / "chroma_src_single")
    _smoke_mod._seed_chroma_source(src_path, 1)

    client = chromadb.PersistentClient(path=src_path)
    col = client.get_collection("mempalace_drawers")
    assert col.count() == 1


@pytest.mark.skipif(
    importlib.util.find_spec("chromadb") is None,
    reason="requires mempalace-code[chroma]",
)
def test_seed_chroma_source_row_contains_marker(tmp_path):
    """Each seeded row document starts with MARKER_PREFIX."""
    import chromadb

    src_path = str(tmp_path / "chroma_src_marker")
    _smoke_mod._seed_chroma_source(src_path, 2)

    client = chromadb.PersistentClient(path=src_path)
    col = client.get_collection("mempalace_drawers")
    result = col.get(include=cast("Any", ["documents"]))
    documents = cast("list[str]", result["documents"] or [])
    for doc in documents:
        assert doc.startswith(_smoke_mod.MARKER_PREFIX), (
            f"document does not start with marker: {doc!r}"
        )


# ── Subprocess wrapper ────────────────────────────────────────────────────────


def test_run_cli_sets_version_check_env():
    """_run_cli passes MEMPALACE_VERSION_CHECK=0 to suppress update prompts."""
    captured_env: dict = {}

    def fake_run(cmd, capture_output, text, env):
        captured_env.update(env)
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        _smoke_mod._run_cli(["--help"])

    assert captured_env.get("MEMPALACE_VERSION_CHECK") == "0"


# ── Cleanup semantics ─────────────────────────────────────────────────────────


def test_main_removes_temp_dir_on_exit(tmp_path, monkeypatch):
    """main() removes the TemporaryDirectory work area even when the smoke exits 0."""
    created_dirs: list[str] = []

    class _FakeTmpDir:
        def __init__(self, **kwargs):
            import tempfile

            self._d = tempfile.mkdtemp(dir=tmp_path)
            created_dirs.append(self._d)

        def __enter__(self):
            return self._d

        def __exit__(self, *args):
            import shutil

            shutil.rmtree(self._d, ignore_errors=True)

    monkeypatch.setattr("tempfile.TemporaryDirectory", _FakeTmpDir)

    monkeypatch.setattr(_smoke_mod, "_check_chroma", lambda: None)
    # smoke function itself is no-op
    monkeypatch.setattr(_smoke_mod, "smoke_happy_path", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["smoke", "--rows", "1"])

    _smoke_mod.main()

    import os

    for d in created_dirs:
        assert not os.path.exists(d), f"temp dir was not cleaned up: {d}"
