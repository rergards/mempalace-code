#!/usr/bin/env python3
"""Run release checks before creating or publishing a tag.

Default checks validate only the checked-out tree and stay deterministic and
network-free. ``--check-live-upstream`` explicitly adds the shared read-only
upstream head comparison. This guard never tags, pushes, creates a release, or
contacts package registries.
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


def check_tag_identity(
    root: Path,
    version: str,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
) -> dict[str, str]:
    """Fail when refs/tags/v{version} already exists but points away from HEAD.

    A same-version tag that resolves to a different commit means a published,
    immutable release is being silently reused for different content. An absent
    tag (not yet released) and a matching tag (re-running preflight against the
    tagged commit, e.g. in publish.yml) are both valid and pass.
    """
    expected_tag = f"v{version}"
    rc, tag_commit = run(
        ["git", "rev-parse", "--verify", "-q", f"refs/tags/{expected_tag}^{{commit}}"], root
    )
    # `git rev-parse --verify -q` documents exit code 1 for "ref does not resolve to
    # an object" — that is the only code meaning absence. Any other nonzero code
    # (e.g. 128 for a missing/corrupt repository, or a permission failure) means the
    # lookup itself is untrustworthy, so fail closed instead of assuming no tag.
    if rc == 1:
        return {
            "name": "tag_identity",
            "status": "ok",
            "detail": f"no existing tag {expected_tag}",
        }
    if rc != 0:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": (
                f"could not resolve tag {expected_tag} (git rev-parse exited {rc}): "
                f"{tag_commit or 'no output'}"
            ),
        }
    tag_commit = tag_commit.strip()
    if not tag_commit:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": f"git rev-parse for tag {expected_tag} succeeded but returned no commit",
        }

    rc, head_commit = run(["git", "rev-parse", "HEAD"], root)
    if rc != 0:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": head_commit or "git rev-parse HEAD failed",
        }
    head_commit = head_commit.strip()
    if not head_commit:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": "git rev-parse HEAD succeeded but returned no commit",
        }

    if tag_commit != head_commit:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": (
                f"tag {expected_tag} already points to {tag_commit}, not HEAD "
                f"({head_commit}); bump project.version before reusing a published tag"
            ),
        }
    return {
        "name": "tag_identity",
        "status": "ok",
        "detail": f"tag {expected_tag} matches HEAD ({head_commit})",
    }


def evaluate(
    root: Path,
    *,
    tag: str | None,
    require_clean: bool,
    check_live_upstream: bool = False,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
) -> tuple[str, list[dict[str, str]]]:
    """Return package version and one result object per local release invariant.

    The default stays deterministic and network-free.  ``check_live_upstream`` is
    the explicit pre-tag opt-in that delegates the one bounded read-only lookup
    to the shared upstream comparison guard.
    """
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

    checks.append(check_tag_identity(root, version, run))

    commands = [
        ("docs_drift", [sys.executable, "scripts/docs_drift_guard.py"]),
        ("public_safety", [sys.executable, "scripts/public_safety_scan.py", "--committed"]),
        ("upstream_comparison", [sys.executable, "scripts/upstream_comparison_guard.py"]),
    ]
    if check_live_upstream:
        commands.append(
            (
                "live_upstream_comparison",
                [sys.executable, "scripts/upstream_comparison_guard.py", "--check-live"],
            )
        )
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
    parser.add_argument(
        "--check-live-upstream",
        action="store_true",
        help=(
            "Opt in to the read-only live upstream branch-head comparison; "
            "fails closed on drift or an untrusted response."
        ),
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON.")
    args = parser.parse_args(argv)

    try:
        version, checks = evaluate(
            args.root.resolve(),
            tag=args.tag,
            require_clean=args.require_clean,
            check_live_upstream=args.check_live_upstream,
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
