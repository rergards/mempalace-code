"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

import pytest
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


class TestDotNetLanguages:
    """.NET language and symbol type additions (MCP-ARCH-TOOLS AC-10, AC-11)."""

    @pytest.fixture
    def dotnet_collection(self, palace_path):
        from mempalace.storage import open_store

        store = open_store(palace_path, create=True)
        store.add(
            ids=["csharp_myservice", "csharp_record_dto"],
            documents=[
                "public class MyService : IService { }",
                "public record PersonDto(string Name, int Age);",
            ],
            metadatas=[
                {
                    "wing": "dotnet_project",
                    "room": "backend",
                    "source_file": "/src/MyService.cs",
                    "language": "csharp",
                    "symbol_name": "MyService",
                    "symbol_type": "class",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                },
                {
                    "wing": "dotnet_project",
                    "room": "backend",
                    "source_file": "/src/PersonDto.cs",
                    "language": "csharp",
                    "symbol_name": "PersonDto",
                    "symbol_type": "record",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-02T00:00:00",
                },
            ],
        )
        return store

    def test_code_search_csharp_language(self, palace_path, dotnet_collection):
        """AC-10: code_search(language='csharp') returns results, not an 'unsupported language' error."""
        result = code_search(palace_path, "service class", language="csharp")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) > 0

    def test_code_search_record_symbol_type(self, palace_path, dotnet_collection):
        """AC-11: code_search(symbol_type='record') returns results, not an 'invalid symbol_type' error."""
        result = code_search(palace_path, "data transfer object", symbol_type="record")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_dotnet_languages_accepted(self, palace_path):
        """AC-10: All .NET languages pass validation (no 'Unsupported language' error)."""
        for lang in ("csharp", "fsharp", "vbnet", "xaml", "dotnet-solution"):
            result = code_search(palace_path, "something", language=lang)
            assert "Unsupported language" not in result.get("error", ""), (
                f"Language {lang!r} should be supported, got: {result.get('error')}"
            )

    def test_dotnet_symbol_types_accepted(self, palace_path):
        """AC-11: All new .NET symbol types pass validation (no 'invalid symbol_type' error)."""
        for sym_type in (
            "record",
            "enum",
            "property",
            "event",
            "module",
            "union",
            "type",
            "view",
            "exception",
        ):
            result = code_search(palace_path, "something", symbol_type=sym_type)
            assert "invalid symbol_type" not in result.get("error", "").lower(), (
                f"Symbol type {sym_type!r} should be valid, got: {result.get('error')}"
            )

    def test_dotnet_languages_in_error_hint(self, palace_path):
        """AC-10: .NET languages appear in the supported_languages hint when an invalid language is used."""
        result = code_search(palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        for lang in ("csharp", "fsharp", "vbnet", "xaml", "dotnet-solution"):
            assert lang in result["supported_languages"], (
                f".NET language {lang!r} missing from supported_languages hint"
            )


class TestLanguageCatalogContract:
    """Code search language validation stays aligned with mined language labels."""

    def test_mined_languages_pass_validation(self, palace_path):
        for lang in ("kotlin", "jsx", "tsx", "xml", "perl"):
            result = code_search(palace_path, "something", language=lang)
            assert "Unsupported language" not in result.get("error", ""), (
                f"Mined language {lang!r} should be filterable, got: {result.get('error')}"
            )

    def test_mined_languages_appear_in_error_hint(self, palace_path):
        result = code_search(palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        for lang in ("kotlin", "jsx", "tsx", "xml", "perl"):
            assert lang in result["supported_languages"], (
                f"Mined language {lang!r} missing from supported_languages hint"
            )
