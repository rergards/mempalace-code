"""Shared response fixtures for release-smoke tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def agent_plugin_mcp_responses(minimal_tool_names: Sequence[str]) -> str:
    """Return the exact four-response MCP release-smoke transcript."""
    tools = [{"name": name} for name in minimal_tool_names]
    responses = [
        {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "mempalace-code"}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {"code": -32602, "message": "content is required"},
        },
        {"jsonrpc": "2.0", "id": 4, "result": {"tools": tools}},
    ]
    return "\n".join(json.dumps(response) for response in responses) + "\n"
