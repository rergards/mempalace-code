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
