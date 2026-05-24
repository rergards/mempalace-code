"""mempalace_code.mcp.tools.write — Add/delete drawer, delete wing, and mine handlers."""

import hashlib
from datetime import datetime
from pathlib import Path

from ...version import __version__
from .. import runtime
from .search import tool_check_duplicate


def tool_add_drawer(
    wing: str, room: str, content: str, source_file: str | None = None, added_by: str = "mcp"
):
    """File verbatim content into a wing/room. Checks for duplicates first."""
    col = runtime._get_store(create=True)
    if not col:
        return runtime._no_palace()

    # Duplicate check
    dup = tool_check_duplicate(content, threshold=0.9)
    if dup.get("is_duplicate"):
        return {
            "success": False,
            "reason": "duplicate",
            "matches": dup["matches"],
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
        return {"success": False, "error": str(e)}


def tool_delete_drawer(drawer_id: str):
    """Delete a single drawer by ID."""
    col = runtime._get_store(create=True)
    if not col:
        return runtime._no_palace()
    existing = col.get(ids=[drawer_id])
    if not existing["ids"]:
        return {"success": False, "error": f"Drawer not found: {drawer_id}"}
    try:
        col.delete(ids=[drawer_id])
        runtime.logger.info(f"Deleted drawer: {drawer_id}")
        return {"success": True, "drawer_id": drawer_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_delete_wing(wing: str):
    """Delete all drawers in a wing. Irreversible."""
    col = runtime._get_store(create=True)
    if not col:
        return runtime._no_palace()
    existing = col.get(where={"wing": wing}, limit=1)
    if not existing["ids"]:
        return {"success": False, "error": f"Wing not found: {wing}"}
    try:
        deleted_count = col.delete_wing(wing)
        runtime.logger.info(f"Deleted wing: {wing} ({deleted_count} drawers)")
        return {"success": True, "wing": wing, "deleted_count": deleted_count}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_mine(directory: str, wing: str | None = None, full: bool = False):
    """Trigger re-mining of a project directory from the MCP server."""
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
            kg=runtime._get_kg(),
        )
        return {"success": True, **stats}
    except (Exception, SystemExit) as e:
        return {"success": False, "error": str(e)}


TOOL_SPECS = {
    "mempalace_add_drawer": {
        "description": "File verbatim content into the palace. Checks for duplicates first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string", "description": "Wing (project name)"},
                "room": {
                    "type": "string",
                    "description": "Room (aspect: backend, decisions, meetings...)",
                },
                "content": {
                    "type": "string",
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
            "Returns {success, files_processed, files_skipped, drawers_filed, elapsed_secs}."
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
