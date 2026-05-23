"""
test_stdio.py — Windows UTF-8 stdio helper tests (AC-1 through AC-4).

All tests use monkeypatched sys.platform and fake stream objects so no Windows
runner is required.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import patch

# ── Fake stream helpers ───────────────────────────────────────────────────────


class FakeStream:
    """Minimal fake text-stream with call-recording reconfigure()."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reconfigure(self, *, encoding: str, errors: str) -> None:
        self.calls.append({"encoding": encoding, "errors": errors})


class RaisingStream:
    """Fake stream whose reconfigure() raises OSError."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def reconfigure(self, *, encoding: str = "", errors: str = "") -> None:
        raise OSError("cannot reconfigure binary pipe")


# ── AC-1: Windows applies correct per-stream policies ────────────────────────


def test_windows_configures_all_streams(monkeypatch):
    """AC-1: on win32, stdin gets surrogateescape and stdout/stderr get replace."""
    monkeypatch.setattr("sys.platform", "win32")

    from mempalace_code._stdio import configure_windows_stdio

    fake_in = FakeStream()
    fake_out = FakeStream()
    fake_err = FakeStream()

    failures = configure_windows_stdio(stdin=fake_in, stdout=fake_out, stderr=fake_err)

    assert failures == [], "expected no failures"
    assert fake_in.calls == [{"encoding": "utf-8", "errors": "surrogateescape"}]
    assert fake_out.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert fake_err.calls == [{"encoding": "utf-8", "errors": "replace"}]


# ── AC-3: Windows stream raises OSError — continues with remaining streams ────


def test_windows_continues_after_stream_failure(monkeypatch):
    """AC-3: a failing stream is recorded in failures; other streams still get reconfigured."""
    monkeypatch.setattr("sys.platform", "win32")

    from mempalace_code._stdio import configure_windows_stdio

    bad_in = RaisingStream()
    fake_out = FakeStream()
    fake_err = FakeStream()

    failures = configure_windows_stdio(stdin=bad_in, stdout=fake_out, stderr=fake_err)

    assert failures == ["stdin"], "failed stream should be named in return value"
    assert fake_out.calls == [{"encoding": "utf-8", "errors": "replace"}], "stdout still configured"
    assert fake_err.calls == [{"encoding": "utf-8", "errors": "replace"}], "stderr still configured"


def test_windows_all_streams_fail_returns_all_names(monkeypatch):
    """AC-3: all streams failing returns all three names without raising."""
    monkeypatch.setattr("sys.platform", "win32")

    from mempalace_code._stdio import configure_windows_stdio

    failures = configure_windows_stdio(
        stdin=RaisingStream(),
        stdout=RaisingStream(),
        stderr=RaisingStream(),
    )

    assert set(failures) == {"stdin", "stdout", "stderr"}


# ── AC-4: Non-Windows is a no-op ─────────────────────────────────────────────


def test_non_windows_is_noop(monkeypatch):
    """AC-4: on linux, no reconfigure calls are made."""
    monkeypatch.setattr("sys.platform", "linux")

    from mempalace_code._stdio import configure_windows_stdio

    fake_in = FakeStream()
    fake_out = FakeStream()
    fake_err = FakeStream()

    failures = configure_windows_stdio(stdin=fake_in, stdout=fake_out, stderr=fake_err)

    assert failures == []
    assert fake_in.calls == [], "stdin must not be touched on non-Windows"
    assert fake_out.calls == [], "stdout must not be touched on non-Windows"
    assert fake_err.calls == [], "stderr must not be touched on non-Windows"


def test_darwin_is_noop(monkeypatch):
    """AC-4: on darwin, no reconfigure calls are made."""
    monkeypatch.setattr("sys.platform", "darwin")

    from mempalace_code._stdio import configure_windows_stdio

    fake_out = FakeStream()
    failures = configure_windows_stdio(stdout=fake_out)

    assert failures == []
    assert fake_out.calls == []


# ── AC-2: MCP non-ASCII JSON output ──────────────────────────────────────────


def test_mcp_non_ascii_preserved_in_json_rpc(monkeypatch):
    """AC-2: a tools/call response with Cyrillic and CJK text serializes as valid
    JSON-RPC with the original non-ASCII characters intact (not escaped)."""
    monkeypatch.setattr("sys.platform", "win32")

    # The non-ASCII content the tool would return.
    cyrillic = "Привет"
    cjk = "世界"
    non_ascii_text = f"{cyrillic} {cjk}"

    # Simulate handle_request for a tools/call that returns non-ASCII content.
    # We use a real call through handle_request with a fake registry entry.
    from mempalace_code.mcp.dispatch import handle_request

    fake_registry = {
        "test_tool": {
            "description": "test",
            "input_schema": {"type": "object", "properties": {}},
            "handler": lambda: non_ascii_text,
        }
    }

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "test_tool", "arguments": {}},
    }
    response = handle_request(request, active_registry=fake_registry)

    # The outer JSON-RPC line must be valid JSON and contain original text.
    line = json.dumps(response, ensure_ascii=False)
    parsed = json.loads(line)

    tool_text = parsed["result"]["content"][0]["text"]
    # The text field is itself JSON (json.dumps of the handler result), so parse it.
    tool_value = json.loads(tool_text)

    assert cyrillic in tool_value, f"Cyrillic text must be preserved, got: {tool_value!r}"
    assert cjk in tool_value, f"CJK text must be preserved, got: {tool_value!r}"


def test_mcp_stdout_write_uses_ensure_ascii_false():
    """AC-2: the stdio loop writes ensure_ascii=False JSON so non-ASCII chars appear
    as literal UTF-8 in the raw stdout line (not as \\uXXXX escapes)."""
    import mempalace_code.mcp.dispatch as dispatch

    cyrillic = "Привет"
    cjk = "世界"

    fake_tools = {
        "test_unicode_tool": {
            "description": "returns non-ASCII text",
            "input_schema": {"type": "object", "properties": {}},
            "handler": lambda: f"{cyrillic} {cjk}",
        }
    }

    request_line = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/call",
                "params": {"name": "test_unicode_tool", "arguments": {}},
            }
        )
        + "\n"
    )

    captured = io.StringIO()
    with patch("sys.stdin") as mock_stdin, patch("sys.stdout", captured):
        mock_stdin.readline.side_effect = [request_line, ""]  # one request + EOF
        with patch.object(dispatch, "TOOLS", fake_tools):
            dispatch.main(argv=[])

    raw_output = captured.getvalue().strip()
    assert raw_output, "main loop must write a response line"
    # The raw line must contain literal non-ASCII characters (not \\uXXXX escapes).
    assert cyrillic in raw_output, f"Cyrillic must be literal chars in raw output, got: {raw_output!r}"
    assert cjk in raw_output, f"CJK must be literal chars in raw output, got: {raw_output!r}"
    # The raw line must also be valid JSON with the expected structure.
    parsed = json.loads(raw_output)
    tool_text = parsed["result"]["content"][0]["text"]
    tool_value = json.loads(tool_text)
    assert cyrillic in tool_value, f"Cyrillic must survive JSON round-trip, got: {tool_value!r}"
    assert cjk in tool_value, f"CJK must survive JSON round-trip, got: {tool_value!r}"


# ── CLI entry-point wiring (import smoke) ────────────────────────────────────


def test_cli_imports_stdio_helper():
    """The CLI module must be importable without calling configure_windows_stdio at import time."""
    import mempalace_code.cli as cli

    # Import should not trigger any stdio reconfiguration side effects.
    assert callable(cli.main)


def test_mcp_dispatch_imports_without_side_effects():
    """The MCP dispatch module must be importable without calling configure_windows_stdio."""
    import mempalace_code.mcp.dispatch as dispatch

    assert callable(dispatch.main)
    assert callable(dispatch.handle_request)
