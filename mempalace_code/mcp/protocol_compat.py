"""
mempalace_code.mcp.protocol_compat — 2026-07-28 protocol metadata negotiation,
SDK type conversion, and legacy/modern result shaping.

Legacy clients (``initialize``-based, protocol 2024-11-05) never send a
``_meta`` object on request params and are handled exactly as before this
module existed (INV-4: no per-request metadata is required of them). Modern
clients opt in to the 2026-07-28 dialect by attaching the reserved
``io.modelcontextprotocol/*`` keys the official SDK defines in
``mcp.types`` under ``params._meta``. A request whose ``_meta`` carries at
least one such reserved key is treated as a modern attempt and validated in
full, so a half-formed reserved block fails loudly (-32602) instead of
silently degrading to the legacy shape. ``_meta`` content that carries only
unrelated keys (e.g. the base-protocol ``progressToken``) stays on the
legacy path unchanged.

The ``mcp`` SDK (and its ``pydantic`` dependency) is imported lazily, inside
the functions that actually build or validate modern wire shapes. A purely
legacy session (``initialize``/``tools/list``/``tools/call`` with no
``_meta``) never imports it, matching the existing lazy-startup contract
(MCP-LAZY-STARTUP) and avoiding surprises in tests that stub platform-level
globals such as ``sys.platform`` around code that never touches the SDK.
"""

from __future__ import annotations

import json
from typing import Any

from ..version import __version__

# ── Protocol version policy ──────────────────────────────────────────────────
# Plain literals, not derived from the SDK: these are the two dialects this
# server actually speaks (legacy handshake, modern per-request), independent
# of the full list of protocol revisions the SDK's type models know about.

PROTOCOL_VERSION_2026 = "2026-07-28"
"""The stateless per-request 2026-07-28 dialect this server speaks."""

LEGACY_PROTOCOL_VERSION = "2024-11-05"
"""The initialize-handshake dialect this server has always spoken."""

SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (PROTOCOL_VERSION_2026, LEGACY_PROTOCOL_VERSION)

SERVER_NAME = "mempalace-code"

MODERN_CACHE_TTL_MS = 0
MODERN_CACHE_SCOPE = "private"

# Reserved request/result `_meta` keys the SDK defines (mcp.types.*_META_KEY).
# Mirrored as literals here so a purely legacy request path never imports the
# SDK; validate_modern_meta cross-checks these against the SDK's own values.
_PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
_CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
_CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
_SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"


class ProtocolMetadataError(ValueError):
    """A request opted into the modern protocol but its ``_meta`` block is malformed."""


class UnsupportedProtocolVersionError(ValueError):
    """A request declared a protocol version this server does not support."""

    def __init__(self, requested: str):
        self.requested = requested
        self.supported = list(SUPPORTED_PROTOCOL_VERSIONS)
        super().__init__(f"Unsupported protocol version: {requested!r}")


_RESERVED_META_PREFIX = "io.modelcontextprotocol/"


def is_modern_attempt(params: dict) -> bool:
    """True when a request opts into the 2026-07-28 dialect via a ``_meta`` object.

    The signal is presence of at least one reserved ``io.modelcontextprotocol/*``
    key — not whether the rest of ``_meta`` is well-formed, so a half-formed
    reserved block is still validated (and rejected) rather than silently
    treated as legacy. Legacy clients may attach unrelated ``_meta`` content
    (e.g. the base-protocol ``progressToken``) on any request; that alone must
    not trip modern validation (INV-4). This check alone never imports the SDK.
    """
    if not isinstance(params, dict):
        return False
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return False
    return any(isinstance(key, str) and key.startswith(_RESERVED_META_PREFIX) for key in meta)


def validate_modern_meta(params: dict) -> str:
    """Validate a modern request's ``_meta`` block; return the negotiated protocol version.

    Raises ``ProtocolMetadataError`` when ``_meta``, ``protocolVersion``,
    ``clientInfo``, or ``clientCapabilities`` is missing or malformed. Raises
    ``UnsupportedProtocolVersionError`` when ``_meta`` is well-formed but names
    a version this server does not support.

    The literals mirrored above are cross-checked against the SDK's own
    ``mcp.types.*_META_KEY`` constants once, in
    ``test_sdk_meta_key_constants_match_mirrored_literals`` — not on every
    request: a mismatch is a packaging-time invariant, not a per-request
    condition, and raising here would put an unhandled exception on the
    request path for every 2026-07-28 call if it ever fired.
    """
    meta = params.get("_meta") if isinstance(params, dict) else None
    if not isinstance(meta, dict):
        raise ProtocolMetadataError("params._meta must be an object for 2026-07-28 requests")

    version = meta.get(_PROTOCOL_VERSION_META_KEY)
    if not isinstance(version, str) or not version:
        raise ProtocolMetadataError(
            f"params._meta[{_PROTOCOL_VERSION_META_KEY!r}] must be a non-empty string"
        )

    client_info = meta.get(_CLIENT_INFO_META_KEY)
    if not isinstance(client_info, dict):
        raise ProtocolMetadataError(f"params._meta[{_CLIENT_INFO_META_KEY!r}] must be an object")

    client_capabilities = meta.get(_CLIENT_CAPABILITIES_META_KEY)
    if not isinstance(client_capabilities, dict):
        raise ProtocolMetadataError(
            f"params._meta[{_CLIENT_CAPABILITIES_META_KEY!r}] must be an object"
        )

    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise UnsupportedProtocolVersionError(version)

    return version


# ── Error construction (SDK ErrorData / error-code constants) ───────────────


def build_invalid_params_error(req_id: Any, message: str) -> dict:
    from mcp import types as mcp_types

    error = mcp_types.ErrorData(code=mcp_types.INVALID_PARAMS, message=message)
    return {"jsonrpc": "2.0", "id": req_id, "error": error.model_dump(exclude_none=True)}


def build_unsupported_version_error(req_id: Any, exc: UnsupportedProtocolVersionError) -> dict:
    from mcp import types as mcp_types

    data = mcp_types.UnsupportedProtocolVersionErrorData(
        supported=exc.supported, requested=exc.requested
    )
    error = mcp_types.ErrorData(
        code=mcp_types.UNSUPPORTED_PROTOCOL_VERSION,
        message=f"Unsupported protocol version: {exc.requested!r}",
        data=data.model_dump(by_alias=True, exclude_none=True),
    )
    return {"jsonrpc": "2.0", "id": req_id, "error": error.model_dump(exclude_none=True)}


def protocol_error_response(req_id: Any, exc: ValueError) -> dict:
    """Dispatch a caught protocol-validation exception to the right JSON-RPC error shape."""
    if isinstance(exc, UnsupportedProtocolVersionError):
        return build_unsupported_version_error(req_id, exc)
    return build_invalid_params_error(req_id, str(exc))


# ── Modern result construction (SDK result models) ───────────────────────────


def _server_info_meta() -> dict:
    return {_SERVER_INFO_META_KEY: {"name": SERVER_NAME, "version": __version__}}


def build_discover_result() -> dict:
    """Build the modern ``server/discover`` result: capabilities, versions, cache hints."""
    from mcp import types as mcp_types

    result = mcp_types.DiscoverResult(
        supported_versions=list(SUPPORTED_PROTOCOL_VERSIONS),
        capabilities=mcp_types.ServerCapabilities(tools=mcp_types.ToolsCapability()),
        result_type="complete",
        ttl_ms=MODERN_CACHE_TTL_MS,
        cache_scope=MODERN_CACHE_SCOPE,
    )
    # Set post-construction: the `meta` field's alias ("_meta") is not a valid
    # synthesized constructor keyword under pyright's dataclass_transform view
    # of pydantic models, even though populate_by_name accepts it at runtime.
    result.meta = _server_info_meta()
    return result.model_dump(by_alias=True, exclude_none=True)


def build_tools_list_result(registry: dict) -> dict:
    """Build the modern ``tools/list`` result from the active registry, in registry order."""
    from mcp import types as mcp_types

    tools = [
        mcp_types.Tool(
            name=name, description=spec["description"], input_schema=spec["input_schema"]
        )
        for name, spec in registry.items()
    ]
    result = mcp_types.ListToolsResult(
        tools=tools,
        result_type="complete",
        ttl_ms=MODERN_CACHE_TTL_MS,
        cache_scope=MODERN_CACHE_SCOPE,
    )
    return result.model_dump(by_alias=True, exclude_none=True)


def build_call_tool_result(value: Any) -> dict:
    """Build the modern ``tools/call`` success result: legacy text content plus structuredContent."""
    from mcp import types as mcp_types

    text = json.dumps(value, indent=2, ensure_ascii=False)
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=text)],
        structured_content=value,
        is_error=False,
        result_type="complete",
    )
    return result.model_dump(by_alias=True, exclude_none=True)
