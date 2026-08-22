#!/usr/bin/env python3
"""release_readiness_gate.py — Orchestrate the complete release-readiness check.

One command that runs the canonical gate inventory, builds artifacts in a
controlled output directory, runs twine check, artifact member inspection, and
installed smoke, then exits nonzero on any failed row.

Usage:
    python scripts/release_readiness_gate.py --check --json
    python scripts/release_readiness_gate.py --artifact-only --json
    python scripts/release_readiness_gate.py --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

PACKAGE_NAME = "mempalace-code"
DEFAULT_TIMEOUT = 120
DEFAULT_REPO = "rergards/mempalace-code"
DEFAULT_REMOTE = "publish"
DEFAULT_BRANCH = "main"

_ADMISSION_CHECKS_MODULE = None

# ── Loader helpers ─────────────────────────────────────────────────────────────


def _load_sibling(name: str, script_name: str):
    path = Path(__file__).resolve().parent / script_name
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_admission_checks():
    global _ADMISSION_CHECKS_MODULE
    if _ADMISSION_CHECKS_MODULE is None:
        _ADMISSION_CHECKS_MODULE = _load_sibling(
            "release_admission_checks", "release_admission_checks.py"
        )
    return _ADMISSION_CHECKS_MODULE


# ── Gate row ──────────────────────────────────────────────────────────────────


def _make_row(gate_id: str, command: str, status: str, detail: str) -> dict:
    return {
        "id": gate_id,
        "command": command,
        "status": status,
        "detail": detail,
    }


def _admission_row_to_gate_row(row, command: str) -> dict:
    status = "pass" if row.status == "ok" else row.status
    result = _make_row(row.name, command, status, row.detail)
    if row.remediation:
        result["remediation"] = row.remediation
    return result


READ_ONLY_LOOKUP_TIMEOUT = 60


def _bounded(command: list[str]) -> tuple[int, str, str]:
    """Run one read-only lookup with a bounded runtime; a timeout is a failure."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=READ_ONLY_LOOKUP_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"{command[0]} timed out after {READ_ONLY_LOOKUP_TIMEOUT}s"
    except OSError as exc:
        return 127, "", f"could not run {command[0]}: {exc}"
    return result.returncode, result.stdout, result.stderr


def _default_run_git(args: list[str]) -> tuple[int, str, str]:
    return _bounded(["git", *args])


def _default_run_gh(args: list[str]) -> tuple[int, str, str]:
    return _bounded(["gh", *args])


def _default_http_get(url: str) -> tuple[int, bytes, str]:
    try:
        with urlopen(url, timeout=30) as response:  # noqa: S310  # reason: public PyPI endpoint
            return response.status, response.read(), ""
    except URLError as exc:
        return 0, b"", str(exc)


def _run_public_admission_checks(
    *,
    version: str,
    repo: str,
    remote: str,
    branch: str,
    package: str,
    candidate_sha: str | None,
    required_check_name: str,
    audit_max_age_hours: int,
    run_git,
    run_gh,
    http_get,
) -> list[dict]:
    admission = _load_admission_checks()
    rows = [
        _admission_row_to_gate_row(
            admission.check_aggregate_required_check(
                candidate_sha,
                repo,
                run_gh,
                check_name=required_check_name,
            ),
            "gh api repos/<repo>/commits/<sha>/check-runs",
        )
    ]
    rows.append(
        _admission_row_to_gate_row(
            admission.check_main_branch_rules(
                repo,
                branch,
                run_gh,
                check_name=required_check_name,
            ),
            "gh api repos/<repo>/rules/branches/<branch>",
        )
    )
    rows.append(
        _admission_row_to_gate_row(
            admission.check_tag_ruleset(repo, run_gh),
            "gh api repos/<repo>/rulesets",
        )
    )
    rows.append(
        _admission_row_to_gate_row(
            admission.check_public_orphan_tags(
                version,
                repo,
                remote,
                package,
                run_git,
                run_gh,
                http_get,
                # Pre-publication: v{version} does not exist publicly yet, so its
                # absence is the expected state rather than an orphan finding.
                require_expected_tag=False,
            ),
            "git ls-remote --tags --refs <remote> refs/tags/v*",
        )
    )
    rows.append(
        _admission_row_to_gate_row(
            admission.check_dependency_audit_freshness(
                repo,
                run_gh,
                max_age_hours=audit_max_age_hours,
            ),
            "gh run list --repo <repo> --workflow 'Dependency Audit'",
        )
    )
    return rows


# ── Inventory check ───────────────────────────────────────────────────────────


def _run_inventory_check(root: Path) -> list[dict]:
    gate_inventory = _load_sibling("_gate_inventory_readiness", "gate_inventory.py")
    errors = gate_inventory.check_parity(root)
    if errors:
        return [
            _make_row(
                "gate_inventory",
                "python scripts/gate_inventory.py --check",
                "fail",
                "; ".join(errors[:5]),
            )
        ]
    return [
        _make_row(
            "gate_inventory",
            "python scripts/gate_inventory.py --check",
            "pass",
            f"{len(gate_inventory.CANONICAL_GATES)} gates, parity ok",
        )
    ]


# ── Artifact build ────────────────────────────────────────────────────────────


def _build_artifacts(root: Path, out_dir: Path) -> tuple[bool, str]:
    """Build wheel and sdist into out_dir. Returns (ok, detail)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "build", "--outdir", str(out_dir), str(root)],
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            cwd=str(root),
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout)[:500]
        return True, f"built to {out_dir}"
    except FileNotFoundError:
        return False, "build tool not installed (pip install build)"
    except subprocess.TimeoutExpired:
        return False, "build timed out"


# ── Artifact inspection ───────────────────────────────────────────────────────


def _run_artifact_inspection(dist_dir: Path) -> list[dict]:
    rag = _load_sibling("_release_artifact_gate_readiness", "release_artifact_gate.py")
    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=True)
    rows = []
    for row in result["rows"]:
        rows.append(
            _make_row(
                f"artifact_{row['check'].replace('-', '_')}",
                f"artifact-gate:{row['check']}",
                row["status"],
                row["detail"],
            )
        )
    return rows


# ── Install smoke ─────────────────────────────────────────────────────────────


def _run_install_smoke(dist_dir: Path) -> list[dict]:
    """Run supported install smokes against the built wheel in dist_dir."""
    smoke = _load_sibling("_release_install_smoke_readiness", "release_install_metadata_smoke.py")

    wheels = sorted(dist_dir.glob("*.whl"))
    if not wheels:
        error_detail = "no wheel found in dist dir after build"
        return [
            _make_row(
                f"install_smoke_{installer.replace('-', '_')}",
                f"python scripts/release_install_metadata_smoke.py --installer {installer} --install-spec <wheel> --json",
                "error",
                error_detail,
            )
            for installer in ("venv", "pipx", "uv-tool", "bootstrap-venv")
        ]

    wheel_path = wheels[0]
    rows = []

    installers = [
        ("venv", smoke.run_venv_smoke),
        ("pipx", smoke.run_pipx_smoke),
        ("bootstrap-venv", smoke.run_bootstrap_venv_smoke),
    ]
    if smoke.find_uv_executable() is None:
        rows.append(
            _make_row(
                "install_smoke_uv_tool",
                "python scripts/release_install_metadata_smoke.py --installer uv-tool --install-spec <wheel> --json",
                "skip",
                "uv executable unavailable; optional uv-tool smoke skipped",
            )
        )
    else:
        installers.append(("uv-tool", smoke.run_uv_tool_smoke))

    for installer_name, run_fn in installers:
        gate_id = f"install_smoke_{installer_name.replace('-', '_')}"
        command = (
            f"python scripts/release_install_metadata_smoke.py"
            f" --installer {installer_name} --install-spec {wheel_path.name} --json"
        )
        try:
            result = run_fn(
                install_spec=str(wheel_path),
                package=PACKAGE_NAME,
                run_subprocess=smoke._default_run_subprocess,
            )
            if result.ok:
                rows.append(
                    _make_row(gate_id, command, "pass", f"version={result.expected_version}")
                )
            else:
                diag = "; ".join(result.diagnostics[:3])
                rows.append(_make_row(gate_id, command, "fail", diag))
        except Exception as exc:  # noqa: BLE001  # reason: surface smoke failures as gate rows
            rows.append(_make_row(gate_id, command, "error", str(exc)[:300]))

    return rows


# ── Orchestration ──────────────────────────────────────────────────────────────


def run_readiness(
    root: Path,
    *,
    artifact_only: bool = False,
    skip_smoke: bool = False,
    public_admission: bool = False,
    version: str = "",
    repo: str = DEFAULT_REPO,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    package: str = PACKAGE_NAME,
    candidate_sha: str | None = None,
    required_check_name: str | None = None,
    audit_max_age_hours: int | None = None,
    run_git=_default_run_git,
    run_gh=_default_run_gh,
    http_get=_default_http_get,
) -> dict:
    """Run the full release-readiness check and return a structured result dict."""
    all_rows: list[dict] = []
    ok = True

    if not artifact_only:
        inventory_rows = _run_inventory_check(root)
        all_rows.extend(inventory_rows)
        if any(r["status"] == "fail" for r in inventory_rows):
            ok = False

    if public_admission:
        admission = _load_admission_checks()
        admission_rows = _run_public_admission_checks(
            version=version or "unknown",
            repo=repo,
            remote=remote,
            branch=branch,
            package=package,
            candidate_sha=candidate_sha,
            required_check_name=required_check_name or admission.AGGREGATE_REQUIRED_CHECK,
            audit_max_age_hours=audit_max_age_hours or admission.DEFAULT_AUDIT_MAX_AGE_HOURS,
            run_git=run_git,
            run_gh=run_gh,
            http_get=http_get,
        )
        all_rows.extend(admission_rows)
        if any(r["status"] not in ("pass", "skip") for r in admission_rows):
            ok = False

    with tempfile.TemporaryDirectory(prefix="mempalace-readiness-") as tmpdir:
        dist_dir = Path(tmpdir) / "dist"
        dist_dir.mkdir()

        build_ok, build_detail = _build_artifacts(root, dist_dir)
        all_rows.append(
            _make_row(
                "artifact_build",
                "python -m build",
                "pass" if build_ok else "fail",
                build_detail,
            )
        )
        if not build_ok:
            ok = False
        else:
            artifact_rows = _run_artifact_inspection(dist_dir)
            all_rows.extend(artifact_rows)
            if any(r["status"] == "fail" for r in artifact_rows):
                ok = False

            if not artifact_only and not skip_smoke:
                smoke_rows = _run_install_smoke(dist_dir)
                all_rows.extend(smoke_rows)
                if any(r["status"] not in ("pass", "skip") for r in smoke_rows):
                    ok = False

    return {
        "ok": ok,
        "rows": all_rows,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orchestrate the complete release-readiness check."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the full release-readiness gate (inventory + build + artifact + smoke).",
    )
    parser.add_argument(
        "--artifact-only",
        action="store_true",
        help="Only build artifacts and run artifact inspection (skip inventory and smoke).",
    )
    parser.add_argument(
        "--skip-smoke",
        action="store_true",
        help="Skip install smoke check.",
    )
    parser.add_argument(
        "--public-admission",
        action="store_true",
        help="Add read-only public release admission rows for candidate SHA, refs, tags, and audit freshness.",
    )
    parser.add_argument("--version", help="Release version used for public orphan-tag checks.")
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help=f"GitHub repo (default: {DEFAULT_REPO})."
    )
    parser.add_argument(
        "--remote", default=DEFAULT_REMOTE, help=f"Public git remote (default: {DEFAULT_REMOTE})."
    )
    parser.add_argument(
        "--branch", default=DEFAULT_BRANCH, help=f"Public branch (default: {DEFAULT_BRANCH})."
    )
    parser.add_argument(
        "--package", default=PACKAGE_NAME, help=f"PyPI package (default: {PACKAGE_NAME})."
    )
    parser.add_argument("--candidate-sha", help="Operator-reviewed 40-hex candidate SHA.")
    parser.add_argument(
        "--required-check-name",
        default=None,
        help="Aggregate required check name. Defaults to release-required.",
    )
    parser.add_argument(
        "--audit-max-age-hours",
        type=int,
        default=None,
        help="Maximum age for the latest successful dependency-audit run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )
    args = parser.parse_args(argv)

    if not args.check and not args.artifact_only:
        parser.error("specify --check or --artifact-only")

    root = Path(__file__).resolve().parent.parent

    result = run_readiness(
        root,
        artifact_only=args.artifact_only,
        skip_smoke=args.skip_smoke,
        public_admission=args.public_admission,
        version=args.version or "",
        repo=args.repo,
        remote=args.remote,
        branch=args.branch,
        package=args.package,
        candidate_sha=args.candidate_sha,
        required_check_name=args.required_check_name,
        audit_max_age_hours=args.audit_max_age_hours,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for row in result["rows"]:
            mark = (
                "PASS"
                if row["status"] == "pass"
                else ("SKIP" if row["status"] == "skip" else "FAIL")
            )
            print(f"  [{mark}] {row['id']}: {row['detail']}")
        if result["ok"]:
            passing = sum(1 for r in result["rows"] if r["status"] == "pass")
            print(f"release-readiness-gate: OK ({passing}/{len(result['rows'])} checks passed)")
        else:
            failing = [r["id"] for r in result["rows"] if r["status"] not in ("pass", "skip")]
            print(f"release-readiness-gate: FAIL ({failing})", file=sys.stderr)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
