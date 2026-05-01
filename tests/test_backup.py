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
import shlex
import sys
import tarfile
import time

import pytest

from mempalace_code.backup import create_backup, list_backups, render_schedule, restore_backup
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
        backups_dir = os.path.join(os.path.dirname(os.path.abspath(palace_path)), "backups")
        assert backups_dir in out
        assert "scheduled_" in out
        # No bare 'mempalace-code backup' without --out
        assert "--out" in out

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
        assert "--out" in out
        backups_dir = os.path.join(os.path.dirname(os.path.abspath(palace_path)), "backups")
        assert backups_dir in out
        assert "scheduled_" in out

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

    def test_default_bin_falls_back_to_mempalace_code_module(self, palace_path, monkeypatch):
        """Packaged docs and generated schedules must use the renamed import module."""
        monkeypatch.setattr("shutil.which", lambda _name: None)

        out = render_schedule("daily", palace_path, "linux")

        assert f"{shlex.quote(sys.executable)} -m mempalace_code backup create" in out
        assert "-m mempalace backup" not in out
