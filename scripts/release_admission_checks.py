#!/usr/bin/env python3
"""Shared read-only release-admission predicates.

Stdlib-only predicates used by release preflight, readiness, and status gates.
Every live input arrives through the sibling endpoint-specific public-read seam.

Nothing here creates, edits, or deletes a GitHub ruleset, branch protection
entry, tag, release, or package. Remediation command text is inert output and is
never passed to a process seam.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


DEFAULT_REPO = "rergards/mempalace-code"
DEFAULT_BRANCH = "main"
DEFAULT_PACKAGE = "mempalace-code"
AGGREGATE_REQUIRED_CHECK = "release-required"
TESTS_WORKFLOW = "Tests"
PUBLISH_WORKFLOW = "Publish to PyPI"
DEPENDENCY_AUDIT_WORKFLOW = "Dependency Audit"
RULESET_DOC = "docs/release-admission-rulesets.md"

# The release-critical ci.yml jobs the aggregate check must depend on. The
# workflow-shape test compares the ``needs:`` list against this tuple, so adding
# a release-critical job to ci.yml without widening the aggregate check fails.
RELEASE_CRITICAL_CI_JOBS: tuple[str, ...] = (
    "chroma-migration-bridge",
    "dependency-upgrade-gate",
    "gitleaks-changed-range",
    "installed-application",
    "lint",
    "package",
    "test",
    "typecheck",
)

# The classification is total: every ci.yml job is either release-critical, the
# aggregate check itself, or listed here with the reason it cannot gate a
# release. ``test_no_ci_job_escapes_the_release_critical_classification``
# compares the workflow's job set against exactly these three groups, so a new
# job added to ci.yml fails until someone classifies it. Nothing in
# RELEASE_CRITICAL_CI_JOBS may ever appear here.
AGGREGATE_EXEMPT_CI_JOBS: dict[str, str] = {
    "model-tests": (
        "manual workflow_dispatch-only needs_network suite: it never runs on push or "
        "pull_request, so requiring it would make release-required permanently red"
    ),
}

# Dependency Audit runs weekly (cron "0 6 * * 1"). A window equal to the cadence
# would flip to stale on every scheduler delay, so the release window is one
# period plus 24h of slack. A genuinely skipped week still fails closed.
DEPENDENCY_AUDIT_CADENCE_HOURS = 168
DEFAULT_AUDIT_MAX_AGE_HOURS = DEPENDENCY_AUDIT_CADENCE_HOURS + 24
# A run stamped in the future means an untrustworthy clock on either side, so
# anything beyond this skew is an error rather than "very fresh".
AUDIT_FUTURE_SKEW = timedelta(hours=1)

# Public ``refs/heads/main`` contract, expressed as GitHub repository-rule types.
# ``non_fast_forward`` rejects force-pushes; ``deletion`` rejects branch deletion.
MAIN_BRANCH_REQUIRED_RULE_TYPES: tuple[str, ...] = (
    "deletion",
    "non_fast_forward",
    "required_status_checks",
)
# Public ``refs/tags/v*`` contract: creation, update, and deletion are all
# restricted to the documented release path.
TAG_RULESET_REF = "refs/tags/v*"
TAG_RULESET_TARGET = "tag"
TAG_RULESET_REQUIRED_RULE_TYPES: tuple[str, ...] = ("creation", "deletion", "update")
RULESET_ACTIVE_ENFORCEMENT = "active"

# Public ``v*`` tags whose missing public surfaces are already known, reviewed,
# and immutable. They are always reported, never repaired by these scripts, and
# never block admission. Any *other* orphan tag is a new regression and fails.
_PRE_AUTOMATION_ORPHAN = (
    "historical tag: PyPI distribution published before GitHub Release creation "
    "was automated; no GitHub Release exists and the tag is immutable"
)
ACKNOWLEDGED_ORPHAN_TAGS: dict[str, str] = {
    "v1.0.0": _PRE_AUTOMATION_ORPHAN,
    "v1.1.0": _PRE_AUTOMATION_ORPHAN,
    "v1.1.1": _PRE_AUTOMATION_ORPHAN,
    "v1.2.0": _PRE_AUTOMATION_ORPHAN,
    "v1.3.0": _PRE_AUTOMATION_ORPHAN,
    "v1.4.0": _PRE_AUTOMATION_ORPHAN,
    "v1.4.1": _PRE_AUTOMATION_ORPHAN,
    "v1.5.0": _PRE_AUTOMATION_ORPHAN,
    "v1.6.0": _PRE_AUTOMATION_ORPHAN,
    "v1.6.1": _PRE_AUTOMATION_ORPHAN,
    "v1.6.2": _PRE_AUTOMATION_ORPHAN,
    "v1.7.0": _PRE_AUTOMATION_ORPHAN,
    "v1.8.0": _PRE_AUTOMATION_ORPHAN,
    "v1.10.2": _PRE_AUTOMATION_ORPHAN,
    "v1.13.2": (
        "failed publish attempt: no PyPI distribution and no GitHub Release; the "
        "tag stays as immutable public evidence and must never be moved or deleted"
    ),
}

# Bounds on live lookups so a large repository cannot flood a release log.
MAX_RULESET_DETAIL_LOOKUPS = 50
# Ask for one ruleset more than the budget. Requesting exactly the budget makes a
# truncated first page indistinguishable from a complete result set, so a v* tag
# ruleset sitting on page 2 would vanish and the predicate would report "no
# ruleset covers refs/tags/v*" instead of "this lookup could not see them all".
RULESET_LIST_PAGE_SIZE = MAX_RULESET_DETAIL_LOOKUPS + 1
MAX_RELEASE_LIST = 200
PUBLIC_RELEASE_FIELDS = "tagName,isDraft,isPrerelease,isLatest,publishedAt"
MAX_CHECK_RUN_PAGE = 100
MAX_WORKFLOW_RUN_LIST = 30
MAX_DETAIL_CHARS = 320
MAX_LISTED_ITEMS = 8

STATUS_OK = "ok"
STATUS_FAIL = "fail"
STATUS_ERROR = "error"

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_PUBLIC_READ_MODULE = None

# Every failed predicate names one concrete command, so an operator resuming with
# lost context never has to reconstruct the next step from prose.
REMEDIATE_EXPECT_SHA = (
    "Rerun with the reviewed candidate 40-hex SHA: "
    "python scripts/release_preflight.py --expect-sha <40-hex-candidate-sha>"
)
REMEDIATE_SHA_DRIFT = "Re-review the moved ref, then rerun with the new candidate --expect-sha."
REMEDIATE_HEAD_SHA = "Check out the reviewed candidate SHA: git checkout <40-hex-candidate-sha>"
REMEDIATE_TAG_SHA = (
    "Re-review the SHA or bump project.version, and never move a published tag: "
    "git rev-parse --verify refs/tags/<tag>^{commit}"
)
REMEDIATE_CANDIDATE_SHA = (
    "Refresh and re-review the public candidate: git fetch <remote> <branch>, then rerun "
    "with the reviewed --expect-sha."
)
# Re-target the push or pull_request run that already exists for the candidate
# SHA. A dispatch-shaped run is never the recovery, and re-running one is not
# either: ci.yml gates dependency-upgrade-gate and gitleaks-changed-range off
# workflow_dispatch, and `gh run rerun` replays the original event, so both a new
# dispatch and a replayed dispatch publish a newer, failing
# AGGREGATE_REQUIRED_CHECK on the SHA they were meant to repair. Every gh command
# names --repo: this text is read by an operator whose shell may be defaulted to
# a fork, where a bare invocation silently inspects the wrong repository.
REMEDIATE_CHECK = (
    f"Re-run the push or pull_request {TESTS_WORKFLOW} run that already exists for the candidate "
    f"SHA: gh run list --repo {DEFAULT_REPO} --workflow {TESTS_WORKFLOW} --json "
    f"headSha,event,databaseId,conclusion, then gh run rerun <run-id> --repo {DEFAULT_REPO} "
    "--failed for a run whose event is push or pull_request. If the candidate SHA has no such run "
    "— none at all, or only a workflow_dispatch run — land it through a push or pull_request event "
    "instead; never rerun or dispatch a workflow_dispatch run, which skips release-critical jobs "
    f"and republishes a failing {AGGREGATE_REQUIRED_CHECK}."
)
REMEDIATE_AUDIT = (
    f"Rerun the audit and wait for a fresh success: gh workflow run "
    f"'{DEPENDENCY_AUDIT_WORKFLOW}' --repo {DEFAULT_REPO}"
)
REMEDIATE_MAIN_RULESET = f"Apply the public main branch-rule contract in {RULESET_DOC}."
REMEDIATE_TAG_RULESET = f"Apply the public v* tag ruleset contract in {RULESET_DOC}."
REMEDIATE_RULESET_SCOPE = (
    "Rerun with a token that has read access to repository rulesets, or verify the "
    f"ruleset by hand against {RULESET_DOC}."
)
# Repair first: during the window between tag push and PyPI/Release completion an
# orphan row is a race, not a permanent gap, and acknowledging it there would
# suppress the very evidence this predicate exists to collect.
REMEDIATE_ORPHAN = (
    "Create the missing non-draft GitHub Release and PyPI distribution for the tag; if the "
    "publication is still in flight, wait for it and rerun. Only when the missing surface is "
    "permanent, record the tag in ACKNOWLEDGED_ORPHAN_TAGS with its reason and update "
    f"{RULESET_DOC}."
)


@dataclass
class AdmissionRow:
    """One release-admission predicate result."""

    name: str
    status: str
    detail: str
    remediation: str = ""

    def to_dict(self) -> dict[str, object]:
        row: dict[str, object] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }
        if self.remediation:
            row["remediation"] = self.remediation
        return row


def truncate(text: str, limit: int = MAX_DETAIL_CHARS) -> str:
    """Bound a live diagnostic so a gate log cannot echo a whole API response."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}… (truncated)"


def ok_row(name: str, detail: str) -> AdmissionRow:
    return AdmissionRow(name, STATUS_OK, truncate(detail))


def fail_row(name: str, detail: str, remediation: str) -> AdmissionRow:
    return AdmissionRow(name, STATUS_FAIL, truncate(detail), remediation)


def error_row(name: str, detail: str, remediation: str) -> AdmissionRow:
    return AdmissionRow(name, STATUS_ERROR, truncate(detail), remediation)


def normalize_expected_sha(value: str | None) -> tuple[str | None, AdmissionRow | None]:
    """Return ``(lowercase sha, row)``; ``(None, None)`` when no SHA was requested."""
    if value is None:
        return None, None
    candidate = value.strip()
    if not SHA_RE.fullmatch(candidate):
        return None, fail_row(
            "expected_sha_format",
            "--expect-sha must be exactly 40 hexadecimal characters",
            REMEDIATE_EXPECT_SHA,
        )
    normalized = candidate.lower()
    return normalized, ok_row("expected_sha_format", f"reviewed SHA {normalized}")


def compare_sha_row(
    name: str,
    actual: str,
    expected: str,
    subject: str,
    remediation: str = REMEDIATE_SHA_DRIFT,
) -> AdmissionRow:
    actual_normalized = actual.strip().lower()
    if actual_normalized == expected:
        return ok_row(name, f"{subject} matches reviewed SHA {expected}")
    return fail_row(
        name,
        f"{subject} is {actual_normalized or '<empty>'}, expected {expected}",
        remediation,
    )


def _load_public_read():
    global _PUBLIC_READ_MODULE
    if _PUBLIC_READ_MODULE is None:
        module_name = "release_public_read"
        path = __import__("pathlib").Path(__file__).resolve().parent / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        _PUBLIC_READ_MODULE = module
    return _PUBLIC_READ_MODULE


def _public_data(
    public_read: Callable[[object], object],
    query: object,
    *,
    row_name: str,
    remediation: str,
    what: str,
) -> tuple[object | None, AdmissionRow | None]:
    """Read one normalized endpoint result and fail closed on transport errors."""
    try:
        result = public_read(query)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return None, error_row(row_name, f"{what} failed: {exc}", remediation)
    error = getattr(result, "error", "")
    if error:
        return None, error_row(row_name, f"{what} failed: {error}", remediation)
    return getattr(result, "data", None), None


def parse_iso_timestamp(value: object) -> datetime | None:
    """Parse one GitHub ISO-8601 stamp to an aware UTC datetime, or ``None``.

    Shared with release_status_gate so every "which run is newest" decision is
    made on parsed instants rather than on lexical order, which silently
    misorders the moment an offset-bearing stamp appears next to a ``Z`` one.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _summarize(items: Sequence[str]) -> str:
    shown = "; ".join(items[:MAX_LISTED_ITEMS])
    remaining = len(items) - MAX_LISTED_ITEMS
    return f"{shown} (+{remaining} more)" if remaining > 0 else shown


# ── Aggregate required check ──────────────────────────────────────────────────


def check_aggregate_required_check(
    candidate_sha: str | None,
    repo: str,
    public_read: Callable[[object], object],
    *,
    check_name: str = AGGREGATE_REQUIRED_CHECK,
) -> AdmissionRow:
    """Require the newest ``check_name`` check-run on the exact candidate SHA to be green.

    Only the newest completed run counts, which matches how GitHub resolves a
    required check. An older green run therefore cannot mask a newer failed,
    cancelled, or skipped one, and a still-running run blocks instead of passing.
    Recency is decided on parsed instants; when several completed runs exist and
    any one of them cannot be dated, the predicate errors rather than guessing.
    """
    row_name = "aggregate_required_check"
    normalized, sha_row = normalize_expected_sha(candidate_sha)
    if normalized is None:
        detail = (
            "candidate SHA is malformed"
            if sha_row is not None
            else "candidate SHA is required before checking the aggregate release check"
        )
        return fail_row(row_name, detail, REMEDIATE_EXPECT_SHA)

    public = _load_public_read()
    try:
        query = public.check_runs(repo, normalized, check_name, MAX_CHECK_RUN_PAGE)
    except ValueError as exc:
        return error_row(row_name, str(exc), REMEDIATE_CHECK)
    data, error = _public_data(
        public_read,
        query,
        row_name=row_name,
        remediation=REMEDIATE_CHECK,
        what=f"check-runs lookup for {normalized}",
    )
    if error is not None:
        return error
    if not isinstance(data, dict):
        return error_row(row_name, "unexpected check-runs response shape", REMEDIATE_CHECK)
    runs = data.get("check_runs")
    if not isinstance(runs, list):
        return error_row(
            row_name, "check-runs response did not include a check_runs list", REMEDIATE_CHECK
        )
    total = data.get("total_count")
    if isinstance(total, int) and total > len(runs):
        return error_row(
            row_name,
            f"check-runs response is paginated ({total} total, {len(runs)} returned); "
            "the newest run cannot be identified",
            REMEDIATE_CHECK,
        )

    matching = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("name") == check_name
        and str(run.get("head_sha", "")).lower() == normalized
    ]
    if not matching:
        return fail_row(
            row_name, f"no {check_name!r} check-run found for {normalized}", REMEDIATE_CHECK
        )
    pending = [run for run in matching if run.get("status") != "completed"]
    if pending:
        state = str(pending[0].get("status", "unknown"))
        return fail_row(
            row_name,
            f"{check_name!r} for {normalized} is not completed (status={state!r})",
            REMEDIATE_CHECK,
        )

    # Order by *parsed* instants. An undatable run must never be given a
    # substitute position: sorting it oldest is what lets an older green run
    # answer for a newer red one whose stamps GitHub returned malformed.
    stamped = [
        (
            parse_iso_timestamp(run.get("completed_at"))
            or parse_iso_timestamp(run.get("started_at")),
            run,
        )
        for run in matching
    ]
    datable = [(stamp, run) for stamp, run in stamped if stamp is not None]
    if len(stamped) > 1 and len(datable) != len(stamped):
        # More than one completed run and at least one cannot be placed in time:
        # there is no defensible newest run, so fail closed instead of letting a
        # substitute timestamp or list position decide. A single run needs no
        # ordering and still counts.
        return error_row(
            row_name,
            f"{len(stamped) - len(datable)} of {len(stamped)} completed {check_name!r} check-runs "
            f"for {normalized} have no parseable completed_at or started_at; the newest run "
            "cannot be identified",
            REMEDIATE_CHECK,
        )

    newest = max(datable, key=lambda item: item[0])[1] if datable else matching[0]
    conclusion = str(newest.get("conclusion", "unknown"))
    if conclusion != "success":
        return fail_row(
            row_name,
            f"newest {check_name!r} check-run for {normalized} concluded {conclusion!r}",
            REMEDIATE_CHECK,
        )
    return ok_row(row_name, f"{check_name!r} is successful for exact candidate SHA {normalized}")


# ── Scheduled dependency-audit freshness ──────────────────────────────────────


def check_dependency_audit_freshness(
    repo: str,
    public_read: Callable[[object], object],
    *,
    max_age_hours: int = DEFAULT_AUDIT_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> AdmissionRow:
    """Require a recent successful scheduled or dispatched Dependency Audit run."""
    row_name = "dependency_audit_freshness"
    public = _load_public_read()
    try:
        query = public.workflow_runs(repo, DEPENDENCY_AUDIT_WORKFLOW, MAX_WORKFLOW_RUN_LIST)
    except ValueError as exc:
        return error_row(row_name, str(exc), REMEDIATE_AUDIT)
    data, error = _public_data(
        public_read,
        query,
        row_name=row_name,
        remediation=REMEDIATE_AUDIT,
        what=f"public workflow-runs lookup for {DEPENDENCY_AUDIT_WORKFLOW!r}",
    )
    if error is not None:
        return error
    if not isinstance(data, list):
        return error_row(
            row_name, "unexpected dependency-audit workflow response shape", REMEDIATE_AUDIT
        )

    # Sort by parsed timestamp instead of trusting the order gh happens to return.
    eligible: list[tuple[datetime, dict[str, object]]] = []
    undatable = 0
    for run in data:
        if not isinstance(run, dict):
            continue
        if run.get("event") not in {"schedule", "workflow_dispatch"}:
            continue
        if run.get("status") != "completed":
            continue
        stamp = parse_iso_timestamp(run.get("updatedAt")) or parse_iso_timestamp(
            run.get("createdAt")
        )
        if stamp is None:
            undatable += 1
            continue
        eligible.append((stamp, run))
    if undatable:
        # Same rule as the aggregate check-run predicate: an undatable run cannot
        # be compared against the ones that can be dated, so dropping it would let
        # an older datable success answer for a newer undatable failure. Fail
        # closed on the whole lookup rather than silently shrinking the set.
        return error_row(
            row_name,
            f"{undatable} of {undatable + len(eligible)} completed dependency-audit runs have "
            "no parseable timestamp; the latest run cannot be identified",
            REMEDIATE_AUDIT,
        )
    if not eligible:
        return fail_row(
            row_name,
            f"no completed scheduled or dispatched {DEPENDENCY_AUDIT_WORKFLOW!r} run found",
            REMEDIATE_AUDIT,
        )

    timestamp, latest = max(eligible, key=lambda item: item[0])
    conclusion = latest.get("conclusion")
    if conclusion != "success":
        return fail_row(
            row_name,
            f"latest dependency-audit run concluded {str(conclusion)!r}",
            REMEDIATE_AUDIT,
        )

    age = (now or datetime.now(UTC)).astimezone(UTC) - timestamp
    if age < -AUDIT_FUTURE_SKEW:
        return error_row(
            row_name,
            "latest dependency-audit run is stamped in the future; the evidence clock "
            "cannot be trusted",
            REMEDIATE_AUDIT,
        )
    age_hours = int(max(age, timedelta(0)).total_seconds() // 3600)
    if age > timedelta(hours=max_age_hours):
        return fail_row(
            row_name,
            f"latest successful dependency-audit run is stale ({age_hours}h old; "
            f"limit {max_age_hours}h)",
            REMEDIATE_AUDIT,
        )
    return ok_row(row_name, f"latest dependency-audit run succeeded {age_hours}h ago")


# ── Public ref protection ─────────────────────────────────────────────────────


def _rule_types(rules: object) -> set[str]:
    if not isinstance(rules, list):
        return set()
    return {
        rule["type"]
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("type"), str)
    }


def _required_check_contexts(rules: object) -> set[str]:
    contexts: set[str] = set()
    if not isinstance(rules, list):
        return contexts
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            continue
        checks = parameters.get("required_status_checks")
        if not isinstance(checks, list):
            continue
        for check in checks:
            if isinstance(check, dict) and isinstance(check.get("context"), str):
                contexts.add(check["context"])
    return contexts


def check_main_branch_rules(
    repo: str,
    branch: str,
    public_read: Callable[[object], object],
    *,
    check_name: str = AGGREGATE_REQUIRED_CHECK,
) -> AdmissionRow:
    """Report the effective repository rules protecting the public release branch.

    Uses the fixed public branch-rules query, which returns the rules that
    actually apply to the ref without credentials.
    """
    row_name = "public_main_protection"
    public = _load_public_read()
    try:
        query = public.branch_rules(repo, branch)
    except ValueError as exc:
        return error_row(row_name, str(exc), REMEDIATE_MAIN_RULESET)
    data, error = _public_data(
        public_read,
        query,
        row_name=row_name,
        remediation=REMEDIATE_MAIN_RULESET,
        what=f"branch rules lookup for {branch!r}",
    )
    if error is not None:
        return error
    if not isinstance(data, list):
        return error_row(row_name, "unexpected branch rules response shape", REMEDIATE_MAIN_RULESET)

    present = _rule_types(data)
    contexts = _required_check_contexts(data)
    missing = [rule for rule in MAIN_BRANCH_REQUIRED_RULE_TYPES if rule not in present]
    if check_name not in contexts:
        missing.append(f"{check_name} required check")
    if missing:
        return fail_row(
            row_name,
            f"public {branch} is missing rules: {', '.join(sorted(missing))}",
            REMEDIATE_MAIN_RULESET,
        )
    return ok_row(
        row_name,
        f"public {branch} rejects force-push and deletion and requires {check_name}",
    )


def check_tag_ruleset(
    repo: str,
    public_read: Callable[[object], object],
) -> AdmissionRow:
    """Report the public ``refs/tags/v*`` ruleset restricting create/update/delete.

    The ruleset *list* endpoint returns summaries without ``conditions`` or
    ``rules``, so each candidate ruleset is read back by id. Any lookup failure
    is an error row, never a silent pass.
    """
    row_name = "public_v_tag_ruleset"
    public = _load_public_read()
    try:
        list_query = public.rulesets(repo, RULESET_LIST_PAGE_SIZE)
    except ValueError as exc:
        return error_row(row_name, str(exc), REMEDIATE_RULESET_SCOPE)
    summaries, error = _public_data(
        public_read,
        list_query,
        row_name=row_name,
        remediation=REMEDIATE_RULESET_SCOPE,
        what="repository ruleset list",
    )
    if error is not None:
        return error
    if not isinstance(summaries, list):
        return error_row(row_name, "unexpected ruleset list response shape", REMEDIATE_TAG_RULESET)

    # The extra requested entry is the overflow signal: seeing more than the
    # budget means a later page exists that this bounded lookup will not read, so
    # "no ruleset covers refs/tags/v*" would be an unproven claim.
    if len(summaries) > MAX_RULESET_DETAIL_LOOKUPS:
        return error_row(
            row_name,
            f"{len(summaries)}+ rulesets exceed the bounded lookup budget of "
            f"{MAX_RULESET_DETAIL_LOOKUPS}; the {TAG_RULESET_REF} ruleset cannot be ruled in or "
            "out from a truncated page",
            REMEDIATE_TAG_RULESET,
        )

    ruleset_ids = [
        item["id"]
        for item in summaries
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    ]
    if not ruleset_ids:
        return fail_row(
            row_name, f"no repository ruleset covers {TAG_RULESET_REF}", REMEDIATE_TAG_RULESET
        )

    reasons: list[str] = []
    for ruleset_id in ruleset_ids:
        detail, detail_error = _public_data(
            public_read,
            public.ruleset(repo, ruleset_id),
            row_name=row_name,
            remediation=REMEDIATE_RULESET_SCOPE,
            what=f"ruleset {ruleset_id} lookup",
        )
        if detail_error is not None:
            return detail_error
        if not isinstance(detail, dict):
            return error_row(
                row_name, f"unexpected ruleset {ruleset_id} response shape", REMEDIATE_TAG_RULESET
            )
        if detail.get("target") != TAG_RULESET_TARGET:
            continue
        conditions = detail.get("conditions")
        ref_name = conditions.get("ref_name") if isinstance(conditions, dict) else None
        include = ref_name.get("include") if isinstance(ref_name, dict) else None
        includes_tags = isinstance(include, list) and TAG_RULESET_REF in {
            str(item) for item in include
        }
        if not includes_tags:
            continue
        name = str(detail.get("name", ruleset_id))
        if detail.get("enforcement") != RULESET_ACTIVE_ENFORCEMENT:
            reasons.append(f"{name}: enforcement is {str(detail.get('enforcement'))!r}")
            continue
        missing = sorted(set(TAG_RULESET_REQUIRED_RULE_TYPES) - _rule_types(detail.get("rules")))
        if missing:
            reasons.append(f"{name}: missing rule types {', '.join(missing)}")
            continue
        bypass = detail.get("bypass_actors")
        bypass_count = len(bypass) if isinstance(bypass, list) else 0
        return ok_row(
            row_name,
            f"ruleset {name!r} restricts {TAG_RULESET_REF} creation, update, and deletion "
            f"with {bypass_count} auditable break-glass bypass actor(s)",
        )

    if reasons:
        return fail_row(row_name, _summarize(reasons), REMEDIATE_TAG_RULESET)
    return fail_row(
        row_name,
        f"no active {TAG_RULESET_TARGET} ruleset includes {TAG_RULESET_REF}",
        REMEDIATE_TAG_RULESET,
    )


def check_public_ref_protection(
    repo: str,
    branch: str,
    public_read: Callable[[object], object],
    *,
    check_name: str = AGGREGATE_REQUIRED_CHECK,
) -> list[AdmissionRow]:
    """Return exactly one row per protected-ref predicate, in a stable order.

    Each predicate is independent: a failure in one never removes the other row,
    so a caller that treats these names as required surfaces can never lose one.
    """
    return [
        check_main_branch_rules(repo, branch, public_read, check_name=check_name),
        check_tag_ruleset(repo, public_read),
    ]


# ── Public orphan tags ────────────────────────────────────────────────────────


def list_public_version_tags(
    repo: str,
    public_read: Callable[[object], object],
) -> tuple[list[str], AdmissionRow | None]:
    public = _load_public_read()
    try:
        query = public.matching_version_tags(repo)
    except ValueError as exc:
        return [], error_row("public_orphan_tags", str(exc), REMEDIATE_ORPHAN)
    data, error = _public_data(
        public_read,
        query,
        row_name="public_orphan_tags",
        remediation=REMEDIATE_ORPHAN,
        what="public matching-tag lookup",
    )
    if error is not None:
        return [], error
    if not isinstance(data, list):
        return [], error_row(
            "public_orphan_tags", "unexpected matching-tag response shape", REMEDIATE_ORPHAN
        )
    tags = {
        str(item["ref"]).removeprefix("refs/tags/")
        for item in data
        if isinstance(item, dict) and str(item.get("ref", "")).startswith("refs/tags/v")
    }
    return sorted(tags), None


def check_public_orphan_tags(
    version: str,
    repo: str,
    package: str,
    public_read: Callable[[object], object],
    *,
    require_expected_tag: bool = False,
) -> AdmissionRow:
    """Report public ``v*`` tags without a non-draft GitHub Release and PyPI identity.

    Tags listed in :data:`ACKNOWLEDGED_ORPHAN_TAGS` are reported as reviewed,
    immutable evidence and never block; every other orphan is a new regression
    and fails closed. ``require_expected_tag`` is for the post-publication status
    gate, where ``v{version}`` must already exist publicly.
    """
    row_name = "public_orphan_tags"
    tags, tag_error = list_public_version_tags(repo, public_read)
    if tag_error is not None:
        return tag_error

    public = _load_public_read()
    try:
        releases_query = public.releases(repo, MAX_RELEASE_LIST)
        pypi_query = public.pypi_metadata(package)
    except ValueError as exc:
        return error_row(row_name, str(exc), REMEDIATE_ORPHAN)
    releases_data, release_error = _public_data(
        public_read,
        releases_query,
        row_name=row_name,
        remediation=REMEDIATE_ORPHAN,
        what="public GitHub release list",
    )
    if release_error is not None:
        return release_error
    if not isinstance(releases_data, list):
        return error_row(
            row_name, "unexpected GitHub release list response shape", REMEDIATE_ORPHAN
        )
    if len(releases_data) >= MAX_RELEASE_LIST:
        return error_row(
            row_name,
            f"GitHub release list hit the {MAX_RELEASE_LIST}-entry bound; orphan evidence "
            "would be incomplete",
            REMEDIATE_ORPHAN,
        )
    releases = {
        item["tagName"]: item
        for item in releases_data
        if isinstance(item, dict) and isinstance(item.get("tagName"), str)
    }

    pypi_data, pypi_error = _public_data(
        public_read,
        pypi_query,
        row_name=row_name,
        remediation=REMEDIATE_ORPHAN,
        what="public PyPI metadata lookup",
    )
    if pypi_error is not None:
        return pypi_error
    if not isinstance(pypi_data, dict) or not isinstance(pypi_data.get("releases"), dict):
        return error_row(
            row_name,
            "unexpected PyPI JSON response shape while checking public tags",
            REMEDIATE_ORPHAN,
        )
    pypi_releases: dict[str, object] = pypi_data["releases"]

    blocking: list[str] = []
    acknowledged: list[str] = []
    for tag in tags:
        problems: list[str] = []
        release = releases.get(tag)
        if release is None:
            problems.append("no GitHub Release")
        elif release.get("isDraft") is True:
            problems.append("GitHub Release is a draft")
        files = pypi_releases.get(tag.removeprefix("v"))
        if not isinstance(files, list) or not files:
            problems.append(f"no PyPI distribution for {package}=={tag.removeprefix('v')}")
        if not problems:
            continue
        if tag in ACKNOWLEDGED_ORPHAN_TAGS:
            acknowledged.append(f"{tag} ({', '.join(problems)})")
        else:
            blocking.append(f"{tag}: {', '.join(problems)}")

    expected_tag = f"v{version}"
    if require_expected_tag and expected_tag not in tags:
        blocking.append(f"{expected_tag}: expected public tag not found")

    evidence = (
        f" acknowledged immutable orphan evidence: {_summarize(acknowledged)}"
        if acknowledged
        else ""
    )
    if blocking:
        return fail_row(
            row_name, f"orphan public tags: {_summarize(blocking)}.{evidence}", REMEDIATE_ORPHAN
        )
    return ok_row(
        row_name,
        f"{len(tags)} public v* tags have a non-draft GitHub Release and PyPI identity, "
        f"or are acknowledged evidence.{evidence}",
    )
