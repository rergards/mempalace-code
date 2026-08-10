#!/usr/bin/env python3
"""release_install_metadata_smoke.py — Prove installed metadata, module, and CLI status agree.

Stdlib-only — no project imports, no third-party dependencies.

Usage:
    python scripts/release_install_metadata_smoke.py --install-spec . --json
    python scripts/release_install_metadata_smoke.py --install-spec mempalace-code==1.2.3
    python scripts/release_install_metadata_smoke.py --installer pipx --install-spec mempalace-code==1.2.3

Installs mempalace-code into a disposable environment (a fresh venv by default,
or a disposable pipx-style tool environment with --installer pipx) and compares
three version surfaces:
  1. importlib.metadata.version("mempalace-code")  (installed package metadata)
  2. mempalace_code.__version__                     (imported module)
  3. `mempalace-code version-check --status`         (installed console script)

Probes run from a neutral temporary working directory outside the source tree
so a source checkout's pyproject.toml cannot shadow the installed package.

Exits 0 only when all three surfaces report the same version.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    RunSubprocess = Callable[..., tuple[int, str, str]]

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_PACKAGE = "mempalace-code"
MODULE_NAME = "mempalace_code"
CONSOLE_SCRIPT = "mempalace-code"
DEFAULT_TIMEOUT_SECONDS = 300

INSTALLER_VENV = "venv"
INSTALLER_PIPX = "pipx"
INSTALLERS = (INSTALLER_VENV, INSTALLER_PIPX)

SURFACE_INSTALL = "install"
SURFACE_METADATA = "package_metadata"
SURFACE_MODULE = "module_version"
SURFACE_CLI = "cli_version_check"

REQUIRED_SURFACES = [SURFACE_METADATA, SURFACE_MODULE, SURFACE_CLI]

STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_ERROR = "error"

_CURRENT_VERSION_RE = re.compile(r"^\s*Current version:\s*(\S+)\s*$", re.MULTILINE)

_PROBE_SCRIPT = (
    "import importlib.metadata\n"
    "try:\n"
    "    print('METADATA=' + importlib.metadata.version('mempalace-code'))\n"
    "except Exception as exc:\n"
    "    print('METADATA-ERROR=' + str(exc))\n"
    "try:\n"
    "    import mempalace_code\n"
    "    print('MODULE=' + mempalace_code.__version__)\n"
    "except Exception as exc:\n"
    "    print('MODULE-ERROR=' + str(exc))\n"
)

# ── Sanitization (mirrors scripts/release_status_gate.py) ─────────────────────

_TOKEN_RE = re.compile(
    r"\b(?:[g]hp_|[g]ithub_pat_|[p]ypi-)[A-Za-z0-9_\-]{4,}\S*",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"(/(?:Users|home|root|tmp)/[^\s:,\"']*|/var/folders/[^\s:,\"']*)")
_PRIVATE_REMOTE_RE = re.compile(r"git@[a-zA-Z0-9._-]+:[^\s\"']+")


def sanitize(text: str) -> str:
    """Remove tokens, local paths, and private remotes from diagnostic text."""
    return _PRIVATE_REMOTE_RE.sub(
        "[REDACTED-REMOTE]",
        _PATH_RE.sub("[REDACTED-PATH]", _TOKEN_RE.sub("[REDACTED-TOKEN]", text)),
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

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "expected_version": self.expected_version,
            "installer": self.installer,
            "install_spec": self.install_spec,
            "surfaces": [s.to_dict() for s in self.surfaces],
            "diagnostics": self.diagnostics,
        }


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


# ── Probes ─────────────────────────────────────────────────────────────────────


def probe_metadata_and_module(
    python_bin: str,
    probe_cwd: str,
    run_subprocess: RunSubprocess,
    env: dict[str, str] | None = None,
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
    for line in out.splitlines():
        if line.startswith("METADATA="):
            metadata_version = line[len("METADATA=") :].strip()
        elif line.startswith("METADATA-ERROR="):
            metadata_error = line[len("METADATA-ERROR=") :].strip()
        elif line.startswith("MODULE="):
            module_version = line[len("MODULE=") :].strip()
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

    return SmokeResult(
        ok=ok,
        expected_version=expected_version,
        installer=installer,
        install_spec=install_spec,
        surfaces=surfaces,
        diagnostics=diagnostics,
    )


# ── Installer flows ─────────────────────────────────────────────────────────────


def run_venv_smoke(
    install_spec: str,
    package: str,
    run_subprocess: RunSubprocess,
) -> SmokeResult:
    """Install into a fresh disposable venv (non-editable) and probe all three surfaces."""
    with tempfile.TemporaryDirectory(prefix="mempalace-install-smoke-") as tmpdir:
        tmp_root = Path(tmpdir)
        venv_dir = tmp_root / "venv"
        probe_cwd = tmp_root / "probe-cwd"
        probe_cwd.mkdir()

        rc, _out, err = run_subprocess([sys.executable, "-m", "venv", str(venv_dir)])
        if rc != 0:
            detail = sanitize(err.strip()) or f"venv creation exited {rc}"
            surfaces = [
                SurfaceResult(SURFACE_INSTALL, STATUS_ERROR, f"venv creation failed: {detail}")
            ]
            return SmokeResult(False, None, INSTALLER_VENV, install_spec, surfaces, [])

        pip = str(venv_dir / "bin" / "pip")
        python_bin = str(venv_dir / "bin" / "python")
        console_bin = str(venv_dir / "bin" / CONSOLE_SCRIPT)

        rc, out, err = run_subprocess([pip, "install", "--no-cache-dir", install_spec])
        if rc != 0:
            detail = sanitize((err or out).strip()) or f"pip install exited {rc}"
            surfaces = [SurfaceResult(SURFACE_INSTALL, STATUS_FAIL, f"install failed: {detail}")]
            return SmokeResult(False, None, INSTALLER_VENV, install_spec, surfaces, [])

        metadata_result, module_result = probe_metadata_and_module(
            python_bin, str(probe_cwd), run_subprocess
        )
        cli_result = probe_cli_version_check(console_bin, str(probe_cwd), run_subprocess)

        surfaces = [metadata_result, module_result, cli_result]
        return evaluate_smoke(surfaces, package, install_spec, INSTALLER_VENV)


def run_pipx_smoke(
    install_spec: str,
    package: str,
    run_subprocess: RunSubprocess,
) -> SmokeResult:
    """Install via pipx into disposable PIPX_HOME/PIPX_BIN_DIR and probe all three surfaces.

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

        env = dict(os.environ)
        env["PIPX_HOME"] = str(pipx_home)
        env["PIPX_BIN_DIR"] = str(pipx_bin)

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
            venv_python, str(probe_cwd), run_subprocess, env=env
        )
        cli_result = probe_cli_version_check(console_bin, str(probe_cwd), run_subprocess, env=env)

        surfaces = [metadata_result, module_result, cli_result]
        return evaluate_smoke(surfaces, package, install_spec, INSTALLER_PIPX)


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


# ── Default subprocess callable ────────────────────────────────────────────────


def _default_run_subprocess(
    args: list[str],
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_seconds, env=env, cwd=cwd
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
    parser.add_argument(
        "--installer",
        choices=INSTALLERS,
        default=INSTALLER_VENV,
        help="Disposable environment kind to install into (default: venv).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-subprocess timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
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
        cmd: list[str], env: dict[str, str] | None = None, cwd: str | None = None
    ) -> tuple[int, str, str]:
        return _default_run_subprocess(cmd, env=env, cwd=cwd, timeout_seconds=args.timeout_seconds)

    if args.installer == INSTALLER_PIPX:
        result = run_pipx_smoke(args.install_spec, args.package, run_subprocess)
    else:
        result = run_venv_smoke(args.install_spec, args.package, run_subprocess)

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_human(result))

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
