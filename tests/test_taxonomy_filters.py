"""Tests for mempalace_code.taxonomy_filters — shared taxonomy filter validation contract."""

import pytest

from mempalace_code.storage import LanceStore, open_store
from mempalace_code.taxonomy_filters import (
    TaxonomyValidationError,
    format_cli_lines,
    validate_taxonomy_filters,
    validate_wing_against_store,
    validate_wing_room_against_taxonomy,
)


@pytest.fixture
def seeded_palace(tmp_path):
    """A small palace with two wings, one of them punctuation-sensitive."""
    palace_path = str(tmp_path / "palace")
    store = open_store(palace_path, create=True)
    store.add(
        ids=["d1", "d2", "d3"],
        documents=["alpha content", "beta content", "gamma content"],
        metadatas=[
            {"wing": "migrate-openclaw", "room": "backend"},
            {"wing": "migrate-openclaw", "room": "frontend"},
            {"wing": "other_wing", "room": "notes"},
        ],
    )
    return palace_path


class TestValidateWingRoomAgainstTaxonomy:
    def test_no_filters_returns_none(self):
        assert validate_wing_room_against_taxonomy({"w1": {"r1": 1}}) is None

    def test_valid_wing_room_pair_returns_none(self):
        taxonomy = {"w1": {"r1": 2}}
        assert validate_wing_room_against_taxonomy(taxonomy, wing="w1", room="r1") is None

    def test_taxonomy_filter_validation_unknown_wing(self):
        result = validate_wing_room_against_taxonomy(
            {"unrelated_project": {"r1": 1}}, wing="totally-different-name"
        )
        assert result == {
            "error": "unknown_wing",
            "filter": "wing",
            "value": "totally-different-name",
            "suggestions": [],
        }

    def test_taxonomy_filter_validation_unknown_room_is_global(self):
        taxonomy = {"w1": {"r1": 1}, "w2": {"r2": 1}}
        result = validate_wing_room_against_taxonomy(taxonomy, room="r3")
        assert result is not None
        assert result["error"] == "unknown_room"
        assert result["filter"] == "room"
        assert result["value"] == "r3"

    def test_room_valid_globally_without_wing(self):
        """AC-4: room-only validation succeeds for any existing room, even in another wing."""
        taxonomy = {"w1": {"r1": 1}, "w2": {"r2": 1}}
        assert validate_wing_room_against_taxonomy(taxonomy, room="r2") is None

    def test_taxonomy_filter_validation_unknown_wing_room_pair(self):
        """AC-4: wing-plus-room requires the exact pair even if each half exists elsewhere."""
        taxonomy = {"w1": {"r1": 1}, "w2": {"r2": 1}}
        result = validate_wing_room_against_taxonomy(taxonomy, wing="w1", room="r2")
        assert result is not None
        assert result["error"] == "unknown_wing_room"
        assert result["filter"] == "wing_room"
        assert result["value"] == {"wing": "w1", "room": "r2"}

    def test_unknown_wing_takes_priority_over_room(self):
        """Validation order: unknown wing is reported before room-only/pair checks."""
        taxonomy = {"w1": {"r1": 1}}
        result = validate_wing_room_against_taxonomy(taxonomy, wing="ghost", room="also-ghost")
        assert result is not None
        assert result["error"] == "unknown_wing"
        assert result["value"] == "ghost"

    def test_suggestions_rank_close_match_but_do_not_rewrite(self):
        """AC-5: punctuation/case differ but the requested value is never rewritten."""
        taxonomy = {"migrate-openclaw": {"r1": 1}}
        result = validate_wing_room_against_taxonomy(taxonomy, wing="migrate_openclaw")
        assert result is not None
        assert result["error"] == "unknown_wing"
        assert result["value"] == "migrate_openclaw"
        assert result["suggestions"] == ["migrate-openclaw"]

    def test_suggestions_bounded_to_three(self):
        taxonomy = {f"wing_{i}": {"r": 1} for i in range(10)}
        result = validate_wing_room_against_taxonomy(taxonomy, wing="wing_1x")
        assert result is not None
        assert len(result["suggestions"]) <= 3

    def test_suggestions_empty_when_no_close_match(self):
        taxonomy = {"completely_different": {"r": 1}}
        result = validate_wing_room_against_taxonomy(taxonomy, wing="zzz")
        assert result is not None
        assert result["suggestions"] == []

    def test_empty_string_wing_with_valid_room_treated_as_no_wing_filter(self):
        """Empty-string wing must be filter-absent, matching downstream `if wing` where-clauses."""
        taxonomy = {"w1": {"r1": 1}, "w2": {"r2": 1}}
        assert validate_wing_room_against_taxonomy(taxonomy, wing="", room="r1") is None

    def test_empty_string_room_with_valid_wing_treated_as_no_room_filter(self):
        taxonomy = {"w1": {"r1": 1}}
        assert validate_wing_room_against_taxonomy(taxonomy, wing="w1", room="") is None

    def test_empty_string_wing_and_room_returns_none(self):
        taxonomy = {"w1": {"r1": 1}}
        assert validate_wing_room_against_taxonomy(taxonomy, wing="", room="") is None

    def test_empty_taxonomy_skips_validation_for_wing(self):
        """A palace with no wings at all has nothing to validate a filter against —
        this must not be reported as unknown_wing, matching the missing-palace carve-out."""
        assert validate_wing_room_against_taxonomy({}, wing="anything") is None

    def test_empty_taxonomy_skips_validation_for_room(self):
        assert validate_wing_room_against_taxonomy({}, room="anything") is None

    def test_empty_taxonomy_skips_validation_for_wing_room_pair(self):
        assert validate_wing_room_against_taxonomy({}, wing="w1", room="r1") is None


class TestValidateTaxonomyFilters:
    def test_no_filters_skips_validation(self, seeded_palace):
        assert validate_taxonomy_filters(seeded_palace) is None

    def test_search_valid_empty_scope_returns_none(self, seeded_palace):
        """A valid wing/room pair with matching taxonomy entries passes validation."""
        assert (
            validate_taxonomy_filters(seeded_palace, wing="migrate-openclaw", room="backend")
            is None
        )

    def test_unknown_taxonomy_wing_returns_structured_error(self, seeded_palace):
        result = validate_taxonomy_filters(seeded_palace, wing="does-not-exist")
        assert result is not None
        assert result["error"] == "unknown_wing"
        assert result["value"] == "does-not-exist"

    def test_unknown_taxonomy_room_returns_structured_error(self, seeded_palace):
        result = validate_taxonomy_filters(seeded_palace, room="does-not-exist")
        assert result is not None
        assert result["error"] == "unknown_room"

    def test_unknown_taxonomy_wing_room_pair_returns_structured_error(self, seeded_palace):
        result = validate_taxonomy_filters(seeded_palace, wing="migrate-openclaw", room="notes")
        assert result is not None
        assert result["error"] == "unknown_wing_room"

    def test_missing_palace_skips_validation(self, tmp_path):
        """INV-4: no-palace stays distinct — validator defers instead of reporting unknown_wing."""
        missing = str(tmp_path / "does-not-exist")
        assert validate_taxonomy_filters(missing, wing="anything") is None

    def test_initialized_but_empty_palace_skips_validation(self, tmp_path):
        """`mine`/`mine-all` open the store with create=True before mining any files, so a
        project with zero indexable files (or a fresh init before the first mine) leaves an
        on-disk table with 0 rows. That must defer like a missing palace, not reject every
        filter as unknown — the empty table means there is no taxonomy to validate against."""
        palace_path = str(tmp_path / "palace")
        open_store(palace_path, create=True)  # table exists on disk, 0 rows, no wings
        assert validate_taxonomy_filters(palace_path, wing="anything") is None
        assert validate_taxonomy_filters(palace_path, room="anything") is None

    def test_empty_string_wing_with_valid_room_returns_none(self, seeded_palace):
        """Empty-string wing must not be validated as an explicit filter (matches searcher.py's
        truthy where-clause construction, which treats '' the same as unset)."""
        assert validate_taxonomy_filters(seeded_palace, wing="", room="backend") is None

    def test_no_embedder_on_invalid_taxonomy(self, seeded_palace, monkeypatch):
        """AC-6: validation never loads the embedding model."""

        def _no_embedder(self):
            raise RuntimeError("_get_embedder must not be called for taxonomy validation")

        monkeypatch.setattr(LanceStore, "_get_embedder", _no_embedder)
        result = validate_taxonomy_filters(seeded_palace, wing="does-not-exist")
        assert result is not None
        assert result["error"] == "unknown_wing"


class TestValidateWingAgainstStore:
    def test_no_wing_returns_none(self, seeded_palace):
        store = open_store(seeded_palace, create=False, read_only=True)
        assert validate_wing_against_store(store, None) is None

    def test_valid_wing_returns_none(self, seeded_palace):
        store = open_store(seeded_palace, create=False, read_only=True)
        assert validate_wing_against_store(store, "migrate-openclaw") is None

    def test_unknown_wing_returns_error(self, seeded_palace):
        store = open_store(seeded_palace, create=False, read_only=True)
        result = validate_wing_against_store(store, "nope")
        assert result is not None
        assert result["error"] == "unknown_wing"
        assert result["value"] == "nope"


class TestTaxonomyValidationError:
    def test_payload_preserved(self):
        payload = {"error": "unknown_wing", "filter": "wing", "value": "x", "suggestions": []}
        exc = TaxonomyValidationError(payload)
        assert exc.payload == payload
        assert str(exc) == "unknown_wing"


class TestFormatCliLines:
    def test_unknown_wing_message(self):
        lines = format_cli_lines(
            {"error": "unknown_wing", "filter": "wing", "value": "foo", "suggestions": ["bar"]}
        )
        text = "\n".join(lines)
        assert "Unknown wing" in text
        assert "'foo'" in text
        assert "Did you mean: bar" in text
        assert "Next:" in text

    def test_unknown_room_message(self):
        lines = format_cli_lines(
            {"error": "unknown_room", "filter": "room", "value": "foo", "suggestions": []}
        )
        text = "\n".join(lines)
        assert "Unknown room" in text
        assert "Did you mean" not in text

    def test_unknown_wing_room_message(self):
        lines = format_cli_lines(
            {
                "error": "unknown_wing_room",
                "filter": "wing_room",
                "value": {"wing": "w", "room": "r"},
                "suggestions": [],
            }
        )
        text = "\n".join(lines)
        assert "wing='w'" in text
        assert "room='r'" in text
