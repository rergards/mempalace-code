"""
mempalace_code.mcp.dispatch — JSON-RPC handle_request, startup flag parsing, and stdio main loop.

Speaks both the legacy ``initialize``-based dialect (2024-11-05) and the
modern 2026-07-28 dialect over the same stdio transport. A request opts into
2026-07-28 by carrying ``_meta`` (see ``protocol_compat``); anything else is
legacy and behaves exactly as before this module gained protocol_compat
(INV-4).
"""

import io
import json
import logging
import math
import os
import stat
import sys
from collections.abc import Mapping
from typing import Optional

from .. import knowledge_graph
from ..errors import InvalidArgumentError
from ..storage import PalaceReadError
from ..version import __version__
from . import protocol_compat
from .registry import TOOLS
from .runtime import NoPalaceError

logger = logging.getLogger("mempalace_mcp")

_NOISE_KEYS = frozenset({"wait_for_previous"})


def _reported_tool_errors() -> tuple[type[Exception], ...]:
    """Exceptions whose message a tool call returns as a tool error, not an internal one."""
    kg_error = getattr(knowledge_graph, "KnowledgeGraphUnavailableError", None)
    if isinstance(kg_error, type) and issubclass(kg_error, Exception):
        return (PalaceReadError, kg_error)
    return (PalaceReadError,)


_REPORTED_TOOL_ERRORS = _reported_tool_errors()

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


def _range_error(key, value, prop: Mapping) -> str | None:
    """Return an error fragment when an argument breaks its schema bounds.

    Numbers are checked against ``minimum``/``maximum``, text against ``maxLength``.
    """
    if isinstance(value, str):
        max_length = prop.get("maxLength")
        if max_length is not None and len(value) > max_length:
            return f"{key} (expected at most {max_length} characters, got {len(value)})"
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    minimum = prop.get("minimum")
    maximum = prop.get("maximum")
    if (minimum is None or value >= minimum) and (maximum is None or value <= maximum):
        return None
    if minimum is not None and maximum is not None:
        expected = f"{minimum} to {maximum}"
    elif minimum is not None:
        expected = f"at least {minimum}"
    else:
        expected = f"at most {maximum}"
    return f"{key} (expected {expected}, got {value})"


def _has_lone_surrogate(value) -> bool:
    """True when *value* holds text with an unpaired surrogate (e.g. JSON "\\ud800").

    Such text cannot be encoded as UTF-8, so it can be neither embedded nor
    stored; rejecting it up front keeps tokenizer and storage errors out of
    replies.
    """
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return True
        return False
    if isinstance(value, Mapping):
        return any(_has_lone_surrogate(k) or _has_lone_surrogate(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_lone_surrogate(item) for item in value)
    return False


def _is_tool_error(result) -> bool:
    """True when a tool handler reported a failure in its payload.

    Handlers report expected failures as data ({"error": ...} or
    {"success": false, ...}); MCP flags those results with ``isError`` so a
    client can tell a failed call from a successful one without parsing text.
    """
    if not isinstance(result, Mapping):
        return False
    return bool(result.get("error")) or result.get("success") is False


def _invalid_argument_names(exc: InvalidArgumentError, tool_args: dict) -> list[str]:
    """Name the argument(s) an InvalidArgumentError refers to, when they can be known."""
    if exc.argument:
        return [exc.argument]
    if exc.value is None:
        return []
    return sorted(key for key, value in tool_args.items() if value == exc.value)


def handle_request(request, active_registry=None):
    """Handle a single JSON-RPC request and return the response dict (or None for notifications).

    ``active_registry`` overrides the module-level ``_active_registry`` when provided.
    Both default to the full TOOLS dict when None, preserving backward compatibility.
    """
    if not isinstance(request, Mapping):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }

    registry = active_registry if active_registry is not None else (_active_registry or TOOLS)

    req_id = request.get("id")
    method = request.get("method")
    if not isinstance(method, str):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Invalid Request"},
        }
    if "id" not in request:
        # A JSON-RPC notification: never answered. Only notifications/* methods
        # are notifications in MCP; anything else sent without an id is not run,
        # so a fire-and-forget tools/call cannot mutate the palace unobserved.
        if not method.startswith("notifications/"):
            logger.warning("Ignored %r sent without an id: MCP requests must carry an id", method)
        return None
    raw_params = request.get("params")
    if raw_params is None:
        params = {}
    elif not isinstance(raw_params, Mapping):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": "Invalid params: params must be an object"},
        }
    else:
        params = dict(raw_params)

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
    elif method == "ping":
        if protocol_compat.is_modern_attempt(params):
            try:
                protocol_compat.validate_modern_meta(params)
            except (
                protocol_compat.ProtocolMetadataError,
                protocol_compat.UnsupportedProtocolVersionError,
            ) as exc:
                return protocol_compat.protocol_error_response(req_id, exc)
            return {"jsonrpc": "2.0", "id": req_id, "result": protocol_compat.build_empty_result()}
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
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
        if not isinstance(tool_name, str) or not tool_name.strip():
            if tool_name is None:
                detail = "missing required argument(s): name"
            else:
                detail = "name must be a non-empty string"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Invalid params: {detail}"},
            }
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
        unencodable = sorted(key for key, value in tool_args.items() if _has_lone_surrogate(value))
        if unencodable:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": (
                        "Invalid params: text with an unpaired surrogate escape (not valid "
                        f"Unicode) in argument(s): {', '.join(unencodable)}"
                    ),
                },
            }
        enum_errors: list[str] = []
        for key, value in tool_args.items():
            allowed_values = schema_props.get(key, {}).get("enum")
            if allowed_values is not None and value not in allowed_values:
                allowed = ", ".join(str(item) for item in allowed_values)
                enum_errors.append(f"{key} (expected one of: {allowed})")
        if enum_errors:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": f"Invalid params: unsupported value for argument(s): {', '.join(enum_errors)}",
                },
            }
        range_errors = [
            err
            for key, value in tool_args.items()
            if (err := _range_error(key, value, schema_props.get(key, {}))) is not None
        ]
        if range_errors:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32602,
                    "message": f"Invalid params: out-of-range value for argument(s): {', '.join(range_errors)}",
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
        except InvalidArgumentError as exc:
            # A handler (or the library beneath it) rejected an argument value
            # the schema cannot express, e.g. a malformed date: name it as -32602.
            message = str(exc)
            names = _invalid_argument_names(exc, tool_args)
            if names and not any(message.startswith(name) for name in names):
                message = f"{', '.join(names)}: {message}"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Invalid params: {message}"},
            }
        except NoPalaceError as exc:
            # The palace directory is missing: the same payload status and search give.
            result = exc.payload
        except _REPORTED_TOOL_ERRORS as exc:
            # An unreadable palace or KG: the message names the store and the recovery.
            result = {"error": str(exc)}
        except Exception:
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "Internal tool error"},
            }
        is_error = _is_tool_error(result)
        if modern:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": protocol_compat.build_call_tool_result(result, is_error=is_error),
            }
        call_result: dict = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                }
            ]
        }
        if is_error:
            call_result["isError"] = True
        return {"jsonrpc": "2.0", "id": req_id, "result": call_result}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def _parse_comma_list(value: str) -> list[str]:
    return [tok.strip() for tok in value.split(",") if tok.strip()]


def _selector_list(flag: str, value: str | None) -> list[str] | None:
    """Parse one selector flag; None when absent, ValueError when given but empty."""
    if value is None:
        return None
    selectors = _parse_comma_list(value)
    if not selectors:
        raise ValueError(
            f"{flag} was given no tool selectors (got {value!r}); pass at least one "
            "selector such as search or diary_*, or omit the flag"
        )
    return selectors


def _maintenance_message(path) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        metadata = path.lstat()
        safe = stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
        detail = json.loads(path.read_text(encoding="utf-8")) if safe else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        detail = {}
    recovery = detail.get("recovery_command")
    message = "MemPalace maintenance is active"
    if isinstance(recovery, str) and recovery:
        message += f"; recovery: {recovery}"
    return message


def main(argv=None):
    import argparse

    from ..mcp_tool_profiles import resolve_active_tools

    parser = argparse.ArgumentParser(
        prog="mempalace-code-mcp",
        description="MemPalace MCP Server — exposes palace tools over stdio",
        add_help=True,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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

    all_tool_names = frozenset(TOOLS)
    try:
        # An explicit but empty selector list (e.g. --tools="$UNSET_VAR") is an
        # error, never "flag not given": that would widen the surface to the profile.
        tools_list = _selector_list("--tools", args.tools)
        include_list = _selector_list("--include", args.include)
        exclude_list = _selector_list("--exclude", args.exclude)
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

    # Keep every installed stdio server on the shared side of the same lock used
    # by storage maintenance.  A live migration also leaves an explicit marker,
    # so a crashed operator cannot silently reopen the palace in a partial state.
    from ..operation_lock import OperationLock, OperationLockedError, owner_palace_kwargs

    lock = OperationLock.default()
    maintenance = lock.path.with_name("live-wing-migration.json")
    message = _maintenance_message(maintenance)
    if message is not None:
        print(message, file=sys.stderr)
        raise SystemExit(os.EX_TEMPFAIL)
    try:
        from .runtime import _config as runtime_config

        lease = lock.acquire_shared(
            "mcp-stdio", **owner_palace_kwargs(lock, runtime_config.palace_path)
        )
    except OperationLockedError as exc:
        print(f"MemPalace maintenance lock is active: {exc}", file=sys.stderr)
        raise SystemExit(os.EX_TEMPFAIL) from exc

    with lease:
        message = _maintenance_message(maintenance)
        if message is not None:
            print(message, file=sys.stderr)
            raise SystemExit(os.EX_TEMPFAIL)
        logger.info("MemPalace MCP Server starting...")
        while True:
            try:
                raw = _read_request_line(sys.stdin)
                if not raw:
                    break
                response = _handle_line(raw)
                if response is not None:
                    sys.stdout.write(_serialize_response(response) + "\n")
                    sys.stdout.flush()
            except KeyboardInterrupt:
                break
            except BrokenPipeError:
                break
            except Exception as e:
                logger.error(f"Server error: {e}")


def _read_request_line(stream) -> bytes | str:
    """Read one request line, as bytes when *stream* exposes its binary buffer.

    Reading bytes keeps an invalid UTF-8 line from breaking the text decoder:
    ``_handle_line`` decodes it and answers a parse error instead. A text-only
    stream (for example one substituted by an embedding host) is read as text.
    """
    buffer = getattr(stream, "buffer", None)
    if isinstance(buffer, io.BufferedIOBase):
        return buffer.readline()
    return stream.readline()


def _serialize_response(response: dict) -> str:
    """Render one response as a JSON line that always encodes as UTF-8.

    Text is written unescaped, except when the response echoes an unpaired
    surrogate from the request (an id or tool name a client cut mid-pair):
    UTF-8 cannot encode it, so that response is written with ASCII escapes,
    which JSON allows, instead of failing and leaving the request unanswered.
    """
    text = json.dumps(response, ensure_ascii=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(response)
    return text


def _parse_error(detail: str) -> dict:
    # Per JSON-RPC 2.0, id is null when the request could not be parsed.
    return {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": f"Parse error: {detail}"},
    }


def _handle_line(raw: bytes | str) -> dict | None:
    """Turn one raw stdio line into the JSON-RPC response to write, or None.

    Every line that cannot become a request is answered with ``-32700`` so the
    client never waits for a reply that will not come: invalid UTF-8, malformed
    JSON, numbers beyond the interpreter's digit limit, and nesting deeper than
    the parser's recursion limit.
    """
    if isinstance(raw, bytes):
        try:
            line = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            return _parse_error(f"request is not valid UTF-8 (invalid byte at offset {exc.start})")
    else:
        line = raw
        try:
            line.encode("utf-8")
        except UnicodeEncodeError as exc:
            # A text stream configured with surrogateescape smuggles invalid bytes in.
            return _parse_error(f"request is not valid UTF-8 (invalid byte at offset {exc.start})")
    line = line.strip()
    if not line:
        return None
    try:
        request = json.loads(line)
    except RecursionError:
        return _parse_error("JSON nesting is too deep")
    except json.JSONDecodeError as exc:
        return _parse_error(str(exc))
    except ValueError:
        # int() digit limit (sys.get_int_max_str_digits) raises a plain ValueError.
        return _parse_error("a number has too many digits")
    try:
        return handle_request(request)
    except Exception:
        logger.exception("Unexpected error while handling a request")
        if isinstance(request, Mapping) and "id" not in request:
            return None
        req_id = request.get("id") if isinstance(request, Mapping) else None
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": "Internal error"},
        }
