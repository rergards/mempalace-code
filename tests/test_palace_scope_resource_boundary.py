"""
test_palace_scope_resource_boundary.py — Focused regressions for PALACE-SCOPE-RESOURCE-BOUNDARY.

Covers:
  AC-1: Explicit --palace backup uses palace-local KG; global KG is excluded.
  AC-2: Scoped backup restore round-trips drawers and scoped KG without global KG data.
  AC-3: No-op incremental mine skips warmup, archive creation, optimize, and KG file creation.
  AC-4: /tmp <-> /private/tmp macOS path spellings are treated as filesystem-equivalent by reader.
"""

import os
import sqlite3
import tarfile
from contextlib import closing
from pathlib import Path

import yaml

from mempalace_code.backup import create_backup, restore_backup
from mempalace_code.knowledge_graph import KnowledgeGraph, LazyKnowledgeGraph, palace_kg_path
from mempalace_code.mining.orchestrator import mine
from mempalace_code.reader import _macos_var_aliases, read_slice
from mempalace_code.storage import LanceStore, open_store

# ─── helpers ──────────────────────────────────────────────────────────────────


def _write_mempalace_yaml(project_path: Path, wing: str = "test_wing") -> None:
    with open(project_path / "mempalace.yaml", "w") as f:
        yaml.dump({"wing": wing, "rooms": [{"name": "general", "description": "All"}]}, f)


def _seed_palace(palace_path: str, wing: str = "test_wing") -> None:
    store = open_store(palace_path, create=True)
    store.add(
        ids=["drawer_test_1"],
        documents=["def hello(): pass\n" * 10],
        metadatas=[
            {
                "wing": wing,
                "room": "general",
                "source_file": "/fake/source.py",
                "chunk_index": 0,
                "added_by": "test",
                "filed_at": "2026-01-01T00:00:00",
                "source_hash": "abc123",
            }
        ],
    )


def _archive_member_names(path: str) -> set:
    with tarfile.open(path, "r:gz") as tar:
        return {m.name for m in tar.getmembers()}


def _archive_kg_bytes(path: str) -> bytes | None:
    with tarfile.open(path, "r:gz") as tar:
        try:
            member = tar.getmember("mempalace_backup/knowledge_graph.sqlite3")
            f = tar.extractfile(member)
            if f is None:
                return None
            with f:
                return f.read()
        except KeyError:
            return None


def _kg_contents(path: str) -> tuple:
    with closing(sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        return (
            db.execute("PRAGMA user_version").fetchone(),
            db.execute("PRAGMA application_id").fetchone(),
            tuple(db.iterdump()),
        )


# ─── AC-1: Scoped backup uses palace-local KG ─────────────────────────────────


class TestScopedBackupKg:
    def test_explicit_palace_backup_uses_local_kg(self, tmp_dir):
        """AC-1: create_backup with palace-local kg_path archives the local KG, not the global one."""
        palace_path = os.path.join(tmp_dir, "palace")
        _seed_palace(palace_path)

        global_kg_path = os.path.join(tmp_dir, "global_kg.sqlite3")
        global_kg = KnowledgeGraph(db_path=global_kg_path)
        global_kg.add_triple("GlobalEntity", "is", "global_only")

        local_kg_path = palace_kg_path(palace_path)
        local_kg = KnowledgeGraph(db_path=local_kg_path)
        local_kg.add_triple("LocalEntity", "is", "local_only")

        backups_dir = os.path.join(tmp_dir, "backups")
        archive_out = os.path.join(backups_dir, "test_scoped.tar.gz")

        local_bytes = Path(local_kg_path).read_bytes()
        global_bytes = Path(global_kg_path).read_bytes()
        local_contents = _kg_contents(local_kg_path)
        global_contents = _kg_contents(global_kg_path)
        assert local_contents != global_contents, "test setup: global and local KG must differ"

        _, archive_path = create_backup(palace_path, out_path=archive_out, kg_path=local_kg_path)

        payload = _archive_kg_bytes(archive_path)
        assert payload is not None, "archive must include a KG member when local KG exists"
        archived_kg = os.path.join(tmp_dir, "archived-local-kg.sqlite3")
        Path(archived_kg).write_bytes(payload)
        # SQLite snapshots can alter file-header counters; compare all schema and data.
        archived_contents = _kg_contents(archived_kg)
        assert archived_contents == local_contents, "archive must contain the palace-local KG"
        assert archived_contents != global_contents, "archive must exclude the global KG"
        assert Path(local_kg_path).read_bytes() == local_bytes
        assert Path(global_kg_path).read_bytes() == global_bytes

    def test_explicit_palace_backup_omits_kg_when_absent(self, tmp_dir):
        """AC-1: When no palace-local KG exists, the archive omits the KG member entirely."""
        palace_path = os.path.join(tmp_dir, "palace")
        _seed_palace(palace_path)

        local_kg_path = palace_kg_path(palace_path)
        assert not os.path.exists(local_kg_path), "test setup: local KG must not exist"

        backups_dir = os.path.join(tmp_dir, "backups")
        archive_out = os.path.join(backups_dir, "test_no_kg.tar.gz")

        _, archive_path = create_backup(palace_path, out_path=archive_out, kg_path=local_kg_path)

        names = _archive_member_names(archive_path)
        assert "mempalace_backup/knowledge_graph.sqlite3" not in names

    def test_palace_kg_path_helper_returns_correct_path(self, tmp_dir):
        """palace_kg_path() returns <palace>/knowledge_graph.sqlite3."""
        palace_path = os.path.join(tmp_dir, "palace")
        expected = os.path.join(palace_path, "knowledge_graph.sqlite3")
        assert palace_kg_path(palace_path) == expected


# ─── AC-2: Scoped archive restore round-trips without global KG pollution ─────


class TestScopedRestore:
    def test_scoped_restore_round_trips_drawers(self, tmp_dir):
        """AC-2: Restore from scoped archive delivers the original drawer count."""
        src_palace = os.path.join(tmp_dir, "src_palace")
        _seed_palace(src_palace)

        local_kg_path = palace_kg_path(src_palace)
        src_kg = KnowledgeGraph(db_path=local_kg_path)
        src_kg.add_triple("ScopedEntity", "belongs_to", "src_palace")

        backups_dir = os.path.join(tmp_dir, "backups")
        archive_out = os.path.join(backups_dir, "scoped_backup.tar.gz")
        _, archive_path = create_backup(src_palace, out_path=archive_out, kg_path=local_kg_path)

        dst_palace = os.path.join(tmp_dir, "dst_palace")
        dst_kg_path = palace_kg_path(dst_palace)

        meta = restore_backup(archive_path, dst_palace, force=True, kg_path=dst_kg_path)
        assert meta is not None

        restored_store = open_store(dst_palace, create=False, read_only=True)
        assert restored_store.count() == 1, "restored palace must contain the original drawer"

    def test_scoped_restore_places_kg_at_palace_local_path(self, tmp_dir):
        """AC-2: Restore with explicit kg_path writes the KG to palace-local path only."""
        src_palace = os.path.join(tmp_dir, "src_palace")
        _seed_palace(src_palace)

        local_kg_path = palace_kg_path(src_palace)
        src_kg = KnowledgeGraph(db_path=local_kg_path)
        src_kg.add_triple("LocalFact", "stored_in", "palace_local")

        archive_out = os.path.join(tmp_dir, "backup.tar.gz")
        _, archive_path = create_backup(src_palace, out_path=archive_out, kg_path=local_kg_path)

        dst_palace = os.path.join(tmp_dir, "dst_palace")
        dst_kg_path = palace_kg_path(dst_palace)
        # Create a sibling "global" path that must remain untouched
        unrelated_kg_path = os.path.join(tmp_dir, "unrelated.sqlite3")

        meta = restore_backup(archive_path, dst_palace, force=True, kg_path=dst_kg_path)

        assert meta is not None
        # The unrelated path must not have been created by restore
        assert not os.path.exists(unrelated_kg_path), (
            "restore must not write to any path other than the explicit kg_path"
        )
        # The palace-local KG must be present at the explicit path
        assert os.path.exists(dst_kg_path), (
            "restore must place the KG at the explicit palace-local path"
        )


# ─── AC-3: No-op incremental mine skips warmup/archive/optimize/KG ────────────


class TestNoopMine:
    def _make_project(self, tmp_dir, wing: str = "noop_wing") -> tuple[str, str]:
        project_path = os.path.join(tmp_dir, "project")
        os.makedirs(project_path)
        src = Path(project_path) / "module.py"
        src.write_text("def alpha():\n    return 1\n\n" * 30)
        _write_mempalace_yaml(Path(project_path), wing=wing)
        palace_path = os.path.join(tmp_dir, "palace")
        return project_path, palace_path

    def test_noop_mine_skips_warmup(self, tmp_dir, monkeypatch):
        """AC-3: Second incremental mine on unchanged project must not call collection.warmup()."""
        project_path, palace_path = self._make_project(tmp_dir)
        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

        warmup_calls = []
        orig_warmup = LanceStore.warmup

        def spy_warmup(self):
            warmup_calls.append(1)
            orig_warmup(self)

        monkeypatch.setattr(LanceStore, "warmup", spy_warmup)

        # First mine — must call warmup and file drawers
        result1 = mine(project_path, palace_path, incremental=True)
        assert len(warmup_calls) >= 1, "first mine must call warmup"
        assert result1["drawers_filed"] > 0, "first mine must file drawers"

        warmup_calls.clear()

        # No-op mine — project unchanged
        result2 = mine(project_path, palace_path, incremental=True)

        assert len(warmup_calls) == 0, "no-op mine must not call warmup"
        assert result2["drawers_filed"] == 0, "no-op mine must file 0 drawers"
        assert result2["files_processed"] == 0, "no-op mine must process 0 files"

    def test_noop_mine_creates_no_archive(self, tmp_dir, monkeypatch):
        """AC-3: No-op mine must not create any pre-optimize archive."""
        project_path, palace_path = self._make_project(tmp_dir)
        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

        mine(project_path, palace_path, incremental=True)

        backups_dir = os.path.join(tmp_dir, "backups")
        archives_before = set(os.listdir(backups_dir)) if os.path.exists(backups_dir) else set()

        mine(project_path, palace_path, incremental=True)

        archives_after = set(os.listdir(backups_dir)) if os.path.exists(backups_dir) else set()
        new_archives = archives_after - archives_before
        assert not new_archives, f"no-op mine must not create archives, got: {new_archives}"

    def test_noop_mine_creates_no_kg_file(self, tmp_dir, monkeypatch):
        """AC-3: No-op mine must not create the palace-local KG SQLite file."""
        project_path, palace_path = self._make_project(tmp_dir)
        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

        mine(project_path, palace_path, incremental=True, kg=None)

        local_kg = palace_kg_path(palace_path)
        assert not os.path.exists(local_kg), "first mine (no kg arg) must not create KG"

        mine(project_path, palace_path, incremental=True, kg=None)

        assert not os.path.exists(local_kg), "no-op mine must not create KG file"

    def test_noop_mine_no_palace_disk_growth(self, tmp_dir, monkeypatch):
        """AC-3: Palace directory size must not grow between a real mine and a no-op mine."""
        project_path, palace_path = self._make_project(tmp_dir)
        monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")

        mine(project_path, palace_path, incremental=True)

        def _dir_bytes(path: str) -> int:
            total = 0
            for dirpath, _, filenames in os.walk(path):
                for fname in filenames:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fname))
                    except OSError:
                        pass
            return total

        size_before = _dir_bytes(palace_path)

        mine(project_path, palace_path, incremental=True)

        size_after = _dir_bytes(palace_path)
        assert size_after <= size_before, (
            f"no-op mine must not grow palace disk: before={size_before}, after={size_after}"
        )


# ─── AC-4: /tmp <-> /private/tmp macOS alias in reader ────────────────────────


class TestTmpPrivateTmpAlias:
    def test_tmp_alias_expands_to_private_tmp(self):
        """AC-4: _macos_var_aliases includes /private/tmp/... for /tmp/... input."""
        aliases = _macos_var_aliases("/tmp/foo/bar.py")
        assert "/tmp/foo/bar.py" in aliases
        assert "/private/tmp/foo/bar.py" in aliases

    def test_private_tmp_alias_expands_to_tmp(self):
        """AC-4: _macos_var_aliases includes /tmp/... for /private/tmp/... input."""
        aliases = _macos_var_aliases("/private/tmp/foo/bar.py")
        assert "/private/tmp/foo/bar.py" in aliases
        assert "/tmp/foo/bar.py" in aliases

    def test_tmp_alias_does_not_affect_other_paths(self):
        """AC-4: Non-/tmp paths produce only the original path in aliases."""
        aliases = _macos_var_aliases("/home/user/project/foo.py")
        assert aliases == {"/home/user/project/foo.py"}

    def test_tmp_and_var_aliases_are_distinct(self):
        """AC-4: /tmp and /var paths produce independent alias sets."""
        tmp_aliases = _macos_var_aliases("/tmp/foo/bar.py")
        var_aliases = _macos_var_aliases("/var/folders/baz.py")
        assert "/private/tmp/foo/bar.py" in tmp_aliases
        assert "/private/var/folders/baz.py" in var_aliases
        assert "/private/var/folders/baz.py" not in tmp_aliases

    def test_read_resolves_private_tmp_alias_to_tmp_stored(self, palace_path):
        """AC-4: read_slice resolves /private/tmp/... when palace stores /tmp/... source."""
        store = open_store(palace_path, create=True)
        stored_source = "/tmp/testdir/module.py"
        store.add(
            ids=["test_tmp_drawer"],
            documents=["line 1\nline 2\nline 3\n"],
            metadatas=[
                {
                    "wing": "test",
                    "room": "general",
                    "source_file": stored_source,
                    "chunk_index": 0,
                    "added_by": "test",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 3,
                }
            ],
        )

        # Read using the macOS /private/tmp spelling
        result = read_slice(store, "/private/tmp/testdir/module.py", 1, 3)
        assert "error" not in result, f"expected success, got: {result}"
        assert result["source_file"] == stored_source

    def test_read_resolves_tmp_alias_to_private_tmp_stored(self, palace_path):
        """AC-4: read_slice resolves /tmp/... when palace stores /private/tmp/... source."""
        store = open_store(palace_path, create=True)
        stored_source = "/private/tmp/testdir/module.py"
        store.add(
            ids=["test_private_tmp_drawer"],
            documents=["alpha\nbeta\ngamma\n"],
            metadatas=[
                {
                    "wing": "test",
                    "room": "general",
                    "source_file": stored_source,
                    "chunk_index": 0,
                    "added_by": "test",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 3,
                }
            ],
        )

        result = read_slice(store, "/tmp/testdir/module.py", 1, 3)
        assert "error" not in result, f"expected success, got: {result}"
        assert result["source_file"] == stored_source

    def test_read_rejects_traversal_through_tmp_alias(self, palace_path):
        """AC-4: /tmp alias does not weaken traversal safety — exact match is still required."""
        store = open_store(palace_path, create=True)
        store.add(
            ids=["safe_drawer"],
            documents=["safe content\n"],
            metadatas=[
                {
                    "wing": "test",
                    "room": "general",
                    "source_file": "/tmp/safe/module.py",
                    "chunk_index": 0,
                    "added_by": "test",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                }
            ],
        )

        # A query for /private/tmp/other/module.py must not match /tmp/safe/module.py
        result = read_slice(store, "/private/tmp/other/module.py", 1, 1)
        assert result.get("error") in ("not_found", "ambiguous_source"), (
            f"traversal-like query must not resolve to a different /tmp path, got: {result}"
        )


# ─── LazyKnowledgeGraph tests ──────────────────────────────────────────────────


class TestLazyKnowledgeGraph:
    def test_lazy_kg_does_not_create_db_on_construction(self, tmp_dir):
        """LazyKnowledgeGraph must not create the SQLite file until a method is called."""
        palace = os.path.join(tmp_dir, "lazy_palace")
        LazyKnowledgeGraph(palace)
        assert not os.path.exists(palace_kg_path(palace)), (
            "SQLite must not be created on construction"
        )

    def test_lazy_kg_creates_db_on_first_method_call(self, tmp_dir):
        """LazyKnowledgeGraph creates the palace SQLite file lazily on first access."""
        palace = os.path.join(tmp_dir, "lazy_palace")
        lkg = LazyKnowledgeGraph(palace)
        lkg.add_triple("A", "rel", "B")
        assert os.path.exists(palace_kg_path(palace)), "SQLite must exist after first method call"

    def test_lazy_kg_proxies_methods_to_real_kg(self, tmp_dir):
        """LazyKnowledgeGraph correctly proxies KG method calls."""
        lkg = LazyKnowledgeGraph(os.path.join(tmp_dir, "proxy_palace"))
        lkg.add_triple("Subject", "predicate", "Object")
        results = lkg.query_entity("Subject")
        assert any(r.get("object") == "Object" for r in results), (
            "lazy KG must proxy query_entity correctly"
        )
