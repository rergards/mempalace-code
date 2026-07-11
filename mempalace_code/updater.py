"""Safe, explicit upgrade orchestration for supported MemPalace installations.

The module deliberately keeps all external effects behind injectable seams.  Calling
``status`` or ``check`` inspects local state and PyPI metadata only; package changes,
service changes, and scheduler writes are reachable only through explicit methods.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.request import urlopen

from packaging.version import InvalidVersion, Version

from .operation_lock import OperationLock, OperationLockedError
from .version import __version__

PACKAGE_NAME = "mempalace-code"
PYPI_PROJECT_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
DEFAULT_WATCHER_UNIT = "mempalace-watch.service"
DEFAULT_TIMER_UNIT = "mempalace-update.timer"
DEFAULT_SERVICE_UNIT = "mempalace-update.service"
MIN_FREE_BYTES = 100 * 1024 * 1024
DEFAULT_COMMAND_TIMEOUT = 15 * 60

CommandRunner = Callable[[list[str]], tuple[int, str, str]]
PypiFetcher = Callable[[], dict[str, Any]]
PalaceValidator = Callable[[str], tuple[bool, str]]
BackupPreflight = Callable[[], tuple[bool, str]]


class WatcherService(Protocol):
    """Service controls required by an update transaction."""

    unit: str

    def is_active(self) -> tuple[bool, str]: ...

    def stop(self) -> tuple[bool, str]: ...

    def start(self) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class Installation:
    """A detected installation that can be upgraded without crossing ownership boundaries."""

    kind: str
    python: str
    cli_command: tuple[str, ...]
    manager_command: tuple[str, ...]
    extras: frozenset[str] = frozenset()
    supported: bool = True
    reason: str = ""

    @classmethod
    def unsupported(cls, reason: str) -> Installation:
        return cls(
            kind="unsupported",
            python=sys.executable,
            cli_command=(sys.executable, "-m", "mempalace_code"),
            manager_command=(),
            supported=False,
            reason=reason,
        )

    def package_spec(self, version: str) -> str:
        extras = f"[{','.join(sorted(self.extras))}]" if self.extras else ""
        return f"{PACKAGE_NAME}{extras}=={version}"

    def install_command(self, version: str) -> list[str]:
        package = self.package_spec(version)
        if self.kind == "uv-tool":
            return [*self.manager_command, "tool", "install", "--force", package]
        if self.kind == "pipx":
            return [*self.manager_command, "install", "--force", package]
        if self.kind == "bootstrap-venv":
            return [*self.manager_command, "install", "--upgrade", package]
        raise ValueError(f"unsupported installation kind: {self.kind}")

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "supported": self.supported,
            "reason": self.reason,
            "extras": sorted(self.extras),
            "cli": list(self.cli_command),
        }


@dataclass(frozen=True)
class ReleaseProvenance:
    """A release selected from canonical PyPI JSON under the stable-major policy."""

    current_version: str
    target_version: str | None
    eligible: bool
    reason: str
    project_url: str = PYPI_PROJECT_URL
    wheel_filename: str | None = None
    wheel_url: str | None = None
    sha256: str | None = None
    upload_time: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "current_version": self.current_version,
            "target_version": self.target_version,
            "eligible": self.eligible,
            "reason": self.reason,
            "project_url": self.project_url,
            "wheel_filename": self.wheel_filename,
            "wheel_url": self.wheel_url,
            "sha256": self.sha256,
            "upload_time": self.upload_time,
        }


@dataclass
class UpdateResult:
    """Stable result returned to the CLI for human and JSON rendering."""

    ok: bool
    stage: str
    message: str
    exit_code: int
    log_path: str | None = None
    data: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "stage": self.stage,
            "message": self.message,
            "exit_code": self.exit_code,
            "log_path": self.log_path,
            **self.data,
        }


class SystemdUserService:
    """Narrow systemctl --user adapter used by the update transaction."""

    def __init__(self, runner: CommandRunner, unit: str = DEFAULT_WATCHER_UNIT) -> None:
        self.runner = runner
        self.unit = unit

    def is_active(self) -> tuple[bool, str]:
        rc, out, err = self._run(["systemctl", "--user", "is-active", "--quiet", self.unit])
        if rc == 0:
            return True, "active"
        detail = (err or out).strip()
        return False, detail or "inactive"

    def stop(self) -> tuple[bool, str]:
        rc, out, err = self._run(["systemctl", "--user", "stop", self.unit])
        return rc == 0, (err or out).strip()

    def start(self) -> tuple[bool, str]:
        rc, out, err = self._run(["systemctl", "--user", "start", self.unit])
        return rc == 0, (err or out).strip()

    def _run(self, command: list[str]) -> tuple[int, str, str]:
        try:
            return self.runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)


def detect_installed_extras() -> frozenset[str]:
    """Infer optional capabilities from importable installed packages without writing state."""
    modules = {
        "watch": "watchfiles",
        "treesitter": "tree_sitter",
        "spellcheck": "autocorrect",
        "chroma": "chromadb",
    }
    return frozenset(extra for extra, module in modules.items() if find_spec(module) is not None)


def _has_editable_metadata() -> bool:
    try:
        dist = metadata.distribution(PACKAGE_NAME)
        direct_url = dist.read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return False
    if not direct_url:
        return False
    try:
        data = json.loads(direct_url)
    except ValueError:
        return True
    return bool(data.get("dir_info", {}).get("editable", True))


def detect_installation(
    *,
    python: str | None = None,
    prefix: str | Path | None = None,
    base_prefix: str | Path | None = None,
    environ: dict[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    extras: frozenset[str] | None = None,
) -> Installation:
    """Detect only isolated installers with an unambiguous MemPalace ownership model."""
    env = os.environ if environ is None else environ
    executable = python or sys.executable
    env_prefix = Path(prefix or sys.prefix).expanduser().resolve()
    system_prefix = Path(base_prefix or sys.base_prefix).expanduser().resolve()
    detected_extras = detect_installed_extras() if extras is None else extras

    if env_prefix == system_prefix:
        return Installation.unsupported(
            "system Python installations are not supported for automatic upgrades"
        )
    if _has_editable_metadata():
        return Installation.unsupported(
            "editable or source-checkout installations are not supported"
        )

    bootstrap = (Path.home() / ".mempalace" / "venv").resolve()
    if env_prefix == bootstrap:
        return Installation(
            kind="bootstrap-venv",
            python=executable,
            cli_command=(executable, "-m", "mempalace_code"),
            manager_command=(executable, "-m", "pip"),
            extras=detected_extras,
        )

    pipx_home = Path(env.get("PIPX_HOME", Path.home() / ".local" / "pipx")).expanduser()
    if (
        pipx_home in env_prefix.parents
        or "pipx" in env_prefix.parts
        and "venvs" in env_prefix.parts
    ):
        pipx = which("pipx")
        if pipx:
            return Installation(
                kind="pipx",
                python=executable,
                cli_command=(executable, "-m", "mempalace_code"),
                manager_command=(pipx,),
                extras=detected_extras,
            )
        return Installation.unsupported("pipx environment found but pipx executable is unavailable")

    xdg_data_home = Path(env.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    uv_tool_roots = [
        Path(env["UV_TOOL_DIR"]) if env.get("UV_TOOL_DIR") else None,
        xdg_data_home / "uv" / "tools",
        Path.home() / "Library" / "Application Support" / "uv" / "tools",
    ]
    if any(
        root is not None and root.expanduser().resolve() in {env_prefix, *env_prefix.parents}
        for root in uv_tool_roots
    ):
        uv = which("uv")
        if uv:
            return Installation(
                kind="uv-tool",
                python=executable,
                cli_command=(executable, "-m", "mempalace_code"),
                manager_command=(uv,),
                extras=detected_extras,
            )
        return Installation.unsupported(
            "uv tool environment found but uv executable is unavailable"
        )

    return Installation.unsupported(
        "ambiguous virtual environment; supported installers are uv tool, pipx, and bootstrap venv"
    )


def _default_runner(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=DEFAULT_COMMAND_TIMEOUT,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _default_fetcher() -> dict[str, Any]:
    with urlopen(PYPI_PROJECT_URL, timeout=10) as response:  # noqa: S310 - fixed PyPI URL
        return json.loads(response.read().decode("utf-8"))


def _default_palace_validator(palace_path: str) -> tuple[bool, str]:
    palace = Path(palace_path).expanduser()
    if not palace.exists():
        return False, f"palace path does not exist: {palace}"
    lance_path = palace / "lance"
    if not lance_path.exists():
        return True, "palace has no Lance data yet"
    try:
        from .storage import open_store

        report = open_store(str(palace), create=False, read_only=True).health_check()  # type: ignore[reportAttributeAccessIssue]  # reason: health checks are a LanceStore-only update validation surface
    except Exception as exc:
        return False, str(exc)
    return bool(report.get("ok")), str(report.get("summary", report))


def _default_backup_preflight() -> tuple[bool, str]:
    """State that package-only rollback preserves palace data; no update backup is created."""
    return (
        True,
        "package upgrade does not modify palace data; existing backup policy remains in effect",
    )


class UpdateManager:
    """Coordinate supported installation upgrades without implicit side effects."""

    def __init__(
        self,
        *,
        state_root: str | Path | None = None,
        palace_path: str | None = None,
        installation: Installation | None = None,
        installation_detector: Callable[[], Installation] = detect_installation,
        runner: CommandRunner = _default_runner,
        fetcher: PypiFetcher = _default_fetcher,
        lock: OperationLock | None = None,
        service: WatcherService | None = None,
        palace_validator: PalaceValidator = _default_palace_validator,
        backup_preflight: BackupPreflight = _default_backup_preflight,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        minimum_free_bytes: int = MIN_FREE_BYTES,
    ) -> None:
        self.state_root = Path(state_root or Path.home() / ".mempalace").expanduser()
        self.palace_path = palace_path or str(self.state_root / "palace")
        self._installation = installation
        self.installation_detector = installation_detector
        self.runner = runner
        self.fetcher = fetcher
        self.lock = lock or OperationLock(self.state_root / "operation.lock")
        self.service = service or SystemdUserService(runner)
        self.palace_validator = palace_validator
        self.backup_preflight = backup_preflight
        self.now = now
        self.minimum_free_bytes = minimum_free_bytes

    @property
    def updates_dir(self) -> Path:
        return self.state_root / "updates"

    @property
    def state_path(self) -> Path:
        return self.updates_dir / "state.json"

    def status(self, *, refresh: bool = True) -> UpdateResult:
        """Inspect eligibility and service/scheduler state without creating or changing files."""
        installation = self._get_installation()
        provenance = self._resolve_provenance() if refresh else self._cached_provenance()
        active, service_detail = self.service.is_active()
        scheduler = self.scheduler_status()
        state = self._read_state()
        required_missing = self._required_extra_missing(installation, active)
        if required_missing:
            eligibility_reason = required_missing
        elif not installation.supported:
            eligibility_reason = installation.reason
        else:
            eligibility_reason = provenance.reason
        data = {
            "installation": installation.as_dict(),
            "provenance": provenance.as_dict(),
            "eligible": installation.supported and provenance.eligible and required_missing is None,
            "watcher": {"unit": self.service.unit, "active": active, "detail": service_detail},
            "scheduler": scheduler,
            "next_run": scheduler.get("next_run"),
            "last_update": state,
            "reason": eligibility_reason,
        }
        return UpdateResult(
            True, "status", "update status inspected without mutation", 0, data=data
        )

    def check(self) -> UpdateResult:
        """Refresh canonical PyPI metadata without installing or persisting update state."""
        return self.status(refresh=True)

    def apply(self, *, scheduled: bool = False) -> UpdateResult:
        """Run the explicit, compensating update transaction for a supported installation."""
        installation = self._get_installation()
        provenance = self._resolve_provenance()
        active, _ = self.service.is_active()
        preflight_error = self._preflight_error(installation, provenance, active)
        if preflight_error:
            return UpdateResult(False, "preflight", preflight_error, 2)

        # Do not stop a managed watcher just to discover an already-running update.
        # A shared watcher lease is handled below after its service has stopped; an
        # exclusive lease can only be another updater and must fail without mutation.
        existing_owner = self.lock.exclusive_owner_details()
        if existing_owner:
            return UpdateResult(
                False,
                "lock",
                "another update operation already owns this installation",
                3,
                data={"lock_owner": existing_owner},
            )

        was_active = active
        if was_active:
            stopped, detail = self.service.stop()
            if not stopped:
                return UpdateResult(False, "watcher-stop", detail or "could not stop watcher", 1)

        try:
            lease = self.lock.acquire_exclusive("scheduled-update" if scheduled else "update")
        except OperationLockedError as exc:
            if was_active:
                self.service.start()
            owner = exc.owner
            return UpdateResult(
                False,
                "lock",
                str(exc),
                3,
                data={"lock_owner": owner},
            )

        with lease:
            log_path = self._new_log_path()
            state: dict[str, object] = {
                "previous_version": provenance.current_version,
                "target_version": provenance.target_version,
                "watcher_was_active": was_active,
                "started_at": self._timestamp(),
                "scheduled": scheduled,
                "provenance": provenance.as_dict(),
                "log_path": str(log_path),
            }
            state_persisted = False
            try:
                self._transition(state, "preflight-passed")
                state_persisted = True
                target = provenance.target_version
                if target is None:  # guarded by _preflight_error; retain fail-closed invariant.
                    return self._rollback(
                        state, installation, was_active, "preflight", "no eligible target"
                    )

                self._transition(state, "watcher-stopped")
                self._transition(state, "installer-started")
                ok, detail = self._run_logged(log_path, installation.install_command(target))
                if not ok:
                    return self._rollback(state, installation, was_active, "installer", detail)

                ok, detail = self._run_logged(
                    log_path, [*installation.cli_command, "update", "--help"]
                )
                if not ok:
                    return self._rollback(state, installation, was_active, "cli-health", detail)
                self._transition(state, "package-validated")

                ok, detail = self.palace_validator(self.palace_path)
                self._append_log(log_path, f"palace-health: {detail}")
                if not ok:
                    return self._rollback(state, installation, was_active, "palace-health", detail)
                self._transition(state, "palace-validated")

                if was_active:
                    started, detail = self.service.start()
                    if not started:
                        return self._rollback(
                            state, installation, was_active, "watcher-restart", detail
                        )
                    active_after, detail = self.service.is_active()
                    if not active_after:
                        return self._rollback(
                            state, installation, was_active, "watcher-validate", detail
                        )
                self._transition(state, "watcher-validated")
                self._transition(state, "succeeded")
                return UpdateResult(
                    True,
                    "succeeded",
                    f"updated {PACKAGE_NAME} to {target}",
                    0,
                    str(log_path),
                    {"previous_version": provenance.current_version, "target_version": target},
                )
            except Exception as exc:
                if state_persisted:
                    return self._rollback(
                        state,
                        installation,
                        was_active,
                        "transaction",
                        f"unexpected transaction error: {exc}",
                    )
                if was_active:
                    self.service.start()
                return UpdateResult(
                    False,
                    "transaction",
                    f"could not persist update state: {exc}",
                    1,
                    str(log_path),
                )

    def scheduler_status(self) -> dict[str, object]:
        """Read current systemd-user timer state; unavailable systems remain diagnostic only."""
        try:
            rc, out, err = self.runner(["systemctl", "--user", "is-enabled", DEFAULT_TIMER_UNIT])
        except (OSError, subprocess.SubprocessError) as exc:
            return {"supported": False, "enabled": False, "detail": str(exc), "next_run": None}
        enabled = rc == 0 and "enabled" in out
        return {
            "supported": True,
            "enabled": enabled,
            "detail": (err or out).strip() or "disabled",
            "next_run": self._next_timer_run() if enabled else None,
        }

    def render_scheduler_units(self) -> dict[str, str]:
        """Render deterministic systemd-user service and timer units without writing them."""
        command = " ".join(
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
        )
        service = "\n".join(
            [
                "[Unit]",
                "Description=MemPalace guarded automatic update",
                "",
                "[Service]",
                "Type=oneshot",
                f"ExecStart={command}",
                "",
            ]
        )
        timer = "\n".join(
            [
                "[Unit]",
                "Description=Daily MemPalace update check",
                "",
                "[Timer]",
                "OnCalendar=daily",
                "Persistent=true",
                f"Unit={DEFAULT_SERVICE_UNIT}",
                "",
                "[Install]",
                "WantedBy=timers.target",
                "",
            ]
        )
        return {DEFAULT_SERVICE_UNIT: service, DEFAULT_TIMER_UNIT: timer}

    def install_scheduler(self) -> UpdateResult:
        """Explicitly write and enable the supported systemd-user update timer."""
        installation = self._get_installation()
        if not installation.supported:
            return UpdateResult(False, "scheduler-preflight", installation.reason, 2)
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        try:
            unit_dir.mkdir(parents=True, exist_ok=True)
            for name, content in self.render_scheduler_units().items():
                self._atomic_write_text(unit_dir / name, content)
            for command in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", DEFAULT_TIMER_UNIT],
            ):
                ok, detail = self._run_plain(command)
                if not ok:
                    return UpdateResult(False, "scheduler-install", detail, 1)
        except OSError as exc:
            return UpdateResult(False, "scheduler-install", str(exc), 1)
        return UpdateResult(True, "scheduler-installed", "systemd-user update timer enabled", 0)

    def remove_scheduler(self) -> UpdateResult:
        """Explicitly disable the supported timer without touching package state."""
        ok, detail = self._run_plain(
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT]
        )
        if not ok:
            return UpdateResult(False, "scheduler-remove", detail, 1)
        return UpdateResult(True, "scheduler-removed", "systemd-user update timer disabled", 0)

    def _get_installation(self) -> Installation:
        return self._installation or self.installation_detector()

    def _resolve_provenance(self) -> ReleaseProvenance:
        try:
            current = Version(__version__)
        except InvalidVersion:
            return ReleaseProvenance(
                __version__, None, False, "installed version is not valid PEP 440"
            )
        try:
            data = self.fetcher()
        except Exception as exc:
            return ReleaseProvenance(
                str(current), None, False, f"PyPI provenance unavailable: {exc}"
            )
        releases = data.get("releases")
        if not isinstance(releases, dict):
            return ReleaseProvenance(str(current), None, False, "PyPI response has no release list")
        candidates: list[tuple[Version, str, dict[str, Any]]] = []
        for raw_version, files in releases.items():
            try:
                candidate = Version(str(raw_version))
            except InvalidVersion:
                continue
            if candidate <= current or candidate.is_prerelease or candidate.major != current.major:
                continue
            if not isinstance(files, list):
                continue
            wheels = [
                file
                for file in files
                if isinstance(file, dict)
                and file.get("packagetype") == "bdist_wheel"
                and not file.get("yanked", False)
            ]
            if wheels:
                candidates.append((candidate, str(raw_version), wheels[0]))
        if not candidates:
            return ReleaseProvenance(
                str(current), None, False, "no newer stable compatible-major wheel is published"
            )
        candidate, raw_version, wheel = max(candidates, key=lambda item: item[0])
        raw_digests = wheel.get("digests")
        digests = raw_digests if isinstance(raw_digests, dict) else {}
        return ReleaseProvenance(
            str(current),
            raw_version,
            True,
            "newer stable compatible-major release is eligible",
            project_url=PYPI_PROJECT_URL,
            wheel_filename=str(wheel.get("filename") or "") or None,
            wheel_url=str(wheel.get("url") or "") or None,
            sha256=str(digests.get("sha256") or "") or None,
            upload_time=str(wheel.get("upload_time_iso_8601") or wheel.get("upload_time") or "")
            or None,
        )

    def _cached_provenance(self) -> ReleaseProvenance:
        state = self._read_state()
        value = state.get("provenance") if isinstance(state, dict) else None
        if isinstance(value, dict):
            return ReleaseProvenance(
                str(value.get("current_version", __version__)),
                value.get("target_version")
                if isinstance(value.get("target_version"), str)
                else None,
                bool(value.get("eligible", False)),
                str(value.get("reason", "no cached provenance")),
            )
        return ReleaseProvenance(__version__, None, False, "no cached provenance; run update check")

    def _required_extra_missing(
        self, installation: Installation, watcher_active: bool
    ) -> str | None:
        if watcher_active and "watch" not in installation.extras:
            return "configured watcher is active but the required watch extra is unavailable"
        return None

    def _preflight_error(
        self, installation: Installation, provenance: ReleaseProvenance, watcher_active: bool
    ) -> str | None:
        if not installation.supported:
            return installation.reason
        if not provenance.eligible:
            return provenance.reason
        missing = self._required_extra_missing(installation, watcher_active)
        if missing:
            return missing
        disk_path = self.state_root
        while not disk_path.exists() and disk_path.parent != disk_path:
            disk_path = disk_path.parent
        try:
            free = shutil.disk_usage(disk_path).free
        except OSError as exc:
            return f"disk preflight unavailable: {exc}"
        if free < self.minimum_free_bytes:
            return f"disk preflight failed: need at least {self.minimum_free_bytes} free bytes"
        backup_ok, backup_detail = self.backup_preflight()
        if not backup_ok:
            return f"backup preflight failed: {backup_detail}"
        return None

    def _rollback(
        self,
        state: dict[str, object],
        installation: Installation,
        was_active: bool,
        failed_stage: str,
        detail: str,
    ) -> UpdateResult:
        log_path = Path(str(state["log_path"]))
        state["failed_stage"] = failed_stage
        state["failure_detail"] = detail
        self._transition(state, "rollback-started")
        previous = str(state["previous_version"])
        rollback_ok, rollback_detail = self._run_logged(
            log_path, installation.install_command(previous)
        )
        service_ok = True
        service_detail = ""
        if was_active:
            started, service_detail = self.service.start()
            verified, verify_detail = (
                self.service.is_active() if started else (False, service_detail)
            )
            service_ok = started and verified
            if not service_ok:
                service_detail = verify_detail or service_detail
        self._append_log(
            log_path,
            f"rollback package={'ok' if rollback_ok else 'failed'} service={'ok' if service_ok else 'failed'}",
        )
        if rollback_ok and service_ok:
            self._transition(state, "rollback-succeeded")
            message = f"update failed at {failed_stage}; restored {previous}"
        else:
            self._transition(state, "rollback-failed")
            message = f"update failed at {failed_stage}; rollback requires operator recovery"
        details = "; ".join(item for item in (detail, rollback_detail, service_detail) if item)
        return UpdateResult(False, failed_stage, f"{message}: {details}", 1, str(log_path))

    def _transition(self, state: dict[str, object], stage: str) -> None:
        state["stage"] = stage
        state["updated_at"] = self._timestamp()
        self._write_state(state)

    def _read_state(self) -> dict[str, object]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, state: dict[str, object]) -> None:
        self.updates_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write_text(self.state_path, json.dumps(state, indent=2, sort_keys=True) + "\n")

    def _new_log_path(self) -> Path:
        day = self.now().strftime("%Y-%m-%d")
        log_dir = self.updates_dir / "logs" / day
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"update-{self.now().strftime('%H%M%S')}-{os.getpid()}.log"
        self._append_log(log_path, f"update started at {self._timestamp()}")
        return log_path

    def _append_log(self, log_path: Path, line: str) -> None:
        safe = line.replace(str(Path.home()), "~")[:4000]
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{safe}\n")

    def _run_logged(self, log_path: Path, command: list[str]) -> tuple[bool, str]:
        try:
            rc, out, err = self.runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            self._append_log(log_path, f"command unavailable: {exc}")
            return False, str(exc)
        rendered = " ".join(shlex.quote(part) for part in command)
        detail = (err or out).strip()[:4000]
        self._append_log(log_path, f"command rc={rc}: {rendered}\n{detail}")
        return rc == 0, detail or f"command exited {rc}"

    def _run_plain(self, command: list[str]) -> tuple[bool, str]:
        try:
            rc, out, err = self.runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        return rc == 0, (err or out).strip() or f"command exited {rc}"

    def _next_timer_run(self) -> str | None:
        try:
            rc, out, _ = self.runner(
                [
                    "systemctl",
                    "--user",
                    "show",
                    DEFAULT_TIMER_UNIT,
                    "--property=NextElapseUSecRealtime",
                ]
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if rc != 0 or "=" not in out:
            return None
        value = out.split("=", 1)[1].strip()
        return value or None

    def _timestamp(self) -> str:
        return self.now().isoformat()

    @staticmethod
    def _atomic_write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False, prefix=f".{path.name}."
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
