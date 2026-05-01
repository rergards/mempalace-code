"""Source-tree compatibility shim for legacy MCP configs.

Packaged installs do not include this package. It exists only so repo-local
``PYTHONPATH=/path/to/checkout python -m mempalace.mcp_server`` configs keep
working after the real package moved to ``mempalace_code``.
"""

from __future__ import annotations

from mempalace_code import __version__, main

__all__ = ["main", "__version__"]
