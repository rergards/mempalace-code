"""
mempalace_code.mcp.dispatch — JSON-RPC handle_request, startup flag parsing, and stdio main loop.

Speaks both the legacy ``initialize``-based dialect (2024-11-05) and the
modern 2026-07-28 dialect over the same stdio transport. A request opts into
2026-07-28 by carrying ``_meta`` (see ``protocol_compat``); anything else is
legacy and behaves exactly as before this module gained protocol_compat
(INV-4).
"""

import json
import logging
import math
import sys
from typing import Optional

from ..version import __version__
from . import protocol_compat
from .registry import TOOLS

logger = logging.getLogger("mempalace_mcp")

_NOISE_KEYS = frozenset({"wait_for_previous"})

# Active tool registry — None means use the full TOOLS dict (default / backward compat).
# Set by main() after parsing startup flags; tests can pass active_registry directly.
_active_registry: Optional[dict] = None


def _coerce_arg(key, value, declared_type):
    """Return (coerced, None) on success or (None, error_fragment) on type mismatch.

    Covers the four primitive JSON Schema types used in the live schema inventory
    (string, boolean, integer, number). Unknown types pass through unchanged.
    """

    def _fail(expected):
        got = "null" if value is None else type(value).__name__
        return None, f"{key} (expected {expected}, got {got})"

    if declared_type == "string":
        return (value, None) if isinstance(value, str) else _fail("string")
    if declared_type == "boolean":
        return (value, None) if isinstance(value, bool) else _fail("boolean")
    if declared_type == "integer":
        # bool is a subclass of int in Python; reject it before the int check.
        if isinstance(value, bool) or value is None:
            return _fail("integer")
        if isinstance(value, int):
            return value, None
        if isinstance(value, float):
            if not (math.isfinite(value) and value.is_integer()):
                return _fail("integer")
            return int(value), None
        try:
            return int(value), None
        except (TypeError, ValueError):
            return _fail("integer")
    if declared_type == "number":
        if isinstance(value, bool) or value is None:
            return _fail("number")
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            return _fail("number")
        if not math.isfinite(coerced):
            return _fail("finite number")
        return value if isinstance(value, (int, float)) else coerced, None
    return value, None


def handle_request(request, active_registry=None):
    """Handle a single JSON-RPC request and return the response dict (or None for notifications).

    ``active_registry`` overrides the module-level ``_active_registry`` when provided.
    Both default to the full TOOLS dict when None, preserving backward compatibility.
    """
    registry = active_registry if active_registry is not None else (_active_registry or TOOLS)

    method = request.get("method", "")
    params = request.get("params") or {}
    req_id = request.get("id")

    if method == "server/discover":
        # server/discover has no legacy counterpart: it always requires full
        # modern _meta, even when the _meta object itself is entirely absent.
        try:
            protocol_compat.validate_modern_meta(params)
        except (
            protocol_compat.ProtocolMetadataError,
            protocol_compat.UnsupportedProtocolVersionError,
        ) as exc:
            return protocol_compat.protocol_error_response(req_id, exc)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": protocol_compat.build_discover_result(),
        }

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": protocol_compat.LEGACY_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mempalace-code", "version": __version__},
            },
        }
    elif method.startswith("notifications/"):
        return None
    elif method == "tools/list":
        modern = protocol_compat.is_modern_attempt(params)
        if modern:
            try:
                protocol_compat.validate_modern_meta(params)
            except (
                protocol_compat.ProtocolMetadataError,
                protocol_compat.UnsupportedProtocolVersionError,
            ) as exc:
                return protocol_compat.protocol_error_response(req_id, exc)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": protocol_compat.build_tools_list_result(registry),
            }
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
        modern = protocol_compat.is_modern_attempt(params)
        if modern:
            try:
                protocol_compat.validate_modern_meta(params)
            except (
                protocol_compat.ProtocolMetadataError,
                protocol_compat.UnsupportedProtocolVersionError,
            ) as exc:
                return protocol_compat.protocol_error_response(req_id, exc)
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
        # Reject arguments not declared in the tool's input_schema properties.
        # Undeclared args would reach the handler as unexpected kwargs and produce
        # client-induced TypeErrors; intercept them here as a bounded -32602.
        undeclared = [k for k in tool_args if k not in schema_props]
        if undeclared:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": f"Invalid params: undeclared argument(s): {', '.join(sorted(undeclared))}",
                },
            }
        # Validate and coerce argument types against the tool's input_schema.
        # Covers all four primitive types (string, boolean, integer, number); rejects
        # bool masquerading as integer/number, and null for any typed property.
        coerce_errors: list[str] = []
        for key, value in list(tool_args.items()):
            declared_type = schema_props.get(key, {}).get("type")
            if declared_type:
                coerced, err = _coerce_arg(key, value, declared_type)
                if err:
                    coerce_errors.append(err)
                else:
                    tool_args[key] = coerced
        if coerce_errors:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": f"Invalid params: type mismatch for argument(s): {', '.join(coerce_errors)}",
                },
            }
        # Validate required arguments before calling handler so client omissions
        # return a bounded -32602 without a Python traceback.
        required_args = registry[tool_name]["input_schema"].get("required", [])
        missing = [arg for arg in required_args if arg not in tool_args]
        if missing:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": f"Invalid params: missing required argument(s): {', '.join(missing)}",
                },
            }
        # Required strings must carry content. Inspect a stripped view only for
        # this predicate; accepted values remain byte-for-byte unchanged.
        blank_required_strings = [
            arg
            for arg in required_args
            if schema_props.get(arg, {}).get("type") == "string" and not tool_args[arg].strip()
        ]
        if blank_required_strings:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": (
                        "Invalid params: blank required argument(s): "
                        f"{', '.join(blank_required_strings)}"
                    ),
                },
            }
        try:
            result = registry[tool_name]["handler"](**tool_args)
            if modern:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": protocol_compat.build_call_tool_result(result),
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}
                    ]
                },
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

    from .._stdio import configure_windows_stdio

    configure_windows_stdio()

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
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except json.JSONDecodeError as e:
            # Per JSON-RPC 2.0 spec, id is null when the request could not be parsed.
            err = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            }
            sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            logger.debug("Parse error (malformed JSON input): %s", e)
        except Exception as e:
            logger.error(f"Server error: {e}")
