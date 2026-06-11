#!/usr/bin/env python3
"""release_status_gate.py — Verify all public publication surfaces before calling a release shipped.

Stdlib-only — no project imports, no third-party dependencies.

Usage:
    python scripts/release_status_gate.py --version X.Y.Z [options]
    python scripts/release_status_gate.py --help

Checks (in order):
  1. publish remote git tag
  2. branch Tests workflow (GitHub Actions)
  3. Publish to PyPI workflow (GitHub Actions)
  4. GitHub Release metadata (non-draft, non-prerelease, latest, matching tag)
  5. PyPI JSON (version, wheel and sdist files)
  6. Install smoke (pip install --no-cache-dir in a disposable venv)

Exits 0 only when all required public surfaces agree.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import urlopen

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Constants ──────────────────────────────────────────────────────────────────

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
DEFAULT_PACKAGE = "mempalace-code"
DEFAULT_REPO = "rergards/mempalace-code"
DEFAULT_REMOTE = "publish"
DEFAULT_BRANCH = "main"
TESTS_WORKFLOW = "Tests"
PUBLISH_WORKFLOW = "Publish to PyPI"

SURFACE_TAG = "publish_remote_tag"
SURFACE_TESTS = "branch_tests_workflow"
SURFACE_PUBLISH = "publish_to_pypi_workflow"
SURFACE_RELEASE = "github_release"
SURFACE_PYPI = "pypi_json"
SURFACE_SMOKE = "install_smoke"

REQUIRED_SURFACES = [
    SURFACE_TAG,
    SURFACE_TESTS,
    SURFACE_PUBLISH,
    SURFACE_RELEASE,
    SURFACE_PYPI,
    SURFACE_SMOKE,
]

STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"
STATUS_ERROR = "error"

# ── Sanitization ───────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"\b(ghp_|github_pat_|pypi-)[A-Za-z0-9_\-]{4,}\S*", re.IGNORECASE)
_PATH_RE = re.compile(r"(/(?:Users|home|root)/[^\s:,\"']*|/var/folders/[^\s:,\"']*)")
_PRIVATE_REMOTE_RE = re.compile(r"git@[a-zA-Z0-9._-]+:[^\s\"']+")


def sanitize(text: str) -> str:
    """Remove tokens, local paths, and private remotes from error text."""
    return _PRIVATE_REMOTE_RE.sub(
        "[REDACTED-REMOTE]",
        _PATH_RE.sub("[REDACTED-PATH]", _TOKEN_RE.sub("[REDACTED-TOKEN]", text)),
    )


# ── Result types ───────────────────────────────────────────────────────────────


@dataclass
class SurfaceResult:
    name: str
    status: str  # ok | fail | skip | error
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass
class GateResult:
    version: str
    ok: bool
    partial: bool
    surfaces: list[SurfaceResult] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "partial": self.partial,
            "version": self.version,
            "surfaces": [s.to_dict() for s in self.surfaces],
            "blockers": self.blockers,
        }


# ── Surface checks ─────────────────────────────────────────────────────────────


def check_publish_remote_tag(
    version: str,
    remote: str,
    run_git: Callable[[list[str]], tuple[int, str, str]],
) -> SurfaceResult:
    tag = f"refs/tags/v{version}"
    exit_code, stdout, stderr = run_git(["ls-remote", "--tags", remote, tag])
    if exit_code != 0:
        return SurfaceResult(
            SURFACE_TAG, STATUS_ERROR, f"git ls-remote failed: {sanitize(stderr.strip())}"
        )
    if tag in stdout:
        return SurfaceResult(SURFACE_TAG, STATUS_OK, f"tag v{version} found on remote {remote!r}")
    return SurfaceResult(SURFACE_TAG, STATUS_FAIL, f"tag v{version} not found on remote {remote!r}")


def check_workflow_run(
    surface_name: str,
    workflow: str,
    repo: str,
    extra_args: list[str],
    run_gh: Callable[[list[str]], tuple[int, str, str]],
) -> SurfaceResult:
    gh_args = [
        "run",
        "list",
        "--repo",
        repo,
        "--workflow",
        workflow,
        "--json",
        "status,conclusion,headBranch,headSha,displayTitle,url",
        "--limit",
        "10",
        *extra_args,
    ]
    exit_code, stdout, stderr = run_gh(gh_args)
    if exit_code != 0:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"gh run list failed for {workflow!r}: {sanitize(stderr.strip())}",
        )
    try:
        runs = json.loads(stdout)
    except json.JSONDecodeError as e:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"could not parse gh run list output: {sanitize(str(e))}",
        )
    if not isinstance(runs, list):
        return SurfaceResult(
            surface_name, STATUS_ERROR, f"unexpected gh run list response shape for {workflow!r}"
        )
    completed = [r for r in runs if isinstance(r, dict) and r.get("status") == "completed"]
    if not completed:
        return SurfaceResult(
            surface_name, STATUS_FAIL, f"no completed runs found for workflow {workflow!r}"
        )
    most_recent = completed[0]
    if most_recent.get("conclusion") == "success":
        return SurfaceResult(
            surface_name, STATUS_OK, f"workflow {workflow!r} most recent completed run succeeded"
        )
    conclusion = str(most_recent.get("conclusion", "unknown"))
    return SurfaceResult(
        surface_name,
        STATUS_FAIL,
        f"workflow {workflow!r} most recent completed run has conclusion: {conclusion!r}",
    )


def check_github_release(
    version: str,
    repo: str,
    run_gh: Callable[[list[str]], tuple[int, str, str]],
    allow_prerelease: bool = False,
) -> SurfaceResult:
    gh_args = [
        "release",
        "view",
        f"v{version}",
        "--repo",
        repo,
        "--json",
        "tagName,isDraft,isPrerelease,isLatest,publishedAt,url,targetCommitish",
    ]
    exit_code, stdout, stderr = run_gh(gh_args)
    if exit_code != 0:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            f"gh release view failed: {sanitize(stderr.strip())}",
        )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            f"could not parse gh release view output: {sanitize(str(e))}",
        )
    if not isinstance(data, dict):
        return SurfaceResult(
            SURFACE_RELEASE, STATUS_ERROR, "unexpected gh release view response shape"
        )
    tag_name = data.get("tagName", "")
    is_draft = data.get("isDraft", True)
    is_prerelease = data.get("isPrerelease", True)
    is_latest = data.get("isLatest", False)

    if tag_name != f"v{version}":
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_FAIL,
            f"release tag {tag_name!r} does not match expected v{version}",
        )
    if is_draft:
        return SurfaceResult(SURFACE_RELEASE, STATUS_FAIL, f"GitHub Release v{version} is a draft")
    if is_prerelease and not allow_prerelease:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_FAIL,
            f"GitHub Release v{version} is a prerelease (pass --allow-prerelease to allow)",
        )
    if not is_latest:
        return SurfaceResult(
            SURFACE_RELEASE, STATUS_FAIL, f"GitHub Release v{version} is not the latest release"
        )
    return SurfaceResult(
        SURFACE_RELEASE,
        STATUS_OK,
        f"GitHub Release v{version} is non-draft, non-prerelease, and latest",
    )


def check_pypi(
    version: str,
    package: str,
    http_get: Callable[[str], tuple[int, bytes, str]],
) -> SurfaceResult:
    url = PYPI_JSON_URL.format(package=package)
    status_code, body, error = http_get(url)
    if status_code != 200:
        msg = sanitize(error) if error else f"HTTP {status_code}"
        return SurfaceResult(SURFACE_PYPI, STATUS_ERROR, f"PyPI JSON fetch failed: {msg}")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return SurfaceResult(SURFACE_PYPI, STATUS_ERROR, f"could not parse PyPI JSON response: {e}")
    if not isinstance(data, dict):
        return SurfaceResult(SURFACE_PYPI, STATUS_ERROR, "unexpected PyPI JSON response shape")

    info_version = data.get("info", {}).get("version", "")
    if info_version != version:
        return SurfaceResult(
            SURFACE_PYPI,
            STATUS_FAIL,
            f"PyPI latest version is {info_version!r}, expected {version!r}",
        )
    releases = data.get("releases", {})
    files = releases.get(version, [])
    if not files:
        return SurfaceResult(
            SURFACE_PYPI,
            STATUS_FAIL,
            f"no distribution files found for {package}=={version} on PyPI",
        )
    types = {f.get("packagetype", "") for f in files if isinstance(f, dict)}
    missing = []
    if "bdist_wheel" not in types:
        missing.append("wheel")
    if "sdist" not in types:
        missing.append("sdist")
    if missing:
        return SurfaceResult(
            SURFACE_PYPI,
            STATUS_FAIL,
            f"missing distribution types for {package}=={version}: {missing}",
        )
    return SurfaceResult(SURFACE_PYPI, STATUS_OK, f"PyPI {package}=={version} has wheel and sdist")


def check_install_smoke(
    version: str,
    package: str,
    run_subprocess: Callable[[list[str]], tuple[int, str, str]],
) -> SurfaceResult:
    """Run no-cache install smoke in a disposable venv."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            venv_dir = Path(tmpdir) / "venv"
            rc, _, err = run_subprocess([sys.executable, "-m", "venv", str(venv_dir)])
            if rc != 0:
                return SurfaceResult(
                    SURFACE_SMOKE,
                    STATUS_ERROR,
                    f"venv creation failed: {sanitize(err.strip())}",
                )
            pip = str(venv_dir / "bin" / "pip")
            rc, out, err = run_subprocess(
                [pip, "install", "--no-cache-dir", f"{package}=={version}"]
            )
            if rc != 0:
                detail = sanitize((err or out).strip())
                return SurfaceResult(SURFACE_SMOKE, STATUS_FAIL, f"install smoke failed: {detail}")
            return SurfaceResult(
                SURFACE_SMOKE, STATUS_OK, f"no-cache install of {package}=={version} succeeded"
            )
    except OSError as exc:
        return SurfaceResult(
            SURFACE_SMOKE,
            STATUS_ERROR,
            f"install smoke setup failed: {sanitize(str(exc))}",
        )


# ── Gate orchestration ─────────────────────────────────────────────────────────


def run_gate(
    version: str,
    repo: str,
    remote: str,
    branch: str,
    package: str,
    allow_prerelease: bool,
    skip_smoke: bool,
    run_git: Callable[[list[str]], tuple[int, str, str]],
    run_gh: Callable[[list[str]], tuple[int, str, str]],
    http_get: Callable[[str], tuple[int, bytes, str]],
    run_subprocess: Callable[[list[str]], tuple[int, str, str]],
) -> GateResult:
    surfaces: list[SurfaceResult] = []

    surfaces.append(check_publish_remote_tag(version, remote, run_git))
    surfaces.append(
        check_workflow_run(SURFACE_TESTS, TESTS_WORKFLOW, repo, ["--branch", branch], run_gh)
    )
    surfaces.append(check_workflow_run(SURFACE_PUBLISH, PUBLISH_WORKFLOW, repo, [], run_gh))
    surfaces.append(check_github_release(version, repo, run_gh, allow_prerelease))
    surfaces.append(check_pypi(version, package, http_get))

    if skip_smoke:
        surfaces.append(
            SurfaceResult(SURFACE_SMOKE, STATUS_SKIP, "install smoke skipped by operator")
        )
        partial = True
    else:
        surfaces.append(check_install_smoke(version, package, run_subprocess))
        partial = False

    blockers = [s.detail for s in surfaces if s.status in (STATUS_FAIL, STATUS_ERROR)]
    ok = len(blockers) == 0 and not partial

    return GateResult(
        version=version,
        ok=ok,
        partial=partial,
        surfaces=surfaces,
        blockers=blockers,
    )


# ── Output formatting ──────────────────────────────────────────────────────────

_STATUS_ICON = {STATUS_OK: "✓", STATUS_FAIL: "✗", STATUS_SKIP: "○", STATUS_ERROR: "!"}


def render_human(result: GateResult) -> str:
    lines = [f"## Release v{result.version}", ""]
    for s in result.surfaces:
        icon = _STATUS_ICON.get(s.status, "?")
        lines.append(f"  {icon} {s.name}: {s.detail}")
    lines.append("")
    if result.ok:
        lines.append(f"Release v{result.version}: SHIPPED — all surfaces green.")
    elif result.partial and not result.blockers:
        lines.append(
            f"Release v{result.version}: DIAGNOSTIC — install smoke skipped; no other blockers."
        )
    else:
        lines.append(f"Release v{result.version}: NOT SHIPPED")
        lines.append("")
        lines.append("Remaining blockers:")
        for b in result.blockers:
            lines.append(f"  - {b}")
    return "\n".join(lines)


# ── Default subprocess/HTTP callables ─────────────────────────────────────────


def _default_run_git(args: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _default_run_gh(args: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _default_http_get(url: str) -> tuple[int, bytes, str]:
    try:
        with urlopen(url, timeout=30) as resp:  # noqa: S310  # reason: public PyPI endpoint, URL not user-controlled
            return resp.status, resp.read(), ""
    except URLError as e:
        return 0, b"", str(e)


def _default_run_subprocess(args: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(args, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


# ── Version resolution ─────────────────────────────────────────────────────────


def _version_from_pyproject(root: Path) -> str | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        version = data.get("project", {}).get("version")
        return str(version) if version else None
    except Exception:  # noqa: BLE001  # reason: version fallback; any parse failure returns None
        return None


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify all public publication surfaces before calling a release shipped.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Checks: publish remote tag, branch Tests workflow, Publish to PyPI workflow,
GitHub Release metadata, PyPI JSON (wheel + sdist), install smoke.

Exits 0 only when all required surfaces agree (or all agree excluding skipped smoke).
        """,
    )
    parser.add_argument(
        "--version",
        "-v",
        help="Package version to verify (e.g. 1.2.3). Derived from pyproject.toml when omitted.",
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"GitHub repository owner/name (default: {DEFAULT_REPO}).",
    )
    parser.add_argument(
        "--remote",
        default=DEFAULT_REMOTE,
        help=f"Git remote for the publish tag check (default: {DEFAULT_REMOTE}).",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_BRANCH,
        help=f"Branch for the branch Tests workflow check (default: {DEFAULT_BRANCH}).",
    )
    parser.add_argument(
        "--package",
        default=DEFAULT_PACKAGE,
        help=f"PyPI package name (default: {DEFAULT_PACKAGE}).",
    )
    parser.add_argument(
        "--allow-prerelease",
        action="store_true",
        help="Allow prerelease GitHub Releases (default: prerelease blocks the gate).",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip install smoke. Result is diagnostic-only; cannot be labeled fully shipped.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output machine-readable JSON with ok, version, surfaces, and blockers.",
    )
    args = parser.parse_args(argv)

    version = args.version
    if not version:
        version = _version_from_pyproject(Path("."))
    if not version:
        print(
            "release-status-gate: ERROR — could not determine version; pass --version X.Y.Z",
            file=sys.stderr,
        )
        return 1

    result = run_gate(
        version=version,
        repo=args.repo,
        remote=args.remote,
        branch=args.branch,
        package=args.package,
        allow_prerelease=args.allow_prerelease,
        skip_smoke=args.skip_smoke,
        run_git=_default_run_git,
        run_gh=_default_run_gh,
        http_get=_default_http_get,
        run_subprocess=_default_run_subprocess,
    )

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_human(result))

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
