#!/usr/bin/env python3
"""Run release checks before creating or publishing a tag.

Default checks validate only the checked-out tree and stay deterministic and
network-free. With ``--tag`` they also require the committed installed-candidate
acceptance report for the exact package tree at ``HEAD``. Explicit
public-admission flags add bounded credential-free reads of their named public
surfaces. This guard never tags, pushes, creates a release, or mutates a package
registry.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


_ADMISSION_CHECKS_MODULE = None
_PUBLIC_READ_MODULE = None
_PUBLIC_SAFETY_MODULE = None

ACCEPTANCE_REPORT_DIR = "docs/quality/acceptance"
ACCEPTANCE_FORMAT_DOC = f"{ACCEPTANCE_REPORT_DIR}/README.md"
# Header field -> the HEAD path whose git object id the report must record. These
# are the package inputs: any change to them after testing needs a new round, while
# documentation-only commits leave every id unchanged.
ACCEPTANCE_BOUND_OBJECTS: tuple[tuple[str, str], ...] = (
    ("mempalace_code_tree", "mempalace_code"),
    ("pyproject_toml_blob", "pyproject.toml"),
    ("uv_lock_blob", "uv.lock"),
)
ACCEPTANCE_REQUIRED_FIELDS: tuple[str, ...] = (
    "version",
    "date",
    "result",
    *(field for field, _path in ACCEPTANCE_BOUND_OBJECTS),
    "wheel_sha256",
)
ACCEPTANCE_REQUIRED_SECTIONS: tuple[str, ...] = ("Coverage", "Issues", "Re-test")
_GIT_OBJECT_ID_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_FENCED_BLOCK_RE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.MULTILINE | re.DOTALL)
_MAX_REPORTED_PROBLEMS = 5


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


def _load_public_read():
    global _PUBLIC_READ_MODULE
    if _PUBLIC_READ_MODULE is None:
        module_name = "release_public_read"
        path = Path(__file__).resolve().parent / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _PUBLIC_READ_MODULE = module
    return _PUBLIC_READ_MODULE


def _load_public_safety():
    global _PUBLIC_SAFETY_MODULE
    if _PUBLIC_SAFETY_MODULE is None:
        module_name = "public_safety_scan"
        path = Path(__file__).resolve().parent / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _PUBLIC_SAFETY_MODULE = module
    return _PUBLIC_SAFETY_MODULE


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


def _with_remediation(
    row: dict[str, object],
    remediation: str,
) -> dict[str, object]:
    if row["status"] == "fail":
        row = dict(row)
        row["remediation"] = remediation
    return row


def check_clean_tree(
    root: Path,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
) -> dict[str, object]:
    """Return the canonical fail-closed clean-worktree release row."""
    rc, output = run(["git", "status", "--porcelain"], root)
    clean = rc == 0 and not output
    if clean:
        detail = "worktree is clean"
    elif rc != 0:
        detail = "git status failed"
    else:
        detail = output
    return _with_remediation(
        {
            "name": "clean_tree",
            "status": "ok" if clean else "fail",
            "detail": detail,
        },
        "Commit or discard unrelated local changes before creating a release tag.",
    )


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


def acceptance_report_path(version: str) -> str:
    """Return the repository-relative acceptance report path for ``version``."""
    return f"{ACCEPTANCE_REPORT_DIR}/v{version}.md"


def _bounded(value: str, limit: int = 60) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _is_iso_date(value: str) -> bool:
    if not _ISO_DATE_RE.fullmatch(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def parse_acceptance_header(text: str) -> tuple[dict[str, str], list[str]]:
    """Return the ``key: value`` front-matter fields of an acceptance report.

    The header is the block between the first line ``---`` and the next ``---``
    line. Values may be wrapped in one pair of matching quotes. The second item
    lists format problems; an empty list means the header parsed cleanly.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, ["the report does not start with a '---' front-matter header"]
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return {}, ["the front-matter header is not closed by a '---' line"]

    fields: dict[str, str] = {}
    problems: list[str] = []
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or not key:
            problems.append(f"malformed header line {_bounded(line.strip())!r}")
            continue
        if key in fields:
            problems.append(f"duplicate header field {key!r}")
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        fields[key] = value
    return fields, problems


def check_acceptance_report(
    root: Path,
    version: str,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
) -> dict[str, object]:
    """Require the committed acceptance report that binds this exact package tree.

    The report must be committed at ``HEAD``, name ``version``, record result
    PASS, and record the git object ids of ``mempalace_code/``,
    ``pyproject.toml``, and ``uv.lock`` exactly as ``HEAD`` has them. Every read
    is a local git plumbing call, so the check stays offline and credential-free.
    """
    report = acceptance_report_path(version)
    remediation = (
        "Run the installed-candidate acceptance test (docs/RELEASING.md section 1a) against "
        f"a wheel built from this exact tree, then commit {report} with result PASS and "
        f"the HEAD ids in the {ACCEPTANCE_FORMAT_DOC} format."
    )

    def row(status: str, detail: str) -> dict[str, object]:
        result: dict[str, object] = {
            "name": "acceptance_report",
            "status": status,
            "detail": detail,
        }
        if status != "ok":
            result["remediation"] = remediation
        return result

    try:
        rc, text = run(["git", "cat-file", "blob", f"HEAD:{report}"], root)
    except UnicodeDecodeError:
        return row("fail", f"{report} is not UTF-8 text")
    if rc != 0:
        return row("fail", f"{report} is not committed at HEAD")

    fields, problems = parse_acceptance_header(text)
    if not problems:
        missing = [field for field in ACCEPTANCE_REQUIRED_FIELDS if not fields.get(field)]
        if missing:
            problems.append(f"missing header fields: {', '.join(missing)}")
        recorded_version = fields.get("version")
        if recorded_version and recorded_version != version:
            problems.append(f"records version {_bounded(recorded_version)!r}, not {version!r}")
        date = fields.get("date")
        if date and not _is_iso_date(date):
            problems.append(f"date {_bounded(date)!r} is not a valid YYYY-MM-DD date")
        result = fields.get("result")
        if result and result != "PASS":
            problems.append(f"result is {_bounded(result)!r}, not 'PASS'")
        wheel_sha256 = fields.get("wheel_sha256")
        if wheel_sha256 and not _SHA256_RE.fullmatch(wheel_sha256):
            problems.append("wheel_sha256 is not a lowercase 64-hex digest")
        for field, path in ACCEPTANCE_BOUND_OBJECTS:
            recorded = fields.get(field)
            if not recorded:
                continue
            if not _GIT_OBJECT_ID_RE.fullmatch(recorded):
                problems.append(f"{field} is not a lowercase git object id")
                continue
            rc, head_id = run(["git", "rev-parse", "--verify", "-q", f"HEAD:{path}"], root)
            head_id = head_id.strip()
            if rc != 0 or not _GIT_OBJECT_ID_RE.fullmatch(head_id):
                problems.append(f"could not resolve HEAD:{path}")
            elif head_id != recorded:
                problems.append(
                    f"{path} changed after acceptance testing (report {recorded[:12]}, "
                    f"HEAD {head_id[:12]})"
                )
    unfenced = _FENCED_BLOCK_RE.sub("", text)
    for section in ACCEPTANCE_REQUIRED_SECTIONS:
        if not re.search(rf"^## {re.escape(section)}\b", unfenced, re.MULTILINE):
            problems.append(f"missing '## {section}' section")
    safety = _load_public_safety()
    hits = safety.scan_text(report, text, safety.rendered_rules())
    if hits:
        first = min(hits, key=lambda hit: (hit.line, hit.column))
        problems.append(
            f"not public-safe: {len(hits)} absolute local path or token match(es), "
            f"first at line {first.line} ({first.rule_id})"
        )

    if problems:
        shown = problems[:_MAX_REPORTED_PROBLEMS]
        if len(problems) > len(shown):
            shown.append(f"(+{len(problems) - len(shown)} more)")
        return row("fail", f"{report}: {'; '.join(shown)}")
    return row(
        "ok",
        f"{report} records PASS on {fields['date']} for the HEAD mempalace_code tree, "
        "pyproject.toml, and uv.lock",
    )


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
    check_public_orphan_tags: bool = False,
    check_public_main: bool = False,
    repo: str | None = None,
    branch: str | None = None,
    required_check_name: str | None = None,
    audit_max_age_hours: int | None = None,
    run: Callable[[list[str], Path], tuple[int, str]] = _run,
    public_read: Callable[[object], object] | None = None,
) -> tuple[str, list[dict[str, object]]]:
    """Return package version and one result object per local release invariant.

    The default stays deterministic and network-free.  ``check_live_upstream`` is
    the explicit pre-tag opt-in that delegates the one bounded read-only lookup
    to the shared upstream comparison guard.

    A ``tag`` adds the ``acceptance_report`` row: the release is admissible only
    with a committed PASS installed-candidate acceptance report whose recorded
    package ids equal ``HEAD`` (``check_acceptance_report``).

    ``check_public_orphan_tags`` opts into the existing bounded GitHub/PyPI
    identity predicate. A matching validated tag may be incomplete only during
    this prepublication transaction; every other orphan still fails closed.

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
    public = _load_public_read()
    query_public = public_read or public.DEFAULT_READER
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
    if tag is not None:
        checks.append(check_acceptance_report(root, version, run))

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
                query_public,
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
                query_public,
                max_age_hours=audit_max_age_hours or admission.DEFAULT_AUDIT_MAX_AGE_HOURS,
            ).to_dict()
        )
    if check_branch_rules:
        checks.append(
            admission.check_main_branch_rules(
                repo_name,
                branch_name,
                query_public,
                check_name=check_name,
            ).to_dict()
        )
    if check_tag_ruleset:
        checks.append(admission.check_tag_ruleset(repo_name, query_public).to_dict())
    if check_public_orphan_tags:
        checks.append(
            admission.check_public_orphan_tags(
                version,
                repo_name,
                admission.DEFAULT_PACKAGE,
                query_public,
                allow_expected_tag_pending=tag is not None and tag_error is None,
            ).to_dict()
        )
    if check_public_main and not admission.SHA_RE.fullmatch(expect_sha or ""):
        checks.append(
            admission.fail_row(
                "public_main_expected_sha",
                "public main lookup requires a valid --expect-sha",
                admission.REMEDIATE_EXPECT_SHA,
            ).to_dict()
        )
    elif check_public_main and expected_sha_valid:
        try:
            result = query_public(public.public_main(repo_name, branch_name))
            public_sha = getattr(result, "data", "")
            public_error = getattr(result, "error", "")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            public_sha, public_error = "", str(exc)
        if public_error or not isinstance(public_sha, str):
            checks.append(
                admission.error_row(
                    "public_main_expected_sha",
                    f"public main lookup failed: {public_error or 'unexpected response'}",
                    admission.REMEDIATE_CANDIDATE_SHA,
                ).to_dict()
            )
        else:
            checks.append(
                admission.compare_sha_row(
                    "public_main_expected_sha",
                    public_sha,
                    str(expect_sha).lower(),
                    f"public {branch_name}",
                    admission.REMEDIATE_CANDIDATE_SHA,
                ).to_dict()
            )

    if require_clean:
        checks.append(check_clean_tree(root, run))

    return version, checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local release invariants without tag, push, publish, or network mutation."
    )
    parser.add_argument(
        "--root", type=Path, default=repo_root(), help="Repository root to inspect."
    )
    parser.add_argument(
        "--tag",
        help=(
            "Expected release tag, for example v1.2.3. Also requires the committed "
            f"acceptance report {ACCEPTANCE_REPORT_DIR}/v<version>.md for the HEAD package tree."
        ),
    )
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
        help="Require the public v* tag ruleset through the credential-free rulesets API.",
    )
    parser.add_argument(
        "--check-public-orphan-tags",
        action="store_true",
        help=(
            "Require every public version tag except the exact validated tag currently being "
            "published to have a non-draft GitHub Release and PyPI distribution."
        ),
    )
    parser.add_argument(
        "--check-public-main",
        action="store_true",
        help="Require the fixed public main branch to match --expect-sha.",
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
            check_public_orphan_tags=args.check_public_orphan_tags,
            check_public_main=args.check_public_main,
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
