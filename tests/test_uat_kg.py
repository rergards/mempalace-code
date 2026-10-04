"""
test_uat_kg.py — regressions for the knowledge-graph UAT findings.

Covers selective KG indexes, closed-fact deduplication, honest invalidation reports,
stored display names, paged KG tools, and legacy adoption reporting.
"""

import json
import sqlite3
import warnings

import pytest

import mempalace_code.knowledge_graph as kg_module
from mempalace_code.knowledge_graph import KnowledgeGraph


@pytest.fixture
def kg(tmp_path):
    return KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))


@pytest.fixture
def mcp_kg(monkeypatch, kg):
    from pathlib import Path

    from mempalace_code.mcp import runtime

    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(Path(kg.db_path).parent))
    monkeypatch.setattr(runtime, "_kg", kg)
    return kg


def _plan(db_path, sql: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        return " ".join(row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
    finally:
        conn.close()


def _rows(db_path) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT subject, predicate, object, valid_from, valid_to FROM triples ORDER BY rowid"
        ).fetchall()
    finally:
        conn.close()


# ── kg-1: selective indexes ─────────────────────────────────────────────────


class TestSelectiveIndexes:
    def test_fact_lookups_use_the_spo_and_source_file_indexes(self, kg):
        dedupe = _plan(
            kg.db_path,
            "SELECT id FROM triples WHERE subject='a' AND predicate='b' AND object='c'"
            " AND valid_to IS NULL",
        )
        by_source = _plan(
            kg.db_path,
            "UPDATE triples SET valid_to='x' WHERE source_file='f' AND valid_to IS NULL",
        )

        assert "idx_triples_spo" in dedupe
        assert "idx_triples_predicate" not in dedupe
        assert "idx_triples_source_file" in by_source
        assert "SCAN" not in by_source

    def test_add_and_invalidate_statements_never_scan_by_predicate(self, kg, monkeypatch):
        for i in range(50):
            kg.add_triple(f"Type{i}", "in_project", "proj0", source_file=f"/src/f{i}.py")
        statements: list[str] = []
        open_conn = KnowledgeGraph._conn

        def traced(self):
            conn = open_conn(self)
            conn.set_trace_callback(statements.append)
            return conn

        monkeypatch.setattr(KnowledgeGraph, "_conn", traced)
        kg.add_triple_report("Type1", "in_project", "proj1")
        kg.invalidate("Nope", "in_project", "proj0")
        kg.invalidate("Type2", "in_project", "proj0")
        kg.invalidate_by_source_file("/src/f3.py")
        monkeypatch.undo()

        conn = sqlite3.connect(kg.db_path)
        try:
            for sql in {s for s in statements if s.lstrip().startswith(("SELECT", "UPDATE"))}:
                plan = " ".join(r[3] for r in conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
                assert "idx_triples_predicate" not in plan, (sql, plan)
                assert "SCAN t" not in plan, (sql, plan)
        finally:
            conn.close()

    def test_existing_kg_gains_the_indexes_on_open(self, tmp_path):
        path = tmp_path / "old.sqlite3"
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE entities (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
            " type TEXT DEFAULT 'unknown', properties TEXT DEFAULT '{}',"
            " created_at TEXT DEFAULT CURRENT_TIMESTAMP);"
            "CREATE TABLE triples (id TEXT PRIMARY KEY, subject TEXT NOT NULL,"
            " predicate TEXT NOT NULL, object TEXT NOT NULL, valid_from TEXT, valid_to TEXT,"
            " confidence REAL DEFAULT 1.0, source_closet TEXT, source_file TEXT,"
            " extracted_at TEXT DEFAULT CURRENT_TIMESTAMP);"
        )
        conn.close()

        KnowledgeGraph(db_path=str(path))

        conn = sqlite3.connect(path)
        names = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        conn.close()
        assert {"idx_triples_spo", "idx_triples_source_file"} <= names


# ── kg-3: closed facts deduplicate ──────────────────────────────────────────


class TestClosedFactDedupe:
    def test_repeated_closed_fact_is_stored_once(self, kg):
        first = kg.add_triple(
            "Orion", "uses", "Python 3.11", valid_from="2024-01-01", valid_to="2025-06-30"
        )
        second = kg.add_triple(
            "Orion", "uses", "Python 3.11", valid_from="2024-01-01", valid_to="2025-06-30"
        )

        assert first == second
        assert len(kg.query_entity("Orion")) == 1

    def test_a_different_closed_window_is_new_history(self, kg):
        kg.add_triple("Orion", "uses", "Python", valid_from="2024-01-01", valid_to="2024-06-30")
        kg.add_triple("Orion", "uses", "Python", valid_from="2025-01-01", valid_to="2025-06-30")

        assert len(kg.query_entity("Orion")) == 2

    def test_mcp_kg_add_reports_existing_fact_and_stored_names(self, mcp_kg):
        from mempalace_code.mcp.tools.kg import tool_kg_add

        mcp_kg.add_triple("Alice", "works_on", "Orion", valid_from="2025-01-10")

        first = tool_kg_add(subject="Orion", predicate="deploys to", object="New York DC")
        again = tool_kg_add(
            subject="  ALICE ", predicate="works_on", object="orion", valid_from="2024-06-01"
        )

        assert first["created"] is True
        assert first["fact"] == "Orion → deploys_to → New York DC"
        assert again["created"] is False
        assert again["fact"] == "Alice → works_on → Orion"
        assert again["valid_from"] == "2025-01-10"
        # The stored start differs from the requested one, so the note says so.
        assert "nothing was added" in again["note"]
        assert again["same_fact_current"][0]["valid_from"] == "2025-01-10"


# ── agent-9 / kg-5: invalidate tells the truth ──────────────────────────────


class TestInvalidateReport:
    def test_missing_fact_is_not_reported_as_success(self, mcp_kg):
        from mempalace_code.mcp.tools.kg import tool_kg_invalidate

        mcp_kg.add_triple("mpc", "current_version", "1.15.0")

        result = tool_kg_invalidate(subject="mpc", predicate="current_version", object="1.15")

        assert result["success"] is False
        assert result["invalidated"] == 0
        assert result["current_objects"] == ["1.15.0"]
        assert [f["current"] for f in mcp_kg.query_entity("mpc")] == [True]

    def test_already_ended_fact_reports_the_stored_end(self, mcp_kg):
        from mempalace_code.mcp.tools.kg import tool_kg_invalidate

        mcp_kg.add_triple(
            "mpc", "current_version", "1.14.2", valid_from="2026-09-01", valid_to="2026-09-25"
        )

        result = tool_kg_invalidate(
            subject="mpc", predicate="current_version", object="1.14.2", ended="2026-09-20"
        )

        assert result["success"] is False
        assert result["already_ended"] == [{"valid_from": "2026-09-01", "valid_to": "2026-09-25"}]
        assert mcp_kg.query_entity("mpc")[0]["valid_to"] == "2026-09-25"

    def test_success_echoes_the_stored_end_instead_of_now(self, mcp_kg):
        from mempalace_code.mcp.tools.kg import tool_kg_invalidate

        mcp_kg.add_triple("Orion", "phase", "design")

        result = tool_kg_invalidate(subject="Orion", predicate="phase", object="design")
        repeat = tool_kg_invalidate(subject="Orion", predicate="phase", object="design")

        stored = mcp_kg.query_entity("Orion")[0]["valid_to"]
        assert result["success"] is True
        assert result["invalidated"] == 1
        assert result["ended"] == stored
        assert result["ended"] != "now"
        assert repeat["success"] is False
        assert repeat["already_ended"][0]["valid_to"] == stored


# ── kg-6: two current values are visible to the writer ─────────────────────


def test_kg_add_lists_other_current_values_for_the_same_predicate(mcp_kg):
    from mempalace_code.mcp.tools.kg import tool_kg_add, tool_kg_invalidate

    tool_kg_add(subject="Orion", predicate="status", object="beta", valid_from="2026-09-01")
    today = kg_module.datetime.now(kg_module.UTC).date().isoformat()
    tool_kg_invalidate(subject="Orion", predicate="status", object="beta", ended=today)

    result = tool_kg_add(subject="Orion", predicate="status", object="ga", valid_from=today)

    assert [fact["object"] for fact in result["other_current"]] == ["beta"]
    assert "mempalace_kg_invalidate" in result["note"]


# ── agent-22 / kg-9: stored names, trimmed input ───────────────────────────


class TestStoredNames:
    def test_query_returns_stored_names_not_the_query_casing(self, kg):
        kg.add_triple("test_e2e", "depends_on", "lancedb")
        kg.add_triple("mpc", "storage_backend", "LanceDB")

        incoming = kg.query_entity("Lancedb", direction="incoming")

        assert {(f["subject"], f["object"]) for f in incoming} == {
            ("test_e2e", "lancedb"),
            ("mpc", "lancedb"),
        }

    def test_query_trims_entity_input(self, kg):
        kg.add_triple("Alice", "works_on", "Orion")

        facts = kg.query_entity("  ALICE  ")

        assert [(f["subject"], f["object"]) for f in facts] == [("Alice", "Orion")]


# ── mcp-6 / agent-11 / kg-7: paged KG tools ────────────────────────────────


class TestPagedKgTools:
    def test_timeline_reports_total_and_pages_to_current_undated_facts(self, mcp_kg):
        from mempalace_code.mcp.tools.kg import tool_kg_timeline

        for i in range(110):
            mcp_kg.add_triple(
                "Acme",
                "event",
                f"e{i}",
                valid_from=f"2020-01-{i % 28 + 1:02d}",
                valid_to="2021-01-01",
            )
        for i in range(10):
            mcp_kg.add_triple("Acme", "has", f"current{i}")

        first = tool_kg_timeline(entity="Acme")
        second = tool_kg_timeline(entity="Acme", offset=first["next_offset"])

        assert first["count"] == 100
        assert first["total"] == 120
        assert first["truncated"] is True
        assert second["count"] == 20
        assert second["truncated"] is False
        assert second["next_offset"] is None
        assert sum(fact["current"] for fact in second["timeline"]) == 10

    def test_kg_query_is_bounded_with_totals(self, mcp_kg):
        from mempalace_code.mcp.tools.kg import tool_kg_query

        for i in range(150):
            mcp_kg.add_triple(f"Type{i}", "in_project", "proj0")

        page = tool_kg_query(entity="proj0", direction="incoming", limit=50)
        last = tool_kg_query(entity="proj0", direction="incoming", limit=50, offset=100)

        assert (page["count"], page["total"], page["truncated"], page["next_offset"]) == (
            50,
            150,
            True,
            50,
        )
        assert (last["count"], last["truncated"]) == (50, False)
        assert tool_kg_query(entity="proj0", limit=0)["error"].startswith("limit must be")


# ── upg-3: adoption reporting and the legacy default ───────────────────────


def test_kg_without_db_path_warns_that_it_opens_the_legacy_kg(tmp_path, monkeypatch):
    monkeypatch.setattr(kg_module, "DEFAULT_KG_PATH", str(tmp_path / "legacy.sqlite3"))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        KnowledgeGraph()

    assert any(
        issubclass(w.category, DeprecationWarning) and "open_palace_kg" in str(w.message)
        for w in caught
    )


def test_export_records_json_roundtrip(kg):
    kg.add_entity("Orion", entity_type="project", properties={"lang": "python"})
    kg.add_triple("Dana", "leads", "Orion")

    entities = list(kg.iter_entities())

    assert entities == [
        {
            "id": "orion",
            "name": "Orion",
            "entity_type": "project",
            "properties": {"lang": "python"},
            "created_at": entities[0]["created_at"],
        }
    ]
    json.dumps(entities)


# ── upg-1 / upg-2 / upg-3: legacy adoption ─────────────────────────────────


@pytest.fixture
def scratch_home(tmp_path, monkeypatch):
    from types import SimpleNamespace

    home = tmp_path / "home"
    state = home / ".mempalace"
    palace = state / "palace"
    state.mkdir(parents=True)
    (state / "config.json").write_text(json.dumps({"palace_path": str(palace)}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("MEMPALACE_PALACE_PATH", raising=False)
    monkeypatch.delenv("MEMPAL_PALACE_PATH", raising=False)
    legacy = state / "knowledge_graph.sqlite3"
    monkeypatch.setattr(kg_module, "DEFAULT_KG_PATH", str(legacy))
    return SimpleNamespace(
        palace=palace,
        legacy=legacy,
        marker=state / "knowledge_graph.sqlite3.adopted",
        palace_kg=palace / "knowledge_graph.sqlite3",
    )


def _run_cli(argv):
    import sys
    from unittest.mock import patch

    from mempalace_code.cli import main

    with patch.object(sys, "argv", argv):
        main()


class TestLegacyAdoption:
    def test_adoption_reports_facts_the_palace_already_holds(self, scratch_home, capsys):
        from mempalace_code.knowledge_graph import adopt_legacy_kg

        KnowledgeGraph(db_path=str(scratch_home.palace_kg)).add_triple("App", "uses", "Postgres")
        legacy = KnowledgeGraph(db_path=str(scratch_home.legacy))
        legacy.add_triple("App", "uses", "Postgres", valid_from="2024-01-01")
        legacy.add_triple("Bob", "works_on", "App")

        assert adopt_legacy_kg(str(scratch_home.palace)) == 1

        err = capsys.readouterr().err
        assert "Adopted 1 fact(s)" in err
        assert "1 legacy fact(s) were not copied" in err

    def test_unreadable_legacy_warning_names_a_next_step(self, scratch_home, capsys):
        from mempalace_code.knowledge_graph import open_palace_kg

        scratch_home.legacy.write_bytes(b"not a sqlite database")

        open_palace_kg(str(scratch_home.palace))

        err = capsys.readouterr().err
        assert "was not adopted" in err
        assert (
            f'Next: if that file is damaged and its facts are not needed, move it aside with: mv "{scratch_home.legacy}"'
            in err
        )

    def test_env_selected_new_palace_does_not_consume_adoption(
        self, scratch_home, tmp_path, monkeypatch
    ):
        from mempalace_code.knowledge_graph import open_palace_kg

        KnowledgeGraph(db_path=str(scratch_home.legacy)).add_triple("Legacy", "owns", "Fact")
        (scratch_home.palace / "lance").mkdir(parents=True)
        other = tmp_path / "other2"
        monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(other))

        open_palace_kg(str(other)).stats()
        open_palace_kg(str(other)).stats()

        assert not scratch_home.marker.exists()
        assert _rows(str(other / "knowledge_graph.sqlite3")) == []

        monkeypatch.delenv("MEMPALACE_PALACE_PATH")
        open_palace_kg(str(scratch_home.palace))

        assert _rows(str(scratch_home.palace_kg)) == [("legacy", "owns", "fact", None, None)]
        assert scratch_home.marker.is_file()

    def test_env_only_palace_still_adopts(self, scratch_home, tmp_path, monkeypatch):
        from mempalace_code.knowledge_graph import open_palace_kg

        KnowledgeGraph(db_path=str(scratch_home.legacy)).add_triple("Legacy", "owns", "Fact")
        env_palace = tmp_path / "env-palace"
        (env_palace / "lance").mkdir(parents=True)
        monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(env_palace))

        open_palace_kg(str(env_palace))

        assert _rows(str(env_palace / "knowledge_graph.sqlite3")) == [
            ("legacy", "owns", "fact", None, None)
        ]

    def test_rebuild_from_pre_upgrade_export_receives_legacy_only_facts(
        self, scratch_home, tmp_path, capsys
    ):
        from mempalace_code.export import write_jsonl
        from mempalace_code.storage import open_store

        # Pre-upgrade state: the palace invalidated a fact the legacy KG still holds open,
        # and the legacy KG holds a fact the palace never saw.
        palace = KnowledgeGraph(db_path=str(scratch_home.palace_kg))
        palace.add_triple("App", "references", "OldLib", valid_from="2026-01-01")
        palace.invalidate("App", "references", "OldLib", ended="2026-02-01")
        legacy = KnowledgeGraph(db_path=str(scratch_home.legacy))
        legacy.add_triple("App", "references", "OldLib", valid_from="2026-01-01")
        legacy.add_triple("Bob", "owns", "App", valid_from="2025-06-01")
        exported = tmp_path / "pre-upgrade.jsonl"
        write_jsonl(
            str(exported),
            open_store(str(scratch_home.palace), create=True),
            kg=palace,
            only_manual=True,
            include_kg=True,
        )
        lines = exported.read_text().splitlines()
        header = json.loads(lines[0])
        header["version"] = "1.14.2"
        exported.write_text("\n".join([json.dumps(header), *lines[1:]]) + "\n")

        # Documented rebuild: backup create adopts into the palace about to be quarantined.
        _run_cli(["mempalace-code", "backup", "create", "--out", str(tmp_path / "pre.tar.gz")])
        assert scratch_home.marker.is_file()
        (scratch_home.palace).rename(tmp_path / "quarantine")
        capsys.readouterr()

        _run_cli(["mempalace-code", "--palace", str(scratch_home.palace), "import", str(exported)])

        assert sorted(_rows(str(scratch_home.palace_kg))) == [
            ("app", "references", "oldlib", "2026-01-01", "2026-02-01"),
            ("bob", "owns", "app", "2025-06-01", None),
        ]
        err = capsys.readouterr().err
        assert "Adopted 1 fact(s)" in err
        assert "made by 1.14.2" in err


# ── import-1 / import-2 / kg-3 / kg-8 / gap-8: JSONL KG round trips ────────


def _export(tmp_path, kg, name="export.jsonl", **filters):
    from mempalace_code.export import write_jsonl
    from mempalace_code.storage import open_store

    palace = tmp_path / "src-palace"
    palace.mkdir(exist_ok=True)
    path = tmp_path / name
    summary = write_jsonl(
        str(path),
        open_store(str(palace), create=True),
        kg=kg,
        include_kg=True,
        palace_path=str(palace),
        **filters,
    )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    return path, summary, records


def _import(path, kg, dry_run=False):
    from mempalace_code.export import import_jsonl

    class _NoDrawers:
        def query(self, **_):
            return {"distances": [[]]}

        def get(self, ids=None, **_):
            return {"ids": []}

    return import_jsonl(str(path), _NoDrawers(), kg=kg, dry_run=dry_run)


class TestKgImportIdempotence:
    def _source(self, tmp_path):
        src = KnowledgeGraph(db_path=str(tmp_path / "src.sqlite3"))
        src.add_triple("billing", "uses", "Stripe", valid_from="2026-03-10")
        src.add_triple(
            "Marco", "on_call_for", "payments", valid_from="2026-02-01", valid_to="2026-06-30"
        )
        src.add_triple("billing", "used", "Braintree", valid_to="2026-03-10")
        return src

    def test_replaying_an_export_is_a_no_op_and_counts_only_inserts(self, tmp_path):
        path, _, _ = _export(tmp_path, self._source(tmp_path))
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))

        first = _import(path, dst)
        rows = _rows(dst.db_path)
        dry = _import(path, dst, dry_run=True)
        second = _import(path, dst)

        assert (first["imported_triples"], first["skipped_kg_duplicates"]) == (3, 0)
        assert (dry["imported_triples"], dry["skipped_kg_duplicates"]) == (0, 3)
        assert (second["imported_triples"], second["skipped_kg_duplicates"]) == (0, 3)
        assert _rows(dst.db_path) == rows
        assert len(rows) == 3

    def test_older_export_does_not_resurrect_a_later_invalidation(self, tmp_path):
        path, _, _ = _export(tmp_path, self._source(tmp_path))
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))
        _import(path, dst)
        dst.invalidate("billing", "uses", "Stripe", ended="2026-09-20")

        again = _import(path, dst)

        stripe = [f for f in dst.query_entity("billing") if f["object"] == "Stripe"]
        assert [(f["valid_to"], f["current"]) for f in stripe] == [("2026-09-20", False)]
        assert again["kg_conflicts"] == 1
        assert any("stay invalidated" in warning for warning in again["warnings"])

    def test_a_newer_export_applies_an_invalidation_to_the_same_fact(self, tmp_path):
        src = self._source(tmp_path)
        old_path, _, _ = _export(tmp_path, src, name="old.jsonl")
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))
        _import(old_path, dst)
        src.invalidate("billing", "uses", "Stripe", ended="2026-09-01")
        new_path, _, _ = _export(tmp_path, src, name="new.jsonl")

        summary = _import(new_path, dst)

        stripe = [f for f in dst.query_entity("billing") if f["object"] == "Stripe"]
        assert [f["valid_to"] for f in stripe] == ["2026-09-01"]
        assert summary["kg_invalidations_applied"] == 1

    def test_round_trip_keeps_entity_metadata_ids_and_extracted_at(self, tmp_path):
        src = KnowledgeGraph(db_path=str(tmp_path / "src.sqlite3"))
        src.add_entity("Orion", entity_type="project", properties={"lang": "python"})
        src.add_entity("Dana", entity_type="person")
        triple_id = src.add_triple("Dana", "leads", "Orion", valid_from="2026-01-01")
        path, summary, records = _export(tmp_path, src)
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))

        result = _import(path, dst)

        assert summary["kg_entity_count"] == 2
        assert {r["type"] for r in records} == {"export_header", "kg_entity", "kg_triple"}
        assert result["imported_kg_entities"] == 2
        conn = sqlite3.connect(dst.db_path)
        entities = conn.execute("SELECT id, type, properties FROM entities ORDER BY id").fetchall()
        stored = conn.execute("SELECT id, extracted_at FROM triples").fetchall()
        conn.close()
        assert entities == [("dana", "person", "{}"), ("orion", "project", '{"lang": "python"}')]
        exported = next(r for r in records if r["type"] == "kg_triple")
        assert stored == [(triple_id, exported["extracted_at"])]

    @staticmethod
    def _reopened_source(tmp_path):
        # Closed history plus a later open copy of one fact, all with valid_from NULL,
        # as left by kg_add → kg_invalidate → kg_add and by re-mines before 1.15.0.
        src = KnowledgeGraph(db_path=str(tmp_path / "src.sqlite3"))
        src.add_triple("Alice", "works_on", "Orion")
        src.invalidate("Alice", "works_on", "Orion", ended="2026-03-01")
        return src

    @staticmethod
    def _current(kg, subject="Alice"):
        return [(f["object"], f["valid_to"], f["current"]) for f in kg.query_entity(subject)]

    def test_export_with_closed_and_reopened_copies_imports_both(self, tmp_path):
        src = self._reopened_source(tmp_path)
        src.add_triple("Alice", "works_on", "Orion")
        path, _, _ = _export(tmp_path, src)
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))

        dry = _import(path, KnowledgeGraph(db_path=str(tmp_path / "dry.sqlite3")), dry_run=True)
        summary = _import(path, dst)
        again = _import(path, dst)

        for result in (dry, summary):
            assert (result["imported_triples"], result["kg_conflicts"]) == (2, 0)
            assert not any("invalidated" in w for w in result["warnings"])
        assert sorted(self._current(dst), key=str) == sorted(
            [("Orion", "2026-03-01", False), ("Orion", None, True)], key=str
        )
        assert (again["imported_triples"], again["skipped_kg_duplicates"]) == (0, 2)
        assert again["kg_conflicts"] == 0

    def test_reopened_fact_imports_after_its_closed_copy_was_imported(self, tmp_path):
        src = self._reopened_source(tmp_path)
        old_path, _, _ = _export(tmp_path, src, name="old.jsonl")
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))
        _import(old_path, dst)
        src.add_triple("Alice", "works_on", "Orion")
        new_path, _, _ = _export(tmp_path, src, name="new.jsonl")

        summary = _import(new_path, dst)

        assert (summary["imported_triples"], summary["kg_conflicts"]) == (1, 0)
        assert ("Orion", None, True) in self._current(dst)

    def test_reopened_history_applies_in_any_record_order(self, tmp_path):
        src = KnowledgeGraph(db_path=str(tmp_path / "src.sqlite3"))
        src.add_triple("Alice", "works_on", "Orion")
        old_path, _, _ = _export(tmp_path, src, name="old.jsonl")
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))
        _import(old_path, dst)
        src.invalidate("Alice", "works_on", "Orion", ended="2026-03-01")
        src.add_triple("Alice", "works_on", "Orion")
        _, _, records = _export(tmp_path, src, name="new.jsonl")
        reversed_path = tmp_path / "reversed.jsonl"
        reversed_path.write_text(
            "\n".join(json.dumps(r) for r in [records[0], *reversed(records[1:])]) + "\n"
        )

        summary = _import(reversed_path, dst)

        assert (summary["kg_invalidations_applied"], summary["imported_triples"]) == (1, 1)
        assert sorted(self._current(dst), key=str) == sorted(
            [("Orion", "2026-03-01", False), ("Orion", None, True)], key=str
        )

    def test_export_without_ids_still_keeps_a_palace_invalidation(self, tmp_path):
        path, _, records = _export(tmp_path, self._source(tmp_path))
        dst = KnowledgeGraph(db_path=str(tmp_path / "dst.sqlite3"))
        _import(path, dst)
        dst.invalidate("billing", "uses", "Stripe", ended="2026-09-20")
        legacy = tmp_path / "no-ids.jsonl"
        legacy.write_text(
            "\n".join(json.dumps({k: v for k, v in r.items() if k != "id"}) for r in records) + "\n"
        )

        summary = _import(legacy, dst)

        stripe = [f for f in dst.query_entity("billing") if f["object"] == "Stripe"]
        assert [f["current"] for f in stripe] == [False]
        assert summary["kg_conflicts"] == 1


def test_cli_import_fails_loudly_when_the_kg_transaction_fails(
    scratch_home, tmp_path, monkeypatch, capsys
):
    path, _, _ = _export(tmp_path, TestKgImportIdempotence()._source(tmp_path))
    target = tmp_path / "target-palace"

    def locked(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(KnowledgeGraph, "import_facts", locked)
    with pytest.raises(SystemExit) as exc:
        _run_cli(["mempalace-code", "--palace", str(target), "import", str(path)])

    err = capsys.readouterr().err
    assert exc.value.code == 1
    assert "KG records were not imported (OperationalError: database is locked)" in err
    assert f"mempalace-code --palace {target} import {path}" in err
    assert _rows(str(target / "knowledge_graph.sqlite3")) == []


class TestScopedKgExport:
    def test_wing_scoped_export_includes_only_that_wings_kg_facts(self, tmp_path):
        from mempalace_code.storage import open_store

        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        kg.add_triple("models", "depends_on", "jinja2", source_file="/src/shop/web/models.py")
        kg.add_triple("NoteTopic", "decided_by", "Alice", source_file="/notes/decision.md")
        kg.add_triple("Alice", "works_on", "Orion")
        kg.add_triple("Notes.Area", "in_project", "notes", source_file="__arch_ns_project__:notes")
        kg.add_triple("Shop.Web", "in_project", "shop", source_file="__arch_ns_project__:shop")
        palace = tmp_path / "src-palace"
        palace.mkdir()
        store = open_store(str(palace), create=True)
        store.add(
            ids=["note-1"],
            documents=["Decision note about the notes wing."],
            metadatas=[{"wing": "notes", "room": "general", "source_file": "/notes/decision.md"}],
        )

        _, summary, records = _export(tmp_path, kg, wing="notes")
        _, since_summary, _ = _export(
            tmp_path, kg, name="since.jsonl", room="general", since="2030-01-01"
        )

        triples = [r for r in records if r["type"] == "kg_triple"]
        assert [(t["subject"], t["object"]) for t in triples] == [
            ("NoteTopic", "Alice"),
            ("Notes.Area", "notes"),
        ]
        assert summary["kg_count"] == 2
        assert summary["kg_scope"] == "drawer_sources"
        assert (
            json.loads((tmp_path / "export.jsonl").read_text().splitlines()[0])["filters"][
                "kg_scope"
            ]
            == "drawer_sources"
        )
        assert since_summary["kg_count"] == 0

    def test_unscoped_export_keeps_the_whole_kg(self, tmp_path):
        kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
        kg.add_triple("models", "depends_on", "jinja2", source_file="/src/shop/web/models.py")
        kg.add_triple("Alice", "works_on", "Orion")

        _, summary, _ = _export(tmp_path, kg)

        assert (summary["kg_count"], summary["kg_scope"]) == (2, "all")


# ── mcp-11 / graph-1: palace graph ──────────────────────────────────────────


class _PairStore:
    """Store exposing only projected pair counts, like LanceStore.count_by_pair."""

    def __init__(self, rows):
        self._rows = rows

    def count_by_pair(self, col_a, col_b):
        out: dict = {}
        for row in self._rows:
            bucket = out.setdefault(row.get(col_a, ""), {})
            bucket[row.get(col_b, "")] = bucket.get(row.get(col_b, ""), 0) + 1
        return out

    def get(self, **_):
        raise AssertionError("the graph must not read every drawer's metadata")

    def count(self):
        return len(self._rows)


_GRAPH_ROWS = [
    {"wing": "billing", "room": "documentation", "hall": "", "date": ""},
    {"wing": "tool", "room": "documentation", "hall": "", "date": ""},
    {"wing": "tool", "room": "testing", "hall": "", "date": ""},
    {"wing": "tool", "room": "general", "hall": "", "date": ""},
]


class TestPalaceGraph:
    def test_tunnels_count_as_edges_without_reading_rows(self):
        from mempalace_code.palace_graph import graph_stats

        stats = graph_stats(col=_PairStore(_GRAPH_ROWS))

        assert stats["total_rooms"] == 2
        assert stats["tunnel_rooms"] == 1
        assert stats["total_edges"] == 1

    def test_general_start_room_is_explained(self):
        from mempalace_code.palace_graph import traverse

        result = traverse("general", col=_PairStore(_GRAPH_ROWS))

        assert isinstance(result, dict)
        assert "catch-all" in result["error"]
        assert "not found" not in result["error"]

    def test_negative_hops_are_rejected(self):
        from mempalace_code.palace_graph import traverse

        result = traverse("testing", col=_PairStore(_GRAPH_ROWS), max_hops=-1)

        assert isinstance(result, dict)
        assert result["error"].startswith("max_hops must be")

    def test_mcp_find_tunnels_rejects_an_unknown_wing(self, monkeypatch):
        from mempalace_code.mcp import runtime
        from mempalace_code.mcp.tools.graph import tool_find_tunnels

        monkeypatch.setattr(runtime, "_get_store", lambda create=False: _PairStore(_GRAPH_ROWS))

        result = tool_find_tunnels(wing_a="nonexistent")
        known = tool_find_tunnels(wing_a="billing")

        assert isinstance(result, dict)
        assert result["error"] == "unknown_wing"
        assert isinstance(known, list)
        assert [t["room"] for t in known] == ["documentation"]


# ── kg-7 / agent-20 / agent-21: architecture tools ─────────────────────────


class TestArchitectureTools:
    def test_project_graph_keeps_python_imports_out_and_is_bounded(self, mcp_kg):
        from mempalace_code.mcp.tools.architecture import tool_show_project_graph

        mcp_kg.add_triple("Shop.Web", "targets_framework", "net8.0", source_file="/s/Web.csproj")
        mcp_kg.add_triple("Shop.Web", "depends_on", "Serilog@3.1", source_file="/s/Web.csproj")
        mcp_kg.add_triple("Shop", "contains_project", "Shop.Web", source_file="/s/Shop.sln")
        for i in range(30):
            mcp_kg.add_triple(f"pkg.mod{i}", "depends_on", "os", source_file=f"/p/mod{i}.py")

        result = tool_show_project_graph(limit=1)

        assert [r["subject"] for r in result["graph"]["depends_on"]] == ["Shop.Web"]
        assert result["totals"]["depends_on"] == 1
        assert result["truncated"] is False
        assert result["next_offset"] is None
        assert tool_show_project_graph(limit=0)["error"].startswith("limit must be")

    def test_project_graph_pages_with_offset(self, mcp_kg):
        from mempalace_code.mcp.tools.architecture import tool_show_project_graph

        for i in range(3):
            mcp_kg.add_triple(f"App{i}", "targets_framework", "net8.0", source_file="/s/a.csproj")

        first = tool_show_project_graph(limit=2)
        second = tool_show_project_graph(limit=2, offset=first["next_offset"])

        assert first["truncated"] is True
        assert first["next_offset"] == 2
        assert second["offset"] == 2
        assert second["truncated"] is False
        assert second["next_offset"] is None
        subjects = [
            r["subject"] for page in (first, second) for r in page["graph"]["targets_framework"]
        ]
        assert sorted(subjects) == ["App0", "App1", "App2"]
        assert second["totals"]["targets_framework"] == 3
        assert tool_show_project_graph(offset=-1)["error"] == "offset must be 0 or greater"

    def test_python_abc_is_not_classified_as_core(self, mcp_kg):
        from mempalace_code.mcp.tools.architecture import tool_extract_reusable

        mcp_kg.add_triple("LanceStore", "inherits", "DrawerStore")
        mcp_kg.add_triple("DrawerStore", "implements", "ABC")

        result = tool_extract_reusable(entity="LanceStore")

        assert [c["entity"] for c in result["graph"]["core"]] == ["DrawerStore"]
        assert [p["entity"] for p in result["graph"]["platform"]] == ["ABC"]

    def test_python_abc_matches_whatever_spelling_the_entity_kept(self, mcp_kg):
        from mempalace_code.mcp.tools.architecture import (
            tool_extract_reusable,
            tool_find_implementations,
        )

        # An earlier-mined `import abc` stores the shared entity as "abc".
        mcp_kg.add_triple("shop.models", "depends_on", "abc")
        mcp_kg.add_triple("DrawerStore", "implements", "ABC")
        mcp_kg.add_triple("LanceStore", "inherits", "DrawerStore")

        reusable = tool_extract_reusable(entity="LanceStore")
        implementations = tool_find_implementations(interface="DrawerStore")

        assert [p["entity"] for p in reusable["graph"]["platform"]] == ["abc"]
        assert [c["entity"] for c in reusable["graph"]["core"]] == ["DrawerStore"]
        assert [i["type"] for i in implementations["implementations"]] == ["LanceStore"]

    def test_find_implementations_description_names_python(self):
        from mempalace_code.mcp.tools.architecture import TOOL_SPECS

        description = TOOL_SPECS["mempalace_find_implementations"]["description"]

        assert "Python" in description
        assert "DOTNET-SYMBOL-GRAPH" not in description

    def test_explain_subsystem_ranks_tests_last_and_adds_module_imports(
        self, mcp_kg, monkeypatch, tmp_path
    ):
        import mempalace_code.searcher as searcher
        from mempalace_code.mcp import runtime
        from mempalace_code.mcp.tools.architecture import tool_explain_subsystem

        package = tmp_path / "mempalace_code"
        package.mkdir()
        (package / "__init__.py").write_text("")
        core = package / "knowledge_graph.py"
        core.write_text("import sqlite3\n")
        hits = [
            {"symbol_name": "TestStats", "source_file": str(tmp_path / "tests/test_kg.py")},
            {"symbol_name": "add_triple", "source_file": str(core)},
        ]
        monkeypatch.setattr(searcher, "code_search", lambda **_: {"results": hits})
        monkeypatch.setattr(runtime, "_get_store", lambda create=False: object())
        mcp_kg.add_triple("mempalace_code.knowledge_graph", "depends_on", "sqlite3")

        result = tool_explain_subsystem(query="temporal facts", n_results=2)

        assert [ep["symbol_name"] for ep in result["entry_points"]] == ["add_triple", "TestStats"]
        assert result["module_graph"] == {
            "mempalace_code.knowledge_graph": {"depends_on": ["sqlite3"]}
        }

    def test_explain_subsystem_says_when_nothing_is_related(self, mcp_kg, monkeypatch):
        import mempalace_code.searcher as searcher
        from mempalace_code.mcp import runtime
        from mempalace_code.mcp.tools.architecture import tool_explain_subsystem

        hits = [{"symbol_name": "helper", "source_file": "/nowhere/helper.go"}]
        monkeypatch.setattr(searcher, "code_search", lambda **_: {"results": hits})
        monkeypatch.setattr(runtime, "_get_store", lambda create=False: object())

        result = tool_explain_subsystem(query="helpers")

        assert "No knowledge-graph relationships" in result["note"]
