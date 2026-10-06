"""Configured backup destinations preserve the existing backup contract."""

import errno
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from mempalace_code import backup, disk_budget, watcher
from mempalace_code.config import MempalaceConfig
from mempalace_code.knowledge_graph import KnowledgeGraph, palace_kg_path


@pytest.fixture
def destination(tmp_path, monkeypatch):
    root = tmp_path / "second-disk" / "archives"
    monkeypatch.setenv("MEMPALACE_BACKUP_DIR", str(root))
    monkeypatch.setenv("MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES", "1")
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "2")
    return root


@pytest.fixture
def kg_palace(tmp_path):
    palace = tmp_path / "data" / "palace"
    palace.mkdir(parents=True)
    KnowledgeGraph(db_path=palace_kg_path(str(palace)))
    return palace


def test_unset_preserves_default_and_footprint(kg_palace, monkeypatch):
    monkeypatch.delenv("MEMPALACE_BACKUP_DIR", raising=False)
    expected = kg_palace.parent / "backups" / kg_palace.name
    assert backup.managed_backups_dir(str(kg_palace)) == str(expected)
    sibling = expected.parent / "another-palace"
    sibling.mkdir(parents=True)
    (sibling / "existing.tar.gz").write_bytes(b"old")
    assert disk_budget.palace_footprint(str(kg_palace))[1] == 3
    assert watcher.check_configured_watch_budget(str(kg_palace), 1).backups_bytes == 3
    _, archive = backup.create_backup(str(kg_palace))
    assert Path(archive).parent == expected


@pytest.mark.parametrize("value", [True, 4, [], {}, "", "  ", "bad\x00path"])
def test_invalid_setting_refuses_without_fallback(kg_palace, tmp_path, monkeypatch, value):
    monkeypatch.delenv("MEMPALACE_BACKUP_DIR", raising=False)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({"backup_dir": value}))
    cfg = MempalaceConfig(config_dir=cfg_dir)
    with pytest.raises(ValueError, match="backup_dir"):
        backup.create_backup(str(kg_palace), config=cfg)
    assert not (kg_palace.parent / "backups").exists()
    _, archive = backup.create_backup(
        str(kg_palace), out_path=str(tmp_path / "explicit.tar.gz"), config=cfg
    )
    assert Path(archive).is_file()


def test_normalization_and_environment_precedence(tmp_path, monkeypatch, capsys):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({"backup_dir": "~/copies"}))
    monkeypatch.delenv("MEMPALACE_BACKUP_DIR", raising=False)
    cfg = MempalaceConfig(config_dir=cfg_dir)
    assert cfg.backup_dir == str(Path.home() / "copies")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MEMPALACE_BACKUP_DIR", "relative-copies")
    assert cfg.backup_dir == str(tmp_path / "relative-copies")
    assert "relative" in capsys.readouterr().err
    monkeypatch.setenv("MEMPALACE_BACKUP_DIR", "")
    with pytest.raises(ValueError, match="MEMPALACE_BACKUP_DIR"):
        _ = cfg.backup_dir


def test_null_setting_is_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("MEMPALACE_BACKUP_DIR", raising=False)
    (tmp_path / "config.json").write_text('{"backup_dir": null}')
    assert MempalaceConfig(config_dir=tmp_path).backup_dir is None


@pytest.mark.parametrize("kind", ["manual", "scheduled", "pre_watch", "pre_optimize"])
def test_kinds_list_and_rotation_use_destination(kg_palace, destination, kind):
    source = Path(palace_kg_path(str(kg_palace))).read_bytes()
    archives = [backup.create_backup(str(kg_palace), kind=kind)[1] for _ in range(3)]
    managed = Path(backup.managed_backups_dir(str(kg_palace)))
    assert managed.parent == destination
    assert not Path(archives[0]).exists()
    assert all(Path(p).is_file() for p in archives[1:])
    entries = backup.list_backups(str(kg_palace))
    assert {e["path"] for e in entries} == set(archives[1:])
    assert all(e["kind"] == kind and e["location"] == "managed" for e in entries)
    assert watcher.check_configured_watch_budget(str(kg_palace), 1).backups_bytes == sum(
        Path(p).stat().st_size for p in archives[1:]
    )
    assert Path(palace_kg_path(str(kg_palace))).read_bytes() == source
    assert stat.S_IMODE(managed.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(Path(p).stat().st_mode) == 0o600 for p in archives[1:])
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700
    assert not (kg_palace.parent / "backups").exists()


def test_retention_isolates_palaces_kinds_and_degraded(kg_palace, destination, tmp_path):
    other = tmp_path / "unrelated" / kg_palace.name
    other.mkdir(parents=True)
    KnowledgeGraph(db_path=palace_kg_path(str(other)))
    assert backup.managed_backups_dir(str(other)) != backup.managed_backups_dir(str(kg_palace))
    other_archive = Path(backup.create_backup(str(other))[1])
    other_bytes = other_archive.read_bytes()
    healthy = [backup.create_backup(str(kg_palace))[1] for _ in range(2)]
    scheduled = backup.create_backup(str(kg_palace), kind="scheduled")[1]
    Path(palace_kg_path(str(kg_palace))).write_bytes(b"broken SQLite")
    degraded = [backup.create_backup(str(kg_palace))[1] for _ in range(3)]
    assert all(Path(p).exists() for p in healthy + [scheduled] + degraded[1:])
    assert not Path(degraded[0]).exists()
    assert other_archive.read_bytes() == other_bytes


def test_changing_setting_is_read_only_and_preserves_existing_archives(
    kg_palace, destination, monkeypatch
):
    destination.mkdir(parents=True)
    destination.chmod(0o755)
    archive = Path(backup.create_backup(str(kg_palace))[1])
    original = archive.read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o755
    new_root = destination.parent / "new-root"
    monkeypatch.setenv("MEMPALACE_BACKUP_DIR", str(new_root))
    assert backup.list_backups(str(kg_palace)) == []
    assert watcher.check_configured_watch_budget(str(kg_palace), 1).backups_bytes == 0
    assert not new_root.exists()
    assert archive.read_bytes() == original


def test_explicit_output_bypasses_rotation(kg_palace, destination, tmp_path, monkeypatch):
    retained = Path(backup.create_backup(str(kg_palace))[1])
    original = retained.read_bytes()
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")
    for n in range(3):
        backup.create_backup(str(kg_palace), out_path=str(tmp_path / f"explicit-{n}.tar.gz"))
    assert retained.read_bytes() == original
    assert len(backup.list_backups(str(kg_palace))) == 1


@pytest.mark.parametrize(
    "source_free,destination_free,allowed", [(0, 1000000, True), (1000000, 0, False)]
)
def test_free_space_uses_destination(
    kg_palace, destination, monkeypatch, source_free, destination_free, allowed
):
    checked = []

    def free(path):
        checked.append(path)
        return destination_free if Path(path).is_relative_to(destination) else source_free

    monkeypatch.setattr(disk_budget, "free_bytes", free)
    if allowed:
        assert Path(backup.create_backup(str(kg_palace))[1]).is_file()
    else:
        with pytest.raises(disk_budget.DiskBudgetError):
            backup.create_backup(str(kg_palace))
        assert not list(destination.rglob("*.tar.gz"))
    assert checked
    assert all(Path(p).is_relative_to(destination) for p in checked)
    assert not (kg_palace.parent / "backups").exists()


def test_destination_free_space_error_fails_closed(kg_palace, destination, monkeypatch):
    def denied(path):
        raise PermissionError(errno.EACCES, "denied", path)

    monkeypatch.setattr(disk_budget, "free_bytes", denied)
    with pytest.raises(OSError, match="backup_dir"):
        backup.create_backup(str(kg_palace))
    assert not list(destination.rglob("*.tar.gz"))
    assert not (kg_palace.parent / "backups").exists()


@pytest.mark.parametrize("case", ["file", "denied", "inside", "source-symlink", "child-symlink"])
def test_invalid_destination_preserves_other_data(kg_palace, destination, monkeypatch, case):
    target = destination / "another-palace"
    if case == "file":
        destination.parent.mkdir()
        destination.write_bytes(b"keep")
    elif case == "denied":
        destination.mkdir(parents=True)
        destination.chmod(0)
    elif case == "inside":
        monkeypatch.setenv("MEMPALACE_BACKUP_DIR", str(kg_palace / "copies"))
    elif case == "source-symlink":
        destination.parent.mkdir()
        destination.symlink_to(kg_palace, target_is_directory=True)
    else:
        destination.mkdir(parents=True)
        target.mkdir()
        (target / "mempalace_backup_old.tar.gz").write_bytes(b"keep")
        Path(backup.managed_backups_dir(str(kg_palace))).symlink_to(
            target, target_is_directory=True
        )
    try:
        for operation in (backup.create_backup, backup.list_backups):
            with pytest.raises((ValueError, OSError)):
                operation(str(kg_palace))
        assert not (kg_palace.parent / "backups").exists()
        if case == "file":
            assert destination.read_bytes() == b"keep"
        elif case == "child-symlink":
            assert (target / "mempalace_backup_old.tar.gz").read_bytes() == b"keep"
            assert stat.S_IMODE(target.stat().st_mode) == 0o755
    finally:
        if case == "denied":
            destination.chmod(0o700)


def test_automatic_callers_use_destination(palace_path, seeded_collection, seeded_kg, destination):
    from mempalace_code.watcher import _create_pre_watch_backup

    watched = _create_pre_watch_backup(palace_path, seeded_kg.db_path, "backup-dir-test")
    assert watched
    assert Path(watched).is_relative_to(destination)
    assert seeded_collection.safe_optimize(
        palace_path, backup_first=True, kg_path=seeded_kg.db_path
    )
    assert {e["kind"] for e in backup.list_backups(palace_path)} == {"pre_watch", "pre_optimize"}


def test_real_cli_success_failure_and_explicit_priority(kg_palace, destination, tmp_path):
    command = [sys.executable, "-m", "mempalace_code", "--palace", str(kg_palace), "backup"]
    created = subprocess.run(
        command + ["create", "--kind", "scheduled"], capture_output=True, text=True
    )
    assert created.returncode == 0, created.stderr
    listed = subprocess.run(command + ["list", "--json"], capture_output=True, text=True)
    assert listed.returncode == 0, listed.stderr
    entries = json.loads(listed.stdout)["backups"]
    assert len(entries) == 1
    assert entries[0]["kind"] == "scheduled"
    assert Path(entries[0]["path"]).is_relative_to(destination)
    env = dict(os.environ, MEMPALACE_BACKUP_DIR="")
    refused = subprocess.run(command + ["create"], env=env, capture_output=True, text=True)
    assert refused.returncode == 1
    assert "MEMPALACE_BACKUP_DIR" in refused.stderr
    explicit = tmp_path / "explicit-cli.tar.gz"
    accepted = subprocess.run(
        command + ["create", "--out", str(explicit)], env=env, capture_output=True, text=True
    )
    assert accepted.returncode == 0, accepted.stderr
    assert explicit.is_file()
    assert not (kg_palace.parent / "backups").exists()
