"""UAT regressions for the MCP protocol surface and the write/diary tools.

Wire-level behaviour (framing, parse errors, notifications) is asserted through a
real ``python -m mempalace_code.mcp_server`` subprocess; argument and tool-result
contracts go through ``handle_request`` with the real registry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_server(lines: list[bytes], home: Path, *args: str, timeout: int = 60):
    """Feed raw byte lines to a fresh stdio server; return (responses, completed process)."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["MEMPALACE_PALACE_PATH"] = str(home / "palace")
    env["HF_HUB_OFFLINE"] = "1"
    env.pop("MEMPALACE_AGENT_NAME", None)
    result = subprocess.run(
        [sys.executable, "-m", "mempalace_code.mcp_server", *args],
        input=b"".join(line + b"\n" for line in lines),
        capture_output=True,
        timeout=timeout,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    responses = [json.loads(line) for line in result.stdout.decode("utf-8").splitlines() if line]
    return responses, result


def _req(req_id, method, params=None) -> bytes:
    request: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        request["params"] = params
    return json.dumps(request).encode()


# ── mcp-7: every unparseable line gets a -32700 reply ──────────────────────


def test_unparseable_lines_each_get_a_parse_error_and_the_session_continues(tmp_path):
    huge_id = b'{"jsonrpc":"2.0","id":' + b"9" * 5000 + b',"method":"tools/list"}'
    huge_arg = (
        b'{"jsonrpc":"2.0","id":778,"method":"tools/call","params":{"name":"mempalace_search",'
        b'"arguments":{"query":"x","limit":' + b"7" * 5000 + b"}}}"
    )
    deep = b'{"jsonrpc":"2.0","id":779,"method":"tools/list","params":' + b"[" * 200000
    deep += b"]" * 200000 + b"}"
    bad_utf8 = b'{"jsonrpc":"2.0","id":780,"method":"tools/list","x":"\xff"}'
    responses, result = _run_server(
        [huge_id, huge_arg, deep, bad_utf8, _req(99, "tools/list")], tmp_path
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert len(responses) == 5, responses
    for response in responses[:4]:
        assert response["id"] is None
        assert response["error"]["code"] == -32700
        assert response["error"]["message"].startswith("Parse error: ")
    assert "digits" in responses[0]["error"]["message"]
    assert "set_int_max_str_digits" not in responses[0]["error"]["message"]
    assert "too deep" in responses[2]["error"]["message"]
    assert "UTF-8" in responses[3]["error"]["message"]
    assert responses[4]["id"] == 99
    assert responses[4]["result"]["tools"]


def test_handle_line_rejects_surrogate_escaped_text_lines():
    from mempalace_code.mcp.dispatch import _handle_line

    response = _handle_line('{"jsonrpc":"2.0","id":1,"method":"tools/list","x":"\udcff"}')
    assert response is not None
    assert response["error"]["code"] == -32700
    assert response["id"] is None


def test_unpaired_surrogate_escapes_are_answered_and_rejected_as_arguments(tmp_path):
    # JSON "\ud800" is well-formed text a client can send by cutting a string
    # mid-pair; echoing it back must not leave the request unanswered.
    lines = [
        rb'{"jsonrpc":"2.0","id":"\ud800","method":"ping"}',
        rb'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"mempalace_nope\ud800"}}',
        rb'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"mempalace_search",'
        rb'"arguments":{"query":"checkout","wing":"\ud800"}}}',
        rb'{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"mempalace_add_drawer",'
        rb'"arguments":{"wing":"shop","room":"notes","content":"half pair \ud800 here"}}}',
        _req(5, "ping"),
    ]
    responses, result = _run_server(lines, tmp_path)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"Server error" not in result.stderr
    assert [response["id"] for response in responses] == ["\ud800", 2, 3, 4, 5]
    assert responses[0]["result"] == {}
    assert responses[1]["error"] == {
        "code": -32601,
        "message": "Unknown tool: mempalace_nope\ud800",
    }
    for response, argument in ((responses[2], "wing"), (responses[3], "content")):
        assert response["error"]["code"] == -32602
        assert response["error"]["message"].endswith(f"argument(s): {argument}")
    assert not (tmp_path / "palace").exists(), "rejected arguments must not open the palace"


def test_serialized_responses_keep_text_unescaped_unless_utf8_cannot_carry_it():
    from mempalace_code.mcp.dispatch import _serialize_response

    plain = _serialize_response({"jsonrpc": "2.0", "id": 1, "result": {"wing": "café"}})
    assert "café" in plain
    lone = _serialize_response({"jsonrpc": "2.0", "id": "\ud800", "result": {"wing": "café"}})
    lone.encode("utf-8")
    assert json.loads(lone)["id"] == "\ud800"
    assert json.loads(lone)["result"]["wing"] == "café"


# ── mcp-9: notifications are never answered and never run a tool ─────────


def test_requests_without_an_id_are_not_answered_or_executed(tmp_path):
    add_drawer = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "mempalace_add_drawer",
            "arguments": {"wing": "notif", "room": "probe", "content": "notification probe"},
        },
    }
    lines = [
        json.dumps(add_drawer).encode(),
        b'{"jsonrpc":"2.0","method":"tools/list"}',
        b'{"jsonrpc":"2.0","method":"notifications/initialized"}',
        _req(5, "tools/list"),
    ]
    responses, result = _run_server(lines, tmp_path)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert [response["id"] for response in responses] == [5]
    assert not (tmp_path / "palace").exists(), "a notification must not create palace state"
    assert b"sent without an id" in result.stderr


def test_handle_request_returns_none_for_any_notification():
    from mempalace_code.mcp.dispatch import handle_request
    from mempalace_code.mcp.registry import TOOLS

    for method in ("tools/list", "ping", "notifications/cancelled", "unknown/method"):
        assert handle_request({"jsonrpc": "2.0", "method": method}, active_registry=TOOLS) is None
    # An explicit null id is still a request and is answered.
    response = handle_request({"jsonrpc": "2.0", "id": None, "method": "ping"}, TOOLS)
    assert response == {"jsonrpc": "2.0", "id": None, "result": {}}
    # A message without a usable method stays an Invalid Request, even without an id.
    assert handle_request({"jsonrpc": "2.0"}, TOOLS)["error"]["code"] == -32600


# ── agent-16: ping ──────────────────────────────────────────────────────────


_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def test_ping_answers_an_empty_result_in_both_dialects(tmp_path):
    lines = [
        _req(1, "initialize", {"protocolVersion": "2024-11-05"}),
        _req(16, "ping", {}),
        _req(17, "ping"),
        _req(18, "ping", {"_meta": _MODERN_META}),
        _req(19, "ping", {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}),
    ]
    responses, result = _run_server(lines, tmp_path)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    by_id = {response["id"]: response for response in responses}
    assert by_id[16] == {"jsonrpc": "2.0", "id": 16, "result": {}}
    assert by_id[17] == {"jsonrpc": "2.0", "id": 17, "result": {}}
    assert by_id[18]["result"] == {"resultType": "complete"}
    assert by_id[19]["error"]["code"] == -32602


# ── agent-12: tool-level failures set isError ──────────────────────────────


def _registry_returning(payload):
    return {
        "probe": {
            "description": "returns a fixed payload",
            "input_schema": {"type": "object", "properties": {}},
            "handler": lambda: payload,
        }
    }


@pytest.mark.parametrize(
    ("payload", "is_error"),
    [
        ({"error": "unknown_wing", "suggestions": ["mpc"]}, True),
        ({"success": False, "error": "Drawer not found: nope"}, True),
        ({"success": False, "reason": "duplicate", "matches": []}, True),
        ({"success": True, "drawer_id": "d1"}, False),
        ({"results": [], "error": None}, False),
        ([{"room": "shared"}], False),
    ],
)
def test_tool_level_failures_set_is_error_in_both_dialects(payload, is_error):
    from mempalace_code.mcp.dispatch import handle_request

    registry = _registry_returning(payload)
    legacy = handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "probe"}},
        active_registry=registry,
    )
    modern = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "probe", "_meta": _MODERN_META},
        },
        active_registry=registry,
    )

    assert json.loads(legacy["result"]["content"][0]["text"]) == payload
    if is_error:
        assert legacy["result"]["isError"] is True
    else:
        # Successful legacy results keep their exact historical envelope.
        assert set(legacy["result"]) == {"content"}
    assert modern["result"]["isError"] is is_error


# ── Real-registry helpers ───────────────────────────────────────────────────


@pytest.fixture
def mcp(monkeypatch, config, palace_path, kg):
    """Call real tools through handle_request against an isolated palace and KG."""
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.dispatch import handle_request
    from mempalace_code.mcp.registry import TOOLS

    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_kg", kg)
    monkeypatch.setattr(runtime, "_store", None)
    monkeypatch.delenv("MEMPALACE_AGENT_NAME", raising=False)

    def call(name, arguments=None, *, params=None):
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": params if params is not None else {"name": name, "arguments": arguments},
        }
        return handle_request(request, active_registry=TOOLS)

    return call


def _payload(response):
    assert "result" in response, response
    return json.loads(response["result"]["content"][0]["text"])


# ── mcp-5 / agent-8 / kg-4: KG argument errors are -32602 naming the argument ─


@pytest.mark.parametrize(
    ("tool", "arguments", "argument", "fragment"),
    [
        ("mempalace_kg_query", {"entity": "myapp", "as_of": "not-a-date"}, "as_of", "not-a-date"),
        ("mempalace_kg_query", {"entity": "myapp", "as_of": "2026-02-30"}, "as_of", "2026-02-30"),
        (
            "mempalace_kg_add",
            {"subject": "a", "predicate": "p", "object": "b", "valid_from": "yesterday"},
            "valid_from",
            "expected YYYY-MM-DD",
        ),
        (
            "mempalace_kg_add",
            {"subject": "a", "predicate": "p", "object": "b", "valid_from": "2026-13-45"},
            "valid_from",
            "month must be in 1..12",
        ),
        (
            "mempalace_kg_add",
            {
                "subject": "a",
                "predicate": "p",
                "object": "b",
                "valid_from": "2026-09-26T10:00:00+02:00",
            },
            "valid_from",
            "UTC ISO datetime",
        ),
        (
            "mempalace_kg_add",
            {
                "subject": "a",
                "predicate": "p",
                "object": "b",
                "valid_from": "2026-05-01",
                "valid_to": "2026-01-01",
            },
            "valid_to",
            "Inverted validity window",
        ),
        (
            "mempalace_kg_invalidate",
            {"subject": "a", "predicate": "p", "object": "b", "ended": "garbage"},
            "ended",
            "garbage",
        ),
    ],
)
def test_kg_argument_errors_are_invalid_params_naming_the_argument(
    mcp, tool, arguments, argument, fragment
):
    response = mcp(tool, arguments)

    assert "result" not in response
    assert response["error"]["code"] == -32602
    message = response["error"]["message"]
    assert message.startswith(f"Invalid params: {argument}: ")
    assert fragment in message


def test_kg_invalidate_before_valid_from_names_ended(mcp):
    added = mcp(
        "mempalace_kg_add",
        {
            "subject": "Alice",
            "predicate": "works_on",
            "object": "Orion",
            "valid_from": "2025-01-10",
        },
    )
    assert _payload(added)["success"] is True

    response = mcp(
        "mempalace_kg_invalidate",
        {"subject": "Alice", "predicate": "works_on", "object": "Orion", "ended": "2024-01-01"},
    )

    assert response["error"]["code"] == -32602
    assert response["error"]["message"].startswith("Invalid params: ended: Inverted invalidation")


def test_unexpected_value_errors_stay_internal(monkeypatch, mcp):
    from mempalace_code.mcp import runtime

    class _BrokenKG:
        def query_entity(self, *args, **kwargs):
            raise ValueError("database row decode failed")

    monkeypatch.setattr(runtime, "_kg", _BrokenKG())
    response = mcp("mempalace_kg_query", {"entity": "x"})
    assert response["error"] == {"code": -32000, "message": "Internal tool error"}


def test_tool_result_text_is_compact_json(mcp):
    from mempalace_code.mcp.protocol_compat import build_call_tool_result

    text = mcp("mempalace_kg_query", {"entity": "nobody"})["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert text == json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    modern = build_call_tool_result({"a": [1, "é"]})
    assert modern["content"][0]["text"] == '{"a":[1,"é"]}'


def test_unreadable_palace_is_a_tool_error_carrying_the_recovery(monkeypatch, mcp):
    from mempalace_code.mcp import runtime
    from mempalace_code.storage import PalaceReadError

    class _UnreadableStore:
        def count(self):
            raise PalaceReadError("/p/palace", RuntimeError("lance fragment missing"))

    monkeypatch.setattr(runtime, "_get_store", lambda create=False: _UnreadableStore())
    response = mcp("mempalace_status", {})

    assert "error" not in response
    assert response["result"]["isError"] is True
    text = response["result"]["content"][0]["text"]
    assert "lance fragment missing" in text
    assert "--palace /p/palace health" in text


# ── agent-17 / mcp-13: one argument validator, schema ranges enforced ─────


@pytest.mark.parametrize(
    ("tool", "arguments", "fragment"),
    [
        ("mempalace_search", {"query": "a", "limit": 0}, "limit (expected 1 to 50, got 0)"),
        ("mempalace_search", {"query": "a", "limit": -3}, "limit (expected 1 to 50, got -3)"),
        (
            "mempalace_check_duplicate",
            {"content": "x", "threshold": 1.5},
            "threshold (expected -1 to 1, got 1.5)",
        ),
        (
            "mempalace_check_duplicate",
            {"content": "x", "threshold": -2},
            "threshold (expected -1 to 1, got -2)",
        ),
        (
            "mempalace_check_duplicate",
            {"content": "x", "threshold": "7"},
            "threshold (expected -1 to 1, got 7.0)",
        ),
        (
            "mempalace_diary_read",
            {"agent_name": "tester", "last_n": -1},
            "last_n (expected at least 1, got -1)",
        ),
        (
            "mempalace_code_search",
            {"query": "a", "n_results": 0},
            "n_results (expected 1 to 50, got 0)",
        ),
        (
            "mempalace_explain_subsystem",
            {"query": "a", "n_results": -2},
            "n_results (expected 1 to 50, got -2)",
        ),
        (
            "mempalace_show_type_dependencies",
            {"type_name": "T", "max_depth": 0},
            "max_depth (expected at least 1, got 0)",
        ),
        (
            "mempalace_extract_reusable",
            {"entity": "E", "max_depth": -1},
            "max_depth (expected at least 1, got -1)",
        ),
        (
            "mempalace_traverse",
            {"start_room": "auth", "max_hops": -1},
            "max_hops (expected at least 0, got -1)",
        ),
    ],
)
def test_schema_ranges_are_enforced_as_invalid_params(mcp, tool, arguments, fragment):
    response = mcp(tool, arguments)

    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == (
        f"Invalid params: out-of-range value for argument(s): {fragment}"
    )


def test_range_bounds_are_declared_in_the_published_schemas():
    from mempalace_code.mcp.registry import TOOLS

    def prop(tool, name):
        return TOOLS[tool]["input_schema"]["properties"][name]

    assert prop("mempalace_search", "limit")["minimum"] == 1
    assert prop("mempalace_check_duplicate", "threshold")["minimum"] == -1
    assert prop("mempalace_check_duplicate", "threshold")["maximum"] == 1
    assert prop("mempalace_diary_read", "last_n")["minimum"] == 1


def test_in_range_boundaries_and_integral_values_are_accepted(mcp, collection):
    collection.add(
        ids=["d1"], documents=["boundary content"], metadatas=[{"wing": "w", "room": "r"}]
    )
    for threshold in (-1, 1, "0.5", 0.9):
        payload = _payload(
            mcp("mempalace_check_duplicate", {"content": "x", "threshold": threshold})
        )
        assert "is_duplicate" in payload
    # Integer arguments accept any JSON form of an integral value; 2.5 is not one.
    assert "results" in _payload(mcp("mempalace_search", {"query": "boundary", "limit": "1"}))
    assert "results" in _payload(mcp("mempalace_search", {"query": "boundary", "limit": 1.0}))
    fractional = mcp("mempalace_search", {"query": "boundary", "limit": 2.5})
    assert fractional["error"]["message"] == (
        "Invalid params: type mismatch for argument(s): limit (expected integer, got float)"
    )


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "Invalid params: missing required argument(s): name"),
        ({"arguments": {}}, "Invalid params: missing required argument(s): name"),
        ({"name": 5}, "Invalid params: name must be a non-empty string"),
        ({"name": "  "}, "Invalid params: name must be a non-empty string"),
    ],
)
def test_tools_call_without_a_tool_name_is_invalid_params(mcp, params, message):
    response = mcp(None, params=params)
    assert response["error"] == {"code": -32602, "message": message}


def test_tools_call_without_params_is_invalid_params():
    from mempalace_code.mcp.dispatch import handle_request
    from mempalace_code.mcp.registry import TOOLS

    response = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call"}, TOOLS)
    assert response["error"]["code"] == -32602


# ── mcp-10 / agent-19: add_drawer wing/room names ──────────────────────────


def _fresh(palace_path):
    """A new store handle: the fixture's handle does not see later MCP writes."""
    from mempalace_code.storage import open_store

    return open_store(palace_path, create=False)


def test_add_drawer_trims_and_refuses_respelled_wings_and_rooms(mcp, collection, palace_path):
    collection.add(
        ids=["seed"],
        documents=["Seeded shop drawer about the checkout service."],
        metadatas=[{"wing": "shop", "room": "notes"}],
    )

    trimmed = _payload(
        mcp("mempalace_add_drawer", {"wing": " shop ", "room": "notes ", "content": "Refunds."})
    )
    assert trimmed["success"] is True
    assert (trimmed["wing"], trimmed["room"]) == ("shop", "notes")
    assert trimmed["drawer_id"].startswith("drawer_shop_notes_")

    cased = mcp("mempalace_add_drawer", {"wing": "Shop", "room": "notes", "content": "Invoices."})
    assert cased["result"]["isError"] is True
    assert _payload(cased)["error"] == "similar_wing_exists"
    assert _payload(cased)["suggestions"] == ["shop"]

    room = mcp("mempalace_add_drawer", {"wing": "shop", "room": "Notes", "content": "Taxes."})
    assert _payload(room)["error"] == "similar_room_exists"
    assert _payload(room)["suggestions"] == ["notes"]

    fresh = _payload(
        mcp("mempalace_add_drawer", {"wing": "shopping", "room": "notes", "content": "Carts."})
    )
    assert fresh["success"] is True
    assert set(_fresh(palace_path).count_by("wing")) == {"shop", "shopping"}


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"wing": "../etc", "room": "r"}, "wing '../etc' must not contain '/', '\\' or control"),
        ({"wing": "a\\b", "room": "r"}, "wing 'a\\\\b' must not contain"),
        ({"wing": "w", "room": "x/y"}, "room 'x/y' must not contain"),
        ({"wing": "w", "room": "tab\there"}, "room 'tab\\there' must not contain"),
    ],
)
def test_add_drawer_refuses_path_like_or_control_names(mcp, palace_path, arguments, message):
    response = mcp("mempalace_add_drawer", {**arguments, "content": "Path-like wing note."})

    assert response["error"]["code"] == -32602
    assert message in response["error"]["message"]
    assert list(Path(palace_path).iterdir()) == [], "names are validated before the palace opens"


def test_near_duplicate_names_ignores_exact_and_non_latin_names():
    from mempalace_code.taxonomy_filters import near_duplicate_names

    assert near_duplicate_names("shop", ["shop", "Shop"]) == []
    assert near_duplicate_names("My-App", ["my_app", "myapp2"]) == ["my_app"]
    assert near_duplicate_names("проект", ["дом", "Проект"]) == ["Проект"]
    assert near_duplicate_names("---", ["___"]) == []


def test_near_duplicate_names_keeps_plus_and_hash_significant():
    from mempalace_code.taxonomy_filters import near_duplicate_names

    assert near_duplicate_names("c++", ["c", "c#"]) == []
    assert near_duplicate_names("c#", ["c", "c++"]) == []
    assert near_duplicate_names("C++", ["c++", "c"]) == ["c++"]
    assert near_duplicate_names("F #", ["f#"]) == ["f#"]


# ── mcp-dup: distinct templated facts are not duplicates ───────────────────


def test_add_drawer_stores_templated_facts_that_differ_by_numbers(mcp, pin_cosine, palace_path):
    contents = [
        pin_cosine(
            f"Decision {i}: we adopted the vermilion-{i} caching policy after the incident "
            f"review on day {i}. Owner: team-{i % 3}.",
            0.97,
            axis=10 + i,
        )
        for i in range(6)
    ]
    for content in contents:
        payload = _payload(
            mcp(
                "mempalace_add_drawer", {"wing": "decisions", "room": "caching", "content": content}
            )
        )
        assert payload["success"] is True, payload
    assert _fresh(palace_path).count() == 6


def test_add_drawer_still_refuses_a_near_identical_copy(mcp, pin_cosine, palace_path):
    original = pin_cosine("Decision 7: adopt the vermilion-7 caching policy.", 0.99, axis=20)
    repeat = pin_cosine("Decision 7: we adopt the vermilion-7 caching policy!", 0.99, axis=21)
    assert _payload(mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": original}))[
        "success"
    ]

    response = mcp("mempalace_add_drawer", {"wing": "w", "room": "r", "content": repeat})
    payload = _payload(response)
    assert response["result"]["isError"] is True
    assert payload["reason"] == "duplicate"
    assert [match["content"] for match in payload["matches"]] == [original]
    assert "hint" in payload
    assert _fresh(palace_path).count() == 1


def test_distinguishing_tokens_are_numbers_and_identifiers():
    from mempalace_code.mcp.tools.write import _distinguishing_tokens

    tokens = _distinguishing_tokens(
        "Decision 5: the CheckoutService in shop/api.py uses vermilion-5 and plain words."
    )
    assert tokens == {"5", "CheckoutService", "shop/api.py", "vermilion-5"}


# ── convos-17 / convos-18 / agent-14: one diary identity for CLI and MCP ───


def _cli(argv, capsys):
    from unittest.mock import patch

    from mempalace_code.cli import main

    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_diary_entry_under_a_custom_wing_is_read_back_by_mcp(mcp, palace_path, capsys):
    code, out, _ = _cli(
        [
            "--palace",
            palace_path,
            "diary",
            "write",
            "--agent",
            "codex",
            "--entry",
            "Custom wing entry DIARY_WING_CANARY.",
            "--wing",
            "convos",
            "--topic",
            "ops",
        ],
        capsys,
    )
    assert code == 0
    assert "Wing: convos" in out
    assert _payload(mcp("mempalace_diary_write", {"agent_name": "codex", "entry": "Default."}))[
        "success"
    ]

    payload = _payload(mcp("mempalace_diary_read", {"agent_name": "codex"}))

    assert payload["total"] == 2
    by_wing = {entry["wing"]: entry for entry in payload["entries"]}
    assert by_wing["convos"]["content"] == "Custom wing entry DIARY_WING_CANARY."
    assert by_wing["convos"]["topic"] == "ops"
    assert by_wing["wing_codex"]["content"] == "Default."


def test_diary_identity_ignores_case_spaces_and_hyphens(mcp):
    for name in ("claude-code", "Claude Code"):
        assert _payload(mcp("mempalace_diary_write", {"agent_name": name, "entry": name}))[
            "success"
        ]

    for reader in ("claude-code", "Claude Code", "CLAUDE_CODE"):
        payload = _payload(mcp("mempalace_diary_read", {"agent_name": reader}))
        assert sorted(entry["content"] for entry in payload["entries"]) == [
            "Claude Code",
            "claude-code",
        ]
    other = _payload(mcp("mempalace_diary_read", {"agent_name": "claude"}))
    assert other["entries"] == []


@pytest.mark.parametrize(
    ("extra", "error"),
    [
        (["--topic", ""], "Error: --topic must not be blank.\n"),
        (["--topic", "   "], "Error: --topic must not be blank.\n"),
        (["--wing", "  "], "Error: --wing must not be blank.\n"),
        (["--wing", ""], "Error: --wing must not be blank.\n"),
        (
            ["--wing", "../etc"],
            "Error: --wing '../etc' must not contain '/', '\\' or control characters.\n",
        ),
        (
            ["--agent", "a/b"],
            "Error: --agent 'a/b' must not contain '/', '\\' or control characters.\n",
        ),
    ],
)
def test_cli_diary_write_refuses_blank_or_unsafe_names_without_poststate(
    tmp_path, capsys, extra, error
):
    palace = tmp_path / "absent-palace"
    argv = ["--palace", str(palace), "diary", "write", "--agent", "tester", "--entry", "text"]

    code, out, err = _cli([*argv, *extra], capsys)

    assert code == 2
    assert out == ""
    assert err.startswith(error)
    assert err.count("\n") == 2
    assert err.splitlines()[1].startswith("Try: ")
    assert not palace.exists()


def test_cli_diary_write_refuses_a_wing_that_respells_an_existing_one(mcp, palace_path, capsys):
    assert _payload(
        mcp("mempalace_add_drawer", {"wing": "shop", "room": "notes", "content": "Shop wing."})
    )["success"]
    argv = ["--palace", palace_path, "diary", "write", "--agent", "tester", "--entry"]

    code, out, err = _cli([*argv, "Respelled wing via CLI", "--wing", "Shop"], capsys)

    assert code == 2
    assert out == ""
    assert err.splitlines() == [
        "Error: --wing 'Shop' differs from the existing wing 'shop' only by case, spacing "
        "or punctuation; wing names are case-sensitive.",
        "Try: --wing shop to file under the existing wing, or choose a clearly different name.",
    ]
    read = _payload(mcp("mempalace_diary_read", {"agent_name": "tester"}))
    assert read["entries"] == []

    code, out, _ = _cli([*argv, "Exact wing via CLI", "--wing", " shop "], capsys)
    assert code == 0
    assert "Wing: shop" in out


def test_mcp_diary_write_refuses_a_blank_topic(mcp):
    response = mcp("mempalace_diary_write", {"agent_name": "tester", "entry": "x", "topic": " "})
    assert response["error"] == {
        "code": -32602,
        "message": "Invalid params: topic must not be blank",
    }


def test_diary_agent_name_defaults_to_the_server_environment(mcp, monkeypatch):
    missing = mcp("mempalace_diary_write", {"entry": "no identity"})
    assert missing["error"]["code"] == -32602
    assert missing["error"]["message"].startswith("Invalid params: agent_name is required")
    assert "MEMPALACE_AGENT_NAME" in missing["error"]["message"]

    monkeypatch.setenv("MEMPALACE_AGENT_NAME", " uat-agent ")
    written = _payload(mcp("mempalace_diary_write", {"entry": "env identity entry"}))
    assert written["agent"] == "uat-agent"
    read = _payload(mcp("mempalace_diary_read", {}))
    assert read["agent"] == "uat-agent"
    assert [entry["content"] for entry in read["entries"]] == ["env identity entry"]
    # An explicit name still wins over the environment.
    explicit = _payload(mcp("mempalace_diary_read", {"agent_name": "someone-else"}))
    assert explicit["entries"] == []


def test_unusable_agent_name_environment_is_named_in_the_error(mcp, monkeypatch):
    monkeypatch.setenv("MEMPALACE_AGENT_NAME", "team/agent")

    response = mcp("mempalace_diary_write", {"entry": "env identity entry"})

    assert response["error"]["code"] == -32602
    message = response["error"]["message"]
    assert message.startswith("Invalid params: MEMPALACE_AGENT_NAME 'team/agent' must not contain")
    assert "pass agent_name" in message
    # An explicit, valid agent_name does not consult the environment.
    assert _payload(mcp("mempalace_diary_write", {"agent_name": "ok", "entry": "fine"}))["success"]


def test_diary_tool_schemas_make_agent_name_optional():
    from mempalace_code.mcp.registry import TOOLS

    assert TOOLS["mempalace_diary_write"]["input_schema"]["required"] == ["entry"]
    assert TOOLS["mempalace_diary_read"]["input_schema"]["required"] == []
    for tool in ("mempalace_diary_write", "mempalace_diary_read"):
        description = TOOLS[tool]["input_schema"]["properties"]["agent_name"]["description"]
        assert "MEMPALACE_AGENT_NAME" in description


# ── install-16: launcher names and versions ────────────────────────────────


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("mempalace_code.mcp_launcher", "mempalace-code-mcp"),
        ("mempalace_code.mcp_server", "mempalace-code-mcp"),
        ("mempalace_code", "mempalace-code"),
    ],
)
def test_launchers_report_their_command_name_and_version(tmp_path, module, expected):
    from mempalace_code.version import __version__

    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    version = subprocess.run(
        [sys.executable, "-m", module, "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    assert version.returncode == 0, version.stderr
    assert version.stdout == f"{expected} {__version__}\n"

    usage = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
        env=env,
    )
    assert usage.returncode == 0, usage.stderr
    assert usage.stdout.startswith(f"usage: {expected} ")


# ── hooks-7: the Save hook names only tools the plugin profile exposes ─────


def test_save_hook_reason_is_conditional_on_tools_outside_the_minimal_profile():
    import re

    from mempalace_code.mcp_tool_profiles import PROFILES

    script = (_REPO_ROOT / "hooks" / "mempal_save_hook.sh").read_text(encoding="utf-8")
    heredoc = script.split("cat << 'HOOKJSON'\n", 1)[1].split("\nHOOKJSON", 1)[0]
    reason = json.loads(heredoc)["reason"]

    assert "Use only the MCP tools in your tool list." in reason
    conditional = "If mempalace_diary_write is listed, call it once"
    assert conditional in reason
    assert "otherwise skip the diary" in reason
    assert "agent_name" in reason
    unconditional = reason.replace(conditional, "")
    for tool in set(re.findall(r"mempalace_\w+", unconditional)) - {"mempalace_diary_write"}:
        assert tool in PROFILES["minimal"], tool


# ── agent-15: SKILL.md gives the minimal profile a valid move on duplicates ─


def test_skill_store_advice_is_possible_with_the_minimal_profile():
    from mempalace_code.agent_plugins import SKILL_PATH, get_agent_plugin_root

    skill = (get_agent_plugin_root() / SKILL_PATH).read_text(encoding="utf-8")
    store = " ".join(skill.split("## Store", 1)[1].split("## Guards", 1)[0].split())

    assert "merge the new fact into one concise drawer" not in store
    assert "cannot edit or merge stored drawers" in store
    assert "file only the new fact in a short drawer that cites the existing drawer id" in store
    assert "`reason: duplicate`" in store
    assert "report them and stop" in store
    assert "re-spells an existing one is refused" in store
