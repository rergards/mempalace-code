#!/usr/bin/env python3
"""release_status_gate.py — Verify all public publication surfaces before calling a release shipped.

Stdlib-only — no project imports, no third-party dependencies. Loads the sibling
scripts/release_install_metadata_smoke.py script by path for the install smoke
surface (not a project import — a sibling stdlib-only script).

Usage:
    python scripts/release_status_gate.py --version X.Y.Z [options]
    python scripts/release_status_gate.py --help

Checks (in order):
  1. publish remote git tag
  2. branch Tests workflow (GitHub Actions)
  3. Publish to PyPI workflow (GitHub Actions)
  4. GitHub Release metadata (non-draft, non-prerelease, matching tag, latest)
  5. PyPI JSON (version, wheel and sdist files)
  6. PyPI provenance (every exact-version file, expected publisher identity)
  7. Install smoke (installed package metadata, module __version__, and CLI
     version-check --status must all agree with the requested version)

Exits 0 only when all required public surfaces agree.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Constants ──────────────────────────────────────────────────────────────────

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
PYPI_PROVENANCE_URL = "https://pypi.org/integrity/{package}/{version}/{filename}/provenance"
DEFAULT_PACKAGE = "mempalace-code"
DEFAULT_REPO = "rergards/mempalace-code"
DEFAULT_REMOTE = "publish"
DEFAULT_BRANCH = "main"
TESTS_WORKFLOW = "Tests"
PUBLISH_WORKFLOW = "Publish to PyPI"
DEFAULT_INSTALL_SMOKE_TIMEOUT_SECONDS = 300
EXPECTED_PROVENANCE_WORKFLOW = ".github/workflows/publish.yml"
EXPECTED_PROVENANCE_ENVIRONMENT = "release"
VERIFIER_PACKAGE = "pypi-attestations"
MAX_PUBLIC_DISTRIBUTIONS = 20
MAX_PUBLIC_FILENAME_LENGTH = 200
MAX_PUBLIC_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_VERIFIER_OUTPUT_BYTES = 4096
WORKFLOW_RUN_LIMIT = 10
WORKFLOW_RUN_LIMIT_BY_SHA = 50
PUBLISH_JOB_NAMES = ("build", "publish", "github-release")
PARTIAL_RECOVERY_COMMAND_TEMPLATE = (
    "gh run rerun {run_id} --job {job_id} --repo rergards/mempalace-code"
)

SURFACE_TAG = "publish_remote_tag"
SURFACE_CANDIDATE_SHA = "release_candidate_sha"
SURFACE_TESTS = "branch_tests_workflow"
SURFACE_PUBLISH = "publish_to_pypi_workflow"
SURFACE_RELEASE = "github_release"
SURFACE_PYPI = "pypi_json"
SURFACE_PYPI_PROVENANCE = "pypi_provenance"
SURFACE_SMOKE = "install_smoke"
SURFACE_REQUIRED_CHECK = "release_required_check"
SURFACE_MAIN_PROTECTION = "public_main_protection"
SURFACE_TAG_RULESET = "public_v_tag_ruleset"
SURFACE_ORPHAN_TAGS = "public_orphan_tags"
SURFACE_AUDIT = "dependency_audit_freshness"

REQUIRED_SURFACES = [
    SURFACE_TAG,
    SURFACE_CANDIDATE_SHA,
    SURFACE_TESTS,
    SURFACE_REQUIRED_CHECK,
    SURFACE_PUBLISH,
    SURFACE_RELEASE,
    SURFACE_PYPI,
    SURFACE_PYPI_PROVENANCE,
    SURFACE_SMOKE,
    SURFACE_MAIN_PROTECTION,
    SURFACE_TAG_RULESET,
    SURFACE_ORPHAN_TAGS,
    SURFACE_AUDIT,
]

STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"
STATUS_ERROR = "error"

# ── Sanitization ───────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"\b(?:[g]hp_|[g]ithub_pat_|[p]ypi-)[A-Za-z0-9_\-]{4,}\S*",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"(/(?:Users|home|root|tmp)/[^\s:,\"']*|/var/folders/[^\s:,\"']*)")
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
    remediation: str = ""
    # Internal exact-run evidence. These fields deliberately stay out of JSON;
    # only the fully admitted remediation command is public output.
    workflow_run_id: int | None = None
    workflow_job_id: int | None = None
    recovery_ready: bool = False

    def to_dict(self) -> dict[str, str]:
        result = {"name": self.name, "status": self.status, "detail": self.detail}
        if self.remediation:
            result["remediation"] = self.remediation
        return result


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


@dataclass(frozen=True)
class PublicDistribution:
    filename: str
    package_type: str
    sha256: str
    url: str


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
            SURFACE_TAG,
            STATUS_ERROR,
            f"git ls-remote failed: {sanitize(stderr.strip())}",
            "Verify the public remote name and rerun the status gate.",
        )
    # Exact ref match: a substring test would let refs/tags/v1.13.2 satisfy a
    # query for refs/tags/v1.1 and report an unpublished version as published.
    found = any(
        len(parts) >= 2 and parts[1] in {tag, f"{tag}^{{}}"}
        for parts in (line.split() for line in stdout.splitlines())
    )
    if found:
        return SurfaceResult(SURFACE_TAG, STATUS_OK, f"tag v{version} found on remote {remote!r}")
    return SurfaceResult(
        SURFACE_TAG,
        STATUS_FAIL,
        f"tag v{version} not found on remote {remote!r}",
        "Push the approved immutable tag to the public publish remote.",
    )


def resolve_remote_tag_sha(
    version: str,
    remote: str,
    run_git: Callable[[list[str]], tuple[int, str, str]],
) -> tuple[str | None, SurfaceResult]:
    """Resolve the public tag to the commit it targets, peeling an annotated tag.

    Always returns a surface: the tag target is evidence in its own right, so a
    failed lookup is reported rather than dropped.
    """
    tag = f"refs/tags/v{version}"
    exit_code, stdout, stderr = run_git(["ls-remote", "--tags", remote, tag, f"{tag}^{{}}"])
    if exit_code != 0:
        return None, SurfaceResult(
            SURFACE_CANDIDATE_SHA,
            STATUS_ERROR,
            f"git ls-remote failed while resolving tag commit: {sanitize(stderr.strip())}",
            "Verify the public remote name and rerun the status gate.",
        )
    direct_sha = ""
    peeled_sha = ""
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[1] == tag:
            direct_sha = parts[0]
        elif parts[1] == f"{tag}^{{}}":
            peeled_sha = parts[0]
    # An annotated tag's own object is not the commit it publishes; the peeled
    # ref is, so it wins whenever the remote reports both.
    candidate = peeled_sha or direct_sha
    if not candidate:
        return None, SurfaceResult(
            SURFACE_CANDIDATE_SHA,
            STATUS_FAIL,
            f"could not resolve public tag v{version} to a candidate SHA",
            "Push the approved immutable tag to the public publish remote.",
        )
    return candidate.lower(), SurfaceResult(
        SURFACE_CANDIDATE_SHA,
        STATUS_OK,
        f"public tag v{version} resolves to candidate SHA {candidate.lower()}",
    )


def resolve_candidate_sha(
    version: str,
    remote: str,
    expect_sha: str | None,
    admission,
    run_git: Callable[[list[str]], tuple[int, str, str]],
) -> tuple[str | None, SurfaceResult]:
    """Return the candidate SHA plus exactly one ``release_candidate_sha`` surface.

    The public tag is resolved and peeled even when the operator passes
    ``--expect-sha`` — the documented invocation. The gate's central claim is that
    the published tag targets the reviewed SHA, and taking that SHA on trust would
    leave a tag moved or recreated after review reporting green.
    """
    expected: str | None = None
    if expect_sha is not None:
        expected, sha_row = admission.normalize_expected_sha(expect_sha)
        if expected is None:
            # Malformed input: there is nothing to reconcile the public tag against.
            return None, _surface_from_admission(sha_row, SURFACE_CANDIDATE_SHA)

    resolved, resolve_surface = resolve_remote_tag_sha(version, remote, run_git)
    if resolved is None:
        # An unresolvable public tag is itself a blocker; the reviewed SHA still
        # drives the remaining exact-SHA surfaces so their evidence is not lost.
        return expected, resolve_surface
    if expected is None:
        return resolved, resolve_surface
    if resolved != expected:
        return expected, SurfaceResult(
            SURFACE_CANDIDATE_SHA,
            STATUS_FAIL,
            f"public tag v{version} targets {resolved} but the reviewed SHA is {expected}",
            admission.REMEDIATE_TAG_SHA,
        )
    return expected, SurfaceResult(
        SURFACE_CANDIDATE_SHA,
        STATUS_OK,
        f"public tag v{version} targets the reviewed SHA {expected}",
    )


def check_workflow_run(
    surface_name: str,
    workflow: str,
    repo: str,
    extra_args: list[str],
    run_gh: Callable[[list[str]], tuple[int, str, str]],
    expected_sha: str | None = None,
    version: str | None = None,
) -> SurfaceResult:
    # `gh run list` has no head-SHA filter, so the exact-SHA run has to be found
    # inside a bounded window. The window is widened when filtering by SHA so a
    # burst of later pushes cannot silently push the candidate's run out of view.
    limit = WORKFLOW_RUN_LIMIT_BY_SHA if expected_sha else WORKFLOW_RUN_LIMIT
    gh_args = [
        "run",
        "list",
        "--repo",
        repo,
        "--workflow",
        workflow,
        "--json",
        "status,conclusion,headBranch,headSha,displayTitle,url,createdAt,event,databaseId",
        "--limit",
        str(limit),
        *extra_args,
    ]
    exit_code, stdout, stderr = run_gh(gh_args)
    if exit_code != 0:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"gh run list failed for {workflow!r}: {sanitize(stderr.strip())}",
            f"Rerun the {workflow} workflow and wait for a successful completed run.",
        )
    try:
        runs = json.loads(stdout)
    except json.JSONDecodeError as e:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"could not parse gh run list output: {sanitize(str(e))}",
            f"Rerun the {workflow} workflow and wait for a parseable GitHub response.",
        )
    if not isinstance(runs, list):
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"unexpected gh run list response shape for {workflow!r}",
            f"Rerun the {workflow} workflow and wait for a parseable GitHub response.",
        )
    candidates = [r for r in runs if isinstance(r, dict)]
    if expected_sha is not None:
        expected = expected_sha.lower()
        candidates = [r for r in candidates if str(r.get("headSha", "")).lower() == expected]
    if version is not None:
        candidates = [
            r
            for r in candidates
            if r.get("event") == "push" and r.get("headBranch") == f"v{version}"
        ]
    if not candidates:
        suffix = f" for SHA {expected_sha}" if expected_sha else ""
        return SurfaceResult(
            surface_name,
            STATUS_FAIL,
            f"no completed runs found for workflow {workflow!r}{suffix} "
            f"in the {limit} most recent runs",
            f"Rerun the {workflow} workflow for the exact candidate SHA.",
        )
    # Order by *parsed* creation time. Comparing the raw strings is only correct
    # while every stamp is Z-normalized: one offset-bearing `createdAt` in the
    # window and lexical order silently picks the wrong run, which is how an
    # older green run masks a newer red one.
    parse_timestamp = _load_admission_checks().parse_iso_timestamp
    # A publish rerun keeps the workflow-run identity while its status changes.
    # Include in-progress candidates so a repeated operator attempt cannot select
    # an older completed state and emit a second rerun command.
    ordered_candidates = (
        candidates
        if version is not None
        else [r for r in candidates if r.get("status") == "completed"]
    )
    if not ordered_candidates:
        suffix = f" for SHA {expected_sha}" if expected_sha else ""
        return SurfaceResult(
            surface_name,
            STATUS_FAIL,
            f"no completed runs found for workflow {workflow!r}{suffix} "
            f"in the {limit} most recent runs",
            f"Rerun the {workflow} workflow for the exact candidate SHA.",
        )
    stamped = [(parse_timestamp(r.get("createdAt")), r) for r in ordered_candidates]
    datable = [(stamp, run) for stamp, run in stamped if stamp is not None]
    if len(stamped) > 1 and len(datable) != len(stamped):
        # More than one candidate run and at least one cannot be placed in time:
        # there is no defensible "most recent", so fail closed rather than let
        # list position decide. A single run needs no ordering and still counts.
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"workflow {workflow!r} returned {len(stamped) - len(datable)} of {len(stamped)} "
            "completed runs with an unparseable createdAt; the most recent run cannot be "
            "identified",
            f"Rerun the {workflow} workflow and wait for a parseable GitHub response.",
        )
    most_recent = max(datable, key=lambda item: item[0])[1] if datable else ordered_candidates[0]
    if version is not None:
        return _check_publish_run_jobs(
            surface_name,
            workflow,
            repo,
            expected_sha,
            most_recent,
            run_gh,
        )
    if most_recent.get("conclusion") == "success":
        suffix = f" for SHA {expected_sha}" if expected_sha else ""
        return SurfaceResult(
            surface_name,
            STATUS_OK,
            f"workflow {workflow!r} most recent completed run succeeded{suffix}",
        )
    conclusion = str(most_recent.get("conclusion", "unknown"))
    return SurfaceResult(
        surface_name,
        STATUS_FAIL,
        f"workflow {workflow!r} most recent completed run has conclusion: {conclusion!r}",
        f"Rerun the {workflow} workflow for the exact candidate SHA.",
    )


def _bounded_recovery_instruction(version: str, repo: str, expected_sha: str | None) -> str:
    sha = expected_sha or "<40-hex-candidate-sha>"
    return (
        "BOUNDED INSTRUCTION: no safe publication mutation command is available. "
        "Resolve the named blocker, then rerun "
        f"python scripts/release_status_gate.py --version {version} --repo {repo} "
        f"--remote publish --branch main --expect-sha {sha}"
    )


def _check_publish_run_jobs(
    surface_name: str,
    workflow: str,
    repo: str,
    expected_sha: str | None,
    run: dict,
    run_gh: Callable[[list[str]], tuple[int, str, str]],
) -> SurfaceResult:
    """Validate the selected tag run and its unique build/publish/release jobs."""
    version = str(run.get("headBranch", "")).removeprefix("v")
    bounded = _bounded_recovery_instruction(version, repo, expected_sha)
    if run.get("status") != "completed":
        return SurfaceResult(
            surface_name,
            STATUS_FAIL,
            f"workflow {workflow!r} exact tag run is {run.get('status', 'unknown')!r}",
            bounded,
        )
    run_id = run.get("databaseId")
    if not isinstance(run_id, int) or run_id <= 0:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"workflow {workflow!r} exact tag run has no valid database ID",
            bounded,
        )
    exit_code, stdout, stderr = run_gh(
        ["run", "view", str(run_id), "--repo", repo, "--json", "jobs"]
    )
    if exit_code != 0:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"gh run view failed for exact run {run_id}: {sanitize(stderr.strip())}",
            bounded,
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"could not parse jobs for exact run {run_id}: {sanitize(str(exc))}",
            bounded,
        )
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"exact run {run_id} returned an unexpected jobs response shape",
            bounded,
        )
    by_name: dict[str, list[dict]] = {name: [] for name in PUBLISH_JOB_NAMES}
    for job in jobs:
        if isinstance(job, dict) and job.get("name") in by_name:
            by_name[str(job["name"])].append(job)
    malformed = [name for name, matches in by_name.items() if len(matches) != 1]
    if malformed:
        return SurfaceResult(
            surface_name,
            STATUS_ERROR,
            f"exact run {run_id} does not have one unique job for: {', '.join(malformed)}",
            bounded,
        )
    selected = {name: matches[0] for name, matches in by_name.items()}
    states = {name: (job.get("status"), job.get("conclusion")) for name, job in selected.items()}
    if run.get("conclusion") == "success" and all(
        status == "completed" and conclusion == "success" for status, conclusion in states.values()
    ):
        return SurfaceResult(
            surface_name,
            STATUS_OK,
            f"workflow {workflow!r} exact run {run_id} and all publication jobs succeeded "
            f"for SHA {expected_sha}",
        )
    release_job = selected["github-release"]
    release_job_id = release_job.get("databaseId")
    safe_partial = (
        repo == DEFAULT_REPO
        and run.get("conclusion") == "failure"
        and states["build"] == ("completed", "success")
        and states["publish"] == ("completed", "success")
        and states["github-release"] == ("completed", "failure")
        and isinstance(release_job_id, int)
        and release_job_id > 0
    )
    detail = f"workflow {workflow!r} exact run {run_id} job states: {states}"
    return SurfaceResult(
        surface_name,
        STATUS_FAIL,
        detail,
        bounded,
        workflow_run_id=run_id if safe_partial else None,
        workflow_job_id=release_job_id if safe_partial else None,
        recovery_ready=safe_partial,
    )


def unbound_candidate_workflow_surface(surface_name: str, workflow: str) -> SurfaceResult:
    """Report an exact-SHA workflow surface that has no candidate SHA to bind to.

    Without this the surface would fall back to ``gh run list``'s branch-latest
    window, so a malformed ``--expect-sha`` — or a public tag that never resolved —
    would print ``ok`` rows sourced from a commit nobody reviewed, sitting inside
    an overall-failing report. The row stays present and machine-readable so the
    required-surface set is never short one entry.
    """
    return SurfaceResult(
        surface_name,
        STATUS_FAIL,
        f"workflow {workflow!r} was not evaluated: no candidate SHA is bound, and a "
        "branch-latest run is not evidence for the reviewed commit",
        "Rerun with a reviewed 40-hex --expect-sha, or publish the tag so it resolves.",
    )


def check_github_release(
    version: str,
    repo: str,
    run_gh: Callable[[list[str]], tuple[int, str, str]],
    allow_prerelease: bool = False,
) -> SurfaceResult:
    view_args = [
        "release",
        "view",
        f"v{version}",
        "--repo",
        repo,
        "--json",
        "tagName,isDraft,isPrerelease,publishedAt,url,targetCommitish",
    ]
    exit_code, stdout, stderr = run_gh(view_args)
    if exit_code != 0:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            f"gh release view failed: {sanitize(stderr.strip())}",
            f"Create or repair the non-draft GitHub Release for v{version}.",
        )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            f"could not parse gh release view output: {sanitize(str(e))}",
            f"Create or repair the non-draft GitHub Release for v{version}.",
        )
    if not isinstance(data, dict):
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            "unexpected gh release view response shape",
            f"Create or repair the non-draft GitHub Release for v{version}.",
        )
    tag_name = data.get("tagName", "")
    is_draft = data.get("isDraft", True)
    is_prerelease = data.get("isPrerelease", True)

    if tag_name != f"v{version}":
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_FAIL,
            f"release tag {tag_name!r} does not match expected v{version}",
            f"Create or repair the GitHub Release for tag v{version}.",
        )
    if is_draft:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_FAIL,
            f"GitHub Release v{version} is a draft",
            f"Publish the GitHub Release for v{version}.",
        )
    if is_prerelease and not allow_prerelease:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_FAIL,
            f"GitHub Release v{version} is a prerelease (pass --allow-prerelease to allow)",
            "Pass --allow-prerelease for an approved prerelease, or publish a stable release.",
        )

    list_args = [
        "release",
        "list",
        "--repo",
        repo,
        "--limit",
        "10",
        "--json",
        "tagName,isLatest,publishedAt",
    ]
    exit_code, stdout, stderr = run_gh(list_args)
    if exit_code != 0:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            f"gh release list failed: {sanitize(stderr.strip())}",
            f"Create or repair the non-draft GitHub Release for v{version}.",
        )
    try:
        releases = json.loads(stdout)
    except json.JSONDecodeError as e:
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            f"could not parse gh release list output: {sanitize(str(e))}",
            f"Create or repair the non-draft GitHub Release for v{version}.",
        )
    if not isinstance(releases, list):
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_ERROR,
            "unexpected gh release list response shape",
            f"Create or repair the non-draft GitHub Release for v{version}.",
        )

    latest_tag = ""
    for release in releases:
        if isinstance(release, dict) and release.get("isLatest") is True:
            latest_tag = str(release.get("tagName", ""))
            break

    if latest_tag != f"v{version}":
        suffix = f" (latest is {latest_tag})" if latest_tag else ""
        return SurfaceResult(
            SURFACE_RELEASE,
            STATUS_FAIL,
            f"GitHub Release v{version} is not the latest release{suffix}",
            f"Mark v{version} as the latest GitHub Release or verify the intended version.",
        )
    return SurfaceResult(
        SURFACE_RELEASE,
        STATUS_OK,
        f"GitHub Release v{version} is non-draft, non-prerelease, and latest",
    )


def fetch_pypi_distributions(
    version: str,
    package: str,
    http_get: Callable[[str], tuple[int, bytes, str]],
) -> tuple[list[PublicDistribution] | None, SurfaceResult]:
    url = PYPI_JSON_URL.format(package=package)
    status_code, body, error = http_get(url)
    if status_code != 200:
        msg = sanitize(error) if error else f"HTTP {status_code}"
        return None, SurfaceResult(
            SURFACE_PYPI,
            STATUS_ERROR,
            f"PyPI JSON fetch failed: {msg}",
            "Wait for PyPI propagation, then rerun the status gate.",
        )
    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        return None, SurfaceResult(
            SURFACE_PYPI,
            STATUS_ERROR,
            f"could not parse PyPI JSON response: {e}",
            "Wait for PyPI propagation, then rerun the status gate.",
        )
    if not isinstance(data, dict):
        return None, SurfaceResult(
            SURFACE_PYPI,
            STATUS_ERROR,
            "unexpected PyPI JSON response shape",
            "Wait for PyPI propagation, then rerun the status gate.",
        )

    info_version = data.get("info", {}).get("version", "")
    if info_version != version:
        return None, SurfaceResult(
            SURFACE_PYPI,
            STATUS_FAIL,
            f"PyPI latest version is {info_version!r}, expected {version!r}",
            "Wait for PyPI propagation, then rerun the status gate.",
        )
    releases = data.get("releases", {})
    files = releases.get(version, []) if isinstance(releases, dict) else []
    if not files:
        return None, SurfaceResult(
            SURFACE_PYPI,
            STATUS_FAIL,
            f"no distribution files found for {package}=={version} on PyPI",
            "Wait for PyPI propagation, then rerun the status gate.",
        )
    if not isinstance(files, list) or len(files) > MAX_PUBLIC_DISTRIBUTIONS:
        return None, SurfaceResult(
            SURFACE_PYPI,
            STATUS_FAIL,
            f"invalid distribution inventory for {package}=={version}",
            "Wait for PyPI propagation or fix the published file inventory, then rerun the status gate.",
        )

    distributions: list[PublicDistribution] = []
    seen_filenames: set[str] = set()
    for row in files:
        if not isinstance(row, dict):
            return None, SurfaceResult(
                SURFACE_PYPI,
                STATUS_FAIL,
                f"malformed distribution entry for {package}=={version}",
                "Wait for PyPI propagation or fix the published file inventory, then rerun the status gate.",
            )
        filename = row.get("filename")
        package_type = row.get("packagetype")
        digest = (
            row.get("digests", {}).get("sha256") if isinstance(row.get("digests"), dict) else None
        )
        file_url = row.get("url")
        valid_filename = (
            isinstance(filename, str)
            and 0 < len(filename) <= MAX_PUBLIC_FILENAME_LENGTH
            and Path(filename).name == filename
        )
        parsed_url = urlsplit(file_url) if isinstance(file_url, str) else None
        valid_url = (
            parsed_url is not None
            and parsed_url.scheme == "https"
            and parsed_url.hostname == "files.pythonhosted.org"
        )
        if (
            not valid_filename
            or package_type not in {"bdist_wheel", "sdist"}
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None
            or not valid_url
        ):
            return None, SurfaceResult(
                SURFACE_PYPI,
                STATUS_FAIL,
                f"malformed distribution metadata for {package}=={version}",
                "Wait for PyPI propagation or fix the published file inventory, then rerun the status gate.",
            )
        if filename in seen_filenames:
            return None, SurfaceResult(
                SURFACE_PYPI,
                STATUS_FAIL,
                f"duplicate distribution filename for {package}=={version}",
                "Wait for PyPI propagation or fix the published file inventory, then rerun the status gate.",
            )
        seen_filenames.add(filename)
        distributions.append(
            PublicDistribution(filename, package_type, digest.lower(), str(file_url))
        )

    types = {distribution.package_type for distribution in distributions}
    missing = []
    if "bdist_wheel" not in types:
        missing.append("wheel")
    if "sdist" not in types:
        missing.append("sdist")
    if missing:
        return None, SurfaceResult(
            SURFACE_PYPI,
            STATUS_FAIL,
            f"missing distribution types for {package}=={version}: {missing}",
            "Publish both wheel and sdist, then rerun the status gate.",
        )
    return distributions, SurfaceResult(
        SURFACE_PYPI,
        STATUS_OK,
        f"PyPI {package}=={version} has {len(distributions)} wheel/sdist files",
    )


def check_pypi(
    version: str,
    package: str,
    http_get: Callable[[str], tuple[int, bytes, str]],
) -> SurfaceResult:
    """Compatibility wrapper for the public PyPI inventory surface."""
    _, surface = fetch_pypi_distributions(version, package, http_get)
    return surface


def _locked_verifier_version(project_root: Path) -> tuple[str | None, str]:
    """Return the one exact verifier version shared by both dev declarations and uv.lock."""
    try:
        with open(project_root / "pyproject.toml", "rb") as handle:
            project = tomllib.load(handle)
        with open(project_root / "uv.lock", "rb") as handle:
            lock = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None, "the project metadata or uv.lock is missing or unusable"

    optional_dev = project.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    group_dev = project.get("dependency-groups", {}).get("dev", [])

    def exact_versions(requirements: object) -> list[str]:
        if not isinstance(requirements, list):
            return []
        prefix = f"{VERIFIER_PACKAGE}=="
        return [
            item.removeprefix(prefix)
            for item in requirements
            if isinstance(item, str) and item.startswith(prefix)
        ]

    optional_versions = exact_versions(optional_dev)
    group_versions = exact_versions(group_dev)
    if len(optional_versions) != 1 or len(group_versions) != 1:
        return None, "the verifier must have one exact pin in both dev dependency declarations"
    if optional_versions[0] != group_versions[0]:
        return None, "the verifier pins disagree between dev dependency declarations"

    locked_versions = [
        row.get("version")
        for row in lock.get("package", [])
        if isinstance(row, dict) and row.get("name") == VERIFIER_PACKAGE
    ]
    if locked_versions != [optional_versions[0]]:
        return None, "uv.lock does not contain the exact configured verifier version"
    return optional_versions[0], ""


def _provenance_failure(status: str, detail: str) -> SurfaceResult:
    return SurfaceResult(
        SURFACE_PYPI_PROVENANCE,
        status,
        detail,
        "Wait for PyPI propagation or fix the published provenance, then rerun the same read-only status gate.",
    )


def _publisher_identity_matches(body: bytes, repo: str) -> bool:
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(document, dict) or document.get("version") != 1:
        return False
    bundles = document.get("attestation_bundles")
    if not isinstance(bundles, list) or len(bundles) != 1:
        return False
    bundle = bundles[0]
    if not isinstance(bundle, dict):
        return False
    publisher = bundle.get("publisher")
    attestations = bundle.get("attestations")
    return (
        isinstance(publisher, dict)
        and publisher.get("kind") == "GitHub"
        and publisher.get("repository") == repo
        and publisher.get("workflow") == Path(EXPECTED_PROVENANCE_WORKFLOW).name
        and publisher.get("environment") == EXPECTED_PROVENANCE_ENVIRONMENT
        and isinstance(attestations, list)
        and len(attestations) == 1
    )


def check_pypi_provenance(
    version: str,
    package: str,
    repo: str,
    distributions: list[PublicDistribution],
    http_get: Callable[[str], tuple[int, bytes, str]],
    run_subprocess: Callable[..., tuple[int, str, str]],
    project_root: Path | None = None,
) -> SurfaceResult:
    """Verify each exact-version file with the locked official verifier and publisher identity."""
    root = project_root or Path(__file__).resolve().parent.parent
    verifier_version, lock_error = _locked_verifier_version(root)
    if verifier_version is None:
        return _provenance_failure(STATUS_ERROR, f"locked verifier setup failed: {lock_error}")
    if not distributions:
        return _provenance_failure(
            STATUS_FAIL, f"no public distributions are available for {package}=={version}"
        )

    with tempfile.TemporaryDirectory(prefix="mempalace-provenance-") as temporary:
        temp_root = Path(temporary)
        venv = temp_root / "venv"
        exit_code, _, _ = run_subprocess(
            ["uv", "lock", "--check"],
            cwd=str(root),
        )
        if exit_code != 0:
            return _provenance_failure(
                STATUS_ERROR,
                "uv.lock is stale for the configured verifier environment",
            )
        exit_code, _, _ = run_subprocess(
            ["uv", "venv", str(venv), "--python", sys.executable, "--no-project"],
            cwd=str(root),
        )
        if exit_code != 0:
            return _provenance_failure(
                STATUS_ERROR,
                f"locked verifier environment creation failed for {VERIFIER_PACKAGE}=={verifier_version}",
            )

        sync_env = os.environ.copy()
        sync_env["VIRTUAL_ENV"] = str(venv)
        exit_code, _, _ = run_subprocess(
            [
                "uv",
                "sync",
                "--frozen",
                "--only-group",
                "dev",
                "--no-install-project",
                "--active",
            ],
            env=sync_env,
            cwd=str(root),
        )
        if exit_code != 0:
            return _provenance_failure(
                STATUS_ERROR,
                f"frozen uv.lock verifier sync failed for {VERIFIER_PACKAGE}=={verifier_version}",
            )

        executable_dir = "Scripts" if os.name == "nt" else "bin"
        verifier = venv / executable_dir / "pypi-attestations"
        for distribution in distributions:
            status_code, artifact, _ = http_get(distribution.url)
            if status_code != 200 or len(artifact) > MAX_PUBLIC_RESPONSE_BYTES:
                return _provenance_failure(
                    STATUS_ERROR,
                    f"could not fetch a bounded public artifact for {distribution.filename}",
                )
            if hashlib.sha256(artifact).hexdigest() != distribution.sha256:
                return _provenance_failure(
                    STATUS_FAIL,
                    f"PyPI digest mismatch for {distribution.filename}",
                )
            artifact_path = temp_root / distribution.filename
            artifact_path.write_bytes(artifact)

            provenance_url = PYPI_PROVENANCE_URL.format(
                package=quote(package, safe=""),
                version=quote(version, safe=""),
                filename=quote(distribution.filename, safe=""),
            )
            status_code, provenance, _ = http_get(provenance_url)
            if (
                status_code != 200
                or len(provenance) > MAX_PUBLIC_RESPONSE_BYTES
                or not _publisher_identity_matches(provenance, repo)
            ):
                return _provenance_failure(
                    STATUS_FAIL,
                    f"missing or unexpected provenance identity for {distribution.filename}",
                )

            exit_code, stdout, stderr = run_subprocess(
                [
                    str(verifier),
                    "verify",
                    "pypi",
                    str(artifact_path),
                    "--repository",
                    f"https://github.com/{repo}",
                ],
                cwd=str(root),
            )
            output_size = len(stdout.encode()) + len(stderr.encode())
            if output_size > MAX_VERIFIER_OUTPUT_BYTES:
                return _provenance_failure(
                    STATUS_ERROR,
                    f"official verifier returned oversized output for {distribution.filename}",
                )
            if exit_code != 0:
                return _provenance_failure(
                    STATUS_FAIL,
                    f"official verifier rejected provenance for {distribution.filename}",
                )
            verifier_streams = [stream.strip() for stream in (stdout, stderr) if stream.strip()]
            verifier_output = verifier_streams[0] if len(verifier_streams) == 1 else ""
            verified_target = verifier_output.removeprefix("OK: ")
            if (
                not verifier_output.startswith("OK: ")
                or Path(verified_target).name != distribution.filename
            ):
                return _provenance_failure(
                    STATUS_ERROR,
                    f"official verifier returned an unexpected result for {distribution.filename}",
                )

    filenames = ", ".join(distribution.filename for distribution in distributions)
    return SurfaceResult(
        SURFACE_PYPI_PROVENANCE,
        STATUS_OK,
        f"verified {len(distributions)} files for {package}=={version}: {filenames}; "
        f"publisher={repo} workflow={EXPECTED_PROVENANCE_WORKFLOW} "
        f"environment={EXPECTED_PROVENANCE_ENVIRONMENT}",
    )


_INSTALL_METADATA_SMOKE_MODULE = None
_ADMISSION_CHECKS_MODULE = None


def _load_install_metadata_smoke():
    """Load the sibling release_install_metadata_smoke.py script by path (not a project import)."""
    global _INSTALL_METADATA_SMOKE_MODULE
    if _INSTALL_METADATA_SMOKE_MODULE is None:
        module_name = "release_install_metadata_smoke"
        smoke_path = Path(__file__).resolve().parent / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, smoke_path)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: sibling script path always returns a spec
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]  # reason: sibling script path has a loader
        _INSTALL_METADATA_SMOKE_MODULE = module
    return _INSTALL_METADATA_SMOKE_MODULE


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


def _surface_from_admission(row, surface_name: str | None = None) -> SurfaceResult:
    return SurfaceResult(
        surface_name or row.name,
        row.status,
        sanitize(row.detail),
        sanitize(row.remediation),
    )


def check_install_smoke(
    version: str,
    package: str,
    run_subprocess: Callable[..., tuple[int, str, str]],
) -> SurfaceResult:
    """Run the install metadata consistency smoke in a disposable venv.

    Delegates to release_install_metadata_smoke.run_venv_smoke: package
    metadata, the imported module's __version__, `version-check --status`, and
    alias provenance must all report the requested version while the Agent
    Plugin and ordinary-runtime probes pass.
    """
    install_spec = f"{package}=={version}"
    try:
        smoke = _load_install_metadata_smoke()
        result = smoke.run_venv_smoke(install_spec, package, run_subprocess)
    except OSError as exc:
        return SurfaceResult(
            SURFACE_SMOKE,
            STATUS_ERROR,
            f"install smoke setup failed: {sanitize(str(exc))}",
            "Fix the install-smoke setup error, then rerun the status gate.",
        )

    surface_detail = "; ".join(
        f"{s.name}={s.status}: {sanitize(s.detail)}" for s in result.surfaces
    )

    if not result.ok:
        status = (
            STATUS_ERROR
            if any(s.status == smoke.STATUS_ERROR for s in result.surfaces)
            else STATUS_FAIL
        )
        detail = f"install metadata smoke failed for {install_spec}"
        if surface_detail:
            detail += f": {surface_detail}"
        return SurfaceResult(
            SURFACE_SMOKE,
            status,
            detail,
            "Fix the install metadata mismatch, then rerun the status gate.",
        )

    if result.expected_version != version:
        return SurfaceResult(
            SURFACE_SMOKE,
            STATUS_FAIL,
            f"install metadata smoke surfaces agreed on {result.expected_version!r} "
            f"but requested version is {version!r}",
            "Wait for fresh install metadata to match the requested release version.",
        )

    return SurfaceResult(
        SURFACE_SMOKE,
        STATUS_OK,
        f"package metadata, module __version__, version-check --status, and alias provenance "
        f"report {package}=={version}; Agent Plugin and ordinary-runtime probes passed",
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
    expect_sha: str | None,
    required_check_name: str,
    audit_max_age_hours: int,
    run_git: Callable[[list[str]], tuple[int, str, str]],
    run_gh: Callable[[list[str]], tuple[int, str, str]],
    http_get: Callable[[str], tuple[int, bytes, str]],
    run_subprocess: Callable[..., tuple[int, str, str]],
) -> GateResult:
    admission = _load_admission_checks()
    surfaces: list[SurfaceResult] = []

    surfaces.append(check_publish_remote_tag(version, remote, run_git))
    candidate_sha, candidate_surface = resolve_candidate_sha(
        version, remote, expect_sha, admission, run_git
    )
    surfaces.append(candidate_surface)

    # Every workflow surface below is exact-SHA evidence. When the candidate SHA
    # could not be established the lookup is not run at all: an unbound
    # `gh run list` answers a different question (what did the branch do lately?)
    # and answering it here would put misleading ok rows in the report.
    if candidate_sha is None:
        surfaces.append(unbound_candidate_workflow_surface(SURFACE_TESTS, TESTS_WORKFLOW))
    else:
        surfaces.append(
            check_workflow_run(
                SURFACE_TESTS,
                TESTS_WORKFLOW,
                repo,
                ["--branch", branch],
                run_gh,
                expected_sha=candidate_sha,
            )
        )
    surfaces.append(
        _surface_from_admission(
            admission.check_aggregate_required_check(
                candidate_sha,
                repo,
                run_gh,
                check_name=required_check_name,
            ),
            SURFACE_REQUIRED_CHECK,
        )
    )
    if candidate_sha is None:
        surfaces.append(unbound_candidate_workflow_surface(SURFACE_PUBLISH, PUBLISH_WORKFLOW))
    else:
        surfaces.append(
            check_workflow_run(
                SURFACE_PUBLISH,
                PUBLISH_WORKFLOW,
                repo,
                [],
                run_gh,
                expected_sha=candidate_sha,
                version=version,
            )
        )
    surfaces.append(check_github_release(version, repo, run_gh, allow_prerelease))
    distributions, pypi_surface = fetch_pypi_distributions(version, package, http_get)
    surfaces.append(pypi_surface)
    if distributions is None:
        surfaces.append(
            _provenance_failure(
                STATUS_FAIL,
                "PyPI provenance was not evaluated because the exact-version inventory is invalid",
            )
        )
    else:
        surfaces.append(
            check_pypi_provenance(
                version,
                package,
                repo,
                distributions,
                http_get,
                run_subprocess,
            )
        )

    if skip_smoke:
        surfaces.append(
            SurfaceResult(SURFACE_SMOKE, STATUS_SKIP, "install smoke skipped by operator")
        )
        partial = True
    else:
        surfaces.append(check_install_smoke(version, package, run_subprocess))
        partial = False

    # One row per protected-ref predicate, always: a failure in either lookup must
    # never remove a required surface from the report.
    surfaces.append(
        _surface_from_admission(
            admission.check_main_branch_rules(
                repo,
                branch,
                run_gh,
                check_name=required_check_name,
            ),
            SURFACE_MAIN_PROTECTION,
        )
    )
    surfaces.append(
        _surface_from_admission(admission.check_tag_ruleset(repo, run_gh), SURFACE_TAG_RULESET)
    )
    surfaces.append(
        _surface_from_admission(
            admission.check_public_orphan_tags(
                version,
                repo,
                remote,
                package,
                run_git,
                run_gh,
                http_get,
                # Post-publication: the public tag for this version must exist.
                require_expected_tag=True,
            ),
            SURFACE_ORPHAN_TAGS,
        )
    )
    surfaces.append(
        _surface_from_admission(
            admission.check_dependency_audit_freshness(
                repo,
                run_gh,
                max_age_hours=audit_max_age_hours,
            ),
            SURFACE_AUDIT,
        )
    )

    _apply_partial_publication_recovery(surfaces, version)
    for surface in surfaces:
        if surface.status not in (STATUS_FAIL, STATUS_ERROR):
            continue
        exact_command = None
        if (
            surface.name == SURFACE_PUBLISH
            and surface.recovery_ready
            and surface.workflow_run_id is not None
            and surface.workflow_job_id is not None
        ):
            exact_command = PARTIAL_RECOVERY_COMMAND_TEMPLATE.format(
                run_id=surface.workflow_run_id,
                job_id=surface.workflow_job_id,
            )
        if surface.remediation == exact_command:
            continue
        if not surface.remediation.startswith("BOUNDED INSTRUCTION: "):
            surface.remediation = f"BOUNDED INSTRUCTION: {surface.remediation}"
    blockers = [s.detail for s in surfaces if s.status in (STATUS_FAIL, STATUS_ERROR)]
    ok = len(blockers) == 0 and not partial

    return GateResult(
        version=version,
        ok=ok,
        partial=partial,
        surfaces=surfaces,
        blockers=blockers,
    )


def _apply_partial_publication_recovery(
    surfaces: list[SurfaceResult],
    version: str,
) -> None:
    """Expose one exact-job rerun only for the fully proven partial state."""
    by_name = {surface.name: surface for surface in surfaces}
    publish = by_name[SURFACE_PUBLISH]
    if not publish.recovery_ready:
        return

    release = by_name[SURFACE_RELEASE]
    release_missing = (
        release.status == STATUS_ERROR and "release not found" in release.detail.lower()
    )
    release_safe = release.status == STATUS_OK or release_missing

    orphan = by_name[SURFACE_ORPHAN_TAGS]
    expected_orphan = re.fullmatch(
        rf"orphan public tags: v{re.escape(version)}: no GitHub Release\."
        r"(?: acknowledged immutable orphan evidence: .+)?",
        orphan.detail,
    )
    orphan_safe = orphan.status == STATUS_OK or (
        orphan.status == STATUS_FAIL and expected_orphan is not None
    )

    allowed_non_ok = {SURFACE_PUBLISH}
    if release_missing:
        allowed_non_ok.add(SURFACE_RELEASE)
    if orphan.status != STATUS_OK and orphan_safe:
        allowed_non_ok.add(SURFACE_ORPHAN_TAGS)
    all_other_surfaces_green = all(
        surface.status == STATUS_OK or surface.name in allowed_non_ok for surface in surfaces
    )
    if not release_safe or not orphan_safe or not all_other_surfaces_green:
        return

    command = PARTIAL_RECOVERY_COMMAND_TEMPLATE.format(
        run_id=publish.workflow_run_id,
        job_id=publish.workflow_job_id,
    )
    publish.remediation = command
    bounded = (
        "BOUNDED INSTRUCTION: use only the exact github-release job rerun printed on "
        f"{SURFACE_PUBLISH}; do not create or edit the GitHub Release manually."
    )
    if release.status != STATUS_OK:
        release.remediation = bounded
    if orphan.status != STATUS_OK:
        orphan.remediation = bounded


# ── Output formatting ──────────────────────────────────────────────────────────

_STATUS_ICON = {STATUS_OK: "✓", STATUS_FAIL: "✗", STATUS_SKIP: "○", STATUS_ERROR: "!"}


def render_human(result: GateResult) -> str:
    lines = [f"## Release v{result.version}", ""]
    for s in result.surfaces:
        icon = _STATUS_ICON.get(s.status, "?")
        lines.append(f"  {icon} {s.name}: {s.detail}")
        if s.status in (STATUS_FAIL, STATUS_ERROR) and s.remediation:
            lines.append(f"    remediation: {s.remediation}")
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
            body = resp.read(MAX_PUBLIC_RESPONSE_BYTES + 1)
            return resp.status, body, ""
    except URLError as e:
        return 0, b"", str(e)


def _default_run_subprocess(
    args: list[str],
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    input_text: str | None = None,
    timeout_seconds: int = DEFAULT_INSTALL_SMOKE_TIMEOUT_SECONDS,
) -> tuple[int, str, str]:
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
GitHub Release metadata, PyPI JSON (wheel + sdist), PyPI provenance, install smoke.

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
        "--expect-sha",
        help="Operator-reviewed 40-hex candidate SHA. Defaults to the public tag commit.",
    )
    parser.add_argument(
        "--required-check-name",
        default=_load_admission_checks().AGGREGATE_REQUIRED_CHECK,
        help=f"Aggregate required check name (default: {_load_admission_checks().AGGREGATE_REQUIRED_CHECK}).",
    )
    parser.add_argument(
        "--audit-max-age-hours",
        type=int,
        default=_load_admission_checks().DEFAULT_AUDIT_MAX_AGE_HOURS,
        help=(
            "Maximum age for the latest successful scheduled dependency-audit run "
            f"(default: {_load_admission_checks().DEFAULT_AUDIT_MAX_AGE_HOURS})."
        ),
    )
    parser.add_argument(
        "--smoke-timeout-seconds",
        type=int,
        default=DEFAULT_INSTALL_SMOKE_TIMEOUT_SECONDS,
        help=(
            "Timeout for each install-smoke subprocess "
            f"(default: {DEFAULT_INSTALL_SMOKE_TIMEOUT_SECONDS})."
        ),
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
        expect_sha=args.expect_sha,
        required_check_name=args.required_check_name,
        audit_max_age_hours=args.audit_max_age_hours,
        run_git=_default_run_git,
        run_gh=_default_run_gh,
        http_get=_default_http_get,
        run_subprocess=lambda cmd, env=None, cwd=None, input_text=None: _default_run_subprocess(
            cmd,
            env=env,
            cwd=cwd,
            input_text=input_text,
            timeout_seconds=args.smoke_timeout_seconds,
        ),
    )

    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(render_human(result))

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
