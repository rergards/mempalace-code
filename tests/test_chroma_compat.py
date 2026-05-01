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
    - lifecycle: add → query → get → delete → count (via deterministic offline EF)
    - missing-id safety: get and delete on absent ids do not raise
"""

import hashlib

import pytest

chromadb = pytest.importorskip("chromadb")  # skip entire module if not installed


class _DeterministicEF:
    """Offline embedding function for tests — no model downloads, fully deterministic.

    Chroma 1.x Collection._embed calls __call__(input=...) for documents and
    embed_query(input=...) for query texts, so both must be implemented.
    """

    DIM = 8

    def __call__(self, input):  # noqa: A002
        result = []
        for s in input:
            h = int(hashlib.md5(s.encode()).hexdigest(), 16)
            result.append([(h >> (i * 4) & 0xF) / 15.0 for i in range(self.DIM)])
        return result

    def embed_query(self, input):  # noqa: A002
        # Chroma 1.x _embed passes query_texts already wrapped: [["text"]] not "text"
        flat = input[0] if input and isinstance(input[0], list) else input
        return self.__call__(flat)


def _make_store_with_ef(tmp_path):
    """Return a ChromaStore whose collection uses the deterministic offline EF.

    Patches _col._embedding_function directly so Chroma 1.x's _embed() dispatches
    to our class instead of DefaultEmbeddingFunction (which downloads a model).
    """
    from mempalace_code._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    store._col._embedding_function = _DeterministicEF()
    return store


def _seed_store(store, rows):
    store._col.add(
        ids=[row["id"] for row in rows],
        documents=[row["document"] for row in rows],
        metadatas=[row["metadata"] for row in rows],
        embeddings=[[float(index)] * 3 for index, _row in enumerate(rows, start=1)],
    )


def test_chroma_store_importable():
    """ChromaStore can be imported from the internal module."""
    from mempalace_code._chroma_store import ChromaStore  # noqa: F401


def test_chroma_store_instantiation(tmp_path):
    """ChromaStore can be instantiated; exercises PersistentClient + get_or_create_collection."""
    from mempalace_code._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    assert store._col is not None


def test_chroma_store_count_empty(tmp_path):
    """count() on a fresh empty store returns 0."""
    from mempalace_code._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    assert store.count() == 0


def test_chroma_store_delete_wing_empty(tmp_path):
    """delete_wing() on an empty store returns 0 without raising."""
    from mempalace_code._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    deleted = store.delete_wing("nonexistent-wing")
    assert deleted == 0


def test_chroma_store_count_by_empty(tmp_path):
    """count_by/count_by_pair on a fresh empty store return empty mappings."""
    from mempalace_code._chroma_store import ChromaStore

    store = ChromaStore(palace_path=str(tmp_path))
    assert store.count_by("wing") == {}
    assert store.count_by_pair("wing", "room") == {}


def test_chroma_store_count_by_metadata_fallback(tmp_path):
    """count_by aggregates requested metadata keys from legacy Chroma rows."""
    from mempalace_code._chroma_store import ChromaStore

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
    from mempalace_code._chroma_store import ChromaStore

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
    from mempalace_code._chroma_store import ChromaStore

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


# ---------------------------------------------------------------------------
# Lifecycle tests — require offline embedding function (no model downloads)
# ---------------------------------------------------------------------------


def test_chroma_store_lifecycle(tmp_path):
    """add → query → get → delete → count exercises all five ChromaStore wrapper ops."""
    store = _make_store_with_ef(tmp_path)

    # Three docs across two wings so the where filter has something to filter out.
    ids = ["d1", "d2", "d3"]
    docs = [
        "LanceDB is the default storage backend.",
        "ChromaDB is the legacy backend.",
        "Unrelated content in another wing.",
    ]
    metas = [
        {"wing": "mempalace", "room": "storage"},
        {"wing": "mempalace", "room": "storage"},
        {"wing": "other", "room": "misc"},
    ]

    store.add(ids=ids, documents=docs, metadatas=metas)
    assert store.count() == 3

    # query with where: must drop the other-wing doc, proving the filter is
    # forwarded through the wrapper rather than silently swallowed.
    results = store.query(
        query_texts=["vector storage backend"],
        n_results=5,
        where={"wing": "mempalace"},
    )
    assert sorted(results["ids"][0]) == ["d1", "d2"]

    # get by id — verify id and document content roundtrip
    fetched = store.get(ids=["d1"])
    assert fetched["ids"] == ["d1"]
    assert fetched["documents"] == [docs[0]]

    # delete — count drops AND the right id is gone (not a sibling).
    store.delete(ids=["d1"])
    assert store.count() == 2
    remaining = store.get()
    assert sorted(remaining["ids"]) == ["d2", "d3"]


def test_chroma_store_missing_ids(tmp_path):
    """get and delete on absent ids are safe and leave count at 0."""
    store = _make_store_with_ef(tmp_path)

    fetched = store.get(ids=["nonexistent-id"])
    assert fetched["ids"] == []

    store.delete(ids=["nonexistent-id"])  # must not raise
    assert store.count() == 0
