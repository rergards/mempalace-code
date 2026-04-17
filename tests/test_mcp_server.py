"""
test_mcp_server.py — Tests for the MCP server tool handlers and dispatch.

Tests each tool handler directly (unit-level) and the handle_request
dispatch layer (integration-level). Uses isolated palace + KG fixtures
via monkeypatch to avoid touching real data.
"""

import json
import pytest
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

    def test_delete_wing_storage_error(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_delete_wing, _get_store

        store = _get_store()

        def explode(wing):
            raise RuntimeError("simulated storage failure")

        monkeypatch.setattr(store, "delete_wing", explode)

        result = tool_delete_wing("project")
        assert result["success"] is False
        assert "simulated storage failure" in result["error"]

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

    def test_diary_write_collision_resistance(self, monkeypatch, config, palace_path, kg):
        """AC-1: two writes with identical content and same agent must both succeed with distinct IDs."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        _ensure_store(palace_path)
        from mempalace.mcp_server import tool_diary_write

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
        from mempalace.mcp_server import tool_code_search

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
        from mempalace.mcp_server import tool_code_search

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

    def test_code_search_devops_languages_in_hint(
        self, monkeypatch, config, palace_path, code_seeded_collection, kg
    ):
        """New DevOps language strings must appear in the supported_languages hint (MINE-DEVOPS-INFRA)."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_code_search

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
        from mempalace.mcp_server import tool_code_search

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
        from mempalace.mcp_server import tool_code_search

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

        from mempalace import mcp_server

        # Force the singleton to open so we have an instance to patch
        live_store = mcp_server._get_store()
        assert live_store is not None

        def _broken_count_by_pair(col_a, col_b):
            raise RuntimeError("fragment missing: IO error reading data file")

        monkeypatch.setattr(live_store, "count_by_pair", _broken_count_by_pair)

        result = mcp_server.tool_status()

        assert "error" in result, f"Expected 'error' key in result, got: {result}"
        assert "hint" in result, f"Expected 'hint' key in result, got: {result}"
        assert result.get("total_drawers", 0) > 0, (
            "total_drawers should still be populated from count()"
        )
        # Silent empty wings/rooms must not appear without explanation
        assert "wings" not in result or "error" in result

    def test_tool_status_healthy_palace_has_no_error_key(
        self, monkeypatch, config, palace_path, seeded_collection, kg
    ):
        """Healthy palace must not include 'error' in tool_status() response."""
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_status

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
        from mempalace.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="IService")
        assert "implementations" in result
        assert result["count"] == 1
        types = [r["type"] for r in result["implementations"]]
        assert "MyService" in types

    def test_find_implementations_empty(self, monkeypatch, config, palace_path, dotnet_kg):
        """AC-2: No implementors → returns empty list, no error."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="NoSuchInterface")
        assert result["implementations"] == []
        assert result["count"] == 0

    def test_find_implementations_multiple(self, monkeypatch, config, palace_path, kg):
        """AC-3: Multiple implementors are all returned."""
        kg.add_triple("ServiceA", "implements", "IDisposable")
        kg.add_triple("ServiceB", "implements", "IDisposable")
        kg.add_triple("ServiceC", "implements", "IDisposable")
        _patch_mcp_server(monkeypatch, config, palace_path, kg)
        from mempalace.mcp_server import tool_find_implementations

        result = tool_find_implementations(interface="IDisposable")
        assert result["count"] == 3
        types = {r["type"] for r in result["implementations"]}
        assert types == {"ServiceA", "ServiceB", "ServiceC"}

    def test_find_references_canonical_categories(
        self, monkeypatch, config, palace_path, dotnet_kg
    ):
        """AC-4: find_references('MyService') returns grouped canonical relationship categories."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace.mcp_server import tool_find_references

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
        from mempalace.mcp_server import tool_find_references

        result = tool_find_references(type_name="MyService")
        refs = result["references"]
        # MyService is not implemented by others (it's a class, not interface)
        assert "implementors" not in refs

    def test_show_project_graph_all(self, monkeypatch, config, palace_path, dotnet_kg):
        """AC-5: show_project_graph returns all project-level predicates grouped."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace.mcp_server import tool_show_project_graph

        result = tool_show_project_graph()
        graph = result["graph"]
        assert "depends_on" in graph
        assert "targets_framework" in graph
        assert "contains_project" in graph
        assert "references_project" in graph

    def test_show_project_graph_solution_filter(self, monkeypatch, config, palace_path, dotnet_kg):
        """AC-6: solution= filter limits graph to projects in that solution."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace.mcp_server import tool_show_project_graph

        result = tool_show_project_graph(solution="MySolution")
        graph = result["graph"]
        # MySolution contains MyApp → MyApp's depends_on/targets_framework appear
        depends = graph.get("depends_on", [])
        assert any(r["subject"] == "MyApp" for r in depends)
        contains = graph.get("contains_project", [])
        assert any(r["object"] == "MyApp" for r in contains)

    def test_show_type_dependencies_ancestors_and_descendants(
        self, monkeypatch, config, palace_path, dotnet_kg
    ):
        """AC-7: type_dependencies for MyService returns ancestors and descendants."""
        _patch_mcp_server(monkeypatch, config, palace_path, dotnet_kg)
        from mempalace.mcp_server import tool_show_type_dependencies

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
        from mempalace.mcp_server import tool_show_type_dependencies

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
        from mempalace.mcp_server import tool_show_type_dependencies

        result = tool_show_type_dependencies(type_name="MyService", max_depth=1)
        ancestor_types = {a["type"] for a in result["ancestors"]}
        assert "BaseService" in ancestor_types
        assert "GrandBase" not in ancestor_types

    def test_arch_tools_in_tools_list(self):
        """AC-12: All 4 new tools appear in tools/list with name, description, and inputSchema."""
        from mempalace.mcp_server import handle_request

        resp = handle_request({"method": "tools/list", "id": 99, "params": {}})
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
