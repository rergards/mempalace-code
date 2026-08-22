#!/usr/bin/env python3
"""Run release checks before creating or publishing a tag.

Default checks validate only the checked-out tree and stay deterministic and
network-free. ``--check-live-upstream`` explicitly adds the shared read-only
upstream head comparison. This guard never tags, pushes, creates a release, or
contacts package registries.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


_ADMISSION_CHECKS_MODULE = None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_admission_checks():
    global _ADMISSION_CHECKS_MODULE
    if _ADMISSION_CHECKS_MODULE is None:
        module_name = "release_admission_checks"
        path = Path(__file__).resolve().parent / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _ADMISSION_CHECKS_MODULE = module
    return _ADMISSION_CHECKS_MODULE


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


GH_TIMEOUT_SECONDS = 60
GH_MAX_OUTPUT_CHARS = 200_000


def _run_gh(command: list[str]) -> tuple[int, str, str]:
    """Run one read-only ``gh`` command with a bounded runtime and bounded output.

    A hung or chatty GitHub call must never stall a release or flood a log, and a
    timeout is an admission failure rather than a pass.
    """
    try:
        completed = subprocess.run(
            ["gh", *command],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"gh timed out after {GH_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return 127, "", f"could not run gh: {exc}"
    return (
        completed.returncode,
        completed.stdout[:GH_MAX_OUTPUT_CHARS],
        completed.stderr[:GH_MAX_OUTPUT_CHARS],
    )


def _with_remediation(
    row: dict[str, object],
    remediation: str,
) -> dict[str, object]:
    if row["status"] == "fail":
        row = dict(row)
        row["remediation"] = remediation
    return row


def check_tag_identity(
    root: Path,
    version: str,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
) -> dict[str, object]:
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
            "remediation": "Inspect the local tag ref, then rerun preflight from a valid git checkout.",
        }
    tag_commit = tag_commit.strip()
    if not tag_commit:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": f"git rev-parse for tag {expected_tag} succeeded but returned no commit",
            "remediation": "Inspect the local tag ref, then rerun preflight from a valid git checkout.",
        }

    rc, head_commit = run(["git", "rev-parse", "HEAD"], root)
    if rc != 0:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": head_commit or "git rev-parse HEAD failed",
            "remediation": "Rerun preflight from the reviewed release commit checkout.",
        }
    head_commit = head_commit.strip()
    if not head_commit:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": "git rev-parse HEAD succeeded but returned no commit",
            "remediation": "Rerun preflight from the reviewed release commit checkout.",
        }

    if tag_commit != head_commit:
        return {
            "name": "tag_identity",
            "status": "fail",
            "detail": (
                f"tag {expected_tag} already points to {tag_commit}, not HEAD "
                f"({head_commit}); bump project.version before reusing a published tag"
            ),
            "remediation": "Bump project.version or move the release candidate back to the tagged SHA.",
        }
    return {
        "name": "tag_identity",
        "status": "ok",
        "detail": f"tag {expected_tag} matches HEAD ({head_commit})",
    }


def check_expected_sha_identity(
    root: Path,
    *,
    tag: str | None,
    expected_sha: str | None,
    candidate_ref: str | None,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
) -> list[dict[str, object]]:
    admission = _load_admission_checks()
    normalized, format_row = admission.normalize_expected_sha(expected_sha)
    if format_row is None:
        return []
    rows = [format_row.to_dict()]
    if normalized is None:
        return rows

    rc, head_sha = run(["git", "rev-parse", "HEAD"], root)
    if rc != 0 or not head_sha.strip():
        rows.append(
            admission.fail_row(
                "head_expected_sha",
                head_sha.strip() or f"git rev-parse HEAD failed with exit code {rc}",
                admission.REMEDIATE_HEAD_SHA,
            ).to_dict()
        )
    else:
        rows.append(
            admission.compare_sha_row(
                "head_expected_sha",
                head_sha,
                normalized,
                "HEAD",
                admission.REMEDIATE_HEAD_SHA,
            ).to_dict()
        )

    if tag is not None:
        # Resolve the fully qualified tag ref so a same-named branch can never be
        # mistaken for the tag, and rely on the documented exit code 1 for
        # "does not resolve" instead of matching localized git error text.
        rc, tag_sha = run(
            ["git", "rev-parse", "--verify", "-q", f"refs/tags/{tag}^{{commit}}"], root
        )
        if rc == 0 and tag_sha.strip():
            rows.append(
                admission.compare_sha_row(
                    "tag_expected_sha",
                    tag_sha,
                    normalized,
                    f"tag {tag}",
                    admission.REMEDIATE_TAG_SHA,
                ).to_dict()
            )
        elif rc == 1:
            rows.append(
                admission.ok_row(
                    "tag_expected_sha",
                    f"tag {tag} is not created yet; intended tag target is the reviewed SHA",
                ).to_dict()
            )
        else:
            rows.append(
                admission.fail_row(
                    "tag_expected_sha",
                    tag_sha.strip() or f"git rev-parse for tag {tag} failed with exit code {rc}",
                    admission.REMEDIATE_TAG_SHA,
                ).to_dict()
            )

    if candidate_ref is not None:
        rc, candidate_sha = run(["git", "rev-parse", f"{candidate_ref}^{{commit}}"], root)
        if rc != 0 or not candidate_sha.strip():
            rows.append(
                admission.fail_row(
                    "candidate_ref_expected_sha",
                    candidate_sha.strip()
                    or f"could not resolve candidate ref {candidate_ref!r} (exit code {rc})",
                    admission.REMEDIATE_CANDIDATE_SHA,
                ).to_dict()
            )
        else:
            rows.append(
                admission.compare_sha_row(
                    "candidate_ref_expected_sha",
                    candidate_sha,
                    normalized,
                    f"candidate ref {candidate_ref}",
                    admission.REMEDIATE_CANDIDATE_SHA,
                ).to_dict()
            )
    return rows


def evaluate(
    root: Path,
    *,
    tag: str | None,
    require_clean: bool,
    check_live_upstream: bool = False,
    with_gitleaks_history: bool = False,
    expect_sha: str | None = None,
    candidate_ref: str | None = None,
    check_required_check: bool = False,
    check_dependency_audit: bool = False,
    check_branch_rules: bool = False,
    check_tag_ruleset: bool = False,
    repo: str | None = None,
    branch: str | None = None,
    required_check_name: str | None = None,
    audit_max_age_hours: int | None = None,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
    run_gh: Callable[[list[str]], tuple[int, str, str]] = _run_gh,
) -> tuple[str, list[dict[str, object]]]:
    """Return package version and one result object per local release invariant.

    The default stays deterministic and network-free.  ``check_live_upstream`` is
    the explicit pre-tag opt-in that delegates the one bounded read-only lookup
    to the shared upstream comparison guard.

    ``with_gitleaks_history`` is the explicit opt-in for the full-history secret
    scan. It is off by default because the scan needs both a non-shallow checkout
    and the Gitleaks CLI, and neither is guaranteed wherever preflight runs — the
    ci.yml ``package`` job uses a shallow checkout with no scanner, and publish.yml
    has already made its checkout shallow by the time preflight runs. Release
    admission for history scanning is therefore an explicit workflow step in
    publish.yml, and this flag is for local release preparation on a full clone.
    """
    version = package_version(root)
    admission = _load_admission_checks()
    checks: list[dict[str, object]] = []

    tag_error = validate_tag(version, tag)
    checks.append(
        _with_remediation(
            {
                "name": "tag_version",
                "status": "fail" if tag_error else "ok",
                "detail": tag_error or f"package version is v{version}",
            },
            "Use the exact v<project.version> tag from pyproject.toml.",
        )
    )

    checks.append(check_tag_identity(root, version, run))
    sha_rows = check_expected_sha_identity(
        root,
        tag=tag,
        expected_sha=expect_sha,
        candidate_ref=candidate_ref,
        run=run,
    )
    checks.extend(sha_rows)
    expected_sha_valid = not any(
        row["name"] == "expected_sha_format" and row["status"] != "ok" for row in sha_rows
    )

    commands = [
        ("docs_drift", [sys.executable, "scripts/docs_drift_guard.py"]),
        ("public_safety", [sys.executable, "scripts/public_safety_scan.py", "--committed"]),
        ("upstream_comparison", [sys.executable, "scripts/upstream_comparison_guard.py"]),
    ]
    if with_gitleaks_history:
        commands.append(
            ("gitleaks_history", [sys.executable, "scripts/gitleaks_scan.py", "full-history"])
        )
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
            _with_remediation(
                {
                    "name": name,
                    "status": "ok" if rc == 0 else "fail",
                    "detail": output or "passed",
                },
                f"Run {' '.join(command)} locally and fix the reported release blocker.",
            )
        )

    repo_name = repo or admission.DEFAULT_REPO
    branch_name = branch or admission.DEFAULT_BRANCH
    check_name = required_check_name or admission.AGGREGATE_REQUIRED_CHECK
    if expected_sha_valid and check_required_check:
        checks.append(
            admission.check_aggregate_required_check(
                expect_sha,
                repo_name,
                run_gh,
                check_name=check_name,
            ).to_dict()
        )
    elif check_required_check:
        checks.append(
            admission.fail_row(
                "aggregate_required_check",
                "aggregate check lookup skipped because --expect-sha is malformed",
                admission.REMEDIATE_EXPECT_SHA,
            ).to_dict()
        )
    if check_dependency_audit:
        checks.append(
            admission.check_dependency_audit_freshness(
                repo_name,
                run_gh,
                max_age_hours=audit_max_age_hours or admission.DEFAULT_AUDIT_MAX_AGE_HOURS,
            ).to_dict()
        )
    if check_branch_rules:
        checks.append(
            admission.check_main_branch_rules(
                repo_name,
                branch_name,
                run_gh,
                check_name=check_name,
            ).to_dict()
        )
    if check_tag_ruleset:
        # Kept separate from --check-branch-rules on purpose: reading a repository
        # ruleset needs administration:read, which a workflow GITHUB_TOKEN cannot
        # be granted, so publish.yml asks only for the branch-rule predicate.
        checks.append(admission.check_tag_ruleset(repo_name, run_gh).to_dict())

    if require_clean:
        rc, output = run(["git", "status", "--porcelain"], root)
        clean = rc == 0 and not output
        checks.append(
            _with_remediation(
                {
                    "name": "clean_tree",
                    "status": "ok" if clean else "fail",
                    "detail": "worktree is clean" if clean else output or "git status failed",
                },
                "Commit or discard unrelated local changes before creating a release tag.",
            )
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
    parser.add_argument(
        "--with-gitleaks-history",
        action="store_true",
        help=(
            "Opt in to the Gitleaks full-history scan; requires a non-shallow "
            "checkout and the Gitleaks CLI on PATH."
        ),
    )
    parser.add_argument(
        "--expect-sha",
        help="Operator-reviewed 40-hex release candidate SHA that every candidate ref must match.",
    )
    parser.add_argument(
        "--candidate-ref",
        help="Read-only git ref for the public release candidate, for example publish/main.",
    )
    parser.add_argument(
        "--check-required-check",
        action="store_true",
        help="Require the aggregate GitHub check-run for --expect-sha to be successful.",
    )
    parser.add_argument(
        "--check-dependency-audit",
        action="store_true",
        help="Require a fresh successful scheduled dependency-audit workflow run.",
    )
    parser.add_argument(
        "--check-branch-rules",
        action="store_true",
        help=(
            "Require the public branch rules protecting --branch through the read-only "
            "effective-rules API (metadata read is enough)."
        ),
    )
    parser.add_argument(
        "--check-tag-ruleset",
        action="store_true",
        help=(
            "Require the public v* tag ruleset through the read-only rulesets API "
            "(needs repository administration read; operator-run only)."
        ),
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repository owner/name for live read-only admission checks.",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Public branch name for ref protection checks.",
    )
    parser.add_argument(
        "--required-check-name",
        default=None,
        help=(
            "Aggregate required check name "
            f"(default: {_load_admission_checks().AGGREGATE_REQUIRED_CHECK})."
        ),
    )
    parser.add_argument(
        "--audit-max-age-hours",
        type=int,
        default=None,
        help="Maximum age for the latest successful dependency-audit run.",
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON.")
    args = parser.parse_args(argv)

    try:
        version, checks = evaluate(
            args.root.resolve(),
            tag=args.tag,
            require_clean=args.require_clean,
            check_live_upstream=args.check_live_upstream,
            with_gitleaks_history=args.with_gitleaks_history,
            expect_sha=args.expect_sha,
            candidate_ref=args.candidate_ref,
            check_required_check=args.check_required_check,
            check_dependency_audit=args.check_dependency_audit,
            check_branch_rules=args.check_branch_rules,
            check_tag_ruleset=args.check_tag_ruleset,
            repo=args.repo,
            branch=args.branch,
            required_check_name=args.required_check_name,
            audit_max_age_hours=args.audit_max_age_hours,
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
            remediation = check.get("remediation")
            if check["status"] != "ok" and remediation:
                print(f"    remediation: {remediation}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
