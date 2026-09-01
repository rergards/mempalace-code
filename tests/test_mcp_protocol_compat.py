"""
test_mcp_protocol_compat.py — 2026-07-28 protocol compatibility coverage.

Subprocess stdio is the decisive acceptance surface here (see the "Design
Notes" in docs/plans/MCP-2026-PROTOCOL-COMPATIBILITY.md): direct
handle_request() calls cannot prove real JSON-RPC wire shapes or stdout
purity, so every behavioral assertion in this file goes through a real
``python -m mempalace_code.mcp_server`` subprocess.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

from mempalace_code.mcp import protocol_compat
from mempalace_code.mcp.registry import TOOLS
from mempalace_code.storage import open_store
from mempalace_code.version import __version__

_REPO_ROOT = Path(__file__).resolve().parents[1]

_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "pytest-client", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _modern_params(**extra):
    params = dict(extra)
    params["_meta"] = dict(_MODERN_META)
    return params


def _run_mcp_stdio(requests, palace_path, fresh_home, server_args=None, timeout=60):
    """Spawn the packaged MCP stdio server, feed JSON-RPC lines, return parsed responses.

    Fails the test outright if any stdout line is not valid JSON (stdout purity, INV-3).
    """
    stdin_data = "\n".join(json.dumps(r) for r in requests) + "\n" if requests else ""

    env = os.environ.copy()
    env["MEMPALACE_PALACE_PATH"] = palace_path
    env["HOME"] = fresh_home
    env["USERPROFILE"] = fresh_home
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env.pop("HF_HOME", None)
    env.pop("HUGGINGFACE_HUB_CACHE", None)
    env.pop("TRANSFORMERS_CACHE", None)

    cmd = [sys.executable, "-m", "mempalace_code.mcp_server", *(server_args or [])]
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_REPO_ROOT),
        env=env,
    )

    responses = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            pytest.fail(
                f"Non-JSON line on stdout (purity violation): {line!r}\n"
                f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )
    return responses, result


@pytest.fixture
def fresh_home():
    d = tempfile.mkdtemp(prefix="mcp_protocol_compat_home_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ── VER-1 / AC-1: dependency metadata ────────────────────────────────────


def test_mcp_sdk_dependency_is_bounded_and_locked():
    """The official mcp SDK is a direct bounded 2.x dependency and uv.lock pins a concrete 2.x package."""
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]

    mcp_dep = next(
        (d for d in deps if d.replace(" ", "").split(">=")[0].split("<")[0] == "mcp"), None
    )
    assert mcp_dep is not None, f"'mcp' not found as a direct runtime dependency: {deps}"
    normalized = mcp_dep.replace(" ", "")
    assert ">=2" in normalized, f"mcp dependency must have a lower 2.x bound, got: {mcp_dep!r}"
    assert "<3" in normalized, f"mcp dependency must have an upper <3 bound, got: {mcp_dep!r}"

    lock = tomllib.loads((_REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    mcp_lock_entries = [pkg for pkg in lock.get("package", []) if pkg.get("name") == "mcp"]
    assert mcp_lock_entries, "uv.lock has no concrete 'mcp' package entry"
    locked_version = mcp_lock_entries[0]["version"]
    assert locked_version.split(".")[0] == "2", (
        f"locked mcp version must be 2.x, got {locked_version!r}"
    )


# ── VER-2 / AC-2, AC-5: modern discover + tools/list ─────────────────────


def test_2026_discover_and_tools_list_metadata(palace_path, fresh_home):
    open_store(palace_path, create=True)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": _modern_params()},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": _modern_params()},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": _modern_params()},
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)
    assert len(responses) == 3, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    discover = responses[0]["result"]
    assert discover["resultType"] == "complete"
    assert "2026-07-28" in discover["supportedVersions"]
    assert "tools" in discover["capabilities"]
    assert discover["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": "mempalace-code",
        "version": __version__,
    }
    assert isinstance(discover["ttlMs"], int)
    assert discover["cacheScope"] in {"public", "private"}

    listing1 = responses[1]["result"]
    listing2 = responses[2]["result"]
    assert listing1["resultType"] == "complete"
    assert isinstance(listing1["ttlMs"], int)
    assert listing1["cacheScope"] in {"public", "private"}
    assert [t["name"] for t in listing1["tools"]] == list(TOOLS)
    # Deterministic across repeated calls in the same session (RISK-3 / INV-5).
    assert [t["name"] for t in listing2["tools"]] == [t["name"] for t in listing1["tools"]]
    for tool in listing1["tools"]:
        assert set(tool.keys()) >= {"name", "description", "inputSchema"}


# ── VER-3 / AC-2, AC-5: malformed / unsupported metadata ─────────────────


def test_2026_malformed_and_unsupported_metadata_errors(palace_path, fresh_home):
    open_store(palace_path, create=True)

    requests = [
        # server/discover always requires modern _meta, even fully absent.
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {}},
        # _meta present but missing required clientCapabilities key.
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "server/discover",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientInfo": {"name": "x", "version": "1"},
                }
            },
        },
        # tools/list opts into modern via _meta but names an unsupported version.
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/list",
            "params": _modern_params()
            | {
                "_meta": {
                    **_MODERN_META,
                    "io.modelcontextprotocol/protocolVersion": "1999-01-01",
                }
            },
        },
        # Legacy tools/list (no _meta at all) must be entirely unaffected (INV-4/INV-5).
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)
    assert len(responses) == 4, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    assert responses[0]["error"]["code"] == -32602
    assert responses[1]["error"]["code"] == -32602

    err3 = responses[2]["error"]
    assert err3["code"] == -32022
    assert err3["data"]["requested"] == "1999-01-01"
    assert "2026-07-28" in err3["data"]["supported"]

    legacy_list = responses[3]["result"]
    assert set(legacy_list.keys()) == {"tools"}
    assert [t["name"] for t in legacy_list["tools"]] == list(TOOLS)


# ── VER-4 / AC-3, AC-5: legacy initialize flow ───────────────────────────


def test_legacy_initialize_flow_preserves_tools_and_calls(palace_path, fresh_home):
    open_store(palace_path, create=True)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "mempalace_status", "arguments": {}},
        },
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)
    # notifications/initialized emits no response line.
    assert len(responses) == 3, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    init_result = responses[0]["result"]
    assert init_result["serverInfo"] == {"name": "mempalace-code", "version": __version__}
    assert "protocolVersion" in init_result

    listing = responses[1]["result"]
    assert set(listing.keys()) == {"tools"}, (
        "legacy tools/list must not gain resultType/ttlMs/cacheScope"
    )
    assert [t["name"] for t in listing["tools"]] == list(TOOLS)

    call_result = responses[2]["result"]
    assert set(call_result.keys()) == {"content"}, (
        "legacy tools/call must not gain structuredContent"
    )
    payload = json.loads(call_result["content"][0]["text"])
    assert "total_drawers" in payload


# ── VER-5 / AC-3, AC-5: profile filtering + disabled-tool diagnostic ─────


def test_profile_filtered_stdio_keeps_disabled_tool_diagnostic(palace_path, fresh_home):
    open_store(palace_path, create=True)

    minimal_tools = {
        "mempalace_status",
        "mempalace_search",
        "mempalace_check_duplicate",
        "mempalace_add_drawer",
    }

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": _modern_params()},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "mempalace_delete_wing", "arguments": {}},
        },
    ]
    responses, result = _run_mcp_stdio(
        requests, palace_path, fresh_home, server_args=["--profile", "minimal"]
    )
    assert len(responses) == 3, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    legacy_names = {t["name"] for t in responses[0]["result"]["tools"]}
    assert legacy_names == minimal_tools

    modern_names = {t["name"] for t in responses[1]["result"]["tools"]}
    assert modern_names == minimal_tools

    disabled = responses[2]["error"]
    assert disabled["code"] == -32601
    assert "not enabled" in disabled["message"]
    assert "active MCP profile" in disabled["message"]


# ── VER-6 / AC-2, AC-5: structured content + stdout purity ───────────────


def test_tool_results_include_text_and_structured_content_without_stdout_noise(
    palace_path, fresh_home
):
    open_store(palace_path, create=True)

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": _modern_params(name="mempalace_status", arguments={}),
        },
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)
    assert len(responses) == 1, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    call_result = responses[0]["result"]
    assert call_result["resultType"] == "complete"
    assert call_result["isError"] is False

    text_payload = json.loads(call_result["content"][0]["text"])
    assert text_payload == call_result["structuredContent"]
    assert "total_drawers" in text_payload

    # Every stdout line must be nothing but the single JSON-RPC response — no
    # banners, warnings, or log lines leaked onto stdout (INV-3).
    stdout_lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(stdout_lines) == 1


def test_modern_tools_call_with_list_returning_tool(palace_path, fresh_home):
    """A handler that returns a bare list (e.g. mempalace_find_tunnels) must round-trip
    through the modern structuredContent path unchanged — the 2026-07-28 dialect this
    server speaks allows any JSON value there, not only objects (mcp_types.CallToolResult
    .structured_content is typed Any; the object-only restriction applies to 2025-06-18
    and 2025-11-25 only)."""
    open_store(palace_path, create=True)

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": _modern_params(name="mempalace_find_tunnels", arguments={}),
        },
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)
    assert len(responses) == 1, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    call_result = responses[0]["result"]
    assert call_result["isError"] is False
    assert call_result["structuredContent"] == []
    text_payload = json.loads(call_result["content"][0]["text"])
    assert text_payload == []


# ── VER-7 / AC-3, AC-5: _meta presence alone must not force the modern path ──


def test_legacy_request_with_progress_token_meta_stays_legacy(palace_path, fresh_home):
    """A legacy (non-2026-07-28) client may attach the base-protocol ``_meta.progressToken``
    to any request. That alone must not be treated as opting into the modern dialect
    (INV-4): the tool must still execute and return the legacy content-only shape,
    not a -32602 protocol-metadata error."""
    open_store(palace_path, create=True)

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mempalace_status",
                "arguments": {},
                "_meta": {"progressToken": "abc123"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {"_meta": {"progressToken": "abc123"}},
        },
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)
    assert len(responses) == 2, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"

    call_result = responses[0]["result"]
    assert set(call_result.keys()) == {"content"}, (
        "legacy tools/call with an unrelated _meta key must not gain structuredContent"
    )
    payload = json.loads(call_result["content"][0]["text"])
    assert "total_drawers" in payload

    listing = responses[1]["result"]
    assert set(listing.keys()) == {"tools"}, (
        "legacy tools/list with an unrelated _meta key must not gain resultType/ttlMs/cacheScope"
    )
    assert [t["name"] for t in listing["tools"]] == list(TOOLS)


def test_sdk_meta_key_constants_match_mirrored_literals():
    """protocol_compat mirrors the SDK's reserved _meta key constants as plain literals
    (see the module docstring) so a purely legacy request path never imports the SDK.
    This is the one-time cross-check for that mirror, replacing the bare asserts that
    used to run on every validate_modern_meta call (previously: silently compiled out
    under python -O, and any AssertionError would have escaped dispatch's caught
    exception tuples and hung the client instead of returning a JSON-RPC error)."""
    from mcp import types as mcp_types

    assert mcp_types.PROTOCOL_VERSION_META_KEY == protocol_compat._PROTOCOL_VERSION_META_KEY
    assert mcp_types.CLIENT_INFO_META_KEY == protocol_compat._CLIENT_INFO_META_KEY
    assert mcp_types.CLIENT_CAPABILITIES_META_KEY == protocol_compat._CLIENT_CAPABILITIES_META_KEY


# ── MCP-DEGRADED-CLIENT-ERROR-CONTAINMENT ────────────────────────────────────


def _run_mcp_raw(raw_lines, palace_path, fresh_home, server_args=None, timeout=60):
    """Like _run_mcp_stdio but accepts pre-formatted string lines (for malformed-input tests).

    All stdout lines must still be valid JSON; a non-JSON line fails the test.
    """
    stdin_data = "\n".join(raw_lines) + "\n" if raw_lines else ""

    env = os.environ.copy()
    env["MEMPALACE_PALACE_PATH"] = palace_path
    env["HOME"] = fresh_home
    env["USERPROFILE"] = fresh_home
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env.pop("HF_HOME", None)
    env.pop("HUGGINGFACE_HUB_CACHE", None)
    env.pop("TRANSFORMERS_CACHE", None)

    cmd = [sys.executable, "-m", "mempalace_code.mcp_server", *(server_args or [])]
    result = subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_REPO_ROOT),
        env=env,
    )

    responses = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except json.JSONDecodeError:
            pytest.fail(
                f"Non-JSON line on stdout (purity violation): {line!r}\n"
                f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
            )
    return responses, result


def test_required_schema_tools_no_traceback_on_empty_args(palace_path, fresh_home):
    """All 20 required-schema tools called with empty args return -32602, no traceback (AC-1, AC-4)."""
    open_store(palace_path, create=True)

    required_tools = [
        (name, spec["input_schema"].get("required", []))
        for name, spec in TOOLS.items()
        if spec["input_schema"].get("required")
    ]
    assert len(required_tools) == 20, (
        f"Expected 20 required-schema tools, got {len(required_tools)}; "
        "update this guard if the registry changes"
    )

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    ]
    tool_req_id_to_name = {}
    for i, (name, _) in enumerate(required_tools, start=2):
        requests.append(
            {
                "jsonrpc": "2.0",
                "id": i,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            }
        )
        tool_req_id_to_name[i] = name

    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)

    # initialize (id=1) + 20 tool responses; notifications/initialized emits no response
    assert len(responses) == 1 + len(required_tools), (
        f"Expected {1 + len(required_tools)} responses, got {len(responses)}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    assert "result" in responses[0], f"initialize must succeed: {responses[0]}"

    for resp in responses[1:]:
        name = tool_req_id_to_name.get(resp["id"], f"id={resp['id']}")
        assert "error" in resp, f"Tool {name} with empty args: expected error, got result: {resp}"
        assert resp["error"]["code"] == -32602, (
            f"Tool {name}: expected -32602 (Invalid params), got {resp['error']['code']}: "
            f"{resp['error']['message']}"
        )

    assert "Traceback" not in result.stderr, (
        f"Python traceback leaked to stderr for required-schema tools:\n{result.stderr}"
    )
    assert "TypeError" not in result.stderr, (
        f"TypeError leaked to stderr for required-schema tools:\n{result.stderr}"
    )


def test_malformed_then_valid_continuity(palace_path, fresh_home):
    """Malformed JSON produces a -32700 parse error; subsequent valid requests still succeed (AC-2)."""
    open_store(palace_path, create=True)

    raw_lines = [
        "this is not json{{",
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
    ]
    responses, result = _run_mcp_raw(raw_lines, palace_path, fresh_home)

    # parse error + initialize + tools/list
    assert len(responses) == 3, (
        f"Expected 3 responses, got {len(responses)}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # First response: JSON-RPC parse error with null id (spec §5.1)
    assert responses[0]["id"] is None
    assert "error" in responses[0]
    assert responses[0]["error"]["code"] == -32700

    # Server remained available for subsequent valid requests
    assert responses[1]["id"] == 1
    assert "result" in responses[1]
    assert responses[1]["result"]["serverInfo"]["name"] == "mempalace-code"

    assert responses[2]["id"] == 2
    assert "result" in responses[2]
    assert "tools" in responses[2]["result"]

    assert "Traceback" not in result.stderr, (
        f"Traceback leaked to stderr after malformed input:\n{result.stderr}"
    )


def test_duplicate_initialize_deterministic(palace_path, fresh_home):
    """Sending initialize twice returns two identical deterministic success responses (AC-3)."""
    open_store(palace_path, create=True)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)

    assert len(responses) == 2, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    for resp in responses:
        assert "result" in resp, f"Expected result, got: {resp}"
        assert resp["result"]["serverInfo"]["name"] == "mempalace-code"

    # Both responses carry identical result payloads (deterministic — no mutable state change)
    assert responses[0]["result"] == responses[1]["result"], (
        "Duplicate initialize must return identical results"
    )


def test_clean_eof_exit(palace_path, fresh_home):
    """Server exits cleanly (code 0) on immediate EOF with no output (AC-3)."""
    open_store(palace_path, create=True)

    responses, result = _run_mcp_stdio([], palace_path, fresh_home)

    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert responses == [], "No output expected on empty input"


def test_profile_disabled_tool_returns_bounded_error_no_traceback(palace_path, fresh_home):
    """Calling a tool disabled by --profile returns -32601 with no traceback (AC-3, AC-4)."""
    open_store(palace_path, create=True)

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "mempalace_delete_wing", "arguments": {"wing": "x"}},
        },
    ]
    responses, result = _run_mcp_stdio(
        requests, palace_path, fresh_home, server_args=["--profile", "minimal"]
    )

    assert len(responses) == 1, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    assert responses[0]["error"]["code"] == -32601
    assert "not enabled" in responses[0]["error"]["message"]
    assert "Traceback" not in result.stderr


# ── MCP-DEGRADED-CLIENT-ERROR-CONTAINMENT — schema guard boundary ──────────
#
# Shared parameter table: (tool_name, arguments, expected_code, msg_fragment)
# Each row proves a distinct class of client-induced bad input at the dispatch
# layer, where dispatch.py must return a bounded -32602 without invoking the
# handler or leaking any Python traceback.
_SCHEMA_GUARD_CASES = [
    # ── existing: integer / number coercion failures ──────────────────────────
    pytest.param(
        "mempalace_search",
        {"query": "hello", "limit": "not-a-number"},
        -32602,
        "type mismatch",
        id="invalid_integer_coercion",
    ),
    pytest.param(
        "mempalace_check_duplicate",
        {"content": "x", "threshold": [1, 2, 3]},
        -32602,
        "type mismatch",
        id="invalid_number_coercion",
    ),
    pytest.param(
        "mempalace_status",
        {"ghost_arg": "surprise"},
        -32602,
        "undeclared",
        id="undeclared_argument",
    ),
    # ── string property receives wrong type ───────────────────────────────────
    pytest.param(
        "mempalace_search",
        {"query": 42},
        -32602,
        "type mismatch",
        id="string_receives_integer",
    ),
    pytest.param(
        "mempalace_search",
        {"query": None},
        -32602,
        "type mismatch",
        id="string_receives_null",
    ),
    # ── boolean property receives wrong type ──────────────────────────────────
    pytest.param(
        "mempalace_mine",
        {"directory": "/tmp", "full": "true"},
        -32602,
        "type mismatch",
        id="boolean_receives_string",
    ),
    pytest.param(
        "mempalace_mine",
        {"directory": "/tmp", "full": None},
        -32602,
        "type mismatch",
        id="boolean_receives_null",
    ),
    # ── integer/number must reject bool (bool is int subclass in Python) ──────
    pytest.param(
        "mempalace_search",
        {"query": "hello", "limit": True},
        -32602,
        "type mismatch",
        id="integer_receives_bool",
    ),
    pytest.param(
        "mempalace_check_duplicate",
        {"content": "x", "threshold": True},
        -32602,
        "type mismatch",
        id="number_receives_bool",
    ),
    # ── integer must reject fractional floats (1.5 → silent truncation to 1) ──
    pytest.param(
        "mempalace_search",
        {"query": "hello", "limit": 1.5},
        -32602,
        "type mismatch",
        id="integer_receives_fractional_float",
    ),
]

# ── valid boundary representatives: type guard must not narrow correct inputs ──
#
# Each entry is (tool_name, arguments). Dispatch must NOT return -32602 — the
# value has the right type (or a coercible equivalent already supported). The
# handler may fail with -32000 if no palace is available; that is irrelevant.
_SCHEMA_GUARD_VALID_CASES = [
    pytest.param("mempalace_search", {"query": "hello"}, id="string_valid"),
    pytest.param("mempalace_mine", {"directory": "/tmp", "full": False}, id="boolean_valid_false"),
    pytest.param("mempalace_mine", {"directory": "/tmp", "full": True}, id="boolean_valid_true"),
    pytest.param("mempalace_search", {"query": "hello", "limit": 10}, id="integer_valid_native"),
    # String that int() can parse — preserved coercion from the original guard.
    pytest.param(
        "mempalace_search", {"query": "hello", "limit": "10"}, id="integer_valid_string_coerce"
    ),
    pytest.param(
        "mempalace_check_duplicate", {"content": "x", "threshold": 0.8}, id="number_valid_float"
    ),
    pytest.param(
        "mempalace_check_duplicate", {"content": "x", "threshold": 1}, id="number_valid_int"
    ),
    # Whole-number float is a valid integer boundary (1.0 → 1, no truncation).
    pytest.param(
        "mempalace_search", {"query": "hello", "limit": 1.0}, id="integer_valid_whole_float"
    ),
]


def _required_argument_placeholders(spec):
    properties = spec["input_schema"].get("properties", {})
    values_by_type = {
        "string": "valid-value",
        "boolean": False,
        "integer": 1,
        "number": 0.5,
    }
    arguments = {}
    for name in spec["input_schema"].get("required", []):
        declared_type = properties[name]["type"]
        assert declared_type in values_by_type, (
            f"Add a typed test placeholder for required {name!r} ({declared_type!r})"
        )
        arguments[name] = values_by_type[declared_type]
    return arguments


def _palace_byte_snapshot(palace_path):
    root = Path(palace_path)
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_required_string_guard_exhausts_live_registry_before_handlers():
    """Every live required string rejects blank variants before its handler can run."""
    from mempalace_code.mcp.dispatch import handle_request

    assert len(TOOLS) == 29, "The release contract requires the live 29-tool registry"
    required_strings = []
    for tool_name, spec in TOOLS.items():
        properties = spec["input_schema"].get("properties", {})
        for argument_name in spec["input_schema"].get("required", []):
            if properties[argument_name].get("type") == "string":
                required_strings.append((tool_name, argument_name, spec))
    assert required_strings, "The live registry must expose required strings"

    for tool_name, argument_name, spec in required_strings:
        for blank in ("", "   ", "\t", " \t\n"):
            calls = []

            def recording_handler(*, _calls=calls, **arguments):
                _calls.append(arguments)
                return {"unexpected": True}

            arguments = _required_argument_placeholders(spec)
            arguments[argument_name] = blank
            registry = {tool_name: {**spec, "handler": recording_handler}}
            response = handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": 91,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                },
                active_registry=registry,
            )

            assert response["error"] == {
                "code": -32602,
                "message": f"Invalid params: blank required argument(s): {argument_name}",
            }
            assert calls == [], f"{tool_name}.{argument_name} invoked its handler for {blank!r}"
            if blank:
                assert blank not in response["error"]["message"]


def test_required_string_guard_preserves_valid_and_optional_strings_verbatim():
    """The blank predicate does not normalize valid required or optional strings."""
    from mempalace_code.mcp.dispatch import handle_request

    cases = []
    for tool_name, spec in TOOLS.items():
        properties = spec["input_schema"].get("properties", {})
        required = spec["input_schema"].get("required", [])
        for argument_name in required:
            if properties[argument_name].get("type") == "string":
                cases.append((tool_name, argument_name, "  valid content\t", spec))
        optional_string = next(
            (
                name
                for name, property_schema in properties.items()
                if name not in required and property_schema.get("type") == "string"
            ),
            None,
        )
        if optional_string is not None:
            cases.append((tool_name, optional_string, " \t ", spec))

    for tool_name, argument_name, original_value, spec in cases:
        calls = []

        def recording_handler(*, _calls=calls, **arguments):
            _calls.append(arguments)
            return {"captured": True}

        arguments = _required_argument_placeholders(spec)
        arguments[argument_name] = original_value
        registry = {tool_name: {**spec, "handler": recording_handler}}
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 92,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            active_registry=registry,
        )

        assert "result" in response, response
        assert calls == [arguments]
        assert calls[0][argument_name] == original_value


def test_required_string_guard_via_full_stdio_preserves_state_and_continues(
    palace_path, fresh_home
):
    """Blank calls cannot mutate a disposable palace and do not desynchronise stdio."""
    open_store(palace_path, create=True)
    before = _palace_byte_snapshot(palace_path)
    requests = []
    expected_fields = {}
    request_id = 1
    for tool_name, spec in TOOLS.items():
        properties = spec["input_schema"].get("properties", {})
        for argument_name in spec["input_schema"].get("required", []):
            if properties[argument_name].get("type") != "string":
                continue
            for blank in ("", "   \t"):
                arguments = _required_argument_placeholders(spec)
                arguments[argument_name] = blank
                requests.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    }
                )
                expected_fields[request_id] = argument_name
                request_id += 1
    continuation_id = request_id
    requests.append({"jsonrpc": "2.0", "id": continuation_id, "method": "tools/list", "params": {}})

    responses, result = _run_mcp_stdio(
        requests, palace_path, fresh_home, server_args=["--profile", "full"]
    )

    assert len(responses) == len(requests), (
        f"Expected {len(requests)} responses, got {len(responses)}; stderr={result.stderr!r}"
    )
    for response in responses[:-1]:
        field = expected_fields[response["id"]]
        assert response["error"] == {
            "code": -32602,
            "message": f"Invalid params: blank required argument(s): {field}",
        }
    assert responses[-1]["id"] == continuation_id
    assert [tool["name"] for tool in responses[-1]["result"]["tools"]] == list(TOOLS)
    assert _palace_byte_snapshot(palace_path) == before
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("tool_name,arguments,expected_code,msg_fragment", _SCHEMA_GUARD_CASES)
def test_schema_guard_via_handle_request(tool_name, arguments, expected_code, msg_fragment):
    """handle_request() intercepts invalid coercions and undeclared args before handler invocation."""
    from mempalace_code.mcp.dispatch import handle_request

    request = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = handle_request(request)
    assert "error" in resp, f"Expected error response, got: {resp}"
    assert resp["error"]["code"] == expected_code
    assert msg_fragment in resp["error"]["message"]


@pytest.mark.parametrize("tool_name,arguments,expected_code,msg_fragment", _SCHEMA_GUARD_CASES)
def test_schema_guard_via_stdio(
    palace_path, fresh_home, tool_name, arguments, expected_code, msg_fragment
):
    """Same schema guard boundary verified over the real stdio wire (stdout purity, no traceback)."""
    open_store(palace_path, create=True)

    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    ]
    responses, result = _run_mcp_stdio(requests, palace_path, fresh_home)

    assert len(responses) == 1, f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    assert "error" in responses[0], f"Expected error response, got: {responses[0]}"
    assert responses[0]["error"]["code"] == expected_code
    assert msg_fragment in responses[0]["error"]["message"]
    assert "Traceback" not in result.stderr
    assert "TypeError" not in result.stderr
    assert "ValueError" not in result.stderr


@pytest.mark.parametrize("tool_name,arguments", _SCHEMA_GUARD_VALID_CASES)
def test_schema_guard_valid_boundaries_via_handle_request(tool_name, arguments):
    """Correct primitive types pass dispatch type checks — no -32602 on valid input."""
    from mempalace_code.mcp.dispatch import handle_request

    request = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = handle_request(request)
    if "error" in resp:
        assert resp["error"]["code"] != -32602, (
            f"Valid args for {tool_name} {arguments!r} must not trigger type-mismatch guard; "
            f"got: {resp['error']}"
        )


def test_unexpected_handler_failure_is_sanitized_and_logged(caplog):
    """An unexpected exception inside a handler returns -32000, leaks no detail to the client,
    and is observable in the mempalace_mcp logger (logger.exception path)."""
    from mempalace_code.mcp.dispatch import handle_request

    def _boom():
        raise RuntimeError("internal chaos — must not reach client")

    boom_registry = {
        "boom_tool": {
            "description": "always raises",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "handler": _boom,
        }
    }

    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "boom_tool", "arguments": {}},
    }

    with caplog.at_level(logging.ERROR, logger="mempalace_mcp"):
        resp = handle_request(request, active_registry=boom_registry)

    assert resp["error"]["code"] == -32000, f"Expected -32000, got: {resp}"
    serialised = json.dumps(resp)
    assert "chaos" not in serialised, "Handler exception detail must not reach the client"
    assert "Traceback" not in serialised

    logged_messages = " ".join(r.getMessage() for r in caplog.records)
    assert "boom_tool" in logged_messages, (
        "logger.exception must record the tool name so operators can diagnose the failure"
    )
