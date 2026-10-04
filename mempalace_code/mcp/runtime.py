"""
mempalace_code.mcp.runtime — Shared mutable MCP state and helpers.

All tool modules import from here. Tests patch the globals here directly.
"""

import functools
import logging
import os
import shlex
import sys
from typing import Callable, Optional, ParamSpec

from ..cli_invocation import degraded_palace_next_step
from ..config import MempalaceConfig
from ..operation_lock import PalaceBusyError, palace_write_lease
from ..searcher import no_palace_payload
from ..storage import DrawerStore, LanceStore, PalaceReadError, open_store

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("mempalace_mcp")

_config = MempalaceConfig()

# Singleton store — opened once, reused across all tool calls.
# _store_read_only tracks whether the cached handle is read-only.
# LanceStore handles read the latest committed version on every operation, so
# writes by other processes (CLI mine, watcher, hooks) are visible without a
# reopen.  _store_identity pins the on-disk table directory the handle was
# opened on: a restore, rebuild, or removal by another process replaces that
# directory, and the next tool call then reopens instead of reusing the handle.
_store: Optional[DrawerStore] = None
_store_read_only: bool = False
_store_identity: Optional[tuple[int, int, int]] = None

# mempalace_mine waits this long for another writer of the same palace (CLI
# mine, watcher cycle, hook convos mine) before returning a "palace busy" error.
MCP_MINE_LEASE_WAIT_SECONDS = 60.0

# Drawer, diary, and wing writes hold the lease only for the table write itself (the
# embedding model loads before the lease is taken), so this budget covers another
# drawer write, a watcher cycle, or the tail of a mine. A writer that holds the lease
# longer makes the call return a retryable "palace busy" result instead of stalling
# the stdio server past typical client timeouts.
MCP_WRITE_LEASE_WAIT_SECONDS = 30.0

_BUSY_HINT = (
    "Nothing was written. Another MemPalace writer (named in error) holds this palace; "
    "retry the same call when it finishes. A mine or conversation import can take "
    "several minutes."
)

_P = ParamSpec("_P")

# Lazy KG singleton — initialized on first KG tool call.
_kg = None


class NoPalaceError(Exception):
    """The configured palace directory does not exist; the dispatcher answers no_palace."""

    def __init__(self, palace_path: str) -> None:
        super().__init__(f"No palace found at {palace_path}")
        self.payload = no_palace_payload(palace_path)


def _palace_dir_exists() -> bool:
    return os.path.isdir(_config.palace_path)


def _get_kg(create: bool = False):
    """Return the KnowledgeGraph singleton, creating it on first call.

    Only explicit ``create=True`` may open the KG when the palace directory is
    missing. Ordinary KG calls check the directory even for a cached handle.
    Mining uses LazyKnowledgeGraph inside its write lease instead.
    """
    global _kg
    if not create and not _palace_dir_exists():
        raise NoPalaceError(_config.palace_path)
    if _kg is None:
        from ..knowledge_graph import open_palace_kg

        _kg = open_palace_kg(_config.palace_path)
    return _kg


def _get_store(create: bool = False) -> Optional[DrawerStore]:
    """Return the drawer store, or None on failure.

    Read tools call with create=False; write tools call with create=True.
    A read-only cached handle is replaced when a write-capable handle is needed.
    """
    global _store, _store_read_only, _store_identity

    previous = _store
    # Upgrade: if write access is needed but cached handle is read-only, clear it.
    if create and _store is not None and _store_read_only:
        _store = None
    # Another process replaced or removed the table directory: drop the old handle.
    if _store is not None and _table_identity() != _store_identity:
        _store = None

    if _store is not None:
        return _store

    read_only = not create
    try:
        new_store = open_store(_config.palace_path, create=create, read_only=read_only)
        _adopt_loaded_embedder(new_store, previous)
        if isinstance(new_store, LanceStore) and new_store._table is None:
            if new_store._db is None:
                # Lance dir missing — no palace on disk; signal with None so tools
                # return _no_palace() instead of a misleading empty-store response.
                return None
            # Lance dir exists but table not yet created (palace dir exists, not yet
            # initialised with mempalace-code init).  Return the empty stub without
            # caching so a later create=True call opens a fresh write-capable handle.
            return new_store
        _store = new_store
        _store_read_only = read_only
        _store_identity = _table_identity()
        return new_store
    except Exception:
        return None


def _adopt_loaded_embedder(new_store: DrawerStore, previous: Optional[DrawerStore]) -> None:
    """Reuse the embedding model a dropped handle already loaded for the same model.

    The model is independent of the table, so a write handle opened under the lease
    need not reload what the pre-lease warm-up loaded on a read-only handle.
    """
    if not isinstance(new_store, LanceStore) or not isinstance(previous, LanceStore):
        return
    embedder = previous._embedder
    if embedder is None or new_store._embedder is not None:
        return
    if new_store.embed_model != previous.embed_model:
        return
    if new_store._table_dim is not None and embedder.ndims() != new_store._table_dim:
        return
    new_store._embedder = embedder


def _table_identity() -> Optional[tuple[int, int, int]]:
    """Return (device, inode, ctime) of the palace's Lance table directory, or None.

    The change time distinguishes a directory recreated on a reused inode.
    """
    table_dir = os.path.join(_config.palace_path, "lance", "mempalace_drawers.lance")
    try:
        info = os.stat(table_dir)
    except OSError:
        return None
    return (info.st_dev, info.st_ino, info.st_ctime_ns)


def _no_palace():
    return no_palace_payload(_config.palace_path)


def _degraded_hint() -> str:
    """Return the health/rollback next step bound to this install and palace."""
    return f"Next: {degraded_palace_next_step(_config.palace_path, 'the call')}"


def _unwritable_palace_dir() -> Optional[str]:
    """The first palace directory this process cannot write, else None."""
    lance_dir = os.path.join(_config.palace_path, "lance")
    for path in (
        _config.palace_path,
        lance_dir,
        os.path.join(lance_dir, "mempalace_drawers.lance"),
    ):
        if os.path.isdir(path) and not os.access(path, os.W_OK):
            return path
    return None


def _write_failure(exc: Exception) -> dict:
    """Result for a failed palace write; a permission failure names the palace, not LanceDB."""
    unwritable = _unwritable_palace_dir()
    if unwritable is None:
        return {"success": False, "error": str(exc)}
    return {
        "success": False,
        "error": f"palace is not writable: {_config.palace_path}",
        "hint": (
            f"Next: give this user write access ({shlex.join(['chmod', '-R', 'u+w', unwritable])})"
            ", then retry the call; nothing was written."
        ),
    }


_RETRY_HINT = "Retry the call: the server has reopened the palace."


def _degraded_response(exc: Exception, **extra) -> dict:
    """Return a structured response when a read on the cached handle fails.

    The cached handle is dropped first.  Only when a freshly opened handle also
    has no usable table or fails the metadata scan is the palace reported as
    degraded with the repair hint; otherwise the failure came from a handle that another process
    outdated, and the caller is told to retry.
    """
    global _store
    _store = None
    try:
        fresh = open_store(_config.palace_path, create=False, read_only=True)
        if isinstance(fresh, LanceStore) and fresh._table is None:
            raise RuntimeError("palace table is unavailable")
        fresh.count_by_pair("wing", "room")
    except Exception:
        # PalaceReadError already says the palace is degraded and names its recovery.
        error = str(exc) if isinstance(exc, PalaceReadError) else f"palace degraded: {exc}"
        return {"error": error, "hint": _degraded_hint(), **extra}
    return {"error": f"palace changed during the call: {exc}", "hint": _RETRY_HINT, **extra}


def _log_lease_wait(owner: Optional[dict]) -> None:
    logger.info("MCP write: waiting for another writer of this palace: %s", owner)


def palace_busy_response(exc: PalaceBusyError) -> dict:
    """The retryable result a write returns when another writer keeps the lease."""
    return {"success": False, "error": str(exc), "retryable": True, "hint": _BUSY_HINT}


def _warm_write_store() -> None:
    """Load the embedding model before the lease is taken, without mutating the palace.

    A cold model load takes seconds; doing it under the lease made concurrent
    writers (a sibling MCP server's first call) time out on each other.  Opening a
    write-capable handle creates a missing table and migrates an old schema, so the
    warm-up uses the cached handle or a read-only one; the write handle opened under
    the lease adopts the loaded model (:func:`_adopt_loaded_embedder`).  A palace
    without a table has nothing to warm: its write handle loads the model under
    the lease while it creates the table.
    """
    store = _get_store(create=False)
    if not isinstance(store, LanceStore) or store._table is None or store._embedder is not None:
        return
    try:
        store.warmup()
    except Exception:
        return  # the handler's own embedding reports the real failure


def _lease_wrapper(handler: Callable[_P, dict], *, warm: bool) -> Callable[_P, dict]:
    @functools.wraps(handler)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> dict:
        # Writes never create a palace: a missing directory (a mistyped
        # MEMPALACE_PALACE_PATH) gets the same answer reads give.
        if not _palace_dir_exists():
            return _no_palace()
        if warm:
            _warm_write_store()
        try:
            with palace_write_lease(
                _config.palace_path,
                "mcp-write",
                wait=MCP_WRITE_LEASE_WAIT_SECONDS,
                on_wait=_log_lease_wait,
            ):
                return handler(*args, **kwargs)
        except PalaceBusyError as exc:
            return palace_busy_response(exc)

    return wrapped


def holds_write_lease(handler: Callable[_P, dict]) -> Callable[_P, dict]:
    """Run a palace-writing tool handler inside the palace write lease.

    A missing palace directory returns the no-palace payload without writing.
    Another writer holding the lease past MCP_WRITE_LEASE_WAIT_SECONDS makes the
    call return :func:`palace_busy_response` instead of blocking the server.
    """
    return _lease_wrapper(handler, warm=False)


def holds_embedding_write_lease(handler: Callable[_P, dict]) -> Callable[_P, dict]:
    """Like :func:`holds_write_lease`, for handlers that embed text before writing.

    The embedding model is loaded before the lease is taken, so the lease covers
    only the palace reads and writes.
    """
    return _lease_wrapper(handler, warm=True)


def _mine_quiet(**kwargs) -> dict:
    """Run mine() with stdout/stderr suppressed at the fd level; return stats dict.

    Uses os.dup2 to redirect fds 1 and 2 to /dev/null so that C-extension writes
    (e.g. from FastEmbed/ONNX Runtime) and buffered Python writes do not corrupt
    the MCP stdio JSON-RPC stream.
    """
    from ..miner import mine  # lazy import — mining loads embedding/runtime owners on demand

    def _log_wait(owner: Optional[dict]) -> None:
        logger.info("mempalace_mine: waiting for another writer of this palace: %s", owner)

    # Serialize with every other writer of this palace, but give up after a
    # bounded wait so one stdio request cannot block the server for a whole mine.
    with palace_write_lease(
        kwargs["palace_path"], "mcp-mine", wait=MCP_MINE_LEASE_WAIT_SECONDS, on_wait=_log_wait
    ):
        return _mine_with_quiet_fds(mine, kwargs)


def _mine_with_quiet_fds(mine, kwargs: dict) -> dict:
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_out = os.dup(1)
    old_err = os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        return mine(**kwargs) or {}
    finally:
        # Flush Python buffers while fds still point to /dev/null so buffered
        # text does not leak to real stdout on restore.
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(old_out, 1)
        os.dup2(old_err, 2)
        os.close(devnull)
        os.close(old_out)
        os.close(old_err)
