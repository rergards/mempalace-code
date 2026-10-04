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

import hashlib
import importlib
import json
import logging
import math
import os
import re
import shlex
import shutil
import stat
import sys
import tomllib
import uuid
from abc import ABC, abstractmethod
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Protocol, cast, runtime_checkable

from mempalace_code.config import expand_palace_path
from mempalace_code.operation_lock import palace_write_lease
from mempalace_code.retrieval_rerank import overfetch_limit, rerank, should_overfetch
from mempalace_code.version import __version__

logger = logging.getLogger("mempalace")
_EMBEDDER_STDIO_LOCK = Lock()


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
    def replace_field_metadata(self, field_name: str, new_metadata: dict[str, str]) -> None: ...
    def optimize(self, **kwargs: Any) -> None: ...
    def list_versions(self) -> list: ...
    def checkout(self, version: int) -> None: ...
    def checkout_latest(self) -> None: ...
    def restore(self, version: int) -> None: ...
    def head(self, n: int) -> Any: ...
    def scanner(self, **kwargs: Any) -> Any: ...


class _LanceDBConnectionProtocol(Protocol):
    def open_table(self, name: str) -> _LanceTableProtocol: ...
    def create_table(
        self, name: str, schema: Any = None, exist_ok: bool = False
    ) -> _LanceTableProtocol: ...


class LanceStoreDependencyError(RuntimeError):
    """Raised when a required Lance cleanup dependency is not available."""


CHROMA_MIGRATION_COMMAND = (
    "uvx --python 3.12 --from 'mempalace-code[chroma]==1.13.4' "
    "mempalace-code migrate-storage SRC DST --verify"
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


class PalaceReadError(RuntimeError):
    """Stored drawer data could not be read: the palace is degraded or corrupted.

    Raised instead of returning empty results, so a damaged palace is never
    mistaken for an empty one. The message names the palace and the recovery
    commands for it.
    """

    def __init__(self, palace_path: str, cause: BaseException):
        from .cli_invocation import cli_command

        self.palace_path = palace_path
        self.cause = cause
        super().__init__(
            f"stored drawers in {palace_path} are unreadable (palace degraded): {cause}. "
            f"Next: run {cli_command('health', palace=palace_path)}, then "
            f"{cli_command('repair', '--rollback', '--dry-run', palace=palace_path)}; if "
            f"nothing can be rolled back, run {cli_command('repair', palace=palace_path)} "
            "(it changes nothing while drawers are unreadable) or restore an archive listed by "
            f"{cli_command('backup', 'list', palace=palace_path)}"
        )


def _is_query_input_error(exc: BaseException) -> bool:
    """True for a rejected filter or query (caller input), not for unreadable stored data."""
    message = str(exc).lower()
    # New LanceDB releases map InvalidInput to ValueError with this exact prefix.
    # Keep the legacy Lance message; other read failures still mean unreadable data.
    return "invalid user input" in message or (
        isinstance(exc, ValueError) and message.startswith("invalid input,")
    )


def lance_commit_state(palace_path: str) -> tuple[str, ...]:
    """Name every committed manifest of every table under ``<palace>/lance``.

    Each Lance commit adds a manifest and version cleanup removes old ones, so two
    equal results mean no table of the palace changed in between. Backup and repair
    compare the state before and after they read the palace to prove they saw one
    consistent version.
    """
    lance_dir = os.path.join(palace_path, "lance")
    try:
        tables = sorted(os.listdir(lance_dir))
    except (FileNotFoundError, NotADirectoryError):
        return ()
    names: list[str] = []
    for table in tables:
        try:
            entries = os.listdir(os.path.join(lance_dir, table, "_versions"))
        except (FileNotFoundError, NotADirectoryError):
            continue
        names.extend(f"{table}/{entry}" for entry in entries if entry.endswith(".manifest"))
    return tuple(sorted(names))


def distance_to_similarity(distance: float) -> float:
    """Return the cosine similarity for a ``distances`` value from :meth:`DrawerStore.query`.

    LanceDB's default metric is squared L2 and every MemPalace embedder
    L2-normalizes its vectors, so ``distance = 2 - 2 * cosine``. The result is
    rounded to 3 decimals: 1.0 is identical direction, 0.0 is unrelated
    (orthogonal), and -1.0 is opposite. Every user-visible similarity score and
    every similarity threshold must go through this function.
    """
    return round(1.0 - float(distance) / 2.0, 3)


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

    def replace_mined_sources(
        self,
        source_files,
        wing: str,
        ids: List[str],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ) -> None:
        """Upsert mined rows and drop the other mined rows of *source_files* in one commit.

        The default is not atomic: it deletes each source's mined rows, then upserts.
        """
        for source_file in dict.fromkeys(source_files):
            self.delete_by_source_file(source_file, wing, mined_rows_only=True)
        self.upsert(ids=ids, documents=documents, metadatas=metadatas)

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
        intent_rerank: bool = True,
    ) -> Dict[str, List[List]]:
        """
        Semantic search. Returns nested lists (one per query text):
          ids: [[id, ...]]
          documents: [[doc, ...]]
          metadatas: [[meta, ...]]
          distances: [[dist, ...]]  (squared L2; see distance_to_similarity)

        intent_rerank: apply the deterministic code-retrieval rerank
        (retrieval_rerank.py) to .NET project-file and CamelCase symbol-intent
        queries. Pass False for plain cosine order (natural-language search,
        duplicate checks).
        """

    @abstractmethod
    def delete(self, ids: List[str]) -> int:
        """Delete drawers by exact ID. Returns the count of deleted drawers."""

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

    def scan_wing_metadata(self, wing: str, columns: List[str]) -> Optional[List[Dict[str, Any]]]:
        """Return *columns* of every drawer in *wing* without text or vectors.

        Returns None when the backend cannot project columns; the base class does not.
        """
        return None

    def delete_by_source_file(
        self, source_file: str, wing: str, *, mined_rows_only: bool = False
    ) -> int:
        """Delete all drawers for a given source_file within a wing. Returns deleted count.

        With *mined_rows_only*, only rows that project mining can regenerate are
        deleted; manual (``add_drawer``), diary, and other protected rows survive.
        """
        return 0

    def delete_by_source_files(self, source_files, wing: str, *, project_root=None) -> int:
        """Bulk-delete all drawers for a collection of source_file values within a wing.

        Fallback: iterates and calls delete_by_source_file() per file.
        Override in backends that support efficient batch deletion (e.g. LanceDB).
        Returns the total deleted row count.
        """
        if project_root is not None:
            return 0
        total = 0
        for sf in source_files:
            total += self.delete_by_source_file(sf, wing)
        return total

    def get_source_file_hashes(
        self, wing: str, *, project_root=None, protected_source_files: Optional[set] = None
    ) -> Optional[dict]:
        """Return {source_file: source_hash} for all drawers in wing.

        Unscoped calls return an empty dict if unsupported. Scoped calls return None
        when provenance assessment is unsupported. Override in LanceDB backend.
        """
        return None if project_root is not None else {}

    def get_source_file_layout(self, wing: str) -> Optional[dict]:
        """Return {source_file: {"strategies", "rooms", "legacy_compressed"}} for mined rows.

        Only rows that project mining can regenerate are described. Returns None
        when the backend cannot project this metadata.
        """
        return None

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
        default, palace_kg_path(palace_path), is used.
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
CANONICAL_EMBED_DIMENSIONS = 384
CANONICAL_EMBED_COMPATIBILITY_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
_CANONICAL_MODEL_ALIASES = frozenset({DEFAULT_EMBED_MODEL, CANONICAL_EMBED_MODEL})
_FASTEMBED_CACHE_LAYOUT_VERSION = 1
_FASTEMBED_CACHE_CHILD = Path("mempalace-fastembed") / "all-MiniLM-L6-v2-v1"
_FASTEMBED_PROVENANCE = ".mempalace-model.json"
_FASTEMBED_DOWNLOAD_METADATA = "files_metadata.json"
_FASTEMBED_REPOSITORY = "models--qdrant--all-MiniLM-L6-v2-onnx"
_FASTEMBED_REQUIRED_ARTIFACTS = (
    "config.json",
    "model.onnx",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
_FASTEMBED_HF_REPOSITORY = "qdrant/all-MiniLM-L6-v2-onnx"
# The reviewed files at CANONICAL_EMBED_MODEL_REVISION: name -> (size, git blob id, LFS
# sha256). A download is checked against these before the cache is trusted, so a
# change upstream (or a corrupted transfer) can never become the canonical model.
_FASTEMBED_PINNED_ARTIFACTS: dict[str, tuple[int, str, str | None]] = {
    "config.json": (650, "56c8c186de9040d4fea8daac2ca110f9d412bf04", None),
    "model.onnx": (
        90387630,
        "672677e74ea0ea5bc37e3698bd1c7f5f1550ac8a",
        "bbd7b466f6d58e646fdc2bd5fd67b2f5e93c0b687011bd4548c420f7bd46f0c5",
    ),
    "special_tokens_map.json": (695, "9bbecc17cabbcbd3112c14d6982b51403b264bfa", None),
    "tokenizer.json": (711661, "c17ed520ed8438736732a54957a69306b8822215", None),
    "tokenizer_config.json": (1433, "61e23f16c75ff9995b1d2f251d720c6146d21338", None),
}
BULK_DELETE_BATCH_SIZE = 500  # max source_file values per single IN-predicate delete

# Cleanup never prunes a table version that was the current version within this
# window (unless --unsafe-now), so a read in another process that started just
# before a mine optimized the palace can finish.  Every LanceStore handle reads the
# latest version at the start of each operation (strong consistency), so the window
# only has to outlast one in-flight read; a longer one keeps more compacted copies
# of the table on disk while a watcher re-mines often.
READER_VERSION_GRACE = timedelta(seconds=60)
# Lance applies a prune cutoff relative to its own clock, a moment after ours.
_PRUNE_CUTOFF_MARGIN = timedelta(seconds=1)
# Table.optimize() always prunes too; this horizon makes its compaction keep every version.
_RETAIN_ALL_VERSIONS = timedelta(days=36500)


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


_OFFLINE_MODE_VARIABLES = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")


def offline_mode_variables() -> tuple[str, ...]:
    """Return the Hugging Face offline switches that are set, in a stable order."""
    return tuple(name for name in _OFFLINE_MODE_VARIABLES if _env_truthy(name))


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
        "dimensions": CANONICAL_EMBED_DIMENSIONS,
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
        size_error = _fastembed_artifact_size_error(repository, snapshot)
        if size_error is not None:
            return size_error
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


def _fastembed_artifact_size_error(repository: Path, snapshot: Path) -> str | None:
    """Compare artifact sizes with the download metadata FastEmbed records, when present.

    A truncated or partially copied ``model.onnx`` keeps its name and provenance but
    cannot load; FastEmbed itself only checks these sizes when it can reach the network.
    ``tokenizer_config.json`` is normalized after download, so its size is not compared.
    """
    metadata_path = repository / _FASTEMBED_DOWNLOAD_METADATA
    if not metadata_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        return "download metadata is not a JSON object"
    for name in _FASTEMBED_REQUIRED_ARTIFACTS:
        if name == "tokenizer_config.json":
            continue
        entry = metadata.get(f"snapshots/{snapshot.name}/{name}")
        expected = entry.get("size") if isinstance(entry, dict) else None
        if isinstance(expected, int) and (snapshot / name).stat().st_size != expected:
            return f"runtime artifact size does not match its download metadata: {name}"
    return None


class CanonicalModelCacheError(RuntimeError):
    """Raised when the canonical FastEmbed cache is missing, not provenance-owned, or damaged."""


def _first_line(exc: BaseException, limit: int = 300) -> str:
    """Return one bounded line describing *exc* for a user-facing message."""
    lines = str(exc).strip().splitlines()
    text = lines[0].strip() if lines else type(exc).__name__
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _require_owned_canonical_fastembed_cache(root: Path | None = None) -> Path:
    cache_root = root or canonical_fastembed_cache_root()
    error = _canonical_fastembed_cache_error(cache_root)
    if error is not None:
        if root is None and orphaned_canonical_fastembed_caches():
            raise CanonicalModelCacheError(
                f"Canonical FastEmbed cache is not owned: {error}. An interrupted "
                "`fetch-model` left the previous cache set aside beside it. Run "
                "`mempalace-code fetch-model` to put it back, then retry."
            )
        raise CanonicalModelCacheError(
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
    """Allow preservation only when no link can escape the cache being renamed.

    A link whose target is missing but would stay inside the cache (a deleted blob)
    marks a partial cache, which is preserved like any other partial download.
    """
    if root.is_symlink() or not root.is_dir():
        return False
    try:
        resolved_root = Path(os.path.realpath(root))
        provenance = root / _FASTEMBED_PROVENANCE
        if provenance.is_symlink():
            return False
        for path in root.rglob("*"):
            if path.is_symlink() and not Path(os.path.realpath(path)).is_relative_to(resolved_root):
                return False
    except OSError:
        return False
    return True


def _remove_file_free_tree(root: Path) -> bool:
    """Remove *root* when it holds only directories; return whether it was removed.

    A failed download can leave an empty cache skeleton behind. Such a tree holds
    nothing worth preserving, so it is removed instead of quarantined; ``rmdir``
    refuses if anything appears concurrently.
    """
    if root.is_symlink() or not root.is_dir():
        return False
    directories: list[str] = []
    for current, subdirectories, files in os.walk(root, followlinks=False):
        if files or any(os.path.islink(os.path.join(current, name)) for name in subdirectories):
            return False
        directories.append(current)
    try:
        for directory in reversed(directories):
            os.rmdir(directory)
    except OSError:
        return False
    return True


def remove_empty_canonical_fastembed_cache_root() -> bool:
    """Remove a canonical cache root that holds no files, such as a failed download's."""
    return _remove_file_free_tree(canonical_fastembed_cache_root())


def quarantine_unowned_canonical_fastembed_cache() -> Path | None:
    """Atomically preserve a safe partial cache beside the canonical root.

    A root that holds no files is removed instead, so failed attempts do not pile up
    empty quarantine directories.
    """
    root = canonical_fastembed_cache_root()
    if not root.exists() and not root.is_symlink():
        return None
    if canonical_fastembed_cache_owned():
        return None
    if _remove_file_free_tree(root):
        return None
    if not _cache_tree_safe_to_quarantine(root):
        raise RuntimeError(
            f"Refusing to quarantine hostile embedding cache: {root}. "
            "Move it aside manually, then run `mempalace-code fetch-model`."
        )
    quarantine = root.with_name(f"{root.name}.quarantine-{uuid.uuid4().hex}")
    root.rename(quarantine)
    return quarantine


def set_aside_owned_canonical_fastembed_cache() -> Path | None:
    """Rename the owned canonical cache to a hidden sibling before a replacement download.

    The set-aside copy is restored with :func:`restore_set_aside_canonical_fastembed_cache`
    when the download fails and deleted with :func:`discard_set_aside_canonical_fastembed_cache`
    only after the replacement validates, so a working cache is never deleted first.
    """
    root = canonical_fastembed_cache_root()
    if not root.exists() and not root.is_symlink():
        return None
    if _canonical_fastembed_cache_error(root) is not None:
        raise RuntimeError(
            f"Refusing to replace unowned embedding cache: {root}. "
            "Move it aside manually, then run `mempalace-code fetch-model`."
        )
    set_aside = root.with_name(f".{root.name}.replace-{os.getpid()}-{uuid.uuid4().hex}")
    root.rename(set_aside)
    return set_aside


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _dead_process_siblings(kind: str) -> list[Path]:
    """Return ``.<root>.<kind>-<pid>-<id>`` siblings whose creating process no longer runs."""
    root = canonical_fastembed_cache_root()
    pattern = re.compile(rf"^\.{re.escape(root.name)}\.{kind}-(\d+)-[0-9a-f]{{32}}$")
    found = []
    try:
        entries = sorted(root.parent.iterdir()) if root.parent.is_dir() else []
    except OSError:
        return []
    for entry in entries:
        match = pattern.match(entry.name)
        if match and not entry.is_symlink() and entry.is_dir():
            if not _process_alive(int(match.group(1))):
                found.append(entry)
    return found


def orphaned_canonical_fastembed_caches() -> list[Path]:
    """Return caches set aside by a ``fetch-model`` process that no longer runs.

    ``fetch-model --force`` renames the working cache to ``.<root>.replace-<pid>-<id>``
    until its replacement validates. A process killed in that window leaves the copy
    behind; :func:`restore_orphaned_canonical_fastembed_cache` puts it back.
    """
    return _dead_process_siblings("replace")


def _discard_tool_download(root: Path, recovery: str) -> None:
    """Delete an incomplete or rejected download that ``fetch-model`` itself made at *root*.

    Only trees this tool created are passed here (a failed or interrupted download), never
    a cache the user supplied, so failed attempts cannot pile up preserved copies. The tree
    is renamed to a hidden ``.delete-`` sibling first; a leftover one is swept later.
    """
    if not root.exists() and not root.is_symlink():
        return
    if _remove_file_free_tree(root):
        return
    if not _cache_tree_safe_to_quarantine(root):
        raise RuntimeError(f"Refusing to delete hostile embedding cache: {root}. {recovery}")
    trash = root.with_name(f".{root.name}.delete-{os.getpid()}-{uuid.uuid4().hex}")
    root.rename(trash)
    shutil.rmtree(trash, ignore_errors=True)


def discard_failed_canonical_fastembed_download() -> None:
    """Delete what a failed or interrupted canonical download left at the cache root."""
    _discard_tool_download(
        canonical_fastembed_cache_root(),
        "Move it aside manually, then run `mempalace-code fetch-model`.",
    )


def restore_orphaned_canonical_fastembed_cache() -> tuple[Path | None, list[Path]]:
    """Put back or discard caches an interrupted ``fetch-model --force`` left set aside.

    When the canonical root is not a usable owned cache, the first orphan that validates
    is moved back; the interrupted run's incomplete download at the root is deleted
    first. Orphans that validate while an owned root exists are redundant copies and are
    deleted, as are hidden ``.delete-`` trees a killed process did not finish removing.
    Returns ``(restored orphan or None, orphans left in place because they do not validate)``.
    """
    root = canonical_fastembed_cache_root()
    for trash in _dead_process_siblings("delete"):
        shutil.rmtree(trash, ignore_errors=True)
    restored: Path | None = None
    kept: list[Path] = []
    for orphan in orphaned_canonical_fastembed_caches():
        if _canonical_fastembed_cache_error(orphan) is not None:
            kept.append(orphan)
            continue
        if _canonical_fastembed_cache_error(root) is None:
            shutil.rmtree(orphan)
            continue
        restore_set_aside_canonical_fastembed_cache(orphan)
        restored = orphan
    return restored, kept


def restore_set_aside_canonical_fastembed_cache(set_aside: Path) -> None:
    """Put a set-aside cache back after a failed replacement.

    Whatever the failed download left at the root was made by ``fetch-model`` after the
    working cache was set aside, so it is deleted rather than preserved.
    """
    root = canonical_fastembed_cache_root()
    _discard_tool_download(root, f"Move it aside manually, then move {set_aside} back to {root}.")
    set_aside.rename(root)


def discard_set_aside_canonical_fastembed_cache(set_aside: Path) -> bool:
    """Delete a set-aside cache once the replacement at the canonical root is owned.

    Returns False, keeping the copy, when either tree fails validation.
    """
    if _canonical_fastembed_cache_error(canonical_fastembed_cache_root()) is not None:
        return False
    if set_aside.is_symlink() or not set_aside.is_dir():
        return False
    if _canonical_fastembed_cache_error(set_aside) is not None:
        return False
    shutil.rmtree(set_aside)
    return True


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


def detect_installed_extras() -> frozenset[str]:
    """Infer optional capabilities from importable installed packages without writing state."""
    modules = {
        "watch": "watchfiles",
        "treesitter": "tree_sitter",
        "spellcheck": "autocorrect",
        "custom-models": "sentence_transformers",
    }
    return frozenset(extra for extra, module in modules.items() if find_spec(module) is not None)


def _uv_tool_receipt(prefix: Path | None = None) -> dict | None:
    """Return the ``[tool]`` table of the uv tool receipt in *prefix*, or None outside uv tool."""
    try:
        receipt = tomllib.loads(
            ((prefix or Path(sys.prefix)) / "uv-receipt.toml").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None
    tool = receipt.get("tool")
    return tool if isinstance(tool, dict) else None


def uv_tool_default_dirs(environ: Any = None) -> list[Path]:
    """Return the tool directories uv uses when ``UV_TOOL_DIR`` is not set."""
    env = os.environ if environ is None else environ
    xdg_data_home = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return [
        xdg_data_home / "uv" / "tools",
        Path.home() / "Library" / "Application Support" / "uv" / "tools",
    ]


def uv_tool_location_environment(
    prefix: Path | None = None, environ: Any = None
) -> tuple[tuple[str, str], ...]:
    """Return the ``UV_TOOL_DIR``/``UV_TOOL_BIN_DIR`` a uv command needs to find this install.

    Empty when *prefix* is not a uv tool environment or lives in uv's default tool
    directory; otherwise the directories are read from the environment's own receipt, so
    a printed or scheduled ``uv tool install`` updates this copy instead of adding one.
    """
    env_prefix = (prefix or Path(sys.prefix)).expanduser().resolve()
    tool = _uv_tool_receipt(env_prefix)
    if tool is None:
        return ()
    tool_dir = env_prefix.parent
    if any(_same_directory(tool_dir, root) for root in uv_tool_default_dirs(environ)):
        return ()
    values = [("UV_TOOL_DIR", str(tool_dir))]
    entrypoints = tool.get("entrypoints")
    for entry in entrypoints if isinstance(entrypoints, list) else ():
        path = entry.get("install-path") if isinstance(entry, dict) else None
        if isinstance(path, str) and entry.get("name") == "mempalace-code":
            values.append(("UV_TOOL_BIN_DIR", str(Path(path).parent)))
            break
    return tuple(values)


def _same_directory(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.expanduser().resolve()
    except OSError:
        return False


def _uv_tool_receipt_extras() -> frozenset[str] | None:
    """Return the extras a uv tool receipt records for mempalace-code, or None outside uv tool."""
    tool = _uv_tool_receipt()
    requirements = tool.get("requirements") if isinstance(tool, dict) else None
    for requirement in requirements if isinstance(requirements, list) else ():
        if isinstance(requirement, dict) and requirement.get("name") == "mempalace-code":
            extras = requirement.get("extras")
            if not isinstance(extras, list):
                return frozenset()
            return frozenset(item for item in extras if isinstance(item, str))
    return None


def _extra_requirements(extra: str) -> list[str]:
    """Return the requirement specifiers the installed metadata declares for *extra*."""
    from importlib import metadata

    try:
        declared = metadata.requires("mempalace-code") or []
    except metadata.PackageNotFoundError:
        return []
    marker = re.compile(r"""^\s*extra\s*==\s*["']([^"']+)["']\s*$""")
    requirements = []
    for entry in declared:
        requirement, _, condition = entry.partition(";")
        match = marker.match(condition)
        if match and match.group(1) == extra:
            requirements.append(requirement.strip().replace(" ", ""))
    return requirements


def _pipx_inject_command(extra: str) -> str | None:
    """Return a ``pipx inject`` command when this interpreter runs in a pipx-managed venv."""
    prefix = Path(sys.prefix)
    if not (prefix / "pipx_metadata.json").is_file():
        return None
    requirements = _extra_requirements(extra)
    if not requirements:
        return None
    pipx_home = prefix.parent.parent
    configured = os.environ.get("PIPX_HOME")
    same_home = False
    if configured:
        try:
            same_home = Path(configured).expanduser().resolve() == pipx_home.resolve()
        except OSError:
            same_home = False
    # pipx finds the venv through PIPX_HOME; name it whenever the shell might not.
    home = "" if same_home else f"PIPX_HOME={shlex.quote(str(pipx_home))} "
    packages = " ".join(shlex.quote(requirement) for requirement in requirements)
    return f"{home}pipx inject {shlex.quote(prefix.name)} {packages}"


def extra_install_command(extra: str) -> str:
    """Return one command that adds *extra* to the installation running mempalace-code.

    ``uv tool`` rebuilds its environment from the requested spec, so the extra is
    requested together with every extra the receipt lists or this environment has
    installed (as ``update apply`` does), at the running version. A pipx venv is changed
    only through pipx (``pipx inject`` with the extra's declared requirements), so pipx
    keeps track of it. Every other environment installs into this interpreter rather than
    whichever ``python`` is first on PATH, pinned to the running version; an environment
    without pip (``uv venv``) gets the equivalent ``uv pip`` form.
    """
    receipt_extras = _uv_tool_receipt_extras()
    if receipt_extras is not None:
        extras = ",".join(sorted(receipt_extras | detect_installed_extras() | {extra}))
        # A custom tool directory must be named, or uv installs a second copy elsewhere.
        location = "".join(
            f"{name}={shlex.quote(value)} " for name, value in uv_tool_location_environment()
        )
        return f"{location}uv tool install --force " + shlex.quote(
            f"mempalace-code[{extras}]=={__version__}"
        )
    pipx_command = _pipx_inject_command(extra)
    if pipx_command is not None:
        return pipx_command
    python = shlex.quote(sys.executable)
    requirement = shlex.quote(f"mempalace-code[{extra}]=={__version__}")
    if find_spec("pip") is None:
        return f"uv pip install --python {python} {requirement}"
    return f"{python} -m pip install {requirement}"


def preflight_embed_model(model_name: str) -> None:
    """Fail explicit custom models before LanceDB or filesystem mutation."""
    if is_canonical_embed_model(model_name):
        return
    try:
        importlib.import_module("sentence_transformers")
    except ImportError as exc:
        raise RuntimeError(
            "Custom embedding model support is not installed. Run exactly: "
            f"{extra_install_command('custom-models')}"
        ) from exc


_EMBED_MODEL_FIELD_METADATA = b"mempalace.embed_model"


class PalaceEmbeddingModelError(CanonicalModelCacheError):
    """A palace's recorded embedding model conflicts with the requested one or cannot load.

    It deliberately shares :class:`CanonicalModelCacheError` handling: the message names its
    own recovery, and palace repair cannot fix (and would re-embed over) a model problem.
    """


def _recordable_model_name(model_name: str) -> str:
    return CANONICAL_EMBED_MODEL if is_canonical_embed_model(model_name) else model_name


def _same_embed_model(left: str, right: str) -> bool:
    """Return whether two model names select the same embedding model."""
    if is_canonical_embed_model(left) and is_canonical_embed_model(right):
        return True
    if left == right:
        return True
    if _is_existing_model_path(left) and _is_existing_model_path(right):
        return os.path.realpath(os.path.expanduser(left)) == os.path.realpath(
            os.path.expanduser(right)
        )
    return False


def _table_embedding_record(table: Any) -> tuple[str | None, int | None]:
    """Return the (recorded model, vector dimension) of a drawers table schema."""
    try:
        field = table.schema.field("vector")
    except (KeyError, AttributeError):
        return None, None
    raw = (field.metadata or {}).get(_EMBED_MODEL_FIELD_METADATA)
    model = raw.decode("utf-8", "replace") if raw else None
    dim = getattr(field.type, "list_size", None)
    return model, dim if isinstance(dim, int) and dim > 0 else None


class CanonicalModelDownloadError(CanonicalModelCacheError):
    """The pinned canonical model could not be downloaded or did not match its review.

    ``reason`` says what went wrong; the full message adds the recovery, so a lazy
    first-use download (``mine``/``search``/MCP) fails with one self-explaining line.
    ``retryable`` is False when trying again cannot help, such as when the reviewed
    revision is no longer published.
    """

    def __init__(self, reason: str, *, retryable: bool):
        if retryable:
            recovery = "Run `mempalace-code fetch-model` while online, then retry."
        else:
            recovery = (
                "Copy a prepared cache from a machine that has one "
                "(docs/OFFLINE_USAGE.md, Option A), or upgrade to a mempalace-code release "
                "that pins an available revision."
            )
        super().__init__(f"Could not download the embedding model: {reason}. {recovery}")
        self.reason = reason
        self.retryable = retryable


def _pinned_artifact_mismatch(path: Path, name: str) -> str | None:
    size, blob_id, sha256 = _FASTEMBED_PINNED_ARTIFACTS[name]
    if not path.is_file():
        return f"{name} is missing"
    if path.stat().st_size != size:
        return f"{name} has {path.stat().st_size} bytes, expected {size}"
    digest = hashlib.sha256() if sha256 else hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != (sha256 or blob_id):
        return f"{name} content differs from the reviewed file"
    return None


def _write_cache_file(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _download_pinned_canonical_snapshot() -> None:
    """Download exactly the reviewed canonical revision into the canonical cache root.

    The download names ``CANONICAL_EMBED_MODEL_REVISION`` explicitly, so new commits on
    the upstream ``main`` branch never change what is installed. Every file is checked
    against the reviewed sizes and digests; then ``refs/main`` and FastEmbed's size
    metadata are written so FastEmbed loads this snapshot with ``local_files_only``.
    """
    from huggingface_hub import snapshot_download

    hub_errors: Any
    try:
        hub_errors = importlib.import_module("huggingface_hub.errors")
    except ImportError:  # older huggingface_hub releases kept their errors in utils
        hub_errors = importlib.import_module("huggingface_hub.utils")

    root = canonical_fastembed_cache_root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        snapshot = Path(
            cast(
                "str",
                snapshot_download(
                    repo_id=_FASTEMBED_HF_REPOSITORY,
                    revision=CANONICAL_EMBED_MODEL_REVISION,
                    cache_dir=str(root),
                    allow_patterns=list(_FASTEMBED_PINNED_ARTIFACTS),
                ),
            )
        )
    except hub_errors.LocalEntryNotFoundError:
        raise  # Hugging Face could not be reached: a network problem, worth retrying.
    except (
        hub_errors.RevisionNotFoundError,
        hub_errors.RepositoryNotFoundError,
        hub_errors.EntryNotFoundError,
    ) as exc:
        # An invalid HF_TOKEN makes Hugging Face answer 401, reported as a missing repository.
        token_hint = (
            "; if HF_TOKEN is set, check that it is valid"
            if isinstance(exc, hub_errors.RepositoryNotFoundError)
            and not isinstance(exc, hub_errors.RevisionNotFoundError)
            else ""
        )
        raise CanonicalModelDownloadError(
            f"the reviewed model revision {CANONICAL_EMBED_MODEL_REVISION} of "
            f"{_FASTEMBED_HF_REPOSITORY} is not available from Hugging Face "
            f"({_first_line(exc)}), so retrying will not help{token_hint}",
            retryable=False,
        ) from exc
    repository = root / _FASTEMBED_REPOSITORY
    expected = repository / "snapshots" / CANONICAL_EMBED_MODEL_REVISION
    if snapshot.resolve() != expected.resolve():
        raise CanonicalModelDownloadError(
            f"the model download landed outside the pinned snapshot ({snapshot})",
            retryable=False,
        )
    for name in _FASTEMBED_PINNED_ARTIFACTS:
        mismatch = _pinned_artifact_mismatch(expected / name, name)
        if mismatch is not None:
            raise CanonicalModelDownloadError(
                f"the downloaded model does not match reviewed revision "
                f"{CANONICAL_EMBED_MODEL_REVISION} (a corrupted or intercepted transfer): "
                f"{mismatch}",
                # A published revision never changes, so only damaged bytes can be retried.
                retryable=not mismatch.endswith(" is missing"),
            )
    metadata = {
        f"snapshots/{CANONICAL_EMBED_MODEL_REVISION}/{name}": {"size": size, "blob_id": blob}
        for name, (size, blob, _sha256) in _FASTEMBED_PINNED_ARTIFACTS.items()
    }
    (repository / "refs").mkdir(exist_ok=True)
    _write_cache_file(repository / "refs" / "main", CANONICAL_EMBED_MODEL_REVISION)
    _write_cache_file(repository / _FASTEMBED_DOWNLOAD_METADATA, json.dumps(metadata))


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
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        created = os.fstat(descriptor)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(canonical_fastembed_provenance(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
        current = temporary.lstat()
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != (created.st_dev, created.st_ino)
            or not temporary.resolve(strict=True).is_relative_to(resolved_root)
        ):
            raise RuntimeError("FastEmbed provenance temporary changed before installation")
        temporary.replace(path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    _require_owned_canonical_fastembed_cache(root)


def _configure_canonical_fastembed_padding(model: object) -> None:
    """Make FastEmbed's canonical ONNX tokenizer emit fixed-width batches."""
    recovery = (
        "Canonical FastEmbed tokenizer padding is incompatible. "
        "Run `mempalace-code fetch-model --force` while online, then retry."
    )
    try:
        tokenizer = cast("Any", model).model.tokenizer
        padding = tokenizer.padding
        if not isinstance(padding, dict):
            raise TypeError("tokenizer padding is unavailable")
        preserved = {
            name: padding[name]
            for name in ("direction", "pad_id", "pad_type_id", "pad_token", "pad_to_multiple_of")
        }
        tokenizer.enable_padding(length=CANONICAL_EMBED_MAX_LENGTH, **preserved)
        configured = tokenizer.padding
        if (
            not isinstance(configured, dict)
            or configured.get("length") != CANONICAL_EMBED_MAX_LENGTH
        ):
            raise ValueError("tokenizer rejected fixed padding length")
        if any(configured.get(name) != value for name, value in preserved.items()):
            raise ValueError("tokenizer changed canonical padding metadata")
    except Exception as exc:
        raise RuntimeError(recovery) from exc


def _disable_onnxruntime_telemetry() -> None:
    """Keep ONNX Runtime from creating its local usage-event store under HOME.

    ONNX Runtime's POSIX telemetry (observed with the 1.29 and 1.30 macOS wheels) opens a
    SQLite event queue and device id under HOME, on macOS in
    ``~/Library/Application Support/Microsoft/DeveloperTools/.onnxruntime/``, as soon as
    the module is imported. It reads ``ORT_DISABLE_TELEMETRY`` at that import, so this
    runs before FastEmbed imports it. An explicit user value is kept.
    """
    os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")


class _FastEmbedder:
    """CPU-only FastEmbed adapter for the canonical MiniLM aliases."""

    def __init__(self, *, local_files_only: bool | None = None):
        _disable_onnxruntime_telemetry()
        from fastembed import TextEmbedding

        explicit_offline = _env_truthy("HF_HUB_OFFLINE") or _env_truthy("TRANSFORMERS_OFFLINE")
        offline = explicit_offline if local_files_only is None else local_files_only
        cache_root = canonical_fastembed_cache_root()
        if offline or cache_root.exists() or cache_root.is_symlink():
            _require_owned_canonical_fastembed_cache()
        else:
            # FastEmbed would download the moving ``main`` branch; fetch the reviewed
            # revision instead and only ever load from the validated local snapshot.
            try:
                _download_pinned_canonical_snapshot()
                _write_canonical_provenance()
            except BaseException as exc:
                # The root did not exist before, so what is there now is this run's
                # failed download: delete it so the next attempt starts clean.
                try:
                    discard_failed_canonical_fastembed_download()
                except (OSError, RuntimeError):
                    pass  # the next fetch-model names and handles what remains
                if isinstance(exc, CanonicalModelDownloadError) or not isinstance(exc, Exception):
                    raise
                raise CanonicalModelDownloadError(
                    f"the download did not complete ({_first_line(exc)}); check network "
                    "access to Hugging Face",
                    retryable=True,
                ) from exc
        kwargs = {
            "model_name": CANONICAL_EMBED_MODEL,
            "cache_dir": str(cache_root),
            "providers": ["CPUExecutionProvider"],
            "cuda": False,
            "local_files_only": True,
        }
        try:
            model = TextEmbedding(**kwargs)
            _configure_canonical_fastembed_padding(model)
        except Exception as exc:
            # The owned cache passed validation but its model cannot load (for example
            # a corrupted model.onnx): name the cache, not the palace, as the cause.
            raise CanonicalModelCacheError(
                f"Canonical FastEmbed model cache failed to load: {_first_line(exc)}. "
                f"Cache: {cache_root}. "
                "Run `mempalace-code fetch-model` while online, then retry."
            ) from exc
        _require_owned_canonical_fastembed_cache()
        self._model = model

    def ndims(self) -> int:
        return CANONICAL_EMBED_DIMENSIONS

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

    def __init__(self, model_name: str, *, from_palace_record: bool = False):
        preflight_embed_model(model_name)
        self._model_name = model_name
        # A model named only by palace data (not by the caller) is untrusted input: it is
        # loaded from local files without remote code, and never downloaded.
        self._from_palace_record = from_palace_record
        self._model = self._load_model()
        self._ndims: int | None = None

    def _load_model(self):
        SentenceTransformer = importlib.import_module("sentence_transformers").SentenceTransformer

        explicit_offline = _env_truthy("HF_HUB_OFFLINE") or _env_truthy("TRANSFORMERS_OFFLINE")
        is_local_path = _is_existing_model_path(self._model_name)
        kwargs = {"device": "cpu", "trust_remote_code": not self._from_palace_record}

        try:
            return SentenceTransformer(
                self._model_name,
                local_files_only=True,
                **kwargs,
            )
        except Exception:
            if explicit_offline or is_local_path or self._from_palace_record:
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


def _canonical_project_root(project_root: object) -> Optional[Path]:
    try:
        if not isinstance(project_root, (str, os.PathLike)):
            return None
        root_text = os.fspath(project_root)
        if not isinstance(root_text, str) or not root_text:
            return None
        root = Path(root_text)
        if not root.is_absolute():
            return None
        resolved_root = root.resolve(strict=False)
        root_stat = resolved_root.lstat()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if str(root) != str(resolved_root) or not stat.S_ISDIR(root_stat.st_mode):
        return None
    return resolved_root


def is_canonical_project_source(source_file: object, project_root: object) -> bool:
    """Return whether a stored source is a canonical descendant owned by the project.

    Nested Git roots deny ownership. The stale leaf and its deleted or renamed parent
    directories may be absent, but every existing intermediate directory must be a
    real directory whose marker is unambiguously absent. The leaf itself is not
    followed: a mined file later replaced by a symlink or another non-regular node is
    no longer a source, and its rows stay owned by the path that produced them.
    """
    if not isinstance(source_file, str) or not source_file:
        return False
    resolved_root = _canonical_project_root(project_root)
    if resolved_root is None:
        return False
    try:
        source = Path(source_file)
        if not source.is_absolute() or source.name in ("", ".", ".."):
            return False
        resolved_source = source.parent.resolve(strict=False) / source.name
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    if source_file != str(resolved_source) or resolved_root not in resolved_source.parents:
        return False

    current = resolved_source.parent
    while current != resolved_root:
        try:
            parent_stat = current.lstat()
        except (FileNotFoundError, NotADirectoryError):
            # A deleted or renamed directory: the stale sources beneath it are absent
            # too. Keep walking up; existing ancestors are still verified.
            current = current.parent
            continue
        except OSError:
            return False
        if not stat.S_ISDIR(parent_stat.st_mode):
            return False
        marker = current / ".git"
        try:
            marker_stat = marker.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        else:
            if stat.S_ISDIR(marker_stat.st_mode) or stat.S_ISREG(marker_stat.st_mode):
                return False
            return False
        current = current.parent
    return True


_FILE_HASH_RE = re.compile(r"^[0-9a-f]{32}$")


def is_valid_file_hash(value: object) -> bool:
    """Return whether a value matches the file-ingest BLAKE2b digest contract."""
    return isinstance(value, str) and _FILE_HASH_RE.fullmatch(value) is not None


def _is_regenerable_file_row(row: dict) -> bool:
    """Return whether projected metadata proves a row is regenerable file output."""
    source_hash = row.get("source_hash")
    return (
        row.get("ingest_mode") == "file"
        and row.get("type") == ""
        and is_valid_file_hash(source_hash)
    )


# Every chunker_strategy project mining has written (<= 1.14: *_v1, 1.15+: *_v2, and the
# per-symbol code chunkers regex_structural_v3/treesitter_v3; keep in sync with
# mining.chunkers.FILE_CHUNKER_STRATEGIES). Rows written before project rows carried
# ingest_mode="file" are recognised by these names.
_FILE_MINING_CHUNKER_STRATEGIES = (
    "dotnet_project_xml_v1",
    "regex_structural_v1",
    "treesitter_adaptive_v1",
    "treesitter_v1",
    "dotnet_project_xml_v2",
    "regex_structural_v2",
    "treesitter_adaptive_v2",
    "treesitter_v2",
    "regex_structural_v3",
    "treesitter_v3",
)
# Strategies of drawers no miner can regenerate; replacements must never delete them.
_PROTECTED_CHUNKER_STRATEGIES = ("manual_v1", "diary_v1")


def is_legacy_compressed(meta) -> bool:
    """Return whether a ``compress`` from before 1.15.0 replaced this drawer's text with AAAK.

    Those releases stored ``original_tokens``/``compression_ratio`` together with the AAAK
    text, and nothing else writes them, so they mark drawers whose verbatim text is gone.
    """
    try:
        original_tokens = int(meta.get("original_tokens", 0) or 0)
        ratio = float(meta.get("compression_ratio", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    return original_tokens > 0 or ratio != 0.0


def _is_mined_file_row(row: dict) -> bool:
    """Python mirror of _MINED_FILE_ROW_SQL for projected metadata rows."""
    ingest_mode = row.get("ingest_mode")
    file_provenance = ingest_mode == "file" or (
        ingest_mode == "" and row.get("chunker_strategy") in _FILE_MINING_CHUNKER_STRATEGIES
    )
    return file_provenance and row.get("type") == "" and is_valid_file_hash(row.get("source_hash"))


def _meta_arrow_types() -> dict:
    """Return the PyArrow type map for _META_FIELD_SPEC type tags.

    Single source of truth for the string→pa.DataType mapping used wherever
    _META_FIELD_SPEC type tags are resolved to PyArrow types.  Kept as a
    function so pyarrow stays a lazy import.
    """
    import pyarrow as pa

    return {"string": pa.string(), "int32": pa.int32(), "float32": pa.float32()}


def _target_drawer_schema(dim: int, embed_model: str | None = None):
    """Return the canonical PyArrow schema for a new drawers table.

    Used only by the new-table creation path in ``LanceStore._open_or_create()``.
    The migration path for existing tables uses ``_META_FIELD_SPEC`` directly so it
    does not need embedding dimensions.  Any new column additions must be made in
    ``_META_FIELD_SPEC`` only. With *embed_model*, the vector field records the model
    that embeds the palace, so later opens use it instead of the default.
    """
    import pyarrow as pa

    arrow_types = _meta_arrow_types()
    vector_metadata = (
        {_EMBED_MODEL_FIELD_METADATA: _recordable_model_name(embed_model).encode("utf-8")}
        if embed_model
        else None
    )
    fields = [
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), dim), metadata=vector_metadata),
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


def _version_timestamps(versions: list) -> Optional[List[datetime]]:
    """Return UTC version timestamps, or None when any is unknown or out of order."""
    stamps: List[datetime] = []
    for version in versions:
        timestamp = version.get("timestamp") if isinstance(version, dict) else None
        if not isinstance(timestamp, datetime):
            return None
        if timestamp.tzinfo is None:
            timestamp = timestamp.astimezone()
        stamps.append(timestamp.astimezone(UTC))
    if any(later < earlier for earlier, later in zip(stamps, stamps[1:])):
        return None
    return stamps


def _prunable_before(versions: list, now: datetime, older_than: timedelta) -> Optional[datetime]:
    """Return the reader-safe prune anchor when some version may be pruned, else None.

    A version is current from its own timestamp until the next version's.  Every
    version older than the newest version created at least READER_VERSION_GRACE
    ago therefore stopped being current before that grace began, so no reader can
    still be on it.  The anchor is that newest version's timestamp; a version is
    pruned only when it is older than both the anchor and *older_than*.
    Unknown or non-monotonic timestamps prune nothing.
    """
    stamps = _version_timestamps(versions)
    if not stamps or len(stamps) < 2:
        return None
    settled = [stamp for stamp in stamps if stamp <= now - READER_VERSION_GRACE]
    if not settled:
        return None
    anchor = settled[-1]
    margin = timedelta(0) if anchor == stamps[-1] else _PRUNE_CUTOFF_MARGIN
    cutoff = min(anchor - margin, now - older_than)
    if not any(stamp < cutoff for stamp in stamps[:-1]):
        return None
    return anchor


def cleanup_plan(
    versions: list, now: datetime, older_than_days: int, *, unsafe_now: bool = False
) -> dict:
    """Predict what ``cleanup_stale_fragments`` removes from *versions* at *now*.

    Returns ``{"remove": [...], "kept_for_readers": [...], "compacts_first": bool}``
    with version numbers.  ``kept_for_readers`` are versions old enough for
    *older_than_days* that the reader grace keeps: versions current within
    READER_VERSION_GRACE, plus those committed within _PRUNE_CUTOFF_MARGIN
    before the newest settled version once compaction has committed newer ones.
    ``compacts_first`` says compaction commits new versions before the prune.
    """
    numbers = [
        version.get("version") if isinstance(version, dict) else None for version in versions
    ]
    compacts_first = bool(versions) and not _latest_version_is_compact(versions)
    if unsafe_now:
        return {"remove": numbers[:-1], "kept_for_readers": [], "compacts_first": compacts_first}
    older_than = timedelta(days=older_than_days)
    stamps = _version_timestamps(versions)
    if not stamps:
        return {"remove": [], "kept_for_readers": [], "compacts_first": compacts_first}
    old_enough = [n for n, stamp in zip(numbers[:-1], stamps[:-1]) if stamp < now - older_than]
    remove: list = []
    anchor = _prunable_before(versions, now, older_than)
    if anchor is not None:
        still_latest = anchor == stamps[-1] and not compacts_first
        margin = timedelta(0) if still_latest else _PRUNE_CUTOFF_MARGIN
        cutoff = min(anchor - margin, now - older_than)
        remove = [n for n, stamp in zip(numbers[:-1], stamps[:-1]) if stamp < cutoff]
    kept = [n for n in old_enough if n not in remove]
    return {"remove": remove, "kept_for_readers": kept, "compacts_first": compacts_first}


def _latest_version_is_compact(versions: list) -> bool:
    """True when the latest version has one fragment and no deletion files.

    Table.optimize() then has nothing to compact: it rewrites no data and commits
    no version, so its prune step runs alone.  Unknown metadata counts as not compact.
    """
    latest = versions[-1] if versions else None
    metadata = latest.get("metadata") if isinstance(latest, dict) else None
    if not isinstance(metadata, dict):
        return False
    try:
        fragments = int(metadata["total_fragments"])
        deletion_files = int(metadata["total_deletion_files"])
    except (KeyError, TypeError, ValueError):
        return False
    return fragments <= 1 and deletion_files == 0


def _is_missing_fragment_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in ("no such file", "object not found", "io error", "not found"))


# ─── SQL filter literals ──────────────────────────────────────────────────────
# Every value interpolated into a LanceDB filter goes through sql_literal() and every
# column name through _sql_identifier(). Lance SQL string literals keep backslashes
# literal, so doubling the single quote is the complete escape.

_SQL_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Ids per ``id IN (...)`` filter, so a large lookup never builds one huge predicate.
_ID_FILTER_BATCH = 500


class DuplicateDrawerIdError(ValueError):
    """Raised when an add would store a drawer id that already exists or repeats."""

    def __init__(self, ids: List[str], *, within_call: bool = False) -> None:
        self.ids = list(ids)
        shown = ", ".join(repr(drawer_id) for drawer_id in self.ids[:5])
        more = f" (+{len(self.ids) - 5} more)" if len(self.ids) > 5 else ""
        where = "repeated within one add call" if within_call else "already stored"
        super().__init__(f"duplicate drawer id {where}: {shown}{more}")


def sql_literal(value: object) -> str:
    """Return *value* as a LanceDB SQL literal.

    This is the one quoting helper for values interpolated into LanceDB filters:
    strings are single-quoted with embedded quotes doubled, numbers are rendered
    unquoted, and any other type is rejected.
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"non-finite number cannot be used in a filter: {value!r}")
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(f"unsupported filter value type: {type(value).__name__}")


def _sql_identifier(name: object) -> str:
    """Return *name* when it is a plain column identifier; reject anything else."""
    if not isinstance(name, str) or not _SQL_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"invalid filter column name: {name!r}")
    return name


def _sql_in(column: str, values: List[Any]) -> str:
    """Return ``column IN (...)`` with every value quoted by :func:`sql_literal`."""
    return f"{_sql_identifier(column)} IN ({', '.join(sql_literal(v) for v in values)})"


# Rows project mining produced and may replace: current file rows plus legacy file rows.
# Manual (manual_v1), diary (diary_v1), typed, and hash-less rows never match.
_MINED_FILE_ROW_SQL = (
    "(ingest_mode = 'file' OR (ingest_mode = '' AND "
    + _sql_in("chunker_strategy", list(_FILE_MINING_CHUNKER_STRATEGIES))
    + ")) AND type = '' AND regexp_like(source_hash, '^[0-9a-f]{32}$')"
)


def _drawer_ids(ids: Any) -> List[str]:
    """Return *ids* as a list after checking that every id is a non-empty string."""
    if isinstance(ids, str):
        raise TypeError("drawer ids must be a list of strings, not a single string")
    out = list(ids)
    for drawer_id in out:
        if not isinstance(drawer_id, str) or not drawer_id:
            raise ValueError(f"drawer id must be a non-empty string, got {drawer_id!r}")
    return out


def unique_drawer_rows(
    ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]]
) -> tuple[List[str], List[str], List[Dict[str, Any]], int, List[tuple[str, str]]]:
    """Return extracted rows in a form :meth:`LanceStore.add` accepts, keeping all content.

    Palaces written before ids were enforced unique can hold repeated or empty ids.
    A row equal to an earlier row with the same id (same text and metadata) is dropped;
    any other row whose id is empty or already used keeps its text and metadata under
    the first free id ``<id>__dup<n>`` (``drawer__dup<n>`` for an empty id).

    Returns ``(ids, documents, metadatas, dropped_count, [(old_id, new_id), ...])``.
    """
    taken = set(ids)
    kept: Dict[str, List[tuple[str, Dict[str, Any]]]] = {}
    out_ids: List[str] = []
    out_docs: List[str] = []
    out_metas: List[Dict[str, Any]] = []
    dropped = 0
    renamed: List[tuple[str, str]] = []
    for drawer_id, doc, meta in zip(ids, documents, metadatas):
        same_id = kept.setdefault(drawer_id, [])
        if (doc, meta) in same_id:
            dropped += 1
            continue
        same_id.append((doc, meta))
        new_id = drawer_id
        if not drawer_id or len(same_id) > 1:
            base = drawer_id or "drawer"
            n = 1
            while f"{base}__dup{n}" in taken:
                n += 1
            new_id = f"{base}__dup{n}"
            taken.add(new_id)
            renamed.append((drawer_id, new_id))
        out_ids.append(new_id)
        out_docs.append(doc)
        out_metas.append(meta)
    return out_ids, out_docs, out_metas, dropped, renamed


class LanceStore(DrawerStore):
    """
    Crash-safe drawer storage using LanceDB.

    Data is stored in Lance columnar format with proper transactions —
    an interrupted write does not corrupt the entire dataset.

    A palace created by this class records its embedding model on the vector column;
    opening it without ``embed_model`` uses that model, and opening it with a different
    one is refused.
    """

    # Embedding-model state; __init__ sets these per palace.
    _palace_path: str = ""
    _requested_model: Optional[str] = None
    _model_name: str = DEFAULT_EMBED_MODEL
    _model_from_record: bool = False
    _table_dim: Optional[int] = None

    def __init__(
        self,
        palace_path: str,
        create: bool = True,
        embed_model: Optional[str] = None,
        read_only: bool = False,
    ):
        palace_path = expand_palace_path(palace_path)
        self._palace_path = palace_path
        self._requested_model = embed_model
        self._model_name = embed_model or DEFAULT_EMBED_MODEL
        # True when the model was read from the palace's own record, not requested.
        self._model_from_record = False
        self._table_dim: int | None = None
        preflight_embed_model(self._model_name)
        import lancedb

        self._read_only = read_only
        self._embedder: _EmbedderProtocol | None = None  # lazy — initialized by _ensure_embedder()
        self._db: _LanceDBConnectionProtocol | None = None
        self._table: _LanceTableProtocol | None = None

        lance_dir = os.path.join(palace_path, "lance")
        self._palace_path = palace_path
        self._lance_dir = lance_dir
        self._table_dir = os.path.join(lance_dir, f"{_LANCE_TABLE}.lance")
        if read_only and not os.path.isdir(lance_dir):
            # Palace absent — return a stub without touching the filesystem.
            return
        if create and not read_only and not os.path.isdir(self._table_dir):
            # A new table needs the model's dimensions: load it before LanceDB writes
            # lance/, so a missing model leaves no bookkeeping-only palace behind.
            self._ensure_embedder()

        # read_consistency_interval=0: every read starts from the latest committed
        # version, so long-lived handles (MCP server, watcher) see other processes'
        # writes and never read a version that a later cleanup may prune.
        self._db = cast(
            "_LanceDBConnectionProtocol",
            lancedb.connect(lance_dir, read_consistency_interval=timedelta(0)),
        )
        self._table = self._open_or_create(create)

    def _get_embedder(self):
        """Load the provider selected by the existing embed_model contract."""
        if is_canonical_embed_model(self._model_name):
            return _FastEmbedder()
        return _SentenceTransformerEmbedder(
            self._model_name, from_palace_record=self._model_from_record
        )

    @property
    def embed_model(self) -> str:
        """The embedding model this store embeds with: the palace's record, else the request."""
        return self._model_name

    def _validated_embedder(self) -> _EmbedderProtocol:
        """Load the embedder and refuse one whose vectors cannot match this palace's column."""
        if self._model_from_record:
            try:
                preflight_embed_model(self._model_name)
            except RuntimeError as exc:
                raise PalaceEmbeddingModelError(
                    f"Palace {self._palace_path} records embedding model "
                    f"{self._model_name!r}, which could not be loaded: {exc}"
                ) from exc
        try:
            embedder = cast("_EmbedderProtocol", self._get_embedder())
        except CanonicalModelCacheError:
            raise
        except Exception as exc:
            if not self._model_from_record or is_canonical_embed_model(self._model_name):
                raise
            model = self._model_name
            raise PalaceEmbeddingModelError(
                f"Palace {self._palace_path} records embedding model {model!r}, which could "
                f"not be loaded from local files: {_first_line(exc)}. A model named only by "
                "palace data is never downloaded and runs without remote code. Download it "
                f"explicitly with `mempalace-code fetch-model --model {model}`, then retry; a "
                "model that needs remote code opens only through the Python API with "
                f"`LanceStore(path, embed_model={model!r})`."
            ) from exc
        produced = embedder.ndims()
        if self._table_dim is not None and produced != self._table_dim:
            raise PalaceEmbeddingModelError(self._dimension_mismatch_message(produced))
        return embedder

    def _dimension_mismatch_message(self, produced: int) -> str:
        palace = self._palace_path
        if self._model_from_record:
            return (
                f"Palace {palace} records embedding model {self._model_name!r}, but its "
                f"vectors are {self._table_dim}-dimensional and the model produces {produced}. "
                "Re-mine the content into a new palace to recover."
            )
        return (
            f"Palace {palace} stores {self._table_dim}-dimensional vectors, but embedding "
            f"model {self._model_name!r} produces {produced}: the palace was built with a "
            "different model and does not record which. Record it once with "
            f"`LanceStore({palace!r}, embed_model='<model that built it>')"
            ".record_embed_model()`; the CLI and MCP server then use it."
        )

    def _adopt_palace_model(self, table: _LanceTableProtocol) -> None:
        """Use the model the palace records; refuse an explicit request for another model."""
        recorded, self._table_dim = _table_embedding_record(table)
        if recorded is None:
            return
        if self._requested_model is None:
            if not _same_embed_model(recorded, self._model_name):
                self._embedder = None  # loaded for another model; reload on first use
            self._model_name = recorded
            self._model_from_record = True
            return
        if not _same_embed_model(self._requested_model, recorded):
            raise PalaceEmbeddingModelError(
                f"Palace {self._palace_path} was built with embedding model {recorded!r} "
                f"({self._table_dim or 'unknown'} dimensions) and cannot be opened with "
                f"{self._requested_model!r}. Open it with embed_model={recorded!r}, or re-mine "
                "the content into a new palace to change models."
            )

    def record_embed_model(self) -> str:
        """Record this store's embedding model in a palace created before models were recorded.

        Loads the model and checks that its vectors fit the palace before writing the record,
        so ``mempalace-code`` and the MCP server use the same model afterwards. Returns the
        recorded name; a palace that already records this model is left unchanged.
        """
        if self._read_only:
            raise RuntimeError("Cannot record the embedding model of a read-only LanceStore")
        table = self._require_table()
        recorded, _ = _table_embedding_record(table)
        name = _recordable_model_name(self._model_name)
        if recorded is not None:
            if not _same_embed_model(recorded, name):
                raise PalaceEmbeddingModelError(
                    f"Palace {self._palace_path} already records embedding model {recorded!r}."
                )
            return recorded
        self._ensure_embedder()
        table.replace_field_metadata("vector", {_EMBED_MODEL_FIELD_METADATA.decode("utf-8"): name})
        self._table = self._reopen_table()
        return name

    def _ensure_embedder(self) -> None:
        """Initialize the embedding model on first use.

        Suppresses noisy HF/safetensors output at the OS fd level so C-extension
        writes don't leak to stdout/stderr.
        """
        if self._embedder is not None:
            return
        with _EMBEDDER_STDIO_LOCK:
            if self._embedder is not None:
                return

            hf_logger = logging.getLogger("huggingface_hub")
            prev_level = hf_logger.level
            devnull: int | None = None
            old_stdout: int | None = None
            old_stderr: int | None = None
            redirect_attempted = False
            logger_changed = False
            try:
                old_stdout = os.dup(1)
                old_stderr = os.dup(2)
                devnull = os.open(os.devnull, os.O_WRONLY)
                hf_logger.setLevel(logging.ERROR)
                logger_changed = True
                sys.stdout.flush()
                sys.stderr.flush()
                redirect_attempted = True
                os.dup2(devnull, 1)
                os.dup2(devnull, 2)
                self._embedder = self._validated_embedder()
            finally:
                try:
                    if redirect_attempted:
                        try:
                            sys.stdout.flush()
                            sys.stderr.flush()
                        finally:
                            assert old_stdout is not None
                            assert old_stderr is not None
                            os.dup2(old_stdout, 1)
                            os.dup2(old_stderr, 2)
                finally:
                    for descriptor in (devnull, old_stdout, old_stderr):
                        if descriptor is not None:
                            os.close(descriptor)
                    if logger_changed:
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

    @contextmanager
    def _reading(self):
        """Turn a failed read of stored data into a PalaceReadError naming this palace.

        Rejected filters stay their original error: they are caller input, not damage.
        """
        try:
            yield
        except PalaceReadError:
            raise
        except Exception as exc:
            if _is_query_input_error(exc):
                raise
            raise PalaceReadError(self._palace_path, exc) from exc

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
                table = db.open_table(_LANCE_TABLE)
            except Exception as e:
                logger.debug("Table %r not found (read_only=True): %s", _LANCE_TABLE, e)
                return None
            self._adopt_palace_model(table)
            return table

        # Write path: open existing table first; embedder only needed for new-table creation.
        db = self._require_db()

        _existing_table: _LanceTableProtocol | None = None
        try:
            _existing_table = db.open_table(_LANCE_TABLE)
        except Exception as e:
            logger.debug("Table %r not found, will create: %s", _LANCE_TABLE, e)

        if _existing_table is not None:
            self._adopt_palace_model(_existing_table)
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
        target = _target_drawer_schema(dim, self._model_name)
        table = db.create_table(_LANCE_TABLE, schema=target, exist_ok=True)
        # exist_ok may return a table another process created meanwhile; honour its record.
        self._adopt_palace_model(table)
        return table

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
        with self._reading():
            return table.count_rows()

    def add(self, ids, documents, metadatas):
        """Insert new drawers; raise DuplicateDrawerIdError before writing on any id clash."""
        if self._read_only:
            raise RuntimeError("Cannot add to a read-only LanceStore")
        ids = _drawer_ids(ids)
        documents = list(documents)
        metadatas = list(metadatas)
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("ids, documents, and metadatas must have equal lengths")
        if not ids:
            return
        if len(set(ids)) != len(ids):
            repeated = sorted(drawer_id for drawer_id, n in Counter(ids).items() if n > 1)
            raise DuplicateDrawerIdError(repeated, within_call=True)
        table = self._require_table()
        stored = self._stored_ids(table, ids)
        if stored:
            raise DuplicateDrawerIdError(sorted(stored))

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

        ingest_modes = {metadata.get("ingest_mode", "") for metadata in metadatas}
        if len(ingest_modes) != 1 or not next(iter(ingest_modes)):
            raise ValueError("replacement rows must share one non-empty ingest_mode")
        protected = _sql_in("chunker_strategy", list(_PROTECTED_CHUNKER_STRATEGIES))
        # Only rows of the replacing ingest mode are replaced; manual and diary drawers
        # that merely cite the same source_file are never deleted.
        source_scope = (
            f"source_file = {sql_literal(source_file)} AND wing = {sql_literal(wing)}"
            f" AND ingest_mode = {sql_literal(next(iter(ingest_modes)))} AND NOT ({protected})"
        )

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

    def replace_mined_sources(self, source_files, wing, ids, documents, metadatas) -> None:
        """Upsert mined rows and drop the other mined rows of *source_files* in one commit.

        One merge_insert commits the new rows and deletes the stale project-mining rows
        of those sources and *wing* together, so a reader sees each file's old drawers
        or its new ones, never neither. Manual, diary and conversation rows that cite
        the same source_file are never deleted.
        """
        if self._read_only:
            raise RuntimeError("Cannot replace sources in a read-only LanceStore")
        sources = list(dict.fromkeys(source_files))
        if not sources:
            self.upsert(ids=ids, documents=documents, metadatas=metadatas)
            return
        if not (len(ids) == len(documents) == len(metadatas)):
            raise ValueError("ids, documents, and metadatas must have equal lengths")
        table = self._require_table()
        vectors = self._embed(list(documents))
        rows = []
        for id_, document, metadata, vector in zip(ids, documents, metadatas, vectors):
            row = self._meta_defaults(metadata)
            row["id"] = id_
            row["text"] = document
            row["vector"] = vector
            rows.append(row)
        scope = (
            f"{_sql_in('source_file', sources)} AND wing = {sql_literal(wing)}"
            f" AND {_MINED_FILE_ROW_SQL}"
        )

        def _execute_merge(target_table: _LanceTableProtocol) -> None:
            (
                target_table.merge_insert("id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .when_not_matched_by_source_delete(scope)
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
            ids = _drawer_ids(ids)
            if not ids:
                return {"ids": [], "documents": [], "metadatas": []}
            # Fetch by explicit IDs. Lookup errors propagate: treating a failed lookup
            # as "absent" would let callers re-add or skip ids they cannot see.
            with self._reading():
                results = self._rows_for_ids(table, ids)
        elif where is not None:
            sql = self._where_to_sql(where)
            with self._reading():
                results = table.search().where(sql).limit(limit).offset(offset).to_list()
        else:
            with self._reading():
                results = table.search().limit(limit).offset(offset).to_list()

        out_ids = [r["id"] for r in results]
        out: Dict[str, List] = {"ids": out_ids}

        if "documents" in include:
            out["documents"] = [r["text"] for r in results]
        if "metadatas" in include:
            out["metadatas"] = [{k: r.get(k, "") for k in _META_KEYS} for r in results]

        return out

    def query(self, query_texts, n_results=5, where=None, include=None, intent_rerank=True):
        table = self._table
        if table is None:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        include = include or []
        all_ids, all_docs, all_metas, all_dists = [], [], [], []

        for text in query_texts:
            vec = self._embed([text])[0]
            # Overfetch for project-file or symbol-intent queries so the reranker
            # has enough candidates to promote highly-relevant but lower-ranked rows.
            if intent_rerank and should_overfetch(text):
                fetch_limit = overfetch_limit(n_results)
            else:
                fetch_limit = n_results
            q = table.search(vec).limit(fetch_limit)
            if where:
                sql = self._where_to_sql(where)
                q = q.where(sql)

            with self._reading():
                results = q.to_list()

            if fetch_limit > n_results:
                results = rerank(results, text, n_results)

            ids = [r["id"] for r in results]
            docs = [r["text"] for r in results]
            metas = []
            dists = []

            for r in results:
                metas.append({k: r.get(k, "") for k in _META_KEYS})
                # LanceDB returns _distance as squared L2 (see distance_to_similarity)
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

    @staticmethod
    def _rows_for_ids(
        table: _LanceTableProtocol, ids: List[str], columns: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Return every stored row whose id is exactly one of *ids* (batched lookups)."""
        wanted = list(dict.fromkeys(ids))
        rows: List[Dict[str, Any]] = []
        for start in range(0, len(wanted), _ID_FILTER_BATCH):
            batch = wanted[start : start + _ID_FILTER_BATCH]
            query = table.search().where(_sql_in("id", batch))
            if columns is not None:
                query = query.select(columns)
            # Exact-id check: only rows whose id was requested are ever returned.
            batch_set = set(batch)
            rows.extend(row for row in query.limit(None).to_list() if row.get("id") in batch_set)
        return rows

    def _stored_ids(self, table: _LanceTableProtocol, ids: List[str]) -> set[str]:
        """Return the subset of *ids* already stored in *table*."""
        return {row["id"] for row in self._rows_for_ids(table, ids, columns=["id"])}

    def delete(self, ids) -> int:
        """Delete the drawers whose id is exactly one of *ids*; return the deleted row count.

        Each batch is verified before deletion: if its filter would match any row whose
        id was not requested, nothing in that batch is deleted and ValueError is raised.
        """
        if self._read_only:
            raise RuntimeError("Cannot delete from a read-only LanceStore")
        table = self._table
        ids = _drawer_ids(ids)
        if table is None or not ids:
            return 0
        deleted = 0
        wanted = list(dict.fromkeys(ids))
        for start in range(0, len(wanted), _ID_FILTER_BATCH):
            batch = wanted[start : start + _ID_FILTER_BATCH]
            predicate = _sql_in("id", batch)
            matched = [
                row["id"]
                for row in table.search().where(predicate).select(["id"]).limit(None).to_list()
            ]
            unexpected = set(matched) - set(batch)
            if unexpected:
                raise ValueError(
                    f"refusing to delete: id filter matched {len(unexpected)} unrequested row(s)"
                )
            if not matched:
                continue
            table.delete(predicate)
            deleted += len(matched)
        return deleted

    def delete_wing(self, wing: str) -> int:
        table = self._table
        if table is None:
            return 0
        predicate = f"wing = {sql_literal(wing)}"
        count = table.count_rows(predicate)
        if count == 0:
            return 0
        table.delete(predicate)
        return count

    def delete_by_source_file(
        self, source_file: str, wing: str, *, mined_rows_only: bool = False
    ) -> int:
        """Delete all drawers for a given source_file within a wing.

        With *mined_rows_only*, only regenerable project-mining rows are deleted.
        """
        table = self._table
        if table is None:
            return 0
        predicate = f"source_file = {sql_literal(source_file)} AND wing = {sql_literal(wing)}"
        if mined_rows_only:
            predicate += f" AND {_MINED_FILE_ROW_SQL}"
        count = table.count_rows(predicate)
        if count == 0:
            return 0
        table.delete(predicate)
        return count

    def delete_by_source_files(self, source_files, wing: str, *, project_root=None) -> int:
        """Bulk-delete drawers for a collection of source_file values within a wing.

        Deduplicates the input, then issues at most one count/delete predicate per
        BULK_DELETE_BATCH_SIZE files. Batches whose count is zero skip table.delete to
        avoid creating no-op Lance versions. Returns total deleted row count.
        """
        table = self._table
        if table is None:
            return 0

        paths = list(dict.fromkeys(source_files))  # dedupe, preserve insertion order
        if project_root is not None:
            if _canonical_project_root(project_root) is None:
                return 0
            paths = [path for path in paths if is_canonical_project_source(path, project_root)]
        if not paths:
            return 0

        total_deleted = 0

        for i in range(0, len(paths), BULK_DELETE_BATCH_SIZE):
            batch = paths[i : i + BULK_DELETE_BATCH_SIZE]
            predicate = f"{_sql_in('source_file', batch)} AND wing = {sql_literal(wing)}"
            if project_root is not None:
                predicate += (
                    " AND ingest_mode = 'file' AND type = ''"
                    " AND regexp_like(source_hash, '^[0-9a-f]{32}$')"
                )
            count = table.count_rows(predicate)
            if count == 0:
                continue
            table.delete(predicate)
            total_deleted += count

        return total_deleted

    def get_source_file_hashes(
        self, wing: str, *, project_root=None, protected_source_files: Optional[set] = None
    ) -> Optional[dict]:
        """Return {source_file: source_hash} for all drawers in wing.

        Uses LanceDB scan-time column projection — no vector scan.
        Deduplicates by taking the first hash per source_file.
        Scoped calls return None when the projection or project scope cannot be
        assessed. A successful scan with no eligible rows returns an empty dict.
        """
        table = self._table
        if table is None:
            return {}
        import pyarrow.compute as pc

        columns = ["source_file", "source_hash", "wing"]
        if project_root is not None:
            if _canonical_project_root(project_root) is None:
                return None
            columns.extend(["ingest_mode", "type"])
        try:
            try:
                arrow_tbl = self._scan_columns(table, columns)
            except Exception as exc:
                if not _is_missing_fragment_error(exc):
                    raise
                # A handle whose version was pruned elsewhere: reread from the latest.
                arrow_tbl = self._scan_columns(self._reopen_table(), columns)
        except Exception as exc:
            if project_root is not None:
                # A scoped destructive assessment cannot use a partial/legacy projection.
                return None
            logger.warning(
                "Stored file hashes for wing %r are unreadable (%s); "
                "incremental mining will re-process every file.",
                wing,
                exc,
            )
            return {}
        result: dict = {}
        if project_root is None:
            filtered = arrow_tbl.filter(pc.field("wing") == wing)
            for sf, sh in zip(
                filtered.column("source_file").to_pylist(),
                filtered.column("source_hash").to_pylist(),
            ):
                # A manual drawer citing a mined file has no file hash; prefer the
                # mined rows' hash so the file is not re-mined on every run.
                if sf not in result or (
                    not is_valid_file_hash(result[sf]) and is_valid_file_hash(sh)
                ):
                    result[sf] = sh
            return result

        protected: set[str] = set()
        for row in arrow_tbl.to_pylist():
            sf = row.get("source_file")
            if not is_canonical_project_source(sf, project_root):
                continue
            if not _is_regenerable_file_row(row):
                protected.add(sf)
                continue
            if row.get("wing") == wing and sf not in result:
                result[sf] = row["source_hash"]
        if protected_source_files is not None:
            protected_source_files.update(protected)
        return result

    def count_by(self, column: str) -> Dict[str, int]:
        table = self._table
        if table is None:
            return {}
        with self._reading():
            arrow_tbl = self._scan_columns(table, [column])
        result = arrow_tbl.group_by(column).aggregate([(column, "count")])
        d = result.to_pydict()
        return dict(zip(d[column], d[f"{column}_count"]))

    def count_by_pair(self, col_a: str, col_b: str) -> Dict[str, Dict[str, int]]:
        table = self._table
        if table is None:
            return {}
        with self._reading():
            arrow_tbl = self._scan_columns(table, [col_a, col_b])
        result = arrow_tbl.group_by([col_a, col_b]).aggregate([(col_b, "count")])
        d = result.to_pydict()
        out: Dict[str, Dict[str, int]] = {}
        for a, b, c in zip(d[col_a], d[col_b], d[f"{col_b}_count"]):
            out.setdefault(a, {})[b] = c
        return out

    def get_source_file_layout(self, wing: str) -> Optional[dict]:
        """Return {source_file: {"strategies", "rooms", "legacy_compressed"}} for mined rows.

        ``legacy_compressed`` is True when any of the file's drawers still holds text a
        pre-1.15.0 ``compress`` replaced (see :func:`is_legacy_compressed`). Column
        projection only (no vectors). Rows that project mining cannot regenerate are
        ignored. Returns None when the projection fails.
        """
        table = self._table
        if table is None:
            return {}
        columns = [
            "source_file",
            "wing",
            "room",
            "chunker_strategy",
            "ingest_mode",
            "type",
            "source_hash",
            "original_tokens",
            "compression_ratio",
        ]
        try:
            existing = set(table.schema.names)
            columns = [c for c in columns if c in existing]
            arrow_tbl = self._scan_columns(table, columns)
        except Exception:
            return None
        import pyarrow.compute as pc

        layout: dict = {}
        for row in arrow_tbl.filter(pc.field("wing") == wing).to_pylist():
            if not _is_mined_file_row(row):
                continue
            entry = layout.setdefault(
                row["source_file"],
                {"strategies": set(), "rooms": set(), "legacy_compressed": False},
            )
            entry["strategies"].add(row.get("chunker_strategy") or "")
            entry["rooms"].add(row.get("room") or "")
            if is_legacy_compressed(row):
                entry["legacy_compressed"] = True
        return layout

    def get_source_files(self, wing: str) -> Optional[set]:
        """Return the set of all source_file values already stored for *wing*.

        Uses LanceDB scan-time column projection and filter — no vector scan required.
        Returns an empty set if the table is empty or doesn't exist.
        """
        table = self._table
        if table is None:
            return set()
        import pyarrow.compute as pc

        with self._reading():
            arrow_tbl = self._scan_columns(table, ["source_file", "wing"])
        filtered = arrow_tbl.filter(pc.field("wing") == wing)
        return set(filtered.column("source_file").to_pylist())

    def scan_wing_metadata(self, wing: str, columns: List[str]) -> Optional[List[Dict[str, Any]]]:
        """Return *columns* of every drawer in *wing* via scan-time column projection.

        Only ``id`` and metadata columns can be requested (no text, no vector scan). A
        column missing from a legacy table is returned with its metadata default.
        """
        unknown = [c for c in columns if c not in _META_KEYS and c != "id"]
        if unknown:
            raise ValueError(f"not an id or metadata column: {', '.join(unknown)}")
        table = self._table
        if table is None:
            return []
        import pyarrow.compute as pc

        existing = set(table.schema.names)
        wanted = [c for c in dict.fromkeys(["wing", *columns]) if c in existing]
        with self._reading():
            arrow_tbl = self._scan_columns(table, wanted)
        rows = arrow_tbl.filter(pc.field("wing") == wing).to_pylist()
        missing = {c: _META_DEFAULTS.get(c, "") for c in columns if c not in wanted}
        if missing:
            for row in rows:
                row.update(missing)
        return rows

    def _scan_columns(self, table: _LanceTableProtocol, columns: List[str]):
        """Return an Arrow table from a LanceDB scan projected to *columns*."""
        scanner = getattr(table, "scanner", None)
        if scanner is not None:
            return scanner(columns=columns).to_table()
        return table.search().select(columns).to_arrow()

    def iter_all(self, where=None, batch_size=1000, include_vectors=False):
        """Stream projected, filtered drawers without materializing the full table."""
        table = self._table
        if table is None:
            return
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        meta_columns = ["id", "text"] + [name for name, _, _ in _META_FIELD_SPEC]
        columns = meta_columns + (["vector"] if include_vectors else [])
        existing = set(table.schema.names)
        columns = [c for c in columns if c in existing]

        # Invalid filters are caller errors, independent of storage health.
        sql = self._where_to_sql(where) if where else None
        with self._reading():
            query = table.search().select(columns).limit(None)
            if sql is not None:
                query = query.where(sql)
            with query.to_batches(batch_size=batch_size) as batches:
                for batch in batches:
                    yield batch.to_pylist()

    def optimize(self) -> None:
        """Merge Lance fragments (post-mining compaction) without pruning versions.

        Version pruning belongs to :meth:`cleanup_stale_fragments`, which spares
        versions that live readers in other processes may still use.
        """
        table = self._table
        if table is not None:
            table.optimize(cleanup_older_than=_RETAIN_ALL_VERSIONS)

    def _palace_dir(self) -> Optional[str]:
        lance_dir = getattr(self, "_lance_dir", None)
        return os.path.dirname(lance_dir) if lance_dir else None

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
                     module default, palace_kg_path(palace_path), is used.

        Returns:
            True if optimize succeeded and table is readable, False otherwise.

        Runs under the palace write lease, so it never overlaps another writer's
        mine, optimize, or cleanup of the same palace.
        """
        if self._table is None:
            return True
        with palace_write_lease(palace_path, "optimize"):
            return self._safe_optimize_locked(palace_path, backup_first, kg_path)

    def _safe_optimize_locked(
        self, palace_path: str, backup_first: bool, kg_path: Optional[str]
    ) -> bool:
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

        # Run optimize — wrapped so any LanceDB exception returns False instead of propagating.
        # Compaction keeps every version; the reader-safe cleanup below does the pruning.
        try:
            table.optimize(cleanup_older_than=_RETAIN_ALL_VERSIONS)
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

        Unless *unsafe_now* is set, a version is pruned only when it is older than
        *older_than_days* **and** stopped being the current version at least
        ``READER_VERSION_GRACE`` ago, so a reader in another process that is still
        on the previous version keeps its data files.  Runs under the palace write
        lease.

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
          version_count_after: int, or None when cleanup failed (count unknown)
          estimated_reclaimable_bytes_before: int
          estimated_reclaimable_bytes_after: int
          cleanup_older_than_days: int
          delete_unverified: bool
          error: str (only present when ok=False)
        """
        palace_dir = self._palace_dir()
        if self._table is None or palace_dir is None:
            return self._cleanup_stale_fragments_locked(older_than_days, unsafe_now)
        with palace_write_lease(palace_dir, "cleanup"):
            return self._cleanup_stale_fragments_locked(older_than_days, unsafe_now)

    def _cleanup_stale_fragments_locked(
        self, older_than_days: int, unsafe_now: bool, *, compact: bool = True
    ) -> dict:
        """Run cleanup with the palace write lease already held.

        With ``compact=False`` it only prunes: it changes nothing unless the latest
        version is already compact, so Table.optimize() rewrites no data.
        """
        table = self._table
        if table is None:
            return {
                "ok": False,
                "rows_before": 0,
                "rows_after": 0,
                "freed_bytes": 0,
                "version_count_before": 0,
                "version_count_after": None,
                "cleanup_older_than_days": 0 if unsafe_now else older_than_days,
                "delete_unverified": unsafe_now,
                "error": "Table is None (not opened)",
            }

        started = datetime.now(UTC)
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
            "version_count_after": None,  # unknown after a failed cleanup
            "cleanup_older_than_days": 0 if unsafe_now else older_than_days,
            "delete_unverified": delete_unverified,
        }

        reclaimable_bytes = before_stats["estimated_reclaimable_bytes"]
        unchanged = {
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

        reader_anchor: Optional[datetime] = None
        older_versions: set = set()
        if not unsafe_now:
            try:
                versions = table.list_versions()
            except Exception:
                versions = []
            reader_anchor = _prunable_before(versions, datetime.now(UTC), cleanup_older_than)
            older_versions = {
                version.get("version") for version in versions[:-1] if isinstance(version, dict)
            }

            if reader_anchor is None:
                unchanged["versions_kept_for_readers"] = len(
                    cleanup_plan(versions, started, older_than_days)["kept_for_readers"]
                )
                return unchanged

        try:
            if reader_anchor is not None:
                if compact:
                    # Compact first, keeping every version, so the prune below applies
                    # its cutoff immediately instead of after a long compaction.
                    table.optimize(cleanup_older_than=_RETAIN_ALL_VERSIONS)
                versions = table.list_versions()
                if not compact and not _latest_version_is_compact(versions):
                    return unchanged
                # Lance never prunes the latest version, so an anchor that is still
                # the latest needs no allowance for Lance's later clock reading.
                stamps = _version_timestamps(versions) or []
                margin = (
                    timedelta(0) if stamps and stamps[-1] == reader_anchor else _PRUNE_CUTOFF_MARGIN
                )
                cleanup_older_than = max(
                    cleanup_older_than, datetime.now(UTC) - reader_anchor + margin
                )
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
        # Older versions, old enough to go, that the reader grace kept (the count the
        # dry run lists); a cleanup a minute later removes them.
        kept_for_readers = 0
        if older_versions:
            try:
                remaining = verify_table.list_versions()
            except Exception:
                remaining = []
            horizon = started - timedelta(days=older_than_days)
            kept_for_readers = sum(
                1
                for version, stamp in zip(remaining, _version_timestamps(remaining) or [])
                if version.get("version") in older_versions and stamp < horizon
            )

        return {
            "ok": True,
            "versions_kept_for_readers": kept_for_readers,
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
          warnings: list of dicts like errors; they do not make ok False
          storage: dict from storage_stats(), or {} when it failed
          embedding: dict — model, recorded (bool), vector_dim, model_dim (None when
            unknown without loading the model), dimension_mismatch (an error when True)
          duplicates: dict — rows, distinct_ids, duplicate_id_rows, duplicate_chunk_rows
            (absent when the table has no id column); duplicates are a warning
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

        duplicates = None
        try:
            duplicates = self._duplicate_report(table)
        except Exception as e:
            warnings.append({"probe": "duplicates", "kind": _classify(e), "message": str(e)})
        if duplicates and (duplicates["duplicate_id_rows"] or duplicates["duplicate_chunk_rows"]):
            warnings.append(
                {
                    "probe": "duplicates",
                    "kind": "duplicates",
                    "message": self._duplicate_message(duplicates),
                }
            )

        embedding = self._embedding_report(table)
        if embedding["dimension_mismatch"]:
            errors.append(
                {
                    "probe": "embedding_model",
                    "kind": "embedding_mismatch",
                    "message": self._dimension_mismatch_message(embedding["model_dim"]),
                }
            )

        report = {
            "ok": len(errors) == 0,
            "total_rows": total_rows,
            "current_version": current_version,
            "errors": errors,
            "warnings": warnings,
            "storage": storage,
            "embedding": embedding,
        }
        if duplicates is not None:
            report["duplicates"] = duplicates
        return report

    def _duplicate_report(self, table: _LanceTableProtocol) -> Optional[dict]:
        """Count rows that repeat an id, or a (wing, source_file, chunk_index) triple.

        Reads metadata columns only. Only rows with a source file count toward the
        triple check. Returns None when the table has no id column to compare.
        """
        import pyarrow.compute as pc

        names = getattr(getattr(table, "schema", None), "names", None)
        if not names or "id" not in names:
            return None
        triple = ["wing", "source_file", "chunk_index"]
        has_triple = all(name in names for name in triple)
        arrow_tbl = self._scan_columns(table, ["id", *triple] if has_triple else ["id"])
        rows = arrow_tbl.num_rows
        distinct_ids = len(arrow_tbl["id"].unique()) if rows else 0
        duplicate_chunk_rows = 0
        if has_triple and rows:
            source = pc.field("source_file")
            mined = arrow_tbl.filter(source.is_valid() & (source != ""))
            if mined.num_rows:
                counts = mined.group_by(triple).aggregate([("id", "count")])["id_count"]
                duplicate_chunk_rows = mined.num_rows - len(counts)
        return {
            "rows": rows,
            "distinct_ids": distinct_ids,
            "duplicate_id_rows": rows - distinct_ids,
            "duplicate_chunk_rows": duplicate_chunk_rows,
        }

    def _duplicate_message(self, duplicates: dict) -> str:
        palace = shlex.quote(getattr(self, "_palace_path", None) or "<palace>")
        return (
            f"{duplicates['duplicate_id_rows']} row(s) repeat an id "
            f"({duplicates['rows']} rows, {duplicates['distinct_ids']} distinct ids) and "
            f"{duplicates['duplicate_chunk_rows']} row(s) repeat a "
            "(wing, source_file, chunk_index) chunk; searches may return duplicates. "
            f"Next: mempalace-code --palace {palace} mine <dir> --full for each mined "
            f"project (mempalace-code --palace {palace} repair also rebuilds with unique ids)"
        )

    def _embedding_report(self, table: _LanceTableProtocol) -> dict:
        """Describe the embedding model and vector column without loading the model.

        A dimension mismatch is flagged only when the model's dimension is known
        without loading it (the canonical MiniLM model).
        """
        recorded, vector_dim = _table_embedding_record(table)
        model = self._model_name
        model_dim = CANONICAL_EMBED_DIMENSIONS if is_canonical_embed_model(model) else None
        return {
            "model": model,
            "recorded": recorded is not None,
            "vector_dim": vector_dim,
            "model_dim": model_dim,
            "dimension_mismatch": bool(model_dim and vector_dim and model_dim != vector_dim),
        }

    def _probe_current(self, table: _LanceTableProtocol) -> None:
        """Run the three health probes against *table*'s checked-out version; raise on failure."""
        table.count_rows()
        table.head(1).to_pydict()
        arrow_tbl = self._scan_columns(table, ["wing", "room"])
        arrow_tbl.group_by(["wing", "room"]).aggregate([("room", "count")])

    def recover_to_last_working_version(self, dry_run: bool = True) -> dict:
        """Find and optionally restore the most recent healthy table version.

        Probes the current version first: when it passes every probe the palace is
        healthy and nothing is restored (``healthy=True``). Otherwise walks
        list_versions() from newest to oldest, probing each older version.

        When dry_run=False and a candidate is found, calls table.restore(v) and
        re-opens the table handle so subsequent reads use the restored head.

        Exceptions from the version walk are caught per-version. Exceptions from the
        final restore() call propagate — a failed restore is a terminal condition.

        Returns dict with keys:
          recovered: bool
          healthy: bool — True when the current version passes all probes (no change)
          candidate_version: int or None
          dry_run: bool
          current_version: int or None — the version that was current when called
          current_rows: int or None — manifest row count of the current version
          candidate_rows: int (when a candidate is found) — rows at the candidate
          discarded_versions: list of int (when a candidate is found) — newer versions
            whose changes the rollback drops from the live palace
          restored_to: int (only when recovered=True and dry_run=False)
          rows_after: int (only when recovered=True and dry_run=False)
          checked_versions: list of int (versions that were probed)
          walk_errors: list of dicts (probe failures during version walk)
        """
        table = self._table
        if table is None:
            return {
                "recovered": False,
                "healthy": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "message": "Table is None (not opened)",
            }

        try:
            versions = table.list_versions()
        except Exception as e:
            return {
                "recovered": False,
                "healthy": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "error": f"Could not list versions: {e}",
            }

        current_version = versions[-1]["version"] if versions else None
        try:
            current_rows: int | None = table.count_rows()
        except Exception:
            current_rows = None

        current_error: str | None = None
        try:
            self._probe_current(table)
        except Exception as e:
            current_error = str(e)
        if current_error is None:
            return {
                "recovered": False,
                "healthy": True,
                "candidate_version": None,
                "dry_run": dry_run,
                "current_version": current_version,
                "current_rows": current_rows,
                "message": "current version passes all health probes; nothing to roll back",
            }

        base = {
            "recovered": False,
            "healthy": False,
            "dry_run": dry_run,
            "current_version": current_version,
            "current_rows": current_rows,
            "current_error": current_error,
        }
        if len(versions) < 2:
            return {
                **base,
                "candidate_version": None,
                "message": "No prior versions to roll back to",
            }

        candidate_version = None
        candidate_rows = None
        checked_versions: list = []
        walk_errors: list = []

        try:
            # Walk from second-newest to oldest (the current version failed above)
            for v in reversed(versions[:-1]):
                ver_num = v["version"]
                checked_versions.append(ver_num)
                try:
                    table.checkout(ver_num)
                    self._probe_current(table)
                    candidate_rows = table.count_rows()
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
                **base,
                "candidate_version": None,
                "checked_versions": checked_versions,
                "walk_errors": walk_errors,
            }

        discarded = [v["version"] for v in versions if v["version"] > candidate_version]
        if dry_run:
            return {
                **base,
                "candidate_version": candidate_version,
                "candidate_rows": candidate_rows,
                "discarded_versions": discarded,
                "checked_versions": checked_versions,
            }

        # Perform the restore — exceptions propagate (terminal condition)
        table.restore(candidate_version)
        reopened = self._require_db().open_table(_LANCE_TABLE)
        self._table = reopened
        rows_after = reopened.count_rows()
        return {
            **base,
            "recovered": True,
            "candidate_version": candidate_version,
            "candidate_rows": candidate_rows,
            "discarded_versions": discarded,
            "restored_to": candidate_version,
            "rows_after": rows_after,
            "dry_run": False,
        }

    def read_all_for_rebuild(self, batch_size: int = 5000, *, salvage: bool = True) -> dict:
        """Read every stored drawer (text, metadata, vector) for a full rebuild.

        Reads in offset batches. With *salvage*, a batch that fails is split in half
        down to single rows, so the rows around a missing or damaged fragment are still
        returned and the unreadable ones are counted exactly; that costs time in
        proportion to the unreadable rows. Without it, reading stops at the first
        failed batch (``stopped_at`` names its offset), which is enough to decide that
        a plain rebuild must not run. Never returns a partial result silently:
        ``unreadable`` is ``total`` minus the rows returned.

        Returns dict with keys:
          total: int — rows declared by the current manifest
          rows: list of dicts ready for :func:`write_drawer_table`
          unreadable: int — rows not returned (an upper bound when ``stopped_at`` is set)
          errors: list of str — up to five distinct read errors
          stopped_at: int or None — offset of the failed batch that stopped reading
        """
        table = self._require_table()
        with self._reading():
            total = table.count_rows()
            existing = set(table.schema.names)
        columns = [c for c in ["id", "text", "vector", *_META_KEYS] if c in existing]
        rows: List[Dict[str, Any]] = []
        errors: List[str] = []

        def visit(offset: int, n: int) -> bool:
            """Read rows [offset, offset + n); return False when a read failed."""
            try:
                batch = table.search().select(columns).limit(n).offset(offset).to_list()
            except Exception as exc:
                if _is_query_input_error(exc):
                    raise
                if salvage and n > 1:
                    half = n // 2
                    first = visit(offset, half)
                    return visit(offset + half, n - half) and first
                if len(errors) < 5 and str(exc) not in errors:
                    errors.append(str(exc))
                return False
            for r in batch:
                row = self._meta_defaults({k: r[k] for k in _META_KEYS if r.get(k) is not None})
                row["id"] = r["id"]
                row["text"] = r["text"]
                row["vector"] = r.get("vector")
                rows.append(row)
            return True

        stopped_at: int | None = None
        for offset in range(0, total, batch_size):
            if not visit(offset, min(batch_size, total - offset)) and not salvage:
                stopped_at = offset
                break
        return {
            "total": total,
            "rows": rows,
            "unreadable": max(0, total - len(rows)),
            "errors": errors,
            "stopped_at": stopped_at,
        }

    def write_rebuilt_table(
        self, staging_palace: str, rows: List[Dict[str, Any]], batch_size: int = 5000
    ) -> int:
        """Create a fresh drawers table under ``staging_palace/lance`` holding *rows*.

        Stored vectors are reused, so a rebuild needs no embedding model and keeps
        the palace's vector space and its embedding-model record. Rows without a stored
        vector are re-embedded with this store's model, which is the palace's recorded
        model when it has one. Returns the new table's row count.
        """
        import lancedb

        if not rows:
            raise ValueError("write_rebuilt_table requires at least one row")
        missing = [row for row in rows if row.get("vector") is None or len(row["vector"]) == 0]
        if missing:
            for row, vector in zip(missing, self._embed([row["text"] for row in missing])):
                row["vector"] = vector
        dim = len(rows[0]["vector"])
        # Keep the palace's embedding-model record; never invent one it did not have.
        recorded, _ = (
            _table_embedding_record(self._table) if self._table is not None else (None, None)
        )
        db = cast(
            "_LanceDBConnectionProtocol", lancedb.connect(os.path.join(staging_palace, "lance"))
        )
        table = db.create_table(_LANCE_TABLE, schema=_target_drawer_schema(dim, recorded))
        for i in range(0, len(rows), batch_size):
            table.add(rows[i : i + batch_size])
        return table.count_rows()

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

        def literal(value: Any) -> str:
            # Numbers stay unquoted (int32 columns reject quoted literals); every
            # other value is compared as a string. All go through sql_literal().
            if isinstance(value, (int, float)):
                return sql_literal(value)
            return sql_literal(value if isinstance(value, str) else str(value))

        comparison_ops = {
            "$eq": "=",
            "$ne": "!=",
            "$gt": ">",
            "$gte": ">=",
            "$lt": "<",
            "$lte": "<=",
        }
        parts = []
        for key, value in where.items():
            column = _sql_identifier(key)
            if not isinstance(value, dict):
                parts.append(f"{column} = {literal(value)}")
                continue
            # Operator filters: {"field": {"$eq": val}} etc.
            for op, val in value.items():
                if op in comparison_ops:
                    parts.append(f"{column} {comparison_ops[op]} {literal(val)}")
                elif op == "$in":
                    if not val:
                        parts.append("1 = 0")
                    elif len(val) == 1:
                        # Single-element optimisation
                        parts.append(f"{column} = {literal(val[0])}")
                    else:
                        first = val[0]
                        if isinstance(first, str):
                            if not all(isinstance(v, str) for v in val):
                                raise ValueError(
                                    f"$in list for '{key}' must be all str or all numeric, not mixed"
                                )
                        elif isinstance(first, (int, float)):
                            if not all(isinstance(v, (int, float)) for v in val):
                                raise ValueError(
                                    f"$in list for '{key}' must be all str or all numeric, not mixed"
                                )
                        else:
                            raise ValueError(
                                f"$in list for '{key}' contains unsupported type: {type(first)}"
                            )
                        parts.append(_sql_in(column, list(val)))
                else:
                    raise ValueError(f"unsupported where operator {op!r} for '{key}'")

        return " AND ".join(parts) if parts else "1=1"


# ─── Store factory ─────────────────────────────────────────────────────────────


def prune_settled_versions(palace_path: str) -> None:
    """Best-effort, prune-only reader-safe cleanup before a mine changes the palace.

    A mine's post-optimize cleanup must keep the versions it just superseded for
    READER_VERSION_GRACE.  Pruning them when the next writer starts (it holds the
    palace write lease and has not written yet) keeps the pre-optimize backup and
    the palace from carrying an extra generation of data files between mines.

    It never compacts, so drawers written since the last optimize are compacted
    only by safe_optimize, after its backup: it prunes only while the latest
    version is still the compact one an optimize left.  With
    ``optimize_after_mine`` off, the version history is the palace's rollback
    source and nothing is pruned.
    """
    from mempalace_code.config import MempalaceConfig

    table_dir = os.path.join(palace_path, "lance", f"{_LANCE_TABLE}.lance")
    if not os.path.isdir(table_dir):
        return
    try:
        if not MempalaceConfig().optimize_after_mine:
            return
        store = LanceStore(palace_path, create=False)
        with palace_write_lease(palace_path, "cleanup"):
            result = store._cleanup_stale_fragments_locked(0, False, compact=False)
    except Exception as exc:
        logger.warning("Stale-version cleanup before writing skipped: %s", exc)
        return
    if not result.get("ok"):
        logger.warning(
            "Stale-version cleanup before writing did not complete: %s",
            result.get("error") or result,
        )


def _detect_backend(palace_path: str) -> str:
    """Auto-detect which backend a palace uses based on directory contents."""
    p = Path(palace_path)
    if (p / "lance").exists():
        return "lance"
    if (p / "chroma.sqlite3").exists():
        return _BACKEND_CHROMA_MIGRATION_REQUIRED
    # New palace — default to LanceDB
    return "lance"


def is_legacy_chroma_palace(palace_path: str) -> bool:
    """Return whether *palace_path* is a legacy ChromaDB palace that needs the bridge release."""
    return _detect_backend(expand_palace_path(palace_path)) == _BACKEND_CHROMA_MIGRATION_REQUIRED


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
        palace_path: Path to the palace data directory; ``~`` and relative paths are
            expanded with ``config.expand_palace_path``.
        backend: "lance" or None. "chroma" is retired and raises before mutation.
        create: Create the LanceDB table if it doesn't exist.
        embed_model: Embedding model name. None = default.
        read_only: When True, skip directory creation, schema migration, and embedder
            initialization for read-only metadata access. A read-only open of a palace
            whose ``lance`` directory does not exist returns an empty stub store
            (``_db is None``, ``count() == 0``) rather than raising; callers that must
            distinguish "missing" from "empty" check the palace directory first.
    """
    palace_path = expand_palace_path(palace_path)
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
        # Drawers hold verbatim notes and transcripts: a new palace is owner-only, like
        # its backups. An existing directory keeps the permissions its owner chose.
        os.makedirs(palace_path, mode=0o700, exist_ok=True)

    return LanceStore(palace_path, create=create, embed_model=embed_model, read_only=read_only)
