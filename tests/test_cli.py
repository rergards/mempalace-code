"""
test_cli.py — Tests for the mempalace CLI entry point.

Tests exercise main() via sys.argv patching, verifying the full
argparse → dispatch → storage path for the diary write subcommand.
"""

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from mempalace_code.cli import _hoist_palace_before_subcommand, install_legacy_alias, main
from mempalace_code.cli_commands.alias import resolve_invoked_canonical_cli
from mempalace_code.storage import CHROMA_RUNTIME_RETIRED_MESSAGE, LanceStore, open_store


def run_mine_cli(argv):
    with patch.object(sys, "argv", argv):
        main()


def _snapshot_paths(*roots):
    entries = []
    for index, root in enumerate(map(Path, roots)):
        if not root.exists():
            entries.append((index, ".", "missing", b""))
            continue
        entries.append((index, ".", "dir" if root.is_dir() else "file", b""))
        for entry in sorted(root.rglob("*")):
            relative = entry.relative_to(root).as_posix()
            if entry.is_symlink():
                entries.append((index, relative, "symlink", os.readlink(entry).encode()))
            elif entry.is_dir():
                entries.append((index, relative, "dir", b""))
            else:
                entries.append((index, relative, "file", entry.read_bytes()))
    return tuple(entries)


class TestInitModelChoiceContract:
    @pytest.mark.parametrize("choice", ["no", "offline"])
    def test_declined_or_offline_init_never_fetches_model(self, tmp_path, monkeypatch, choice):
        project = tmp_path / f"project-{choice}"
        project.mkdir()
        (project / "README.md").write_text("# Project\n", encoding="utf-8")
        calls: list[str] = []

        monkeypatch.setattr(
            "mempalace_code.cli_commands.model.fetch_model",
            lambda model_name, force=False: calls.append(model_name),
        )
        run_mine_cli(["mempalace-code", "init", str(project), "--skip-model-download"])
        run_mine_cli(["mempalace-code", "init", str(project), "--skip-model-download"])

        assert calls == []
        assert (project / "mempalace.yaml").is_file()


class TestLegacyAlias:
    def _write_executable(self, path: Path) -> None:
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)

    def test_install_legacy_alias_creates_mempalace_when_unused(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        canonical = bin_dir / "mempalace-code"
        self._write_executable(canonical)
        monkeypatch.setenv("PATH", str(bin_dir))

        alias = install_legacy_alias()

        assert alias == bin_dir / "mempalace"
        assert alias.is_symlink()
        assert alias.resolve() == canonical.resolve()

    def test_install_legacy_alias_refuses_existing_mempalace(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        canonical = bin_dir / "mempalace-code"
        existing = bin_dir / "mempalace"
        self._write_executable(canonical)
        self._write_executable(existing)
        monkeypatch.setenv("PATH", str(bin_dir))

        with pytest.raises(RuntimeError, match="already in use"):
            install_legacy_alias()

        assert existing.is_file()
        assert not existing.is_symlink()

    def test_explicit_target_dir_creates_alias_even_when_correct_alias_exists_elsewhere(
        self, tmp_path, monkeypatch
    ):
        source_bin = tmp_path / "source-bin"
        target_bin = tmp_path / "target-bin"
        user_bin = tmp_path / "user-bin"
        for bin_dir in (source_bin, target_bin, user_bin):
            bin_dir.mkdir()
        canonical = source_bin / "mempalace-code"
        existing_path_alias = user_bin / "mempalace"
        self._write_executable(canonical)
        existing_path_alias.symlink_to(canonical)
        monkeypatch.setenv("PATH", os.pathsep.join([str(user_bin), str(source_bin)]))

        alias = install_legacy_alias(target_dir=target_bin)

        assert alias == target_bin / "mempalace"
        assert alias.is_symlink()
        assert alias.resolve() == canonical.resolve()
        assert existing_path_alias.resolve() == canonical.resolve()

    def test_absolute_invocation_prefers_invoked_executable_when_path_shadows_canonical(
        self, tmp_path, monkeypatch
    ):
        invoked_bin = tmp_path / "invoked-bin"
        ambient_bin = tmp_path / "ambient-bin"
        target_bin = tmp_path / "target-bin"
        for bin_dir in (invoked_bin, ambient_bin, target_bin):
            bin_dir.mkdir()
        invoked = invoked_bin / "mempalace-code"
        ambient = ambient_bin / "mempalace-code"
        self._write_executable(invoked)
        self._write_executable(ambient)
        monkeypatch.setenv("PATH", str(ambient_bin))

        with patch.object(sys, "argv", [str(invoked), "install-alias"]):
            alias = install_legacy_alias(target_dir=target_bin)

        assert alias == target_bin / "mempalace"
        assert alias.is_symlink()
        assert alias.resolve() == invoked.resolve()
        assert alias.resolve() != ambient.resolve()

    @pytest.mark.parametrize(
        "argv0", ["invoked-bin/mempalace-code", "./invoked-bin/mempalace-code"]
    )
    def test_reusable_resolver_preserves_relative_invocation(self, tmp_path, monkeypatch, argv0):
        invoked_bin = tmp_path / "invoked-bin"
        ambient_bin = tmp_path / "ambient-bin"
        invoked_bin.mkdir()
        ambient_bin.mkdir()
        invoked = invoked_bin / "mempalace-code"
        ambient = ambient_bin / "mempalace-code"
        self._write_executable(invoked)
        self._write_executable(ambient)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PATH", str(ambient_bin))

        with patch.object(sys, "argv", [argv0, "backup", "schedule"]):
            selected = resolve_invoked_canonical_cli()

        assert selected == invoked
        assert selected != ambient

    def test_reusable_resolver_preserves_symlinked_launcher_path(self, tmp_path, monkeypatch):
        managed_bin = tmp_path / "managed" / "bin"
        invoked_bin = tmp_path / "invoked bin"
        managed_bin.mkdir(parents=True)
        invoked_bin.mkdir()
        managed = managed_bin / "mempalace-code"
        invoked = invoked_bin / "mempalace-code"
        self._write_executable(managed)
        invoked.symlink_to(managed)

        with patch.object(sys, "argv", [str(invoked), "watch", "schedule"]):
            selected = resolve_invoked_canonical_cli()

        assert selected is not None
        assert selected == invoked
        assert selected.resolve() == managed.resolve()

    def test_reusable_resolver_maps_dedicated_entry_point_to_sibling(self, tmp_path):
        bin_dir = tmp_path / "dedicated bin"
        bin_dir.mkdir()
        canonical = bin_dir / "mempalace-code"
        installer = bin_dir / "mempalace-code-alias"
        self._write_executable(canonical)
        self._write_executable(installer)

        with patch.object(sys, "argv", [str(installer)]):
            selected = resolve_invoked_canonical_cli()

        assert selected == canonical

    def test_reusable_resolver_rejects_missing_dedicated_sibling_before_path_fallback(
        self, tmp_path, monkeypatch
    ):
        invoked_bin = tmp_path / "invoked-bin"
        ambient_bin = tmp_path / "ambient-bin"
        invoked_bin.mkdir()
        ambient_bin.mkdir()
        installer = invoked_bin / "mempalace-code-alias"
        ambient = ambient_bin / "mempalace-code"
        self._write_executable(installer)
        self._write_executable(ambient)
        monkeypatch.setenv("PATH", str(ambient_bin))

        with patch.object(sys, "argv", [str(installer)]):
            with pytest.raises(RuntimeError, match="cannot find executable sibling"):
                resolve_invoked_canonical_cli()

    def test_reusable_resolver_leaves_bare_canonical_command_to_path_fallback(self, monkeypatch):
        monkeypatch.setenv("PATH", "/ambient/bin")

        with patch.object(sys, "argv", ["mempalace-code", "backup", "schedule"]):
            assert resolve_invoked_canonical_cli() is None

    def test_symlinked_invocation_keeps_default_alias_beside_launcher(self, tmp_path, monkeypatch):
        managed_bin = tmp_path / "managed" / "bin"
        launcher_bin = tmp_path / "path-bin"
        managed_bin.mkdir(parents=True)
        launcher_bin.mkdir()
        managed = managed_bin / "mempalace-code"
        launcher = launcher_bin / "mempalace-code"
        self._write_executable(managed)
        launcher.symlink_to(managed)
        monkeypatch.setenv("PATH", str(launcher_bin))

        with patch.object(sys, "argv", [str(launcher), "install-alias"]):
            alias = install_legacy_alias()

        assert alias == launcher_bin / "mempalace"
        assert alias.is_symlink()
        assert alias.readlink() == Path("mempalace-code")
        assert alias.resolve() == managed.resolve()
        assert not (managed_bin / "mempalace").exists()

    def test_relative_invocation_prefers_invoked_executable_when_path_is_shadowed(
        self, tmp_path, monkeypatch
    ):
        invoked_bin = tmp_path / "invoked-bin"
        ambient_bin = tmp_path / "ambient-bin"
        target_bin = tmp_path / "target-bin"
        for bin_dir in (invoked_bin, ambient_bin, target_bin):
            bin_dir.mkdir()
        invoked = invoked_bin / "mempalace-code"
        ambient = ambient_bin / "mempalace-code"
        self._write_executable(invoked)
        self._write_executable(ambient)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PATH", str(ambient_bin))

        with patch.object(sys, "argv", ["invoked-bin/mempalace-code", "install-alias"]):
            alias = install_legacy_alias(target_dir=target_bin)

        assert alias.resolve() == invoked.resolve()
        assert alias.resolve() != ambient.resolve()

    def test_alias_installer_binds_to_sibling_canonical_under_path_shadowing(
        self, tmp_path, monkeypatch
    ):
        launcher_bin = tmp_path / "launcher-bin"
        ambient_bin = tmp_path / "ambient-bin"
        launcher_bin.mkdir()
        ambient_bin.mkdir()
        canonical = launcher_bin / "mempalace-code"
        installer = launcher_bin / "mempalace-code-alias"
        ambient = ambient_bin / "mempalace-code"
        for executable in (canonical, installer, ambient):
            self._write_executable(executable)
        monkeypatch.setenv("PATH", os.pathsep.join((str(ambient_bin), str(launcher_bin))))

        with patch.object(sys, "argv", [str(installer)]):
            alias = install_legacy_alias()

        assert alias == launcher_bin / "mempalace"
        assert alias.is_symlink()
        assert alias.resolve() == canonical.resolve()
        assert alias.resolve() != ambient.resolve()

    def test_alias_installer_without_sibling_fails_closed(self, tmp_path, monkeypatch):
        launcher_bin = tmp_path / "launcher-bin"
        ambient_bin = tmp_path / "ambient-bin"
        launcher_bin.mkdir()
        ambient_bin.mkdir()
        installer = launcher_bin / "mempalace-code-alias"
        ambient = ambient_bin / "mempalace-code"
        self._write_executable(installer)
        self._write_executable(ambient)
        monkeypatch.setenv("PATH", os.pathsep.join((str(ambient_bin), str(launcher_bin))))

        with patch.object(sys, "argv", [str(installer)]):
            with pytest.raises(RuntimeError, match="cannot find executable sibling"):
                install_legacy_alias()

        assert not (launcher_bin / "mempalace").exists()
        assert not (ambient_bin / "mempalace").exists()

    def test_explicit_target_dir_accepts_existing_correct_target_alias(self, tmp_path, monkeypatch):
        source_bin = tmp_path / "source-bin"
        target_bin = tmp_path / "target-bin"
        user_bin = tmp_path / "user-bin"
        for bin_dir in (source_bin, target_bin, user_bin):
            bin_dir.mkdir()
        canonical = source_bin / "mempalace-code"
        target_alias = target_bin / "mempalace"
        existing_path_alias = user_bin / "mempalace"
        self._write_executable(canonical)
        target_alias.symlink_to(canonical)
        existing_path_alias.symlink_to(canonical)
        monkeypatch.setenv("PATH", os.pathsep.join([str(user_bin), str(source_bin)]))

        alias = install_legacy_alias(target_dir=target_bin)

        assert alias == target_alias
        assert alias.is_symlink()
        assert alias.resolve() == canonical.resolve()
        assert not (source_bin / "mempalace").exists()

    @pytest.mark.parametrize("collision_kind", ["regular-file", "dangling-symlink"])
    def test_explicit_target_dir_refuses_conflicting_target_entry(
        self, tmp_path, monkeypatch, collision_kind
    ):
        source_bin = tmp_path / "source-bin"
        target_bin = tmp_path / "target-bin"
        user_bin = tmp_path / "user-bin"
        for bin_dir in (source_bin, target_bin, user_bin):
            bin_dir.mkdir()
        canonical = source_bin / "mempalace-code"
        target_alias = target_bin / "mempalace"
        existing_path_alias = user_bin / "mempalace"
        self._write_executable(canonical)
        existing_path_alias.symlink_to(canonical)
        monkeypatch.setenv("PATH", os.pathsep.join([str(user_bin), str(source_bin)]))

        if collision_kind == "regular-file":
            target_alias.write_text("not the mempalace-code alias\n", encoding="utf-8")
            before = target_alias.read_text(encoding="utf-8")
        else:
            target_alias.symlink_to(target_bin / "missing-command")
            before = os.readlink(target_alias)

        with pytest.raises(RuntimeError, match="already exists; not overwriting"):
            install_legacy_alias(target_dir=target_bin)

        if collision_kind == "regular-file":
            assert target_alias.read_text(encoding="utf-8") == before
            assert not target_alias.is_symlink()
        else:
            assert target_alias.is_symlink()
            assert os.readlink(target_alias) == before
        assert existing_path_alias.resolve() == canonical.resolve()

    def test_default_install_alias_returns_existing_correct_path_alias(self, tmp_path, monkeypatch):
        source_bin = tmp_path / "source-bin"
        user_bin = tmp_path / "user-bin"
        for bin_dir in (source_bin, user_bin):
            bin_dir.mkdir()
        canonical = source_bin / "mempalace-code"
        existing_path_alias = user_bin / "mempalace"
        self._write_executable(canonical)
        existing_path_alias.symlink_to(canonical)
        monkeypatch.setenv("PATH", os.pathsep.join([str(user_bin), str(source_bin)]))

        alias = install_legacy_alias()

        assert alias == existing_path_alias
        assert alias.resolve() == canonical.resolve()
        assert not (source_bin / "mempalace").exists()

    def test_install_alias_subcommand_dispatches(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        canonical = bin_dir / "mempalace-code"
        self._write_executable(canonical)
        monkeypatch.setenv("PATH", str(bin_dir))

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "install-alias", "--target-dir", str(bin_dir)],
        ):
            main()

        assert (bin_dir / "mempalace").resolve() == canonical.resolve()


class TestInitEntityDetection:
    def test_init_default_skips_entity_detection(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        source_file = project_dir / "notes.md"
        source_file.write_text("Alice discussed Apollo.", encoding="utf-8")

        with (
            patch("mempalace_code.entity_detector.scan_for_detection") as mock_scan,
            patch("mempalace_code.entity_detector.detect_entities") as mock_detect,
            patch("mempalace_code.entity_detector.confirm_entities") as mock_confirm,
            patch("mempalace_code.room_detector_local.detect_rooms_local") as mock_rooms,
        ):
            run_mine_cli(["mempalace", "init", str(project_dir), "--skip-model-download"])

        mock_scan.assert_not_called()
        mock_detect.assert_not_called()
        mock_confirm.assert_not_called()
        mock_rooms.assert_called_once_with(
            project_dir=str(project_dir), yes=False, interactive=False
        )
        assert not (project_dir / "entities.json").exists()

    def test_init_detect_entities_overwrites_regular_entities_preserving_mode(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        source_file = project_dir / "notes.md"
        source_file.write_text("Alice discussed Apollo.", encoding="utf-8")
        entities_path = project_dir / "entities.json"
        entities_path.write_text('{"people": ["stale"]}', encoding="utf-8")
        entities_path.chmod(0o640)

        detected = {
            "people": [{"name": "Alice"}],
            "projects": [{"name": "Apollo"}],
            "uncertain": [],
        }
        confirmed = {"people": ["Alice"], "projects": ["Apollo"]}

        with (
            patch(
                "mempalace_code.entity_detector.scan_for_detection", return_value=[str(source_file)]
            ) as mock_scan,
            patch(
                "mempalace_code.entity_detector.detect_entities", return_value=detected
            ) as mock_detect,
            patch(
                "mempalace_code.entity_detector.confirm_entities", return_value=confirmed
            ) as mock_confirm,
            patch("mempalace_code.room_detector_local.detect_rooms_local"),
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
        saved = json.loads(entities_path.read_text(encoding="utf-8"))
        assert saved == confirmed
        assert entities_path.stat().st_mode & 0o777 == 0o640

    def test_init_entities_write_failure_restores_config_and_entities(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "src").mkdir()
        config_path = project_dir / "mempalace.yaml"
        entities_path = project_dir / "entities.json"
        config_path.write_text("wing: old\nrooms: []\n", encoding="utf-8")
        entities_path.write_text('{"people": ["old"]}', encoding="utf-8")
        before = {path: path.read_bytes() for path in (config_path, entities_path)}
        detected = {"people": [{"name": "Alice"}], "projects": [], "uncertain": []}
        confirmed = {"people": ["Alice"], "projects": []}

        from mempalace_code.room_detector_local import write_regular_destination as real_write

        failed = False

        def fail_entities_once(destination, content):
            nonlocal failed
            if destination == entities_path and not failed:
                failed = True
                raise OSError("simulated entities write failure")
            return real_write(destination, content)

        with (
            patch("mempalace_code.entity_detector.scan_for_detection", return_value=["source"]),
            patch("mempalace_code.entity_detector.detect_entities", return_value=detected),
            patch("mempalace_code.entity_detector.confirm_entities", return_value=confirmed),
            patch(
                "mempalace_code.room_detector_local.write_regular_destination",
                side_effect=fail_entities_once,
            ),
            pytest.raises(SystemExit),
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

        assert {path: path.read_bytes() for path in before} == before

    def test_init_global_config_failure_restores_project_and_global_state(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        config_path = project_dir / "mempalace.yaml"
        prior_config = b"wing: prior\nrooms: []\n"
        config_path.write_bytes(prior_config)
        global_dir = tmp_path / ".mempalace"

        def write_partial_then_fail(config):
            config._config_dir.mkdir(parents=True, exist_ok=True)
            config._config_file.write_text("partial", encoding="utf-8")
            raise OSError("simulated global config failure")

        with patch(
            "mempalace_code.cli_commands.ingest.MempalaceConfig.init",
            autospec=True,
            side_effect=write_partial_then_fail,
        ):
            with pytest.raises(SystemExit):
                run_mine_cli(["mempalace", "init", str(project_dir), "--skip-model-download"])

        assert config_path.read_bytes() == prior_config
        assert not global_dir.exists()

    def test_init_yes_without_detect_entities_skips_scan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        with (
            patch("mempalace_code.entity_detector.scan_for_detection") as mock_scan,
            patch("mempalace_code.entity_detector.confirm_entities") as mock_confirm,
            patch("mempalace_code.room_detector_local.detect_rooms_local") as mock_rooms,
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
                "mempalace_code.entity_detector.scan_for_detection", return_value=[str(source_file)]
            ) as mock_scan,
            patch(
                "mempalace_code.entity_detector.detect_entities", return_value=detected
            ) as mock_detect,
            patch(
                "mempalace_code.entity_detector.confirm_entities", return_value=confirmed
            ) as mock_confirm,
            patch("mempalace_code.room_detector_local.detect_rooms_local"),
        ):
            run_mine_cli(["mempalace", "init", str(project_dir), "--skip-model-download"])

        mock_scan.assert_called_once_with(str(project_dir))
        mock_detect.assert_called_once_with([str(source_file)])
        mock_confirm.assert_called_once_with(detected, yes=False)
        saved = json.loads((project_dir / "entities.json").read_text(encoding="utf-8"))
        assert saved == confirmed


class TestInitNonInteractiveOnboarding:
    """Tests for config-file-first init and onboarding subcommand dispatch."""

    def _run_init(self, argv):
        with patch.object(sys, "argv", argv):
            main()

    def test_init_default_writes_config_without_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "pyproject.toml").write_text("[project]\nname = 'myproject'\n")
        (project_dir / "src").mkdir()

        with patch("builtins.input", side_effect=AssertionError):
            self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        config_path = project_dir / "mempalace.yaml"
        assert config_path.exists(), "mempalace.yaml must be written"
        cfg = yaml.safe_load(config_path.read_text())
        assert cfg["wing"] == "myproject", (
            f"wing must derive from dir name, got {cfg.get('wing')!r}"
        )
        assert isinstance(cfg["rooms"], list)
        assert len(cfg["rooms"]) >= 1
        assert all("name" in r for r in cfg["rooms"]), "every room must have a name"

    def test_init_overwrites_existing_regular_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        config_path = project_dir / "mempalace.yaml"
        config_path.write_text("wing: stale\nrooms: []\n", encoding="utf-8")
        config_path.chmod(0o600)
        (project_dir / "src").mkdir()

        self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["wing"] == "myproject"
        assert [room["name"] for room in cfg["rooms"]] == ["src", "general"]
        assert config_path.stat().st_mode & 0o777 == 0o600
        assert list(project_dir.glob(".mempalace.yaml.*")) == []

    def test_init_post_validation_symlink_swap_exits_without_traceback(
        self, tmp_path, monkeypatch, capsys
    ):
        from mempalace_code.room_detector_local import validate_regular_destination

        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        config_path = project_dir / "mempalace.yaml"
        outside = tmp_path / "outside.yaml"
        outside.write_text("wing: outside\nrooms: []\n", encoding="utf-8")
        calls = 0

        def swap_after_prevalidation(destination):
            nonlocal calls
            result = validate_regular_destination(destination)
            if destination == config_path and calls == 0:
                try:
                    config_path.symlink_to(outside)
                except OSError as exc:
                    pytest.skip(f"symlink creation is not available for this user/platform: {exc}")
            calls += 1
            return result

        with patch(
            "mempalace_code.room_detector_local.validate_regular_destination",
            side_effect=swap_after_prevalidation,
        ):
            with pytest.raises(SystemExit) as exc:
                self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert str(config_path) in captured.err
        assert f"mempalace-code init {project_dir}" in captured.err
        assert "Traceback" not in captured.err
        assert config_path.is_symlink()
        assert outside.read_text(encoding="utf-8") == "wing: outside\nrooms: []\n"

    def test_init_atomic_write_failure_preserves_config_and_cleans_temp(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        config_path = project_dir / "mempalace.yaml"
        prior_config = b"wing: prior\nrooms: []\n"
        config_path.write_bytes(prior_config)

        def replace_then_fail(source, destination):
            assert source.parent == project_dir
            assert destination == config_path
            raise OSError("boom")

        with patch("mempalace_code.room_detector_local.os.replace", side_effect=replace_then_fail):
            with pytest.raises(SystemExit) as exc:
                self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        assert exc.value.code != 0
        assert config_path.read_bytes() == prior_config
        assert list(project_dir.glob(".mempalace.yaml.*")) == []
        captured = capsys.readouterr()
        assert str(config_path) in captured.err
        assert f"mempalace-code init {project_dir}" in captured.err
        assert "Traceback" not in captured.err

    def test_init_retry_after_atomic_write_failure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        config_path = project_dir / "mempalace.yaml"
        prior_config = b"wing: prior\nrooms: []\n"
        config_path.write_bytes(prior_config)
        argv = ["mempalace", "init", str(project_dir), "--skip-model-download"]

        def replace_then_fail(source, destination):
            assert source.parent == project_dir
            assert destination == config_path
            raise OSError("boom")

        with patch("mempalace_code.room_detector_local.os.replace", side_effect=replace_then_fail):
            with pytest.raises(SystemExit) as exc:
                self._run_init(argv)
        assert exc.value.code != 0
        assert config_path.read_bytes() == prior_config

        self._run_init(argv)

        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["wing"] == "myproject"
        assert cfg["rooms"] == [
            {"name": "general", "description": "All project files", "keywords": []}
        ]
        assert list(project_dir.glob(".mempalace.yaml.*")) == []

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

    def test_init_missing_directory_exits_before_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        missing = tmp_path / "does_not_exist"

        with pytest.raises(SystemExit) as exc:
            self._run_init(["mempalace", "init", str(missing), "--skip-model-download"])

        assert exc.value.code != 0
        assert not (missing / "mempalace.yaml").exists()

    def test_init_flat_project_generates_general_room_without_prompt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "flat_project"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("# Flat project\n")

        with patch("builtins.input", side_effect=AssertionError):
            self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        cfg = yaml.safe_load((project_dir / "mempalace.yaml").read_text())
        assert cfg["wing"] == "flat_project"
        room_names = [r["name"] for r in cfg["rooms"]]
        assert "general" in room_names, f"expected 'general' room, got {room_names}"

    def test_onboarding_command_dispatches_guided_flow(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        with patch("mempalace_code.onboarding.run_onboarding") as mock_onboarding:
            with patch.object(sys, "argv", ["mempalace", "onboarding", str(project_dir)]):
                main()

        mock_onboarding.assert_called_once_with(directory=str(project_dir))

    def test_init_does_not_call_run_onboarding(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()

        with patch("mempalace_code.onboarding.run_onboarding") as mock_onboarding:
            with patch("mempalace_code.room_detector_local.detect_rooms_local"):
                self._run_init(["mempalace", "init", str(project_dir), "--skip-model-download"])

        mock_onboarding.assert_not_called()

    def test_init_yes_compatibility_is_non_interactive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        (project_dir / "README.md").write_text("# project\n")

        with patch("builtins.input", side_effect=AssertionError):
            self._run_init(
                ["mempalace", "init", str(project_dir), "--yes", "--skip-model-download"]
            )

        cfg = yaml.safe_load((project_dir / "mempalace.yaml").read_text())
        assert cfg["wing"] == "myproject"
        assert isinstance(cfg["rooms"], list)
        assert len(cfg["rooms"]) >= 1

    def test_init_missing_directory_with_entity_detection_exits_before_scan(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        missing = tmp_path / "does_not_exist"

        with patch("mempalace_code.entity_detector.scan_for_detection", side_effect=AssertionError):
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
        with patch("mempalace_code.mining.orchestrator.mine") as mock_mine:
            run_mine_cli(["mempalace", "mine", str(tmp_path)])

        assert mock_mine.call_args.kwargs["spellcheck"] is False

    def test_convos_mode_defaults_spellcheck_true(self, tmp_path):
        with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(["mempalace", "mine", str(tmp_path), "--mode", "convos"])

        assert mock_mine_convos.call_args.kwargs["spellcheck"] is True
        assert mock_mine_convos.call_args.kwargs["incremental"] is True

    def test_convos_full_disables_incremental_mining(self, tmp_path):
        with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(["mempalace", "mine", str(tmp_path), "--mode", "convos", "--full"])

        assert mock_mine_convos.call_args.kwargs["incremental"] is False

    def test_spellcheck_flag_overrides_project_default(self, tmp_path):
        with patch("mempalace_code.mining.orchestrator.mine") as mock_mine:
            run_mine_cli(["mempalace", "mine", str(tmp_path), "--spellcheck"])

        assert mock_mine.call_args.kwargs["spellcheck"] is True

    def test_no_spellcheck_flag_overrides_convos_default(self, tmp_path):
        with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
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

        with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(["mempalace", "mine", str(tmp_path), "--mode", "convos"])

        assert mock_mine_convos.call_args.kwargs["spellcheck"] is False

    def test_cli_flag_overrides_config_spellcheck_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".mempalace").mkdir()
        (tmp_path / ".mempalace" / "config.json").write_text(
            '{"spellcheck_enabled": true}', encoding="utf-8"
        )

        with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
            run_mine_cli(
                ["mempalace", "mine", str(tmp_path), "--mode", "convos", "--no-spellcheck"]
            )

        assert mock_mine_convos.call_args.kwargs["spellcheck"] is False


class TestMineGeneralEmotionalFlag:
    def test_mine_convos_general_defaults_extract_categories(self, tmp_path):
        with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
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
        with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
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
    @pytest.mark.parametrize(
        ("option", "value", "other_option", "other_value"),
        [
            ("--agent", "", "--entry", "valid entry"),
            ("--agent", " \t\n", "--entry", "valid entry"),
            ("--entry", "", "--agent", "valid-agent"),
            ("--entry", " \t\n", "--agent", "valid-agent"),
        ],
    )
    def test_diary_write_rejects_blank_required_fields_before_palace_access(
        self, tmp_path, capsys, option, value, other_option, other_value
    ):
        palace = tmp_path / "absent-palace"
        argv = [
            "mempalace",
            "--palace",
            str(palace),
            "diary",
            "write",
            option,
            value,
            other_option,
            other_value,
            "--topic",
            "",
        ]

        for _attempt in range(2):
            with patch.object(sys, "argv", argv):
                with pytest.raises(SystemExit) as exc:
                    main()

            captured = capsys.readouterr()
            assert exc.value.code == 2
            assert captured.out == ""
            assert captured.err == (
                f"Error: {option} must not be blank.\n"
                "Try: mempalace-code diary write --agent agent-name "
                "--entry 'your diary entry'\n"
            )
            assert not palace.exists()

    def test_diary_write_success(self, tmp_path, capsys):
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
        captured = capsys.readouterr()
        assert captured.err == ""
        assert "Diary entry stored." in captured.out
        assert f"ID: {results['ids'][0]}" in captured.out
        assert "Wing: wing_test" in captured.out
        assert "Room: diary" in captured.out
        assert "Topic: general" in captured.out
        assert "Verify before retry:" in captured.out
        assert "mempalace-code --palace" in captured.out
        assert "search hell --wing wing_test --room diary --results 10" in captured.out
        assert "hello" not in captured.out
        assert len(captured.out) < 1024

    def test_diary_write_single_character_uses_topic_as_recovery_clue(self, tmp_path, capsys):
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
                "x",
                "--topic",
                "recovery-topic",
            ],
        ):
            main()

        output = capsys.readouterr().out
        assert "search recovery-topic --wing wing_test --room diary --results 10" in output

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
        from mempalace_code import storage

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
        assert captured.out == ""
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

    def test_health_degraded_prints_next_action(self, tmp_path, capsys):
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        open_store(palace, create=True)
        degraded_report = {
            "ok": False,
            "total_rows": 1,
            "current_version": 7,
            "errors": [{"kind": "fragment", "probe": "head", "message": "missing fragment"}],
            "warnings": [],
            "storage": {"error": "not available"},
        }

        with patch.object(LanceStore, "health_check", return_value=degraded_report):
            with patch.object(sys, "argv", ["mempalace", "--palace", palace, "health"]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "DEGRADED" in captured.out
        assert "Next:" in captured.out
        assert "repair --rollback --dry-run" in captured.out

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

    def test_repair_full_missing_palace_exits_nonzero_with_next_action(self, tmp_path, capsys):
        """Full repair on a missing palace must fail closed and tell the user what to do."""
        palace = str(tmp_path / "missing-palace")

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "repair"]):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "No palace found" in captured.err
        assert "Next:" in captured.err
        assert "init <dir>" in captured.err
        assert "mine <dir>" in captured.err
        assert "--palace" in captured.err

    @pytest.mark.parametrize(
        ("dry_run", "expected_exit", "active_stream"),
        [(True, 0, "stdout"), (False, 1, "stderr")],
        ids=["dry-run", "live"],
    )
    def test_repair_rollback_no_candidate_output_contract(
        self, tmp_path, capsys, dry_run, expected_exit, active_stream
    ):
        """No-candidate rollback emits one ordered summary on the outcome stream."""
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["repair_nc1"],
            documents=["repair no candidate test content here"],
            metadatas=[{"wing": "test", "room": "general"}],
        )
        assert isinstance(store, LanceStore)
        recover_calls = []

        def _no_candidate(_store, *, dry_run):
            recover_calls.append(dry_run)
            return {
                "recovered": False,
                "candidate_version": None,
                "dry_run": dry_run,
                "message": "no healthy prior version found",
            }

        argv = ["mempalace", "--palace", palace, "repair", "--rollback"]
        if dry_run:
            argv.append("--dry-run")
        with patch.object(
            sys,
            "argv",
            argv,
        ):
            with patch.object(LanceStore, "recover_to_last_working_version", _no_candidate):
                if expected_exit:
                    with pytest.raises(SystemExit) as exc:
                        main()
                    assert exc.value.code == expected_exit
                else:
                    main()

        assert recover_calls == [dry_run]
        captured = capsys.readouterr()
        output = captured.out if active_stream == "stdout" else captured.err
        inactive_output = captured.err if active_stream == "stdout" else captured.out
        assert inactive_output == ""

        mutation = (
            "Mutation: preview completed; no changes were made; no restore or full rebuild occurred."
            if dry_run
            else "Mutation: rollback attempted; no restore or full rebuild occurred; "
            "palace remained unchanged."
        )
        exit_meaning = (
            "Exit status: 0 (completed non-mutating preview)."
            if dry_run
            else "Exit status: 1 (rollback failed because no candidate was found)."
        )
        ordered_markers = [
            "MemPalace Repair — Version Rollback",
            "Mode: dry-run" if dry_run else "Mode: live",
            "No candidate version: no healthy prior version found",
            mutation,
            exit_meaning,
            "Try: mempalace-code repair (full rebuild)",
        ]
        positions = [output.index(marker) for marker in ordered_markers]
        assert positions == sorted(positions)
        separator = "=" * 55
        assert output.count(separator) == 3
        assert not re.search(rf"{separator}\s*{separator}", output)
        assert output.rstrip().endswith(separator)

    def test_repair_rollback_live_restore_exception_exits_1(self, tmp_path, capsys):
        """F-3 regression: --rollback exits 1 with clean message when restore() raises."""
        from mempalace_code.storage import LanceStore

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


class TestCleanupCommand:
    """CLI tests for the cleanup subcommand (STORAGE-LANCE-STALE-FRAGMENT-CLEANUP)."""

    def test_cleanup_defaults_exit_zero(self, tmp_path, capsys):
        """cleanup with defaults exits 0 on a healthy Lance palace."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        for i in range(3):
            store.add(
                ids=[f"cl{i}"],
                documents=[f"cleanup cli test drawer {i} content"],
                metadatas=[{"wing": "w", "room": "r"}],
            )

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "cleanup"]):
            main()  # must not raise

        captured = capsys.readouterr()
        assert "ok" in captured.out.lower()

    def test_cleanup_json_output_ok_true(self, tmp_path, capsys):
        """cleanup --json emits JSON with ok=true and row counts (AC-1)."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["cj1"],
            documents=["cleanup json output test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "cleanup", "--json"]):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["rows_before"] == data["rows_after"]

    def test_cleanup_unsafe_now_warns_and_exits_zero(self, tmp_path, capsys):
        """cleanup --unsafe-now shows no-writer warning and exits 0 (AC-3)."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["cu1"],
            documents=["cleanup unsafe now test content here"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch.object(
            sys, "argv", ["mempalace", "--palace", palace, "cleanup", "--unsafe-now"]
        ):
            main()

        captured = capsys.readouterr()
        assert "no other writer" in captured.out.lower() or "writer" in captured.out.lower()

    def test_cleanup_failed_result_prints_next_action(self, tmp_path, capsys):
        """Failed cleanup result should tell the operator how to proceed safely."""
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        open_store(palace, create=True)
        failed_result = {
            "ok": False,
            "rows_before": 1,
            "rows_after": 1,
            "version_count_before": 2,
            "version_count_after": 2,
            "freed_bytes": 0,
            "error": "simulated cleanup failure",
        }

        with patch.object(LanceStore, "cleanup_stale_fragments", return_value=failed_result):
            with patch.object(sys, "argv", ["mempalace", "--palace", palace, "cleanup"]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "FAILED" in captured.out
        assert "simulated cleanup failure" in captured.err
        assert "Next:" in captured.err
        assert "stopping watchers" in captured.err

    def test_cleanup_unsafe_now_json_delete_unverified_true(self, tmp_path, capsys):
        """cleanup --unsafe-now --json has delete_unverified=true in output (AC-3)."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["cuj1"],
            documents=["cleanup unsafe json test content here"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "cleanup", "--unsafe-now", "--json"],
        ):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["delete_unverified"] is True
        assert data["cleanup_older_than_days"] == 0

    def test_cleanup_nonexistent_palace_exits_nonzero(self, tmp_path, capsys):
        """cleanup exits non-zero with message when palace does not exist."""
        palace = str(tmp_path / "nonexistent")

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "cleanup"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0

    def test_cleanup_dependency_error_exits_cleanly(self, tmp_path, capsys):
        """AC-4: LanceStoreDependencyError exits non-zero with a clean hint, no traceback."""
        from mempalace_code.storage import LanceStore, LanceStoreDependencyError

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["dep1"],
            documents=["cleanup dependency error test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        def _raise_dep(*args, **kwargs):
            raise LanceStoreDependencyError(
                "Lance cleanup requires an updated lancedb installation. "
                "Run: pip install 'mempalace-code' --upgrade"
            )

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "cleanup", "--json"]):
            with patch.object(LanceStore, "cleanup_stale_fragments", _raise_dep):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code != 0
        captured = capsys.readouterr()
        # Must print a clean error hint, not a raw traceback
        assert "Traceback" not in captured.err
        assert "upgrade" in captured.err.lower() or "install" in captured.err.lower()

    def test_cleanup_older_than_days_flag(self, tmp_path, capsys):
        """--older-than-days is passed through to cleanup_stale_fragments."""
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["otd1"],
            documents=["cleanup older than days flag test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        calls = []

        _real_cleanup = LanceStore.cleanup_stale_fragments

        def _capture(self, older_than_days=7, unsafe_now=False):
            calls.append({"older_than_days": older_than_days, "unsafe_now": unsafe_now})
            return _real_cleanup(self, older_than_days=older_than_days, unsafe_now=unsafe_now)

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "cleanup", "--older-than-days", "14"],
        ):
            with patch.object(LanceStore, "cleanup_stale_fragments", _capture):
                main()

        assert len(calls) == 1
        assert calls[0]["older_than_days"] == 14


class TestHealthCommandWithStorage:
    """AC-5: health command exposes storage metrics in both human and JSON output."""

    def test_health_human_output_includes_storage_metrics(self, tmp_path, capsys):
        """health human output includes Storage: and Versions: lines."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["hhs1"],
            documents=["health human storage metrics test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "health"]):
            main()

        captured = capsys.readouterr()
        assert "Storage:" in captured.out
        assert "Versions:" in captured.out

    def test_health_json_output_includes_storage_keys(self, tmp_path, capsys):
        """health --json output includes storage dict with expected keys."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["hjs1"],
            documents=["health json storage keys test content"],
            metadatas=[{"wing": "w", "room": "r"}],
        )

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "health", "--json"]):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "storage" in data
        for key in (
            "version_count",
            "logical_bytes",
            "on_disk_bytes",
            "estimated_reclaimable_bytes",
        ):
            assert key in data["storage"], f"storage missing key: {key}"


class TestBackupCommand:
    """CLI tests for the backup subcommands."""

    def test_backup_list_empty(self, tmp_path, capsys):
        """AC-5: backup list with no backups/ dir → 'No backups found.' exit 0."""
        palace = str(tmp_path / "palace")
        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "backup", "list"]):
            main()  # must not raise
        captured = capsys.readouterr()
        assert "No backups found" in captured.out
        assert "Next:" in captured.out
        assert "backup create" in captured.out

    def test_backup_list_populated(self, tmp_path, capsys):
        """backup list shows archive name and drawer count."""
        from mempalace_code.backup import create_backup

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
        from mempalace_code.backup import create_backup

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
        assert "--kind scheduled" in captured.out
        assert "To install" not in captured.out
        assert "To install" in captured.err

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
        assert "--kind scheduled" in captured.out
        assert "--palace" in captured.out
        assert "To install" not in captured.out
        assert "To install" in captured.err

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
        with patch("mempalace_code.mining.orchestrator.mine") as mock_mine:
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
        with patch("mempalace_code.mining.orchestrator.mine") as mock_mine:
            with patch.object(
                sys,
                "argv",
                ["mempalace", "--palace", palace, "mine", str(tmp_path)],
            ):
                main()
        assert mock_mine.call_args.kwargs["incremental"] is True


class TestMirrorPreflightCommand:
    """Tests for 'mempalace-code preflight mirror --command ...'."""

    # A delete-mode state mirror with all required excludes — must be accepted.
    SAFE_CMD = (
        "rsync -a --delete "
        "--exclude=palace/ "
        "--exclude=knowledge_graph.sqlite3 "
        "--exclude=config.json "
        "--exclude=backups/ "
        "~/.mempalace/ user@host:.mempalace/"
    )

    # A bare delete-mode state mirror with no excludes — must be blocked.
    DANGEROUS_CMD = "rsync -a --delete ~/.mempalace/ user@host:.mempalace/"

    def test_safe_mirror_with_required_excludes_exits_zero(self, capsys):
        """AC-1: delete-mode state mirror with required excludes is accepted (exit 0)."""
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", self.SAFE_CMD]
        ):
            main()  # must not raise
        out = capsys.readouterr().out
        assert "OK" in out

    def test_delete_mode_state_mirror_missing_excludes_exits_nonzero(self, capsys):
        """AC-2: bare rsync --delete state mirror is blocked; reports all missing families."""
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", self.DANGEROUS_CMD]
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        out = capsys.readouterr().out
        assert "palace" in out
        assert "kg" in out
        assert "config" in out
        assert "backups" in out

    def test_non_state_or_no_delete_commands_remain_ok(self, capsys):
        """AC-3: non-MemPalace delete rsyncs and MemPalace rsyncs without --delete are not flagged."""
        # Non-MemPalace rsync --delete
        no_state_cmd = "rsync -a --delete /home/user/docs/ user@host:/backup/docs/"
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", no_state_cmd]
        ):
            main()
        assert "OK" in capsys.readouterr().out

        # MemPalace rsync without --delete semantics
        no_delete_cmd = "rsync -a ~/.mempalace/ user@host:.mempalace/"
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", no_delete_cmd]
        ):
            main()
        assert "OK" in capsys.readouterr().out

    def test_mirror_preflight_json_reports_missing_excludes(self, capsys):
        """AC-4: --json output is valid JSON with ok=false, pattern_id, and missing families."""
        with patch.object(
            sys,
            "argv",
            ["mempalace", "preflight", "mirror", "--json", "--command", self.DANGEROUS_CMD],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert data["pattern_id"] == "delete-mode-state-mirror-missing-excludes"
        assert "palace" in data["missing_excludes"]
        assert "kg" in data["missing_excludes"]
        assert "config" in data["missing_excludes"]
        assert "backups" in data["missing_excludes"]

    def test_preflight_never_executes_inspected_command(self, capsys):
        """AC-6 / INV-1: inspecting a dangerous command never spawns a subprocess or shells out."""
        with (
            patch("subprocess.run") as mock_run,
            patch("subprocess.Popen") as mock_popen,
            patch("os.system") as mock_system,
            patch("os.popen") as mock_os_popen,
        ):
            with patch.object(
                sys, "argv", ["mempalace", "preflight", "mirror", "--command", self.DANGEROUS_CMD]
            ):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code != 0  # classified as dangerous
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_os_popen.assert_not_called()

    def test_delete_excluded_always_blocked_even_with_all_excludes(self, capsys):
        """F-1 regression: --delete-excluded removes destination-side excluded files, so
        no exclude list can protect palace data — always blocked for state-dir mirrors."""
        delete_excluded_full = (
            "rsync -a --delete-excluded "
            "--exclude=palace/ "
            "--exclude=knowledge_graph.sqlite3 "
            "--exclude=config.json "
            "--exclude=backups/ "
            "~/.mempalace/ user@host:.mempalace/"
        )
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", delete_excluded_full]
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        out = capsys.readouterr().out
        assert "delete-excluded-state-mirror" in out

    def test_delete_excluded_json_output(self, capsys):
        """F-1 regression (JSON path): --delete-excluded state mirror emits correct pattern_id."""
        delete_excluded_cmd = "rsync -a --delete-excluded ~/.mempalace/ user@host:.mempalace/"
        with patch.object(
            sys,
            "argv",
            ["mempalace", "preflight", "mirror", "--json", "--command", delete_excluded_cmd],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert data["pattern_id"] == "delete-excluded-state-mirror"

    def test_delete_excluded_non_state_dir_remains_ok(self, capsys):
        """--delete-excluded targeting a non-MemPalace directory must not be flagged."""
        non_state_cmd = "rsync -a --delete-excluded /home/user/docs/ user@host:/backup/docs/"
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", non_state_cmd]
        ):
            main()
        assert "OK" in capsys.readouterr().out

    # === Wrapper-prefix tests (MIRROR-PREFLIGHT-WRAPPER-DETECTION) ===

    def test_wrapped_safe_mirror_with_required_excludes_exits_zero(self, capsys):
        """AC-1: wrapper-prefixed rsync --delete state mirror with all required excludes is accepted."""
        wrapped_safe = (
            "sudo rsync -a --delete "
            "--exclude=palace/ "
            "--exclude=knowledge_graph.sqlite3 "
            "--exclude=config.json "
            "--exclude=backups/ "
            "~/.mempalace/ user@host:.mempalace/"
        )
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", wrapped_safe]
        ):
            main()
        assert "OK" in capsys.readouterr().out

    def test_sudo_wrapped_delete_mode_state_mirror_missing_excludes_exits_nonzero(self, capsys):
        """AC-2: sudo rsync --delete state mirror without excludes is blocked; reports all missing families."""
        sudo_dangerous = "sudo rsync -a --delete ~/.mempalace/ user@host:.mempalace/"
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", sudo_dangerous]
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        out = capsys.readouterr().out
        assert "palace" in out
        assert "kg" in out
        assert "config" in out
        assert "backups" in out

    def test_env_wrapped_delete_excluded_state_mirror_exits_nonzero(self, capsys):
        """AC-3: env VAR=value rsync --delete-excluded state mirror is blocked with delete-excluded pattern."""
        env_dangerous = (
            "env VAR=value rsync -a --delete-excluded ~/.mempalace/ user@host:.mempalace/"
        )
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", env_dangerous]
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        out = capsys.readouterr().out
        assert "delete-excluded-state-mirror" in out

    def test_simple_shell_wrapped_delete_mode_state_mirror_is_classified(self, capsys):
        """AC-4: sh -c and bash -c wrappers around a destructive rsync are classified by the guard."""
        for shell in ("sh", "bash"):
            cmd = f"{shell} -c 'rsync -a --delete ~/.mempalace/ user@host:.mempalace/'"
            with patch.object(sys, "argv", ["mempalace", "preflight", "mirror", "--command", cmd]):
                with pytest.raises(SystemExit) as exc:
                    main()
            assert exc.value.code == 1, (
                f"Expected exit 1 (blocked, not parse error) for {shell} -c wrapper"
            )
            out = capsys.readouterr().out
            assert "delete-mode-state-mirror" in out, (
                f"Expected blocking pattern_id in output for {shell} -c wrapper, got: {out!r}"
            )

    def test_wrapped_non_state_or_no_delete_commands_remain_ok(self, capsys):
        """AC-5: wrapper-prefixed commands that lack delete semantics or a state-dir target remain OK.

        Also verifies that non-wrapper commands merely mentioning rsync and wrappers resolving
        to non-rsync commands are not flagged (no broad-scan false positives per RISK-1).
        """
        safe_cases = [
            # Wrapped rsync: no delete semantics
            "sudo rsync -a ~/.mempalace/ user@host:.mempalace/",
            # Wrapped rsync: no state-dir target
            "sudo rsync -a --delete /home/user/docs/ user@host:/backup/docs/",
            # env-wrapped rsync: no state-dir target
            "env RSYNC_RSH=ssh rsync -a --delete /src/ user@host:/dst/",
            # Wrapper resolving to a non-rsync command — must not be flagged
            "sudo cp -r ~/.mempalace/ /dst/",
            # Non-wrapper command that merely mentions rsync in its arguments — must not be flagged
            "echo rsync --delete ~/.mempalace/",
        ]
        for cmd in safe_cases:
            with patch.object(sys, "argv", ["mempalace", "preflight", "mirror", "--command", cmd]):
                main()
            out = capsys.readouterr().out
            assert "OK" in out, f"Expected OK for: {cmd!r}, got: {out!r}"

    def test_malformed_wrapper_shell_text_reports_parse_error(self, capsys):
        """AC-6: malformed shell payload inside a supported wrapper exits 2 with a parse error.

        Outer shlex.split succeeds (single-quoted token); inner re-tokenization of the
        -c payload fails due to an unmatched double-quote in the payload string.
        """
        # The Python string contains a single-quoted shell argument whose content
        # includes a lone double-quote — outer parse ok, inner payload parse fails.
        malformed = "sh -c 'rsync -a --delete ~/.mempalace/ user@host:.mempalace/ \"'"
        with patch.object(
            sys, "argv", ["mempalace", "preflight", "mirror", "--command", malformed]
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "ERROR" in captured.err or "error" in captured.err.lower(), (
            f"Expected parse error message on stderr, got: {captured.err!r}"
        )

    # === sudo combined-option tests (MIRROR-PREFLIGHT-SUDO-COMBINED-OPTS) ===

    def test_sudo_combined_option_delete_mode_state_mirror_missing_excludes_exits_nonzero(
        self, capsys
    ):
        """AC-1: compact sudo options wrapping a destructive state mirror are blocked.

        Covers compact no-arg bundle (-nE), argument-attached one-arg (-uroot),
        and mixed bundle (-nEuroot) so that token normalization reaches rsync for all forms.
        """
        cases = [
            # compact no-arg bundle
            "sudo -nE rsync -a --delete ~/.mempalace/ user@host:.mempalace/",
            # argument-attached one-arg flag
            "sudo -uroot rsync -a --delete ~/.mempalace/ user@host:.mempalace/",
            # mixed: no-arg chars then one-arg with attached value
            "sudo -nEuroot rsync -a --delete ~/.mempalace/ user@host:.mempalace/",
            # one-arg flag at last bundle position, value as separate next token (consumed_next path)
            "sudo -nu root rsync -a --delete ~/.mempalace/ user@host:.mempalace/",
        ]
        for cmd in cases:
            with patch.object(sys, "argv", ["mempalace", "preflight", "mirror", "--command", cmd]):
                with pytest.raises(SystemExit) as exc:
                    main()
            assert exc.value.code != 0, f"Expected nonzero exit for: {cmd!r}"
            out = capsys.readouterr().out
            assert "palace" in out, f"Expected 'palace' in output for: {cmd!r}, got: {out!r}"
            assert "kg" in out, f"Expected 'kg' in output for: {cmd!r}, got: {out!r}"
            assert "config" in out, f"Expected 'config' in output for: {cmd!r}, got: {out!r}"
            assert "backups" in out, f"Expected 'backups' in output for: {cmd!r}, got: {out!r}"

    def test_sudo_combined_option_safe_mirror_remains_ok(self, capsys):
        """AC-2: sudo with compact options wrapping a non-delete state mirror exits 0 and prints OK."""
        safe_cases = [
            # compact no-arg bundle, no --delete flag
            "sudo -nE rsync -a ~/.mempalace/ user@host:.mempalace/",
            # argument-attached one-arg flag, no --delete flag
            "sudo -uroot rsync -a ~/.mempalace/ user@host:.mempalace/",
            # one-arg flag at last bundle position, value as separate next token (consumed_next path)
            "sudo -nu root rsync -a ~/.mempalace/ user@host:.mempalace/",
        ]
        for cmd in safe_cases:
            with patch.object(sys, "argv", ["mempalace", "preflight", "mirror", "--command", cmd]):
                main()
            out = capsys.readouterr().out
            assert "OK" in out, f"Expected OK for: {cmd!r}, got: {out!r}"


class TestMirrorPreflightSecurityBoundary:
    """AC-1/AC-3: mirror preflight command parsing abuse cases — malformed command
    text is rejected with a stable parse_error and never spawns a subprocess."""

    # Unterminated double-quote — shlex.split fails at the top level (not inside a wrapper).
    UNTERMINATED_QUOTE_CMD = 'rsync -a --delete "~/.mempalace/ user@host:.mempalace/'

    def test_security_boundary_mirror_preflight_malformed_text_exits_with_parse_error(self, capsys):
        """Top-level unterminated-quote command text exits 2 with a stderr parse error."""
        with patch.object(
            sys,
            "argv",
            ["mempalace", "preflight", "mirror", "--command", self.UNTERMINATED_QUOTE_CMD],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "ERROR" in captured.err

    def test_security_boundary_mirror_preflight_malformed_text_json_output(self, capsys):
        """--json mode reports {"ok": false, "parse_error": ...} for malformed text."""
        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "preflight",
                "mirror",
                "--json",
                "--command",
                self.UNTERMINATED_QUOTE_CMD,
            ],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
        data = json.loads(capsys.readouterr().out)
        assert data["ok"] is False
        assert data["parse_error"]

    def test_security_boundary_mirror_preflight_empty_command_is_parse_error(self, capsys):
        """A blank/whitespace-only command string is rejected, not silently accepted."""
        with patch.object(sys, "argv", ["mempalace", "preflight", "mirror", "--command", "   "]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "ERROR" in captured.err

    def test_security_boundary_mirror_preflight_malformed_text_never_executes(self, capsys):
        """Malformed command text must never spawn a subprocess or shell out, even
        though it fails to parse (INV-5)."""
        with (
            patch("subprocess.run") as mock_run,
            patch("subprocess.Popen") as mock_popen,
            patch("os.system") as mock_system,
            patch("os.popen") as mock_os_popen,
        ):
            with patch.object(
                sys,
                "argv",
                ["mempalace", "preflight", "mirror", "--command", self.UNTERMINATED_QUOTE_CMD],
            ):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 2
        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        mock_os_popen.assert_not_called()


class TestMirrorDocs:
    """Assert that mirror-safety guidance is present in both README.md and docs/BACKUP_RESTORE.md.

    The sentinel phrase 'remote-owned' and a safe rsync --delete example with required excludes
    (palace, knowledge_graph.sqlite3, config.json, backups) were verified ABSENT on the
    pre-implementation HEAD, so these tests fail before implementation and pass only once both
    documents carry the guidance.
    """

    SENTINEL = "remote-owned"
    RSYNC_DELETE_EXAMPLE = "--delete"
    # Concrete exclude patterns that must appear in both docs as part of the new guidance.
    REQUIRED_EXCLUDE_PATTERNS = ["palace", "knowledge_graph.sqlite3", "config.json", "backups"]

    def _read_doc(self, name: str) -> str:
        root = Path(__file__).parent.parent
        return (root / name).read_text(encoding="utf-8")

    def test_readme_has_mirror_safety_guidance(self):
        """README.md must contain the backup-vs-mirror sentinel and a safe rsync example."""
        content = self._read_doc("README.md")
        assert self.SENTINEL in content, (
            "README.md must contain 'remote-owned' to distinguish managed backups from mirror risk"
        )
        assert self.RSYNC_DELETE_EXAMPLE in content, (
            "README.md must contain an rsync --delete example"
        )
        for pattern in self.REQUIRED_EXCLUDE_PATTERNS:
            assert pattern in content, (
                f"README.md rsync example must include exclude pattern for '{pattern}'"
            )

    def test_backup_restore_doc_has_mirror_safety_guidance(self):
        """docs/BACKUP_RESTORE.md must contain the backup-vs-mirror sentinel and a safe rsync example."""
        content = self._read_doc("docs/BACKUP_RESTORE.md")
        assert self.SENTINEL in content, (
            "docs/BACKUP_RESTORE.md must contain 'remote-owned' to distinguish managed backups from mirror risk"
        )
        assert self.RSYNC_DELETE_EXAMPLE in content, (
            "docs/BACKUP_RESTORE.md must contain an rsync --delete example"
        )
        for pattern in self.REQUIRED_EXCLUDE_PATTERNS:
            assert pattern in content, (
                f"docs/BACKUP_RESTORE.md rsync example must include exclude pattern for '{pattern}'"
            )


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
    def _run_mine_all(self, palace: str, parent_dir: str, extra_args: list | None = None):
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

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
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

        with patch("mempalace_code.mining.orchestrator.mine") as mock_mine:
            with patch("mempalace_code.storage.open_store") as mock_open_store:
                self._run_mine_all(palace, str(dev), ["--dry-run"])

        mock_mine.assert_not_called()
        mock_open_store.assert_not_called()
        out = capsys.readouterr().out
        assert "proj_a" in out
        assert "Dry run" in out or "dry run" in out.lower()

    def test_mine_all_dry_run_discovers_init_marker_only_project(self, tmp_path, capsys):
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        project = dev / "initialized-only"
        project.mkdir(parents=True)
        (project / "mempalace.yaml").write_text(
            "wing: initialized_only\nrooms: []\n", encoding="utf-8"
        )

        with patch("mempalace_code.mining.orchestrator.mine") as mock_mine:
            with patch("mempalace_code.storage.open_store") as mock_open_store:
                self._run_mine_all(palace, str(dev), ["--dry-run"])

        mock_mine.assert_not_called()
        mock_open_store.assert_not_called()
        output = capsys.readouterr().out
        assert "initialized-only" in output
        assert "initialized_only" in output

    def test_mine_all_skip_existing(self, tmp_path):
        """--new-only: wing already in palace -> skipped; others still mined."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "existing")
        _make_initialized_project(dev, "newproj")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {"existing": 10}
                self._run_mine_all(palace, str(dev), ["--new-only"])

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

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {"existing": 10}
                self._run_mine_all(palace, str(dev), ["--force"])

        wings_called = [c["wing_override"] for c in mine_calls]
        assert "existing" in wings_called

    def test_mine_all_no_projects(self, tmp_path, capsys):
        """AC-7: empty dir prints 'no projects found'."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()

        with patch("mempalace_code.mining.orchestrator.mine"):
            with patch("mempalace_code.storage.open_store"):
                self._run_mine_all(palace, str(dev))

        out = capsys.readouterr().out
        assert "No projects" in out or "no projects" in out.lower()
        assert "Next:" in out
        assert "mempalace-code init <project-dir>" in out

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

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
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

        with patch("mempalace_code.mining.orchestrator.mine") as mock_mine:
            with patch("mempalace_code.storage.open_store") as mock_store:
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

        with patch("mempalace_code.mining.orchestrator.mine"):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                # Should not raise SystemExit
                self._run_mine_all(palace, str(dev))

    def test_mine_all_exit_code_one_on_error(self, tmp_path):
        """AC-11: exit code 1 when any project errors."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "boom")

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=RuntimeError("fail")):
            with patch("mempalace_code.storage.open_store") as mock_store:
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

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=SystemExit(1)):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                with pytest.raises(SystemExit) as exc_info:
                    self._run_mine_all(palace, str(dev))
        # The final sys.exit(1) from cmd_mine_all's error path is what propagates
        assert exc_info.value.code == 1

    def test_mine_all_dedup_wing_names(self, tmp_path):
        """Two projects resolving to the same wing → exit 1 before any mining."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        # Both projects declare the same wing in their mempalace.yaml
        proj_a = dev / "alpha"
        proj_a.mkdir()
        (proj_a / ".git").mkdir()
        (proj_a / "mempalace.yaml").write_text("wing: shared_wing\n")
        proj_b = dev / "alpha-copy"
        proj_b.mkdir()
        (proj_b / ".git").mkdir()
        (proj_b / "mempalace.yaml").write_text("wing: shared_wing\n")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                with pytest.raises(SystemExit) as exc_info:
                    self._run_mine_all(palace, str(dev))

        assert exc_info.value.code == 1
        assert len(mine_calls) == 0

    def test_mine_all_include_ignored_comma_splits_to_mine(self, tmp_path):
        """mine-all splits --include-ignored on commas and trims whitespace before forwarding to mine()."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "proj")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                self._run_mine_all(
                    palace, str(dev), ["--include-ignored", "ignored/a.py, ignored/b.py"]
                )

        assert len(mine_calls) == 1
        assert mine_calls[0]["include_ignored"] == ["ignored/a.py", "ignored/b.py"]

    # ------------------------------------------------------------------
    # AC-1: incremental sync by default
    # ------------------------------------------------------------------

    def test_mine_all_syncs_existing_wings_incrementally_by_default(self, tmp_path):
        """AC-1: wing already in palace is still mined (incremental=True) by default."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "alpha")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                # Pretend wing 'alpha' already exists in palace
                mock_store.return_value.count_by.return_value = {"alpha": 10}
                self._run_mine_all(palace, str(dev))

        assert len(mine_calls) == 1
        assert mine_calls[0]["wing_override"] == "alpha"
        assert mine_calls[0]["incremental"] is True

    # ------------------------------------------------------------------
    # AC-2: --new-only skip behavior
    # ------------------------------------------------------------------

    def test_mine_all_new_only_skips_existing_wings(self, tmp_path, capsys):
        """AC-2: --new-only skips existing wings; new projects are still mined."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        _make_initialized_project(dev, "alpha")
        _make_initialized_project(dev, "beta")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {"alpha": 5}
                self._run_mine_all(palace, str(dev), ["--new-only"])

        wings_called = [c["wing_override"] for c in mine_calls]
        assert "alpha" not in wings_called
        assert "beta" in wings_called

        out = capsys.readouterr().out
        assert "already exists" in out or "--new-only" in out

    # ------------------------------------------------------------------
    # AC-4: duplicate wing batch error
    # ------------------------------------------------------------------

    def test_mine_all_duplicate_wings_fail_before_mining(self, tmp_path, capsys):
        """AC-4: two projects resolving same wing → exit 1 before any mine() call."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        proj_a = dev / "proj-a"
        proj_a.mkdir()
        (proj_a / ".git").mkdir()
        (proj_a / "mempalace.yaml").write_text("wing: collision\n")
        proj_b = dev / "proj-b"
        proj_b.mkdir()
        (proj_b / ".git").mkdir()
        (proj_b / "mempalace.yaml").write_text("wing: collision\n")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                with pytest.raises(SystemExit) as exc_info:
                    self._run_mine_all(palace, str(dev))

        assert exc_info.value.code == 1
        assert len(mine_calls) == 0

        # stderr must name the duplicate wing and both project paths
        err = capsys.readouterr().err
        assert "collision" in err
        assert "proj-a" in err
        assert "proj-b" in err

    # ------------------------------------------------------------------
    # AC-5: same relative filenames stay separate by wing
    # ------------------------------------------------------------------

    def test_mine_all_same_relative_filenames_stay_separate_by_wing(self, tmp_path):
        """AC-5: two repos with src/settings.py produce distinct mine() calls with different wings."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()

        repo_a = dev / "repo_a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        (repo_a / "mempalace.yaml").write_text("wing: alpha\n")
        (repo_a / "src").mkdir()
        (repo_a / "src" / "settings.py").write_text("X = 1")

        repo_b = dev / "repo_b"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()
        (repo_b / "mempalace.yaml").write_text("wing: beta\n")
        (repo_b / "src").mkdir()
        (repo_b / "src" / "settings.py").write_text("Y = 2")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                self._run_mine_all(palace, str(dev))

        assert len(mine_calls) == 2
        wings = {c["wing_override"] for c in mine_calls}
        assert wings == {"alpha", "beta"}

        dirs = {c["project_dir"] for c in mine_calls}
        assert str(repo_a) in dirs
        assert str(repo_b) in dirs
        # No two calls share the same (project_dir, wing) — no cross-repo collision
        assert mine_calls[0]["wing_override"] != mine_calls[1]["wing_override"]

    # ------------------------------------------------------------------
    # Configured wing override used (resolver reads mempalace.yaml)
    # ------------------------------------------------------------------

    def test_mine_all_configured_wing_override_used(self, tmp_path):
        """Wing declared in mempalace.yaml is used instead of folder name."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        proj = dev / "folder_name"
        proj.mkdir()
        (proj / ".git").mkdir()
        # Wing in config differs from folder name
        (proj / "mempalace.yaml").write_text("wing: custom_wing\n")

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                self._run_mine_all(palace, str(dev))

        assert len(mine_calls) == 1
        assert mine_calls[0]["wing_override"] == "custom_wing"

    # ------------------------------------------------------------------
    # Regression: uninitialized + initialized colliding wings must NOT fail
    # the batch — the uninitialized project would be skipped anyway, so the
    # initialized project should still be mined.
    # ------------------------------------------------------------------

    def test_mine_all_uninit_wing_collision_does_not_block_initialized(self, tmp_path):
        """An uninit project resolving to the same wing as an init project does not abort the batch.

        Regression for round-1 hardening F-1: previously, the duplicate-wing
        check ran before the uninitialized skip, so an uninit folder whose
        derived name collided with an initialized project killed the batch.
        Uninitialized projects are skipped later and cannot mine, so they
        cannot corrupt the palace and must not trigger a fatal duplicate.
        """
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()
        # Initialized project explicitly declaring wing "shared".
        init_proj = dev / "init_proj"
        init_proj.mkdir()
        (init_proj / ".git").mkdir()
        (init_proj / "mempalace.yaml").write_text("wing: shared\n")
        # Uninitialized folder that also resolves to wing "shared" — no
        # mempalace.yaml present, but folder name normalizes to "shared".
        uninit = dev / "shared"
        uninit.mkdir()
        (uninit / ".git").mkdir()
        # No mempalace.yaml → not "initialized" per detect_projects.

        mine_calls = []

        def fake_mine(**kwargs):
            mine_calls.append(kwargs)

        with patch("mempalace_code.mining.orchestrator.mine", side_effect=fake_mine):
            with patch("mempalace_code.storage.open_store") as mock_store:
                mock_store.return_value.count_by.return_value = {}
                self._run_mine_all(palace, str(dev))

        # The initialized project was mined; the uninitialized one was skipped.
        wings_called = [c["wing_override"] for c in mine_calls]
        assert wings_called == ["shared"]
        assert mine_calls[0]["project_dir"] == str(init_proj)

    # ------------------------------------------------------------------
    # AC-5 integration: same relative filename across two repos must produce
    # distinct stored entries (different wing AND different source_file). This
    # exercises real mine() + real LanceDB storage instead of mock-only checks.
    # ------------------------------------------------------------------

    def test_mine_all_same_relative_filenames_distinct_in_storage(self, tmp_path):
        """AC-5 (integration): two repos with src/settings.py both end up in storage
        under different wings with full source_file paths — no drawer-id collision."""
        palace = str(tmp_path / "palace")
        dev = tmp_path / "dev"
        dev.mkdir()

        # Padded content so each file exceeds the miner's minimum size threshold
        padding = "    # " + "x" * 60 + "\n"
        body_a = (
            "def configure_alpha():\n"
            '    """Configure alpha-flavored settings."""\n' + padding * 12 + "    return 'alpha'\n"
        )
        body_b = (
            "def configure_beta():\n"
            '    """Configure beta-flavored settings."""\n' + padding * 12 + "    return 'beta'\n"
        )

        repo_a = dev / "repo_a"
        repo_a.mkdir()
        (repo_a / ".git").mkdir()
        (repo_a / "mempalace.yaml").write_text("wing: alpha\n")
        (repo_a / "src").mkdir()
        (repo_a / "src" / "settings.py").write_text(body_a)

        repo_b = dev / "repo_b"
        repo_b.mkdir()
        (repo_b / ".git").mkdir()
        (repo_b / "mempalace.yaml").write_text("wing: beta\n")
        (repo_b / "src").mkdir()
        (repo_b / "src" / "settings.py").write_text(body_b)

        # Real mine via cmd_mine_all — no mocks on miner/storage.
        self._run_mine_all(palace, str(dev))

        store = open_store(palace, create=False)

        # Stored counts include both wings.
        wing_counts = store.count_by("wing")
        assert wing_counts.get("alpha", 0) >= 1
        assert wing_counts.get("beta", 0) >= 1

        # Pull rows for each wing and confirm:
        #   - source_file is the absolute repo-scoped path (no cross-repo aliasing)
        #   - drawer ids differ between wings even though the relative path matches
        results = store.query(
            query_texts=["configure settings"],
            n_results=20,
            include=["metadatas", "documents"],
        )
        metas = results["metadatas"][0]

        rows_a = [m for m in metas if m.get("wing") == "alpha"]
        rows_b = [m for m in metas if m.get("wing") == "beta"]
        assert rows_a, "expected at least one alpha row in search results"
        assert rows_b, "expected at least one beta row in search results"

        sources_a = {m.get("source_file", "") for m in rows_a}
        sources_b = {m.get("source_file", "") for m in rows_b}
        # Each wing's source_file must point at its own repo and contain the
        # full relative subpath — they must not collide.
        assert any("repo_a" in s and "settings.py" in s for s in sources_a)
        assert any("repo_b" in s and "settings.py" in s for s in sources_b)
        assert sources_a.isdisjoint(sources_b)


class TestChromaRuntimeRetiredCli:
    def test_chroma_only_palace_is_one_actionable_cli_error(self, tmp_path, capsys):
        palace = tmp_path / "palace"
        palace.mkdir()
        marker = palace / "chroma.sqlite3"
        marker.touch()
        source = tmp_path / "drawers.jsonl"
        source.write_text(
            '{"content": "legacy import", "wing": "w", "room": "r"}\n',
            encoding="utf-8",
        )

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", str(palace), "import", str(source)],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == f"Error: {CHROMA_RUNTIME_RETIRED_MESSAGE}\n"
        assert "mempalace-code[chroma-migration]" in captured.err
        assert "mempalace-code migrate-storage SRC DST --verify" in captured.err
        assert "Traceback" not in captured.err
        assert marker.exists()
        assert not (palace / "lance").exists()

    def test_lance_status_remains_successful(self, tmp_path, capsys):
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["lance_status_1"],
            documents=["healthy Lance status"],
            metadatas=[{"wing": "healthy", "room": "status"}],
        )

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", palace, "status", "--summary"],
        ):
            main()

        captured = capsys.readouterr()
        assert "Drawers: 1" in captured.out
        assert captured.err == ""

    def test_unrelated_runtime_error_still_propagates(self, tmp_path, capsys):
        with (
            patch("mempalace_code.cli.cmd_status", side_effect=RuntimeError("unexpected")),
            patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(tmp_path), "status"],
            ),
            pytest.raises(RuntimeError, match="unexpected"),
        ):
            main()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


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
            "mempalace_code.migrate.migrate_chroma_to_lance", return_value=(10, 7)
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

    def test_migrate_storage_help_names_migration_bridge_extra(self, capsys):
        """AC-1: help points users to the migration-only extra."""
        with pytest.raises(SystemExit) as exc:
            self._run(["mempalace", "migrate-storage", "--help"])

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "legacy ChromaDB palace to LanceDB" in captured.out
        assert "mempalace-code[chroma-migration]" in captured.out

    def test_migrate_storage_cli_verify_fail(self, tmp_path, capsys):
        """AC-2: VerificationError exits with code 1, stderr includes 'Verification failed:'."""
        from mempalace_code.migrate import VerificationError

        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        with patch(
            "mempalace_code.migrate.migrate_chroma_to_lance",
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
            "mempalace_code.migrate.migrate_chroma_to_lance", return_value=(5, 5)
        ) as mock_migrate:
            self._run(["mempalace", "migrate-storage", src, dst, "--backup-dir", backup])

        assert mock_migrate.call_args.kwargs["backup_dir"] == backup

    def test_migrate_storage_cli_force_passthrough(self, tmp_path, capsys):
        """AC-4: --force reaches migrate_chroma_to_lance with force=True."""
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        with patch(
            "mempalace_code.migrate.migrate_chroma_to_lance", return_value=(3, 3)
        ) as mock_migrate:
            self._run(["mempalace", "migrate-storage", src, dst, "--force"])

        assert mock_migrate.call_args.kwargs["force"] is True

    def test_migrate_storage_cli_verify_passthrough(self, tmp_path):
        """AC-1: --verify flag reaches migrate_chroma_to_lance as verify=True."""
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        with patch(
            "mempalace_code.migrate.migrate_chroma_to_lance", return_value=(0, 0)
        ) as mock_migrate:
            self._run(["mempalace", "migrate-storage", src, dst, "--verify"])

        assert mock_migrate.call_args.kwargs["verify"] is True

    def test_migrate_storage_cli_embed_model_passthrough(self, tmp_path):
        """AC-2: --embed-model VALUE reaches migrate_chroma_to_lance as embed_model='VALUE'."""
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        with patch(
            "mempalace_code.migrate.migrate_chroma_to_lance", return_value=(0, 0)
        ) as mock_migrate:
            self._run(["mempalace", "migrate-storage", src, dst, "--embed-model", "test-model"])

        assert mock_migrate.call_args.kwargs["embed_model"] == "test-model"

    def test_migrate_storage_cli_runtime_error_exits_1(self, tmp_path, capsys):
        """AC-3: RuntimeError from migrator exits with code 1 and writes 'Error:' to stderr."""
        src = str(tmp_path / "src")
        dst = str(tmp_path / "dst")

        with patch(
            "mempalace_code.migrate.migrate_chroma_to_lance",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(SystemExit) as exc:
                self._run(["mempalace", "migrate-storage", src, dst])

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error: boom" in captured.err


class TestVersionCheckCLIHook:
    """Integration tests: version-check hook preserves existing command stdout."""

    def _run(self, argv):
        with patch.object(sys, "argv", argv):
            main()

    def test_health_json_stdout_unchanged_with_no_opt_in(self, tmp_path, capsys, monkeypatch):
        """health --json stdout must be byte-for-byte valid JSON after the automatic hook is wired.

        When version checks are disabled (no opt-in), the hook must not add anything to stdout.
        """
        monkeypatch.delenv("MEMPALACE_VERSION_CHECK", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["hook_json_1"],
            documents=["version check hook json test drawer content"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        self._run(["mempalace", "--palace", palace, "health", "--json"])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["ok"] is True
        assert data["total_rows"] == 1

    def test_health_json_stdout_unchanged_with_opt_in(self, tmp_path, capsys, monkeypatch):
        """health --json stdout must remain machine-parseable JSON even when opted-in.

        The automatic check runs after dispatch; any hint must go only to stderr.
        """
        monkeypatch.setenv("HOME", str(tmp_path))
        # Opt in via env var so the check runs after the command
        monkeypatch.setenv("MEMPALACE_VERSION_CHECK", "1")
        monkeypatch.setenv("MEMPALACE_VERSION_CHECK_INTERVAL_HOURS", "1")

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["hook_opted_1"],
            documents=["version check hook opted-in json test drawer"],
            metadatas=[{"wing": "test", "room": "general"}],
        )

        with patch(
            "mempalace_code.version_check.fetch_latest_version",
            return_value="99.0.0",
        ):
            self._run(["mempalace", "--palace", palace, "health", "--json"])

        captured = capsys.readouterr()
        # stdout must still be valid JSON — the update hint must not appear there
        data = json.loads(captured.out)
        assert data["ok"] is True
        # update hint should be on stderr
        assert "99.0.0" in captured.err

    def test_version_check_subcommand_status(self, tmp_path, capsys, monkeypatch):
        """version-check --status prints effective state without contacting PyPI."""
        monkeypatch.delenv("MEMPALACE_VERSION_CHECK", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        # bare invocation (default is status)
        self._run(["mempalace", "version-check"])
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "version" in combined.lower()

        # explicit --status flag must work identically
        self._run(["mempalace", "version-check", "--status"])
        captured2 = capsys.readouterr()
        combined2 = captured2.out + captured2.err
        assert "version" in combined2.lower(), "--status flag must print version-check status"

    def test_version_check_enable_then_disable(self, tmp_path, capsys, monkeypatch):
        """version-check --enable and --disable write state without modifying config.json."""
        monkeypatch.delenv("MEMPALACE_VERSION_CHECK", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))

        self._run(["mempalace", "version-check", "--enable"])
        out_enable = capsys.readouterr().out
        assert "enabled" in out_enable.lower()

        self._run(["mempalace", "version-check", "--disable"])
        out_disable = capsys.readouterr().out
        assert "disabled" in out_disable.lower()

        config_json = tmp_path / ".mempalace" / "config.json"
        if config_json.exists():
            import json as _json

            cfg = _json.loads(config_json.read_text())
            assert "version_check_enabled" not in cfg, (
                "config.json must not be written by --enable/--disable"
            )

    @pytest.mark.parametrize("env_value", ["0", "invalid\n" + "x" * 10_000])
    def test_check_now_honors_environment_kill_switch(
        self, env_value, tmp_path, capsys, monkeypatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("MEMPALACE_VERSION_CHECK", env_value)
        fetch_calls = []

        with patch(
            "mempalace_code.cli_commands.version_check.fetch_latest_version",
            side_effect=lambda: fetch_calls.append(True) or "99.0.0",
        ):
            with pytest.raises(SystemExit) as exc:
                self._run(["mempalace", "version-check", "--check-now"])

        captured = capsys.readouterr()
        assert exc.value.code == 2
        assert fetch_calls == []
        assert captured.out == ""
        assert captured.err == (
            "mempalace-code: version check blocked by MEMPALACE_VERSION_CHECK. "
            "Run 'unset MEMPALACE_VERSION_CHECK' (or set it to 1) before retrying.\n"
        )
        assert env_value not in captured.out + captured.err
        assert "Traceback" not in captured.out + captured.err

    def test_no_prompt_on_non_tty_in_cli(self, tmp_path, capsys, monkeypatch):
        """Non-TTY CLI invocations must not call run_first_run_prompt.

        The hook calls should_prompt_first_run which returns False on non-TTY,
        so run_first_run_prompt must never be called.
        """
        monkeypatch.delenv("MEMPALACE_VERSION_CHECK", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        palace = str(tmp_path / "palace")
        # Create a minimal palace so 'status' succeeds
        store = open_store(palace, create=True)
        store.add(
            ids=["nc_1"],
            documents=["no prompt test"],
            metadatas=[{"wing": "t", "room": "general"}],
        )

        prompt_called = []
        with patch(
            "mempalace_code.version_check.run_first_run_prompt",
            side_effect=lambda *a, **kw: prompt_called.append(True),
        ):
            # should_prompt_first_run returns False in non-TTY so prompt fn never fires
            self._run(["mempalace", "--palace", palace, "status"])

        assert prompt_called == [], "run_first_run_prompt must not be called in non-TTY"


class TestAgentPluginCommand:
    def _run(self, argv):
        with patch.object(sys, "argv", argv):
            main()

    def test_agent_plugin_path_prints_installed_root(self, capsys, monkeypatch):
        monkeypatch.delenv("MEMPALACE_VERSION_CHECK", raising=False)
        from mempalace_code.agent_plugins import get_agent_plugin_root

        expected = str(get_agent_plugin_root())

        self._run(["mempalace", "agent-plugin", "path"])

        captured = capsys.readouterr()
        assert captured.out == expected + "\n"
        assert captured.err == ""

    def test_agent_plugin_path_json_output(self, capsys, monkeypatch):
        monkeypatch.delenv("MEMPALACE_VERSION_CHECK", raising=False)
        from mempalace_code.agent_plugins import get_agent_plugin_root

        expected = str(get_agent_plugin_root())

        self._run(["mempalace", "agent-plugin", "path", "--json"])

        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"path": expected}
        assert captured.err == ""

    def test_agent_plugin_path_reports_missing_plugin(self, capsys, monkeypatch):
        monkeypatch.delenv("MEMPALACE_VERSION_CHECK", raising=False)

        with patch(
            "mempalace_code.cli_commands.agent_plugin.get_agent_plugin_root",
            side_effect=RuntimeError("installed Agent Plugin directory is missing"),
        ):
            with pytest.raises(SystemExit) as exc:
                self._run(["mempalace", "agent-plugin", "path"])

        captured = capsys.readouterr()
        assert exc.value.code == 1
        assert captured.out == ""
        assert "Error: installed Agent Plugin directory is missing" in captured.err

    def test_agent_plugin_path_skips_version_check_prompt_and_auto_check(self, capsys, monkeypatch):
        monkeypatch.setenv("MEMPALACE_VERSION_CHECK", "1")
        monkeypatch.setenv("MEMPALACE_VERSION_CHECK_INTERVAL_HOURS", "1")

        with (
            patch(
                "mempalace_code.version_check.run_first_run_prompt",
                side_effect=AssertionError("prompt must not run"),
            ),
            patch(
                "mempalace_code.version_check.run_automatic_check",
                side_effect=AssertionError("automatic check must not run"),
            ),
        ):
            self._run(["mempalace", "agent-plugin", "path"])

        captured = capsys.readouterr()
        assert "agent_plugin" in captured.out or "agent-plugin" in captured.out
        assert captured.err == ""


# =============================================================================
# status --summary tests
# =============================================================================


def test_status_summary_cli_prints_only_bounded_metrics(tmp_path, capsys):
    """status --summary prints only drawer/wing/room-pair/storage/version metrics (AC-1)."""
    palace = str(tmp_path / "palace")
    store = open_store(palace, create=True)
    store.add(
        ids=["cs1", "cs2"],
        documents=["cli summary drawer one", "cli summary drawer two"],
        metadatas=[
            {"wing": "cli_wing", "room": "general"},
            {"wing": "cli_wing", "room": "notes"},
        ],
    )

    with patch.object(sys, "argv", ["mempalace", "--palace", palace, "status", "--summary"]):
        main()
    captured = capsys.readouterr().out

    assert "Drawers: 2" in captured, f"Expected 'Drawers: 2' in output:\n{captured}"
    assert "Wings: 1" in captured, f"Expected 'Wings: 1' in output:\n{captured}"
    assert "Room pairs: 2" in captured, f"Expected 'Room pairs: 2' in output:\n{captured}"
    assert "Storage:" in captured
    assert "Versions:" in captured
    assert "WING:" not in captured
    assert "ROOM:" not in captured
    assert "cli_wing" not in captured


def test_status_summary_missing_palace_does_not_create_or_embed(tmp_path, capsys, monkeypatch):
    """status --summary on a missing palace reports absence without creating the path or embedding (AC-4)."""
    from mempalace_code.storage import LanceStore

    palace = str(tmp_path / "nonexistent_palace")

    def _embedder_raises(self):
        raise RuntimeError("embedder must not be called for missing-palace status --summary")

    monkeypatch.setattr(LanceStore, "_get_embedder", _embedder_raises)

    with patch.object(sys, "argv", ["mempalace", "--palace", palace, "status", "--summary"]):
        main()
    captured = capsys.readouterr().out

    assert "No palace found" in captured, f"Expected 'No palace found' in output:\n{captured}"
    assert not os.path.exists(palace), "status --summary must not create the palace directory"


def test_status_summary_help_and_agent_docs(capsys):
    """CLI help and agent-facing docs recommend status --summary without claiming MCP status is bounded (AC-6)."""
    root = Path(__file__).parent.parent

    with patch.object(sys, "argv", ["mempalace", "status", "--help"]):
        with pytest.raises(SystemExit):
            main()
    help_out = capsys.readouterr().out
    assert "--summary" in help_out, f"status --help must document --summary:\n{help_out}"

    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "status --summary" in readme, "README.md must document status --summary"

    agent_install = (root / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    assert "status --summary" in agent_install, (
        "docs/AGENT_INSTALL.md must recommend status --summary for shell-based readiness checks"
    )

    llm_rules = (root / "docs" / "LLM_USAGE_RULES.md").read_text(encoding="utf-8")
    assert "status --summary" in llm_rules, (
        "docs/LLM_USAGE_RULES.md must mention status --summary for bounded CLI discovery"
    )
    # The existing MCP status caution must remain — this feature does not change MCP status.
    assert "not an operating protocol" in llm_rules, (
        "docs/LLM_USAGE_RULES.md must retain the caution that mempalace_status is unbounded"
    )


# ─── CLI read command tests ───────────────────────────────────────────────────


class TestSearchCommandBlankQuery:
    @pytest.mark.parametrize("query", ["", " \t\n"])
    def test_rejects_blank_query_before_lazy_search_import(self, tmp_path, capsys, query):
        palace = tmp_path / "absent-palace"

        with patch.dict(sys.modules, {"mempalace_code.searcher": None}):
            with patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(palace), "search", query],
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        captured = capsys.readouterr()
        assert exc_info.value.code == 2
        assert captured.out == ""
        assert captured.err == (
            "Error: query must not be blank.\nTry: mempalace-code search 'your search query'\n"
        )
        assert "Traceback" not in captured.err
        assert not palace.exists()

    def test_valid_query_preserves_surrounding_whitespace(self, tmp_path, capsys):
        query = "  configure settings \t"

        with patch("mempalace_code.searcher.search") as mock_search:
            with patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(tmp_path / "palace"), "search", query],
            ):
                main()

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""
        assert mock_search.call_args.kwargs["query"] == query


class TestSearchCommandTaxonomyValidation:
    """search_command: explicit --wing/--room filters are validated against the taxonomy."""

    def _seed(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["sc1"],
            documents=["def authenticate(user): validate credentials"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )
        return palace_path

    def test_search_unknown_taxonomy_exit_2(self, tmp_path, capsys, monkeypatch):
        """AC-2: an unknown --wing exits with status 2 and an actionable message."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "search",
                "anything",
                "--wing",
                "does-not-exist",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Unknown wing" in captured.err
        assert "does-not-exist" in captured.err
        assert "Next:" in captured.err

    def test_search_taxonomy_filter_validation_suggestions_are_advisory(
        self, tmp_path, capsys, monkeypatch
    ):
        """AC-5: a close punctuation variant is suggested but never silently substituted."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed(palace_path)

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", palace_path, "search", "anything", "--wing", "pro-j"],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "Did you mean" in captured.err
        assert "proj" in captured.err
        assert "pro-j" in captured.err  # the supplied value is not rewritten

    def test_search_valid_empty_search_scope_exit_0(self, tmp_path, capsys, monkeypatch):
        """AC-1: a valid wing scope with zero query hits stays a successful, exit-0 result."""
        from mempalace_code.storage import LanceStore

        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed(palace_path)

        def _empty_query(self, *args, **kwargs):
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

        monkeypatch.setattr(LanceStore, "query", _empty_query)

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", palace_path, "search", "anything", "--wing", "proj"],
        ):
            main()  # valid wing scope; must not raise or exit nonzero

        captured = capsys.readouterr()
        assert "No results found" in captured.out
        assert captured.err == ""


class TestWakeupCommandTaxonomyValidation:
    """wake-up validates explicit wings before constructing the memory stack."""

    @staticmethod
    def _seed(palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["wu_project", "wu_archive"],
            documents=["current project wake-up memory", "archived wake-up memory"],
            metadatas=[
                {"wing": "proj", "room": "current", "source_file": "project.md"},
                {"wing": "archive", "room": "history", "source_file": "archive.md"},
            ],
        )

    @staticmethod
    def _isolated_config(tmp_path, monkeypatch):
        home = tmp_path / "home"
        config_path = home / ".mempalace" / "config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_bytes(b'{"palace_path": "/must-not-be-used"}\n')
        monkeypatch.setenv("HOME", str(home))
        return config_path.parent

    @staticmethod
    def _guard_embedder(monkeypatch):
        def fail_embedder(_store):
            raise AssertionError("wake-up taxonomy validation must not initialize the embedder")

        monkeypatch.setattr(LanceStore, "_get_embedder", fail_embedder)

    @pytest.mark.parametrize(
        ("wing", "suggestion_line"),
        [("does-not-exist", None), ("pro-j", "  Did you mean: proj?\n")],
    )
    def test_unknown_wing_exits_2_without_startup_or_state_change(
        self, tmp_path, capsys, monkeypatch, wing, suggestion_line
    ):
        palace = tmp_path / "palace"
        self._seed(str(palace))
        config_root = self._isolated_config(tmp_path, monkeypatch)
        self._guard_embedder(monkeypatch)
        baseline = _snapshot_paths(palace, config_root)

        with (
            patch("mempalace_code.layers.MemoryStack") as memory_stack,
            patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(palace), "wake-up", "--wing", wing],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        captured = capsys.readouterr()
        expected = f"\n  Unknown wing: {wing!r}\n"
        if suggestion_line:
            expected += suggestion_line
        expected += (
            "  Next: run mempalace-code status, or check mempalace_list_wings / "
            "mempalace_list_rooms / mempalace_get_taxonomy for valid taxonomy identifiers "
            "— filters are validated against the palace taxonomy and suggestions are "
            "advisory only.\n"
        )
        assert exc_info.value.code == 2
        assert captured.out == ""
        assert captured.err == expected
        assert wing in captured.err
        assert "Traceback" not in captured.err
        memory_stack.assert_not_called()
        assert _snapshot_paths(palace, config_root) == baseline

    def test_valid_populated_wing_keeps_filtered_wakeup_behavior(
        self, tmp_path, capsys, monkeypatch
    ):
        palace = tmp_path / "palace"
        self._seed(str(palace))
        config_root = self._isolated_config(tmp_path, monkeypatch)
        self._guard_embedder(monkeypatch)
        baseline = _snapshot_paths(palace, config_root)

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", str(palace), "wake-up", "--wing", "proj"],
        ):
            main()

        captured = capsys.readouterr()
        assert "L1 — ESSENTIAL STORY" in captured.out
        assert "current project wake-up memory" in captured.out
        assert "archived wake-up memory" not in captured.out
        assert captured.err == ""
        assert _snapshot_paths(palace, config_root) == baseline

    def test_valid_taxonomy_wing_with_no_l1_match_stays_successful(
        self, tmp_path, capsys, monkeypatch
    ):
        palace = tmp_path / "palace"
        self._seed(str(palace))
        config_root = self._isolated_config(tmp_path, monkeypatch)
        self._guard_embedder(monkeypatch)
        baseline = _snapshot_paths(palace, config_root)

        with (
            patch.object(
                LanceStore,
                "get",
                return_value={"ids": [], "documents": [], "metadatas": []},
            ),
            patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(palace), "wake-up", "--wing", "proj"],
            ),
        ):
            main()

        captured = capsys.readouterr()
        assert "L1 — No memories yet." in captured.out
        assert captured.err == ""
        assert _snapshot_paths(palace, config_root) == baseline

    def test_genuinely_empty_palace_keeps_existing_wakeup_behavior(
        self, tmp_path, capsys, monkeypatch
    ):
        palace = tmp_path / "palace"
        open_store(str(palace), create=True)
        config_root = self._isolated_config(tmp_path, monkeypatch)
        self._guard_embedder(monkeypatch)
        baseline = _snapshot_paths(palace, config_root)

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", str(palace), "wake-up", "--wing", "unmined"],
        ):
            main()

        captured = capsys.readouterr()
        assert "L1 — No memories yet." in captured.out
        assert captured.err == ""
        assert _snapshot_paths(palace, config_root) == baseline


class TestReadCommand:
    """read_command: mempalace-code read prints numbered lines on success and exits non-zero on failure."""

    def _seed_readable(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["rc_chunk0"],
            documents=[
                "def authenticate(user): validate credentials\ndef authorize(user): check role"
            ],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 2,
                }
            ],
        )
        return palace_path

    def test_read_command_success(self, tmp_path, capsys, monkeypatch):
        """read_command: success path prints numbered source lines (AC-3)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_readable(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "/project/src/auth.py",
                "--start",
                "1",
                "--end",
                "2",
            ],
        ):
            main()

        out = capsys.readouterr().out
        assert "1:" in out or "     1:" in out
        assert "authenticate" in out

    def test_read_command_not_found_exits_nonzero(self, tmp_path, capsys, monkeypatch):
        """read_command: exits non-zero when source_file has no palace chunks (AC-4)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        open_store(palace_path, create=True)  # empty palace

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "/nonexistent/file.py",
                "--start",
                "1",
                "--end",
                "5",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Not found" in captured.err
        assert "Next:" in captured.err
        assert "exact Source path" in captured.err
        assert "mempalace-code mine <project-dir>" in captured.err

    def test_read_command_stale_pointer_exits_nonzero(self, tmp_path, capsys, monkeypatch):
        """read_command: exits non-zero when range overlaps no stored chunk (AC-5)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_readable(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "/project/src/auth.py",
                "--start",
                "999",
                "--end",
                "1000",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Stale pointer" in captured.err
        assert "Next:" in captured.err
        assert "refresh line metadata" in captured.err

    def test_read_command_invalid_range_exits_nonzero(self, tmp_path, capsys, monkeypatch):
        """read_command: exits non-zero when start > end (AC-5)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_readable(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "/project/src/auth.py",
                "--start",
                "10",
                "--end",
                "5",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Invalid range" in captured.err
        assert "Next:" in captured.err
        assert "--start" in captured.err

    def test_read_command_read_unknown_wing_exit_2(self, tmp_path, capsys, monkeypatch):
        """AC-1/AC-2: an unknown --wing exits with status 2, distinct from not_found (AC-3)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_readable(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "/project/src/auth.py",
                "--start",
                "1",
                "--end",
                "2",
                "--wing",
                "does-not-exist",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Unknown wing" in captured.err
        assert "does-not-exist" in captured.err
        assert "Next:" in captured.err


# ─── CLI read command: source path discovery tests ────────────────────────────


class TestReadCommandSourcePathDiscovery:
    """read_command: source_file resolution — basename, suffix, alias, ambiguous, missing."""

    def _seed_multi_source(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["spd_src_auth", "spd_web_auth", "spd_login"],
            documents=[
                "def authenticate(user): validate\ndef authorize(user): check role",
                "class AuthController: pass",
                "def login(): pass",
            ],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 2,
                },
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/web/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                },
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/src/login.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 1,
                },
            ],
        )

    def test_read_command_source_path_discovery_unique_basename(
        self, tmp_path, capsys, monkeypatch
    ):
        """read_command: unique basename resolves and prints lines (AC-2)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_multi_source(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "login.py",
                "--start",
                "1",
                "--end",
                "1",
                "--wing",
                "proj",
            ],
        ):
            main()

        out = capsys.readouterr().out
        assert "     1: def login(): pass" in out

    def test_read_command_source_path_discovery_unique_suffix(self, tmp_path, capsys, monkeypatch):
        """read_command: unique project-relative suffix resolves and prints lines (AC-3)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_multi_source(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "src/auth.py",
                "--start",
                "1",
                "--end",
                "2",
                "--wing",
                "proj",
            ],
        ):
            main()

        out = capsys.readouterr().out
        assert "     1: def authenticate(user): validate" in out
        assert "     2: def authorize(user): check role" in out

    def test_read_command_source_path_discovery_ambiguous_exits_nonzero(
        self, tmp_path, capsys, monkeypatch
    ):
        """read_command: ambiguous basename exits non-zero and lists candidates without drawer content (AC-4)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_multi_source(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "auth.py",
                "--start",
                "1",
                "--end",
                "1",
                "--wing",
                "proj",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert captured.out == ""
        err = captured.err
        assert "Ambiguous" in err or "ambiguous" in err
        assert "Next:" in err
        assert "full stored path" in err
        assert "/project/src/auth.py" in err
        assert "/project/web/auth.py" in err
        # Must not print drawer content on ambiguous read
        assert "authenticate" not in err
        assert "AuthController" not in err

    def test_read_command_source_path_discovery_missing_exits_nonzero(
        self, tmp_path, capsys, monkeypatch
    ):
        """read_command: unresolvable source exits non-zero without file_context fallback (AC-6)."""
        monkeypatch.setenv("HOME", str(tmp_path))
        palace_path = str(tmp_path / "palace")
        self._seed_multi_source(palace_path)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                palace_path,
                "read",
                "missing.py",
                "--start",
                "1",
                "--end",
                "1",
                "--wing",
                "proj",
            ],
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Not found" in captured.err or "not found" in captured.err
        assert "Next:" in captured.err


# ─── export --out - stdout cleanliness tests ─────────────────────────────────


class TestJsonlStdoutContract:
    """AC-1..AC-4: export --out - emits only JSONL on stdout; progress goes to stderr."""

    def _seed_manual_drawer(self, palace_path: str):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["manual_export_1"],
            documents=["manual drawer for export test content here"],
            metadatas=[
                {
                    "wing": "test",
                    "room": "general",
                    "chunker_strategy": "manual_v1",
                    "added_by": "mcp",
                    "filed_at": "2026-01-01T00:00:00",
                }
            ],
        )

    def test_export_help_omits_removed_pretty_option(self, capsys):
        with patch.object(sys, "argv", ["mempalace-code", "export", "--help"]):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert " export [-h]" in captured.out
        assert "--out FILE" in captured.out
        assert "--pretty" not in captured.out

    @pytest.mark.parametrize("existing_output", [False, True])
    def test_removed_pretty_option_exits_before_touching_output(
        self, tmp_path, capsys, existing_output
    ):
        out_file = tmp_path / "export.jsonl"
        sentinel = b"existing export sentinel\n"
        if existing_output:
            out_file.write_bytes(sentinel)

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "export", "--out", str(out_file), "--pretty"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 2
        if existing_output:
            assert out_file.read_bytes() == sentinel
        else:
            assert not out_file.exists()
        captured = capsys.readouterr()
        assert "export" in captured.err
        assert "unrecognized arguments: --pretty" in captured.err

    def test_export_stdout_contains_only_jsonl(self, tmp_path, capsys):
        """AC-1: stdout begins with valid JSONL export_header; no human progress lines appear."""
        palace = str(tmp_path / "palace")
        self._seed_manual_drawer(palace)

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "export", "--out", "-", "--only-manual"],
        ):
            main()

        captured = capsys.readouterr()
        lines = [ln for ln in captured.out.splitlines() if ln.strip()]
        assert lines, "stdout must not be empty"
        header = json.loads(lines[0])
        assert header["type"] == "export_header", (
            f"first stdout line must be export_header JSONL, got: {lines[0]!r}"
        )
        for line in lines:
            json.loads(line)  # every line must be valid JSON

    def test_export_stdout_progress_on_stderr(self, tmp_path, capsys):
        """AC-2: progress/summary lines appear on stderr, not stdout, for --out -."""
        palace = str(tmp_path / "palace")
        self._seed_manual_drawer(palace)

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "export", "--out", "-", "--only-manual"],
        ):
            main()

        captured = capsys.readouterr()
        assert "Exporting from" in captured.err
        assert "Exported" in captured.err
        assert "Exporting from" not in captured.out
        assert "Exported" not in captured.out

    def test_export_stdout_pipe_to_import_dry_run(self, tmp_path, capsys, monkeypatch):
        """AC-3: stdout from export --out - is valid JSONL that import - --dry-run accepts."""
        import io

        palace = str(tmp_path / "palace")
        self._seed_manual_drawer(palace)

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "export", "--out", "-", "--only-manual"],
        ):
            main()

        export_stdout = capsys.readouterr().out
        assert export_stdout.strip(), "export must produce non-empty stdout"

        import_palace = str(tmp_path / "import_palace")
        monkeypatch.setattr(sys, "stdin", io.StringIO(export_stdout))
        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", import_palace, "import", "-", "--dry-run"],
        ):
            main()  # must not raise; import reads JSONL cleanly

        import_captured = capsys.readouterr()
        assert "Imported drawers:   1" in import_captured.out, (
            f"import must report 1 drawer from the export stream; got: {import_captured.out!r}"
        )

    def test_export_file_writes_valid_jsonl(self, tmp_path, capsys):
        """AC-4: file-backed export writes valid JSONL; progress is on stderr."""
        palace = str(tmp_path / "palace")
        self._seed_manual_drawer(palace)
        out_file = str(tmp_path / "export.jsonl")

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "export", "--out", out_file, "--only-manual"],
        ):
            main()

        content = Path(out_file).read_text(encoding="utf-8")
        lines = [ln for ln in content.splitlines() if ln.strip()]
        assert lines, "exported file must not be empty"
        header = json.loads(lines[0])
        assert header["type"] == "export_header"

        captured = capsys.readouterr()
        assert "Exporting from" in captured.err
        assert "Exported" in captured.err

    def test_export_zero_results_prints_next_action_on_stderr(self, tmp_path, capsys):
        """A filtered empty export should keep stdout clean and explain the next action on stderr."""
        palace = str(tmp_path / "palace")
        open_store(palace, create=True)

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "export", "--out", "-", "--only-manual"],
        ):
            main()

        captured = capsys.readouterr()
        assert "Next:" not in captured.out
        assert "Next:" in captured.err
        assert "relax export filters" in captured.err

    def test_export_missing_palace_exits_with_next_action(self, tmp_path, capsys):
        """Export on a missing palace should fail without a traceback."""
        palace = str(tmp_path / "missing-palace")

        with patch.object(
            sys,
            "argv",
            ["mempalace", "--palace", palace, "export", "--out", "-"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "no palace found" in captured.err
        assert "Next:" in captured.err
        assert "init <dir>" in captured.err

    def test_export_unopenable_palace_points_to_health_and_repair(self, tmp_path, capsys):
        """Export on an existing broken palace should not suggest only init/mine."""
        palace = tmp_path / "palace"
        palace.mkdir()

        with (
            patch("mempalace_code.storage.open_store", side_effect=RuntimeError("corrupt")),
            patch.object(
                sys,
                "argv",
                ["mempalace", "--palace", str(palace), "export", "--out", "-"],
            ),
        ):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "cannot open palace" in captured.err
        assert "Next:" in captured.err
        assert "correct --palace path" in captured.err
        assert "health" in captured.err
        assert "repair --rollback --dry-run" in captured.err


# ─── Compress token accounting ───────────────────────────────────────────────


class TestCompressTokenAccounting:
    class _Store:
        def __init__(self, documents):
            self.documents = documents
            self.metadatas = [
                {"wing": "wing", "room": "room", "source_file": f"doc-{index}.md"}
                for index, _document in enumerate(self.documents)
            ]
            self.ids = [f"drawer-{index}" for index, _document in enumerate(self.documents)]
            self.upserts = []

        def get(self, ids=None, limit=10000, offset=0, **kwargs):
            selected = range(len(self.ids))
            if ids is not None:
                selected = [self.ids.index(doc_id) for doc_id in ids if doc_id in self.ids]
            else:
                selected = list(selected)[offset : offset + limit]
            return {
                "documents": [self.documents[index] for index in selected],
                "metadatas": [self.metadatas[index] for index in selected],
                "ids": [self.ids[index] for index in selected],
            }

        def upsert(self, **kwargs):
            self.upserts.append(kwargs)
            index = self.ids.index(kwargs["ids"][0])
            self.documents[index] = kwargs["documents"][0]
            self.metadatas[index] = kwargs["metadatas"][0]

    def _run_compress(self, capsys, documents, stats_by_document, *, dry_run):
        from mempalace_code.dialect import Dialect

        store = self._Store(documents)

        def fake_compress(_dialect, document, metadata=None):
            return f"summary:{document}"

        def fake_stats(_dialect, original, summary):
            return stats_by_document[original]

        argv = ["mempalace", "--palace", "/unused-palace", "compress"]
        if dry_run:
            argv.append("--dry-run")
        with (
            patch("mempalace_code.storage.open_store", return_value=store),
            patch(
                "mempalace_code.backup.create_backup",
                return_value=({}, "/tmp/mempalace-compress-test.tar.gz"),
            ),
            patch.object(Dialect, "compress", autospec=True, side_effect=fake_compress),
            patch.object(Dialect, "compression_stats", autospec=True, side_effect=fake_stats),
            patch.object(sys, "argv", argv),
        ):
            main()

        return capsys.readouterr().out, store

    def test_two_drawer_totals_match_rows_in_dry_run_and_live_modes(self, capsys):
        stats = {
            "alpha": {
                "original_chars": 124,
                "summary_chars": 44,
                "original_tokens_est": 31,
                "summary_tokens_est": 11,
                "size_ratio": 2.8,
            },
            "beta": {
                "original_chars": 132,
                "summary_chars": 24,
                "original_tokens_est": 33,
                "summary_tokens_est": 6,
                "size_ratio": 5.5,
            },
        }

        dry_output, dry_store = self._run_compress(capsys, ["alpha", "beta"], stats, dry_run=True)
        live_output, live_store = self._run_compress(
            capsys, ["alpha", "beta"], stats, dry_run=False
        )

        assert "    31t -> 11t (2.8x)" in dry_output
        assert "    33t -> 6t (5.5x)" in dry_output
        assert "Total: 64t -> 17t (3.8x compression)" in dry_output
        assert "Total: 64t -> 17t (3.8x compression)" in live_output
        assert dry_store.upserts == []
        assert len(live_store.upserts) == 2
        assert [call["metadatas"][0]["original_tokens"] for call in live_store.upserts] == [
            31,
            33,
        ]

    def test_no_drawers_keeps_existing_guidance(self, capsys):
        output, store = self._run_compress(capsys, [], {}, dry_run=True)

        assert "No drawers found" in output
        assert "Next: check --wing/--room filters" in output
        assert "Total:" not in output
        assert store.upserts == []

    def test_zero_token_drawer_has_finite_zero_total(self, capsys):
        stats = {
            "": {
                "original_chars": 0,
                "summary_chars": 0,
                "original_tokens_est": 0,
                "summary_tokens_est": 0,
                "size_ratio": 0.0,
            }
        }

        output, store = self._run_compress(capsys, [""], stats, dry_run=True)

        assert "    0t -> 0t (0.0x)" in output
        assert "Total: 0t -> 0t (0.0x compression)" in output
        assert store.upserts == []


class TestCompressRetryIdempotentRecovery:
    class _Store:
        def __init__(self, rows, *, trace=None):
            self.rows = {row[0]: [row[1], dict(row[2])] for row in rows}
            self.order = [row[0] for row in rows]
            self.trace = trace if trace is not None else []
            self.upserts = []
            self.fail_on: str | None = None
            self.mismatch_readback = False

        def get(self, ids=None, where=None, limit=10000, offset=0, **kwargs):
            if ids is None:
                selected = [
                    doc_id
                    for doc_id in self.order
                    if where is None or self.rows[doc_id][1].get("wing") == where.get("wing")
                ][offset : offset + limit]
            else:
                self.trace.append("verify")
                selected = [doc_id for doc_id in ids if doc_id in self.rows]
            documents = [self.rows[doc_id][0] for doc_id in selected]
            metadatas = [dict(self.rows[doc_id][1]) for doc_id in selected]
            if ids is not None and self.mismatch_readback and documents:
                documents[0] = "divergent stored value"
            return {"ids": selected, "documents": documents, "metadatas": metadatas}

        def upsert(self, **kwargs):
            doc_id = kwargs["ids"][0]
            self.trace.append(f"upsert:{doc_id}")
            if doc_id == self.fail_on:
                raise RuntimeError("injected upsert failure")
            self.upserts.append(kwargs)
            self.rows[doc_id] = [kwargs["documents"][0], dict(kwargs["metadatas"][0])]

    @staticmethod
    def _stats(document):
        return {
            "original_chars": len(document),
            "summary_chars": len(f"summary:{document}"),
            "original_tokens_est": max(1, len(document) // 4),
            "summary_tokens_est": max(1, len(f"summary:{document}") // 4),
            "size_ratio": 2.0,
        }

    def _run(self, capsys, store, *, dry_run=False, wing=None, backup_effect=None):
        from mempalace_code.dialect import Dialect

        compressed_inputs = []

        def fake_compress(_dialect, document, metadata=None):
            compressed_inputs.append(document)
            return f"summary:{document}"

        def fake_stats(_dialect, original, summary):
            return self._stats(original)

        def default_backup(*args, **kwargs):
            store.trace.append("backup")
            return {}, "/tmp/recovery archive.tar.gz"

        argv = ["mempalace", "--palace", "/tmp/palace root", "compress"]
        if wing:
            argv.extend(["--wing", wing])
        if dry_run:
            argv.append("--dry-run")
        with (
            patch("mempalace_code.storage.open_store", return_value=store),
            patch("mempalace_code.taxonomy_filters.validate_taxonomy_filters", return_value=None),
            patch(
                "mempalace_code.backup.create_backup",
                side_effect=backup_effect or default_backup,
            ) as backup,
            patch.object(Dialect, "compress", autospec=True, side_effect=fake_compress),
            patch.object(Dialect, "compression_stats", autospec=True, side_effect=fake_stats),
            patch.object(sys, "argv", argv),
        ):
            main()
        return capsys.readouterr(), compressed_inputs, backup

    @staticmethod
    def _row(doc_id, document, *, completed=False, wing="source"):
        metadata: dict[str, object] = {
            "wing": wing,
            "room": "code",
            "source_file": f"{doc_id}.py",
        }
        if completed:
            metadata.update({"compression_ratio": 2.0, "original_tokens": 10})
        return doc_id, document, metadata

    def test_identical_retry_is_byte_stable_and_creates_no_second_backup(self, capsys):
        store = self._Store([self._row("one", "ordinary source text")])

        first, first_inputs, first_backup = self._run(capsys, store, wing="source")
        stored_after_first = store.rows["one"][0]
        second, second_inputs, second_backup = self._run(capsys, store, wing="source")

        assert first_inputs == ["ordinary source text"]
        assert first_backup.call_count == 1
        assert "Stored and verified 1 compressed drawers" in first.out
        assert second_inputs == []
        assert second_backup.call_count == 0
        assert store.rows["one"][0] == stored_after_first
        assert "Pending: 0; skipped already compressed: 1" in second.out

    def test_mixed_dry_run_previews_only_pending_without_writes(self, capsys):
        store = self._Store(
            [
                self._row("done", "summary:stable", completed=True),
                self._row("todo", "ordinary pending text"),
            ]
        )
        before = {doc_id: (row[0], dict(row[1])) for doc_id, row in store.rows.items()}

        captured, compressed_inputs, backup = self._run(capsys, store, dry_run=True, wing="source")

        assert compressed_inputs == ["ordinary pending text"]
        assert backup.call_count == 0
        assert store.upserts == []
        assert store.rows == {doc_id: [row[0], row[1]] for doc_id, row in before.items()}
        assert "Pending: 1; skipped already compressed: 1" in captured.out
        assert "summary:ordinary pending text" in captured.out
        assert "summary:stable" not in captured.out
        assert "dry run -- nothing stored" in captured.out

    def test_backup_precedes_upsert_and_output_exposes_shell_safe_restore(self, capsys):
        trace = []
        store = self._Store([self._row("one", "ordinary source text")], trace=trace)

        captured, _inputs, _backup = self._run(capsys, store, wing="source")

        assert trace == ["backup", "upsert:one", "verify"]
        assert "Recovery archive: /tmp/recovery archive.tar.gz" in captured.out
        assert (
            "Recovery command: mempalace-code --palace '/tmp/palace root' restore "
            "'/tmp/recovery archive.tar.gz' --force"
        ) in captured.out

    def test_backup_failure_exits_before_upsert(self, capsys):
        store = self._Store([self._row("one", "ordinary source text")])

        with pytest.raises(SystemExit) as exc:
            self._run(
                capsys,
                store,
                wing="source",
                backup_effect=RuntimeError("backup unavailable"),
            )

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error creating pre-compression backup" in captured.err
        assert store.upserts == []

    def test_partial_reordered_retry_processes_only_remaining_drawer(self, capsys):
        store = self._Store(
            [self._row("first", "first original"), self._row("second", "second original")]
        )
        store.fail_on = "second"

        with pytest.raises(SystemExit) as exc:
            self._run(capsys, store, wing="source")
        assert exc.value.code == 1
        capsys.readouterr()
        first_completed_bytes = store.rows["first"][0]
        store.fail_on = None
        store.order.reverse()

        captured, compressed_inputs, backup = self._run(capsys, store, wing="source")

        assert compressed_inputs == ["second original"]
        assert backup.call_count == 1
        assert store.rows["first"][0] == first_completed_bytes
        assert "Pending: 1; skipped already compressed: 1" in captured.out

    def test_readback_mismatch_fails_with_recovery_command(self, capsys):
        store = self._Store([self._row("one", "ordinary source text")])
        store.mismatch_readback = True

        with pytest.raises(SystemExit) as exc:
            self._run(capsys, store, wing="source")

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "Error verifying stored compressed drawers" in captured.err
        assert "Recover with: mempalace-code" in captured.err

    def test_unknown_wing_fails_before_store_or_backup_and_empty_scope_is_noop(self, capsys):
        payload = {
            "error": "unknown_wing",
            "filter": "wing",
            "value": "definitely-missing",
            "suggestions": [],
        }
        with (
            patch(
                "mempalace_code.taxonomy_filters.validate_taxonomy_filters",
                return_value=payload,
            ),
            patch("mempalace_code.storage.open_store") as open_store_mock,
            patch("mempalace_code.backup.create_backup") as backup,
            patch.object(
                sys,
                "argv",
                [
                    "mempalace",
                    "--palace",
                    "/tmp/palace",
                    "compress",
                    "--wing",
                    "definitely-missing",
                ],
            ),
        ):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "Unknown wing: 'definitely-missing'" in captured.err
        assert "mempalace-code status" in captured.err
        open_store_mock.assert_not_called()
        backup.assert_not_called()

        empty_store = self._Store([])
        captured, compressed_inputs, backup = self._run(
            capsys, empty_store, dry_run=True, wing="valid-empty"
        )
        assert compressed_inputs == []
        assert backup.call_count == 0
        assert "No drawers found in wing 'valid-empty'" in captured.out


# ─── No-embedder regression: read-only non-search CLI paths ──────────────────


class TestReadOnlyNonSearchNoEmbedder:
    """AC-1/AC-2: read-only non-search CLI commands avoid embedder startup."""

    def _seed(self, palace_path):
        store = open_store(palace_path, create=True)
        store.add(
            ids=["nse_seed_1"],
            documents=["read only non search test content for no embedder check"],
            metadatas=[{"wing": "w", "room": "r"}],
        )
        return store

    def _embedder_raises(self, *args, **kwargs):
        raise RuntimeError("embedder must not be initialized in this read-only path")

    def test_health_readonly_non_search_no_embedder(self, tmp_path, monkeypatch, capsys):
        """AC-1: health does not initialize embedder on a populated palace."""
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        self._seed(palace)
        monkeypatch.setattr(LanceStore, "_get_embedder", self._embedder_raises)

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "health"]):
            main()  # must not raise

        captured = capsys.readouterr()
        assert "ok" in captured.out.lower()

    def test_read_readonly_non_search_no_embedder(self, tmp_path, monkeypatch, capsys):
        """AC-1: read does not initialize embedder on a populated palace."""
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["rd_no_emb_chunk0"],
            documents=["def authenticate(user): validate credentials and authorize access"],
            metadatas=[
                {
                    "wing": "proj",
                    "room": "backend",
                    "source_file": "/project/auth.py",
                    "chunk_index": 0,
                    "added_by": "miner",
                    "filed_at": "2026-01-01T00:00:00",
                    "line_start": 1,
                    "line_end": 2,
                }
            ],
        )
        monkeypatch.setattr(LanceStore, "_get_embedder", self._embedder_raises)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "--palace",
                palace,
                "read",
                "/project/auth.py",
                "--start",
                "1",
                "--end",
                "2",
            ],
        ):
            main()

        captured = capsys.readouterr()
        assert "authenticate" in captured.out

    def test_compress_dry_run_readonly_non_search_no_embedder(self, tmp_path, monkeypatch, capsys):
        """AC-1: compress --dry-run does not initialize embedder."""
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        self._seed(palace)
        monkeypatch.setattr(LanceStore, "_get_embedder", self._embedder_raises)

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "compress", "--dry-run"]):
            main()

        captured = capsys.readouterr()
        assert "dry run" in captured.out.lower() or "nothing stored" in captured.out.lower()

    def test_repair_rollback_dry_run_readonly_non_search_no_embedder(
        self, tmp_path, monkeypatch, capsys
    ):
        """AC-1: repair --rollback --dry-run does not initialize embedder."""
        from mempalace_code.storage import LanceStore

        palace = str(tmp_path / "palace")
        self._seed(palace)
        monkeypatch.setattr(LanceStore, "_get_embedder", self._embedder_raises)

        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "--palace",
                palace,
                "repair",
                "--rollback",
                "--dry-run",
            ],
        ):
            main()  # must not raise

        captured = capsys.readouterr()
        assert captured.out.strip() != ""  # some version/candidate output expected

    def test_read_missing_palace_no_create_readonly_non_search_no_embedder(self, tmp_path, capsys):
        """AC-2: read on a missing palace does not create the palace directory."""
        palace = str(tmp_path / "nonexistent_palace")

        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "--palace",
                palace,
                "read",
                "/some/file.py",
                "--start",
                "1",
                "--end",
                "5",
            ],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code != 0
        assert not os.path.isdir(palace)
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "No palace found" in captured.err
        assert "Next:" in captured.err
        assert "mempalace-code init <dir>" in captured.err
        assert "mempalace-code mine <dir>" in captured.err

    def test_compress_dry_run_empty_palace_prints_next_action(self, tmp_path, capsys):
        """Empty compress result should name the safe next action."""
        palace = str(tmp_path / "palace")
        open_store(palace, create=True)

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "compress", "--dry-run"]):
            main()

        captured = capsys.readouterr()
        assert "No drawers found" in captured.out
        assert "Next:" in captured.out
        assert "mempalace-code mine <project-dir>" in captured.out

    def test_compress_dry_run_missing_palace_no_create_readonly_non_search_no_embedder(
        self, tmp_path, capsys
    ):
        """AC-2: compress --dry-run on a missing palace does not create the palace directory."""
        palace = str(tmp_path / "nonexistent_palace")

        with patch.object(
            sys,
            "argv",
            [
                "mempalace",
                "--palace",
                palace,
                "compress",
                "--dry-run",
            ],
        ):
            main()  # exits cleanly with "No drawers found." message

        captured = capsys.readouterr()
        assert "no drawers" in captured.out.lower() or "no palace" in captured.out.lower()
        assert not os.path.isdir(palace)


class TestCompressLiveRemainsWritable:
    """AC-3: live compress (without --dry-run) uses a write-capable store handle."""

    def test_compress_live_remains_writable(self, tmp_path, capsys):
        """AC-3: compress without --dry-run upserts compressed drawers through write handle."""
        palace = str(tmp_path / "palace")
        store = open_store(palace, create=True)
        store.add(
            ids=["comp_live_1"],
            documents=[
                "def authenticate(user): validate user credentials with JWT tokens for access control"
            ],
            metadatas=[{"wing": "w", "room": "r", "source_file": "auth.py"}],
        )
        count_before = store.count()

        with patch.object(sys, "argv", ["mempalace", "--palace", palace, "compress"]):
            main()  # must not raise

        store2 = open_store(palace, create=False)
        assert store2.count() == count_before

        captured = capsys.readouterr()
        assert "Stored" in captured.out or "compressed" in captured.out.lower()


# ── CLI-DEGRADED-INPUT-RECOVERY: parser-level and boundary tests ────────────────


class TestVersionAndHelp:
    def test_version_flag_exits_zero_with_version_string(self, capsys):
        from mempalace_code.version import __version__

        with pytest.raises(SystemExit) as exc:
            with patch.object(sys, "argv", ["mempalace-code", "--version"]):
                main()

        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert __version__ in captured.out

    def test_help_subcommand_prints_help_exits_zero(self, capsys):
        with patch.object(sys, "argv", ["mempalace-code", "help"]):
            main()

        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower()

    def test_no_command_prints_help_exits_zero(self, capsys):
        with patch.object(sys, "argv", ["mempalace-code"]):
            main()

        captured = capsys.readouterr()
        assert "usage:" in captured.out.lower()


class TestPalaceOptionOrderTolerance:
    def test_palace_before_subcommand_accepted(self, tmp_path, capsys):
        palace = str(tmp_path / "palace")
        with patch.object(sys, "argv", ["mempalace-code", "--palace", palace, "status"]):
            main()

    def test_palace_after_subcommand_accepted(self, tmp_path, capsys):
        palace = str(tmp_path / "palace")
        with patch.object(sys, "argv", ["mempalace-code", "status", "--palace", palace]):
            main()

    def test_palace_after_subcommand_equals_form_accepted(self, tmp_path, capsys):
        palace = str(tmp_path / "palace")
        with patch.object(sys, "argv", ["mempalace-code", "status", f"--palace={palace}"]):
            main()

    def test_palace_after_subcommand_reaches_handler(self, tmp_path, capsys):
        palace_a = tmp_path / "palace_a"
        palace_b = tmp_path / "palace_b"
        store_a = open_store(str(palace_a), create=True)
        store_a.add(
            ids=["id1"],
            documents=["content alpha"],
            metadatas=[{"wing": "wing_alpha", "room": "r", "source_file": "f.py"}],
        )
        store_b = open_store(str(palace_b), create=True)
        store_b.add(
            ids=["id2"],
            documents=["content beta"],
            metadatas=[{"wing": "wing_beta", "room": "r", "source_file": "f.py"}],
        )

        with patch.object(sys, "argv", ["mempalace-code", "status", "--palace", str(palace_a)]):
            main()

        captured = capsys.readouterr()
        assert "wing_alpha" in captured.out
        assert "wing_beta" not in captured.out

        capsys.readouterr()
        with patch.object(sys, "argv", ["mempalace-code", "status", "--palace", str(palace_b)]):
            main()

        captured = capsys.readouterr()
        assert "wing_beta" in captured.out
        assert "wing_alpha" not in captured.out

    # ── Repeated-palace unit tests (CLI-DEGRADED-INPUT-RECOVERY) ──────────────

    @pytest.mark.parametrize(
        "argv_builder",
        [
            lambda p: ["mp", "--palace", p, "status", "--palace", p],
            lambda p: ["mp", f"--palace={p}", "status", f"--palace={p}"],
            lambda p: ["mp", "--palace", p, "status", f"--palace={p}"],
        ],
        ids=["space+space", "equals+equals", "space+equals"],
    )
    def test_palace_duplicate_identical_normalises(self, tmp_path, argv_builder):
        """Identical --palace values (any form combination) normalise idempotently — exit 0."""
        palace = str(tmp_path / "palace")
        with patch.object(sys, "argv", argv_builder(palace)):
            main()  # must not raise

    def test_palace_conflicting_values(self, tmp_path, capsys):
        """Conflicting --palace values exit 2, name both paths in stderr, and create no dirs."""
        palace_a = str(tmp_path / "palace_a")
        palace_b = str(tmp_path / "palace_b")
        with patch.object(
            sys, "argv", ["mp", "--palace", palace_a, "status", "--palace", palace_b]
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert palace_a in err, f"first path missing from error: {err!r}"
        assert palace_b in err, f"second path missing from error: {err!r}"
        assert not (tmp_path / "palace_a").exists(), "palace_a must not be created on conflict"
        assert not (tmp_path / "palace_b").exists(), "palace_b must not be created on conflict"

    def test_palace_missing_value_at_end_is_parser_error(self, tmp_path, capsys):
        """Bare --palace with no value at argv end must exit 2 via argparse."""
        with patch.object(sys, "argv", ["mp", "status", "--palace"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2

    def test_hoist_helper_idempotent_same_value(self, tmp_path):
        """Unit: identical values in both space and = forms collapse to one palace token."""
        p = str(tmp_path / "palace")
        result = _hoist_palace_before_subcommand(["status", "--palace", p, "--palace", p])
        assert result.count("--palace") == 1
        assert result[result.index("--palace") + 1] == p

    def test_hoist_helper_conflict_raises_system_exit_2(self, tmp_path):
        """Unit: conflicting values raise SystemExit(2) from the helper itself."""
        a = str(tmp_path / "a")
        b = str(tmp_path / "b")
        with pytest.raises(SystemExit) as exc:
            _hoist_palace_before_subcommand(["status", "--palace", a, "--palace", b])
        assert exc.value.code == 2

    def test_hoist_helper_missing_value_passthrough(self, tmp_path):
        """Unit: bare --palace at argv end is passed through unchanged for argparse."""
        result = _hoist_palace_before_subcommand(["status", "--palace"])
        assert result == ["status", "--palace"]

    def test_hoist_helper_option_token_as_value_exits_2(self):
        """Unit: --palace followed by an option token is a bounded missing-value error (gap 1)."""
        with pytest.raises(SystemExit) as exc:
            _hoist_palace_before_subcommand(["status", "--palace", "--summary"])
        assert exc.value.code == 2

    def test_hoist_helper_delimiter_stops_hoisting(self, tmp_path):
        """Unit: -- sentinel stops scanning; --palace after -- is never extracted (gap 2)."""
        p = str(tmp_path / "palace")
        result = _hoist_palace_before_subcommand(["status", "--", "--palace", p])
        assert result == ["status", "--", "--palace", p]

    def test_palace_option_token_as_value_is_parser_error(self, tmp_path, capsys):
        """Integration: --palace followed by an option token exits 2 without misrouting (gap 1)."""
        with patch.object(sys, "argv", ["mp", "status", "--palace", "--summary"]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2


class TestSearchResultsBoundary:
    def test_results_zero_rejected_at_cli(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            with patch.object(sys, "argv", ["mempalace-code", "search", "query", "--results", "0"]):
                main()

        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "error" in captured.err.lower() or "invalid" in captured.err.lower()

    def test_results_negative_rejected_at_cli(self, tmp_path, capsys):
        with pytest.raises(SystemExit) as exc:
            with patch.object(
                sys, "argv", ["mempalace-code", "search", "query", "--results", "-1"]
            ):
                main()

        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "error" in captured.err.lower() or "invalid" in captured.err.lower()

    def test_results_one_accepted(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        palace = str(tmp_path / "palace")

        with patch("mempalace_code.searcher.search") as mock_search:
            with patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", palace, "search", "q", "--results", "1"],
            ):
                main()

        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs["n_results"] == 1


class TestImportDryRunReadOnly:
    @staticmethod
    def _configure_isolated_state(tmp_path, monkeypatch):
        home = tmp_path / "home"
        process_tmp = tmp_path / "process-tmp"
        process_tmp.mkdir()
        monkeypatch.setenv("HOME", str(home))
        for name in ("TMPDIR", "TMP", "TEMP"):
            monkeypatch.setenv(name, str(process_tmp))
        monkeypatch.setattr(tempfile, "tempdir", str(process_tmp))

        kg_path = home / ".mempalace" / "knowledge_graph.sqlite3"
        monkeypatch.setattr(
            "mempalace_code.knowledge_graph.DEFAULT_KG_PATH",
            str(kg_path),
        )
        return kg_path, process_tmp

    @staticmethod
    def _write_records(path, records):
        path.write_text(
            "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records),
            encoding="utf-8",
        )

    @staticmethod
    def _records(drawer_id="drawer-1", text="unique import preview text"):
        return [
            {"type": "export_header"},
            {
                "type": "drawer",
                "id": drawer_id,
                "text": text,
                "wing": "test",
                "room": "imports",
            },
            {
                "type": "kg_triple",
                "subject": "Preview Subject",
                "predicate": "relates_to",
                "object": "Preview Object",
            },
        ]

    def test_absent_state_repeated_preview_and_skip_kg_create_nothing(
        self, tmp_path, capsys, monkeypatch
    ):
        global_kg_path, process_tmp = self._configure_isolated_state(tmp_path, monkeypatch)
        palace = tmp_path / "absent-palace"
        local_kg_path = palace / "knowledge_graph.sqlite3"
        jsonl = tmp_path / "import.jsonl"
        self._write_records(jsonl, self._records())

        def fail_embedder(_store):
            raise AssertionError("absent-state dry-run must not initialize the embedder")

        monkeypatch.setattr(LanceStore, "_get_embedder", fail_embedder)
        baseline = _snapshot_paths(tmp_path, process_tmp)

        for _ in range(2):
            with patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(palace), "import", str(jsonl), "--dry-run"],
            ):
                main()

            out = capsys.readouterr().out
            assert "Imported drawers:   1" in out
            assert "Skipped duplicates: 0" in out
            assert "Imported KG triples:1" in out
            assert _snapshot_paths(tmp_path, process_tmp) == baseline

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                str(palace),
                "import",
                str(jsonl),
                "--dry-run",
                "--skip-kg",
            ],
        ):
            main()

        out = capsys.readouterr().out
        assert "Imported drawers:   1" in out
        assert "Skipped duplicates: 0" in out
        assert "Imported KG triples:0" in out
        assert _snapshot_paths(tmp_path, process_tmp) == baseline
        assert not palace.exists()
        assert not local_kg_path.exists()
        assert not global_kg_path.exists()

    @pytest.mark.parametrize("source", ["file", "stdin"])
    def test_malformed_input_exits_before_store_or_kg_initialization(
        self, tmp_path, capsys, monkeypatch, source
    ):
        import io

        self._configure_isolated_state(tmp_path, monkeypatch)
        palace = tmp_path / "absent-palace"
        jsonl = tmp_path / "malformed.jsonl"
        jsonl.write_text('{"type": "drawer"\n', encoding="utf-8")
        baseline = _snapshot_paths(tmp_path)
        input_arg = str(jsonl)
        if source == "stdin":
            input_arg = "-"
            monkeypatch.setattr(sys, "stdin", io.StringIO('{"type": "drawer"\n'))

        with (
            patch("mempalace_code.storage.open_store") as store_open,
            patch("mempalace_code.knowledge_graph.KnowledgeGraph") as kg_open,
            patch("mempalace_code.knowledge_graph.LazyKnowledgeGraph") as lazy_kg_open,
            pytest.raises(SystemExit) as exc,
            patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(palace), "import", input_arg, "--dry-run"],
            ),
        ):
            main()

        assert exc.value.code != 0
        assert "malformed JSONL input" in capsys.readouterr().err
        store_open.assert_not_called()
        kg_open.assert_not_called()
        lazy_kg_open.assert_not_called()
        assert _snapshot_paths(tmp_path) == baseline

    def test_existing_state_preview_keeps_counts_health_and_bytes_stable(
        self, tmp_path, capsys, monkeypatch
    ):
        global_kg_path, _process_tmp = self._configure_isolated_state(tmp_path, monkeypatch)
        palace = tmp_path / "palace"
        local_kg_path = palace / "knowledge_graph.sqlite3"
        duplicate_text = "existing drawer text for deterministic duplicate detection"
        store = open_store(str(palace), create=True)
        assert isinstance(store, LanceStore)
        store.add(
            ids=["existing-drawer"],
            documents=[duplicate_text],
            metadatas=[{"wing": "test", "room": "imports"}],
        )

        from mempalace_code.knowledge_graph import KnowledgeGraph

        kg = KnowledgeGraph(db_path=str(local_kg_path))
        kg.add_triple("Existing Subject", "relates_to", "Existing Object")

        jsonl = tmp_path / "import.jsonl"
        records = self._records("duplicate-drawer", duplicate_text)
        records.insert(
            2,
            {
                "type": "drawer",
                "id": "new-drawer",
                "text": "entirely separate vocabulary for the new preview drawer",
                "wing": "test",
                "room": "imports",
            },
        )
        self._write_records(jsonl, records)
        health_before = store.health_check()
        kg_stats_before = kg.stats()
        # Lance may retain empty process-scoped scratch directories until process
        # exit. The user-facing dry-run contract covers persistent palace and KG state.
        baseline = _snapshot_paths(palace, local_kg_path, global_kg_path)

        for _ in range(2):
            with patch.object(
                sys,
                "argv",
                ["mempalace-code", "--palace", str(palace), "import", str(jsonl), "--dry-run"],
            ):
                main()

            out = capsys.readouterr().out
            assert "Imported drawers:   1" in out
            assert "Skipped duplicates: 1" in out
            assert "Imported KG triples:1" in out
            assert _snapshot_paths(palace, local_kg_path, global_kg_path) == baseline
            assert store.health_check() == health_before
            assert kg.stats() == kg_stats_before
            assert local_kg_path.is_file()
            assert not global_kg_path.exists()

    def test_live_import_still_creates_and_writes_palace_and_kg(
        self, tmp_path, capsys, monkeypatch
    ):
        global_kg_path, _process_tmp = self._configure_isolated_state(tmp_path, monkeypatch)
        palace = tmp_path / "live-palace"
        local_kg_path = palace / "knowledge_graph.sqlite3"
        jsonl = tmp_path / "live-import.jsonl"
        text = "live import drawer content"
        self._write_records(jsonl, self._records("live-drawer", text))

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", str(palace), "import", str(jsonl)],
        ):
            main()

        out = capsys.readouterr().out
        assert "Imported drawers:   1" in out
        assert "Skipped duplicates: 0" in out
        assert "Imported KG triples:1" in out
        assert palace.is_dir()
        assert local_kg_path.is_file()
        assert not global_kg_path.exists()

        stored = open_store(str(palace), create=False, read_only=True).get(
            ids=["live-drawer"], include=["documents"]
        )
        assert stored["ids"] == ["live-drawer"]
        assert stored["documents"] == [text]

        from mempalace_code.knowledge_graph import KnowledgeGraph

        assert KnowledgeGraph(db_path=str(local_kg_path)).stats()["triples"] == 1

    def test_omitted_palace_keeps_home_global_kg_default(self, tmp_path, capsys, monkeypatch):
        global_kg_path, _process_tmp = self._configure_isolated_state(tmp_path, monkeypatch)
        default_palace = tmp_path / "default-palace"
        local_kg_path = default_palace / "knowledge_graph.sqlite3"
        jsonl = tmp_path / "global-import.jsonl"
        self._write_records(jsonl, self._records("global-drawer", "global import content"))

        with (
            patch("mempalace_code.cli_commands.export_import.MempalaceConfig") as config,
            patch.object(sys, "argv", ["mempalace-code", "import", str(jsonl)]),
        ):
            config.return_value.palace_path = str(default_palace)
            main()

        assert "Imported KG triples:1" in capsys.readouterr().out
        assert global_kg_path.is_file()
        assert not local_kg_path.exists()

        from mempalace_code.knowledge_graph import KnowledgeGraph

        assert KnowledgeGraph().stats()["triples"] == 1

    def test_explicit_two_palaces_isolate_file_stdin_and_skip_kg(
        self, tmp_path, capsys, monkeypatch
    ):
        import io

        global_kg_path, _process_tmp = self._configure_isolated_state(tmp_path, monkeypatch)
        palace_file = tmp_path / "palace-file"
        palace_stdin = tmp_path / "palace-stdin"
        palace_skip = tmp_path / "palace-skip"
        file_kg_path = palace_file / "knowledge_graph.sqlite3"
        stdin_kg_path = palace_stdin / "knowledge_graph.sqlite3"
        skip_kg_path = palace_skip / "knowledge_graph.sqlite3"
        jsonl = tmp_path / "file-import.jsonl"
        file_records = self._records("file-drawer", "file import content")
        file_records[-1]["subject"] = "File Subject"
        stdin_records = self._records("stdin-drawer", "stdin import content")
        stdin_records[-1]["subject"] = "Stdin Subject"
        self._write_records(jsonl, file_records)

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", str(palace_file), "import", str(jsonl)],
        ):
            main()
        capsys.readouterr()

        stdin_payload = "".join(
            f"{json.dumps(record, sort_keys=True)}\n" for record in stdin_records
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", str(palace_stdin), "import", "-"],
        ):
            main()
        capsys.readouterr()

        with patch.object(
            sys,
            "argv",
            [
                "mempalace-code",
                "--palace",
                str(palace_skip),
                "import",
                str(jsonl),
                "--skip-kg",
            ],
        ):
            main()
        assert "Imported KG triples:0" in capsys.readouterr().out

        from mempalace_code.knowledge_graph import KnowledgeGraph

        file_subjects = {
            triple["subject"]
            for batch in KnowledgeGraph(db_path=str(file_kg_path)).iter_all_triples()
            for triple in batch
        }
        stdin_subjects = {
            triple["subject"]
            for batch in KnowledgeGraph(db_path=str(stdin_kg_path)).iter_all_triples()
            for triple in batch
        }
        assert file_subjects == {"File Subject"}
        assert stdin_subjects == {"Stdin Subject"}
        assert not skip_kg_path.exists()
        assert not global_kg_path.exists()


class TestImportMissingFile:
    def test_missing_jsonl_file_exits_without_traceback(self, tmp_path, capsys):
        missing = str(tmp_path / "nonexistent.jsonl")

        with pytest.raises(SystemExit) as exc:
            with patch.object(sys, "argv", ["mempalace-code", "import", missing]):
                main()

        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert "Traceback" not in captured.out + captured.err
        assert missing in captured.err

    def test_missing_jsonl_file_shows_recovery_action(self, tmp_path, capsys):
        missing = str(tmp_path / "nonexistent.jsonl")

        with pytest.raises(SystemExit) as exc:
            with patch.object(sys, "argv", ["mempalace-code", "import", missing]):
                main()

        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert "Next:" in captured.err or "export" in captured.err.lower()

    def test_valid_file_reaches_storage_not_missing_file_error(self, tmp_path, capsys):
        """A valid JSONL file passes the missing-file guard and proceeds to storage."""
        good_jsonl = tmp_path / "good.jsonl"
        good_jsonl.write_text(
            '{"content": "hello", "wing": "w", "room": "r", "chunker_strategy": "manual_v1"}\n',
            encoding="utf-8",
        )
        palace = str(tmp_path / "palace")

        with patch.object(
            sys,
            "argv",
            ["mempalace-code", "--palace", palace, "import", str(good_jsonl)],
        ):
            main()

        captured = capsys.readouterr()
        assert "import file not found" not in captured.err
