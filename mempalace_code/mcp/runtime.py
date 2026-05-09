"""
mempalace_code.mcp.runtime — Shared mutable MCP state and helpers.

All tool modules import from here. Tests patch the globals here directly.
"""

import logging
import os
import sys
from typing import Optional

from ..config import MempalaceConfig
from ..storage import DrawerStore, LanceStore, open_store

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("mempalace_mcp")

_config = MempalaceConfig()

# Singleton store — opened once, reused across all tool calls.
# _store_read_only tracks whether the cached handle is read-only.
_store: Optional[DrawerStore] = None
_store_read_only: bool = False

# Lazy KG singleton — initialized on first KG tool call.
_kg = None


def _get_kg():
    """Return the KnowledgeGraph singleton, creating it on first call."""
    global _kg
    if _kg is None:
        from ..knowledge_graph import KnowledgeGraph

        _kg = KnowledgeGraph()
    return _kg


def _get_store(create: bool = False) -> Optional[DrawerStore]:
    """Return the drawer store, or None on failure.

    Read tools call with create=False; write tools call with create=True.
    A read-only cached handle is replaced when a write-capable handle is needed.
    """
    global _store, _store_read_only

    # Upgrade: if write access is needed but cached handle is read-only, clear it.
    if create and _store is not None and _store_read_only:
        _store = None

    if _store is not None:
        return _store

    read_only = not create
    try:
        new_store = open_store(_config.palace_path, create=create, read_only=read_only)
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
        return new_store
    except Exception:
        return None


def _no_palace():
    return {
        "error": "No palace found",
        "hint": "Run: mempalace-code init <dir> && mempalace-code mine <dir>",
    }


_DEGRADED_HINT = "Run: mempalace-code health && mempalace-code repair --rollback --dry-run"


def _degraded_response(exc: Exception, **extra) -> dict:
    """Return a structured degraded-palace response when taxonomy calls fail but count() works."""
    return {
        "error": f"palace degraded: {exc}",
        "hint": _DEGRADED_HINT,
        **extra,
    }


def _mine_quiet(**kwargs) -> dict:
    """Run mine() with stdout/stderr suppressed at the fd level; return stats dict.

    Uses os.dup2 to redirect fds 1 and 2 to /dev/null so that C-extension writes
    (e.g. from sentence-transformers) and buffered Python writes do not corrupt
    the MCP stdio JSON-RPC stream.
    """
    from ..miner import mine  # lazy import — miner imports torch at module level

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
