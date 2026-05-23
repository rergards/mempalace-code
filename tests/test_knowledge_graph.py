"""
test_knowledge_graph.py — Tests for the temporal knowledge graph.

Covers: entity CRUD, triple CRUD, temporal queries, invalidation,
timeline, stats, edge cases (duplicate triples, ID collisions), and
temporal validation (ISO date/datetime acceptance, natural-language
rejection, inverted-window rejection, inclusive boundaries).
"""

import pytest


class TestEntityOperations:
    def test_add_entity(self, kg):
        eid = kg.add_entity("Alice", entity_type="person")
        assert eid == "alice"

    def test_add_entity_normalizes_id(self, kg):
        eid = kg.add_entity("Dr. Chen", entity_type="person")
        assert eid == "dr._chen"

    def test_add_entity_upsert(self, kg):
        kg.add_entity("Alice", entity_type="person")
        kg.add_entity("Alice", entity_type="engineer")
        # Should not raise — INSERT OR REPLACE
        stats = kg.stats()
        assert stats["entities"] == 1


class TestTripleOperations:
    def test_add_triple_creates_entities(self, kg):
        tid = kg.add_triple("Alice", "knows", "Bob")
        assert tid.startswith("t_alice_knows_bob_")
        stats = kg.stats()
        assert stats["entities"] == 2  # auto-created

    def test_add_triple_with_dates(self, kg):
        tid = kg.add_triple("Max", "does", "swimming", valid_from="2025-01-01")
        assert tid.startswith("t_max_does_swimming_")

    def test_duplicate_triple_returns_existing_id(self, kg):
        tid1 = kg.add_triple("Alice", "knows", "Bob")
        tid2 = kg.add_triple("Alice", "knows", "Bob")
        assert tid1 == tid2

    def test_invalidated_triple_allows_re_add(self, kg):
        tid1 = kg.add_triple("Alice", "works_at", "Acme")
        kg.invalidate("Alice", "works_at", "Acme", ended="2025-01-01")
        tid2 = kg.add_triple("Alice", "works_at", "Acme")
        assert tid1 != tid2  # new triple since old one was closed


class TestQueries:
    def test_query_outgoing(self, seeded_kg):
        results = seeded_kg.query_entity("Alice", direction="outgoing")
        predicates = {r["predicate"] for r in results}
        assert "parent_of" in predicates
        assert "works_at" in predicates

    def test_query_incoming(self, seeded_kg):
        results = seeded_kg.query_entity("Max", direction="incoming")
        assert any(r["subject"] == "Alice" and r["predicate"] == "parent_of" for r in results)

    def test_query_both_directions(self, seeded_kg):
        results = seeded_kg.query_entity("Max", direction="both")
        directions = {r["direction"] for r in results}
        assert "outgoing" in directions
        assert "incoming" in directions

    def test_query_as_of_filters_expired(self, seeded_kg):
        results = seeded_kg.query_entity("Alice", as_of="2023-06-01", direction="outgoing")
        employers = [r["object"] for r in results if r["predicate"] == "works_at"]
        assert "Acme Corp" in employers
        assert "NewCo" not in employers

    def test_query_as_of_shows_current(self, seeded_kg):
        results = seeded_kg.query_entity("Alice", as_of="2025-06-01", direction="outgoing")
        employers = [r["object"] for r in results if r["predicate"] == "works_at"]
        assert "NewCo" in employers
        assert "Acme Corp" not in employers

    def test_query_relationship(self, seeded_kg):
        results = seeded_kg.query_relationship("does")
        assert len(results) == 2  # swimming + chess


class TestInvalidation:
    def test_invalidate_sets_valid_to(self, seeded_kg):
        seeded_kg.invalidate("Max", "does", "chess", ended="2026-01-01")
        results = seeded_kg.query_entity("Max", direction="outgoing")
        chess = [r for r in results if r["object"] == "chess"]
        assert len(chess) == 1
        assert chess[0]["valid_to"] == "2026-01-01"
        assert chess[0]["current"] is False


class TestTimeline:
    def test_timeline_all(self, seeded_kg):
        tl = seeded_kg.timeline()
        assert len(tl) >= 4

    def test_timeline_entity(self, seeded_kg):
        tl = seeded_kg.timeline("Max")
        subjects_and_objects = {t["subject"] for t in tl} | {t["object"] for t in tl}
        assert "Max" in subjects_and_objects

    def test_timeline_global_has_limit(self, kg):
        # Add > 100 triples
        for i in range(105):
            kg.add_triple(f"entity_{i}", "relates_to", f"entity_{i + 1}")
        tl = kg.timeline()
        assert len(tl) == 100  # LIMIT 100

    def test_timeline_entity_has_limit(self, kg):
        # Add > 100 triples all connected to a single entity
        for i in range(105):
            kg.add_triple(
                "hub", "connects_to", f"spoke_{i}", valid_from=f"2025-01-{(i % 28) + 1:02d}"
            )
        tl = kg.timeline("hub")
        assert len(tl) == 100  # LIMIT 100 on entity-filtered branch


class TestWALMode:
    def test_wal_mode_enabled(self, kg):
        conn = kg._conn()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


class TestStats:
    def test_stats_empty(self, kg):
        stats = kg.stats()
        assert stats["entities"] == 0
        assert stats["triples"] == 0

    def test_stats_seeded(self, seeded_kg):
        stats = seeded_kg.stats()
        assert stats["entities"] >= 4
        assert stats["triples"] == 5
        assert stats["current_facts"] == 4  # 1 expired (Acme Corp)
        assert stats["expired_facts"] == 1


class TestTemporalValidation:
    def test_add_triple_accepts_iso_dates_and_utc_datetimes(self, kg):
        # Plain ISO date
        tid = kg.add_triple("Alice", "knows", "Bob", valid_from="2026-01-01")
        assert tid.startswith("t_")

        # UTC datetime with Z suffix
        tid2 = kg.add_triple("Carol", "works_at", "Corp", valid_from="2026-01-01T09:00:00Z")
        assert tid2.startswith("t_")

        # UTC datetime with +00:00 suffix
        tid3 = kg.add_triple("Dave", "uses", "Python", valid_from="2026-03-15T14:30:00+00:00")
        assert tid3.startswith("t_")

        # Query with ISO date as_of — date-based fact is visible
        results = kg.query_entity("Alice", as_of="2026-01-15")
        assert any(r["predicate"] == "knows" for r in results)

        # Query with UTC datetime as_of — datetime-based fact is visible
        results = kg.query_entity("Carol", as_of="2026-01-01T12:00:00Z")
        assert any(r["predicate"] == "works_at" for r in results)

    def test_add_triple_rejects_natural_language_temporal_inputs_before_write(self, kg):
        before = kg.stats()["triples"]

        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.add_triple("Alice", "knows", "Bob", valid_from="next Monday")

        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.add_triple("Alice", "knows", "Carol", valid_from="yesterday")

        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.add_triple("Alice", "knows", "Dave", valid_to="in 3 weeks")

        # as_of validation on query
        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.query_entity("Alice", as_of="last week")

        # Triple count unchanged — no partial writes
        assert kg.stats()["triples"] == before

    def test_inverted_windows_are_rejected_before_mutation(self, kg):
        # Add a valid triple to test invalidate against
        kg.add_triple("Alice", "works_at", "Corp", valid_from="2026-01-01")
        before = kg.stats()["triples"]

        # Inverted valid_from/valid_to on add_triple
        with pytest.raises(ValueError, match="Inverted validity window"):
            kg.add_triple("Bob", "knows", "Carol", valid_from="2026-06-01", valid_to="2026-01-01")
        assert kg.stats()["triples"] == before

        # Inverted ended on invalidate (ended precedes valid_from)
        with pytest.raises(ValueError, match="Inverted invalidation"):
            kg.invalidate("Alice", "works_at", "Corp", ended="2025-06-01")

        # Original triple remains unmodified
        results = kg.query_entity("Alice", direction="outgoing")
        corp_facts = [r for r in results if r["object"] == "Corp"]
        assert len(corp_facts) == 1
        assert corp_facts[0]["valid_to"] is None

    def test_equal_window_endpoints_remain_valid_and_inclusive(self, kg):
        # valid_from == valid_to is a single-point window — must be stored
        tid = kg.add_triple(
            "Alice",
            "attended",
            "Conference",
            valid_from="2026-05-10",
            valid_to="2026-05-10",
        )
        assert tid.startswith("t_")

        # Visible exactly on the boundary date
        results = kg.query_entity("Alice", as_of="2026-05-10", direction="outgoing")
        conf = [r for r in results if r["object"] == "Conference"]
        assert len(conf) == 1

        # Not visible the day before
        results = kg.query_entity("Alice", as_of="2026-05-09", direction="outgoing")
        conf = [r for r in results if r["object"] == "Conference"]
        assert len(conf) == 0

        # Not visible the day after
        results = kg.query_entity("Alice", as_of="2026-05-11", direction="outgoing")
        conf = [r for r in results if r["object"] == "Conference"]
        assert len(conf) == 0

    def test_date_only_valid_to_inclusive_for_same_day_datetime_as_of(self, kg):
        # A date-only valid_to must remain inclusive for any datetime as_of within
        # the same calendar day (end-of-day semantics).
        kg.add_triple(
            "Alice",
            "attended",
            "Workshop",
            valid_from="2026-05-10",
            valid_to="2026-05-10",
        )

        # Visible at midnight UTC
        r = kg.query_entity("Alice", as_of="2026-05-10T00:00:00Z", direction="outgoing")
        assert any(x["object"] == "Workshop" for x in r)

        # Visible mid-day
        r = kg.query_entity("Alice", as_of="2026-05-10T12:00:00Z", direction="outgoing")
        assert any(x["object"] == "Workshop" for x in r)

        # Visible at 23:59:59Z
        r = kg.query_entity("Alice", as_of="2026-05-10T23:59:59Z", direction="outgoing")
        assert any(x["object"] == "Workshop" for x in r)

        # Not visible at midnight of the next day
        r = kg.query_entity("Alice", as_of="2026-05-11T00:00:00Z", direction="outgoing")
        assert not any(x["object"] == "Workshop" for x in r)

    def test_bulk_invalidation_helpers_reject_invalid_ended(self, kg):
        kg.add_triple("Alice", "works_at", "Corp", valid_from="2026-01-01", source_file="a.py")
        kg.add_triple("Bob", "knows", "Carol", valid_from="2026-01-01")
        before = kg.stats()["triples"]

        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.invalidate_by_source_file("a.py", ended="last month")
        assert kg.stats()["triples"] == before

        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.invalidate_by_predicates(["works_at"], ended="yesterday")
        assert kg.stats()["triples"] == before

        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.invalidate_arch_by_project_root(["works_at"], project_root="/tmp", ended="next week")
        assert kg.stats()["triples"] == before

        with pytest.raises(ValueError, match="Invalid temporal"):
            kg.invalidate_legacy_arch_ns_project_for_wing("__arch__", "mywing", ended="2 days ago")
        assert kg.stats()["triples"] == before
