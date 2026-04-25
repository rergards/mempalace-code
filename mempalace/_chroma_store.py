"""
_chroma_store.py — ChromaDB storage backend (legacy, optional)
==============================================================

This module is only importable when the [chroma] extra is installed::

    pip install 'mempalace[chroma]'

Importing this file without chromadb present raises ``ImportError`` immediately
(top-level ``import chromadb`` ensures a clean failure surface).

Internal module — use ``mempalace.storage.open_store(..., backend="chroma")`` or
``from mempalace.storage import ChromaStore`` from external code.
"""

from __future__ import annotations

import chromadb  # top-level import: fails fast with ImportError if [chroma] extra not installed

from typing import Any, Dict

from .storage import DrawerStore


class ChromaStore(DrawerStore):
    """
    Legacy ChromaDB-backed storage. Kept for migration and compatibility.

    WARNING: ChromaDB PersistentClient uses HNSW with no WAL.
    An interrupted write can corrupt the entire collection.
    """

    def __init__(
        self, palace_path: str, collection_name: str = "mempalace_drawers", create: bool = True
    ):
        self._client = chromadb.PersistentClient(path=palace_path)
        if create:
            self._col = self._client.get_or_create_collection(collection_name)
        else:
            try:
                self._col = self._client.get_collection(collection_name)
            except Exception:
                self._col = None

    def count(self) -> int:
        if self._col is None:
            return 0
        return self._col.count()

    def add(self, ids, documents, metadatas):
        self._col.add(ids=ids, documents=documents, metadatas=metadatas)

    def upsert(self, ids, documents, metadatas):
        self._col.upsert(ids=ids, documents=documents, metadatas=metadatas)

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        kwargs: Dict[str, Any] = {}
        if ids is not None:
            kwargs["ids"] = ids
        if where:
            kwargs["where"] = where
        if include:
            kwargs["include"] = include
        kwargs["limit"] = limit
        if offset > 0:
            kwargs["offset"] = offset
        return self._col.get(**kwargs)

    def query(self, query_texts, n_results=5, where=None, include=None):
        kwargs: Dict[str, Any] = {
            "query_texts": query_texts,
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        if include:
            kwargs["include"] = include
        return self._col.query(**kwargs)

    def delete(self, ids):
        self._col.delete(ids=ids)

    def delete_wing(self, wing: str) -> int:
        if self._col is None:
            return 0
        results = self.get(where={"wing": wing})
        ids = results.get("ids", [])
        if not ids:
            return 0
        self._col.delete(ids=ids)
        return len(ids)

    def count_by(self, column: str) -> Dict[str, int]:
        total = self.count()
        if total == 0:
            return {}

        # Deprecated backend stop-gap: ChromaDB has no cheap metadata group-by,
        # so MCP status/taxonomy calls fall back to iterating metadata rows.
        results = self.get(include=["metadatas"], limit=total)
        counts: Dict[str, int] = {}
        for metadata in results.get("metadatas", []):
            if not metadata or column not in metadata:
                continue
            value = metadata[column]
            counts[value] = counts.get(value, 0) + 1
        return counts

    def count_by_pair(self, col_a: str, col_b: str) -> Dict[str, Dict[str, int]]:
        total = self.count()
        if total == 0:
            return {}

        # Deprecated backend stop-gap: ChromaDB has no cheap metadata group-by,
        # so MCP status/taxonomy calls fall back to iterating metadata rows.
        results = self.get(include=["metadatas"], limit=total)
        counts: Dict[str, Dict[str, int]] = {}
        for metadata in results.get("metadatas", []):
            if not metadata or col_a not in metadata or col_b not in metadata:
                continue
            value_a = metadata[col_a]
            value_b = metadata[col_b]
            nested = counts.setdefault(value_a, {})
            nested[value_b] = nested.get(value_b, 0) + 1
        return counts
