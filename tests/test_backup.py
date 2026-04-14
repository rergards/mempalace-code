"""
tests/test_backup.py — Unit and integration tests for palace backup/restore.

Uses the shared fixtures from conftest.py:
  palace_path        — empty palace directory
  seeded_collection  — palace pre-loaded with 4 drawers (wing=project×2, notes×1, frontend×1)
  kg                 — isolated KnowledgeGraph at a temp SQLite path
  seeded_kg          — KG pre-loaded with triples
"""

import json
import os
import tarfile

import pytest

from mempalace.backup import create_backup, restore_backup
from mempalace.storage import open_store


# ── Helpers ────────────────────────────────────────────────────────────────────


def _archive_names(path: str) -> set:
    with tarfile.open(path, "r:gz") as tar:
        return {m.name for m in tar.getmembers()}


def _read_metadata(path: str) -> dict:
    with tarfile.open(path, "r:gz") as tar:
        member = tar.getmember("mempalace_backup/metadata.json")
        f = tar.extractfile(member)
        assert f is not None, "metadata.json is not a regular file in the archive"
        return json.loads(f.read().decode())


# ── create_backup ──────────────────────────────────────────────────────────────


def test_backup_creates_tarball(seeded_collection, palace_path, tmp_dir):
    out = os.path.join(tmp_dir, "test.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")  # non-existent → omitted
    create_backup(palace_path, out_path=out, kg_path=kg_path)

    assert os.path.isfile(out)
    names = _archive_names(out)
    assert "mempalace_backup/metadata.json" in names
    # At least one lance entry should be present
    assert any(n.startswith("mempalace_backup/lance") for n in names)


def test_backup_metadata_contents(seeded_collection, palace_path, tmp_dir):
    out = os.path.join(tmp_dir, "test.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    meta = create_backup(palace_path, out_path=out, kg_path=kg_path)

    # Returned dict
    assert meta["drawer_count"] == 4
    assert set(meta["wings"]) == {"project", "notes"}
    assert "timestamp" in meta
    assert meta["mempalace_version"]
    assert meta["backend_type"] == "lancedb"

    # Written metadata.json matches returned dict
    archived_meta = _read_metadata(out)
    assert archived_meta["drawer_count"] == meta["drawer_count"]
    assert archived_meta["wings"] == meta["wings"]
    assert archived_meta["backend_type"] == "lancedb"


def test_backup_without_kg(seeded_collection, palace_path, tmp_dir):
    """When KG file doesn't exist, backup succeeds and archive has no KG entry."""
    out = os.path.join(tmp_dir, "no_kg.tar.gz")
    kg_path = os.path.join(tmp_dir, "nonexistent.sqlite3")
    create_backup(palace_path, out_path=out, kg_path=kg_path)

    names = _archive_names(out)
    assert "mempalace_backup/knowledge_graph.sqlite3" not in names
    assert "mempalace_backup/metadata.json" in names


def test_backup_includes_kg_when_present(seeded_collection, palace_path, tmp_dir, seeded_kg):
    """When KG file exists, it should appear in the archive."""
    out = os.path.join(tmp_dir, "with_kg.tar.gz")
    create_backup(palace_path, out_path=out, kg_path=seeded_kg.db_path)

    names = _archive_names(out)
    assert "mempalace_backup/knowledge_graph.sqlite3" in names


def test_backup_default_out_path(seeded_collection, palace_path, tmp_dir, monkeypatch):
    """Default out_path is mempalace_backup_<ts>.tar.gz in CWD."""
    monkeypatch.chdir(tmp_dir)
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    meta = create_backup(palace_path, kg_path=kg_path)

    files = [
        f
        for f in os.listdir(tmp_dir)
        if f.startswith("mempalace_backup_") and f.endswith(".tar.gz")
    ]
    assert len(files) == 1
    assert meta["drawer_count"] == 4


# ── restore_backup ─────────────────────────────────────────────────────────────


def test_restore_to_empty_palace(seeded_collection, palace_path, tmp_dir):
    """Extract to a fresh path — lance/ directory should appear."""
    out = os.path.join(tmp_dir, "backup.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    create_backup(palace_path, out_path=out, kg_path=kg_path)

    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")
    restore_backup(out, restore_dir, kg_path=restore_kg)

    assert os.path.isdir(os.path.join(restore_dir, "lance"))


def test_restore_refuses_non_empty_without_force(seeded_collection, palace_path, tmp_dir):
    """Restore to a non-empty palace without --force raises FileExistsError."""
    out = os.path.join(tmp_dir, "backup.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    create_backup(palace_path, out_path=out, kg_path=kg_path)

    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")

    # First restore — succeeds
    restore_backup(out, restore_dir, kg_path=restore_kg)

    # Second restore — should refuse
    with pytest.raises(FileExistsError, match="--force"):
        restore_backup(out, restore_dir, force=False, kg_path=restore_kg)


def test_restore_with_force_overwrites(seeded_collection, palace_path, tmp_dir):
    """--force removes the existing lance/ and re-extracts cleanly."""
    out = os.path.join(tmp_dir, "backup.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    create_backup(palace_path, out_path=out, kg_path=kg_path)

    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")

    restore_backup(out, restore_dir, kg_path=restore_kg)
    # Should not raise with force=True
    restore_backup(out, restore_dir, force=True, kg_path=restore_kg)

    assert os.path.isdir(os.path.join(restore_dir, "lance"))


# ── Round-trip tests ───────────────────────────────────────────────────────────


def test_roundtrip_drawers(seeded_collection, palace_path, tmp_dir):
    """seed → backup → restore to new path → open_store → verify same drawer count and wings."""
    out = os.path.join(tmp_dir, "roundtrip.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    create_backup(palace_path, out_path=out, kg_path=kg_path)

    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")
    restore_backup(out, restore_dir, kg_path=restore_kg)

    restored_store = open_store(restore_dir, create=False)
    assert restored_store.count() == 4

    wings = set(restored_store.count_by("wing").keys())
    assert wings == {"project", "notes"}


def test_roundtrip_kg(seeded_kg, seeded_collection, palace_path, tmp_dir):
    """seed KG → backup → restore → query_entity → verify same triples."""
    out = os.path.join(tmp_dir, "roundtrip_kg.tar.gz")
    create_backup(palace_path, out_path=out, kg_path=seeded_kg.db_path)

    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restored_kg_path = os.path.join(tmp_dir, "restored_kg.sqlite3")
    restore_backup(out, restore_dir, kg_path=restored_kg_path)

    from mempalace.knowledge_graph import KnowledgeGraph

    restored_kg = KnowledgeGraph(db_path=restored_kg_path)
    triples = restored_kg.query_entity("Max")

    # seeded_kg: Max does swimming, Max does chess
    assert len(triples) == 2
    assert all(t["subject"] == "Max" for t in triples)
    predicates = {t["predicate"] for t in triples}
    assert predicates == {"does"}
    objects = {t["object"] for t in triples}
    assert objects == {"swimming", "chess"}
