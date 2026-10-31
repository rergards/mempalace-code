"""Behavioral tests for explicit, rollback-safe update orchestration."""

from __future__ import annotations

import dis
import inspect
import json
import os
import plistlib
import shlex
import signal
import sqlite3
import subprocess
import sys
import threading
from argparse import Namespace
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
from packaging.version import Version

import mempalace_code.updater as updater
from mempalace_code.cli_commands.update import cmd_update
from mempalace_code.operation_lock import OperationLock
from mempalace_code.updater import (
    DEFAULT_LAUNCHD_WATCH_LABEL,
    DEFAULT_SERVICE_UNIT,
    DEFAULT_TIMER_UNIT,
    DEFAULT_WATCHER_UNIT,
    SCHEDULER_UNSET_ENVIRONMENT,
    SYSTEMD_BASELINE_PATH,
    Installation,
    LaunchdUserService,
    SystemdUserService,
    UpdateManager,
    UpdateResult,
    WatcherDiscovery,
    detect_installation,
)
from mempalace_code.updater import __version__ as _INSTALLED_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable

# Release fixtures are derived from the installed version rather than hard-coded,
# so they stay eligible/prerelease/incompatible relative to whatever version this
# checkout actually reports instead of drifting stale as releases ship.
_CURRENT = Version(_INSTALLED_VERSION)
CURRENT_VERSION = str(_CURRENT)
ELIGIBLE_VERSION = f"{_CURRENT.major}.{_CURRENT.minor}.{_CURRENT.micro + 1}"
PRERELEASE_VERSION = f"{_CURRENT.major}.{_CURRENT.minor}.{_CURRENT.micro + 2}rc1"
INCOMPATIBLE_MAJOR_VERSION = f"{_CURRENT.major + 1}.0.0"


@pytest.fixture(autouse=True)
def _supported_update_platform(monkeypatch, tmp_path):
    """Keep established transaction tests on their supported Linux boundary."""
    monkeypatch.setattr(updater.sys, "platform", "linux")
    monkeypatch.setattr(updater.Path, "home", lambda: tmp_path)
    original_alive = OperationLock._owner_is_alive
    monkeypatch.setattr(
        OperationLock,
        "_owner_is_alive",
        staticmethod(
            lambda owner: (
                owner.get("pid") in {91001, 91002, *range(4200, 4300)} or original_alive(owner)
            )
        ),
    )


class FakeService:
    def __init__(self, active: bool = True) -> None:
        self.active = active
        self.unit = "mempalace-watch.service"
        self.calls: list[str] = []
        self._stopped: tuple[str, ...] = ()
        self.stop_guard: Callable[[], None] | None = None
        self.prepare_capture: Callable[[], None] = lambda: None

    @property
    def attempted_stops(self) -> tuple[str, ...]:
        return self._stopped

    def capture_actors(self, observe: updater.ProcessObserver) -> tuple[updater.WatcherActor, ...]:
        self.prepare_capture()
        birth = observe(91001)
        if birth is None:
            raise ValueError("selected fixture actor exited")
        return (updater.WatcherActor(self.unit, 91001, birth),)

    def discover(self) -> WatcherDiscovery:
        return WatcherDiscovery(unit=self.unit, active=self.active, safe=True, detail="")

    def is_active(self) -> tuple[bool, str]:
        self.calls.append("is-active")
        return self.active, "active" if self.active else "inactive"

    def stop(self) -> tuple[bool, str]:
        if self.stop_guard is not None:
            self.stop_guard()
        self._stopped = (self.unit,)
        self.calls.append("stop")
        self.active = False
        return True, ""

    def start(self) -> tuple[bool, str]:
        self.calls.append("start")
        self._stopped = ()
        self.active = True
        return True, ""


def _wal_fixture(palace: Path) -> None:
    palace.mkdir(parents=True, exist_ok=True)
    path = palace / "knowledge_graph.sqlite3"
    if not path.exists():
        with closing(sqlite3.connect(path)) as db, db:
            assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            db.execute("CREATE TABLE specimen (value TEXT)")
            db.execute("INSERT INTO specimen VALUES ('preserved')")


def _owner_fixture(manager: UpdateManager, actors: tuple[updater.WatcherActor, ...]) -> None:
    path = manager.lock.owners_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    actor.unit: {
                        "pid": actor.pid,
                        "mode": "shared",
                        "operation": "watcher",
                        "palace": str(Path(manager.palace_path).resolve()),
                        "acquired_at": int(updater.time.time()),
                    }
                    for actor in actors
                }
            ),
            encoding="utf-8",
        )


def _prepare_fake(manager: UpdateManager, service: FakeService) -> None:
    _wal_fixture(Path(manager.palace_path))
    _owner_fixture(manager, (updater.WatcherActor(service.unit, 91001, 1),))


def _installation(extras: frozenset[str] = frozenset({"watch", "spellcheck"})) -> Installation:
    return Installation(
        kind="bootstrap-venv",
        python="/opt/mempalace/bin/python",
        cli_command=("/opt/mempalace/bin/python", "-m", "mempalace_code"),
        manager_command=("/opt/mempalace/bin/python", "-m", "pip"),
        extras=extras,
    )


def test_detect_installed_extras_ignores_retired_chromadb(monkeypatch):
    queried: list[str] = []

    def fake_find_spec(module: str):
        queried.append(module)
        return object() if module in {"watchfiles", "chromadb"} else None

    monkeypatch.setattr("mempalace_code.storage.find_spec", fake_find_spec)

    extras = updater.detect_installed_extras()

    assert extras == frozenset({"watch"})
    assert "chromadb" not in queried
    assert _installation(extras).package_spec(ELIGIBLE_VERSION) == (
        f"mempalace-code[watch]=={ELIGIBLE_VERSION}"
    )


def test_detect_installed_extras_retains_custom_models(monkeypatch):
    """uv tool install --force rebuilds from the spec, so a dropped extra is uninstalled."""
    present = {"sentence_transformers", "watchfiles"}
    monkeypatch.setattr(
        "mempalace_code.storage.find_spec", lambda module: object() if module in present else None
    )

    extras = updater.detect_installed_extras()

    assert extras == frozenset({"custom-models", "watch"})
    assert _installation(extras).package_spec(ELIGIBLE_VERSION) == (
        f"mempalace-code[custom-models,watch]=={ELIGIBLE_VERSION}"
    )


def _wheel(
    version: str, *, digest: str, yanked: bool = False, **overrides: object
) -> dict[str, object]:
    return {
        "packagetype": "bdist_wheel",
        "filename": f"mempalace_code-{version}-py3-none-any.whl",
        "url": f"https://files.pythonhosted.org/mempalace-{version}.whl",
        "digests": {"sha256": digest * 64},
        "upload_time_iso_8601": "2026-07-11T00:00:00Z",
        "yanked": yanked,
        **overrides,
    }


def _pypi():
    return {
        "releases": {
            ELIGIBLE_VERSION: [_wheel(ELIGIBLE_VERSION, digest="a")],
            # Keep rejected releases installable so target selection proves the
            # prerelease and major-version policy instead of missing wheel metadata.
            PRERELEASE_VERSION: [_wheel(PRERELEASE_VERSION, digest="b")],
            INCOMPATIBLE_MAJOR_VERSION: [_wheel(INCOMPATIBLE_MAJOR_VERSION, digest="c")],
        }
    }


def _current_pypi():
    return {
        "releases": {
            CURRENT_VERSION: [_wheel(CURRENT_VERSION, digest="d")],
            PRERELEASE_VERSION: [_wheel(PRERELEASE_VERSION, digest="e")],
            INCOMPATIBLE_MAJOR_VERSION: [_wheel(INCOMPATIBLE_MAJOR_VERSION, digest="f")],
        }
    }


def _yanked_current_pypi():
    return {"releases": {CURRENT_VERSION: [_wheel(CURRENT_VERSION, digest="g", yanked=True)]}}


def _manager(
    tmp_path: Path,
    *,
    service: FakeService | None = None,
    palace_validator: Callable[[str], tuple[bool, str]] | None = None,
    fetcher: Callable[[], dict[str, Any]] | None = None,
    installation: Installation | None = None,
    backup_preflight: Callable[[], tuple[bool, str]] | None = None,
    minimum_free_bytes: int = 0,
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
        installation=installation
        or _installation(extras if extras is not None else frozenset({"watch", "spellcheck"})),
        runner=default_runner,
        fetcher=fetcher or _pypi,
        lock=OperationLock(tmp_path / "state" / "operation.lock"),
        service=service or FakeService(),
        palace_validator=palace_validator or (lambda _path: (True, "healthy")),
        backup_preflight=backup_preflight or (lambda: (True, "backup policy checked")),
        scheduler_context=lambda: (Path.home() / ".config" / "systemd" / "user", None),
        minimum_free_bytes=minimum_free_bytes,
    )
    assert isinstance(manager.service, FakeService)
    selected_service = manager.service
    selected_service.prepare_capture = lambda: _prepare_fake(manager, selected_service)
    if selected_service.active:
        _owner_fixture(manager, (updater.WatcherActor(selected_service.unit, 91001, 1),))
    original_alive = manager.lock._owner_is_alive
    manager.lock._owner_is_alive = lambda owner: owner.get("pid") == 91001 or original_alive(owner)
    manager.observe_process = lambda _pid: 1 if selected_service.active else None
    manager.writer_wait = 0
    return manager, commands


def _systemd_manager(
    tmp_path: Path,
    *,
    active_units: list[str],
    exec_starts: dict[str, str],
    list_rc: int = 0,
    palace_validator: Callable[[str], tuple[bool, str]] | None = None,
):
    commands: list[list[str]] = []
    active = set(active_units)

    def runner(command: list[str]):
        commands.append(command)
        if command[:3] == ["systemctl", "--user", "list-units"]:
            if list_rc:
                return list_rc, "", "user manager unavailable"
            lines = [f"{unit} loaded active running watcher" for unit in sorted(active)]
            return 0, "\n".join(lines), ""
        if command[:3] == ["systemctl", "--user", "show"]:
            unit = command[3]
            if "--property=MainPID" in command:
                return 0, "91001", ""
            if "--property=ExecStart" in command:
                exec_start = exec_starts.get(unit, "")
                return 0, f"{{ path=/bin/sh ; argv[]={exec_start} ; ignore_errors=no ; }}", ""
            return 0, "NextElapseUSecRealtime=\n", ""
        if command[:3] == ["systemctl", "--user", "is-active"]:
            return (0, "active\n", "") if command[-1] in active else (3, "inactive\n", "")
        if command[:3] == ["systemctl", "--user", "stop"]:
            active.discard(command[-1])
            return 0, "", ""
        if command[:3] == ["systemctl", "--user", "start"]:
            active.add(command[-1])
            return 0, "", ""
        if command[:3] == ["systemctl", "--user", "is-enabled"]:
            return 1, "disabled\n", ""
        return 0, "ok", ""

    manager = UpdateManager(
        state_root=tmp_path / "state",
        palace_path=str(tmp_path / "palace"),
        installation=_installation(),
        runner=runner,
        fetcher=_pypi,
        lock=OperationLock(tmp_path / "state" / "operation.lock"),
        service=SystemdUserService(runner),
        palace_validator=palace_validator or (lambda _path: (True, "healthy")),
        backup_preflight=lambda: (True, "backup policy checked"),
        scheduler_context=lambda: (Path.home() / ".config" / "systemd" / "user", None),
        minimum_free_bytes=0,
    )
    if active_units:
        _wal_fixture(Path(manager.palace_path))
        _owner_fixture(manager, (updater.WatcherActor(active_units[0], 91001, 1),))
    manager.observe_process = lambda _pid: 1 if active else None
    manager.writer_wait = 0
    return manager, commands


class TestUpdateStatus:
    def test_status_reports_eligibility_provenance_and_next_run_without_mutation(self, tmp_path):
        service = FakeService(active=True)
        manager, commands = _manager(tmp_path, service=service)

        result = manager.status()

        assert result.ok is True
        assert result.stage == "status"
        assert result.data["eligible"] is True
        assert result.data["provenance"]["target_version"] == ELIGIBLE_VERSION  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["provenance"]["sha256"] == "a" * 64  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["installation"]["extras"] == ["spellcheck", "watch"]  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["watcher"]["active"] is True  # type: ignore[index]  # reason: result.data is typed as object; dict access is safe in tests
        assert result.data["next_run"] is None
        assert not (tmp_path / "state" / "updates" / "state.json").exists()
        assert all("pip" not in command for command in commands)
        assert service.calls == ["is-active"]


class TestUnsupportedPlatformDiagnostics:
    @staticmethod
    def _manager(tmp_path: Path, calls: list[list[str]]) -> UpdateManager:
        def runner(command: list[str]) -> tuple[int, str, str]:
            calls.append(command)
            raise FileNotFoundError(2, "No such file or directory", command[0])

        def unexpected_installation() -> Installation:
            raise AssertionError("mutation platform preflight must precede installer detection")

        def unexpected_fetch() -> dict[str, Any]:
            raise AssertionError("mutation platform preflight must precede provenance resolution")

        return UpdateManager(
            state_root=tmp_path / "state",
            installation_detector=unexpected_installation,
            runner=runner,
            fetcher=unexpected_fetch,
            minimum_free_bytes=0,
        )

    @staticmethod
    def _scheduler_result(platform: str = "darwin") -> dict[str, object]:
        """The scheduler boundary stays Linux systemd-user only on every platform."""
        return {
            "ok": False,
            "stage": "unsupported-platform",
            "message": (
                "scheduled update mutations require Linux systemd-user; "
                f"current platform is {platform}"
            ),
            "exit_code": 2,
            "log_path": None,
            "platform": platform,
            "required_platform": "linux",
            "service_manager": "systemd-user",
            "recovery_command": "mempalace-code update status --json",
        }

    @staticmethod
    def _manual_result(platform: str = "win32") -> dict[str, object]:
        """Manual apply refuses only where no supported user service manager exists."""
        return {
            "ok": False,
            "stage": "unsupported-platform",
            "message": (
                "manual update mutations require Linux systemd-user or macOS launchd-user; "
                f"current platform is {platform}"
            ),
            "exit_code": 2,
            "log_path": None,
            "platform": platform,
            "required_platforms": ["darwin", "linux"],
            "service_managers": ["launchd-user", "systemd-user"],
            "recovery_command": "mempalace-code update status --json",
        }

    @pytest.mark.parametrize("method", ["install_scheduler", "remove_scheduler"])
    def test_scheduler_mutations_refuse_before_effects_on_darwin(
        self, tmp_path, monkeypatch, method
    ):
        monkeypatch.setattr(updater.sys, "platform", "darwin")
        calls: list[list[str]] = []
        manager = self._manager(tmp_path, calls)
        before = tuple(tmp_path.rglob("*"))

        result = getattr(manager, method)()

        assert result.as_dict() == self._scheduler_result()
        assert calls == []
        assert tuple(tmp_path.rglob("*")) == before

    @pytest.mark.parametrize("method", ["apply", "install_scheduler", "remove_scheduler"])
    def test_confirmed_mutations_refuse_before_effects(self, tmp_path, monkeypatch, method):
        monkeypatch.setattr(updater.sys, "platform", "win32")
        calls: list[list[str]] = []
        manager = self._manager(tmp_path, calls)
        before = tuple(tmp_path.rglob("*"))

        result = getattr(manager, method)()

        expected = self._manual_result() if method == "apply" else self._scheduler_result("win32")
        assert result.as_dict() == expected
        assert calls == []
        assert tuple(tmp_path.rglob("*")) == before

    def test_status_is_useful_and_bypasses_systemd(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater.sys, "platform", "win32")
        calls: list[list[str]] = []

        def runner(command: list[str]) -> tuple[int, str, str]:
            calls.append(command)
            raise FileNotFoundError(2, "No such file or directory", command[0])

        manager = UpdateManager(
            state_root=tmp_path / "state",
            installation=_installation(),
            runner=runner,
            fetcher=_pypi,
            minimum_free_bytes=0,
        )
        before = tuple(tmp_path.rglob("*"))

        result = manager.status()
        scheduler = manager.scheduler_status()

        assert result.ok is True
        assert result.stage == "status"
        assert result.data["platform"] == "win32"
        assert result.data["installation"]["supported"] is True  # type: ignore[index]  # reason: stable status mapping
        assert result.data["provenance"]["target_version"] == ELIGIBLE_VERSION  # type: ignore[index]  # reason: stable status mapping
        assert result.data["watcher"] == {  # type: ignore[comparison-overlap]  # reason: stable status mapping
            "unit": DEFAULT_WATCHER_UNIT,
            "active": False,
            "detail": (
                "manual update mutations require Linux systemd-user or macOS launchd-user; "
                "current platform is win32"
            ),
            "safe": False,
            "supported": False,
            "platform": "win32",
            "required_platforms": ["darwin", "linux"],
            "service_managers": ["launchd-user", "systemd-user"],
            "recovery_command": "mempalace-code update status --json",
        }
        assert scheduler == result.data["scheduler"]
        assert calls == []
        assert tuple(tmp_path.rglob("*")) == before

    @pytest.mark.parametrize(
        ("update_command", "scheduler_command"),
        [("apply", None), ("scheduler", "install"), ("scheduler", "remove")],
    )
    def test_json_cli_uses_stable_result(
        self, tmp_path, monkeypatch, capsys, update_command, scheduler_command
    ):
        monkeypatch.setattr(updater.sys, "platform", "win32")
        calls: list[list[str]] = []
        manager = self._manager(tmp_path, calls)
        args = Namespace(
            update_command=update_command,
            scheduler_command=scheduler_command,
            palace=None,
            yes=True,
            json=True,
            scheduled=False,
        )

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            with pytest.raises(SystemExit) as exc_info:
                cmd_update(args)

        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.err == ""
        expected = (
            self._manual_result() if update_command == "apply" else self._scheduler_result("win32")
        )
        assert json.loads(captured.out) == expected
        assert "FileNotFoundError" not in captured.out
        assert "Errno" not in captured.out
        assert "systemctl" not in captured.out
        assert calls == []

    def test_linux_platform_passes_through_to_scheduler_transaction(self, tmp_path, monkeypatch):
        monkeypatch.setattr(updater.sys, "platform", "linux-gnu")
        monkeypatch.setattr(updater.Path, "home", lambda: tmp_path / "home")
        manager, commands = _manager(tmp_path)

        result = manager.install_scheduler()

        assert result.as_dict() == {
            "ok": True,
            "stage": "scheduler-installed",
            "message": "systemd-user update timer enabled",
            "exit_code": 0,
            "log_path": None,
        }
        assert commands == [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", DEFAULT_TIMER_UNIT],
        ]


WATCH_SH_ARGUMENTS = ["/bin/sh", "-c", "/usr/local/bin/mempalace-code watch /srv/dev"]
RECOVERY_HINT = "mempalace-code update status --json"


def _write_agent_plist(
    home: Path,
    label: str,
    *,
    program_arguments: list[str] | None = None,
    plist_label: str | None = None,
    symlink: bool = False,
) -> Path:
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / f"{label}.plist"
    if symlink:
        target = home / f"{label}.source.plist"
        target.write_bytes(b"")
        path.symlink_to(target)
        return path
    with path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": plist_label or label,
                "ProgramArguments": program_arguments or list(WATCH_SH_ARGUMENTS),
            },
            handle,
        )
    return path


def _launchd_manager(
    tmp_path: Path,
    monkeypatch,
    *,
    active_labels: list[str],
    list_rc: int = 0,
    bootout_rc: dict[str, int] | None = None,
    bootstrap_rc: dict[str, int] | None = None,
    passwd_home: Path | None = None,
    pids: dict[str, str] | None = None,
    domains: dict[str, tuple[str, ...]] | None = None,
):
    """Build a Darwin manager whose only service seam is a fake ``launchctl``."""
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    home = tmp_path / "home"
    (home / "Library" / "LaunchAgents").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(updater.Path, "home", lambda: home)
    # The adapter fails closed unless the process home is the effective uid's passwd
    # home, so the fixture injects that identity instead of relaxing the check.
    identity = home if passwd_home is None else passwd_home
    monkeypatch.setattr(updater.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=str(identity)))

    commands: list[list[str]] = []
    active = list(active_labels)
    bootout_codes = bootout_rc if bootout_rc is not None else {}
    bootstrap_codes = bootstrap_rc if bootstrap_rc is not None else {}
    pid_column = {
        label: (pids or {}).get(label, str(4200 + index))
        for index, label in enumerate(active_labels)
    }
    living = {int(value) for value in pid_column.values() if value.isdigit()}

    def runner(command: list[str]) -> tuple[int, str, str]:
        commands.append(command)
        if command[:2] == ["launchctl", "print"]:
            kind, _uid, label = command[2].split("/", 2)
            matches = (domains or {}).get(label, ("gui",))
            return (0, "", "") if kind in matches else (113, "", "service absent")
        if command[:2] == ["launchctl", "list"]:
            if list_rc:
                return list_rc, "", "Could not find domain for gui"
            lines = ["PID\tStatus\tLabel", "-\t0\tcom.apple.unrelated", "-\t0\tcom.mempalace.mine"]
            lines += [
                f"{pid_column.get(label, str(4200 + index))}\t0\t{label}"
                for index, label in enumerate(active)
            ]
            return 0, "\n".join(lines), ""
        if command[:2] == ["launchctl", "bootout"]:
            label = command[2].rsplit("/", 1)[-1]
            rc = bootout_codes.get(label, 0)
            if pid_column[label].isdigit():
                living.discard(int(pid_column[label]))
            if rc == 0 and label in active:
                active.remove(label)
            return rc, "", ("" if rc == 0 else "Bootout failed: 3: No such process")
        if command[:2] == ["launchctl", "bootstrap"]:
            label = Path(command[3]).name.removesuffix(".plist")
            rc = bootstrap_codes.get(label, 0)
            if rc == 0 and label not in active:
                active.append(label)
            if rc == 0 and pid_column[label].isdigit():
                living.add(int(pid_column[label]))
            return rc, "", ("" if rc == 0 else "Bootstrap failed: 5: Input/output error")
        return 0, "ok", ""

    manager = UpdateManager(
        state_root=tmp_path / "state",
        palace_path=str(tmp_path / "palace"),
        installation=_installation(),
        runner=runner,
        fetcher=_pypi,
        lock=OperationLock(tmp_path / "state" / "operation.lock"),
        service=LaunchdUserService(runner),
        palace_validator=lambda _path: (True, "healthy"),
        backup_preflight=lambda: (True, "backup policy checked"),
        minimum_free_bytes=0,
    )
    if active_labels:
        _wal_fixture(Path(manager.palace_path))
        _owner_fixture(
            manager,
            tuple(
                updater.WatcherActor(label, int(pid), 1)
                for label, pid in pid_column.items()
                if pid.isdigit()
            ),
        )
    manager.observe_process = lambda pid: 1 if pid in living else None
    manager.writer_wait = 0
    return manager, commands, home


def _domain(label: str) -> str:
    return f"gui/{os.geteuid()}/{label}"


class TestLaunchdWatcherDiscovery:
    """macOS manual apply coordinates launchd; scheduling stays Linux systemd-user."""

    def test_status_is_eligible_with_no_active_watcher(self, tmp_path, monkeypatch):
        manager, commands, _home = _launchd_manager(tmp_path, monkeypatch, active_labels=[])

        result = manager.status()

        assert result.data["eligible"] is True
        assert result.data["manual_update_supported"] is True
        assert result.data["watcher"] == {  # type: ignore[comparison-overlap]  # reason: stable status mapping
            "unit": DEFAULT_LAUNCHD_WATCH_LABEL,
            "active": False,
            "detail": "no active MemPalace watcher discovered",
            "safe": True,
        }
        assert result.data["scheduler"]["supported"] is False  # type: ignore[index]  # reason: stable status mapping
        assert result.data["scheduler"]["service_manager"] == "systemd-user"  # type: ignore[index]  # reason: stable status mapping
        assert all(command[0] != "systemctl" for command in commands)
        assert not manager.state_path.exists()

    @pytest.mark.parametrize("kinds", [("user",), ("gui",)])
    def test_apply_uses_the_verified_watcher_domain(self, tmp_path, monkeypatch, kinds):
        label = DEFAULT_LAUNCHD_WATCH_LABEL
        manager, commands, home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[label], domains={label: kinds}
        )
        agent = _write_agent_plist(home, label)
        result = manager.apply()
        assert result.ok
        domain = f"{kinds[0]}/{os.geteuid()}"
        assert ["launchctl", "bootout", f"{domain}/{label}"] in commands
        assert ["launchctl", "bootstrap", domain, str(agent)] in commands
        other = "gui" if kinds[0] == "user" else "user"
        assert ["launchctl", "bootout", f"{other}/{os.geteuid()}/{label}"] not in commands

    @pytest.mark.parametrize("kinds", [(), ("gui", "user")])
    def test_apply_refuses_missing_or_ambiguous_watcher_domain(self, tmp_path, monkeypatch, kinds):
        label = DEFAULT_LAUNCHD_WATCH_LABEL
        manager, commands, home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[label], domains={label: kinds}
        )
        _write_agent_plist(home, label)
        result = manager.apply()
        assert not result.ok
        assert result.stage == "preflight"
        assert "exactly one account launchd domain" in result.message
        assert not any(
            c[:2] in (["launchctl", "bootout"], ["launchctl", "bootstrap"]) for c in commands
        )
        assert not any("install" in c for c in commands)
        assert not manager.state_path.exists()

    def test_domain_probe_discards_service_environment(self, monkeypatch):
        mock = MagicMock(return_value=SimpleNamespace(returncode=0, stderr=""))
        monkeypatch.setattr(updater.subprocess, "run", mock)
        command = ["launchctl", "print", f"user/{os.geteuid()}/com.mempalace.watch"]
        assert updater._default_runner(command) == (0, "", "")
        assert mock.call_args.kwargs["stdout"] == subprocess.DEVNULL

    def test_apply_refuses_unavailable_domain_evidence(self, tmp_path, monkeypatch):
        label = DEFAULT_LAUNCHD_WATCH_LABEL
        manager, commands, home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[label], domains={label: ("user",)}
        )
        _write_agent_plist(home, label)
        service = manager.service
        assert isinstance(service, LaunchdUserService)
        original = service.runner

        def denied(command):
            if command == ["launchctl", "print", f"gui/{os.geteuid()}/{label}"]:
                return 13, "", "permission denied"
            return original(command)

        service.runner = denied
        result = manager.apply()
        assert not result.ok
        assert result.stage == "preflight"
        assert "cannot verify launchd domain" in result.message
        assert not any(c[:2] == ["launchctl", "bootout"] for c in commands)
        assert not any("install" in c for c in commands)

    def test_apply_keeps_each_watcher_in_its_own_domain(self, tmp_path, monkeypatch):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.background"]
        manager, commands, home = _launchd_manager(
            tmp_path,
            monkeypatch,
            active_labels=labels,
            domains={labels[0]: ("gui",), labels[1]: ("user",)},
        )
        agents = {label: _write_agent_plist(home, label) for label in labels}
        assert manager.apply().ok
        for kind, label in zip(("gui", "user"), labels):
            domain = f"{kind}/{os.geteuid()}"
            assert ["launchctl", "bootout", f"{domain}/{label}"] in commands
            assert ["launchctl", "bootstrap", domain, str(agents[label])] in commands

    def test_status_selects_every_active_watcher(self, tmp_path, monkeypatch):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.srv-dev"]
        manager, commands, home = _launchd_manager(tmp_path, monkeypatch, active_labels=labels)
        for label in labels:
            _write_agent_plist(home, label)

        result = manager.status()

        watcher = result.data["watcher"]
        assert watcher["unit"] == ", ".join(labels)  # type: ignore[index]  # reason: stable status mapping
        assert watcher["active"] is True  # type: ignore[index]  # reason: stable status mapping
        assert watcher["safe"] is True  # type: ignore[index]  # reason: stable status mapping
        assert "selected active MemPalace LaunchAgents" in watcher["detail"]  # type: ignore[operator]  # reason: stable status mapping
        assert result.data["eligible"] is True
        assert manager.service.labels == tuple(labels)  # type: ignore[union-attr]  # reason: adapter is the concrete launchd service
        assert all(command[0] != "systemctl" for command in commands)

    def test_apply_stops_and_restarts_every_active_watcher(self, tmp_path, monkeypatch):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.srv-dev"]
        manager, commands, home = _launchd_manager(tmp_path, monkeypatch, active_labels=labels)
        agents = {label: _write_agent_plist(home, label) for label in labels}

        result = manager.apply()

        assert result.ok is True
        assert result.stage == "succeeded"
        for label in labels:
            assert ["launchctl", "bootout", _domain(label)] in commands
            assert ["launchctl", "bootstrap", f"gui/{os.geteuid()}", str(agents[label])] in (
                commands
            )
        assert all(command[0] != "systemctl" for command in commands)
        state = json.loads(manager.state_path.read_text(encoding="utf-8"))
        assert state["stage"] == "succeeded"
        assert state["watcher_unit"] == ", ".join(labels)
        assert state["watcher_was_active"] is True

    @pytest.mark.parametrize(
        ("label", "plist_kwargs", "list_rc", "expected_detail"),
        [
            (
                DEFAULT_LAUNCHD_WATCH_LABEL,
                {"plist_label": "com.example.other"},
                0,
                "label does not match the active label",
            ),
            ("com.mempalace.watch.srv-dev", None, 0, "no owned LaunchAgent plist"),
            (
                "com.mempalace.watch.srv-dev",
                {"symlink": True},
                0,
                "not a regular file",
            ),
            (
                "com.mempalace.watch.srv-dev",
                {"program_arguments": ["/usr/bin/other-watch", "/srv/dev"]},
                0,
                "not a MemPalace watch command",
            ),
            (
                "com.mempalace.watch.srv-dev",
                {"program_arguments": ["/bin/sh", "-c", "mempalace-code watch 'unterminated"]},
                0,
                "ProgramArguments is malformed",
            ),
            ("com.mempalace.watch..bad", {}, 0, "malformed launchd label"),
            (DEFAULT_LAUNCHD_WATCH_LABEL, {}, 1, "discovery unavailable"),
        ],
    )
    def test_apply_refuses_unsafe_state_before_package_install(
        self, tmp_path, monkeypatch, label, plist_kwargs, list_rc, expected_detail
    ):
        manager, commands, home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[label], list_rc=list_rc
        )
        if plist_kwargs is not None:
            _write_agent_plist(home, label, **plist_kwargs)

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "preflight"
        assert expected_detail in result.message
        assert RECOVERY_HINT in result.message
        assert not any(command[:2] == ["launchctl", "bootout"] for command in commands)
        assert not any("install" in command for command in commands)
        assert not manager.state_path.exists()

    def test_apply_restores_already_stopped_watchers_when_a_later_stop_fails(
        self, tmp_path, monkeypatch
    ):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.srv-dev"]
        manager, commands, home = _launchd_manager(
            tmp_path,
            monkeypatch,
            active_labels=labels,
            bootout_rc={"com.mempalace.watch.srv-dev": 1},
        )
        agents = {label: _write_agent_plist(home, label) for label in labels}

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "watcher-stop"
        assert "could not stop com.mempalace.watch.srv-dev" in result.message
        # The first agent was already booted out, so the failed stop compensates it back.
        assert ["launchctl", "bootout", _domain(DEFAULT_LAUNCHD_WATCH_LABEL)] in commands
        assert [
            "launchctl",
            "bootstrap",
            f"gui/{os.geteuid()}",
            str(agents[DEFAULT_LAUNCHD_WATCH_LABEL]),
        ] in commands
        assert not any("install" in command for command in commands)
        assert not manager.state_path.exists()

    def test_stop_leaves_only_unrestored_watchers_pending_for_a_later_start(
        self, tmp_path, monkeypatch
    ):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.srv-dev"]
        bootstrap_rc = {DEFAULT_LAUNCHD_WATCH_LABEL: 1}
        manager, commands, home = _launchd_manager(
            tmp_path,
            monkeypatch,
            active_labels=labels,
            bootout_rc={"com.mempalace.watch.srv-dev": 1},
            bootstrap_rc=bootstrap_rc,
        )
        agents = {label: _write_agent_plist(home, label) for label in labels}
        service = manager.service

        stopped, _detail = service.stop()

        assert stopped is False
        # Both dispatched attempts remain pending until caller-owned drain and start.
        assert service.attempted_stops == tuple(labels)

        # Compensation is explicit and runs after the fixture's old actors have exited.
        started, detail = service.start()
        assert not started
        assert service.attempted_stops == (DEFAULT_LAUNCHD_WATCH_LABEL,)
        bootstrap_rc.clear()
        commands.clear()
        started, detail = service.start()

        assert (started, detail) == (True, "")
        assert commands == [
            [
                "launchctl",
                "bootstrap",
                f"gui/{os.geteuid()}",
                str(agents[DEFAULT_LAUNCHD_WATCH_LABEL]),
            ]
        ]
        assert service._stopped == ()  # type: ignore[union-attr]  # reason: adapter is the concrete launchd service

    def test_start_retries_only_the_labels_that_are_still_stopped(self, tmp_path, monkeypatch):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.srv-dev"]
        bootstrap_rc = {"com.mempalace.watch.srv-dev": 1}
        manager, commands, home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=labels, bootstrap_rc=bootstrap_rc
        )
        agents = {label: _write_agent_plist(home, label) for label in labels}
        service = manager.service
        assert service.stop() == (True, "")
        commands.clear()

        started, detail = service.start()

        assert started is False
        assert "could not start com.mempalace.watch.srv-dev" in detail
        assert RECOVERY_HINT in detail

        bootstrap_rc.clear()
        commands.clear()
        retried, retry_detail = service.start()

        assert (retried, retry_detail) == (True, "")
        # A succeeded on the first start, so the retry never bootstraps it again.
        assert commands == [
            [
                "launchctl",
                "bootstrap",
                f"gui/{os.geteuid()}",
                str(agents["com.mempalace.watch.srv-dev"]),
            ]
        ]

    def test_apply_refuses_loaded_watchers_listed_without_a_pid(self, tmp_path, monkeypatch):
        # `launchctl list` prints "-" for a loaded job that is not currently running;
        # KeepAlive can respawn it mid-replacement, so it must still be coordinated.
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.srv-dev"]
        manager, commands, home = _launchd_manager(
            tmp_path,
            monkeypatch,
            active_labels=labels,
            pids={DEFAULT_LAUNCHD_WATCH_LABEL: "-"},
        )
        for label in labels:
            _write_agent_plist(home, label)

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "watcher-stop"
        assert "PID" in result.message
        assert RECOVERY_HINT in result.message
        assert not any(command[:2] == ["launchctl", "bootout"] for command in commands)
        assert not any("install" in command for command in commands)

    def test_stop_waits_until_launchd_drops_the_selected_label(self, monkeypatch):
        label = DEFAULT_LAUNCHD_WATCH_LABEL
        service = LaunchdUserService(lambda _command: (0, "", ""))
        service.labels = (label,)
        service._domains[label] = f"gui/{os.geteuid()}"
        service._discovery = WatcherDiscovery(label, True, True, "selected")
        states = iter([([label], None), ([label], None), ([], None)])
        monkeypatch.setattr(service, "_active_watch_labels", lambda: next(states))
        sleeps: list[float] = []
        monkeypatch.setattr(updater.time, "sleep", sleeps.append)

        stopped, detail = service.stop()

        assert (stopped, detail) == (True, "")
        assert sleeps == [0.1, 0.1]

    def test_stop_defers_restoration_when_launchd_never_settles(self, monkeypatch):
        label = DEFAULT_LAUNCHD_WATCH_LABEL
        commands: list[list[str]] = []
        service = LaunchdUserService(lambda command: commands.append(command) or (0, "", ""))
        service.labels = (label,)
        service._domains[label] = f"gui/{os.geteuid()}"
        service._discovery = WatcherDiscovery(label, True, True, "selected")
        monkeypatch.setattr(service, "_active_watch_labels", lambda: ([label], None))
        monkeypatch.setattr(service, "_plist_path", lambda _label: (Path("/owned.plist"), ""))
        monkeypatch.setattr(updater.time, "sleep", lambda _delay: None)

        stopped, detail = service.stop()

        assert stopped is False
        assert "remained loaded after bootout" in detail
        assert commands == [["launchctl", "bootout", _domain(label)]]
        assert service._stopped == (label,)
        assert service.start() == (True, "")
        assert commands[-1] == ["launchctl", "bootstrap", f"gui/{os.geteuid()}", "/owned.plist"]

    def test_start_accepts_an_exact_selected_label_that_is_already_active(self, monkeypatch):
        label = DEFAULT_LAUNCHD_WATCH_LABEL
        service = LaunchdUserService(lambda _command: (5, "", "already loaded"))
        service.labels = (label,)
        service._domains[label] = f"gui/{os.geteuid()}"
        service._stopped = (label,)
        service._discovery = WatcherDiscovery(label, True, True, "selected")
        monkeypatch.setattr(service, "_plist_path", lambda _label: (Path("/owned.plist"), ""))
        monkeypatch.setattr(service, "_active_watch_labels", lambda: ([label], None))

        started, detail = service.start()

        assert (started, detail) == (True, "")
        assert service._stopped == ()

    def test_status_accepts_the_canonical_cli_alias_watch_command(self, tmp_path, monkeypatch):
        manager, _commands, home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[DEFAULT_LAUNCHD_WATCH_LABEL]
        )
        _write_agent_plist(
            home,
            DEFAULT_LAUNCHD_WATCH_LABEL,
            program_arguments=["/bin/sh", "-c", "/usr/local/bin/mempalace watch /srv/dev"],
        )

        result = manager.status()

        watcher = result.data["watcher"]
        assert watcher["safe"] is True  # type: ignore[index]  # reason: stable status mapping
        assert watcher["active"] is True  # type: ignore[index]  # reason: stable status mapping
        assert result.data["eligible"] is True

    def test_apply_refuses_when_home_is_not_the_effective_uid_passwd_home(
        self, tmp_path, monkeypatch
    ):
        foreign_home = tmp_path / "foreign-home"
        foreign_home.mkdir()
        manager, commands, home = _launchd_manager(
            tmp_path,
            monkeypatch,
            active_labels=[DEFAULT_LAUNCHD_WATCH_LABEL],
            passwd_home=foreign_home,
        )
        _write_agent_plist(home, DEFAULT_LAUNCHD_WATCH_LABEL)

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "preflight"
        assert "HOME does not match the effective uid passwd directory" in result.message
        assert RECOVERY_HINT in result.message
        assert commands == []
        assert not manager.state_path.exists()

    @pytest.mark.parametrize("method", ["install_scheduler", "remove_scheduler"])
    def test_scheduler_mutations_never_call_launchctl(self, tmp_path, monkeypatch, method):
        manager, commands, _home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[DEFAULT_LAUNCHD_WATCH_LABEL]
        )

        result = getattr(manager, method)()

        assert result.ok is False
        assert result.stage == "unsupported-platform"
        assert result.data["service_manager"] == "systemd-user"
        assert commands == []


class TestSystemdWatcherDiscovery:
    def test_status_selects_unique_named_module_watcher_without_mutation(self, tmp_path):
        unit = "mempalace-watch-srv-dev.service"
        manager, commands = _systemd_manager(
            tmp_path,
            active_units=[unit],
            exec_starts={unit: "/opt/mempalace/bin/python -m mempalace_code watch /srv/dev"},
        )

        result = manager.status()

        watcher = result.data["watcher"]
        assert watcher["unit"] == unit  # type: ignore[index]  # reason: result data is stable JSON-like test data
        assert watcher["active"] is True  # type: ignore[index]  # reason: result data is stable JSON-like test data
        assert watcher["safe"] is True  # type: ignore[index]  # reason: result data is stable JSON-like test data
        assert "selected active named watcher" in watcher["detail"]  # type: ignore[operator]  # reason: result data is stable JSON-like test data
        assert ["systemctl", "--user", "stop", unit] not in commands
        assert ["systemctl", "--user", "start", unit] not in commands
        assert not any("install" in command for command in commands)

    def test_status_retains_active_legacy_console_script_watcher(self, tmp_path):
        manager, _ = _systemd_manager(
            tmp_path,
            active_units=[DEFAULT_WATCHER_UNIT],
            exec_starts={DEFAULT_WATCHER_UNIT: "/usr/local/bin/mempalace-code watch /srv/dev"},
        )

        result = manager.status()

        watcher = result.data["watcher"]
        assert watcher["unit"] == DEFAULT_WATCHER_UNIT  # type: ignore[index]  # reason: result data is stable JSON-like test data
        assert watcher["active"] is True  # type: ignore[index]  # reason: result data is stable JSON-like test data
        assert "selected active legacy watcher" in watcher["detail"]  # type: ignore[operator]  # reason: result data is stable JSON-like test data

    @pytest.mark.parametrize(
        ("active_units", "exec_starts", "list_rc", "expected_detail"),
        [
            (
                ["mempalace-watch-one.service", "mempalace-watch-two.service"],
                {
                    "mempalace-watch-one.service": "mempalace-code watch /one",
                    "mempalace-watch-two.service": "mempalace-code watch /two",
                },
                0,
                "ambiguous",
            ),
            (["mempalace-watch-.service"], {}, 0, "malformed"),
            (
                ["mempalace-watch-srv-dev.service"],
                {"mempalace-watch-srv-dev.service": "/usr/bin/other-watch /srv/dev"},
                0,
                "not a MemPalace watch command",
            ),
            (
                ["mempalace-watch-srv-dev.service"],
                {
                    "mempalace-watch-srv-dev.service": "other-binary -m mempalace_code watch /srv/dev"
                },
                0,
                "not a MemPalace watch command",
            ),
            ([], {}, 1, "discovery unavailable"),
        ],
    )
    def test_apply_refuses_unsafe_discovery_before_mutation(
        self, tmp_path, active_units, exec_starts, list_rc, expected_detail
    ):
        manager, commands = _systemd_manager(
            tmp_path,
            active_units=active_units,
            exec_starts=exec_starts,
            list_rc=list_rc,
        )

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "preflight"
        assert expected_detail in result.message
        assert not any(command[:3] == ["systemctl", "--user", "stop"] for command in commands)
        assert not any(command[:3] == ["systemctl", "--user", "start"] for command in commands)
        assert not any("install" in command for command in commands)
        assert not manager.state_path.exists()

    def test_apply_coordinates_the_selected_named_watcher(self, tmp_path):
        unit = "mempalace-watch-srv-dev.service"
        manager, commands = _systemd_manager(
            tmp_path,
            active_units=[unit],
            exec_starts={unit: "mempalace-code watch /srv/dev"},
        )

        result = manager.apply()

        assert result.ok is True
        assert ["systemctl", "--user", "stop", unit] in commands
        assert ["systemctl", "--user", "start", unit] in commands
        assert ["systemctl", "--user", "stop", DEFAULT_WATCHER_UNIT] not in commands
        assert ["systemctl", "--user", "start", DEFAULT_WATCHER_UNIT] not in commands
        state = json.loads(manager.state_path.read_text(encoding="utf-8"))
        assert state["watcher_unit"] == unit

    def test_rollback_restarts_the_selected_named_watcher(self, tmp_path):
        unit = "mempalace-watch-srv-dev.service"
        manager, commands = _systemd_manager(
            tmp_path,
            active_units=[unit],
            exec_starts={unit: "mempalace-code watch /srv/dev"},
            palace_validator=lambda _path: (False, "fragment probe failed"),
        )

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "palace-health"
        assert ["systemctl", "--user", "stop", unit] in commands
        assert ["systemctl", "--user", "start", unit] in commands
        assert ["systemctl", "--user", "start", DEFAULT_WATCHER_UNIT] not in commands


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
        assert f"mempalace-code[spellcheck,watch]=={ELIGIBLE_VERSION}" in install
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
        assert install_commands[0][-1].endswith(f"=={ELIGIBLE_VERSION}")
        assert install_commands[1][-1].endswith(f"=={CURRENT_VERSION}")
        state = (tmp_path / "state" / "updates" / "state.json").read_text(encoding="utf-8")
        assert '"stage": "rollback-succeeded"' in state
        assert service.active is True

    def test_installer_timeout_rolls_back_and_restores_watcher(self, tmp_path):
        service = FakeService(active=True)
        manager, commands = _manager(tmp_path, service=service)

        def timeout_runner(command: list[str]):
            commands.append(command)
            if "install" in command and command[-1].endswith(f"=={ELIGIBLE_VERSION}"):
                raise subprocess.TimeoutExpired(command, timeout=900)
            return 0, "ok", ""

        manager.runner = timeout_runner

        result = manager.apply()

        assert result.ok is False
        assert result.stage == "installer"
        assert "timed out" in result.message
        install_commands = [command for command in commands if "install" in command]
        assert [command[-1] for command in install_commands] == [
            f"mempalace-code[spellcheck,watch]=={ELIGIBLE_VERSION}",
            f"mempalace-code[spellcheck,watch]=={CURRENT_VERSION}",
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
        assert install_commands[1][-1].endswith(f"=={CURRENT_VERSION}")
        assert service.calls == ["is-active", "stop", "start", "is-active"]
        state = json.loads(manager.state_path.read_text(encoding="utf-8"))
        assert state["stage"] == "rollback-succeeded"


class TestScheduling:
    def test_scheduler_remove_disables_and_removes_owned_units(self, tmp_path):
        commands: list[list[str]] = []
        home = tmp_path / "home"
        unit_dir = home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        manager, _ = _manager(tmp_path)
        for name, content in manager.render_scheduler_units().items():
            (unit_dir / name).write_text(content, encoding="utf-8")
        manager.runner = lambda command: (commands.append(command), (0, "ok", ""))[1]

        with patch.object(Path, "home", return_value=home):
            result = manager.remove_scheduler()

        assert result.ok is True
        assert result.stage == "scheduler-removed"
        assert commands == [
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT],
            ["systemctl", "--user", "stop", DEFAULT_SERVICE_UNIT],
            ["systemctl", "--user", "daemon-reload"],
        ]
        assert not (unit_dir / DEFAULT_TIMER_UNIT).exists()
        assert not (unit_dir / DEFAULT_SERVICE_UNIT).exists()

    def test_scheduler_remove_preserves_units_when_disable_fails(self, tmp_path):
        home = tmp_path / "home"
        unit_dir = home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        timer = unit_dir / DEFAULT_TIMER_UNIT
        manager, _ = _manager(tmp_path)
        for name, content in manager.render_scheduler_units().items():
            (unit_dir / name).write_text(content, encoding="utf-8")
        manager.runner = lambda command: (1, "", "disable failed")

        with patch.object(Path, "home", return_value=home):
            result = manager.remove_scheduler()

        assert result.ok is False
        assert result.stage == "scheduler-remove"
        assert result.message == "disable failed"
        assert (
            timer.read_text(encoding="utf-8")
            == manager.render_scheduler_units()[DEFAULT_TIMER_UNIT]
        )

    @pytest.mark.parametrize(
        "case",
        [
            "partial",
            "symlink",
            "non-regular",
            "foreign-owner",
            "content-mismatch",
            "identity-mismatch",
            "path-escape",
        ],
    )
    def test_scheduler_unit_ownership_matrix_refuses_before_mutation(
        self, tmp_path, monkeypatch, case
    ):
        home = tmp_path / "home"
        unit_dir = home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        manager, commands = _manager(tmp_path)
        manager.scheduler_context = lambda: (unit_dir, None)
        rendered = manager.render_scheduler_units()
        for name, content in rendered.items():
            (unit_dir / name).write_text(content, encoding="utf-8")

        if case == "partial":
            (unit_dir / DEFAULT_TIMER_UNIT).unlink()
        elif case == "symlink":
            service = unit_dir / DEFAULT_SERVICE_UNIT
            service.unlink()
            service.symlink_to(unit_dir / DEFAULT_TIMER_UNIT)
        elif case == "non-regular":
            service = unit_dir / DEFAULT_SERVICE_UNIT
            service.unlink()
            service.mkdir()
        elif case == "foreign-owner":
            actual_uid = os.geteuid()
            monkeypatch.setattr(updater.os, "geteuid", lambda: actual_uid + 1)
        elif case == "content-mismatch":
            (unit_dir / DEFAULT_SERVICE_UNIT).write_text("foreign\n", encoding="utf-8")
        elif case == "identity-mismatch":
            manager.scheduler_context = lambda: (
                unit_dir,
                "XDG runtime and bus do not match the effective uid",
            )
        elif case == "path-escape":
            manager.scheduler_context = lambda: (
                unit_dir,
                "scheduler unit directory escapes HOME",
            )

        before = tuple(
            (path.name, path.is_symlink(), path.read_bytes() if path.is_file() else b"")
            for path in unit_dir.iterdir()
        )
        result = manager.install_scheduler()

        assert result.ok is False
        assert result.stage == "scheduler-preflight"
        assert result.exit_code == 2
        assert commands == []
        after = tuple(
            (path.name, path.is_symlink(), path.read_bytes() if path.is_file() else b"")
            for path in unit_dir.iterdir()
        )
        assert after == before

    def test_scheduler_matching_owned_pair_is_idempotent(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        unit_dir = home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        manager, commands = _manager(tmp_path)
        manager.scheduler_context = lambda: (unit_dir, None)
        rendered = manager.render_scheduler_units()
        for name, content in rendered.items():
            (unit_dir / name).write_text(content, encoding="utf-8")
        before = {name: (unit_dir / name).read_bytes() for name in rendered}
        monkeypatch.setattr(
            manager,
            "_atomic_write_text",
            lambda *_args: pytest.fail("matching scheduler units must not be rewritten"),
        )

        with patch.object(Path, "home", return_value=home):
            first = manager.install_scheduler()
            second = manager.install_scheduler()
            removed = manager.remove_scheduler()

        assert first.ok is True
        assert second.ok is True
        assert removed.ok is True
        assert commands == [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", DEFAULT_TIMER_UNIT],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", DEFAULT_TIMER_UNIT],
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT],
            ["systemctl", "--user", "stop", DEFAULT_SERVICE_UNIT],
            ["systemctl", "--user", "daemon-reload"],
        ]
        assert before
        assert not any((unit_dir / name).exists() for name in rendered)

    def test_scheduler_install_rolls_back_partial_pair(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        unit_dir = home / ".config" / "systemd" / "user"
        manager, commands = _manager(tmp_path)
        manager.scheduler_context = lambda: (unit_dir, None)
        atomic_write = manager._atomic_write_text
        writes = 0

        def fail_second_write(path, content):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("injected second-unit failure")
            atomic_write(path, content)

        monkeypatch.setattr(manager, "_atomic_write_text", fail_second_write)

        result = manager.install_scheduler()

        assert result.ok is False
        assert result.stage == "scheduler-install"
        assert "injected second-unit failure" in result.message
        assert not any((unit_dir / name).exists() for name in manager.render_scheduler_units())
        assert commands == [
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT],
            ["systemctl", "--user", "daemon-reload"],
        ]

    def test_scheduler_remove_stops_service_before_deleting_units(self, tmp_path):
        unit_dir = tmp_path / "home" / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        commands: list[list[str]] = []

        def runner(command):
            commands.append(command)
            if command[:3] == ["systemctl", "--user", "stop"]:
                return 1, "", "service still running"
            return 0, "ok", ""

        manager, _ = _manager(tmp_path)
        manager.runner = runner
        manager.scheduler_context = lambda: (unit_dir, None)
        rendered = manager.render_scheduler_units()
        for name, content in rendered.items():
            (unit_dir / name).write_text(content, encoding="utf-8")

        result = manager.remove_scheduler()

        assert result.ok is False
        assert result.stage == "scheduler-remove"
        assert "service still running" in result.message
        assert commands == [
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT],
            ["systemctl", "--user", "stop", DEFAULT_SERVICE_UNIT],
        ]
        assert all((unit_dir / name).exists() for name in rendered)

    def test_scheduler_remove_restores_units_when_final_reload_fails(self, tmp_path):
        unit_dir = tmp_path / "home" / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        commands: list[list[str]] = []
        reloads = 0

        def runner(command):
            nonlocal reloads
            commands.append(command)
            if command == ["systemctl", "--user", "daemon-reload"]:
                reloads += 1
                if reloads == 1:
                    return 1, "", "injected reload failure"
            return 0, "ok", ""

        manager, _ = _manager(tmp_path)
        manager.runner = runner
        manager.scheduler_context = lambda: (unit_dir, None)
        rendered = manager.render_scheduler_units()
        for name, content in rendered.items():
            (unit_dir / name).write_text(content, encoding="utf-8")

        result = manager.remove_scheduler()

        assert result.ok is False
        assert result.stage == "scheduler-remove"
        assert result.message == "injected reload failure"
        assert commands == [
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT],
            ["systemctl", "--user", "stop", DEFAULT_SERVICE_UNIT],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", DEFAULT_TIMER_UNIT],
        ]
        assert {
            name: (unit_dir / name).read_text(encoding="utf-8") for name in rendered
        } == rendered

    def test_scheduler_context_refuses_home_mismatch_before_runtime_access(
        self, tmp_path, monkeypatch
    ):
        passwd_home = tmp_path / "passwd-home"
        configured_home = tmp_path / "configured-home"
        passwd_home.mkdir()
        configured_home.mkdir()
        uid = os.geteuid()
        monkeypatch.setattr(
            updater.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_dir=passwd_home)
        )

        with patch.dict(os.environ, {"HOME": str(configured_home)}, clear=True):
            unit_dir, error = UpdateManager._scheduler_context()

        assert unit_dir == passwd_home
        assert error == "HOME does not match the effective uid passwd directory"
        assert uid == os.geteuid()

    @pytest.mark.parametrize(
        "unsafe_character",
        [":", "\x00", "\n", "\r", "\t", "\x1f", "\x7f"],
        ids=["colon", "nul", "newline", "carriage-return", "tab", "unit-separator", "del"],
    )
    def test_scheduler_render_rejects_unsafe_absolute_manager_directory(
        self, tmp_path, unsafe_character
    ):
        installation = Installation(
            kind="uv-tool",
            python="/opt/mempalace/bin/python",
            cli_command=("/opt/mempalace/bin/python", "-m", "mempalace_code"),
            manager_command=(f"/opt/manager{unsafe_character}dir/uv",),
            extras=frozenset({"watch"}),
        )
        manager, _ = _manager(tmp_path, installation=installation, fetcher=_current_pypi)

        with pytest.raises(ValueError, match="colon or ASCII control character"):
            manager.render_scheduler_units()

    def test_scheduler_install_rejects_unsafe_manager_path_before_writes_or_systemctl(
        self, tmp_path
    ):
        commands: list[list[str]] = []
        installation = Installation(
            kind="pipx",
            python="/opt/mempalace/bin/python",
            cli_command=("/opt/mempalace/bin/python", "-m", "mempalace_code"),
            manager_command=("/opt/unsafe:manager/pipx",),
            extras=frozenset({"watch"}),
        )
        manager = UpdateManager(
            state_root=tmp_path / "state",
            palace_path=str(tmp_path / "palace"),
            installation=installation,
            runner=lambda command: (commands.append(command), (0, "ok", ""))[1],
            service=FakeService(active=False),
        )

        with patch.object(Path, "home", return_value=tmp_path / "home"):
            result = manager.install_scheduler()

        assert isinstance(result, UpdateResult)
        assert result.ok is False
        assert result.stage == "scheduler-preflight"
        assert result.exit_code != 0
        assert "colon or ASCII control character" in result.message
        assert commands == []
        assert not (tmp_path / "home").exists()

    def test_scheduler_units_include_manager_path_for_uv_and_pipx_with_systemd_escaping(
        self, tmp_path, monkeypatch
    ):
        for name in ("PIPX_HOME", "PIPX_BIN_DIR", "UV_TOOL_DIR", "UV_TOOL_BIN_DIR"):
            monkeypatch.delenv(name, raising=False)
        inherited_path = "/interactive/bin:/from/shell"
        for kind, executable in (("uv-tool", "uv"), ("pipx", "pipx")):
            manager_dir = tmp_path / f'{executable} bin % "quoted" \\ slash'
            installation = Installation(
                kind=kind,
                python=str(tmp_path / kind / "bin" / "python"),
                cli_command=(str(tmp_path / kind / "bin" / "python"), "-m", "mempalace_code"),
                manager_command=(str(manager_dir / executable),),
                extras=frozenset({"watch"}),
            )
            manager = UpdateManager(
                state_root=tmp_path / kind / "state",
                palace_path=str(tmp_path / kind / "palace"),
                installation=installation,
                fetcher=_current_pypi,
                runner=lambda _command: (0, "ok", ""),
                lock=OperationLock(tmp_path / kind / "state" / "operation.lock"),
                service=FakeService(active=False),
                palace_validator=lambda _path: (True, "healthy"),
                backup_preflight=lambda: (True, "backup policy checked"),
                minimum_free_bytes=0,
            )

            with patch.dict(os.environ, {"PATH": inherited_path}):
                rendered = manager.render_scheduler_units()

            service = rendered[DEFAULT_SERVICE_UNIT]
            expected_path = ":".join([str(manager_dir), *SYSTEMD_BASELINE_PATH])
            escaped_path = (
                expected_path.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
            )
            assert service.split("\n") == [
                "[Unit]",
                "Description=MemPalace guarded automatic update",
                "",
                "[Service]",
                "Type=oneshot",
                f'Environment="PATH={escaped_path}"',
                'Environment="PIP_CONFIG_FILE=/dev/null"',
                'Environment="PIP_KEYRING_PROVIDER=disabled"',
                'Environment="PYTHONNOUSERSITE=1"',
                "UnsetEnvironment=" + " ".join(SCHEDULER_UNSET_ENVIRONMENT),
                "ExecStart="
                + " ".join(
                    shlex.quote(part)
                    for part in [
                        sys.executable,
                        "-m",
                        "mempalace_code",
                        "update",
                        "apply",
                        "--yes",
                        "--scheduled",
                    ]
                ),
                "",
            ]
            assert inherited_path not in service
            assert rendered[DEFAULT_TIMER_UNIT].split("\n")[-2] == "WantedBy=timers.target"

    def test_scheduled_up_to_date_returns_success_without_mutation(self, tmp_path):
        service = FakeService(active=True)

        def forbidden_runner(command: list[str]):
            raise AssertionError(f"unexpected command: {command}")

        def forbidden_backup() -> tuple[bool, str]:
            raise AssertionError("backup preflight must not run")

        def forbidden_validator(_path: str) -> tuple[bool, str]:
            raise AssertionError("palace validation must not run")

        manager = UpdateManager(
            state_root=tmp_path / "state",
            palace_path=str(tmp_path / "palace"),
            installation=_installation(),
            runner=forbidden_runner,
            fetcher=_current_pypi,
            lock=OperationLock(tmp_path / "state" / "operation.lock"),
            service=service,
            palace_validator=forbidden_validator,
            backup_preflight=forbidden_backup,
            minimum_free_bytes=0,
        )

        result = manager.apply(scheduled=True)

        assert result.ok is True
        assert result.stage == "up-to-date"
        assert result.exit_code == 0
        assert result.log_path is None
        assert result.data["current_version"] == CURRENT_VERSION
        assert result.data["target_version"] is None
        assert result.data["provenance"]["already_current"] is True  # type: ignore[index]  # reason: result data is stable JSON-like test data
        assert service.calls == []
        assert not manager.state_path.exists()
        assert not manager.updates_dir.exists()
        assert not Path(manager.palace_path).exists()
        assert not manager.lock.owners_path.exists()

    @pytest.mark.parametrize(
        ("field", "value", "expected_detail"),
        [
            ("filename", "", "filename"),
            ("filename", "unexpected.whl", "filename"),
            ("url", "", "HTTPS"),
            ("url", "http://files.pythonhosted.org/current.whl", "HTTPS"),
            ("digests", {"sha256": "d" * 63}, "sha256"),
            ("upload_time_iso_8601", "", "upload time"),
        ],
        ids=[
            "empty-filename",
            "unexpected-filename",
            "empty-url",
            "http-url",
            "sha256",
            "upload-time",
        ],
    )
    def test_scheduled_current_noop_rejects_incomplete_live_wheel_provenance(
        self, tmp_path, field, value, expected_detail
    ):
        data = _current_pypi()
        data["releases"][CURRENT_VERSION][0][field] = value

        class ForbiddenService(FakeService):
            unit = DEFAULT_WATCHER_UNIT

            def discover(self) -> WatcherDiscovery:
                raise AssertionError("watcher must not be queried")

            def is_active(self) -> tuple[bool, str]:
                raise AssertionError("watcher must not be queried")

            def stop(self) -> tuple[bool, str]:
                raise AssertionError("watcher must not be stopped")

            def start(self) -> tuple[bool, str]:
                raise AssertionError("watcher must not be started")

        manager = UpdateManager(
            state_root=tmp_path / "state",
            palace_path=str(tmp_path / "palace"),
            installation=_installation(),
            runner=lambda command: (_ for _ in ()).throw(
                AssertionError(f"unexpected command: {command}")
            ),
            fetcher=lambda: data,
            lock=OperationLock(tmp_path / "state" / "operation.lock"),
            service=ForbiddenService(),
            palace_validator=lambda _path: (_ for _ in ()).throw(
                AssertionError("palace validation must not run")
            ),
            backup_preflight=lambda: (_ for _ in ()).throw(
                AssertionError("backup preflight must not run")
            ),
            minimum_free_bytes=sys.maxsize,
        )

        result = manager.apply(scheduled=True)

        assert result.ok is False
        assert result.stage == "preflight"
        assert result.exit_code != 0
        assert expected_detail in result.message
        assert not manager.state_path.exists()
        assert not manager.updates_dir.exists()
        assert not Path(manager.palace_path).exists()
        assert not manager.lock.owners_path.exists()

    def test_cached_current_provenance_cannot_authorize_scheduled_noop(self, tmp_path):
        manager, _ = _manager(
            tmp_path,
            fetcher=lambda: (_ for _ in ()).throw(RuntimeError("network offline")),
            service=FakeService(active=False),
        )
        manager.state_path.parent.mkdir(parents=True)
        manager.state_path.write_text(
            json.dumps(
                {"provenance": {"already_current": True, "current_version": CURRENT_VERSION}}
            ),
            encoding="utf-8",
        )

        cached = manager._cached_provenance()
        result = manager.apply(scheduled=True)

        assert cached.already_current is False
        assert manager._scheduled_up_to_date(_installation(), cached) is False
        assert result.ok is False
        assert result.stage == "preflight"
        assert result.exit_code != 0
        assert "PyPI provenance unavailable" in result.message

    def test_scheduled_failures_remain_nonzero_except_exact_current_stable_noop(self, tmp_path):
        manual, _ = _manager(tmp_path / "manual", fetcher=_current_pypi)
        manual_result = manual.apply()
        assert manual_result.ok is False
        assert manual_result.stage == "preflight"
        assert manual_result.exit_code == 2
        assert "up-to-date" in manual_result.message

        network, _ = _manager(
            tmp_path / "network",
            fetcher=lambda: (_ for _ in ()).throw(RuntimeError("network offline")),
        )
        network_result = network.apply(scheduled=True)
        assert network_result.ok is False
        assert network_result.stage == "preflight"
        assert network_result.exit_code == 2
        assert "PyPI provenance unavailable" in network_result.message

        unsupported, _ = _manager(
            tmp_path / "unsupported",
            fetcher=_current_pypi,
            installation=Installation.unsupported("unsupported installer"),
        )
        unsupported_result = unsupported.apply(scheduled=True)
        assert unsupported_result.ok is False
        assert unsupported_result.stage == "preflight"
        assert unsupported_result.exit_code == 2
        assert "unsupported installer" in unsupported_result.message

        class UnsafeService(FakeService):
            def discover(self) -> WatcherDiscovery:
                return WatcherDiscovery(
                    unit=self.unit, active=True, safe=False, detail="unsafe watcher"
                )

        unsafe, _ = _manager(tmp_path / "unsafe", service=UnsafeService(), fetcher=_pypi)
        unsafe_result = unsafe.apply(scheduled=True)
        assert unsafe_result.ok is False
        assert unsafe_result.stage == "preflight"
        assert unsafe_result.exit_code == 2
        assert "unsafe watcher" in unsafe_result.message

        missing_extra, commands = _manager(
            tmp_path / "missing-extra",
            service=FakeService(active=True),
            fetcher=_pypi,
            extras=frozenset(),
        )
        missing_extra_result = missing_extra.apply(scheduled=True)
        assert missing_extra_result.ok is False
        assert missing_extra_result.stage == "preflight"
        assert missing_extra_result.exit_code == 2
        assert "required watch extra" in missing_extra_result.message
        assert not any("install" in command for command in commands)

        disk, _ = _manager(
            tmp_path / "disk",
            fetcher=_pypi,
            minimum_free_bytes=sys.maxsize,
        )
        disk_result = disk.apply(scheduled=True)
        assert disk_result.ok is False
        assert disk_result.stage == "preflight"
        assert disk_result.exit_code == 2
        assert "disk preflight failed" in disk_result.message

        backup, _ = _manager(
            tmp_path / "backup",
            fetcher=_pypi,
            backup_preflight=lambda: (False, "backup unavailable"),
        )
        backup_result = backup.apply(scheduled=True)
        assert backup_result.ok is False
        assert backup_result.stage == "preflight"
        assert backup_result.exit_code == 2
        assert "backup preflight failed: backup unavailable" in backup_result.message

        locked, locked_commands = _manager(tmp_path / "locked", fetcher=_pypi)
        with locked.lock.acquire_exclusive("scheduled-update"):
            locked_result = locked.apply(scheduled=True)
        assert locked_result.ok is False
        assert locked_result.stage == "lock"
        assert locked_result.exit_code == 3
        assert "already owns" in locked_result.message
        assert not any(
            command[:3] == ["systemctl", "--user", "stop"] for command in locked_commands
        )

    def test_generated_service_command_uses_minimal_systemd_environment_and_fails_closed(
        self, tmp_path
    ):
        tool_root = tmp_path / "uv-tools"
        prefix = tool_root / "mempalace-code"
        manager_dir = tmp_path / "managed-bin"
        manager_dir.mkdir()
        uv = manager_dir / "uv"
        uv.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        uv.chmod(0o700)
        installation = Installation(
            kind="uv-tool",
            python=str(prefix / "bin" / "python"),
            cli_command=(str(prefix / "bin" / "python"), "-m", "mempalace_code"),
            manager_command=(str(uv),),
            extras=frozenset({"watch"}),
        )
        rendered = UpdateManager(
            state_root=tmp_path / "render-state",
            palace_path=str(tmp_path / "render-palace"),
            installation=installation,
            runner=lambda _command: (0, "ok", ""),
            service=FakeService(active=False),
        ).render_scheduler_units()
        service_path = f"{manager_dir}:{':'.join(SYSTEMD_BASELINE_PATH)}"
        assert f'Environment="PATH={service_path}"' in rendered[DEFAULT_SERVICE_UNIT]

        def which_from_path(name: str, *, env_path: str = service_path) -> str | None:
            for entry in env_path.split(":"):
                candidate = Path(entry) / name
                if candidate.exists():
                    return str(candidate)
            return None

        minimal_env = {"PATH": service_path, "UV_TOOL_DIR": str(tool_root)}
        with patch("mempalace_code.updater._has_editable_metadata", return_value=False):
            manager = UpdateManager(
                state_root=tmp_path / "service-state",
                palace_path=str(tmp_path / "service-palace"),
                installation_detector=lambda: detect_installation(
                    python=str(prefix / "bin" / "python"),
                    prefix=prefix,
                    base_prefix=tmp_path / "system-python",
                    environ=minimal_env,
                    which=which_from_path,
                    extras=frozenset({"watch"}),
                ),
                runner=lambda _command: (0, "ok", ""),
                fetcher=_current_pypi,
                lock=OperationLock(tmp_path / "service-state" / "operation.lock"),
                service=FakeService(active=False),
                palace_validator=lambda _path: (True, "healthy"),
                backup_preflight=lambda: (True, "backup policy checked"),
                minimum_free_bytes=0,
            )
            result = manager.apply(scheduled=True)

        assert result.ok is True
        assert result.stage == "up-to-date"

        missing_env = {"PATH": ":".join(SYSTEMD_BASELINE_PATH), "UV_TOOL_DIR": str(tool_root)}
        with patch("mempalace_code.updater._has_editable_metadata", return_value=False):
            missing_manager = UpdateManager(
                state_root=tmp_path / "missing-state",
                palace_path=str(tmp_path / "missing-palace"),
                installation_detector=lambda: detect_installation(
                    python=str(prefix / "bin" / "python"),
                    prefix=prefix,
                    base_prefix=tmp_path / "system-python",
                    environ=missing_env,
                    which=lambda _name: None,
                    extras=frozenset({"watch"}),
                ),
                runner=lambda _command: (0, "ok", ""),
                fetcher=_current_pypi,
                lock=OperationLock(tmp_path / "missing-state" / "operation.lock"),
                service=FakeService(active=False),
                palace_validator=lambda _path: (True, "healthy"),
                backup_preflight=lambda: (True, "backup policy checked"),
                minimum_free_bytes=0,
            )
            missing_result = missing_manager.apply(scheduled=True)

        assert missing_result.ok is False
        assert missing_result.stage == "preflight"
        assert "uv executable is unavailable" in missing_result.message

        unexpected, _ = _manager(tmp_path / "unexpected-provenance", fetcher=_yanked_current_pypi)
        unexpected_result = unexpected.apply(scheduled=True)
        assert unexpected_result.ok is False
        assert unexpected_result.stage == "preflight"
        assert "not proven current" in unexpected_result.message

    def test_live_systemd_user_scheduled_current_noop_control_run(self, tmp_path):
        if os.environ.get("MEMPALACE_TEST_LIVE_SYSTEMD_USER") != "1":
            pytest.skip("live systemd-user smoke is opt-in")
        if sys.platform != "linux":
            pytest.skip("live systemd-user smoke requires Linux")

        show_environment = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if show_environment.returncode != 0:
            pytest.skip("systemd-user manager is unavailable")

        unit = f"mempalace-update-noop-smoke-{os.getpid()}"
        systemd_run = subprocess.run(
            [
                "systemd-run",
                "--user",
                "--wait",
                "--collect",
                f"--unit={unit}",
                f"--working-directory={Path.cwd()}",
                sys.executable,
                "-m",
                "pytest",
                "tests/test_updater.py::TestScheduling::"
                "test_scheduled_up_to_date_returns_success_without_mutation",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert systemd_run.returncode == 0, systemd_run.stdout + systemd_run.stderr

        manager, _ = _manager(tmp_path, fetcher=_current_pypi, service=FakeService(active=False))
        noop = manager.apply(scheduled=True)

        assert noop.ok is True
        assert noop.stage == "up-to-date"
        assert noop.exit_code == 0

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
                    **json.loads(manager.lock.owners_path.read_text()),
                    "stale": {
                        "mode": "exclusive",
                        "operation": "update",
                        "pid": 999999999,
                    },
                }
            ),
            encoding="utf-8",
        )

        result = manager.apply()

        assert result.ok is True
        assert result.stage == "succeeded"
        assert service.calls == ["is-active", "stop", "start", "is-active"]


class TestInstallerDetection:
    @pytest.mark.parametrize("home_kind", ["physical", "alias", "unrelated"])
    @pytest.mark.parametrize("manager_available", [True, False])
    def test_custom_pipx_home_uses_filesystem_identity(
        self, tmp_path, home_kind, manager_available
    ):
        home = tmp_path / "custom-tools"
        prefix = home / "venvs" / "mempalace-code"
        prefix.mkdir(parents=True)
        alias = tmp_path / "home-alias"
        alias.symlink_to(home, target_is_directory=True)
        homes = {"physical": home, "alias": alias, "unrelated": tmp_path / "other"}
        assert alias.samefile(home)
        with patch("mempalace_code.updater._has_editable_metadata", return_value=False):
            installation = detect_installation(
                python=str(prefix / "bin" / "python"),
                prefix=prefix,
                base_prefix=tmp_path / "system-python",
                environ={"PIPX_HOME": str(homes[home_kind])},
                which=lambda name: (
                    "/selected/pipx" if name == "pipx" and manager_available else None
                ),
                extras=frozenset(),
            )
        supported = home_kind != "unrelated" and manager_available
        assert installation.supported is supported
        assert installation.kind == ("pipx" if supported else "unsupported")
        if home_kind != "unrelated" and not manager_available:
            assert installation.reason == updater.UNSUPPORTED_PIPX_WITHOUT_PIPX

    @pytest.mark.parametrize(
        ("direct_url", "expected"),
        [
            ('{"archive_info": {"hash": "sha256=abc"}}', False),
            ('{"dir_info": {"editable": false}}', False),
            ('{"dir_info": {"editable": true}}', True),
            ('{"dir_info": {"editable": "true"}}', True),
            ('{"dir_info": "invalid"}', True),
            ('["not", "an", "object"]', True),
            ("not-json", True),
        ],
    )
    def test_editable_metadata_requires_explicit_boolean_and_fails_closed_on_malformed_shape(
        self, direct_url, expected
    ):
        dist = MagicMock()
        dist.read_text.return_value = direct_url
        with patch("mempalace_code.updater.metadata.distribution", return_value=dist):
            assert updater._has_editable_metadata() is expected

    def test_pipx_wheel_direct_url_without_dir_info_remains_supported(self, tmp_path):
        prefix = tmp_path / "pipx" / "venvs" / "mempalace-code"
        dist = MagicMock()
        dist.read_text.return_value = '{"archive_info": {"hash": "sha256=abc"}}'
        with patch("mempalace_code.updater.metadata.distribution", return_value=dist):
            installation = detect_installation(
                python=str(prefix / "bin" / "python"),
                prefix=prefix,
                base_prefix=tmp_path / "system-python",
                environ={"PIPX_HOME": str(tmp_path / "pipx")},
                which=lambda name: "/usr/bin/pipx" if name == "pipx" else None,
                extras=frozenset(),
            )

        assert installation.supported is True
        assert installation.kind == "pipx"

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
    @pytest.mark.parametrize(("active", "state"), [(True, "active"), (False, "inactive")])
    def test_status_renders_selected_watcher_unit_and_state_for_humans(self, capsys, active, state):
        manager = MagicMock()
        manager.status.return_value = UpdateResult(
            True,
            "status",
            "update status inspected without mutation",
            0,
            data={
                "installation": {},
                "provenance": {},
                "watcher": {
                    "unit": "mempalace-watch-srv-dev.service",
                    "active": active,
                    "detail": "selected active named watcher: mempalace-watch-srv-dev.service",
                },
                "scheduler": {},
            },
        )
        args = Namespace(update_command="status", palace=None, json=False)

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            cmd_update(args)

        assert f"Watcher (mempalace-watch-srv-dev.service, {state}):" in capsys.readouterr().out

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

    @pytest.mark.parametrize(
        ("update_command", "scheduler_command", "method", "action"),
        [
            ("apply", None, "apply", ("update", "apply")),
            ("scheduler", "install", "install_scheduler", ("update", "scheduler", "install")),
            ("scheduler", "remove", "remove_scheduler", ("update", "scheduler", "remove")),
        ],
    )
    @pytest.mark.parametrize("as_json", [False, True])
    def test_guarded_mutations_require_yes_without_invoking_updater(
        self, capsys, update_command, scheduler_command, method, action, as_json
    ):
        manager = MagicMock()
        args = Namespace(
            update_command=update_command,
            scheduler_command=scheduler_command,
            palace="/tmp/palace with spaces",
            yes=False,
            json=as_json,
            scheduled=False,
        )

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            with pytest.raises(SystemExit) as exc_info:
                cmd_update(args)

        assert exc_info.value.code == 2
        getattr(manager, method).assert_not_called()
        manager.apply.assert_not_called()
        manager.install_scheduler.assert_not_called()
        manager.remove_scheduler.assert_not_called()
        captured = capsys.readouterr()
        assert captured.err == ""
        expected_command = shlex.join(
            [
                "mempalace-code",
                "--palace",
                "/tmp/palace with spaces",
                *action,
                "--yes",
                *(["--json"] if as_json else []),
            ]
        )
        if as_json:
            payload = json.loads(captured.out)
            assert payload == {
                "exit_code": 2,
                "log_path": None,
                "message": (
                    "refused: package or systemd-user mutation requires explicit confirmation"
                ),
                "ok": False,
                "recovery_command": expected_command,
                "stage": "confirmation",
            }
        else:
            assert captured.out.splitlines() == [
                "  Update confirmation: refused: package or systemd-user mutation requires "
                "explicit confirmation",
                f"  Recovery: {expected_command}",
            ]


class TestUatUpdaterUx:
    """UAT install-19, install-20, update-1: actionable reasons in precedence order."""

    @staticmethod
    def _plain_venv() -> Installation:
        return Installation.unsupported(updater.UNSUPPORTED_AMBIGUOUS_VENV)

    def test_home_mismatch_recovery_names_the_account_home_not_status_itself(
        self, tmp_path, monkeypatch
    ):
        passwd_home = tmp_path / "account home"
        passwd_home.mkdir()
        manager, commands, _home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[], passwd_home=passwd_home
        )

        detail = manager.status().data["watcher"]["detail"]  # type: ignore[index]  # reason: stable status mapping

        assert "HOME does not match the effective uid passwd directory" in detail
        assert (
            f"recovery: rerun with HOME set to the account home: "
            f"HOME={shlex.quote(str(passwd_home))} mempalace-code update status --json"
        ) in detail
        assert commands == []

    def test_unsupported_installer_outranks_an_unsafe_watcher(self, tmp_path, monkeypatch):
        manager, _commands, _home = _launchd_manager(
            tmp_path, monkeypatch, active_labels=[], passwd_home=tmp_path / "elsewhere"
        )
        (tmp_path / "elsewhere").mkdir()
        manager._installation = self._plain_venv()
        monkeypatch.setattr(updater, "_recorded_installer", lambda: "pip")

        status = manager.status()
        applied = manager.apply()

        assert status.data["reason"] == updater.UNSUPPORTED_AMBIGUOUS_VENV
        assert status.data["manual_update_supported"] is False
        assert status.data["manual_upgrade_command"] == (
            f'"{sys.executable}" -m pip install --upgrade "mempalace-code=={ELIGIBLE_VERSION}"'
        )
        assert applied.stage == "preflight"
        assert applied.message.startswith(updater.UNSUPPORTED_AMBIGUOUS_VENV)
        assert "-m pip install --upgrade" in applied.message
        assert "watcher" not in applied.message

    def test_current_pip_install_gets_no_placeholder_upgrade_command(
        self, tmp_path, monkeypatch, capsys
    ):
        manager, _service = _manager(
            tmp_path, fetcher=_current_pypi, installation=self._plain_venv()
        )
        monkeypatch.setattr(updater, "_recorded_installer", lambda: "pip")

        status = manager.status()
        applied = manager.apply()

        assert "manual_upgrade_command" not in status.data
        note = status.data["manual_upgrade_note"]
        assert isinstance(note, str)
        assert note.startswith("no newer compatible release")
        assert "`mempalace-code version-check --check-now`" in note
        assert "X.Y.Z" not in applied.message
        assert note in applied.message
        args = Namespace(update_command="status", palace=None, json=False)
        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            cmd_update(args)
        out = capsys.readouterr().out
        assert "Upgrade this pip install with" not in out
        assert f"  Pip upgrade: {note}" in out

    def test_human_status_shows_the_installer_refusal_and_pip_path(self, capsys):
        manager = MagicMock()
        manager.status.return_value = UpdateResult(
            True,
            "status",
            "update status inspected without mutation",
            0,
            data={
                "installation": {
                    "kind": "unsupported",
                    "supported": False,
                    "reason": updater.UNSUPPORTED_AMBIGUOUS_VENV,
                },
                "provenance": {},
                "watcher": {},
                "scheduler": {},
                "manual_upgrade_command": '"/v/bin/python" -m pip install --upgrade x',
                "reason": updater.UNSUPPORTED_AMBIGUOUS_VENV,
            },
        )
        args = Namespace(update_command="status", palace=None, json=False)

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            cmd_update(args)

        out = capsys.readouterr().out
        assert f"  Installer refusal: {updater.UNSUPPORTED_AMBIGUOUS_VENV}" in out
        assert '  Upgrade this pip install with: "/v/bin/python" -m pip install --upgrade x' in out

    def test_check_has_its_own_stage(self, tmp_path):
        manager = UpdateManager(
            state_root=tmp_path / "state",
            installation=_installation(),
            runner=lambda command: (0, "", ""),
            fetcher=_pypi,
            service=FakeService(active=False),
            minimum_free_bytes=0,
        )

        checked = manager.check()

        assert checked.stage == "check"
        assert checked.message != manager.status().message
        assert checked.data["provenance"]["target_version"] == ELIGIBLE_VERSION  # type: ignore[index]  # reason: stable status mapping

    def test_units_differing_only_in_carried_locations_stay_owned(self, tmp_path, monkeypatch):
        pipx = Installation(
            kind="pipx",
            python="/pipx/venvs/mempalace-code/bin/python",
            cli_command=("/pipx/venvs/mempalace-code/bin/python", "-m", "mempalace_code"),
            manager_command=("/usr/bin/pipx",),
        )
        home = tmp_path / "home"
        unit_dir = home / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        manager, _commands = _manager(tmp_path, installation=pipx)
        monkeypatch.delenv("PIPX_HOME", raising=False)
        legacy = manager.render_scheduler_units()
        for name, content in legacy.items():
            (unit_dir / name).write_text(content, encoding="utf-8")
        monkeypatch.setenv("PIPX_HOME", str(tmp_path / "pipx"))
        service = unit_dir / DEFAULT_SERVICE_UNIT

        with patch.object(Path, "home", return_value=home):
            installed = manager.install_scheduler()
            assert installed.ok is True
            assert f'Environment="PIPX_HOME={tmp_path / "pipx"}"' in service.read_text()
            monkeypatch.delenv("PIPX_HOME")
            removed = manager.remove_scheduler()
            assert removed.ok is True
            assert not service.exists()

            for name, content in legacy.items():
                (unit_dir / name).write_text(content, encoding="utf-8")
            service.write_text(legacy[DEFAULT_SERVICE_UNIT] + "ExecStartPre=/bin/true\n")
            refused = manager.remove_scheduler()
        assert refused.ok is False
        assert "content does not match" in refused.message

    def test_scheduler_render_warns_and_carries_manager_locations(
        self, tmp_path, monkeypatch, capsys
    ):
        pipx = Installation(
            kind="pipx",
            python="/pipx/venvs/mempalace-code/bin/python",
            cli_command=("/pipx/venvs/mempalace-code/bin/python", "-m", "mempalace_code"),
            manager_command=("/usr/bin/pipx",),
        )
        monkeypatch.setenv("PIPX_HOME", str(tmp_path / "pipx"))
        monkeypatch.setenv("PIPX_BIN_DIR", str(tmp_path / "pipx-bin"))
        monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "uv-tools"))
        manager = UpdateManager(state_root=tmp_path / "state", installation=pipx)

        service = manager.render_scheduler_units()[DEFAULT_SERVICE_UNIT]

        assert f'Environment="PIPX_HOME={tmp_path / "pipx"}"' in service
        assert f'Environment="PIPX_BIN_DIR={tmp_path / "pipx-bin"}"' in service
        assert "UV_TOOL_DIR" not in service
        assert manager.scheduler_render_warning() is None

        unsupported = MagicMock()
        unsupported.render_scheduler_units.return_value = {"x.service": "[Unit]\n"}
        unsupported.scheduler_render_warning.return_value = "preview only; reason"
        args = Namespace(
            update_command="scheduler", scheduler_command="render", palace=None, json=False
        )
        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=unsupported):
            cmd_update(args)
        captured = capsys.readouterr()
        assert captured.err == "  Warning: preview only; reason\n"
        assert captured.out == "# x.service\n[Unit]\n"

        plain = UpdateManager(state_root=tmp_path / "state", installation=self._plain_venv())
        monkeypatch.setattr(updater.sys, "platform", "darwin")
        warning = plain.scheduler_render_warning()
        assert warning is not None
        assert updater.UNSUPPORTED_AMBIGUOUS_VENV in warning
        assert "current platform is darwin" in warning

    @pytest.mark.parametrize("scheduler_command", ["install", "remove"])
    def test_darwin_scheduler_mutation_reports_the_platform_not_a_yes_retry(
        self, capsys, monkeypatch, scheduler_command
    ):
        monkeypatch.setattr(updater.sys, "platform", "darwin")
        manager = MagicMock()
        args = Namespace(
            update_command="scheduler",
            scheduler_command=scheduler_command,
            palace=None,
            yes=False,
            json=False,
            scheduled=False,
        )

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            with pytest.raises(SystemExit) as exc_info:
                cmd_update(args)

        assert exc_info.value.code == 2
        out = capsys.readouterr().out
        assert "Update unsupported-platform: scheduled update mutations require Linux" in out
        assert "--yes" not in out
        manager.install_scheduler.assert_not_called()
        manager.remove_scheduler.assert_not_called()

    def test_darwin_apply_confirmation_names_launchd(self, capsys, monkeypatch):
        monkeypatch.setattr(updater.sys, "platform", "darwin")
        args = Namespace(update_command="apply", palace=None, yes=False, json=False)

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=MagicMock()):
            with pytest.raises(SystemExit):
                cmd_update(args)

        assert "package or launchd-user mutation requires explicit confirmation" in (
            capsys.readouterr().out
        )

    def test_recovery_names_the_invoked_launcher_when_path_does_not_find_it(
        self, tmp_path, capsys, monkeypatch
    ):
        launcher = tmp_path / "venvs" / "plain" / "bin" / "mempalace-code"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("#!/bin/sh\n", encoding="utf-8")
        launcher.chmod(0o755)
        monkeypatch.setattr(sys, "argv", [str(launcher), "update", "apply"])
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        args = Namespace(update_command="apply", palace=None, yes=False, json=False)

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=MagicMock()):
            with pytest.raises(SystemExit):
                cmd_update(args)

        assert f"  Recovery: {launcher.resolve()} update apply --yes" in capsys.readouterr().out

    def test_human_scheduler_status_shows_its_state(self, capsys, monkeypatch):
        monkeypatch.setattr(updater.sys, "platform", "darwin")
        manager = MagicMock()
        manager.scheduler_status.return_value = {
            "supported": False,
            "enabled": False,
            "detail": "scheduled update mutations require Linux systemd-user",
            "next_run": None,
        }
        args = Namespace(
            update_command="scheduler", scheduler_command="status", palace=None, json=False
        )

        with patch("mempalace_code.cli_commands.update.UpdateManager", return_value=manager):
            cmd_update(args)

        out = capsys.readouterr().out
        assert "  Scheduler supported: False" in out
        assert "  Scheduler enabled: False" in out
        assert "  Detail: scheduled update mutations require Linux systemd-user" in out
        assert "  Next run: not scheduled" in out


class TestWriterDrain:
    @staticmethod
    def prepared(tmp_path, monkeypatch):
        monkeypatch.setattr(updater.Path, "home", lambda: tmp_path)
        manager, commands = _manager(tmp_path)
        assert isinstance(manager.service, FakeService)
        service = manager.service
        _prepare_fake(manager, service)
        service.prepare_capture = lambda: None
        return manager, service, commands

    @staticmethod
    def assert_fenced(manager):
        for lock in (manager.lock, OperationLock.for_palace(manager.palace_path)):
            with pytest.raises(updater.OperationLockedError):
                lock.acquire_exclusive("independent writer")
        with sqlite3.connect(
            Path(manager.palace_path) / "knowledge_graph.sqlite3", timeout=0
        ) as db:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                db.execute("BEGIN IMMEDIATE")

    @staticmethod
    def assert_drain_released(manager):
        with OperationLock.for_palace(manager.palace_path).acquire_exclusive("independent writer"):
            pass
        with closing(
            sqlite3.connect(Path(manager.palace_path) / "knowledge_graph.sqlite3", timeout=0)
        ) as db:
            db.execute("BEGIN IMMEDIATE")
            db.rollback()

    @staticmethod
    def assert_released(manager):
        with manager.lock.acquire_exclusive("independent writer"):
            pass
        TestWriterDrain.assert_drain_released(manager)

    @pytest.mark.parametrize("kind", ["palace", "sqlite"])
    def test_busy_native_writer_refuses_before_stop(self, tmp_path, monkeypatch, kind):
        manager, service, commands = self.prepared(tmp_path, monkeypatch)
        with ExitStack() as stack:
            if kind == "palace":
                stack.enter_context(
                    OperationLock.for_palace(manager.palace_path).acquire_exclusive("writer")
                )
            else:
                db = sqlite3.connect(Path(manager.palace_path) / "knowledge_graph.sqlite3")
                stack.callback(db.close)
                db.execute("BEGIN IMMEDIATE")
            result = manager.apply()
        assert not result.ok
        assert result.stage == "watcher-stop"
        assert "recovery:" in result.message
        assert "stop" not in service.calls
        assert not any("install" in command for command in commands)

    @pytest.mark.parametrize(
        "kind",
        [
            "missing",
            "malformed",
            "empty",
            "incomplete",
            "foreign",
            "palace-less",
            "stale-birth",
            "contradictory",
            "duplicate-key",
        ],
    )
    def test_unknown_owner_refuses_before_stop(self, tmp_path, monkeypatch, kind):
        manager, service, commands = self.prepared(tmp_path, monkeypatch)
        path = manager.lock.owners_path
        owners = json.loads(path.read_text())
        record = owners[service.unit]
        if kind == "missing":
            path.unlink()
        elif kind == "malformed":
            path.write_text("{broken")
        elif kind == "empty":
            path.write_text("{}")
        elif kind == "duplicate-key":
            path.write_text('{"same": {}, "same": {}}')
        else:
            if kind == "incomplete":
                record["pid"] = 91002
            elif kind == "foreign":
                foreign = tmp_path / "foreign"
                foreign.mkdir()
                record["palace"] = str(foreign)
            elif kind == "palace-less":
                record.pop("palace")
            elif kind == "stale-birth":
                record["acquired_at"] = 0
            elif kind == "contradictory":
                owners["conflict"] = {**record, "operation": "mine"}
            path.write_text(json.dumps(owners))
        result = manager.apply()
        assert not result.ok
        assert "stop" not in service.calls
        assert not commands
        assert "recovery:" in result.message

    def test_absent_kg_refuses_without_creating_it(self, tmp_path, monkeypatch):
        manager, service, commands = self.prepared(tmp_path, monkeypatch)
        kg = Path(manager.palace_path) / "knowledge_graph.sqlite3"
        kg.unlink()
        result = manager.apply()
        assert not result.ok
        assert not kg.exists()
        assert "stop" not in service.calls
        assert not commands
        # The existing owner really can create this file outside the palace lease.
        from mempalace_code.knowledge_graph import KnowledgeGraph

        with updater.palace_write_lease(manager.palace_path, "independent premise"):
            KnowledgeGraph(db_path=str(kg))
        assert kg.exists()

    @pytest.mark.parametrize("kind", ["non-wal", "symlink", "directory", "inode-drift"])
    def test_unsafe_kg_refuses_before_dispatch(self, tmp_path, monkeypatch, kind):
        manager, service, commands = self.prepared(tmp_path, monkeypatch)
        kg = Path(manager.palace_path) / "knowledge_graph.sqlite3"
        if kind == "non-wal":
            with sqlite3.connect(kg) as db:
                assert db.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
        elif kind == "symlink":
            replacement = kg.with_suffix(".other")
            kg.rename(replacement)
            kg.symlink_to(replacement)
        elif kind == "directory":
            kg.unlink()
            kg.mkdir()
        else:
            original = service.capture_actors
            calls = 0

            def drift(observe):
                nonlocal calls
                calls += 1
                if calls == 3:
                    replacement = kg.with_suffix(".old")
                    kg.rename(replacement)
                    kg.write_bytes(replacement.read_bytes())
                return original(observe)

            service.capture_actors = drift
        result = manager.apply()
        assert not result.ok
        assert "stop" not in service.calls
        assert not commands

    def test_actor_birth_drift_refuses_before_dispatch(self, tmp_path, monkeypatch):
        manager, service, commands = self.prepared(tmp_path, monkeypatch)
        births = iter([1, 1, 2])
        manager.observe_process = lambda _pid: next(births)
        result = manager.apply()
        assert not result.ok
        assert "stop" not in service.calls
        assert not commands

    @pytest.mark.parametrize(
        "failure",
        [
            "false",
            "exception",
            "interrupt",
            "system-exit",
            "observer",
            "pause",
            "notice",
            "pid-reuse",
            "success",
        ],
    )
    def test_attempted_actor_drain_defers_failures_and_compensation(
        self, tmp_path, monkeypatch, failure
    ):
        manager, service, commands = self.prepared(tmp_path, monkeypatch)
        alive = True
        dispatched = False
        events = []
        observation_failed = False
        pause_failed = False
        original_start = service.start

        def observe(_pid):
            nonlocal observation_failed
            if dispatched:
                self.assert_fenced(manager)
                if failure == "observer" and not observation_failed:
                    observation_failed = True
                    raise OSError("observer unavailable")
            return 1 if alive else (2 if failure == "pid-reuse" else None)

        def stop():
            nonlocal dispatched
            assert service.stop_guard is not None
            service.stop_guard()
            service._stopped = (service.unit,)
            dispatched = True
            service.calls.append("stop")
            self.assert_fenced(manager)
            events.append("dispatch")
            if failure == "exception":
                raise RuntimeError("dispatched exception")
            if failure == "interrupt":
                raise KeyboardInterrupt("dispatched interrupt")
            if failure == "system-exit":
                raise SystemExit("dispatched exit")
            return failure in ("success", "pid-reuse"), "injected stop failure"

        def pause(_seconds):
            nonlocal alive, pause_failed
            self.assert_fenced(manager)
            if failure == "pause" and not pause_failed:
                pause_failed = True
                raise KeyboardInterrupt("pause interrupted")
            events.append("exit")
            alive = False

        def notice(_message):
            self.assert_fenced(manager)
            if failure == "notice":
                raise SystemExit("notice interrupted")

        def start():
            assert not alive
            if failure in ("success", "pid-reuse"):
                self.assert_drain_released(manager)
                assert manager.lock.held_linked_in_thread(exclusive=True)
            else:
                self.assert_released(manager)
            events.append("restart")
            return original_start()

        manager.observe_process = observe
        manager.drain_pause = pause
        manager.drain_notice = notice
        service.stop = stop
        service.start = start
        error = {
            "exception": RuntimeError,
            "interrupt": KeyboardInterrupt,
            "system-exit": SystemExit,
            "observer": OSError,
            "pause": KeyboardInterrupt,
            "notice": SystemExit,
        }.get(failure)
        if error is not None:
            with pytest.raises(error):
                manager.apply()
        else:
            result = manager.apply()
            assert result.ok == (failure in ("success", "pid-reuse"))
        assert events.index("dispatch") < events.index("exit") < events.index("restart")
        self.assert_released(manager)
        if failure not in ("success", "pid-reuse"):
            assert not any("install" in command for command in commands)

    @pytest.mark.parametrize("mode", ["false", "exception", "unload"])
    def test_actual_launchd_owner_drains_only_attempted_labels(self, tmp_path, monkeypatch, mode):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.second"]
        manager, commands, home = _launchd_manager(tmp_path, monkeypatch, active_labels=labels)
        for label in labels:
            _write_agent_plist(home, label)
        service = manager.service
        assert isinstance(service, LaunchdUserService)
        attempted = []
        alive = True
        original_observe = manager.observe_process
        original_start = service.start

        def bootout(label):
            self.assert_fenced(manager)
            attempted.append(label)
            if mode == "exception":
                raise RuntimeError("after dispatch")
            return mode != "false", "indeterminate"

        def observe(pid):
            if attempted:
                assert pid == 4200
                self.assert_fenced(manager)
                return 1 if alive else None
            return original_observe(pid)

        def pause(_seconds):
            nonlocal alive
            self.assert_fenced(manager)
            alive = False

        def start():
            assert attempted == [labels[0]]
            assert not alive
            self.assert_released(manager)
            assert service._stopped == (labels[0],)
            return original_start()

        service._bootout = bootout
        service._wait_until_unloaded = lambda label: (False, f"unload uncertain: {label}")
        service.start = start
        manager.observe_process = observe
        manager.drain_pause = pause
        if mode == "exception":
            with pytest.raises(RuntimeError, match="after dispatch"):
                manager.apply()
        else:
            result = manager.apply()
            assert not result.ok
            assert result.stage == "watcher-stop"
        assert attempted == [labels[0]]
        assert not any("install" in command for command in commands)
        assert not any(
            command[:2] == ["launchctl", "bootstrap"] and command[-1].endswith(labels[1] + ".plist")
            for command in commands
        )

    def test_no_watcher_needs_no_kg_or_actor_attribution(self, tmp_path):
        manager, _commands = _manager(tmp_path, service=FakeService(active=False))
        assert manager.apply().ok
        assert not Path(manager.palace_path).exists()

    def test_systemd_zero_main_pid_refuses_before_stop(self, tmp_path, monkeypatch):
        unit = DEFAULT_WATCHER_UNIT
        manager, commands = _systemd_manager(
            tmp_path, active_units=[unit], exec_starts={unit: "mempalace-code watch /srv/dev"}
        )
        service = manager.service
        assert isinstance(service, SystemdUserService)
        original = service.runner

        def zero_pid(command):
            if "--property=MainPID" in command:
                return 0, "0", ""
            return original(command)

        service.runner = zero_pid
        result = manager.apply()
        assert not result.ok
        assert "MainPID" in result.message
        assert not any(command[:3] == ["systemctl", "--user", "stop"] for command in commands)

    def test_new_selected_actor_before_dispatch_refuses(self, tmp_path, monkeypatch):
        manager, service, commands = self.prepared(tmp_path, monkeypatch)
        original = service.capture_actors
        captures = 0

        def capture(observe):
            nonlocal captures
            captures += 1
            actors = original(observe)
            if captures >= 3:
                return (*actors, updater.WatcherActor("new-watcher", 91002, 1))
            return actors

        service.capture_actors = capture
        result = manager.apply()
        assert not result.ok
        assert "stop" not in service.calls
        assert not commands

    def test_success_retains_fences_until_both_launchd_actors_exit(self, tmp_path, monkeypatch):
        labels = [DEFAULT_LAUNCHD_WATCH_LABEL, "com.mempalace.watch.second"]
        manager, commands, home = _launchd_manager(tmp_path, monkeypatch, active_labels=labels)
        for label in labels:
            _write_agent_plist(home, label)
        service = manager.service
        assert isinstance(service, LaunchdUserService)
        alive = {4200, 4201}
        phase = "capture"
        observed = []
        original_start = service.start

        def observe(pid):
            if phase == "drain":
                self.assert_fenced(manager)
                observed.append(pid)
            return 1 if pid in alive else None

        original_stop = service.stop

        def stop():
            nonlocal phase
            result = original_stop()
            phase = "drain"
            return result

        def pause(_seconds):
            self.assert_fenced(manager)
            assert service._stopped == tuple(labels)
            alive.clear()

        def start():
            assert not alive
            self.assert_drain_released(manager)
            assert manager.lock.held_linked_in_thread(exclusive=True)
            return original_start()

        manager.observe_process = observe
        manager.drain_pause = pause
        service.stop = stop
        service.start = start
        assert manager.apply().ok
        assert set(observed) == {4200, 4201}
        assert sum(command[:2] == ["launchctl", "bootout"] for command in commands) == 2

    @pytest.mark.parametrize("outcome", ["unknown", "absent", "birth", "child", "foreign"])
    def test_default_process_observer_requires_complete_same_user_identity(
        self, monkeypatch, outcome
    ):
        uid = os.geteuid() + (1 if outcome == "foreign" else 0)
        rows = "" if outcome == "absent" else f"91001 1 {uid} Tue Oct 27 12:00:00 2026"
        rows += f"\n{os.getpid()} 1 {os.geteuid()} Tue Oct 27 11:59:00 2026"
        if outcome == "child":
            rows += f"\n91002 91001 {uid} Tue Oct 27 12:00:01 2026"
        monkeypatch.setattr(
            updater.subprocess,
            "run",
            lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1 if outcome == "unknown" else 0, stdout=rows
            ),
        )
        if outcome in ("unknown", "child", "foreign"):
            with pytest.raises((OSError, ValueError)):
                updater._process_birth(91001)
        elif outcome == "absent":
            assert updater._process_birth(91001) is None
        else:
            assert updater._process_birth(91001) == int(
                updater.time.mktime(
                    updater.time.strptime("Tue Oct 27 12:00:00 2026", "%a %b %d %H:%M:%S %Y")
                )
            )


class TestShutdownSigint:
    @pytest.mark.parametrize(
        "boundary",
        [
            "drain-entry",
            "observer-error",
            "pause-error",
            "notice-error",
            "teardown",
            "restore",
            "late-check",
            "return-handoff",
            "return-opcode",
        ],
    )
    def test_real_sigint_retains_fences_and_restores_signal_state(
        self, tmp_path, monkeypatch, boundary
    ):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        original_handler = signal.getsignal(signal.SIGINT)
        original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        assert original_handler is signal.default_int_handler
        alive = True
        dispatched = False
        injected = False
        failed = False
        opcode_count = 0
        restarts = []
        original_stop = service.stop
        original_start = service.start
        method = updater.UpdateManager._drain_fenced_watcher
        if boundary in ("teardown", "restore", "late-check", "return-handoff", "return-opcode"):
            method = updater.UpdateManager._stop_fenced_watcher
        lines, first = inspect.getsourcelines(method)
        target = {
            "drain-entry": "while pending:",
            "observer-error": "if deferred is None:",
            "pause-error": "if deferred is None:",
            "notice-error": "if deferred is None:",
            "teardown": "signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})",
            "restore": "signal.signal(signal.SIGINT, original_handler)",
            "late-check": "if interrupted is not None:",
            "return-handoff": "return result",
            "return-opcode": "return result",
        }[boundary]
        injection_line = next(first + i for i, line in enumerate(lines) if line.strip() == target)
        instructions = list(dis.get_instructions(method))
        return_offset = (
            next(
                instructions[i + 1].offset
                for i, instruction in enumerate(instructions[:-1])
                if instruction.opname == "LOAD_FAST"
                and instruction.argval == "result"
                and instructions[i + 1].opname == "RETURN_VALUE"
            )
            if boundary == "return-opcode"
            else None
        )

        def observe(_pid):
            nonlocal failed
            if dispatched and boundary == "observer-error" and not failed:
                failed = True
                raise OSError("observer failure before actual SIGINT")
            return 1 if alive else None

        def stop():
            nonlocal dispatched
            result = original_stop()
            dispatched = True
            return result

        def pause(_seconds):
            nonlocal alive, failed
            TestWriterDrain.assert_fenced(manager)
            if boundary == "pause-error" and not failed:
                failed = True
                raise RuntimeError("pause failure before actual SIGINT")
            alive = False

        def notice(_message):
            nonlocal failed
            if boundary == "notice-error" and not failed:
                failed = True
                raise RuntimeError("notice failure before actual SIGINT")

        def start():
            assert not alive
            TestWriterDrain.assert_released(manager)
            restarts.append(True)
            return original_start()

        def trace(frame, event, _arg):
            nonlocal injected, opcode_count
            if frame.f_code is method.__code__ and boundary == "return-opcode":
                frame.f_trace_opcodes = True
                if event == "opcode" and dispatched:
                    opcode_count += 1
            at_boundary = (
                event == "opcode" and frame.f_lasti == return_offset
                if boundary == "return-opcode"
                else event == "line" and frame.f_lineno == injection_line
            )
            if at_boundary and frame.f_code is method.__code__ and dispatched and not injected:
                injected = True
                if alive:
                    TestWriterDrain.assert_fenced(manager)
                signal.raise_signal(signal.SIGINT)
                if alive:
                    TestWriterDrain.assert_fenced(manager)
            return trace

        manager.observe_process = observe
        manager.drain_pause = pause
        manager.drain_notice = notice
        service.stop = stop
        service.start = start
        previous_trace = sys.gettrace()
        # Prime opcode tracing before settrace on the supported Python 3.12
        # test runtime, and require positive normal-flow delivery below.
        tracing_frame = sys._getframe()
        previous_opcodes = tracing_frame.f_trace_opcodes
        tracing_frame.f_trace_opcodes = True
        sys.settrace(trace)
        try:
            expected = (
                OSError
                if boundary == "observer-error"
                else RuntimeError
                if boundary in ("pause-error", "notice-error")
                else KeyboardInterrupt
            )
            with pytest.raises(expected):
                manager.apply()
        finally:
            sys.settrace(previous_trace)
            tracing_frame.f_trace_opcodes = previous_opcodes
        assert injected
        assert not alive
        assert restarts == [True]
        assert service.calls.count("stop") == 1
        if boundary == "return-opcode":
            assert opcode_count > 0
        assert signal.getsignal(signal.SIGINT) is original_handler
        assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == original_mask
        TestWriterDrain.assert_released(manager)
        assert not any("install" in command for command in commands)

    def test_sigint_while_acquiring_fence_never_dispatches_stop(self, tmp_path, monkeypatch):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        acquire = manager.lock.acquire_shared
        original_handler = signal.getsignal(signal.SIGINT)

        def interrupted_acquisition(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            signal.raise_signal(signal.SIGINT)
            return lease

        monkeypatch.setattr(manager.lock, "acquire_shared", interrupted_acquisition)
        with pytest.raises(KeyboardInterrupt):
            manager.apply()
        assert "stop" not in service.calls
        assert signal.getsignal(signal.SIGINT) is original_handler
        TestWriterDrain.assert_released(manager)
        assert not any("install" in command for command in commands)

    def test_nonmain_thread_refuses_before_effects(self, tmp_path, monkeypatch):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        results = []
        thread = threading.Thread(target=lambda: results.append(manager.apply()))
        thread.start()
        thread.join()
        assert len(results) == 1
        assert not results[0].ok
        assert "main thread" in results[0].message
        assert "stop" not in service.calls
        assert not commands

    def test_custom_sigint_handler_refuses_before_effects(self, tmp_path, monkeypatch):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        monkeypatch.setattr(signal, "getsignal", lambda _sig: lambda *_args: None)
        result = manager.apply()
        assert not result.ok
        assert "unsupported SIGINT" in result.message
        assert "stop" not in service.calls
        assert not commands

    def test_preblocked_sigint_refuses_and_preserves_mask(self, tmp_path, monkeypatch):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
        try:
            result = manager.apply()
            assert not result.ok
            assert "already blocked" in result.message
            assert signal.SIGINT in signal.pthread_sigmask(signal.SIG_BLOCK, set())
            assert "stop" not in service.calls
            assert not commands
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, original_mask)

    @pytest.mark.parametrize("unsupported", ["mask", "handler-install"])
    def test_unavailable_deferral_refuses_before_effects(self, tmp_path, monkeypatch, unsupported):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        original_handler = signal.getsignal(signal.SIGINT)
        original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())

        def unavailable(*_args):
            raise OSError("unsupported signal route")

        with monkeypatch.context() as patched:
            if unsupported == "mask":
                patched.setattr(signal, "pthread_sigmask", unavailable)
            else:
                patched.setattr(signal, "signal", unavailable)
            result = manager.apply()
        assert not result.ok
        assert "SIGINT deferral unavailable" in result.message
        assert "recovery:" in result.message
        assert "stop" not in service.calls
        assert not commands
        assert signal.getsignal(signal.SIGINT) is original_handler
        assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == original_mask

    @pytest.mark.parametrize("failure", ["false", "exception"])
    def test_late_sigint_never_retries_failed_compensation(self, tmp_path, monkeypatch, failure):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        original_stop = service.stop
        restores = []
        injected = False

        def stop():
            original_stop()
            return False, "stop failed after dispatch"

        def start():
            TestWriterDrain.assert_released(manager)
            restores.append(True)
            if failure == "exception":
                raise RuntimeError("restoration failed")
            return False, "restoration failed"

        method = updater.UpdateManager._stop_fenced_watcher
        lines, first = inspect.getsourcelines(method)
        target = next(
            first + i
            for i, line in enumerate(lines)
            if line.strip() == "signal.signal(signal.SIGINT, original_handler)"
        )

        def trace(frame, event, _arg):
            nonlocal injected
            if (
                event == "line"
                and frame.f_code is method.__code__
                and frame.f_lineno == target
                and not injected
            ):
                assert restores == [True]
                injected = True
                signal.raise_signal(signal.SIGINT)
            return trace

        service.stop = stop
        service.start = start
        previous_trace = sys.gettrace()
        sys.settrace(trace)
        try:
            with pytest.raises(KeyboardInterrupt):
                manager.apply()
        finally:
            sys.settrace(previous_trace)
        assert injected
        assert restores == [True]
        assert service.calls.count("stop") == 1
        assert not any("install" in command for command in commands)

    def test_late_sigint_does_not_restore_an_untouched_actor(self, tmp_path, monkeypatch):
        manager, service, commands = TestWriterDrain.prepared(tmp_path, monkeypatch)
        (Path(manager.palace_path) / "knowledge_graph.sqlite3").unlink()
        method = updater.UpdateManager._stop_fenced_watcher
        lines, first = inspect.getsourcelines(method)
        target = next(first + i for i, line in enumerate(lines) if line.strip() == "return result")
        injected = False

        def trace(frame, event, _arg):
            nonlocal injected
            if (
                event == "line"
                and frame.f_code is method.__code__
                and frame.f_lineno == target
                and not injected
            ):
                injected = True
                signal.raise_signal(signal.SIGINT)
            return trace

        previous_trace = sys.gettrace()
        sys.settrace(trace)
        try:
            with pytest.raises(KeyboardInterrupt):
                manager.apply()
        finally:
            sys.settrace(previous_trace)
        assert injected
        assert "stop" not in service.calls
        assert "start" not in service.calls
        assert not commands

    @pytest.mark.parametrize("point", ["final-attribution", "after-commit"])
    def test_systemd_cancel_before_and_after_atomic_dispatch_commit(
        self, tmp_path, monkeypatch, point
    ):
        unit = DEFAULT_WATCHER_UNIT
        manager, commands = _systemd_manager(
            tmp_path,
            active_units=[unit],
            exec_starts={unit: "/opt/mempalace/bin/python -m mempalace_code watch /srv/dev"},
        )
        service = manager.service
        assert isinstance(service, SystemdUserService)
        original_owners = updater._watcher_owners
        original_handler = signal.getsignal(signal.SIGINT)
        original_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        injected = False

        def owners(*args):
            nonlocal injected
            original_owners(*args)
            if service.stop_guard is not None and point == "final-attribution" and not injected:
                assert signal.SIGINT in signal.pthread_sigmask(signal.SIG_BLOCK, set())
                injected = True
                signal.raise_signal(signal.SIGINT)

        monkeypatch.setattr(updater, "_watcher_owners", owners)
        lines, first = inspect.getsourcelines(SystemdUserService.stop)
        target = next(
            first + i
            for i, line in enumerate(lines)
            if line.strip() == "self._stopped = (self.unit,)"
        )

        def trace(frame, event, _arg):
            nonlocal injected
            if (
                point == "after-commit"
                and event == "line"
                and frame.f_code is SystemdUserService.stop.__code__
                and frame.f_lineno == target
                and not injected
            ):
                assert signal.SIGINT in signal.pthread_sigmask(signal.SIG_BLOCK, set())
                injected = True
                signal.raise_signal(signal.SIGINT)
            return trace

        previous_trace = sys.gettrace()
        sys.settrace(trace)
        try:
            with pytest.raises(KeyboardInterrupt):
                manager.apply()
        finally:
            sys.settrace(previous_trace)
        assert injected
        expected = 0 if point == "final-attribution" else 1
        assert commands.count(["systemctl", "--user", "stop", unit]) == expected
        assert commands.count(["systemctl", "--user", "start", unit]) == expected
        assert signal.getsignal(signal.SIGINT) is original_handler
        assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == original_mask
        TestWriterDrain.assert_released(manager)
        assert not any("install" in command for command in commands)
