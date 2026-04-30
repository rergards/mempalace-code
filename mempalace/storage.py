"""
storage.py — Pluggable storage backend for MemPalace
=====================================================

Provides a unified interface for drawer storage, abstracting away
the underlying vector database. Ships with LanceDB (default, crash-safe)
and ChromaDB (legacy, optional) backends.

Usage:
    from mempalace.storage import open_store

    store = open_store("/path/to/palace")          # auto-detect or create LanceDB
    store = open_store("/path/to/palace", "lance")  # explicit backend
    store = open_store("/path/to/palace", "chroma") # legacy ChromaDB (requires [chroma] extra)

The store object exposes a collection-like API that all MemPalace code
uses instead of calling ChromaDB/LanceDB directly.

ChromaStore is defined in ``mempalace._chroma_store`` and only importable
when the ``[chroma]`` extra is installed. For backwards compatibility,
``from mempalace.storage import ChromaStore`` also works when chromadb is
present (raises ImportError with a helpful message when it is not).
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mempalace")


def _prune_pre_optimize_backups(backup_dir: str, retain_count: int) -> None:
    """Best-effort pruning for pre-optimize archives only."""
    if retain_count <= 0:
        return

    candidates = []
    for path in Path(backup_dir).glob("pre_optimize_*.tar.gz"):
        if not path.is_file():
            continue
        try:
            candidates.append((path.stat().st_mtime, path.name, path))
        except OSError as e:
            logger.warning("Pre-optimize backup pruning failed for %s: %s", path, e)
    candidates.sort(reverse=True)

    for _, _, archive in candidates[retain_count:]:
        try:
            archive.unlink()
        except OSError as e:
            logger.warning("Pre-optimize backup pruning failed for %s: %s", archive, e)


# ─── Abstract interface ────────────────────────────────────────────────────────


class DrawerStore(ABC):
    """Minimal interface that every storage backend must implement."""

    @abstractmethod
    def count(self) -> int:
        """Total number of drawers."""

    @abstractmethod
    def add(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Insert new drawers. Raises on duplicate IDs."""

    @abstractmethod
    def upsert(
        self,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Insert or update drawers."""

    @abstractmethod
    def get(
        self,
        ids: Optional[List[str]] = None,
        where: Optional[Dict[str, Any]] = None,
        include: Optional[List[str]] = None,
        limit: int = 10000,
        offset: int = 0,
    ) -> Dict[str, List]:
        """
        Retrieve drawers by ID or metadata filter.

        Returns dict with keys: ids, documents, metadatas
        (each key present only if requested via `include` or always for ids).
        """

    @abstractmethod
    def query(
        self,
        query_texts: List[str],
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        include: Optional[List[str]] = None,
    ) -> Dict[str, List[List]]:
        """
        Semantic search. Returns nested lists (one per query text):
          ids: [[id, ...]]
          documents: [[doc, ...]]
          metadatas: [[meta, ...]]
          distances: [[dist, ...]]
        """

    @abstractmethod
    def delete(self, ids: List[str]) -> None:
        """Delete drawers by ID."""

    @abstractmethod
    def delete_wing(self, wing: str) -> int:
        """Delete all drawers in a wing. Returns the count of deleted drawers."""

    @abstractmethod
    def count_by(self, column: str) -> Dict[str, int]:
        """Return {value: count} for every distinct value in *column*."""

    @abstractmethod
    def count_by_pair(self, col_a: str, col_b: str) -> Dict[str, Dict[str, int]]:
        """Return {a_value: {b_value: count}} for every (col_a, col_b) pair."""

    def get_source_files(self, wing: str) -> Optional[set]:
        """Return a set of all source_file values for a wing, or None if unsupported.

        Returning None signals the caller to fall back to per-file file_already_mined()
        checks. The base implementation returns None — override in backends that support
        efficient bulk retrieval (LanceDB).
        """
        return None

    def delete_by_source_file(self, source_file: str, wing: str) -> int:
        """Delete all drawers for a given source_file within a wing. Returns deleted count."""
        return 0

    def get_source_file_hashes(self, wing: str) -> dict:
        """Return {source_file: source_hash} for all drawers in wing.

        Returns an empty dict if unsupported. Override in LanceDB backend.
        """
        return {}

    def iter_all(self, where=None, batch_size=1000, include_vectors=False):
        """Yield batches of drawers as lists of dicts. Streams without loading full table.

        Each batch is a list of dicts with keys: id, text, and all metadata fields.
        If include_vectors is True, a 'vector' key with the float list is also present.
        """
        raise NotImplementedError

    def optimize(self) -> None:
        """Merge Lance fragments and prune old versions. No-op on unsupported backends."""

    def warmup(self) -> None:
        """Force embedding model init so HuggingFace output appears before batch processing."""


# ─── LanceDB backend ──────────────────────────────────────────────────────────

_LANCE_TABLE = "mempalace_drawers"
DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"  # same model ChromaDB uses by default

# Single source of truth for metadata fields.
# Adding a new metadata column? Append ONE tuple here.
# Format: (field_name, arrow_type_tag, default_value)
# arrow_type_tag: "string" | "int32" | "float32"
_META_FIELD_SPEC: tuple = (
    # Core metadata
    ("wing", "string", ""),
    ("room", "string", ""),
    ("source_file", "string", ""),
    ("chunk_index", "int32", 0),
    ("added_by", "string", ""),
    ("filed_at", "string", ""),
    # Diary/graph fields
    ("hall", "string", ""),
    ("topic", "string", ""),
    ("type", "string", ""),
    ("agent", "string", ""),
    ("date", "string", ""),
    # Convo mining
    ("ingest_mode", "string", ""),
    ("extract_mode", "string", ""),
    # Compression
    ("compression_ratio", "float32", 0.0),
    ("original_tokens", "int32", 0),
    # Language detection
    ("language", "string", ""),
    # Symbol metadata
    ("symbol_name", "string", ""),
    ("symbol_type", "string", ""),
    # Markdown / prose section metadata
    ("heading", "string", ""),
    ("heading_level", "int32", 0),
    ("heading_path", "string", ""),
    ("doc_section_type", "string", ""),
    ("contains_mermaid", "int32", 0),
    ("contains_code", "int32", 0),
    ("contains_table", "int32", 0),
    # Provenance (CODE-INCREMENTAL)
    ("source_hash", "string", ""),
    ("extractor_version", "string", ""),
    ("chunker_strategy", "string", ""),
)

_META_KEYS: frozenset = frozenset(name for name, _, _ in _META_FIELD_SPEC)
_META_DEFAULTS: dict = {name: default for name, _, default in _META_FIELD_SPEC}


def _target_drawer_schema(dim: int):
    """Return the canonical PyArrow schema for the drawers table.

    Single source of truth — used by both the create-table and migrate-existing paths in
    ``LanceStore._open_or_create()``.  Any new column additions must be made here only.
    """
    import pyarrow as pa

    _ARROW_TYPES = {"string": pa.string(), "int32": pa.int32(), "float32": pa.float32()}
    fields = [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ]
    for name, type_tag, _ in _META_FIELD_SPEC:
        fields.append(pa.field(name, _ARROW_TYPES[type_tag]))
    return pa.schema(fields)


def _sql_default_for_arrow_type(arrow_type) -> str:
    """Map a PyArrow scalar type to its SQL literal default for ``add_columns()``.

    Raises ``RuntimeError`` for unsupported types.  In particular, ``pa.list_(...)``
    (the vector column type) is not supported — the vector column must already exist in
    the base schema; if it is missing the table is corrupt or unsupported.
    """
    import pyarrow as pa

    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "CAST('' AS string)"
    if pa.types.is_int32(arrow_type):
        return "0"
    if pa.types.is_int64(arrow_type):
        return "0"
    if pa.types.is_float32(arrow_type):
        return "0.0"
    raise RuntimeError(
        f"No SQL default defined for Arrow type {arrow_type!r}. "
        "The vector column (list type) must already exist in the base schema — "
        "if it is missing the table is corrupt or unsupported."
    )


class LanceStore(DrawerStore):
    """
    Crash-safe drawer storage using LanceDB.

    Data is stored in Lance columnar format with proper transactions —
    an interrupted write does not corrupt the entire dataset.
    """

    def __init__(self, palace_path: str, create: bool = True, embed_model: Optional[str] = None):
        import logging

        import lancedb

        self._model_name = embed_model or DEFAULT_EMBED_MODEL
        self._db = lancedb.connect(os.path.join(palace_path, "lance"))

        # Suppress noisy HF/safetensors output (BertModel LOAD REPORT, tqdm bars,
        # unauthenticated-request warnings).  Must redirect at the OS fd level
        # because the noise comes from C/Rust code, not Python.
        hf_logger = logging.getLogger("huggingface_hub")
        prev_level = hf_logger.level
        hf_logger.setLevel(logging.ERROR)
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stdout = os.dup(1)
        old_stderr = os.dup(2)
        try:
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            self._embedder = self._get_embedder()
            self._table = self._open_or_create(create)
        finally:
            os.dup2(old_stdout, 1)
            os.dup2(old_stderr, 2)
            os.close(devnull)
            os.close(old_stdout)
            os.close(old_stderr)
            hf_logger.setLevel(prev_level)

    def _get_embedder(self):
        """Load the sentence-transformers embedding model."""
        from lancedb.embeddings import get_registry

        return get_registry().get("sentence-transformers").create(name=self._model_name)

    def _open_or_create(self, create: bool):
        """Open existing table or create a new one, migrating schema if needed."""
        dim = self._embedder.ndims()
        target = _target_drawer_schema(dim)

        # Try to open existing table first
        _existing_table = None
        try:
            _existing_table = self._db.open_table(_LANCE_TABLE)
        except Exception as e:
            logger.debug("Table %r not found, will create: %s", _LANCE_TABLE, e)

        if _existing_table is not None:
            existing_names = set(_existing_table.schema.names)
            missing_fields = [f for f in target if f.name not in existing_names]
            if missing_fields:
                cols_to_add = {f.name: _sql_default_for_arrow_type(f.type) for f in missing_fields}
                logger.info(
                    "Migrating palace schema: adding columns %s",
                    sorted(cols_to_add),
                )
                _existing_table.add_columns(cols_to_add)
                # Reload the handle so its schema reflects the updated on-disk table
                _existing_table = self._db.open_table(_LANCE_TABLE)
                reloaded_names = set(_existing_table.schema.names)
                if not set(target.names) <= reloaded_names:
                    still_missing = set(target.names) - reloaded_names
                    raise RuntimeError(
                        f"Post-migration assertion failed — still missing columns: {still_missing}"
                    )
            return _existing_table

        if not create:
            return None

        return self._db.create_table(_LANCE_TABLE, schema=target)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        return self._embedder.compute_source_embeddings(texts)

    @staticmethod
    def _meta_defaults(meta: Dict[str, Any]) -> Dict[str, Any]:
        """Fill in default values for metadata fields; drop unknown keys."""
        # Start with defaults, overlay known keys from meta, drop unknowns
        merged = dict(_META_DEFAULTS)
        for k, v in meta.items():
            if k in _META_DEFAULTS:
                merged[k] = v
        # Ensure numeric fields have correct types (derived from _META_FIELD_SPEC type_tags)
        for name, type_tag, _ in _META_FIELD_SPEC:
            if type_tag == "int32":
                merged[name] = int(merged[name])
            elif type_tag == "float32":
                merged[name] = float(merged[name])
        return merged

    def count(self) -> int:
        if self._table is None:
            return 0
        return self._table.count_rows()

    def add(self, ids, documents, metadatas):
        if self._table is None:
            raise RuntimeError("Table does not exist and create=False")

        vectors = self._embed(documents)
        rows = []
        for id_, doc, meta, vec in zip(ids, documents, metadatas, vectors):
            row = self._meta_defaults(meta)
            row["id"] = id_
            row["text"] = doc
            row["vector"] = vec
            rows.append(row)

        self._table.add(rows)

    def upsert(self, ids, documents, metadatas):
        # LanceDB merge_insert for upsert
        if self._table is None:
            raise RuntimeError("Table does not exist and create=False")

        vectors = self._embed(documents)
        rows = []
        for id_, doc, meta, vec in zip(ids, documents, metadatas, vectors):
            row = self._meta_defaults(meta)
            row["id"] = id_
            row["text"] = doc
            row["vector"] = vec
            rows.append(row)

        self._table.merge_insert(
            "id"
        ).when_matched_update_all().when_not_matched_insert_all().execute(rows)

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        if self._table is None:
            return {"ids": [], "documents": [], "metadatas": []}

        include = include or []

        if ids is not None:
            if not ids:
                return {"ids": [], "documents": [], "metadatas": []}
            # Fetch by explicit IDs
            id_list = ", ".join(f"'{id_}'" for id_ in ids)
            try:
                results = self._table.search().where(f"id IN ({id_list})").limit(len(ids)).to_list()
            except Exception:
                results = []
        elif where is not None:
            sql = self._where_to_sql(where)
            try:
                results = self._table.search().where(sql).limit(limit).offset(offset).to_list()
            except Exception:
                results = []
        else:
            try:
                results = self._table.search().limit(limit).offset(offset).to_list()
            except Exception:
                results = []

        out_ids = [r["id"] for r in results]
        out: Dict[str, List] = {"ids": out_ids}

        if "documents" in include:
            out["documents"] = [r["text"] for r in results]
        if "metadatas" in include:
            out["metadatas"] = [{k: r.get(k, "") for k in _META_KEYS} for r in results]

        return out

    def query(self, query_texts, n_results=5, where=None, include=None):
        if self._table is None:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        include = include or []
        all_ids, all_docs, all_metas, all_dists = [], [], [], []

        for text in query_texts:
            vec = self._embed([text])[0]
            q = self._table.search(vec).limit(n_results)
            if where:
                sql = self._where_to_sql(where)
                q = q.where(sql)

            try:
                results = q.to_list()
            except Exception:
                results = []

            ids = [r["id"] for r in results]
            docs = [r["text"] for r in results]
            metas = []
            dists = []

            for r in results:
                metas.append({k: r.get(k, "") for k in _META_KEYS})
                # LanceDB returns _distance (L2 distance)
                dists.append(r.get("_distance", 0.0))

            all_ids.append(ids)
            all_docs.append(docs)
            all_metas.append(metas)
            all_dists.append(dists)

        out: Dict[str, List[List]] = {"ids": all_ids}
        if "documents" in include:
            out["documents"] = all_docs
        if "metadatas" in include:
            out["metadatas"] = all_metas
        if "distances" in include:
            out["distances"] = all_dists

        return out

    def delete(self, ids):
        if self._table is None:
            return
        if not ids:
            return
        id_list = ", ".join(f"'{id_}'" for id_ in ids)
        self._table.delete(f"id IN ({id_list})")

    def delete_wing(self, wing: str) -> int:
        if self._table is None:
            return 0
        escaped = wing.replace("'", "''")
        count = self._table.count_rows(f"wing = '{escaped}'")
        if count == 0:
            return 0
        self._table.delete(f"wing = '{escaped}'")
        return count

    def delete_by_source_file(self, source_file: str, wing: str) -> int:
        """Delete all drawers for a given source_file within a wing."""
        if self._table is None:
            return 0
        escaped_file = source_file.replace("'", "''")
        escaped_wing = wing.replace("'", "''")
        count = self._table.count_rows(
            f"source_file = '{escaped_file}' AND wing = '{escaped_wing}'"
        )
        if count == 0:
            return 0
        self._table.delete(f"source_file = '{escaped_file}' AND wing = '{escaped_wing}'")
        return count

    def get_source_file_hashes(self, wing: str) -> dict:
        """Return {source_file: source_hash} for all drawers in wing.

        Uses LanceDB scan-time column projection — no vector scan.
        Deduplicates by taking the first hash per source_file.
        Returns an empty dict if the table is empty or column is absent.
        """
        if self._table is None:
            return {}
        import pyarrow.compute as pc

        try:
            arrow_tbl = self._scan_columns(["source_file", "source_hash", "wing"])
        except Exception:
            # Table predates migration (source_hash column missing) — return empty
            return {}
        filtered = arrow_tbl.filter(pc.field("wing") == wing)
        result: dict = {}
        for sf, sh in zip(
            filtered.column("source_file").to_pylist(),
            filtered.column("source_hash").to_pylist(),
        ):
            if sf not in result:
                result[sf] = sh
        return result

    def count_by(self, column: str) -> Dict[str, int]:
        if self._table is None:
            return {}
        arrow_tbl = self._scan_columns([column])
        result = arrow_tbl.group_by(column).aggregate([(column, "count")])
        d = result.to_pydict()
        return dict(zip(d[column], d[f"{column}_count"]))

    def count_by_pair(self, col_a: str, col_b: str) -> Dict[str, Dict[str, int]]:
        if self._table is None:
            return {}
        arrow_tbl = self._scan_columns([col_a, col_b])
        result = arrow_tbl.group_by([col_a, col_b]).aggregate([(col_b, "count")])
        d = result.to_pydict()
        out: Dict[str, Dict[str, int]] = {}
        for a, b, c in zip(d[col_a], d[col_b], d[f"{col_b}_count"]):
            out.setdefault(a, {})[b] = c
        return out

    def get_source_files(self, wing: str) -> Optional[set]:
        """Return the set of all source_file values already stored for *wing*.

        Uses LanceDB scan-time column projection and filter — no vector scan required.
        Returns an empty set if the table is empty or doesn't exist.
        """
        if self._table is None:
            return set()
        import pyarrow.compute as pc

        arrow_tbl = self._scan_columns(["source_file", "wing"])
        filtered = arrow_tbl.filter(pc.field("wing") == wing)
        return set(filtered.column("source_file").to_pylist())

    def _scan_columns(self, columns: List[str]):
        """Return an Arrow table from a LanceDB scan projected to *columns*."""
        if hasattr(self._table, "scanner"):
            return self._table.scanner(columns=columns).to_table()
        return self._table.search().select(columns).to_arrow()

    def iter_all(self, where=None, batch_size=1000, include_vectors=False):
        """Yield batches of drawers as lists of dicts using PyArrow column projection.

        Loads all non-vector columns via to_arrow() (no vector scan), applies an
        optional PyArrow-level filter, then yields one list of dicts per batch.
        """
        if self._table is None:
            return

        meta_columns = ["id", "text"] + [name for name, _, _ in _META_FIELD_SPEC]
        columns = meta_columns + (["vector"] if include_vectors else [])
        # Only include columns that actually exist in the schema
        existing = set(self._table.schema.names)
        columns = [c for c in columns if c in existing]

        try:
            arrow_tbl = self._table.to_arrow().select(columns)
        except Exception:
            return

        if where:
            mask = self._where_to_arrow_mask(arrow_tbl, where)
            if mask is not None:
                arrow_tbl = arrow_tbl.filter(mask)

        for batch in arrow_tbl.to_batches(max_chunksize=batch_size):
            rows = batch.to_pydict()
            n = len(rows["id"])
            result = []
            for i in range(n):
                row = {col: rows[col][i] for col in rows}
                result.append(row)
            yield result

    @staticmethod
    def _where_to_arrow_mask(arrow_tbl, where):
        """Recursively convert a where dict to a PyArrow boolean array for filtering.

        Mirrors _where_to_sql semantics but operates on an in-memory Arrow table.
        Supports $and, $or, $in, and simple {field: value} equality/comparison clauses.
        """
        import pyarrow as pa
        import pyarrow.compute as pc

        if "$and" in where:
            masks = [LanceStore._where_to_arrow_mask(arrow_tbl, sub) for sub in where["$and"]]
            masks = [m for m in masks if m is not None]
            if not masks:
                return None
            result = masks[0]
            for m in masks[1:]:
                result = pc.and_(result, m)
            return result

        if "$or" in where:
            masks = [LanceStore._where_to_arrow_mask(arrow_tbl, sub) for sub in where["$or"]]
            masks = [m for m in masks if m is not None]
            if not masks:
                return None
            result = masks[0]
            for m in masks[1:]:
                result = pc.or_(result, m)
            return result

        _OP_MAP = {
            "$eq": pc.equal,
            "$ne": pc.not_equal,
            "$gt": pc.greater,
            "$gte": pc.greater_equal,
            "$lt": pc.less,
            "$lte": pc.less_equal,
        }

        parts = []
        for key, value in where.items():
            if key not in arrow_tbl.schema.names:
                continue
            col = arrow_tbl.column(key)
            if isinstance(value, str):
                parts.append(pc.equal(col, value))
            elif isinstance(value, (int, float)):
                parts.append(pc.equal(col, value))
            elif isinstance(value, dict):
                for op, operand in value.items():
                    fn = _OP_MAP.get(op)
                    if fn is not None:
                        parts.append(fn(col, operand))
                    elif op == "$in":
                        parts.append(pc.is_in(col, value_set=pa.array(operand, type=col.type)))
        if not parts:
            return None
        result = parts[0]
        for p in parts[1:]:
            result = pc.and_(result, p)
        return result

    def optimize(self) -> None:
        """Merge Lance fragments and prune old versions (post-mining compaction)."""
        if self._table is not None:
            self._table.optimize()

    def safe_optimize(self, palace_path: str, backup_first: bool = False) -> bool:
        """Optimize with optional pre-backup and post-verification.

        Fail-closed contract: if backup_first=True and the backup fails, returns False
        without running optimize(). The table is never compacted when the backup gate fails.

        Args:
            palace_path: Path to palace directory (for backup).
            backup_first: Create backup before optimizing. If True and backup fails,
                          returns False without optimizing.

        Returns:
            True if optimize succeeded and table is readable, False otherwise.
        """
        if self._table is None:
            return True

        palace_path = palace_path.rstrip("/\\")

        # Pre-optimize backup (fail-closed gate)
        if backup_first:
            try:
                from .backup import create_backup

                backup_dir = os.path.join(os.path.dirname(palace_path), "backups")
                os.makedirs(backup_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = os.path.join(backup_dir, f"pre_optimize_{timestamp}.tar.gz")
                create_backup(palace_path, backup_path)
                logger.info("Pre-optimize backup: %s", backup_path)
            except Exception as e:
                logger.error("Pre-optimize backup failed — skipping optimize: %s", e)
                return False

        # Get row count before optimize
        pre_count = self._table.count_rows()

        # Run optimize — wrapped so any LanceDB exception returns False instead of propagating
        try:
            self._table.optimize()
        except Exception as e:
            logger.error("optimize() raised an exception: %s", e)
            return False

        # Verify table is still readable
        try:
            self._table.head(1).to_pydict()
            post_count = self._table.count_rows()
            if post_count != pre_count:
                logger.warning("Row count changed after optimize: %d -> %d", pre_count, post_count)
            if backup_first:
                from .config import MempalaceConfig

                backup_dir = os.path.join(os.path.dirname(palace_path), "backups")
                _prune_pre_optimize_backups(
                    backup_dir,
                    MempalaceConfig().backup_retain_count,
                )
            return True
        except Exception as e:
            logger.error("Table unreadable after optimize: %s", e)
            return False

    def health_check(self) -> dict:
        """Probe the store for fragment-missing or read errors.

        Runs three probes covering the failure surfaces from the 2026-04-16 incident:
          1. count_rows() — touches the manifest
          2. head(1).to_pydict() — touches at least one fragment's data
          3. projected ["wing","room"] group-by — touches every fragment's metadata

        Returns a structured report. Never raises — all exceptions are caught.

        Returns dict with keys:
          ok: bool — True if all probes passed
          total_rows: int — result of count_rows(), or 0 on failure
          current_version: int or None — current table version number
          errors: list of dicts with keys 'probe', 'kind', 'message'
        """
        if self._table is None:
            return {
                "ok": False,
                "total_rows": 0,
                "current_version": None,
                "errors": [
                    {
                        "probe": "table_open",
                        "kind": "read_failed",
                        "message": "Table is None (not opened)",
                    }
                ],
            }

        def _classify(e: Exception) -> str:
            msg = str(e).lower()
            if any(s in msg for s in ("no such file", "object not found", "io error", "not found")):
                return "fragment_missing"
            if "schema" in msg:
                return "schema_error"
            if any(s in msg for s in ("read", "decode", "parse")):
                return "read_failed"
            return "other"

        errors = []
        total_rows = 0
        current_version = None

        # Probe 1: count_rows — touches manifest
        try:
            total_rows = self._table.count_rows()
        except Exception as e:
            errors.append({"probe": "count_rows", "kind": _classify(e), "message": str(e)})

        # Probe 2: head(1) — touches at least one fragment's data
        try:
            self._table.head(1).to_pydict()
        except Exception as e:
            errors.append({"probe": "head", "kind": _classify(e), "message": str(e)})

        # Probe 3: column scan — touches every fragment's metadata (the silent-failure surface)
        try:
            arrow_tbl = self._scan_columns(["wing", "room"])
            arrow_tbl.group_by(["wing", "room"]).aggregate([("room", "count")])
        except Exception as e:
            errors.append({"probe": "count_by_pair", "kind": _classify(e), "message": str(e)})

        # Version info — best-effort; failures go into warnings, not errors, to avoid
        # false-positive DEGRADED status when data probes all pass.
        warnings = []
        try:
            versions = self._table.list_versions()
            if versions:
                current_version = versions[-1]["version"]
        except Exception as e:
            warnings.append({"probe": "list_versions", "kind": _classify(e), "message": str(e)})

        return {
            "ok": len(errors) == 0,
            "total_rows": total_rows,
            "current_version": current_version,
            "errors": errors,
            "warnings": warnings,
        }

    def recover_to_last_working_version(self, dry_run: bool = True) -> dict:
        """Find and optionally restore the most recent healthy table version.

        Walks list_versions() from newest to oldest (skipping current), probing each
        version. Returns a structured result.

        When dry_run=False and a candidate is found, calls table.restore(v) and
        re-opens the table handle so subsequent reads use the restored head.

        Exceptions from the version walk are caught per-version. Exceptions from the
        final restore() call propagate — a failed restore is a terminal condition.

        Returns dict with keys:
          recovered: bool
          candidate_version: int or None
          dry_run: bool
          restored_to: int (only when recovered=True and dry_run=False)
          rows_after: int (only when recovered=True and dry_run=False)
          checked_versions: list of int (versions that were probed)
          walk_errors: list of dicts (probe failures during version walk)
        """
        if self._table is None:
            return {
                "recovered": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "message": "Table is None (not opened)",
            }

        try:
            versions = self._table.list_versions()
        except Exception as e:
            return {
                "recovered": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "error": f"Could not list versions: {e}",
            }

        if len(versions) < 2:
            return {
                "recovered": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "message": "No prior versions to roll back to",
            }

        candidate_version = None
        checked_versions: list = []
        walk_errors: list = []

        try:
            # Walk from second-newest to oldest (skip current = versions[-1])
            for v in reversed(versions[:-1]):
                ver_num = v["version"]
                checked_versions.append(ver_num)
                try:
                    self._table.checkout(ver_num)
                    # Run all three probes
                    self._table.count_rows()
                    self._table.head(1).to_pydict()
                    arrow_tbl = self._scan_columns(["wing", "room"])
                    arrow_tbl.group_by(["wing", "room"]).aggregate([("room", "count")])
                    # All probes passed
                    candidate_version = ver_num
                    break
                except Exception as e:
                    walk_errors.append({"version": ver_num, "error": str(e)})
                    continue
        finally:
            # Always return to latest version — leaves handle unpinned after dry-run walk
            try:
                self._table.checkout_latest()
            except Exception:
                pass

        if candidate_version is None:
            return {
                "recovered": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "checked_versions": checked_versions,
                "walk_errors": walk_errors,
            }

        if dry_run:
            return {
                "recovered": False,
                "candidate_version": candidate_version,
                "dry_run": True,
                "checked_versions": checked_versions,
            }

        # Perform the restore — exceptions propagate (terminal condition)
        self._table.restore(candidate_version)
        self._table = self._db.open_table(_LANCE_TABLE)
        rows_after = self._table.count_rows()
        return {
            "recovered": True,
            "restored_to": candidate_version,
            "rows_after": rows_after,
            "dry_run": False,
        }

    def warmup(self) -> None:
        """Embed a throwaway string to force model loading before batch processing."""
        self._embed(["warmup"])

    @staticmethod
    def _where_to_sql(where: Dict[str, Any]) -> str:
        """
        Convert ChromaDB-style where filters to SQL WHERE clauses.

        Supports:
          {"wing": "foo"}                → wing = 'foo'
          {"$and": [{"wing": "a"}, {"room": "b"}]}  → (wing = 'a') AND (room = 'b')
          {"wing": {"$in": ["a", "b"]}}  → wing IN ('a', 'b')
          {"wing": {"$in": []}}          → 1 = 0
          {"wing": {"$in": ["a"]}}       → wing = 'a'  (single-element optimisation)
        """
        if "$and" in where:
            clauses = [LanceStore._where_to_sql(sub) for sub in where["$and"]]
            return " AND ".join(f"({c})" for c in clauses)
        if "$or" in where:
            clauses = [LanceStore._where_to_sql(sub) for sub in where["$or"]]
            return " OR ".join(f"({c})" for c in clauses)

        parts = []
        for key, value in where.items():
            if isinstance(value, str):
                escaped = value.replace("'", "''")
                parts.append(f"{key} = '{escaped}'")
            elif isinstance(value, (int, float)):
                parts.append(f"{key} = {value}")
            elif isinstance(value, dict):
                # Operator filters: {"field": {"$eq": val}} etc.
                for op, val in value.items():
                    if op == "$eq":
                        if isinstance(val, (int, float)):
                            parts.append(f"{key} = {val}")
                        else:
                            escaped = str(val).replace("'", "''")
                            parts.append(f"{key} = '{escaped}'")
                    elif op == "$ne":
                        if isinstance(val, (int, float)):
                            parts.append(f"{key} != {val}")
                        else:
                            escaped = str(val).replace("'", "''")
                            parts.append(f"{key} != '{escaped}'")
                    elif op in ("$gt", "$gte", "$lt", "$lte"):
                        sql_op = {"$gt": ">", "$gte": ">=", "$lt": "<", "$lte": "<="}[op]
                        parts.append(f"{key} {sql_op} {val}")
                    elif op == "$in":
                        if not val:
                            parts.append("1 = 0")
                        elif len(val) == 1:
                            # Single-element optimisation — reuse $eq escaping logic
                            v = val[0]
                            if isinstance(v, (int, float)):
                                parts.append(f"{key} = {v}")
                            else:
                                escaped = str(v).replace("'", "''")
                                parts.append(f"{key} = '{escaped}'")
                        else:
                            first = val[0]
                            if isinstance(first, str):
                                if not all(isinstance(v, str) for v in val):
                                    raise ValueError(
                                        f"$in list for '{key}' must be all str or all numeric, not mixed"
                                    )
                                items = ", ".join(
                                    f"'{str(v).replace(chr(39), chr(39) * 2)}'" for v in val
                                )
                            elif isinstance(first, (int, float)):
                                if not all(isinstance(v, (int, float)) for v in val):
                                    raise ValueError(
                                        f"$in list for '{key}' must be all str or all numeric, not mixed"
                                    )
                                items = ", ".join(str(v) for v in val)
                            else:
                                raise ValueError(
                                    f"$in list for '{key}' contains unsupported type: {type(first)}"
                                )
                            parts.append(f"{key} IN ({items})")
            else:
                parts.append(f"{key} = '{value}'")

        return " AND ".join(parts) if parts else "1=1"


# ─── Backwards-compat lazy re-export of ChromaStore ──────────────────────────


def __getattr__(name: str):
    if name == "ChromaStore":
        try:
            from ._chroma_store import ChromaStore

            return ChromaStore
        except ImportError as exc:
            raise ImportError(
                "ChromaStore requires the [chroma] extra: pip install 'mempalace[chroma]'"
            ) from exc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ─── Store factory ─────────────────────────────────────────────────────────────


def _detect_backend(palace_path: str) -> str:
    """Auto-detect which backend a palace uses based on directory contents."""
    p = Path(palace_path)
    if (p / "lance").exists():
        return "lance"
    if (p / "chroma.sqlite3").exists():
        return "chroma"
    # New palace — default to LanceDB
    return "lance"


def open_store(
    palace_path: str,
    backend: Optional[str] = None,
    collection_name: str = "mempalace_drawers",
    create: bool = True,
    embed_model: Optional[str] = None,
) -> DrawerStore:
    """
    Open a drawer store. Auto-detects backend if not specified.

    Args:
        palace_path: Path to the palace data directory.
        backend: "lance" or "chroma". None = auto-detect.
        collection_name: Collection name (ChromaDB only).
        create: Create table/collection if it doesn't exist.
        embed_model: Embedding model name (LanceDB only). None = default.
    """
    os.makedirs(palace_path, exist_ok=True)

    if backend is None:
        backend = _detect_backend(palace_path)

    if backend == "lance":
        return LanceStore(palace_path, create=create, embed_model=embed_model)
    elif backend == "chroma":
        try:
            from ._chroma_store import ChromaStore
        except ImportError as exc:
            raise ImportError(
                "ChromaDB backend requires the [chroma] extra: pip install 'mempalace[chroma]'"
            ) from exc
        return ChromaStore(palace_path, collection_name=collection_name, create=create)
    else:
        raise ValueError(f"Unknown storage backend: {backend!r}. Use 'lance' or 'chroma'.")
