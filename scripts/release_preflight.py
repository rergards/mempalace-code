#!/usr/bin/env python3
"""Run deterministic local release checks before creating or publishing a tag.

This guard validates only the checked-out tree. It never tags, pushes, creates a
release, or contacts package registries.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def package_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle).get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("pyproject.toml must define project.version")
    return version


def validate_tag(version: str, tag: str | None) -> str | None:
    if tag is None:
        return None
    expected = f"v{version}"
    if tag != expected:
        return f"tag {tag!r} does not match package version {expected!r}"
    return None


def _run(command: list[str], root: Path) -> tuple[int, str]:
    completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
    output = (completed.stderr or completed.stdout).strip()
    return completed.returncode, output


def evaluate(
    root: Path,
    *,
    tag: str | None,
    require_clean: bool,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
) -> tuple[str, list[dict[str, str]]]:
    """Return package version and one result object per local release invariant."""
    version = package_version(root)
    checks: list[dict[str, str]] = []

    tag_error = validate_tag(version, tag)
    checks.append(
        {
            "name": "tag_version",
            "status": "fail" if tag_error else "ok",
            "detail": tag_error or f"package version is v{version}",
        }
    )

    commands = [
        ("docs_drift", [sys.executable, "scripts/docs_drift_guard.py"]),
        ("public_safety", [sys.executable, "scripts/public_safety_scan.py", "--committed"]),
        # Static mode only — the local preflight must stay network-free. The live
        # upstream head comparison runs in publish.yml and upstream-drift.yml.
        ("upstream_comparison", [sys.executable, "scripts/upstream_comparison_guard.py"]),
    ]
    for name, command in commands:
        rc, output = run(command, root)
        checks.append(
            {
                "name": name,
                "status": "ok" if rc == 0 else "fail",
                "detail": output or "passed",
            }
        )

    if require_clean:
        rc, output = run(["git", "status", "--porcelain"], root)
        clean = rc == 0 and not output
        checks.append(
            {
                "name": "clean_tree",
                "status": "ok" if clean else "fail",
                "detail": "worktree is clean" if clean else output or "git status failed",
            }
        )

    return version, checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local release invariants without tag, push, publish, or network mutation."
    )
    parser.add_argument(
        "--root", type=Path, default=repo_root(), help="Repository root to inspect."
    )
    parser.add_argument("--tag", help="Expected release tag, for example v1.2.3.")
    parser.add_argument(
        "--require-clean", action="store_true", help="Fail when git worktree is dirty."
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON.")
    args = parser.parse_args(argv)

    try:
        version, checks = evaluate(
            args.root.resolve(), tag=args.tag, require_clean=args.require_clean
        )
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(f"release-preflight: ERROR — {exc}", file=sys.stderr)
        return 1

    ok = all(check["status"] == "ok" for check in checks)
    result = {"ok": ok, "version": version, "checks": checks}
    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"release-preflight: {'OK' if ok else 'FAIL'} version=v{version}")
        for check in checks:
            print(f"  {check['status']}: {check['name']} — {check['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
