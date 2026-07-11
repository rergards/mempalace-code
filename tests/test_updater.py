"""Behavioral tests for explicit, rollback-safe update orchestration."""

from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from mempalace_code.cli_commands.update import cmd_update
from mempalace_code.operation_lock import OperationLock
from mempalace_code.updater import Installation, UpdateManager, UpdateResult, detect_installation

if TYPE_CHECKING:
    from collections.abc import Callable


class FakeService:
    def __init__(self, active: bool = True) -> None:
        self.active = active
        self.unit = "mempalace-watch.service"
        self.calls: list[str] = []

    def is_active(self) -> tuple[bool, str]:
        self.calls.append("is-active")
        return self.active, "active" if self.active else "inactive"

    def stop(self) -> tuple[bool, str]:
        self.calls.append("stop")
        self.active = False
        return True, ""

    def start(self) -> tuple[bool, str]:
        self.calls.append("start")
        self.active = True
        return True, ""


def _installation(extras: frozenset[str] = frozenset({"watch", "spellcheck"})) -> Installation:
    return Installation(
        kind="bootstrap-venv",
        python="/opt/mempalace/bin/python",
        cli_command=("/opt/mempalace/bin/python", "-m", "mempalace_code"),
        manager_command=("/opt/mempalace/bin/python", "-m", "pip"),
        extras=extras,
    )


def _pypi():
    return {
        "releases": {
            "1.11.1": [
                {
                    "packagetype": "bdist_wheel",
                    "filename": "mempalace_code-1.11.1-py3-none-any.whl",
                    "url": "https://files.pythonhosted.org/mempalace-1.11.1.whl",
                    "digests": {"sha256": "a" * 64},
                    "upload_time_iso_8601": "2026-07-11T00:00:00Z",
                    "yanked": False,
                }
            ],
            "1.12.0rc1": [{"packagetype": "bdist_wheel", "yanked": False}],
            "2.0.0": [{"packagetype": "bdist_wheel", "yanked": False}],
        }
    }


def _manager(
    tmp_path: Path,
    *,
    service: FakeService | None = None,
    palace_validator: Callable[[str], tuple[bool, str]] | None = None,
    extras: frozenset[str] | None = None,
):
    commands: list[list[str]] = []

    def default_runner(command: list[str]):
        commands.append(command)
        if command[:3] == ["systemctl", "--user", "is-enabled"]:
            return 1, "disabled\n", ""
        if command[:3] == ["systemctl", "--user", "show"]:
            return 0, "NextElapseUSecRealtime=\n", ""
        return 0, "ok", ""

    manager = UpdateManager(
        state_root=tmp_path / "state",
        palace_path=str(tmp_path / "palace"),
        installation=_installation(
            extras if extras is not None else frozenset({"watch", "spellcheck"})
        ),
        runner=default_runner,
        fetcher=_pypi,
        lock=OperationLock(tmp_path / "state" / "operation.lock"),
        service=service or FakeService(),
        palace_validator=palace_validator or (lambda _path: (True, "healthy")),
        backup_preflight=lambda: (True, "backup policy checked"),
        minimum_free_bytes=0,
    )
    return manager, commands


class TestUpdateStatus:
    def test_status_reports_eligibility_provenance_and_next_run_without_mutation(self, tmp_path):
        service = FakeService(active=True)
        manager, commands = _manager(tmp_path, service=service)

        result = manager.status()

        assert result.ok is True
        assert result.stage == "status"
        assert result.data["eligible"] is True
        assert result.data["provenance"]["target_version"] == "1.11.1"  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["provenance"]["sha256"] == "a" * 64  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["installation"]["extras"] == ["spellcheck", "watch"]  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["watcher"]["active"] is True  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["next_run"] is None
        assert not (tmp_path / "state" / "updates" / "state.json").exists()
        assert all("pip" not in command for command in commands)
        assert service.calls == ["is-active"]


class TestApplyUpdate:
    def test_apply_stops_active_watcher_preserves_extras_and_restarts_after_validation(
        self, tmp_path
    ):
        service = FakeService(active=True)
        manager, commands = _manager(tmp_path, service=service)

        result = manager.apply()

        assert result.ok is True
        assert result.stage == "succeeded"
        install = next(command for command in commands if "install" in command)
        assert "mempalace-code[spellcheck,watch]==1.11.1" in install
        assert service.calls == ["is-active", "stop", "start", "is-active"]
        assert (tmp_path / "state" / "updates" / "state.json").exists()
        assert result.log_path is not None
        assert Path(result.log_path).exists()


class TestRollback:
    def test_failed_validation_restores_prior_version_and_reports_stage_log(self, tmp_path):
        service = FakeService(active=True)
        manager, commands = _manager(
            tmp_path,
            service=service,
            palace_validator=lambda _path: (False, "fragment probe failed"),
        )

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "palace-health"
        assert result.log_path is not None
        assert Path(result.log_path).exists()
        install_commands = [command for command in commands if "install" in command]
        assert install_commands[0][-1].endswith("==1.11.1")
        assert install_commands[1][-1].endswith("==1.11.0")
        state = (tmp_path / "state" / "updates" / "state.json").read_text(encoding="utf-8")
        assert '"stage": "rollback-succeeded"' in state
        assert service.active is True

    def test_installer_timeout_rolls_back_and_restores_watcher(self, tmp_path):
        service = FakeService(active=True)
        manager, commands = _manager(tmp_path, service=service)

        def timeout_runner(command: list[str]):
            commands.append(command)
            if "install" in command and command[-1].endswith("==1.11.1"):
                raise subprocess.TimeoutExpired(command, timeout=900)
            return 0, "ok", ""

        manager.runner = timeout_runner

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "installer"
        assert "timed out" in result.message
        install_commands = [command for command in commands if "install" in command]
        assert [command[-1] for command in install_commands] == [
            "mempalace-code[spellcheck,watch]==1.11.1",
            "mempalace-code[spellcheck,watch]==1.11.0",
        ]
        assert service.calls == ["is-active", "stop", "start", "is-active"]
        state = json.loads(manager.state_path.read_text(encoding="utf-8"))
        assert state["stage"] == "rollback-succeeded"

    def test_unexpected_validation_error_rolls_back_and_restores_watcher(self, tmp_path):
        service = FakeService(active=True)

        def broken_validator(_path: str) -> tuple[bool, str]:
            raise RuntimeError("health probe unexpectedly crashed")

        manager, commands = _manager(
            tmp_path,
            service=service,
            palace_validator=broken_validator,
        )

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "transaction"
        assert "health probe unexpectedly crashed" in result.message
        install_commands = [command for command in commands if "install" in command]
        assert install_commands[1][-1].endswith("==1.11.0")
        assert service.calls == ["is-active", "stop", "start", "is-active"]
        state = json.loads(manager.state_path.read_text(encoding="utf-8"))
        assert state["stage"] == "rollback-succeeded"


class TestScheduling:
    def test_scheduler_is_disabled_by_default_and_refuses_overlap(self, tmp_path):
        service = FakeService(active=True)
        manager, commands = _manager(tmp_path, service=service)

        assert manager.scheduler_status()["enabled"] is False
        rendered = manager.render_scheduler_units()
        assert "--scheduled" in rendered["mempalace-update.service"]

        with manager.lock.acquire_exclusive("scheduled-update"):
            result = manager.apply(scheduled=True)

        assert result.ok is False
        assert result.stage == "lock"
        assert not any("pip" in command for command in commands)
        assert service.calls == ["is-active"]

    def test_stale_exclusive_owner_does_not_block_apply(self, tmp_path):
        service = FakeService(active=True)
        manager, _ = _manager(tmp_path, service=service)
        manager.lock.owners_path.parent.mkdir(parents=True, exist_ok=True)
        manager.lock.owners_path.write_text(
            json.dumps(
                {
                    "stale": {
                        "mode": "exclusive",
                        "operation": "update",
                        "pid": 999999999,
                    }
                }
            ),
            encoding="utf-8",
        )

        result = manager.apply()

        assert result.ok is True
        assert result.stage == "succeeded"
        assert service.calls == ["is-active", "stop", "start", "is-active"]


class TestInstallerDetection:
    def test_unsupported_or_missing_required_extra_fails_before_mutation(self, tmp_path):
        service = FakeService(active=True)
        manager, commands = _manager(tmp_path, service=service, extras=frozenset())

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "preflight"
        assert "required watch extra" in result.message
        assert service.calls == ["is-active"]
        assert not any("pip" in command for command in commands)
        assert not (tmp_path / "state" / "updates" / "state.json").exists()

    def test_default_uv_tool_prefix_is_supported_without_environment_override(self, tmp_path):
        data_home = tmp_path / "xdg-data"
        prefix = data_home / "uv" / "tools" / "mempalace-code"

        with patch("mempalace_code.updater._has_editable_metadata", return_value=False):
            installation = detect_installation(
                python=str(prefix / "bin" / "python"),
                prefix=prefix,
                base_prefix=tmp_path / "system-python",
                environ={"XDG_DATA_HOME": str(data_home)},
                which=lambda name: "/usr/bin/uv" if name == "uv" else None,
                extras=frozenset(),
            )

        assert installation.kind == "uv-tool"
        assert installation.supported is True
        assert installation.manager_command == ("/usr/bin/uv",)


class TestUpdateCommand:
    def test_status_renders_json_without_invoking_apply(self, capsys):
        manager = MagicMock()
        manager.status.return_value = UpdateResult(
            True,
            "status",
            "update status inspected without mutation",
            0,
            data={
                "eligible": True,
                "installation": {},
                "provenance": {},
                "watcher": {},
                "scheduler": {},
            },
        )
        args = Namespace(update_command="status", palace=None, json=True)

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            cmd_update(args)

        assert '"eligible": true' in capsys.readouterr().out
        manager.status.assert_called_once_with()
        manager.apply.assert_not_called()

    def test_apply_requires_yes_before_invoking_updater(self, capsys):
        manager = MagicMock()
        args = Namespace(update_command="apply", palace=None, yes=False, json=False)

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            with pytest.raises(SystemExit) as exc_info:
                cmd_update(args)

        assert exc_info.value.code == 2
        manager.apply.assert_not_called()
        assert "Re-run with --yes" in capsys.readouterr().err
