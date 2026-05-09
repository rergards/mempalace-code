"""
mempalace_code.mcp — Internal MCP package.

Stable surface: TOOLS, handle_request, main.
"""

from .dispatch import handle_request, main
from .registry import TOOLS

__all__ = ["TOOLS", "handle_request", "main"]
