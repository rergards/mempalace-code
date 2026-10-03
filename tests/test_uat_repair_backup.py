"""UAT regressions for backup create/list/retention and restore safety."""

import glob
import json
import os
import stat
import sys
import tarfile
from unittest.mock import patch

import pytest

import mempalace_code.backup as backup_module
from mempalace_code.backup import (
    BackupSourceError,
    create_backup,
    list_backups,
    managed_backups_dir,
)
from mempalace_code.cli import main
from mempalace_code.knowledge_graph import palace_kg_path
from mempalace_code.operation_lock import OperationLock
from mempalace_code.storage import ChromaRuntimeRetiredError, open_store


def _make_palace(path: str, wing: str, n: int = 2) -> str:
    store = open_store(path, create=True)
    for i in range(n):
        store.add(
            ids=[f"drawer_{wing}_{i}"],
            documents=[f"{wing} fact number {i}"],
            metadatas=[{"wing": wing, "room": "notes"}],
        )
    return path


def _run(argv, capsys):
    code = 0
    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr()
    return code, out.out, out.err


def _wings(archive: str) -> list:
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile("mempalace_backup/metadata.json")
        assert member is not None
        return json.loads(member.read())["wings"]


# ── Per-palace retention and listing (backup-1 ×2) ─────────────────────────────


def test_sibling_palaces_keep_separate_backups_and_retention(tmp_path, monkeypatch):
    palace_x = _make_palace(str(tmp_path / "palaceX"), "projX")
    palace_y = _make_palace(str(tmp_path / "palaceY"), "projY")
    x_archives = [create_backup(palace_x, kind="scheduled")[1] for _ in range(3)]
    for _ in range(5):
        create_backup(palace_y, kind="scheduled")

    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "2")
    create_backup(palace_y, kind="scheduled")

    assert all(os.path.isfile(path) for path in x_archives)
    listed_x = list_backups(palace_x)
    assert sorted(e["path"] for e in listed_x) == sorted(os.path.abspath(p) for p in x_archives)
    assert all(_wings(e["path"]) == ["projX"] for e in listed_x)
    listed_y = list_backups(palace_y)
    assert len(listed_y) == 2
    assert all(_wings(e["path"]) == ["projY"] for e in listed_y)
    assert managed_backups_dir(palace_x) == str(tmp_path / "backups" / "palaceX")


def test_pre_optimize_backups_of_siblings_do_not_prune_each_other(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")
    palace_a = _make_palace(str(tmp_path / "pal_a"), "a")
    palace_b = _make_palace(str(tmp_path / "pal_b"), "b")
    _, a_archive = create_backup(palace_a, kind="pre_optimize")
    for _ in range(3):
        create_backup(palace_b, kind="pre_optimize")

    assert os.path.isfile(a_archive)
    assert len(os.listdir(managed_backups_dir(palace_b))) == 1


def test_legacy_shared_dir_archives_are_listed_as_shared_and_never_pruned(tmp_path, monkeypatch):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    legacy_dir = tmp_path / "backups"
    legacy_dir.mkdir()
    legacy = str(legacy_dir / "scheduled_20200101_000000_000000.tar.gz")
    create_backup(palace, out_path=legacy)
    other = str(legacy_dir / "scheduled_20200101_000001_000000.tar.gz")
    other_palace = _make_palace(str(tmp_path / "other"), "o")
    create_backup(other_palace, out_path=other)  # records the other palace's path

    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")
    create_backup(palace, kind="scheduled")
    create_backup(palace, kind="scheduled")

    assert os.path.isfile(legacy)
    entries = {e["path"]: e for e in list_backups(palace)}
    assert entries[os.path.abspath(legacy)]["location"] == "shared"
    assert entries[os.path.abspath(legacy)]["stale"] is False
    assert os.path.abspath(other) not in entries


def test_backup_list_json(tmp_path, capsys):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    create_backup(palace)

    code, out, _ = _run(["--palace", palace, "backup", "list", "--json"], capsys)

    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert len(payload["backups"]) == 1
    assert payload["backups"][0]["location"] == "managed"
    assert payload["backups"][0]["palace_path"] == os.path.abspath(palace)


# ── Nothing to back up / degraded (backup-1) ───────────────────────────────────


@pytest.mark.parametrize("shape", ["missing", "empty-dir", "failed-first-mine"])
def test_backup_create_refuses_when_there_is_nothing_to_back_up(tmp_path, capsys, shape):
    target = tmp_path / "target"
    if shape != "missing":
        target.mkdir()
    if shape == "failed-first-mine":
        (target / "lance").mkdir()
        (target / "lance" / "__manifest").mkdir()  # LanceDB bookkeeping, no drawer table
    archive = tmp_path / "out.tar.gz"

    code, out, err = _run(
        ["--palace", str(target), "backup", "create", "--out", str(archive)], capsys
    )

    assert code == 1
    assert f"No palace found at {target}" in err
    assert f"--palace {target} mine <dir>" in err
    # A failed first mine points at the usual cause: a missing embedding model.
    assert (" fetch-model" in err) == (shape == "failed-first-mine")
    assert "Backed up" not in out
    assert not archive.exists()


def test_backup_create_refuses_a_legacy_chroma_palace(tmp_path, capsys):
    target = tmp_path / "chroma"
    target.mkdir()
    (target / "chroma.sqlite3").write_text("x")
    archive = tmp_path / "b.tar.gz"

    with pytest.raises(ChromaRuntimeRetiredError):
        create_backup(str(target), out_path=str(archive))
    code, _, err = _run(
        ["--palace", str(target), "backup", "create", "--out", str(archive)], capsys
    )

    assert code == 1
    assert "retired" in err
    assert not archive.exists()


def test_degraded_palace_backup_is_flagged_and_never_rotates_healthy_ones(
    tmp_path, capsys, monkeypatch
):
    palace = _make_palace(str(tmp_path / "palace"), "w", n=1)
    monkeypatch.setenv("MEMPALACE_BACKUP_RETAIN_COUNT", "1")
    _, healthy = create_backup(palace, kind="scheduled")
    before = set(glob.glob(os.path.join(palace, "lance", "mempalace_drawers.lance", "data", "*")))
    open_store(palace, create=False).add(
        ids=["drawer_w_late"], documents=["late"], metadatas=[{"wing": "w", "room": "notes"}]
    )
    for path in set(glob.glob(os.path.join(palace, "lance", "*", "data", "*"))) - before:
        os.remove(path)

    code, out, err = _run(["--palace", palace, "backup", "create", "--kind", "scheduled"], capsys)

    assert code == 1
    assert "DEGRADED" in out
    assert "restore refuses it" in err
    assert os.path.isfile(healthy)
    [degraded] = [e for e in list_backups(palace) if e["degraded"]]
    assert degraded["path"].endswith("_DEGRADED.tar.gz")
    with tarfile.open(degraded["path"], "r:gz") as tar:
        member = tar.extractfile("mempalace_backup/metadata.json")
        assert member is not None
        assert json.loads(member.read())["degraded"] is True


# ── --out handling (backup-2) ──────────────────────────────────────────────────


def test_backup_out_never_overwrites_and_rejects_a_directory(tmp_path, capsys):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    existing = tmp_path / "existing.tar.gz"
    existing.write_text("precious")

    code, _, err = _run(["--palace", palace, "backup", "create", "--out", str(existing)], capsys)
    assert code == 1
    assert "already exists" in err
    assert existing.read_text() == "precious"

    code, _, err = _run(["--palace", palace, "backup", "create", "--out", str(tmp_path)], capsys)
    assert code == 1
    assert "--out is a directory" in err
    assert ".tar.gz.tmp" not in err
    assert "Errno" not in err


def test_backup_out_prints_absolute_path_and_warns_on_extension(tmp_path, capsys, monkeypatch):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    monkeypatch.chdir(tmp_path)

    code, out, _ = _run(["--palace", palace, "backup", "create", "--out", "rel.tar.gz"], capsys)
    assert code == 0
    assert f"Archive: {tmp_path / 'rel.tar.gz'}" in out
    assert stat.S_IMODE(os.stat(tmp_path / "rel.tar.gz").st_mode) == 0o600

    code, _, err = _run(["--palace", palace, "backup", "create", "--out", "out3.zip"], capsys)
    assert code == 0
    assert "name it *.tar.gz" in err


# ── Concurrent writers (backup-2) ──────────────────────────────────────────────


def test_backup_skips_lance_temp_files_and_retries_when_files_vanish(tmp_path):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    real_listdir = os.listdir
    calls = {"n": 0}

    def racing_listdir(path):
        names = real_listdir(path)
        if path.endswith(os.path.join("mempalace_drawers.lance", "data")):
            calls["n"] += 1
            if calls["n"] == 1:  # a compaction removed this file mid-walk
                names = [*names, "vanished-fragment.lance"]
            names = [*names, ".tmpABC123"]  # an uncommitted Lance temp file
        return names

    with patch.object(backup_module.os, "listdir", racing_listdir):
        meta, archive = create_backup(palace, out_path=str(tmp_path / "b.tar.gz"))

    assert calls["n"] == 2
    assert meta["drawer_count"] == 2
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert not any(".tmp" in name for name in names)


def test_backup_fails_clearly_when_the_palace_keeps_changing(tmp_path):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    real_listdir = os.listdir

    def always_racing(path):
        names = real_listdir(path)
        if path.endswith("data"):
            names = [*names, "vanished-fragment.lance"]
        return names

    with patch.object(backup_module.os, "listdir", always_racing):
        with patch.object(backup_module.time, "sleep"):
            with pytest.raises(RuntimeError, match="changed while it was being archived"):
                create_backup(palace, out_path=str(tmp_path / "b.tar.gz"))
    assert not (tmp_path / "b.tar.gz").exists()
    assert not glob.glob(str(tmp_path / "*.tmp"))


def _commit_during_lance_walk(palace: str, commits: dict, *, every_attempt: bool):
    """Wrap _add_tree so a separate writer commits a drawer while lance/ is archived."""
    writer = open_store(palace, create=True)
    real_add_tree = backup_module._add_tree

    def add_tree(tar, path, arcname, vanished):
        if arcname == "mempalace_backup/lance" and (every_attempt or commits["n"] == 0):
            commits["n"] += 1
            writer.add(
                ids=[f"drawer_w_late_{commits['n']}"],
                documents=[f"fact committed while archiving {commits['n']}"],
                metadatas=[{"wing": "w", "room": "notes"}],
            )
        real_add_tree(tar, path, arcname, vanished)

    return add_tree


def test_backup_retries_when_a_commit_lands_while_archiving(tmp_path):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    commits = {"n": 0}

    add_tree = _commit_during_lance_walk(palace, commits, every_attempt=False)
    with patch.object(backup_module, "_add_tree", add_tree):
        with patch.object(backup_module.time, "sleep"):
            meta, archive = create_backup(palace, out_path=str(tmp_path / "b.tar.gz"))

    assert commits["n"] == 1
    assert meta["drawer_count"] == 3  # the archive's version, not the one before the commit
    restored = str(tmp_path / "restored")
    backup_module.restore_backup(archive, restored)
    assert open_store(restored, create=False, read_only=True).count() == 3


def test_backup_fails_clearly_when_commits_keep_landing(tmp_path):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    commits = {"n": 0}

    add_tree = _commit_during_lance_walk(palace, commits, every_attempt=True)
    with patch.object(backup_module, "_add_tree", add_tree):
        with patch.object(backup_module.time, "sleep"):
            with pytest.raises(RuntimeError, match="changed while it was being archived"):
                create_backup(palace, out_path=str(tmp_path / "b.tar.gz"))

    assert commits["n"] == 3
    assert not (tmp_path / "b.tar.gz").exists()
    assert not glob.glob(str(tmp_path / "*.tmp"))


def test_backup_source_error_is_a_runtime_error():
    assert issubclass(BackupSourceError, RuntimeError)


# ── Restore (restore-1, maint-1, restore-2, restore-3) ─────────────────────────


def test_force_restore_refuses_while_another_process_holds_a_lease(tmp_path, capsys):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    _, archive = create_backup(palace, out_path=str(tmp_path / "b.tar.gz"))
    lance_before = sorted(os.listdir(os.path.join(palace, "lance", "mempalace_drawers.lance")))

    with OperationLock.default().acquire_shared("watcher"):
        code, out, err = _run(["--palace", palace, "restore", archive, "--force"], capsys)

    assert code == 1
    assert "operation=watcher" in err
    assert "Restored palace" not in out
    assert sorted(os.listdir(os.path.join(palace, "lance", "mempalace_drawers.lance"))) == (
        lance_before
    )


def test_restore_into_a_new_palace_needs_no_exclusive_lease(tmp_path, capsys):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    _, archive = create_backup(palace, out_path=str(tmp_path / "b.tar.gz"))
    target = str(tmp_path / "restored")

    with OperationLock.default().acquire_shared("mcp-stdio"):
        code, out, _ = _run(["--palace", target, "restore", archive], capsys)

    assert code == 0
    assert "Restored palace to:" in out
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o700


def test_force_restore_into_a_symlinked_root_names_the_resolved_path(tmp_path, capsys):
    palace = _make_palace(str(tmp_path / "palace"), "w")
    _, archive = create_backup(palace, out_path=str(tmp_path / "b.tar.gz"))
    link = tmp_path / "link"
    link.symlink_to(palace)

    code, _, err = _run(["--palace", str(link), "restore", archive, "--force"], capsys)

    assert code == 1
    assert "is a symlink to" in err
    assert f"--palace {os.path.realpath(palace)} restore" in err
    assert "not a directory" not in err
    assert "use --force only if" not in err  # the generic hint would contradict the refusal


def test_restore_failure_messages_name_the_archive(tmp_path, capsys):
    not_a_tar = tmp_path / "notatar"
    not_a_tar.write_text("hello")

    code, _, err = _run(["--palace", str(tmp_path / "t"), "restore", str(not_a_tar)], capsys)

    assert code == 1
    assert str(not_a_tar) in err
    assert "backup create --out" not in err


# ── Live palace permissions (gap-10) ───────────────────────────────────────────


def test_new_palace_directory_is_owner_only(tmp_path):
    palace = _make_palace(str(tmp_path / "palace"), "w")

    assert stat.S_IMODE(os.stat(palace).st_mode) == 0o700
    assert os.path.dirname(palace_kg_path(palace)) == palace


def _write_project(root, name: str) -> str:
    project = root / name
    project.mkdir()
    (project / "mempalace.yaml").write_text(
        f"wing: {name}\nrooms:\n- name: general\n  description: All files\n  keywords: []\n"
    )
    (project / "notes.md").write_text(
        "# Payments\n\n"
        + "The refund gateway retries failed payouts three times before paging on-call. " * 8
    )
    return str(project)


@pytest.mark.parametrize("mode", ["projects", "convos"])
def test_mine_creates_an_owner_only_palace(tmp_path, capsys, mode):
    palace = tmp_path / "new-palace"
    if mode == "projects":
        argv = ["--palace", str(palace), "mine", _write_project(tmp_path, "proj")]
    else:
        convos = tmp_path / "convos"
        convos.mkdir()
        (convos / "chat.txt").write_text(
            "> how do refunds work in the payments service\n"
            "The refund gateway retries failed payouts three times before paging on-call.\n\n"
            "> what happens after the third retry\n"
            "The payout is parked and an operator reviews it in the morning queue.\n"
        )
        argv = ["--palace", str(palace), "mine", str(convos), "--mode", "convos"]
        argv.append("--no-spellcheck")

    old_umask = os.umask(0o022)
    try:
        code, _, err = _run(argv, capsys)
    finally:
        os.umask(old_umask)

    assert code == 0, err
    assert stat.S_IMODE(palace.stat().st_mode) == 0o700


def test_existing_palace_directory_keeps_its_permissions(tmp_path):
    palace = tmp_path / "shared"
    palace.mkdir()
    palace.chmod(0o750)

    _make_palace(str(palace), "w")

    assert stat.S_IMODE(palace.stat().st_mode) == 0o750


def test_watcher_starts_after_a_failed_first_mine_left_no_drawer_table(tmp_path):
    """A lance/ holding only LanceDB bookkeeping has nothing to back up; watch still starts."""
    pytest.importorskip("watchfiles")
    from mempalace_code.watcher import watch_and_mine

    palace = tmp_path / "palace"
    (palace / "lance" / "__manifest").mkdir(parents=True)
    project = tmp_path / "proj"
    project.mkdir()
    mined = []

    def fake_watch(*args, stop_event=None, **kwargs):
        yield from ()

    with (
        patch("mempalace_code.watcher.mine", side_effect=lambda **kw: mined.append(kw) or {}),
        patch("watchfiles.watch", side_effect=fake_watch),
    ):
        watch_and_mine(str(project), str(palace))

    assert mined, "the initial mine must run"
    assert not (tmp_path / "backups").exists()
