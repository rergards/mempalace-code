"""
tests/test_backup_cli.py — CLI dispatch tests for backup and restore commands.

Drives mempalace_code.cli.main() via sys.argv patching to cover the argparse
wiring, cmd_backup / cmd_restore dispatch, printed output, and sys.exit(1) on
error.  Library-level behaviour is covered by tests/test_backup.py.
"""

import errno
import io
import os
import sys
import tarfile
from unittest.mock import patch

import pytest

import mempalace_code.backup as backup_module
from mempalace_code.backup import create_backup
from mempalace_code.cli import main
from mempalace_code.knowledge_graph import DEFAULT_KG_PATH, KnowledgeGraph
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


def _path_snapshot(path: str):
    """Return a byte-sensitive snapshot without following symlinks."""
    if not os.path.lexists(path):
        return ("missing",)
    if os.path.islink(path):
        return ("symlink", os.readlink(path))
    if os.path.isfile(path):
        with open(path, "rb") as file:
            return ("file", file.read())
    return (
        "dir",
        tuple(
            (entry.name, _path_snapshot(entry.path))
            for entry in sorted(os.scandir(path), key=lambda item: item.name)
        ),
    )


# ── backup CLI ─────────────────────────────────────────────────────────────────


def test_backup_cli_default_out(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-3: no-verb backup creates archive under <palace_parent>/backups/ and prints Archive: line."""
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


def test_backup_parent_out_compat(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-1: backup --out FILE create (parent-level --out) writes to FILE, not default dir."""
    explicit = os.path.join(tmp_dir, "compat.tar.gz")
    _run(["mempalace-code", "--palace", palace_path, "backup", "--out", explicit, "create"])

    captured = capsys.readouterr()
    assert os.path.isfile(explicit), f"Archive not created at {explicit}"
    archive_path = _archive_line(captured.out)
    assert os.path.abspath(archive_path) == os.path.abspath(explicit)
    assert "Backed up 4 drawers from 2 wing(s)." in captured.out


def test_backup_parent_out_missing_dir(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-4: backup --out FILE create succeeds even when FILE's parent directory does not exist."""
    nested = os.path.join(tmp_dir, "new_subdir", "archive.tar.gz")
    assert not os.path.exists(os.path.dirname(nested))
    _run(["mempalace-code", "--palace", palace_path, "backup", "--out", nested, "create"])

    captured = capsys.readouterr()
    assert os.path.isfile(nested), f"Archive not created at {nested}"
    archive_path = _archive_line(captured.out)
    assert os.path.abspath(archive_path) == os.path.abspath(nested)


def test_backup_create_default_out(seeded_collection, palace_path, tmp_dir, capsys):
    """AC-3 (create verb): backup create with no --out writes to default backups dir."""
    _run(["mempalace-code", "--palace", palace_path, "backup", "create"])

    captured = capsys.readouterr()
    archive_path = _archive_line(captured.out)
    assert os.path.isfile(archive_path), f"Archive not found at {archive_path}"
    backups_dir = os.path.join(tmp_dir, "backups")
    assert os.path.abspath(archive_path).startswith(os.path.abspath(backups_dir)), (
        f"Expected archive under {backups_dir}, got {archive_path}"
    )


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
    """AC-5: restore collision names the backup-first, destination-aware recovery."""
    archive = _make_archive(palace_path, tmp_dir, capsys)

    restore_target = os.path.join(tmp_dir, "restore_palace3")
    _run(["mempalace-code", "--palace", restore_target, "restore", archive])
    capsys.readouterr()

    with pytest.raises(SystemExit) as exc:
        _run(["mempalace-code", "--palace", restore_target, "restore", archive])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert (
        "Next: back up the reported destination state, then use --force only if you intend "
        "to replace it." in captured.err
    )


def test_restore_cli_missing_archive_exits_1(palace_path, tmp_dir, capsys):
    """Generic exception path: a non-existent archive must exit 1 with an Error: line on stderr."""
    missing = os.path.join(tmp_dir, "does_not_exist.tar.gz")
    restore_target = os.path.join(tmp_dir, "restore_target")

    with pytest.raises(SystemExit) as exc:
        _run(["mempalace-code", "--palace", restore_target, "restore", missing])

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


# ── KG path scoping regression (RESTORE-KG-PATH-SCOPING) ──────────────────────


def _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys):
    """Create a backup archive that includes seeded_kg and return its path."""
    archive = os.path.join(tmp_dir, "kg_backup.tar.gz")
    create_backup(palace_path, out_path=archive, kg_path=seeded_kg.db_path)
    capsys.readouterr()  # discard any output
    return archive


def test_restore_cli_explicit_palace_scopes_kg(
    seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
):
    """AC-1: explicit --palace restore writes archived KG to <palace>/knowledge_graph.sqlite3 and leaves DEFAULT_KG_PATH untouched."""
    archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
    restore_target = os.path.join(tmp_dir, "restore_palace_kg_scope")
    scoped_kg = os.path.join(restore_target, "knowledge_graph.sqlite3")

    # Plant a sentinel at DEFAULT_KG_PATH; it must not be overwritten by --palace restore.
    sentinel_content = b"AC1_DEFAULT_SENTINEL"
    os.makedirs(os.path.dirname(os.path.abspath(DEFAULT_KG_PATH)), exist_ok=True)
    with open(DEFAULT_KG_PATH, "wb") as f:
        f.write(sentinel_content)

    _run(["mempalace-code", "--palace", restore_target, "restore", archive])
    capsys.readouterr()

    # KG must be written to the custom palace, not to the global default
    assert os.path.isfile(scoped_kg), f"Expected KG at {scoped_kg}"
    with open(DEFAULT_KG_PATH, "rb") as f:
        assert f.read() == sentinel_content, (
            "DEFAULT_KG_PATH sentinel was overwritten by --palace restore"
        )

    # Verify the restored KG contains the expected data
    restored_kg = KnowledgeGraph(db_path=scoped_kg)
    triples = restored_kg.query_entity("Max")
    subjects_predicates = {(t["subject"], t["predicate"]) for t in triples}
    assert ("Max", "does") in subjects_predicates


def test_restore_cli_refusal_does_not_touch_kg(
    seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
):
    """AC-2: non-forced restore refusal exits 1 before touching scoped or default KG files."""
    archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
    restore_target = os.path.join(tmp_dir, "restore_refusal_palace")

    # First restore to populate lance/ so the second attempt is refused
    _run(["mempalace-code", "--palace", restore_target, "restore", archive])
    capsys.readouterr()

    # Plant sentinels at both KG locations
    scoped_kg = os.path.join(restore_target, "knowledge_graph.sqlite3")
    sentinel_content = b"SENTINEL"
    with open(scoped_kg, "wb") as f:
        f.write(sentinel_content)

    os.makedirs(os.path.dirname(os.path.abspath(DEFAULT_KG_PATH)), exist_ok=True)
    with open(DEFAULT_KG_PATH, "wb") as f:
        f.write(sentinel_content)

    # Attempt refused restore
    with pytest.raises(SystemExit) as exc:
        _run(["mempalace-code", "--palace", restore_target, "restore", archive])
    assert exc.value.code == 1
    capsys.readouterr()

    # Neither sentinel should have been modified
    with open(scoped_kg, "rb") as f:
        assert f.read() == sentinel_content, "scoped KG sentinel was modified"
    with open(DEFAULT_KG_PATH, "rb") as f:
        assert f.read() == sentinel_content, "DEFAULT_KG_PATH sentinel was modified"


def test_restore_cli_kg_path_overrides_palace_scope(
    seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
):
    """AC-3: --kg-path wins over palace-scoped default; scoped and global paths are untouched."""
    archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
    restore_target = os.path.join(tmp_dir, "restore_palace_override")
    explicit_kg = os.path.join(tmp_dir, "explicit_restore_kg.sqlite3")
    scoped_kg = os.path.join(restore_target, "knowledge_graph.sqlite3")

    _run(
        [
            "mempalace-code",
            "--palace",
            restore_target,
            "restore",
            archive,
            "--kg-path",
            explicit_kg,
        ]
    )
    capsys.readouterr()

    assert os.path.isfile(explicit_kg), f"KG not written to explicit --kg-path {explicit_kg}"
    assert not os.path.exists(scoped_kg), (
        "KG must not be written to <palace>/knowledge_graph.sqlite3 when --kg-path overrides"
    )

    restored_kg = KnowledgeGraph(db_path=explicit_kg)
    triples = restored_kg.query_entity("Max")
    assert len(triples) >= 2, "Expected at least 2 triples for Max in restored KG"


def test_restore_cli_kg_path_without_palace(
    seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
):
    """--kg-path explicit destination is honoured even without top-level --palace."""
    archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
    default_restore_target = os.path.join(tmp_dir, "kg_path_no_palace")
    explicit_kg = os.path.join(tmp_dir, "no_palace_explicit_kg.sqlite3")

    # Plant a sentinel at DEFAULT_KG_PATH; --kg-path without --palace must not touch it.
    os.makedirs(os.path.dirname(os.path.abspath(DEFAULT_KG_PATH)), exist_ok=True)
    sentinel_content = b"NO_PALACE_KG_PATH_SENTINEL"
    with open(DEFAULT_KG_PATH, "wb") as f:
        f.write(sentinel_content)

    with patch("mempalace_code.cli_commands.backup_restore.MempalaceConfig") as mock_cfg:
        mock_cfg.return_value.palace_path = default_restore_target
        _run(["mempalace-code", "restore", archive, "--kg-path", explicit_kg])
    capsys.readouterr()

    assert os.path.isfile(explicit_kg), f"KG must be written to --kg-path {explicit_kg}"
    with open(DEFAULT_KG_PATH, "rb") as f:
        assert f.read() == sentinel_content, (
            "--kg-path without --palace must not touch DEFAULT_KG_PATH"
        )
    restored_kg = KnowledgeGraph(db_path=explicit_kg)
    triples = restored_kg.query_entity("Max")
    assert len(triples) >= 2, "Expected at least 2 triples for Max in restored KG"


def test_restore_cli_default_without_palace_keeps_default_kg(
    seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
):
    """AC-4: restore without top-level --palace writes KG to DEFAULT_KG_PATH (backward compat)."""
    archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)

    # Use a fresh empty dir as the default palace so the restore is not refused.
    default_restore_target = os.path.join(tmp_dir, "default_palace_ac4")
    if os.path.lexists(DEFAULT_KG_PATH):
        os.unlink(DEFAULT_KG_PATH)

    with patch("mempalace_code.cli_commands.backup_restore.MempalaceConfig") as mock_cfg:
        mock_cfg.return_value.palace_path = default_restore_target
        _run(["mempalace-code", "restore", archive])
    capsys.readouterr()

    # DEFAULT_KG_PATH is isolated by conftest HOME redirect; the KG must land there.
    assert os.path.isfile(DEFAULT_KG_PATH), (
        f"KG should be written to DEFAULT_KG_PATH {DEFAULT_KG_PATH}"
    )
    restored_kg = KnowledgeGraph(db_path=DEFAULT_KG_PATH)
    triples = restored_kg.query_entity("Max")
    subjects_predicates = {(t["subject"], t["predicate"]) for t in triples}
    assert ("Max", "does") in subjects_predicates


class TestRestoreTargetStateCollisionGuard:
    @pytest.mark.parametrize(
        "shape", ["kg_only", "palace_file", "palace_symlink", "empty_lance", "lance"]
    )
    def test_refuses_existing_palace_shapes_unchanged(
        self, shape, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, f"collision_{shape}")
        scoped_kg = os.path.join(target, "knowledge_graph.sqlite3")
        referent = os.path.join(tmp_dir, "palace_referent")

        if shape == "kg_only":
            os.makedirs(target)
            with open(scoped_kg, "wb") as file:
                file.write(b"KG_ONLY_SENTINEL")
        elif shape == "palace_file":
            with open(target, "wb") as file:
                file.write(b"PALACE_FILE_SENTINEL")
        elif shape == "palace_symlink":
            os.makedirs(referent)
            with open(os.path.join(referent, "outside.txt"), "wb") as file:
                file.write(b"REFERENT_SENTINEL")
            os.symlink(referent, target)
        elif shape == "lance":
            os.makedirs(os.path.join(target, "lance"))
            with open(os.path.join(target, "lance", "sentinel.bin"), "wb") as file:
                file.write(b"LANCE_SENTINEL")
        else:
            os.makedirs(os.path.join(target, "lance"))

        before = _path_snapshot(target)
        referent_before = _path_snapshot(referent)
        with pytest.raises(SystemExit) as exc:
            _run(["mempalace-code", "--palace", target, "restore", archive])

        assert exc.value.code == 1
        assert _path_snapshot(target) == before
        assert _path_snapshot(referent) == referent_before
        captured = capsys.readouterr()
        assert target in captured.err
        assert "Use --force" in captured.err

    def test_explicit_kg_collision_refuses_before_extraction(
        self, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, "explicit_kg_target")
        selected_kg = os.path.join(tmp_dir, "selected.sqlite3")
        with open(selected_kg, "wb") as file:
            file.write(b"EXPLICIT_KG_SENTINEL")

        with patch.object(backup_module.tempfile, "TemporaryDirectory") as tempdir:
            with pytest.raises(SystemExit) as exc:
                _run(
                    [
                        "mempalace-code",
                        "--palace",
                        target,
                        "restore",
                        archive,
                        "--kg-path",
                        selected_kg,
                    ]
                )

        assert exc.value.code == 1
        tempdir.assert_not_called()
        assert _path_snapshot(target) == ("missing",)
        assert _path_snapshot(selected_kg) == ("file", b"EXPLICIT_KG_SENTINEL")
        assert selected_kg in capsys.readouterr().err

    def test_default_kg_collision_refuses_unchanged(
        self, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys, monkeypatch
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, "default_kg_target")
        default_kg_path = os.path.join(tmp_dir, "default_kg.sqlite3")
        monkeypatch.setattr("mempalace_code.knowledge_graph.DEFAULT_KG_PATH", default_kg_path)
        with open(default_kg_path, "wb") as file:
            file.write(b"DEFAULT_KG_SENTINEL")

        with patch("mempalace_code.cli_commands.backup_restore.MempalaceConfig") as config:
            config.return_value.palace_path = target
            with pytest.raises(SystemExit) as exc:
                _run(["mempalace-code", "restore", archive])

        assert exc.value.code == 1
        assert _path_snapshot(target) == ("missing",)
        assert _path_snapshot(default_kg_path) == ("file", b"DEFAULT_KG_SENTINEL")
        assert default_kg_path in capsys.readouterr().err

    def test_repeated_restore_is_refused_without_changes(
        self, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, "repeat_target")
        _run(["mempalace-code", "--palace", target, "restore", archive])
        capsys.readouterr()
        before = _path_snapshot(target)

        with pytest.raises(SystemExit) as exc:
            _run(["mempalace-code", "--palace", target, "restore", archive])

        assert exc.value.code == 1
        assert _path_snapshot(target) == before
        assert "back up the reported destination state" in capsys.readouterr().err

    def test_non_force_preserves_preexisting_legacy_kg_tmp_symlink(
        self, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, "legacy_tmp_target")
        selected_kg = os.path.join(tmp_dir, "legacy_tmp_kg.sqlite3")
        tmp_referent = os.path.join(tmp_dir, "legacy_tmp_referent.sqlite3")
        with open(tmp_referent, "wb") as file:
            file.write(b"LEGACY_TMP_SENTINEL")
        os.symlink(tmp_referent, selected_kg + ".tmp")
        tmp_referent_before = _path_snapshot(tmp_referent)

        _run(
            [
                "mempalace-code",
                "--palace",
                target,
                "restore",
                archive,
                "--kg-path",
                selected_kg,
            ]
        )

        assert len(KnowledgeGraph(db_path=selected_kg).query_entity("Max")) == 2
        assert _path_snapshot(selected_kg + ".tmp") == ("symlink", tmp_referent)
        assert _path_snapshot(tmp_referent) == tmp_referent_before

    @pytest.mark.parametrize("empty_palace", [False, True])
    def test_absent_state_and_empty_palace_restore_successfully(
        self, empty_palace, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, f"clean_target_{empty_palace}")
        selected_kg = os.path.join(tmp_dir, f"clean_kg_{empty_palace}.sqlite3")
        if empty_palace:
            os.makedirs(target)

        _run(
            [
                "mempalace-code",
                "--palace",
                target,
                "restore",
                archive,
                "--kg-path",
                selected_kg,
            ]
        )

        assert open_store(target, create=False).count() == 4
        assert len(KnowledgeGraph(db_path=selected_kg).query_entity("Max")) == 2
        assert "Restored palace to:" in capsys.readouterr().out

    def test_palace_state_raced_in_after_preflight_is_preserved(
        self, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, "raced_palace")
        selected_kg = os.path.join(tmp_dir, "raced_palace_kg.sqlite3")
        real_check = backup_module._restore_destination_collisions
        calls = 0

        def inject_on_publication(palace, kg_path, allowed=frozenset()):
            nonlocal calls
            calls += 1
            if calls == 2:
                os.makedirs(palace)
                with open(os.path.join(palace, "raced.bin"), "wb") as file:
                    file.write(b"RACED_PALACE_SENTINEL")
            return real_check(palace, kg_path, allowed)

        with patch.object(
            backup_module, "_restore_destination_collisions", side_effect=inject_on_publication
        ):
            with pytest.raises(SystemExit) as exc:
                _run(
                    [
                        "mempalace-code",
                        "--palace",
                        target,
                        "restore",
                        archive,
                        "--kg-path",
                        selected_kg,
                    ]
                )

        assert exc.value.code == 1
        assert _path_snapshot(target) == (
            "dir",
            (("raced.bin", ("file", b"RACED_PALACE_SENTINEL")),),
        )
        assert _path_snapshot(selected_kg) == ("missing",)
        assert "Use --force" in capsys.readouterr().err

    @pytest.mark.parametrize("shape", ["file", "dangling_symlink"])
    def test_kg_state_raced_at_atomic_publication_is_preserved(
        self, shape, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, "raced_kg_palace")
        selected_kg = os.path.join(tmp_dir, "raced_kg.sqlite3")
        missing_referent = os.path.join(tmp_dir, "raced_kg_missing_referent.sqlite3")
        real_link = os.link

        def inject_before_link(src, dst, *args, **kwargs):
            assert dst == selected_kg
            if shape == "file":
                with open(dst, "wb") as file:
                    file.write(b"RACED_KG_SENTINEL")
            else:
                os.symlink(missing_referent, dst)
            return real_link(src, dst, *args, **kwargs)

        with patch.object(backup_module.os, "link", side_effect=inject_before_link):
            with pytest.raises(SystemExit) as exc:
                _run(
                    [
                        "mempalace-code",
                        "--palace",
                        target,
                        "restore",
                        archive,
                        "--kg-path",
                        selected_kg,
                    ]
                )

        assert exc.value.code == 1
        assert _path_snapshot(target) == ("missing",)
        if shape == "file":
            assert _path_snapshot(selected_kg) == ("file", b"RACED_KG_SENTINEL")
        else:
            assert _path_snapshot(selected_kg) == ("symlink", missing_referent)
        assert not [
            entry
            for entry in os.listdir(tmp_dir)
            if entry.startswith(f".{os.path.basename(selected_kg)}.") and entry.endswith(".tmp")
        ]
        assert "back up the reported destination state" in capsys.readouterr().err

    @pytest.mark.parametrize("shape", ["empty", "sentinel"])
    def test_lance_claim_race_preserves_existing_root(
        self, shape, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, f"raced_lance_{shape}")
        selected_kg = os.path.join(tmp_dir, f"raced_lance_{shape}.sqlite3")
        lance_dir = os.path.join(target, "lance")
        real_mkdir = os.mkdir

        def inject_before_claim(path, mode=0o777, *, dir_fd=None):
            if path == lance_dir:
                real_mkdir(path, mode, dir_fd=dir_fd)
                if shape == "sentinel":
                    with open(os.path.join(path, "sentinel.bin"), "wb") as file:
                        file.write(b"RACED_LANCE_SENTINEL")
            return real_mkdir(path, mode, dir_fd=dir_fd)

        with patch.object(backup_module.os, "mkdir", side_effect=inject_before_claim):
            with pytest.raises(SystemExit) as exc:
                _run(
                    [
                        "mempalace-code",
                        "--palace",
                        target,
                        "restore",
                        archive,
                        "--kg-path",
                        selected_kg,
                    ]
                )

        assert exc.value.code == 1
        expected_lance = ("dir", ())
        if shape == "sentinel":
            expected_lance = ("dir", (("sentinel.bin", ("file", b"RACED_LANCE_SENTINEL")),))
        assert _path_snapshot(target) == ("dir", (("lance", expected_lance),))
        assert _path_snapshot(selected_kg) == ("missing",)
        assert not [
            entry
            for entry in os.listdir(tmp_dir)
            if entry.startswith(f".{os.path.basename(selected_kg)}.") and entry.endswith(".tmp")
        ]
        assert "Use --force" in capsys.readouterr().err

    def test_hardlink_unavailable_rolls_back_owned_lance(
        self, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, "hardlink_unavailable_palace")
        selected_kg = os.path.join(tmp_dir, "hardlink_unavailable.sqlite3")

        with patch.object(
            backup_module.os,
            "link",
            side_effect=OSError(errno.EOPNOTSUPP, "hard links unavailable"),
        ):
            with pytest.raises(SystemExit) as exc:
                _run(
                    [
                        "mempalace-code",
                        "--palace",
                        target,
                        "restore",
                        archive,
                        "--kg-path",
                        selected_kg,
                    ]
                )

        assert exc.value.code == 1
        assert _path_snapshot(target) == ("missing",)
        assert _path_snapshot(selected_kg) == ("missing",)
        assert not [
            entry
            for entry in os.listdir(tmp_dir)
            if entry.startswith(f".{os.path.basename(selected_kg)}.") and entry.endswith(".tmp")
        ]


class TestRestoreForceCollisionGuard:
    @pytest.mark.parametrize("shape", ["palace_file", "palace_symlink", "lance"])
    @pytest.mark.parametrize("kg_symlink", [False, True])
    def test_force_replaces_managed_state_without_following_links(
        self, shape, kg_symlink, seeded_collection, palace_path, seeded_kg, tmp_dir, capsys
    ):
        archive = _make_kg_archive(palace_path, seeded_kg, tmp_dir, capsys)
        target = os.path.join(tmp_dir, f"force_{shape}")
        selected_kg = os.path.join(tmp_dir, f"force_{shape}.sqlite3")
        referent = os.path.join(tmp_dir, f"force_{shape}_referent")
        kg_referent = os.path.join(tmp_dir, f"force_{shape}_kg_referent.sqlite3")
        unrelated = None

        if shape == "palace_file":
            with open(target, "wb") as file:
                file.write(b"PALACE_FILE_SENTINEL")
        elif shape == "palace_symlink":
            os.makedirs(referent)
            with open(os.path.join(referent, "outside.bin"), "wb") as file:
                file.write(b"REFERENT_SENTINEL")
            os.symlink(referent, target)
        else:
            os.makedirs(os.path.join(target, "lance"))
            with open(os.path.join(target, "lance", "old.bin"), "wb") as file:
                file.write(b"OLD_LANCE_SENTINEL")
            unrelated = os.path.join(target, "keep.bin")
            with open(unrelated, "wb") as file:
                file.write(b"UNRELATED_SENTINEL")

        referent_before = _path_snapshot(referent)
        existing_kg = kg_referent if kg_symlink else selected_kg
        with open(existing_kg, "wb") as file:
            file.write(b"OLD_KG_SENTINEL")
        if kg_symlink:
            os.symlink(kg_referent, selected_kg)
        kg_referent_before = _path_snapshot(kg_referent)
        tmp_referent = os.path.join(tmp_dir, f"force_{shape}_tmp_referent.sqlite3")
        with open(tmp_referent, "wb") as file:
            file.write(b"LEGACY_TMP_SENTINEL")
        os.symlink(tmp_referent, selected_kg + ".tmp")
        tmp_referent_before = _path_snapshot(tmp_referent)

        _run(
            [
                "mempalace-code",
                "--palace",
                target,
                "restore",
                archive,
                "--kg-path",
                selected_kg,
                "--force",
            ]
        )

        assert not os.path.islink(target)
        assert open_store(target, create=False).count() == 4
        assert len(KnowledgeGraph(db_path=selected_kg).query_entity("Max")) == 2
        assert _path_snapshot(referent) == referent_before
        assert not os.path.islink(selected_kg)
        assert _path_snapshot(kg_referent) == kg_referent_before
        assert _path_snapshot(selected_kg + ".tmp") == ("symlink", tmp_referent)
        assert _path_snapshot(tmp_referent) == tmp_referent_before
        if unrelated is not None:
            assert _path_snapshot(unrelated) == ("file", b"UNRELATED_SENTINEL")
        assert "Restored palace to:" in capsys.readouterr().out

    @pytest.mark.parametrize("archive_shape", ["unsafe_member", "malformed_metadata"])
    def test_force_rejects_invalid_archive_before_mutation(self, archive_shape, tmp_dir, capsys):
        archive = os.path.join(tmp_dir, f"{archive_shape}.tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            if archive_shape == "unsafe_member":
                unsafe = tarfile.TarInfo("mempalace_backup/lance/link")
                unsafe.type = tarfile.SYMTYPE
                unsafe.linkname = "/etc/passwd"
                tar.addfile(unsafe)
            else:
                malformed = b"{not-json"
                metadata = tarfile.TarInfo("mempalace_backup/metadata.json")
                metadata.size = len(malformed)
                tar.addfile(metadata, io.BytesIO(malformed))

        target = os.path.join(tmp_dir, "unsafe_target")
        os.makedirs(os.path.join(target, "lance"))
        with open(os.path.join(target, "lance", "sentinel.bin"), "wb") as file:
            file.write(b"LANCE_SENTINEL")
        selected_kg = os.path.join(tmp_dir, "unsafe_kg.sqlite3")
        with open(selected_kg, "wb") as file:
            file.write(b"KG_SENTINEL")
        palace_before = _path_snapshot(target)
        kg_before = _path_snapshot(selected_kg)

        with pytest.raises(SystemExit) as exc:
            _run(
                [
                    "mempalace-code",
                    "--palace",
                    target,
                    "restore",
                    archive,
                    "--kg-path",
                    selected_kg,
                    "--force",
                ]
            )

        assert exc.value.code == 1
        assert _path_snapshot(target) == palace_before
        assert _path_snapshot(selected_kg) == kg_before
        expected_error = (
            "unsafe_archive_member" if archive_shape == "unsafe_member" else "malformed_metadata"
        )
        assert expected_error in capsys.readouterr().err


# ── Disk-budget CLI guard ──────────────────────────────────────────────────────


def test_backup_create_cli_exits_1_on_disk_budget_error(
    seeded_collection, palace_path, tmp_dir, capsys
):
    """AC-4 (CLI): 'backup create' exits 1 with 'disk budget' message when disk is low."""
    out_path = os.path.join(tmp_dir, "rejected.tar.gz")

    # free_bytes=0 → projected_free is negative → budget check fails
    with patch("mempalace_code.disk_budget.free_bytes", return_value=0):
        with pytest.raises(SystemExit) as exc:
            _run(
                [
                    "mempalace-code",
                    "--palace",
                    palace_path,
                    "backup",
                    "create",
                    "--out",
                    out_path,
                ]
            )

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "disk budget" in captured.err

    # Neither the final archive nor a temp file should have been created
    assert not os.path.exists(out_path)
    assert not os.path.exists(out_path + ".tmp")
