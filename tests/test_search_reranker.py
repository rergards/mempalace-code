"""
test_search_reranker.py — Unit tests for the hybrid BM25-style reranker.

Covers: exact-token boosts, project-file metadata boosts, None document safety,
stable vector-order tie handling, and edge cases.
"""

from mempalace_code.search_reranker import _tokenize, hybrid_rerank


class TestTokenize:
    def test_camel_case_split(self):
        tokens = _tokenize("PackageReference")
        assert "package" in tokens
        assert "reference" in tokens

    def test_pascal_case_split(self):
        tokens = _tokenize("EntityFrameworkCore")
        assert "entity" in tokens
        assert "framework" in tokens
        assert "core" in tokens

    def test_extension_dot_split(self):
        tokens = _tokenize("Infrastructure.csproj")
        assert "infrastructure" in tokens
        assert "csproj" in tokens

    def test_path_separator_split(self):
        tokens = _tokenize("src/Application/Application.csproj")
        assert "src" in tokens
        assert "application" in tokens
        assert "csproj" in tokens

    def test_lowercase_output(self):
        tokens = _tokenize("MyClass")
        assert all(t == t.lower() for t in tokens)

    def test_empty_string_returns_empty_list(self):
        assert _tokenize("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert _tokenize("   ") == []

    def test_nuget_split(self):
        # "NuGet" has u→G camelCase boundary → exactly ["nu", "get"]
        assert _tokenize("NuGet") == ["nu", "get"]

    def test_project_reference_split(self):
        tokens = _tokenize("ProjectReference")
        assert "project" in tokens
        assert "reference" in tokens

    def test_uppercase_acronym_handled(self):
        # "SQLServer" → SQL + Server (UPPER→Upper boundary "L→Se")
        assert _tokenize("SQLServer") == ["sql", "server"]


class TestHybridRerank:
    def test_empty_candidates_returns_empty(self):
        assert hybrid_rerank("any query", []) == []

    def test_single_candidate_returned_unchanged(self):
        candidates = [{"text": "only one", "source_file": "a.cs"}]
        result = hybrid_rerank("query", candidates)
        assert len(result) == 1
        assert result[0]["source_file"] == "a.cs"

    def test_all_candidates_preserved(self):
        """Reranking never drops candidates."""
        candidates = [{"text": f"text {i}", "source_file": f"file{i}.cs"} for i in range(10)]
        result = hybrid_rerank("some query", candidates)
        assert len(result) == 10

    def test_tie_preserves_vector_order(self):
        """AC-4: When all candidates have identical lexical score, original order is preserved."""
        candidates = [
            {"text": "identical text", "source_file": "first.cs"},
            {"text": "identical text", "source_file": "second.cs"},
            {"text": "identical text", "source_file": "third.cs"},
        ]
        # Query has no token overlap with "identical text" so lex=0 for all
        result = hybrid_rerank("unique_z_query_no_token_overlap", candidates)
        assert [c["source_file"] for c in result] == ["first.cs", "second.cs", "third.cs"]

    def test_exact_token_boost_promotes_candidate(self):
        """Candidate with exact query tokens in document text is promoted."""
        candidates = [
            {"text": "generic content with no relevant terms", "source_file": "generic.cs"},
            {
                "text": "ProjectReference Application Domain specific content",
                "source_file": "Infrastructure.csproj",
            },
        ]
        query = "ProjectReference Application Domain"
        result = hybrid_rerank(query, candidates)
        assert result[0]["source_file"] == "Infrastructure.csproj", (
            f"Candidate with exact query tokens should be promoted, got: {result[0]['source_file']}"
        )

    def test_csproj_promoted_over_readme_for_package_reference_query(self):
        """AC-2: Hybrid reranking promotes .csproj over README for PackageReference query.

        The fixture places README first (vector rank 0) and csproj second (rank 1)
        to replicate the known failure mode. Hybrid reranking must flip the order
        based on token overlap without hard-coding the expected filename.
        """
        candidates = [
            {
                "text": "# README for Infrastructure layer — overview of services",
                "source_file": "src/Infrastructure/README.md",
                "symbol_type": "",
                "symbol_name": "",
                "language": "markdown",
                "room": "backend",
                "wing": "dotnet",
            },
            {
                "text": (
                    '<PackageReference Include="Microsoft.EntityFrameworkCore.SqlServer"'
                    ' Version="7.0.0" />'
                ),
                "source_file": "src/Infrastructure/Infrastructure.csproj",
                "symbol_type": "project_file",
                "symbol_name": "",
                "language": "xml",
                "room": "backend",
                "wing": "dotnet",
            },
        ]
        query = "Microsoft EntityFrameworkCore SqlServer NuGet PackageReference"
        result = hybrid_rerank(query, candidates)

        assert result[0]["source_file"].endswith(".csproj"), (
            f"Expected .csproj first for PackageReference query, got: {result[0]['source_file']}"
        )

    def test_source_file_tokens_contribute_to_lexical_score(self):
        """source_file path tokens are included in the lexical surface."""
        candidates = [
            {"text": "generic content", "source_file": "src/some/other.cs"},
            {"text": "generic content", "source_file": "src/Infrastructure/Infrastructure.csproj"},
        ]
        # Query tokens match source_file tokens of csproj but not other.cs
        query = "Infrastructure csproj project"
        result = hybrid_rerank(query, candidates)
        assert result[0]["source_file"].endswith(".csproj"), (
            "source_file path tokens should boost the csproj candidate"
        )

    def test_symbol_name_tokens_contribute_to_lexical_score(self):
        """symbol_name tokens are included in the lexical surface."""
        candidates = [
            {
                "text": "generic code",
                "source_file": "a.cs",
                "symbol_name": "GenericHelperUtil",
            },
            {
                "text": "generic code",
                "source_file": "b.cs",
                "symbol_name": "PackageReference",
            },
        ]
        result = hybrid_rerank("PackageReference lookup", candidates)
        assert result[0]["symbol_name"] == "PackageReference", (
            "symbol_name tokens should contribute to lexical boost"
        )

    def test_none_document_does_not_raise(self):
        """AC-3: None document value is handled without raising."""
        candidates = [
            {"text": None, "source_file": "a.cs", "symbol_name": "Foo"},
            {"text": "valid PackageReference content", "source_file": "b.csproj"},
        ]
        result = hybrid_rerank("PackageReference", candidates)
        assert len(result) == 2
        sources = {c["source_file"] for c in result}
        assert "a.cs" in sources
        assert "b.csproj" in sources

    def test_none_source_file_does_not_raise(self):
        """AC-3: None source_file is handled without raising."""
        candidates = [
            {"text": "some text", "source_file": None},
            {"text": "PackageReference content", "source_file": "b.csproj"},
        ]
        result = hybrid_rerank("PackageReference", candidates)
        assert len(result) == 2

    def test_missing_all_metadata_does_not_raise(self):
        """AC-3: Candidate with only 'text' key (no metadata) does not raise."""
        candidates = [
            {"text": "bare content"},
            {"text": "PackageReference content", "source_file": "app.csproj"},
        ]
        result = hybrid_rerank("PackageReference", candidates)
        assert len(result) == 2

    def test_none_all_fields_does_not_raise(self):
        """AC-3: Candidate where every field is None does not raise."""
        candidates = [
            {"text": None, "source_file": None, "symbol_name": None, "language": None},
        ]
        result = hybrid_rerank("any query", candidates)
        assert len(result) == 1

    def test_all_candidates_have_identical_hybrid_score_preserves_order(self):
        """AC-4: When hybrid scores are equal (no lexical evidence), vector order is kept."""
        # All candidates have same text, no query token overlap → pure vector order
        candidates = [
            {"text": "zzz", "source_file": "rank0.cs"},
            {"text": "zzz", "source_file": "rank1.cs"},
            {"text": "zzz", "source_file": "rank2.cs"},
            {"text": "zzz", "source_file": "rank3.cs"},
        ]
        result = hybrid_rerank("aaa_unique_no_overlap", candidates)
        assert [c["source_file"] for c in result] == [
            "rank0.cs",
            "rank1.cs",
            "rank2.cs",
            "rank3.cs",
        ]

    def test_lexical_weight_zero_returns_original_order(self):
        """lexical_weight=0 produces pure vector ordering regardless of token overlap."""
        # Even if a later-ranked candidate has full token overlap, vec ordering wins.
        candidates = [
            {"text": "no overlap", "source_file": "rank0.cs"},
            {"text": "query term match", "source_file": "rank1.cs"},
            {"text": "query term match", "source_file": "rank2.cs"},
        ]
        result = hybrid_rerank("query term match", candidates, lexical_weight=0.0)
        assert [c["source_file"] for c in result] == ["rank0.cs", "rank1.cs", "rank2.cs"]

    def test_lexical_weight_one_ranks_by_overlap_only(self):
        """lexical_weight=1 produces pure lexical ordering; vector rank is tie-breaker."""
        candidates = [
            {"text": "no overlap content here", "source_file": "rank0.cs"},
            {"text": "full overlap query tokens", "source_file": "rank1.cs"},
        ]
        result = hybrid_rerank("query tokens", candidates, lexical_weight=1.0)
        assert result[0]["source_file"] == "rank1.cs", (
            "With lexical_weight=1, the candidate with full token overlap should rank first"
        )

    def test_project_reference_query_promotes_csproj(self):
        """ProjectReference query promotes .csproj over a .cs file at rank 0.

        The fixture uses a .cs file whose tokens have zero overlap with the
        query so the csproj's strong lexical match overcomes its lower vector rank.
        """
        candidates = [
            {
                # No query tokens ("project", "reference", "infrastructure",
                # "depends", "application") appear in this text or its path.
                "text": "public class OrderService : IOrderService { }",
                "source_file": "src/Domain/Services/OrderService.cs",
                "language": "csharp",
            },
            {
                "text": (
                    '<ProjectReference Include="../Application/Application.csproj" />'
                    "<TargetFramework>net7.0</TargetFramework>"
                ),
                "source_file": "src/Infrastructure/Infrastructure.csproj",
                "language": "xml",
            },
        ]
        query = "project reference Infrastructure depends on Application ProjectReference"
        result = hybrid_rerank(query, candidates)
        assert result[0]["source_file"].endswith(".csproj"), (
            f"ProjectReference query should promote .csproj, got: {result[0]['source_file']}"
        )
