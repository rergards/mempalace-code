"""
test_cli.py — Tests for the mempalace CLI entry point.

Tests exercise main() via sys.argv patching, verifying the full
argparse → dispatch → storage path for the diary write subcommand.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mempalace.cli import main
from mempalace.storage import open_store


class TestDiaryWrite:
    def test_diary_write_success(self, tmp_path):
        palace = str(tmp_path / "palace")
        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "--palace",
                palace,
                "diary",
                "write",
                "--agent",
                "test",
                "--entry",
                "hello",
            ],
        ):
            main()  # must not raise

        store = open_store(palace, create=False)
        results = store.get(include=["documents", "metadatas"])
        assert len(results["ids"]) == 1
        assert results["documents"][0] == "hello"
        meta = results["metadatas"][0]
        assert meta["agent"] == "test"
        assert meta["topic"] == "general"
        assert meta["wing"] == "wing_test"
        assert meta["room"] == "diary"
        assert meta["type"] == "diary_entry"

    def test_diary_write_missing_agent(self, tmp_path):
        palace = str(tmp_path / "palace")
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "diary", "write", "--entry", "hello"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2

    def test_diary_write_missing_entry(self, tmp_path):
        palace = str(tmp_path / "palace")
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "diary", "write", "--agent", "test"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2

    def test_diary_write_default_topic(self, tmp_path):
        palace = str(tmp_path / "palace")
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "diary", "write", "--agent", "test", "--entry", "hi"],
        ):
            main()

        store = open_store(palace, create=False)
        results = store.get(include=["metadatas"])
        assert results["metadatas"][0]["topic"] == "general"

    def test_diary_write_custom_wing(self, tmp_path):
        palace = str(tmp_path / "palace")
        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "--palace",
                palace,
                "diary",
                "write",
                "--agent",
                "test",
                "--entry",
                "hi",
                "--wing",
                "custom_wing",
            ],
        ):
            main()

        store = open_store(palace, create=False)
        results = store.get(include=["metadatas"])
        assert results["metadatas"][0]["wing"] == "custom_wing"

    def test_diary_write_palace_flag(self, tmp_path):
        palace_a = str(tmp_path / "palace_a")
        palace_b = str(tmp_path / "palace_b")
        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "--palace",
                palace_a,
                "diary",
                "write",
                "--agent",
                "test",
                "--entry",
                "in_a",
            ],
        ):
            main()

        # Entry must be in palace_a, not palace_b
        store_a = open_store(palace_a, create=False)
        assert len(store_a.get()["ids"]) == 1

        # palace_b should not exist / be empty
        import os

        assert not os.path.exists(palace_b)

    def test_diary_write_help(self, tmp_path, capsys):
        with patch.object(
            sys,
            "argv",
            ["mempalace", "diary", "write", "--help"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "--agent" in captured.out
        assert "--entry" in captured.out
        assert "--topic" in captured.out

    def test_diary_bare_subcommand(self, tmp_path):
        with patch.object(sys, "argv", ["mempalace", "diary"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2

    def test_diary_write_collision_resistance(self, tmp_path):
        """AC-1: two writes with identical content in the same second both succeed with distinct IDs."""
        palace = str(tmp_path / "palace")
        for _ in range(2):
            with patch.object(
                sys,
                "argv",
                [
                    "mempalace",
                    "--palace",
                    palace,
                    "diary",
                    "write",
                    "--agent",
                    "test",
                    "--entry",
                    "same content exactly",
                ],
            ):
                main()  # must not raise

        store = open_store(palace, create=False)
        results = store.get(include=["documents"])
        assert len(results["ids"]) == 2, "both entries must be stored"
        assert results["ids"][0] != results["ids"][1], "IDs must be distinct"

    def test_diary_write_store_error(self, tmp_path, capsys):
        palace = str(tmp_path / "palace")
        from mempalace import storage

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "diary", "write", "--agent", "test", "--entry", "hi"],
        ):
            with patch.object(storage, "open_store", side_effect=RuntimeError("boom")):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert "boom" in captured.err


class TestHealthCommand:
    """AC-5: mempalace health on a healthy palace exits 0 and prints 'ok'."""

    def test_health_command_healthy_palace(self, tmp_path, capsys):
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["health_test_1"],
            documents=["health command test drawer content"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "health"]):
            main()  # must not raise (exit 0)

        captured = capsys.readouterr()
        assert "ok" in captured.out.lower()
        assert "1" in captured.out  # total_rows = 1

    def test_health_command_json_output(self, tmp_path, capsys):
        import json

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["hj1"],
            documents=["health json test drawer content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "health", "--json"]):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["total_rows"] == 1
        assert data["errors"] == []

    def test_health_command_nonexistent_palace_exits_nonzero(self, tmp_path, capsys):
        palace = str(tmp_path / "nonexistent")

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "health"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0


class TestRepairRollbackCommand:
    """AC-6: mempalace repair --rollback --dry-run exits 0 without mutating palace."""

    def test_repair_rollback_dry_run_healthy_palace(self, tmp_path, capsys):
        """On a healthy palace with one version, dry-run rollback exits 0 (no candidate needed)."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["repair_1"],
            documents=["repair rollback dry run test content"],
            metadatas=[{"wing": "test", "room": "general"}],
        )
        count_before = store.count()

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "repair", "--rollback", "--dry-run"],
        ):
            main()  # must not raise

        # Palace must not be mutated
        store2 = open_store(palace, create=False)
        assert store2.count() == count_before

        captured = capsys.readouterr()
        # Output should mention version, candidate, or no-candidate message
        assert captured.out.strip() != ""

    def test_repair_dry_run_without_rollback_exits_2(self, tmp_path, capsys):
        """--dry-run without --rollback must print an error and exit 2."""
        palace = str(tmp_path / "palace")

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "repair", "--dry-run"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2

    def test_repair_rollback_live_no_candidate_exits_1(self, tmp_path, capsys):
        """F-2 regression: --rollback live mode exits 1 when no candidate version found."""
        from mempalace.storage import LanceStore

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["repair_nc1"],
            documents=["repair no candidate test content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )
        assert isinstance(store, LanceStore)

        # Simulate the case where all prior versions are also corrupt (no candidate)
        def _no_candidate(dry_run=True):
            return {
                "recovered": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "message": "no healthy prior version found",
            }

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "repair", "--rollback"],
        ):
            with patch.object(LanceStore, "recover_to_last_working_version", _no_candidate):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 1, "must exit 1 when no candidate found in live mode"

    def test_repair_rollback_live_restore_exception_exits_1(self, tmp_path, capsys):
        """F-3 regression: --rollback exits 1 with clean message when restore() raises."""
        from mempalace.storage import LanceStore

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["repair_ex1"],
            documents=["repair restore exception test content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )
        assert isinstance(store, LanceStore)

        def _broken_recover(*args, **kwargs):
            raise RuntimeError("simulated restore failure")

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "repair", "--rollback"],
        ):
            with patch.object(store.__class__, "recover_to_last_working_version", _broken_recover):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "restore failed" in (captured.err + captured.out).lower()


class TestBackupCommand:
    """CLI tests for the backup subcommands."""

    def test_backup_list_empty(self, tmp_path, capsys):
        """AC-5: backup list with no backups/ dir → 'No backups found.' exit 0."""
        palace = str(tmp_path / "palace")
        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "backup", "list"]):
            main()  # must not raise
        captured = capsys.readouterr()
        assert "No backups found" in captured.out

    def test_backup_list_populated(self, tmp_path, capsys):
        """backup list shows archive name and drawer count."""
        from mempalace.backup import create_backup

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["bl1"],
            documents=["backup list populated test content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        # Create a backup in the default location
        create_backup(palace)

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "backup", "list"]):
            main()
        captured = capsys.readouterr()
        # Should show a table row with drawer count
        assert "1" in captured.out  # 1 drawer

    def test_backup_list_extra_dir(self, tmp_path, capsys):
        """backup list --dir includes archives outside <palace_parent>/backups/."""
        from mempalace.backup import create_backup

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["bl2"],
            documents=["backup list extra dir test content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        extra_dir = str(tmp_path / "elsewhere")
        os.makedirs(extra_dir)
        extra_archive = os.path.join(extra_dir, "mempalace_backup_extra.tar.gz")
        create_backup(palace, out_path=extra_archive)

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "backup", "list", "--dir", extra_dir],
        ):
            main()
        captured = capsys.readouterr()
        assert "backup_extra" in captured.out

    def test_backup_schedule_daily_darwin(self, tmp_path, capsys, monkeypatch):
        """AC-7: darwin daily → stdout contains plist XML with StartCalendarInterval."""
        import sys as _sys

        palace = str(tmp_path / "palace")
        monkeypatch.setattr(_sys, "platform", "darwin")
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "backup", "schedule", "--freq", "daily"],
        ):
            main()
        captured = capsys.readouterr()
        assert "<?xml" in captured.out
        assert "StartCalendarInterval" in captured.out
        assert "scheduled_" in captured.out

    def test_backup_schedule_hourly_darwin(self, tmp_path, capsys, monkeypatch):
        """darwin hourly → StartInterval and 3600."""
        import sys as _sys

        palace = str(tmp_path / "palace")
        monkeypatch.setattr(_sys, "platform", "darwin")
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "backup", "schedule", "--freq", "hourly"],
        ):
            main()
        captured = capsys.readouterr()
        assert "StartInterval" in captured.out
        assert "3600" in captured.out

    def test_backup_schedule_daily_linux(self, tmp_path, capsys, monkeypatch):
        """AC-8: linux daily → cron line with 0 3 pattern."""
        import re
        import sys as _sys

        palace = str(tmp_path / "palace")
        monkeypatch.setattr(_sys, "platform", "linux")
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "backup", "schedule", "--freq", "daily"],
        ):
            main()
        captured = capsys.readouterr()
        assert re.search(r"0\s+3\s+\*\s+\*\s+\*", captured.out)
        assert "--out" in captured.out
        assert "scheduled_" in captured.out

    def test_backup_schedule_install_rejected(self, tmp_path, capsys):
        """AC-15: --install exits non-zero with 'owner action required' message."""
        palace = str(tmp_path / "palace")
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "backup", "schedule", "--freq", "daily", "--install"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert "owner action required" in captured.err

    def test_backup_no_verb_creates(self, tmp_path, capsys):
        """AC-6: mempalace backup --out X with no verb still creates archive."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["nv1"],
            documents=["backup no verb creates test content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        out = str(tmp_path / "noverb.tar.gz")
        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "backup", "--out", out]):
            main()
        assert os.path.isfile(out)

    def test_backup_create_verb_with_out(self, tmp_path, capsys):
        """AC-11: mempalace backup create --out X creates archive at X."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["cv1"],
            documents=["backup create verb test content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        out = str(tmp_path / "create_verb.tar.gz")
        with patch.object(
            sys, "argv", ["mempalace", "--palace", palace, "backup", "create", "--out", out]
        ):
            main()
        assert os.path.isfile(out)


class TestMineCommand:
    """CLI tests for the mine subcommand --full flag wiring."""

    def test_mine_full_flag(self, tmp_path):
        """AC-1: --full wires incremental=False to mine()."""
        palace = str(tmp_path / "palace")
        with patch("mempalace.miner.mine") as mock_mine:
            with patch.object(
                sys,
                "argv",
                ["mempalace", "--palace", palace, "mine", str(tmp_path), "--full"],
            ):
                main()
        assert mock_mine.call_args.kwargs["incremental"] is False

    def test_mine_default_incremental(self, tmp_path):
        """AC-2: omitting --full wires incremental=True to mine()."""
        palace = str(tmp_path / "palace")
        with patch("mempalace.miner.mine") as mock_mine:
            with patch.object(
                sys,
                "argv",
                ["mempalace", "--palace", palace, "mine", str(tmp_path)],
            ):
                main()
        assert mock_mine.call_args.kwargs["incremental"] is True


# =============================================================================
# mine-all command tests
# =============================================================================


def _make_initialized_project(parent: Path, name: str, git_remote: str = "") -> Path:
    """Create a minimal initialized project directory."""
    proj = parent / name
    proj.mkdir()
    (proj / ".git").mkdir()
    (proj / "mempalace.yaml").write_text(f"wing: {name}\n")
    return proj


def _make_uninit_project(parent: Path, name: str) -> Path:
    """Create a project directory without mempalace.yaml."""
    proj = parent / name
    proj.mkdir()
    (proj / ".git").mkdir()
    return proj


class TestMineAllCommand:
    def _run_mine_all(self, palace: str, parent_dir: str, extra_args: list = None):
        argv = ["mempalace", "--palace", palace, "mine-all", parent_dir]
        if extra_args:
            argv.extend(extra_args)
        with patch.object(sys, "argv", argv):
            main()

    def test_mine_all_basic(self, tmp_path):
        """AC-1: 3 initialized subdirs are all mined, each into correct wing."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "alpha")
        _make_initialized_project(dev, "beta")
        _make_initialized_project(dev, "gamma")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace.miner.mine", side_effect=fake_mine):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                self._run_mine_all(palace, str(dev))

        assert len(mine_calls) == 3
        wings_called = {c["wing_override"] for c in mine_calls}
        assert "alpha" in wings_called
        assert "beta" in wings_called
        assert "gamma" in wings_called

    def test_mine_all_dry_run(self, tmp_path, capsys):
        """AC-2: --dry-run prints projects without calling mine() or opening store."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "proj_a")

        with patch("mempalace.miner.mine") as mock_mine:
            with patch("mempalace.storage.open_store") as mock_open_store:
                self._run_mine_all(palace, str(dev), ["--dry-run"])

        mock_mine.assert_not_called()
        mock_open_store.assert_not_called()
        out = capsys.readouterr().out
        assert "proj_a" in out
        assert "Dry run" in out or "dry run" in out.lower()

    def test_mine_all_skip_existing(self, tmp_path):
        """AC-3: wing already in palace -> skipped; others still mined."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "existing")
        _make_initialized_project(dev, "newproj")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace.miner.mine", side_effect=fake_mine):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {"existing": 10}
                self._run_mine_all(palace, str(dev))

        wings_called = [c["wing_override"] for c in mine_calls]
        assert "existing" not in wings_called
        assert "newproj" in wings_called

    def test_mine_all_force_remines(self, tmp_path):
        """AC-4: --force re-mines even when wing already exists."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "existing")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace.miner.mine", side_effect=fake_mine):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {"existing": 10}
                self._run_mine_all(palace, str(dev), ["--force"])

        wings_called = [c["wing_override"] for c in mine_calls]
        assert "existing" in wings_called

    def test_mine_all_no_projects(self, tmp_path, capsys):
        """AC-7: empty dir prints 'no projects found'."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()

        with patch("mempalace.miner.mine"):
            with patch("mempalace.storage.open_store"):
                self._run_mine_all(palace, str(dev))

        out = capsys.readouterr().out
        assert "No projects" in out or "no projects" in out.lower()

    def test_mine_all_error_continues(self, tmp_path):
        """AC-5: one mine() raises, others still mined; summary shows 1 error."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "good")
        _make_initialized_project(dev, "bad")

        call_order = []

        def fake_mine(**kwargs):
            call_order.append(kwargs["wing_override"])
            if kwargs["wing_override"] == "bad":
                raise RuntimeError("oops")

        with patch("mempalace.miner.mine", side_effect=fake_mine):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                with pytest.raises(SystemExit) as exc_info:
                    self._run_mine_all(palace, str(dev))
        assert exc_info.value.code == 1
        assert len(call_order) == 2  # both projects were attempted

    def test_mine_all_skips_uninitialized(self, tmp_path, capsys):
        """AC-9: subdir with .git but no mempalace.yaml is skipped with warning."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_uninit_project(dev, "uninit")

        with patch("mempalace.miner.mine") as mock_mine:
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                self._run_mine_all(palace, str(dev))

        mock_mine.assert_not_called()
        out = capsys.readouterr().out
        assert "not initialized" in out or "uninit" in out

    def test_mine_all_exit_code_zero_on_success(self, tmp_path):
        """AC-10: exit code 0 when all mined/skipped successfully."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "proj")

        with patch("mempalace.miner.mine"):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                # Should not raise SystemExit
                self._run_mine_all(palace, str(dev))

    def test_mine_all_exit_code_one_on_error(self, tmp_path):
        """AC-11: exit code 1 when any project errors."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "boom")

        with patch("mempalace.miner.mine", side_effect=RuntimeError("fail")):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                with pytest.raises(SystemExit) as exc_info:
                    self._run_mine_all(palace, str(dev))
        assert exc_info.value.code == 1

    def test_mine_all_system_exit_caught(self, tmp_path):
        """SystemExit from mine() is caught and reported, not propagated as exit(1) without summary."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "proj")

        with patch("mempalace.miner.mine", side_effect=SystemExit(1)):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                with pytest.raises(SystemExit) as exc_info:
                    self._run_mine_all(palace, str(dev))
        # The final sys.exit(1) from cmd_mine_all's error path is what propagates
        assert exc_info.value.code == 1

    def test_mine_all_dedup_wing_names(self, tmp_path):
        """F-1 fix: two projects that derive the same wing name — second is skipped with warning."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "alpha")
        _make_initialized_project(dev, "alpha-copy")  # will derive different folder name

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        # Force both projects to derive the same wing name
        with patch("mempalace.miner.mine", side_effect=fake_mine):
            with patch("mempalace.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                with patch("mempalace.miner.derive_wing_name", return_value="shared_wing"):
                    self._run_mine_all(palace, str(dev))

        # Only the first project should be mined; second skipped due to name clash
        assert len(mine_calls) == 1
        assert mine_calls[0]["wing_override"] == "shared_wing"
