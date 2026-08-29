"""
storage.py — LanceDB storage backend for MemPalace
==================================================

Provides a unified interface for drawer storage backed by LanceDB
(default, crash-safe).

Usage:
    from mempalace_code.storage import open_store

    store = open_store("/path/to/palace")          # auto-detect or create LanceDB
    store = open_store("/path/to/palace", "lance")  # explicit backend

The store object exposes a collection-like API that all MemPalace code
uses instead of calling LanceDB directly. Current releases are LanceDB-only.
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import shutil
import sys
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, cast, runtime_checkable

from mempalace_code.retrieval_rerank import overfetch_limit, rerank, should_overfetch

logger = logging.getLogger("mempalace")


# ─── Internal structural protocols for LanceDB handles ────────────────────────
# These keep Pyright happy without importing lancedb at module load time and
# without requiring stubs that cover every dynamic attribute (head, scanner, etc.)


class _EmbedderProtocol(Protocol):
    def ndims(self) -> int: ...
    def compute_source_embeddings(self, texts: list[str]) -> list[list[float]]: ...


class _LanceTableProtocol(Protocol):
    @property
    def schema(self) -> Any: ...
    def search(self, query: Any = None) -> Any: ...
    def add(self, data: list) -> None: ...
    def merge_insert(self, on: str | list[str]) -> Any: ...
    def delete(self, condition: str) -> None: ...
    def count_rows(self, filter: str = "") -> int: ...
    def to_arrow(self) -> Any: ...
    def add_columns(self, transforms: dict) -> None: ...
    def optimize(self, **kwargs: Any) -> None: ...
    def list_versions(self) -> list: ...
    def checkout(self, version: int) -> None: ...
    def checkout_latest(self) -> None: ...
    def restore(self, version: int) -> None: ...
    def head(self, n: int) -> Any: ...
    def scanner(self, **kwargs: Any) -> Any: ...


class _LanceDBConnectionProtocol(Protocol):
    def open_table(self, name: str) -> _LanceTableProtocol: ...
    def create_table(self, name: str, schema: Any = None) -> _LanceTableProtocol: ...


class LanceStoreDependencyError(RuntimeError):
    """Raised when a required Lance cleanup dependency is not available."""


CHROMA_MIGRATION_COMMAND = (
    "uvx --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify"
)
CHROMA_RUNTIME_RETIRED_MESSAGE = (
    "ChromaDB migration support is retired from current releases because every available "
    "ChromaDB release is advisory-affected. Back up the source palace before upgrading. "
    "Use the last public bridge release in isolation exactly once: "
    f"`{CHROMA_MIGRATION_COMMAND}`."
)
_BACKEND_CHROMA_MIGRATION_REQUIRED = "chroma_migration_required"


class ChromaRuntimeRetiredError(RuntimeError):
    """Raised when legacy ChromaDB storage is requested as a runtime backend."""


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

    def replace_source(
        self,
        source_file: str,
        wing: str,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Atomically replace every drawer for one exact source and wing."""
        raise NotImplementedError

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

    def delete_by_source_files(self, source_files, wing: str) -> int:
        """Bulk-delete all drawers for a collection of source_file values within a wing.

        Fallback: iterates and calls delete_by_source_file() per file.
        Override in backends that support efficient batch deletion (e.g. LanceDB).
        Returns the total deleted row count.
        """
        total = 0
        for sf in source_files:
            total += self.delete_by_source_file(sf, wing)
        return total

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


# ─── Optimize capability contract ─────────────────────────────────────────────


@dataclass
class OptimizeResult:
    ok: bool
    supported: bool


@runtime_checkable
class SafeOptimizeStore(Protocol):
    """Optional protocol for stores that support fail-safe compaction."""

    def safe_optimize(
        self, palace_path: str, backup_first: bool = False, kg_path: Optional[str] = None
    ) -> bool: ...


class OptimizableStore(Protocol):
    """Minimal capability optimize_store actually relies on for the fallback path."""

    def optimize(self) -> None: ...


def optimize_store(
    store: OptimizableStore | SafeOptimizeStore,
    palace_path: str,
    backup_first: bool = False,
    kg_path: Optional[str] = None,
) -> OptimizeResult:
    """Route optimization through safe_optimize when supported, otherwise use optimize().

    Returns OptimizeResult(ok, supported) so callers can distinguish failure from
    an unsupported/no-op path without relying on hasattr checks.

    kg_path: explicit KG path for pre-optimize backups. When None, the backup module
        default is used. Pass palace_kg_path(palace_path) for scoped palace operations.
    """
    if isinstance(store, SafeOptimizeStore):
        ok = store.safe_optimize(palace_path, backup_first=backup_first, kg_path=kg_path)
        return OptimizeResult(ok=ok, supported=True)
    store.optimize()
    return OptimizeResult(ok=True, supported=False)


# ─── LanceDB backend ──────────────────────────────────────────────────────────

_LANCE_TABLE = "mempalace_drawers"
DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"  # same model ChromaDB uses by default
CANONICAL_EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CANONICAL_EMBED_MODEL_REVISION = "5f1b8cd78bc4fb444dd171e59b18f3a3af89a079"
CANONICAL_EMBED_MAX_LENGTH = 256
CANONICAL_EMBED_COMPATIBILITY_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
CUSTOM_MODELS_INSTALL_COMMAND = "python -m pip install 'mempalace-code[custom-models]'"
_CANONICAL_MODEL_ALIASES = frozenset({DEFAULT_EMBED_MODEL, CANONICAL_EMBED_MODEL})
_FASTEMBED_CACHE_LAYOUT_VERSION = 1
_FASTEMBED_CACHE_CHILD = Path("mempalace-fastembed") / "all-MiniLM-L6-v2-v1"
_FASTEMBED_PROVENANCE = ".mempalace-model.json"
_FASTEMBED_REPOSITORY = "models--qdrant--all-MiniLM-L6-v2-onnx"
_FASTEMBED_REQUIRED_ARTIFACTS = (
    "config.json",
    "model.onnx",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
BULK_DELETE_BATCH_SIZE = 500  # max source_file values per single IN-predicate delete


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_existing_model_path(model_name: str) -> bool:
    try:
        return Path(model_name).expanduser().exists()
    except OSError:
        return False


def is_canonical_embed_model(model_name: str) -> bool:
    """Return whether *model_name* selects the built-in MiniLM runtime."""
    return model_name in _CANONICAL_MODEL_ALIASES


def canonical_fastembed_cache_root() -> Path:
    """Return the one explicit FastEmbed cache root used by every runtime contour."""
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return hf_home.expanduser() / _FASTEMBED_CACHE_CHILD


def canonical_fastembed_provenance() -> dict[str, object]:
    """Return the immutable identity required before an offline cache is trusted."""
    return {
        "cache_layout_version": _FASTEMBED_CACHE_LAYOUT_VERSION,
        "dimensions": 384,
        "max_sequence_length": CANONICAL_EMBED_MAX_LENGTH,
        "model": CANONICAL_EMBED_MODEL,
        "normalization": "l2",
        "provider": "CPUExecutionProvider",
        "revision": CANONICAL_EMBED_MODEL_REVISION,
        "runtime": "fastembed",
        "sequence_length_source_revision": CANONICAL_EMBED_COMPATIBILITY_REVISION,
    }


def canonical_fastembed_provenance_path() -> Path:
    return canonical_fastembed_cache_root() / _FASTEMBED_PROVENANCE


def _read_canonical_provenance(root: Path | None = None) -> dict[str, object] | None:
    path = (root or canonical_fastembed_cache_root()) / _FASTEMBED_PROVENANCE
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _canonical_fastembed_cache_error(root: Path) -> str | None:
    """Return why *root* is not the exact bounded cache owned by MemPalace."""
    if root.is_symlink() or not root.is_dir():
        return "cache root is missing, not a directory, or symlinked"
    try:
        resolved_root = root.resolve(strict=True)
        if resolved_root.parent != root.parent.resolve(strict=True):
            return "cache root resolves outside its owner parent"
        if _read_canonical_provenance(root) != canonical_fastembed_provenance():
            return "cache provenance is missing, symlinked, or mismatched"

        repository = root / _FASTEMBED_REPOSITORY
        refs = repository / "refs"
        snapshots = repository / "snapshots"
        snapshot = snapshots / CANONICAL_EMBED_MODEL_REVISION
        for directory in (repository, refs, snapshots, snapshot):
            if directory.is_symlink() or not directory.is_dir():
                return f"runtime cache component is missing or symlinked: {directory.name}"
            if not directory.resolve(strict=True).is_relative_to(resolved_root):
                return "runtime cache component resolves outside the owned root"

        revision_path = refs / "main"
        if revision_path.is_symlink() or not revision_path.is_file():
            return "refs/main is missing or symlinked"
        if not revision_path.resolve(strict=True).is_relative_to(resolved_root):
            return "refs/main resolves outside the owned root"
        if revision_path.read_text(encoding="utf-8").strip() != CANONICAL_EMBED_MODEL_REVISION:
            return "refs/main does not equal the pinned revision"

        for name in _FASTEMBED_REQUIRED_ARTIFACTS:
            artifact = snapshot / name
            if not artifact.is_file():
                return f"runtime artifact is missing or not a file: {name}"
            if not artifact.resolve(strict=True).is_relative_to(resolved_root):
                return f"runtime artifact resolves outside the owned root: {name}"
        tokenizer_config = json.loads(
            (snapshot / "tokenizer_config.json").read_text(encoding="utf-8")
        )
        if (
            not isinstance(tokenizer_config, dict)
            or tokenizer_config.get("max_length") != CANONICAL_EMBED_MAX_LENGTH
        ):
            return "tokenizer max_length does not equal the compatibility contract"
    except (json.JSONDecodeError, OSError, UnicodeError):
        return "cache ownership validation could not read a required component"
    return None


def _require_owned_canonical_fastembed_cache(root: Path | None = None) -> Path:
    cache_root = root or canonical_fastembed_cache_root()
    error = _canonical_fastembed_cache_error(cache_root)
    if error is not None:
        raise RuntimeError(
            f"Canonical FastEmbed cache is not owned: {error}. "
            "Run `mempalace-code fetch-model` while online, then retry offline."
        )
    return cache_root


def canonical_fastembed_cache_owned() -> bool:
    return _canonical_fastembed_cache_error(canonical_fastembed_cache_root()) is None


def canonical_fastembed_cache_status() -> dict[str, object]:
    """Return the installed runtime owner's cache identity and validation result."""
    root = canonical_fastembed_cache_root()
    error = _canonical_fastembed_cache_error(root)
    return {
        "owned": error is None,
        "root": str(root),
        "error": error,
    }


def _cache_tree_safe_to_quarantine(root: Path) -> bool:
    """Allow preservation only when no link can escape the cache being renamed."""
    if root.is_symlink() or not root.is_dir():
        return False
    try:
        resolved_root = root.resolve(strict=True)
        provenance = root / _FASTEMBED_PROVENANCE
        if provenance.is_symlink():
            return False
        for path in root.rglob("*"):
            if path.is_symlink() and not path.resolve(strict=True).is_relative_to(resolved_root):
                return False
    except OSError:
        return False
    return True


def quarantine_unowned_canonical_fastembed_cache() -> Path | None:
    """Atomically preserve a safe partial cache beside the canonical root."""
    root = canonical_fastembed_cache_root()
    if not root.exists() and not root.is_symlink():
        return None
    if canonical_fastembed_cache_owned():
        return None
    if not _cache_tree_safe_to_quarantine(root):
        raise RuntimeError(
            f"Refusing to quarantine hostile embedding cache: {root}. "
            "Move it aside manually, then run `mempalace-code fetch-model`."
        )
    quarantine = root.with_name(f"{root.name}.quarantine-{uuid.uuid4().hex}")
    root.rename(quarantine)
    return quarantine


def remove_owned_canonical_fastembed_cache() -> bool:
    """Remove only the exact, provenance-bound canonical artifact."""
    root = canonical_fastembed_cache_root()
    if not root.exists() and not root.is_symlink():
        return False
    if _canonical_fastembed_cache_error(root) is not None:
        raise RuntimeError(
            f"Refusing to remove unowned embedding cache: {root}. "
            "Move it aside manually, then run `mempalace-code fetch-model`."
        )
    # Rename first so a concurrent replacement at the public path cannot change
    # what is deleted. Revalidate the exact renamed tree before recursive removal.
    quarantine = root.with_name(f".{root.name}.delete-{os.getpid()}-{uuid.uuid4().hex}")
    root.rename(quarantine)
    try:
        _require_owned_canonical_fastembed_cache(quarantine)
    except Exception:
        if not root.exists() and not root.is_symlink():
            quarantine.rename(root)
        raise RuntimeError(
            f"Refusing to remove embedding cache changed during validation: {root}. "
            "Move it aside manually, then run `mempalace-code fetch-model`."
        ) from None
    shutil.rmtree(quarantine)
    return True


def preflight_embed_model(model_name: str) -> None:
    """Fail explicit custom models before LanceDB or filesystem mutation."""
    if is_canonical_embed_model(model_name):
        return
    try:
        importlib.import_module("sentence_transformers")
    except ImportError as exc:
        raise RuntimeError(
            "Custom embedding model support is not installed. Run exactly: "
            f"{CUSTOM_MODELS_INSTALL_COMMAND}"
        ) from exc


def _write_canonical_provenance() -> None:
    root = canonical_fastembed_cache_root()
    root.mkdir(parents=True, exist_ok=True)
    revision_path = root / _FASTEMBED_REPOSITORY / "refs" / "main"
    try:
        resolved_revision = revision_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("FastEmbed cache is missing immutable model revision evidence") from exc
    if resolved_revision != CANONICAL_EMBED_MODEL_REVISION:
        raise RuntimeError(
            "FastEmbed model revision changed; refusing to bless unreviewed cache artifact"
        )
    tokenizer_config = (
        root
        / _FASTEMBED_REPOSITORY
        / "snapshots"
        / CANONICAL_EMBED_MODEL_REVISION
        / "tokenizer_config.json"
    )
    resolved_root = root.resolve(strict=True)
    if not tokenizer_config.is_file() or not tokenizer_config.resolve(strict=True).is_relative_to(
        resolved_root
    ):
        raise RuntimeError("FastEmbed tokenizer configuration is missing or unowned")
    try:
        config = json.loads(tokenizer_config.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise RuntimeError("FastEmbed tokenizer configuration is invalid") from exc
    if not isinstance(config, dict):
        raise RuntimeError("FastEmbed tokenizer configuration is invalid")
    config["max_length"] = CANONICAL_EMBED_MAX_LENGTH
    temporary_config = tokenizer_config.with_name(
        f".{tokenizer_config.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temporary_config.open("x", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2, sort_keys=True)
            handle.write("\n")
        if not tokenizer_config.is_file() or not tokenizer_config.resolve(
            strict=True
        ).is_relative_to(root.resolve(strict=True)):
            raise RuntimeError("FastEmbed tokenizer configuration changed during normalization")
        temporary_config.replace(tokenizer_config)
    finally:
        temporary_config.unlink(missing_ok=True)
    path = canonical_fastembed_provenance_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(canonical_fastembed_provenance(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    _require_owned_canonical_fastembed_cache(root)


class _FastEmbedder:
    """CPU-only FastEmbed adapter for the canonical MiniLM aliases."""

    def __init__(self, *, local_files_only: bool | None = None):
        from fastembed import TextEmbedding

        explicit_offline = _env_truthy("HF_HUB_OFFLINE") or _env_truthy("TRANSFORMERS_OFFLINE")
        offline = explicit_offline if local_files_only is None else local_files_only
        if offline:
            _require_owned_canonical_fastembed_cache()
            cache_owned = True
        else:
            cache_owned = canonical_fastembed_cache_owned()
            cache_root = canonical_fastembed_cache_root()
            if (cache_root.exists() or cache_root.is_symlink()) and not cache_owned:
                _require_owned_canonical_fastembed_cache()
        kwargs = {
            "model_name": CANONICAL_EMBED_MODEL,
            "cache_dir": str(canonical_fastembed_cache_root()),
            "providers": ["CPUExecutionProvider"],
            "cuda": False,
            "local_files_only": offline or cache_owned,
        }
        if offline or cache_owned:
            _require_owned_canonical_fastembed_cache()
        try:
            model = TextEmbedding(**kwargs)
        except Exception:
            if offline:
                raise
            kwargs["local_files_only"] = False
            model = TextEmbedding(**kwargs)
        if offline or cache_owned:
            _require_owned_canonical_fastembed_cache()
        if not offline:
            _write_canonical_provenance()
            if not cache_owned:
                kwargs["local_files_only"] = True
                model = TextEmbedding(**kwargs)
        self._model = model

    def ndims(self) -> int:
        return 384

    def compute_source_embeddings(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for raw in self._model.embed(list(texts)):
            vector = [float(value) for value in raw]
            norm = math.sqrt(sum(value * value for value in vector))
            if norm == 0:
                raise RuntimeError("FastEmbed returned a zero-length embedding")
            vectors.append([value / norm for value in vector])
        return vectors


class _SentenceTransformerEmbedder:
    """MemPalace-controlled sentence-transformers wrapper.

    LanceDB's registry wrapper does not expose local_files_only and loads the
    model lazily, so a cached search can still make HuggingFace metadata calls.
    This wrapper keeps the same model/device/normalization defaults while trying
    local resolution before any network-capable load.
    """

    def __init__(self, model_name: str):
        preflight_embed_model(model_name)
        self._model_name = model_name
        self._model = self._load_model()
        self._ndims: int | None = None

    def _load_model(self):
        SentenceTransformer = importlib.import_module("sentence_transformers").SentenceTransformer

        explicit_offline = _env_truthy("HF_HUB_OFFLINE") or _env_truthy("TRANSFORMERS_OFFLINE")
        is_local_path = _is_existing_model_path(self._model_name)
        kwargs = {"device": "cpu", "trust_remote_code": True}

        try:
            return SentenceTransformer(
                self._model_name,
                local_files_only=True,
                **kwargs,
            )
        except Exception:
            if explicit_offline or is_local_path:
                raise
            logger.debug(
                "Embedding model %r was not available locally; retrying online",
                self._model_name,
            )

        return SentenceTransformer(self._model_name, **kwargs)

    def ndims(self) -> int:
        if self._ndims is None:
            self._ndims = len(self.compute_source_embeddings(["foo"])[0])
        return self._ndims

    def compute_source_embeddings(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vectors.tolist()


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
    # Line range metadata; 0 means unknown (legacy rows or chunks without exact-match).
    ("line_start", "int32", 0),
    ("line_end", "int32", 0),
)

_META_KEYS: frozenset = frozenset(name for name, _, _ in _META_FIELD_SPEC)
_META_DEFAULTS: dict = {name: default for name, _, default in _META_FIELD_SPEC}


def _meta_arrow_types() -> dict:
    """Return the PyArrow type map for _META_FIELD_SPEC type tags.

    Single source of truth for the string→pa.DataType mapping used wherever
    _META_FIELD_SPEC type tags are resolved to PyArrow types.  Kept as a
    function so pyarrow stays a lazy import.
    """
    import pyarrow as pa

    return {"string": pa.string(), "int32": pa.int32(), "float32": pa.float32()}


def _target_drawer_schema(dim: int):
    """Return the canonical PyArrow schema for a new drawers table.

    Used only by the new-table creation path in ``LanceStore._open_or_create()``.
    The migration path for existing tables uses ``_META_FIELD_SPEC`` directly so it
    does not need embedding dimensions.  Any new column additions must be made in
    ``_META_FIELD_SPEC`` only.
    """
    import pyarrow as pa

    arrow_types = _meta_arrow_types()
    fields = [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ]
    for name, type_tag, _ in _META_FIELD_SPEC:
        fields.append(pa.field(name, arrow_types[type_tag]))
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


def _is_missing_fragment_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in ("no such file", "object not found", "io error", "not found"))


class LanceStore(DrawerStore):
    """
    Crash-safe drawer storage using LanceDB.

    Data is stored in Lance columnar format with proper transactions —
    an interrupted write does not corrupt the entire dataset.
    """

    def __init__(
        self,
        palace_path: str,
        create: bool = True,
        embed_model: Optional[str] = None,
        read_only: bool = False,
    ):
        self._model_name = embed_model or DEFAULT_EMBED_MODEL
        preflight_embed_model(self._model_name)
        import lancedb

        self._read_only = read_only
        self._embedder: _EmbedderProtocol | None = None  # lazy — initialized by _ensure_embedder()
        self._db: _LanceDBConnectionProtocol | None = None
        self._table: _LanceTableProtocol | None = None

        lance_dir = os.path.join(palace_path, "lance")
        self._lance_dir = lance_dir
        self._table_dir = os.path.join(lance_dir, f"{_LANCE_TABLE}.lance")
        if read_only and not os.path.isdir(lance_dir):
            # Palace absent — return a stub without touching the filesystem.
            return

        self._db = cast("_LanceDBConnectionProtocol", lancedb.connect(lance_dir))
        self._table = self._open_or_create(create)

    def _get_embedder(self):
        """Load the provider selected by the existing embed_model contract."""
        if is_canonical_embed_model(self._model_name):
            return _FastEmbedder()
        return _SentenceTransformerEmbedder(self._model_name)

    def _ensure_embedder(self) -> None:
        """Initialize the embedding model on first use.

        Suppresses noisy HF/safetensors output at the OS fd level so C-extension
        writes don't leak to stdout/stderr.
        """
        if self._embedder is not None:
            return
        import logging

        hf_logger = logging.getLogger("huggingface_hub")
        prev_level = hf_logger.level
        hf_logger.setLevel(logging.ERROR)
        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stdout = os.dup(1)
        old_stderr = os.dup(2)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            self._embedder = cast("_EmbedderProtocol", self._get_embedder())
        finally:
            try:
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                finally:
                    os.dup2(old_stdout, 1)
                    os.dup2(old_stderr, 2)
            finally:
                os.close(devnull)
                os.close(old_stdout)
                os.close(old_stderr)
                hf_logger.setLevel(prev_level)

    def _require_db(self) -> _LanceDBConnectionProtocol:
        """Return the open LanceDB connection or raise RuntimeError."""
        db = self._db
        if db is None:
            raise RuntimeError("LanceDB connection is not open")
        return db

    def _require_table(
        self, message: str = "Table does not exist and create=False"
    ) -> _LanceTableProtocol:
        """Return the open LanceDB table or raise RuntimeError."""
        table = self._table
        if table is None:
            raise RuntimeError(message)
        return table

    def _reopen_table(self) -> _LanceTableProtocol:
        """Re-open the Lance table and replace the cached handle."""
        table = self._require_db().open_table(_LANCE_TABLE)
        self._table = table
        return table

    def _embedder_handle(self) -> _EmbedderProtocol:
        """Return the initialized embedder; caller must have called _ensure_embedder() first."""
        embedder = self._embedder
        if embedder is None:
            raise RuntimeError("Embedder not initialized — call _ensure_embedder() first")
        return embedder

    def _open_or_create(self, create: bool) -> _LanceTableProtocol | None:
        """Open existing table or create a new one, migrating schema if needed."""
        if self._read_only:
            # Read-only: open if present, return None without creating or migrating.
            db = self._db
            if db is None:
                return None
            try:
                return db.open_table(_LANCE_TABLE)
            except Exception as e:
                logger.debug("Table %r not found (read_only=True): %s", _LANCE_TABLE, e)
                return None

        # Write path: open existing table first; embedder only needed for new-table creation.
        db = self._require_db()

        _existing_table: _LanceTableProtocol | None = None
        try:
            _existing_table = db.open_table(_LANCE_TABLE)
        except Exception as e:
            logger.debug("Table %r not found, will create: %s", _LANCE_TABLE, e)

        if _existing_table is not None:
            # Migrate metadata columns from _META_FIELD_SPEC without needing embedding
            # dimensions — the vector column already exists in the on-disk schema.
            existing_names = set(_existing_table.schema.names)
            missing_meta = [
                (name, type_tag)
                for name, type_tag, _ in _META_FIELD_SPEC
                if name not in existing_names
            ]
            if missing_meta:
                arrow_types = _meta_arrow_types()
                cols_to_add = {
                    name: _sql_default_for_arrow_type(arrow_types[type_tag])
                    for name, type_tag in missing_meta
                }
                logger.info("Migrating palace schema: adding columns %s", sorted(cols_to_add))
                _existing_table.add_columns(cols_to_add)
                _existing_table = db.open_table(_LANCE_TABLE)
                reloaded_names = set(_existing_table.schema.names)
                expected_names = {"id", "text", "vector"} | {n for n, _, _ in _META_FIELD_SPEC}
                if not expected_names <= reloaded_names:
                    still_missing = expected_names - reloaded_names
                    raise RuntimeError(
                        f"Post-migration assertion failed — still missing columns: {still_missing}"
                    )
            return _existing_table

        if not create:
            return None

        # New table: need embedding dimensions for the vector column schema.
        self._ensure_embedder()
        dim = self._embedder_handle().ndims()
        target = _target_drawer_schema(dim)
        return db.create_table(_LANCE_TABLE, schema=target)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        self._ensure_embedder()
        embedder = self._embedder_handle()
        return [list(v) for v in embedder.compute_source_embeddings(texts)]

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
        table = self._table
        if table is None:
            return 0
        return table.count_rows()

    def add(self, ids, documents, metadatas):
        if self._read_only:
            raise RuntimeError("Cannot add to a read-only LanceStore")
        table = self._require_table()

        vectors = self._embed(documents)
        rows = []
        for id_, doc, meta, vec in zip(ids, documents, metadatas, vectors):
            row = self._meta_defaults(meta)
            row["id"] = id_
            row["text"] = doc
            row["vector"] = vec
            rows.append(row)

        table.add(rows)

    def upsert(self, ids, documents, metadatas):
        # LanceDB merge_insert for upsert
        if self._read_only:
            raise RuntimeError("Cannot upsert a read-only LanceStore")
        table = self._require_table()

        vectors = self._embed(documents)
        rows = []
        for id_, doc, meta, vec in zip(ids, documents, metadatas, vectors):
            row = self._meta_defaults(meta)
            row["id"] = id_
            row["text"] = doc
            row["vector"] = vec
            rows.append(row)

        def _execute_merge(target_table: _LanceTableProtocol) -> None:
            target_table.merge_insert(
                "id"
            ).when_matched_update_all().when_not_matched_insert_all().execute(rows)

        try:
            _execute_merge(table)
        except Exception as exc:
            if not _is_missing_fragment_error(exc):
                raise
            logger.warning("Lance upsert saw a missing fragment; reopening table and retrying once")
            _execute_merge(self._reopen_table())

    def replace_source(
        self,
        source_file: str,
        wing: str,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Atomically replace every drawer for one exact source and wing."""
        if self._read_only:
            raise RuntimeError("Cannot replace a source in a read-only LanceStore")
        if not source_file or not wing:
            raise ValueError("source_file and wing must be non-empty")
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("ids, documents, and metadatas must have equal lengths")
        if not ids:
            raise ValueError("replace_source requires at least one replacement row")
        if any(
            metadata.get("source_file") != source_file or metadata.get("wing") != wing
            for metadata in metadatas
        ):
            raise ValueError("every replacement row must match the exact source_file and wing")

        table = self._require_table()
        vectors = self._embed(documents)
        rows = []
        for id_, document, metadata, vector in zip(ids, documents, metadatas, vectors):
            row = self._meta_defaults(metadata)
            row["id"] = id_
            row["text"] = document
            row["vector"] = vector
            rows.append(row)

        escaped_file = source_file.replace("'", "''")
        escaped_wing = wing.replace("'", "''")
        source_scope = f"source_file = '{escaped_file}' AND wing = '{escaped_wing}'"

        def _execute_merge(target_table: _LanceTableProtocol) -> None:
            (
                target_table.merge_insert(["id", "source_file", "wing"])
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .when_not_matched_by_source_delete(source_scope)
                .execute(rows)
            )

        try:
            _execute_merge(table)
        except Exception as exc:
            if not _is_missing_fragment_error(exc):
                raise
            logger.warning(
                "Lance source replacement saw a missing fragment; reopening table and retrying once"
            )
            _execute_merge(self._reopen_table())

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        table = self._table
        if table is None:
            return {"ids": [], "documents": [], "metadatas": []}

        include = include or []

        if ids is not None:
            if not ids:
                return {"ids": [], "documents": [], "metadatas": []}
            # Fetch by explicit IDs
            id_list = ", ".join(f"'{id_}'" for id_ in ids)
            try:
                results = table.search().where(f"id IN ({id_list})").limit(len(ids)).to_list()
            except Exception:
                results = []
        elif where is not None:
            sql = self._where_to_sql(where)
            try:
                results = table.search().where(sql).limit(limit).offset(offset).to_list()
            except Exception:
                results = []
        else:
            try:
                results = table.search().limit(limit).offset(offset).to_list()
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
        table = self._table
        if table is None:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        include = include or []
        all_ids, all_docs, all_metas, all_dists = [], [], [], []

        for text in query_texts:
            vec = self._embed([text])[0]
            # Overfetch for project-file or symbol-intent queries so the reranker
            # has enough candidates to promote highly-relevant but lower-ranked rows.
            if should_overfetch(text):
                fetch_limit = overfetch_limit(n_results)
            else:
                fetch_limit = n_results
            q = table.search(vec).limit(fetch_limit)
            if where:
                sql = self._where_to_sql(where)
                q = q.where(sql)

            try:
                results = q.to_list()
            except Exception:
                results = []

            if fetch_limit > n_results:
                results = rerank(results, text, n_results)

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
        table = self._table
        if table is None:
            return
        if not ids:
            return
        id_list = ", ".join(f"'{id_}'" for id_ in ids)
        table.delete(f"id IN ({id_list})")

    def delete_wing(self, wing: str) -> int:
        table = self._table
        if table is None:
            return 0
        escaped = wing.replace("'", "''")
        count = table.count_rows(f"wing = '{escaped}'")
        if count == 0:
            return 0
        table.delete(f"wing = '{escaped}'")
        return count

    def delete_by_source_file(self, source_file: str, wing: str) -> int:
        """Delete all drawers for a given source_file within a wing."""
        table = self._table
        if table is None:
            return 0
        escaped_file = source_file.replace("'", "''")
        escaped_wing = wing.replace("'", "''")
        count = table.count_rows(f"source_file = '{escaped_file}' AND wing = '{escaped_wing}'")
        if count == 0:
            return 0
        table.delete(f"source_file = '{escaped_file}' AND wing = '{escaped_wing}'")
        return count

    def delete_by_source_files(self, source_files, wing: str) -> int:
        """Bulk-delete drawers for a collection of source_file values within a wing.

        Deduplicates the input, then issues at most one count/delete predicate per
        BULK_DELETE_BATCH_SIZE files. Batches whose count is zero skip table.delete to
        avoid creating no-op Lance versions. Returns total deleted row count.
        """
        table = self._table
        if table is None:
            return 0

        paths = list(dict.fromkeys(source_files))  # dedupe, preserve insertion order
        if not paths:
            return 0

        escaped_wing = wing.replace("'", "''")
        total_deleted = 0

        for i in range(0, len(paths), BULK_DELETE_BATCH_SIZE):
            batch = paths[i : i + BULK_DELETE_BATCH_SIZE]
            escaped_items = ", ".join("'" + p.replace("'", "''") + "'" for p in batch)
            predicate = f"source_file IN ({escaped_items}) AND wing = '{escaped_wing}'"
            count = table.count_rows(predicate)
            if count == 0:
                continue
            table.delete(predicate)
            total_deleted += count

        return total_deleted

    def get_source_file_hashes(self, wing: str) -> dict:
        """Return {source_file: source_hash} for all drawers in wing.

        Uses LanceDB scan-time column projection — no vector scan.
        Deduplicates by taking the first hash per source_file.
        Returns an empty dict if the table is empty or column is absent.
        """
        table = self._table
        if table is None:
            return {}
        import pyarrow.compute as pc

        try:
            arrow_tbl = self._scan_columns(table, ["source_file", "source_hash", "wing"])
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
        table = self._table
        if table is None:
            return {}
        arrow_tbl = self._scan_columns(table, [column])
        result = arrow_tbl.group_by(column).aggregate([(column, "count")])
        d = result.to_pydict()
        return dict(zip(d[column], d[f"{column}_count"]))

    def count_by_pair(self, col_a: str, col_b: str) -> Dict[str, Dict[str, int]]:
        table = self._table
        if table is None:
            return {}
        arrow_tbl = self._scan_columns(table, [col_a, col_b])
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
        table = self._table
        if table is None:
            return set()
        import pyarrow.compute as pc

        arrow_tbl = self._scan_columns(table, ["source_file", "wing"])
        filtered = arrow_tbl.filter(pc.field("wing") == wing)
        return set(filtered.column("source_file").to_pylist())

    def _scan_columns(self, table: _LanceTableProtocol, columns: List[str]):
        """Return an Arrow table from a LanceDB scan projected to *columns*."""
        scanner = getattr(table, "scanner", None)
        if scanner is not None:
            return scanner(columns=columns).to_table()
        return table.search().select(columns).to_arrow()

    def iter_all(self, where=None, batch_size=1000, include_vectors=False):
        """Yield batches of drawers as lists of dicts using PyArrow column projection.

        Loads all non-vector columns via to_arrow() (no vector scan), applies an
        optional PyArrow-level filter, then yields one list of dicts per batch.
        """
        table = self._table
        if table is None:
            return

        meta_columns = ["id", "text"] + [name for name, _, _ in _META_FIELD_SPEC]
        columns = meta_columns + (["vector"] if include_vectors else [])
        # Only include columns that actually exist in the schema
        existing = set(table.schema.names)
        columns = [c for c in columns if c in existing]

        try:
            arrow_tbl = table.to_arrow().select(columns)
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
        import pyarrow.compute as _pc

        # Route through getattr to avoid PyArrow stub gaps for compute functions.
        def _f(name: str):
            return getattr(_pc, name)

        if "$and" in where:
            masks = [LanceStore._where_to_arrow_mask(arrow_tbl, sub) for sub in where["$and"]]
            masks = [m for m in masks if m is not None]
            if not masks:
                return None
            result = masks[0]
            for m in masks[1:]:
                result = _f("and_")(result, m)
            return result

        if "$or" in where:
            masks = [LanceStore._where_to_arrow_mask(arrow_tbl, sub) for sub in where["$or"]]
            masks = [m for m in masks if m is not None]
            if not masks:
                return None
            result = masks[0]
            for m in masks[1:]:
                result = _f("or_")(result, m)
            return result

        _OP_MAP = {
            "$eq": _f("equal"),
            "$ne": _f("not_equal"),
            "$gt": _f("greater"),
            "$gte": _f("greater_equal"),
            "$lt": _f("less"),
            "$lte": _f("less_equal"),
        }

        parts = []
        for key, value in where.items():
            if key not in arrow_tbl.schema.names:
                continue
            col = arrow_tbl.column(key)
            if isinstance(value, str):
                parts.append(_f("equal")(col, value))
            elif isinstance(value, (int, float)):
                parts.append(_f("equal")(col, value))
            elif isinstance(value, dict):
                for op, operand in value.items():
                    fn = _OP_MAP.get(op)
                    if fn is not None:
                        parts.append(fn(col, operand))
                    elif op == "$in":
                        parts.append(_f("is_in")(col, value_set=pa.array(operand, type=col.type)))
        if not parts:
            return None
        result = parts[0]
        for p in parts[1:]:
            result = _f("and_")(result, p)
        return result

    def optimize(self) -> None:
        """Merge Lance fragments and prune old versions (post-mining compaction)."""
        table = self._table
        if table is not None:
            table.optimize()

    def safe_optimize(
        self, palace_path: str, backup_first: bool = False, kg_path: Optional[str] = None
    ) -> bool:
        """Optimize with optional pre-backup and post-verification.

        Fail-closed contract: if backup_first=True and the backup fails, returns False
        without running optimize(). The table is never compacted when the backup gate fails.

        Args:
            palace_path: Path to palace directory (for backup).
            backup_first: Create backup before optimizing. If True and backup fails,
                          returns False without optimizing.
            kg_path: Explicit KG path for the pre-optimize backup. When None, the backup
                     module default (DEFAULT_KG_PATH) is used. Pass palace_kg_path(palace_path)
                     for scoped palace operations to avoid archiving the global KG.

        Returns:
            True if optimize succeeded and table is readable, False otherwise.
        """
        table = self._table
        if table is None:
            return True

        # Pre-optimize backup via shared managed path (fail-closed gate).
        # Disk guard and per-kind retention run inside create_backup.
        if backup_first:
            try:
                backup_mod = importlib.import_module("mempalace_code.backup")
                _, backup_path = backup_mod.create_backup(
                    palace_path, kind="pre_optimize", kg_path=kg_path
                )
                logger.info("Pre-optimize backup: %s", backup_path)
            except Exception as e:
                logger.error("Pre-optimize backup failed — skipping optimize: %s", e)
                return False

        # Get row count before optimize
        pre_count = table.count_rows()

        # Run optimize — wrapped so any LanceDB exception returns False instead of propagating
        try:
            table.optimize()
        except Exception as e:
            logger.error("optimize() raised an exception: %s", e)
            return False

        try:
            table = self._reopen_table()
        except Exception as e:
            logger.error("Table could not be reopened after optimize: %s", e)
            return False

        # Verify table is still readable
        try:
            table.head(1).to_pydict()
            post_count = table.count_rows()
            if post_count != pre_count:
                logger.warning("Row count changed after optimize: %d -> %d", pre_count, post_count)
            try:
                cleanup_result = self.cleanup_stale_fragments(older_than_days=0, unsafe_now=False)
                if not cleanup_result.get("ok"):
                    cleanup_error = str(cleanup_result.get("error") or cleanup_result)
                    logger.warning(
                        "Post-optimize stale-version cleanup did not complete: %s",
                        cleanup_error,
                    )
                    if cleanup_error.startswith(
                        (
                            "Could not reopen table after cleanup",
                            "Table unreadable after cleanup",
                            "Column scan failed after cleanup",
                        )
                    ):
                        return False
            except Exception as cleanup_exc:
                logger.warning("Post-optimize stale-version cleanup skipped: %s", cleanup_exc)
            return True
        except Exception as e:
            logger.error("Table unreadable after optimize: %s", e)
            return False

    def storage_stats(self) -> dict:
        """Return disk and version metrics for the Lance table.

        Returns dict with keys:
          version_count: int — number of Lance versions in the table manifest
          logical_bytes: int — bytes referenced by the current version
          on_disk_bytes: int — total bytes across all files in the table directory
          current_data_files: int — data files in the current version
          on_disk_data_files: int — total data files on disk (current + stale)
          current_deletion_files: int — deletion files in the current version
          on_disk_deletion_files: int — total deletion files on disk
          estimated_reclaimable_bytes: int — max(0, on_disk_bytes - logical_bytes)
        """
        empty = {
            "version_count": 0,
            "logical_bytes": 0,
            "on_disk_bytes": 0,
            "current_data_files": 0,
            "on_disk_data_files": 0,
            "current_deletion_files": 0,
            "on_disk_deletion_files": 0,
            "estimated_reclaimable_bytes": 0,
        }
        table = self._table
        if table is None:
            return empty

        version_count = 0
        logical_bytes = 0
        current_data_files = 0
        current_deletion_files = 0

        try:
            versions = table.list_versions()
            version_count = len(versions)
            if versions:
                meta = versions[-1].get("metadata", {})
                logical_bytes = int(meta.get("total_files_size", 0))
                current_data_files = int(meta.get("total_data_files", 0))
                current_deletion_files = int(meta.get("total_deletion_files", 0))
        except Exception:
            pass

        on_disk_bytes = 0
        on_disk_data_files = 0
        on_disk_deletion_files = 0

        table_dir = self._table_dir
        if os.path.isdir(table_dir):
            try:
                for dirpath, _, filenames in os.walk(table_dir):
                    for fname in filenames:
                        try:
                            on_disk_bytes += os.path.getsize(os.path.join(dirpath, fname))
                        except OSError:
                            pass
            except Exception:
                pass

            data_dir = os.path.join(table_dir, "data")
            if os.path.isdir(data_dir):
                try:
                    on_disk_data_files = sum(
                        1 for f in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir, f))
                    )
                except Exception:
                    pass

            deletions_dir = os.path.join(table_dir, "_deletions")
            if os.path.isdir(deletions_dir):
                try:
                    on_disk_deletion_files = sum(
                        1
                        for f in os.listdir(deletions_dir)
                        if os.path.isfile(os.path.join(deletions_dir, f))
                    )
                except Exception:
                    pass

        return {
            "version_count": version_count,
            "logical_bytes": logical_bytes,
            "on_disk_bytes": on_disk_bytes,
            "current_data_files": current_data_files,
            "on_disk_data_files": on_disk_data_files,
            "current_deletion_files": current_deletion_files,
            "on_disk_deletion_files": on_disk_deletion_files,
            "estimated_reclaimable_bytes": max(0, on_disk_bytes - logical_bytes),
        }

    def cleanup_stale_fragments(self, older_than_days: int = 7, unsafe_now: bool = False) -> dict:
        """Remove stale Lance versions and their data/deletion files.

        Uses Table.optimize(cleanup_older_than=..., delete_unverified=...) — the
        supported LanceDB maintenance path. Never deletes files directly.

        Args:
            older_than_days: Remove versions older than this many days. Default 7.
                Ignored when unsafe_now=True (maps to timedelta(0)).
            unsafe_now: Map to cleanup_older_than=timedelta(0) and
                delete_unverified=True. Only safe when no other writer is active.

        Returns dict with keys:
          ok: bool
          rows_before: int
          rows_after: int
          freed_bytes: int — max(0, on_disk_before - on_disk_after)
          version_count_before: int
          version_count_after: int
          estimated_reclaimable_bytes_before: int
          estimated_reclaimable_bytes_after: int
          cleanup_older_than_days: int
          delete_unverified: bool
          error: str (only present when ok=False)
        """
        table = self._table
        if table is None:
            return {
                "ok": False,
                "rows_before": 0,
                "rows_after": 0,
                "freed_bytes": 0,
                "version_count_before": 0,
                "version_count_after": 0,
                "cleanup_older_than_days": 0 if unsafe_now else older_than_days,
                "delete_unverified": unsafe_now,
                "error": "Table is None (not opened)",
            }

        before_stats = self.storage_stats()
        rows_before = table.count_rows()
        version_count_before = before_stats["version_count"]
        on_disk_bytes_before = before_stats["on_disk_bytes"]
        cleanup_older_than = timedelta(0) if unsafe_now else timedelta(days=older_than_days)
        delete_unverified = unsafe_now

        _err_base = {
            "rows_before": rows_before,
            "rows_after": rows_before,
            "freed_bytes": 0,
            "version_count_before": version_count_before,
            "version_count_after": 0,
            "cleanup_older_than_days": 0 if unsafe_now else older_than_days,
            "delete_unverified": delete_unverified,
        }

        if not unsafe_now:
            try:
                versions = table.list_versions()
                cutoff = datetime.now(UTC) - cleanup_older_than
                no_eligible_version = len(versions) == version_count_before
                for version in versions[:-1]:
                    timestamp = version.get("timestamp")
                    if not isinstance(timestamp, datetime):
                        no_eligible_version = False
                        break
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.astimezone()
                    if timestamp.astimezone(UTC) <= cutoff:
                        no_eligible_version = False
                        break
            except Exception:
                no_eligible_version = False

            if no_eligible_version:
                reclaimable_bytes = before_stats["estimated_reclaimable_bytes"]
                return {
                    "ok": True,
                    "rows_before": rows_before,
                    "rows_after": rows_before,
                    "freed_bytes": 0,
                    "version_count_before": version_count_before,
                    "version_count_after": version_count_before,
                    "estimated_reclaimable_bytes_before": reclaimable_bytes,
                    "estimated_reclaimable_bytes_after": reclaimable_bytes,
                    "cleanup_older_than_days": older_than_days,
                    "delete_unverified": False,
                }

        try:
            table.optimize(
                cleanup_older_than=cleanup_older_than,
                delete_unverified=delete_unverified,
            )
        except (ModuleNotFoundError, ImportError) as e:
            msg = str(e).lower()
            if "lance" in msg or "pylance" in msg:
                raise LanceStoreDependencyError(
                    "Lance cleanup requires an updated lancedb installation. "
                    "Run: pip install 'mempalace-code' --upgrade  "
                    "(or: uv pip install 'mempalace-code' --upgrade)"
                ) from e
            raise
        except Exception as e:
            return {**_err_base, "ok": False, "error": str(e)}

        verify_table = table
        db = getattr(self, "_db", None)
        if db is not None:
            try:
                verify_table = db.open_table(_LANCE_TABLE)
                self._table = verify_table
            except Exception as e:
                return {
                    **_err_base,
                    "ok": False,
                    "error": f"Could not reopen table after cleanup: {e}",
                }

        # Post-cleanup verification
        try:
            rows_after = verify_table.count_rows()
            verify_table.head(1).to_pydict()
        except Exception as e:
            return {
                **_err_base,
                "ok": False,
                "rows_after": 0,
                "error": f"Table unreadable after cleanup: {e}",
            }

        try:
            arrow_tbl = self._scan_columns(verify_table, ["wing", "room"])
            arrow_tbl.group_by(["wing", "room"]).aggregate([("room", "count")])
        except Exception as e:
            return {
                **_err_base,
                "ok": False,
                "rows_after": rows_after,
                "error": f"Column scan failed after cleanup: {e}",
            }

        after_stats = self.storage_stats()
        version_count_after = after_stats["version_count"]
        freed_bytes = max(0, on_disk_bytes_before - after_stats["on_disk_bytes"])

        return {
            "ok": True,
            "rows_before": rows_before,
            "rows_after": rows_after,
            "freed_bytes": freed_bytes,
            "version_count_before": version_count_before,
            "version_count_after": version_count_after,
            "estimated_reclaimable_bytes_before": before_stats["estimated_reclaimable_bytes"],
            "estimated_reclaimable_bytes_after": after_stats["estimated_reclaimable_bytes"],
            "cleanup_older_than_days": 0 if unsafe_now else older_than_days,
            "delete_unverified": delete_unverified,
        }

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
        table = self._table
        if table is None:
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
            total_rows = table.count_rows()
        except Exception as e:
            errors.append({"probe": "count_rows", "kind": _classify(e), "message": str(e)})

        # Probe 2: head(1) — touches at least one fragment's data
        try:
            table.head(1).to_pydict()
        except Exception as e:
            errors.append({"probe": "head", "kind": _classify(e), "message": str(e)})

        # Probe 3: column scan — touches every fragment's metadata (the silent-failure surface)
        try:
            arrow_tbl = self._scan_columns(table, ["wing", "room"])
            arrow_tbl.group_by(["wing", "room"]).aggregate([("room", "count")])
        except Exception as e:
            errors.append({"probe": "count_by_pair", "kind": _classify(e), "message": str(e)})

        # Version info — best-effort; failures go into warnings, not errors, to avoid
        # false-positive DEGRADED status when data probes all pass.
        warnings = []
        try:
            versions = table.list_versions()
            if versions:
                current_version = versions[-1]["version"]
        except Exception as e:
            warnings.append({"probe": "list_versions", "kind": _classify(e), "message": str(e)})

        storage = {}
        try:
            storage = self.storage_stats()
        except Exception as e:
            warnings.append({"probe": "storage_stats", "kind": "other", "message": str(e)})

        return {
            "ok": len(errors) == 0,
            "total_rows": total_rows,
            "current_version": current_version,
            "errors": errors,
            "warnings": warnings,
            "storage": storage,
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
        table = self._table
        if table is None:
            return {
                "recovered": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "message": "Table is None (not opened)",
            }

        try:
            versions = table.list_versions()
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
                    table.checkout(ver_num)
                    # Run all three probes
                    table.count_rows()
                    table.head(1).to_pydict()
                    arrow_tbl = self._scan_columns(table, ["wing", "room"])
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
                table.checkout_latest()
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
        table.restore(candidate_version)
        reopened = self._require_db().open_table(_LANCE_TABLE)
        self._table = reopened
        rows_after = reopened.count_rows()
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


# ─── Store factory ─────────────────────────────────────────────────────────────


def _detect_backend(palace_path: str) -> str:
    """Auto-detect which backend a palace uses based on directory contents."""
    p = Path(palace_path)
    if (p / "lance").exists():
        return "lance"
    if (p / "chroma.sqlite3").exists():
        return _BACKEND_CHROMA_MIGRATION_REQUIRED
    # New palace — default to LanceDB
    return "lance"


def open_store(
    palace_path: str,
    backend: Optional[str] = None,
    create: bool = True,
    embed_model: Optional[str] = None,
    read_only: bool = False,
) -> LanceStore:
    """
    Open a LanceDB drawer store. Auto-detects LanceDB palaces if not specified.

    Args:
        palace_path: Path to the palace data directory.
        backend: "lance" or None. "chroma" is retired and raises before mutation.
        create: Create the LanceDB table if it doesn't exist.
        embed_model: Embedding model name. None = default.
        read_only: When True, skip directory creation, schema migration, and embedder
            initialization for read-only metadata access.
    """
    if backend == "chroma":
        raise ChromaRuntimeRetiredError(CHROMA_RUNTIME_RETIRED_MESSAGE)
    if backend not in (None, "lance"):
        raise ValueError(f"Unknown storage backend: {backend!r}. Use 'lance'.")

    if backend is None:
        backend = _detect_backend(palace_path)
    if backend == _BACKEND_CHROMA_MIGRATION_REQUIRED:
        raise ChromaRuntimeRetiredError(CHROMA_RUNTIME_RETIRED_MESSAGE)

    table_dir = os.path.join(palace_path, "lance", f"{_LANCE_TABLE}.lance")
    if not read_only and not create and not os.path.isdir(table_dir):
        raise RuntimeError("Table does not exist and create=False")

    if not read_only:
        os.makedirs(palace_path, exist_ok=True)

    return LanceStore(palace_path, create=create, embed_model=embed_model, read_only=read_only)
