#!/usr/bin/env python3
"""Guard the reviewed upstream comparison against silent drift.

The guard is stdlib-only so it can run in lint CI without importing package
dependencies. Static mode reads only the checked-out tree and performs no
network access. Live mode is opt-in, read-only, and performs exactly one
GitHub API request for the pinned branch head.

The guard never rewrites the manifest, the comparison document, or the README,
and never performs a GitHub mutation of any kind.

Usage:
    python scripts/upstream_comparison_guard.py
    python scripts/upstream_comparison_guard.py --root /path/to/checkout --json
    python scripts/upstream_comparison_guard.py --check-live
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

MANIFEST_PATH = "docs/quality/upstream-comparison.json"
SUPPORTED_SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_DAYS = 30
GITHUB_API_ROOT = "https://api.github.com"
GITHUB_REPOSITORY_ROOT = "https://github.com/"
USER_AGENT = "mempalace-code-upstream-comparison-guard"
LIVE_TIMEOUT_SECONDS = 20

COMMIT_RE = re.compile(r"[0-9a-f]{40}")
ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
IDENTIFIER_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

REQUIRED_STRING_FIELDS = (
    "canonical_repository",
    "branch",
    "commit",
    "reviewed_date",
    "canonical_document",
    "readme_path",
)
REQUIRED_LIST_FIELDS = (
    "tracked_source_paths",
    "readme_markers",
    "comparison_markers",
)
CAPABILITY_GROUPS = ("upstream_advertised", "fork_current")


class LiveCheckError(RuntimeError):
    """Raised when the read-only upstream head lookup cannot be trusted."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_manifest(root: Path) -> dict[str, Any]:
    """Read the comparison manifest, raising ValueError on unusable input."""
    path = root / MANIFEST_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"manifest-missing: {MANIFEST_PATH} could not be read ({exc})") from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest-shape: {MANIFEST_PATH} is not valid JSON ({exc})") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest-shape: {MANIFEST_PATH} must contain a JSON object")
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return shape errors for the manifest, independent of any repository file."""
    errors: list[str] = []

    schema_version = manifest.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        errors.append(
            "manifest-shape: schema_version must be "
            f"{SUPPORTED_SCHEMA_VERSION}, found {schema_version!r}"
        )

    for field in REQUIRED_STRING_FIELDS:
        value = manifest.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"manifest-shape: {field} must be a non-empty string")

    for field in REQUIRED_LIST_FIELDS:
        value = manifest.get(field)
        if not isinstance(value, list) or not value:
            errors.append(f"manifest-shape: {field} must be a non-empty list")
        elif not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"manifest-shape: {field} must contain only non-empty strings")

    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        errors.append("manifest-shape: capabilities must be an object")
    else:
        for group in CAPABILITY_GROUPS:
            value = capabilities.get(group)
            if not isinstance(value, list) or not value:
                errors.append(f"manifest-shape: capabilities.{group} must be a non-empty list")
                continue
            for item in value:
                if not isinstance(item, str) or not IDENTIFIER_RE.fullmatch(item):
                    errors.append(
                        f"manifest-shape: capabilities.{group} entry {item!r} "
                        "is not a lowercase-hyphen identifier"
                    )

    commit = manifest.get("commit")
    if isinstance(commit, str) and not COMMIT_RE.fullmatch(commit):
        errors.append("manifest-commit: commit must be a full 40-character lowercase hex sha")

    repository = manifest.get("canonical_repository")
    if isinstance(repository, str) and repository.strip():
        try:
            repository_slug(repository)
        except ValueError as exc:
            errors.append(str(exc))

    return errors


def repository_slug(repository: str) -> tuple[str, str]:
    """Split a canonical https://github.com/<owner>/<repo> URL into its parts."""
    if not repository.startswith(GITHUB_REPOSITORY_ROOT):
        raise ValueError(
            "manifest-shape: canonical_repository must be a https://github.com/<owner>/<repo> URL"
        )
    parts = repository[len(GITHUB_REPOSITORY_ROOT) :].strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            "manifest-shape: canonical_repository must name exactly one owner and one repository"
        )
    return parts[0], parts[1]


def parse_reviewed_date(value: str) -> date:
    """Parse a strict ISO calendar date, rejecting any other accepted ISO form."""
    if not ISO_DATE_RE.fullmatch(value):
        raise ValueError("manifest-date: reviewed_date must be an ISO date formatted YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"manifest-date: reviewed_date is not a real calendar date ({exc})"
        ) from exc


def _read_text(root: Path, relative_path: str, error_class: str) -> tuple[str | None, str | None]:
    path = root / relative_path
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError:
        return None, f"{error_class}: required file is missing or unreadable: {relative_path}"


def evaluate(
    root: Path,
    *,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    today: date | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return reviewed upstream facts and any static drift errors. No network access."""
    if max_age_days < 0:
        return {}, [f"config-invalid: max_age_days must not be negative, found {max_age_days}"]

    try:
        manifest = load_manifest(root)
    except ValueError as exc:
        return {}, [str(exc)]

    errors = validate_manifest(manifest)
    if errors:
        return {}, errors

    repository = str(manifest["canonical_repository"])
    branch = str(manifest["branch"])
    commit = str(manifest["commit"])
    reviewed_date_text = str(manifest["reviewed_date"])
    canonical_document = str(manifest["canonical_document"])
    readme_path = str(manifest["readme_path"])

    try:
        reviewed_date = parse_reviewed_date(reviewed_date_text)
    except ValueError as exc:
        return {}, [str(exc)]

    current_day = today or datetime.now(UTC).date()
    age_days = (current_day - reviewed_date).days
    if age_days < 0:
        errors.append(
            f"manifest-date: reviewed_date {reviewed_date_text} is in the future "
            f"relative to {current_day.isoformat()}"
        )
    elif age_days > max_age_days:
        errors.append(
            f"review-stale: upstream comparison was reviewed {age_days} days ago "
            f"({reviewed_date_text}), which exceeds the maximum review age of "
            f"{max_age_days} days; re-review upstream and refresh the manifest and "
            f"{canonical_document} together"
        )

    readme, readme_error = _read_text(root, readme_path, "readme-pointer")
    if readme_error:
        errors.append(readme_error)
    else:
        assert readme is not None
        for marker in manifest["readme_markers"]:
            if marker not in readme:
                errors.append(
                    f"readme-pointer: {readme_path} is missing the required marker {marker!r}; "
                    "the fork-vs-upstream section must keep its heading and its pointers"
                )

    document, document_error = _read_text(root, canonical_document, "comparison-document")
    if document_error:
        errors.append(document_error)
    else:
        assert document is not None
        for marker in manifest["comparison_markers"]:
            if marker not in document:
                errors.append(
                    f"comparison-document: {canonical_document} is missing the required "
                    f"section marker {marker!r}"
                )
        for field_name, expected in (
            ("canonical_repository", repository),
            ("branch", branch),
            ("commit", commit),
            ("reviewed_date", reviewed_date_text),
        ):
            if expected not in document:
                errors.append(
                    f"ref-consistency: {canonical_document} does not state the manifest "
                    f"{field_name} {expected!r}"
                )
        capabilities: dict[str, Any] = manifest["capabilities"]
        for group in CAPABILITY_GROUPS:
            for identifier in capabilities[group]:
                if identifier not in document:
                    errors.append(
                        f"ref-consistency: {canonical_document} does not list the manifest "
                        f"capability identifier {identifier!r} from capabilities.{group}"
                    )

    facts: dict[str, Any] = {
        "canonical_repository": repository,
        "branch": branch,
        "commit": commit,
        "reviewed_date": reviewed_date_text,
        "review_age_days": age_days,
        "max_age_days": max_age_days,
        "canonical_document": canonical_document,
        "tracked_source_paths": list(manifest["tracked_source_paths"]),
        "capabilities": {
            group: list(manifest["capabilities"][group]) for group in CAPABILITY_GROUPS
        },
    }
    return facts, errors


def _default_fetch(url: str) -> str:
    request = urllib.request.Request(  # noqa: S310 - fixed https GitHub API endpoint
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=LIVE_TIMEOUT_SECONDS) as response:  # noqa: S310
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LiveCheckError(f"live-response: upstream head request failed ({exc})") from exc
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiveCheckError("live-response: upstream head reply was not valid UTF-8") from exc


def head_commit_url(manifest: dict[str, Any]) -> str:
    """Build the read-only GitHub API URL for the manifest branch head."""
    owner, repo = repository_slug(str(manifest["canonical_repository"]))
    branch = urllib.parse.quote(str(manifest["branch"]), safe="")
    return f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/commits/{branch}"


def fetch_head_commit(
    manifest: dict[str, Any],
    *,
    fetch: Callable[[str], str] = _default_fetch,
) -> str:
    """Return the current head sha of the manifest branch using one read-only request."""
    payload = fetch(head_commit_url(manifest))
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise LiveCheckError("live-response: upstream head reply was not valid JSON") from exc
    if not isinstance(data, dict):
        raise LiveCheckError("live-response: upstream head reply was not a JSON object")
    sha = data.get("sha")
    if not isinstance(sha, str) or not COMMIT_RE.fullmatch(sha):
        raise LiveCheckError("live-response: upstream head reply carried no 40-hex commit sha")
    return sha


def check_live(
    manifest: dict[str, Any],
    *,
    fetch: Callable[[str], str] = _default_fetch,
) -> tuple[dict[str, Any], list[str]]:
    """Compare the pinned commit against the live branch head. Read-only, no mutation."""
    pinned = str(manifest.get("commit", ""))
    branch = str(manifest.get("branch", ""))
    repository = str(manifest.get("canonical_repository", ""))
    try:
        head = fetch_head_commit(manifest, fetch=fetch)
    except (LiveCheckError, ValueError) as exc:
        return {"live_head": None, "pinned_commit": pinned}, [str(exc)]

    facts = {"live_head": head, "pinned_commit": pinned, "branch": branch}
    if head != pinned:
        return facts, [
            f"upstream-drift: {repository} branch {branch} now heads at {head}, "
            f"but the reviewed snapshot is pinned to {pinned}; re-review upstream and "
            "refresh the manifest and comparison document together"
        ]
    return facts, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the reviewed upstream comparison snapshot. Static checks are "
            "network-free; --check-live adds one read-only GitHub API request."
        )
    )
    parser.add_argument(
        "--root", type=Path, default=repo_root(), help="Repository root to inspect."
    )
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON.")
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Maximum allowed review age in days (default: {DEFAULT_MAX_AGE_DAYS}).",
    )
    parser.add_argument(
        "--check-live",
        action="store_true",
        dest="check_live",
        help="Additionally query the upstream branch head read-only and compare it to the pin.",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    facts, errors = evaluate(root, max_age_days=args.max_age_days)

    live_facts: dict[str, Any] = {}
    if args.check_live and not errors:
        try:
            manifest = load_manifest(root)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            live_facts, live_errors = check_live(manifest)
            errors.extend(live_errors)
    elif args.check_live:
        errors.append(
            "live-skipped: static checks failed, so the read-only upstream head "
            "comparison was not attempted"
        )

    result = {
        "ok": not errors,
        "live_checked": bool(args.check_live and live_facts),
        "facts": facts,
        "live": live_facts,
        "errors": errors,
    }
    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif errors:
        print("upstream-comparison-guard: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    else:
        live_note = f" live_head={live_facts['live_head']}" if live_facts else ""
        print(
            "upstream-comparison-guard: OK "
            f"branch={facts['branch']} commit={facts['commit']} "
            f"reviewed={facts['reviewed_date']} age_days={facts['review_age_days']}{live_note}"
        )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
