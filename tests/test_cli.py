"""
test_cli.py — Tests for the mempalace CLI entry point.

Tests exercise main() via sys.argv patching, verifying the full
argparse → dispatch → storage path for the diary write subcommand.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mempalace.cli import main
from mempalace.storage import open_store


def run_mine_cli(argv):
    with patch.object(sys, "argv", argv):
        main()


class TestInitEntityDetection:
    def test_init_default_skips_entity_detection(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        source_file = project_dir / "notes.md"
        source_file.write_text("Alice discussed Apollo.", encoding="utf-8")

        with (
            patch("mempalace.entity_detector.scan_for_detection") as mock_scan,
            patch("mempalace.entity_detector.detect_entities") as mock_detect,
            patch("mempalace.entity_detector.confirm_entities") as mock_confirm,
            patch("mempalace.room_detector_local.detect_rooms_local") as mock_rooms,
        ):
            run_mine_cli(["mempalace", "init", str(project_dir), "--skip-model-download"])

        mock_scan.assert_not_called()
        mock_detect.assert_not_called()
        mock_confirm.assert_not_called()
        mock_rooms.assert_called_once_with(
            project_dir=str(project_dir), yes=False, interactive=False
        )
        assert not (project_dir / "entities.json").exists()

    def test_init_detect_entities_runs_scan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        source_file = project_dir / "notes.md"
        source_file.write_text("Alice discussed Apollo.", encoding="utf-8")

        detected = {
            "people": [{"name": "Alice"}],
            "projects": [{"name": "Apollo"}],
            "uncertain": [],
        }
        confirmed = {"people": ["Alice"], "projects": ["Apollo"]}

        with (
            patch(
                "mempalace.entity_detector.scan_for_detection", return_value=[str(source_file)]
            ) as mock_scan,
            patch(
                "mempalace.entity_detector.detect_entities", return_value=detected
            ) as mock_detect,
            patch(
                "mempalace.entity_detector.confirm_entities", return_value=confirmed
            ) as mock_confirm,
            patch("mempalace.room_detector_local.detect_rooms_local"),
        ):
            run_mine_cli(
                [
                    "mempalace",
                    "init",
                    str(project_dir),
                    "--detect-entities",
                    "--skip-model-download",
                ]
            )

        mock_scan.assert_called_once_with(str(project_dir))
        mock_detect.assert_called_once_with([str(source_file)])
        mock_confirm.assert_called_once_with(detected, yes=False)
        saved = json.loads((project_dir / "entities.json").read_text(encoding="utf-8"))
        assert saved == confirmed

    def test_init_yes_without_detect_entities_skips_scan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with (
            patch("mempalace.entity_detector.scan_for_detection") as mock_scan,
            patch("mempalace.entity_detector.confirm_entities") as mock_confirm,
            patch("mempalace.room_detector_local.detect_rooms_local") as mock_rooms,
        ):
            run_mine_cli(["mempalace", "init", str(project_dir), "--yes", "--skip-model-download"])

        mock_scan.assert_not_called()
        mock_confirm.assert_not_called()
        mock_rooms.assert_called_once_with(
            project_dir=str(project_dir), yes=True, interactive=False
        )
        assert not (project_dir / "entities.json").exists()

    def test_init_config_entity_detection_true_runs_scan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        config_dir = tmp_path / ".mempalace"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(
            json.dumps({"entity_detection": True}), encoding="utf-8"
        )
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        source_file = project_dir / "notes.md"
        source_file.write_text("Alice discussed Apollo.", encoding="utf-8")

        detected = {
            "people": [{"name": "Alice"}],
            "projects": [],
            "uncertain": [],
        }
        confirmed = {"people": ["Alice"], "projects": []}

        with (
            patch(
                "mempalace.entity_detector.scan_for_detection", return_value=[str(source_file)]
            ) as mock_scan,
            patch(
                "mempalace.entity_detector.detect_entities", return_value=detected
            ) as mock_detect,
            patch(
                "mempalace.entity_detector.confirm_entities", return_value=confirmed
            ) as mock_confirm,
            patch("mempalace.room_detector_local.detect_rooms_local"),
        ):
            run_mine_cli(["mempalace", "init", str(project_dir), "--skip-model-download"])

        mock_scan.assert_called_once_with(str(project_dir))
        mock_detect.assert_called_once_with([str(source_file)])
        mock_confirm.assert_called_once_with(detected, yes=False)
        saved = json.loads((project_dir / "entities.json").read_text(encoding="utf-8"))
        assert saved == confirmed


class TestInitNonInteractiveOnboarding:
    """AC-1 through AC-7: config-file-first init and onboarding subcommand dispatch."""

    def _run_init(self, argv):
        with patch.object(sys, "argv", argv):
            main()

    # AC-1: default init writes config without any input() prompt
    def test_init_default_writes_config_without_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").write_text("[project]\nname = 'myproject'\n")
        (project_dir / "src").mkdir()

        def _raise_if_called(*args, **kwargs):
            raise AssertionError("input() must not be called in non-interactive mode")

        with patch("builtins.input", side_effect=_raise_if_called):
            self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        config_path = project_dir / "mempalace.yaml"
        assert config_path.exists(), "mempalace.yaml must be written"
        import yaml

        cfg = yaml.safe_load(config_path.read_text())
        assert cfg["wing"] == "myproject", (
            f"wing must derive from dir name, got {cfg.get('wing')!r}"
        )
        assert isinstance(cfg["rooms"], list)
        assert len(cfg["rooms"]) >= 1
        assert all("name" in r for r in cfg["rooms"]), "every room must have a name"

    # AC-2: --interactive calls room review prompt and still writes config
    def test_init_interactive_prompts_for_room_review(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").write_text("[project]\nname = 'myproject'\n")

        with patch("builtins.input", return_value="") as mock_input:
            self._run_init(
                ["mempalace", "init", str(project_dir), "--interactive", "--skip-model-download"]
            )

        mock_input.assert_called()
        assert (project_dir / "mempalace.yaml").exists(), "mempalace.yaml must be written"

    # AC-3: missing directory exits non-zero before writing config
    def test_init_missing_directory_exits_before_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        missing = tmp_path / "does_not_exist"

        with pytest.raises(SystemExit) as exc:
            self._run_init(["mempalace", "init", str(missing), "--skip-model-download"])

        assert exc.value.code != 0
        assert not (missing / "mempalace.yaml").exists()

    # AC-4: flat project (README.md only) gets a general room without prompting
    def test_init_flat_project_generates_general_room_without_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "flat_project"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("# Flat project\n")

        def _raise_if_called(*args, **kwargs):
            raise AssertionError("input() must not be called in non-interactive mode")

        with patch("builtins.input", side_effect=_raise_if_called):
            self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        import yaml

        cfg = yaml.safe_load((project_dir / "mempalace.yaml").read_text())
        assert cfg["wing"] == "flat_project"
        room_names = [r["name"] for r in cfg["rooms"]]
        assert "general" in room_names, f"expected 'general' room, got {room_names}"

    # AC-5: onboarding subcommand dispatches to run_onboarding; init does not
    def test_onboarding_command_dispatches_guided_flow(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        with patch("mempalace.onboarding.run_onboarding") as mock_onboarding:
            with patch.object(sys, "argv", ["mempalace", "onboarding", str(project_dir)]):
                main()

        mock_onboarding.assert_called_once_with(directory=str(project_dir))

    def test_init_does_not_call_run_onboarding(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        with patch("mempalace.onboarding.run_onboarding") as mock_onboarding:
            with patch("mempalace.room_detector_local.detect_rooms_local"):
                self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        mock_onboarding.assert_not_called()

    # AC-6: --yes is backward-compatible; must not trigger room review prompt
    def test_init_yes_compatibility_is_non_interactive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("# project\n")

        def _raise_if_called(*args, **kwargs):
            raise AssertionError("input() must not be called with --yes")

        with patch("builtins.input", side_effect=_raise_if_called):
            self._run_init(
                ["mempalace", "init", str(project_dir), "--yes", "--skip-model-download"]
            )

        import yaml

        cfg = yaml.safe_load((project_dir / "mempalace.yaml").read_text())
        assert cfg["wing"] == "myproject"
        assert isinstance(cfg["rooms"], list)
        assert len(cfg["rooms"]) >= 1

    # AC-7: missing directory with --detect-entities exits before entity scan
    def test_init_missing_directory_with_entity_detection_exits_before_scan(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        missing = tmp_path / "does_not_exist"

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("scan_for_detection must not be called when dir is missing")

        with patch("mempalace.entity_detector.scan_for_detection", side_effect=_fail_if_called):
            with pytest.raises(SystemExit) as exc:
                self._run_init(
                    [
                        "mempalace",
                        "init",
                        str(missing),
                        "--detect-entities",
                        "--skip-model-download",
                    ]
                )

        assert exc.value.code != 0
        assert not (missing / "mempalace.yaml").exists()
        assert not (missing / "entities.json").exists()


class TestMineSpellcheckFlags:
    def test_project_mode_defaults_spellcheck_false(self, tmp_path):
        with patch("mempalace.miner.mine") as mock_mine:
            run_mine_cli(["mempalace", "mine", str(tmp_path)])

        assert mock_mine.call_args.kwargs["spellcheck"] is False

    def test_convos_mode_defaults_spellcheck_true(self, tmp_path):
        with patch("mempalace.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(["mempalace", "mine", str(tmp_path), "--mode", "convos"])

        assert mock_mine_convos.call_args.kwargs["spellcheck"] is True

    def test_spellcheck_flag_overrides_project_default(self, tmp_path):
        with patch("mempalace.miner.mine") as mock_mine:
            run_mine_cli(["mempalace", "mine", str(tmp_path), "--spellcheck"])

        assert mock_mine.call_args.kwargs["spellcheck"] is True

    def test_no_spellcheck_flag_overrides_convos_default(self, tmp_path):
        with patch("mempalace.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(
                ["mempalace", "mine", str(tmp_path), "--mode", "convos", "--no-spellcheck"]
            )

        assert mock_mine_convos.call_args.kwargs["spellcheck"] is False

    def test_config_spellcheck_value_used_without_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".mempalace").mkdir()
        (tmp_path / ".mempalace" / "config.json").write_text(
            '{"spellcheck_enabled": false}', encoding="utf-8"
        )

        with patch("mempalace.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(["mempalace", "mine", str(tmp_path), "--mode", "convos"])

        assert mock_mine_convos.call_args.kwargs["spellcheck"] is False

    def test_cli_flag_overrides_config_spellcheck_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".mempalace").mkdir()
        (tmp_path / ".mempalace" / "config.json").write_text(
            '{"spellcheck_enabled": true}', encoding="utf-8"
        )

        with patch("mempalace.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(
                ["mempalace", "mine", str(tmp_path), "--mode", "convos", "--no-spellcheck"]
            )

        assert mock_mine_convos.call_args.kwargs["spellcheck"] is False


class TestMineGeneralEmotionalFlag:
    def test_mine_convos_general_defaults_extract_categories(self, tmp_path):
        with patch("mempalace.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(
                [
                    "mempalace",
                    "mine",
                    str(tmp_path),
                    "--mode",
                    "convos",
                    "--extract",
                    "general",
                ]
            )

        assert mock_mine_convos.call_args.kwargs["extract_categories"] is None

    def test_mine_convos_general_include_emotional_dispatches_categories(self, tmp_path):
        with patch("mempalace.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(
                [
                    "mempalace",
                    "mine",
                    str(tmp_path),
                    "--mode",
                    "convos",
                    "--extract",
                    "general",
                    "--include-emotional",
                ]
            )

        assert mock_mine_convos.call_args.kwargs["extract_categories"] == [
            "decision",
            "preference",
            "milestone",
            "problem",
            "emotional",
        ]

    def test_mine_convos_general_emotional_flag_requires_general_mode(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as excinfo:
            run_mine_cli(
                [
                    "mempalace",
                    "mine",
                    str(tmp_path),
                    "--mode",
                    "convos",
                    "--include-emotional",
                ]
            )

        captured = capsys.readouterr()
        assert excinfo.value.code == 2
        assert "--include-emotional requires --mode convos --extract general" in captured.err


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


class TestMigrateStorageCommand:
    """CLI-level tests for migrate-storage argparse wiring and dispatch."""

    def _run(self, argv):
        with patch.object(sys, "argv", argv):
            main()

    def test_migrate_storage_cli_happy_path(self, tmp_path, capsys):
        """AC-1: happy path calls migrate_chroma_to_lance with expected defaults and prints counts."""
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        # Use distinct counts so a src/dst swap in the print statement is detectable.
        with patch(
            "mempalace.migrate.migrate_chroma_to_lance", return_value=(10, 7)
        ) as mock_migrate:
            self._run(["mempalace", "migrate-storage", src, dst])

        mock_migrate.assert_called_once_with(
            src_path=src,
            dst_path=dst,
            backup_dir=None,
            force=False,
            embed_model=None,
            verify=False,
            no_backup=False,
        )
        captured = capsys.readouterr()
        assert "Source drawers: 10" in captured.out
        assert "Destination drawers: 7" in captured.out

    def test_migrate_storage_cli_verify_fail(self, tmp_path, capsys):
        """AC-2: VerificationError exits with code 1, stderr includes 'Verification failed:'."""
        from mempalace.migrate import VerificationError

        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        with patch(
            "mempalace.migrate.migrate_chroma_to_lance",
            side_effect=VerificationError("wing count mismatch"),
        ):
            with pytest.raises(SystemExit) as exc:
                self._run(["mempalace", "migrate-storage", src, dst])

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Verification failed: wing count mismatch" in captured.err

    def test_migrate_storage_cli_backup_dir_passthrough(self, tmp_path, capsys):
        """AC-3: --backup-dir <dir> reaches migrate_chroma_to_lance as backup_dir."""
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")
        backup = str(tmp_path / "backups")

        with patch(
            "mempalace.migrate.migrate_chroma_to_lance", return_value=(5, 5)
        ) as mock_migrate:
            self._run(["mempalace", "migrate-storage", src, dst, "--backup-dir", backup])

        assert mock_migrate.call_args.kwargs["backup_dir"] == backup

    def test_migrate_storage_cli_force_passthrough(self, tmp_path, capsys):
        """AC-4: --force reaches migrate_chroma_to_lance with force=True."""
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        with patch(
            "mempalace.migrate.migrate_chroma_to_lance", return_value=(3, 3)
        ) as mock_migrate:
            self._run(["mempalace", "migrate-storage", src, dst, "--force"])

        assert mock_migrate.call_args.kwargs["force"] is True
