#!/usr/bin/env python3
"""
MemPalace MCP Server — read/write palace access for Claude Code
================================================================
Install: claude mcp add mempalace-code -- python -m mempalace_code.mcp_server

Public entrypoint shim. Implementation lives under mempalace_code/mcp/.
"""

# Re-export stable surface — keep all public names that external code imports.
from .mcp.dispatch import handle_request, main  # noqa: F401
from .mcp.protocol_text import AAAK_SPEC, PALACE_PROTOCOL  # noqa: F401
from .mcp.registry import TOOLS  # noqa: F401
from .mcp.runtime import (  # noqa: F401
    _DEGRADED_HINT,
    _config,
    _degraded_response,
    _get_kg,
    _get_store,
    _mine_quiet,
    _no_palace,
    logger,
)

# Tool handler re-exports — kept for direct-import tests and mempalace.mcp_server shim.
from .mcp.tools.architecture import (  # noqa: F401
    EXPANSION_PREDICATES,
    PLATFORM_FRAMEWORK_MARKERS,
    PLATFORM_KG_PREDICATES,
    PLATFORM_PACKAGE_PREFIXES,
    tool_explain_subsystem,
    tool_extract_reusable,
    tool_find_implementations,
    tool_find_references,
    tool_show_project_graph,
    tool_show_type_dependencies,
)
from .mcp.tools.diary import tool_diary_read, tool_diary_write  # noqa: F401
from .mcp.tools.graph import tool_find_tunnels, tool_graph_stats, tool_traverse_graph  # noqa: F401
from .mcp.tools.kg import (  # noqa: F401
    tool_kg_add,
    tool_kg_invalidate,
    tool_kg_query,
    tool_kg_stats,
    tool_kg_timeline,
)
from .mcp.tools.read import (  # noqa: F401
    tool_get_aaak_spec,
    tool_get_taxonomy,
    tool_list_rooms,
    tool_list_wings,
    tool_status,
)
from .mcp.tools.search import (  # noqa: F401
    tool_check_duplicate,
    tool_code_search,
    tool_file_context,
    tool_read,
    tool_search,
)
from .mcp.tools.write import (  # noqa: F401
    tool_add_drawer,
    tool_delete_drawer,
    tool_delete_wing,
    tool_mine,
)

if __name__ == "__main__":
    main()
