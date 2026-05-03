"""Unit tests for the deterministic retrieval reranker."""

from mempalace_code.retrieval_rerank import (
    has_project_file_intent,
    has_symbol_intent,
    overfetch_limit,
    rerank,
    should_overfetch,
)

# =============================================================================
# Intent detection
# =============================================================================


def test_project_intent_single_token():
    assert has_project_file_intent("Microsoft EntityFrameworkCore SqlServer NuGet PackageReference")


def test_project_intent_bigram_package_reference():
    assert has_project_file_intent("MediatR package reference application layer service dependency")


def test_project_intent_bigram_project_reference():
    assert has_project_file_intent(
        "project reference Infrastructure depends on Application ProjectReference"
    )


def test_project_intent_bigram_target_framework():
    assert has_project_file_intent("target framework net7 web sdk application configuration")


def test_project_intent_camelcase_token():
    assert has_project_file_intent("Domain class library TargetFramework no external dependencies")


def test_project_intent_sdk_token():
    assert has_project_file_intent("sdk web project configuration")


def test_project_intent_not_triggered_for_plain_prose():
    assert not has_project_file_intent("TodoItem domain entity title description is done priority")


def test_symbol_intent_detects_camelcase():
    assert has_symbol_intent("TodoItem domain entity title description")


def test_symbol_intent_detects_interface():
    assert has_symbol_intent("IApplicationDbContext interface Entity Framework DbSet")


def test_symbol_intent_not_triggered_for_plain_words():
    assert not has_symbol_intent("target framework web sdk application configuration")


def test_should_overfetch_project_query():
    assert should_overfetch("NuGet PackageReference EntityFrameworkCore")


def test_should_overfetch_symbol_query():
    assert should_overfetch("CreateTodoItemCommand handler application layer")


def test_should_not_overfetch_plain_prose():
    assert not should_overfetch("how does the application work")


# =============================================================================
# Non-intent queries — original vector order preserved
# =============================================================================


def test_non_intent_preserves_vector_order():
    """A query without code-symbol or project-file intent returns candidates in original order."""
    candidates = [
        {"id": "a", "_distance": 0.1, "source_file": "Foo.cs", "symbol_name": ""},
        {"id": "b", "_distance": 0.2, "source_file": "Bar.cs", "symbol_name": ""},
        {"id": "c", "_distance": 0.3, "source_file": "Baz.cs", "symbol_name": ""},
    ]
    result = rerank(candidates, "how does the application work", n_results=3)
    assert [r["id"] for r in result] == ["a", "b", "c"]


def test_non_intent_respects_n_results_truncation():
    candidates = [
        {"id": str(i), "_distance": float(i) * 0.1, "source_file": "x.cs", "symbol_name": ""}
        for i in range(10)
    ]
    result = rerank(candidates, "what does this do", n_results=5)
    assert len(result) == 5
    assert result[0]["id"] == "0"


# =============================================================================
# Project-file promotion
# =============================================================================


def _make_row(id_, distance, source_file, symbol_name=""):
    return {
        "id": id_,
        "_distance": distance,
        "source_file": source_file,
        "symbol_name": symbol_name,
    }


def test_project_file_promoted_to_top():
    """A .csproj file ranked behind prose files is promoted to #1 for a project-intent query."""
    candidates = [
        _make_row("readme", 0.30, "README.md"),
        _make_row("generated", 0.32, "Generated/ApiClient.cs"),
        _make_row("service", 0.34, "Services/TodoService.cs"),
        _make_row("csproj", 0.80, "Infrastructure/Infrastructure.csproj"),
    ]
    query = "project reference Infrastructure depends on Application ProjectReference"
    result = rerank(candidates, query, n_results=3)
    assert result[0]["id"] == "csproj", f"Expected csproj first, got: {[r['id'] for r in result]}"


def test_project_file_stem_match_bonus_adds_extra_promotion():
    """A .csproj whose stem matches a query token ranks above a .csproj with no stem match."""
    candidates = [
        _make_row("domain_csproj", 0.75, "Domain/Domain.csproj"),
        _make_row("infra_csproj", 0.80, "Infrastructure/Infrastructure.csproj"),
        _make_row("prose", 0.25, "README.md"),
    ]
    # "Infrastructure" appears in query → infrastructure.csproj gets extra bonus
    query = "Infrastructure project reference depends on Application ProjectReference"
    result = rerank(candidates, query, n_results=3)
    assert result[0]["id"] == "infra_csproj"


def test_non_project_files_not_promoted_for_project_query():
    """Non-project files do not get the project-file bonus."""
    candidates = [
        _make_row("cs_file", 0.20, "Services/TodoService.cs"),
        _make_row("csproj", 0.80, "Domain/Domain.csproj"),
    ]
    query = "Domain class library TargetFramework no external dependencies"
    result = rerank(candidates, query, n_results=2)
    # csproj gets bonus: 0.80 - 0.50 = 0.30 < 0.20 → csproj promoted ahead
    assert result[0]["id"] == "csproj"


# =============================================================================
# Symbol promotion
# =============================================================================


def test_symbol_name_match_promotes_result():
    """A result whose symbol_name matches a query identifier is promoted."""
    candidates = [
        _make_row("other", 0.20, "Other.cs", symbol_name="OtherClass"),
        _make_row("target", 0.40, "TodoItem.cs", symbol_name="TodoItem"),
    ]
    query = "TodoItem domain entity title description"
    result = rerank(candidates, query, n_results=2)
    assert result[0]["id"] == "target"


def test_source_stem_match_promotes_result():
    """A result whose source file stem matches a query identifier is promoted."""
    candidates = [
        _make_row("other", 0.15, "Unrelated.cs", symbol_name=""),
        _make_row("target", 0.35, "IDateTime.cs", symbol_name=""),
    ]
    # "IDateTime" is CamelCase → triggers symbol intent; stem "idatetime" matches token "IDateTime"
    query = "IDateTime interface abstract system clock current date time"
    result = rerank(candidates, query, n_results=2)
    assert result[0]["id"] == "target"


# =============================================================================
# Edge cases
# =============================================================================


def test_rerank_empty_candidates():
    assert rerank([], "NuGet PackageReference", n_results=5) == []


def test_rerank_fewer_candidates_than_n_results():
    candidates = [_make_row("a", 0.5, "App.csproj")]
    result = rerank(candidates, "MediatR package reference application layer", n_results=10)
    assert len(result) == 1
    assert result[0]["id"] == "a"


def test_stable_tie_breaking_by_original_rank():
    """Two .csproj files with the same distance break ties by original vector rank."""
    candidates = [
        _make_row("first_csproj", 0.5, "App/App.csproj"),
        _make_row("second_csproj", 0.5, "Web/Web.csproj"),
        _make_row("prose", 0.3, "README.md"),
    ]
    query = "NuGet PackageReference EntityFrameworkCore"
    result = rerank(candidates, query, n_results=3)
    # Both .csproj files tie on bonus-adjusted distance; original order must be preserved
    csproj_results = [r["id"] for r in result if "csproj" in r["id"]]
    assert csproj_results == ["first_csproj", "second_csproj"]


# =============================================================================
# Overfetch limit
# =============================================================================


def test_overfetch_limit_small_n_results_uses_floor():
    """For tiny n_results the overfetch floor (50) takes effect."""
    assert overfetch_limit(1) == 50
    assert overfetch_limit(3) == 50


def test_overfetch_limit_typical_n_results_uses_multiplier():
    """For typical n_results the multiplier path applies until the cap."""
    # n_results=5 → 5*15=75
    assert overfetch_limit(5) == 75


def test_overfetch_limit_capped_at_max():
    """For larger n_results the cap (150) is applied — but never below n_results."""
    # n_results=20 → 20*15=300 → capped to 150
    assert overfetch_limit(20) == 150


def test_overfetch_limit_never_below_n_results():
    """Regression: if a caller asks for more than the rerank cap, fetch_limit must keep up."""
    # n_results=200 must not be silently downgraded to the 150 cap
    assert overfetch_limit(200) == 200
    assert overfetch_limit(151) == 151


def test_missing_distance_field_treated_as_zero():
    """Rows without _distance should not raise and be ranked using distance 0.0."""
    candidates = [
        {"id": "no_dist", "source_file": "App.csproj", "symbol_name": ""},
        {"id": "has_dist", "_distance": 0.5, "source_file": "Other.cs", "symbol_name": ""},
    ]
    result = rerank(candidates, "NuGet PackageReference", n_results=2)
    assert len(result) == 2
    # no_dist is a .csproj with implicit distance 0.0 → score 0.0 - 0.50 = -0.50
    # has_dist is non-project with distance 0.5 → score 0.5 (no bonus)
    # The .csproj row must rank first.
    assert [r["id"] for r in result] == ["no_dist", "has_dist"]
