"""Tests for retired ChromaDB runtime errors."""

from __future__ import annotations

import sys

import pytest


def _clear_chroma_modules() -> None:
    sys.modules.pop("chromadb", None)
    sys.modules.pop("mempalace_code._chroma_store", None)
    sys.modules.pop("mempalace_code.legacy_optional.chroma", None)


def _assert_runtime_retired_message(message: str) -> None:
    assert "ChromaDB runtime storage has been retired" in message
    assert "mempalace-code migrate-storage SRC DST --verify" in message
    assert "source backup by default" in message
    assert "mempalace-code[chroma-migration]" in message


def test_storage_chroma_store_runtime_retired_error(tmp_path):
    """storage.ChromaStore is a failure stub and does not import the migration bridge."""
    _clear_chroma_modules()
    import mempalace_code.storage as storage_mod

    with pytest.raises(storage_mod.ChromaRuntimeRetiredError) as exc_info:
        storage_mod.ChromaStore(str(tmp_path))

    _assert_runtime_retired_message(str(exc_info.value))
    assert "chromadb" not in sys.modules
    assert "mempalace_code._chroma_store" not in sys.modules
    assert "mempalace_code.legacy_optional.chroma" not in sys.modules


def test_open_store_chroma_runtime_retired_error(tmp_path):
    """open_store(..., backend='chroma') fails before creating the requested path."""
    _clear_chroma_modules()
    from mempalace_code.storage import ChromaRuntimeRetiredError, open_store

    missing_path = tmp_path / "new-palace"
    with pytest.raises(ChromaRuntimeRetiredError) as exc_info:
        open_store(str(missing_path), backend="chroma")

    _assert_runtime_retired_message(str(exc_info.value))
    assert not missing_path.exists()
    assert "chromadb" not in sys.modules
    assert "mempalace_code._chroma_store" not in sys.modules


def test_open_store_chroma_only_auto_detect_runtime_retired_error(tmp_path):
    """A Chroma-only marker cannot be opened implicitly as runtime storage."""
    _clear_chroma_modules()
    from mempalace_code.storage import ChromaRuntimeRetiredError, open_store

    marker = tmp_path / "chroma.sqlite3"
    marker.touch()
    with pytest.raises(ChromaRuntimeRetiredError) as exc_info:
        open_store(str(tmp_path))

    _assert_runtime_retired_message(str(exc_info.value))
    assert marker.exists()
    assert not (tmp_path / "lance").exists()
    assert "chromadb" not in sys.modules
