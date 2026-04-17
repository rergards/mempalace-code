"""
test_chroma_compat.py — Smoke tests for the legacy ChromaDB backend.

These tests are automatically skipped when chromadb is not installed (the
[chroma] extra is absent). They cover only operations that require no
embedding computation and therefore no network access:

    - import
    - instantiation (PersistentClient + get_or_create_collection)
    - count() on an empty store
    - delete_wing() on an empty store
"""

import pytest

chromadb = pytest.importorskip("chromadb")  # skip entire module if not installed


def test_chroma_store_importable():
    """ChromaStore can be imported from the internal module."""
    from mempalace._chroma_store import ChromaStore  # noqa: F401


def test_chroma_store_instantiation(tmp_path):
    """ChromaStore can be instantiated; exercises PersistentClient + get_or_create_collection."""
    from mempalace._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    assert store._col is not None


def test_chroma_store_count_empty(tmp_path):
    """count() on a fresh empty store returns 0."""
    from mempalace._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    assert store.count() == 0


def test_chroma_store_delete_wing_empty(tmp_path):
    """delete_wing() on an empty store returns 0 without raising."""
    from mempalace._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    deleted = store.delete_wing("nonexistent-wing")
    assert deleted == 0
