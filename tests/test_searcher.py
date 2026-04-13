"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

from mempalace.searcher import code_search, search_memories


class TestSearchMemories:
    def test_basic_search(self, palace_path, seeded_collection):
        result = search_memories("JWT authentication", palace_path)
        assert "results" in result
        assert len(result["results"]) > 0
        assert result["query"] == "JWT authentication"

    def test_wing_filter(self, palace_path, seeded_collection):
        result = search_memories("planning", palace_path, wing="notes")
        assert all(r["wing"] == "notes" for r in result["results"])

    def test_room_filter(self, palace_path, seeded_collection):
        result = search_memories("database", palace_path, room="backend")
        assert all(r["room"] == "backend" for r in result["results"])

    def test_wing_and_room_filter(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, wing="project", room="frontend")
        assert all(r["wing"] == "project" and r["room"] == "frontend" for r in result["results"])

    def test_n_results_limit(self, palace_path, seeded_collection):
        result = search_memories("code", palace_path, n_results=2)
        assert len(result["results"]) <= 2

    def test_no_palace_returns_error(self):
        result = search_memories("anything", "/nonexistent/path")
        assert "error" in result

    def test_result_fields(self, palace_path, seeded_collection):
        result = search_memories("authentication", palace_path)
        hit = result["results"][0]
        assert "text" in hit
        assert "wing" in hit
        assert "room" in hit
        assert "source_file" in hit
        assert "symbol_name" in hit
        assert "symbol_type" in hit
        assert "language" in hit
        assert "similarity" in hit
        assert isinstance(hit["similarity"], float)

    def test_result_fields_code_drawer_values_populated(self, palace_path, code_seeded_collection):
        """Code drawers must return non-empty symbol_name, symbol_type, and language."""
        result = search_memories("detect programming language", palace_path)
        assert len(result["results"]) > 0
        # Find a hit that came from a code drawer (has symbol metadata)
        code_hits = [
            r for r in result["results"] if r["symbol_name"] or r["symbol_type"] or r["language"]
        ]
        assert len(code_hits) > 0, "Expected at least one result with symbol metadata"
        hit = code_hits[0]
        assert hit["symbol_name"] != ""
        assert hit["symbol_type"] != ""
        assert hit["language"] != ""


class TestCodeSearch:
    def test_code_search_returns_code_shape(self, palace_path, code_seeded_collection):
        result = code_search(palace_path, "language detection")
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
        assert isinstance(hit["similarity"], float)
        # filters key must have all 5 entries
        assert set(result["filters"].keys()) == {
            "language",
            "symbol_name",
            "symbol_type",
            "file_glob",
            "wing",
        }

    def test_code_search_post_filter_reduces_count(self, palace_path, code_seeded_collection):
        # 5 drawers seeded; only 2 have "detect" in symbol_name
        result = code_search(palace_path, "detect function", symbol_name="detect", n_results=5)
        assert "results" in result
        # Must be fewer than 5 (the seeded total) because post-filter excludes non-detect symbols
        assert len(result["results"]) < 5
        assert all("detect" in r["symbol_name"].lower() for r in result["results"])

    def test_code_search_no_palace_returns_error(self):
        result = code_search("/nonexistent/path", "authentication")
        assert "error" in result
        assert result["error"] == "No palace found"
        assert "hint" in result
