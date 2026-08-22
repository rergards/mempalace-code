"""
_chroma_store.py — private ChromaDB migration adapter
=====================================================

This module is only importable when the Chroma migration extra is installed::

    pip install 'mempalace-code[chroma-migration]'

Importing this file without chromadb present raises ``ImportError`` immediately
(top-level ``import chromadb`` ensures a clean migration-dependency boundary).

Internal module — used by ``mempalace_code.migrate`` for the one-way
ChromaDB-to-LanceDB bridge. It is not a supported runtime storage backend.
"""

from __future__ import annotations

from typing import Any, Dict

import chromadb  # type: ignore[import-untyped]  # reason: top-level import; fails fast with ImportError if [chroma-migration] extra not installed

from .storage import DrawerStore


class ChromaStore(DrawerStore):
    """
    Legacy ChromaDB-backed reader used only by migrate-storage.

    WARNING: ChromaDB PersistentClient uses HNSW with no WAL.
    An interrupted write can corrupt the entire collection.
    """

    def __init__(
        self, palace_path: str, collection_name: str = "mempalace_drawers", create: bool = True
    ):
        self._client = chromadb.PersistentClient(
            path=palace_path,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
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
        if self._col is None:
            raise RuntimeError("ChromaDB collection not initialized")
        self._col.add(ids=ids, documents=documents, metadatas=metadatas)  # type: ignore[reportArgumentType]  # reason: chromadb stubs use OneOrMany[Metadata]; List[Dict[str,Any]] is runtime-compatible

    def upsert(self, ids, documents, metadatas):
        raise NotImplementedError("ChromaStore is a migration-only adapter; upsert is retired")

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        if self._col is None:
            raise RuntimeError("ChromaDB collection not initialized")
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
        raise NotImplementedError("ChromaStore is a migration-only adapter; query is retired")

    def delete(self, ids):
        if self._col is None:
            raise RuntimeError("ChromaDB collection not initialized")
        self._col.delete(ids=ids)

    def delete_wing(self, wing: str) -> int:
        raise NotImplementedError("ChromaStore is a migration-only adapter; delete_wing is retired")

    def count_by(self, column: str) -> Dict[str, int]:
        raise NotImplementedError("ChromaStore is a migration-only adapter; count_by is retired")

    def count_by_pair(self, col_a: str, col_b: str) -> Dict[str, Dict[str, int]]:
        raise NotImplementedError(
            "ChromaStore is a migration-only adapter; count_by_pair is retired"
        )
