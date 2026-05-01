"""
test_chroma_import_errors.py — Tests for ChromaStore ImportError paths when chromadb is absent.

Uses unittest.mock.patch.dict to hide chromadb from sys.modules so these tests run regardless
of whether the [chroma] extra is installed in the developer's environment.
"""

from __future__ import annotations

import sys
import unittest.mock

import pytest


def test_storage_chroma_store_import_error():
    """storage.ChromaStore raises ImportError mentioning mempalace[chroma] when chromadb absent."""
    with unittest.mock.patch.dict(sys.modules, {"chromadb": None}):
        sys.modules.pop("mempalace._chroma_store", None)
        import mempalace.storage as storage_mod

        with pytest.raises(ImportError, match="mempalace\\[chroma\\]"):
            _ = storage_mod.ChromaStore


def test_open_store_chroma_import_error(tmp_path):
    """open_store(..., backend='chroma') raises ImportError mentioning mempalace[chroma] when chromadb absent."""
    with unittest.mock.patch.dict(sys.modules, {"chromadb": None}):
        sys.modules.pop("mempalace._chroma_store", None)
        from mempalace.storage import open_store

        with pytest.raises(ImportError, match="mempalace\\[chroma\\]"):
            open_store(str(tmp_path), backend="chroma")


def test_storage_chroma_store_import_error_message_detail():
    """ImportError message from storage.ChromaStore includes pip install hint."""
    with unittest.mock.patch.dict(sys.modules, {"chromadb": None}):
        sys.modules.pop("mempalace._chroma_store", None)
        import mempalace.storage as storage_mod

        with pytest.raises(ImportError) as exc_info:
            _ = storage_mod.ChromaStore

        assert "mempalace[chroma]" in str(exc_info.value)


def test_open_store_chroma_import_error_message_detail(tmp_path):
    """ImportError message from open_store chroma backend includes pip install hint."""
    with unittest.mock.patch.dict(sys.modules, {"chromadb": None}):
        sys.modules.pop("mempalace._chroma_store", None)
        from mempalace.storage import open_store

        with pytest.raises(ImportError) as exc_info:
            open_store(str(tmp_path), backend="chroma")

        assert "mempalace[chroma]" in str(exc_info.value)
