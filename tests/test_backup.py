"""
tests/test_backup.py — Unit and integration tests for palace backup/restore.

Uses the shared fixtures from conftest.py:
  palace_path        — empty palace directory
  seeded_collection  — palace pre-loaded with 4 drawers (wing=project×2, notes×1, frontend×1)
  kg                 — isolated KnowledgeGraph at a temp SQLite path
  seeded_kg          — KG pre-loaded with triples
"""

import io
import json
import os
import plistlib
import shlex
import subprocess
import sys
import tarfile
import time
from argparse import Namespace
from unittest.mock import patch

import pytest

import mempalace_code.backup as backup_module
from mempalace_code.backup import (
    BackupArchiveError,
    create_backup,
    list_backups,
    render_schedule,
    restore_backup,
)
from mempalace_code.cli_commands.backup_restore import cmd_backup_schedule
from mempalace_code.storage import open_store

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


def _write_member(
    tar: tarfile.TarFile, name: str, member_type: bytes, content: bytes = b""
) -> None:
    """Add a single managed member of *member_type* to an open tar for abuse tests."""
    info = tarfile.TarInfo(name=name)
    info.type = member_type
    if member_type == tarfile.SYMTYPE:
        info.linkname = "/etc/passwd"
    elif member_type == tarfile.LNKTYPE:
        info.linkname = "mempalace_backup/metadata.json"
    elif member_type in (tarfile.CHRTYPE, tarfile.BLKTYPE):
        info.devmajor = 1
        info.devminor = 1
    if member_type == tarfile.REGTYPE:
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    else:
        tar.addfile(info)


def _build_malicious_archive(
    tmp_dir: str, archive_name: str, member_name: str, member_type: bytes, content: bytes = b""
) -> str:
    """Build a minimal .tar.gz archive containing one unsafe managed member."""
    out = os.path.join(tmp_dir, archive_name)
    with tarfile.open(out, "w:gz") as tar:
        meta_bytes = json.dumps({"drawer_count": 0, "wings": []}).encode()
        meta_info = tarfile.TarInfo(name="mempalace_backup/metadata.json")
        meta_info.size = len(meta_bytes)
        tar.addfile(meta_info, io.BytesIO(meta_bytes))
        _write_member(tar, member_name, member_type, content)
    return out


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
    meta, returned_out = create_backup(palace_path, out_path=out, kg_path=kg_path)
    assert returned_out == out

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


def test_backup_default_out_path(seeded_collection, palace_path, tmp_dir):
    """Default out_path is mempalace_backup_<ts>.tar.gz under <palace_parent>/backups/."""
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    meta, default_out = create_backup(palace_path, kg_path=kg_path)

    # palace_path = tmp_dir/palace, so palace_parent = tmp_dir
    backups_dir = os.path.join(tmp_dir, "backups")
    assert os.path.isdir(backups_dir), "backups/ directory should have been created"
    files = [
        f
        for f in os.listdir(backups_dir)
        if f.startswith("mempalace_backup_") and f.endswith(".tar.gz")
    ]
    assert len(files) == 1
    assert os.path.abspath(default_out) == os.path.abspath(os.path.join(backups_dir, files[0]))
    assert meta["drawer_count"] == 4


def test_backup_explicit_out_overrides_default(seeded_collection, palace_path, tmp_dir):
    """Explicit out_path still overrides the default backups/ directory (AC-14)."""
    explicit_out = os.path.join(tmp_dir, "custom_backup.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    meta, returned_out = create_backup(palace_path, out_path=explicit_out, kg_path=kg_path)
    assert returned_out == explicit_out
    assert os.path.isfile(explicit_out)


def test_backup_default_dir_has_restrictive_permissions(seeded_collection, palace_path, tmp_dir):
    """F-9: default backups/ directory is created with owner-only (0o700) permissions."""
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    create_backup(palace_path, kg_path=kg_path)
    backups_dir = os.path.join(tmp_dir, "backups")
    mode = os.stat(backups_dir).st_mode & 0o777
    assert mode == 0o700, f"Expected 0o700, got {oct(mode)}"


def test_backup_creates_missing_parent_dir(seeded_collection, palace_path, tmp_dir):
    """F-10: create_backup auto-creates missing parent directories for explicit --out."""
    nested = os.path.join(tmp_dir, "nested", "subdir", "backup.tar.gz")
    kg_path = os.path.join(tmp_dir, "kg.sqlite3")
    create_backup(palace_path, out_path=nested, kg_path=kg_path)
    assert os.path.isfile(nested)


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


def test_force_restore_copy_failure_preserves_existing_lance(
    seeded_collection, palace_path, tmp_dir
):
    out = os.path.join(tmp_dir, "backup.tar.gz")
    create_backup(palace_path, out_path=out, kg_path=os.path.join(tmp_dir, "source-kg"))
    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")
    restore_backup(out, restore_dir, kg_path=restore_kg)
    sentinel = os.path.join(restore_dir, "lance", "preserve.txt")
    with open(sentinel, "w", encoding="utf-8") as handle:
        handle.write("old state")

    with patch("mempalace_code.backup.shutil.copytree", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            restore_backup(out, restore_dir, force=True, kg_path=restore_kg)

    with open(sentinel, encoding="utf-8") as handle:
        assert handle.read() == "old state"
    assert not any(name.startswith(".mempalace-lance-") for name in os.listdir(restore_dir))


def test_force_restore_publish_failure_restores_existing_lance(
    seeded_collection, palace_path, tmp_dir
):
    out = os.path.join(tmp_dir, "backup.tar.gz")
    create_backup(palace_path, out_path=out, kg_path=os.path.join(tmp_dir, "source-kg"))
    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")
    restore_backup(out, restore_dir, kg_path=restore_kg)
    sentinel = os.path.join(restore_dir, "lance", "preserve.txt")
    with open(sentinel, "w", encoding="utf-8") as handle:
        handle.write("old state")
    real_replace = os.replace

    def fail_staged_publish(source, destination):
        if ".mempalace-lance-stage-" in str(source) and str(destination) == os.path.join(
            restore_dir, "lance"
        ):
            raise OSError("publish failed")
        return real_replace(source, destination)

    with patch("mempalace_code.backup.os.replace", side_effect=fail_staged_publish):
        with pytest.raises(OSError, match="publish failed"):
            restore_backup(out, restore_dir, force=True, kg_path=restore_kg)

    with open(sentinel, encoding="utf-8") as handle:
        assert handle.read() == "old state"
    assert not any(name.startswith(".mempalace-lance-") for name in os.listdir(restore_dir))


def test_force_restore_kg_publish_failure_restores_existing_lance_and_kg(
    seeded_collection, palace_path, tmp_dir
):
    source_kg = os.path.join(tmp_dir, "source-kg.sqlite3")
    with open(source_kg, "wb") as handle:
        handle.write(b"new kg")
    out = os.path.join(tmp_dir, "backup.tar.gz")
    create_backup(palace_path, out_path=out, kg_path=source_kg)

    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")
    restore_backup(out, restore_dir, kg_path=restore_kg)
    sentinel = os.path.join(restore_dir, "lance", "preserve.txt")
    with open(sentinel, "w", encoding="utf-8") as handle:
        handle.write("old lance")
    with open(restore_kg, "wb") as handle:
        handle.write(b"old kg")
    real_replace = os.replace

    def fail_kg_publish(source, destination):
        if str(destination) == restore_kg and str(source).endswith(".tmp"):
            raise OSError("kg publish failed")
        return real_replace(source, destination)

    with patch("mempalace_code.backup.os.replace", side_effect=fail_kg_publish):
        with pytest.raises(OSError, match="kg publish failed"):
            restore_backup(out, restore_dir, force=True, kg_path=restore_kg)

    with open(sentinel, encoding="utf-8") as handle:
        assert handle.read() == "old lance"
    with open(restore_kg, "rb") as handle:
        assert handle.read() == b"old kg"
    assert not any(name.startswith(".mempalace-lance-") for name in os.listdir(restore_dir))


def test_force_restore_rollback_failure_preserves_existing_lance_backup(
    seeded_collection, palace_path, tmp_dir
):
    source_kg = os.path.join(tmp_dir, "source-kg.sqlite3")
    with open(source_kg, "wb") as handle:
        handle.write(b"new kg")
    out = os.path.join(tmp_dir, "backup.tar.gz")
    create_backup(palace_path, out_path=out, kg_path=source_kg)

    restore_dir = os.path.join(tmp_dir, "restored_palace")
    restore_kg = os.path.join(tmp_dir, "restored_kg.sqlite3")
    restore_backup(out, restore_dir, kg_path=restore_kg)
    sentinel = os.path.join(restore_dir, "lance", "preserve.txt")
    with open(sentinel, "w", encoding="utf-8") as handle:
        handle.write("old lance")
    real_replace = os.replace

    def fail_kg_publish(source, destination):
        if str(destination) == restore_kg and str(source).endswith(".tmp"):
            raise OSError("kg publish failed")
        return real_replace(source, destination)

    with (
        patch("mempalace_code.backup.os.replace", side_effect=fail_kg_publish),
        patch("mempalace_code.backup._remove_owned_lance_dir", return_value=False),
        pytest.raises(RuntimeError, match="rollback failed.*prior state remains"),
    ):
        restore_backup(out, restore_dir, force=True, kg_path=restore_kg)

    backups = [
        os.path.join(restore_dir, name)
        for name in os.listdir(restore_dir)
        if name.startswith(".mempalace-lance-backup-")
    ]
    assert len(backups) == 1
    with open(os.path.join(backups[0], "lance", "preserve.txt"), encoding="utf-8") as handle:
        assert handle.read() == "old lance"


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

    from mempalace_code.knowledge_graph import KnowledgeGraph

    restored_kg = KnowledgeGraph(db_path=restored_kg_path)
    triples = restored_kg.query_entity("Max")

    # seeded_kg: Max does swimming, Max does chess
    assert len(triples) == 2
    assert all(t["subject"] == "Max" for t in triples)
    predicates = {t["predicate"] for t in triples}
    assert predicates == {"does"}
    objects = {t["object"] for t in triples}
    assert objects == {"swimming", "chess"}


# ── TestAutoBackupDefault ──────────────────────────────────────────────────────


class TestAutoBackupDefault:
    def test_default_is_true(self, tmp_dir):
        """AC-1: fresh MempalaceConfig() has backup_before_optimize=True."""
        from mempalace_code.config import MempalaceConfig

        cfg = MempalaceConfig(config_dir=os.path.join(tmp_dir, "cfg"))
        assert cfg.backup_before_optimize is True
        assert cfg.auto_backup_before_optimize is True
        assert cfg.backup_schedule == "off"

    def test_legacy_env_opt_out(self, tmp_dir, monkeypatch):
        """AC-2: MEMPALACE_BACKUP_BEFORE_OPTIMIZE=0 overrides flipped default → False."""
        from mempalace_code.config import MempalaceConfig

        monkeypatch.setenv("MEMPALACE_BACKUP_BEFORE_OPTIMIZE", "0")
        cfg = MempalaceConfig(config_dir=os.path.join(tmp_dir, "cfg"))
        assert cfg.backup_before_optimize is False

    def test_file_key_opt_out(self, tmp_dir):
        """AC-3: config.json with backup_before_optimize=false is honored."""
        import json as _json

        from mempalace_code.config import MempalaceConfig

        cfg_dir = os.path.join(tmp_dir, "cfg")
        os.makedirs(cfg_dir)
        with open(os.path.join(cfg_dir, "config.json"), "w") as f:
            _json.dump({"backup_before_optimize": False}, f)
        cfg = MempalaceConfig(config_dir=cfg_dir)
        assert cfg.backup_before_optimize is False

    def test_auto_alias_file_key(self, tmp_dir):
        """auto_backup_before_optimize file key takes precedence over backup_before_optimize."""
        import json as _json

        from mempalace_code.config import MempalaceConfig

        cfg_dir = os.path.join(tmp_dir, "cfg")
        os.makedirs(cfg_dir)
        # backup_before_optimize=false but auto_ key overrides to true
        with open(os.path.join(cfg_dir, "config.json"), "w") as f:
            _json.dump({"backup_before_optimize": False, "auto_backup_before_optimize": True}, f)
        cfg = MempalaceConfig(config_dir=cfg_dir)
        assert cfg.backup_before_optimize is True

    def test_auto_env_beats_legacy_env(self, tmp_dir, monkeypatch):
        """AC-12: MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE=1 wins over MEMPALACE_BACKUP_BEFORE_OPTIMIZE=0."""
        from mempalace_code.config import MempalaceConfig

        monkeypatch.setenv("MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE", "1")
        monkeypatch.setenv("MEMPALACE_BACKUP_BEFORE_OPTIMIZE", "0")
        cfg = MempalaceConfig(config_dir=os.path.join(tmp_dir, "cfg"))
        assert cfg.backup_before_optimize is True

    def test_backup_schedule_env_override(self, tmp_dir, monkeypatch):
        """MEMPALACE_BACKUP_SCHEDULE env var overrides the default 'off' value."""
        from mempalace_code.config import MempalaceConfig

        monkeypatch.setenv("MEMPALACE_BACKUP_SCHEDULE", "DAILY")
        cfg = MempalaceConfig(config_dir=os.path.join(tmp_dir, "cfg"))
        # env value is lowercased
        assert cfg.backup_schedule == "daily"

    def test_backup_schedule_file_key(self, tmp_dir):
        """backup_schedule file key is honored when env var is absent."""
        import json as _json

        from mempalace_code.config import MempalaceConfig

        cfg_dir = os.path.join(tmp_dir, "cfg")
        os.makedirs(cfg_dir)
        with open(os.path.join(cfg_dir, "config.json"), "w") as f:
            _json.dump({"backup_schedule": "weekly"}, f)
        cfg = MempalaceConfig(config_dir=cfg_dir)
        assert cfg.backup_schedule == "weekly"

    def test_backup_retain_count_default(self, tmp_dir):
        """backup_retain_count defaults to 0, which disables pruning."""
        from mempalace_code.config import MempalaceConfig

        cfg = MempalaceConfig(config_dir=os.path.join(tmp_dir, "cfg"))
        assert cfg.backup_retain_count == 0

    def test_backup_retain_count_file_key(self, tmp_dir):
        """backup_retain_count file key is honored when env var is absent."""
        import json as _json

        from mempalace_code.config import MempalaceConfig

        cfg_dir = os.path.join(tmp_dir, "cfg")
        os.makedirs(cfg_dir)
        with open(os.path.join(cfg_dir, "config.json"), "w") as f:
            _json.dump({"backup_retain_count": 2}, f)
        cfg = MempalaceConfig(config_dir=cfg_dir)
        assert cfg.backup_retain_count == 2

    def test_backup_retain_count_env_overrides_file(self, tmp_dir, monkeypatch):
        """AC-5: MEMPALACE_BACKUP_RETAIN_COUNT wins over backup_retain_count."""
        import json as _json

        from mempalace_code.config import MempalaceConfig

        cfg_dir = os.path.join(tmp_dir, "cfg")
        os.makedirs(cfg_dir)
        with open(os.path.join(cfg_dir, "config.json"), "w") as f:
            _json.dump({"backup_retain_count": 1}, f)

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "3")
        cfg = MempalaceConfig(config_dir=cfg_dir)
        assert cfg.backup_retain_count == 3

    @pytest.mark.parametrize("env_value", ["", "not-a-number", "-1"])
    def test_backup_retain_count_invalid_env_disables_retention(
        self, tmp_dir, monkeypatch, env_value
    ):
        """Invalid or negative env values fall back to disabled retention."""
        from mempalace_code.config import MempalaceConfig

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", env_value)
        cfg = MempalaceConfig(config_dir=os.path.join(tmp_dir, "cfg"))
        assert cfg.backup_retain_count == 0


# ── TestListBackups ────────────────────────────────────────────────────────────


class TestListBackups:
    def test_empty_no_backups_dir(self, palace_path, tmp_dir):
        """AC-5 variant: list_backups() returns [] when backups/ doesn't exist."""
        result = list_backups(palace_path)
        assert result == []

    def test_lists_all_kinds(self, seeded_collection, palace_path, tmp_dir):
        """AC-4: archives of all three kinds are listed with correct kind field."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        # Create three archives with different name prefixes
        pre_opt_path = os.path.join(backups_dir, "pre_optimize_20260101_120000.tar.gz")
        manual_path = os.path.join(backups_dir, "mempalace_backup_20260101_110000.tar.gz")
        scheduled_path = os.path.join(backups_dir, "scheduled_20260101_100000.tar.gz")

        create_backup(palace_path, out_path=pre_opt_path, kg_path=kg_path)
        time.sleep(0.01)
        create_backup(palace_path, out_path=manual_path, kg_path=kg_path)
        time.sleep(0.01)
        create_backup(palace_path, out_path=scheduled_path, kg_path=kg_path)

        result = list_backups(palace_path)
        assert len(result) == 3

        kinds = {e["kind"] for e in result}
        assert kinds == {"pre_optimize", "manual", "scheduled"}

        for e in result:
            assert e["drawer_count"] == 4
            assert e["wings"] is not None

    def test_newest_first_ordering(self, seeded_collection, palace_path, tmp_dir):
        """list_backups returns entries sorted newest mtime first."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        path_a = os.path.join(backups_dir, "mempalace_backup_a.tar.gz")
        path_b = os.path.join(backups_dir, "mempalace_backup_b.tar.gz")
        create_backup(palace_path, out_path=path_a, kg_path=kg_path)
        time.sleep(0.05)
        create_backup(palace_path, out_path=path_b, kg_path=kg_path)

        result = list_backups(palace_path)
        assert len(result) == 2
        assert result[0]["path"] == os.path.abspath(path_b)
        assert result[1]["path"] == os.path.abspath(path_a)

    def test_missing_metadata_tolerated(self, palace_path, tmp_dir):
        """Archives without metadata.json still appear in the list (drawer_count=None)."""
        import io as _io
        import tarfile as _tarfile

        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        archive_path = os.path.join(backups_dir, "mempalace_backup_nometa.tar.gz")

        # Create a minimal tar.gz with no metadata.json
        with _tarfile.open(archive_path, "w:gz") as tar:
            data = b"placeholder"
            info = _tarfile.TarInfo(name="mempalace_backup/dummy.txt")
            info.size = len(data)
            tar.addfile(info, _io.BytesIO(data))

        result = list_backups(palace_path)
        assert len(result) == 1
        assert result[0]["drawer_count"] is None
        assert result[0]["wings"] == []

    def test_corrupted_archive_skipped(self, palace_path, tmp_dir):
        """Unreadable archives are logged and skipped."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        bad_path = os.path.join(backups_dir, "mempalace_backup_bad.tar.gz")

        with open(bad_path, "wb") as f:
            f.write(b"not a valid tar.gz")

        result = list_backups(palace_path)
        assert result == []

    def test_extra_dir_merges_results(self, seeded_collection, palace_path, tmp_dir):
        """--dir flag includes archives from an extra directory."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        extra_dir = os.path.join(tmp_dir, "legacy_backups")
        os.makedirs(extra_dir)

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        main_arch = os.path.join(backups_dir, "mempalace_backup_main.tar.gz")
        extra_arch = os.path.join(extra_dir, "mempalace_backup_extra.tar.gz")

        create_backup(palace_path, out_path=main_arch, kg_path=kg_path)
        create_backup(palace_path, out_path=extra_arch, kg_path=kg_path)

        result = list_backups(palace_path, extra_dir=extra_dir)
        paths = {e["path"] for e in result}
        assert os.path.abspath(main_arch) in paths
        assert os.path.abspath(extra_arch) in paths

    def test_extra_dir_deduplicates(self, seeded_collection, palace_path, tmp_dir):
        """Passing backups_dir as extra_dir does not duplicate entries."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        create_backup(palace_path, kg_path=kg_path)

        result_no_extra = list_backups(palace_path)
        result_with_same = list_backups(palace_path, extra_dir=backups_dir)
        assert len(result_no_extra) == len(result_with_same)


# ── TestRenderSchedule ─────────────────────────────────────────────────────────


class TestRenderSchedule:
    _BIN = "/usr/local/bin/mempalace"

    def test_darwin_daily(self, palace_path, tmp_dir):
        """AC-7: darwin daily emits plist with StartCalendarInterval Hour=3, Minute=0."""
        out = render_schedule("daily", palace_path, "darwin", mempalace_bin=self._BIN)
        assert "<?xml" in out
        assert "StartCalendarInterval" in out
        assert "<integer>3</integer>" in out  # Hour=3
        assert "<integer>0</integer>" in out  # Minute=0
        assert "Weekday" not in out
        assert self._BIN in out
        # AC-6: new schedule format uses --kind scheduled --palace rather than --out $(date...)
        assert "backup create --kind scheduled" in out
        assert "--palace" in out
        assert os.path.abspath(palace_path) in out
        assert "$(date" not in out

    def test_darwin_weekly(self, palace_path):
        """darwin weekly adds Weekday=0 to StartCalendarInterval."""
        out = render_schedule("weekly", palace_path, "darwin", mempalace_bin=self._BIN)
        assert "StartCalendarInterval" in out
        assert "Weekday" in out
        assert "<integer>0</integer>" in out

    def test_darwin_hourly(self, palace_path):
        """AC: darwin hourly emits StartInterval=3600 (not StartCalendarInterval)."""
        out = render_schedule("hourly", palace_path, "darwin", mempalace_bin=self._BIN)
        assert "StartInterval" in out
        assert "3600" in out
        assert "StartCalendarInterval" not in out

    def test_linux_daily(self, palace_path, tmp_dir):
        """AC-8: linux daily emits cron line matching ^0 3 * * * pattern."""
        import re

        out = render_schedule("daily", palace_path, "linux", mempalace_bin=self._BIN)
        assert re.match(r"^0\s+3\s+\*\s+\*\s+\*\s+", out)
        assert self._BIN in out
        assert "backup" in out
        assert "create" in out
        # AC-6: new schedule format uses --kind scheduled --palace rather than --out $(date...)
        assert "backup create --kind scheduled" in out
        assert "--palace" in out
        assert os.path.abspath(palace_path) in out
        assert "$(date" not in out

    def test_linux_weekly(self, palace_path):
        """linux weekly: cron line with dow=0."""
        import re

        out = render_schedule("weekly", palace_path, "linux", mempalace_bin=self._BIN)
        assert re.match(r"^0\s+3\s+\*\s+\*\s+0\s+", out)

    def test_linux_hourly(self, palace_path):
        """linux hourly: cron line '0 * * * *'."""
        import re

        out = render_schedule("hourly", palace_path, "linux", mempalace_bin=self._BIN)
        assert re.match(r"^0\s+\*\s+\*\s+\*\s+\*\s+", out)

    def test_invalid_freq_raises(self, palace_path):
        with pytest.raises(ValueError, match="Unsupported freq"):
            render_schedule("monthly", palace_path, "linux", mempalace_bin=self._BIN)

    def test_invalid_platform_raises(self, palace_path):
        with pytest.raises(ValueError, match="Unsupported platform"):
            render_schedule("daily", palace_path, "windows", mempalace_bin=self._BIN)

    def test_cron_bin_with_spaces_is_shell_quoted(self, palace_path):
        """F-8: shell-quoting applied to binary path with spaces in cron snippet."""
        bin_with_space = "/home/user/my apps/mempalace"
        out = render_schedule("daily", palace_path, "linux", mempalace_bin=bin_with_space)
        assert shlex.quote(bin_with_space) in out

    def test_plist_bin_with_spaces_is_shell_quoted(self, palace_path):
        """F-8: shell-quoting applied to binary path with spaces in launchd plist."""
        bin_with_space = "/home/user/my apps/mempalace"
        out = render_schedule("daily", palace_path, "darwin", mempalace_bin=bin_with_space)
        assert shlex.quote(bin_with_space) in out

    @pytest.mark.parametrize("platform", ["linux", "darwin"])
    def test_rendered_command_executes_launcher_and_preserves_arguments(self, tmp_path, platform):
        launcher = tmp_path / "launcher ; path" / "mempalace-code"
        palace = tmp_path / "palace ; path"
        record = tmp_path / "recorded argv"
        launcher.parent.mkdir()
        launcher.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$@\" > {shlex.quote(str(record))}\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)

        snippet = render_schedule("daily", str(palace), platform, mempalace_bin=str(launcher))
        if platform == "linux":
            command = snippet.rstrip().split(maxsplit=5)[5]
            subprocess.run(["/bin/sh", "-c", command], check=True)
        else:
            arguments = plistlib.loads(snippet.encode())["ProgramArguments"]
            subprocess.run(arguments, check=True)

        assert record.read_text(encoding="utf-8").splitlines() == [
            "--palace",
            str(palace.resolve()),
            "backup",
            "create",
            "--kind",
            "scheduled",
        ]

    def test_default_bin_falls_back_to_mempalace_code_module(self, palace_path, monkeypatch):
        """Packaged docs and generated schedules must use the renamed import module."""
        monkeypatch.setattr("shutil.which", lambda _name: None)

        out = render_schedule("daily", palace_path, "linux")

        # --palace must precede the 'backup' subcommand because it is a top-level argparse arg
        assert f"{shlex.quote(sys.executable)} -m mempalace_code --palace " in out
        assert "backup create" in out
        assert "-m mempalace backup" not in out

    def test_invoked_launcher_precedes_conflicting_path(self, palace_path, tmp_path, monkeypatch):
        invoked_dir = tmp_path / "invoked bin"
        ambient_dir = tmp_path / "ambient-bin"
        invoked_dir.mkdir()
        ambient_dir.mkdir()
        invoked = invoked_dir / "mempalace-code"
        ambient = ambient_dir / "mempalace-code"
        for executable in (invoked, ambient):
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        monkeypatch.setenv("PATH", str(ambient_dir))
        monkeypatch.setattr(sys, "argv", [str(invoked), "backup", "schedule"])

        out = render_schedule("daily", palace_path, "linux")

        assert shlex.quote(str(invoked)) in out
        assert str(ambient) not in out

    def test_command_handler_reuses_selected_launcher_in_deterministic_guidance(
        self, tmp_path, monkeypatch, capsys
    ):
        invoked_dir = tmp_path / "invoked bin"
        ambient_dir = tmp_path / "ambient-bin"
        home = tmp_path / "home with spaces"
        for directory in (invoked_dir, ambient_dir, home):
            directory.mkdir()
        invoked = invoked_dir / "mempalace-code"
        ambient = ambient_dir / "mempalace-code"
        for executable in (invoked, ambient):
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        palace = tmp_path / "palace ; quoted"
        args = Namespace(palace=str(palace), freq="daily", install=False)
        monkeypatch.setenv("PATH", str(ambient_dir))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(sys, "argv", [str(invoked), "backup", "schedule"])
        before = tuple(sorted(tmp_path.rglob("*")))

        cmd_backup_schedule(args)
        first = capsys.readouterr()
        cmd_backup_schedule(args)
        second = capsys.readouterr()

        assert first == second
        assert shlex.quote(str(invoked)) in first.out
        assert shlex.quote(str(invoked)) in first.err
        assert str(ambient) not in first.out + first.err
        assert shlex.quote(str(palace.resolve())) in first.out + first.err
        assert "--freq daily" in first.err
        assert (
            shlex.quote(str(home / "Library/LaunchAgents/com.mempalace.backup.plist")) in first.err
        )
        assert tuple(sorted(tmp_path.rglob("*"))) == before

    def test_install_refusal_names_selected_launcher_and_explicit_targets(
        self, tmp_path, monkeypatch, capsys
    ):
        invoked = tmp_path / "bin with spaces" / "mempalace-code"
        invoked.parent.mkdir()
        invoked.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        invoked.chmod(0o755)
        palace = tmp_path / "palace with spaces"
        monkeypatch.setattr(sys, "argv", [str(invoked), "backup", "schedule"])

        with pytest.raises(SystemExit) as exc_info:
            cmd_backup_schedule(Namespace(palace=str(palace), freq="weekly", install=True))

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert shlex.quote(str(invoked)) in captured.err
        assert shlex.quote(str(palace.resolve())) in captured.err
        assert "--freq weekly" in captured.err
        assert "com.mempalace.backup.plist" in captured.err

    def test_missing_dedicated_sibling_refuses_before_emitting_snippet(
        self, tmp_path, monkeypatch, capsys
    ):
        invoked = tmp_path / "invoked-bin" / "mempalace-code-alias"
        ambient = tmp_path / "ambient-bin" / "mempalace-code"
        invoked.parent.mkdir()
        ambient.parent.mkdir()
        for executable in (invoked, ambient):
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        monkeypatch.setenv("PATH", str(ambient.parent))
        monkeypatch.setattr(sys, "argv", [str(invoked), "backup", "schedule"])

        with pytest.raises(SystemExit) as exc_info:
            cmd_backup_schedule(
                Namespace(palace=str(tmp_path / "palace"), freq="daily", install=False)
            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "cannot find executable sibling" in captured.err
        assert str(ambient) not in captured.err

    def test_render_schedule_kind_scheduled_darwin(self, palace_path):
        """AC-6: darwin schedule contains '--kind scheduled', does not contain '$(date'."""
        out = render_schedule("daily", palace_path, "darwin", mempalace_bin=self._BIN)
        assert "backup create --kind scheduled" in out
        assert "$(date" not in out
        assert "--palace" in out
        assert os.path.abspath(palace_path) in out

    def test_render_schedule_kind_scheduled_linux(self, palace_path):
        """AC-6: linux schedule contains '--kind scheduled', does not contain '$(date'."""
        out = render_schedule("daily", palace_path, "linux", mempalace_bin=self._BIN)
        assert "backup create --kind scheduled" in out
        assert "$(date" not in out
        assert "--palace" in out
        assert os.path.abspath(palace_path) in out

    def test_rendered_linux_command_parses_via_argparse(self, palace_path):
        """Regression guard: the rendered cron command must be a valid mempalace-code invocation.

        ``--palace`` is a top-level argparse argument and must precede the ``backup``
        subcommand; placing it after the subcommand causes argparse to reject the
        command at runtime.  The previous schedule format (``--out $(date ...)``)
        masked this constraint because it never used ``--palace`` at all.
        """
        import argparse as _argparse

        out = render_schedule("daily", palace_path, "linux", mempalace_bin=self._BIN)
        # Cron line layout: [min, hour, dom, month, dow, bin, *args]
        tokens = shlex.split(out.strip())
        args_after_bin = tokens[6:]

        # Mirror the real top-level + backup-create subparser shape.
        parser = _argparse.ArgumentParser()
        parser.add_argument("--palace", default=None)
        sub = parser.add_subparsers(dest="command")
        backup_p = sub.add_parser("backup")
        backup_sub = backup_p.add_subparsers(dest="backup_command")
        create_p = backup_sub.add_parser("create")
        create_p.add_argument("--out", default=None)
        create_p.add_argument(
            "--kind", choices=["manual", "scheduled", "pre_optimize"], default="manual"
        )

        try:
            ns = parser.parse_args(args_after_bin)
        except SystemExit:
            raise AssertionError(f"Rendered command does not parse: {args_after_bin!r}") from None

        assert ns.palace == os.path.abspath(palace_path)
        assert ns.command == "backup"
        assert ns.backup_command == "create"
        assert ns.kind == "scheduled"


# ── TestManagedRetention ────────────────────────────────────────────────────────


class TestManagedRetention:
    """AC-1, AC-2: Per-kind retention via create_backup."""

    def test_scheduled_retain_1_keeps_only_newest(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-1: MEMPALACE_BACKUP_RETAIN_COUNT=1 leaves only the newest scheduled archive."""
        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        paths_created = []
        for _ in range(3):
            _, out = create_backup(palace_path, kind="scheduled", kg_path=kg_path)
            paths_created.append(os.path.abspath(out))
            time.sleep(0.05)

        backups_dir = os.path.join(tmp_dir, "backups")
        remaining = [
            os.path.join(backups_dir, f)
            for f in os.listdir(backups_dir)
            if f.startswith("scheduled_") and f.endswith(".tar.gz")
        ]
        assert len(remaining) == 1
        assert os.path.abspath(remaining[0]) == paths_created[-1]

    def test_scheduled_retain_0_keeps_all(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """Retain count 0 disables pruning — all archives survive."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "0")

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        # Use fake timestamps to ensure unique filenames despite fast execution
        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            _dt(2026, 1, 1, 12, 0, 0),
            _dt(2026, 1, 1, 12, 0, 0),  # 2nd call (metadata timestamp)
            _dt(2026, 1, 1, 12, 0, 1),
            _dt(2026, 1, 1, 12, 0, 1),
            _dt(2026, 1, 1, 12, 0, 2),
            _dt(2026, 1, 1, 12, 0, 2),
        ]
        with patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(3):
                create_backup(palace_path, kind="scheduled", kg_path=kg_path)

        backups_dir = os.path.join(tmp_dir, "backups")
        remaining = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("scheduled_") and f.endswith(".tar.gz")
        ]
        assert len(remaining) == 3

    def test_pre_optimize_retain_2(self, palace_path, tmp_dir, monkeypatch):
        """AC-2: retain_count=2 after three safe_optimize cycles leaves 2 newest pre_optimize archives."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "2")

        store = open_store(palace_path, create=True)
        store.add(
            ids=["d1"],
            documents=["retention pre_optimize test document"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        # Use fake timestamps to ensure unique filenames despite fast execution
        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            _dt(2026, 1, 1, 12, 0, 0),
            _dt(2026, 1, 1, 12, 0, 0),  # 2nd call (metadata timestamp)
            _dt(2026, 1, 1, 12, 0, 1),
            _dt(2026, 1, 1, 12, 0, 1),
            _dt(2026, 1, 1, 12, 0, 2),
            _dt(2026, 1, 1, 12, 0, 2),
        ]
        with patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(3):
                ok = store.safe_optimize(palace_path, backup_first=True)  # type: ignore[reportAttributeAccessIssue]  # reason: LanceStore implements SafeOptimizeStore.safe_optimize; confirmed by fixture setup
                assert ok

        backups_dir = os.path.join(tmp_dir, "backups")
        archives = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("pre_optimize_") and f.endswith(".tar.gz")
        ]
        assert len(archives) == 2

    def test_pre_optimize_retain_0_keeps_all(self, palace_path, tmp_dir, monkeypatch):
        """AC-2: retain_count=0 disables pruning for pre_optimize archives."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "0")

        store = open_store(palace_path, create=True)
        store.add(
            ids=["d2"],
            documents=["retention zero pre_optimize test document"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        # Use fake timestamps to ensure unique filenames despite fast execution
        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            _dt(2026, 1, 1, 12, 1, 0),
            _dt(2026, 1, 1, 12, 1, 0),
            _dt(2026, 1, 1, 12, 1, 1),
            _dt(2026, 1, 1, 12, 1, 1),
            _dt(2026, 1, 1, 12, 1, 2),
            _dt(2026, 1, 1, 12, 1, 2),
        ]
        with patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(3):
                ok = store.safe_optimize(palace_path, backup_first=True)  # type: ignore[reportAttributeAccessIssue]  # reason: LanceStore implements SafeOptimizeStore.safe_optimize; confirmed by fixture setup
                assert ok

        backups_dir = os.path.join(tmp_dir, "backups")
        archives = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("pre_optimize_") and f.endswith(".tar.gz")
        ]
        assert len(archives) == 3

    def test_retention_does_not_prune_other_kinds(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """Scheduled retention only prunes scheduled archives, not manual ones."""
        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")

        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        # Create a manual archive that should not be pruned
        manual_path = os.path.join(backups_dir, "mempalace_backup_sentinel.tar.gz")
        create_backup(palace_path, out_path=manual_path, kg_path=kg_path)

        # Create 2 scheduled archives — only newest should survive
        for _ in range(2):
            create_backup(palace_path, kind="scheduled", kg_path=kg_path)
            time.sleep(0.05)

        scheduled = [f for f in os.listdir(backups_dir) if f.startswith("scheduled_")]
        manual = [f for f in os.listdir(backups_dir) if f.startswith("mempalace_backup_")]
        assert len(scheduled) == 1
        assert len(manual) == 1  # manual sentinel untouched

    def test_explicit_out_path_does_not_trigger_retention(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """Archives created with explicit --out do not trigger per-kind retention."""
        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")

        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        # Create archives directly in backups_dir via explicit paths — no retention
        for i in range(3):
            path = os.path.join(backups_dir, f"scheduled_explicit_{i:03d}.tar.gz")
            create_backup(palace_path, out_path=path, kind="scheduled", kg_path=kg_path)

        remaining = [f for f in os.listdir(backups_dir) if f.startswith("scheduled_explicit_")]
        assert len(remaining) == 3  # all survive — explicit paths skip retention

    def test_prune_managed_backups_tied_mtime_keeps_newest_filename(self, tmp_dir):
        """When archives share an mtime, the secondary sort key must keep the newest filename.

        Each managed prefix embeds a sortable YYYYMMDD_HHMMSS timestamp, so among
        same-mtime ties we must retain the lexicographically highest filename
        (newest embedded timestamp), not the lowest.
        """
        from mempalace_code.backup import prune_managed_backups

        backups_dir = os.path.join(tmp_dir, "managed")
        os.makedirs(backups_dir, exist_ok=True)
        names = [
            "scheduled_20260101_120000.tar.gz",
            "scheduled_20260101_120001.tar.gz",
            "scheduled_20260101_120002.tar.gz",
        ]
        # Create files with identical mtimes
        fixed_ts = 1_700_000_000.0
        for name in names:
            fpath = os.path.join(backups_dir, name)
            with open(fpath, "wb") as f:
                f.write(b"stub")
            os.utime(fpath, (fixed_ts, fixed_ts))

        deleted = prune_managed_backups(backups_dir, "scheduled", retain_count=1)

        remaining = sorted(os.listdir(backups_dir))
        assert remaining == ["scheduled_20260101_120002.tar.gz"], (
            f"expected newest-named archive to survive on mtime tie, got {remaining}; "
            f"deleted={deleted}"
        )

    def test_prune_managed_backups_handles_concurrent_disappearance(
        self, tmp_dir, monkeypatch, caplog
    ):
        """A concurrently removed candidate is quiet; other unlink failures still warn."""
        original_unlink = os.unlink

        def create_candidates(directory):
            os.makedirs(directory)
            retained = os.path.join(directory, "scheduled_20260101_120001.tar.gz")
            stale = os.path.join(directory, "scheduled_20260101_120000.tar.gz")
            for path in (retained, stale):
                with open(path, "wb") as archive:
                    archive.write(b"stub")
                os.utime(path, (1_700_000_000.0, 1_700_000_000.0))
            return retained, stale

        disappeared_dir = os.path.join(tmp_dir, "disappeared")
        disappeared_retained, disappeared_stale = create_candidates(disappeared_dir)

        def disappear_then_unlink(path):
            original_unlink(path)
            raise FileNotFoundError(path)

        with monkeypatch.context() as patch_context:
            patch_context.setattr(backup_module.os, "unlink", disappear_then_unlink)
            disappeared = backup_module.prune_managed_backups(
                disappeared_dir, "scheduled", retain_count=1
            )

        assert disappeared == []
        assert os.path.isfile(disappeared_retained)
        assert not os.path.exists(disappeared_stale)
        assert not any("Backup pruning failed" in message for message in caplog.messages)

        caplog.clear()
        denied_dir = os.path.join(tmp_dir, "denied")
        denied_retained, denied_stale = create_candidates(denied_dir)

        def deny_unlink(path):
            raise PermissionError(path)

        with monkeypatch.context() as patch_context:
            patch_context.setattr(backup_module.os, "unlink", deny_unlink)
            denied = backup_module.prune_managed_backups(denied_dir, "scheduled", retain_count=1)

        assert denied == []
        assert os.path.isfile(denied_retained)
        assert os.path.isfile(denied_stale)
        pruning_failures = [
            message for message in caplog.messages if "Backup pruning failed" in message
        ]
        assert len(pruning_failures) == 1
        assert denied_stale in pruning_failures[0]

    def test_default_scheduled_retention_prunes_to_bound(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-4: 15 managed scheduled backups leave only the newest 14 by default."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock, patch

        monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        fake_datetime = MagicMock()
        # 15 archives × 2 datetime.now() calls each (filename ts + metadata ts)
        fake_datetime.now.side_effect = [
            ts for i in range(15) for ts in (_dt(2026, 1, 1, 12, 0, i), _dt(2026, 1, 1, 12, 0, i))
        ]
        with patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(15):
                create_backup(palace_path, kind="scheduled", kg_path=kg_path)

        backups_dir = os.path.join(tmp_dir, "backups")
        remaining = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("scheduled_") and f.endswith(".tar.gz")
        ]
        assert len(remaining) == 14, (
            f"expected 14 archives after default prune, got {len(remaining)}"
        )

    def test_default_scheduled_retain_0_keeps_all(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-2: explicit backup_retain_count=0 keeps all scheduled archives unbounded."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "0")
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            ts for i in range(15) for ts in (_dt(2026, 1, 1, 13, 0, i), _dt(2026, 1, 1, 13, 0, i))
        ]
        with patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(15):
                create_backup(palace_path, kind="scheduled", kg_path=kg_path)

        backups_dir = os.path.join(tmp_dir, "backups")
        remaining = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("scheduled_") and f.endswith(".tar.gz")
        ]
        assert len(remaining) == 15, (
            f"expected all 15 kept with retain_count=0, got {len(remaining)}"
        )

    def test_explicit_scheduled_retain_3_keeps_three(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-3: explicit backup_retain_count=3 keeps only newest 3 scheduled archives."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock, patch

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "3")
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            ts for i in range(5) for ts in (_dt(2026, 1, 1, 14, 0, i), _dt(2026, 1, 1, 14, 0, i))
        ]
        with patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(5):
                create_backup(palace_path, kind="scheduled", kg_path=kg_path)

        backups_dir = os.path.join(tmp_dir, "backups")
        remaining = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("scheduled_") and f.endswith(".tar.gz")
        ]
        assert len(remaining) == 3, f"expected 3 archives with retain_count=3, got {len(remaining)}"

    def test_explicit_out_path_does_not_trigger_scheduled_default_retention(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-6: explicit --out archives bypass the implicit scheduled retention of 14."""
        monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)

        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        for i in range(16):
            path = os.path.join(backups_dir, f"scheduled_explicit_{i:03d}.tar.gz")
            create_backup(palace_path, out_path=path, kind="scheduled", kg_path=kg_path)

        remaining = [f for f in os.listdir(backups_dir) if f.startswith("scheduled_explicit_")]
        assert len(remaining) == 16, (
            "explicit-path archives must not be pruned by managed retention"
        )


# ── TestDiskPreflight ───────────────────────────────────────────────────────────


class TestDiskPreflight:
    """AC-3, AC-4: Disk-space guard in create_backup."""

    def test_rejection_one_byte_below_threshold(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-3: backup fails with DiskBudgetError when one byte below threshold."""
        import shutil as _shutil

        from mempalace_code.disk_budget import DiskBudgetError, palace_footprint

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        estimated, _ = palace_footprint(palace_path)
        min_free = 1024
        monkeypatch.setenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", str(min_free))

        class _FakeDU:
            total = 10 * 1024**3
            used = 5 * 1024**3
            free = estimated + min_free - 1  # one byte short

        monkeypatch.setattr(_shutil, "disk_usage", lambda _: _FakeDU())

        backups_dir = os.path.join(tmp_dir, "backups")
        with pytest.raises(DiskBudgetError, match="disk budget"):
            create_backup(palace_path, kg_path=kg_path)

        if os.path.isdir(backups_dir):
            assert not any(f.endswith(".tar.gz") for f in os.listdir(backups_dir))

    def test_passes_at_exact_threshold(self, seeded_collection, palace_path, tmp_dir, monkeypatch):
        """AC-4: at exactly estimated + min_free bytes available, backup succeeds."""
        import shutil as _shutil

        from mempalace_code.disk_budget import palace_footprint

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        estimated, _ = palace_footprint(palace_path)
        min_free = 1024
        monkeypatch.setenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", str(min_free))

        class _FakeDU:
            total = 10 * 1024**3
            used = 5 * 1024**3
            free = estimated + min_free  # exactly at boundary

        monkeypatch.setattr(_shutil, "disk_usage", lambda _: _FakeDU())

        meta, out = create_backup(palace_path, kg_path=kg_path)
        assert os.path.isfile(out)
        with tarfile.open(out, "r:gz") as tar:
            names = {m.name for m in tar.getmembers()}
        assert "mempalace_backup/metadata.json" in names

    def test_disabled_with_min_free_zero(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-4: MEMPALACE_BACKUP_MIN_FREE_BYTES=0 disables the guard; backup succeeds."""
        import shutil as _shutil

        monkeypatch.setenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", "0")

        class _FakeDU:
            total = 1024**3
            used = 1024**3
            free = 0  # no free space — guard is disabled

        monkeypatch.setattr(_shutil, "disk_usage", lambda _: _FakeDU())

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        meta, out = create_backup(palace_path, kg_path=kg_path)
        assert os.path.isfile(out)

    def test_disk_usage_oserror_skips_guard(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """When disk_usage raises OSError (e.g. unsupported fs), guard is skipped."""
        import shutil as _shutil

        monkeypatch.setenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", "1000000000")
        monkeypatch.setattr(
            _shutil, "disk_usage", lambda _: (_ for _ in ()).throw(OSError("unsupported"))
        )

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        # Should succeed — OSError means guard is bypassed
        meta, out = create_backup(palace_path, kg_path=kg_path)
        assert os.path.isfile(out)

    def test_scheduled_budget_refusal_does_not_prune_existing_archives(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-5: DiskBudgetError is raised before writing or pruning scheduled archives."""
        import shutil as _shutil

        from mempalace_code.disk_budget import DiskBudgetError

        monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        # Pre-create 16 scheduled archives via explicit out_path (bypasses retention)
        for i in range(16):
            path = os.path.join(backups_dir, f"scheduled_{i:03d}.tar.gz")
            create_backup(palace_path, out_path=path, kind="scheduled", kg_path=kg_path)

        assert len([f for f in os.listdir(backups_dir) if f.startswith("scheduled_")]) == 16

        # Force disk budget to fail on the next managed create attempt
        monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", str(1024 * 1024 * 1024))

        class _FakeDU:
            total = 10 * 1024**3
            used = 10 * 1024**3 - 1
            free = 1  # far below 1 GiB floor

        monkeypatch.setattr(_shutil, "disk_usage", lambda _: _FakeDU())

        with pytest.raises(DiskBudgetError):
            create_backup(palace_path, kind="scheduled", kg_path=kg_path)

        # Still exactly 16 — no new archive written, no existing archive pruned
        remaining = [f for f in os.listdir(backups_dir) if f.startswith("scheduled_")]
        assert len(remaining) == 16, (
            f"expected 16 archives unchanged after budget refusal, got {len(remaining)}"
        )


# ── TestListBackupsAnnotations ──────────────────────────────────────────────────


class TestListBackupsAnnotations:
    """AC-5: list_backups stale/oversized annotations and totals."""

    def test_stale_annotation_for_kind(self, seeded_collection, palace_path, tmp_dir, monkeypatch):
        """AC-5: older archives beyond retain_count are marked stale."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        # Create 2 scheduled archives via explicit paths (no retention triggered)
        p_old = os.path.join(backups_dir, "scheduled_old.tar.gz")
        p_new = os.path.join(backups_dir, "scheduled_new.tar.gz")
        create_backup(palace_path, out_path=p_old, kg_path=kg_path)
        time.sleep(0.05)
        create_backup(palace_path, out_path=p_new, kg_path=kg_path)

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")
        from mempalace_code.config import MempalaceConfig

        config = MempalaceConfig()
        result = list_backups(palace_path, config=config)

        scheduled = [e for e in result if e["kind"] == "scheduled"]
        assert len(scheduled) == 2
        newest = next(e for e in scheduled if "new" in os.path.basename(e["path"]))
        oldest = next(e for e in scheduled if "old" in os.path.basename(e["path"]))
        assert not newest["stale"]
        assert oldest["stale"]

    def test_oversized_annotation(self, seeded_collection, palace_path, tmp_dir, monkeypatch):
        """AC-5: archives exceeding warn_size_bytes are marked oversized."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        archive_path = os.path.join(backups_dir, "mempalace_backup_test.tar.gz")
        create_backup(palace_path, out_path=archive_path, kg_path=kg_path)

        actual_size = os.path.getsize(archive_path)
        # Set warn threshold just below actual size so this archive is oversized
        monkeypatch.setenv("MEMPALACE_BACKUP_WARN_SIZE_BYTES", str(actual_size - 1))
        from mempalace_code.config import MempalaceConfig

        config = MempalaceConfig()
        result = list_backups(palace_path, config=config)

        assert len(result) == 1
        assert result[0]["oversized"] is True

    def test_not_oversized_when_below_threshold(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """Archives smaller than warn_size_bytes are not marked oversized."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        archive_path = os.path.join(backups_dir, "mempalace_backup_small.tar.gz")
        create_backup(palace_path, out_path=archive_path, kg_path=kg_path)

        # Set threshold very large (1 TiB)
        monkeypatch.setenv("MEMPALACE_BACKUP_WARN_SIZE_BYTES", str(1024**4))
        from mempalace_code.config import MempalaceConfig

        result = list_backups(palace_path, config=MempalaceConfig())
        assert len(result) == 1
        assert result[0]["oversized"] is False

    def test_stale_false_when_retain_zero(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """retain_count=0 means nothing is stale."""
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        for i in range(3):
            create_backup(
                palace_path,
                out_path=os.path.join(backups_dir, f"scheduled_{i:03d}.tar.gz"),
                kind="scheduled",
                kg_path=kg_path,
            )

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "0")
        from mempalace_code.config import MempalaceConfig

        result = list_backups(palace_path, config=MempalaceConfig())
        assert all(not e["stale"] for e in result)

    def test_stale_flags_use_kind_aware_retention_defaults(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-7: backup list uses kind-aware defaults — scheduled stale after 14, pre_optimize after 5, manual never."""
        monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)

        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")

        # 2 scheduled archives — under the implicit 14 bound, none should be stale
        for i in range(2):
            create_backup(
                palace_path,
                out_path=os.path.join(backups_dir, f"scheduled_{i:03d}.tar.gz"),
                kind="scheduled",
                kg_path=kg_path,
            )
            time.sleep(0.02)

        # 6 pre_optimize archives — over the implicit 5 bound, oldest 1 should be stale
        for i in range(6):
            create_backup(
                palace_path,
                out_path=os.path.join(backups_dir, f"pre_optimize_{i:03d}.tar.gz"),
                kind="pre_optimize",
                kg_path=kg_path,
            )
            time.sleep(0.02)

        # 1 manual archive — unbounded by default, must not be stale
        create_backup(
            palace_path,
            out_path=os.path.join(backups_dir, "mempalace_backup_manual.tar.gz"),
            kg_path=kg_path,
        )

        from mempalace_code.config import MempalaceConfig

        result = list_backups(palace_path, config=MempalaceConfig())

        scheduled = [e for e in result if e["kind"] == "scheduled"]
        pre_optimize = [e for e in result if e["kind"] == "pre_optimize"]
        manual = [e for e in result if e["kind"] == "manual"]

        assert all(not e["stale"] for e in scheduled), (
            "scheduled under implicit 14 must not be stale"
        )
        stale_pre_opt = [e for e in pre_optimize if e["stale"]]
        assert len(stale_pre_opt) == 1, (
            f"only the oldest pre_optimize should be stale; got {stale_pre_opt}"
        )
        assert all(not e["stale"] for e in manual), "manual archives must not be stale by default"


# ── Disk-budget guard tests ────────────────────────────────────────────────────


class TestCreateBackupDiskBudget:
    """AC-4: create_backup raises DiskBudgetError before creating any file when disk is low."""

    def test_raises_disk_budget_error_when_projected_free_too_low(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """create_backup raises DiskBudgetError (not OSError) when budget check fails.

        free_bytes=0 ensures projected_free is deeply negative, below the 1 GiB default.
        """
        from mempalace_code.disk_budget import DiskBudgetError

        out_path = os.path.join(tmp_dir, "should_not_exist.tar.gz")

        with patch("mempalace_code.disk_budget.free_bytes", return_value=0):
            with pytest.raises(DiskBudgetError, match="disk budget"):
                create_backup(palace_path, out_path=out_path)

    def test_no_final_archive_on_refusal(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-4: no .tar.gz or .tar.gz.tmp file exists after a disk-budget refusal."""
        from mempalace_code.disk_budget import DiskBudgetError

        out_path = os.path.join(tmp_dir, "refused.tar.gz")
        tmp_out = out_path + ".tmp"

        with patch("mempalace_code.disk_budget.free_bytes", return_value=0):
            with pytest.raises(DiskBudgetError):
                create_backup(palace_path, out_path=out_path)

        assert not os.path.exists(out_path), "Final archive must not exist after refusal"
        assert not os.path.exists(tmp_out), "Temp archive must not exist after refusal"

    def test_backup_succeeds_when_budget_is_not_a_concern(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """create_backup succeeds normally when a large free-space value is available."""
        out_path = os.path.join(tmp_dir, "ok_backup.tar.gz")

        # Override min_free to 1 byte — any real disk will pass
        monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", "1")
        meta, returned_out = create_backup(palace_path, out_path=out_path)
        assert os.path.isfile(returned_out)
        assert meta["drawer_count"] == 4


# ── TestBoundedPreOptimizeRetention ────────────────────────────────────────────


class TestBoundedPreOptimizeRetention:
    """AC-4, AC-5: Implicit pre_optimize retention boundary and disk-budget fail-closed behavior."""

    def test_pre_optimize_default_retention_does_not_prune_manual_or_explicit_out(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-4: implicit pre_optimize pruning leaves manual, scheduled, and unrelated archives intact.

        Creates one manual and one scheduled sentinel archive, then triggers
        implicit pre_optimize retention by running six pre_optimize creates
        (default bound = 5).  Only the oldest pre_optimize is pruned; the
        sentinels must survive.
        """
        from datetime import datetime as _dt
        from unittest.mock import MagicMock

        monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
        # Disable disk budget so the test is about retention only
        monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", "0")

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)

        # Sentinel archives — written via explicit out_path so retention never runs on them
        manual_path = os.path.join(backups_dir, "mempalace_backup_sentinel.tar.gz")
        scheduled_path = os.path.join(backups_dir, "scheduled_sentinel.tar.gz")
        create_backup(palace_path, out_path=manual_path, kg_path=kg_path)
        create_backup(palace_path, out_path=scheduled_path, kg_path=kg_path)

        # Six pre_optimize creates via managed path — default bound of 5 prunes the oldest
        fake_dt = MagicMock()
        fake_dt.now.side_effect = [
            _dt(2026, 1, 1, 12, 0, 0),
            _dt(2026, 1, 1, 12, 0, 0),
            _dt(2026, 1, 1, 12, 0, 1),
            _dt(2026, 1, 1, 12, 0, 1),
            _dt(2026, 1, 1, 12, 0, 2),
            _dt(2026, 1, 1, 12, 0, 2),
            _dt(2026, 1, 1, 12, 0, 3),
            _dt(2026, 1, 1, 12, 0, 3),
            _dt(2026, 1, 1, 12, 0, 4),
            _dt(2026, 1, 1, 12, 0, 4),
            _dt(2026, 1, 1, 12, 0, 5),
            _dt(2026, 1, 1, 12, 0, 5),
        ]
        with patch("mempalace_code.backup.datetime", fake_dt):
            for _ in range(6):
                create_backup(palace_path, kind="pre_optimize", kg_path=kg_path)

        files = os.listdir(backups_dir)
        pre_opt = sorted(f for f in files if f.startswith("pre_optimize_"))
        manual = [f for f in files if f.startswith("mempalace_backup_")]
        scheduled = [f for f in files if f.startswith("scheduled_")]

        # Oldest pre_optimize pruned; newest five kept
        assert len(pre_opt) == 5
        assert "pre_optimize_20260101_120000_000000.tar.gz" not in pre_opt
        # Sentinels untouched
        assert len(manual) == 1
        assert len(scheduled) == 1

    def test_pre_optimize_budget_refusal_does_not_prune_existing_archives(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """AC-5: DiskBudgetError is raised before any archive is written or pruned.

        Places two pre_optimize archives in the managed backups directory, then
        forces a disk-budget refusal on the next create_backup call.  Both
        existing archives must remain intact afterward.
        """
        from mempalace_code.disk_budget import DiskBudgetError

        monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)
        # Ensure the budget guard is active (non-zero floor)
        monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", str(1 * 1024**3))
        monkeypatch.delenv("MEMPALACE_BACKUP_MIN_FREE_BYTES", raising=False)

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        backups_dir = os.path.join(tmp_dir, "backups")
        os.makedirs(backups_dir, exist_ok=True)

        existing = []
        for name in ("pre_optimize_20260101_110000.tar.gz", "pre_optimize_20260101_110001.tar.gz"):
            p = os.path.join(backups_dir, name)
            create_backup(palace_path, out_path=p, kg_path=kg_path)
            existing.append(name)

        # Now force a budget refusal — free_bytes returns 0 so projected free < floor
        with patch("mempalace_code.disk_budget.free_bytes", return_value=0):
            with pytest.raises(DiskBudgetError, match="disk budget"):
                create_backup(palace_path, kind="pre_optimize", kg_path=kg_path)

        after = sorted(os.listdir(backups_dir))
        assert sorted(existing) == after


# ── TestCreateBackupReadOnlyNoEmbedder ─────────────────────────────────────────


class TestCreateBackupReadOnlyNoEmbedder:
    """AC-1: create_backup gathers drawer count and wing metadata without initializing the embedder."""

    def test_create_backup_readonly_no_embedder(
        self, seeded_collection, palace_path, tmp_dir, monkeypatch
    ):
        """create_backup opens the store read-only for metadata; no embedder must be started."""
        from mempalace_code.storage import LanceStore

        def _embedder_raises(self, *args, **kwargs):
            raise RuntimeError("embedder must not be initialized in create_backup path")

        monkeypatch.setattr(LanceStore, "_get_embedder", _embedder_raises)

        out = os.path.join(tmp_dir, "no_emb_backup.tar.gz")
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        meta, returned_out = create_backup(palace_path, out_path=out, kg_path=kg_path)

        assert os.path.isfile(returned_out)
        assert meta["drawer_count"] == 4
        assert set(meta["wings"]) == {"project", "notes"}


# ── TestPreWatchBackups ──────────────────────────────────────────────────────


class TestPreWatchBackups:
    """AC-7: pre_watch backup taxonomy and retention behavior."""

    def test_pre_watch_kind_uses_prefix_and_list_kind(
        self, seeded_collection, palace_path, tmp_dir
    ):
        """AC-7a: pre_watch_ prefix and kind=pre_watch in list_backups output."""
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        _, archive_path = create_backup(palace_path, kind="pre_watch", kg_path=kg_path)

        assert os.path.basename(archive_path).startswith("pre_watch_")

        result = list_backups(palace_path)
        pre_watch = [e for e in result if "pre_watch" in os.path.basename(e["path"])]
        assert len(pre_watch) == 1
        assert pre_watch[0]["kind"] == "pre_watch"

    def test_pre_watch_default_retention_is_bounded(self, palace_path, tmp_dir, monkeypatch):
        """AC-7b: absent explicit config → DEFAULT_PRE_WATCH_RETAIN_COUNT caps the archive count."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch

        from mempalace_code.config import DEFAULT_PRE_WATCH_RETAIN_COUNT

        monkeypatch.delenv("MEMPALACE_BACKUP_RETAIN_COUNT", raising=False)

        store = open_store(palace_path, create=True)
        store.add(
            ids=["d1"],
            documents=["pre_watch retention test document"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        n_archives = DEFAULT_PRE_WATCH_RETAIN_COUNT + 1

        fake_datetime = MagicMock()
        # Two datetime.now() calls per create_backup: filename timestamp + metadata timestamp
        fake_datetime.now.side_effect = [
            ts
            for i in range(n_archives)
            for ts in [_dt(2026, 1, 1, 12, 0, i), _dt(2026, 1, 1, 12, 0, i)]
        ]

        with _patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(n_archives):
                create_backup(palace_path, kind="pre_watch", kg_path=kg_path)

        backups_dir = os.path.join(tmp_dir, "backups")
        remaining = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("pre_watch_") and f.endswith(".tar.gz")
        ]
        assert len(remaining) == DEFAULT_PRE_WATCH_RETAIN_COUNT

    def test_explicit_zero_retention_keeps_all_pre_watch_archives(
        self, palace_path, tmp_dir, monkeypatch
    ):
        """AC-7c: explicit backup_retain_count=0 disables pruning for pre_watch archives."""
        from datetime import datetime as _dt
        from unittest.mock import MagicMock
        from unittest.mock import patch as _patch

        monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "0")

        store = open_store(palace_path, create=True)
        store.add(
            ids=["d1"],
            documents=["keep-all retention test document"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        count = 3

        fake_datetime = MagicMock()
        fake_datetime.now.side_effect = [
            ts
            for i in range(count)
            for ts in [_dt(2026, 1, 1, 12, 0, i), _dt(2026, 1, 1, 12, 0, i)]
        ]

        with _patch("mempalace_code.backup.datetime", fake_datetime):
            for _ in range(count):
                create_backup(palace_path, kind="pre_watch", kg_path=kg_path)

        backups_dir = os.path.join(tmp_dir, "backups")
        remaining = [
            f
            for f in os.listdir(backups_dir)
            if f.startswith("pre_watch_") and f.endswith(".tar.gz")
        ]
        assert len(remaining) == count

    def test_concurrent_pre_watch_backups_produce_distinct_filenames(
        self, seeded_collection, palace_path, tmp_dir
    ):
        """F-2: Two pre_watch backups created in quick succession produce distinct filenames."""
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        _, path1 = create_backup(palace_path, kind="pre_watch", kg_path=kg_path)
        _, path2 = create_backup(palace_path, kind="pre_watch", kg_path=kg_path)

        assert path1 != path2, "rapid pre-watch backups must produce unique filenames"
        assert os.path.isfile(path1), "first archive must still exist (not overwritten)"
        assert os.path.isfile(path2), "second archive must exist"


# ── Restore archive abuse cases (security boundary) ─────────────────────────────


class TestRestoreArchiveSecurityBoundary:
    """AC-1/AC-3: restore_backup rejects unsafe managed archive members before any

    staged extraction, and leaves no palace/lance/KG side effect behind.
    """

    UNSAFE_CASES = [
        (
            "parent_traversal",
            "mempalace_backup/lance/../../../../etc/passwd",
            tarfile.REGTYPE,
            b"pwned",
        ),
        (
            "absolute_component",
            "mempalace_backup//etc/passwd",
            tarfile.REGTYPE,
            b"pwned",
        ),
        (
            "windows_drive_component",
            "mempalace_backup/C:/evil",
            tarfile.REGTYPE,
            b"pwned",
        ),
        (
            "empty_component",
            "mempalace_backup/lance//evil.lance",
            tarfile.REGTYPE,
            b"pwned",
        ),
        (
            "symlink_member",
            "mempalace_backup/lance/evil_link",
            tarfile.SYMTYPE,
            b"",
        ),
        (
            "hardlink_member",
            "mempalace_backup/lance/evil_hardlink",
            tarfile.LNKTYPE,
            b"",
        ),
        (
            "fifo_member",
            "mempalace_backup/lance/evil_fifo",
            tarfile.FIFOTYPE,
            b"",
        ),
        (
            "device_member",
            "mempalace_backup/lance/evil_dev",
            tarfile.CHRTYPE,
            b"",
        ),
    ]

    @pytest.mark.parametrize(
        "metadata",
        [None, [], {"drawer_count": True}, {"drawer_count": -1}, {"drawer_count": "4"}],
    )
    def test_restore_rejects_missing_or_invalid_canonical_metadata_before_mutation(
        self, metadata, tmp_dir
    ):
        archive = os.path.join(tmp_dir, f"invalid-metadata-{type(metadata).__name__}.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            if metadata is not None:
                payload = json.dumps(metadata).encode()
                info = tarfile.TarInfo("mempalace_backup/metadata.json")
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
            escaped = tarfile.TarInfo("../../mempalace-direct-escaped.txt")
            escaped.size = 7
            tar.addfile(escaped, io.BytesIO(b"escaped"))

        target = os.path.join(tmp_dir, "invalid-metadata-target")
        selected_kg = os.path.join(tmp_dir, "invalid-metadata-kg.sqlite3")
        os.makedirs(os.path.join(target, "lance"))
        sentinel = os.path.join(target, "lance", "sentinel.bin")
        with open(sentinel, "wb") as file:
            file.write(b"LANCE_SENTINEL")
        with open(selected_kg, "wb") as file:
            file.write(b"KG_SENTINEL")

        with pytest.raises(BackupArchiveError) as exc_info:
            restore_backup(archive, target, force=True, kg_path=selected_kg)

        expected_code = "missing_metadata" if metadata is None else "malformed_metadata"
        assert exc_info.value.code == expected_code
        with open(sentinel, "rb") as file:
            assert file.read() == b"LANCE_SENTINEL"
        with open(selected_kg, "rb") as file:
            assert file.read() == b"KG_SENTINEL"
        assert not os.path.lexists(os.path.join(tmp_dir, "mempalace-direct-escaped.txt"))

    def test_restore_rejects_positive_drawer_count_without_lance(self, tmp_dir):
        archive = os.path.join(tmp_dir, "contradictory.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            payload = json.dumps({"drawer_count": 1, "wings": []}).encode()
            info = tarfile.TarInfo("mempalace_backup/metadata.json")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        with pytest.raises(BackupArchiveError) as exc_info:
            restore_backup(
                archive,
                os.path.join(tmp_dir, "contradictory-target"),
                kg_path=os.path.join(tmp_dir, "contradictory-kg.sqlite3"),
            )

        assert exc_info.value.code == "invalid_backup_shape"

    def test_create_backup_shapes_restore_declared_state(
        self, seeded_collection, palace_path, tmp_dir
    ):
        source_kg = os.path.join(tmp_dir, "source-kg.sqlite3")
        with open(source_kg, "wb") as file:
            file.write(b"KG_PAYLOAD")
        cases = [
            (
                "empty",
                os.path.join(tmp_dir, "absent-palace"),
                os.path.join(tmp_dir, "absent-kg"),
                False,
                False,
            ),
            ("lance", palace_path, os.path.join(tmp_dir, "absent-lance-kg"), True, False),
            ("kg", os.path.join(tmp_dir, "absent-kg-palace"), source_kg, False, True),
            ("combined", palace_path, source_kg, True, True),
        ]

        for name, source_palace, source_graph, expect_lance, expect_kg in cases:
            archive = os.path.join(tmp_dir, f"{name}.tar.gz")
            metadata, _ = create_backup(source_palace, out_path=archive, kg_path=source_graph)
            target = os.path.join(tmp_dir, f"{name}-target")
            selected_kg = os.path.join(tmp_dir, f"{name}-target.sqlite3")

            restored = restore_backup(archive, target, kg_path=selected_kg)

            assert restored == metadata
            assert os.path.isdir(os.path.join(target, "lance")) is expect_lance
            assert os.path.isfile(selected_kg) is expect_kg
            if expect_lance:
                assert open_store(target, create=False, read_only=True).count() == 4
            if expect_kg:
                with open(selected_kg, "rb") as file:
                    assert file.read() == b"KG_PAYLOAD"

    def test_force_post_state_verification_failure_restores_prior_lance_and_kg(
        self, seeded_collection, palace_path, tmp_dir
    ):
        source_kg = os.path.join(tmp_dir, "post-verify-source.sqlite3")
        with open(source_kg, "wb") as file:
            file.write(b"NEW_KG")
        archive = os.path.join(tmp_dir, "post-verify.tar.gz")
        create_backup(palace_path, out_path=archive, kg_path=source_kg)
        target = os.path.join(tmp_dir, "post-verify-target")
        selected_kg = os.path.join(tmp_dir, "post-verify-target.sqlite3")
        restore_backup(archive, target, kg_path=selected_kg)
        sentinel = os.path.join(target, "lance", "prior.bin")
        with open(sentinel, "wb") as file:
            file.write(b"PRIOR_LANCE")
        with open(selected_kg, "wb") as file:
            file.write(b"PRIOR_KG")

        real_verify = backup_module._verify_restored_lance
        calls = 0

        def fail_final_verification(path, count):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BackupArchiveError("invalid_lance_payload", "mempalace_backup/lance")
            return real_verify(path, count)

        with patch(
            "mempalace_code.backup._verify_restored_lance", side_effect=fail_final_verification
        ):
            with pytest.raises(BackupArchiveError, match="invalid_lance_payload"):
                restore_backup(archive, target, force=True, kg_path=selected_kg)

        with open(sentinel, "rb") as file:
            assert file.read() == b"PRIOR_LANCE"
        with open(selected_kg, "rb") as file:
            assert file.read() == b"PRIOR_KG"

    def test_force_post_state_failure_restores_kg_symlink_to_directory(
        self, seeded_collection, palace_path, tmp_dir
    ):
        source_kg = os.path.join(tmp_dir, "symlink-source.sqlite3")
        with open(source_kg, "wb") as file:
            file.write(b"NEW_KG")
        archive = os.path.join(tmp_dir, "symlink-rollback.tar.gz")
        create_backup(palace_path, out_path=archive, kg_path=source_kg)

        target = os.path.join(tmp_dir, "symlink-target")
        selected_kg = os.path.join(tmp_dir, "selected-kg.sqlite3")
        referent = os.path.join(tmp_dir, "kg-referent")
        os.mkdir(referent)
        sentinel = os.path.join(referent, "preserve.bin")
        with open(sentinel, "wb") as file:
            file.write(b"PRIOR_REFERENT")
        os.symlink(referent, selected_kg)
        link_before = os.lstat(selected_kg)
        referent_before = os.stat(selected_kg)

        real_verify = backup_module._verify_restored_lance
        calls = 0

        def fail_final_verification(path, count):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BackupArchiveError("invalid_lance_payload", "mempalace_backup/lance")
            return real_verify(path, count)

        with patch(
            "mempalace_code.backup._verify_restored_lance", side_effect=fail_final_verification
        ):
            with pytest.raises(BackupArchiveError, match="invalid_lance_payload"):
                restore_backup(archive, target, force=True, kg_path=selected_kg)

        link_after = os.lstat(selected_kg)
        referent_after = os.stat(selected_kg)
        assert (link_after.st_dev, link_after.st_ino) == (link_before.st_dev, link_before.st_ino)
        assert os.readlink(selected_kg) == referent
        assert (referent_after.st_dev, referent_after.st_ino) == (
            referent_before.st_dev,
            referent_before.st_ino,
        )
        with open(sentinel, "rb") as file:
            assert file.read() == b"PRIOR_REFERENT"

    def test_nonforce_post_state_verification_failure_removes_owned_state(
        self, seeded_collection, palace_path, tmp_dir
    ):
        source_kg = os.path.join(tmp_dir, "nonforce-verify-source.sqlite3")
        with open(source_kg, "wb") as file:
            file.write(b"NEW_KG")
        archive = os.path.join(tmp_dir, "nonforce-verify.tar.gz")
        create_backup(palace_path, out_path=archive, kg_path=source_kg)
        target = os.path.join(tmp_dir, "nonforce-verify-target")
        selected_kg = os.path.join(tmp_dir, "nonforce-verify-target.sqlite3")
        real_verify = backup_module._verify_restored_lance
        calls = 0

        def fail_final_verification(path, count):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BackupArchiveError("invalid_lance_payload", "mempalace_backup/lance")
            return real_verify(path, count)

        with patch(
            "mempalace_code.backup._verify_restored_lance", side_effect=fail_final_verification
        ):
            with pytest.raises(BackupArchiveError, match="invalid_lance_payload"):
                restore_backup(archive, target, kg_path=selected_kg)

        assert not os.path.lexists(target)
        assert not os.path.lexists(selected_kg)

    def test_security_boundary_restore_rejects_unsafe_members(self, tmp_dir):
        """Each unsafe managed member raises BackupArchiveError(unsafe_archive_member)
        before any lance/KG data is copied into the destination palace (AC-1, AC-3)."""
        for case_id, member_name, member_type, content in self.UNSAFE_CASES:
            archive = _build_malicious_archive(
                tmp_dir, f"malicious_{case_id}.tar.gz", member_name, member_type, content
            )
            restore_dir = os.path.join(tmp_dir, f"restored_{case_id}")
            restore_kg = os.path.join(tmp_dir, f"restored_kg_{case_id}.sqlite3")

            with pytest.raises(BackupArchiveError) as exc_info:
                restore_backup(archive, restore_dir, kg_path=restore_kg)

            assert exc_info.value.code == "unsafe_archive_member", case_id
            assert exc_info.value.member_name == member_name, case_id

            # No side effects: nothing was written to the target palace or KG path.
            assert not os.path.exists(restore_dir), (
                f"{case_id}: unsafe archive must not create the destination palace directory"
            )
            assert not os.path.exists(restore_kg), (
                f"{case_id}: unsafe archive must not write a KG file"
            )

    def test_security_boundary_restore_unsafe_member_leaves_existing_palace_untouched(
        self, seeded_collection, palace_path, tmp_dir
    ):
        """A malicious archive rejected via --force must not delete the existing lance/
        directory it was about to overwrite (validation runs before any destructive
        action, not just before the final copy)."""
        # First, populate a real target palace with a valid backup so it is non-empty.
        valid_out = os.path.join(tmp_dir, "valid.tar.gz")
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        create_backup(palace_path, out_path=valid_out, kg_path=kg_path)

        target_dir = os.path.join(tmp_dir, "target_palace")
        target_kg = os.path.join(tmp_dir, "target_kg.sqlite3")
        restore_backup(valid_out, target_dir, kg_path=target_kg)
        assert os.path.isdir(os.path.join(target_dir, "lance"))

        malicious = _build_malicious_archive(
            tmp_dir,
            "malicious_force.tar.gz",
            "mempalace_backup/lance/../../evil",
            tarfile.REGTYPE,
            b"pwned",
        )

        with pytest.raises(BackupArchiveError):
            restore_backup(malicious, target_dir, force=True, kg_path=target_kg)

        # The pre-existing lance/ directory from the earlier valid restore must survive.
        assert os.path.isdir(os.path.join(target_dir, "lance")), (
            "existing palace data must not be deleted before an unsafe archive is rejected"
        )

    def test_security_boundary_restore_malformed_metadata_rejected(self, tmp_dir):
        """An archive with safe managed members but malformed metadata.json must raise
        a stable BackupArchiveError, not an uncontrolled json.JSONDecodeError."""
        archive = os.path.join(tmp_dir, "malformed_metadata.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            meta_bytes = b"{not valid json"
            meta_info = tarfile.TarInfo(name="mempalace_backup/metadata.json")
            meta_info.size = len(meta_bytes)
            tar.addfile(meta_info, io.BytesIO(meta_bytes))

        restore_dir = os.path.join(tmp_dir, "restored_malformed_metadata")
        restore_kg = os.path.join(tmp_dir, "restored_malformed_metadata_kg.sqlite3")

        with pytest.raises(BackupArchiveError) as exc_info:
            restore_backup(archive, restore_dir, kg_path=restore_kg)

        assert exc_info.value.code == "malformed_metadata"
        assert not os.path.exists(restore_dir)
        assert not os.path.exists(restore_kg)

    def test_security_boundary_restore_malformed_metadata_leaves_existing_palace_untouched(
        self, seeded_collection, palace_path, tmp_dir
    ):
        """With --force, an archive whose members pass validation but whose
        metadata.json is malformed must not delete the existing lance/ directory —
        metadata must be parsed before the destructive rmtree, not after."""
        valid_out = os.path.join(tmp_dir, "valid.tar.gz")
        kg_path = os.path.join(tmp_dir, "kg.sqlite3")
        create_backup(palace_path, out_path=valid_out, kg_path=kg_path)

        target_dir = os.path.join(tmp_dir, "target_palace")
        target_kg = os.path.join(tmp_dir, "target_kg.sqlite3")
        restore_backup(valid_out, target_dir, kg_path=target_kg)
        assert os.path.isdir(os.path.join(target_dir, "lance"))

        malformed = os.path.join(tmp_dir, "malformed_metadata_force.tar.gz")
        with tarfile.open(malformed, "w:gz") as tar:
            meta_bytes = b"{not valid json"
            meta_info = tarfile.TarInfo(name="mempalace_backup/metadata.json")
            meta_info.size = len(meta_bytes)
            tar.addfile(meta_info, io.BytesIO(meta_bytes))

        with pytest.raises(BackupArchiveError) as exc_info:
            restore_backup(malformed, target_dir, force=True, kg_path=target_kg)

        assert exc_info.value.code == "malformed_metadata"
        assert os.path.isdir(os.path.join(target_dir, "lance")), (
            "existing palace data must not be deleted before malformed metadata is rejected"
        )

    def test_security_boundary_restore_valid_archive_still_restores(
        self, seeded_collection, palace_path, tmp_dir
    ):
        """Regression: the canonical create_backup output remains restorable (INV-1)."""
        safe = os.path.join(tmp_dir, "safe.tar.gz")
        metadata, _ = create_backup(
            palace_path, out_path=safe, kg_path=os.path.join(tmp_dir, "missing-kg")
        )
        restore_dir = os.path.join(tmp_dir, "safe_restored")

        restored = restore_backup(
            safe, restore_dir, kg_path=os.path.join(tmp_dir, "safe_restored_kg.sqlite3")
        )

        assert restored == metadata
        assert open_store(restore_dir, create=False, read_only=True).count() == 4
