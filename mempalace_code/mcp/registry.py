"""
mempalace_code.mcp.registry — Authoritative ordered TOOLS registry.

Assembles tool specs from family modules in the exact insertion order
required by AC-1 (mempalace_status through mempalace_diary_read).
Validates duplicate names at import time.
"""

from .tools.architecture import TOOL_SPECS as _arch_specs
from .tools.diary import TOOL_SPECS as _diary_specs
from .tools.graph import TOOL_SPECS as _graph_specs
from .tools.kg import TOOL_SPECS as _kg_specs
from .tools.read import TOOL_SPECS as _read_specs
from .tools.search import TOOL_SPECS as _search_specs
from .tools.write import TOOL_SPECS as _write_specs


def _build_tools(*families: dict) -> dict:
    """Merge family dicts in order; raise on duplicate name."""
    result: dict = {}
    for family in families:
        for name, spec in family.items():
            if name in result:
                raise ValueError(f"Duplicate MCP tool name: {name!r}")
            result[name] = spec
    return result


# Registry insertion order matches original mcp_server.py TOOLS dict exactly:
# read → kg → architecture → graph → search → write → diary
TOOLS = _build_tools(
    _read_specs,
    _kg_specs,
    _arch_specs,
    _graph_specs,
    _search_specs,
    _write_specs,
    _diary_specs,
)
