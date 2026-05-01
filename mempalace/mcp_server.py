# ruff: noqa: F401,F403
"""Compatibility entry point for legacy source-tree MCP configs."""

from __future__ import annotations

from mempalace_code.mcp_server import *
from mempalace_code.mcp_server import main

if __name__ == "__main__":
    main()
