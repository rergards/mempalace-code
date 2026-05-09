"""
mempalace_code.mcp.dispatch — JSON-RPC handle_request, startup flag parsing, and stdio main loop.
"""

import json
import logging
import sys
from typing import Optional

from ..version import __version__
from .registry import TOOLS

logger = logging.getLogger("mempalace_mcp")

_NOISE_KEYS = frozenset({"wait_for_previous"})

# Active tool registry — None means use the full TOOLS dict (default / backward compat).
# Set by main() after parsing startup flags; tests can pass active_registry directly.
_active_registry: Optional[dict] = None


def handle_request(request, active_registry=None):
    """Handle a single JSON-RPC request and return the response dict (or None for notifications).

    ``active_registry`` overrides the module-level ``_active_registry`` when provided.
    Both default to the full TOOLS dict when None, preserving backward compatibility.
    """
    registry = active_registry if active_registry is not None else (_active_registry or TOOLS)

    method = request.get("method", "")
    params = request.get("params") or {}
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mempalace-code", "version": __version__},
            },
        }
    elif method.startswith("notifications/"):
        return None
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {"name": n, "description": t["description"], "inputSchema": t["input_schema"]}
                    for n, t in registry.items()
                ]
            },
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        raw_args = params.get("arguments")
        if raw_args is None:
            tool_args = {}
        elif not isinstance(raw_args, dict):
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Invalid params: arguments must be an object"},
            }
        else:
            tool_args = dict(raw_args)
        if tool_name not in registry:
            # Distinguish between truly unknown tools and tools hidden by the active profile.
            if tool_name in TOOLS:
                msg = f"Tool not enabled by the active MCP profile: {tool_name}"
            else:
                msg = f"Unknown tool: {tool_name}"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": msg},
            }
        # Drop known client compatibility noise keys not declared in the tool schema.
        schema_props = registry[tool_name]["input_schema"].get("properties", {})
        for key in _NOISE_KEYS:
            if key in tool_args and key not in schema_props:
                del tool_args[key]
        # Coerce argument types based on input_schema.
        # MCP JSON transport may deliver integers as floats or strings;
        # ChromaDB and Python slicing require native int.
        for key, value in list(tool_args.items()):
            prop_schema = schema_props.get(key, {})
            declared_type = prop_schema.get("type")
            if declared_type == "integer" and not isinstance(value, int):
                tool_args[key] = int(value)
            elif declared_type == "number" and not isinstance(value, (int, float)):
                tool_args[key] = float(value)
        try:
            result = registry[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception:
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "Internal tool error"},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def _parse_comma_list(value: str) -> list[str]:
    return [tok.strip() for tok in value.split(",") if tok.strip()]


def main(argv=None):
    import argparse

    from ..mcp_tool_profiles import resolve_active_tools

    parser = argparse.ArgumentParser(
        prog="mempalace-mcp",
        description="MemPalace MCP Server — exposes palace tools over stdio",
        add_help=True,
    )
    parser.add_argument(
        "--profile",
        default="full",
        metavar="PROFILE",
        help=(
            "Named tool profile: minimal, kg, code, notes, full (default: full). "
            "Determines the base tool set exposed to MCP clients."
        ),
    )
    parser.add_argument(
        "--tools",
        default=None,
        metavar="SELECTORS",
        help=(
            "Comma-separated tool selectors that REPLACE the profile base set. "
            "Accepts full names (mempalace_search), short names (search), "
            "or wildcards (diary_*). Cannot be combined with --include."
        ),
    )
    parser.add_argument(
        "--include",
        default=None,
        metavar="SELECTORS",
        help=(
            "Comma-separated tool selectors to ADD to the profile base set. "
            "Applied before --exclude. Cannot be combined with --tools."
        ),
    )
    parser.add_argument(
        "--exclude",
        default=None,
        metavar="SELECTORS",
        help=(
            "Comma-separated tool selectors to REMOVE from the active set. "
            "Applied last; exclude wins over include."
        ),
    )

    args = parser.parse_args(argv)

    tools_list = _parse_comma_list(args.tools) if args.tools else None
    include_list = _parse_comma_list(args.include) if args.include else None
    exclude_list = _parse_comma_list(args.exclude) if args.exclude else None

    all_tool_names = frozenset(TOOLS)
    try:
        active_names = resolve_active_tools(
            all_tool_names,
            profile=args.profile,
            tools=tools_list,
            include=include_list,
            exclude=exclude_list,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    global _active_registry
    _active_registry = {k: v for k, v in TOOLS.items() if k in active_names}

    logger.info("MemPalace MCP Server starting...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Server error: {e}")
