"""
tests/test_backup_cli.py — CLI dispatch tests for backup and restore commands.

Drives mempalace_code.cli.main() via sys.argv patching to cover the argparse
wiring, cmd_backup / cmd_restore dispatch, printed output, and sys.exit(1) on
error.  Library-level behaviour is covered by tests/test_backup.py.
"""

import os
import sys
from unittest.mock import patch

import pytest

from mempalace_code.cli import main
from mempalace_code.storage import open_store

# ── helpers ────────────────────────────────────────────────────────────────────


def _run(argv):
    with patch.object(sys, "argv", argv):
        main()


def _archive_line(stdout: str) -> str:
    """Return the path shown on the 'Archive:' line."""
    for line in stdout.splitlines():
        if "Archive:" in line:
            return line.split("Archive:", 1)[1].strip()
    raise AssertionError(f"No 'Archive:' line found in output:\n{stdout}")


# ── backup CLI ─────────────────────────────────────────────────────────────────


def test_backup_cli_default_out(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-1: no-verb backup creates archive under <palace_parent>/backups/ and prints Archive: line."""
    _run(["mempalace-code", "--palace", palace_path, "backup"])

    captured = capsys.readouterr()
    archive_path = _archive_line(captured.out)

    assert os.path.isfile(archive_path), f"Archive not found at {archive_path}"
    assert archive_path.endswith(".tar.gz")
    backups_dir = os.path.join(tmp_dir, "backups")
    assert os.path.abspath(archive_path).startswith(os.path.abspath(backups_dir)), (
        f"Expected archive under {backups_dir}, got {archive_path}"
    )
    # seeded_collection has 4 drawers across 2 wings (project, notes) — verify
    # the CLI summary lines reflect that, not just the Archive: path.
    assert "Backed up 4 drawers from 2 wing(s)." in captured.out
    assert "Wings: notes, project" in captured.out


def test_backup_cli_explicit_out(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-2: backup create --out <path> creates archive at the explicit path and prints it."""
    explicit = os.path.join(tmp_dir, "explicit.tar.gz")
    _run(["mempalace-code", "--palace", palace_path, "backup", "create", "--out", explicit])

    captured = capsys.readouterr()
    assert os.path.isfile(explicit)
    archive_path = _archive_line(captured.out)
    assert os.path.abspath(archive_path) == os.path.abspath(explicit)
    assert "Backed up 4 drawers from 2 wing(s)." in captured.out


# ── restore CLI ────────────────────────────────────────────────────────────────


def _make_archive(palace_path, tmp_dir, capsys):
    """Create a backup archive from palace_path and return the archive file path."""
    archive = os.path.join(tmp_dir, "cli_backup.tar.gz")
    _run(["mempalace-code", "--palace", palace_path, "backup", "create", "--out", archive])
    capsys.readouterr()  # discard backup output
    return archive


def test_restore_cli_happy(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-3: restore to an empty palace creates lance/ dir and prints 'Restored palace to:'."""
    archive = _make_archive(palace_path, tmp_dir, capsys)

    restore_target = os.path.join(tmp_dir, "restore_palace")
    _run(["mempalace-code", "--palace", restore_target, "restore", archive])

    captured = capsys.readouterr()
    assert os.path.isdir(os.path.join(restore_target, "lance"))
    assert "Restored palace to:" in captured.out
    # The CLI prints the archive metadata after restore — verify drawer count
    # and wings appear, not just the trailing path line.
    assert "Drawers: 4" in captured.out
    assert "Wings: notes, project" in captured.out


def test_restore_cli_force_flag(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-4: restore --force on a non-empty palace re-extracts and yields a working store."""
    archive = _make_archive(palace_path, tmp_dir, capsys)

    restore_target = os.path.join(tmp_dir, "restore_palace2")
    _run(["mempalace-code", "--palace", restore_target, "restore", archive])
    capsys.readouterr()

    # Second restore with --force must not raise
    _run(["mempalace-code", "--palace", restore_target, "restore", archive, "--force"])

    assert os.path.isdir(os.path.join(restore_target, "lance"))
    # Re-open the store so a silent --force no-op (e.g. lance/ left empty
    # after rmtree but no re-extraction) would fail this assertion.
    restored = open_store(restore_target, create=False)
    assert restored.count() == 4


def test_restore_cli_error_exit(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-5: restore without --force on a non-empty palace exits 1 and prints 'Use --force'."""
    archive = _make_archive(palace_path, tmp_dir, capsys)

    restore_target = os.path.join(tmp_dir, "restore_palace3")
    _run(["mempalace-code", "--palace", restore_target, "restore", archive])
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        _run(["mempalace-code", "--palace", restore_target, "restore", archive])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Use --force" in captured.err


def test_restore_cli_missing_archive_exits_1(palace_path, tmp_dir, capsys):
    """Generic exception path: a non-existent archive must exit 1 with an Error: line on stderr."""
    missing = os.path.join(tmp_dir, "does_not_exist.tar.gz")
    restore_target = os.path.join(tmp_dir, "restore_target")

    with pytest.raises(SystemExit) as exc:
        _run(["mempalace-code", "--palace", restore_target, "restore", missing])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
