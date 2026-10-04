"""
backup.py — Palace backup and restore via .tar.gz archives.

Creates and extracts self-contained snapshots of the palace:

    mempalace_backup/
    ├── lance/                        # Full copy of <palace>/lance/
    │   └── ...                       # LanceDB columnar files, transactions, etc.
    ├── knowledge_graph.sqlite3       # Copy of the KG SQLite database (omitted if absent)
    └── metadata.json                 # Backup metadata (drawer_count, wings, timestamp, …)

The ``mempalace_backup/`` prefix prevents tarbomb extraction.
"""

import contextlib
import errno
import io
import json
import logging
import ntpath
import os
import shlex
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger("mempalace")

# Filename prefix for each managed backup kind.
_KIND_PREFIXES: Dict[str, str] = {
    "manual": "mempalace_backup_",
    "scheduled": "scheduled_",
    "pre_optimize": "pre_optimize_",
    "pre_watch": "pre_watch_",
}

# Managed archive prefix — the only tree that restore_backup extracts from.
_MANAGED_MEMBER_PREFIX = "mempalace_backup/"
_METADATA_MEMBER = f"{_MANAGED_MEMBER_PREFIX}metadata.json"
_LANCE_MEMBER = f"{_MANAGED_MEMBER_PREFIX}lance"
_KG_MEMBER = f"{_MANAGED_MEMBER_PREFIX}knowledge_graph.sqlite3"


class BackupSourceError(RuntimeError):
    """Raised when there is nothing to back up at the selected palace path."""


class RestoreTargetError(FileExistsError):
    """``restore --force`` cannot replace this palace root; the message says what to run."""


def managed_backups_dir(palace_path: str) -> str:
    """Return the managed backup directory of one palace: ``<parent>/backups/<palace name>/``.

    Each palace gets its own directory, so listing and retention of one palace never
    touch the archives of a sibling palace that shares the same parent directory.
    """
    palace_abs = os.path.abspath(palace_path)
    return os.path.join(os.path.dirname(palace_abs), "backups", os.path.basename(palace_abs))


def _legacy_backups_dir(palace_path: str) -> str:
    """The shared ``<parent>/backups/`` directory of releases up to and including 1.15.0."""
    return os.path.join(os.path.dirname(os.path.abspath(palace_path)), "backups")


_DEGRADED_SUFFIX = "_DEGRADED.tar.gz"


def _is_lance_temp_name(name: str) -> bool:
    """Lance writes temporary files under a ``.tmp`` prefix and renames them on commit."""
    return name.startswith(".tmp")


class _VanishedFiles(Exception):
    """A concurrent writer removed files while the archive was being written."""

    def __init__(self, paths: List[str]):
        self.paths = paths
        super().__init__(f"{len(paths)} file(s) vanished while archiving, e.g. {paths[0]}")


class _SnapshotMoved(Exception):
    """A concurrent writer committed while the archive was being written."""

    def __init__(self) -> None:
        super().__init__("a new table version was committed while archiving")


def _add_tree(tar: tarfile.TarFile, path: str, arcname: str, vanished: List[str]) -> None:
    """Add *path* recursively, skipping Lance temp files and recording files that vanish."""
    try:
        tar.add(path, arcname=arcname, recursive=False)
    except FileNotFoundError:
        vanished.append(path)
        return
    if os.path.isdir(path) and not os.path.islink(path):
        try:
            names = sorted(os.listdir(path))
        except FileNotFoundError:
            vanished.append(path)
            return
        for name in names:
            if _is_lance_temp_name(name):
                continue
            _add_tree(tar, os.path.join(path, name), f"{arcname}/{name}", vanished)


def _publish_new_file(tmp_path: str, out_path: str) -> None:
    """Move *tmp_path* to *out_path* without replacing an existing file."""
    try:
        os.link(tmp_path, out_path)
    except FileExistsError:
        raise
    except OSError as exc:
        # This check only improves the error; it never authorizes a replacing rename.
        if os.path.lexists(out_path):
            raise FileExistsError(errno.EEXIST, "archive already exists", out_path) from None
        raise OSError(
            exc.errno,
            "cannot safely publish backup without overwriting another archive; "
            "choose a backup directory on a filesystem that supports hard links",
            out_path,
        ) from exc
    try:
        os.unlink(tmp_path)
    except OSError as exc:  # the archive is published; a leftover temp name is harmless
        logger.warning("Could not remove temporary archive name %s: %s", tmp_path, exc)


class BackupArchiveError(Exception):
    """Raised when a backup archive contains an unsafe or malformed managed member.

    Attributes:
        code: stable machine-testable archive-shape error code.
        member_name: the offending tar member name.
        reason: detail for ``degraded_archive`` (the archived ``degraded_error``), else None.
    """

    def __init__(self, code: str, member_name: str, reason: Optional[str] = None):
        self.code = code
        self.member_name = member_name
        self.reason = reason
        super().__init__(f"{code}: {member_name}" + (f" ({reason})" if reason else ""))


class _RestoreMetadata(dict):
    """Parsed metadata with non-serialized restore-shape facts for the CLI.

    ``legacy_kg`` is True when the archive's KG is the legacy global KG that a
    release before 1.15.0 archived for ``backup create`` without ``--palace``;
    ``legacy_kg_possible`` is True when a pre-1.15.0 archive's KG source cannot be
    told (it holds no facts, or the legacy file is gone), so it may be that KG.
    """

    def __init__(
        self,
        metadata: dict,
        *,
        has_lance: bool,
        has_kg: bool,
        legacy_kg: bool = False,
        legacy_kg_possible: bool = False,
    ):
        super().__init__(metadata)
        self.has_lance = has_lance
        self.has_kg = has_kg
        self.legacy_kg = legacy_kg
        self.legacy_kg_possible = legacy_kg_possible


def _archived_kg_origin(metadata: dict, extracted_kg: str) -> tuple[str, list[str]]:
    """Return a pre-1.15.0 archive KG's origin (``"legacy"``/``"palace"``/``"unknown"``,
    or ``"current"`` for a 1.15.0+ archive) and its triple ids."""
    from .knowledge_graph import _predates_adoption, kg_file_triple_ids, pre_adoption_kg_origin

    if not _predates_adoption(metadata.get("mempalace_version")):
        return "current", []
    try:
        ids = kg_file_triple_ids(extracted_kg)
    except sqlite3.Error:
        return "unknown", []
    return pre_adoption_kg_origin(ids), ids


def _validate_archive_members(members: List[tarfile.TarInfo]) -> None:
    """Reject managed archive members with unsafe paths or non-file/non-dir types.

    Every member under the ``mempalace_backup/`` prefix must be a regular file or a
    directory, and its relative path must not contain empty, ``..``, drive-letter
    (e.g. ``C:``), or otherwise absolute-looking components. The drive-letter check
    uses ``ntpath`` unconditionally (not the host ``os.path``) so a POSIX host still
    rejects a component that would escape the staging directory on Windows via
    ``os.path.join``'s drive-relative behavior. Raises before any staged extraction
    happens so a malicious archive can never leave partial or unsafe state on disk.
    """
    for member in members:
        name = member.name
        if not name.startswith(_MANAGED_MEMBER_PREFIX):
            continue
        if not (member.isfile() or member.isdir()):
            raise BackupArchiveError("unsafe_archive_member", name)
        rel = name[len(_MANAGED_MEMBER_PREFIX) :]
        if not rel:
            continue
        parts = rel.replace("\\", "/").split("/")
        if any(p in ("", "..") or ntpath.splitdrive(p)[0] for p in parts):
            raise BackupArchiveError("unsafe_archive_member", name)


def _parse_backup_shape(
    tar: tarfile.TarFile, members: List[tarfile.TarInfo]
) -> tuple[dict, bool, bool]:
    """Return canonical metadata and declared Lance/KG payload presence."""
    metadata_members = [member for member in members if member.name == _METADATA_MEMBER]
    if len(metadata_members) != 1 or not metadata_members[0].isfile():
        raise BackupArchiveError("missing_metadata", _METADATA_MEMBER)

    metadata_file = tar.extractfile(metadata_members[0])
    if metadata_file is None:
        raise BackupArchiveError("malformed_metadata", _METADATA_MEMBER)
    try:
        metadata = json.loads(metadata_file.read().decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupArchiveError("malformed_metadata", _METADATA_MEMBER) from exc
    if not isinstance(metadata, dict):
        raise BackupArchiveError("malformed_metadata", _METADATA_MEMBER)
    drawer_count = metadata.get("drawer_count")
    if isinstance(drawer_count, bool) or not isinstance(drawer_count, int) or drawer_count < 0:
        raise BackupArchiveError("malformed_metadata", _METADATA_MEMBER)

    lance_root = [member for member in members if member.name == _LANCE_MEMBER]
    if len(lance_root) > 1 or (lance_root and not lance_root[0].isdir()):
        raise BackupArchiveError("invalid_backup_shape", _LANCE_MEMBER)
    has_lance = bool(lance_root)

    kg_members = [member for member in members if member.name == _KG_MEMBER]
    if len(kg_members) > 1 or (kg_members and not kg_members[0].isfile()):
        raise BackupArchiveError("invalid_backup_shape", _KG_MEMBER)
    has_kg = bool(kg_members)

    for member in members:
        name = member.name
        if not name.startswith(_MANAGED_MEMBER_PREFIX):
            continue
        if name in (_MANAGED_MEMBER_PREFIX, _METADATA_MEMBER, _LANCE_MEMBER, _KG_MEMBER):
            continue
        if name.startswith(f"{_LANCE_MEMBER}/"):
            if not has_lance:
                raise BackupArchiveError("invalid_backup_shape", name)
            continue
        raise BackupArchiveError("invalid_backup_shape", name)

    if drawer_count > 0 and not has_lance:
        raise BackupArchiveError("invalid_backup_shape", _LANCE_MEMBER)
    return metadata, has_lance, has_kg


def _verify_restored_lance(palace_path: str, expected_count: int) -> None:
    """Require a readable, healthy final Lance store matching declared metadata."""
    from .storage import open_store

    try:
        store = open_store(palace_path, create=False, read_only=True)
        health = store.health_check()
        actual_count = store.count()
    except Exception as exc:
        raise BackupArchiveError("invalid_lance_payload", _LANCE_MEMBER) from exc
    if not health.get("ok") or health.get("total_rows") != expected_count:
        raise BackupArchiveError("invalid_lance_payload", _LANCE_MEMBER)
    if actual_count != expected_count:
        raise BackupArchiveError("invalid_lance_payload", _LANCE_MEMBER)


def _remove_owned_file(path: str, owner: tuple[int, int] | None) -> bool:
    """Unlink a regular file only while its device/inode ownership is unchanged."""
    if owner is None:
        return False
    try:
        current = os.lstat(path)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != owner:
        return False
    os.unlink(path)
    return True


def _restore_destination_collisions(
    palace_path: str,
    kg_path: str,
) -> List[str]:
    """Return existing restore destinations without following the palace root.

    A real empty palace directory is reusable. Every other palace root shape and
    every directory entry not created by this restore counts as state. ``lexists``
    keeps dangling KG symlinks inside the collision boundary.
    """
    collisions: List[str] = []
    try:
        palace_mode = os.lstat(palace_path).st_mode
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISDIR(palace_mode):
            collisions.append(palace_path)
        else:
            try:
                entries = set(os.listdir(palace_path))
            except FileNotFoundError:
                entries = set()
            if entries:
                collisions.append(palace_path)

    if os.path.lexists(kg_path):
        collisions.append(kg_path)
    return collisions


def _refuse_restore_collisions(
    palace_path: str,
    kg_path: str,
) -> None:
    collisions = _restore_destination_collisions(palace_path, kg_path)
    if collisions:
        destinations = ", ".join(repr(path) for path in collisions)
        raise FileExistsError(
            f"Restore destination already contains state: {destinations}. "
            "Use --force to overwrite managed state."
        )


def _remove_owned_lance_dir(lance_dir: str, owner: tuple[int, int] | None) -> bool:
    """Remove ``lance_dir`` only when this restore still owns its claimed root."""
    if owner is None:
        return False
    try:
        current = os.lstat(lance_dir)
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != owner:
        return False
    shutil.rmtree(lance_dir)
    return True


def estimate_backup_source_bytes(palace_path: str, kg_path: Optional[str] = None) -> int:
    """Return the total byte size of files that will be archived.

    Walks ``<palace>/lance/`` and adds the KG SQLite file when present.
    Used for disk-space preflight before creating the temp tar.
    """
    from .knowledge_graph import palace_kg_path

    if kg_path is None:
        kg_path = palace_kg_path(palace_path)

    total = 0
    lance_dir = os.path.join(palace_path, "lance")
    if os.path.isdir(lance_dir):
        for dirpath, _, filenames in os.walk(lance_dir):
            for fname in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass

    if os.path.isfile(kg_path):
        try:
            total += os.path.getsize(kg_path)
        except OSError:
            pass

    return total


def prune_managed_backups(
    backups_dir: str, kind: str, retain_count: int, *, degraded: bool = False
) -> List[str]:
    """Delete old archives of *kind* inside *backups_dir*, keeping the newest *retain_count*.

    Healthy archives and archives of a degraded palace (``*_DEGRADED.tar.gz``) are
    counted and pruned separately, so a run of degraded snapshots never deletes the
    last healthy backups. Returns the list of paths that were deleted. Deletion
    errors are logged as warnings and do not raise — a failed prune must never mask
    a successful backup.
    """
    if retain_count <= 0 or not os.path.isdir(backups_dir):
        return []

    prefix = _KIND_PREFIXES.get(kind, "")
    if not prefix:
        return []

    candidates = []
    for fname in os.listdir(backups_dir):
        if not fname.startswith(prefix) or not fname.endswith(".tar.gz"):
            continue
        if fname.endswith(_DEGRADED_SUFFIX) is not degraded:
            continue
        fpath = os.path.join(backups_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            mtime = os.stat(fpath).st_mtime
            candidates.append((mtime, fname, fpath))
        except OSError as exc:
            logger.warning("Backup pruning: could not stat %s: %s", fpath, exc)

    # Sort newest-first by mtime, then by filename DESC as a stable secondary key.
    # All managed prefixes embed a sortable YYYYMMDD_HHMMSS_ffffff timestamp, so DESC filename
    # also corresponds to "newer first" when mtimes tie (e.g. same-microsecond creation).
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)

    pruned = []
    for _, _, fpath in candidates[retain_count:]:
        try:
            os.unlink(fpath)
            pruned.append(fpath)
            logger.info("Pruned managed backup: %s", fpath)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Backup pruning failed for %s: %s", fpath, exc)

    return pruned


def create_backup(
    palace_path: str,
    out_path: Optional[str] = None,
    kg_path: Optional[str] = None,
    kind: str = "manual",
    config=None,
) -> tuple:
    """Create a .tar.gz backup of the palace.

    Parameters
    ----------
    palace_path:
        Root directory of the palace (``lance/`` subdirectory lives here).
    out_path:
        Destination ``.tar.gz`` file; an existing file is never replaced.  Defaults to
        ``<palace_parent>/backups/<palace name>/<kind_prefix>YYYYMMDD_HHMMSS_ffffff.tar.gz``.
        When not given the archive is placed in the managed backups directory
        and retention pruning runs after a successful write.
    kg_path:
        Path to the knowledge-graph SQLite file.  Defaults to the palace's own
        ``knowledge_graph.palace_kg_path(palace_path)``.
    kind:
        Backup kind: ``manual`` (default), ``scheduled``, ``pre_optimize``, or
        ``pre_watch``.  Controls the filename prefix when *out_path* is None
        and which per-kind archives are pruned by retention.
    config:
        Optional :class:`~mempalace_code.config.MempalaceConfig` instance.
        Created internally when not provided.

    Returns
    -------
    tuple
        ``(metadata, out_path)`` — the metadata dict written to ``metadata.json``
        and the resolved output path of the archive. When retention deleted older
        archives, the returned dict also has ``pruned``: their paths.

    Raises
    ------
    BackupSourceError
        When there is neither drawer data under the palace nor a knowledge graph at
        *kg_path* (a missing or empty palace: nothing to back up).
    ChromaRuntimeRetiredError
        When the path is a legacy ChromaDB palace.
    FileExistsError
        When an explicit *out_path* already exists; archives are never overwritten.
    IsADirectoryError
        When an explicit *out_path* is a directory.
    OSError
        When the destination filesystem cannot atomically publish with a hard link.
    DiskBudgetError
        When the disk-space guard rejects the backup.
    OperationLockedError
        When another writer keeps the palace write lease (:class:`PalaceBusyError`)
        or an exclusive maintenance command holds the installation lease.

    A degraded palace (drawer data present but unreadable, or a knowledge graph that
    fails SQLite's ``quick_check``) is still archived as a forensic copy named
    ``*_DEGRADED.tar.gz``: its metadata carries ``degraded: true`` and the reason
    (``kg_corrupt: ...`` for the KG), retention counts it apart from healthy archives,
    so it never displaces a healthy backup, and :func:`restore_backup` refuses it.
    """
    from .config import MempalaceConfig
    from .disk_budget import DiskBudgetError, check_backup_budget, format_bytes
    from .knowledge_graph import kg_integrity_problem, palace_kg_path
    from .operation_lock import palace_write_lease
    from .storage import (
        _LANCE_TABLE,
        CHROMA_RUNTIME_RETIRED_MESSAGE,
        ChromaRuntimeRetiredError,
        PalaceReadError,
        lance_commit_state,
        open_store,
    )
    from .version import __version__

    if kg_path is None:
        kg_path = palace_kg_path(palace_path)

    lance_dir = os.path.join(palace_path, "lance")
    if not os.path.exists(lance_dir) and os.path.exists(
        os.path.join(palace_path, "chroma.sqlite3")
    ):
        raise ChromaRuntimeRetiredError(CHROMA_RUNTIME_RETIRED_MESSAGE)
    # Drawer data exists once the drawer table does; a failed first mine can leave
    # lance/ holding only LanceDB bookkeeping, which is not a palace.
    has_lance = os.path.isdir(os.path.join(lance_dir, f"{_LANCE_TABLE}.lance"))
    if not has_lance and not os.path.isfile(kg_path):
        raise BackupSourceError(
            f"No palace found at {palace_path}; nothing to back up."
            if not os.path.isdir(palace_path)
            else f"No palace found at {palace_path}: it holds no drawer data and no "
            "knowledge graph; nothing to back up."
        )
    if out_path is not None:
        if os.path.isdir(out_path):
            raise IsADirectoryError(
                errno.EISDIR,
                "--out is a directory; pass an archive file path such as "
                f"{os.path.join(os.path.abspath(out_path), 'mempalace-backup.tar.gz')}",
                os.path.abspath(out_path),
            )
        if os.path.lexists(out_path):
            raise FileExistsError(
                errno.EEXIST,
                "archive already exists; choose a new --out path (backups are never overwritten)",
                os.path.abspath(out_path),
            )

    if config is None:
        from .config import MempalaceConfig

        config = MempalaceConfig()

    # Determine output path and whether this is a managed-dir backup.
    _managed_dir: Optional[str]
    if out_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backups_dir = managed_backups_dir(palace_path)
        os.makedirs(backups_dir, mode=0o700, exist_ok=True)
        os.chmod(os.path.dirname(backups_dir), 0o700)  # F-9: restrict to owner only
        os.chmod(backups_dir, 0o700)
        prefix = _KIND_PREFIXES.get(kind, "mempalace_backup_")
        out_path = os.path.join(backups_dir, f"{prefix}{ts}.tar.gz")
        _managed_dir = backups_dir
    else:
        _managed_dir = None  # explicit path — retention does not apply

    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)  # F-10: auto-create parent dir for explicit --out paths

    # Disk-budget guard: refuse before opening any file handles when the projected
    # post-backup free space would fall below the configured floor. The legacy
    # MEMPALACE_BACKUP_MIN_FREE_BYTES setting is folded into backup_disk_min_free_bytes.
    min_free, min_free_source = config.backup_disk_min_free_setting
    if min_free > 0:
        try:
            budget = check_backup_budget(palace_path, out_path, min_free, kg_path=kg_path)
        except OSError as exc:
            logger.warning("Backup disk-budget check skipped for %s: %s", out_path, exc)
        else:
            if not budget.allowed:
                raise DiskBudgetError(
                    f"disk budget: not enough free space to create backup. "
                    f"Free: {format_bytes(budget.free_bytes)}, "
                    f"required floor after archive: {format_bytes(budget.min_free_bytes)}. "
                    f"Palace: {palace_path}. "
                    f"Free up disk space or lower {min_free_source}."
                )

    def gather_metadata() -> dict:
        drawer_count = 0
        wings: List[str] = []
        degraded_error: Optional[str] = None
        if has_lance:
            try:
                store = open_store(palace_path, create=False, read_only=True)
                if store._table is None:
                    degraded_error = "the drawer table cannot be opened"
                else:
                    drawer_count = store.count()
                    wings = sorted(store.count_by("wing").keys())
            except PalaceReadError as exc:
                degraded_error = str(exc.cause)
            except ChromaRuntimeRetiredError:
                raise
            except Exception as exc:
                degraded_error = str(exc)
        # A corrupt KG makes the palace degraded too (health reports kg_corrupt): its
        # archive must never pass for a healthy one that restores a usable KG.
        kg_problem = kg_integrity_problem(kg_path)
        if kg_problem is not None and kg_problem["kind"] == "kg_corrupt":
            kg_error = f"kg_corrupt: {kg_problem['message']}"
            degraded_error = kg_error if degraded_error is None else f"{degraded_error}; {kg_error}"
        metadata = {
            "drawer_count": drawer_count,
            "wings": wings,
            "timestamp": datetime.now().isoformat(),
            "mempalace_version": __version__,
            "backend_type": "lancedb",
            "palace_path": os.path.abspath(palace_path),
        }
        if degraded_error is not None:
            metadata["degraded"] = True
            metadata["degraded_error"] = degraded_error
        return metadata

    # Hold the palace write lease so no leased writer (mine, optimize, cleanup,
    # watcher) commits mid-walk. It is reentrant: the pre-optimize backup nests
    # under the lease safe_optimize already holds. Unleased writers are still
    # caught by the retries below.
    with palace_write_lease(palace_path, "backup"):
        # Write atomically: build archive in a temp file, then publish it. A concurrent
        # writer can remove Lance files mid-walk, or commit a version newer than the one
        # the metadata counted (restore would then reject the archive); either way the
        # whole snapshot is retried a few times.
        attempts = 3
        for attempt in range(1, attempts + 1):
            commit_state = lance_commit_state(palace_path)
            metadata = gather_metadata()
            tmp_fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".tar.gz.tmp")
            os.close(tmp_fd)
            try:
                vanished: List[str] = []
                with tarfile.open(tmp_path, "w:gz") as tar:
                    if has_lance:
                        _add_tree(tar, lance_dir, "mempalace_backup/lance", vanished)

                    if os.path.isfile(kg_path):
                        if "kg_corrupt:" in metadata.get("degraded_error", ""):
                            # Keep damaged bytes as a clearly marked forensic archive.
                            tar.add(kg_path, arcname=_KG_MEMBER)
                        else:
                            # A file copy omits committed pages still in SQLite's WAL.
                            # SQLite's backup API takes a consistent snapshot without
                            # checkpointing or disrupting an open reader of the source.
                            with tempfile.TemporaryDirectory(dir=out_dir) as snapshot_dir:
                                snapshot = os.path.join(snapshot_dir, "knowledge_graph.sqlite3")
                                uri = Path(kg_path).resolve().as_uri() + "?mode=ro"
                                with (
                                    contextlib.closing(sqlite3.connect(uri, uri=True)) as source,
                                    contextlib.closing(sqlite3.connect(snapshot)) as target,
                                ):
                                    source.backup(target)
                                tar.add(snapshot, arcname=_KG_MEMBER)

                    meta_bytes = json.dumps(metadata, indent=2).encode()
                    info = tarfile.TarInfo(name="mempalace_backup/metadata.json")
                    info.size = len(meta_bytes)
                    info.mtime = int(time.time())
                    tar.addfile(info, io.BytesIO(meta_bytes))
                if vanished:
                    raise _VanishedFiles(vanished)
                if lance_commit_state(palace_path) != commit_state:
                    raise _SnapshotMoved
                if _managed_dir is not None and metadata.get("degraded"):
                    out_path = out_path[: -len(".tar.gz")] + _DEGRADED_SUFFIX
                _publish_new_file(tmp_path, out_path)
            except (_VanishedFiles, _SnapshotMoved) as exc:
                os.unlink(tmp_path)
                if attempt == attempts:
                    raise RuntimeError(
                        f"the palace changed while it was being archived ({exc}); "
                        "retry the backup when mining and watchers are idle"
                    ) from None
                time.sleep(0.2 * attempt)
                continue
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            break

    if _managed_dir is not None:
        retain_count = config.retain_count_for_kind(kind)
        if retain_count > 0:
            # A degraded archive only rotates other degraded archives, never a healthy one.
            pruned = prune_managed_backups(
                _managed_dir, kind, retain_count, degraded=bool(metadata.get("degraded"))
            )
            if pruned:
                # Reported to the caller only; metadata.json inside the archive is final.
                metadata = {**metadata, "pruned": pruned}

    return metadata, out_path


def restore_backup(
    archive_path: str,
    palace_path: str,
    force: bool = False,
    kg_path: Optional[str] = None,
    *,
    private_target: bool = False,
) -> _RestoreMetadata:
    """Extract a backup archive into the target palace path.

    Parameters
    ----------
    archive_path:
        Path to the ``.tar.gz`` archive created by :func:`create_backup`.
    palace_path:
        Root directory where the palace should be restored.
    force:
        When ``True``, existing managed palace and KG state may be replaced.
        When ``False`` (default), any existing palace or selected KG state raises
        :class:`FileExistsError`; a real empty palace directory remains reusable.
    kg_path:
        Destination for the knowledge-graph SQLite file.  Defaults to the palace's
        own ``knowledge_graph.palace_kg_path(palace_path)``.
    private_target:
        ``True`` when *palace_path* is a fresh scratch directory only the caller
        knows (e.g. reading an archive back); no palace write lease is taken then.

    Returns
    -------
    dict
        The parsed ``metadata.json`` from the archive.

    Raises
    ------
    FileExistsError
        If the palace or selected KG destination contains state and *force* is
        ``False``.
    BackupArchiveError
        If the archive is unsafe, lacks usable canonical metadata, contradicts that
        metadata, is a forensic copy of a degraded palace (``degraded_archive``), holds a
        corrupt knowledge graph (``invalid_kg_payload``), or cannot produce its declared
        healthy managed state.
    RestoreTargetError
        If *force* would replace the palace's own KG with the legacy global KG that a
        release before 1.15.0 archived for ``backup create`` without ``--palace``; the
        message names the rerun that writes the archived KG elsewhere. Without *force*
        such an archive restores, and the returned metadata's ``legacy_kg`` is True.
    """
    from .knowledge_graph import kg_ids_missing_from, kg_integrity_problem, palace_kg_path
    from .operation_lock import palace_write_lease

    if kg_path is None:
        kg_path = palace_kg_path(palace_path)

    lance_dir = os.path.join(palace_path, "lance")
    # A writer holding the palace write lease (a mine creating the drawer table)
    # must not interleave with publishing the restored state.
    lease = (
        contextlib.nullcontext() if private_target else palace_write_lease(palace_path, "restore")
    )
    with lease:
        palace_was_absent = not os.path.lexists(palace_path)
        with tarfile.open(archive_path, "r:gz") as tar:
            members = tar.getmembers()
            _validate_archive_members(members)
            metadata, has_lance, has_kg = _parse_backup_shape(tar, members)
            if metadata.get("degraded"):
                # A forensic copy of a damaged palace would restore that damage.
                raise BackupArchiveError(
                    "degraded_archive",
                    _METADATA_MEMBER,
                    str(metadata.get("degraded_error") or "unknown"),
                )

            # Validation and metadata parsing complete before any destination mutation.
            if not force:
                _refuse_restore_collisions(palace_path, kg_path)
            else:
                try:
                    palace_mode = os.lstat(palace_path).st_mode
                except FileNotFoundError:
                    palace_mode = None
                if palace_mode is not None and stat.S_ISLNK(palace_mode):
                    resolved = os.path.realpath(palace_path)
                    raise RestoreTargetError(
                        f"Restore palace root {palace_path!r} is a symlink to {resolved!r}; "
                        "--force does not replace a symlinked palace root. Rerun with the "
                        f"resolved path: mempalace-code --palace {shlex.quote(resolved)} restore "
                        f"{shlex.quote(os.path.abspath(archive_path))} --force"
                    )
                if palace_mode is not None and not stat.S_ISDIR(palace_mode):
                    raise RestoreTargetError(
                        f"Restore palace root is not a directory: {palace_path!r}. "
                        "Move it aside, then rerun restore."
                    )

            with tempfile.TemporaryDirectory(prefix="mempalace_restore_") as tmpdir:
                for member in members:
                    name = member.name

                    if not name.startswith("mempalace_backup/"):
                        continue

                    rel = name[len("mempalace_backup/") :]
                    if not rel:
                        continue

                    parts = rel.replace("\\", "/").split("/")
                    if any(p in ("", "..") or ntpath.splitdrive(p)[0] for p in parts):
                        continue

                    dest = os.path.join(tmpdir, *parts)

                    if member.isdir():
                        os.makedirs(dest, exist_ok=True)
                    elif member.isfile():
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        src = tar.extractfile(member)
                        if src is not None:
                            with src, open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst, length=65536)

                extracted_lance = os.path.join(tmpdir, "lance")
                if has_lance:
                    _verify_restored_lance(tmpdir, metadata["drawer_count"])
                extracted_kg = os.path.join(tmpdir, "knowledge_graph.sqlite3")
                legacy_kg = False
                legacy_kg_possible = False
                if has_kg:
                    kg_problem = kg_integrity_problem(extracted_kg)
                    if kg_problem is not None and kg_problem["kind"] == "kg_corrupt":
                        raise BackupArchiveError("invalid_kg_payload", _KG_MEMBER)
                    origin, archived_ids = _archived_kg_origin(metadata, extracted_kg)
                    legacy_kg = origin == "legacy"
                    legacy_kg_possible = origin == "unknown"
                    replaces_palace_kg = (
                        force
                        and os.path.lexists(kg_path)
                        and os.path.abspath(kg_path) == os.path.abspath(palace_kg_path(palace_path))
                    )
                    # An archive whose source cannot be told refuses only when it would
                    # drop facts the palace KG holds; the rerun keeps them either way.
                    unsafe_unknown = (
                        legacy_kg_possible
                        and replaces_palace_kg
                        and kg_ids_missing_from(kg_path, archived_ids) > 0
                    )
                    if replaces_palace_kg and (legacy_kg or unsafe_unknown):
                        archive_abs = os.path.abspath(archive_path)
                        side_kg = f"{archive_abs}.legacy-kg.sqlite3"
                        rerun = shlex.join(
                            [
                                "mempalace-code",
                                "--palace",
                                os.path.abspath(palace_path),
                                "restore",
                                archive_abs,
                                "--force",
                                "--kg-path",
                                side_kg,
                            ]
                        )
                        version = metadata.get("mempalace_version")
                        if legacy_kg:
                            raise RestoreTargetError(
                                f"{archive_abs} was made by mempalace-code {version} without "
                                "--palace: its knowledge graph is the legacy global knowledge "
                                f"graph, not this palace's. Restoring it over {kg_path} would "
                                "drop the facts added through MCP and reopen facts this palace "
                                "ended; nothing was restored. To roll back the drawers and keep "
                                "this palace's knowledge graph, write the archived one "
                                f"elsewhere: {rerun}"
                            )
                        lost = kg_ids_missing_from(kg_path, archived_ids)
                        raise RestoreTargetError(
                            f"{archive_abs} was made by mempalace-code {version}, and its "
                            f"knowledge graph ({len(archived_ids)} fact(s)) may be the legacy "
                            "global knowledge graph: through 1.14.2, backup create without "
                            "--palace archived that file, and this one cannot be told apart "
                            f"(it holds no facts, or the legacy file is gone). Restoring it over "
                            f"{kg_path} would drop {lost} fact(s) this palace holds; nothing "
                            "was restored. To roll back the drawers and keep this palace's "
                            f"knowledge graph, write the archived one elsewhere: {rerun} (if "
                            f"you know the archive was made with --palace, move {side_kg} over "
                            f"{kg_path} afterwards while no MemPalace process runs)."
                        )
                lance_owner: tuple[int, int] | None = None
                force_backup_container: str | None = None
                force_previous_lance: str | None = None
                force_lance_owner: tuple[int, int] | None = None
                kg_owner: tuple[int, int] | None = None
                force_previous_kg: str | None = None
                force_kg_owner: tuple[int, int] | None = None

                def rollback_owned_lance() -> None:
                    if _remove_owned_lance_dir(lance_dir, lance_owner):
                        if (
                            palace_was_absent
                            and os.path.isdir(palace_path)
                            and not os.listdir(palace_path)
                        ):
                            os.rmdir(palace_path)

                def finish_force_lance(*, rollback: bool) -> None:
                    nonlocal force_backup_container, force_previous_lance
                    if rollback:
                        if force_lance_owner is not None:
                            try:
                                removed = _remove_owned_lance_dir(lance_dir, force_lance_owner)
                            except OSError as exc:
                                raise RuntimeError(
                                    "Lance restore rollback failed; the prior state remains at "
                                    f"{force_previous_lance!r}. Inspect it and {lance_dir!r} "
                                    "before retrying restore."
                                ) from exc
                            if not removed:
                                raise RuntimeError(
                                    "Lance restore rollback failed because the published path "
                                    "changed ownership; the prior state remains at "
                                    f"{force_previous_lance!r}. Inspect it and {lance_dir!r} "
                                    "before retrying restore."
                                )
                        if (
                            force_previous_lance is not None
                            and os.path.lexists(force_previous_lance)
                            and not os.path.lexists(lance_dir)
                        ):
                            try:
                                os.replace(force_previous_lance, lance_dir)
                            except OSError as exc:
                                raise RuntimeError(
                                    "Lance restore rollback failed; the prior state remains at "
                                    f"{force_previous_lance!r}. Move it back to {lance_dir!r} "
                                    "before retrying restore."
                                ) from exc
                    if force_backup_container is not None:
                        shutil.rmtree(force_backup_container, ignore_errors=True)
                        force_backup_container = None
                        force_previous_lance = None
                    if (
                        palace_was_absent
                        and os.path.isdir(palace_path)
                        and not os.listdir(palace_path)
                    ):
                        os.rmdir(palace_path)

                def rollback_owned_kg() -> None:
                    if kg_owner is not None and not _remove_owned_file(kg_path, kg_owner):
                        raise RuntimeError(
                            "Knowledge graph restore rollback failed because the published path "
                            f"changed ownership. Inspect {kg_path!r} before retrying restore."
                        )

                def finish_force_kg(*, rollback: bool) -> None:
                    nonlocal force_previous_kg
                    if rollback and force_kg_owner is not None:
                        if not _remove_owned_file(kg_path, force_kg_owner):
                            raise RuntimeError(
                                "Knowledge graph restore rollback failed because the published path "
                                "changed ownership; the prior state remains at "
                                f"{force_previous_kg!r}. Inspect it and {kg_path!r} before retrying "
                                "restore."
                            )
                    if (
                        rollback
                        and force_previous_kg is not None
                        and os.path.lexists(force_previous_kg)
                    ):
                        if os.path.lexists(kg_path):
                            raise RuntimeError(
                                "Knowledge graph restore rollback failed; the prior state remains at "
                                f"{force_previous_kg!r}. Inspect it and {kg_path!r} before retrying "
                                "restore."
                            )
                        try:
                            os.replace(force_previous_kg, kg_path)
                        except OSError as exc:
                            raise RuntimeError(
                                "Knowledge graph restore rollback failed; the prior state remains at "
                                f"{force_previous_kg!r}. Move it back to {kg_path!r} before retrying "
                                "restore."
                            ) from exc
                    if force_previous_kg is not None:
                        if os.path.lexists(force_previous_kg):
                            os.unlink(force_previous_kg)
                        force_previous_kg = None

                def rollback_published_state() -> None:
                    rollback_error: BaseException | None = None
                    try:
                        if force:
                            finish_force_kg(rollback=True)
                        else:
                            rollback_owned_kg()
                    except BaseException as exc:
                        rollback_error = exc
                    try:
                        if force:
                            finish_force_lance(rollback=True)
                        else:
                            rollback_owned_lance()
                    except BaseException as exc:
                        if rollback_error is None:
                            rollback_error = exc
                    if rollback_error is not None:
                        raise rollback_error

                if has_lance:
                    if not force:
                        _refuse_restore_collisions(palace_path, kg_path)
                    os.makedirs(palace_path, mode=0o700, exist_ok=True)
                    if force:
                        stage_container = tempfile.mkdtemp(
                            dir=palace_path, prefix=".mempalace-lance-stage-"
                        )
                        staged_lance = os.path.join(stage_container, "lance")
                        try:
                            shutil.copytree(extracted_lance, staged_lance)
                            if os.path.lexists(lance_dir):
                                force_backup_container = tempfile.mkdtemp(
                                    dir=palace_path, prefix=".mempalace-lance-backup-"
                                )
                                force_previous_lance = os.path.join(force_backup_container, "lance")
                                os.replace(lance_dir, force_previous_lance)
                            try:
                                os.replace(staged_lance, lance_dir)
                                claimed_lance = os.lstat(lance_dir)
                                force_lance_owner = (claimed_lance.st_dev, claimed_lance.st_ino)
                            except Exception:
                                finish_force_lance(rollback=True)
                                raise
                        finally:
                            shutil.rmtree(stage_container, ignore_errors=True)
                            if (
                                palace_was_absent
                                and os.path.isdir(palace_path)
                                and not os.listdir(palace_path)
                            ):
                                os.rmdir(palace_path)
                    else:
                        try:
                            os.mkdir(lance_dir)
                        except FileExistsError:
                            _refuse_restore_collisions(palace_path, kg_path)
                            raise
                        claimed_lance = os.lstat(lance_dir)
                        lance_owner = (claimed_lance.st_dev, claimed_lance.st_ino)
                        try:
                            shutil.copytree(extracted_lance, lance_dir, dirs_exist_ok=True)
                        except Exception:
                            rollback_owned_lance()
                            raise
                try:
                    if has_kg:
                        if force and os.path.lexists(kg_path):
                            print(
                                f"  Warning: overwriting existing knowledge graph at {kg_path}",
                                file=sys.stderr,
                            )
                        kg_dir = os.path.dirname(os.path.abspath(kg_path))
                        os.makedirs(kg_dir, exist_ok=True)
                        kg_fd, kg_tmp = tempfile.mkstemp(
                            dir=kg_dir,
                            prefix=f".{os.path.basename(kg_path)}.",
                            suffix=".tmp",
                        )
                        try:
                            with os.fdopen(kg_fd, "wb") as dst, open(extracted_kg, "rb") as src:
                                shutil.copyfileobj(src, dst)
                            claimed_kg = os.lstat(kg_tmp)
                            if not force:
                                os.link(kg_tmp, kg_path)
                                kg_owner = (claimed_kg.st_dev, claimed_kg.st_ino)
                            else:
                                if os.path.lexists(kg_path) and not stat.S_ISDIR(
                                    os.lstat(kg_path).st_mode
                                ):
                                    previous_fd, force_previous_kg = tempfile.mkstemp(
                                        dir=kg_dir,
                                        prefix=f".{os.path.basename(kg_path)}.backup.",
                                    )
                                    os.close(previous_fd)
                                    os.unlink(force_previous_kg)
                                    os.replace(kg_path, force_previous_kg)
                                os.replace(kg_tmp, kg_path)
                                force_kg_owner = (claimed_kg.st_dev, claimed_kg.st_ino)
                        finally:
                            if os.path.lexists(kg_tmp):
                                os.unlink(kg_tmp)
                    if has_lance:
                        _verify_restored_lance(palace_path, metadata["drawer_count"])
                    if has_kg:
                        final_kg = os.lstat(kg_path)
                        if not stat.S_ISREG(final_kg.st_mode):
                            raise BackupArchiveError("invalid_kg_payload", _KG_MEMBER)
                except BaseException:
                    rollback_published_state()
                    raise
                else:
                    if force:
                        finish_force_kg(rollback=False)
                        finish_force_lance(rollback=False)

    return _RestoreMetadata(
        metadata,
        has_lance=has_lance,
        has_kg=has_kg,
        legacy_kg=legacy_kg,
        legacy_kg_possible=legacy_kg_possible,
    )


def list_backups(
    palace_path: str,
    extra_dir: Optional[str] = None,
    config=None,
) -> List[Dict[str, Any]]:
    """List this palace's backup archives, newest first.

    Scans the palace's managed directory ``<palace_parent>/backups/<palace name>/``,
    the shared ``<palace_parent>/backups/`` directory older releases wrote into, and
    *extra_dir* when given. Shared-directory archives that record a different palace
    are skipped; those that record none (older releases) are listed with
    ``location="shared"`` because they may belong to a sibling palace. Only managed
    archives are subject to retention, so only they can be flagged ``stale``.

    Parameters
    ----------
    palace_path:
        Root directory of the palace.
    extra_dir:
        Optional additional directory to scan (e.g. a legacy CWD backup location).
    config:
        Optional :class:`~mempalace_code.config.MempalaceConfig` instance.
        Created internally when not provided.

    Returns
    -------
    list of dicts, sorted newest-first, each with keys:
        path, size_bytes, mtime, timestamp, drawer_count, wings, kind, stale, oversized,
        location ("managed", "shared", or "extra"), palace_path, degraded
    """
    if config is None:
        from .config import MempalaceConfig

        config = MempalaceConfig()

    palace_abs = os.path.abspath(palace_path)
    dirs_to_scan = [
        (managed_backups_dir(palace_path), "managed"),
        (_legacy_backups_dir(palace_path), "shared"),
    ]
    if extra_dir is not None:
        abs_extra = os.path.abspath(extra_dir)
        if abs_extra not in {d for d, _ in dirs_to_scan}:
            dirs_to_scan.append((abs_extra, "extra"))

    seen_paths: set = set()
    entries = []

    for scan_dir, location in dirs_to_scan:
        if not os.path.isdir(scan_dir):
            continue
        for fname in os.listdir(scan_dir):
            if not fname.endswith(".tar.gz"):
                continue
            fpath = os.path.abspath(os.path.join(scan_dir, fname))
            if fpath in seen_paths:
                continue
            seen_paths.add(fpath)

            try:
                stat = os.stat(fpath)
            except (FileNotFoundError, PermissionError) as exc:
                logger.warning("Could not stat backup file (skipped): %s (%s)", fpath, exc)
                continue
            entry: Dict[str, Any] = {
                "path": fpath,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "timestamp": None,
                "drawer_count": None,
                "wings": [],
                "kind": _classify_backup_kind(fname),
                "stale": False,
                "oversized": False,
                "location": location,
                "palace_path": None,
                "degraded": fname.endswith(_DEGRADED_SUFFIX),
            }

            try:
                with tarfile.open(fpath, "r:gz") as tar:
                    members = {m.name for m in tar.getmembers()}
                    if "mempalace_backup/metadata.json" in members:
                        try:
                            f = tar.extractfile(tar.getmember("mempalace_backup/metadata.json"))
                            if f is not None:
                                meta = json.loads(f.read().decode())
                                entry["timestamp"] = meta.get("timestamp")
                                entry["drawer_count"] = meta.get("drawer_count")
                                entry["wings"] = meta.get("wings", [])
                                entry["palace_path"] = meta.get("palace_path")
                                entry["degraded"] = bool(meta.get("degraded"))
                        except Exception:
                            logger.warning("Could not parse metadata.json in archive: %s", fpath)
            except Exception:
                logger.warning("Could not open backup archive (skipped): %s", fpath)
                continue

            if location == "shared" and entry["palace_path"] not in (None, palace_abs):
                continue  # a sibling palace's archive
            entries.append(entry)

    entries.sort(key=lambda e: e["mtime"], reverse=True)

    warn_size = config.backup_warn_size_bytes

    by_kind: Dict[tuple, List[Dict[str, Any]]] = {}
    for e in entries:
        if warn_size > 0 and e["size_bytes"] > warn_size:
            e["oversized"] = True
        if e["location"] == "managed":
            by_kind.setdefault((e["kind"], e["degraded"]), []).append(e)

    for (kind, _), kind_entries in by_kind.items():
        # kind_entries is already sorted newest-first (inherited from global sort)
        kind_retain = config.retain_count_for_kind(kind)
        for i, e in enumerate(kind_entries):
            if kind_retain > 0 and i >= kind_retain:
                e["stale"] = True

    return entries


def _classify_backup_kind(filename: str) -> str:
    """Classify a backup archive filename into a kind string."""
    if filename.startswith("pre_watch_"):
        return "pre_watch"
    if filename.startswith("pre_optimize_"):
        return "pre_optimize"
    if filename.startswith("scheduled_"):
        return "scheduled"
    if filename.startswith("mempalace_backup_"):
        return "manual"
    return "other"


BACKUP_LAUNCHD_LABEL_PREFIX = "com.mempalace.backup"


def backup_launchd_label(palace_path: str) -> str:
    """Return the launchd label for one palace's scheduled backups.

    ``com.mempalace.backup.<palace-dir-name>-<hash>``: each palace gets its own job,
    so scheduling a second palace never replaces the first.
    """
    from .launchd import launchd_label

    return launchd_label(BACKUP_LAUNCHD_LABEL_PREFIX, palace_path)


def render_schedule(
    freq: str,
    palace_path: str,
    platform: str,
    mempalace_bin: Optional[str] = None,
    *,
    environment: Optional[Mapping[str, str]] = None,
) -> str:
    """Render a scheduler snippet (launchd plist or cron line) for scheduled backups.

    Parameters
    ----------
    freq:
        One of: daily, weekly, hourly.
    palace_path:
        Root directory of the palace (used to pin ``--palace`` in the snippet).
    platform:
        'darwin' for launchd plist, 'linux' for cron line.
    mempalace_bin:
        Override the mempalace-code binary path (default: invoked launcher, then PATH).
    environment:
        Environment to select job settings from (default: ``os.environ``): ``HF_HOME``
        and every ``MEMPALACE_*`` retention, floor, and path setting, so the job applies
        the same retention as the rendering shell. The launchd job also logs to
        ``~/Library/Logs/<label>.log``.

    Returns
    -------
    str
        Launchd plist XML (darwin) or cron line (linux).

    Raises
    ------
    ValueError
        If freq or platform is unsupported.
    """
    import shlex as _shlex
    import shutil as _shutil

    valid_freqs = ("daily", "weekly", "hourly")
    if freq not in valid_freqs:
        raise ValueError(f"Unsupported freq {freq!r}; must be one of: {valid_freqs}")
    if platform not in ("darwin", "linux"):
        raise ValueError(f"Unsupported platform {platform!r}; must be 'darwin' or 'linux'")

    if mempalace_bin is None:
        from .cli_commands.alias import resolve_invoked_canonical_cli

        invoked_bin = resolve_invoked_canonical_cli()
        resolved_bin = (
            str(invoked_bin) if invoked_bin is not None else _shutil.which("mempalace-code")
        )
        if resolved_bin is None:
            safe_bin = f"{_shlex.quote(sys.executable)} -m mempalace_code"
        else:
            safe_bin = _shlex.quote(resolved_bin)
    else:
        safe_bin = _shlex.quote(mempalace_bin)

    # Pin the palace path so the daemon backs up the right palace regardless of cwd.
    # Note: --palace is a top-level argparse argument, so it must precede the 'backup' subcommand.
    safe_palace = _shlex.quote(os.path.abspath(palace_path))
    cmd_args = f"--palace {safe_palace} backup create --kind scheduled"
    from .launchd import daemon_environment, launchd_log_path

    env = daemon_environment(os.environ if environment is None else environment)

    if platform == "linux":
        if freq == "daily":
            cron_time = "0 3 * * *"
        elif freq == "weekly":
            cron_time = "0 3 * * 0"
        else:  # hourly
            cron_time = "0 * * * *"
        assignments = "".join(f"{name}={_shlex.quote(value)} " for name, value in env.items())
        # cron turns an unescaped % into a newline.
        return f"{cron_time} {assignments}{safe_bin} {cmd_args}\n".replace("%", "\\%")

    # darwin: launchd plist
    def _xml_escape(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    label = backup_launchd_label(palace_path)
    log_path = _xml_escape(str(launchd_log_path(label)))
    env_xml = "".join(
        f"        <key>{_xml_escape(name)}</key>\n        <string>{_xml_escape(value)}</string>\n"
        for name, value in env.items()
    )

    if freq == "daily":
        schedule_xml = (
            "    <key>StartCalendarInterval</key>\n"
            "    <dict>\n"
            "        <key>Hour</key>\n"
            "        <integer>3</integer>\n"
            "        <key>Minute</key>\n"
            "        <integer>0</integer>\n"
            "    </dict>"
        )
    elif freq == "weekly":
        schedule_xml = (
            "    <key>StartCalendarInterval</key>\n"
            "    <dict>\n"
            "        <key>Hour</key>\n"
            "        <integer>3</integer>\n"
            "        <key>Minute</key>\n"
            "        <integer>0</integer>\n"
            "        <key>Weekday</key>\n"
            "        <integer>0</integer>\n"
            "    </dict>"
        )
    else:  # hourly
        schedule_xml = "    <key>StartInterval</key>\n    <integer>3600</integer>"

    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
        '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{label}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        "        <string>/bin/sh</string>\n"
        "        <string>-c</string>\n"
        f"        <string>{_xml_escape(f'{safe_bin} {cmd_args}')}</string>\n"
        "    </array>\n"
        "    <key>EnvironmentVariables</key>\n"
        "    <dict>\n"
        f"{env_xml}"
        "    </dict>\n"
        f"{schedule_xml}\n"
        "    <key>RunAtLoad</key>\n"
        "    <false/>\n"
        "    <key>StandardOutPath</key>\n"
        f"    <string>{log_path}</string>\n"
        "    <key>StandardErrorPath</key>\n"
        f"    <string>{log_path}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )
    return plist
