"""
test_mcp_server.py — Tests for the MCP server tool handlers and dispatch.

Tests each tool handler directly (unit-level) and the handle_request
dispatch layer (integration-level). Uses isolated palace + KG fixtures
via monkeypatch to avoid touching real data.
"""

import json

import pytest

from mempalace_code.storage import open_store


def _patch_mcp_server(monkeypatch, config, palace_path, kg):
    """Patch the mcp runtime module globals to use test fixtures."""
    from mempalace_code.mcp import runtime

    assert getattr(config, "palace_path", None) == palace_path, (
        f"config.palace_path ({getattr(config, 'palace_path', None)!r}) does not match palace_path fixture ({palace_path!r})"
    )
    monkeypatch.setattr(runtime, "_config", config)
    monkeypatch.setattr(runtime, "_kg", kg)
    # Reset the singleton store so it re-opens with the test palace
    monkeypatch.setattr(runtime, "_store", None)


def _ensure_store(palace_path):
    """Helper to ensure a store exists at the test palace path."""
    return open_store(palace_path, create=True)


# ── Protocol Layer ──────────────────────────────────────────────────────


class TestHandleRequest:
    def test_initialize(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "initialize", "id": 1, "params": {}})
        assert resp is not None
        assert resp["result"]["serverInfo"]["name"] == "mempalace-code"
        assert resp["id"] == 1

    def test_notifications_initialized_returns_none(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "notifications/initialized", "id": None, "params": {}})
        assert resp is None

    def test_tools_list(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 2, "params": {}})
        assert resp is not None
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "mempalace_status" in names
        assert "mempalace_search" in names
        assert "mempalace_add_drawer" in names
        assert "mempalace_kg_add" in names
        assert "mempalace_delete_wing" in names

    def test_unknown_tool(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 3,
                "params": {"name": "nonexistent_tool", "arguments": {}},
            }
        )
        assert resp is not None
        assert resp["error"]["code"] == -32601

    def test_unknown_method(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "unknown/method", "id": 4, "params": {}})
        assert resp is not None
        assert resp["error"]["code"] == -32601

    def test_tools_call_dispatches(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace_code.mcp_server import handle_request

        # Ensure store exists
        _ensure_store(palace_path)

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 5,
                "params": {"name": "mempalace_status", "arguments": {}},
            }
        )
        assert resp is not None
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content

    # AC-1: null arguments must not crash; tool result must contain total_drawers
    def test_tools_call_null_arguments(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 10,
                "params": {"name": "mempalace_status", "arguments": None},
            }
        )
        assert resp is not None
        assert "result" in resp, f"expected result, got: {resp}"
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content

    # AC-1 variant: omitted arguments key also normalizes to {}
    def test_tools_call_missing_arguments(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 11,
                "params": {"name": "mempalace_status"},
            }
        )
        assert resp is not None
        assert "result" in resp, f"expected result, got: {resp}"
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content

    # AC-2: wait_for_previous noise key is stripped, tool returns normal result
    def test_tools_call_strips_wait_for_previous(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 12,
                "params": {
                    "name": "mempalace_status",
                    "arguments": {"wait_for_previous": False},
                },
            }
        )
        assert resp is not None
        assert "result" in resp, f"expected result, got: {resp}"
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content

    # AC-2 extended: declared args survive alongside noise key
    def test_tools_call_strips_noise_preserves_declared_args(
        self, monkeypatch, config, palace_path, seeded_kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import handle_request

        # mempalace_search declares "query"; wait_for_previous is noise
        resp = handle_request(
            {
                "method": "tools/call",
                "id": 13,
                "params": {
                    "name": "mempalace_search",
                    "arguments": {"query": "test query", "wait_for_previous": False},
                },
            }
        )
        # Should return a result (not an Internal tool error) because query was preserved
        assert resp is not None
        assert "result" in resp, f"expected result, got: {resp}"

    # AC-3: unknown notifications/* method returns None (fire-and-forget)
    def test_unknown_notification_returns_none(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "notifications/cancelled", "id": None, "params": {}})
        assert resp is None

    # AC-4: unknown non-notification method still returns -32601
    def test_unknown_non_notification_method_returns_error(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "unknown/method", "id": 14, "params": {}})
        assert resp is not None
        assert resp["error"]["code"] == -32601

    # AC-5: unknown tool + null arguments returns Unknown tool error, does not raise
    def test_unknown_tool_null_arguments_no_crash(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 15,
                "params": {"name": "nonexistent_tool", "arguments": None},
            }
        )
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32601
        assert "Unknown tool" in resp["error"]["message"]

    # Non-dict arguments return -32602 (invalid params)
    def test_tools_call_non_dict_arguments_returns_invalid_params(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 16,
                "params": {"name": "mempalace_status", "arguments": ["not", "a", "dict"]},
            }
        )
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    # Request-level params=null must not crash; returns Unknown tool because no name was set
    def test_tools_call_request_params_null(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/call", "id": 17, "params": None})
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32601


# ── Read Tools ──────────────────────────────────────────────────────────


class TestReadTools:
    def test_status_empty_palace(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == 0
        assert result["wings"] == {}

    def test_status_with_data(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == 4
        assert "project" in result["wings"]
        assert "notes" in result["wings"]

    def test_list_wings(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_list_wings

        result = tool_list_wings()
        assert result["wings"]["project"] == 3  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert result["wings"]["notes"] == 1  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_list_rooms_all(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_list_rooms

        result = tool_list_rooms()
        assert "backend" in result["rooms"]
        assert "frontend" in result["rooms"]
        assert "planning" in result["rooms"]

    def test_list_rooms_filtered(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_list_rooms

        result = tool_list_rooms(wing="project")
        assert "backend" in result["rooms"]
        assert "planning" not in result["rooms"]

    def test_get_taxonomy(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_get_taxonomy

        result = tool_get_taxonomy()
        assert result["taxonomy"]["project"]["backend"] == 2  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert result["taxonomy"]["project"]["frontend"] == 1  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert result["taxonomy"]["notes"]["planning"] == 1  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_no_palace_returns_error(self, monkeypatch, config, kg):
        config._file_config["palace_path"] = "/nonexistent/path"
        _patch_mcp_server(monkeypatch, config, "/nonexistent/path", kg)
        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert "error" in result

    def test_status_no_aaak_by_default(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        monkeypatch.delenv("MEMPALACE_AAAK", raising=False)
        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert "aaak_dialect" not in result
        assert "protocol" not in result

    def test_status_aaak_when_env_set(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        monkeypatch.setenv("MEMPALACE_AAAK", "1")
        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert "aaak_dialect" in result
        assert "protocol" in result

    def test_get_aaak_spec_always_available(self, monkeypatch, config, palace_path, kg):
        """mempalace_get_aaak_spec returns the spec regardless of MEMPALACE_AAAK (AC-3)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_get_aaak_spec

        monkeypatch.delenv("MEMPALACE_AAAK", raising=False)
        result = tool_get_aaak_spec()
        assert "aaak_spec" in result
        assert "AAAK" in result["aaak_spec"]

        monkeypatch.setenv("MEMPALACE_AAAK", "1")
        result = tool_get_aaak_spec()
        assert "aaak_spec" in result
        assert "AAAK" in result["aaak_spec"]


# ── Search Tool ─────────────────────────────────────────────────────────


class TestSearchTool:
    def test_search_basic(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_search

        result = tool_search(query="JWT authentication tokens")
        assert "results" in result
        assert len(result["results"]) > 0
        # Top result should be the auth drawer
        top = result["results"][0]
        assert "JWT" in top["text"] or "authentication" in top["text"].lower()

    def test_search_with_wing_filter(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_search

        result = tool_search(query="planning", wing="notes")
        assert all(r["wing"] == "notes" for r in result["results"])

    def test_search_with_room_filter(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_search

        result = tool_search(query="database", room="backend")
        assert all(r["room"] == "backend" for r in result["results"])

    def test_tool_search_full_source_file_path(
        self, monkeypatch, config, palace_path, collection, kg
    ):
        collection.add(
            ids=["auth_tool_search"],
            documents=["def authenticate(): validate JWT token and return the current user"],
            metadatas=[
                {
                    "wing": "project",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_search

        result = tool_search(query="authenticate JWT", limit=1)

        assert result["results"][0]["source_file"] == "/project/src/auth.py"


# ── Write Tools ─────────────────────────────────────────────────────────


class TestWriteTools:
    def test_add_drawer_after_status_on_new_palace(self, monkeypatch, config, palace_path, kg):
        """_get_store singleton must not cache a broken stub when palace doesn't exist yet.

        Regression: tool_status() with create=False used to cache a LanceStore
        with _table=None.  A subsequent tool_add_drawer() call would return the
        cached stub and fail with RuntimeError("Table does not exist and create=False").
        """
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_add_drawer, tool_status

        # Step 1: read-only call on a palace that has no lance dir yet.
        # New behaviour: returns _no_palace() rather than a zero-count stub,
        # and must NOT cache the missing-store sentinel (so step 2 can write).
        status_result = tool_status()
        assert "error" in status_result, f"Expected _no_palace() error, got: {status_result}"

        # Step 2: write call must succeed — not hit the cached broken stub
        add_result = tool_add_drawer(
            wing="test_wing",
            room="general",
            content="Content written after initial status call.",
        )
        assert add_result["success"] is True

    def test_add_drawer(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_add_drawer

        result = tool_add_drawer(
            wing="test_wing",
            room="test_room",
            content="This is a test memory about Python decorators and metaclasses.",
        )
        assert result["success"] is True
        assert result["wing"] == "test_wing"
        assert result["room"] == "test_room"
        assert result["drawer_id"].startswith("drawer_test_wing_test_room_")

    def test_tool_add_drawer_sets_provenance(self, monkeypatch, config, palace_path, kg):
        """tool_add_drawer must set extractor_version and chunker_strategy=manual_v1 (AC-1)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_add_drawer
        from mempalace_code.storage import open_store
        from mempalace_code.version import __version__

        result = tool_add_drawer(
            wing="test_prov",
            room="general",
            content="This is a provenance test drawer content for AC-1.",
        )
        assert result["success"] is True

        store = open_store(palace_path, create=False)
        fetched = store.get(ids=[result["drawer_id"]], include=["metadatas"])
        assert fetched["ids"]
        meta = fetched["metadatas"][0]
        assert meta["chunker_strategy"] == "manual_v1"
        assert meta["extractor_version"] == __version__

    def test_add_drawer_duplicate_detection(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_add_drawer

        content = "This is a unique test memory about Rust ownership and borrowing."
        result1 = tool_add_drawer(wing="w", room="r", content=content)
        assert result1["success"] is True

        result2 = tool_add_drawer(wing="w", room="r", content=content)
        assert result2["success"] is False
        assert result2["reason"] == "duplicate"

    def test_delete_drawer(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import _get_store, tool_delete_drawer

        result = tool_delete_drawer("drawer_proj_backend_aaa")
        assert result["success"] is True
        # Verify through the MCP server's store (same connection path)
        store = _get_store()
        assert store is not None
        assert store.count() == 3

    def test_delete_drawer_not_found(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_delete_drawer

        result = tool_delete_drawer("nonexistent_drawer")
        assert result["success"] is False

    def test_delete_wing(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import _get_store, tool_delete_wing

        result = tool_delete_wing("project")
        assert result["success"] is True
        assert result["wing"] == "project"
        assert result["deleted_count"] == 3
        store = _get_store()
        assert store is not None
        assert store.count() == 1

    def test_delete_wing_not_found(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_delete_wing

        result = tool_delete_wing("nonexistent_wing")
        assert result["success"] is False
        assert "error" in result

    def test_delete_wing_storage_error(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_delete_wing
        from mempalace_code.storage import LanceStore

        def explode(self_store, wing):
            raise RuntimeError("simulated storage failure")

        # Patch at the class level: tool_delete_wing(create=True) discards a cached
        # read-only handle and opens a new instance, so instance-level patches miss.
        monkeypatch.setattr(LanceStore, "delete_wing", explode)

        result = tool_delete_wing("project")
        assert result["success"] is False
        assert "simulated storage failure" in result["error"]

    def test_check_duplicate(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_check_duplicate

        # Exact match text from seeded_collection should be flagged
        result = tool_check_duplicate(
            "The authentication module uses JWT tokens for session management. "
            "Tokens expire after 24 hours. Refresh tokens are stored in HttpOnly cookies.",
            threshold=0.5,
        )
        assert result["is_duplicate"] is True

        # Unrelated content should not be flagged
        result = tool_check_duplicate(
            "Black holes emit Hawking radiation at the event horizon.",
            threshold=0.99,
        )
        assert result["is_duplicate"] is False


# ── KG Tools ────────────────────────────────────────────────────────────


class TestKGTools:
    def test_kg_add(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="likes",
            object="coffee",
            valid_from="2025-01-01",
        )
        assert result["success"] is True

    def test_kg_query(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace_code.mcp_server import tool_kg_query

        result = tool_kg_query(entity="Max")
        assert result["count"] > 0

    def test_kg_invalidate(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace_code.mcp_server import tool_kg_invalidate

        result = tool_kg_invalidate(
            subject="Max",
            predicate="does",
            object="chess",
            ended="2026-03-01",
        )
        assert result["success"] is True

    def test_kg_timeline(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace_code.mcp_server import tool_kg_timeline

        result = tool_kg_timeline(entity="Alice")
        assert result["count"] > 0

    def test_kg_stats(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace_code.mcp_server import tool_kg_stats

        result = tool_kg_stats()
        assert result["entities"] >= 4

    def test_kg_query_arch_facts_queryable(self, monkeypatch, config, palace_path, kg):
        """Architecture is_pattern and is_layer facts are queryable via mempalace_kg_query."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_kg_query

        kg.add_triple("UserService", "is_pattern", "Service")
        kg.add_triple("UserRepository", "is_layer", "Data")

        svc_result = tool_kg_query(entity="Service", direction="incoming")
        assert svc_result["count"] > 0
        subjects = {r["subject"] for r in svc_result["facts"]}
        assert "UserService" in subjects

        data_result = tool_kg_query(entity="Data", direction="incoming")
        assert data_result["count"] > 0
        subjects = {r["subject"] for r in data_result["facts"]}
        assert "UserRepository" in subjects

    def test_kg_add_stores_full_window_and_source_metadata(
        self, monkeypatch, config, palace_path, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="works_at",
            object="Corp",
            valid_from="2026-01-01",
            valid_to="2027-12-31",
            source_closet="drawer_abc",
            source_file="notes.md",
        )
        assert result["success"] is True

        # Inspect stored metadata via iter_all_triples
        all_rows = [r for batch in kg.iter_all_triples() for r in batch]
        corp_row = next(r for r in all_rows if r["predicate"] == "works_at")
        assert corp_row["valid_from"] == "2026-01-01"
        assert corp_row["valid_to"] == "2027-12-31"
        assert corp_row["source_closet"] == "drawer_abc"
        assert corp_row["source_file"] == "notes.md"

    def test_kg_tools_reject_invalid_temporal_arguments_before_write(
        self, monkeypatch, config, palace_path, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_kg_add, tool_kg_invalidate, tool_kg_query

        before = kg.stats()["triples"]

        # Invalid valid_from on add
        with pytest.raises(ValueError, match="Invalid temporal"):
            tool_kg_add(subject="A", predicate="b", object="C", valid_from="next year")

        # Inverted window on add
        with pytest.raises(ValueError, match="Inverted validity window"):
            tool_kg_add(
                subject="A",
                predicate="b",
                object="C",
                valid_from="2026-06-01",
                valid_to="2026-01-01",
            )

        assert kg.stats()["triples"] == before

        # Invalid as_of on query
        with pytest.raises(ValueError, match="Invalid temporal"):
            tool_kg_query(entity="Alice", as_of="two weeks ago")

        # Invalid ended on invalidate
        kg.add_triple("X", "knows", "Y", valid_from="2026-01-01")
        with pytest.raises(ValueError, match="Invalid temporal"):
            tool_kg_invalidate(subject="X", predicate="knows", object="Y", ended="last month")

    def test_kg_query_returns_source_file_provenance(
        self, monkeypatch, config, palace_path, kg
    ):
        """AC-1: kg_query exposes source_file on sourced facts and preserves source_closet."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_kg_add, tool_kg_query

        tool_kg_add(
            subject="AuthService",
            predicate="implements",
            object="IAuthService",
            source_closet="closet_42",
            source_file="src/auth.py",
        )

        result = tool_kg_query(entity="IAuthService", direction="incoming")
        assert result["count"] == 1
        fact = result["facts"][0]
        assert fact["subject"] == "AuthService"
        assert fact["source_file"] == "src/auth.py"
        assert fact["source_closet"] == "closet_42"

    def test_kg_timeline_returns_source_file_provenance(
        self, monkeypatch, config, palace_path, kg
    ):
        """AC-2: kg_timeline exposes source_file on timeline rows without altering temporal fields."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_kg_add, tool_kg_timeline

        tool_kg_add(
            subject="AuthService",
            predicate="implements",
            object="IAuthService",
            valid_from="2026-01-01",
            source_file="src/auth.py",
        )

        result = tool_kg_timeline(entity="AuthService")
        assert result["count"] == 1
        row = result["timeline"][0]
        assert row["subject"] == "AuthService"
        assert row["predicate"] == "implements"
        assert row["object"] == "IAuthService"
        assert row["valid_from"] == "2026-01-01"
        assert row["source_file"] == "src/auth.py"
        assert row["current"] is True

    def test_kg_query_and_timeline_keep_legacy_unsourced_rows(
        self, monkeypatch, config, palace_path, kg
    ):
        """AC-5: triples stored without source_file are still returned with source_file=None."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_kg_add, tool_kg_query, tool_kg_timeline

        tool_kg_add(subject="Legacy", predicate="uses", object="OldLib")

        query_result = tool_kg_query(entity="Legacy", direction="outgoing")
        assert query_result["count"] == 1
        assert query_result["facts"][0]["source_file"] is None

        timeline_result = tool_kg_timeline(entity="Legacy")
        assert timeline_result["count"] == 1
        assert timeline_result["timeline"][0]["source_file"] is None


# ── Diary Tools ─────────────────────────────────────────────────────────


class TestDiaryTools:
    def test_diary_write_and_read(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_diary_read, tool_diary_write

        w = tool_diary_write(
            agent_name="TestAgent",
            entry="Today we discussed authentication patterns.",
            topic="architecture",
        )
        assert w["success"] is True
        assert w["agent"] == "TestAgent"

        r = tool_diary_read(agent_name="TestAgent")
        assert r["total"] == 1
        assert r["entries"][0]["topic"] == "architecture"  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert "authentication" in r["entries"][0]["content"]  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_diary_read_empty(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_diary_read

        r = tool_diary_read(agent_name="Nobody")
        assert r["entries"] == []

    def test_diary_write_collision_resistance(self, monkeypatch, config, palace_path, kg):
        """AC-1: two writes with identical content and same agent must both succeed with distinct IDs."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_diary_write

        r1 = tool_diary_write(agent_name="TestAgent", entry="same entry", topic="test")
        r2 = tool_diary_write(agent_name="TestAgent", entry="same entry", topic="test")
        assert r1["success"] is True, f"first write failed: {r1}"
        assert r2["success"] is True, f"second write failed: {r2}"
        assert r1["entry_id"] != r2["entry_id"], "IDs must be distinct"

    def test_diary_read_beyond_legacy_limit(self, monkeypatch, config, palace_path, kg):
        """tool_diary_read must return entries when diary count exceeds legacy 10k limit."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        # Simulate what happens when count() > 10000: seed count() by adding
        # drawers in other wings so count() > the number of diary entries.
        # We verify the fetch is not artificially capped by inserting diary
        # entries directly and checking last_n is respected.
        from mempalace_code.mcp_server import tool_diary_read, tool_diary_write

        for i in range(3):
            tool_diary_write(agent_name="BoundaryAgent", entry=f"Entry number {i}", topic="test")

        r = tool_diary_read(agent_name="BoundaryAgent", last_n=2)
        assert r["showing"] == 2
        assert r["total"] == 3


# ── Aggregation Regression Tests ─────────────────────────────────────────


class TestCodeSearchTool:
    def test_code_search_basic(self, monkeypatch, config, palace_path, code_seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="language detection file extension")
        assert "results" in result
        assert len(result["results"]) > 0
        hit = result["results"][0]
        for field in (
            "text",
            "wing",
            "room",
            "source_file",
            "symbol_name",
            "symbol_type",
            "language",
            "line_range",
            "similarity",
        ):
            assert field in hit, f"Missing field: {field}"
        assert hit["line_range"] is None

    def test_code_search_language_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="code function", language="python")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["language"] == "python" for r in result["results"])

    def test_code_search_symbol_name_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="detect language user", symbol_name="detect")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all("detect" in r["symbol_name"].lower() for r in result["results"])

    def test_code_search_symbol_type_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="code function", symbol_type="function")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["symbol_type"] == "function" for r in result["results"])

    def test_code_search_file_glob_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="code storage", file_glob="*/mempalace/*.py")
        assert "results" in result
        assert len(result["results"]) > 0
        import fnmatch

        for r in result["results"]:
            assert fnmatch.fnmatch(r["source_file"], "*/mempalace/*.py"), (
                f"source_file {r['source_file']!r} did not match glob"
            )

    def test_code_search_combined_filters(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="code", language="python", symbol_type="function")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["language"] == "python" for r in result["results"])
        assert all(r["symbol_type"] == "function" for r in result["results"])

    def test_code_search_invalid_language(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="something", language="cobol")
        assert "error" in result
        assert "supported_languages" in result
        assert "python" in result["supported_languages"]
        # Verify config-file languages are included in the hint list (AC regression guard)
        for lang in ("yaml", "json", "toml"):
            assert lang in result["supported_languages"], (
                f"{lang!r} missing from supported_languages"
            )

    def test_code_search_yaml_language(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """code_search(language='yaml') must return results, not an error (AC-1)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        # Seed a yaml drawer directly so the filter returns at least one hit.
        code_seeded_collection.add(
            ids=["code_yaml_pyproject"],
            documents=["name = 'mempalace'\nversion = '0.1.0'\n[tool.ruff]\nline-length = 100"],
            metadatas=[
                {
                    "wing": "mempalace",
                    "room": "backend",
                    "source_file": "/project/mempalace/pyproject.toml",
                    "language": "yaml",
                    "symbol_name": "",
                    "symbol_type": "",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-06T00:00:00",
                }
            ],
        )
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="project configuration", language="yaml")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) > 0, (
            "language='yaml' filter returned no results despite seeded data"
        )

    def test_code_search_cpp_language(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """code_search(language='cpp') must return results, not an error (AC-2)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        # Seed a cpp drawer directly so the filter returns at least one hit.
        code_seeded_collection.add(
            ids=["code_cpp_node"],
            documents=["class Node {\npublic:\n    int val;\n    Node* next;\n};\n"],
            metadatas=[
                {
                    "wing": "mempalace",
                    "room": "backend",
                    "source_file": "/project/src/node.cpp",
                    "language": "cpp",
                    "symbol_name": "Node",
                    "symbol_type": "class",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-06T00:00:00",
                }
            ],
        )
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="linked list node", language="cpp")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) > 0, (
            "language='cpp' filter returned no results despite seeded data"
        )

    def test_code_search_invalid_symbol_type(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="something", symbol_type="variable")
        assert "error" in result
        assert "valid_symbol_types" in result
        assert "function" in result["valid_symbol_types"]

    def test_code_search_n_results_clamp(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result_zero = tool_code_search(query="code", n_results=0)
        assert "results" in result_zero
        assert len(result_zero["results"]) <= 1

        result_huge = tool_code_search(query="code", n_results=999)
        assert "results" in result_huge
        assert len(result_huge["results"]) <= 50

    def test_code_search_wing_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="code storage", wing="mempalace")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["wing"] == "mempalace" for r in result["results"])

    def test_code_search_in_tools_list(self):
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert "mempalace_code_search" in tools

        schema = tools["mempalace_code_search"]["inputSchema"]
        props = schema["properties"]
        assert set(props.keys()) == {
            "query",
            "language",
            "symbol_name",
            "symbol_type",
            "file_glob",
            "wing",
            "n_results",
            "rerank",
        }
        assert schema.get("required") == ["query"]
        assert props["n_results"]["type"] == "integer"
        assert props["rerank"]["type"] == "string"

    def test_code_search_accepts_hybrid_rerank_param(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="language detection file extension", rerank="hybrid")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_code_search_react_and_dart_in_language_description(self):
        """The mempalace_code_search language description must mention jsx, tsx, and dart."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 100, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        lang_desc = tools["mempalace_code_search"]["inputSchema"]["properties"]["language"][
            "description"
        ]
        for lang in ("jsx", "tsx", "dart"):
            assert lang in lang_desc, f"{lang!r} not found in language description: {lang_desc!r}"

    def test_code_search_language_description_matches_catalog(self):
        """The language schema description exposes the sorted catalog exactly once."""
        from mempalace_code.language_catalog import sorted_searchable_languages
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 102, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        lang_desc = tools["mempalace_code_search"]["inputSchema"]["properties"]["language"][
            "description"
        ]
        prefix = "Supported languages: "
        assert lang_desc.startswith("Filter by language. ")
        assert prefix in lang_desc

        parsed = [part.strip() for part in lang_desc.split(prefix, 1)[1].split(",")]
        assert parsed == list(sorted_searchable_languages())
        assert len(parsed) == len(set(parsed))
        assert parsed.count("kubernetes") == 1

    def test_code_search_dart_symbol_types_in_description(self):
        """The mempalace_code_search symbol_type description must mention mixin, extension_type, constructor."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 101, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        sym_desc = tools["mempalace_code_search"]["inputSchema"]["properties"]["symbol_type"][
            "description"
        ]
        for sym in ("mixin", "extension_type", "constructor"):
            assert sym in sym_desc, f"'{sym}' not found in symbol_type description: {sym_desc!r}"


class TestAggregationRegression:
    """Regression tests ensuring all wings/rooms are visible regardless of palace size."""

    def _seed_multi_wing(self, store):
        """Seed drawers across 3 wings with distinct rooms."""
        ids = []
        documents = []
        metadatas = []
        for wing in ("alpha", "beta", "gamma"):
            for room in ("frontend", "backend"):
                for i in range(2):
                    idx = f"{wing}_{room}_{i}"
                    ids.append(idx)
                    documents.append(f"Content for {wing}/{room} index {i}")
                    metadatas.append({"wing": wing, "room": room})
        store.add(ids=ids, documents=documents, metadatas=metadatas)
        return store

    def test_list_wings_all_visible(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = _ensure_store(palace_path)
        self._seed_multi_wing(store)
        from mempalace_code.mcp_server import tool_list_wings

        result = tool_list_wings()
        assert set(result["wings"].keys()) == {"alpha", "beta", "gamma"}  # type: ignore[reportAttributeAccessIssue]  # reason: MCP tool handlers return dict[str, Any]; .keys() is valid
        assert result["wings"]["alpha"] == 4  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert result["wings"]["beta"] == 4  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert result["wings"]["gamma"] == 4  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_list_rooms_filtered(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = _ensure_store(palace_path)
        # Seed two wings with different rooms
        store.add(
            ids=["w1_r1", "w1_r2", "w2_r1"],
            documents=["wing1 room1", "wing1 room2", "wing2 room1"],
            metadatas=[
                {"wing": "wing1", "room": "roomA"},
                {"wing": "wing1", "room": "roomB"},
                {"wing": "wing2", "room": "roomC"},
            ],
        )
        from mempalace_code.mcp_server import tool_list_rooms

        result = tool_list_rooms(wing="wing1")
        assert set(result["rooms"].keys()) == {"roomA", "roomB"}  # type: ignore[reportAttributeAccessIssue]  # reason: MCP tool handlers return dict[str, Any]; .keys() is valid
        assert "roomC" not in result["rooms"]

    def test_status_counts_match_total(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = _ensure_store(palace_path)
        self._seed_multi_wing(store)
        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == sum(result["wings"].values())  # type: ignore[reportAttributeAccessIssue]  # reason: MCP tool handlers return dict[str, Any]; .values() is valid

    def test_taxonomy_complete(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = _ensure_store(palace_path)
        self._seed_multi_wing(store)
        from mempalace_code.mcp_server import tool_get_taxonomy

        result = tool_get_taxonomy()
        tax = result["taxonomy"]
        assert set(tax.keys()) == {"alpha", "beta", "gamma"}  # type: ignore[reportAttributeAccessIssue]  # reason: MCP tool handlers return dict[str, Any]; .keys() is valid
        for wing in ("alpha", "beta", "gamma"):
            assert tax[wing]["frontend"] == 2  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
            assert tax[wing]["backend"] == 2  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_code_search_devops_languages_in_hint(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """New DevOps language strings must appear in the supported_languages hint (MINE-DEVOPS-INFRA)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="something", language="notareallangnnn")
        assert "supported_languages" in result
        devops_langs = (
            "terraform",
            "hcl",
            "dockerfile",
            "make",
            "gotemplate",
            "jinja2",
            "conf",
            "ini",
        )
        for lang in devops_langs:
            assert lang in result["supported_languages"], (
                f"DevOps language {lang!r} missing from supported_languages hint"
            )

    def test_code_search_prose_languages_in_hint(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """Prose/data language strings must appear in the supported_languages hint (CODE-SEARCH-LANG-PROSE)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="something", language="notareallangnnn")
        assert "supported_languages" in result
        for lang in ("markdown", "text", "csv"):
            assert lang in result["supported_languages"], (
                f"Prose/data language {lang!r} missing from supported_languages hint"
            )

    def test_code_search_markdown_language(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """code_search(language='markdown') must return results, not an error (AC-1)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        # Seed a markdown drawer so the filter returns at least one hit.
        code_seeded_collection.add(
            ids=["code_md_readme"],
            documents=["# Introduction\n\nThis is the mempalace README.\n"],
            metadatas=[
                {
                    "wing": "mempalace",
                    "room": "backend",
                    "source_file": "/project/README.md",
                    "language": "markdown",
                    "symbol_name": "",
                    "symbol_type": "",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-06T00:00:00",
                }
            ],
        )
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search(query="introduction readme", language="markdown")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) > 0, (
            "language='markdown' filter returned no results despite seeded data"
        )


# ── Degraded Palace (FIX-LANCE-CORRUPT) ──────────────────────────────────


class TestDegradedPalace:
    """AC-7: When count() > 0 but count_by_pair raises, MCP tools return error + hint."""

    def test_tool_status_count_by_pair_raises_returns_error_and_hint(
        self, monkeypatch, config, palace_path, kg
    ):
        """tool_status() must include 'error' and 'hint' when taxonomy call fails."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = _ensure_store(palace_path)
        store.add(
            ids=["degrade_1"],
            documents=["degraded palace test drawer content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        from mempalace_code import mcp_server

        # Force the singleton to open so we have an instance to patch
        live_store = mcp_server._get_store()
        assert live_store is not None

        def _broken_count_by_pair(col_a, col_b):
            raise RuntimeError("fragment missing: IO error reading data file")

        monkeypatch.setattr(live_store, "count_by_pair", _broken_count_by_pair)

        result = mcp_server.tool_status()

        assert "error" in result, f"Expected 'error' key in result, got: {result}"
        assert "hint" in result, f"Expected 'hint' key in result, got: {result}"
        assert result.get("total_drawers", 0) > 0, (  # type: ignore[reportOperatorIssue]  # reason: MCP tool handlers return dict[str, Any]; total_drawers is int at runtime
            "total_drawers should still be populated from count()"
        )
        # Silent empty wings/rooms must not appear without explanation
        assert "wings" not in result or "error" in result

    def test_tool_status_healthy_palace_has_no_error_key(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        """Healthy palace must not include 'error' in tool_status() response."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert "error" not in result
        assert result["total_drawers"] == 4


# ── Architecture Tools (MCP-ARCH-TOOLS) ──────────────────────────────────


class TestArchTools:
    """Tests for the 4 architecture-oriented MCP tools."""

    @pytest.fixture
    def dotnet_kg(self, kg):
        """KG seeded with .NET-style type relationships per MCP-ARCH-TOOLS design notes."""
        kg.add_triple("MyService", "implements", "IService")
        kg.add_triple("MyService", "inherits", "BaseService")
        kg.add_triple("SpecialService", "inherits", "MyService")
        kg.add_triple("IService", "extends", "IDisposable")
        kg.add_triple("MyApp", "depends_on", "Newtonsoft.Json@13.0.3")
        kg.add_triple("MyApp", "references_project", "Shared")
        kg.add_triple("MyApp", "targets_framework", "net8.0")
        kg.add_triple("MySolution", "contains_project", "MyApp")
        return kg

    def test_find_implementations_returns_implementors(
        self, monkeypatch, config, palace_path, dotnet_kg
    ):
        """AC-1: KG has MyService implements IService → find_implementations('IService') returns MyService."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="IService")
        assert "implementations" in result
        assert result["count"] == 1
        types = [r["type"] for r in result["implementations"]]
        assert "MyService" in types

    def test_find_implementations_empty(self, monkeypatch, config, palace_path, dotnet_kg):
        """AC-2: No implementors → returns empty list, no error."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="NoSuchInterface")
        assert result["implementations"] == []
        assert result["count"] == 0

    def test_find_implementations_multiple(self, monkeypatch, config, palace_path, kg):
        """AC-3: Multiple implementors are all returned."""
        kg.add_triple("ServiceA", "implements", "IDisposable")
        kg.add_triple("ServiceB", "implements", "IDisposable")
        kg.add_triple("ServiceC", "implements", "IDisposable")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="IDisposable")
        assert result["count"] == 3
        types = {r["type"] for r in result["implementations"]}
        assert types == {"ServiceA", "ServiceB", "ServiceC"}

    def test_find_implementations_includes_inherits_for_abc(
        self, monkeypatch, config, palace_path, kg
    ):
        """AC-1 (Python ABC): inherits edges are returned when interface has an implements-ABC triple."""
        kg.add_triple("DrawerStore", "implements", "ABC")
        kg.add_triple("LanceStore", "inherits", "DrawerStore")
        kg.add_triple("ChromaStore", "inherits", "DrawerStore")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="DrawerStore")
        types = {r["type"] for r in result["implementations"]}
        assert "LanceStore" in types
        assert "ChromaStore" in types
        assert result["count"] == 2

    def test_find_implementations_concrete_class_still_empty(
        self, monkeypatch, config, palace_path, kg
    ):
        """AC-2: inherits edge without an implements-ABC triple → not treated as implementation."""
        kg.add_triple("Child", "inherits", "BaseClass")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="BaseClass")
        assert result["implementations"] == []
        assert result["count"] == 0

    def test_find_implementations_protocol_base(self, monkeypatch, config, palace_path, kg):
        """Protocol base triggers same inherits-as-implements heuristic as ABC."""
        kg.add_triple("Runnable", "implements", "Protocol")
        kg.add_triple("TaskRunner", "inherits", "Runnable")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="Runnable")
        types = {r["type"] for r in result["implementations"]}
        assert "TaskRunner" in types
        assert result["count"] == 1

    def test_find_implementations_no_duplicates_when_both_edges(
        self, monkeypatch, config, palace_path, kg
    ):
        """Class with both implements and inherits edges to an ABC appears only once."""
        kg.add_triple("MyABC", "implements", "ABC")
        kg.add_triple("ConcreteA", "implements", "MyABC")
        kg.add_triple("ConcreteA", "inherits", "MyABC")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="MyABC")
        types = [r["type"] for r in result["implementations"]]
        assert types.count("ConcreteA") == 1
        assert result["count"] == 1

    def test_find_references_canonical_categories(
        self, monkeypatch, config, palace_path, dotnet_kg
    ):
        """AC-4: find_references('MyService') returns grouped canonical relationship categories."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_find_references

        result = tool_find_references(type_name="MyService")
        refs = result["references"]
        # Outgoing: MyService implements IService, MyService inherits BaseService
        assert "implements" in refs
        assert any(r["type"] == "IService" for r in refs["implements"])
        assert "inherits" in refs
        assert any(r["type"] == "BaseService" for r in refs["inherits"])
        # Incoming: SpecialService inherits MyService
        assert "subclasses" in refs
        assert any(r["type"] == "SpecialService" for r in refs["subclasses"])

    def test_find_references_empty_categories_omitted(
        self, monkeypatch, config, palace_path, dotnet_kg
    ):
        """AC-4: Empty relationship categories are omitted from the response."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_find_references

        result = tool_find_references(type_name="MyService")
        refs = result["references"]
        # MyService is not implemented by others (it's a class, not interface)
        assert "implementors" not in refs

    def test_find_references_depended_by(self, monkeypatch, config, palace_path, kg):
        """Incoming depends_on edges are grouped under depended_by."""
        kg.add_triple("ConsumerProject", "depends_on", "MyApp")
        kg.add_triple("MyApp", "depends_on", "Newtonsoft.Json@13.0.3")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_references

        result = tool_find_references(type_name="MyApp")
        refs = result["references"]

        assert "depended_by" in refs
        assert [r["type"] for r in refs["depended_by"]] == ["ConsumerProject"]
        assert "depends_on" in refs
        assert [r["type"] for r in refs["depends_on"]] == ["Newtonsoft.Json@13.0.3"]
        assert "referenced_by" not in refs

    def test_find_references_referenced_by(self, monkeypatch, config, palace_path, kg):
        """Incoming references_project edges are grouped under referenced_by."""
        kg.add_triple("ConsumerProject", "references_project", "MyApp")
        kg.add_triple("MyApp", "references_project", "Shared")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_references

        result = tool_find_references(type_name="MyApp")
        refs = result["references"]

        assert "referenced_by" in refs
        assert [r["type"] for r in refs["referenced_by"]] == ["ConsumerProject"]
        assert "references_project" in refs
        assert [r["type"] for r in refs["references_project"]] == ["Shared"]
        assert "depended_by" not in refs

    def test_show_project_graph_all(self, monkeypatch, config, palace_path, dotnet_kg):
        """AC-5: show_project_graph returns all project-level predicates grouped."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_show_project_graph

        result = tool_show_project_graph()
        graph = result["graph"]
        assert "depends_on" in graph
        assert "targets_framework" in graph
        assert "contains_project" in graph
        assert "references_project" in graph

    def test_show_project_graph_solution_filter(self, monkeypatch, config, palace_path, dotnet_kg):
        """AC-6: solution= filter limits graph to projects in that solution."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_show_project_graph

        result = tool_show_project_graph(solution="MySolution")
        graph = result["graph"]
        # MySolution contains MyApp → MyApp's depends_on/targets_framework appear
        depends = graph.get("depends_on", [])
        assert any(r["subject"] == "MyApp" for r in depends)
        contains = graph.get("contains_project", [])
        assert any(r["object"] == "MyApp" for r in contains)

    def test_show_project_graph_unknown_solution(self, monkeypatch, config, palace_path, dotnet_kg):
        """F-2: solution= with no matching solution returns empty graph, no error."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_show_project_graph

        result = tool_show_project_graph(solution="NoSuchSolution")
        assert result["solution"] == "NoSuchSolution"
        assert result["graph"] == {}

    def test_show_type_dependencies_ancestors_and_descendants(
        self, monkeypatch, config, palace_path, dotnet_kg
    ):
        """AC-7: type_dependencies for MyService returns ancestors and descendants."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace_code.mcp_server import tool_show_type_dependencies

        result = tool_show_type_dependencies(type_name="MyService")
        assert result["type"] == "MyService"
        ancestor_types = {a["type"] for a in result["ancestors"]}
        assert "IService" in ancestor_types
        assert "BaseService" in ancestor_types
        descendant_types = {d["type"] for d in result["descendants"]}
        assert "SpecialService" in descendant_types

    def test_show_type_dependencies_cycle_safe(self, monkeypatch, config, palace_path, kg):
        """AC-8: Circular references do not cause infinite loop."""
        kg.add_triple("TypeA", "inherits", "TypeB")
        kg.add_triple("TypeB", "inherits", "TypeA")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_show_type_dependencies

        result = tool_show_type_dependencies(type_name="TypeA")
        assert "ancestors" in result
        assert "descendants" in result
        # Starting type must not appear in its own ancestors
        ancestor_types = [a["type"] for a in result["ancestors"]]
        assert ancestor_types.count("TypeA") == 0

    def test_show_type_dependencies_max_depth(self, monkeypatch, config, palace_path, kg):
        """AC-9: max_depth=1 returns only direct parents, not transitive ones."""
        kg.add_triple("MyService", "inherits", "BaseService")
        kg.add_triple("BaseService", "inherits", "GrandBase")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_show_type_dependencies

        result = tool_show_type_dependencies(type_name="MyService", max_depth=1)
        ancestor_types = {a["type"] for a in result["ancestors"]}
        assert "BaseService" in ancestor_types
        assert "GrandBase" not in ancestor_types

    def test_arch_relationship_outputs_include_source_file_provenance(
        self, monkeypatch, config, palace_path, kg
    ):
        """AC-3: project graph and find_references entries retain source_file from KG facts."""
        kg.add_triple(
            "AppProject",
            "depends_on",
            "SharedLib",
            source_file="src/app.csproj",
        )
        kg.add_triple(
            "AppProject",
            "references_project",
            "CoreLib",
            source_file="src/app.csproj",
        )
        kg.add_triple(
            "ServiceImpl",
            "implements",
            "IService",
            source_file="src/service.cs",
        )
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_find_references, tool_show_project_graph

        # project graph: depends_on rows must carry source_file
        graph_result = tool_show_project_graph()
        dep_rows = graph_result["graph"].get("depends_on", [])
        app_dep = next((r for r in dep_rows if r["subject"] == "AppProject"), None)
        assert app_dep is not None
        assert app_dep["source_file"] == "src/app.csproj"

        # project graph: references_project rows too
        ref_rows = graph_result["graph"].get("references_project", [])
        app_ref = next((r for r in ref_rows if r["subject"] == "AppProject"), None)
        assert app_ref is not None
        assert app_ref["source_file"] == "src/app.csproj"

        # find_references: implements entries carry source_file
        refs_result = tool_find_references(type_name="ServiceImpl")
        impl_entries = refs_result["references"].get("implements", [])
        assert len(impl_entries) == 1
        assert impl_entries[0]["source_file"] == "src/service.cs"

    def test_arch_tools_in_tools_list(self):
        """AC-12: All 4 new tools appear in tools/list with name, description, and inputSchema."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
        assert resp is not None
        tool_names = {t["name"] for t in resp["result"]["tools"]}
        assert "mempalace_find_implementations" in tool_names
        assert "mempalace_find_references" in tool_names
        assert "mempalace_show_project_graph" in tool_names
        assert "mempalace_show_type_dependencies" in tool_names
        # Each must have all 3 required fields
        tool_map = {t["name"]: t for t in resp["result"]["tools"]}
        for tool_name in (
            "mempalace_find_implementations",
            "mempalace_find_references",
            "mempalace_show_project_graph",
            "mempalace_show_type_dependencies",
        ):
            t = tool_map[tool_name]
            assert t["name"]
            assert t["description"]
            assert t["inputSchema"]


# ── Explain Subsystem Tool (ARCH-RETRIEVAL) ───────────────────────────────


class TestExplainSubsystem:
    """Tests for mempalace_explain_subsystem (ARCH-RETRIEVAL)."""

    @pytest.fixture
    def code_kg(self, kg):
        """KG seeded with relationships for symbols in code_seeded_collection."""
        kg.add_triple("LanceStore", "implements", "DrawerStore")
        kg.add_triple("LanceStore", "inherits", "BaseStore")
        kg.add_triple("MockStore", "implements", "DrawerStore")
        return kg

    def test_basic_query_returns_structure(
        self, monkeypatch, config, palace_path, code_seeded_collection, code_kg
    ):
        """AC-1: Returns entry_points list with required fields."""
        _patch_mcp_server(monkeypatch, config, palace_path, code_kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="vector storage backend")
        assert "entry_points" in result
        assert "symbol_graph" in result
        assert "summary" in result
        assert result["query"] == "vector storage backend"
        assert len(result["entry_points"]) > 0
        ep = result["entry_points"][0]
        for field in (
            "text",
            "source_file",
            "symbol_name",
            "symbol_type",
            "language",
            "similarity",
        ):
            assert field in ep, f"Missing field: {field}"

    def test_kg_expansion(self, monkeypatch, config, palace_path, code_seeded_collection, code_kg):
        """AC-2: symbol_graph contains KG relationships for discovered symbols."""
        _patch_mcp_server(monkeypatch, config, palace_path, code_kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="vector storage backend LanceStore")
        assert "LanceStore" in result["symbol_graph"]
        lancestore_graph = result["symbol_graph"]["LanceStore"]
        assert "implements" in lancestore_graph
        assert "DrawerStore" in lancestore_graph["implements"]

    def test_empty_kg_valid_response(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-3: Empty KG returns valid response — entry_points populated, symbol_graph entries empty."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="vector storage backend")
        assert "entry_points" in result
        assert "symbol_graph" in result
        assert len(result["entry_points"]) > 0
        for sym, rels in result["symbol_graph"].items():
            assert rels == {}, f"Expected empty relations for {sym}, got {rels}"
        assert result["summary"]["relationships_found"] == 0

    def test_wing_filter(self, monkeypatch, config, palace_path, code_seeded_collection, kg):
        """AC-4: wing filter restricts entry_points to that wing."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="language detection storage", wing="mempalace")
        assert len(result["entry_points"]) > 0
        assert all(ep["wing"] == "mempalace" for ep in result["entry_points"])

    def test_language_filter(self, monkeypatch, config, palace_path, code_seeded_collection, kg):
        """AC-5: language filter restricts entry_points to that language."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="code function", language="python")
        assert len(result["entry_points"]) > 0
        assert all(ep["language"] == "python" for ep in result["entry_points"])

    def test_no_results_empty_response(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-6: No matching code chunks → empty response, no error."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(
            query="quantum entanglement teleportation", wing="nonexistent_wing_xyz"
        )
        assert result["entry_points"] == []
        assert result["symbol_graph"] == {}
        assert result["summary"] == {
            "symbols_found": 0,
            "relationships_found": 0,
            "entry_point_count": 0,
        }

    def test_no_palace_returns_error(self, monkeypatch, config, kg):
        """AC-7: No palace → error dict with hint."""
        config._file_config["palace_path"] = "/nonexistent/path"
        _patch_mcp_server(monkeypatch, config, "/nonexistent/path", kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="anything")
        assert "error" in result
        assert "hint" in result

    def test_in_tools_list(self):
        """AC-8: Tool appears in tools/list with correct schema."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
        assert resp is not None
        tool_map = {t["name"]: t for t in resp["result"]["tools"]}
        assert "mempalace_explain_subsystem" in tool_map
        t = tool_map["mempalace_explain_subsystem"]
        assert t["name"]
        assert t["description"]
        schema = t["inputSchema"]
        props = schema["properties"]
        assert "query" in props
        assert "wing" in props
        assert "language" in props
        assert "n_results" in props
        assert schema.get("required") == ["query"]

    def test_expired_kg_relationships_excluded(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-10: Expired KG relationships are not included in symbol_graph."""
        kg.add_triple("LanceStore", "implements", "OldStore", valid_to="2020-01-01")
        kg.add_triple("LanceStore", "implements", "DrawerStore")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="vector storage backend LanceStore")
        if "LanceStore" in result["symbol_graph"]:
            impl = result["symbol_graph"]["LanceStore"].get("implements", [])
            assert "OldStore" not in impl, "Expired relationship must not appear in symbol_graph"
            assert "DrawerStore" in impl, "Active relationship must appear in symbol_graph"

    def test_mixed_palace_code_only_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-11: Mixed palace — only code-shaped hits (non-empty symbol_name) in entry_points."""
        # Add a non-code (prose) drawer that semantically matches the same query
        code_seeded_collection.add(
            ids=["prose_storage_doc"],
            documents=[
                "The storage system documentation explains how vector storage works in detail."
            ],
            metadatas=[
                {
                    "wing": "mempalace",
                    "room": "documentation",
                    "source_file": "/docs/storage.md",
                    "language": "markdown",
                    "symbol_name": "",
                    "symbol_type": "",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-06T00:00:00",
                }
            ],
        )
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="vector storage backend", n_results=10)
        assert len(result["entry_points"]) > 0
        for ep in result["entry_points"]:
            assert ep.get("symbol_name"), (
                f"Non-code drawer leaked into entry_points: {ep.get('source_file')}"
            )

    def test_n_results_one_returns_exactly_one(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-1 (EXPLAIN-NRESULTS-CLAMP): n_results=1 returns exactly 1 entry_point."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="code", n_results=1)
        assert "error" not in result
        assert len(result["entry_points"]) == 1
        assert result["summary"]["entry_point_count"] == 1

    def test_n_results_zero_clamped_to_one(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-2 (EXPLAIN-NRESULTS-CLAMP): n_results=0 is clamped to 1, returns 1 entry_point."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="code", n_results=0)
        assert "error" not in result
        assert len(result["entry_points"]) == 1
        assert result["summary"]["entry_point_count"] == 1

    def test_n_results_negative_clamped_to_one(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-3 (EXPLAIN-NRESULTS-CLAMP): n_results=-1 is clamped to 1, not sliced negatively."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="code", n_results=-1)
        assert "error" not in result
        assert len(result["entry_points"]) == 1
        assert result["summary"]["entry_point_count"] == 1

    def test_invalid_language_with_zero_n_results_propagates_error(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """AC-4 (EXPLAIN-NRESULTS-CLAMP): unsupported language error propagates even when n_results also needs clamping."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_explain_subsystem

        result = tool_explain_subsystem(query="code", language="not-a-language", n_results=0)
        assert "error" in result
        assert "supported_languages" in result


# ── Extract Reusable Tool (LOGIC-EXTRACTION) ─────────────────────────────


class TestExtractReusable:
    """Tests for mempalace_extract_reusable (LOGIC-EXTRACTION)."""

    @pytest.fixture
    def extraction_kg(self, kg):
        """KG seeded with mixed core/platform/glue entities per LOGIC-EXTRACTION plan fixture."""
        # Pure core: interface + its extension
        kg.add_triple("IService", "extends", "IDisposable")
        # Pure core implementation
        kg.add_triple("CoreService", "implements", "IService")
        # Platform: WpfView depends on a WPF package and uses XAML bindings
        kg.add_triple("WpfView", "depends_on", "Microsoft.WindowsDesktop.App.WPF@8.0")
        kg.add_triple("WpfView", "binds_viewmodel", "MainViewModel")
        # Glue: implements core interface + depends on platform package
        kg.add_triple("WinFormsAdapter", "implements", "IService")
        kg.add_triple("WinFormsAdapter", "depends_on", "System.Windows.Forms@8.0")
        # Project-level
        kg.add_triple("MyApp", "references_project", "CoreLib")
        kg.add_triple("MyApp", "targets_framework", "net8.0-windows")
        kg.add_triple("MySolution", "contains_project", "MyApp")
        kg.add_triple("MySolution", "contains_project", "CoreLib")
        kg.add_triple("CoreLib", "targets_framework", "netstandard2.0")
        return kg

    def test_pure_core_graph_classifies_all_core(self, monkeypatch, config, palace_path, kg):
        """AC-1: Pure core graph — all reachable entities classified as core."""
        kg.add_triple("MyService", "implements", "IService")
        kg.add_triple("MyService", "inherits", "BaseService")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="MyService")
        assert result["entity"] == "MyService"
        # IService and BaseService discovered; both should be core
        core_entities = {e["entity"] for e in result["graph"]["core"]}
        assert "IService" in core_entities
        assert "BaseService" in core_entities
        assert result["graph"]["platform"] == []
        assert result["graph"]["glue"] == []

    def test_platform_entity_classified_with_evidence(
        self, monkeypatch, config, palace_path, extraction_kg
    ):
        """AC-2: WpfView depends_on WPF package and uses binds_viewmodel → classified platform."""
        _patch_mcp_server(monkeypatch, config, palace_path, extraction_kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="WpfView")
        platform = result["graph"]["platform"]
        # Microsoft.WindowsDesktop.App.WPF@8.0 should appear as a platform leaf
        platform_names = {e["entity"] for e in platform}
        assert "Microsoft.WindowsDesktop.App.WPF@8.0" in platform_names
        # Evidence must be non-empty for each platform entity
        for p in platform:
            assert p["evidence"], f"Platform entity {p['entity']} has no evidence"

    def test_glue_detection_at_interface_boundary(
        self, monkeypatch, config, palace_path, extraction_kg
    ):
        """AC-3: WinFormsAdapter implements IService (core) + depends_on System.Windows.Forms → glue.
        boundary_interfaces must include IService with WinFormsAdapter as implementor."""
        _patch_mcp_server(monkeypatch, config, palace_path, extraction_kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="WinFormsAdapter")
        # WinFormsAdapter is the root — verify via boundary_interfaces
        assert len(result["boundary_interfaces"]) >= 1
        bi_ifaces = {b["interface"] for b in result["boundary_interfaces"]}
        assert "IService" in bi_ifaces
        # WinFormsAdapter must appear as an implementor
        for bi in result["boundary_interfaces"]:
            if bi["interface"] == "IService":
                implementors = {imp["entity"] for imp in bi["implemented_by"]}
                assert "WinFormsAdapter" in implementors

    def test_references_project_to_platform_project_promotes_glue(
        self, monkeypatch, config, palace_path, kg
    ):
        """Project references to platform-classified projects promote implementors to glue."""
        kg.add_triple("WpfAdapter", "implements", "IService")
        kg.add_triple("WpfAdapter", "references_project", "WpfHost")
        kg.add_triple("WpfHost", "targets_framework", "net8.0-windows")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        root_result = tool_extract_reusable(entity="WpfAdapter")
        boundary_by_interface = {
            item["interface"]: item["implemented_by"] for item in root_result["boundary_interfaces"]
        }
        assert boundary_by_interface == {
            "IService": [{"entity": "WpfAdapter", "classification": "glue"}]
        }

        kg.add_triple("Container", "references_project", "WpfAdapter")
        container_result = tool_extract_reusable(entity="Container")
        glue_by_entity = {item["entity"]: item for item in container_result["graph"]["glue"]}
        assert glue_by_entity["WpfAdapter"]["core_interfaces"] == ["IService"]
        assert glue_by_entity["WpfAdapter"]["platform_deps"] == ["WpfHost"]

    def test_references_project_to_core_project_does_not_promote_glue(
        self, monkeypatch, config, palace_path, kg
    ):
        """Non-platform project references do not create glue boundaries by themselves."""
        kg.add_triple("CoreAdapter", "implements", "IService")
        kg.add_triple("CoreAdapter", "references_project", "CoreLib")
        kg.add_triple("CoreLib", "targets_framework", "netstandard2.0")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="CoreAdapter")
        assert result["boundary_interfaces"] == []
        assert result["graph"]["glue"] == []
        assert {item["entity"] for item in result["graph"]["core"]} == {"IService", "CoreLib"}

    def test_expired_references_project_to_platform_project_is_ignored(
        self, monkeypatch, config, palace_path, kg
    ):
        """Expired project references are not traversed and cannot promote glue."""
        kg.add_triple("ExpiredAdapter", "implements", "IService")
        kg.add_triple(
            "ExpiredAdapter",
            "references_project",
            "WpfHost",
            valid_to="2020-01-01",
        )
        kg.add_triple("WpfHost", "targets_framework", "net8.0-windows")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="ExpiredAdapter")
        assert result["boundary_interfaces"] == []
        assert result["graph"]["glue"] == []
        all_entities = {item["entity"] for values in result["graph"].values() for item in values}
        assert all_entities == {"IService"}
        assert "WpfHost" not in all_entities

    def test_empty_kg_returns_empty_graph(self, monkeypatch, config, palace_path, kg):
        """AC-4: Entity has no KG facts → valid empty response, no error."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="UnknownEntity")
        assert result["entity"] == "UnknownEntity"
        assert result["graph"]["core"] == []
        assert result["graph"]["platform"] == []
        assert result["graph"]["glue"] == []
        assert result["boundary_interfaces"] == []
        summary = result["summary"]
        assert summary["total_entities"] == 0
        assert summary["core_count"] == 0
        assert summary["platform_count"] == 0
        assert summary["glue_count"] == 0
        assert summary["boundary_interface_count"] == 0

    def test_cycle_safe_traversal(self, monkeypatch, config, palace_path, kg):
        """AC-5: Circular KG references terminate without infinite loop; each entity appears once."""
        kg.add_triple("TypeA", "depends_on", "TypeB")
        kg.add_triple("TypeB", "depends_on", "TypeA")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="TypeA")
        all_entities = (
            [e["entity"] for e in result["graph"]["core"]]
            + [e["entity"] for e in result["graph"]["platform"]]
            + [e["entity"] for e in result["graph"]["glue"]]
        )
        # TypeB should appear exactly once; TypeA (root) should not appear in graph
        assert all_entities.count("TypeB") == 1
        assert "TypeA" not in all_entities

    def test_max_depth_caps_expansion(self, monkeypatch, config, palace_path, kg):
        """AC-6: max_depth=1 returns only direct deps; depth-2+ nodes are omitted."""
        kg.add_triple("Root", "implements", "InterfaceA")
        kg.add_triple("InterfaceA", "extends", "InterfaceB")
        kg.add_triple("InterfaceB", "extends", "InterfaceC")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="Root", max_depth=1)
        all_entities = {e["entity"] for lst in result["graph"].values() for e in lst}
        assert "InterfaceA" in all_entities
        assert "InterfaceB" not in all_entities
        assert "InterfaceC" not in all_entities

    def test_expired_facts_excluded_from_traversal(self, monkeypatch, config, palace_path, kg):
        """AC-7: Expired KG relationships are not traversed or classified."""
        kg.add_triple("MyType", "implements", "OldInterface", valid_to="2020-01-01")
        kg.add_triple("MyType", "implements", "IService")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="MyType")
        all_entities = {e["entity"] for lst in result["graph"].values() for e in lst}
        assert "OldInterface" not in all_entities, "Expired relationship must not be traversed"
        assert "IService" in all_entities, "Active relationship must be traversed"

    def test_tool_appears_in_tools_list(self):
        """AC-8: mempalace_extract_reusable appears in tools/list with correct schema."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
        assert resp is not None
        tool_map = {t["name"]: t for t in resp["result"]["tools"]}
        assert "mempalace_extract_reusable" in tool_map
        t = tool_map["mempalace_extract_reusable"]
        assert t["name"]
        assert t["description"]
        schema = t["inputSchema"]
        props = schema["properties"]
        assert "entity" in props
        assert "max_depth" in props
        assert schema.get("required") == ["entity"]

    def test_package_leaf_nodes_classified_platform(self, monkeypatch, config, palace_path, kg):
        """AC-2 / package-leaf: Package entities matching PLATFORM_PACKAGE_PREFIXES are platform."""
        kg.add_triple("MyProject", "depends_on", "System.Windows.Forms@8.0")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="MyProject")
        platform_names = {e["entity"] for e in result["graph"]["platform"]}
        assert "System.Windows.Forms@8.0" in platform_names
        # MyProject itself is platform because of its platform dep
        # (root excluded from graph but the dep node itself should be platform)

    def test_solution_level_expands_through_contains_project(
        self, monkeypatch, config, palace_path, extraction_kg
    ):
        """AC-10: Solution-level query expands through contains_project to project deps."""
        _patch_mcp_server(monkeypatch, config, palace_path, extraction_kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="MySolution")
        all_entities = {e["entity"] for lst in result["graph"].values() for e in lst}
        # MySolution contains MyApp and CoreLib
        assert "MyApp" in all_entities or "CoreLib" in all_entities

    def test_boundary_interfaces_only_implements_not_inherits(
        self, monkeypatch, config, palace_path, kg
    ):
        """Plan spec: only `implements` (interface contracts) qualify for boundary_interfaces; not `inherits`."""
        kg.add_triple("GlueType", "implements", "IContract")
        kg.add_triple("GlueType", "inherits", "BasePlatformClass")
        kg.add_triple("GlueType", "depends_on", "System.Windows.Forms@8.0")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="GlueType")
        bi_ifaces = {b["interface"] for b in result["boundary_interfaces"]}
        # IContract (via implements) should appear as boundary interface
        assert "IContract" in bi_ifaces
        # BasePlatformClass (via inherits) must NOT appear
        assert "BasePlatformClass" not in bi_ifaces

    def test_summary_counts_match_graph_lists(
        self, monkeypatch, config, palace_path, extraction_kg
    ):
        """Summary counts must equal len() of corresponding graph lists."""
        _patch_mcp_server(monkeypatch, config, palace_path, extraction_kg)
        from mempalace_code.mcp_server import tool_extract_reusable

        result = tool_extract_reusable(entity="MySolution")
        summary = result["summary"]
        assert summary["core_count"] == len(result["graph"]["core"])
        assert summary["platform_count"] == len(result["graph"]["platform"])
        assert summary["glue_count"] == len(result["graph"]["glue"])
        assert summary["boundary_interface_count"] == len(result["boundary_interfaces"])
        assert summary["total_entities"] == (
            summary["core_count"] + summary["platform_count"] + summary["glue_count"]
        )


# ── File Context Tool ──────────────────────────────────────────────────────


def _seed_file_context(collection, source_file, wing, room="backend"):
    """Seed 3 chunks for a file, inserted in reverse chunk_index order."""
    collection.add(
        ids=[
            f"fc_{wing}_chunk2",
            f"fc_{wing}_chunk0",
            f"fc_{wing}_chunk1",
        ],
        documents=[
            "def third_function(): pass",
            "def first_function(): pass",
            "def second_function(): pass",
        ],
        metadatas=[
            {
                "wing": wing,
                "room": room,
                "source_file": source_file,
                "symbol_name": "third_function",
                "symbol_type": "function",
                "language": "python",
                "chunk_index": 2,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
            },
            {
                "wing": wing,
                "room": room,
                "source_file": source_file,
                "symbol_name": "first_function",
                "symbol_type": "function",
                "language": "python",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
            },
            {
                "wing": wing,
                "room": room,
                "source_file": source_file,
                "symbol_name": "second_function",
                "symbol_type": "function",
                "language": "python",
                "chunk_index": 1,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
            },
        ],
    )


class TestFileContextTool:
    def test_happy_path_returns_all_chunks_with_fields(
        self, monkeypatch, config, palace_path, collection, kg
    ):
        """AC-1: 3 chunks for a file → {total: 3, chunks: [...]} with all required fields."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _seed_file_context(collection, source_file="mempalace/storage.py", wing="myproject")
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context(source_file="mempalace/storage.py")

        assert result["total"] == 3
        assert result["source_file"] == "mempalace/storage.py"
        assert result["wing"] is None
        assert len(result["chunks"]) == 3
        chunk = result["chunks"][0]
        for field in (
            "chunk_index",
            "content",
            "symbol_name",
            "symbol_type",
            "wing",
            "room",
            "language",
            "line_range",
        ):
            assert field in chunk, f"Missing field: {field}"
        assert chunk["line_range"] is None  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_missing_file_returns_empty(self, monkeypatch, config, palace_path, collection, kg):
        """AC-2: source_file not in palace → {total: 0, chunks: []} with no error key."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context(source_file="nonexistent/file.py")

        assert "error" not in result
        assert result["total"] == 0
        assert result["chunks"] == []

    def test_wing_filter_isolates_wing(self, monkeypatch, config, palace_path, collection, kg):
        """AC-3: file in two wings + wing filter → only the specified wing's chunks."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _seed_file_context(collection, source_file="shared/utils.py", wing="wing_a")
        # Add one chunk in wing_b for the same file
        collection.add(
            ids=["fc_wing_b_chunk0"],
            documents=["def util_b(): pass"],
            metadatas=[
                {
                    "wing": "wing_b",
                    "room": "backend",
                    "source_file": "shared/utils.py",
                    "symbol_name": "util_b",
                    "symbol_type": "function",
                    "language": "python",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context(source_file="shared/utils.py", wing="wing_a")

        assert result["total"] == 3
        assert result["wing"] == "wing_a"
        assert all(c["wing"] == "wing_a" for c in result["chunks"])  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_chunks_sorted_by_chunk_index(self, monkeypatch, config, palace_path, collection, kg):
        """AC-4: chunks inserted in reverse order → response sorted ascending by chunk_index.

        Also verifies content-index alignment: each chunk's symbol_name must match its
        chunk_index, not just that the indices themselves are in order.
        """
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _seed_file_context(collection, source_file="mempalace/miner.py", wing="mempalace")
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context(source_file="mempalace/miner.py")

        indices = [c["chunk_index"] for c in result["chunks"]]  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert indices == sorted(indices), f"chunks not sorted: {indices}"
        assert indices == [0, 1, 2]
        # Verify content is aligned with index (not just indices sorted in isolation)
        assert result["chunks"][0]["symbol_name"] == "first_function"  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert result["chunks"][1]["symbol_name"] == "second_function"  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct
        assert result["chunks"][2]["symbol_name"] == "third_function"  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_no_palace_returns_error(self, monkeypatch, kg):
        """AC-5: no palace (_get_store returns None) → standard error dict with 'error' and 'hint'."""
        from mempalace_code.mcp import runtime

        monkeypatch.setattr(runtime, "_kg", kg)
        monkeypatch.setattr(runtime, "_store", None)
        # Simulate _get_store() returning None (palace open failed)
        monkeypatch.setattr(runtime, "_get_store", lambda create=False: None)

        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context(source_file="anything.py")

        assert "error" in result
        assert "hint" in result

    def test_tools_list_includes_file_context(self):
        """AC-6: tools/list response includes mempalace_file_context with source_file required."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}

        assert "mempalace_file_context" in tools
        schema = tools["mempalace_file_context"]["inputSchema"]
        assert "source_file" in schema["properties"]
        assert "source_file" in schema.get("required", [])

    def test_source_file_with_apostrophe_does_not_raise(
        self, monkeypatch, config, palace_path, collection, kg
    ):
        """F-1: source_file containing a single quote is SQL-escaped by _where_to_sql; no error."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        # Seed a chunk with an apostrophe in its path
        collection.add(
            ids=["fc_quote_chunk0"],
            documents=["def tricky(): pass"],
            metadatas=[
                {
                    "wing": "myproject",
                    "room": "backend",
                    "source_file": "O'Brien/module.py",
                    "symbol_name": "tricky",
                    "symbol_type": "function",
                    "language": "python",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        from mempalace_code.mcp_server import tool_file_context

        # Must not raise; must find the chunk (not return error or empty)
        result = tool_file_context(source_file="O'Brien/module.py")

        assert "error" not in result
        assert result["total"] == 1
        assert result["chunks"][0]["symbol_name"] == "tricky"  # type: ignore[reportArgumentType]  # reason: MCP tool handlers return dict[str, Any]; string key subscript is correct

    def test_empty_source_file_returns_error(
        self, monkeypatch, config, palace_path, collection, kg
    ):
        """F-2: source_file='' must return an error, not scan all un-sourced rows."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context(source_file="")

        assert "error" in result

    def test_storage_exception_returns_error_and_hint(self, monkeypatch, kg):
        """F-1: col.get() raising an exception → {"error": ..., "hint": ...} (not just error)."""
        from mempalace_code.mcp import runtime

        class _FailingStore:
            def get(self, *args, **kwargs):
                raise RuntimeError("simulated storage failure")

        monkeypatch.setattr(runtime, "_kg", kg)
        monkeypatch.setattr(runtime, "_get_store", lambda create=False: _FailingStore())

        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context(source_file="any/file.py")

        assert "error" in result
        assert "hint" in result

    def test_tool_call_dispatch(self, monkeypatch, config, palace_path, collection, kg):
        """F-4: tools/call dispatch for mempalace_file_context returns structured result.

        Exercises the handle_request → TOOLS lookup → handler path end-to-end,
        catching any wiring bug in the TOOLS registry.
        """
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _seed_file_context(collection, source_file="dispatch/test.py", wing="myproject")
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 10,
                "params": {
                    "name": "mempalace_file_context",
                    "arguments": {"source_file": "dispatch/test.py"},
                },
            }
        )

        assert resp is not None
        assert resp["id"] == 10
        assert "error" not in resp
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["total"] == 3
        assert data["source_file"] == "dispatch/test.py"


# ── Mine Tool (MCP-MINE-TRIGGER) ──────────────────────────────────────────


def _make_mine_project(tmp_path, wing="test_mine_wing"):
    """Create a minimal project directory with mempalace.yaml and one Python file."""
    import yaml as _yaml

    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / "mempalace.yaml").write_text(
        _yaml.dump(
            {
                "wing": wing,
                "rooms": [
                    {"name": "backend", "description": "Backend code"},
                    {"name": "general", "description": "General"},
                ],
            }
        ),
        encoding="utf-8",
    )
    # Write a Python file with enough content to exceed MIN_CHUNK (100 chars)
    # so that the miner produces at least one drawer.
    (project_dir / "utils.py").write_text(
        "def compute_result(value: int) -> int:\n"
        '    """Compute a result by squaring the input value."""\n'
        "    return value * value\n\n\n"
        "def transform_list(items: list) -> list:\n"
        '    """Apply compute_result to every element of a list."""\n'
        "    return [compute_result(x) for x in items]\n",
        encoding="utf-8",
    )
    return str(project_dir)


class TestToolMine:
    """Tests for tool_mine / mempalace_mine (MCP-MINE-TRIGGER)."""

    def test_successful_incremental_mine(self, monkeypatch, config, palace_path, kg, tmp_path):
        """AC-1: mine a valid project directory, returns success with expected fields."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        project_dir = _make_mine_project(tmp_path)
        from mempalace_code.mcp_server import tool_mine

        result = tool_mine(directory=project_dir)

        assert result["success"] is True, f"Expected success, got: {result}"
        for field in ("files_processed", "files_skipped", "drawers_filed", "elapsed_secs"):
            assert field in result, f"Missing field: {field}"
        assert result["files_processed"] >= 1
        assert result["drawers_filed"] >= 1

    def test_full_mine_files_skipped_is_zero(self, monkeypatch, config, palace_path, kg, tmp_path):
        """AC-2: full=True forces re-processing all files (files_skipped == 0)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        project_dir = _make_mine_project(tmp_path)
        from mempalace_code.mcp_server import tool_mine

        # Mine once to populate hashes
        r1 = tool_mine(directory=project_dir)
        assert r1["success"] is True

        # Mine again incrementally — some files should be skipped
        r2 = tool_mine(directory=project_dir, full=False)
        assert r2["success"] is True
        assert r2["files_skipped"] >= 1, "Incremental re-mine should skip unchanged files"

        # Full rebuild — nothing skipped
        r3 = tool_mine(directory=project_dir, full=True)
        assert r3["success"] is True
        assert r3["files_skipped"] == 0, f"full=True must have files_skipped==0, got {r3}"

    def test_nonexistent_directory(self, monkeypatch, config, palace_path, kg):
        """AC-3: non-existent directory → {success: false, error: ...} without exception."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace_code.mcp_server import tool_mine

        result = tool_mine(directory="/tmp/absolutely_does_not_exist_xyz123abc")

        assert result["success"] is False
        assert "error" in result

    def test_path_is_file_not_directory(self, monkeypatch, config, palace_path, kg, tmp_path):
        """AC-3b: path exists but is a file → {success: false, error: ...}."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        a_file = tmp_path / "somefile.txt"
        a_file.write_text("content")
        from mempalace_code.mcp_server import tool_mine

        result = tool_mine(directory=str(a_file))

        assert result["success"] is False
        assert "error" in result

    def test_directory_missing_mempalace_yaml(self, monkeypatch, config, palace_path, kg, tmp_path):
        """AC-3c: valid directory but no mempalace.yaml → graceful {success: false, error: ...}."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        bare_dir = tmp_path / "bare"
        bare_dir.mkdir()
        (bare_dir / "some_code.py").write_text("x = 1\n")
        from mempalace_code.mcp_server import tool_mine

        result = tool_mine(directory=str(bare_dir))

        assert result["success"] is False
        assert "error" in result
        # Must not have raised SystemExit or Exception propagated to caller

    def test_wing_override_drawers_filed_under_custom_wing(
        self, monkeypatch, config, palace_path, kg, tmp_path
    ):
        """AC-4: wing='custom_wing' → mined drawers filed under custom_wing in the store."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        project_dir = _make_mine_project(tmp_path, wing="default_wing")
        from mempalace_code.mcp_server import tool_mine
        from mempalace_code.storage import open_store

        result = tool_mine(directory=project_dir, wing="custom_wing")

        assert result["success"] is True
        store = open_store(palace_path, create=False)
        drawers_in_custom = store.get(
            where={"wing": "custom_wing"},
            include=["metadatas"],
            limit=1000,
        )
        assert len(drawers_in_custom["ids"]) >= 1, "Expected drawers filed under 'custom_wing'"
        # Verify no drawers were filed under the default wing
        drawers_in_default = store.get(
            where={"wing": "default_wing"},
            include=["metadatas"],
            limit=1000,
        )
        assert len(drawers_in_default["ids"]) == 0, (
            "No drawers should be filed under the config-default wing when wing is overridden"
        )

    def test_mine_appears_in_tools_list(self):
        """AC-5: mempalace_mine appears in tools/list with correct input schema."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}

        assert "mempalace_mine" in tools
        t = tools["mempalace_mine"]
        assert t["description"]
        schema = t["inputSchema"]
        assert "directory" in schema["properties"]
        assert schema.get("required") == ["directory"]
        assert schema["properties"].get("full", {}).get("type") == "boolean"

    def test_mine_via_protocol_dispatch(self, monkeypatch, config, palace_path, kg, tmp_path):
        """Protocol-level: tools/call dispatch for mempalace_mine returns success result."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        project_dir = _make_mine_project(tmp_path)
        from mempalace_code.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 42,
                "params": {
                    "name": "mempalace_mine",
                    "arguments": {"directory": project_dir},
                },
            }
        )

        assert resp is not None
        assert resp["id"] == 42
        assert "error" not in resp, f"Unexpected error: {resp.get('error')}"
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is True
        assert "drawers_filed" in data


# ── Lazy Startup (MCP-LAZY-STARTUP) ──────────────────────────────────────


class TestLazyStartup:
    """AC-1 through AC-6 for lazy MCP startup."""

    def test_ac1_initialize_and_tools_list_without_torch_or_miner(self, tmp_path):
        """AC-1: initialize + tools/list succeed in a subprocess that blocks torch/miner imports.

        Uses the modern importlib find_spec API (find_module/load_module are silently
        ignored in Python 3.12+, so the legacy form would falsely pass). Also asserts
        post-call sys.modules to detect any import that slipped through.
        """
        import subprocess
        import sys

        script = """
import sys

# Block imports that must NOT be triggered by initialize/tools-list.
# Uses find_spec (PEP 451) — find_module is deprecated and ignored in 3.12+.
class _Blocker:
    _BLOCKED = frozenset({
        "torch",
        "sentence_transformers",
        "mempalace_code.miner",
    })
    def find_spec(self, name, path=None, target=None):
        if name in self._BLOCKED:
            raise ImportError("Blocked by test: " + name)
        return None

sys.meta_path.insert(0, _Blocker())

# HOME isolation so KG init writes to a throwaway dir
import tempfile, os
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

from mempalace_code.mcp_server import handle_request

resp1 = handle_request({"method": "initialize", "id": 1, "params": {}})
assert resp1["result"]["serverInfo"]["name"] == "mempalace-code", resp1
resp2 = handle_request({"method": "tools/list", "id": 2, "params": {}})
tool_names = {t["name"] for t in resp2["result"]["tools"]}
assert "mempalace_mine" in tool_names, tool_names

# Defense in depth: even if the blocker were a no-op, these would catch a
# regression that re-introduces eager imports.
for mod in ("torch", "sentence_transformers", "mempalace_code.miner"):
    assert mod not in sys.modules, mod + " was imported during init/tools-list"

print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout, f"unexpected output: {result.stdout}"

    def test_ac2_metadata_reads_skip_embedder(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        """AC-2: status/list_wings/get_taxonomy work even when _get_embedder raises."""
        from mempalace_code.storage import LanceStore

        _patch_mcp_server(monkeypatch, config, palace_path, kg)

        # Override the deterministic-test-embedder patch with one that raises,
        # AFTER the seeded palace already exists on disk.
        def _embedder_raises(self):
            raise RuntimeError("embedder must not be called for read-only metadata ops")

        monkeypatch.setattr(LanceStore, "_get_embedder", _embedder_raises)

        from mempalace_code.mcp_server import tool_get_taxonomy, tool_list_wings, tool_status

        status = tool_status()
        assert "error" not in status, f"tool_status raised embedder: {status}"
        assert status["total_drawers"] == 4

        wings = tool_list_wings()
        assert "error" not in wings
        assert "project" in wings["wings"]

        taxonomy = tool_get_taxonomy()
        assert "error" not in taxonomy
        assert "project" in taxonomy["taxonomy"]

    def test_ac3_read_then_write_cache_upgrade(self, monkeypatch, config, palace_path, kg):
        """AC-3: status (read) caches store, add_drawer (write) succeeds, status shows new count."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)

        from mempalace_code.mcp_server import tool_add_drawer, tool_status

        # Step 1: read — caches a read-only store
        status1 = tool_status()
        assert status1["total_drawers"] == 0

        # Step 2: write — must succeed despite read-only cache
        add_result = tool_add_drawer(
            wing="lazy_test",
            room="general",
            content="Content written after status caches read-only store.",
        )
        assert add_result["success"] is True, f"add_drawer failed: {add_result}"

        # Step 3: read again — must reflect the new drawer
        status2 = tool_status()
        assert status2["total_drawers"] == 1

    def test_ac4_status_missing_palace_no_directory_created(self, monkeypatch, tmp_path, kg):
        """AC-4: status with a missing palace_path returns error and does not create the directory."""
        from mempalace_code.config import MempalaceConfig

        missing = tmp_path / "never_created"
        assert not missing.exists()

        # Build a config pointing at the missing path
        cfg_dir = str(tmp_path / "cfg")
        import os

        os.makedirs(cfg_dir)
        import json

        with open(os.path.join(cfg_dir, "config.json"), "w") as f:
            json.dump({"palace_path": str(missing)}, f)
        cfg = MempalaceConfig(config_dir=cfg_dir)

        from mempalace_code.mcp import runtime

        monkeypatch.setattr(runtime, "_config", cfg)
        monkeypatch.setattr(runtime, "_store", None)

        from mempalace_code.mcp_server import tool_status

        result = tool_status()
        assert "error" in result, f"Expected error for missing palace, got: {result}"
        assert not missing.exists(), "Missing palace directory must not be created by read tools"

    def test_ac5_mine_invalid_dir_no_miner_import(self, monkeypatch, config, palace_path, kg):
        """AC-5: tool_mine with non-existent dir validates path before importing miner.

        Verifies the early-return guards in tool_mine fire before _mine_quiet runs the
        lazy `from .miner import mine`. Uses subprocess + find_spec because (a) other
        tests in this run may have already imported mempalace_code.miner, polluting
        sys.modules, and (b) find_module is a no-op in Python 3.12+.
        """
        import subprocess
        import sys

        script = """
import sys

class _MinerBlocker:
    _BLOCKED = frozenset({"mempalace_code.miner", "torch"})
    def find_spec(self, name, path=None, target=None):
        if name in self._BLOCKED:
            raise ImportError("Blocked by test: " + name)
        return None

sys.meta_path.insert(0, _MinerBlocker())

import tempfile, os
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

from mempalace_code.mcp_server import tool_mine

result = tool_mine(directory="/nonexistent/path/that/does/not/exist")
assert result["success"] is False, "Expected failure for non-existent dir: " + repr(result)
assert "error" in result
assert "Directory not found" in result["error"], result["error"]

for mod in ("mempalace_code.miner", "torch"):
    assert mod not in sys.modules, mod + " was imported during invalid-dir tool_mine"

print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout, f"unexpected output: {result.stdout}"


# ── MCP Tool Profiles — Dispatch Tests (MCP-TOOL-PROFILES) ───────────────────


class TestMCPToolProfiles:
    """JSON-RPC dispatch tests for startup-time tool profile filtering.

    These tests pass active_registry directly to handle_request so they do not
    depend on the module-level _active_registry set by main().
    """

    def _build_registry(self, profile=None, tools=None, include=None, exclude=None):
        from mempalace_code.mcp_server import TOOLS
        from mempalace_code.mcp_tool_profiles import resolve_active_tools

        all_names = frozenset(TOOLS)
        active = resolve_active_tools(
            all_names,
            profile=profile or "full",
            tools=tools,
            include=include,
            exclude=exclude,
        )
        return {k: v for k, v in TOOLS.items() if k in active}

    # AC-1: default (no flags) exposes all 28 tools via handle_request with no registry override.
    def test_ac1_default_full_toolset(self):
        from mempalace_code.mcp_server import TOOLS, handle_request

        resp = handle_request({"method": "tools/list", "id": 1, "params": {}})
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == frozenset(TOOLS)

    # AC-2: --profile=minimal exposes exactly the 4 minimal tools.
    def test_ac2_minimal_profile_tools_list(self):
        from mempalace_code.mcp_server import handle_request

        registry = self._build_registry(profile="minimal")
        resp = handle_request(
            {"method": "tools/list", "id": 2, "params": {}}, active_registry=registry
        )
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == frozenset(
            {
                "mempalace_status",
                "mempalace_search",
                "mempalace_check_duplicate",
                "mempalace_add_drawer",
            }
        )

    # AC-3: --profile=code exposes code tools and omits write/diary tools.
    def test_ac3_code_profile_includes_code_tools(self):
        from mempalace_code.mcp_server import handle_request

        registry = self._build_registry(profile="code")
        resp = handle_request(
            {"method": "tools/list", "id": 3, "params": {}}, active_registry=registry
        )
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "mempalace_code_search" in names
        assert "mempalace_file_context" in names
        assert "mempalace_explain_subsystem" in names
        assert "mempalace_extract_reusable" in names

    def test_ac3_code_profile_omits_write_and_diary(self):
        from mempalace_code.mcp_server import handle_request

        registry = self._build_registry(profile="code")
        resp = handle_request(
            {"method": "tools/list", "id": 4, "params": {}}, active_registry=registry
        )
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "mempalace_add_drawer" not in names
        assert "mempalace_diary_write" not in names

    # AC-4: minimal + include=kg_query, exclude=search.
    def test_ac4_include_exclude_precedence(self):
        from mempalace_code.mcp_server import handle_request

        registry = self._build_registry(profile="minimal", include=["kg_query"], exclude=["search"])
        resp = handle_request(
            {"method": "tools/list", "id": 5, "params": {}}, active_registry=registry
        )
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "mempalace_kg_query" in names
        assert "mempalace_search" not in names

    # AC-5: --tools=search,add_drawer,diary_* exposes exactly those 4 tools.
    def test_ac5_tools_with_wildcard(self):
        from mempalace_code.mcp_server import handle_request

        registry = self._build_registry(tools=["search", "add_drawer", "diary_*"])
        resp = handle_request(
            {"method": "tools/list", "id": 6, "params": {}}, active_registry=registry
        )
        assert resp is not None
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == frozenset(
            {
                "mempalace_search",
                "mempalace_add_drawer",
                "mempalace_diary_write",
                "mempalace_diary_read",
            }
        )

    # AC-6: calling a hidden tool returns -32601 with the "not enabled by the active MCP profile" message.
    def test_ac6_hidden_tool_call_returns_profile_error(self):
        from mempalace_code.mcp_server import handle_request

        registry = self._build_registry(profile="minimal")
        resp = handle_request(
            {
                "method": "tools/call",
                "id": 7,
                "params": {"name": "mempalace_delete_wing", "arguments": {"wing": "test"}},
            },
            active_registry=registry,
        )
        assert resp is not None
        assert resp["error"]["code"] == -32601
        assert "not enabled by the active MCP profile" in resp["error"]["message"]

    def test_hidden_tool_is_distinct_from_unknown_tool(self):
        from mempalace_code.mcp_server import handle_request

        registry = self._build_registry(profile="minimal")
        resp = handle_request(
            {
                "method": "tools/call",
                "id": 8,
                "params": {"name": "totally_nonexistent_tool", "arguments": {}},
            },
            active_registry=registry,
        )
        assert resp is not None
        assert resp["error"]["code"] == -32601
        assert "Unknown tool" in resp["error"]["message"]
        assert "not enabled" not in resp["error"]["message"]

    # AC-7 (startup validation) — tested via main() with sys.exit.
    def test_ac7_invalid_profile_exits_before_loop(self):
        import subprocess
        import sys

        script = """
import sys
import tempfile, os
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

from mempalace_code.mcp_server import main
try:
    main(["--profile", "not_a_real_profile"])
except SystemExit as e:
    print("EXIT:" + str(e.code))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "EXIT:1" in result.stdout, f"Expected SystemExit(1), got: {result.stdout!r}"
        assert "Invalid MCP tool profile" in result.stderr, f"stderr: {result.stderr!r}"

    def test_ac7_unknown_tool_selector_exits(self):
        import subprocess
        import sys

        script = """
import sys, tempfile, os
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

from mempalace_code.mcp_server import main
try:
    main(["--tools", "definitely_not_a_tool"])
except SystemExit as e:
    print("EXIT:" + str(e.code))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "EXIT:1" in result.stdout
        assert "Unknown MCP tool selector" in result.stderr

    def test_ac7_tools_and_include_conflict_exits(self):
        import subprocess
        import sys

        script = """
import sys, tempfile, os
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

from mempalace_code.mcp_server import main
try:
    main(["--tools", "search", "--include", "kg_query"])
except SystemExit as e:
    print("EXIT:" + str(e.code))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert "EXIT:1" in result.stdout
        assert "cannot be combined" in result.stderr

    # AC-1b (lazy startup): profile-filtered startup must not import miner/torch.
    def test_ac1b_minimal_profile_lazy_startup(self):
        import subprocess
        import sys

        script = """
import sys

class _Blocker:
    _BLOCKED = frozenset({"torch", "sentence_transformers", "mempalace_code.miner"})
    def find_spec(self, name, path=None, target=None):
        if name in self._BLOCKED:
            raise ImportError("Blocked by test: " + name)
        return None

sys.meta_path.insert(0, _Blocker())

import tempfile, os
_tmp = tempfile.mkdtemp()
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

from mempalace_code.mcp_server import handle_request, TOOLS
from mempalace_code.mcp_tool_profiles import resolve_active_tools

all_names = frozenset(TOOLS)
active = resolve_active_tools(all_names, profile="minimal")
registry = {k: v for k, v in TOOLS.items() if k in active}

resp1 = handle_request({"method": "initialize", "id": 1, "params": {}})
assert resp1["result"]["serverInfo"]["name"] == "mempalace-code", resp1

resp2 = handle_request({"method": "tools/list", "id": 2, "params": {}}, active_registry=registry)
names = {t["name"] for t in resp2["result"]["tools"]}
assert "mempalace_status" in names
assert "mempalace_mine" not in names  # excluded by minimal profile

for mod in ("torch", "sentence_transformers", "mempalace_code.miner"):
    assert mod not in sys.modules, mod + " was imported during minimal-profile init/tools-list"

print("OK")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "OK" in result.stdout


class TestLuaMCPSchema:
    """AC-8: MCP tools/list exposes lua in language description and local_function in symbol_type."""

    def test_lua_in_language_description(self):
        """'lua' appears in the mempalace_code_search language description."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 200, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        lang_desc = tools["mempalace_code_search"]["inputSchema"]["properties"]["language"][
            "description"
        ]
        assert "lua" in lang_desc, f"'lua' not found in language description: {lang_desc!r}"

    def test_local_function_in_symbol_type_description(self):
        """'local_function' appears in the mempalace_code_search symbol_type description."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 201, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        sym_desc = tools["mempalace_code_search"]["inputSchema"]["properties"]["symbol_type"][
            "description"
        ]
        assert "local_function" in sym_desc, (
            f"'local_function' not found in symbol_type description: {sym_desc!r}"
        )

    def test_lua_in_language_description_exactly_once(self):
        """'lua' appears exactly once in the language description (no duplicate)."""
        from mempalace_code.language_catalog import sorted_searchable_languages
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 202, "params": {}})
        assert resp is not None
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        lang_desc = tools["mempalace_code_search"]["inputSchema"]["properties"]["language"][
            "description"
        ]
        parsed = [
            part.strip() for part in lang_desc.split("Supported languages: ", 1)[1].split(",")
        ]
        assert parsed.count("lua") == 1, f"'lua' should appear exactly once, got: {parsed}"
        assert "lua" in list(sorted_searchable_languages())


# ── File context line ranges and MCP surgical read ───────────────────────────


class TestFileContextLineRange:
    """file_context_line_range: file_context returns non-null line_range for newly mined chunks."""

    def _seed_with_line_ranges(self, palace_path, wing=None):
        from mempalace_code.storage import open_store

        store = open_store(palace_path, create=True)
        store.add(
            ids=["fc_chunk0", "fc_chunk1"],
            documents=[
                "def authenticate(user): validate credentials",
                "def authorize(user, role): check permissions",
            ],
            metadatas=[
                {
                    "wing": wing or "proj",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 5,
                },
                {
                    "wing": wing or "proj",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "chunk_index": 1,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 6,
                    "line_end": 10,
                },
            ],
        )
        return store

    def test_happy_path_returns_all_chunks_with_fields(self, monkeypatch, config, palace_path, kg):
        """file_context_line_range: all chunks have chunk_index, content, symbol_name, line_range fields."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._seed_with_line_ranges(palace_path)
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context("/project/src/auth.py")
        assert result["total"] == 2
        for chunk in result["chunks"]:
            assert "chunk_index" in chunk
            assert "content" in chunk
            assert "line_range" in chunk

    def test_file_context_line_range_non_null_for_new_chunks(
        self, monkeypatch, config, palace_path, kg
    ):
        """file_context_line_range: chunks with positive line_start/line_end report non-null line_range."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._seed_with_line_ranges(palace_path)
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context("/project/src/auth.py")
        chunk0 = next(c for c in result["chunks"] if c["chunk_index"] == 0)
        chunk1 = next(c for c in result["chunks"] if c["chunk_index"] == 1)
        assert chunk0["line_range"] == {"start": 1, "end": 5}
        assert chunk1["line_range"] == {"start": 6, "end": 10}

    def test_file_context_line_range_null_for_legacy_chunks(
        self, monkeypatch, config, palace_path, kg
    ):
        """file_context_line_range: chunks without line metadata report null line_range (AC-6)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = open_store(palace_path, create=True)
        store.add(
            ids=["legacy_chunk"],
            documents=["class LegacyClass: old code"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/legacy.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context("/project/src/legacy.py")
        assert result["chunks"][0]["line_range"] is None

    def test_file_context_chunks_ordered_by_chunk_index(self, monkeypatch, config, palace_path, kg):
        """file_context_line_range: chunks are sorted by chunk_index regardless of storage order."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._seed_with_line_ranges(palace_path)
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context("/project/src/auth.py")
        indices = [c["chunk_index"] for c in result["chunks"]]
        assert indices == sorted(indices)

    def test_code_search_basic(self, monkeypatch, config, palace_path, kg):
        """Regression REG-2: existing MCP code_search still returns results with line_range field."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._seed_with_line_ranges(palace_path)
        from mempalace_code.mcp_server import tool_code_search

        result = tool_code_search("authenticate credentials")
        assert "results" in result
        assert len(result["results"]) > 0
        hit = result["results"][0]
        assert "line_range" in hit


class TestMCPReadSlice:
    """read_slice: MCP mempalace_read returns surgical slices for palace chunks."""

    def _seed_sliceable(self, palace_path):
        from mempalace_code.storage import open_store

        store = open_store(palace_path, create=True)
        store.add(
            ids=["rs_chunk0", "rs_chunk1"],
            documents=[
                "line A\nline B\nline C\nline D\nline E",
                "line F\nline G\nline H\nline I\nline J",
            ],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/sliceable.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 5,
                },
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/sliceable.py",
                    "chunk_index": 1,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 6,
                    "line_end": 10,
                },
            ],
        )

    def test_read_slice_single_chunk(self, monkeypatch, config, palace_path, kg):
        """read_slice: returns only requested lines from a single overlapping chunk."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._seed_sliceable(palace_path)
        from mempalace_code.mcp_server import tool_read

        result = tool_read("/project/src/sliceable.py", start_line=2, end_line=4)
        assert "error" not in result, f"Unexpected error: {result}"
        assert result["start"] == 2
        assert result["end"] == 4
        line_nos = [entry["line"] for entry in result["lines"]]
        assert line_nos == [2, 3, 4]
        assert result["lines"][0]["text"] == "line B"
        assert result["lines"][1]["text"] == "line C"
        assert result["lines"][2]["text"] == "line D"

    def test_read_slice_spanning_two_chunks(self, monkeypatch, config, palace_path, kg):
        """read_slice: returns lines from two chunks when range spans the boundary (AC-3)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._seed_sliceable(palace_path)
        from mempalace_code.mcp_server import tool_read

        result = tool_read("/project/src/sliceable.py", start_line=4, end_line=7)
        assert "error" not in result
        line_nos = [entry["line"] for entry in result["lines"]]
        assert 4 in line_nos
        assert 5 in line_nos
        assert 6 in line_nos
        assert 7 in line_nos
        assert line_nos == sorted(line_nos), "Lines must be in order"

    def test_read_slice_not_found(self, monkeypatch, config, palace_path, kg):
        """read_slice: returns not_found when source_file has no palace chunks (AC-4)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_read

        result = tool_read("/nonexistent/source.py", start_line=1, end_line=5)
        assert result["error"] == "not_found"

    def test_read_slice_stale_pointer(self, monkeypatch, config, palace_path, kg):
        """read_slice: returns stale_pointer when range does not overlap any stored chunk (AC-5)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._seed_sliceable(palace_path)
        from mempalace_code.mcp_server import tool_read

        result = tool_read("/project/src/sliceable.py", start_line=100, end_line=200)
        assert result["error"] == "stale_pointer"

    def test_read_slice_invalid_range(self, monkeypatch, config, palace_path, kg):
        """read_slice: returns invalid_range when start > end (AC-5)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_read

        result = tool_read("/project/src/sliceable.py", start_line=10, end_line=5)
        assert result["error"] == "invalid_range"

    def test_read_tool_registered_in_tools_list(self):
        """read_slice: mempalace_read appears in the MCP tools/list response."""
        from mempalace_code.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 300, "params": {}})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "mempalace_read" in names


# ── Graph Tools No-Embedder ─────────────────────────────────────────────────


def _guard_embedder_mcp(monkeypatch) -> None:
    """Patch LanceStore._get_embedder to raise — proves MCP graph tools avoid embedder startup."""
    from mempalace_code.storage import LanceStore

    def _raise(_self):  # noqa: N805
        raise RuntimeError("embedder must not be called during read-only graph tool operation")

    monkeypatch.setattr(LanceStore, "_get_embedder", _raise)


def _seed_graph_collection(palace_path: str) -> None:
    """Seed a palace with graph-friendly metadata for MCP graph tool tests."""
    store = open_store(palace_path, create=True)
    store.add(
        ids=["mcp_g_alpha_arch_001", "mcp_g_beta_arch_002", "mcp_g_alpha_backend_003"],
        documents=[
            "Architecture overview for the alpha project.",
            "Architecture notes shared with beta project.",
            "Backend implementation details for alpha.",
        ],
        metadatas=[
            {
                "wing": "alpha",
                "room": "architecture",
                "hall": "design",
                "date": "2026-01-01",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-01T00:00:00",
            },
            {
                "wing": "beta",
                "room": "architecture",
                "hall": "design",
                "date": "2026-01-02",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-02T00:00:00",
            },
            {
                "wing": "alpha",
                "room": "backend",
                "hall": "",
                "date": "",
                "chunk_index": 0,
                "added_by": "miner",
                "filed_at": "2026-01-03T00:00:00",
            },
        ],
    )


class TestGraphToolsNoEmbedder:
    """MCP graph tool calls use runtime read-only store without embedder startup."""

    def test_graph_stats_graph_tools_no_embedder(self, monkeypatch, config, palace_path, kg):
        """graph_stats MCP tool returns expected keys without embedder startup."""
        _seed_graph_collection(palace_path)
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _guard_embedder_mcp(monkeypatch)
        from mempalace_code.mcp_server import tool_graph_stats

        result = tool_graph_stats()

        assert "total_rooms" in result
        assert "tunnel_rooms" in result
        assert "total_edges" in result
        assert result["total_rooms"] == 2
        assert result["tunnel_rooms"] == 1

    def test_find_tunnels_graph_tools_no_embedder(self, monkeypatch, config, palace_path, kg):
        """find_tunnels MCP tool returns tunnel list without embedder startup."""
        _seed_graph_collection(palace_path)
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _guard_embedder_mcp(monkeypatch)
        from mempalace_code.mcp_server import tool_find_tunnels

        result = tool_find_tunnels()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["room"] == "architecture"

    def test_traverse_graph_tools_no_embedder(self, monkeypatch, config, palace_path, kg):
        """traverse MCP tool walks the graph without embedder startup."""
        _seed_graph_collection(palace_path)
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _guard_embedder_mcp(monkeypatch)
        from mempalace_code.mcp_server import tool_traverse_graph

        result = tool_traverse_graph(start_room="architecture")

        assert isinstance(result, list)
        rooms = {r["room"] for r in result}
        assert "architecture" in rooms

    def test_graph_stats_no_palace_graph_tools_no_embedder(self, monkeypatch, config, kg):
        """graph_stats MCP tool returns no-palace error when palace is missing."""
        config._file_config["palace_path"] = "/nonexistent/path"
        _patch_mcp_server(monkeypatch, config, "/nonexistent/path", kg)
        _guard_embedder_mcp(monkeypatch)
        from mempalace_code.mcp_server import tool_graph_stats

        result = tool_graph_stats()

        assert "error" in result


# ── MCP Read-Only Non-Search No-Embedder ───────────────────────────────────────


class TestMCPReadOnlyNonSearchNoEmbedder:
    """AC-4: MCP non-search read tools (file_context, read, diary_read) avoid embedder startup."""

    @staticmethod
    def _guard(monkeypatch):
        from mempalace_code.storage import LanceStore

        def _raise(_self, *args, **kwargs):
            raise RuntimeError("embedder must not be initialized in non-search read path")

        monkeypatch.setattr(LanceStore, "_get_embedder", _raise)

    def test_file_context_readonly_non_search_no_embedder(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        """tool_file_context returns chunks without touching the embedder."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._guard(monkeypatch)
        from mempalace_code.mcp_server import tool_file_context

        result = tool_file_context("auth.py")

        assert "error" not in result
        assert result["total"] >= 1
        assert result["chunks"]

    def test_read_readonly_non_search_no_embedder(self, monkeypatch, config, palace_path, kg):
        """tool_read returns sliced lines without touching the embedder."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["mcp_rd_slice_001"],
            documents=["line A\nline B\nline C"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/mcp_rd_auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 3,
                }
            ],
        )
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        self._guard(monkeypatch)
        from mempalace_code.mcp_server import tool_read

        result = tool_read("/project/mcp_rd_auth.py", start_line=1, end_line=2)

        assert result.get("error") != "not_found", f"Unexpected not_found: {result}"
        assert "lines" in result
        assert len(result["lines"]) >= 1

    def test_diary_read_readonly_non_search_no_embedder(self, monkeypatch, config, palace_path, kg):
        """tool_diary_read returns entries without touching the embedder."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace_code.mcp_server import tool_diary_write

        tool_diary_write("test_no_emb_agent", "No-embedder diary test entry.")

        self._guard(monkeypatch)
        from mempalace_code.mcp_server import tool_diary_read

        result = tool_diary_read("test_no_emb_agent")

        assert "error" not in result, f"Unexpected error: {result}"
        assert result.get("entries"), f"Expected entries in result: {result}"
        assert len(result["entries"]) >= 1


# ── Delete-After-Read Upgrade ───────────────────────────────────────────────────


class TestDeleteAfterReadUpgrade:
    """AC-3: delete tools upgrade a cached read-only handle to a write-capable handle."""

    def test_delete_after_read_upgrade(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        """Calling tool_delete_drawer after tool_status (read-only) must succeed.

        tool_status opens the store read-only; tool_delete_drawer must detect the
        cached read-only handle, discard it, and open a write-capable handle.
        """
        from mempalace_code.mcp import runtime

        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        monkeypatch.setattr(runtime, "_store_read_only", False)

        from mempalace_code.mcp_server import tool_delete_drawer, tool_status

        status = tool_status()
        assert status["total_drawers"] == 4
        assert runtime._store_read_only is True

        result = tool_delete_drawer("drawer_proj_backend_aaa")
        assert result["success"] is True

        status2 = tool_status()
        assert status2["total_drawers"] == 3


# ── Delete-After-Read: offline no-embedder subprocess tests ────────────────────

_MODEL_NOISE_MARKERS = (
    "huggingface",
    "sentence-transformers",
    "Loading embedding model",
    "Loading weights",
    "No sentence-transformers model found",
)


def _assert_no_model_noise(stdout: str, stderr: str) -> None:
    combined = (stdout + stderr).lower()
    for marker in _MODEL_NOISE_MARKERS:
        assert marker.lower() not in combined, (
            f"Model-loading marker {marker!r} found in subprocess output.\n"
            f"stdout: {stdout!r}\nstderr: {stderr!r}"
        )


def _run_mcp_stdio(
    requests: list,
    palace_path: str,
    sys_executable: str,
    fresh_home: str,
    timeout: int = 60,
):
    """Spawn the MCP stdio server, send JSON-RPC requests, return (responses, stdout, stderr)."""
    import os
    import subprocess

    stdin_data = "\n".join(json.dumps(r) for r in requests) + "\n"

    env = os.environ.copy()
    env["MEMPALACE_PALACE_PATH"] = palace_path
    env["HOME"] = fresh_home
    env["USERPROFILE"] = fresh_home
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    # Remove HF cache env vars so the subprocess has no model cache.
    env.pop("HF_HOME", None)
    env.pop("HUGGINGFACE_HUB_CACHE", None)
    env.pop("TRANSFORMERS_CACHE", None)

    result = subprocess.run(
        [sys_executable, "-m", "mempalace_code.mcp_server"],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )

    responses = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return responses, result.stdout, result.stderr


class TestDeleteAfterReadOfflineNoEmbedder:
    """AC-1/AC-2/AC-3: real stdio MCP subprocess proves delete works offline without embedder."""

    def test_delete_after_read_offline_no_embedder_delete_drawer(
        self, palace_path, seeded_collection
    ):
        """status-then-delete_drawer succeeds in an offline fresh-HOME subprocess."""
        import sys
        import tempfile

        fresh_home = tempfile.mkdtemp(prefix="mcp_fresh_home_")
        try:
            drawer_id = "drawer_proj_backend_aaa"
            requests = [
                {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {"name": "mempalace_status", "arguments": {}},
                },
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 3,
                    "params": {
                        "name": "mempalace_delete_drawer",
                        "arguments": {"drawer_id": drawer_id},
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 4,
                    "params": {"name": "mempalace_status", "arguments": {}},
                },
            ]

            responses, stdout, stderr = _run_mcp_stdio(
                requests, palace_path, sys.executable, fresh_home
            )

            assert len(responses) == 4, (
                f"Expected 4 responses, got {len(responses)}.\nstdout: {stdout}\nstderr: {stderr}"
            )

            # Response 0: initialize
            assert responses[0]["result"]["serverInfo"]["name"] == "mempalace-code"

            # Response 1: status before delete — should have 4 drawers from seeded_collection
            status_before = json.loads(responses[1]["result"]["content"][0]["text"])
            assert "error" not in status_before, f"status before delete failed: {status_before}"
            drawers_before = status_before["total_drawers"]
            assert drawers_before >= 1

            # Response 2: delete_drawer — must succeed
            delete_result = json.loads(responses[2]["result"]["content"][0]["text"])
            assert delete_result.get("success") is True, (
                f"delete_drawer failed: {delete_result}\nstdout: {stdout}\nstderr: {stderr}"
            )
            assert delete_result.get("drawer_id") == drawer_id

            # Response 3: status after delete — must show one fewer drawer
            status_after = json.loads(responses[3]["result"]["content"][0]["text"])
            assert "error" not in status_after, f"status after delete failed: {status_after}"
            assert status_after["total_drawers"] == drawers_before - 1

            _assert_no_model_noise(stdout, stderr)
        finally:
            import shutil

            shutil.rmtree(fresh_home, ignore_errors=True)

    def test_delete_after_read_offline_no_embedder_delete_wing(
        self, palace_path, seeded_collection
    ):
        """status-then-delete_wing succeeds in an offline fresh-HOME subprocess."""
        import sys
        import tempfile

        fresh_home = tempfile.mkdtemp(prefix="mcp_fresh_home_")
        try:
            requests = [
                {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {"name": "mempalace_status", "arguments": {}},
                },
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 3,
                    "params": {
                        "name": "mempalace_delete_wing",
                        "arguments": {"wing": "project"},
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 4,
                    "params": {"name": "mempalace_status", "arguments": {}},
                },
            ]

            responses, stdout, stderr = _run_mcp_stdio(
                requests, palace_path, sys.executable, fresh_home
            )

            assert len(responses) == 4, (
                f"Expected 4 responses, got {len(responses)}.\nstdout: {stdout}\nstderr: {stderr}"
            )

            # Response 1: status before delete
            status_before = json.loads(responses[1]["result"]["content"][0]["text"])
            assert "error" not in status_before, f"status before delete failed: {status_before}"
            drawers_before = status_before["total_drawers"]
            assert drawers_before >= 1

            # Response 2: delete_wing — must succeed with expected count
            delete_result = json.loads(responses[2]["result"]["content"][0]["text"])
            assert delete_result.get("success") is True, (
                f"delete_wing failed: {delete_result}\nstdout: {stdout}\nstderr: {stderr}"
            )
            assert delete_result.get("wing") == "project"
            deleted_count = delete_result.get("deleted_count", 0)
            assert deleted_count >= 1

            # Response 3: status after delete — wing must be gone
            status_after = json.loads(responses[3]["result"]["content"][0]["text"])
            assert "error" not in status_after, f"status after delete failed: {status_after}"
            assert status_after["total_drawers"] == drawers_before - deleted_count
            assert "project" not in status_after.get("wings", {})

            _assert_no_model_noise(stdout, stderr)
        finally:
            import shutil

            shutil.rmtree(fresh_home, ignore_errors=True)

    def test_delete_after_read_offline_no_embedder_not_found(self, palace_path, seeded_collection):
        """Missing drawer/wing deletes return structured errors, not 'No palace found'."""
        import sys
        import tempfile

        fresh_home = tempfile.mkdtemp(prefix="mcp_fresh_home_")
        try:
            requests = [
                {"jsonrpc": "2.0", "method": "initialize", "id": 1, "params": {}},
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {"name": "mempalace_status", "arguments": {}},
                },
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 3,
                    "params": {
                        "name": "mempalace_delete_drawer",
                        "arguments": {"drawer_id": "nonexistent_drawer_id_xyz"},
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 4,
                    "params": {
                        "name": "mempalace_delete_wing",
                        "arguments": {"wing": "nonexistent_wing_xyz"},
                    },
                },
            ]

            responses, stdout, stderr = _run_mcp_stdio(
                requests, palace_path, sys.executable, fresh_home
            )

            assert len(responses) == 4, (
                f"Expected 4 responses, got {len(responses)}.\nstdout: {stdout}\nstderr: {stderr}"
            )

            # Response 2: delete missing drawer — must be structured not-found, not "No palace found"
            delete_drawer_result = json.loads(responses[2]["result"]["content"][0]["text"])
            assert delete_drawer_result.get("success") is False, (
                f"Expected success=False for missing drawer: {delete_drawer_result}"
            )
            assert "No palace found" not in str(delete_drawer_result), (
                f"Got 'No palace found' instead of structured not-found: {delete_drawer_result}"
            )
            assert "error" in delete_drawer_result

            # Response 3: delete missing wing — must be structured not-found, not "No palace found"
            delete_wing_result = json.loads(responses[3]["result"]["content"][0]["text"])
            assert delete_wing_result.get("success") is False, (
                f"Expected success=False for missing wing: {delete_wing_result}"
            )
            assert "No palace found" not in str(delete_wing_result), (
                f"Got 'No palace found' instead of structured not-found: {delete_wing_result}"
            )
            assert "error" in delete_wing_result

            _assert_no_model_noise(stdout, stderr)
        finally:
            import shutil

            shutil.rmtree(fresh_home, ignore_errors=True)
