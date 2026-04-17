"""
test_migrate.py — Tests for mempalace/migrate.py (ChromaDB → LanceDB migration).

Requires chromadb (mempalace[chroma] extra). The entire module is skipped when
chromadb is not installed so CI without the chroma extra stays green.
"""

import os

import pytest

pytest.importorskip("chromadb")

from mempalace.migrate import VerificationError, migrate_chroma_to_lance  # noqa: E402
from mempalace._chroma_store import ChromaStore  # noqa: E402
from mempalace.storage import LanceStore  # noqa: E402


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _seed_chroma(path: str, n_per_wing: int, wings: list[str]) -> int:
    """Create a ChromaDB palace and seed it with n_per_wing drawers per wing."""
    os.makedirs(path, exist_ok=True)
    store = ChromaStore(path, create=True)
    ids, docs, metas = [], [], []
    for wing in wings:
        for i in range(n_per_wing):
            ids.append(f"{wing}_{i}")
            docs.append(f"Content for {wing} drawer {i}. " * 5)
            metas.append({"wing": wing, "room": "general", "source_file": f"{wing}_{i}.md"})
    store.add(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


# ─── AC-1: Happy path ─────────────────────────────────────────────────────────


def test_migrate_chroma_to_lance_happy_path(tmp_path):
    """Migrate 50 drawers across 2 wings; both stores should end up with 50 rows."""
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")

    total = _seed_chroma(src, n_per_wing=25, wings=["wing_a", "wing_b"])
    assert total == 50

    src_count, dst_count = migrate_chroma_to_lance(src, dst, no_backup=True)

    assert src_count == 50
    assert dst_count == 50

    # Per-wing counts must match source.
    dst_store = LanceStore(dst, create=False)
    by_wing = dst_store.count_by("wing")
    assert by_wing.get("wing_a", 0) == 25
    assert by_wing.get("wing_b", 0) == 25


# ─── AC-2: Refuse non-empty destination ───────────────────────────────────────


def test_migrate_refuses_nonempty_dst(tmp_path):
    """Migration must raise RuntimeError if destination already has rows (no --force)."""
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")

    _seed_chroma(src, n_per_wing=10, wings=["wing_a"])

    # Pre-seed destination with 1 row.
    os.makedirs(dst, exist_ok=True)
    dst_store = LanceStore(dst, create=True)
    dst_store.add(
        ids=["pre_existing"],
        documents=["pre-existing content for testing collision guard"],
        metadatas=[{"wing": "wing_x", "room": "general"}],
    )
    assert dst_store.count() == 1

    with pytest.raises(RuntimeError, match="already contains rows"):
        migrate_chroma_to_lance(src, dst, no_backup=True)


# ─── AC-3: Force appends to non-empty destination ─────────────────────────────


def test_migrate_force_appends(tmp_path):
    """With force=True, dst count == src_count + pre_existing_dst_count."""
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")

    src_total = _seed_chroma(src, n_per_wing=10, wings=["wing_a", "wing_b"])
    assert src_total == 20

    # Pre-seed destination with 3 rows using different IDs.
    os.makedirs(dst, exist_ok=True)
    dst_store = LanceStore(dst, create=True)
    pre_existing = 3
    dst_store.add(
        ids=[f"pre_{i}" for i in range(pre_existing)],
        documents=[f"pre-existing content {i} in dst palace" for i in range(pre_existing)],
        metadatas=[{"wing": "wing_z", "room": "general"} for _ in range(pre_existing)],
    )
    assert dst_store.count() == pre_existing

    src_count, dst_count = migrate_chroma_to_lance(src, dst, force=True, no_backup=True)

    assert src_count == 20
    assert dst_count == src_total + pre_existing


# ─── AC-4: Backup created ─────────────────────────────────────────────────────


def test_migrate_backup_created(tmp_path):
    """A .tar.gz backup of the source palace should be created in backup_dir."""
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")
    backup_dir = str(tmp_path / "backups")

    _seed_chroma(src, n_per_wing=5, wings=["wing_a"])

    migrate_chroma_to_lance(src, dst, backup_dir=backup_dir, no_backup=False)

    assert os.path.isdir(backup_dir), "backup_dir was not created"
    tar_files = [f for f in os.listdir(backup_dir) if f.endswith(".tar.gz")]
    assert len(tar_files) == 1, f"Expected 1 .tar.gz, found: {tar_files}"
    assert tar_files[0].startswith("chroma-pre-migrate-")


# ─── AC-5: Verify catches mismatch ────────────────────────────────────────────


def test_migrate_verify_catches_mismatch(tmp_path):
    """
    When source and destination per-wing counts diverge, --verify raises VerificationError.

    Mismatch is engineered by pre-seeding dst with rows in wing_a (different IDs),
    then migrating with force=True. The accumulated src_wing_counts for wing_a (5) will
    not match the dst count for wing_a (5 src + 3 pre-existing = 8).
    """
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")

    _seed_chroma(src, n_per_wing=5, wings=["wing_a", "wing_b"])

    # Pre-seed dst with 3 extra rows in wing_a (different IDs → no collision).
    os.makedirs(dst, exist_ok=True)
    dst_store = LanceStore(dst, create=True)
    dst_store.add(
        ids=["extra_a_0", "extra_a_1", "extra_a_2"],
        documents=[
            "extra content alpha for mismatch test",
            "extra content beta for mismatch test",
            "extra content gamma for mismatch test",
        ],
        metadatas=[{"wing": "wing_a", "room": "general"} for _ in range(3)],
    )
    assert dst_store.count() == 3

    with pytest.raises(VerificationError, match="wing_a"):
        migrate_chroma_to_lance(src, dst, force=True, verify=True, no_backup=True)


# ─── AC-6: Empty source early-exit ───────────────────────────────────────────


def test_migrate_empty_src(tmp_path):
    """
    When the source collection exists but has no rows, migrate_chroma_to_lance
    should return (0, 0) without creating the destination directory.
    """
    src = str(tmp_path / "src")
    dst = str(tmp_path / "dst")

    # Seed then delete all rows so the collection exists but is empty.
    _seed_chroma(src, n_per_wing=3, wings=["wing_a"])
    src_store = ChromaStore(src, create=False)
    all_ids = src_store.get(include=["documents"])["ids"]
    assert len(all_ids) == 3
    src_store.delete(all_ids)
    assert src_store.count() == 0

    result = migrate_chroma_to_lance(src, dst, no_backup=True)

    assert result == (0, 0)
    assert not os.path.isdir(dst), "destination directory must not be created on early exit"
