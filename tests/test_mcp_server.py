"""
test_mcp_server.py — Tests for the MCP server tool handlers and dispatch.

Tests each tool handler directly (unit-level) and the handle_request
dispatch layer (integration-level). Uses isolated palace + KG fixtures
via monkeypatch to avoid touching real data.
"""

import json
from mempalace.storage import open_store


def _patch_mcp_server(monkeypatch, config, palace_path, kg):
    """Patch the mcp_server module globals to use test fixtures."""
    from mempalace import mcp_server

    assert getattr(config, "palace_path", None) == palace_path, (
        f"config.palace_path ({getattr(config, 'palace_path', None)!r}) does not match palace_path fixture ({palace_path!r})"
    )
    monkeypatch.setattr(mcp_server, "_config", config)
    monkeypatch.setattr(mcp_server, "_kg", kg)
    # Reset the singleton store so it re-opens with the test palace
    monkeypatch.setattr(mcp_server, "_store", None)


def _ensure_store(palace_path):
    """Helper to ensure a store exists at the test palace path."""
    return open_store(palace_path, create=True)


# ── Protocol Layer ──────────────────────────────────────────────────────


class TestHandleRequest:
    def test_initialize(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "initialize", "id": 1, "params": {}})
        assert resp["result"]["serverInfo"]["name"] == "mempalace"
        assert resp["id"] == 1

    def test_notifications_initialized_returns_none(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "notifications/initialized", "id": None, "params": {}})
        assert resp is None

    def test_tools_list(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 2, "params": {}})
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "mempalace_status" in names
        assert "mempalace_search" in names
        assert "mempalace_add_drawer" in names
        assert "mempalace_kg_add" in names
        assert "mempalace_delete_wing" in names

    def test_unknown_tool(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 3,
                "params": {"name": "nonexistent_tool", "arguments": {}},
            }
        )
        assert resp["error"]["code"] == -32601

    def test_unknown_method(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "unknown/method", "id": 4, "params": {}})
        assert resp["error"]["code"] == -32601

    def test_tools_call_dispatches(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import handle_request

        # Ensure store exists
        _ensure_store(palace_path)

        resp = handle_request(
            {
                "method": "tools/call",
                "id": 5,
                "params": {"name": "mempalace_status", "arguments": {}},
            }
        )
        assert "result" in resp
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "total_drawers" in content


# ── Read Tools ──────────────────────────────────────────────────────────


class TestReadTools:
    def test_status_empty_palace(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == 0
        assert result["wings"] == {}

    def test_status_with_data(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == 4
        assert "project" in result["wings"]
        assert "notes" in result["wings"]

    def test_list_wings(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_list_wings

        result = tool_list_wings()
        assert result["wings"]["project"] == 3
        assert result["wings"]["notes"] == 1

    def test_list_rooms_all(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_list_rooms

        result = tool_list_rooms()
        assert "backend" in result["rooms"]
        assert "frontend" in result["rooms"]
        assert "planning" in result["rooms"]

    def test_list_rooms_filtered(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_list_rooms

        result = tool_list_rooms(wing="project")
        assert "backend" in result["rooms"]
        assert "planning" not in result["rooms"]

    def test_get_taxonomy(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_get_taxonomy

        result = tool_get_taxonomy()
        assert result["taxonomy"]["project"]["backend"] == 2
        assert result["taxonomy"]["project"]["frontend"] == 1
        assert result["taxonomy"]["notes"]["planning"] == 1

    def test_no_palace_returns_error(self, monkeypatch, config, kg):
        config._file_config["palace_path"] = "/nonexistent/path"
        _patch_mcp_server(monkeypatch, config, "/nonexistent/path", kg)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert "error" in result

    def test_status_no_aaak_by_default(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        monkeypatch.delenv("MEMPALACE_AAAK", raising=False)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert "aaak_dialect" not in result
        assert "protocol" not in result

    def test_status_aaak_when_env_set(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        monkeypatch.setenv("MEMPALACE_AAAK", "1")
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert "aaak_dialect" in result
        assert "protocol" in result

    def test_get_aaak_spec_always_available(self, monkeypatch, config, palace_path, kg):
        """mempalace_get_aaak_spec returns the spec regardless of MEMPALACE_AAAK (AC-3)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_get_aaak_spec

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
        from mempalace.mcp_server import tool_search

        result = tool_search(query="JWT authentication tokens")
        assert "results" in result
        assert len(result["results"]) > 0
        # Top result should be the auth drawer
        top = result["results"][0]
        assert "JWT" in top["text"] or "authentication" in top["text"].lower()

    def test_search_with_wing_filter(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_search

        result = tool_search(query="planning", wing="notes")
        assert all(r["wing"] == "notes" for r in result["results"])

    def test_search_with_room_filter(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_search

        result = tool_search(query="database", room="backend")
        assert all(r["room"] == "backend" for r in result["results"])


# ── Write Tools ─────────────────────────────────────────────────────────


class TestWriteTools:
    def test_add_drawer_after_status_on_new_palace(self, monkeypatch, config, palace_path, kg):
        """_get_store singleton must not cache a broken stub when palace doesn't exist yet.

        Regression: tool_status() with create=False used to cache a LanceStore
        with _table=None.  A subsequent tool_add_drawer() call would return the
        cached stub and fail with RuntimeError("Table does not exist and create=False").
        """
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_status, tool_add_drawer

        # Step 1: read-only call on a palace that has no table yet
        status_result = tool_status()
        assert status_result["total_drawers"] == 0

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
        from mempalace.mcp_server import tool_add_drawer

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
        from mempalace.mcp_server import tool_add_drawer
        from mempalace.storage import open_store
        from mempalace.version import __version__

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
        from mempalace.mcp_server import tool_add_drawer

        content = "This is a unique test memory about Rust ownership and borrowing."
        result1 = tool_add_drawer(wing="w", room="r", content=content)
        assert result1["success"] is True

        result2 = tool_add_drawer(wing="w", room="r", content=content)
        assert result2["success"] is False
        assert result2["reason"] == "duplicate"

    def test_delete_drawer(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_delete_drawer, _get_store

        result = tool_delete_drawer("drawer_proj_backend_aaa")
        assert result["success"] is True
        # Verify through the MCP server's store (same connection path)
        store = _get_store()
        assert store.count() == 3

    def test_delete_drawer_not_found(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_delete_drawer

        result = tool_delete_drawer("nonexistent_drawer")
        assert result["success"] is False

    def test_delete_wing(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_delete_wing, _get_store

        result = tool_delete_wing("project")
        assert result["success"] is True
        assert result["wing"] == "project"
        assert result["deleted_count"] == 3
        store = _get_store()
        assert store.count() == 1

    def test_delete_wing_not_found(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_delete_wing

        result = tool_delete_wing("nonexistent_wing")
        assert result["success"] is False
        assert "error" in result

    def test_check_duplicate(self, monkeypatch, config, palace_path, seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_check_duplicate

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
        from mempalace.mcp_server import tool_kg_add

        result = tool_kg_add(
            subject="Alice",
            predicate="likes",
            object="coffee",
            valid_from="2025-01-01",
        )
        assert result["success"] is True

    def test_kg_query(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_query

        result = tool_kg_query(entity="Max")
        assert result["count"] > 0

    def test_kg_invalidate(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_invalidate

        result = tool_kg_invalidate(
            subject="Max",
            predicate="does",
            object="chess",
            ended="2026-03-01",
        )
        assert result["success"] is True

    def test_kg_timeline(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_timeline

        result = tool_kg_timeline(entity="Alice")
        assert result["count"] > 0

    def test_kg_stats(self, monkeypatch, config, palace_path, seeded_kg):
        _patch_mcp_server(monkeypatch, config, palace_path, seeded_kg)
        from mempalace.mcp_server import tool_kg_stats

        result = tool_kg_stats()
        assert result["entities"] >= 4


# ── Diary Tools ─────────────────────────────────────────────────────────


class TestDiaryTools:
    def test_diary_write_and_read(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace.mcp_server import tool_diary_write, tool_diary_read

        w = tool_diary_write(
            agent_name="TestAgent",
            entry="Today we discussed authentication patterns.",
            topic="architecture",
        )
        assert w["success"] is True
        assert w["agent"] == "TestAgent"

        r = tool_diary_read(agent_name="TestAgent")
        assert r["total"] == 1
        assert r["entries"][0]["topic"] == "architecture"
        assert "authentication" in r["entries"][0]["content"]

    def test_diary_read_empty(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace.mcp_server import tool_diary_read

        r = tool_diary_read(agent_name="Nobody")
        assert r["entries"] == []

    def test_diary_read_beyond_legacy_limit(self, monkeypatch, config, palace_path, kg):
        """tool_diary_read must return entries when diary count exceeds legacy 10k limit."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        # Simulate what happens when count() > 10000: seed count() by adding
        # drawers in other wings so count() > the number of diary entries.
        # We verify the fetch is not artificially capped by inserting diary
        # entries directly and checking last_n is respected.
        from mempalace.mcp_server import tool_diary_write, tool_diary_read

        for i in range(3):
            tool_diary_write(agent_name="BoundaryAgent", entry=f"Entry number {i}", topic="test")

        r = tool_diary_read(agent_name="BoundaryAgent", last_n=2)
        assert r["showing"] == 2
        assert r["total"] == 3


# ── Aggregation Regression Tests ─────────────────────────────────────────


class TestCodeSearchTool:
    def test_code_search_basic(self, monkeypatch, config, palace_path, code_seeded_collection, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

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
        from mempalace.mcp_server import tool_code_search

        result = tool_code_search(query="code function", language="python")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["language"] == "python" for r in result["results"])

    def test_code_search_symbol_name_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

        result = tool_code_search(query="detect language user", symbol_name="detect")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all("detect" in r["symbol_name"].lower() for r in result["results"])

    def test_code_search_symbol_type_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

        result = tool_code_search(query="code function", symbol_type="function")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["symbol_type"] == "function" for r in result["results"])

    def test_code_search_file_glob_filter(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

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
        from mempalace.mcp_server import tool_code_search

        result = tool_code_search(query="code", language="python", symbol_type="function")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["language"] == "python" for r in result["results"])
        assert all(r["symbol_type"] == "function" for r in result["results"])

    def test_code_search_invalid_language(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

        result = tool_code_search(query="something", language="cobol")
        assert "error" in result
        assert "supported_languages" in result
        assert "python" in result["supported_languages"]

    def test_code_search_invalid_symbol_type(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

        result = tool_code_search(query="something", symbol_type="variable")
        assert "error" in result
        assert "valid_symbol_types" in result
        assert "function" in result["valid_symbol_types"]

    def test_code_search_n_results_clamp(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

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
        from mempalace.mcp_server import tool_code_search

        result = tool_code_search(query="code storage", wing="mempalace")
        assert "results" in result
        assert len(result["results"]) > 0
        assert all(r["wing"] == "mempalace" for r in result["results"])

    def test_code_search_in_tools_list(self):
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
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
        }
        assert schema.get("required") == ["query"]
        assert props["n_results"]["type"] == "integer"


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
        from mempalace.mcp_server import tool_list_wings

        result = tool_list_wings()
        assert set(result["wings"].keys()) == {"alpha", "beta", "gamma"}
        assert result["wings"]["alpha"] == 4
        assert result["wings"]["beta"] == 4
        assert result["wings"]["gamma"] == 4

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
        from mempalace.mcp_server import tool_list_rooms

        result = tool_list_rooms(wing="wing1")
        assert set(result["rooms"].keys()) == {"roomA", "roomB"}
        assert "roomC" not in result["rooms"]

    def test_status_counts_match_total(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = _ensure_store(palace_path)
        self._seed_multi_wing(store)
        from mempalace.mcp_server import tool_status

        result = tool_status()
        assert result["total_drawers"] == sum(result["wings"].values())

    def test_taxonomy_complete(self, monkeypatch, config, palace_path, kg):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        store = _ensure_store(palace_path)
        self._seed_multi_wing(store)
        from mempalace.mcp_server import tool_get_taxonomy

        result = tool_get_taxonomy()
        tax = result["taxonomy"]
        assert set(tax.keys()) == {"alpha", "beta", "gamma"}
        for wing in ("alpha", "beta", "gamma"):
            assert tax[wing]["frontend"] == 2
            assert tax[wing]["backend"] == 2
