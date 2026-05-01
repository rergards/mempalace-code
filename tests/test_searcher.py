"""
test_searcher.py — Tests for the programmatic search_memories API.

Tests the library-facing search interface (not the CLI print variant).
"""

import pytest

from mempalace_code.language_catalog import sorted_searchable_languages
from mempalace_code.searcher import code_search, search_memories
from mempalace_code.storage import open_store


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
