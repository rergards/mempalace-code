#!/usr/bin/env python3
"""release_install_metadata_smoke.py — Prove installed metadata, module, and CLI status agree.

Stdlib-only — no project imports, no third-party dependencies.

Usage:
    python scripts/release_install_metadata_smoke.py --install-spec . --json
    python scripts/release_install_metadata_smoke.py --install-spec mempalace-code==1.2.3
    python scripts/release_install_metadata_smoke.py --installer pipx --install-spec mempalace-code==1.2.3
    python scripts/release_install_metadata_smoke.py --installer uv-tool --install-spec mempalace-code==1.2.3
    python scripts/release_install_metadata_smoke.py --installer bootstrap-venv --install-spec mempalace-code==1.2.3

Installs mempalace-code into a disposable environment (a fresh venv by default,
or a disposable pipx/uv-tool/bootstrap-venv environment) and compares installed
version and provenance surfaces:
  1. importlib.metadata.version("mempalace-code")  (installed package metadata)
  2. mempalace_code.__version__                     (imported module)
  3. `mempalace-code version-check --status`         (installed console script)
  4. `mempalace-code install-alias` provenance       (legacy alias target)
  5. ordinary package import, CLI help, and LanceDB read-only open while
     chromadb imports are blocked

Probes run from neutral temporary working directories outside the source tree
so a source checkout's pyproject.toml or ambient PATH entry cannot shadow the
installed package.

Exits 0 only when every required surface passes and all versioned surfaces agree.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    RunSubprocess = Callable[..., tuple[int, str, str]]

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_PACKAGE = "mempalace-code"
MODULE_NAME = "mempalace_code"
CONSOLE_SCRIPT = "mempalace-code"
ALIAS_INSTALLER_SCRIPT = "mempalace-code-alias"
AGENT_PLUGIN_MCP_SCRIPT = "mempalace-code-mcp"
DEFAULT_TIMEOUT_SECONDS = 300
DEFAULT_INSTALL_TIMEOUT_SECONDS = 600

INSTALLER_VENV = "venv"
INSTALLER_PIPX = "pipx"
INSTALLER_UV_TOOL = "uv-tool"
INSTALLER_BOOTSTRAP_VENV = "bootstrap-venv"
INSTALLERS = (
    INSTALLER_VENV,
    INSTALLER_BOOTSTRAP_VENV,
    INSTALLER_PIPX,
    INSTALLER_UV_TOOL,
)
MISSING_TOOL_RECOVERY = {
    INSTALLER_PIPX: "python -m pip install pipx",
    INSTALLER_UV_TOOL: "python -m pip install uv",
}

SURFACE_INSTALL = "install"
SURFACE_METADATA = "package_metadata"
SURFACE_MODULE = "module_version"
SURFACE_CLI = "cli_version_check"
SURFACE_ALIAS_PROVENANCE = "alias_provenance"
SURFACE_AGENT_PLUGIN = "agent_plugin"
SURFACE_RUNTIME_NO_CHROMADB = "ordinary_runtime_no_chromadb"
SURFACE_RECOVERY_SAFETY = "no_model_recovery"
SURFACE_VERSION_CHECK_NETWORK = "version_check_no_network"
SURFACE_UPDATE_PLATFORM = "unsupported_platform_updates"
SURFACE_LINUX_SYSTEMD_LIFECYCLE = "linux_systemd_update_lifecycle"

LIFECYCLE_STATUS_PASS = "pass"
LIFECYCLE_STATUS_FAIL = "fail"
LIFECYCLE_STATUS_UNRUN = "unrun"
LIFECYCLE_AUTHORITY_ENV = "MEMPALACE_RELEASE_SYSTEMD_USER"
LIFECYCLE_RECOVERY_COMMAND = (
    "MEMPALACE_RELEASE_SYSTEMD_USER=1 python "
    "scripts/release_install_metadata_smoke.py --all-installers "
    "--install-spec dist/mempalace_code-*.whl --json"
)

REQUIRED_SURFACES = [
    SURFACE_METADATA,
    SURFACE_MODULE,
    SURFACE_CLI,
    SURFACE_ALIAS_PROVENANCE,
    SURFACE_AGENT_PLUGIN,
    SURFACE_RUNTIME_NO_CHROMADB,
]

STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_ERROR = "error"

_CURRENT_VERSION_RE = re.compile(r"^\s*Current version:\s*(\S+)\s*$", re.MULTILINE)
_PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
_MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
_MINIMAL_TOOLS = (
    "mempalace_status",
    "mempalace_search",
    "mempalace_check_duplicate",
    "mempalace_add_drawer",
)
_REQUIRED_AGENT_PLUGIN_FILES = (
    "plugin.json",
    "mcp.json",
    "skills/mempalace/SKILL.md",
    "schemas/1.0.0/plugin.schema.json",
    "schemas/1.0.0/mcp.schema.json",
    "schemas/SCHEMA-NOTICE.md",
)
_SOURCE_ROOT = Path(__file__).resolve().parent.parent

_PROBE_SCRIPT = (
    "import importlib.metadata\n"
    "try:\n"
    "    print('METADATA=' + importlib.metadata.version('mempalace-code'))\n"
    "except Exception as exc:\n"
    "    print('METADATA-ERROR=' + str(exc))\n"
    "try:\n"
    "    import mempalace_code\n"
    "    print('MODULE=' + mempalace_code.__version__)\n"
    "    print('MODULE-FILE=' + str(mempalace_code.__file__))\n"
    "except Exception as exc:\n"
    "    print('MODULE-ERROR=' + str(exc))\n"
)

_EXTRA_METADATA_OUTPUT_LIMIT = 32 * 1024
_EXTRA_METADATA_ENTRY_LIMIT = 32
_EXTRA_METADATA_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_EXTRA_METADATA_PROBE_SCRIPT = (
    "import importlib.metadata, json\n"
    "dist = importlib.metadata.distribution('mempalace-code')\n"
    "print(json.dumps({\n"
    "    'version': dist.version,\n"
    "    'root': str(dist.locate_file('')),\n"
    "    'provides_extra': dist.metadata.get_all('Provides-Extra'),\n"
    "}, separators=(',', ':')))\n"
)

_RUNTIME_NO_CHROMADB_PROBE_SCRIPT = (
    "import builtins\n"
    "import sys\n"
    "import tempfile\n"
    "_orig_import = builtins.__import__\n"
    "def _guard(name, globals=None, locals=None, fromlist=(), level=0):\n"
    "    if name == 'chromadb' or name.startswith('chromadb.'):\n"
    "        raise RuntimeError('chromadb import blocked during ordinary runtime probe')\n"
    "    return _orig_import(name, globals, locals, fromlist, level)\n"
    "builtins.__import__ = _guard\n"
    "import mempalace_code\n"
    "from mempalace_code.storage import open_store\n"
    "with tempfile.TemporaryDirectory(prefix='mempalace-runtime-probe-') as palace:\n"
    "    store = open_store(palace, backend='lance', create=False, read_only=True)\n"
    "    assert store.count() == 0\n"
    "from mempalace_code import cli\n"
    "sys.argv = ['mempalace-code']\n"
    "cli.main()\n"
    "print('RUNTIME-NO-CHROMADB=ok')\n"
)

# ── Sanitization (mirrors scripts/release_status_gate.py) ─────────────────────

_TOKEN_RE = re.compile(
    r"\b(?:[g]hp_|[g]ithub_pat_|[p]ypi-)[A-Za-z0-9_\-]{4,}\S*",
    re.IGNORECASE,
)
_PATH_RE = re.compile(
    r"(/(?:Users|home|root|tmp)/[^\s:,\"']*|/(?:private/)?var/folders/[^\s:,\"']*)"
)
_PRIVATE_REMOTE_RE = re.compile(r"git@[a-zA-Z0-9._-]+:[^\s\"']+")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?:^|[?&])(?:access[_-]?token|api[_-]?key|auth|credential|password|secret|token)=[^&]*",
    re.IGNORECASE,
)


def sanitize(
    text: str,
    *,
    known_secrets: Iterable[str] = (),
    local_paths: Iterable[str | Path] = (),
) -> str:
    """Remove credentials and concrete local paths from retained diagnostics."""
    sanitized = text
    for secret in sorted({value for value in known_secrets if value}, key=len, reverse=True):
        sanitized = sanitized.replace(secret, "[REDACTED-SECRET]")
    for path in sorted({str(value) for value in local_paths if str(value)}, key=len, reverse=True):
        sanitized = sanitized.replace(path, "[REDACTED-PATH]")

    def redact_url(match: re.Match[str]) -> str:
        value = match.group(0)
        authority = value.split("://", 1)[1].split("/", 1)[0]
        if "@" in authority or _SENSITIVE_QUERY_RE.search(value):
            return "[REDACTED-URL]"
        return value

    sanitized = _URL_RE.sub(redact_url, sanitized)
    return _PRIVATE_REMOTE_RE.sub(
        "[REDACTED-REMOTE]",
        _PATH_RE.sub("[REDACTED-PATH]", _TOKEN_RE.sub("[REDACTED-TOKEN]", sanitized)),
    )


# ── Result types ────────────────────────────────────────────────────────────────


@dataclass
class SurfaceResult:
    name: str
    status: str  # ok | fail | error
    detail: str
    version: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "version": self.version,
        }


@dataclass
class SmokeResult:
    ok: bool
    expected_version: str | None
    installer: str
    install_spec: str
    surfaces: list[SurfaceResult] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    manager: str | None = None
    update_eligible: bool | None = None
    lifecycle: LinuxSystemdLifecycleResult | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "expected_version": self.expected_version,
            "installer": self.installer,
            "install_spec": self.install_spec,
            "surfaces": [s.to_dict() for s in self.surfaces],
            "diagnostics": self.diagnostics,
            "manager": self.manager,
            "update_eligible": self.update_eligible,
        }


@dataclass
class LinuxSystemdLifecycleResult:
    status: str
    detail: str
    evidence: dict[str, object] = field(default_factory=dict)
    recovery_command: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == LIFECYCLE_STATUS_PASS

    def to_dict(self) -> dict[str, object]:
        return {
            "name": SURFACE_LINUX_SYSTEMD_LIFECYCLE,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
            "recovery_command": self.recovery_command,
        }


@dataclass
class AggregateSmokeResult:
    ok: bool
    install_spec: str
    results: list[SmokeResult] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    linux_systemd_update_lifecycle: LinuxSystemdLifecycleResult | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "install_spec": self.install_spec,
            "installers": [result.to_dict() for result in self.results],
            "diagnostics": self.diagnostics,
            SURFACE_LINUX_SYSTEMD_LIFECYCLE: (
                self.linux_systemd_update_lifecycle.to_dict()
                if self.linux_systemd_update_lifecycle is not None
                else None
            ),
        }


@dataclass(frozen=True)
class CandidateExtraMetadata:
    """Strict candidate-wheel optional-extra discovery for downstream release gates."""

    ok: bool
    extras: tuple[str, ...] = ()
    runtime_extras: tuple[str, ...] = ()
    version: str | None = None
    detail: str = ""


# ── Reinstall guidance ────────────────────────────────────────────────────────


def build_reinstall_commands(package: str, install_spec: str) -> list[str]:
    """Generic, public-safe reinstall commands for stale pipx/uv-tool/venv installs."""
    pinned = install_spec if "==" in install_spec else None
    pip_target = pinned or package
    return [
        f"python -m pip install --upgrade --force-reinstall {pip_target}",
        f"pipx reinstall {package}",
        f"uv tool install --force {pinned or package}",
    ]


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _credential_free_env() -> dict[str, str]:
    """Return the small environment needed by disposable install probes."""
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "PIP_KEYRING_PROVIDER": "disabled",
        "MEMPALACE_VERSION_CHECK": "0",
    }
    for name in ("LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "SYSTEMROOT", "WINDIR"):
        value = os.environ.get(name)
        if value:
            env[name] = value
    return env


def _env_with_script_dir(script_dir: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(_credential_free_env() if base is None else base)
    current_path = env.get("PATH", "")
    env["PATH"] = (
        str(script_dir) if not current_path else str(script_dir) + os.pathsep + current_path
    )
    return env


def _isolate_probe_state(env: dict[str, str], root: Path, script_dir: Path) -> dict[str, str]:
    """Confine all user and tool state while retaining system tools needed by installers."""
    isolated = dict(env)
    state_dirs = {
        "HOME": root / "home",
        "USERPROFILE": root / "home",
        "XDG_CACHE_HOME": root / "xdg-cache",
        "XDG_CONFIG_HOME": root / "xdg-config",
        "XDG_DATA_HOME": root / "xdg-data",
        "PIP_CACHE_DIR": root / "pip-cache",
        "HF_HOME": root / "hf-cache",
        "TRANSFORMERS_CACHE": root / "transformers-cache",
    }
    for name, path in state_dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        isolated[name] = str(path)
    isolated["PATH"] = os.pathsep.join((str(script_dir), os.defpath))
    return isolated


def _snapshot_tree(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    snapshot = []
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_symlink():
            snapshot.append((relative, "symlink", os.readlink(path).encode()))
        elif path.is_file():
            snapshot.append((relative, "file", path.read_bytes()))
        elif path.is_dir():
            snapshot.append((relative, "dir", b""))
    return tuple(snapshot)


def _snapshot_mutable_state(env: dict[str, str]) -> tuple[tuple[str, object], ...]:
    names = (
        "HOME",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "PIP_CACHE_DIR",
        "HF_HOME",
        "TRANSFORMERS_CACHE",
        "PIPX_HOME",
        "UV_CACHE_DIR",
    )
    snapshots = []
    for name in names:
        value = env.get(name)
        if value:
            snapshots.append((name, _snapshot_tree(Path(value))))
    return tuple(snapshots)


_RENDER_SCHEDULER_UNITS_SCRIPT = (
    "import json; from mempalace_code.updater import UpdateManager; "
    "print(json.dumps(UpdateManager().render_scheduler_units(), sort_keys=True))"
)

_CANDIDATE_INSTALL_SNAPSHOT_SCRIPT = """\
import hashlib
import json
from importlib import metadata

dist = metadata.distribution("mempalace-code")
digest = hashlib.sha256()
count = 0
for item in sorted(dist.files or (), key=str):
    path = dist.locate_file(item)
    if path.is_file():
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\\0")
        digest.update(path.read_bytes())
        count += 1
print(json.dumps({"version": dist.version, "sha256": digest.hexdigest(), "files": count}))
"""


def _linux_systemd_boundary(
    console_bin: str, env: dict[str, str]
) -> tuple[dict[str, object] | None, str | None]:
    """Admit only an explicit exact-console disposable-user contour."""
    if not sys.platform.startswith("linux"):
        return None, "supported Linux evidence is unavailable on this platform"
    if env.get(LIFECYCLE_AUTHORITY_ENV) != "1":
        return None, f"{LIFECYCLE_AUTHORITY_ENV}=1 disposable-user authority is required"
    uid = os.geteuid()
    try:
        passwd_home = Path(pwd.getpwuid(uid).pw_dir).resolve(strict=True)
        home = Path(env["HOME"]).resolve(strict=True)
    except (KeyError, OSError) as exc:
        return None, f"disposable-user HOME is unavailable: {sanitize(str(exc))}"
    if home != passwd_home or home.stat().st_uid != uid or not home.is_dir():
        return None, "HOME does not match the effective uid passwd directory"
    console = Path(console_bin)
    if not console.is_absolute() or not console.exists():
        return None, "the selected installed console is not an existing absolute path"
    return {
        "uid_match": True,
        "home_match": True,
        "absolute_installed_console": True,
        "home": home,
    }, None


def _lifecycle_snapshot(home: Path) -> tuple[object, object]:
    return (
        _snapshot_tree(home / ".mempalace"),
        _snapshot_tree(home / ".config" / "systemd" / "user"),
    )


def _candidate_install_snapshot(
    python_bin: str,
    *,
    env: dict[str, str],
    cwd: str,
    run_subprocess: RunSubprocess,
) -> dict[str, object] | None:
    rc, out, err = run_subprocess(
        [python_bin, "-c", _CANDIDATE_INSTALL_SNAPSHOT_SCRIPT], env=env, cwd=cwd
    )
    if rc != 0 or err or len(out.encode("utf-8")) > 4096:
        return None
    try:
        payload = json.loads(out)
    except (json.JSONDecodeError, TypeError, UnicodeError):
        return None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("version"), str)
        or not isinstance(payload.get("sha256"), str)
        or len(payload["sha256"]) != 64
        or not isinstance(payload.get("files"), int)
        or payload["files"] <= 0
    ):
        return None
    return payload


def _json_command(
    args: list[str],
    *,
    env: dict[str, str],
    cwd: str,
    run_subprocess: RunSubprocess,
) -> tuple[int, dict[str, object] | None, str]:
    rc, out, err = run_subprocess(args, env=env, cwd=cwd)
    if len(out.encode("utf-8")) > 32 * 1024 or len(err.encode("utf-8")) > 8 * 1024:
        return rc, None, "command returned oversized diagnostics"
    try:
        payload = json.loads(out)
    except (json.JSONDecodeError, TypeError, UnicodeError):
        payload = None
    diagnostic = err if isinstance(payload, dict) else err or out
    return rc, payload if isinstance(payload, dict) else None, sanitize(diagnostic.strip())


def _systemd_properties(output: str) -> dict[str, str]:
    return {
        key: value
        for line in output.splitlines()
        if "=" in line
        for key, value in (line.split("=", 1),)
    }


def run_linux_systemd_update_lifecycle(
    console_bin: str,
    python_bin: str,
    expected_version: str | None,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str],
    *,
    boundary_probe: Callable[
        [str, dict[str, str]], tuple[dict[str, object] | None, str | None]
    ] = _linux_systemd_boundary,
) -> LinuxSystemdLifecycleResult:
    """Qualify one exact installed manager and its real same-user systemd lifecycle."""
    boundary, unavailable = boundary_probe(console_bin, env)
    if boundary is None:
        return LinuxSystemdLifecycleResult(
            LIFECYCLE_STATUS_UNRUN,
            sanitize(unavailable or "same-user systemd evidence is unavailable"),
            recovery_command=LIFECYCLE_RECOVERY_COMMAND,
        )
    home_value = boundary.get("home")
    if not isinstance(home_value, Path) or expected_version is None:
        return LinuxSystemdLifecycleResult(
            LIFECYCLE_STATUS_FAIL,
            "candidate attribution or verified HOME is missing",
        )
    home = home_value
    unit_dir = home / ".config" / "systemd" / "user"
    marker_value = env.get("MEMPALACE_SOCKET_GUARD_LOADED")
    attempts_value = env.get("MEMPALACE_SOCKET_ATTEMPTS")
    if not marker_value or not attempts_value:
        return LinuxSystemdLifecycleResult(
            LIFECYCLE_STATUS_FAIL,
            "installed network guard evidence paths are missing",
        )
    marker = Path(marker_value)
    attempts = Path(attempts_value)
    installed = False
    cleanup_ok = False
    evidence: dict[str, object] = {
        key: value for key, value in boundary.items() if isinstance(value, bool)
    }

    def fail(detail: str) -> LinuxSystemdLifecycleResult:
        return LinuxSystemdLifecycleResult(
            LIFECYCLE_STATUS_FAIL, sanitize(detail), evidence=evidence
        )

    result: LinuxSystemdLifecycleResult | None = None
    try:
        baseline = _lifecycle_snapshot(home)
        candidate_baseline = _candidate_install_snapshot(
            python_bin, env=env, cwd=probe_cwd, run_subprocess=run_subprocess
        )
        if candidate_baseline is None or candidate_baseline.get("version") != expected_version:
            return fail("installed candidate package snapshot is unavailable")
        boundary_unit = f"mempalace-release-boundary-{os.getpid()}"
        rc, manager_home, manager_error = run_subprocess(
            [
                "systemd-run",
                "--user",
                "--wait",
                "--pipe",
                "--collect",
                f"--unit={boundary_unit}",
                "/usr/bin/printenv",
                "HOME",
            ],
            env=env,
            cwd=probe_cwd,
        )
        if rc != 0 or manager_error or manager_home.strip() != str(home):
            return LinuxSystemdLifecycleResult(
                LIFECYCLE_STATUS_UNRUN,
                "systemd-user manager HOME does not match the disposable user",
                evidence=evidence,
                recovery_command=LIFECYCLE_RECOVERY_COMMAND,
            )
        evidence["manager_home_match"] = True
        rc, status, detail = _json_command(
            [console_bin, "update", "status", "--json"],
            env=env,
            cwd=probe_cwd,
            run_subprocess=run_subprocess,
        )
        provenance = status.get("provenance") if isinstance(status, dict) else None
        if (
            rc != 0
            or detail
            or status is None
            or status.get("ok") is not True
            or status.get("stage") != "status"
            or not isinstance(provenance, dict)
            or provenance.get("current_version") != expected_version
            or _lifecycle_snapshot(home) != baseline
            or _candidate_install_snapshot(
                python_bin, env=env, cwd=probe_cwd, run_subprocess=run_subprocess
            )
            != candidate_baseline
        ):
            return fail(detail or "update status failed exact-candidate read-only semantics")
        evidence["candidate_version"] = expected_version
        evidence["status_read_only"] = True

        rc, refusal, detail = _json_command(
            [console_bin, "update", "apply", "--json"],
            env=env,
            cwd=probe_cwd,
            run_subprocess=run_subprocess,
        )
        if (
            rc != 2
            or detail
            or refusal is None
            or refusal.get("stage") != "confirmation"
            or refusal.get("recovery_command") != "mempalace-code update apply --yes --json"
            or _lifecycle_snapshot(home) != baseline
            or _candidate_install_snapshot(
                python_bin, env=env, cwd=probe_cwd, run_subprocess=run_subprocess
            )
            != candidate_baseline
        ):
            return fail(detail or "unconfirmed update apply was not an exact read-only refusal")
        evidence["confirmation_read_only"] = True

        rc, install, detail = _json_command(
            [console_bin, "update", "scheduler", "install", "--yes", "--json"],
            env=env,
            cwd=probe_cwd,
            run_subprocess=run_subprocess,
        )
        installed = (
            rc == 0 and install is not None and install.get("stage") == "scheduler-installed"
        )
        if not installed:
            return fail(detail or "scheduler install did not return scheduler-installed")

        rc, rendered_out, rendered_err = run_subprocess(
            [python_bin, "-c", _RENDER_SCHEDULER_UNITS_SCRIPT], env=env, cwd=probe_cwd
        )
        try:
            rendered = json.loads(rendered_out)
        except json.JSONDecodeError:
            rendered = None
        if rc != 0 or not isinstance(rendered, dict):
            return fail(rendered_err or "installed scheduler renderer did not return JSON")
        for name, content in rendered.items():
            path = unit_dir / str(name)
            if not isinstance(content, str) or not path.is_file() or path.read_text() != content:
                return fail(f"manager unit content mismatch for {name}")
            rc, shown, err = run_subprocess(
                [
                    "systemctl",
                    "--user",
                    "show",
                    str(name),
                    "--property=FragmentPath,LoadState,ActiveState,UnitFileState",
                ],
                env=env,
                cwd=probe_cwd,
            )
            properties = _systemd_properties(shown)
            if (
                rc != 0
                or properties.get("FragmentPath") != str(path)
                or properties.get("LoadState") != "loaded"
                or (
                    name == "mempalace-update.timer"
                    and (
                        properties.get("ActiveState") != "active"
                        or properties.get("UnitFileState") != "enabled"
                    )
                )
            ):
                return fail(err or f"systemd FragmentPath mismatch for {name}")
        for command in (
            ["systemctl", "--user", "is-enabled", "mempalace-update.timer"],
            ["systemctl", "--user", "is-active", "mempalace-update.timer"],
        ):
            rc, _out, err = run_subprocess(command, env=env, cwd=probe_cwd)
            if rc != 0:
                return fail(err or f"manager state check failed: {' '.join(command)}")
        evidence.update(
            {"fragment_content_match": True, "timer_enabled": True, "timer_active": True}
        )

        before_repeat = {name: (unit_dir / name).read_bytes() for name in rendered}
        rc, repeated, detail = _json_command(
            [console_bin, "update", "scheduler", "install", "--yes", "--json"],
            env=env,
            cwd=probe_cwd,
            run_subprocess=run_subprocess,
        )
        if (
            rc != 0
            or repeated is None
            or repeated.get("stage") != "scheduler-installed"
            or before_repeat != {name: (unit_dir / name).read_bytes() for name in rendered}
        ):
            return fail(detail or "repeated scheduler install changed the owned unit pair")
        evidence["repeat_idempotent"] = True

        rc, removed, detail = _json_command(
            [console_bin, "update", "scheduler", "remove", "--yes", "--json"],
            env=env,
            cwd=probe_cwd,
            run_subprocess=run_subprocess,
        )
        installed = False
        if (
            rc != 0
            or removed is None
            or removed.get("stage") != "scheduler-removed"
            or any((unit_dir / name).exists() for name in rendered)
        ):
            return fail(detail or "scheduler removal did not remove the complete owned pair")
        for command, allowed in (
            (
                ["systemctl", "--user", "is-enabled", "mempalace-update.timer"],
                {"disabled", "not-found", ""},
            ),
            (
                ["systemctl", "--user", "is-active", "mempalace-update.timer"],
                {"inactive", "unknown", ""},
            ),
        ):
            rc, out, err = run_subprocess(command, env=env, cwd=probe_cwd)
            if rc == 0 or out.strip() not in allowed:
                return fail(err or f"removed manager state remained live: {' '.join(command)}")
        for name in rendered:
            rc, shown, err = run_subprocess(
                [
                    "systemctl",
                    "--user",
                    "show",
                    str(name),
                    "--property=FragmentPath,LoadState",
                ],
                env=env,
                cwd=probe_cwd,
            )
            properties = _systemd_properties(shown)
            if (
                rc != 0
                or properties.get("FragmentPath", "") != ""
                or properties.get("LoadState") != "not-found"
            ):
                return fail(err or f"removed manager unit remained loaded: {name}")
        evidence["confirmed_removal"] = True

        before_apply = _lifecycle_snapshot(home)
        attempts.unlink(missing_ok=True)
        rc, applied, detail = _json_command(
            [console_bin, "update", "apply", "--yes", "--json"],
            env=env,
            cwd=probe_cwd,
            run_subprocess=run_subprocess,
        )
        safe_preflight = (
            rc == 2
            and not detail
            and applied is not None
            and applied.get("ok") is False
            and applied.get("stage") == "preflight"
            and any(
                marker in str(applied.get("message", ""))
                for marker in (
                    "PyPI provenance unavailable",
                    "not proven current",
                    "no newer stable compatible-major wheel",
                )
            )
            and _lifecycle_snapshot(home) == before_apply
            and _candidate_install_snapshot(
                python_bin, env=env, cwd=probe_cwd, run_subprocess=run_subprocess
            )
            == candidate_baseline
            and marker.is_file()
            and attempts.is_file()
            and "pypi.org" in attempts.read_text(encoding="utf-8")
        )
        if not safe_preflight:
            return fail(detail or "confirmed apply escaped the blocked-network preflight boundary")
        evidence["apply_terminal_stage"] = applied.get("stage") if applied else None
        evidence["package_snapshot_unchanged"] = True
        evidence["network_attempt_blocked"] = True
        evidence["unauthorized_mutation"] = False
        result = LinuxSystemdLifecycleResult(
            LIFECYCLE_STATUS_PASS,
            "exact candidate scheduler and bounded update lifecycle passed",
            evidence=evidence,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        result = fail(f"lifecycle probe failed safely: {exc}")
    finally:
        if installed:
            rc, cleanup, _detail = _json_command(
                [console_bin, "update", "scheduler", "remove", "--yes", "--json"],
                env=env,
                cwd=probe_cwd,
                run_subprocess=run_subprocess,
            )
            cleanup_ok = (
                rc == 0 and cleanup is not None and cleanup.get("stage") == "scheduler-removed"
            )
        else:
            cleanup_ok = not any(
                (unit_dir / name).exists()
                for name in ("mempalace-update.service", "mempalace-update.timer")
            )
        evidence["cleanup_complete"] = cleanup_ok
    if not cleanup_ok:
        return fail("scheduler cleanup was incomplete")
    assert result is not None
    return result


def _probe_recovery_refusals(
    console_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str],
) -> SurfaceResult:
    before = _snapshot_mutable_state(env)
    actions = (
        ("update apply", ["update", "apply", "--json"]),
        ("update scheduler install", ["update", "scheduler", "install", "--json"]),
        ("update scheduler remove", ["update", "scheduler", "remove", "--json"]),
    )
    for label, action in actions:
        rc, out, err = run_subprocess([console_bin, *action], env=env, cwd=probe_cwd)
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        expected = f"mempalace-code {label} --yes --json"
        if (
            rc != 2
            or err != ""
            or not isinstance(payload, dict)
            or payload.get("ok") is not False
            or payload.get("stage") != "confirmation"
            or payload.get("exit_code") != 2
            or payload.get("recovery_command") != expected
        ):
            return SurfaceResult(
                SURFACE_RECOVERY_SAFETY,
                STATUS_FAIL,
                f"{label} did not return the exact confirmation refusal",
            )
    if _snapshot_mutable_state(env) != before:
        return SurfaceResult(
            SURFACE_RECOVERY_SAFETY,
            STATUS_FAIL,
            "guarded update actions mutated disposable state",
        )
    return SurfaceResult(
        SURFACE_RECOVERY_SAFETY,
        STATUS_OK,
        "all guarded update actions returned exact recovery JSON without mutation",
    )


def _probe_unsupported_platform_updates(
    console_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str],
) -> SurfaceResult:
    platform_fields = {
        "platform": sys.platform,
        "required_platform": "linux",
        "service_manager": "systemd-user",
        "recovery_command": "mempalace-code update status --json",
    }
    expected_message = (
        f"update mutations require Linux systemd-user; current platform is {sys.platform}"
    )
    before_status = _snapshot_mutable_state(env)
    rc, out, err = run_subprocess(
        [console_bin, "update", "status", "--json"], env=env, cwd=probe_cwd
    )
    try:
        status = json.loads(out)
    except json.JSONDecodeError:
        status = None
    if (
        rc != 0
        or err != ""
        or not isinstance(status, dict)
        or status.get("ok") is not True
        or status.get("stage") != "status"
        or any(status.get(key) != value for key, value in platform_fields.items())
        or not isinstance(status.get("installation"), dict)
        or not isinstance(status.get("provenance"), dict)
        or not isinstance(status.get("watcher"), dict)
        or not isinstance(status.get("scheduler"), dict)
    ):
        return SurfaceResult(
            SURFACE_UPDATE_PLATFORM,
            STATUS_FAIL,
            "update status did not return the unsupported-host diagnostic contract",
        )
    if _snapshot_mutable_state(env) != before_status:
        return SurfaceResult(
            SURFACE_UPDATE_PLATFORM,
            STATUS_FAIL,
            "update status mutated disposable state",
        )

    before_mutations = _snapshot_mutable_state(env)
    actions = (
        ["update", "apply", "--yes", "--json"],
        ["update", "scheduler", "install", "--yes", "--json"],
        ["update", "scheduler", "remove", "--yes", "--json"],
    )
    forbidden_diagnostics = ("FileNotFoundError", "Errno", "systemctl")
    for action in actions:
        rc, out, err = run_subprocess([console_bin, *action], env=env, cwd=probe_cwd)
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        if (
            rc != 2
            or err != ""
            or not isinstance(payload, dict)
            or payload.get("ok") is not False
            or payload.get("stage") != "unsupported-platform"
            or payload.get("exit_code") != 2
            or payload.get("message") != expected_message
            or any(payload.get(key) != value for key, value in platform_fields.items())
            or any(marker in out for marker in forbidden_diagnostics)
        ):
            return SurfaceResult(
                SURFACE_UPDATE_PLATFORM,
                STATUS_FAIL,
                "confirmed update mutation did not return the unsupported-platform contract",
            )
    if _snapshot_mutable_state(env) != before_mutations:
        return SurfaceResult(
            SURFACE_UPDATE_PLATFORM,
            STATUS_FAIL,
            "confirmed update mutations changed disposable state",
        )
    return SurfaceResult(
        SURFACE_UPDATE_PLATFORM,
        STATUS_OK,
        "status and all confirmed update mutations returned stable unsupported-platform JSON",
    )


_SITE_GUARD = """\
import os
import socket
from pathlib import Path
def _blocked(address, *args, **kwargs):
    with open(os.environ["MEMPALACE_SOCKET_ATTEMPTS"], "a", encoding="utf-8") as handle:
        handle.write(repr(address) + "\\n")
    raise OSError("socket blocked by installed release smoke")
_OriginalSocket = socket.socket
class _GuardedSocket(_OriginalSocket):
    def connect(self, address):
        return _blocked(address)
    def connect_ex(self, address):
        return _blocked(address)
socket.create_connection = _blocked
socket.socket = _GuardedSocket
Path(os.environ["MEMPALACE_SOCKET_GUARD_LOADED"]).write_text("loaded\\n", encoding="utf-8")
"""

_SITE_PACKAGES_SCRIPT = (
    "import json, site, sys; "
    "print(json.dumps([path for path in site.getsitepackages() if path in sys.path]))"
)
_SITE_GUARD_PTH = "_mempalace_release_smoke.pth"


def _probe_version_check_no_network(
    python_bin: str,
    console_bin: str,
    probe_cwd: str,
    state_root: Path,
    run_subprocess: RunSubprocess,
    env: dict[str, str],
) -> SurfaceResult:
    rc, out, err = run_subprocess(
        [python_bin, "-c", _SITE_PACKAGES_SCRIPT],
        env=env,
        cwd=probe_cwd,
    )
    try:
        site_paths = json.loads(out)
    except json.JSONDecodeError:
        site_paths = None
    if (
        rc != 0
        or err
        or not isinstance(site_paths, list)
        or len(site_paths) != 1
        or not isinstance(site_paths[0], str)
        or not Path(site_paths[0]).is_absolute()
    ):
        return SurfaceResult(
            SURFACE_VERSION_CHECK_NETWORK, STATUS_ERROR, "installed site-packages discovery failed"
        )
    site_dir = Path(site_paths[0])
    guard = site_dir / "sitecustomize.py"
    guard_loader = site_dir / _SITE_GUARD_PTH
    if guard.exists() or guard.is_symlink() or guard_loader.exists() or guard_loader.is_symlink():
        return SurfaceResult(
            SURFACE_VERSION_CHECK_NETWORK,
            STATUS_FAIL,
            "refused to overwrite an existing installed socket guard path",
        )
    marker = state_root / "socket-guard-loaded"
    attempts = state_root / "socket-attempts.log"
    guard.write_text(_SITE_GUARD, encoding="utf-8")
    guard_loader.write_text(f"import runpy; runpy.run_path({str(guard)!r})\n", encoding="utf-8")
    probe_env = dict(env)
    probe_env.update(
        {
            "MEMPALACE_VERSION_CHECK": "0",
            "MEMPALACE_SOCKET_GUARD_LOADED": str(marker),
            "MEMPALACE_SOCKET_ATTEMPTS": str(attempts),
        }
    )
    rc, out, err = run_subprocess(
        [console_bin, "version-check", "--check-now"], env=probe_env, cwd=probe_cwd
    )
    attempts_text = attempts.read_text(encoding="utf-8") if attempts.exists() else ""
    if rc != 2:
        detail = f"version-check exited {rc}, expected 2"
    elif not marker.is_file():
        detail = "installed interpreter did not load the socket guard"
    elif attempts_text:
        detail = "version-check attempted a socket before honoring the kill switch"
    elif "unset MEMPALACE_VERSION_CHECK" not in (out + err):
        detail = "version-check omitted the bounded environment recovery command"
    else:
        detail = ""
    if detail:
        return SurfaceResult(
            SURFACE_VERSION_CHECK_NETWORK,
            STATUS_FAIL,
            detail,
        )
    return SurfaceResult(
        SURFACE_VERSION_CHECK_NETWORK,
        STATUS_OK,
        "installed interpreter guard loaded and version-check stopped before socket access",
    )


def _read_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, sanitize(str(exc))
    if not isinstance(value, dict):
        return None, f"{path.name} is not a JSON object"
    return value, None


_SENSITIVE_KEY_PARTS = ("token", "secret", "password", "credential", "private_key", "api_key")

# Secret-like literal patterns. Mirrors scripts/public_safety_scan.py's
# _token_rules() so both scanners agree on what a leaked credential looks like;
# duplicated (not imported) because this script is documented stdlib-only with
# no project imports.
_SECRET_TOKEN_PATTERNS = (
    re.compile(r"\b[g]hp_[A-Za-z0-9]{20,}"),
    re.compile(r"[g]ithub_pat_"),
    re.compile(r"\b[p]ypi-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b[s]k-[A-Za-z0-9]{16,}"),
    re.compile(r"\b[s]k-ant-[A-Za-z0-9_-]{16,}"),
)

# Credential-bearing URLs: embedded userinfo (scheme://user:pass@host) or a
# credential-shaped query parameter (?token=..., &api_key=..., etc).
_CREDENTIAL_URL_USERINFO_RE = re.compile(r"://[^/@\s]+:[^/@\s]+@")
_CREDENTIAL_QUERY_PARAM_RE = re.compile(
    r"[?&](?:token|api[_-]?key|secret|password|access[_-]?token|auth[_-]?token)=[^&\s]+",
    re.IGNORECASE,
)


def _is_sensitive_string_value(value: str) -> bool:
    if any(pattern.search(value) for pattern in _SECRET_TOKEN_PATTERNS):
        return True
    return bool(
        _CREDENTIAL_URL_USERINFO_RE.search(value) or _CREDENTIAL_QUERY_PARAM_RE.search(value)
    )


def _contains_sensitive_content(value: object) -> bool:
    """Recursively scan for sensitive key names, secret-like string values, and
    credential-bearing URLs — not just key names."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if any(part in str(key).lower() for part in _SENSITIVE_KEY_PARTS):
                return True
            if _contains_sensitive_content(nested):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_sensitive_content(item) for item in value)
    if isinstance(value, str):
        return _is_sensitive_string_value(value)
    return False


def _validate_agent_plugin_files(
    plugin_root: Path, source_root: Path
) -> tuple[dict | None, str | None, str | None]:
    """Validate the installed Agent Plugin files.

    Returns (mcp_json, plugin_json version, error). ``version`` is only populated
    on success, so callers can fold plugin.json's declared version into the
    surface-agreement check alongside importlib.metadata/module/CLI versions —
    this is what makes a stale wheel/sdist plugin.json fail the smoke instead of
    only failing the separate schema/shape checks.
    """
    if not plugin_root.is_dir():
        return None, None, "agent-plugin path is not a directory"
    if _path_is_relative_to(plugin_root, source_root / MODULE_NAME):
        return None, None, "agent-plugin path resolves inside the checkout source tree"

    missing = [rel for rel in _REQUIRED_AGENT_PLUGIN_FILES if not (plugin_root / rel).is_file()]
    if missing:
        return None, None, f"missing Agent Plugin files: {missing}"

    plugin_json, error = _read_json(plugin_root / "plugin.json")
    if error:
        return None, None, f"plugin.json invalid: {error}"
    mcp_json, error = _read_json(plugin_root / "mcp.json")
    if error:
        return None, None, f"mcp.json invalid: {error}"
    plugin_schema, error = _read_json(plugin_root / "schemas/1.0.0/plugin.schema.json")
    if error:
        return None, None, f"plugin schema invalid: {error}"
    mcp_schema, error = _read_json(plugin_root / "schemas/1.0.0/mcp.schema.json")
    if error:
        return None, None, f"MCP schema invalid: {error}"

    assert plugin_json is not None
    assert mcp_json is not None
    assert plugin_schema is not None
    assert mcp_schema is not None

    if plugin_json.get("$schema") != _PLUGIN_SCHEMA_ID:
        return None, None, "plugin.json uses the wrong Agent Plugins schema ID"
    if mcp_json.get("$schema") != _MCP_SCHEMA_ID:
        return None, None, "mcp.json uses the wrong Agent Plugins MCP schema ID"
    if plugin_schema.get("$id") != _PLUGIN_SCHEMA_ID:
        return None, None, "vendored plugin schema has the wrong $id"
    if mcp_schema.get("$id") != _MCP_SCHEMA_ID:
        return None, None, "vendored MCP schema has the wrong $id"
    if _contains_sensitive_content(plugin_json) or _contains_sensitive_content(mcp_json):
        return None, None, "Agent Plugin metadata contains sensitive keys, values, or URLs"

    plugin_version = plugin_json.get("version")
    if not isinstance(plugin_version, str) or not plugin_version:
        return None, None, "plugin.json has no string 'version' field"

    servers = mcp_json.get("mcpServers")
    if not isinstance(servers, dict) or "mempalace-code" not in servers:
        return None, None, "mcp.json does not declare the mempalace-code MCP server"
    server = servers["mempalace-code"]
    if not isinstance(server, dict):
        return None, None, "mempalace-code MCP server config is not an object"
    if server.get("type") != "stdio":
        return None, None, "mempalace-code MCP server is not stdio"
    if server.get("command") != AGENT_PLUGIN_MCP_SCRIPT:
        return None, None, "mcp.json does not use the installed mempalace-code-mcp launcher"
    if server.get("args") != ["--profile=minimal"]:
        return None, None, "mcp.json does not select the minimal MCP profile"
    if "env" in server or "cwd" in server:
        return None, None, "mcp.json should not declare env or cwd for the portable default"

    return mcp_json, plugin_version, None


def _decode_mcp_json_lines(
    output: str, *, label: str, output_limit: int
) -> tuple[list[dict] | None, str | None]:
    """Decode bounded JSON-lines stdout for release-owned MCP probes."""
    if len(output.encode("utf-8")) > output_limit:
        return None, f"{label} output is oversized"
    responses: list[dict] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return None, f"{label} printed non-JSON stdout"
        if not isinstance(value, dict):
            return None, f"{label} printed non-object JSON stdout"
        responses.append(value)
    return responses, None


def _validate_mcp_responses(
    responses: list[dict],
    expected: tuple[tuple[int | None, str], ...],
    *,
    label: str,
) -> str | None:
    """Validate ordered JSON-RPC envelopes, IDs, and result/error kinds."""
    if len(responses) != len(expected):
        return f"{label} returned {len(responses)} response lines"
    for response, (expected_id, expected_kind) in zip(responses, expected, strict=True):
        if response.get("jsonrpc") != "2.0":
            return f"{label} response {expected_id} has invalid jsonrpc"
        response_id = response.get("id")
        if expected_id is None:
            id_matches = response_id is None
        else:
            id_matches = type(response_id) is int and response_id == expected_id
        if not id_matches:
            return f"{label} returned reordered or mismatched response IDs"
        has_result = "result" in response
        has_error = "error" in response
        if has_result == has_error:
            return f"{label} response {expected_id} must contain exactly one of result or error"
        if expected_kind not in response:
            return f"{label} response {expected_id} returned the wrong response kind"
    return None


def _probe_declared_mcp_command(
    mcp_json: dict,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str],
) -> str | None:
    server = mcp_json["mcpServers"]["mempalace-code"]
    cmd = [server["command"], *server.get("args", [])]
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "mempalace_check_duplicate",
                "arguments": {"content": "   \t"},
            },
        },
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
    ]
    stdin_data = "\n".join(json.dumps(request) for request in requests) + "\n"
    rc, out, err = run_subprocess(cmd, env=env, cwd=probe_cwd, input_text=stdin_data)
    if rc != 0:
        detail = sanitize((err or out).strip()) or f"declared MCP command exited {rc}"
        return f"declared MCP command failed: {detail}"

    responses, error = _decode_mcp_json_lines(
        out, label="declared MCP command", output_limit=1024 * 1024
    )
    if error is not None:
        return error
    assert responses is not None
    error = _validate_mcp_responses(
        responses,
        ((1, "result"), (2, "result"), (3, "error"), (4, "result")),
        label="declared MCP command",
    )
    if error is not None:
        return error
    init_result = responses[0].get("result")
    server_info = init_result.get("serverInfo") if isinstance(init_result, dict) else None
    if (
        not isinstance(init_result, dict)
        or not isinstance(server_info, dict)
        or not isinstance(server_info.get("name"), str)
        or server_info["name"] != "mempalace-code"
    ):
        return "declared MCP command did not complete initialize"
    tools_result = responses[1].get("result")
    if not isinstance(tools_result, dict) or not isinstance(tools_result.get("tools"), list):
        return "declared MCP command did not return tools/list"
    tool_names_list: list[str] = []
    for tool in tools_result["tools"]:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            return "declared MCP command did not return tools/list"
        tool_names_list.append(tool["name"])
    tool_names = tuple(tool_names_list)
    if tool_names != _MINIMAL_TOOLS:
        return f"declared MCP command listed unexpected tools: {tool_names}"
    blank_error = responses[2].get("error")
    blank_message = blank_error.get("message") if isinstance(blank_error, dict) else None
    if (
        not isinstance(blank_error, dict)
        or type(blank_error.get("code")) is not int
        or blank_error["code"] != -32602
        or not isinstance(blank_message, str)
        or "content" not in blank_message
        or "   \t" in blank_message
    ):
        return "declared MCP command did not reject blank required content safely"
    continued_result = responses[3].get("result")
    if not isinstance(continued_result, dict) or not isinstance(
        continued_result.get("tools"), list
    ):
        return "declared MCP command did not continue after blank required content"
    continued_names_list: list[str] = []
    for tool in continued_result["tools"]:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            return "declared MCP command did not continue after blank required content"
        continued_names_list.append(tool["name"])
    continued_names = tuple(continued_names_list)
    if continued_names != _MINIMAL_TOOLS:
        return f"declared MCP command continuation listed unexpected tools: {continued_names}"
    return None


# ── Pipx discovery ────────────────────────────────────────────────────────────


def find_pipx_executable() -> str | None:
    """Discover pipx as an external executable: PATH first, then Homebrew fallbacks.

    Does NOT use sys.executable -m pipx — that would require pipx to be installed
    in the current Python env, which is not guaranteed and would defeat the purpose
    of an independent install smoke.

    Homebrew fallback paths checked:
      /opt/homebrew/bin/pipx  — Apple Silicon Homebrew default
      /usr/local/bin/pipx     — Intel Mac Homebrew default
    """
    path_pipx = shutil.which("pipx")
    if path_pipx:
        return path_pipx
    for homebrew_path in ("/opt/homebrew/bin/pipx", "/usr/local/bin/pipx"):
        if os.path.isfile(homebrew_path) and os.access(homebrew_path, os.X_OK):
            return homebrew_path
    return None


def find_uv_executable() -> str | None:
    """Discover uv as an external executable: PATH first, then Homebrew fallbacks."""
    path_uv = shutil.which("uv")
    if path_uv:
        return path_uv
    for homebrew_path in ("/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        if os.path.isfile(homebrew_path) and os.access(homebrew_path, os.X_OK):
            return homebrew_path
    return None


def find_uv_tool_python(tool_dir: Path) -> Path | None:
    """Find the interpreter in a disposable UV_TOOL_DIR containing one installed tool."""
    candidates = sorted(tool_dir.glob("*/bin/python"))
    candidates.extend(sorted(tool_dir.glob("*/Scripts/python.exe")))
    return candidates[0] if len(candidates) == 1 else None


# ── Probes ─────────────────────────────────────────────────────────────────────


def probe_metadata_and_module(
    python_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str] | None = None,
    source_root: str | None = None,
    expected_root: str | None = None,
) -> tuple[SurfaceResult, SurfaceResult]:
    """Probe importlib.metadata and the imported module's __version__ in one subprocess."""
    rc, out, err = run_subprocess([python_bin, "-c", _PROBE_SCRIPT], env=env, cwd=probe_cwd)
    if rc != 0:
        detail = sanitize((err or out).strip()) or f"metadata/module probe exited {rc}"
        return (
            SurfaceResult(
                SURFACE_METADATA, STATUS_ERROR, f"metadata/module probe failed: {detail}"
            ),
            SurfaceResult(SURFACE_MODULE, STATUS_ERROR, f"metadata/module probe failed: {detail}"),
        )

    metadata_version: str | None = None
    module_version: str | None = None
    metadata_error: str | None = None
    module_error: str | None = None
    module_file: str | None = None
    for line in out.splitlines():
        if line.startswith("METADATA="):
            metadata_version = line[len("METADATA=") :].strip()
        elif line.startswith("METADATA-ERROR="):
            metadata_error = line[len("METADATA-ERROR=") :].strip()
        elif line.startswith("MODULE="):
            module_version = line[len("MODULE=") :].strip()
        elif line.startswith("MODULE-FILE="):
            module_file = line[len("MODULE-FILE=") :].strip()
        elif line.startswith("MODULE-ERROR="):
            module_error = line[len("MODULE-ERROR=") :].strip()

    if metadata_version:
        metadata_result = SurfaceResult(
            SURFACE_METADATA,
            STATUS_OK,
            f"importlib.metadata.version('mempalace-code') reports {metadata_version}",
            metadata_version,
        )
    else:
        detail = sanitize(metadata_error or "importlib.metadata.version() returned no value")
        metadata_result = SurfaceResult(SURFACE_METADATA, STATUS_ERROR, detail)

    if module_version:
        if (
            source_root
            and module_file
            and _path_is_relative_to(Path(module_file), Path(source_root) / MODULE_NAME)
        ):
            module_result = SurfaceResult(
                SURFACE_MODULE,
                STATUS_FAIL,
                "mempalace_code imported from checkout source tree",
            )
            return metadata_result, module_result
        if expected_root and (
            not module_file or not _path_is_relative_to(Path(module_file), Path(expected_root))
        ):
            module_result = SurfaceResult(
                SURFACE_MODULE,
                STATUS_FAIL,
                "mempalace_code did not import from the disposable installed contour",
            )
            return metadata_result, module_result
        module_result = SurfaceResult(
            SURFACE_MODULE,
            STATUS_OK,
            f"mempalace_code.__version__ reports {module_version}",
            module_version,
        )
    else:
        detail = sanitize(module_error or "mempalace_code.__version__ was not readable")
        module_result = SurfaceResult(SURFACE_MODULE, STATUS_ERROR, detail)

    return metadata_result, module_result


def probe_candidate_extra_metadata(
    python_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    *,
    env: dict[str, str] | None = None,
    expected_root: str | None = None,
    expected_version: str | None = None,
) -> CandidateExtraMetadata:
    """Discover canonical ``Provides-Extra`` entries from one installed candidate."""
    rc, out, err = run_subprocess(
        [python_bin, "-c", _EXTRA_METADATA_PROBE_SCRIPT], env=env, cwd=probe_cwd
    )
    if rc != 0:
        detail = sanitize((err or out).strip()) or f"extra metadata probe exited {rc}"
        return CandidateExtraMetadata(False, detail=f"extra metadata probe failed: {detail}")
    if err.strip():
        return CandidateExtraMetadata(False, detail="extra metadata probe wrote to stderr")
    if len(out.encode("utf-8")) > _EXTRA_METADATA_OUTPUT_LIMIT:
        return CandidateExtraMetadata(False, detail="extra metadata probe output exceeded limit")
    try:
        payload = json.loads(out)
    except (json.JSONDecodeError, TypeError, UnicodeError):
        return CandidateExtraMetadata(False, detail="extra metadata probe returned invalid JSON")
    if not isinstance(payload, dict) or set(payload) != {"version", "root", "provides_extra"}:
        return CandidateExtraMetadata(False, detail="extra metadata probe returned invalid shape")
    version = payload["version"]
    root = payload["root"]
    raw_extras = payload["provides_extra"]
    if not isinstance(version, str) or not version or not isinstance(root, str) or not root:
        return CandidateExtraMetadata(False, detail="extra metadata provenance is malformed")
    if expected_version is not None and version != expected_version:
        return CandidateExtraMetadata(
            False, detail="extra metadata version mismatched candidate wheel"
        )
    if expected_root is not None and not _path_is_relative_to(Path(root), Path(expected_root)):
        return CandidateExtraMetadata(
            False, detail="extra metadata resolved outside candidate contour"
        )
    if (
        not isinstance(raw_extras, list)
        or not raw_extras
        or len(raw_extras) > _EXTRA_METADATA_ENTRY_LIMIT
        or any(not isinstance(extra, str) or not extra for extra in raw_extras)
    ):
        return CandidateExtraMetadata(
            False, detail="Provides-Extra entries are missing or malformed"
        )
    if any(_EXTRA_METADATA_TOKEN.fullmatch(extra) is None for extra in raw_extras):
        return CandidateExtraMetadata(False, detail="Provides-Extra contains a non-canonical name")
    if len(set(raw_extras)) != len(raw_extras):
        return CandidateExtraMetadata(False, detail="Provides-Extra contains duplicate names")
    extras = tuple(sorted(raw_extras))
    runtime_extras = tuple(extra for extra in extras if extra != "dev")
    if not runtime_extras:
        return CandidateExtraMetadata(False, detail="Provides-Extra declares no non-dev extras")
    return CandidateExtraMetadata(
        True,
        extras=extras,
        runtime_extras=runtime_extras,
        version=version,
        detail="candidate Provides-Extra metadata is canonical and provenance-bound",
    )


def probe_cli_version_check(
    console_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str] | None = None,
) -> SurfaceResult:
    """Probe the installed console script's `version-check --status` Current version line."""
    rc, out, err = run_subprocess(
        [console_bin, "version-check", "--status"], env=env, cwd=probe_cwd
    )
    if rc != 0:
        detail = sanitize((err or out).strip()) or f"version-check --status exited {rc}"
        return SurfaceResult(SURFACE_CLI, STATUS_ERROR, f"version-check --status failed: {detail}")

    matches = _CURRENT_VERSION_RE.findall(out)
    if not matches:
        return SurfaceResult(
            SURFACE_CLI,
            STATUS_FAIL,
            "version-check --status output has no 'Current version:' line",
        )
    if len(set(matches)) > 1:
        return SurfaceResult(
            SURFACE_CLI,
            STATUS_FAIL,
            f"version-check --status printed conflicting 'Current version:' lines: {sorted(set(matches))}",
        )
    version = matches[0]
    return SurfaceResult(
        SURFACE_CLI, STATUS_OK, f"version-check --status reports {version}", version
    )


def _samefile_or_resolves_to(left: Path, right: Path) -> bool:
    try:
        return left.samefile(right)
    except OSError:
        return left.resolve(strict=False) == right.resolve(strict=False)


def _write_conflicting_console_script(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'ambient mempalace-code should not run'\nexit 42\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def probe_alias_provenance(
    console_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str] | None = None,
) -> SurfaceResult:
    """Create the legacy alias under PATH shadowing and verify its target and version."""
    console_path = Path(console_bin)
    with tempfile.TemporaryDirectory(prefix="mempalace-alias-provenance-") as tmpdir:
        tmp_root = Path(tmpdir)
        conflict_bin = tmp_root / "conflict-bin"
        launcher_bin = tmp_root / "launcher-bin"
        conflict_bin.mkdir()
        launcher_bin.mkdir()

        _write_conflicting_console_script(conflict_bin / CONSOLE_SCRIPT)
        launcher = launcher_bin / CONSOLE_SCRIPT
        launcher.symlink_to(console_path.absolute())

        probe_env = dict(env or os.environ)
        probe_env["PATH"] = os.pathsep.join((str(conflict_bin), str(launcher_bin)))

        rc, out, err = run_subprocess(
            [str(launcher), "install-alias"],
            env=probe_env,
            cwd=probe_cwd,
        )
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"install-alias exited {rc}"
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_ERROR,
                f"install-alias under PATH shadowing failed: {detail}",
            )

        alias_path = launcher_bin / "mempalace"
        if not alias_path.exists() and not alias_path.is_symlink():
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_FAIL,
                "install-alias did not create the legacy mempalace alias",
            )

        if not _samefile_or_resolves_to(alias_path, launcher):
            target_detail = (
                os.readlink(alias_path) if alias_path.is_symlink() else "non-symlink alias entry"
            )
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_FAIL,
                "legacy alias does not target the invoked mempalace-code under PATH shadowing: "
                + sanitize(target_detail),
            )

        rc, out, err = run_subprocess(
            [str(alias_path), "version-check", "--status"],
            env=probe_env,
            cwd=probe_cwd,
        )
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"alias version-check exited {rc}"
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_ERROR,
                f"alias version-check --status failed: {detail}",
            )

        matches = _CURRENT_VERSION_RE.findall(out)
        if not matches:
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_FAIL,
                "alias version-check --status output has no 'Current version:' line",
            )
        if len(set(matches)) > 1:
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_FAIL,
                "alias version-check --status printed conflicting 'Current version:' lines: "
                + str(sorted(set(matches))),
            )
        version = matches[0]

        installer_bin = tmp_root / "alias-installer-bin"
        installer_bin.mkdir()
        installer_canonical = installer_bin / CONSOLE_SCRIPT
        installer_canonical.symlink_to(console_path.absolute())
        installer_launcher = installer_bin / ALIAS_INSTALLER_SCRIPT
        installer_launcher.symlink_to(console_path.with_name(ALIAS_INSTALLER_SCRIPT).absolute())
        installer_env = dict(probe_env)
        installer_env["PATH"] = os.pathsep.join((str(conflict_bin), str(installer_bin)))

        rc, out, err = run_subprocess(
            [str(installer_launcher)],
            env=installer_env,
            cwd=probe_cwd,
        )
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"{ALIAS_INSTALLER_SCRIPT} exited {rc}"
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_ERROR,
                f"dedicated alias installer under PATH shadowing failed: {detail}",
            )

        installer_alias = installer_bin / "mempalace"
        if not installer_alias.exists() and not installer_alias.is_symlink():
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_FAIL,
                "dedicated alias installer did not create the legacy mempalace alias",
            )
        if not _samefile_or_resolves_to(installer_alias, installer_canonical):
            target_detail = (
                os.readlink(installer_alias)
                if installer_alias.is_symlink()
                else "non-symlink alias entry"
            )
            return SurfaceResult(
                SURFACE_ALIAS_PROVENANCE,
                STATUS_FAIL,
                "dedicated alias installer did not bind to its sibling mempalace-code: "
                + sanitize(target_detail),
            )

        return SurfaceResult(
            SURFACE_ALIAS_PROVENANCE,
            STATUS_OK,
            f"legacy alias and dedicated installer target invoked mempalace-code and report {version}",
            version,
        )


def probe_ordinary_runtime_no_chromadb(
    python_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str] | None = None,
) -> SurfaceResult:
    """Probe ordinary runtime paths while failing on any chromadb import."""
    rc, out, err = run_subprocess(
        [python_bin, "-c", _RUNTIME_NO_CHROMADB_PROBE_SCRIPT],
        env=env,
        cwd=probe_cwd,
    )
    if rc != 0:
        detail = sanitize((err or out).strip()) or f"ordinary runtime probe exited {rc}"
        return SurfaceResult(
            SURFACE_RUNTIME_NO_CHROMADB,
            STATUS_ERROR,
            f"ordinary runtime no-chromadb probe failed: {detail}",
        )
    if "RUNTIME-NO-CHROMADB=ok" not in out:
        return SurfaceResult(
            SURFACE_RUNTIME_NO_CHROMADB,
            STATUS_FAIL,
            "ordinary runtime no-chromadb probe did not report success",
        )
    if "migrate-storage" not in out:
        return SurfaceResult(
            SURFACE_RUNTIME_NO_CHROMADB,
            STATUS_FAIL,
            "CLI help did not include migrate-storage during ordinary runtime probe",
        )
    return SurfaceResult(
        SURFACE_RUNTIME_NO_CHROMADB,
        STATUS_OK,
        "package import, CLI help, and LanceDB read-only open avoided chromadb",
    )


def probe_agent_plugin_package(
    console_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str],
    source_root: str | None = None,
) -> SurfaceResult:
    """Probe the installed Agent Plugin path, manifests, and declared MCP command."""
    rc, out, err = run_subprocess(
        [console_bin, "agent-plugin", "path", "--json"], env=env, cwd=probe_cwd
    )
    if rc != 0:
        detail = sanitize((err or out).strip()) or f"agent-plugin path exited {rc}"
        return SurfaceResult(
            SURFACE_AGENT_PLUGIN, STATUS_ERROR, f"agent-plugin path failed: {detail}"
        )

    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:
        return SurfaceResult(
            SURFACE_AGENT_PLUGIN,
            STATUS_FAIL,
            f"agent-plugin path output is not JSON: {sanitize(str(exc))}",
        )
    path_value = payload.get("path") if isinstance(payload, dict) else None
    if not isinstance(path_value, str) or not path_value:
        return SurfaceResult(SURFACE_AGENT_PLUGIN, STATUS_FAIL, "agent-plugin path JSON lacks path")

    mcp_json, plugin_version, error = _validate_agent_plugin_files(
        Path(path_value), Path(source_root) if source_root else _SOURCE_ROOT
    )
    if error:
        return SurfaceResult(SURFACE_AGENT_PLUGIN, STATUS_FAIL, error)
    assert mcp_json is not None
    assert plugin_version is not None

    error = _probe_declared_mcp_command(mcp_json, probe_cwd, run_subprocess, env)
    if error:
        return SurfaceResult(SURFACE_AGENT_PLUGIN, STATUS_ERROR, error)

    return SurfaceResult(
        SURFACE_AGENT_PLUGIN,
        STATUS_OK,
        "agent-plugin path, manifests, and declared minimal MCP command passed",
        plugin_version,
    )


# ── Evaluation ─────────────────────────────────────────────────────────────────


def evaluate_smoke(
    surfaces: list[SurfaceResult],
    package: str,
    install_spec: str,
    installer: str,
) -> SmokeResult:
    """Combine probe surfaces into a SmokeResult, agreeing only when every surface matches."""
    versions = {s.name: s.version for s in surfaces if s.status == STATUS_OK and s.version}
    failed = [s for s in surfaces if s.status != STATUS_OK]

    diagnostics: list[str] = []
    expected_version: str | None = None

    if failed:
        diagnostics.extend(f"{s.name}: {s.detail}" for s in failed)
    elif len(set(versions.values())) > 1:
        diagnostics.extend(
            f"{name} reports {version}" for name, version in sorted(versions.items())
        )
        diagnostics.append(
            "surfaces disagree on installed version — mismatched surfaces: "
            + ", ".join(sorted(versions))
        )
    else:
        expected_version = next(iter(versions.values()), None)

    ok = not failed and bool(versions) and len(set(versions.values())) == 1

    if not ok:
        diagnostics.extend(sanitize(cmd) for cmd in build_reinstall_commands(package, install_spec))

    manager_by_installer = {
        INSTALLER_VENV: "pip",
        INSTALLER_PIPX: "pipx",
        INSTALLER_UV_TOOL: "uv-tool",
        INSTALLER_BOOTSTRAP_VENV: "bootstrap-venv",
    }
    return SmokeResult(
        ok=ok,
        expected_version=expected_version,
        installer=installer,
        install_spec=install_spec,
        surfaces=surfaces,
        diagnostics=diagnostics,
        manager=manager_by_installer.get(installer),
        update_eligible=ok and installer != INSTALLER_VENV,
    )


# ── Installer flows ─────────────────────────────────────────────────────────────


def _append_recovery_safety(
    surfaces: list[SurfaceResult],
    *,
    python_bin: str,
    console_bin: str,
    probe_cwd: str,
    state_root: Path,
    run_subprocess: RunSubprocess,
    env: dict[str, str],
) -> None:
    resolved_console = Path(console_bin).resolve()
    if not _path_is_relative_to(resolved_console, state_root):
        surfaces.append(
            SurfaceResult(
                SURFACE_RECOVERY_SAFETY,
                STATUS_FAIL,
                "installed console resolves outside the disposable contour",
            )
        )
        return
    ambient_console = shutil.which(CONSOLE_SCRIPT, path=env.get("PATH"))
    if ambient_console is None or Path(ambient_console).resolve() != resolved_console:
        surfaces.append(
            SurfaceResult(
                SURFACE_RECOVERY_SAFETY,
                STATUS_FAIL,
                "PATH does not resolve uniquely to the disposable installed console",
            )
        )
        return
    surfaces.append(_probe_recovery_refusals(console_bin, probe_cwd, run_subprocess, env))
    if not sys.platform.startswith("linux"):
        surfaces.append(
            _probe_unsupported_platform_updates(console_bin, probe_cwd, run_subprocess, env)
        )
    surfaces.append(
        _probe_version_check_no_network(
            python_bin, console_bin, probe_cwd, state_root, run_subprocess, env
        )
    )


def run_venv_smoke(
    install_spec: str,
    package: str,
    run_subprocess: RunSubprocess,
    *,
    recovery_safety: bool = False,
) -> SmokeResult:
    """Install into a fresh disposable venv (non-editable) and probe all surfaces."""
    with tempfile.TemporaryDirectory(prefix="mempalace-install-smoke-") as tmpdir:
        tmp_root = Path(tmpdir)
        venv_dir = tmp_root / "venv"
        probe_cwd = tmp_root / "probe-cwd"
        probe_home = tmp_root / "home"
        probe_tmp = tmp_root / "tmp"
        probe_cwd.mkdir()
        probe_home.mkdir()
        probe_tmp.mkdir()
        install_env = _credential_free_env()
        install_env.update({"HOME": str(probe_home), "TMPDIR": str(probe_tmp)})

        rc, _out, err = run_subprocess(
            [sys.executable, "-m", "venv", str(venv_dir)], env=install_env
        )
        if rc != 0:
            detail = sanitize(err.strip()) or f"venv creation exited {rc}"
            surfaces = [
                SurfaceResult(SURFACE_INSTALL, STATUS_ERROR, f"venv creation failed: {detail}")
            ]
            return SmokeResult(False, None, INSTALLER_VENV, install_spec, surfaces, [])

        pip = str(venv_dir / "bin" / "pip")
        python_bin = str(venv_dir / "bin" / "python")
        script_dir = venv_dir / "bin"
        console_bin = str(script_dir / CONSOLE_SCRIPT)
        probe_env = _isolate_probe_state(install_env, tmp_root, script_dir)

        rc, out, err = run_subprocess(
            [pip, "install", "--no-cache-dir", install_spec], env=install_env
        )
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"pip install exited {rc}"
            surfaces = [SurfaceResult(SURFACE_INSTALL, STATUS_FAIL, f"install failed: {detail}")]
            return SmokeResult(False, None, INSTALLER_VENV, install_spec, surfaces, [])

        metadata_result, module_result = probe_metadata_and_module(
            python_bin,
            str(probe_cwd),
            run_subprocess,
            env=probe_env,
            source_root=str(_SOURCE_ROOT),
            expected_root=str(tmp_root) if recovery_safety else None,
        )
        cli_result = probe_cli_version_check(
            console_bin, str(probe_cwd), run_subprocess, env=probe_env
        )
        alias_result = probe_alias_provenance(
            console_bin, str(probe_cwd), run_subprocess, env=probe_env
        )
        agent_plugin_result = probe_agent_plugin_package(
            console_bin,
            str(probe_cwd),
            run_subprocess,
            env=probe_env,
            source_root=str(_SOURCE_ROOT),
        )
        runtime_result = probe_ordinary_runtime_no_chromadb(
            python_bin, str(probe_cwd), run_subprocess, env=probe_env
        )

        surfaces = [
            metadata_result,
            module_result,
            cli_result,
            alias_result,
            agent_plugin_result,
            runtime_result,
        ]
        if recovery_safety:
            _append_recovery_safety(
                surfaces,
                python_bin=python_bin,
                console_bin=console_bin,
                probe_cwd=str(probe_cwd),
                state_root=tmp_root,
                run_subprocess=run_subprocess,
                env=probe_env,
            )
        return evaluate_smoke(surfaces, package, install_spec, INSTALLER_VENV)


def run_bootstrap_venv_smoke(
    install_spec: str,
    package: str,
    run_subprocess: RunSubprocess,
    *,
    recovery_safety: bool = False,
) -> SmokeResult:
    """Exercise the documented ~/.mempalace/venv topology under a disposable HOME."""
    with tempfile.TemporaryDirectory(prefix="mempalace-bootstrap-smoke-") as tmpdir:
        tmp_root = Path(tmpdir)
        fake_home = tmp_root / "home"
        fake_home.mkdir()
        venv_dir = fake_home / ".mempalace" / "venv"
        probe_cwd = tmp_root / "probe-cwd"
        probe_cwd.mkdir()

        env = _credential_free_env()
        env["HOME"] = str(fake_home)

        rc, _out, err = run_subprocess([sys.executable, "-m", "venv", str(venv_dir)], env=env)
        if rc != 0:
            detail = sanitize(err.strip()) or f"venv creation exited {rc}"
            surfaces = [
                SurfaceResult(SURFACE_INSTALL, STATUS_ERROR, f"venv creation failed: {detail}")
            ]
            return SmokeResult(False, None, INSTALLER_BOOTSTRAP_VENV, install_spec, surfaces, [])

        script_dir = venv_dir / "bin"
        pip = str(script_dir / "pip")
        python_bin = str(script_dir / "python")
        console_bin = str(script_dir / CONSOLE_SCRIPT)
        probe_env = _isolate_probe_state(env, tmp_root, script_dir)

        rc, out, err = run_subprocess(
            [pip, "install", "--no-cache-dir", install_spec], env=probe_env
        )
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"pip install exited {rc}"
            surfaces = [SurfaceResult(SURFACE_INSTALL, STATUS_FAIL, f"install failed: {detail}")]
            return SmokeResult(False, None, INSTALLER_BOOTSTRAP_VENV, install_spec, surfaces, [])

        metadata_result, module_result = probe_metadata_and_module(
            python_bin,
            str(probe_cwd),
            run_subprocess,
            env=probe_env,
            source_root=str(_SOURCE_ROOT),
            expected_root=str(tmp_root) if recovery_safety else None,
        )
        cli_result = probe_cli_version_check(
            console_bin, str(probe_cwd), run_subprocess, env=probe_env
        )
        alias_result = probe_alias_provenance(
            console_bin, str(probe_cwd), run_subprocess, env=probe_env
        )
        agent_plugin_result = probe_agent_plugin_package(
            console_bin,
            str(probe_cwd),
            run_subprocess,
            env=probe_env,
            source_root=str(_SOURCE_ROOT),
        )
        runtime_result = probe_ordinary_runtime_no_chromadb(
            python_bin, str(probe_cwd), run_subprocess, env=probe_env
        )
        surfaces = [
            metadata_result,
            module_result,
            cli_result,
            alias_result,
            agent_plugin_result,
            runtime_result,
        ]
        if recovery_safety:
            _append_recovery_safety(
                surfaces,
                python_bin=python_bin,
                console_bin=console_bin,
                probe_cwd=str(probe_cwd),
                state_root=tmp_root,
                run_subprocess=run_subprocess,
                env=probe_env,
            )
        return evaluate_smoke(surfaces, package, install_spec, INSTALLER_BOOTSTRAP_VENV)


def run_pipx_smoke(
    install_spec: str,
    package: str,
    run_subprocess: RunSubprocess,
    *,
    recovery_safety: bool = False,
) -> SmokeResult:
    """Install via pipx into disposable PIPX_HOME/PIPX_BIN_DIR and probe all surfaces.

    Uses temp PIPX_HOME/PIPX_BIN_DIR so the operator's real pipx tool install is
    never touched.
    """
    with tempfile.TemporaryDirectory(prefix="mempalace-pipx-smoke-") as tmpdir:
        tmp_root = Path(tmpdir)
        pipx_home = tmp_root / "pipx-home"
        pipx_bin = tmp_root / "pipx-bin"
        pipx_home.mkdir()
        pipx_bin.mkdir()
        probe_cwd = tmp_root / "probe-cwd"
        probe_cwd.mkdir()

        env = _credential_free_env()
        env["PIPX_HOME"] = str(pipx_home)
        env["PIPX_BIN_DIR"] = str(pipx_bin)
        env = _isolate_probe_state(env, tmp_root, pipx_bin)

        pipx_exe = find_pipx_executable()
        if pipx_exe is None:
            surfaces = [
                SurfaceResult(
                    SURFACE_INSTALL,
                    STATUS_ERROR,
                    "pipx not found on PATH or Homebrew paths (/opt/homebrew/bin/pipx, /usr/local/bin/pipx)",
                )
            ]
            return SmokeResult(False, None, INSTALLER_PIPX, install_spec, surfaces, [])

        rc, out, err = run_subprocess([pipx_exe, "install", install_spec], env=env)
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"pipx install exited {rc}"
            surfaces = [
                SurfaceResult(SURFACE_INSTALL, STATUS_FAIL, f"pipx install failed: {detail}")
            ]
            return SmokeResult(False, None, INSTALLER_PIPX, install_spec, surfaces, [])

        console_bin = str(pipx_bin / CONSOLE_SCRIPT)
        venv_python = str(pipx_home / "venvs" / package / "bin" / "python")

        metadata_result, module_result = probe_metadata_and_module(
            venv_python,
            str(probe_cwd),
            run_subprocess,
            env=env,
            source_root=str(_SOURCE_ROOT),
            expected_root=str(tmp_root) if recovery_safety else None,
        )
        cli_result = probe_cli_version_check(console_bin, str(probe_cwd), run_subprocess, env=env)
        alias_result = probe_alias_provenance(console_bin, str(probe_cwd), run_subprocess, env=env)
        agent_plugin_result = probe_agent_plugin_package(
            console_bin,
            str(probe_cwd),
            run_subprocess,
            env=env,
            source_root=str(_SOURCE_ROOT),
        )
        runtime_result = probe_ordinary_runtime_no_chromadb(
            venv_python, str(probe_cwd), run_subprocess, env=env
        )

        surfaces = [
            metadata_result,
            module_result,
            cli_result,
            alias_result,
            agent_plugin_result,
            runtime_result,
        ]
        if recovery_safety:
            _append_recovery_safety(
                surfaces,
                python_bin=venv_python,
                console_bin=console_bin,
                probe_cwd=str(probe_cwd),
                state_root=tmp_root,
                run_subprocess=run_subprocess,
                env=env,
            )
        return evaluate_smoke(surfaces, package, install_spec, INSTALLER_PIPX)


def run_uv_tool_smoke(
    install_spec: str,
    package: str,
    run_subprocess: RunSubprocess,
    *,
    recovery_safety: bool = False,
    linux_lifecycle: bool = False,
) -> SmokeResult:
    """Install via uv tool into disposable tool, bin, and cache directories."""
    with tempfile.TemporaryDirectory(prefix="mempalace-uv-tool-smoke-") as tmpdir:
        tmp_root = Path(tmpdir)
        tool_dir = tmp_root / "tools"
        bin_dir = tmp_root / "bin"
        cache_dir = tmp_root / "cache"
        probe_cwd = tmp_root / "probe-cwd"
        for path in (tool_dir, bin_dir, cache_dir, probe_cwd):
            path.mkdir()

        env = _credential_free_env()
        env["UV_TOOL_DIR"] = str(tool_dir)
        env["UV_TOOL_BIN_DIR"] = str(bin_dir)
        env["UV_CACHE_DIR"] = str(cache_dir)
        env = _isolate_probe_state(env, tmp_root, bin_dir)

        uv_exe = find_uv_executable()
        if uv_exe is None:
            surfaces = [SurfaceResult(SURFACE_INSTALL, STATUS_ERROR, "uv not found on PATH")]
            return SmokeResult(False, None, INSTALLER_UV_TOOL, install_spec, surfaces, [])

        rc, out, err = run_subprocess([uv_exe, "tool", "install", "--force", install_spec], env=env)
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"uv tool install exited {rc}"
            surfaces = [
                SurfaceResult(SURFACE_INSTALL, STATUS_FAIL, f"uv tool install failed: {detail}")
            ]
            return SmokeResult(False, None, INSTALLER_UV_TOOL, install_spec, surfaces, [])

        python_path = find_uv_tool_python(tool_dir)
        if python_path is None:
            surfaces = [
                SurfaceResult(
                    SURFACE_INSTALL,
                    STATUS_ERROR,
                    "uv tool interpreter not found uniquely in disposable UV_TOOL_DIR",
                )
            ]
            return SmokeResult(False, None, INSTALLER_UV_TOOL, install_spec, surfaces, [])

        console_bin = str(bin_dir / CONSOLE_SCRIPT)
        metadata_result, module_result = probe_metadata_and_module(
            str(python_path),
            str(probe_cwd),
            run_subprocess,
            env=env,
            source_root=str(_SOURCE_ROOT),
            expected_root=str(tmp_root) if recovery_safety else None,
        )
        cli_result = probe_cli_version_check(console_bin, str(probe_cwd), run_subprocess, env=env)
        alias_result = probe_alias_provenance(console_bin, str(probe_cwd), run_subprocess, env=env)
        agent_plugin_result = probe_agent_plugin_package(
            console_bin,
            str(probe_cwd),
            run_subprocess,
            env=env,
            source_root=str(_SOURCE_ROOT),
        )
        runtime_result = probe_ordinary_runtime_no_chromadb(
            str(python_path), str(probe_cwd), run_subprocess, env=env
        )
        surfaces = [
            metadata_result,
            module_result,
            cli_result,
            alias_result,
            agent_plugin_result,
            runtime_result,
        ]
        if recovery_safety:
            _append_recovery_safety(
                surfaces,
                python_bin=str(python_path),
                console_bin=console_bin,
                probe_cwd=str(probe_cwd),
                state_root=tmp_root,
                run_subprocess=run_subprocess,
                env=env,
            )
        result = evaluate_smoke(surfaces, package, install_spec, INSTALLER_UV_TOOL)
        if linux_lifecycle and result.ok:
            lifecycle_env = dict(env)
            lifecycle_env.update(
                {
                    "MEMPALACE_SOCKET_GUARD_LOADED": str(tmp_root / "socket-guard-loaded"),
                    "MEMPALACE_SOCKET_ATTEMPTS": str(tmp_root / "socket-attempts.log"),
                    "PATH": os.pathsep.join(
                        (str(bin_dir), str(Path(uv_exe).resolve().parent), os.defpath)
                    ),
                }
            )
            for name in (
                "HOME",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                LIFECYCLE_AUTHORITY_ENV,
            ):
                value = os.environ.get(name)
                if value is not None:
                    lifecycle_env[name] = value
            result.lifecycle = run_linux_systemd_update_lifecycle(
                console_bin,
                str(python_path),
                result.expected_version,
                str(probe_cwd),
                run_subprocess,
                lifecycle_env,
            )
        return result


def run_all_installers_smoke(
    install_spec: str,
    package: str,
    run_subprocess: RunSubprocess,
) -> AggregateSmokeResult:
    """Qualify one exact install spec through every canonical installer in order."""
    runners = {
        INSTALLER_VENV: run_venv_smoke,
        INSTALLER_PIPX: run_pipx_smoke,
        INSTALLER_UV_TOOL: run_uv_tool_smoke,
        INSTALLER_BOOTSTRAP_VENV: run_bootstrap_venv_smoke,
    }
    results = []
    diagnostics = []
    for installer in INSTALLERS:
        if (
            installer == INSTALLER_PIPX
            and find_pipx_executable() is None
            or installer == INSTALLER_UV_TOOL
            and find_uv_executable() is None
        ):
            diagnostics.append(
                f"{installer}: required tool unavailable; recovery: {MISSING_TOOL_RECOVERY[installer]}"
            )
        if installer == INSTALLER_UV_TOOL:
            result = run_uv_tool_smoke(
                install_spec,
                package,
                run_subprocess,
                recovery_safety=True,
                linux_lifecycle=True,
            )
        else:
            result = runners[installer](install_spec, package, run_subprocess, recovery_safety=True)
        results.append(result)
        if not result.ok:
            diagnostics.extend(f"{installer}: {item}" for item in result.diagnostics)
    lifecycle = next((result.lifecycle for result in results if result.lifecycle is not None), None)
    if lifecycle is None:
        lifecycle = LinuxSystemdLifecycleResult(
            LIFECYCLE_STATUS_UNRUN,
            "no exact installed manager supplied Linux systemd-user lifecycle evidence",
            recovery_command=LIFECYCLE_RECOVERY_COMMAND,
        )
    if not lifecycle.ok:
        diagnostics.append(
            f"{SURFACE_LINUX_SYSTEMD_LIFECYCLE}: {lifecycle.status}: {lifecycle.detail}; "
            f"recovery: {lifecycle.recovery_command}"
        )
    return AggregateSmokeResult(
        ok=(
            len(results) == len(INSTALLERS)
            and all(result.ok for result in results)
            and lifecycle.ok
        ),
        install_spec=install_spec,
        results=results,
        diagnostics=diagnostics,
        linux_systemd_update_lifecycle=lifecycle,
    )


# ── Output formatting ──────────────────────────────────────────────────────────

_STATUS_ICON = {STATUS_OK: "✓", STATUS_FAIL: "✗", STATUS_ERROR: "!"}


def render_human(result: SmokeResult) -> str:
    lines = [f"## Install metadata smoke ({result.installer}, spec={result.install_spec})", ""]
    for s in result.surfaces:
        icon = _STATUS_ICON.get(s.status, "?")
        suffix = f" [{s.version}]" if s.version else ""
        lines.append(f"  {icon} {s.name}: {s.detail}{suffix}")
    lines.append("")
    if result.ok:
        lines.append(f"Install metadata smoke: OK — all surfaces report {result.expected_version}.")
    else:
        lines.append("Install metadata smoke: FAILED — surfaces disagree or a probe failed.")
        lines.append("")
        lines.append("Diagnostics:")
        for d in result.diagnostics:
            lines.append(f"  - {d}")
    return "\n".join(lines)


def render_aggregate_human(result: AggregateSmokeResult) -> str:
    lines = [render_human(installer_result) for installer_result in result.results]
    lines.append(
        "All-installers smoke: OK"
        if result.ok
        else "All-installers smoke: FAILED\n" + "\n".join(result.diagnostics)
    )
    return "\n\n".join(lines)


# ── Default subprocess callable ────────────────────────────────────────────────


def _is_dependency_install(args: list[str]) -> bool:
    if len(args) < 2:
        return False
    executable = Path(args[0]).name
    return (
        (executable in {"pip", "pip3"} and args[1] == "install")
        or (executable == "pipx" and args[1] == "install")
        or (executable == "uv" and args[1:3] == ["tool", "install"])
    )


def _default_run_subprocess(
    args: list[str],
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    input_text: str | None = None,
    timeout_seconds: int | None = None,
) -> tuple[int, str, str]:
    if timeout_seconds is None:
        timeout_seconds = (
            DEFAULT_INSTALL_TIMEOUT_SECONDS
            if _is_dependency_install(args)
            else DEFAULT_TIMEOUT_SECONDS
        )
    try:
        r = subprocess.run(
            args,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        command = Path(args[0]).name if args else "command"
        detail = stderr.strip() or f"{command} timed out after {timeout_seconds}s"
        return 124, stdout, detail
    except OSError as exc:
        return 1, "", str(exc)
    return r.returncode, r.stdout, r.stderr


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prove installed package metadata, imported module __version__, and "
            "CLI version-check --status agree on one version."
        ),
    )
    parser.add_argument(
        "--install-spec",
        default=".",
        help="pip install spec, e.g. '.' for the current checkout or 'mempalace-code==1.2.3' (default: .).",
    )
    parser.add_argument(
        "--package",
        default=DEFAULT_PACKAGE,
        help=f"Distribution name to check metadata for (default: {DEFAULT_PACKAGE}).",
    )
    installer_mode = parser.add_mutually_exclusive_group()
    installer_mode.add_argument(
        "--installer",
        choices=INSTALLERS,
        default=INSTALLER_VENV,
        help="Disposable environment kind to install into (default: venv).",
    )
    installer_mode.add_argument(
        "--all-installers",
        action="store_true",
        help="Run every required installer in canonical release order; incompatible with --installer.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=None,
        help=(
            "Override every subprocess timeout in seconds "
            f"(defaults: probes {DEFAULT_TIMEOUT_SECONDS}, installs "
            f"{DEFAULT_INSTALL_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output machine-readable JSON with ok, expected_version, installer, install_spec, "
        "surfaces, and diagnostics.",
    )
    args = parser.parse_args(argv)

    def run_subprocess(
        cmd: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        input_text: str | None = None,
    ) -> tuple[int, str, str]:
        return _default_run_subprocess(
            cmd,
            env=env,
            cwd=cwd,
            input_text=input_text,
            timeout_seconds=args.timeout_seconds,
        )

    runners = {
        INSTALLER_VENV: run_venv_smoke,
        INSTALLER_PIPX: run_pipx_smoke,
        INSTALLER_UV_TOOL: run_uv_tool_smoke,
        INSTALLER_BOOTSTRAP_VENV: run_bootstrap_venv_smoke,
    }
    if args.all_installers:
        result = run_all_installers_smoke(args.install_spec, args.package, run_subprocess)
    else:
        result = runners[args.installer](
            args.install_spec,
            args.package,
            run_subprocess,
            recovery_safety=not sys.platform.startswith("linux"),
        )

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if isinstance(result, AggregateSmokeResult):
            print(render_aggregate_human(result))
        else:
            print(render_human(result))

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
