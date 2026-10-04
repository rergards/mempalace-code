"""
test_uat_kg_backup.py — UAT regressions for KG, backup, restore, export, and import safety.

Covers pre-1.15.0 exports and archives that hold the legacy global KG instead of the
palace KG, corrupt and read-only KGs in backup/restore/export/mine, degraded-archive
refusal, restore and export argument checks, import normalization, and kg_add
reporting.
"""

import io
import json
import os
import sqlite3
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

import mempalace_code.knowledge_graph as kg_module
from mempalace_code.backup import (
    BackupArchiveError,
    RestoreTargetError,
    create_backup,
    managed_backups_dir,
    restore_backup,
)
from mempalace_code.cli import main
from mempalace_code.export import export_kg, import_jsonl
from mempalace_code.knowledge_graph import (
    KnowledgeGraph,
    KnowledgeGraphCorruptError,
    KnowledgeGraphReadOnlyError,
    LazyKnowledgeGraph,
    palace_kg_path,
)
from mempalace_code.miner import mine
from mempalace_code.storage import open_store

REPO = Path(__file__).resolve().parents[1]


def _run(argv, capsys):
    code = 0
    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr()
    return code, out.out, out.err


def _make_palace(path, wing="billing", n=2) -> str:
    store = open_store(str(path), create=True)
    for i in range(n):
        store.add(
            ids=[f"drawer_{wing}_{i}"],
            documents=[f"{wing} fact number {i}"],
            metadatas=[{"wing": wing, "room": "notes", "chunker_strategy": "manual_v1"}],
        )
    return str(path)


def _facts(db_path) -> set[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return set(
            conn.execute("SELECT subject, predicate, object, valid_to FROM triples").fetchall()
        )
    finally:
        conn.close()


def _corrupt(path) -> None:
    Path(path).write_bytes(os.urandom(4096))


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A disposable HOME whose configured palace and legacy KG are known."""
    root = tmp_path / "home"
    state = root / ".mempalace"
    palace = state / "palace"
    state.mkdir(parents=True)
    (state / "config.json").write_text(json.dumps({"palace_path": str(palace)}))
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.delenv("MEMPALACE_PALACE_PATH", raising=False)
    monkeypatch.delenv("MEMPAL_PALACE_PATH", raising=False)
    legacy = state / "knowledge_graph.sqlite3"
    monkeypatch.setattr(kg_module, "DEFAULT_KG_PATH", str(legacy))
    return SimpleNamespace(root=root, palace=palace, legacy=legacy)


def _seed_upgrade_state(home) -> None:
    """Legacy KG written by CLI runs without --palace; palace KG written through MCP."""
    legacy = KnowledgeGraph(db_path=str(home.legacy))
    legacy.add_triple("Bob", "works_on", "billing", valid_from="2024-03-01")
    legacy.add_triple("billing", "uses", "Postgres", valid_from="2025-01-02")
    _make_palace(home.palace)
    palace = KnowledgeGraph(db_path=palace_kg_path(str(home.palace)))
    palace.add_triple("Alice", "works_on", "billing", valid_from="2025-01-10")
    palace.add_triple("billing", "uses", "Postgres", valid_from="2025-01-02")
    palace.invalidate("billing", "uses", "Postgres", ended="2026-05-31")


def _old_export(path, kg_path, version="1.14.2") -> str:
    """Write an export shaped like a 1.14.2 `export --only-manual --with-kg` of *kg_path*."""
    kg = KnowledgeGraph(db_path=str(kg_path))
    records = [r for r in export_kg(kg) if r["type"] == "kg_triple"]
    header = {
        "type": "export_header",
        "version": version,
        "palace_path": "/gone/palace",
        "filters": {"only_manual": True, "with_kg": True},
        "drawer_count": 0,
        "kg_count": len(records),
    }
    with open(path, "w", encoding="utf-8") as handle:
        for record in [header, *records]:
            handle.write(json.dumps(record) + "\n")
    return str(path)


def _rewrite_archive(archive: str, name_suffix: str, transform) -> None:
    """Rewrite the member of *archive* whose name ends with *name_suffix*."""
    members: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            handle = tar.extractfile(member) if member.isfile() else None
            members.append((member, handle.read() if handle is not None else None))
    with tarfile.open(archive, "w:gz") as tar:
        for member, data in members:
            if data is not None and member.name.endswith(name_suffix):
                data = transform(data)
                member.size = len(data)
            tar.addfile(member, io.BytesIO(data) if data is not None else None)


def _set_archive_version(archive: str, version: str, **extra) -> None:
    """Rewrite metadata.json of *archive* as an older release (or with extra keys) would."""

    def transform(data: bytes) -> bytes:
        meta = json.loads(data)
        meta["mempalace_version"] = version
        meta.update(extra)
        return json.dumps(meta).encode()

    _rewrite_archive(archive, "mempalace_backup/metadata.json", transform)


# ── upg-4: a pre-1.15.0 export of the legacy KG ────────────────────────────────


class TestLegacyKgExport:
    def test_dry_run_and_import_refuse_an_export_of_the_legacy_kg(self, home, tmp_path, capsys):
        _seed_upgrade_state(home)
        export = _old_export(tmp_path / "exp1142.jsonl", home.legacy)
        before = _facts(palace_kg_path(str(home.palace)))

        for extra in (["--dry-run"], []):
            code, _, err = _run(["--palace", str(home.palace), "import", export, *extra], capsys)

            assert code == 1
            assert "without --palace" in err
            assert "legacy global knowledge graph" in err
            assert "Nothing was imported" in err
            assert "export --only-manual --with-kg --out" in err
            assert _facts(palace_kg_path(str(home.palace))) == before

    def test_skip_kg_imports_only_the_drawers(self, home, tmp_path, capsys):
        _seed_upgrade_state(home)
        export = _old_export(tmp_path / "exp1142.jsonl", home.legacy)

        code, out, _ = _run(
            ["--palace", str(home.palace), "import", export, "--skip-kg", "--dry-run"], capsys
        )

        assert code == 0
        assert "Imported KG triples:0" in out

    def test_a_palace_scoped_old_export_still_imports(self, home, tmp_path, capsys):
        _seed_upgrade_state(home)
        export = _old_export(tmp_path / "exp_palace.jsonl", palace_kg_path(str(home.palace)))

        code, _, err = _run(["--palace", str(home.palace), "import", export, "--dry-run"], capsys)

        assert code == 0
        assert "legacy global" not in err

    def test_without_the_legacy_file_the_import_warns(self, home, tmp_path, capsys):
        _seed_upgrade_state(home)
        export = _old_export(tmp_path / "exp1142.jsonl", home.legacy)
        home.legacy.unlink()

        code, _, err = _run(["--palace", str(home.palace), "import", export, "--dry-run"], capsys)

        assert code == 0
        assert "WARNING" in err
        assert "without --palace" in err


def _seed_mcp_only_state(home) -> None:
    """1.14.2 used only through MCP: the legacy KG exists but holds no facts."""
    KnowledgeGraph(db_path=str(home.legacy))
    _make_palace(home.palace)
    palace = KnowledgeGraph(db_path=palace_kg_path(str(home.palace)))
    palace.add_triple("Alice", "works_on", "billing", valid_from="2025-01-10")
    palace.add_triple("billing", "uses", "Postgres", valid_from="2025-01-02")
    palace.invalidate("billing", "uses", "Postgres", ended="2026-05-31")


class TestEmptyLegacyKgExport:
    """A 1.14.2 no --palace export of an empty legacy KG looks like an empty palace KG."""

    def test_dry_run_and_import_refuse_while_the_palace_kg_holds_facts(
        self, home, tmp_path, capsys
    ):
        _seed_mcp_only_state(home)
        export = _old_export(tmp_path / "exp1142.jsonl", home.legacy)
        before = _facts(palace_kg_path(str(home.palace)))

        for extra in (["--dry-run"], []):
            code, _, err = _run(["--palace", str(home.palace), "import", export, *extra], capsys)

            assert code == 1
            assert "holds no KG records" in err
            assert "holds 2 fact(s)" in err
            assert "Nothing was imported" in err
            assert "export --only-manual --with-kg --out" in err
            assert "--skip-kg" in err
            assert _facts(palace_kg_path(str(home.palace))) == before

    def test_rebuild_into_a_moved_palace_warns(self, home, tmp_path, capsys):
        _seed_mcp_only_state(home)
        export = _old_export(tmp_path / "exp1142.jsonl", home.legacy)
        os.rename(home.palace, tmp_path / "quarantine")

        code, _, err = _run(["--palace", str(home.palace), "import", export], capsys)

        assert code == 0
        assert "WARNING" in err
        assert "without --palace" in err
        assert "facts added through MCP are missing" in err

    def test_skip_kg_imports_the_drawers(self, home, tmp_path, capsys):
        _seed_mcp_only_state(home)
        export = _old_export(tmp_path / "exp1142.jsonl", home.legacy)

        code, _, _ = _run(
            ["--palace", str(home.palace), "import", export, "--skip-kg", "--dry-run"], capsys
        )

        assert code == 0

    def test_an_export_without_kg_stays_silent(self, home, tmp_path, capsys):
        _seed_mcp_only_state(home)
        export = tmp_path / "drawers_only.jsonl"
        header = {"type": "export_header", "version": "1.14.2", "filters": {"only_manual": True}}
        export.write_text(json.dumps(header) + "\n")

        code, _, err = _run(
            ["--palace", str(home.palace), "import", str(export), "--dry-run"], capsys
        )

        assert code == 0
        assert "legacy global" not in err


# ── upg-5: a pre-1.15.0 archive of the legacy KG ───────────────────────────────


class TestLegacyKgArchive:
    def _archive(self, home, tmp_path) -> str:
        _seed_upgrade_state(home)
        archive = str(tmp_path / "bk1142.tar.gz")
        # 1.14.2 `backup create` without --palace archived the legacy KG.
        create_backup(str(home.palace), out_path=archive, kg_path=str(home.legacy))
        _set_archive_version(archive, "1.14.2")
        return archive

    def test_force_restore_keeps_the_palace_kg(self, home, tmp_path):
        archive = self._archive(home, tmp_path)
        palace_kg = palace_kg_path(str(home.palace))
        before = _facts(palace_kg)

        with pytest.raises(RestoreTargetError, match="legacy global knowledge graph") as raised:
            restore_backup(archive, str(home.palace), force=True)

        assert "--kg-path" in str(raised.value)
        assert _facts(palace_kg) == before
        side_kg = str(tmp_path / "legacy-copy.sqlite3")
        meta = restore_backup(archive, str(home.palace), force=True, kg_path=side_kg)
        assert meta.legacy_kg is True
        assert _facts(palace_kg) == before
        assert ("alice", "works_on", "billing", None) in before

    def test_restore_into_a_new_palace_warns(self, home, tmp_path, capsys):
        archive = self._archive(home, tmp_path)

        code, out, err = _run(["--palace", str(tmp_path / "fresh"), "restore", archive], capsys)

        assert code == 0
        assert "Restored knowledge graph to:" in out
        assert "legacy" in err
        assert "without --palace" in err

    def test_a_palace_scoped_old_archive_restores_silently(self, home, tmp_path):
        _seed_upgrade_state(home)
        archive = str(tmp_path / "bk1142_palace.tar.gz")
        create_backup(str(home.palace), out_path=archive)
        _set_archive_version(archive, "1.14.2")

        meta = restore_backup(archive, str(home.palace), force=True)

        assert meta.legacy_kg is False


class TestAmbiguousOldArchive:
    """A pre-1.15.0 archive whose KG source cannot be told must not replace palace facts."""

    def _archive(self, home, tmp_path) -> str:
        _seed_mcp_only_state(home)
        archive = str(tmp_path / "bk1142.tar.gz")
        # 1.14.2 `backup create` without --palace archived the empty legacy KG.
        create_backup(str(home.palace), out_path=archive, kg_path=str(home.legacy))
        _set_archive_version(archive, "1.14.2")
        return archive

    def test_force_restore_of_an_empty_legacy_kg_keeps_the_palace_kg(self, home, tmp_path, capsys):
        archive = self._archive(home, tmp_path)
        palace_kg = palace_kg_path(str(home.palace))
        before = _facts(palace_kg)

        code, _, err = _run(["--palace", str(home.palace), "restore", archive, "--force"], capsys)

        assert code == 1
        assert "may be the legacy global knowledge graph" in err
        assert "drop 2 fact(s)" in err
        assert "--kg-path" in err
        assert _facts(palace_kg) == before
        side_kg = str(tmp_path / "side.sqlite3")
        meta = restore_backup(archive, str(home.palace), force=True, kg_path=side_kg)
        assert meta.legacy_kg_possible is True
        assert _facts(palace_kg) == before

    def test_missing_legacy_file_with_extra_palace_facts_refuses(self, home, tmp_path):
        _seed_upgrade_state(home)
        archive = str(tmp_path / "bk1142.tar.gz")
        create_backup(str(home.palace), out_path=archive, kg_path=str(home.legacy))
        _set_archive_version(archive, "1.14.2")
        home.legacy.unlink()

        with pytest.raises(RestoreTargetError, match="may be the legacy"):
            restore_backup(archive, str(home.palace), force=True)

    def test_missing_legacy_file_without_palace_loss_restores(self, home, tmp_path):
        _seed_upgrade_state(home)
        archive = str(tmp_path / "bk1142_palace.tar.gz")
        create_backup(str(home.palace), out_path=archive)
        _set_archive_version(archive, "1.14.2")
        home.legacy.unlink()

        meta = restore_backup(archive, str(home.palace), force=True)

        assert meta.legacy_kg_possible is True
        assert ("alice", "works_on", "billing", None) in _facts(palace_kg_path(str(home.palace)))

    def test_restore_into_a_new_palace_warns(self, home, tmp_path, capsys):
        archive = self._archive(home, tmp_path)

        code, _, err = _run(["--palace", str(tmp_path / "fresh"), "restore", archive], capsys)

        assert code == 0
        assert "if it was made without --palace" in err


# ── backup-3 / ops-3 / restore-4: corrupt KG and degraded archives ────────────


class TestCorruptKgBackups:
    def test_backup_of_a_corrupt_kg_is_degraded_and_exits_1(self, tmp_path, capsys):
        palace = _make_palace(tmp_path / "palace")
        _corrupt(palace_kg_path(palace))

        meta, archive = create_backup(palace)
        assert meta["degraded"] is True
        assert meta["degraded_error"].startswith("kg_corrupt:")
        assert archive.endswith("_DEGRADED.tar.gz")

        code, out, err = _run(
            ["--palace", palace, "backup", "create", "--out", str(tmp_path / "x.tar.gz")], capsys
        )
        assert code == 1
        assert "knowledge graph is corrupt" in out
        assert "restore refuses it" in err

    def test_restore_refuses_a_degraded_archive(self, tmp_path, capsys):
        palace = _make_palace(tmp_path / "palace")
        archive = str(tmp_path / "flagged.tar.gz")
        create_backup(palace, out_path=archive)
        _set_archive_version(archive, "1.15.0", degraded=True, degraded_error="x")

        with pytest.raises(BackupArchiveError) as raised:
            restore_backup(archive, str(tmp_path / "target"))
        assert raised.value.code == "degraded_archive"
        assert not (tmp_path / "target").exists()

        code, _, err = _run(["--palace", str(tmp_path / "t2"), "restore", archive], capsys)
        assert code == 1
        assert "forensic copy of a degraded palace (x)" in err
        assert "backup list" in err

    def test_restore_refuses_an_unflagged_archive_with_a_corrupt_kg(self, tmp_path):
        palace = _make_palace(tmp_path / "palace")
        source_kg = str(tmp_path / "kg.sqlite3")
        KnowledgeGraph(db_path=source_kg).add_triple("a", "b", "c")
        archive = str(tmp_path / "old.tar.gz")
        create_backup(palace, out_path=archive, kg_path=source_kg)
        # As an older release archived it: no integrity check at create time.
        _rewrite_archive(archive, "knowledge_graph.sqlite3", lambda _: os.urandom(4096))

        with pytest.raises(BackupArchiveError) as raised:
            restore_backup(archive, str(tmp_path / "target"))

        assert raised.value.code == "invalid_kg_payload"
        assert not (tmp_path / "target").exists()

    def test_health_names_a_rebuild_path_for_a_corrupt_kg(self, tmp_path, capsys):
        palace = _make_palace(tmp_path / "palace")
        _corrupt(palace_kg_path(palace))

        code, out, _ = _run(["--palace", palace, "health"], capsys)

        assert code == 1
        assert "kg_corrupt" in out
        assert "--full" in out
        assert "not with --force" in out


# ── export-4: export --with-kg of a corrupt KG ────────────────────────────────


def test_export_with_a_corrupt_kg_fails_without_a_traceback(tmp_path, capsys):
    palace = _make_palace(tmp_path / "palace")
    KnowledgeGraph(db_path=palace_kg_path(palace)).add_triple("a", "b", "c")
    raw = bytearray(Path(palace_kg_path(palace)).read_bytes())
    raw[4096:8192] = b"\xff" * 4096
    Path(palace_kg_path(palace)).write_bytes(bytes(raw))
    out_file = tmp_path / "ex.jsonl"

    code, _, err = _run(["--palace", palace, "export", "--with-kg", "--out", str(out_file)], capsys)

    assert code == 1
    assert "is corrupt" in err
    assert "health" in err
    assert "Traceback" not in err
    assert not out_file.exists()


# ── ops-2 / gap-5: mine checks the KG before any drawer changes ──────────────


def _project(root: Path) -> Path:
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    body = "\n".join(f"    def step_{i}(self):\n        return {i}\n" for i in range(12))
    (root / "app" / "base.py").write_text(f"class Base:\n{body}")
    (root / "app" / "child.py").write_text(
        f"from app.base import Base\n\n\nclass Child(Base):\n{body}"
    )
    (root / "mempalace.yaml").write_text(
        yaml.dump({"wing": "app", "rooms": [{"name": "general", "description": "All"}]})
    )
    return root


def test_mine_with_a_corrupt_kg_changes_no_drawer(tmp_path):
    project = _project(tmp_path / "proj")
    palace = str(tmp_path / "palace")
    mine(str(project), palace, kg=LazyKnowledgeGraph(palace), skip_optimize=True)
    before = open_store(palace, create=False, read_only=True).count()
    assert before > 0
    _corrupt(palace_kg_path(palace))
    (project / "app" / "child.py").write_text(
        (project / "app" / "child.py").read_text() + "\n# changed\n"
    )

    for incremental in (True, False):
        with pytest.raises(KnowledgeGraphCorruptError):
            mine(
                str(project),
                palace,
                kg=LazyKnowledgeGraph(palace),
                incremental=incremental,
                skip_optimize=True,
            )
        assert open_store(palace, create=False, read_only=True).count() == before


@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root ignores permissions"
)
def test_a_read_only_kg_is_reported_precisely(tmp_path):
    folder = tmp_path / "ro"
    folder.mkdir()
    db = folder / "knowledge_graph.sqlite3"
    KnowledgeGraph(db_path=str(db)).add_triple("a", "b", "c")
    for leftover in folder.glob("*-*"):
        leftover.unlink()
    db.chmod(0o444)
    folder.chmod(0o555)
    try:
        with pytest.raises(KnowledgeGraphReadOnlyError, match="not writable"):
            KnowledgeGraph(db_path=str(db))
        with pytest.raises(KnowledgeGraphReadOnlyError, match="chmod"):
            LazyKnowledgeGraph(str(folder)).check_writable()
    finally:
        folder.chmod(0o755)
        db.chmod(0o644)


def test_mcp_reports_an_unavailable_kg_as_a_tool_error():
    from mempalace_code.mcp import dispatch

    assert issubclass(KnowledgeGraphReadOnlyError, dispatch._REPORTED_TOOL_ERRORS)
    assert issubclass(KnowledgeGraphCorruptError, dispatch._REPORTED_TOOL_ERRORS)


# ── arch-3: the mine summary counts expired facts ────────────────────────────


def test_mine_summary_counts_facts_of_a_deleted_file(tmp_path, capsys):
    project = _project(tmp_path / "proj")
    palace = str(tmp_path / "palace")
    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    mine(str(project), palace, kg=kg, skip_optimize=True)
    capsys.readouterr()
    open_before = sum(1 for fact in _facts(kg.db_path) if fact[3] is None)
    (project / "app" / "child.py").unlink()

    mine(str(project), palace, kg=kg, skip_optimize=True)

    out = capsys.readouterr().out
    expired = open_before - sum(1 for fact in _facts(kg.db_path) if fact[3] is None)
    assert expired > 0
    line = next(line for line in out.splitlines() if "Knowledge graph:" in line)
    assert f"{expired} expired" in line


# ── kg-10 / kg-12: kg_add reports ─────────────────────────────────────────────


@pytest.fixture
def mcp_kg(monkeypatch, tmp_path):
    from mempalace_code.mcp import runtime

    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(tmp_path))
    monkeypatch.setattr(runtime, "_kg", kg)
    return kg


def test_kg_add_never_adds_a_second_current_copy_of_a_fact(mcp_kg):
    from mempalace_code.mcp.tools.kg import tool_kg_add

    mcp_kg.add_triple("Alice", "works_on", "Orion", valid_from="2025-01-10")

    result = tool_kg_add(
        subject="alice",
        predicate="Works On",
        object="ORION",
        valid_from="2025-01-10",
        valid_to="2099-12-31",
    )

    assert result["created"] is False
    assert result["valid_to"] is None
    assert result["same_fact_current"][0]["valid_to"] is None
    assert "mempalace_kg_invalidate" in result["note"]
    current = [f for f in mcp_kg.query_entity("Orion", direction="incoming") if f["current"]]
    assert len(current) == 1
    # A window that does not overlap the current copy is history, and is recorded.
    past = tool_kg_add(
        subject="Alice",
        predicate="works_on",
        object="Orion",
        valid_from="2020-01-01",
        valid_to="2021-01-01",
    )
    assert past["created"] is True


def test_kg_add_reports_a_current_copy_with_another_start(mcp_kg):
    from mempalace_code.mcp.tools.kg import tool_kg_add

    mcp_kg.add_triple("Alice", "works_on", "Orion", valid_from="2025-01-10")

    result = tool_kg_add(
        subject="Alice", predicate="works_on", object="Orion", valid_from="2024-01-01"
    )

    assert result["created"] is False
    assert result["valid_from"] == "2025-01-10"
    assert result["same_fact_current"][0]["valid_from"] == "2025-01-10"
    assert "identical" not in result["note"]
    assert "mempalace_kg_invalidate" in result["note"]
    # The same open request as stored stays a plain duplicate.
    again = tool_kg_add(
        subject="Alice", predicate="works_on", object="Orion", valid_from="2025-01-10"
    )
    assert "same_fact_current" not in again
    assert "identical" in again["note"]


def test_kg_add_always_returns_other_current(mcp_kg):
    from mempalace_code.mcp.tools.kg import tool_kg_add

    result = tool_kg_add(subject="Carol", predicate="works_on", object="billing")

    assert result["other_current"] == []


def test_explain_subsystem_notes_missing_type_relationships_beside_imports(tmp_path, monkeypatch):
    import mempalace_code.searcher as searcher
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.architecture import tool_explain_subsystem

    kg = KnowledgeGraph(db_path=str(tmp_path / "kg.sqlite3"))
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(tmp_path))
    monkeypatch.setattr(runtime, "_kg", kg)
    package = tmp_path / "mempalace_code"
    package.mkdir()
    (package / "__init__.py").write_text("")
    core = package / "knowledge_graph.py"
    core.write_text("import sqlite3\n")
    hits = [{"symbol_name": "add_triple", "source_file": str(core)}]
    monkeypatch.setattr(searcher, "code_search", lambda **_: {"results": hits})
    monkeypatch.setattr(runtime, "_get_store", lambda create=False: object())
    kg.add_triple("mempalace_code.knowledge_graph", "depends_on", "sqlite3")

    result = tool_explain_subsystem(query="temporal facts", n_results=1)

    assert result["summary"]["relationships_found"] == 0
    assert "module_graph" in result
    assert "No knowledge-graph relationships" in result["note"]


# ── restore-5 / restore-6 / ux-misc: restore arguments and output ─────────────


def test_failed_restores_point_to_tar_and_backup_list(tmp_path, capsys):
    not_tar = tmp_path / "notatar"
    not_tar.write_text("notatar\n")

    code, _, err = _run(["--palace", str(tmp_path / "e1"), "restore", str(not_tar)], capsys)
    assert code == 1
    assert "tar -tzf" in err
    assert "backup list" in err

    code, _, err = _run(
        ["--palace", str(tmp_path / "e3"), "restore", str(tmp_path / "missing.tar.gz")], capsys
    )
    assert code == 1
    assert "no such file" in err
    assert "backup list" in err


def test_restore_refuses_a_directory_kg_path(tmp_path, capsys):
    palace = _make_palace(tmp_path / "palace")
    archive = str(tmp_path / "b1.tar.gz")
    create_backup(palace, out_path=archive)
    kg_dir = tmp_path / "kgdir"
    kg_dir.mkdir()
    (kg_dir / "file.txt").write_text("important")

    for extra in ([], ["--force"]):
        code, _, err = _run(
            [
                "--palace",
                str(tmp_path / "k3"),
                "restore",
                archive,
                "--kg-path",
                str(kg_dir),
                *extra,
            ],
            capsys,
        )
        assert code == 1
        assert "is a directory" in err
        assert "knowledge_graph.sqlite3" in err
    assert (kg_dir / "file.txt").read_text() == "important"
    assert not (tmp_path / "k3").exists()


def test_restore_prints_where_the_kg_went(tmp_path, capsys):
    palace = _make_palace(tmp_path / "palace")
    KnowledgeGraph(db_path=palace_kg_path(palace)).add_triple("a", "b", "c")
    archive = str(tmp_path / "b1.tar.gz")
    create_backup(palace, out_path=archive)
    kg_dest = tmp_path / "k6kg.sqlite3"

    code, out, _ = _run(
        ["--palace", str(tmp_path / "k6"), "restore", archive, "--kg-path", str(kg_dest)], capsys
    )

    assert code == 0
    assert "Restored palace to:" in out
    assert f"Restored knowledge graph to: {kg_dest}" in out


def test_backup_create_reports_pruned_archives(tmp_path, capsys, monkeypatch):
    palace = _make_palace(tmp_path / "palace")
    for _ in range(3):
        create_backup(palace)
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "2")

    code, out, _ = _run(["--palace", palace, "backup", "create"], capsys)

    assert code == 0
    assert "Retention pruned 2 older manual archive(s)" in out
    assert len(os.listdir(managed_backups_dir(palace))) == 2


# ── ops-4 / r1-ops-20 / ux-misc: export and wake-up checks ────────────────────


def test_export_refuses_an_unknown_wing(tmp_path, capsys):
    palace = _make_palace(tmp_path / "palace", wing="small")
    out_file = tmp_path / "x2.jsonl"

    code, _, err = _run(
        ["--palace", palace, "export", "--wing", "smal", "--out", str(out_file)], capsys
    )

    assert code == 2
    assert "Unknown wing" in err
    assert "small" in err
    assert not out_file.exists()


def test_export_and_wake_up_refuse_a_directory_that_is_not_a_palace(tmp_path, capsys):
    project = tmp_path / "small"
    project.mkdir()
    (project / "mempalace.yaml").write_text("wing: small\n")
    out_file = tmp_path / "x.jsonl"

    code, _, err = _run(["--palace", str(project), "export", "--out", str(out_file)], capsys)
    assert code == 1
    assert "no palace found" in err.lower()
    assert not out_file.exists()

    code, out, err = _run(["--palace", str(project), "wake-up"], capsys)
    assert code == 1
    assert "No palace found" in err
    assert "No memories" not in out


def test_export_without_kg_prints_no_kg_scope_and_accepts_dev_null(tmp_path, capsys):
    palace = _make_palace(tmp_path / "palace")

    code, _, err = _run(["--palace", palace, "export", "--wing", "billing", "--out", "-"], capsys)
    assert code == 0
    assert "KG scope" not in err

    if os.path.exists(os.devnull):
        code, _, err = _run(
            ["--palace", palace, "export", "--with-kg", "--out", os.devnull], capsys
        )
        assert code == 0, err
        assert "Exported 2 drawers" in err


# ── import-7 / gap-3: import normalization and wing-override checks ──────────


def test_import_keeps_a_strategy_less_manual_drawer_in_only_manual_exports(tmp_path, capsys):
    palace = str(tmp_path / "odd")
    jsonl = tmp_path / "odd.jsonl"
    jsonl.write_text(
        json.dumps(
            {
                "type": "drawer",
                "id": "ok1",
                "text": "valid one about lighthouses",
                "wing": "w",
                "room": "r",
            }
        )
        + "\n"
    )

    summary = import_jsonl(str(jsonl), open_store(palace, create=True), skip_kg=True)
    assert summary["imported_drawers"] == 1
    assert any("manual_v1" in warning for warning in summary["warnings"])

    code, out, err = _run(["--palace", palace, "export", "--only-manual", "--out", "-"], capsys)
    assert code == 0
    assert "Exported 1 drawers" in err
    assert '"chunker_strategy": "manual_v1"' in out


@pytest.mark.parametrize("wing", ["a/b", "", "  ", "../x"])
def test_import_refuses_an_invalid_wing_override(tmp_path, capsys, wing):
    source = _make_palace(tmp_path / "src")
    export = str(tmp_path / "src.jsonl")
    _run(["--palace", source, "export", "--out", export], capsys)
    target = tmp_path / "pal5"

    code, _, err = _run(
        ["--palace", str(target), "import", export, "--wing-override", wing], capsys
    )

    assert code == 2
    assert "--wing-override" in err
    assert not target.exists()


def test_import_refuses_a_wing_override_that_respells_an_existing_wing(tmp_path, capsys):
    source = _make_palace(tmp_path / "src", wing="alpha")
    export = str(tmp_path / "src.jsonl")
    _run(["--palace", source, "export", "--out", export], capsys)
    target = _make_palace(tmp_path / "target", wing="shop")

    code, _, err = _run(["--palace", target, "import", export, "--wing-override", "Shop"], capsys)

    assert code == 2
    assert "'shop'" in err
    assert open_store(target, create=False, read_only=True).count_by("wing") == {"shop": 2}


# ── docs-1 / doc-1 / gap-11: release boundaries and PyPI links ────────────────


def test_docs_name_the_release_that_changed_backups_and_watch_logs():
    text = (REPO / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")

    assert "up to and including 1.15.0" not in text
    assert "rendered by 1.15.0 or an earlier release" not in text
    assert "Releases before 1.15.0 wrote every sibling palace" in text


def test_readme_links_to_docs_are_absolute_for_pypi():
    text = (REPO / "README.md").read_text(encoding="utf-8")

    assert "](docs/" not in text
