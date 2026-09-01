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
import ast
import hashlib
import hmac
import importlib.util
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

MANIFEST_PATH = "docs/quality/upstream-comparison.json"
SUPPORTED_SCHEMA_VERSION = 2
DEFAULT_MAX_AGE_DAYS = 30
GITHUB_REPOSITORY_ROOT = "https://github.com/"
DEFAULT_RECOVERY_COMMAND = "python scripts/upstream_comparison_guard.py --check-live --json"
_PUBLIC_READ_MODULE = None

INVENTORY_ANCHOR_FIELD = "inventory_anchor"
INVENTORY_ANCHOR_ALGORITHM = "sha256"
INVENTORY_ANCHOR_VERSION = 1
INVENTORY_ANCHOR_FIELDS = {"algorithm", "version", "count", "digest"}

COMMIT_RE = re.compile(r"[0-9a-f]{40}")
DIGEST_RE = re.compile(r"[0-9a-f]{64}")
ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
IDENTIFIER_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

REQUIRED_STRING_FIELDS = (
    "canonical_repository",
    "branch",
    "commit",
    "previous_commit",
    "reviewed_date",
    "previous_reviewed_date",
    "compare_ref",
    "recovery_command",
    "canonical_document",
    "readme_path",
)
REQUIRED_LIST_FIELDS = (
    "tracked_source_paths",
    "readme_markers",
    "comparison_markers",
)
REQUIRED_MAPPING_FIELDS = (
    "source_refs",
    "capability_sources",
)
CAPABILITY_GROUPS = ("upstream_advertised", "fork_current")

# Closed set of adaptation stances. The comparison document must use the same
# strings, so a decision renamed in one place and not the other fails static
# validation instead of silently drifting.
DECISION_CATEGORIES = (
    "adopted",
    "equivalent-local",
    "migration-only",
    "deferred",
    "irrelevant",
)
# A decision may cite a tracked upstream file, or this literal for a change whose
# only public evidence is the pinned commit range itself (repository metadata,
# website-only files). A release-critical decision must cite a tracked file.
COMPARE_SOURCE_TOKEN = "compare"
DECISION_REQUIRED_FIELDS = (
    "id",
    "upstream_change",
    "source_refs",
    "release_critical",
    "decision",
    "rationale",
    "local_predicates",
)
DECISION_INVENTORY_FIELDS = ("merge_group", "constituent_commits")
# Stances that must carry a named local regression predicate: the fork claims a
# guard exists, so the guard has to be nameable and present in the checkout.
PREDICATE_REQUIRED_DECISIONS = ("adopted", "equivalent-local")

# Current releases fully retire ChromaDB support. All Chroma capability claims
# are forbidden from the fork-current set.
REQUIRED_FORK_CAPABILITIES: tuple[str, ...] = ()
FORBIDDEN_FORK_CAPABILITIES = (
    "backend-chromadb",
    "backend-chromadb-default",
    "backend-chromadb-optional",
    "backend-chromadb-optional-deprecated",
    "backend-chromadb-runtime",
    "backend-chromadb-migration-bridge-only",
)


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

    for field in REQUIRED_MAPPING_FIELDS:
        value = manifest.get(field)
        if not isinstance(value, dict) or not value:
            errors.append(f"manifest-shape: {field} must be a non-empty object")

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

    for field in ("commit", "previous_commit"):
        value = manifest.get(field)
        if isinstance(value, str) and not COMMIT_RE.fullmatch(value):
            errors.append(f"manifest-commit: {field} must be a full 40-character lowercase hex sha")

    commit = manifest.get("commit")
    previous_commit = manifest.get("previous_commit")
    if isinstance(commit, str) and commit == previous_commit:
        errors.append(
            "manifest-commit: previous_commit must differ from commit; a refreshed review "
            "records the pin it replaced"
        )

    repository = manifest.get("canonical_repository")
    if isinstance(repository, str) and repository.strip():
        try:
            repository_slug(repository)
        except ValueError as exc:
            errors.append(str(exc))

    errors.extend(_validate_recovery_command(manifest))
    errors.extend(_validate_compare_ref(manifest))
    errors.extend(_validate_source_refs(manifest))
    errors.extend(_validate_capability_sources(manifest))
    errors.extend(_validate_chroma_stance(manifest))
    errors.extend(_validate_delta_decisions(manifest))
    errors.extend(_validate_inventory_anchor(manifest))

    return errors


def _validate_inventory_anchor(manifest: dict[str, Any]) -> list[str]:
    """Validate the reviewed anchor shape before comparing its derived digest."""
    anchor = manifest.get(INVENTORY_ANCHOR_FIELD)
    if not isinstance(anchor, dict):
        return [f"manifest-shape: {INVENTORY_ANCHOR_FIELD} must be an object"]

    errors: list[str] = []
    fields = set(anchor)
    if fields != INVENTORY_ANCHOR_FIELDS:
        errors.append(
            f"manifest-shape: {INVENTORY_ANCHOR_FIELD} fields must be exactly "
            f"{sorted(INVENTORY_ANCHOR_FIELDS)}, found {sorted(fields)}"
        )
    if anchor.get("algorithm") != INVENTORY_ANCHOR_ALGORITHM:
        errors.append(
            f"manifest-shape: {INVENTORY_ANCHOR_FIELD}.algorithm must be "
            f"{INVENTORY_ANCHOR_ALGORITHM!r}"
        )
    version = anchor.get("version")
    if isinstance(version, bool) or version != INVENTORY_ANCHOR_VERSION:
        errors.append(
            f"manifest-shape: {INVENTORY_ANCHOR_FIELD}.version must be {INVENTORY_ANCHOR_VERSION}"
        )
    count = anchor.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        errors.append(f"manifest-shape: {INVENTORY_ANCHOR_FIELD}.count must be a positive integer")
    digest = anchor.get("digest")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        errors.append(
            f"manifest-shape: {INVENTORY_ANCHOR_FIELD}.digest must be a lowercase "
            "64-character hex sha256"
        )
    return errors


def _validate_recovery_command(manifest: dict[str, Any]) -> list[str]:
    """The published recovery command must actually rerun this guard against upstream."""
    command = manifest.get("recovery_command")
    if not isinstance(command, str) or not command.strip():
        return []
    if "scripts/upstream_comparison_guard.py" not in command or "--check-live" not in command:
        return [
            "manifest-recovery: recovery_command must rerun "
            "scripts/upstream_comparison_guard.py with --check-live, found "
            f"{command!r}"
        ]
    return []


def _validate_compare_ref(manifest: dict[str, Any]) -> list[str]:
    """compare_ref must be the pinned previous_commit...commit range on the same repository."""
    compare_ref = manifest.get("compare_ref")
    repository = manifest.get("canonical_repository")
    previous_commit = manifest.get("previous_commit")
    commit = manifest.get("commit")
    fields = (compare_ref, repository, previous_commit, commit)
    if not all(isinstance(value, str) for value in fields):
        return []
    expected = f"{repository}/compare/{previous_commit}...{commit}"
    if compare_ref != expected:
        return [f"manifest-compare: compare_ref must be {expected!r}, found {compare_ref!r}"]
    return []


def _validate_source_refs(manifest: dict[str, Any]) -> list[str]:
    """Every tracked upstream path needs exactly one link pinned at the reviewed commit."""
    source_refs = manifest.get("source_refs")
    tracked = manifest.get("tracked_source_paths")
    repository = manifest.get("canonical_repository")
    commit = manifest.get("commit")
    if not isinstance(source_refs, dict) or not isinstance(tracked, list):
        return []
    if not isinstance(repository, str) or not isinstance(commit, str):
        return []

    errors: list[str] = []
    tracked_paths = [item for item in tracked if isinstance(item, str)]
    for path in tracked_paths:
        if path not in source_refs:
            errors.append(f"source-ref: tracked source path {path!r} has no entry in source_refs")
            continue
        expected = f"{repository}/blob/{commit}/{path}"
        if source_refs[path] != expected:
            errors.append(
                f"source-ref: source_refs[{path!r}] must be pinned at the reviewed commit "
                f"({expected!r}), found {source_refs[path]!r}"
            )
    for path in source_refs:
        if path not in tracked_paths:
            errors.append(
                f"source-ref: source_refs entry {path!r} is not listed in tracked_source_paths"
            )
    return errors


def _validate_capability_sources(manifest: dict[str, Any]) -> list[str]:
    """Every advertised upstream capability must cite tracked public sources."""
    capability_sources = manifest.get("capability_sources")
    capabilities = manifest.get("capabilities")
    tracked = manifest.get("tracked_source_paths")
    if not isinstance(capability_sources, dict) or not isinstance(capabilities, dict):
        return []
    advertised = capabilities.get("upstream_advertised")
    if not isinstance(advertised, list) or not isinstance(tracked, list):
        return []

    errors: list[str] = []
    tracked_paths = {item for item in tracked if isinstance(item, str)}
    for identifier in advertised:
        if not isinstance(identifier, str):
            continue
        refs = capability_sources.get(identifier)
        if not isinstance(refs, list) or not refs:
            errors.append(
                f"capability-source: capability {identifier!r} has no tracked upstream source; "
                "every advertised capability statement must name where it was read"
            )
            continue
        for ref in refs:
            if ref not in tracked_paths:
                errors.append(
                    f"capability-source: capability {identifier!r} cites {ref!r}, "
                    "which is not a tracked_source_paths entry"
                )
    for identifier in capability_sources:
        if identifier not in advertised:
            errors.append(
                f"capability-source: capability_sources entry {identifier!r} is not listed in "
                "capabilities.upstream_advertised"
            )
    return errors


def _validate_chroma_stance(manifest: dict[str, Any]) -> list[str]:
    """The current fork capability set must record no ChromaDB support."""
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, dict):
        return []
    fork_current = capabilities.get("fork_current")
    if not isinstance(fork_current, list):
        return []

    errors: list[str] = []
    present = {item for item in fork_current if isinstance(item, str)}
    for required in REQUIRED_FORK_CAPABILITIES:
        if required not in present:
            errors.append(
                f"chroma-stance: capabilities.fork_current must record {required!r}; "
                "current releases have retired ChromaDB support"
            )
    for forbidden in FORBIDDEN_FORK_CAPABILITIES:
        if forbidden in present:
            errors.append(
                f"chroma-stance: capabilities.fork_current must not claim {forbidden!r}; "
                "current releases have retired ChromaDB support"
            )
    return errors


def _validate_delta_decisions(manifest: dict[str, Any]) -> list[str]:
    """Each changed upstream item needs one closed-set stance and, when claimed, a predicate."""
    decisions = manifest.get("delta_decisions")
    if not isinstance(decisions, list) or not decisions:
        return ["manifest-shape: delta_decisions must be a non-empty list"]

    tracked = manifest.get("tracked_source_paths")
    tracked_paths: set[str] = set()
    if isinstance(tracked, list):
        tracked_paths = {item for item in tracked if isinstance(item, str)}

    errors: list[str] = []
    seen: set[str] = set()
    commit_occurrences: dict[str, list[str]] = {}
    for index, decision in enumerate(decisions):
        label = f"delta_decisions[{index}]"
        if not isinstance(decision, dict):
            errors.append(f"delta-decision: {label} must be an object")
            continue
        missing = [
            field
            for field in (*DECISION_REQUIRED_FIELDS, *DECISION_INVENTORY_FIELDS)
            if field not in decision
        ]
        if missing:
            errors.append(f"delta-decision: {label} is missing required fields {sorted(missing)}")
            continue

        identifier = decision["id"]
        if not isinstance(identifier, str) or not IDENTIFIER_RE.fullmatch(identifier):
            errors.append(
                f"delta-decision: {label} id {identifier!r} is not a lowercase-hyphen identifier"
            )
            continue
        label = f"delta decision {identifier!r}"
        if identifier in seen:
            errors.append(f"delta-decision: {label} is declared more than once")
        else:
            seen.add(identifier)
        merge_group = decision["merge_group"]
        if not isinstance(merge_group, str) or not COMMIT_RE.fullmatch(merge_group):
            errors.append(
                f"commit-inventory: {label} merge_group must be a full 40-character "
                "lowercase hex sha"
            )
        else:
            commit_occurrences.setdefault(merge_group, []).append(f"{label} merge_group")
        constituent_commits = decision["constituent_commits"]
        if not isinstance(constituent_commits, list) or not constituent_commits:
            errors.append(f"commit-inventory: {label} constituent_commits must be a non-empty list")
        else:
            if not all(
                isinstance(item, str) and COMMIT_RE.fullmatch(item) for item in constituent_commits
            ):
                errors.append(
                    f"commit-inventory: {label} constituent_commits must contain only full "
                    "40-character lowercase hex shas"
                )
            for commit_index, commit in enumerate(constituent_commits):
                if isinstance(commit, str) and COMMIT_RE.fullmatch(commit):
                    occurrence = f"{label} constituent_commits[{commit_index}]"
                    commit_occurrences.setdefault(commit, []).append(occurrence)
        errors.extend(_validate_decision_body(decision, label, tracked_paths))
    for commit, occurrences in commit_occurrences.items():
        if len(occurrences) > 1:
            errors.append(
                f"commit-inventory: commit {commit} is declared more than once: "
                f"{', '.join(occurrences)}"
            )
    return errors


def manifest_commit_inventory(manifest: dict[str, Any]) -> set[str]:
    """Return all merge and constituent commits from a validated manifest."""
    inventory: set[str] = set()
    for decision in manifest["delta_decisions"]:
        inventory.add(str(decision["merge_group"]))
        inventory.update(str(commit) for commit in decision["constituent_commits"])
    return inventory


def inventory_anchor_payload(manifest: dict[str, Any], commits: set[str]) -> bytes:
    """Return canonical bytes binding the reviewed range identity and full inventory."""
    anchor = manifest[INVENTORY_ANCHOR_FIELD]
    payload = {
        "algorithm": anchor["algorithm"],
        "version": anchor["version"],
        "canonical_repository": manifest["canonical_repository"],
        "branch": manifest["branch"],
        "previous_commit": manifest["previous_commit"],
        "commit": manifest["commit"],
        "count": anchor["count"],
        "inventory": sorted(commits),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def inventory_anchor_digest(manifest: dict[str, Any], commits: set[str]) -> str:
    """Return the SHA-256 digest of the canonical reviewed inventory payload."""
    return hashlib.sha256(inventory_anchor_payload(manifest, commits)).hexdigest()


def _validate_decision_body(
    decision: dict[str, Any], label: str, tracked_paths: set[str]
) -> list[str]:
    errors: list[str] = []

    for field in ("upstream_change", "rationale"):
        value = decision[field]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"delta-decision: {label} {field} must be a non-empty string")

    category = decision["decision"]
    if category not in DECISION_CATEGORIES:
        errors.append(
            f"delta-decision: {label} decision {category!r} is not one of "
            f"{list(DECISION_CATEGORIES)}"
        )

    release_critical = decision["release_critical"]
    if not isinstance(release_critical, bool):
        errors.append(f"delta-decision: {label} release_critical must be a boolean")
        release_critical = False

    source_refs = decision["source_refs"]
    if not isinstance(source_refs, list) or not source_refs:
        errors.append(f"delta-decision: {label} source_refs must be a non-empty list")
    else:
        allowed = tracked_paths | {COMPARE_SOURCE_TOKEN}
        unknown = [ref for ref in source_refs if ref not in allowed]
        if unknown:
            errors.append(
                f"delta-decision: {label} cites untracked sources {unknown}; use a "
                f"tracked_source_paths entry or {COMPARE_SOURCE_TOKEN!r}"
            )
        if release_critical and not any(ref in tracked_paths for ref in source_refs):
            errors.append(
                f"delta-decision: {label} is release-critical and must cite at least one "
                "tracked public upstream source"
            )

    predicates = decision["local_predicates"]
    if not isinstance(predicates, list) or not all(
        isinstance(item, str) and item.strip() for item in predicates
    ):
        errors.append(
            f"delta-decision: {label} local_predicates must be a list of non-empty strings"
        )
    elif category in PREDICATE_REQUIRED_DECISIONS and not predicates:
        errors.append(
            f"delta-decision: {label} claims decision {category!r} and must name at least one "
            "local regression predicate"
        )
    return errors


def predicate_path(predicate: str) -> str | None:
    """Return the repo-relative file a predicate names, if it names one.

    Predicates are recorded as ``path::name``, a bare path, or a command that
    contains one; only the path part is checked, because a renamed or deleted
    guard file is the drift this catches.
    """
    for token in predicate.split():
        candidate = token.split("::", 1)[0]
        if "/" in candidate:
            return candidate
    return None


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


def parse_reviewed_date(value: str, field: str = "reviewed_date") -> date:
    """Parse a strict ISO calendar date, rejecting any other accepted ISO form."""
    if not ISO_DATE_RE.fullmatch(value):
        raise ValueError(f"manifest-date: {field} must be an ISO date formatted YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"manifest-date: {field} is not a real calendar date ({exc})") from exc


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
    previous_commit = str(manifest["previous_commit"])
    reviewed_date_text = str(manifest["reviewed_date"])
    previous_reviewed_date_text = str(manifest["previous_reviewed_date"])
    compare_ref = str(manifest["compare_ref"])
    recovery_command = str(manifest["recovery_command"])
    canonical_document = str(manifest["canonical_document"])
    readme_path = str(manifest["readme_path"])

    try:
        reviewed_date = parse_reviewed_date(reviewed_date_text)
        previous_reviewed_date = parse_reviewed_date(
            previous_reviewed_date_text, field="previous_reviewed_date"
        )
    except ValueError as exc:
        return {}, [str(exc)]

    if previous_reviewed_date > reviewed_date:
        errors.append(
            f"manifest-date: previous_reviewed_date {previous_reviewed_date_text} is after "
            f"reviewed_date {reviewed_date_text}; the refreshed review must not predate the pin "
            "it replaces"
        )

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
            ("previous_commit", previous_commit),
            ("reviewed_date", reviewed_date_text),
            ("previous_reviewed_date", previous_reviewed_date_text),
            ("compare_ref", compare_ref),
            ("recovery_command", recovery_command),
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
        for path, ref in sorted(manifest["source_refs"].items()):
            if ref not in document:
                errors.append(
                    f"source-ref: {canonical_document} does not publish the pinned source link "
                    f"for {path!r}; readers cannot check the claim without it"
                )
        for decision in manifest["delta_decisions"]:
            identifier = str(decision["id"])
            decision_lines = _document_decision_lines(document, identifier)
            if not decision_lines:
                errors.append(
                    f"delta-decision: {canonical_document} does not record delta decision "
                    f"{identifier!r}"
                )
            category = str(decision["decision"])
            if decision_lines and not any(
                _line_binds_decision(line, identifier, category) for line in decision_lines
            ):
                errors.append(
                    f"delta-decision: {canonical_document} does not bind {identifier!r} to "
                    f"the manifest decision category {category!r} on the same line"
                )

    errors.extend(_missing_predicate_errors(root, manifest["delta_decisions"]))

    manifest_commits = manifest_commit_inventory(manifest)
    anchor: dict[str, Any] = manifest[INVENTORY_ANCHOR_FIELD]
    derived_count = len(manifest_commits)
    computed_digest = inventory_anchor_digest(manifest, manifest_commits)
    count_exact = anchor["count"] == derived_count
    digest_exact = hmac.compare_digest(anchor["digest"], computed_digest)
    if not count_exact:
        errors.append(
            "commit-inventory: trust-anchor count mismatch: expected "
            f"{anchor['count']}, derived {derived_count}"
        )
    if not digest_exact:
        errors.append(
            "commit-inventory: trust-anchor digest mismatch: expected "
            f"{anchor['digest']}, computed {computed_digest}"
        )

    facts: dict[str, Any] = {
        "canonical_repository": repository,
        "branch": branch,
        "commit": commit,
        "previous_commit": previous_commit,
        "compare_ref": compare_ref,
        "reviewed_date": reviewed_date_text,
        "previous_reviewed_date": previous_reviewed_date_text,
        "review_age_days": age_days,
        "max_age_days": max_age_days,
        "canonical_document": canonical_document,
        "recovery_command": recovery_command,
        "tracked_source_paths": list(manifest["tracked_source_paths"]),
        "capabilities": {
            group: list(manifest["capabilities"][group]) for group in CAPABILITY_GROUPS
        },
        "delta_decisions": {
            str(decision["id"]): str(decision["decision"])
            for decision in manifest["delta_decisions"]
        },
        "release_critical_decisions": sorted(
            str(decision["id"])
            for decision in manifest["delta_decisions"]
            if decision["release_critical"]
        ),
        "inventory_anchor_algorithm": anchor["algorithm"],
        "inventory_anchor_version": anchor["version"],
        "inventory_anchor_declared_count": anchor["count"],
        "inventory_anchor_derived_count": derived_count,
        "inventory_anchor_digest": anchor["digest"],
        "inventory_anchor_computed_digest": computed_digest,
        "commit_inventory_exact": count_exact and digest_exact,
    }
    return facts, errors


def _document_decision_lines(document: str, identifier: str) -> list[str]:
    """Return canonical table or bullet rows owned by one decision identifier."""
    marker = f"`{identifier}`"
    lines: list[str] = []
    for raw_line in document.splitlines():
        line = raw_line.strip()
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if cells and cells[0] == marker:
                lines.append(line)
        elif line.startswith(f"- {marker} "):
            lines.append(line)
    return lines


def _line_binds_decision(line: str, identifier: str, category: str) -> bool:
    """Require the category in the owned table cell or canonical fixture bullet."""
    expected = f"`{category}`"
    if line.startswith("|"):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        return len(cells) >= 3 and cells[0] == f"`{identifier}`" and cells[2] == expected
    return line == f"- `{identifier}` — {expected}"


def _missing_predicate_errors(root: Path, decisions: list[Any]) -> list[str]:
    """A named local guard must exist in this checkout, or the stance is unproven."""
    errors: list[str] = []
    for decision in decisions:
        identifier = str(decision["id"])
        for predicate in decision["local_predicates"]:
            relative = predicate_path(str(predicate))
            if relative is None:
                errors.append(
                    f"local-predicate: delta decision {identifier!r} predicate {predicate!r} "
                    "does not name a repository-relative path"
                )
                continue
            if not (root / relative).is_file():
                errors.append(
                    f"local-predicate: delta decision {identifier!r} names {relative!r}, "
                    "which is not a file in this checkout"
                )
                continue
            test_name = predicate_test_name(str(predicate))
            if test_name is not None and not python_file_defines(root / relative, test_name):
                errors.append(
                    f"local-predicate: delta decision {identifier!r} names test "
                    f"{test_name!r}, which is not defined in {relative!r}"
                )
    return errors


def predicate_test_name(predicate: str) -> str | None:
    """Return the final pytest node component from a path::node predicate."""
    for token in predicate.split():
        if "::" not in token:
            continue
        parts = token.split("::")
        if "/" in parts[0] and parts[-1]:
            return parts[-1].split("[", 1)[0]
    return None


def python_file_defines(path: Path, function_name: str) -> bool:
    """Verify a Python predicate names a concrete function or method definition."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        for node in ast.walk(tree)
    )


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


def fetch_head_commit(
    manifest: dict[str, Any],
    *,
    public_read: Callable[[object], object] | None = None,
) -> str:
    """Return the current head sha of the manifest branch using one read-only request."""
    public = _load_public_read()
    reader = public_read or public.DEFAULT_READER
    owner, name = repository_slug(str(manifest["canonical_repository"]))
    repository = f"{owner}/{name}"
    branch = str(manifest["branch"])
    try:
        result = reader(public.reviewed_upstream_head(repository, branch))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise LiveCheckError(f"live-response: upstream head request failed ({exc})") from exc
    if getattr(result, "error", ""):
        raise LiveCheckError(
            f"live-response: upstream head request failed ({getattr(result, 'error', '')})"
        )
    sha = getattr(result, "data", None)
    if not isinstance(sha, str) or not COMMIT_RE.fullmatch(sha):
        raise LiveCheckError("live-response: upstream head reply carried no 40-hex commit sha")
    return sha


def check_live(
    manifest: dict[str, Any],
    *,
    public_read: Callable[[object], object] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Compare the pinned commit against the live branch head. Read-only, no mutation."""
    pinned = str(manifest.get("commit", ""))
    branch = str(manifest.get("branch", ""))
    repository = str(manifest.get("canonical_repository", ""))
    recovery = str(manifest.get("recovery_command") or DEFAULT_RECOVERY_COMMAND)
    try:
        head = fetch_head_commit(manifest, public_read=public_read)
    except (LiveCheckError, ValueError) as exc:
        return {"live_head": None, "pinned_commit": pinned}, [str(exc)]

    facts = {"live_head": head, "pinned_commit": pinned, "branch": branch}
    if head != pinned:
        return facts, [
            f"upstream-drift: {repository} branch {branch} now heads at {head}, "
            f"but the reviewed snapshot is pinned to {pinned}; re-review upstream at "
            f"{repository}/compare/{pinned}...{head} and refresh the manifest and "
            f"comparison document together, then confirm with: {recovery}"
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
        recovery = facts.get("recovery_command", DEFAULT_RECOVERY_COMMAND)
        print(f"  recovery: {recovery}", file=sys.stderr)
    else:
        live_note = f" live_head={live_facts['live_head']}" if live_facts else ""
        decisions = facts["delta_decisions"]
        print(
            "upstream-comparison-guard: OK "
            f"branch={facts['branch']} commit={facts['commit']} "
            f"previous={facts['previous_commit']} "
            f"reviewed={facts['reviewed_date']} age_days={facts['review_age_days']} "
            f"delta_decisions={len(decisions)} "
            f"release_critical={len(facts['release_critical_decisions'])} "
            f"manifest_inventory_commits={facts['inventory_anchor_derived_count']}"
            f"{live_note}"
        )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
