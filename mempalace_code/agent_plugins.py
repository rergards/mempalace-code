"""Helpers for locating the installed Agent Plugin package data."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

AGENT_PLUGIN_DIRNAME = "agent_plugin"
PLUGIN_JSON = "plugin.json"
MCP_JSON = "mcp.json"
SKILL_PATH = Path("skills") / "mempalace" / "SKILL.md"
SCHEMA_VERSION = "1.0.0"

PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

REQUIRED_AGENT_PLUGIN_MEMBERS: tuple[str, ...] = (
    "mempalace_code/agent_plugin/plugin.json",
    "mempalace_code/agent_plugin/mcp.json",
    "mempalace_code/agent_plugin/skills/mempalace/SKILL.md",
    "mempalace_code/agent_plugin/schemas/1.0.0/plugin.schema.json",
    "mempalace_code/agent_plugin/schemas/1.0.0/mcp.schema.json",
    "mempalace_code/agent_plugin/schemas/SCHEMA-NOTICE.md",
)


def get_agent_plugin_root() -> Path:
    """Return the installed Agent Plugin root as a filesystem path."""
    root = resources.files("mempalace_code").joinpath(AGENT_PLUGIN_DIRNAME)
    if not root.is_dir():
        raise RuntimeError("installed Agent Plugin directory is missing")
    path = Path(str(root))
    if not path.is_dir():
        raise RuntimeError("installed Agent Plugin directory is not filesystem-backed")
    return path


def get_agent_plugin_member(relative_path: str | Path) -> Path:
    """Return a contained plugin member path, raising when it is missing or escapes."""
    root = get_agent_plugin_root()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Agent Plugin member escapes plugin root: {relative_path}") from exc
    if not candidate.exists():
        raise RuntimeError(f"Agent Plugin member is missing: {relative_path}")
    return candidate


def load_plugin_json() -> dict[str, Any]:
    """Load the installed plugin.json manifest."""
    with get_agent_plugin_member(PLUGIN_JSON).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_mcp_json() -> dict[str, Any]:
    """Load the installed mcp.json configuration."""
    with get_agent_plugin_member(MCP_JSON).open("r", encoding="utf-8") as fh:
        return json.load(fh)
