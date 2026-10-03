"""
test_palace_kg_owner.py — every surface uses the selected palace's KG.

Covers the palace-owned KG resolution shared by CLI, MCP, backup, export, and
watcher surfaces, plus the one-way, one-time adoption of facts that only the
legacy global KG holds. Each test runs in a disposable HOME whose configured palace
is ``~/.mempalace/palace``, whose legacy KG is ``~/.mempalace/knowledge_graph.sqlite3``,
and whose adoption marker is ``~/.mempalace/knowledge_graph.sqlite3.adopted``.
"""

import hashlib
import json
import os
import sqlite3
import sys
import tarfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import mempalace_code.knowledge_graph as kg_module
from mempalace_code.backup import create_backup, restore_backup
from mempalace_code.cli import main
from mempalace_code.config import MempalaceConfig
from mempalace_code.export import write_jsonl
from mempalace_code.knowledge_graph import (
    KnowledgeGraph,
    LazyKnowledgeGraph,
    adopt_legacy_kg,
    open_palace_kg,
    palace_kg_path,
)
from mempalace_code.storage import open_store


@pytest.fixture
def scratch_home(tmp_path, monkeypatch):
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


def _facts(db_path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, subject, predicate, object, valid_from, valid_to, source_file "
            "FROM triples ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _file_state(path) -> tuple[str, int]:
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def _subjects_in_jsonl(path) -> set[str]:
    with open(path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    return {record["subject"] for record in records if record["type"] == "kg_triple"}


def _run(argv):
    with patch.object(sys, "argv", argv):
        main()


def _windows(db_path) -> list[tuple]:
    return sorted(row[1:6] for row in _facts(db_path))


def _adopted_then_invalidated_in_palace(home) -> None:
    KnowledgeGraph(db_path=str(home.legacy)).add_triple(
        "Alice", "uses", "Chroma", valid_from="2025-01-01"
    )
    open_palace_kg(str(home.palace)).invalidate("Alice", "uses", "Chroma", ended="2026-01-01")


def _both_present_invalidated_in_palace(home) -> None:
    palace = KnowledgeGraph(db_path=str(home.palace_kg))
    palace.add_triple("App", "references", "OldLib", valid_from="2026-01-01")
    palace.invalidate("App", "references", "OldLib", ended="2026-02-01")
    legacy = KnowledgeGraph(db_path=str(home.legacy))
    legacy.add_triple("App", "references", "OldLib", valid_from="2026-01-01")
    legacy.add_triple("Bob", "owns", "App", valid_from="2025-06-01")


def _invalidated_in_legacy(home) -> None:
    legacy = KnowledgeGraph(db_path=str(home.legacy))
    legacy.add_triple("Alice", "uses", "Chroma", valid_from="2025-01-01")
    legacy.invalidate("Alice", "uses", "Chroma", ended="2026-01-01")
    legacy.add_triple("Alice", "works_on", "App", valid_from="2025-01-01")


class TestLegacyAdoptionBranches:
    def test_no_legacy_uses_palace_kg_and_creates_no_legacy_file(self, scratch_home, capsys):
        kg = open_palace_kg(str(scratch_home.palace))
        kg.add_triple("App", "uses", "Postgres")

        assert kg.db_path == str(scratch_home.palace_kg)
        assert len(_facts(scratch_home.palace_kg)) == 1
        assert not scratch_home.legacy.exists()
        assert capsys.readouterr().err == ""

    def test_legacy_only_is_copied_once_with_ids_windows_and_entity_types(
        self, scratch_home, capsys
    ):
        legacy = KnowledgeGraph(db_path=str(scratch_home.legacy))
        legacy.add_entity("Alice", "person", {"role": "owner"})
        legacy.add_triple("Alice", "works_on", "MemPalace", valid_from="2026-01-01")
        legacy.add_triple("Alice", "uses", "Chroma", valid_from="2025-01-01")
        legacy.invalidate("Alice", "uses", "Chroma", ended="2026-01-01")
        legacy_facts = _facts(scratch_home.legacy)
        before = _file_state(scratch_home.legacy)

        kg = open_palace_kg(str(scratch_home.palace))

        assert _facts(scratch_home.palace_kg) == legacy_facts
        conn = sqlite3.connect(str(scratch_home.palace_kg))
        entity = conn.execute("SELECT type, properties FROM entities WHERE id = 'alice'").fetchone()
        conn.close()
        assert entity == ("person", '{"role": "owner"}')
        assert {f["object"] for f in kg.query_entity("Alice") if f["current"]} == {"MemPalace"}
        assert _file_state(scratch_home.legacy) == before
        err = capsys.readouterr().err
        assert "Adopted 2 fact(s)" in err
        assert "the legacy database was not changed" in err
        assert scratch_home.marker.is_file()

        # Later opens skip the unchanged legacy file without reading it.
        with patch.object(kg_module.sqlite3, "connect", side_effect=AssertionError("re-read")):
            assert adopt_legacy_kg(str(scratch_home.palace)) == 0

        # Deleting the marker adopts again, which adds nothing the palace already knows.
        scratch_home.marker.unlink()
        assert adopt_legacy_kg(str(scratch_home.palace)) == 0
        assert _facts(scratch_home.palace_kg) == legacy_facts
        assert _file_state(scratch_home.legacy) == before
        assert scratch_home.marker.is_file()
        assert capsys.readouterr().err == ""

    def test_both_present_keeps_palace_facts_authoritative(self, scratch_home, capsys):
        palace = KnowledgeGraph(db_path=str(scratch_home.palace_kg))
        palace.add_triple("App", "references", "OldLib", valid_from="2026-01-01")
        palace.invalidate("App", "references", "OldLib", ended="2026-02-01")
        palace.add_triple("App", "references", "NewLib", valid_from="2026-02-01")
        legacy = KnowledgeGraph(db_path=str(scratch_home.legacy))
        legacy.add_triple("App", "references", "OldLib", valid_from="2026-01-01")
        legacy.add_triple("Bob", "owns", "App", valid_from="2025-06-01")
        legacy.invalidate("Bob", "owns", "App", ended="2026-01-01")
        legacy.add_triple("Bob", "owns", "App", valid_from="2026-03-01")
        palace_before = set(_facts(scratch_home.palace_kg))
        legacy_before = _file_state(scratch_home.legacy)

        assert adopt_legacy_kg(str(scratch_home.palace)) == 2

        after = set(_facts(scratch_home.palace_kg))
        assert palace_before <= after
        adopted = after - palace_before
        assert {row[1:4] for row in adopted} == {("bob", "owns", "app")}
        assert len(adopted) == 2, "legacy history of a fact the palace lacks is kept"
        old_lib = [row for row in after if row[1:4] == ("app", "references", "oldlib")]
        assert len(old_lib) == 1, "no duplicated legacy copy"
        assert old_lib[0][5] is not None, "the palace invalidation is not resurrected"
        assert _file_state(scratch_home.legacy) == legacy_before
        assert "Adopted 2 fact(s)" in capsys.readouterr().err

        scratch_home.marker.unlink()
        assert adopt_legacy_kg(str(scratch_home.palace)) == 0
        assert set(_facts(scratch_home.palace_kg)) == after

    def test_changed_legacy_is_checked_again_and_adds_only_new_facts(self, scratch_home):
        legacy = KnowledgeGraph(db_path=str(scratch_home.legacy))
        legacy.add_triple("Alice", "uses", "Chroma", valid_from="2025-01-01")
        open_palace_kg(str(scratch_home.palace)).invalidate(
            "Alice", "uses", "Chroma", ended="2026-01-01"
        )
        legacy.add_triple("Alice", "uses", "LanceDB", valid_from="2026-01-01")
        # Make the change visible even where file mtimes are coarse.
        stat = scratch_home.legacy.stat()
        os.utime(scratch_home.legacy, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))

        assert adopt_legacy_kg(str(scratch_home.palace)) == 1

        assert _windows(scratch_home.palace_kg) == [
            ("alice", "uses", "chroma", "2025-01-01", "2026-01-01"),
            ("alice", "uses", "lancedb", "2026-01-01", None),
        ]

    def test_low_predicate_cardinality_is_filtered_before_the_write_lock(
        self, scratch_home, monkeypatch
    ):
        # Real KGs hold few distinct predicates. A per-fact membership lookup through
        # idx_triples_predicate under the write lock scaled with legacy x palace rows
        # and made concurrent add_triple calls fail with "database is locked".
        def fill(path, prefix, first):
            KnowledgeGraph(db_path=str(path))
            conn = sqlite3.connect(str(path))
            conn.executemany(
                "INSERT INTO triples (id, subject, predicate, object) VALUES (?, ?, ?, 'app')",
                [
                    (f"{prefix}{i}", f"file{i}", ("in_project", "in_namespace")[i % 2])
                    for i in range(first, first + 4000)
                ],
            )
            conn.commit()
            conn.close()

        fill(scratch_home.palace_kg, "p", 0)
        fill(scratch_home.legacy, "l", 2000)
        statements: list[str] = []
        open_conn = KnowledgeGraph._conn

        def traced_conn(kg):
            conn = open_conn(kg)
            conn.set_trace_callback(statements.append)
            return conn

        monkeypatch.setattr(KnowledgeGraph, "_conn", traced_conn)
        started = time.perf_counter()

        assert adopt_legacy_kg(str(scratch_home.palace)) == 2000

        assert time.perf_counter() - started < 10, "generous bound; measured well under 1s"
        assert len(_facts(scratch_home.palace_kg)) == 6000
        begin = statements.index("BEGIN IMMEDIATE")
        assert "SELECT subject, predicate, object FROM triples" in statements[:begin]
        locked_reads = {sql for sql in statements[begin:] if sql.startswith("SELECT")}
        assert len(locked_reads) == 2000, "only the missing facts are re-checked under the lock"
        conn = sqlite3.connect(str(scratch_home.palace_kg))
        try:
            for sql in locked_reads:
                plan = " ".join(row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
                assert "idx_triples_spo" in plan, plan
        finally:
            conn.close()

    def test_fact_written_after_the_unlocked_filter_is_not_adopted_again(
        self, scratch_home, monkeypatch
    ):
        legacy = KnowledgeGraph(db_path=str(scratch_home.legacy))
        legacy.add_triple("App", "uses", "Redis", valid_from="2025-01-01")
        legacy.add_triple("App", "uses", "Kafka", valid_from="2025-01-01")
        palace = KnowledgeGraph(db_path=str(scratch_home.palace_kg))
        open_conn = KnowledgeGraph._conn

        class RacingConnection:
            def __init__(self, conn):
                self._conn = conn

            def __getattr__(self, name):
                return getattr(self._conn, name)

            def execute(self, sql, *params):
                if sql == "BEGIN IMMEDIATE":
                    # A concurrent writer lands between the filter and the write lock.
                    palace.add_triple("App", "uses", "Redis", valid_from="2026-01-01")
                return self._conn.execute(sql, *params)

        monkeypatch.setattr(KnowledgeGraph, "_conn", lambda kg: RacingConnection(open_conn(kg)))

        assert adopt_legacy_kg(str(scratch_home.palace)) == 1

        assert _windows(scratch_home.palace_kg) == [
            ("app", "uses", "kafka", "2025-01-01", None),
            ("app", "uses", "redis", "2026-01-01", None),
        ]

    def test_other_palace_never_receives_legacy_facts(self, scratch_home, tmp_path):
        KnowledgeGraph(db_path=str(scratch_home.legacy)).add_triple("Global", "knows", "All")
        other = tmp_path / "other-palace"

        kg = open_palace_kg(str(other))

        assert kg.db_path == palace_kg_path(str(other))
        assert _facts(kg.db_path) == []
        assert not scratch_home.palace_kg.exists()
        assert not scratch_home.marker.exists()

    def test_unreadable_legacy_warns_and_changes_nothing(self, scratch_home, capsys):
        scratch_home.legacy.write_bytes(b"not a sqlite database")

        kg = open_palace_kg(str(scratch_home.palace))
        kg.add_triple("App", "uses", "Redis")

        err = capsys.readouterr().err
        assert f"legacy knowledge graph {scratch_home.legacy} was not adopted" in err
        assert "no facts were copied" in err
        assert scratch_home.legacy.read_bytes() == b"not a sqlite database"
        assert not scratch_home.marker.exists()
        assert [row[1:4] for row in _facts(scratch_home.palace_kg)] == [("app", "uses", "redis")]

    def test_lazy_palace_kg_defers_open_and_adoption(self, scratch_home):
        KnowledgeGraph(db_path=str(scratch_home.legacy)).add_triple("Global", "knows", "All")

        lazy = LazyKnowledgeGraph(str(scratch_home.palace))
        assert not scratch_home.palace_kg.exists()

        assert lazy.stats()["triples"] == 1
        assert [row[1:4] for row in _facts(scratch_home.palace_kg)] == [("global", "knows", "all")]


class TestSurfacesShareConfiguredPalaceKg:
    def test_cli_mcp_export_and_backup_see_the_same_palace_kg(
        self, scratch_home, tmp_path, monkeypatch, capsys
    ):
        from mempalace_code.mcp import runtime
        from mempalace_code.mcp.tools import kg as kg_tools

        KnowledgeGraph(db_path=str(scratch_home.legacy)).add_triple("GlobalAlice", "knows", "Bob")
        legacy_before = _file_state(scratch_home.legacy)
        project = tmp_path / "project"
        project.mkdir()
        (project / "mempalace.yaml").write_text(
            "wing: project\nrooms:\n  - name: general\n    description: all files\n"
        )
        (project / "shapes.py").write_text(
            "class Shape:\n    pass\n\n\nclass Circle(Shape):\n    pass\n"
        )

        # CLI mine without --palace writes architecture/type facts to the configured palace.
        _run(["mempalace-code", "mine", str(project)])

        # MCP uses the same configured palace KG for reads and writes.
        monkeypatch.setattr(runtime, "_config", MempalaceConfig())
        monkeypatch.setattr(runtime, "_kg", None)
        assert kg_tools.tool_kg_add("LocalBob", "knows", "Carol")["success"] is True
        assert kg_tools.tool_kg_query("Circle")["count"] >= 1
        assert kg_tools.tool_kg_query("GlobalAlice")["count"] == 1

        default_jsonl = tmp_path / "default.jsonl"
        explicit_jsonl = tmp_path / "explicit.jsonl"
        _run(["mempalace-code", "export", "--with-kg", "--out", str(default_jsonl)])
        _run(
            [
                "mempalace-code",
                "--palace",
                str(scratch_home.palace),
                "export",
                "--with-kg",
                "--out",
                str(explicit_jsonl),
            ]
        )
        default_subjects = _subjects_in_jsonl(default_jsonl)
        assert {"GlobalAlice", "LocalBob", "Circle"} <= default_subjects
        assert _subjects_in_jsonl(explicit_jsonl) == default_subjects

        archive = tmp_path / "default.tar.gz"
        _run(["mempalace-code", "backup", "create", "--out", str(archive)])
        extracted = tmp_path / "archived_kg.sqlite3"
        with tarfile.open(archive, "r:gz") as tar:
            member = tar.extractfile("mempalace_backup/knowledge_graph.sqlite3")
            assert member is not None
            extracted.write_bytes(member.read())
        archived = {row[1] for row in _facts(extracted)}
        assert {"globalalice", "localbob", "circle"} <= archived

        assert _file_state(scratch_home.legacy) == legacy_before
        assert os.path.isfile(scratch_home.palace_kg)

    def test_backup_library_defaults_use_the_palace_kg(
        self, scratch_home, seeded_collection, palace_path, tmp_path
    ):
        # Pre-optimize, pre-watch, and compress backups rely on these defaults.
        KnowledgeGraph(db_path=str(scratch_home.legacy)).add_triple("GlobalAlice", "knows", "Bob")
        legacy_before = _file_state(scratch_home.legacy)
        KnowledgeGraph(db_path=palace_kg_path(palace_path)).add_triple("LocalBob", "knows", "Carol")

        _meta, archive = create_backup(palace_path, out_path=str(tmp_path / "default.tar.gz"))
        target = tmp_path / "restored"
        restore_backup(archive, str(target))

        assert [row[1] for row in _facts(palace_kg_path(str(target)))] == ["localbob"]
        assert _file_state(scratch_home.legacy) == legacy_before

    @pytest.mark.parametrize(
        "setup",
        [
            _adopted_then_invalidated_in_palace,
            _both_present_invalidated_in_palace,
            _invalidated_in_legacy,
        ],
    )
    def test_rebuild_replays_the_palace_kg_without_readopting_legacy(
        self, scratch_home, tmp_path, capsys, setup
    ):
        setup(scratch_home)
        open_store(str(scratch_home.palace), create=True)
        legacy_before = _file_state(scratch_home.legacy)
        exported = tmp_path / "manual.jsonl"
        palace_cli = ["mempalace-code", "--palace", str(scratch_home.palace)]
        _run([*palace_cli, "export", "--only-manual", "--with-kg", "--out", str(exported)])
        exported_windows = _windows(scratch_home.palace_kg)

        # Documented rebuild: quarantine the palace, then replay the export into a
        # fresh palace in a new process. The legacy KG must not be adopted again.
        os.rename(scratch_home.palace, tmp_path / "quarantine")
        _run([*palace_cli, "import", str(exported)])

        assert _windows(scratch_home.palace_kg) == exported_windows
        current = KnowledgeGraph(db_path=str(scratch_home.palace_kg)).stats()["current_facts"]
        assert current == sum(1 for row in exported_windows if row[4] is None)
        assert _file_state(scratch_home.legacy) == legacy_before

    def test_import_of_a_pre_marker_export_keeps_palace_invalidations(
        self, scratch_home, tmp_path, capsys
    ):
        # An export written before the marker existed holds only the palace KG, while
        # the legacy KG still holds the palace-invalidated fact open.
        _both_present_invalidated_in_palace(scratch_home)
        exported = tmp_path / "pre-marker.jsonl"
        write_jsonl(
            str(exported),
            open_store(str(scratch_home.palace), create=True),
            kg=KnowledgeGraph(db_path=str(scratch_home.palace_kg)),
            only_manual=True,
            include_kg=True,
        )
        assert not scratch_home.marker.exists()
        os.rename(scratch_home.palace, tmp_path / "quarantine")

        _run(["mempalace-code", "--palace", str(scratch_home.palace), "import", str(exported)])

        # The replay lands first, so adoption adds only the legacy-only fact.
        assert _windows(scratch_home.palace_kg) == [
            ("app", "references", "oldlib", "2026-01-01", "2026-02-01"),
            ("bob", "owns", "app", "2025-06-01", None),
        ]
        assert scratch_home.marker.is_file()
        assert "Adopted 1 fact(s)" in capsys.readouterr().err

    def test_backup_create_adopts_legacy_before_archiving(self, scratch_home, tmp_path, capsys):
        KnowledgeGraph(db_path=str(scratch_home.legacy)).add_triple("Legacy", "owns", "Fact")
        archive = tmp_path / "legacy.tar.gz"

        _run(["mempalace-code", "backup", "create", "--out", str(archive)])

        with tarfile.open(archive, "r:gz") as tar:
            assert "mempalace_backup/knowledge_graph.sqlite3" in tar.getnames()
        assert [row[1:4] for row in _facts(scratch_home.palace_kg)] == [("legacy", "owns", "fact")]
        assert "Adopted 1 fact(s)" in capsys.readouterr().err
