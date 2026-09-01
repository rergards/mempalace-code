"""Safe, explicit upgrade orchestration for supported MemPalace installations.

The module deliberately keeps all external effects behind injectable seams.  Calling
``status`` or ``check`` inspects local state and PyPI metadata only; package changes,
service changes, and scheduler writes are reachable only through explicit methods.
"""

from __future__ import annotations

import json
import os
import plistlib
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse
from urllib.request import urlopen

from packaging.version import InvalidVersion, Version

from .cli_commands.alias import CANONICAL_CLI_COMMAND, LEGACY_CLI_ALIAS
from .operation_lock import OperationLock, OperationLockedError
from .version import __version__

PACKAGE_NAME = "mempalace-code"
PYPI_PROJECT_URL = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
DEFAULT_WATCHER_UNIT = "mempalace-watch.service"
DEFAULT_TIMER_UNIT = "mempalace-update.timer"
DEFAULT_SERVICE_UNIT = "mempalace-update.service"
MIN_FREE_BYTES = 100 * 1024 * 1024
DEFAULT_COMMAND_TIMEOUT = 15 * 60
SYSTEMD_BASELINE_PATH = ("/usr/local/bin", "/usr/bin", "/bin")
REQUIRED_UPDATE_PLATFORM = "linux"
UPDATE_SERVICE_MANAGER = "systemd-user"
UNSUPPORTED_PLATFORM_RECOVERY_COMMAND = "mempalace-code update status --json"
# Manual apply coordinates whichever user service manager owns the watcher; scheduling
# stays Linux systemd-user only, so the two boundaries are reported independently.
DARWIN_UPDATE_PLATFORM = "darwin"
DARWIN_SERVICE_MANAGER = "launchd-user"
MANUAL_UPDATE_PLATFORMS = (DARWIN_UPDATE_PLATFORM, REQUIRED_UPDATE_PLATFORM)
DEFAULT_LAUNCHD_WATCH_LABEL = "com.mempalace.watch"
LAUNCH_AGENTS_DIR = ("Library", "LaunchAgents")
# Both console scripts ship in this distribution, so an owned watcher may invoke either.
SUPPORTED_WATCH_CONSOLE_SCRIPTS = frozenset({CANONICAL_CLI_COMMAND, LEGACY_CLI_ALIAS})
SCHEDULER_UNSET_ENVIRONMENT = (
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CODEX_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "GOOGLE_API_KEY",
    "HF_TOKEN",
    "OPENAI_API_KEY",
    "PIP_EXTRA_INDEX_URL",
    "PIP_INDEX_URL",
    "PYPI_TOKEN",
    "SSH_AUTH_SOCK",
    "UV_EXTRA_INDEX_URL",
    "UV_INDEX_URL",
)
_CUSTOM_WATCHER_UNIT = re.compile(r"^mempalace-watch-[A-Za-z0-9][A-Za-z0-9_.@-]*\.service$")
_LAUNCHD_WATCH_LABEL = re.compile(r"^com\.mempalace\.watch(?:[.-][A-Za-z0-9][A-Za-z0-9_.-]*)?$")
_PYTHON_EXECUTABLE = re.compile(r"^python(?:3(?:\.\d+)?t?)?$")
_ASCII_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")

CommandRunner = Callable[[list[str]], tuple[int, str, str]]
PypiFetcher = Callable[[], dict[str, Any]]
PalaceValidator = Callable[[str], tuple[bool, str]]
BackupPreflight = Callable[[], tuple[bool, str]]
SchedulerContext = Callable[[], tuple[Path, str | None]]


class WatcherService(Protocol):
    """Service controls required by an update transaction."""

    unit: str

    def discover(self) -> WatcherDiscovery: ...

    def is_active(self) -> tuple[bool, str]: ...

    def stop(self) -> tuple[bool, str]: ...

    def start(self) -> tuple[bool, str]: ...


@dataclass(frozen=True)
class WatcherDiscovery:
    """A watcher selection that is safe to coordinate during an update."""

    unit: str
    active: bool
    safe: bool
    detail: str


# Every reason `detect_installation` can refuse with. They are named because the
# refusal is not just a message: exactly one of them — an ambiguous venv — can
# still be an ordinary pip install, and the ordinary-pip upgrade hint keys off it.
UNSUPPORTED_SYSTEM = "system Python installations are not supported for automatic upgrades"
UNSUPPORTED_EDITABLE = "editable or source-checkout installations are not supported"
UNSUPPORTED_PIPX_WITHOUT_PIPX = "pipx environment found but pipx executable is unavailable"
UNSUPPORTED_UV_WITHOUT_UV = "uv tool environment found but uv executable is unavailable"
UNSUPPORTED_AMBIGUOUS_VENV = (
    "ambiguous virtual environment; supported installers are uv tool, pipx, and bootstrap venv"
)


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
    already_current: bool = False
    current_release: bool = False

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
            "already_current": self.already_current,
            "current_release": self.current_release,
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


def _is_supported_watch_command(tokens: list[str]) -> bool:
    """Accept only the MemPalace watch invocations the project itself renders.

    Both console-script names ship in the same distribution, so generated and legacy
    agents and units may invoke either alias.
    """
    if len(tokens) >= 2 and Path(tokens[0]).name in SUPPORTED_WATCH_CONSOLE_SCRIPTS:
        return tokens[1] == "watch"
    return (
        len(tokens) >= 4
        and bool(_PYTHON_EXECUTABLE.fullmatch(Path(tokens[0]).name))
        and tokens[1] == "-m"
        and tokens[2] == "mempalace_code"
        and tokens[3] == "watch"
    )


class SystemdUserService:
    """Narrow systemctl --user adapter used by the update transaction."""

    def __init__(self, runner: CommandRunner, unit: str = DEFAULT_WATCHER_UNIT) -> None:
        self.runner = runner
        self.unit = unit
        self._discovery: WatcherDiscovery | None = None

    def discover(self) -> WatcherDiscovery:
        """Select one attributable active watcher once and retain it for this adapter."""
        if self._discovery is not None:
            return self._discovery

        rc, out, err = self._run(
            [
                "systemctl",
                "--user",
                "list-units",
                "--type=service",
                "--state=active",
                "--no-legend",
                "--plain",
            ]
        )
        if rc != 0:
            detail = (err or out).strip() or "systemd-user manager is unavailable"
            return self._record_discovery(False, f"watcher discovery unavailable: {detail}")

        units = self._active_watcher_units(out)
        malformed = [unit for unit in units if not self._is_valid_watcher_unit(unit)]
        if malformed:
            return self._record_discovery(
                False, f"watcher discovery found malformed unit name: {malformed[0]}"
            )

        attributable: list[str] = []
        for unit in units:
            valid, detail = self._is_mempalace_watch_command(unit)
            if not valid:
                return self._record_discovery(False, f"watcher discovery refused {unit}: {detail}")
            attributable.append(unit)

        named = [unit for unit in attributable if unit != DEFAULT_WATCHER_UNIT]
        if len(named) > 1 or (named and DEFAULT_WATCHER_UNIT in attributable):
            return self._record_discovery(
                False, "watcher discovery is ambiguous; exactly one active watcher is required"
            )
        if named:
            return self._record_discovery(
                True, f"selected active named watcher: {named[0]}", named[0]
            )
        if DEFAULT_WATCHER_UNIT in attributable:
            return self._record_discovery(
                True, f"selected active legacy watcher: {DEFAULT_WATCHER_UNIT}"
            )
        return self._record_discovery(True, "no active MemPalace watcher discovered")

    def is_active(self) -> tuple[bool, str]:
        discovery = self.discover()
        if not discovery.safe:
            return False, discovery.detail
        rc, out, err = self._run(["systemctl", "--user", "is-active", "--quiet", self.unit])
        if rc == 0:
            return True, "active"
        detail = (err or out).strip()
        return False, detail or "inactive"

    def stop(self) -> tuple[bool, str]:
        discovery = self.discover()
        if not discovery.safe:
            return False, discovery.detail
        rc, out, err = self._run(["systemctl", "--user", "stop", self.unit])
        return rc == 0, (err or out).strip()

    def start(self) -> tuple[bool, str]:
        discovery = self.discover()
        if not discovery.safe:
            return False, discovery.detail
        rc, out, err = self._run(["systemctl", "--user", "start", self.unit])
        return rc == 0, (err or out).strip()

    @staticmethod
    def _is_valid_watcher_unit(unit: str) -> bool:
        return unit == DEFAULT_WATCHER_UNIT or bool(_CUSTOM_WATCHER_UNIT.fullmatch(unit))

    @staticmethod
    def _active_watcher_units(output: str) -> list[str]:
        related: list[str] = []
        for line in output.splitlines():
            parts = line.split(maxsplit=1)
            if parts and (
                parts[0] == DEFAULT_WATCHER_UNIT or parts[0].startswith("mempalace-watch-")
            ):
                related.append(parts[0])
        return list(dict.fromkeys(related))

    def _is_mempalace_watch_command(self, unit: str) -> tuple[bool, str]:
        rc, out, err = self._run(
            ["systemctl", "--user", "show", unit, "--property=ExecStart", "--value"]
        )
        if rc != 0:
            return False, (err or out).strip() or "could not inspect ExecStart"
        tokens = self._parse_exec_start(out)
        if tokens is None:
            return False, "ExecStart is malformed"
        if _is_supported_watch_command(tokens):
            return True, ""
        return False, "ExecStart is not a MemPalace watch command"

    @staticmethod
    def _parse_exec_start(output: str) -> list[str] | None:
        value = output.strip()
        if value.startswith("ExecStart="):
            value = value.removeprefix("ExecStart=").strip()
        match = re.search(r"argv\[\]=(.*?)(?=\s*;\s*[A-Za-z_][A-Za-z0-9_]*=|\s*})", value)
        if match:
            value = match.group(1).strip()
        if not value or value.startswith("{"):
            return None
        try:
            tokens = shlex.split(value)
        except ValueError:
            return None
        return tokens or None

    def _record_discovery(
        self, safe: bool, detail: str, unit: str = DEFAULT_WATCHER_UNIT
    ) -> WatcherDiscovery:
        self.unit = unit
        self._discovery = WatcherDiscovery(unit=unit, active=False, safe=safe, detail=detail)
        return self._discovery

    def _run(self, command: list[str]) -> tuple[int, str, str]:
        try:
            return self.runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)


class LaunchdUserService:
    """Narrow launchctl adapter that coordinates every attributable macOS watcher.

    Unlike the systemd-user slice, macOS installs routinely carry several
    ``com.mempalace.watch*`` LaunchAgents, so discovery selects the whole active set
    rather than refusing more than one. Everything before ``stop`` is read-only, and
    an active agent that cannot be attributed to an owned MemPalace plist makes the
    whole discovery unsafe so no package mutation can start.
    """

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner
        self.unit = DEFAULT_LAUNCHD_WATCH_LABEL
        self.labels: tuple[str, ...] = ()
        self._stopped: tuple[str, ...] = ()
        self._discovery: WatcherDiscovery | None = None

    def discover(self) -> WatcherDiscovery:
        """Select every attributable active watcher once and retain it for this adapter."""
        if self._discovery is not None:
            return self._discovery

        _home, home_error = self._verified_home()
        if home_error is not None:
            return self._record_discovery(False, f"watcher discovery unavailable: {home_error}")

        active, error = self._active_watch_labels()
        if error is not None:
            return self._record_discovery(False, f"watcher discovery unavailable: {error}")

        malformed = [label for label in active if not _LAUNCHD_WATCH_LABEL.fullmatch(label)]
        if malformed:
            return self._record_discovery(
                False, f"watcher discovery found malformed launchd label: {malformed[0]}"
            )
        for label in active:
            owned, detail = self._is_owned_watch_agent(label)
            if not owned:
                return self._record_discovery(False, f"watcher discovery refused {label}: {detail}")
        if not active:
            return self._record_discovery(True, "no active MemPalace watcher discovered")
        return self._record_discovery(
            True,
            f"selected active MemPalace LaunchAgents: {', '.join(active)}",
            tuple(active),
        )

    def is_active(self) -> tuple[bool, str]:
        discovery = self.discover()
        if not discovery.safe:
            return False, discovery.detail
        if not self.labels:
            return False, "no active MemPalace watcher discovered"
        active, error = self._active_watch_labels()
        if error is not None:
            return False, error
        missing = [label for label in self.labels if label not in active]
        if missing:
            return False, f"inactive LaunchAgents: {', '.join(missing)}"
        return True, "active"

    def stop(self) -> tuple[bool, str]:
        """Stop the whole selected set, restoring any already-stopped agent on failure."""
        discovery = self.discover()
        if not discovery.safe:
            return False, discovery.detail
        stopped: list[str] = []
        for label in self.labels:
            ok, detail = self._bootout(label)
            if ok:
                stopped.append(label)
                ok, detail = self._wait_until_unloaded(label)
            if not ok:
                failures = [f"could not stop {label}: {detail}"]
                # Keep only what compensation could not put back, so a later explicit
                # start retries exactly the watchers still down.
                unrestored: list[str] = []
                for restored in reversed(stopped):
                    restored_ok, restored_detail = self._bootstrap(restored)
                    if not restored_ok:
                        unrestored.append(restored)
                        failures.append(f"could not restore {restored}: {restored_detail}")
                self._stopped = tuple(unrestored)
                return False, self._with_recovery("; ".join(failures))
        self._stopped = tuple(stopped)
        return True, ""

    def start(self) -> tuple[bool, str]:
        """Restart only what is still stopped, so a retry never re-bootstraps a live agent."""
        discovery = self.discover()
        if not discovery.safe:
            return False, discovery.detail
        pending: list[str] = []
        failures: list[str] = []
        for label in self._stopped:
            ok, detail = self._bootstrap(label)
            if ok:
                continue
            pending.append(label)
            failures.append(f"could not start {label}: {detail}")
        self._stopped = tuple(pending)
        if failures:
            return False, self._with_recovery("; ".join(failures))
        return True, ""

    @property
    def _domain(self) -> str:
        return f"gui/{os.geteuid()}"

    @staticmethod
    def _verified_home() -> tuple[Path, str | None]:
        """Fail closed unless the process home is the effective uid's passwd home.

        Every plist read and every launchctl mutation is addressed relative to this
        directory, so a mismatched identity must stop the adapter before it acts.
        """
        uid = os.geteuid()
        try:
            passwd_home = Path(pwd.getpwuid(uid).pw_dir).resolve(strict=True)
            home = Path.home().resolve(strict=True)
        except (KeyError, OSError) as exc:
            return Path("."), f"cannot resolve passwd HOME for uid {uid}: {exc}"
        if home != passwd_home:
            return Path("."), "HOME does not match the effective uid passwd directory"
        return home, None

    def _plist_path(self, label: str) -> tuple[Path | None, str]:
        home, error = self._verified_home()
        if error is not None:
            return None, error
        return home.joinpath(*LAUNCH_AGENTS_DIR, f"{label}.plist"), ""

    def _active_watch_labels(self) -> tuple[list[str], str | None]:
        rc, out, err = self._run(["launchctl", "list"])
        if rc != 0:
            return [], (err or out).strip() or "launchd user domain is unavailable"
        labels: list[str] = []
        for line in out.splitlines():
            parts = line.split("\t") if "\t" in line else line.split()
            if len(parts) < 3:
                continue
            pid, label = parts[0].strip(), parts[-1].strip()
            # A loaded job lists "-" when it is not currently running; KeepAlive can
            # respawn it mid-replacement, so it is coordinated exactly like a live PID.
            if not (pid == "-" or pid.isdigit()) or not self._is_watch_candidate(label):
                continue
            labels.append(label)
        return list(dict.fromkeys(labels)), None

    @staticmethod
    def _is_watch_candidate(label: str) -> bool:
        return label == DEFAULT_LAUNCHD_WATCH_LABEL or any(
            label.startswith(f"{DEFAULT_LAUNCHD_WATCH_LABEL}{separator}")
            for separator in (".", "-")
        )

    def _is_owned_watch_agent(self, label: str) -> tuple[bool, str]:
        path, path_error = self._plist_path(label)
        if path is None:
            return False, path_error
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False, "no owned LaunchAgent plist in ~/Library/LaunchAgents"
        except OSError as exc:
            return False, f"cannot inspect LaunchAgent plist: {exc}"
        if not stat.S_ISREG(info.st_mode):
            return False, "LaunchAgent plist is not a regular file"
        if info.st_uid != os.geteuid():
            return False, "LaunchAgent plist has a foreign owner"
        try:
            with path.open("rb") as handle:
                plist = plistlib.load(handle)
        except (OSError, ValueError) as exc:
            return False, f"cannot read LaunchAgent plist: {exc}"
        if not isinstance(plist, dict):
            return False, "LaunchAgent plist is malformed"
        if plist.get("Label") != label:
            return False, "LaunchAgent plist label does not match the active label"
        tokens = self._program_tokens(plist.get("ProgramArguments"))
        if tokens is None:
            return False, "ProgramArguments is malformed"
        if not _is_supported_watch_command(tokens):
            return False, "ProgramArguments is not a MemPalace watch command"
        return True, ""

    @staticmethod
    def _program_tokens(arguments: object) -> list[str] | None:
        if not isinstance(arguments, list) or not arguments:
            return None
        if not all(isinstance(argument, str) for argument in arguments):
            return None
        tokens = [str(argument) for argument in arguments]
        # MemPalace renders its own agent as `/bin/sh -c "<cli> watch <root>"`.
        if len(tokens) == 3 and Path(tokens[0]).name in {"sh", "bash"} and tokens[1] == "-c":
            try:
                tokens = shlex.split(tokens[2])
            except ValueError:
                return None
        return tokens or None

    def _bootout(self, label: str) -> tuple[bool, str]:
        rc, out, err = self._run(["launchctl", "bootout", f"{self._domain}/{label}"])
        return rc == 0, (err or out).strip()

    def _wait_until_unloaded(self, label: str) -> tuple[bool, str]:
        for _attempt in range(50):
            active, error = self._active_watch_labels()
            if error is not None:
                return False, error
            if label not in active:
                return True, ""
            time.sleep(0.1)
        return False, f"launchd job remained loaded after bootout: {label}"

    def _bootstrap(self, label: str) -> tuple[bool, str]:
        path, path_error = self._plist_path(label)
        if path is None:
            return False, path_error
        rc, out, err = self._run(["launchctl", "bootstrap", self._domain, str(path)])
        if rc == 0:
            return True, ""
        active, error = self._active_watch_labels()
        if error is None and label in active:
            return True, "already active"
        return False, (err or out).strip()

    @staticmethod
    def _with_recovery(detail: str) -> str:
        # A refusal or failed mutation blocks the operator, so it has to carry the one
        # read-only command that shows what state the watchers were left in.
        return f"{detail}; recovery: {UNSUPPORTED_PLATFORM_RECOVERY_COMMAND}"

    def _record_discovery(
        self, safe: bool, detail: str, labels: tuple[str, ...] = ()
    ) -> WatcherDiscovery:
        self.labels = labels
        self.unit = ", ".join(labels) if labels else DEFAULT_LAUNCHD_WATCH_LABEL
        if not safe:
            detail = self._with_recovery(detail)
        self._discovery = WatcherDiscovery(unit=self.unit, active=False, safe=safe, detail=detail)
        return self._discovery

    def _run(self, command: list[str]) -> tuple[int, str, str]:
        try:
            return self.runner(command)
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)


def _default_watcher_service(runner: CommandRunner) -> WatcherService:
    """Bind the watcher adapter that owns this platform's user services."""
    if sys.platform.startswith(DARWIN_UPDATE_PLATFORM):
        return LaunchdUserService(runner)
    return SystemdUserService(runner)


def detect_installed_extras() -> frozenset[str]:
    """Infer optional capabilities from importable installed packages without writing state."""
    modules = {
        "watch": "watchfiles",
        "treesitter": "tree_sitter",
        "spellcheck": "autocorrect",
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
    if not isinstance(data, dict):
        return True
    dir_info = data.get("dir_info")
    if dir_info is None:
        return False
    if not isinstance(dir_info, dict):
        return True
    editable = dir_info.get("editable")
    if not isinstance(editable, bool):
        return True
    return editable


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
        return Installation.unsupported(UNSUPPORTED_SYSTEM)
    if _has_editable_metadata():
        return Installation.unsupported(UNSUPPORTED_EDITABLE)

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
        return Installation.unsupported(UNSUPPORTED_PIPX_WITHOUT_PIPX)

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
        return Installation.unsupported(UNSUPPORTED_UV_WITHOUT_UV)

    return Installation.unsupported(UNSUPPORTED_AMBIGUOUS_VENV)


def _recorded_installer() -> str | None:
    """Read the ``INSTALLER`` marker the installing tool writes beside the dist-info."""
    try:
        text = metadata.distribution(PACKAGE_NAME).read_text("INSTALLER")
    except metadata.PackageNotFoundError:
        return None
    return text.strip() if text else None


def is_plain_pip_install(installation: Installation | None = None) -> bool:
    """True only when telling the user to pip-upgrade *this* interpreter is correct.

    `detect_installation` already refuses four environments that a pip upgrade
    would damage or could not move: a managed uv-tool/pipx/bootstrap env that
    `update` owns, a system interpreter that is frequently externally managed, an
    editable source checkout with no PyPI version to move to, and a managed env
    whose manager binary has gone missing. Each refusal carries its own reason, so
    the single remaining verdict — an ambiguous virtual environment — is the only
    one that can still be an ordinary pip install.

    Ambiguous is not sufficient on its own, though: it is also where anything
    unclassifiable lands. So the marker pip writes at install time has to say
    ``pip`` as well. Anything else stays silent rather than naming an interpreter
    we could not identify.
    """
    detected = detect_installation() if installation is None else installation
    if detected.supported or detected.reason != UNSUPPORTED_AMBIGUOUS_VENV:
        return False
    return _recorded_installer() == "pip"


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


def _available_wheels(files: object) -> list[dict[str, Any]]:
    if not isinstance(files, list):
        return []
    return [
        entry
        for entry in files
        if isinstance(entry, dict)
        and entry.get("packagetype") == "bdist_wheel"
        and not entry.get("yanked", False)
    ]


def _systemd_quoted_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def _current_wheel_provenance(
    current: Version, wheel: dict[str, Any]
) -> tuple[bool, str, str | None, str | None, str | None, str | None]:
    """Validate the live wheel facts required to authorize a scheduled current-version no-op."""
    filename = wheel.get("filename")
    expected_filename = f"{PACKAGE_NAME.replace('-', '_')}-{current}-py3-none-any.whl"
    if filename != expected_filename:
        return (
            False,
            f"current wheel filename must be {expected_filename}",
            None,
            None,
            None,
            None,
        )
    url = wheel.get("url")
    if (
        not isinstance(url, str)
        or not url.strip()
        or urlparse(url).scheme != "https"
        or not urlparse(url).netloc
    ):
        return False, "current wheel URL must be nonempty HTTPS", filename, None, None, None
    digests = wheel.get("digests")
    sha256 = digests.get("sha256") if isinstance(digests, dict) else None
    if not isinstance(sha256, str) or not _SHA256_HEX.fullmatch(sha256):
        return (
            False,
            "current wheel sha256 must be exactly 64 hexadecimal characters",
            filename,
            url,
            None,
            None,
        )
    upload_time = wheel.get("upload_time_iso_8601") or wheel.get("upload_time")
    if not isinstance(upload_time, str) or not upload_time.strip():
        return False, "current wheel upload time must be nonempty", filename, url, sha256, None
    return True, "installed stable wheel is up-to-date", filename, url, sha256, upload_time


def _default_palace_validator(palace_path: str) -> tuple[bool, str]:
    palace = Path(palace_path).expanduser()
    if not palace.exists():
        return False, f"palace path does not exist: {palace}"
    lance_path = palace / "lance"
    if not lance_path.exists():
        return True, "palace has no Lance data yet"
    try:
        from .storage import open_store

        report = open_store(str(palace), create=False, read_only=True).health_check()
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
        scheduler_context: SchedulerContext | None = None,
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
        self.service = service or _default_watcher_service(runner)
        self.palace_validator = palace_validator
        self.backup_preflight = backup_preflight
        self.scheduler_context = scheduler_context or self._scheduler_context
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
        state = self._read_state()
        # Manual apply and scheduling have independent platform boundaries: the watcher
        # block follows whichever user service manager this platform supports, while the
        # scheduler block stays Linux systemd-user only.
        manual_boundary = self._unsupported_manual_platform_data()
        scheduler = self.scheduler_status()
        if manual_boundary is None:
            watcher = self._watcher_status()
            watcher_data = {
                "unit": watcher.unit,
                "active": watcher.active,
                "detail": watcher.detail,
                "safe": watcher.safe,
            }
            required_missing = self._required_extra_missing(installation, watcher.active)
            if not watcher.safe:
                eligibility_reason = watcher.detail
            elif required_missing:
                eligibility_reason = required_missing
            elif not installation.supported:
                eligibility_reason = installation.reason
            else:
                eligibility_reason = provenance.reason
        else:
            detail = self._unsupported_manual_platform_message()
            watcher_data = {
                "unit": DEFAULT_WATCHER_UNIT,
                "active": False,
                "detail": detail,
                "safe": False,
                "supported": False,
                **manual_boundary,
            }
            required_missing = None
            eligibility_reason = detail
        data = {
            "installation": installation.as_dict(),
            "provenance": provenance.as_dict(),
            "manual_update_supported": manual_boundary is None,
            "eligible": (
                manual_boundary is None
                and installation.supported
                and provenance.eligible
                and required_missing is None
                and watcher_data["safe"]
            ),
            "watcher": watcher_data,
            "scheduler": scheduler,
            "next_run": scheduler.get("next_run"),
            "last_update": state,
            "reason": eligibility_reason,
            **(manual_boundary or {}),
        }
        return UpdateResult(
            True, "status", "update status inspected without mutation", 0, data=data
        )

    def check(self) -> UpdateResult:
        """Refresh canonical PyPI metadata without installing or persisting update state."""
        return self.status(refresh=True)

    def apply(self, *, scheduled: bool = False) -> UpdateResult:
        """Run the explicit, compensating update transaction for a supported installation."""
        platform_error = self._unsupported_manual_platform_result()
        if platform_error is not None:
            return platform_error
        installation = self._get_installation()
        provenance = self._resolve_provenance()
        if scheduled and provenance.current_release:
            if self._scheduled_up_to_date(installation, provenance):
                return UpdateResult(
                    True,
                    "up-to-date",
                    f"{PACKAGE_NAME} {provenance.current_version} is up-to-date",
                    0,
                    data={
                        "current_version": provenance.current_version,
                        "target_version": provenance.target_version,
                        "provenance": provenance.as_dict(),
                    },
                )
            return UpdateResult(
                False,
                "preflight",
                installation.reason if not installation.supported else provenance.reason,
                2,
            )
        watcher = self._watcher_status()
        active = watcher.active
        preflight_error = self._preflight_error(
            installation, provenance, active, watcher.safe, watcher.detail
        )
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
                "watcher_unit": watcher.unit,
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
        platform_boundary = self._unsupported_platform_data()
        if platform_boundary is not None:
            return {
                "supported": False,
                "enabled": False,
                "detail": self._unsupported_platform_message(),
                "next_run": None,
                **platform_boundary,
            }
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
        installation = self._get_installation()
        environment_path = self._scheduler_path(installation)
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
                f"Environment={_systemd_quoted_value(f'PATH={environment_path}')}",
                f"Environment={_systemd_quoted_value('PIP_CONFIG_FILE=/dev/null')}",
                f"Environment={_systemd_quoted_value('PIP_KEYRING_PROVIDER=disabled')}",
                f"Environment={_systemd_quoted_value('PYTHONNOUSERSITE=1')}",
                "UnsetEnvironment=" + " ".join(SCHEDULER_UNSET_ENVIRONMENT),
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
        platform_error = self._unsupported_platform_result()
        if platform_error is not None:
            return platform_error
        installation = self._get_installation()
        if not installation.supported:
            return UpdateResult(False, "scheduler-preflight", installation.reason, 2)
        try:
            units = self.render_scheduler_units()
        except ValueError as exc:
            return UpdateResult(False, "scheduler-preflight", str(exc), 2)
        unit_dir, existing, boundary_error = self._scheduler_units_preflight(
            units, require_present=False
        )
        if boundary_error:
            return UpdateResult(False, "scheduler-preflight", boundary_error, 2)
        created: list[Path] = []
        try:
            if not existing:
                unit_dir.mkdir(parents=True, exist_ok=True)
                for name, content in units.items():
                    path = unit_dir / name
                    self._atomic_write_text(path, content)
                    created.append(path)
            for command in (
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", DEFAULT_TIMER_UNIT],
            ):
                ok, detail = self._run_plain(command)
                if not ok:
                    if created:
                        cleanup_ok, cleanup_detail = self._rollback_scheduler_install(created)
                        if not cleanup_ok:
                            detail = f"{detail}; scheduler cleanup failed: {cleanup_detail}"
                    return UpdateResult(False, "scheduler-install", detail, 1)
        except OSError as exc:
            detail = str(exc)
            if created:
                cleanup_ok, cleanup_detail = self._rollback_scheduler_install(created)
                if not cleanup_ok:
                    detail = f"{detail}; scheduler cleanup failed: {cleanup_detail}"
            return UpdateResult(False, "scheduler-install", detail, 1)
        return UpdateResult(True, "scheduler-installed", "systemd-user update timer enabled", 0)

    def remove_scheduler(self) -> UpdateResult:
        """Explicitly disable the supported timer and remove its owned user units."""
        platform_error = self._unsupported_platform_result()
        if platform_error is not None:
            return platform_error
        try:
            units = self.render_scheduler_units()
        except ValueError as exc:
            return UpdateResult(False, "scheduler-preflight", str(exc), 2)
        unit_dir, _existing, boundary_error = self._scheduler_units_preflight(
            units, require_present=True
        )
        if boundary_error:
            return UpdateResult(False, "scheduler-preflight", boundary_error, 2)
        ok, detail = self._run_plain(
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT]
        )
        if not ok:
            return UpdateResult(False, "scheduler-remove", detail, 1)
        ok, detail = self._run_plain(["systemctl", "--user", "stop", DEFAULT_SERVICE_UNIT])
        if not ok:
            return UpdateResult(False, "scheduler-remove", detail, 1)
        removed: list[str] = []
        try:
            for name in (DEFAULT_TIMER_UNIT, DEFAULT_SERVICE_UNIT):
                (unit_dir / name).unlink(missing_ok=True)
                removed.append(name)
        except OSError as exc:
            detail = str(exc)
            rollback_ok, rollback_detail = self._rollback_scheduler_removal(
                unit_dir, units, removed
            )
            if not rollback_ok:
                detail += f"; scheduler rollback failed: {rollback_detail}"
            return UpdateResult(False, "scheduler-remove", detail, 1)
        ok, detail = self._run_plain(["systemctl", "--user", "daemon-reload"])
        if not ok:
            rollback_ok, rollback_detail = self._rollback_scheduler_removal(
                unit_dir, units, removed
            )
            if not rollback_ok:
                detail += f"; scheduler rollback failed: {rollback_detail}"
            return UpdateResult(False, "scheduler-remove", detail, 1)
        return UpdateResult(True, "scheduler-removed", "systemd-user update timer disabled", 0)

    def _rollback_scheduler_install(self, created: list[Path]) -> tuple[bool, str]:
        """Disable any partial install, remove only paths created here, and reload."""
        failures: list[str] = []
        ok, detail = self._run_plain(
            ["systemctl", "--user", "disable", "--now", DEFAULT_TIMER_UNIT]
        )
        if not ok and "not loaded" not in detail and "does not exist" not in detail:
            failures.append(detail)
        for path in reversed(created):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                failures.append(f"{path.name}: {exc}")
        ok, detail = self._run_plain(["systemctl", "--user", "daemon-reload"])
        if not ok:
            failures.append(detail)
        return not failures, "; ".join(failures)

    def _rollback_scheduler_removal(
        self, unit_dir: Path, units: dict[str, str], removed: list[str]
    ) -> tuple[bool, str]:
        """Restore the owned unit pair and enabled timer after a failed removal."""
        failures: list[str] = []
        for name in removed:
            try:
                self._atomic_write_text(unit_dir / name, units[name])
            except OSError as exc:
                failures.append(f"{name}: {exc}")
        if failures:
            return False, "; ".join(failures)
        for command in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", DEFAULT_TIMER_UNIT],
        ):
            ok, detail = self._run_plain(command)
            if not ok:
                failures.append(detail)
                break
        return not failures, "; ".join(failures)

    def _scheduler_units_preflight(
        self, units: dict[str, str], *, require_present: bool
    ) -> tuple[Path, bool, str | None]:
        """Validate the same-user systemd boundary and the complete canonical unit pair."""
        unit_dir, boundary_error = self.scheduler_context()
        if boundary_error:
            return unit_dir, False, boundary_error

        states: list[tuple[Path, os.stat_result | None]] = []
        for name in (DEFAULT_SERVICE_UNIT, DEFAULT_TIMER_UNIT):
            path = unit_dir / name
            try:
                metadata = path.lstat()
            except FileNotFoundError:
                metadata = None
            except OSError as exc:
                return unit_dir, False, f"cannot inspect scheduler unit {name}: {exc}"
            states.append((path, metadata))

        present = [metadata is not None for _path, metadata in states]
        if any(present) and not all(present):
            return unit_dir, False, "scheduler unit pair is partial"
        if not any(present):
            if require_present:
                return unit_dir, False, "scheduler unit pair is absent"
            return unit_dir, False, None

        uid = os.geteuid()
        for path, metadata in states:
            assert metadata is not None
            if not stat.S_ISREG(metadata.st_mode):
                return unit_dir, False, f"scheduler unit {path.name} is not a regular file"
            if metadata.st_uid != uid:
                return unit_dir, False, f"scheduler unit {path.name} has a foreign owner"
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                return unit_dir, False, f"cannot read scheduler unit {path.name}: {exc}"
            if content != units[path.name]:
                return unit_dir, False, f"scheduler unit {path.name} content does not match"
        return unit_dir, True, None

    @staticmethod
    def _scheduler_context() -> tuple[Path, str | None]:
        """Return the canonical unit directory only for one coherent user-manager identity."""
        uid = os.geteuid()
        try:
            passwd_home = Path(pwd.getpwuid(uid).pw_dir).resolve(strict=True)
        except (KeyError, OSError) as exc:
            return Path("."), f"cannot resolve passwd HOME for uid {uid}: {exc}"

        configured_home = os.environ.get("HOME")
        if not configured_home:
            return passwd_home, "HOME is not set"
        try:
            home = Path(configured_home).resolve(strict=True)
            home_metadata = home.stat()
        except OSError as exc:
            return passwd_home, f"cannot resolve HOME: {exc}"
        if (
            home != passwd_home
            or home_metadata.st_uid != uid
            or not stat.S_ISDIR(home_metadata.st_mode)
        ):
            return passwd_home, "HOME does not match the effective uid passwd directory"

        expected_runtime = Path("/run/user") / str(uid)
        configured_runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not configured_runtime:
            return home, "XDG_RUNTIME_DIR is not set"
        try:
            runtime = Path(configured_runtime).resolve(strict=True)
            runtime_metadata = runtime.stat()
            bus_metadata = (runtime / "bus").stat()
        except OSError as exc:
            return home, f"systemd-user runtime boundary is unavailable: {exc}"
        if (
            runtime != expected_runtime
            or runtime_metadata.st_uid != uid
            or not stat.S_ISDIR(runtime_metadata.st_mode)
            or bus_metadata.st_uid != uid
            or not stat.S_ISSOCK(bus_metadata.st_mode)
        ):
            return home, "XDG runtime and bus do not match the effective uid"

        expected_bus = f"unix:path={runtime / 'bus'}"
        if os.environ.get("DBUS_SESSION_BUS_ADDRESS") != expected_bus:
            return home, "DBUS session bus does not match XDG_RUNTIME_DIR"

        unit_dir = home / ".config" / "systemd" / "user"
        try:
            unit_dir.resolve(strict=False).relative_to(home)
        except (OSError, ValueError):
            return unit_dir, "scheduler unit directory escapes HOME"
        current = home
        for part in (".config", "systemd", "user"):
            current /= part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                break
            except OSError as exc:
                return unit_dir, f"cannot inspect scheduler unit directory: {exc}"
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != uid:
                return unit_dir, "scheduler unit directory is not an owned regular directory"
        return unit_dir, None

    @staticmethod
    def _unsupported_platform_data() -> dict[str, object] | None:
        """Report the scheduler boundary, which stays Linux systemd-user only."""
        if sys.platform.startswith(REQUIRED_UPDATE_PLATFORM):
            return None
        return {
            "platform": sys.platform,
            "required_platform": REQUIRED_UPDATE_PLATFORM,
            "service_manager": UPDATE_SERVICE_MANAGER,
            "recovery_command": UNSUPPORTED_PLATFORM_RECOVERY_COMMAND,
        }

    @staticmethod
    def _unsupported_platform_message() -> str:
        return (
            f"scheduled update mutations require Linux {UPDATE_SERVICE_MANAGER}; "
            f"current platform is {sys.platform}"
        )

    def _unsupported_platform_result(self) -> UpdateResult | None:
        data = self._unsupported_platform_data()
        if data is None:
            return None
        return UpdateResult(
            False,
            "unsupported-platform",
            self._unsupported_platform_message(),
            2,
            data=data,
        )

    @staticmethod
    def _unsupported_manual_platform_data() -> dict[str, object] | None:
        """Report the manual-apply boundary, which covers every supported service manager."""
        if sys.platform.startswith(MANUAL_UPDATE_PLATFORMS):
            return None
        return {
            "platform": sys.platform,
            "required_platforms": list(MANUAL_UPDATE_PLATFORMS),
            "service_managers": [DARWIN_SERVICE_MANAGER, UPDATE_SERVICE_MANAGER],
            "recovery_command": UNSUPPORTED_PLATFORM_RECOVERY_COMMAND,
        }

    @staticmethod
    def _unsupported_manual_platform_message() -> str:
        return (
            f"manual update mutations require Linux {UPDATE_SERVICE_MANAGER} or "
            f"macOS {DARWIN_SERVICE_MANAGER}; current platform is {sys.platform}"
        )

    def _unsupported_manual_platform_result(self) -> UpdateResult | None:
        data = self._unsupported_manual_platform_data()
        if data is None:
            return None
        return UpdateResult(
            False,
            "unsupported-platform",
            self._unsupported_manual_platform_message(),
            2,
            data=data,
        )

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
        current_wheels: list[dict[str, Any]] = []
        for raw_version, files in releases.items():
            try:
                candidate = Version(str(raw_version))
            except InvalidVersion:
                continue
            wheels = [
                wheel for wheel in _available_wheels(files) if candidate.major == current.major
            ]
            if candidate == current and not candidate.is_prerelease and wheels:
                current_wheels.extend(wheels)
            if candidate <= current or candidate.is_prerelease or candidate.major != current.major:
                continue
            if wheels:
                candidates.append((candidate, str(raw_version), wheels[0]))
        if not candidates:
            if current_wheels:
                valid, reason, filename, url, sha256, upload_time = _current_wheel_provenance(
                    current, current_wheels[0]
                )
                return ReleaseProvenance(
                    str(current),
                    None,
                    False,
                    reason,
                    project_url=PYPI_PROJECT_URL,
                    wheel_filename=filename,
                    wheel_url=url,
                    sha256=sha256,
                    upload_time=upload_time,
                    already_current=valid,
                    current_release=True,
                )
            return ReleaseProvenance(
                str(current),
                None,
                False,
                "no newer stable compatible-major wheel is published and installed version is not "
                "proven current",
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
        self,
        installation: Installation,
        provenance: ReleaseProvenance,
        watcher_active: bool,
        watcher_safe: bool,
        watcher_detail: str,
    ) -> str | None:
        if not watcher_safe:
            return watcher_detail
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

    def _watcher_status(self) -> WatcherDiscovery:
        discovery = self.service.discover()
        if not discovery.safe:
            return discovery
        active, detail = self.service.is_active()
        return WatcherDiscovery(
            unit=self.service.unit,
            active=active,
            safe=True,
            detail=discovery.detail or detail,
        )

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
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False, prefix=f".{path.name}."
            ) as handle:
                handle.write(content)
                temp_path = Path(handle.name)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _scheduler_path(installation: Installation) -> str:
        paths: list[str] = []
        if installation.kind in {"uv-tool", "pipx"} and installation.manager_command:
            manager = Path(installation.manager_command[0])
            if manager.is_absolute():
                manager_dir = str(manager.parent)
                if ":" in manager_dir or _ASCII_CONTROL.search(manager_dir):
                    raise ValueError(
                        "scheduler manager directory contains a colon or ASCII control character"
                    )
                paths.append(manager_dir)
        paths.extend(SYSTEMD_BASELINE_PATH)
        return ":".join(dict.fromkeys(paths))

    @staticmethod
    def _scheduled_up_to_date(installation: Installation, provenance: ReleaseProvenance) -> bool:
        return installation.supported and provenance.already_current
