"""mempalace_code.mcp.tools.graph — Palace graph traversal, tunnel, and graph stats handlers."""

from .. import runtime


def tool_traverse_graph(start_room: str, max_hops: int = 2):
    """Walk the palace graph from a room. Find connected ideas across wings."""
    from ...palace_graph import traverse

    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    return traverse(start_room, col=col, max_hops=max_hops)


def tool_find_tunnels(wing_a: str | None = None, wing_b: str | None = None):
    """Find rooms that bridge two wings — the hallways connecting domains."""
    from ...palace_graph import find_tunnels
    from ...taxonomy_filters import validate_wing_against_store

    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    for wing in (wing_a, wing_b):
        error = validate_wing_against_store(col, wing)
        if error:
            return error
    return find_tunnels(wing_a, wing_b, col=col)


def tool_graph_stats():
    """Palace graph overview: nodes, tunnels, edges, connectivity."""
    from ...palace_graph import graph_stats

    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    return graph_stats(col=col)


TOOL_SPECS = {
    "mempalace_traverse": {
        "description": (
            "Walk the palace graph from a room. Rooms connect when they share a wing; a "
            "room name found in several wings is a tunnel between them. E.g. start at "
            "'auth' in wing_api and discover it also appears in wing_web (decisions). "
            "The catch-all 'general' room is not part of the graph. Returns at most 50 "
            "rooms, nearest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_room": {
                    "type": "string",
                    "description": "Room to start from (e.g. 'auth', 'deployment'); not 'general'",
                },
                "max_hops": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "How many connections to follow, 0 or more (default: 2)",
                },
            },
            "required": ["start_room"],
        },
        "handler": tool_traverse_graph,
    },
    "mempalace_find_tunnels": {
        "description": (
            "Find rooms that bridge two wings — the same room name in both. E.g. what "
            "topics connect wing_code to wing_team? Unknown wings return an unknown_wing "
            "error with suggestions. Returns at most 50 rooms, largest first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wing_a": {"type": "string", "description": "First wing (optional)"},
                "wing_b": {"type": "string", "description": "Second wing (optional)"},
            },
        },
        "handler": tool_find_tunnels,
    },
    "mempalace_graph_stats": {
        "description": (
            "Palace graph overview: total rooms (excluding 'general'), tunnel rooms, and "
            "total_edges — one per pair of wings a tunnel room connects (per hall when "
            "the room has halls)."
        ),
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_graph_stats,
    },
}
