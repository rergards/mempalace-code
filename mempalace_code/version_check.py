"""
Opt-in periodic PyPI version check for mempalace-code.

All I/O is injectable for testing:
  time_fn      — returns current time as float (default: time.time)
  is_tty_fn    — returns True when stdin/stdout/stderr are all TTYs
  prompt_fn    — prints the first-run prompt and returns the user's answer
  stderr_fn    — writes a string to stderr
  fetch_fn     — fetches the latest version string from PyPI
  stdout_fn    — writes a string to stdout (for check-now)

State is stored in ~/.mempalace/version_check.json, separate from config.json.
Config is read via MempalaceConfig (version_check_enabled, version_check_interval_hours).
Env override: MEMPALACE_VERSION_CHECK=1/0, MEMPALACE_VERSION_CHECK_INTERVAL_HOURS=N.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

PYPI_URL = "https://pypi.org/pypi/mempalace-code/json"
DEFAULT_INTERVAL_HOURS = 168
STATE_FILE_NAME = "version_check.json"


@dataclass
class VersionCheckConfig:
    """Resolved effective configuration for version checks."""

    enabled: Optional[bool]
    source: str  # "env", "config", "state", or "default"
    interval_hours: int
    pypi_url: str = PYPI_URL


@dataclass
class VersionCheckState:
    """Mutable state stored in ~/.mempalace/version_check.json."""

    enabled: Optional[bool] = None
    last_check_ts: Optional[float] = None
    last_error_ts: Optional[float] = None


def _mempalace_dir() -> Path:
    return Path(os.path.expanduser("~/.mempalace"))


def _state_file(config_dir: Optional[Path] = None) -> Path:
    return (config_dir if config_dir is not None else _mempalace_dir()) / STATE_FILE_NAME


def load_state(config_dir: Optional[Path] = None) -> VersionCheckState:
    """Load mutable state from ~/.mempalace/version_check.json."""
    path = _state_file(config_dir)
    if not path.exists():
        return VersionCheckState()
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return VersionCheckState()
        return VersionCheckState(
            enabled=data.get("enabled"),
            last_check_ts=data.get("last_check_ts"),
            last_error_ts=data.get("last_error_ts"),
        )
    except (json.JSONDecodeError, OSError, TypeError):
        return VersionCheckState()


def save_state(state: VersionCheckState, config_dir: Optional[Path] = None) -> None:
    """Atomically write state to ~/.mempalace/version_check.json."""
    dir_ = config_dir if config_dir is not None else _mempalace_dir()
    try:
        dir_.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    path = _state_file(config_dir)
    tmp_path = path.with_suffix(".json.tmp")
    data: dict = {}
    if state.enabled is not None:
        data["enabled"] = state.enabled
    if state.last_check_ts is not None:
        data["last_check_ts"] = state.last_check_ts
    if state.last_error_ts is not None:
        data["last_error_ts"] = state.last_error_ts
    try:
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        tmp_path.replace(path)
    except OSError:
        pass


def resolve_config(config_dir: Optional[Path] = None) -> VersionCheckConfig:
    """Resolve effective version-check configuration.

    Precedence: MEMPALACE_VERSION_CHECK env > config file key > state file > default (None).
    Invalid env values fail closed (disabled) rather than raising during CLI startup.
    """
    from .config import MempalaceConfig

    cfg = MempalaceConfig(config_dir=config_dir) if config_dir is not None else MempalaceConfig()

    env_raw = os.environ.get("MEMPALACE_VERSION_CHECK")
    if env_raw is not None:
        enabled: Optional[bool] = env_raw.strip() in ("1", "true", "yes")
        source = "env"
    elif cfg.version_check_enabled is not None:
        enabled = cfg.version_check_enabled
        source = "config"
    else:
        state = load_state(config_dir)
        if state.enabled is not None:
            enabled = state.enabled
            source = "state"
        else:
            enabled = None
            source = "default"

    return VersionCheckConfig(
        enabled=enabled,
        source=source,
        interval_hours=cfg.version_check_interval_hours,
    )


def fetch_latest_version(url: str = PYPI_URL, timeout: int = 5) -> str:
    """Fetch the latest version from PyPI. Returns version string or raises."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "mempalace-code/version-check"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return str(data["info"]["version"])


def compare_versions(current: str, latest: str) -> int:
    """Compare two PEP 440 versions. Returns -1, 0, or 1.

    Falls back to lexicographic comparison if packaging is unavailable.
    """
    try:
        from packaging.version import Version

        c = Version(current)
        la = Version(latest)
        if c < la:
            return -1
        elif c > la:
            return 1
        return 0
    except Exception:
        if current < latest:
            return -1
        elif current > latest:
            return 1
        return 0


def _all_ttys() -> bool:
    """Return True when stdin, stdout, and stderr are all TTYs."""
    try:
        return sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()
    except AttributeError:
        return False


def _default_prompt_fn() -> str:
    """Print the first-run prompt to stderr and read the user's answer from stdin."""
    print(
        "\nmempalace-code: Enable periodic new-version checks? "
        "This contacts PyPI for package metadata only. [y/N] ",
        end="",
        file=sys.stderr,
        flush=True,
    )
    try:
        line = sys.stdin.readline()
        return line.strip()
    except (EOFError, OSError):
        return ""


def should_prompt_first_run(
    command: Optional[str],
    config: VersionCheckConfig,
    is_tty_fn: Callable[[], bool] = _all_ttys,
) -> bool:
    """True when a first-run opt-in prompt should be shown.

    Guards: real subcommand, no existing choice, all three streams are TTYs.
    Never prompts for the version-check command itself, no-command help, or --help.
    """
    if not command:
        return False
    if command == "version-check":
        return False
    if config.enabled is not None:
        return False
    return is_tty_fn()


def run_first_run_prompt(
    state: VersionCheckState,
    config_dir: Optional[Path] = None,
    prompt_fn: Callable[[], str] = _default_prompt_fn,
    stderr_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """Ask the user whether to enable periodic version checks. Persists the choice.

    Returns True if the user opted in.
    """
    _stderr = (
        stderr_fn if stderr_fn is not None else (lambda s: print(s, file=sys.stderr, flush=True))
    )

    try:
        answer = prompt_fn().lower()
    except Exception:
        answer = ""

    enabled = answer in ("y", "yes")
    state.enabled = enabled
    save_state(state, config_dir)

    if enabled:
        _stderr(
            "  Version checks enabled. "
            "Run 'mempalace-code version-check --status' to view settings."
        )
    else:
        _stderr("  Opted out. Run 'mempalace-code version-check --enable' to opt in later.")
    return enabled


def _interval_due(state: VersionCheckState, config: VersionCheckConfig, now: float) -> bool:
    """Return True when enough time has passed since the last automatic check."""
    if state.last_check_ts is None:
        return True
    elapsed_hours = (now - state.last_check_ts) / 3600.0
    return elapsed_hours >= config.interval_hours


def run_automatic_check(
    current_version: str,
    config: VersionCheckConfig,
    state: VersionCheckState,
    config_dir: Optional[Path] = None,
    time_fn: Callable[[], float] = time.time,
    fetch_fn: Optional[Callable[[], str]] = None,
    stderr_fn: Optional[Callable[[str], None]] = None,
) -> None:
    """Run an automatic background version check when opted-in and interval is due.

    Hints to stderr only; never raises; rate-limits errors so failures don't retry every command.
    """
    _fetch = fetch_fn if fetch_fn is not None else (lambda: fetch_latest_version())
    _stderr = (
        stderr_fn if stderr_fn is not None else (lambda s: print(s, file=sys.stderr, flush=True))
    )

    now = time_fn()

    if not _interval_due(state, config, now):
        return

    try:
        latest = _fetch()
    except Exception:
        state.last_check_ts = now
        state.last_error_ts = now
        save_state(state, config_dir)
        return

    state.last_check_ts = now
    save_state(state, config_dir)

    if compare_versions(current_version, latest) < 0:
        _stderr(
            f"\n[mempalace-code] New version available: {latest} "
            f"(you have {current_version})\n"
            f"  Upgrade: pip install --upgrade mempalace-code\n"
        )


def run_check_now(
    current_version: str,
    fetch_fn: Optional[Callable[[], str]] = None,
    stdout_fn: Optional[Callable[[str], None]] = None,
) -> None:
    """Run an explicit version check, printing results or network errors to stdout."""
    _fetch = fetch_fn if fetch_fn is not None else (lambda: fetch_latest_version())
    _stdout = stdout_fn if stdout_fn is not None else (lambda s: print(s, flush=True))

    _stdout(f"  Current version:  {current_version}")
    _stdout(f"  PyPI URL:         {PYPI_URL}")

    try:
        latest = _fetch()
    except urllib.error.URLError as exc:
        _stdout(f"  Network error:    {exc}")
        _stdout("  Could not reach PyPI. Check your internet connection.")
        return
    except Exception as exc:
        _stdout(f"  Error fetching PyPI metadata: {exc}")
        return

    _stdout(f"  Latest version:   {latest}")
    cmp = compare_versions(current_version, latest)
    if cmp < 0:
        _stdout(f"\n  A newer version is available: {latest}")
        _stdout("  Upgrade: pip install --upgrade mempalace-code")
    elif cmp > 0:
        _stdout("\n  You are running a version ahead of PyPI.")
    else:
        _stdout("\n  You are up to date.")
