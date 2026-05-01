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
    """storage.ChromaStore raises ImportError mentioning mempalace-code[chroma] when chromadb absent.

    Also verifies the original ImportError is preserved as __cause__ (raise ... from exc),
    so debuggers can see why the lazy import actually failed.
    """
    with unittest.mock.patch.dict(sys.modules, {"chromadb": None}):
        sys.modules.pop("mempalace_code._chroma_store", None)
        import mempalace_code.storage as storage_mod

        with pytest.raises(ImportError, match=r"mempalace-code\[chroma\]") as exc_info:
            _ = storage_mod.ChromaStore

        assert isinstance(exc_info.value.__cause__, ImportError)


def test_open_store_chroma_import_error(tmp_path):
    """open_store(..., backend='chroma') raises ImportError mentioning mempalace-code[chroma].

    Also verifies the original ImportError is preserved as __cause__ (raise ... from exc).
    """
    with unittest.mock.patch.dict(sys.modules, {"chromadb": None}):
        sys.modules.pop("mempalace_code._chroma_store", None)
        from mempalace_code.storage import open_store

        with pytest.raises(ImportError, match=r"mempalace-code\[chroma\]") as exc_info:
            open_store(str(tmp_path), backend="chroma")

        assert isinstance(exc_info.value.__cause__, ImportError)
