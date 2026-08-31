"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

import shlex

import pytest

from mempalace_code.language_catalog import sorted_searchable_languages
from mempalace_code.searcher import SearchError, code_search, search, search_memories
from mempalace_code.storage import LanceStore, open_store
from mempalace_code.taxonomy_filters import TaxonomyValidationError


class TestSearchMemories:
    class FakeSearchStore:
        def __init__(self, metadata):
            self.metadata = metadata

        def query(self, **_kwargs):
            return {
                "documents": [["def authenticate(): return current_user"]],
                "metadatas": [[self.metadata]],
                "distances": [[0.125]],
            }

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

    def test_no_palace_returns_error(self, tmp_path):
        palace_path = tmp_path / "missing" / "palace"
        expected = {
            "error": "No palace found",
            "hint": "Run: mempalace-code init <dir> && mempalace-code mine <dir>",
        }

        for _ in range(2):
            assert search_memories("anything", str(palace_path)) == expected
            assert not palace_path.exists()

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

    def test_search_memories_full_source_file_path(self, monkeypatch):
        store = self.FakeSearchStore(
            {
                "wing": "project",
                "room": "backend",
                "source_file": "/project/src/auth.py",
            }
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_args, **_kwargs: store)

        result = search_memories("authentication", "/fake/palace")

        assert result["results"][0]["source_file"] == "/project/src/auth.py"

    def test_search_memories_missing_source_file_fallback(self, monkeypatch):
        store = self.FakeSearchStore({"wing": "project", "room": "backend"})
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_args, **_kwargs: store)

        result = search_memories("authentication", "/fake/palace")

        assert result["results"][0]["source_file"] == "?"


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

    def test_code_search_invalid_language_matches_catalog(self, monkeypatch):
        def fail_open_store(*_args, **_kwargs):
            raise AssertionError("invalid language validation should run before storage open")

        monkeypatch.setattr("mempalace_code.searcher.open_store", fail_open_store)

        result = code_search("/unused/palace", "something", language="notareallangnnn")

        assert result == {
            "error": "Unsupported language: 'notareallangnnn'",
            "supported_languages": list(sorted_searchable_languages()),
        }

    def test_code_search_catalog_language_filters_include_pr4_detector_labels(self):
        for lang in ("kotlin", "xml", "perl"):
            result = code_search("/unused/palace", "something", language=lang)
            assert "Unsupported language" not in result.get("error", ""), (
                f"Catalog language {lang!r} should be accepted, got: {result.get('error')}"
            )

    def test_code_search_full_source_file_path_unchanged(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["auth_function"],
            documents=["def authenticate(): validate JWT token and return the current user"],
            metadatas=[
                {
                    "wing": "project",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "language": "python",
                    "symbol_name": "authenticate",
                    "symbol_type": "function",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )

        result = code_search(palace_path, "authenticate JWT", n_results=1)

        assert result["results"][0]["source_file"] == "/project/src/auth.py"


class TestSearchCompactCLI:
    class FakeStore:
        def __init__(self, documents, metadatas):
            self.documents = documents
            self.metadatas = metadatas
            self.query_kwargs = None

        def query(self, **kwargs):
            self.query_kwargs = kwargs
            limit = kwargs["n_results"]
            return {
                "documents": [self.documents[:limit]],
                "metadatas": [self.metadatas[:limit]],
                "distances": [[0.125] * min(limit, len(self.documents))],
            }

    @staticmethod
    def _render(monkeypatch, capsys, documents, metadatas, **kwargs):
        store = TestSearchCompactCLI.FakeStore(documents, metadatas)
        monkeypatch.setattr("mempalace_code.searcher.os.path.isdir", lambda _path: True)
        monkeypatch.setattr(
            "mempalace_code.searcher.validate_taxonomy_filters", lambda *_args, **_kwargs: None
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_args, **_kwargs: store)
        search("needle", "/fake/palace", **kwargs)
        return capsys.readouterr().out, store

    def test_compact_bounds_previews_and_preserves_exact_metadata(self, monkeypatch, capsys):
        long_document = "first line\n" + "x" * 400
        source = "/project/odd path/o'hare.py"
        wing = "project wing"
        metadata = {
            "wing": wing,
            "room": "backend",
            "source_file": source,
            "line_start": "12",
            "line_end": 18,
        }

        output, store = self._render(
            monkeypatch,
            capsys,
            [long_document] * 4,
            [metadata] * 4,
            compact=True,
            n_results=3,
        )

        previews = [
            line.removeprefix("      ") for line in output.splitlines() if "first line" in line
        ]
        assert store.query_kwargs["n_results"] == 3
        assert len(previews) == 3
        assert all(len(preview) == 300 and preview.endswith("...") for preview in previews)
        assert output.count("Source: /project/odd path/o'hare.py") == 3
        assert output.count("Lines:  12-18") == 3
        assert output.count("Match:  0.875") == 3
        command = (
            f"mempalace-code read {shlex.quote(source)} --start 12 --end 18 "
            f"--wing {shlex.quote(wing)}"
        )
        assert output.count(f"Recovery: {command}") == 3

    @pytest.mark.parametrize(
        "metadata",
        [
            {},
            {"source_file": "", "wing": "project", "line_start": 1, "line_end": 2},
            {"source_file": [], "wing": "project", "line_start": 1, "line_end": 2},
            {"source_file": "?", "wing": "project", "line_start": 1, "line_end": 2},
            {"source_file": "a.py", "wing": " ", "line_start": 1, "line_end": 2},
            {"source_file": "a.py", "wing": "project", "line_start": 0, "line_end": 2},
            {"source_file": "a.py", "wing": "project", "line_start": 3, "line_end": 2},
            {"source_file": "a.py", "wing": "project", "line_start": "x", "line_end": 2},
            {"source_file": "a.py", "wing": "project", "line_start": True, "line_end": 2},
        ],
    )
    def test_compact_malformed_metadata_never_invents_recovery(self, monkeypatch, capsys, metadata):
        output, _store = self._render(monkeypatch, capsys, ["document"], [metadata], compact=True)

        assert output.count("Recovery: unavailable") == 1
        assert "mempalace-code read" not in output

    def test_compact_empty_document_and_equal_range_are_safe(self, monkeypatch, capsys):
        metadata = {
            "source_file": "a.py",
            "wing": "project",
            "room": "backend",
            "line_start": 7,
            "line_end": 7,
        }

        output, _store = self._render(monkeypatch, capsys, [None], [metadata], compact=True)

        assert "Lines:  7-7" in output
        assert "Recovery: mempalace-code read a.py --start 7 --end 7 --wing project" in output

    def test_default_output_remains_full_text(self, monkeypatch, capsys):
        document = "first line\n" + "x" * 400
        metadata = {
            "wing": "project",
            "room": "backend",
            "source_file": "/project/app.py",
            "line_start": 1,
            "line_end": 2,
        }

        output, _store = self._render(monkeypatch, capsys, [document], [metadata])

        assert f"      {document.splitlines()[1]}" in output
        assert "Lines:" not in output
        assert "Recovery:" not in output


class TestTaxonomyFilterValidation:
    """Explicit wing/room filters are validated against the palace taxonomy before retrieval."""

    def test_search_valid_empty_scope_stays_successful(
        self, palace_path, seeded_collection, monkeypatch
    ):
        """A valid wing with genuinely zero matches is a success, not a validation error."""

        def _empty_query(self, *args, **kwargs):
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}

        monkeypatch.setattr(LanceStore, "query", _empty_query)

        result = search_memories("anything", palace_path, wing="project")

        assert "error" not in result
        assert result["results"] == []
        assert result["filters"] == {"wing": "project", "room": None}

    def test_search_memories_unknown_taxonomy_wing_returns_structured_error(
        self, palace_path, seeded_collection
    ):
        result = search_memories("anything", palace_path, wing="does-not-exist")
        assert result["error"] == "unknown_wing"
        assert result["filter"] == "wing"
        assert result["value"] == "does-not-exist"
        assert "results" not in result

    def test_search_memories_unknown_taxonomy_room_returns_structured_error(
        self, palace_path, seeded_collection
    ):
        result = search_memories("anything", palace_path, room="does-not-exist")
        assert result["error"] == "unknown_room"
        assert result["filter"] == "room"

    def test_search_memories_taxonomy_filter_validation_wing_room_pair(
        self, palace_path, seeded_collection
    ):
        """AC-4: "planning" only exists under wing "notes", not "project"."""
        result = search_memories("anything", palace_path, wing="project", room="planning")
        assert result["error"] == "unknown_wing_room"
        assert result["filter"] == "wing_room"
        assert result["value"] == {"wing": "project", "room": "planning"}

    def test_code_search_unknown_taxonomy_wing_returns_structured_error(
        self, palace_path, code_seeded_collection
    ):
        result = code_search(palace_path, "anything", wing="does-not-exist")
        assert result["error"] == "unknown_wing"
        assert result["filter"] == "wing"

    def test_taxonomy_filter_validation_preserves_supplied_value(
        self, palace_path, seeded_collection
    ):
        """AC-5: a close punctuation variant of "project" ranks as a suggestion, not a rewrite."""
        result = search_memories("anything", palace_path, wing="pro-ject")
        assert result["error"] == "unknown_wing"
        assert result["value"] == "pro-ject"
        assert "project" in result["suggestions"]

    def test_search_memories_no_embedder_on_invalid_taxonomy(
        self, palace_path, seeded_collection, monkeypatch
    ):
        """AC-6: an unknown wing must not trigger embedder initialization."""

        def _no_embedder(self):
            raise RuntimeError("_get_embedder must not be called for an invalid taxonomy filter")

        monkeypatch.setattr(LanceStore, "_get_embedder", _no_embedder)

        result = search_memories("anything", palace_path, wing="does-not-exist")
        assert result["error"] == "unknown_wing"

    def test_code_search_no_embedder_on_invalid_taxonomy(
        self, palace_path, code_seeded_collection, monkeypatch
    ):
        def _no_embedder(self):
            raise RuntimeError("_get_embedder must not be called for an invalid taxonomy filter")

        monkeypatch.setattr(LanceStore, "_get_embedder", _no_embedder)

        result = code_search(palace_path, "anything", wing="does-not-exist")
        assert result["error"] == "unknown_wing"

    def test_search_print_variant_raises_taxonomy_validation_error(
        self, palace_path, seeded_collection
    ):
        with pytest.raises(TaxonomyValidationError) as exc_info:
            search("anything", palace_path, wing="does-not-exist")
        assert exc_info.value.payload["error"] == "unknown_wing"
        assert exc_info.value.payload["value"] == "does-not-exist"

    def test_search_print_variant_valid_wing_still_searches(
        self, palace_path, seeded_collection, capsys
    ):
        """A valid wing does not raise — the print search path runs normally."""
        search("authentication", palace_path, wing="project")
        out = capsys.readouterr().out
        assert "authenticate" in out.lower() or "Results for" in out


class TestReactLanguageSupport:
    """Regression coverage for JSX/TSX code_search language filters."""

    class FakeReactStore:
        def __init__(self):
            self.documents = [
                "export function Button() { return <button>Save</button>; }",
                (
                    "type ProfileProps = { name: string }; "
                    "export function Profile(props: ProfileProps) { "
                    "return <section>{props.name}</section>; }"
                ),
            ]
            self.metadatas = [
                {
                    "wing": "react_app",
                    "room": "frontend",
                    "source_file": "/project/src/Button.jsx",
                    "language": "jsx",
                    "symbol_name": "Button",
                    "symbol_type": "function",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                },
                {
                    "wing": "react_app",
                    "room": "frontend",
                    "source_file": "/project/src/Profile.tsx",
                    "language": "tsx",
                    "symbol_name": "Profile",
                    "symbol_type": "function",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-02T00:00:00",
                },
            ]

        def query(self, **kwargs):
            where = kwargs.get("where", {})
            language = where.get("language")
            matches = [
                (doc, meta)
                for doc, meta in zip(self.documents, self.metadatas)
                if language is None or meta["language"] == language
            ]
            return {
                "documents": [[doc for doc, _meta in matches]],
                "metadatas": [[meta for _doc, meta in matches]],
                "distances": [[0.1 for _doc, _meta in matches]],
            }

    @pytest.fixture
    def react_palace_path(self, monkeypatch):
        store = self.FakeReactStore()
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_args, **_kwargs: store)
        return "/fake/react-palace"

    def test_code_search_jsx_language(self, react_palace_path):
        """code_search(language='jsx') returns seeded JSX drawers instead of a validation error."""
        result = code_search(react_palace_path, "button component", language="jsx")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["filters"]["language"] == "jsx"
        assert len(result["results"]) > 0
        assert all(hit["language"] == "jsx" for hit in result["results"])
        assert any(hit["symbol_name"] == "Button" for hit in result["results"])

    def test_code_search_tsx_language(self, react_palace_path):
        """code_search(language='tsx') returns seeded TSX drawers instead of a validation error."""
        result = code_search(react_palace_path, "profile component", language="tsx")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["filters"]["language"] == "tsx"
        assert len(result["results"]) > 0
        assert all(hit["language"] == "tsx" for hit in result["results"])
        assert any(hit["symbol_name"] == "Profile" for hit in result["results"])

    def test_code_search_tsx_language_uppercase_is_normalized(self, react_palace_path):
        """code_search(language='TSX') normalizes to the stored 'tsx' language value."""
        result = code_search(react_palace_path, "profile component", language="TSX")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert result["filters"]["language"] == "tsx"
        assert len(result["results"]) > 0
        assert all(hit["language"] == "tsx" for hit in result["results"])

    def test_react_languages_in_supported_hint(self, react_palace_path):
        """jsx/tsx appear in the supported_languages hint on an invalid language query."""
        result = code_search(react_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "jsx" in result["supported_languages"]
        assert "tsx" in result["supported_languages"]


class TestDotNetLanguages:
    """.NET language and symbol type additions (MCP-ARCH-TOOLS AC-10, AC-11)."""

    @pytest.fixture
    def dotnet_collection(self, palace_path):
        from mempalace_code.storage import open_store

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


class TestSwiftLanguageSupport:
    """AC: Swift language and new symbol types pass code_search validation."""

    @pytest.fixture
    def swift_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["swift_userservice"],
            documents=["class UserService { func fetchUser() { } }"],
            metadatas=[
                {
                    "wing": "myapp",
                    "room": "backend",
                    "source_file": "UserService.swift",
                    "language": "swift",
                    "symbol_name": "UserService",
                    "symbol_type": "class",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_swift_language(self, swift_palace_path):
        """code_search(language='swift') does not return an 'unsupported language' error."""
        result = code_search(swift_palace_path, "user service", language="swift")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_swift_language_in_supported_hint(self, swift_palace_path):
        """'swift' appears in the supported_languages hint on an invalid language query."""
        result = code_search(swift_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "swift" in result["supported_languages"], (
            "'swift' missing from supported_languages hint"
        )

    def test_code_search_protocol_symbol_type(self, swift_palace_path):
        """code_search(symbol_type='protocol') does not return 'invalid symbol_type' error."""
        result = code_search(swift_palace_path, "something", symbol_type="protocol")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'protocol' should be valid, got: {result.get('error')}"
        )

    def test_code_search_actor_symbol_type(self, swift_palace_path):
        """code_search(symbol_type='actor') does not return 'invalid symbol_type' error."""
        result = code_search(swift_palace_path, "something", symbol_type="actor")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'actor' should be valid, got: {result.get('error')}"
        )

    def test_code_search_extension_symbol_type(self, swift_palace_path):
        """code_search(symbol_type='extension') does not return 'invalid symbol_type' error."""
        result = code_search(swift_palace_path, "something", symbol_type="extension")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'extension' should be valid, got: {result.get('error')}"
        )

    def test_code_search_typealias_symbol_type(self, swift_palace_path):
        """code_search(symbol_type='typealias') does not return 'invalid symbol_type' error.

        typealias is produced by both Swift and Kotlin extractors; it must be accepted
        as a valid filter so mined drawers are reachable via type-filtered search.
        """
        result = code_search(swift_palace_path, "something", symbol_type="typealias")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'typealias' should be valid, got: {result.get('error')}"
        )

    def test_swift_new_symbol_types_in_error_hint(self, swift_palace_path):
        """protocol/actor/extension/typealias appear in valid_symbol_types hint on invalid type query."""
        result = code_search(swift_palace_path, "something", symbol_type="notarealtype")
        assert "valid_symbol_types" in result
        for sym in ("protocol", "actor", "extension", "typealias"):
            assert sym in result["valid_symbol_types"], (
                f"Symbol type {sym!r} missing from valid_symbol_types hint"
            )


class TestPhpLanguageSupport:
    """AC: PHP language and new symbol types (trait, namespace) pass code_search validation."""

    @pytest.fixture
    def php_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["php_userservice"],
            documents=["class UserService { public function findById(int $id): ?array {} }"],
            metadatas=[
                {
                    "wing": "myapp",
                    "room": "backend",
                    "source_file": "UserService.php",
                    "language": "php",
                    "symbol_name": "UserService",
                    "symbol_type": "class",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_php_language(self, php_palace_path):
        """code_search(language='php') does not return an 'unsupported language' error."""
        result = code_search(php_palace_path, "user service", language="php")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_php_language_in_supported_hint(self, php_palace_path):
        """'php' appears in the supported_languages hint on an invalid language query."""
        result = code_search(php_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "php" in result["supported_languages"], "'php' missing from supported_languages hint"

    def test_code_search_trait_symbol_type(self, php_palace_path):
        """code_search(symbol_type='trait') does not return 'invalid symbol_type' error."""
        result = code_search(php_palace_path, "something", symbol_type="trait")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'trait' should be valid, got: {result.get('error')}"
        )

    def test_code_search_namespace_symbol_type(self, php_palace_path):
        """code_search(symbol_type='namespace') does not return 'invalid symbol_type' error."""
        result = code_search(php_palace_path, "something", symbol_type="namespace")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'namespace' should be valid, got: {result.get('error')}"
        )

    def test_php_new_symbol_types_in_error_hint(self, php_palace_path):
        """trait/namespace appear in valid_symbol_types hint on an invalid type query."""
        result = code_search(php_palace_path, "something", symbol_type="notarealtype")
        assert "valid_symbol_types" in result
        for sym in ("trait", "namespace"):
            assert sym in result["valid_symbol_types"], (
                f"Symbol type {sym!r} missing from valid_symbol_types hint"
            )


class TestKubernetesLanguageSupport:
    """AC-8, AC-9: kubernetes language and K8s resource kinds pass code_search validation."""

    @pytest.fixture
    def k8s_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["k8s_deployment_nginx"],
            documents=[
                "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: nginx\nspec:\n  replicas: 1\n"
            ],
            metadatas=[
                {
                    "wing": "infra",
                    "room": "general",
                    "source_file": "deploy.yaml",
                    "language": "kubernetes",
                    "symbol_name": "Deployment/nginx",
                    "symbol_type": "deployment",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_kubernetes_language(self, k8s_palace_path):
        """AC-8: code_search(language='kubernetes') does not return an 'unsupported language' error."""
        result = code_search(k8s_palace_path, "nginx", language="kubernetes")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) > 0

    def test_code_search_deployment_symbol_type(self, k8s_palace_path):
        """AC-9: code_search(symbol_type='deployment') does not return 'invalid symbol_type' error."""
        result = code_search(k8s_palace_path, "nginx", symbol_type="deployment")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_code_search_k8s_symbol_types_accepted(self, k8s_palace_path):
        """All K8s resource kinds pass symbol_type validation."""
        for sym_type in (
            "deployment",
            "service",
            "configmap",
            "secret",
            "ingress",
            "customresourcedefinition",
        ):
            result = code_search(k8s_palace_path, "something", symbol_type=sym_type)
            assert "invalid symbol_type" not in result.get("error", "").lower(), (
                f"symbol_type {sym_type!r} should be valid, got: {result.get('error')}"
            )

    def test_kubernetes_in_supported_languages_hint(self, k8s_palace_path):
        """'kubernetes' appears in the supported_languages hint on invalid language query."""
        result = code_search(k8s_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "kubernetes" in result["supported_languages"]


class TestScalaLanguageSupport:
    """AC-13/AC-14: Scala language and new symbol types (object, case_class, case_object)
    pass code_search validation."""

    @pytest.fixture
    def scala_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["scala_userservice"],
            documents=["class UserService(db: Database) { def findById(id: Long) = ??? }"],
            metadatas=[
                {
                    "wing": "myapp",
                    "room": "backend",
                    "source_file": "UserService.scala",
                    "language": "scala",
                    "symbol_name": "UserService",
                    "symbol_type": "class",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_scala_language(self, scala_palace_path):
        """AC-13: code_search(language='scala') does not return an 'unsupported language' error."""
        result = code_search(scala_palace_path, "user service", language="scala")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_scala_language_in_supported_hint(self, scala_palace_path):
        """'scala' appears in the supported_languages hint on an invalid language query."""
        result = code_search(scala_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "scala" in result["supported_languages"], (
            "'scala' missing from supported_languages hint"
        )

    def test_code_search_object_symbol_type(self, scala_palace_path):
        """AC-14: code_search(symbol_type='object') does not return 'invalid symbol_type' error."""
        result = code_search(scala_palace_path, "something", symbol_type="object")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'object' should be valid, got: {result.get('error')}"
        )

    def test_code_search_case_class_symbol_type(self, scala_palace_path):
        """AC-14: code_search(symbol_type='case_class') does not return 'invalid symbol_type' error."""
        result = code_search(scala_palace_path, "something", symbol_type="case_class")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'case_class' should be valid, got: {result.get('error')}"
        )

    def test_code_search_case_object_symbol_type(self, scala_palace_path):
        """AC-14: code_search(symbol_type='case_object') does not return 'invalid symbol_type' error."""
        result = code_search(scala_palace_path, "something", symbol_type="case_object")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'case_object' should be valid, got: {result.get('error')}"
        )

    def test_scala_new_symbol_types_in_error_hint(self, scala_palace_path):
        """object/case_class/case_object appear in valid_symbol_types hint on invalid type query."""
        result = code_search(scala_palace_path, "something", symbol_type="notarealtype")
        assert "valid_symbol_types" in result
        for sym in ("object", "case_class", "case_object"):
            assert sym in result["valid_symbol_types"], (
                f"Symbol type {sym!r} missing from valid_symbol_types hint"
            )


class TestCodeSearchDart:
    """Tests for Dart language and new Dart-specific symbol types in code_search."""

    @pytest.fixture
    def dart_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["dart_userservice"],
            documents=[
                "class UserService { Future<User?> fetchUser(int id) async { return null; } }"
            ],
            metadatas=[
                {
                    "wing": "myapp",
                    "room": "backend",
                    "source_file": "user_service.dart",
                    "language": "dart",
                    "symbol_name": "UserService",
                    "symbol_type": "class",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_dart_language(self, dart_palace_path):
        """AC-12: code_search(language='dart') does not return an 'unsupported language' error."""
        result = code_search(dart_palace_path, "user service", language="dart")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_dart_language_in_supported_hint(self, dart_palace_path):
        """'dart' appears in the supported_languages hint on an invalid language query."""
        result = code_search(dart_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "dart" in result["supported_languages"], (
            "'dart' missing from supported_languages hint"
        )

    def test_code_search_mixin_symbol_type(self, dart_palace_path):
        """AC-13: code_search(symbol_type='mixin') does not return 'invalid symbol_type' error."""
        result = code_search(dart_palace_path, "something", symbol_type="mixin")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'mixin' should be valid, got: {result.get('error')}"
        )

    def test_code_search_extension_type_symbol_type(self, dart_palace_path):
        """AC-13: code_search(symbol_type='extension_type') does not return 'invalid symbol_type' error."""
        result = code_search(dart_palace_path, "something", symbol_type="extension_type")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'extension_type' should be valid, got: {result.get('error')}"
        )

    def test_code_search_constructor_symbol_type(self, dart_palace_path):
        """AC-13: code_search(symbol_type='constructor') does not return 'invalid symbol_type' error."""
        result = code_search(dart_palace_path, "something", symbol_type="constructor")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'constructor' should be valid, got: {result.get('error')}"
        )

    def test_dart_new_symbol_types_in_error_hint(self, dart_palace_path):
        """mixin/extension_type/constructor appear in valid_symbol_types hint on invalid type query."""
        result = code_search(dart_palace_path, "something", symbol_type="notarealtype")
        assert "valid_symbol_types" in result
        for sym in ("mixin", "extension_type", "constructor"):
            assert sym in result["valid_symbol_types"], (
                f"Symbol type {sym!r} missing from valid_symbol_types hint"
            )


class _FakeNoneMetaStore:
    """Fake store that returns results containing None metadata or documents."""

    def __init__(self, documents, metadatas, distances=None):
        self._documents = documents
        self._metadatas = metadatas
        self._distances = distances or [0.1] * len(documents)

    def query(self, **_kwargs):
        return {
            "documents": [self._documents],
            "metadatas": [self._metadatas],
            "distances": [self._distances],
        }


class TestNoneMetadataRobustness:
    """AC-1/AC-2/AC-3: search_memories() and code_search() tolerate None metadata/documents."""

    def test_search_memories_tolerates_none_metadata(self, monkeypatch):
        """AC-1: None metadata row returns fallback sentinel values without raising."""
        store = _FakeNoneMetaStore(
            documents=["def authenticate(): return current_user"],
            metadatas=[None],
            distances=[0.125],
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: store)

        result = search_memories("authentication", "/fake/palace")

        assert "error" not in result
        assert len(result["results"]) == 1
        hit = result["results"][0]
        assert hit["text"] == "def authenticate(): return current_user"
        assert hit["wing"] == "unknown"
        assert hit["room"] == "unknown"
        assert hit["source_file"] == "?"
        assert hit["symbol_name"] == ""
        assert hit["similarity"] == round(1 - 0.125, 3)

    def test_code_search_tolerates_none_document_and_metadata(self, monkeypatch):
        """AC-2: None document and None metadata row returns empty-text result without raising."""
        store = _FakeNoneMetaStore(
            documents=[None],
            metadatas=[None],
            distances=[0.2],
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: store)

        result = code_search("/fake/palace", "anything")

        assert "error" not in result
        assert len(result["results"]) == 1
        hit = result["results"][0]
        assert hit["text"] == ""
        assert hit["wing"] == "unknown"
        assert hit["room"] == "unknown"
        assert hit["source_file"] == ""
        assert hit["symbol_name"] == ""
        assert hit["line_range"] is None
        assert hit["similarity"] == round(1 - 0.2, 3)

    def test_code_search_skips_none_metadata_when_post_filters_require_fields(self, monkeypatch):
        """AC-3: None-metadata hit is filtered out when symbol_name or file_glob is specified."""
        store = _FakeNoneMetaStore(
            documents=[None, "def authenticate(): JWT validation"],
            metadatas=[
                None,
                {
                    "wing": "project",
                    "room": "backend",
                    "source_file": "/src/auth.py",
                    "symbol_name": "authenticate",
                    "symbol_type": "function",
                },
            ],
            distances=[0.1, 0.15],
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: store)

        result = code_search("/fake/palace", "auth", symbol_name="authenticate")

        assert "error" not in result
        assert len(result["results"]) == 1
        assert result["results"][0]["symbol_name"] == "authenticate"

    def test_code_search_none_metadata_excluded_by_file_glob(self, monkeypatch):
        """None-metadata hit is excluded when file_glob filter is active."""
        store = _FakeNoneMetaStore(
            documents=[None, "func handleRequest()"],
            metadatas=[
                None,
                {
                    "wing": "backend",
                    "room": "api",
                    "source_file": "/src/handler.go",
                    "symbol_name": "handleRequest",
                    "symbol_type": "function",
                },
            ],
            distances=[0.05, 0.12],
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: store)

        result = code_search("/fake/palace", "handler", file_glob="*.go")

        assert "error" not in result
        assert len(result["results"]) == 1
        assert result["results"][0]["source_file"] == "/src/handler.go"

    def test_search_cli_tolerates_none_metadata_and_document(self, tmp_path, monkeypatch, capsys):
        """CLI search() does not crash when metadata or document is None and prints fallback values."""
        store = _FakeNoneMetaStore(
            documents=[None],
            metadatas=[None],
            distances=[0.3],
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: store)
        palace = tmp_path / "palace"
        palace.mkdir()

        search("query", str(palace))

        captured = capsys.readouterr()
        assert "[1] ? / ?" in captured.out
        assert "Source: ?" in captured.out
        assert "Match:  0.7" in captured.out

    def test_search_cli_full_source_file_path(self, tmp_path, monkeypatch, capsys):
        """CLI search() prints the full stored source_file path, not just the basename (AC-1)."""
        store = _FakeNoneMetaStore(
            documents=["def authenticate(): return current_user"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/private/var/tmp/project/auth.py",
                }
            ],
            distances=[0.125],
        )
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: store)
        palace = tmp_path / "palace"
        palace.mkdir()

        search("credential lookup", str(palace))

        captured = capsys.readouterr()
        assert "Source: /private/var/tmp/project/auth.py" in captured.out, (
            f"Expected full stored path in Source: line, got:\n{captured.out}"
        )
        assert "Source: auth.py" not in captured.out, "Source: line must not trim to basename only"

    def test_search_cli_missing_palace_uses_stderr_next_action(self, capsys):
        """CLI search() failures should not pollute stdout and should give the next step."""
        with pytest.raises(SearchError):
            search("anything", "/nonexistent/path")

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "No palace found" in captured.err
        assert "Next:" in captured.err
        assert "mempalace-code init <dir>" in captured.err

    def test_search_cli_store_error_uses_stderr_next_action(self, tmp_path, monkeypatch, capsys):
        """CLI search() runtime failures should tell the user how to recover."""

        class FailingStore:
            def query(self, **_kwargs):
                raise RuntimeError("broken index")

        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: FailingStore())
        palace = tmp_path / "palace"
        palace.mkdir()

        with pytest.raises(SearchError):
            search("anything", str(palace))

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Search error" in captured.err
        assert "Next:" in captured.err
        assert "repair --rollback --dry-run" in captured.err


class TestCodeSearchHybridRerank:
    """AC-5 / AC-6: Hybrid reranking in code_search."""

    class FakeCsprojStore:
        """Fake store that returns README before .csproj in vector order."""

        README_DOC = "# README for Infrastructure layer — overview and architecture"
        CSPROJ_DOC = (
            '<PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer" Version="7.0.0" />'
        )
        README_META = {
            "wing": "dotnet",
            "room": "backend",
            "source_file": "/src/Infrastructure/README.md",
            "language": "markdown",
            "symbol_name": "",
            "symbol_type": "",
            "chunk_index": 0,
            "added_by": "miner",
            "filed_at": "2026-01-01T00:00:00",
        }
        CSPROJ_META = {
            "wing": "dotnet",
            "room": "backend",
            "source_file": "/src/Infrastructure/Infrastructure.csproj",
            "language": "xml",
            "symbol_name": "",
            "symbol_type": "",
            "chunk_index": 0,
            "added_by": "miner",
            "filed_at": "2026-01-01T00:00:00",
        }

        def query(self, **kwargs):
            # README has better vector distance (closer = lower cosine distance)
            return {
                "documents": [[self.README_DOC, self.CSPROJ_DOC]],
                "metadatas": [[self.README_META, self.CSPROJ_META]],
                "distances": [[0.10, 0.35]],
            }

    @pytest.fixture
    def csproj_palace_path(self, monkeypatch):
        store = self.FakeCsprojStore()
        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_args, **_kwargs: store)
        return "/fake/dotnet-palace"

    def test_default_ordering_preserved_without_rerank(self, csproj_palace_path):
        """AC-5: Without rerank, vector order is unchanged — README remains first."""
        result = code_search(
            csproj_palace_path,
            "Microsoft EntityFrameworkCore SqlServer NuGet PackageReference",
            n_results=2,
        )

        assert "error" not in result
        assert len(result["results"]) == 2
        assert result["results"][0]["source_file"].endswith("README.md"), (
            f"Default mode must keep README first (vector order), "
            f"got: {result['results'][0]['source_file']}"
        )

    def test_hybrid_rerank_promotes_csproj_over_readme(self, csproj_palace_path):
        """AC-6: Hybrid reranking promotes .csproj over README for PackageReference query."""
        result = code_search(
            csproj_palace_path,
            "Microsoft EntityFrameworkCore SqlServer NuGet PackageReference",
            n_results=2,
            rerank="hybrid",
        )

        assert "error" not in result
        assert len(result["results"]) == 2
        assert result["results"][0]["source_file"].endswith(".csproj"), (
            f"Hybrid mode must promote .csproj first, got: {result['results'][0]['source_file']}"
        )

    def test_hybrid_rerank_result_count_limited_to_n_results(self, csproj_palace_path):
        """AC-6: Result set is still limited to n_results after hybrid reranking."""
        result = code_search(
            csproj_palace_path,
            "Microsoft EntityFrameworkCore SqlServer NuGet PackageReference",
            n_results=1,
            rerank="hybrid",
        )

        assert "error" not in result
        assert len(result["results"]) == 1

    def test_hybrid_rerank_result_fields_unchanged(self, csproj_palace_path):
        """Hybrid mode returns the same field set as vector mode."""
        default_result = code_search(
            csproj_palace_path,
            "Microsoft EntityFrameworkCore SqlServer NuGet PackageReference",
            n_results=2,
        )
        hybrid_result = code_search(
            csproj_palace_path,
            "Microsoft EntityFrameworkCore SqlServer NuGet PackageReference",
            n_results=2,
            rerank="hybrid",
        )

        default_keys = set(default_result["results"][0].keys())
        hybrid_keys = set(hybrid_result["results"][0].keys())
        assert default_keys == hybrid_keys, (
            "Hybrid mode must return the same field set as vector mode"
        )

    def test_invalid_rerank_mode_returns_error_without_querying_store(self, csproj_palace_path):
        """Invalid rerank mode returns an error without opening the store."""
        result = code_search(csproj_palace_path, "any query", rerank="bad_mode")
        assert "error" in result
        assert "bad_mode" in result["error"]
        assert "valid_rerank_modes" in result

    def test_filters_dict_shape_unchanged_with_hybrid_rerank(self, csproj_palace_path):
        """Hybrid rerank does not alter the filters key shape (AC-5 regression guard)."""
        result = code_search(
            csproj_palace_path,
            "query",
            n_results=1,
            rerank="hybrid",
        )
        assert set(result["filters"].keys()) == {
            "language",
            "symbol_name",
            "symbol_type",
            "file_glob",
            "wing",
        }


class TestLuaLanguageSupport:
    """AC-4/AC-5/AC-6: Lua language and local_function symbol type pass code_search validation."""

    @pytest.fixture
    def lua_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["lua_spawnEnemy"],
            documents=[
                "-- Spawns an enemy at position x, y.\n"
                "function spawn_enemy(x, y, difficulty)\n"
                "  local e = { x = x, y = y, hp = difficulty * 10 }\n"
                "  return e\n"
                "end\n"
            ],
            metadatas=[
                {
                    "wing": "mygame",
                    "room": "backend",
                    "source_file": "enemy.lua",
                    "language": "lua",
                    "symbol_name": "spawn_enemy",
                    "symbol_type": "function",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_lua_language(self, lua_palace_path):
        """AC-4: code_search(language='lua') does not return an 'unsupported language' error."""
        result = code_search(lua_palace_path, "spawn enemy", language="lua")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_code_search_lua_language_filter_in_result(self, lua_palace_path):
        """AC-4: code_search with language='lua' exposes filters.language='lua'."""
        result = code_search(lua_palace_path, "enemy", language="lua")
        assert result.get("filters", {}).get("language") == "lua"

    def test_lua_in_supported_languages_hint(self, lua_palace_path):
        """AC-5: 'lua' appears in supported_languages on an invalid language query."""
        result = code_search(lua_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "lua" in result["supported_languages"], "'lua' missing from supported_languages hint"

    def test_code_search_local_function_symbol_type(self, lua_palace_path):
        """AC-6: code_search(symbol_type='local_function') does not return an error."""
        result = code_search(lua_palace_path, "something", symbol_type="local_function")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'local_function' should be valid, got: {result.get('error')}"
        )

    def test_local_function_in_valid_symbol_types_hint(self, lua_palace_path):
        """AC-6: 'local_function' appears in valid_symbol_types on an invalid symbol_type query."""
        result = code_search(lua_palace_path, "something", symbol_type="notarealtype")
        assert "valid_symbol_types" in result
        assert "local_function" in result["valid_symbol_types"], (
            "'local_function' missing from valid_symbol_types hint"
        )


class TestHelmLanguageSupport:
    """AC-5: helm language and helm_chart/helm_values symbol filters pass code_search validation."""

    @pytest.fixture
    def helm_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["helm_chart_mychart"],
            documents=[
                "apiVersion: v2\nname: my-chart\ndescription: A test chart\nversion: 0.1.0\n"
            ],
            metadatas=[
                {
                    "wing": "infra",
                    "room": "general",
                    "source_file": "/charts/my-chart/Chart.yaml",
                    "language": "helm",
                    "symbol_name": "HelmChart/my-chart",
                    "symbol_type": "helm_chart",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_helm_language(self, helm_palace_path):
        """code_search(language='helm') does not return an 'unsupported language' error."""
        result = code_search(helm_palace_path, "chart", language="helm")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) > 0

    def test_code_search_helm_chart_symbol_type(self, helm_palace_path):
        """code_search(symbol_type='helm_chart') does not return 'invalid symbol_type' error."""
        result = code_search(helm_palace_path, "chart", symbol_type="helm_chart")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_code_search_helm_values_symbol_type(self, helm_palace_path):
        """code_search(symbol_type='helm_values') does not return 'invalid symbol_type' error."""
        result = code_search(helm_palace_path, "values", symbol_type="helm_values")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'helm_values' should be valid, got: {result.get('error')}"
        )

    def test_helm_in_supported_languages_hint(self, helm_palace_path):
        """'helm' appears in the supported_languages hint on an invalid language query."""
        result = code_search(helm_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "helm" in result["supported_languages"], (
            "'helm' missing from supported_languages hint"
        )

    def test_helm_symbol_types_in_valid_hint(self, helm_palace_path):
        """helm_chart and helm_values appear in valid_symbol_types hint on an invalid type query."""
        result = code_search(helm_palace_path, "something", symbol_type="notarealtype")
        assert "valid_symbol_types" in result
        for sym in ("helm_chart", "helm_values"):
            assert sym in result["valid_symbol_types"], (
                f"Symbol type {sym!r} missing from valid_symbol_types hint"
            )


class TestAnsibleLanguageSupport:
    """AC-6: ansible language and Ansible-specific symbol filters pass code_search validation."""

    @pytest.fixture
    def ansible_palace_path(self, tmp_path):
        palace_dir = str(tmp_path / "palace")
        store = open_store(palace_dir, create=True)
        store.add(
            ids=["ansible_play_deploy"],
            documents=[
                "- name: Deploy web application\n  hosts: webservers\n  tasks:\n    - name: Install nginx\n      apt:\n        name: nginx\n        state: present\n"
            ],
            metadatas=[
                {
                    "wing": "infra",
                    "room": "general",
                    "source_file": "site.yml",
                    "language": "ansible",
                    "symbol_name": "Deploy web application hosts=webservers",
                    "symbol_type": "ansible_play",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_dir

    def test_code_search_ansible_language(self, ansible_palace_path):
        """code_search(language='ansible') does not return an 'unsupported language' error."""
        result = code_search(ansible_palace_path, "nginx deployment", language="ansible")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) > 0

    def test_code_search_ansible_play_symbol_type(self, ansible_palace_path):
        """code_search(symbol_type='ansible_play') does not return 'invalid symbol_type' error."""
        result = code_search(ansible_palace_path, "deploy", symbol_type="ansible_play")
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        assert "results" in result

    def test_code_search_ansible_task_symbol_type(self, ansible_palace_path):
        """code_search(symbol_type='ansible_task') does not return 'invalid symbol_type' error."""
        result = code_search(ansible_palace_path, "nginx", symbol_type="ansible_task")
        assert "invalid symbol_type" not in result.get("error", "").lower(), (
            f"symbol_type 'ansible_task' should be valid, got: {result.get('error')}"
        )

    def test_code_search_ansible_handler_symbol_type(self, ansible_palace_path):
        """code_search(symbol_type='ansible_handler') passes validation."""
        result = code_search(ansible_palace_path, "restart", symbol_type="ansible_handler")
        assert "invalid symbol_type" not in result.get("error", "").lower()

    def test_code_search_ansible_vars_symbol_type(self, ansible_palace_path):
        """code_search(symbol_type='ansible_vars') passes validation."""
        result = code_search(ansible_palace_path, "vars", symbol_type="ansible_vars")
        assert "invalid symbol_type" not in result.get("error", "").lower()

    def test_code_search_ansible_inventory_symbol_type(self, ansible_palace_path):
        """code_search(symbol_type='ansible_inventory') passes validation."""
        result = code_search(ansible_palace_path, "inventory", symbol_type="ansible_inventory")
        assert "invalid symbol_type" not in result.get("error", "").lower()

    def test_ansible_in_supported_languages_hint(self, ansible_palace_path):
        """'ansible' appears in the supported_languages hint on an invalid language query."""
        result = code_search(ansible_palace_path, "something", language="notareallangnnn")
        assert "supported_languages" in result
        assert "ansible" in result["supported_languages"], (
            "'ansible' missing from supported_languages hint"
        )

    def test_ansible_symbol_types_in_valid_hint(self, ansible_palace_path):
        """Ansible symbol types appear in valid_symbol_types hint on an invalid type query."""
        result = code_search(ansible_palace_path, "something", symbol_type="notarealtype")
        assert "valid_symbol_types" in result
        for sym in (
            "ansible_play",
            "ansible_task",
            "ansible_handler",
            "ansible_vars",
            "ansible_inventory",
        ):
            assert sym in result["valid_symbol_types"], (
                f"Symbol type {sym!r} missing from valid_symbol_types hint"
            )


# ─── Line range tests ─────────────────────────────────────────────────────────


class TestLineRange:
    """line_range: search_memories and code_search expose real line_range for new rows."""

    @pytest.fixture
    def line_range_collection(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["lr_func", "lr_legacy"],
            documents=[
                "def authenticate(user): validate credentials and return session",
                "class LegacyHandler: old code without line metadata",
            ],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "language": "python",
                    "symbol_name": "authenticate",
                    "symbol_type": "function",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 10,
                    "line_end": 15,
                },
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/legacy.py",
                    "language": "python",
                    "symbol_name": "LegacyHandler",
                    "symbol_type": "class",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-02T00:00:00",
                    # line_start/line_end intentionally absent (legacy row)
                },
            ],
        )
        return store

    def test_code_search_line_range_populated_for_new_row(self, palace_path, line_range_collection):
        """line_range: code_search returns {start, end} when line_start/line_end are positive."""
        result = code_search(palace_path, "authenticate credentials")
        assert "results" in result
        auth_hits = [r for r in result["results"] if r["source_file"] == "/project/src/auth.py"]
        assert auth_hits, "Expected a hit for auth.py"
        hit = auth_hits[0]
        assert hit["line_range"] is not None, "Expected non-null line_range for new row"
        assert hit["line_range"]["start"] == 10
        assert hit["line_range"]["end"] == 15

    def test_code_search_line_range_null_for_legacy_row(self, palace_path, line_range_collection):
        """line_range: code_search returns None for rows without line metadata (AC-6)."""
        result = code_search(palace_path, "legacy handler old code")
        legacy_hits = [r for r in result["results"] if r["source_file"] == "/project/src/legacy.py"]
        assert legacy_hits, "Expected a hit for legacy.py"
        assert legacy_hits[0]["line_range"] is None, "Legacy row must have null line_range"

    def test_search_memories_line_range_populated(self, palace_path, line_range_collection):
        """line_range: search_memories returns {start, end} for rows with line metadata."""
        result = search_memories("authenticate credentials", palace_path)
        auth_hits = [r for r in result["results"] if r["source_file"] == "/project/src/auth.py"]
        assert auth_hits
        assert auth_hits[0]["line_range"] == {"start": 10, "end": 15}

    def test_search_memories_line_range_null_legacy(self, palace_path, line_range_collection):
        """line_range: search_memories returns None for legacy rows (AC-6)."""
        result = search_memories("legacy handler", palace_path)
        legacy_hits = [r for r in result["results"] if r["source_file"] == "/project/src/legacy.py"]
        assert legacy_hits
        assert legacy_hits[0]["line_range"] is None

    def test_code_search_tolerates_none_document_and_metadata(self, monkeypatch):
        """line_range: code_search handles None document and metadata without crashing (AC-6)."""

        class NullStore:
            def query(self, **_kwargs):
                return {
                    "documents": [[None]],
                    "metadatas": [[None]],
                    "distances": [[0.1]],
                }

        monkeypatch.setattr("mempalace_code.searcher.open_store", lambda *_a, **_kw: NullStore())
        result = code_search("/fake/palace", "test query")
        assert "results" in result
        assert result["results"][0]["line_range"] is None
        assert result["results"][0]["source_file"] == ""
