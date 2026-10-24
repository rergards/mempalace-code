"""mempalace_code.mcp.tools.write — Add/delete drawer, delete wing, and mine handlers."""

import hashlib
from datetime import datetime
from pathlib import Path

from ...errors import InvalidArgumentError
from ...knowledge_graph import LazyKnowledgeGraph
from ...operation_lock import PalaceBusyError
from ...taxonomy_filters import clean_write_name, near_duplicate_names
from ...version import __version__
from .. import runtime

DUPLICATE_THRESHOLD = 0.9
"""Default advisory cosine for check_duplicate neighbours; similarity never refuses a write."""

EXACT_MATCH_LIMIT = 5
"""Most identical drawers one duplicate check reports."""

MAX_DRAWER_CHARS = 100_000
"""Longest drawer or diary text an MCP write accepts (schema maxLength).

Only the first 256 embedding tokens (roughly 1,000 characters) steer search, so
long text belongs in several drawers; this cap keeps one call from filing a
multi-megabyte row.
"""


def exact_drawer_matches(col, content: str, wing: str | None = None) -> list[dict]:
    """Stored drawers whose complete text equals *content*, within *wing* when given.

    Exact equality is the only automatic duplicate proof. Case, word order, negation,
    punctuation and conditions all count, so an opposite or conditional statement is a
    different fact, and identical text in another wing belongs to another project.
    The lookup is an exact filtered read, independent of semantic ranking.
    """
    clauses: list[dict] = [{"text": content}]
    if wing is not None:
        clauses.insert(0, {"wing": wing})
    where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
    found = col.get(where=where, include=["documents", "metadatas"], limit=EXACT_MATCH_LIMIT)
    matches = []
    for drawer_id, doc, meta in zip(
        found.get("ids", []), found.get("documents", []), found.get("metadatas", [])
    ):
        meta = meta or {}
        if doc != content or (wing is not None and meta.get("wing") != wing):
            continue
        matches.append(
            {
                "id": drawer_id,
                "wing": meta.get("wing", "?"),
                "room": meta.get("room", "?"),
                "content": doc[:200] + "..." if len(doc) > 200 else doc,
            }
        )
    return matches


def _taxonomy_conflict(col, wing: str, room: str) -> dict | None:
    """Refuse a new wing/room name that only re-spells an existing one."""
    try:
        taxonomy = col.count_by_pair("wing", "room")
    except Exception:
        return None  # degraded taxonomy read: the write itself reports real failures
    similar_wings = near_duplicate_names(wing, taxonomy)
    if similar_wings:
        return {
            "success": False,
            "error": "similar_wing_exists",
            "wing": wing,
            "suggestions": similar_wings,
            "hint": (
                "Wing names are case-sensitive. Retry with the existing wing exactly as "
                "suggested, or choose a clearly different name."
            ),
        }
    all_rooms = {name for rooms in taxonomy.values() for name in rooms}
    similar_rooms = near_duplicate_names(room, all_rooms)
    if similar_rooms:
        return {
            "success": False,
            "error": "similar_room_exists",
            "room": room,
            "suggestions": similar_rooms,
            "hint": (
                "Room names are case-sensitive. Retry with the existing room exactly as "
                "suggested, or choose a clearly different name."
            ),
        }
    return None


def tool_add_drawer(
    wing: str, room: str, content: str, source_file: str | None = None, added_by: str = "mcp"
):
    """File verbatim content into a wing/room. Checks for duplicates first."""
    # Names are validated before the palace is opened or the model loads.
    return _add_drawer(
        clean_write_name(wing, "wing"),
        clean_write_name(room, "room"),
        content,
        source_file,
        added_by,
    )


@runtime.holds_embedding_write_lease
def _add_drawer(wing: str, room: str, content: str, source_file: str | None, added_by: str):
    col = runtime._get_store(create=True)
    if not col:
        return runtime._no_palace()

    conflict = _taxonomy_conflict(col, wing, room)
    if conflict is not None:
        return conflict

    try:
        duplicates = exact_drawer_matches(col, content, wing)
    except Exception as e:
        return {"success": False, "error": f"Duplicate check failed: {e}"}
    if duplicates:
        return {
            "success": False,
            "reason": "duplicate",
            "matches": duplicates,
            "hint": (
                "A drawer in this wing already holds exactly this text; cite its id instead "
                "of storing a copy. Different wording, a negation, a new condition, or the "
                "same text in another wing is stored as a separate drawer."
            ),
        }

    drawer_id = f"drawer_{wing}_{room}_{hashlib.md5((content[:100] + datetime.now().isoformat()).encode()).hexdigest()[:16]}"

    try:
        col.add(
            ids=[drawer_id],
            documents=[content],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "source_file": source_file or "",
                    "chunk_index": 0,
                    "added_by": added_by,
                    "filed_at": datetime.now().isoformat(),
                    "extractor_version": __version__,
                    "chunker_strategy": "manual_v1",
                }
            ],
        )
        runtime.logger.info(f"Filed drawer: {drawer_id} → {wing}/{room}")
        return {"success": True, "drawer_id": drawer_id, "wing": wing, "room": room}
    except Exception as e:
        return runtime._write_failure(e)


@runtime.holds_write_lease
def tool_delete_drawer(drawer_id: str):
    """Delete a single drawer by ID."""
    col = runtime._get_store(create=True)
    if not col:
        return runtime._no_palace()
    try:
        existing = col.get(ids=[drawer_id])
    except Exception as e:
        return {"success": False, "error": str(e)}
    if not existing["ids"]:
        return {"success": False, "error": f"Drawer not found: {drawer_id}"}
    try:
        col.delete(ids=[drawer_id])
        runtime.logger.info(f"Deleted drawer: {drawer_id}")
        return {"success": True, "drawer_id": drawer_id}
    except Exception as e:
        return runtime._write_failure(e)


@runtime.holds_write_lease
def tool_delete_wing(wing: str):
    """Delete all drawers in a wing. Irreversible."""
    col = runtime._get_store(create=True)
    if not col:
        return runtime._no_palace()
    try:
        existing = col.get(where={"wing": wing}, limit=1)
    except Exception as e:
        return {"success": False, "error": str(e)}
    if not existing["ids"]:
        return {"success": False, "error": f"Wing not found: {wing}"}
    try:
        deleted_count = col.delete_wing(wing)
        runtime.logger.info(f"Deleted wing: {wing} ({deleted_count} drawers)")
        return {"success": True, "wing": wing, "deleted_count": deleted_count}
    except Exception as e:
        return runtime._write_failure(e)


def tool_mine(directory: str, wing: str | None = None, full: bool = False):
    """Trigger re-mining of a project directory from the MCP server."""
    if wing is not None:
        # The same rule add_drawer applies: a path-like wing is -32602, not a new wing.
        wing = clean_write_name(wing, "wing")
    if not Path(directory).expanduser().is_absolute():
        raise InvalidArgumentError(
            f"directory must be an absolute path (got {directory!r}); the MCP server's "
            "working directory is not your project's",
            argument="directory",
        )
    try:
        dir_path = Path(directory).expanduser().resolve()
    except Exception as e:
        return {"success": False, "error": f"Invalid path: {e}"}

    if not dir_path.exists():
        return {"success": False, "error": f"Directory not found: {directory}"}

    if not dir_path.is_dir():
        return {"success": False, "error": f"Path is not a directory: {directory}"}

    # Validate mempalace.yaml or mempal.yaml exists; avoids sys.exit(1) in load_config()
    if not (dir_path / "mempalace.yaml").exists() and not (dir_path / "mempal.yaml").exists():
        return {
            "success": False,
            "error": (
                f"No mempalace.yaml found in {directory}. Run: mempalace-code init {directory}"
            ),
        }

    palace_path = runtime._config.palace_path

    try:
        stats = runtime._mine_quiet(
            project_dir=str(dir_path),
            palace_path=palace_path,
            wing_override=wing,
            incremental=not full,
            kg=LazyKnowledgeGraph(palace_path),
        )
        return {"success": True, **stats}
    except PalaceBusyError as e:
        return runtime.palace_busy_response(e)
    except (Exception, SystemExit) as e:
        return {"success": False, "error": str(e)}


TOOL_SPECS = {
    "mempalace_add_drawer": {
        "description": (
            "File verbatim content into the palace (at most 100,000 characters; only about "
            "the first 1,000 characters steer search, so file long text as several drawers). "
            "Refuses an exact duplicate (reason: duplicate, with the matching drawer ids): a "
            "drawer in the same wing whose complete text is identical. Different wording, a "
            "negation, a new condition, or the same text in another wing is stored. Wing and "
            "room names are trimmed and case-sensitive; a new "
            "name that differs from an existing wing or room only by case, spacing, or "
            "punctuation other than + and # is refused with the existing name as a suggestion."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {
                    "type": "string",
                    "description": "Wing (project name); no '/', '\\' or control characters",
                },
                "room": {
                    "type": "string",
                    "description": "Room (aspect: backend, decisions, meetings...)",
                },
                "content": {
                    "type": "string",
                    "maxLength": MAX_DRAWER_CHARS,
                    "description": "Verbatim content to store — exact words, never summarized",
                },
                "source_file": {"type": "string", "description": "Where this came from (optional)"},
                "added_by": {"type": "string", "description": "Who is filing this (default: mcp)"},
            },
            "required": ["wing", "room", "content"],
        },
        "handler": tool_add_drawer,
    },
    "mempalace_delete_drawer": {
        "description": "Delete a drawer by ID. Irreversible.",
        "input_schema": {
            "type": "object",
            "properties": {
                "drawer_id": {"type": "string", "description": "ID of the drawer to delete"},
            },
            "required": ["drawer_id"],
        },
        "handler": tool_delete_drawer,
    },
    "mempalace_delete_wing": {
        "description": "Delete ALL drawers in a wing. IRREVERSIBLE — use before re-mining a project to clear stale data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {
                    "type": "string",
                    "description": "Wing name whose drawers should be deleted",
                },
            },
            "required": ["wing"],
        },
        "handler": tool_delete_wing,
    },
    "mempalace_mine": {
        "description": (
            "Trigger re-mining of a project directory. "
            "Re-indexes the project's source files into the palace so the agent can "
            "search recently added or modified code without restarting the MCP server. "
            "Uses incremental mining by default (only changed files are re-processed). "
            "The project must have a mempalace.yaml (run: mempalace-code init <dir> first). "
            "Returns {success, files_processed, files_skipped, files_tiny, drawers_filed, elapsed_secs}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Absolute path to the project root to mine",
                },
                "wing": {
                    "type": "string",
                    "description": (
                        "Override wing name. When omitted, mine() uses config['wing'] "
                        "from the project's mempalace.yaml (optional)"
                    ),
                },
                "full": {
                    "type": "boolean",
                    "description": (
                        "Force full rebuild — re-process all files regardless of hash. "
                        "Default false (incremental)"
                    ),
                },
            },
            "required": ["directory"],
        },
        "handler": tool_mine,
    },
}
