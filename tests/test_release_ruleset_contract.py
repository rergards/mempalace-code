"""Contract tests for the public release-admission ruleset predicates.

The contract is evaluated against fixture GitHub API payloads shaped like the
real endpoints, not asserted by grepping prose. The documentation check is
delegated to the drift guard so the doc, the code constants, and these tests all
read the same source of truth.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parent.parent
RULESET_DOC = ROOT / "docs" / "release-admission-rulesets.md"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ADMISSION = _load("release_admission_checks", "scripts/release_admission_checks.py")
DRIFT_GUARD = _load("docs_drift_guard", "scripts/docs_drift_guard.py")
ADMISSION._load_public_read().PUBLIC_REPOSITORY = "acme/tool"


# ── Fixture payloads ──────────────────────────────────────────────────────────


def _branch_rules(rule_types: list[str], contexts: list[str]) -> list[dict]:
    """Shape of GET /repos/{repo}/rules/branches/{branch}: effective rules."""
    rules: list[dict] = [
        {"type": rule_type} for rule_type in rule_types if rule_type != "required_status_checks"
    ]
    if "required_status_checks" in rule_types:
        rules.append(
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": context} for context in contexts]
                },
            }
        )
    return rules


def _compliant_branch_rules() -> list[dict]:
    return _branch_rules(
        list(ADMISSION.MAIN_BRANCH_REQUIRED_RULE_TYPES),
        [ADMISSION.AGGREGATE_REQUIRED_CHECK, "some-other-check"],
    )


def _ruleset_summary(ruleset_id: int, name: str) -> dict:
    """Shape of GET /repos/{repo}/rulesets: summaries with no rules/conditions."""
    return {"id": ruleset_id, "name": name, "target": "tag", "enforcement": "active"}


def _ruleset_detail(
    ruleset_id: int = 7,
    *,
    name: str = "public-v-tags",
    target: str = "tag",
    enforcement: str = "active",
    rule_types: list[str] | None = None,
    include: list[str] | None = None,
) -> dict:
    """Shape of GET /repos/{repo}/rulesets/{id}: full rules and conditions."""
    if rule_types is None:
        rule_types = list(ADMISSION.TAG_RULESET_REQUIRED_RULE_TYPES)
    if include is None:
        include = [ADMISSION.TAG_RULESET_REF]
    return {
        "id": ruleset_id,
        "name": name,
        "target": target,
        "enforcement": enforcement,
        "conditions": {"ref_name": {"include": include, "exclude": []}},
        "rules": [{"type": rule_type} for rule_type in rule_types],
    }


def _query_path(query) -> str:
    repo = query.values[0]
    if query.endpoint == "github_branch_rules":
        return f"repos/{repo}/rules/branches/{query.values[1]}"
    if query.endpoint == "github_rulesets":
        return f"repos/{repo}/rulesets?per_page={query.values[1]}"
    if query.endpoint == "github_ruleset":
        return f"repos/{repo}/rulesets/{query.values[1]}"
    if query.endpoint == "github_check_runs":
        return f"repos/{repo}/commits/{query.values[1]}/check-runs"
    raise AssertionError(f"unexpected public query: {query.endpoint}")


def _fixture_result(response: object):
    if isinstance(response, tuple):
        code, output, error = response
        if code != 0:
            return SimpleNamespace(data=None, error=error or output or "fixture error")
        try:
            return SimpleNamespace(data=json.loads(output), error="")
        except json.JSONDecodeError as exc:
            return SimpleNamespace(data=None, error=f"unparseable JSON: {exc}")
    return SimpleNamespace(data=response, error="")


def _gh(responses: dict[str, object]):
    """Map a normalized public query to one hermetic payload fixture."""

    def public_read(query):
        path = _query_path(query)
        for prefix, response in responses.items():
            if path.startswith(prefix):
                return _fixture_result(response)
        raise AssertionError(f"unexpected public query path: {path}")

    return public_read


BRANCH_RULES_PATH = "repos/acme/tool/rules/branches/main"
RULESET_LIST_PATH = "repos/acme/tool/rulesets?"
RULESET_DETAIL_PATH = "repos/acme/tool/rulesets/"


# ── Public main branch rules ──────────────────────────────────────────────────


def test_compliant_main_branch_rules_pass():
    row = ADMISSION.check_main_branch_rules(
        "acme/tool", "main", _gh({BRANCH_RULES_PATH: _compliant_branch_rules()})
    )
    assert row.status == ADMISSION.STATUS_OK


@pytest.mark.parametrize("dropped", ADMISSION.MAIN_BRANCH_REQUIRED_RULE_TYPES)
def test_missing_main_rule_type_fails_and_names_the_rule(dropped):
    remaining = [r for r in ADMISSION.MAIN_BRANCH_REQUIRED_RULE_TYPES if r != dropped]
    row = ADMISSION.check_main_branch_rules(
        "acme/tool",
        "main",
        _gh({BRANCH_RULES_PATH: _branch_rules(remaining, [ADMISSION.AGGREGATE_REQUIRED_CHECK])}),
    )
    assert row.status == ADMISSION.STATUS_FAIL
    assert dropped in row.detail
    assert row.remediation


def test_main_rules_without_the_aggregate_check_context_fail():
    row = ADMISSION.check_main_branch_rules(
        "acme/tool",
        "main",
        _gh(
            {
                BRANCH_RULES_PATH: _branch_rules(
                    list(ADMISSION.MAIN_BRANCH_REQUIRED_RULE_TYPES), ["lint", "test"]
                )
            }
        ),
    )
    assert row.status == ADMISSION.STATUS_FAIL
    assert ADMISSION.AGGREGATE_REQUIRED_CHECK in row.detail


def test_unqueryable_branch_rules_error_instead_of_passing():
    row = ADMISSION.check_main_branch_rules(
        "acme/tool", "main", _gh({BRANCH_RULES_PATH: (1, "", "HTTP 403: Resource not accessible")})
    )
    assert row.status == ADMISSION.STATUS_ERROR
    assert row.remediation


def test_unparseable_branch_rules_error_instead_of_passing():
    row = ADMISSION.check_main_branch_rules(
        "acme/tool", "main", _gh({BRANCH_RULES_PATH: (0, "<html>rate limited</html>", "")})
    )
    assert row.status == ADMISSION.STATUS_ERROR


# ── Public v* tag ruleset ─────────────────────────────────────────────────────


def test_compliant_tag_ruleset_restricts_creation_update_and_deletion():
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh(
            {
                RULESET_LIST_PATH: [_ruleset_summary(7, "public-v-tags")],
                RULESET_DETAIL_PATH: _ruleset_detail(),
            }
        ),
    )
    assert row.status == ADMISSION.STATUS_OK
    assert "restrict refs/tags/v* creation, update, and deletion" in row.detail
    assert "bypass identity is owner-verified" in row.detail


def test_public_gate_does_not_require_or_infer_omitted_bypass_actors():
    detail = _ruleset_detail()
    assert "bypass_actors" not in detail
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh(
            {
                RULESET_LIST_PATH: [_ruleset_summary(7, "public-v-tags")],
                RULESET_DETAIL_PATH: detail,
            }
        ),
    )

    assert row.status == ADMISSION.STATUS_OK
    assert "0 auditable" not in row.detail


def test_reordered_and_aggregated_tag_rules_keep_the_same_verdict():
    summaries = [
        _ruleset_summary(9, "public-v-tag-creation"),
        _ruleset_summary(7, "public-v-tag-updates"),
        _ruleset_summary(8, "public-v-tag-deletions"),
    ]
    details = {
        7: _ruleset_detail(7, name="public-v-tag-updates", rule_types=["update"]),
        8: _ruleset_detail(
            8,
            name="public-v-tag-deletions",
            rule_types=["deletion"],
            include=["refs/tags/v1.*", ADMISSION.TAG_RULESET_REF],
        ),
        9: _ruleset_detail(9, name="public-v-tag-creation", rule_types=["creation"]),
    }

    def public_read(query):
        if query.endpoint == "github_rulesets":
            return _fixture_result(list(reversed(summaries)))
        if query.endpoint == "github_ruleset":
            return _fixture_result(details[query.values[1]])
        raise AssertionError(f"unexpected public query: {query.endpoint}")

    row = ADMISSION.check_tag_ruleset("acme/tool", public_read)

    assert row.status == ADMISSION.STATUS_OK
    assert "3 active ruleset(s)" in row.detail


def test_inactive_matching_ruleset_does_not_change_the_active_contract():
    summaries = [
        _ruleset_summary(7, "public-v-tags"),
        _ruleset_summary(8, "inactive-malformed-rules"),
    ]
    details = {
        7: _ruleset_detail(7, name="public-v-tags"),
        8: {
            **_ruleset_detail(8, name="inactive-malformed-rules", enforcement="evaluate"),
            "rules": "malformed",
        },
    }

    def public_read(query):
        if query.endpoint == "github_rulesets":
            return _fixture_result(summaries)
        if query.endpoint == "github_ruleset":
            return _fixture_result(details[query.values[1]])
        raise AssertionError(f"unexpected public query: {query.endpoint}")

    row = ADMISSION.check_tag_ruleset("acme/tool", public_read)

    assert row.status == ADMISSION.STATUS_OK


def test_ruleset_summary_without_detail_lookup_is_not_enough():
    """The list endpoint omits rules/conditions, so the detail must be fetched."""
    summary_only = _ruleset_summary(7, "public-v-tags")
    assert "rules" not in summary_only
    assert "conditions" not in summary_only

    detail_paths: list[str] = []

    def public_read(query):
        path = _query_path(query)
        if path.startswith(RULESET_LIST_PATH):
            return _fixture_result([summary_only])
        detail_paths.append(path)
        return _fixture_result(_ruleset_detail())

    row = ADMISSION.check_tag_ruleset("acme/tool", public_read)
    assert row.status == ADMISSION.STATUS_OK
    assert detail_paths == ["repos/acme/tool/rulesets/7"]


@pytest.mark.parametrize("dropped", ADMISSION.TAG_RULESET_REQUIRED_RULE_TYPES)
def test_tag_ruleset_missing_a_rule_type_fails(dropped):
    remaining = [r for r in ADMISSION.TAG_RULESET_REQUIRED_RULE_TYPES if r != dropped]
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh(
            {
                RULESET_LIST_PATH: [_ruleset_summary(7, "public-v-tags")],
                RULESET_DETAIL_PATH: _ruleset_detail(rule_types=remaining),
            }
        ),
    )
    assert row.status == ADMISSION.STATUS_FAIL
    assert dropped in row.detail


def test_evaluate_mode_tag_ruleset_fails():
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh(
            {
                RULESET_LIST_PATH: [_ruleset_summary(7, "public-v-tags")],
                RULESET_DETAIL_PATH: _ruleset_detail(enforcement="evaluate"),
            }
        ),
    )
    assert row.status == ADMISSION.STATUS_FAIL
    assert "evaluate" in row.detail


def test_ruleset_covering_another_ref_pattern_does_not_satisfy_the_contract():
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh(
            {
                RULESET_LIST_PATH: [_ruleset_summary(7, "release-candidates")],
                RULESET_DETAIL_PATH: _ruleset_detail(include=["refs/tags/rc-*"]),
            }
        ),
    )
    assert row.status == ADMISSION.STATUS_FAIL


def test_branch_targeted_ruleset_does_not_satisfy_the_tag_contract():
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh(
            {
                RULESET_LIST_PATH: [_ruleset_summary(7, "main-protection")],
                RULESET_DETAIL_PATH: _ruleset_detail(target="branch"),
            }
        ),
    )
    assert row.status == ADMISSION.STATUS_FAIL


def test_no_rulesets_at_all_fails_closed():
    row = ADMISSION.check_tag_ruleset("acme/tool", _gh({RULESET_LIST_PATH: []}))
    assert row.status == ADMISSION.STATUS_FAIL
    assert ADMISSION.TAG_RULESET_REF in row.detail


def test_ruleset_permission_error_is_an_error_row_with_a_scope_remediation():
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh({RULESET_LIST_PATH: (1, "", "HTTP 403: Must have admin rights to Repository")}),
    )
    assert row.status == ADMISSION.STATUS_ERROR
    assert "credential-free public GitHub API" in row.remediation
    assert "--repo rergards/mempalace-code --check-tag-ruleset --json" in row.remediation


def test_ruleset_doc_assigns_hosted_branch_and_tag_checks_to_credential_free_reader():
    text = RULESET_DOC.read_text(encoding="utf-8")

    assert "Hosted `.github/workflows/publish.yml`" in text
    assert "`refs/heads/main`" in text
    assert all(rule in text for rule in ADMISSION.MAIN_BRANCH_REQUIRED_RULE_TYPES)
    assert "`refs/tags/v*` ruleset" in text
    assert "credential-free public reader" in text
    assert "admission receives no GitHub token" in text
    assert "does not expose `bypass_actors`" in text
    assert "owner verifies the configured bypass actor" in text
    assert "break-glass" in text
    assert (
        "python scripts/release_preflight.py --repo rergards/mempalace-code "
        "--check-tag-ruleset --json"
    ) in text


def test_ruleset_doc_owns_the_exact_job_partial_publication_recovery():
    text = RULESET_DOC.read_text(encoding="utf-8")

    assert DRIFT_GUARD.CANONICAL_PARTIAL_PUBLICATION_RECOVERY_COMMAND in text
    assert "whole-workflow rerun" in text
    assert "Manual Release creation" in text
    assert "BOUNDED INSTRUCTION" in text


def test_ruleset_detail_error_never_degrades_into_a_pass():
    row = ADMISSION.check_tag_ruleset(
        "acme/tool",
        _gh(
            {
                RULESET_LIST_PATH: [_ruleset_summary(7, "public-v-tags")],
                RULESET_DETAIL_PATH: (1, "", "HTTP 404"),
            }
        ),
    )
    assert row.status == ADMISSION.STATUS_ERROR


def test_ruleset_detail_lookups_stay_bounded():
    many = [_ruleset_summary(i, f"ruleset-{i}") for i in range(500)]
    row = ADMISSION.check_tag_ruleset("acme/tool", _gh({RULESET_LIST_PATH: many}))
    assert row.status == ADMISSION.STATUS_ERROR
    assert "bounded lookup budget" in row.detail


def test_ruleset_list_requests_one_more_than_it_will_read_back():
    """The overflow signal only exists if the page is larger than the budget.

    Requesting exactly `MAX_RULESET_DETAIL_LOOKUPS` makes a truncated first page
    look identical to a complete result set, so the bound above would be
    unreachable and a `v*` ruleset on page 2 would be reported as absent.
    """
    requested: list[str] = []

    def public_read(query):
        requested.append(_query_path(query))
        return _fixture_result([_ruleset_summary(7, "public-v-tags")])

    ADMISSION.check_tag_ruleset("acme/tool", public_read)

    assert ADMISSION.RULESET_LIST_PAGE_SIZE > ADMISSION.MAX_RULESET_DETAIL_LOOKUPS
    assert f"per_page={ADMISSION.RULESET_LIST_PAGE_SIZE}" in requested[0]


def test_a_ruleset_list_that_fills_the_page_errors_instead_of_reporting_none_found():
    """One entry past the budget means a later page exists that is never read.

    Reporting "no ruleset covers refs/tags/v*" from a truncated page would be a
    fail row asserting something the lookup did not establish.
    """
    overflowing = [
        _ruleset_summary(i, f"ruleset-{i}") for i in range(ADMISSION.MAX_RULESET_DETAIL_LOOKUPS + 1)
    ]

    row = ADMISSION.check_tag_ruleset("acme/tool", _gh({RULESET_LIST_PATH: overflowing}))

    assert row.status == ADMISSION.STATUS_ERROR
    assert "bounded lookup budget" in row.detail
    assert ADMISSION.TAG_RULESET_REF in row.detail


def test_a_full_but_not_overflowing_ruleset_list_is_still_evaluated():
    """Exactly the budget is readable in full, so it must not error spuriously."""
    summaries = [
        _ruleset_summary(i, f"ruleset-{i}") for i in range(1, ADMISSION.MAX_RULESET_DETAIL_LOOKUPS)
    ]
    summaries.append(_ruleset_summary(9001, "public-v-tags"))

    def public_read(query):
        path = _query_path(query)
        if path.startswith(RULESET_LIST_PATH):
            return _fixture_result(summaries)
        ruleset_id = int(path.rsplit("/", 1)[1])
        if ruleset_id == 9001:
            return _fixture_result(_ruleset_detail(9001))
        return _fixture_result(_ruleset_detail(ruleset_id, target="branch"))

    row = ADMISSION.check_tag_ruleset("acme/tool", public_read)

    assert len(summaries) == ADMISSION.MAX_RULESET_DETAIL_LOOKUPS
    assert row.status == ADMISSION.STATUS_OK


# ── Both predicates are always reported ───────────────────────────────────────


def test_ref_protection_always_returns_one_row_per_predicate_even_on_failure():
    rows = ADMISSION.check_public_ref_protection(
        "acme/tool",
        "main",
        _gh(
            {
                BRANCH_RULES_PATH: (1, "", "HTTP 500"),
                RULESET_LIST_PATH: (1, "", "HTTP 403"),
            }
        ),
    )
    assert [row.name for row in rows] == ["public_main_protection", "public_v_tag_ruleset"]
    assert all(row.status == ADMISSION.STATUS_ERROR for row in rows)
    assert all(row.remediation for row in rows)


# ── Documentation is checked against the code constants ───────────────────────


def test_documented_contract_matches_the_code_constants():
    text = RULESET_DOC.read_text(encoding="utf-8")
    missing = [marker for marker in DRIFT_GUARD.release_admission_markers() if marker not in text]
    assert missing == []


def test_every_acknowledged_orphan_tag_is_documented_with_a_reason():
    text = RULESET_DOC.read_text(encoding="utf-8")
    for tag, reason in ADMISSION.ACKNOWLEDGED_ORPHAN_TAGS.items():
        assert tag in text, tag
        assert reason.strip()


def test_v1_13_2_stays_immutable_evidence_rather_than_a_repair_target():
    reason = ADMISSION.ACKNOWLEDGED_ORPHAN_TAGS["v1.13.2"]
    assert "immutable" in reason
    assert "never be moved or deleted" in reason
    assert "must never be moved or deleted" in RULESET_DOC.read_text(encoding="utf-8")


def test_each_documented_predicate_row_names_a_recovery_command():
    text = RULESET_DOC.read_text(encoding="utf-8")
    for row_name in (
        "aggregate_required_check",
        "dependency_audit_freshness",
        "public_main_protection",
        "public_v_tag_ruleset",
        "public_orphan_tags",
    ):
        assert row_name in text, row_name
    for command in (
        "fixed GitHub check-runs GET",
        "fixed GitHub effective branch-rules GET",
        "fixed GitHub ruleset list/detail GETs",
        "gh workflow run 'Dependency Audit'",
    ):
        assert command in text, command


# ── Lost-context and stale-state recovery ─────────────────────────────────────
#
# These cover the operator (or agent) who resumed with partial context: a SHA
# copied from yesterday, a candidate ref that moved under them, a check that has
# not finished, an old green run masking a new red one, or audit evidence that
# cannot be trusted. Every one of them must fail closed with a recovery command,
# never pass because the last thing anyone looked at happened to be green.

OLD_SHA = "1" * 40
NEW_SHA = "2" * 40
CHECK_RUNS_PATH = f"repos/acme/tool/commits/{OLD_SHA}/check-runs"
AUDIT_ARGS_PATH = "run"


def _check_run(
    sha: str,
    *,
    status: str = "completed",
    conclusion: str = "success",
    completed_at: str = "2026-08-16T00:00:00Z",
    started_at: str | None = None,
) -> dict:
    run = {
        "name": ADMISSION.AGGREGATE_REQUIRED_CHECK,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "completed_at": completed_at,
    }
    if started_at is not None:
        run["started_at"] = started_at
    return run


def _audit_gh(runs: list[dict] | tuple[int, str, str]):
    def public_read(query):
        assert query.endpoint == "github_workflow_runs"
        return _fixture_result(runs)

    return public_read


def test_yesterdays_sha_does_not_inherit_todays_green_check():
    """A stale SHA has no check-run of its own; today's green run must not count."""
    gh = _gh(
        {f"repos/acme/tool/commits/{OLD_SHA}/check-runs": {"check_runs": [_check_run(NEW_SHA)]}}
    )

    row = ADMISSION.check_aggregate_required_check(OLD_SHA, "acme/tool", gh)

    assert row.status == ADMISSION.STATUS_FAIL
    assert OLD_SHA in row.detail
    assert NEW_SHA not in row.detail
    assert row.remediation


def test_candidate_ref_that_moved_is_reported_as_drift_not_silently_accepted():
    row = ADMISSION.compare_sha_row(
        "candidate_ref_expected_sha",
        NEW_SHA,
        OLD_SHA,
        "candidate ref publish/main",
        ADMISSION.REMEDIATE_CANDIDATE_SHA,
    )

    assert row.status == ADMISSION.STATUS_FAIL
    assert NEW_SHA in row.detail
    assert OLD_SHA in row.detail
    assert "git fetch" in row.remediation


def test_check_still_running_blocks_instead_of_passing():
    gh = _gh(
        {
            CHECK_RUNS_PATH: {
                "check_runs": [_check_run(OLD_SHA, status="in_progress", conclusion="")]
            }
        }
    )

    row = ADMISSION.check_aggregate_required_check(OLD_SHA, "acme/tool", gh)

    assert row.status == ADMISSION.STATUS_FAIL
    assert "in_progress" in row.detail
    assert row.remediation


def test_older_green_check_run_cannot_mask_a_newer_failed_one():
    gh = _gh(
        {
            CHECK_RUNS_PATH: {
                "check_runs": [
                    _check_run(OLD_SHA, completed_at="2026-08-16T00:00:00Z"),
                    _check_run(OLD_SHA, conclusion="failure", completed_at="2026-08-16T06:00:00Z"),
                ]
            }
        }
    )

    row = ADMISSION.check_aggregate_required_check(OLD_SHA, "acme/tool", gh)

    assert row.status == ADMISSION.STATUS_FAIL
    assert "failure" in row.detail
    assert row.remediation


def test_an_undatable_newer_failure_cannot_be_sorted_under_an_older_green_run():
    """The higher-consequence twin of the status gate's unorderable-run rule.

    Both runs are completed and on the candidate SHA. The failure carries neither
    a parseable ``completed_at`` nor a parseable ``started_at``, so giving it a
    substitute instant sorts it *oldest* and hands the verdict to the older
    success — a malformed GitHub response would then admit an unproven commit
    inside publish.yml. With more than one completed run and any of them
    undatable there is no defensible newest run, so this must error.
    """
    gh = _gh(
        {
            CHECK_RUNS_PATH: {
                "check_runs": [
                    _check_run(OLD_SHA, completed_at="2026-08-16T00:00:00Z"),
                    _check_run(
                        OLD_SHA,
                        conclusion="failure",
                        completed_at="not-a-timestamp",
                        started_at="also-not-a-timestamp",
                    ),
                ]
            }
        }
    )
    # The hazard is real: neither stamp parses, so any fallback instant is invented.
    assert ADMISSION.parse_iso_timestamp("not-a-timestamp") is None
    assert ADMISSION.parse_iso_timestamp("also-not-a-timestamp") is None

    row = ADMISSION.check_aggregate_required_check(OLD_SHA, "acme/tool", gh)

    assert row.status == ADMISSION.STATUS_ERROR, row.detail
    assert "newest run cannot be identified" in row.detail
    assert row.remediation


def test_a_single_undatable_check_run_is_still_usable_evidence():
    """One run needs no ordering, so a missing stamp must not manufacture an error.

    Pinned to a *failing* run so the fallback cannot pass this test vacuously.
    """
    gh = _gh(
        {
            CHECK_RUNS_PATH: {
                "check_runs": [
                    _check_run(OLD_SHA, conclusion="failure", completed_at="not-a-timestamp")
                ]
            }
        }
    )

    row = ADMISSION.check_aggregate_required_check(OLD_SHA, "acme/tool", gh)

    assert row.status == ADMISSION.STATUS_FAIL, row.detail
    assert "failure" in row.detail


def test_paginated_check_runs_error_rather_than_trusting_the_first_page():
    gh = _gh(
        {
            CHECK_RUNS_PATH: {
                "total_count": 250,
                "check_runs": [_check_run(OLD_SHA)],
            }
        }
    )

    row = ADMISSION.check_aggregate_required_check(OLD_SHA, "acme/tool", gh)

    assert row.status == ADMISSION.STATUS_ERROR
    assert "paginated" in row.detail


def test_missing_candidate_sha_fails_closed_with_the_expect_sha_recovery():
    row = ADMISSION.check_aggregate_required_check(None, "acme/tool", _gh({}))

    assert row.status == ADMISSION.STATUS_FAIL
    assert "--expect-sha" in row.remediation


@pytest.mark.parametrize(
    ("constant", "command"),
    [
        ("REMEDIATE_EXPECT_SHA", "python scripts/release_preflight.py"),
        ("REMEDIATE_HEAD_SHA", "git checkout"),
        ("REMEDIATE_TAG_SHA", "git rev-parse"),
        ("REMEDIATE_CANDIDATE_SHA", "git fetch"),
        ("REMEDIATE_CHECK", "gh run rerun"),
        ("REMEDIATE_AUDIT", "gh workflow run"),
        ("REMEDIATE_MAIN_RULESET", ADMISSION.RULESET_DOC),
        ("REMEDIATE_TAG_RULESET", ADMISSION.RULESET_DOC),
        ("REMEDIATE_RULESET_SCOPE", ADMISSION.RULESET_DOC),
        ("REMEDIATE_ORPHAN", ADMISSION.RULESET_DOC),
    ],
)
def test_every_remediation_names_one_runnable_next_step(constant, command):
    """A failed predicate must hand back a command, not an aspiration."""
    text = getattr(ADMISSION, constant)
    assert command in text, text


# ── A Tests dispatch is rejected wherever it could be written ─────────────────
#
# `gh workflow run <Tests>` would destroy the candidate it claims to repair: it
# takes a branch rather than a SHA, and a dispatched run skips
# `dependency-upgrade-gate` and `gitleaks-changed-range`, so it publishes a newer
# *failing* release-required on the candidate SHA. Once that lands, the
# newest-run rule makes a green candidate permanently un-admittable.
#
# The detector below matches the *command shape*, not one literal string, so
# quoting, casing, spacing, flag order, and the workflow-file spelling are all
# covered. It stops at a newline, backtick, or table pipe so it reads one command
# at a time out of Markdown prose rather than grepping the prose itself.

_GH_WORKFLOW_RUN_RE = re.compile(r"gh\s+workflow\s+run\b[^\n`|]*", re.IGNORECASE)

# The two spellings gh accepts for this workflow: its `name:` and its file name.
TESTS_WORKFLOW_ALIASES = (ADMISSION.TESTS_WORKFLOW.lower(), CI_WORKFLOW.name.lower())

# Every public Markdown surface an operator or agent could read a recovery out of.
PUBLIC_DOCS = sorted((ROOT / "docs").rglob("*.md")) + sorted(ROOT.glob("*.md"))


def _tests_dispatch_commands(text: str) -> list[str]:
    """Return every ``gh workflow run`` invocation that would dispatch **Tests**."""
    found: list[str] = []
    for match in _GH_WORKFLOW_RUN_RE.finditer(text):
        command = match.group(0)
        normalized = command.lower().replace('"', "").replace("'", "")
        if any(alias in normalized for alias in TESTS_WORKFLOW_ALIASES):
            found.append(command.strip())
    return found


def test_the_tests_workflow_aliases_name_the_real_workflow():
    """The aliases only mean anything if ci.yml really is the Tests workflow."""
    assert f"name: {ADMISSION.TESTS_WORKFLOW}\n" in CI_WORKFLOW.read_text(encoding="utf-8")
    assert TESTS_WORKFLOW_ALIASES == ("tests", "ci.yml")


@pytest.mark.parametrize(
    "harmful",
    [
        "gh workflow run Tests",
        "gh workflow run 'Tests'",
        'gh workflow run "Tests" --ref main',
        "gh workflow run --repo rergards/mempalace-code Tests",
        "gh workflow run -R rergards/mempalace-code 'Tests' --ref main",
        "gh workflow run ci.yml",
        "GH WORKFLOW RUN TESTS",
        "gh  workflow   run   'Tests'",
        "recover with `gh workflow run tests` and wait",
        "| `aggregate_required_check` | … | `gh workflow run Tests` |",
    ],
)
def test_the_dispatch_detector_catches_every_harmful_spelling(harmful):
    """A detector that only matched the one spelling already in the doc is vacuous."""
    assert _tests_dispatch_commands(harmful), harmful


@pytest.mark.parametrize(
    "benign",
    [
        ADMISSION.REMEDIATE_CHECK,
        ADMISSION.REMEDIATE_AUDIT,
        "gh workflow run 'Dependency Audit' --repo rergards/mempalace-code",
        "gh run list --repo rergards/mempalace-code --workflow Tests --json headSha,event",
        "gh run rerun <run-id> --repo rergards/mempalace-code --failed",
        "never dispatch a workflow_dispatch run for the Tests workflow",
    ],
)
def test_the_dispatch_detector_allows_the_supported_commands(benign):
    """`Dependency Audit` does accept a dispatch; only the Tests spelling is forbidden."""
    assert _tests_dispatch_commands(benign) == []


def test_no_remediation_constant_dispatches_the_tests_workflow():
    offenders = {
        name: _tests_dispatch_commands(getattr(ADMISSION, name))
        for name in dir(ADMISSION)
        if name.startswith("REMEDIATE_") and _tests_dispatch_commands(getattr(ADMISSION, name))
    }
    assert offenders == {}
    assert "gh run rerun" in ADMISSION.REMEDIATE_CHECK


def test_no_public_doc_recommends_dispatching_the_tests_workflow():
    """One doc and one spelling is not enough: an agent reads whichever doc it opens."""
    offenders = {
        str(doc.relative_to(ROOT)): commands
        for doc in PUBLIC_DOCS
        if (commands := _tests_dispatch_commands(doc.read_text(encoding="utf-8")))
    }
    assert offenders == {}
    # The scan must actually cover the docs that carry release recovery text.
    assert RULESET_DOC in PUBLIC_DOCS
    assert ROOT / "docs" / "RELEASING.md" in PUBLIC_DOCS
    assert ROOT / "docs" / "DEPENDENCY_UPGRADE_GATE.md" in PUBLIC_DOCS


def test_check_remediation_lets_an_operator_see_the_triggering_event():
    """Without `event` in the field list the push/dispatch distinction is invisible."""
    match = re.search(r"gh run list [^.]*--json (\S+)", ADMISSION.REMEDIATE_CHECK)
    assert match is not None, ADMISSION.REMEDIATE_CHECK
    fields = set(match.group(1).rstrip(",").split(","))
    assert {"headSha", "event", "databaseId", "conclusion"} <= fields, fields


def test_check_remediation_never_recommends_rerunning_a_dispatch_shaped_run():
    """`gh run rerun` replays the original event, so re-running a dispatch stays red.

    A dispatch-shaped run is therefore not a repairable run. The remediation has
    to scope the rerun to `push`/`pull_request` and give the dispatch-only case
    the *same* single bounded exit as the no-run-at-all case, rather than leaving
    it to be improvised.
    """
    text = ADMISSION.REMEDIATE_CHECK
    assert "push or pull_request" in text
    assert "workflow_dispatch" in text
    # Exactly one rerun instruction and one fallback: no menu of options to pick
    # the destructive item from.
    assert text.count("gh run rerun") == 1
    assert text.index("gh run rerun") < text.index("workflow_dispatch")


def _gh_invocations(text: str) -> list[str]:
    """Split a remediation into one fragment per ``gh`` command it names."""
    return [part for part in re.split(r"(?=\bgh\s)", text) if re.match(r"\bgh\s", part)]


def test_every_gh_remediation_binds_the_public_repository_explicitly():
    """An operator shell defaulted to a fork must not be able to answer these.

    `gh repo set-default` is ambient state the release path does not control; a
    bare `gh run list` in this checkout returns the upstream fork's runs.
    """
    unbound = {
        name: fragment
        for name in dir(ADMISSION)
        if name.startswith("REMEDIATE_")
        for fragment in _gh_invocations(getattr(ADMISSION, name))
        if f"--repo {ADMISSION.DEFAULT_REPO}" not in fragment
    }
    assert unbound == {}
    # Guard against the scan passing because it found no gh commands at all.
    assert _gh_invocations(ADMISSION.REMEDIATE_CHECK)
    assert _gh_invocations(ADMISSION.REMEDIATE_AUDIT)


def test_orphan_remediation_puts_repair_before_acknowledgement():
    """Acknowledging a tag that is merely still publishing would suppress a real race."""
    text = ADMISSION.REMEDIATE_ORPHAN
    assert text.index("Create the missing") < text.index("ACKNOWLEDGED_ORPHAN_TAGS")
    assert "permanent" in text


def test_unqueryable_dependency_audit_is_an_error_not_a_pass():
    row = ADMISSION.check_dependency_audit_freshness(
        "acme/tool", _audit_gh((1, "", "HTTP 403: Resource not accessible"))
    )

    assert row.status == ADMISSION.STATUS_ERROR
    assert row.remediation
    assert "403" in row.detail


def test_future_stamped_dependency_audit_is_untrusted_evidence():
    """A clock-skewed or forged future timestamp must not read as maximally fresh."""
    row = ADMISSION.check_dependency_audit_freshness(
        "acme/tool",
        _audit_gh(
            [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "event": "schedule",
                    "updatedAt": "2026-08-20T00:00:00Z",
                }
            ]
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert row.status == ADMISSION.STATUS_ERROR
    assert "future" in row.detail


def test_undatable_dependency_audit_runs_error_instead_of_passing():
    row = ADMISSION.check_dependency_audit_freshness(
        "acme/tool",
        _audit_gh(
            [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "event": "schedule",
                    "updatedAt": "not-a-timestamp",
                }
            ]
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert row.status == ADMISSION.STATUS_ERROR
    assert "timestamp" in row.detail


def test_an_undatable_audit_run_is_not_dropped_in_favour_of_an_older_datable_success():
    """Dropping the undatable run would let a stale success answer for it.

    The success below is fresh enough to pass on its own, so the only thing that
    can block here is refusing to shrink the candidate set: the second run is a
    completed dispatched audit whose outcome cannot be placed in time relative to
    it, and skipping it would report freshness the lookup never established.
    """
    row = ADMISSION.check_dependency_audit_freshness(
        "acme/tool",
        _audit_gh(
            [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "event": "schedule",
                    "updatedAt": "2026-08-15T00:00:00Z",
                },
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "event": "workflow_dispatch",
                    "updatedAt": "not-a-timestamp",
                    "createdAt": "also-not-a-timestamp",
                },
            ]
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert row.status == ADMISSION.STATUS_ERROR, row.detail
    assert "latest run cannot be identified" in row.detail
    assert row.remediation


def test_a_fully_datable_audit_history_still_passes():
    """The rule above must block only on undatable evidence, not on every history."""
    row = ADMISSION.check_dependency_audit_freshness(
        "acme/tool",
        _audit_gh(
            [
                {
                    "status": "completed",
                    "conclusion": "failure",
                    "event": "workflow_dispatch",
                    "updatedAt": "2026-08-10T00:00:00Z",
                },
                {
                    "status": "completed",
                    "conclusion": "success",
                    "event": "schedule",
                    "updatedAt": "2026-08-15T00:00:00Z",
                },
            ]
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert row.status == ADMISSION.STATUS_OK, row.detail


def test_manual_push_event_audit_run_does_not_satisfy_the_scheduled_requirement():
    row = ADMISSION.check_dependency_audit_freshness(
        "acme/tool",
        _audit_gh(
            [
                {
                    "status": "completed",
                    "conclusion": "success",
                    "event": "push",
                    "updatedAt": "2026-08-16T00:00:00Z",
                }
            ]
        ),
        now=datetime(2026, 8, 16, tzinfo=UTC),
    )

    assert row.status == ADMISSION.STATUS_FAIL
    assert "no completed scheduled" in row.detail


def test_live_diagnostics_are_truncated_so_a_gate_log_cannot_echo_an_api_dump():
    noisy = "x" * (ADMISSION.MAX_DETAIL_CHARS * 3)
    row = ADMISSION.check_dependency_audit_freshness("acme/tool", _audit_gh((1, "", noisy)))

    assert row.status == ADMISSION.STATUS_ERROR
    assert len(row.detail) <= ADMISSION.MAX_DETAIL_CHARS + len("… (truncated)")
    assert row.detail.endswith("… (truncated)")
