"""test_disk_budget.py — Unit tests for mempalace_code/disk_budget.py.

Covers:
  - parse_bytes(): int/str/suffix parsing, negative/invalid fallback
  - _dir_size(): recursive byte counting, missing/permission-error paths
  - palace_footprint(): palace + backups/ measurement
  - check_watch_budget(): allow/skip decisions at and below threshold
  - check_backup_budget(): projected-free calculation, backup projection
  - format_bytes(): human-readable output
  - Boundary: exactly at threshold is allowed; one byte below is skipped
"""

from unittest.mock import patch

import pytest

from mempalace_code.disk_budget import (
    DiskBudgetStatus,
    _dir_size,
    check_backup_budget,
    check_watch_budget,
    format_bytes,
    palace_footprint,
    parse_bytes,
)

# ---------------------------------------------------------------------------
# parse_bytes
# ---------------------------------------------------------------------------


class TestParseBytes:
    def test_integer_passthrough(self):
        assert parse_bytes(1024) == 1024

    def test_zero_integer(self):
        assert parse_bytes(0) == 0

    def test_plain_string(self):
        assert parse_bytes("2048") == 2048

    def test_suffix_gb(self):
        assert parse_bytes("1GB") == 1_000_000_000

    def test_suffix_gib(self):
        assert parse_bytes("1GiB") == 1024**3

    def test_suffix_mb(self):
        assert parse_bytes("500MB") == 500_000_000

    def test_suffix_mib(self):
        assert parse_bytes("512MiB") == 512 * 1024**2

    def test_suffix_kb(self):
        assert parse_bytes("100KB") == 100_000

    def test_suffix_kib(self):
        assert parse_bytes("128KiB") == 128 * 1024

    def test_suffix_case_insensitive(self):
        assert parse_bytes("1gib") == parse_bytes("1GiB")

    def test_decimal_suffix(self):
        result = parse_bytes("1.5GiB")
        assert result == int(1.5 * 1024**3)

    def test_negative_int_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            parse_bytes(-1)

    def test_negative_string_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            parse_bytes("-100")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Empty"):
            parse_bytes("")

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_bytes("not_a_number")

    def test_bad_type_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_bytes(None)

    def test_suffix_b_bytes(self):
        assert parse_bytes("100B") == 100

    def test_suffix_tb(self):
        assert parse_bytes("1TB") == 1_000_000_000_000

    def test_bool_true_rejected(self):
        """bool is an int subclass — must be rejected so config True doesn't become 1 byte."""
        with pytest.raises(ValueError, match="bool"):
            parse_bytes(True)

    def test_bool_false_rejected(self):
        """bool is an int subclass — must be rejected so config False doesn't become 0 bytes."""
        with pytest.raises(ValueError, match="bool"):
            parse_bytes(False)


class TestParseBytesViaConfig:
    def test_bool_in_config_falls_back_to_default(self, tmp_path, monkeypatch):
        """A bool value for disk_min_free_bytes must fall back to the 1 GiB default,
        not be silently coerced to 0/1 byte (which would disable the guard)."""
        import json

        from mempalace_code.config import DEFAULT_DISK_MIN_FREE_BYTES, MempalaceConfig

        monkeypatch.delenv("MEMPALACE_DISK_MIN_FREE_BYTES", raising=False)
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(json.dumps({"disk_min_free_bytes": False}))
        cfg = MempalaceConfig(config_dir=str(cfg_dir))
        assert cfg.disk_min_free_bytes == DEFAULT_DISK_MIN_FREE_BYTES


# ---------------------------------------------------------------------------
# _dir_size
# ---------------------------------------------------------------------------


class TestDirSize:
    def test_counts_files_in_single_dir(self, tmp_path):
        (tmp_path / "a.txt").write_bytes(b"hello")
        (tmp_path / "b.txt").write_bytes(b"world!")
        assert _dir_size(str(tmp_path)) == 11

    def test_counts_recursively(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (tmp_path / "root.txt").write_bytes(b"12345")
        (sub / "deep.txt").write_bytes(b"67890")
        assert _dir_size(str(tmp_path)) == 10

    def test_missing_path_returns_zero(self, tmp_path):
        assert _dir_size(str(tmp_path / "nonexistent")) == 0

    def test_empty_dir_returns_zero(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert _dir_size(str(empty)) == 0


# ---------------------------------------------------------------------------
# palace_footprint
# ---------------------------------------------------------------------------


class TestPalaceFootprint:
    def test_measures_palace_and_backups(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 100)

        backups = tmp_path / "backups"
        backups.mkdir()
        (backups / "backup.tar.gz").write_bytes(b"y" * 200)

        palace_b, backups_b = palace_footprint(str(palace))
        assert palace_b == 100
        assert backups_b == 200

    def test_missing_palace_counts_zero(self, tmp_path):
        palace_b, _ = palace_footprint(str(tmp_path / "nonexistent"))
        assert palace_b == 0

    def test_missing_backups_counts_zero(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"a" * 50)
        _, backups_b = palace_footprint(str(palace))
        assert backups_b == 0


# ---------------------------------------------------------------------------
# check_watch_budget — allow/skip, boundary
# ---------------------------------------------------------------------------


class TestCheckWatchBudget:
    def test_allowed_when_free_above_threshold(self, tmp_path):
        min_free = 100
        with patch("mempalace_code.disk_budget.free_bytes", return_value=200):
            status = check_watch_budget(str(tmp_path), min_free)
        assert status.allowed is True
        assert status.free_bytes == 200
        assert status.min_free_bytes == 100

    def test_skipped_when_free_below_threshold(self, tmp_path):
        min_free = 500
        with patch("mempalace_code.disk_budget.free_bytes", return_value=499):
            status = check_watch_budget(str(tmp_path), min_free)
        assert status.allowed is False

    def test_allowed_at_exactly_threshold(self, tmp_path):
        """AC-3: exactly at threshold is allowed."""
        min_free = 1000
        with patch("mempalace_code.disk_budget.free_bytes", return_value=1000):
            status = check_watch_budget(str(tmp_path), min_free)
        assert status.allowed is True

    def test_skipped_one_byte_below_threshold(self, tmp_path):
        """AC-3: one byte below threshold is skipped."""
        min_free = 1000
        with patch("mempalace_code.disk_budget.free_bytes", return_value=999):
            status = check_watch_budget(str(tmp_path), min_free)
        assert status.allowed is False

    def test_status_includes_palace_and_backups_bytes(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 50)
        backups = tmp_path / "backups"
        backups.mkdir()
        (backups / "bak.tar.gz").write_bytes(b"y" * 30)

        with patch("mempalace_code.disk_budget.free_bytes", return_value=5000):
            status = check_watch_budget(str(palace), 100)

        assert status.palace_bytes == 50
        assert status.backups_bytes == 30

    def test_total_footprint_property(self, tmp_path):
        status = DiskBudgetStatus(
            free_bytes=1000,
            min_free_bytes=500,
            palace_bytes=200,
            backups_bytes=100,
            allowed=True,
        )
        assert status.total_footprint_bytes == 300


# ---------------------------------------------------------------------------
# check_backup_budget — projected free calculation
# ---------------------------------------------------------------------------


class TestCheckBackupBudget:
    def test_allowed_when_projected_free_above_floor(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 100)

        out_path = str(tmp_path / "backup.tar.gz")
        min_free = 50

        # free=300, projected_archive=100 (palace), projected_free=200 >= 50
        with patch("mempalace_code.disk_budget.free_bytes", return_value=300):
            status = check_backup_budget(str(palace), out_path, min_free)
        assert status.allowed is True

    def test_refused_when_projected_free_below_floor(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 200)

        out_path = str(tmp_path / "backup.tar.gz")
        min_free = 100

        # free=250, projected_archive=200, projected_free=50 < 100
        with patch("mempalace_code.disk_budget.free_bytes", return_value=250):
            status = check_backup_budget(str(palace), out_path, min_free)
        assert status.allowed is False

    def test_kg_size_included_in_projection(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 100)

        kg_file = tmp_path / "kg.sqlite3"
        kg_file.write_bytes(b"k" * 150)

        out_path = str(tmp_path / "backup.tar.gz")
        min_free = 50

        # free=200, projected_archive=100+150=250, projected_free=-50 < 50
        with patch("mempalace_code.disk_budget.free_bytes", return_value=200):
            status = check_backup_budget(str(palace), out_path, min_free, kg_path=str(kg_file))
        assert status.allowed is False

    def test_missing_kg_not_included_in_projection(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 100)

        out_path = str(tmp_path / "backup.tar.gz")
        kg_path = str(tmp_path / "nonexistent.sqlite3")
        min_free = 50

        # free=200, projected_archive=100 (kg missing), projected_free=100 >= 50
        with patch("mempalace_code.disk_budget.free_bytes", return_value=200):
            status = check_backup_budget(str(palace), out_path, min_free, kg_path=kg_path)
        assert status.allowed is True

    def test_exactly_at_floor_is_allowed(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 100)

        out_path = str(tmp_path / "backup.tar.gz")
        min_free = 100

        # free=200, projected_archive=100, projected_free=100 == 100: allowed
        with patch("mempalace_code.disk_budget.free_bytes", return_value=200):
            status = check_backup_budget(str(palace), out_path, min_free)
        assert status.allowed is True

    def test_one_byte_below_floor_is_refused(self, tmp_path):
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "data.bin").write_bytes(b"x" * 100)

        out_path = str(tmp_path / "backup.tar.gz")
        min_free = 101

        # free=200, projected_archive=100, projected_free=100 < 101: refused
        with patch("mempalace_code.disk_budget.free_bytes", return_value=200):
            status = check_backup_budget(str(palace), out_path, min_free)
        assert status.allowed is False


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------


class TestFormatBytes:
    def test_bytes(self):
        assert format_bytes(512) == "512 B"

    def test_kibibytes(self):
        result = format_bytes(2048)
        assert "KiB" in result

    def test_mibibytes(self):
        result = format_bytes(2 * 1024**2)
        assert "MiB" in result

    def test_gibibytes(self):
        result = format_bytes(1024**3)
        assert "GiB" in result

    def test_zero(self):
        assert format_bytes(0) == "0 B"
