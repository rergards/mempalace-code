"""mempalace_code.mcp.tools.read — Status, wing/room/taxonomy, and AAAK spec handlers."""

import os

from .. import runtime
from ..protocol_text import AAAK_SPEC, PALACE_PROTOCOL


def tool_status():
    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    count = col.count()
    wings: dict = {}
    rooms: dict = {}
    try:
        taxonomy = col.count_by_pair("wing", "room")
        for w, room_counts in taxonomy.items():
            wings[w] = sum(room_counts.values())
            for r, c in room_counts.items():
                rooms[r] = rooms.get(r, 0) + c
    except Exception as e:
        return runtime._degraded_response(
            e, total_drawers=count, palace_path=runtime._config.palace_path
        )
    result = {
        "total_drawers": count,
        "wings": wings,
        "rooms": rooms,
        "palace_path": runtime._config.palace_path,
    }
    if os.environ.get("MEMPALACE_AAAK") == "1":
        result["protocol"] = PALACE_PROTOCOL
        result["aaak_dialect"] = AAAK_SPEC
    return result


def tool_list_wings():
    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    try:
        wings = col.count_by("wing")
    except Exception as e:
        return runtime._degraded_response(e, wings={})
    return {"wings": wings}


def tool_list_rooms(wing: str | None = None):
    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    rooms: dict = {}
    try:
        taxonomy = col.count_by_pair("wing", "room")
        if wing:
            rooms = taxonomy.get(wing, {})
        else:
            for wing_rooms in taxonomy.values():
                for r, c in wing_rooms.items():
                    rooms[r] = rooms.get(r, 0) + c
    except Exception as e:
        return runtime._degraded_response(e, wing=wing or "all", rooms={})
    return {"wing": wing or "all", "rooms": rooms}


def tool_get_taxonomy():
    col = runtime._get_store()
    if not col:
        return runtime._no_palace()
    try:
        taxonomy = col.count_by_pair("wing", "room")
    except Exception as e:
        return runtime._degraded_response(e, taxonomy={})
    return {"taxonomy": taxonomy}


def tool_get_aaak_spec():
    """Return the AAAK dialect specification. Not in MCP registry — compatibility helper."""
    return {"aaak_spec": AAAK_SPEC}


TOOL_SPECS = {
    "mempalace_status": {
        "description": "Palace overview — total drawers, wing and room counts",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_status,
    },
    "mempalace_list_wings": {
        "description": "List all wings with drawer counts",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_list_wings,
    },
    "mempalace_list_rooms": {
        "description": "List rooms within a wing (or all rooms if no wing given)",
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string", "description": "Wing to list rooms for (optional)"},
            },
        },
        "handler": tool_list_rooms,
    },
    "mempalace_get_taxonomy": {
        "description": "Full taxonomy: wing → room → drawer count",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_get_taxonomy,
    },
}
