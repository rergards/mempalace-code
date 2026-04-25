"""
test_chroma_compat.py — Smoke tests for the legacy ChromaDB backend.

These tests are automatically skipped when chromadb is not installed (the
[chroma] extra is absent). They cover only operations that require no
embedding computation and therefore no network access:

    - import
    - instantiation (PersistentClient + get_or_create_collection)
    - count() on an empty store
    - delete_wing() on an empty store
    - count_by()/count_by_pair() metadata fallbacks
"""

import pytest

chromadb = pytest.importorskip("chromadb")  # skip entire module if not installed


def _seed_store(store, rows):
    store._col.add(
        ids=[row["id"] for row in rows],
        documents=[row["document"] for row in rows],
        metadatas=[row["metadata"] for row in rows],
        embeddings=[[float(index)] * 3 for index, _row in enumerate(rows, start=1)],
    )


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


def test_chroma_store_count_by_empty(tmp_path):
    """count_by/count_by_pair on a fresh empty store return empty mappings."""
    from mempalace._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    assert store.count_by("wing") == {}
    assert store.count_by_pair("wing", "room") == {}


def test_chroma_store_count_by_metadata_fallback(tmp_path):
    """count_by aggregates requested metadata keys from legacy Chroma rows."""
    from mempalace._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    _seed_store(
        store,
        [
            {"id": "1", "document": "alpha", "metadata": {"wing": "code", "room": "storage"}},
            {"id": "2", "document": "bravo", "metadata": {"wing": "code", "room": "storage"}},
            {"id": "3", "document": "charlie", "metadata": {"wing": "docs", "room": "plans"}},
        ],
    )

    assert store.count_by("wing") == {"code": 2, "docs": 1}


def test_chroma_store_count_by_pair_metadata_fallback(tmp_path):
    """count_by_pair aggregates the full wing-to-room taxonomy."""
    from mempalace._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    _seed_store(
        store,
        [
            {"id": "1", "document": "alpha", "metadata": {"wing": "code", "room": "storage"}},
            {"id": "2", "document": "bravo", "metadata": {"wing": "code", "room": "storage"}},
            {"id": "3", "document": "charlie", "metadata": {"wing": "code", "room": "search"}},
            {"id": "4", "document": "delta", "metadata": {"wing": "docs", "room": "plans"}},
        ],
    )

    assert store.count_by_pair("wing", "room") == {
        "code": {"storage": 2, "search": 1},
        "docs": {"plans": 1},
    }


def test_chroma_store_count_helpers_skip_missing_metadata_keys(tmp_path):
    """Records missing requested metadata keys are ignored, not fatal."""
    from mempalace._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    _seed_store(
        store,
        [
            {"id": "1", "document": "alpha", "metadata": {"wing": "code", "room": "storage"}},
            {"id": "2", "document": "bravo", "metadata": {"wing": "code"}},
            {"id": "3", "document": "charlie", "metadata": {"room": "plans"}},
            {"id": "4", "document": "delta", "metadata": {"wing": "docs", "room": "plans"}},
        ],
    )

    assert store.count_by("wing") == {"code": 2, "docs": 1}
    assert store.count_by_pair("wing", "room") == {
        "code": {"storage": 1},
        "docs": {"plans": 1},
    }
