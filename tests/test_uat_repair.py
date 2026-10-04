"""UAT regressions for repair, rollback, health, cleanup, and degraded-palace reads."""

import glob
import json
import os
import sys
from typing import Any, cast
from unittest.mock import patch

import pytest

from mempalace_code.cli import main
from mempalace_code.cli_invocation import cli_command
from mempalace_code.knowledge_graph import KnowledgeGraph, palace_kg_path
from mempalace_code.operation_lock import OperationLock
from mempalace_code.storage import LanceStore, PalaceReadError, open_store


def _data_files(palace: str) -> set:
    return set(glob.glob(os.path.join(palace, "lance", "mempalace_drawers.lance", "data", "*")))


def _make_palace(root, n_fragments: int = 3) -> tuple[str, list[set]]:
    """Palace with one drawer per fragment, a KG with two triples, and a sidecar file."""
    palace = str(root / "palace")
    store = open_store(palace, create=True)
    fragments = []
    for i in range(n_fragments):
        before = _data_files(palace)
        store.add(
            ids=[f"drawer_w_r_{i:04d}"],
            documents=[f"Diary entry number {i} about the refund gateway"],
            metadatas=[{"wing": "wing_uat", "room": "diary", "added_by": "diary"}],
        )
        fragments.append(_data_files(palace) - before)
    kg = KnowledgeGraph(palace_kg_path(palace))
    kg.add_triple("Aiko", "works_on", "payments")
    kg.add_triple("refund", "part_of", "billing")
    os.makedirs(os.path.join(palace, ".mempalace"), exist_ok=True)
    with open(os.path.join(palace, ".mempalace", "tiny_hashes.json"), "w") as fh:
        fh.write('{"x": "y"}')
    return palace, fragments


def _run(argv, capsys):
    """Run the CLI; return (exit code, stdout, stderr)."""
    code = 0
    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    out = capsys.readouterr()
    return code, out.out, out.err


def _kg_triples(palace: str) -> int:
    return KnowledgeGraph(palace_kg_path(palace)).stats()["triples"]


def _backups(palace: str) -> list:
    return sorted(glob.glob(f"{palace}.backup*"))


# ── Full rebuild (ops-1, repair-2, repair-3, repair-5, repair-6, ops-3, repair-1) ──


def test_full_repair_keeps_kg_and_sidecars_in_place(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)

    code, out, err = _run(["--palace", palace, "repair"], capsys)

    assert code == 0, err
    assert "3 of 3 drawers rebuilt" in out
    assert _kg_triples(palace) == 2
    assert os.path.isfile(os.path.join(palace, ".mempalace", "tiny_hashes.json"))
    assert open_store(palace, create=False, read_only=True).count() == 3
    [backup] = _backups(palace)
    assert os.path.isfile(os.path.join(backup, "knowledge_graph.sqlite3"))
    assert os.path.isdir(os.path.join(backup, "lance"))
    assert "Kept in place:" in out
    assert "knowledge_graph.sqlite3" in out


def test_repeated_repair_never_deletes_an_earlier_backup(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)
    legacy = f"{palace}.backup"
    os.makedirs(legacy)
    with open(os.path.join(legacy, "SENTINEL"), "w") as fh:
        fh.write("only copy")

    assert _run(["--palace", palace, "repair"], capsys)[0] == 0
    assert _run(["--palace", palace, "repair"], capsys)[0] == 0

    assert open(os.path.join(legacy, "SENTINEL")).read() == "only copy"
    assert len(_backups(palace)) == 3  # the legacy one plus two new timestamped copies
    assert _kg_triples(palace) == 2


def test_repair_stops_without_changes_when_a_drawer_is_unreadable(tmp_path, capsys):
    palace, fragments = _make_palace(tmp_path)
    for path in fragments[0]:
        os.remove(path)
    files_before = _data_files(palace)

    code, out, err = _run(["--palace", palace, "repair"], capsys)

    assert code == 1
    assert "at least one of the 3 drawers could not be read" in err
    assert "The palace was not changed" in err
    assert f"--palace {palace} repair --salvage" in err
    assert f"--palace {palace} backup list" in err
    assert "Repair complete" not in out
    assert _data_files(palace) == files_before
    assert _backups(palace) == []
    assert _kg_triples(palace) == 2


def test_repair_salvage_rebuilds_the_readable_drawers(tmp_path, capsys):
    palace, fragments = _make_palace(tmp_path)
    for path in fragments[0]:
        os.remove(path)

    code, out, err = _run(["--palace", palace, "repair", "--salvage"], capsys)

    assert code == 0, err
    assert "2 of 3 drawers rebuilt; 1 unreadable" in out
    store = open_store(palace, create=False, read_only=True)
    assert store.health_check()["ok"] is True
    assert sorted(store.get(include=[])["ids"]) == ["drawer_w_r_0001", "drawer_w_r_0002"]
    assert _kg_triples(palace) == 2
    [backup] = _backups(palace)
    assert open_store(backup, create=False, read_only=True).count() == 3


def test_repair_that_cannot_save_its_copy_leaves_the_palace_as_it_was(tmp_path, capsys):
    import errno

    palace, _ = _make_palace(tmp_path)
    files_before = _data_files(palace)

    def disk_full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    with patch("mempalace_code.cli_commands.maintenance.shutil.copy2", disk_full):
        code, out, err = _run(["--palace", palace, "repair"], capsys)

    assert code == 1
    assert "could not save the pre-repair copy" in err
    assert "Repair complete" not in out
    assert _data_files(palace) == files_before
    assert open_store(palace, create=False, read_only=True).count() == 3
    assert _kg_triples(palace) == 2
    assert not glob.glob(os.path.join(palace, ".mempalace-repair-*"))


def test_plain_repair_stops_at_the_first_failed_read_without_bisecting(tmp_path):
    palace = str(tmp_path / "palace")
    store = open_store(palace, create=True)
    store.add(
        ids=[f"drawer_w_r_{i:04d}" for i in range(16)],
        documents=[f"Diary entry number {i} about the refund gateway" for i in range(16)],
        metadatas=[{"wing": "wing_uat", "room": "diary"}] * 16,
    )
    for path in _data_files(palace):
        os.remove(path)

    class CountingTable:
        def __init__(self, table):
            self._table = table
            self.searches = 0

        def search(self, *args, **kwargs):
            self.searches += 1
            return self._table.search(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._table, name)

    plain = open_store(palace, create=False, read_only=True)
    plain_table = CountingTable(plain._table)
    plain._table = cast("Any", plain_table)  # counting proxy around the real table
    result = plain.read_all_for_rebuild(salvage=False)
    assert plain_table.searches == 1  # one failed batch decides; no row-by-row bisecting
    assert result["stopped_at"] == 0
    assert result["rows"] == []

    salvage = open_store(palace, create=False, read_only=True)
    salvage_table = CountingTable(salvage._table)
    salvage._table = cast("Any", salvage_table)
    result = salvage.read_all_for_rebuild(salvage=True)
    assert salvage_table.searches == 31  # 16 rows bisected down to single-row reads
    assert result["stopped_at"] is None
    assert result["unreadable"] == 16


def test_repair_stops_when_another_process_writes_meanwhile(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)
    real_write = LanceStore.write_rebuilt_table

    def rebuild_while_a_miner_commits(self, staging, rows, *args, **kwargs):
        rebuilt = real_write(self, staging, rows, *args, **kwargs)
        miner = open_store(palace, create=True)
        miner.add(
            ids=["drawer_race_1"],
            documents=["Written by a miner while repair was running"],
            metadatas=[{"wing": "wing_uat", "room": "diary"}],
        )
        return rebuilt

    with patch.object(LanceStore, "write_rebuilt_table", rebuild_while_a_miner_commits):
        code, out, err = _run(["--palace", palace, "repair"], capsys)

    assert code == 1
    assert "another process wrote to the palace while repair was reading it" in err
    assert "The palace was not changed" in err
    assert f"then run {cli_command('repair', palace=palace)}" in err
    assert "Repair complete" not in out
    store = open_store(palace, create=False, read_only=True)
    assert store.count() == 4
    assert store.get(ids=["drawer_race_1"])["ids"] == ["drawer_race_1"]
    assert _backups(palace) == []
    assert not glob.glob(os.path.join(palace, ".mempalace-repair-*"))


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_repair_without_a_writable_parent_explains_and_changes_nothing(tmp_path, capsys):
    parent = tmp_path / "readonly-parent"
    parent.mkdir()
    palace, _ = _make_palace(parent)
    files_before = _data_files(palace)

    os.chmod(parent, 0o555)
    try:
        code, out, err = _run(["--palace", palace, "repair"], capsys)
    finally:
        os.chmod(parent, 0o755)

    assert code == 1
    assert "Traceback" not in err
    assert "repair cannot create its pre-repair copy next to the palace" in err
    assert "The palace was not changed" in err
    assert f"make {parent} writable" in err
    assert "Repair complete" not in out
    assert _data_files(palace) == files_before
    assert _backups(palace) == []
    assert not glob.glob(os.path.join(palace, ".mempalace-repair-*"))


def test_repair_salvage_refuses_when_nothing_is_readable(tmp_path, capsys):
    palace, fragments = _make_palace(tmp_path, n_fragments=1)
    for path in fragments[0]:
        os.remove(path)

    code, out, err = _run(["--palace", palace, "repair", "--salvage"], capsys)

    assert code == 1
    assert "none of the 1 drawers can be read" in err
    assert "Repair complete" not in out
    assert _backups(palace) == []


@pytest.mark.parametrize("shape", ["empty-dir", "project-dir", "failed-first-mine"])
def test_repair_on_a_non_palace_exits_nonzero(tmp_path, capsys, shape):
    target = tmp_path / "target"
    target.mkdir()
    if shape == "project-dir":
        (target / "README.md").write_text("# project\n")
    elif shape == "failed-first-mine":
        (target / "lance").mkdir()

    code, _, err = _run(["--palace", str(target), "repair"], capsys)

    assert code == 1
    assert f"No palace found at {target}" in err
    assert f"--palace {target} mine <dir>" in err
    assert (" fetch-model" in err) == (shape == "failed-first-mine")


def test_repair_on_legacy_chroma_palace_exits_nonzero(tmp_path, capsys):
    target = tmp_path / "chroma"
    target.mkdir()
    (target / "chroma.sqlite3").write_text("x")

    code, _, err = _run(["--palace", str(target), "repair"], capsys)

    assert code == 1
    assert "retired" in err.lower()


@pytest.mark.parametrize(
    "argv",
    [["repair"], ["repair", "--rollback"], ["cleanup"], ["cleanup", "--unsafe-now"]],
    ids=["repair", "rollback", "cleanup", "cleanup-unsafe-now"],
)
def test_mutating_maintenance_refuses_while_another_process_holds_a_lease(tmp_path, capsys, argv):
    palace, _ = _make_palace(tmp_path)
    files_before = _data_files(palace)

    with OperationLock.default().acquire_shared("mcp-stdio"):
        code, out, err = _run(["--palace", palace, *argv], capsys)

    assert code == 1
    assert "operation=mcp-stdio" in err
    assert "Stop MemPalace MCP servers" in err
    assert f"--palace {palace}" in err
    assert _data_files(palace) == files_before
    assert _backups(palace) == []


def test_rollback_preview_needs_no_lease(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)

    with OperationLock.default().acquire_shared("mcp-stdio"):
        code, out, _ = _run(["--palace", palace, "repair", "--rollback", "--dry-run"], capsys)

    assert code == 0
    assert "Palace is healthy" in out


# ── Rollback (repair-4, ops-2, ops-18) ─────────────────────────────────────────


@pytest.mark.parametrize("dry_run", [True, False], ids=["dry-run", "live"])
def test_rollback_on_a_healthy_palace_changes_nothing(tmp_path, capsys, dry_run):
    palace, _ = _make_palace(tmp_path)
    argv = ["--palace", palace, "repair", "--rollback"] + (["--dry-run"] if dry_run else [])

    code, out, err = _run(argv, capsys)

    assert code == 0, err
    assert "Palace is healthy" in out
    assert "Nothing to roll back" in out
    store = open_store(palace, create=False, read_only=True)
    assert "drawer_w_r_0002" in store.get(include=[])["ids"]


def test_rollback_on_a_healthy_single_version_palace_does_not_suggest_rebuild(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path, n_fragments=1)

    code, out, err = _run(["--palace", palace, "repair", "--rollback"], capsys)

    assert code == 0
    assert "Palace is healthy" in out
    assert "full rebuild" not in out + err


def test_rollback_preview_shows_rows_that_would_be_lost(tmp_path, capsys):
    palace, fragments = _make_palace(tmp_path)
    for path in fragments[-1]:
        os.remove(path)

    code, out, _ = _run(["--palace", palace, "repair", "--rollback", "--dry-run"], capsys)

    assert code == 0
    assert "rows after rollback: 2" in out
    assert "rows that would be lost: 1" in out

    code, out, _ = _run(["--palace", palace, "repair", "--rollback"], capsys)
    assert code == 0
    assert "rows lost: 1" in out
    assert open_store(palace, create=False, read_only=True).health_check()["ok"] is True


def test_repair_help_matches_rollback_behaviour(capsys):
    code, out, _ = _run(["repair", "--help"], capsys)

    assert code == 0
    assert "falling back to full rebuild" not in out
    assert "never falls back to a full rebuild" in " ".join(out.split())
    assert "--salvage" in out


# ── Health (ops-12, install-9, ops-11, ops-20, health-1) ───────────────────────


def test_health_reports_a_corrupt_knowledge_graph(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)
    with open(palace_kg_path(palace), "wb") as fh:
        fh.write(os.urandom(4096))

    code, out, _ = _run(["--palace", palace, "health"], capsys)

    assert code == 1
    assert "DEGRADED" in out
    assert "[kg_corrupt] kg_quick_check" in out
    assert f"--palace {palace} backup list" in out

    code, out, _ = _run(["--palace", palace, "health", "--json"], capsys)
    report = json.loads(out)
    assert code == 1
    assert report["ok"] is False
    assert report["errors"][0]["kind"] == "kg_corrupt"


def test_health_checks_the_knowledge_graph_of_a_palace_with_uri_characters_in_its_path(
    tmp_path, capsys
):
    root = tmp_path / "odd%41 dir"
    root.mkdir()
    palace, _ = _make_palace(root)
    with open(palace_kg_path(palace), "wb") as fh:
        fh.write(os.urandom(4096))

    code, out, _ = _run(["--palace", palace, "health", "--json"], capsys)

    report = json.loads(out)
    assert code == 1
    assert [err["kind"] for err in report["errors"]] == ["kg_corrupt"]
    assert report["warnings"] == []


def test_degraded_read_error_names_every_recovery_step_for_the_palace():
    message = str(PalaceReadError("/data/palace", RuntimeError("fragment missing")))

    # Every step uses this installation's launcher, like search/read hints (ops-8).
    assert cli_command("health", palace="/data/palace") in message
    assert cli_command("repair", "--rollback", "--dry-run", palace="/data/palace") in message
    assert f"{cli_command('repair', palace='/data/palace')} (" in message
    assert cli_command("backup", "list", palace="/data/palace") in message


def test_ids_with_quotes_can_be_read_and_deleted(tmp_path):
    store = open_store(str(tmp_path / "palace"), create=True)
    store.add(
        ids=["drawer_o'neil_1", "drawer_plain_2"],
        documents=["O'Neil wrote this note", "A plain note"],
        metadatas=[{"wing": "o'neil", "room": "notes"}] * 2,
    )

    assert store.get(ids=["drawer_o'neil_1"])["ids"] == ["drawer_o'neil_1"]
    store.delete(["drawer_o'neil_1"])
    assert store.get(include=[])["ids"] == ["drawer_plain_2"]


@pytest.mark.parametrize("shape", ["missing", "project-dir", "failed-first-mine"])
def test_health_on_a_non_palace_says_no_palace_found(tmp_path, capsys, shape):
    target = tmp_path / "target"
    if shape != "missing":
        target.mkdir()
    if shape == "failed-first-mine":
        (target / "lance").mkdir()

    code, out, err = _run(["--palace", str(target), "health"], capsys)

    assert code == 1
    assert f"No palace found at {target}" in err
    assert "rollback" not in out + err

    code, out, _ = _run(["--palace", str(target), "health", "--json"], capsys)
    payload = json.loads(out)
    assert code == 1
    assert payload == {
        "ok": False,
        "error": f"No palace found at {target}",
        "error_code": "no_palace",
        "palace": str(target),
        "next": payload["next"],
    }


def test_health_next_step_keeps_the_selected_palace(tmp_path, capsys):
    palace, fragments = _make_palace(tmp_path)
    for path in fragments[0]:
        os.remove(path)

    code, out, _ = _run(["--palace", palace, "health"], capsys)

    assert code == 1
    rollback = cli_command("repair", "--rollback", "--dry-run", palace=palace)
    assert f"Next: run {rollback}" in out


# ── Cleanup (ops-19, cleanup-1, maint-1, ops-11, health-1) ─────────────────────


def test_cleanup_rejects_negative_days(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)

    code, _, err = _run(["--palace", palace, "cleanup", "--older-than-days", "-1"], capsys)
    assert code == 2
    assert "--older-than-days must be 0 or greater" in err

    code, out, _ = _run(
        ["--palace", palace, "cleanup", "--older-than-days", "-1", "--json"], capsys
    )
    assert code == 2
    assert json.loads(out)["error_code"] == "invalid_argument"


def test_cleanup_dry_run_lists_versions_without_removing_them(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)
    store = open_store(palace, create=False, read_only=True)
    assert isinstance(store, LanceStore)
    versions_before = store.storage_stats()["version_count"]

    code, out, _ = _run(
        ["--palace", palace, "cleanup", "--older-than-days", "0", "--dry-run", "--json"], capsys
    )

    assert code == 0
    preview = json.loads(out)
    assert preview["dry_run"] is True
    # A just-built palace is inside the reader grace: the preview keeps what cleanup keeps.
    listed = preview["versions_to_remove"] + preview["versions_kept_for_readers"]
    assert len(listed) == versions_before - 1
    fresh = open_store(palace, create=False, read_only=True)
    assert isinstance(fresh, LanceStore)
    assert fresh.storage_stats()["version_count"] == versions_before

    code, out, _ = _run(["--palace", palace, "cleanup", "--dry-run"], capsys)
    assert code == 0
    # The estimate covers the whole palace, not only the versions listed for removal.
    assert "Reclaimable in the whole palace (estimate, not only these versions):" in out


def test_cleanup_zero_days_warns_about_rollback_history(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)

    code, out, _ = _run(["--palace", palace, "cleanup", "--older-than-days", "0"], capsys)

    assert code == 0
    assert "repair --rollback loses its history" in out


def test_failed_cleanup_reports_the_real_version_count(tmp_path, capsys):
    palace, _ = _make_palace(tmp_path)
    store = open_store(palace, create=False, read_only=True)
    assert isinstance(store, LanceStore)
    versions = store.storage_stats()["version_count"]
    failed = {
        "ok": False,
        "rows_before": 3,
        "rows_after": 3,
        "freed_bytes": 0,
        "version_count_before": versions,
        "version_count_after": None,
        "error": "simulated",
    }

    with patch.object(LanceStore, "cleanup_stale_fragments", return_value=dict(failed)):
        code, out, err = _run(["--palace", palace, "cleanup", "--json"], capsys)

    assert code == 1
    result = json.loads(out)
    assert result["version_count_after"] == versions
    assert f"--palace {palace} health" in result["next"]

    # When even the re-read fails, the count is reported as unknown, never as 0.
    with (
        patch.object(LanceStore, "cleanup_stale_fragments", return_value=dict(failed)),
        patch.object(LanceStore, "storage_stats", side_effect=RuntimeError("unreadable")),
    ):
        code, out, err = _run(["--palace", palace, "cleanup"], capsys)

    assert code == 1
    assert f"Versions before: {versions}  after: unknown" in out


def test_cleanup_json_on_missing_palace_emits_json(tmp_path, capsys):
    code, out, _ = _run(["--palace", str(tmp_path / "nope"), "cleanup", "--json"], capsys)

    assert code == 1
    assert json.loads(out)["error_code"] == "no_palace"


def test_watcher_recovery_retries_without_rolling_back_a_healthy_palace(tmp_path, capsys):
    """A stale-handle failure on a healthy palace retries the mine; nothing is rolled back."""
    from unittest.mock import MagicMock

    from mempalace_code import watcher

    palace = tmp_path / "palace"
    stale_store = MagicMock(name="stale_store")
    fresh_store = MagicMock(name="fresh_store")
    mine_calls = []

    def fake_mine(**kwargs):
        mine_calls.append(kwargs)
        if len(mine_calls) == 1:
            raise Exception("no such file or directory: fragment.lance")
        return {"embedder_warmed": True}

    recovery_store = MagicMock()
    recovery_store.recover_to_last_working_version.return_value = {
        "recovered": False,
        "healthy": True,
        "candidate_version": None,
    }

    with (
        patch("mempalace_code.watcher.get_collection", side_effect=[stale_store, fresh_store]),
        patch("mempalace_code.watcher.mine", side_effect=fake_mine),
        patch("mempalace_code.storage.open_store", return_value=recovery_store),
    ):
        mining_store = watcher._WatcherMiningStore(str(palace))
        stats = watcher._run_initial_mine_with_recovery({}, str(palace), None, None, mining_store)

    assert stats == {"embedder_warmed": True}
    assert [call["collection"] for call in mine_calls] == [stale_store, fresh_store]
    out = capsys.readouterr().out
    # The watcher never restores a shared palace on its own (fix/uat-watch).
    assert "No rollback is performed" in out
    recovery_store.recover_to_last_working_version.assert_not_called()
