"""Tests for local, non-mutating release preflight checks."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load_module("release_preflight", ROOT / "scripts" / "release_preflight.py")

SHA = "a" * 40


def _root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    return tmp_path


def test_clean_tree_owner_accepts_clean_checkout(tmp_path: Path):
    calls = []

    def run(command, root):
        calls.append((command, root))
        return 0, ""

    row = preflight.check_clean_tree(tmp_path, run)

    assert row == {
        "name": "clean_tree",
        "status": "ok",
        "detail": "worktree is clean",
    }
    assert calls == [(["git", "status", "--porcelain"], tmp_path)]


def test_clean_tree_owner_rejects_dirty_checkout_with_remediation(tmp_path: Path):
    row = preflight.check_clean_tree(
        tmp_path, lambda command, root: (0, " M scripts/release_preflight.py")
    )

    assert row["status"] == "fail"
    assert row["detail"] == " M scripts/release_preflight.py"
    assert "Commit or discard" in row["remediation"]


def test_clean_tree_owner_fails_closed_when_git_probe_fails(tmp_path: Path):
    row = preflight.check_clean_tree(tmp_path, lambda command, root: (128, "fatal detail"))

    assert row["status"] == "fail"
    assert row["detail"] == "git status failed"
    assert "fatal detail" not in row["detail"]


def test_evaluate_accepts_matching_tag_and_passing_local_gates(tmp_path: Path):
    root = _root(tmp_path)

    def run(command, _root):
        if command[:2] == ["git", "status"]:
            return 0, ""
        return 0, "passed"

    version, checks = preflight.evaluate(root, tag="v1.2.3", require_clean=True, run=run)

    assert version == "1.2.3"
    assert [check["name"] for check in checks] == [
        "tag_version",
        "tag_identity",
        "docs_drift",
        "public_safety",
        "upstream_comparison",
        "clean_tree",
    ]
    assert all(check["status"] == "ok" for check in checks)


def test_evaluate_default_keeps_upstream_comparison_static_and_network_free(tmp_path: Path):
    root = _root(tmp_path)
    commands: list[list[str]] = []

    def run(command, _root):
        commands.append(command)
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        return 0, "passed"

    _, checks = preflight.evaluate(root, tag=None, require_clean=False, run=run)

    assert all(check["status"] == "ok" for check in checks)
    assert ["scripts/upstream_comparison_guard.py", "--check-live"] not in commands
    assert [
        preflight.sys.executable,
        "scripts/upstream_comparison_guard.py",
    ] in commands


def test_default_preflight_executes_static_upstream_guard_successfully():
    upstream_command = [preflight.sys.executable, "scripts/upstream_comparison_guard.py"]

    def run(command, root):
        if command == upstream_command:
            return preflight._run(command, root)
        if command[:2] == ["git", "rev-parse"]:
            return 1, "absent"
        return 0, "passed"

    _, checks = preflight.evaluate(ROOT, tag=None, require_clean=False, run=run)

    upstream = next(check for check in checks if check["name"] == "upstream_comparison")
    assert upstream["status"] == "ok"
    assert "manifest_inventory_commits=10" in upstream["detail"]


def test_default_preflight_propagates_static_inventory_failure(tmp_path: Path):
    root = _root(tmp_path)
    upstream_command = [preflight.sys.executable, "scripts/upstream_comparison_guard.py"]

    def run(command, _root):
        if command == upstream_command:
            return 1, "commit-inventory: trust-anchor digest mismatch"
        if command[:2] == ["git", "rev-parse"]:
            return 1, "absent"
        return 0, "passed"

    _, checks = preflight.evaluate(root, tag=None, require_clean=False, run=run)

    upstream = next(check for check in checks if check["name"] == "upstream_comparison")
    assert upstream["status"] == "fail"
    assert upstream["detail"] == "commit-inventory: trust-anchor digest mismatch"
    assert upstream["remediation"] == (
        f"Run {' '.join(upstream_command)} locally and fix the reported release blocker."
    )


def test_evaluate_opt_in_runs_gitleaks_history_gate_and_surfaces_failure(tmp_path: Path):
    root = _root(tmp_path)
    commands: list[list[str]] = []

    def run(command, _root):
        commands.append(command)
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        if command == [preflight.sys.executable, "scripts/gitleaks_scan.py", "full-history"]:
            return 1, "gitleaks-scan: FAIL - full-history scan requires fetch-depth 0"
        return 0, "passed"

    _, checks = preflight.evaluate(
        root, tag=None, require_clean=False, with_gitleaks_history=True, run=run
    )

    assert [preflight.sys.executable, "scripts/gitleaks_scan.py", "full-history"] in commands
    gitleaks_check = next(check for check in checks if check["name"] == "gitleaks_history")
    assert gitleaks_check["status"] == "fail"
    assert gitleaks_check["detail"] == (
        "gitleaks-scan: FAIL - full-history scan requires fetch-depth 0"
    )
    assert gitleaks_check["remediation"]


def test_evaluate_default_does_not_require_history_scanning_it_cannot_perform(tmp_path: Path):
    """The default must stay runnable on a shallow checkout with no scanner.

    ci.yml's package job runs preflight against a shallow checkout that never
    installs Gitleaks, and publish.yml has already shallow-fetched origin/main by
    the time preflight runs there. Release admission for full-history scanning is
    the explicit publish.yml step, so the scan is opt-in here rather than a check
    that fails for reasons unrelated to the tree being released.
    """
    root = _root(tmp_path)
    commands: list[list[str]] = []

    def run(command, _root):
        commands.append(command)
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        return 0, "passed"

    _, checks = preflight.evaluate(root, tag=None, require_clean=False, run=run)

    assert [preflight.sys.executable, "scripts/gitleaks_scan.py", "full-history"] not in commands
    assert "gitleaks_history" not in {check["name"] for check in checks}
    assert all(check["status"] == "ok" for check in checks)


def test_evaluate_opt_in_runs_shared_live_upstream_guard_and_surfaces_failure(tmp_path: Path):
    root = _root(tmp_path)
    commands: list[list[str]] = []

    def run(command, _root):
        commands.append(command)
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        if command[-1:] == ["--check-live"]:
            return 1, "upstream-drift: reviewed pin is stale"
        return 0, "passed"

    _, checks = preflight.evaluate(
        root, tag=None, require_clean=False, check_live_upstream=True, run=run
    )

    assert commands[-1] == [
        preflight.sys.executable,
        "scripts/upstream_comparison_guard.py",
        "--check-live",
    ]
    assert checks[-1]["name"] == "live_upstream_comparison"
    assert checks[-1]["status"] == "fail"
    assert checks[-1]["detail"] == "upstream-drift: reviewed pin is stale"
    assert checks[-1]["remediation"]


def test_evaluate_binds_expected_sha_to_head_tag_and_candidate_ref(tmp_path: Path):
    root = _root(tmp_path)
    commands: list[list[str]] = []

    def run(command, _root):
        commands.append(command)
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 0, f"{SHA}\n"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, f"{SHA}\n"
        if command == ["git", "rev-parse", "--verify", "-q", "refs/tags/v1.2.3^{commit}"]:
            return 0, f"{SHA}\n"
        if command == ["git", "rev-parse", "publish/main^{commit}"]:
            return 0, f"{SHA}\n"
        return 0, "passed"

    _, checks = preflight.evaluate(
        root,
        tag="v1.2.3",
        require_clean=False,
        expect_sha=SHA,
        candidate_ref="publish/main",
        run=run,
    )

    assert ["git", "rev-parse", "--verify", "-q", "refs/tags/v1.2.3^{commit}"] in commands
    assert ["git", "rev-parse", "publish/main^{commit}"] in commands
    for name in (
        "expected_sha_format",
        "head_expected_sha",
        "tag_expected_sha",
        "candidate_ref_expected_sha",
    ):
        row = next(check for check in checks if check["name"] == name)
        assert row["status"] == "ok", row


def test_evaluate_rejects_sha_drift_with_bounded_remediation(tmp_path: Path):
    root = _root(tmp_path)
    drift_sha = "b" * 40

    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 0, f"{SHA}\n"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, f"{SHA}\n"
        if command == ["git", "rev-parse", "--verify", "-q", "refs/tags/v1.2.3^{commit}"]:
            return 0, f"{SHA}\n"
        if command == ["git", "rev-parse", "publish/main^{commit}"]:
            return 0, f"{drift_sha}\n"
        return 0, "passed"

    _, checks = preflight.evaluate(
        root,
        tag="v1.2.3",
        require_clean=False,
        expect_sha=SHA,
        candidate_ref="publish/main",
        run=run,
    )

    candidate = next(check for check in checks if check["name"] == "candidate_ref_expected_sha")
    assert candidate["status"] == "fail"
    assert drift_sha in candidate["detail"]
    assert SHA in candidate["detail"]
    assert "review" in candidate["remediation"].lower()


def test_malformed_expect_sha_skips_live_aggregate_lookup(tmp_path: Path):
    root = _root(tmp_path)
    public_queries: list[object] = []

    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        return 0, "passed"

    def public_read(query):
        public_queries.append(query)
        return SimpleNamespace(data={}, error="")

    _, checks = preflight.evaluate(
        root,
        tag=None,
        require_clean=False,
        expect_sha="bad-sha",
        check_required_check=True,
        run=run,
        public_read=public_read,
    )

    assert public_queries == []
    format_row = next(check for check in checks if check["name"] == "expected_sha_format")
    aggregate = next(check for check in checks if check["name"] == "aggregate_required_check")
    assert format_row["status"] == "fail"
    assert aggregate["status"] == "fail"
    assert aggregate["remediation"]


def test_required_check_blocks_when_missing_or_failed(tmp_path: Path):
    root = _root(tmp_path)

    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, f"{SHA}\n"
        return 0, "passed"

    def failed_check(query):
        assert query.endpoint == "github_check_runs"
        assert query.values == (
            "rergards/mempalace-code",
            SHA,
            "release-required",
            100,
        )
        data = {
            "total_count": 1,
            "check_runs": [
                {
                    "name": "release-required",
                    "head_sha": SHA,
                    "status": "completed",
                    "conclusion": "failure",
                }
            ],
        }
        return SimpleNamespace(data=data, error="")

    _, checks = preflight.evaluate(
        root,
        tag=None,
        require_clean=False,
        expect_sha=SHA,
        check_required_check=True,
        run=run,
        public_read=failed_check,
    )

    aggregate = next(check for check in checks if check["name"] == "aggregate_required_check")
    assert aggregate["status"] == "fail"
    assert "failure" in aggregate["detail"]
    assert "release-required" in aggregate["remediation"]


def test_dependency_audit_staleness_blocks_release_admission(tmp_path: Path):
    root = _root(tmp_path)
    admission = preflight._load_admission_checks()
    # Stamp the run relative to now rather than to a fixed date: a hardcoded
    # timestamp would drift in and out of the freshness window as the clock moves.
    stale_stamp = datetime.now(UTC) - timedelta(hours=admission.DEFAULT_AUDIT_MAX_AGE_HOURS + 24)

    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        return 0, "passed"

    def public_read(query):
        assert query.endpoint == "github_workflow_runs"
        assert query.values[1] == "Dependency Audit"
        return SimpleNamespace(
            data=[
                {
                    "status": "completed",
                    "conclusion": "success",
                    "event": "schedule",
                    "updatedAt": stale_stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            ],
            error="",
        )

    _, checks = preflight.evaluate(
        root,
        tag=None,
        require_clean=False,
        check_dependency_audit=True,
        run=run,
        public_read=public_read,
    )

    audit = next(check for check in checks if check["name"] == "dependency_audit_freshness")
    assert audit["status"] == "fail"
    assert "stale" in audit["detail"]
    assert "Dependency Audit" in audit["remediation"]


def test_public_main_comparison_uses_the_normalized_public_query(tmp_path: Path):
    root = _root(tmp_path)
    observed = []

    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, SHA
        return 0, "passed"

    def public_read(query):
        observed.append(query.endpoint)
        return SimpleNamespace(data=SHA, error="")

    _, checks = preflight.evaluate(
        root,
        tag=None,
        require_clean=False,
        expect_sha=SHA,
        check_public_main=True,
        run=run,
        public_read=public_read,
    )

    row = next(check for check in checks if check["name"] == "public_main_expected_sha")
    assert row["status"] == "ok"
    assert observed == ["github_commit"]


def test_public_main_comparison_requires_a_reviewed_sha_without_network(tmp_path: Path):
    root = _root(tmp_path)

    def forbidden_public_read(_query):
        raise AssertionError("public read must not run")

    _, checks = preflight.evaluate(
        root,
        tag=None,
        require_clean=False,
        check_public_main=True,
        run=lambda _command, _root: (0, "passed"),
        public_read=forbidden_public_read,
    )

    row = next(check for check in checks if check["name"] == "public_main_expected_sha")
    assert row["status"] == "fail"
    assert "--expect-sha" in row["detail"]


def test_orphan_preflight_allows_pending_tag_only_after_exact_tag_validation(
    tmp_path: Path, monkeypatch
):
    root = _root(tmp_path)
    admission = preflight._load_admission_checks()
    observed: list[bool] = []

    def check_public_orphan_tags(
        version, repo, package, public_read, *, allow_expected_tag_pending=False
    ):
        assert version == "1.2.3"
        assert repo == admission.DEFAULT_REPO
        assert package == admission.DEFAULT_PACKAGE
        observed.append(allow_expected_tag_pending)
        return admission.ok_row("public_orphan_tags", "fixture passed")

    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "absent"
        return 0, "passed"

    monkeypatch.setattr(admission, "check_public_orphan_tags", check_public_orphan_tags)
    for tag in ("v1.2.3", "v9.9.9"):
        preflight.evaluate(
            root,
            tag=tag,
            require_clean=False,
            check_public_orphan_tags=True,
            run=run,
            public_read=lambda _query: (_ for _ in ()).throw(
                AssertionError("fixture predicate owns public reads")
            ),
        )

    assert observed == [True, False]


def test_cli_wires_live_upstream_opt_in(tmp_path: Path, monkeypatch, capsys):
    root = _root(tmp_path)
    observed: dict[str, object] = {}

    def evaluate(
        root,
        *,
        tag,
        require_clean,
        check_live_upstream,
        with_gitleaks_history,
        expect_sha,
        candidate_ref,
        check_required_check,
        check_dependency_audit,
        check_branch_rules,
        check_tag_ruleset,
        check_public_orphan_tags,
        check_public_main,
        repo,
        branch,
        required_check_name,
        audit_max_age_hours,
    ):
        observed.update(
            root=root,
            tag=tag,
            require_clean=require_clean,
            check_live_upstream=check_live_upstream,
            with_gitleaks_history=with_gitleaks_history,
            expect_sha=expect_sha,
            candidate_ref=candidate_ref,
            check_required_check=check_required_check,
            check_dependency_audit=check_dependency_audit,
            check_branch_rules=check_branch_rules,
            check_tag_ruleset=check_tag_ruleset,
            check_public_orphan_tags=check_public_orphan_tags,
            check_public_main=check_public_main,
            repo=repo,
            branch=branch,
            required_check_name=required_check_name,
            audit_max_age_hours=audit_max_age_hours,
        )
        return "1.2.3", [{"name": "live_upstream_comparison", "status": "ok", "detail": "passed"}]

    monkeypatch.setattr(preflight, "evaluate", evaluate)

    assert (
        preflight.main(
            [
                "--root",
                str(root),
                "--tag",
                "v1.2.3",
                "--require-clean",
                "--check-live-upstream",
                "--json",
            ]
        )
        == 0
    )

    assert observed == {
        "root": root.resolve(),
        "tag": "v1.2.3",
        "require_clean": True,
        "check_live_upstream": True,
        # Not requested on the command line, so history scanning stays off.
        "with_gitleaks_history": False,
        "expect_sha": None,
        "candidate_ref": None,
        "check_required_check": False,
        "check_dependency_audit": False,
        "check_branch_rules": False,
        "check_tag_ruleset": False,
        "check_public_orphan_tags": False,
        "check_public_main": False,
        "repo": None,
        "branch": None,
        "required_check_name": None,
        "audit_max_age_hours": None,
    }
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_evaluate_rejects_tag_that_does_not_match_package_version(tmp_path: Path):
    root = _root(tmp_path)

    _, checks = preflight.evaluate(
        root, tag="v1.2.4", require_clean=False, run=lambda _command, _root: (0, "passed")
    )

    tag_check = checks[0]
    assert tag_check["status"] == "fail"
    assert "does not match" in tag_check["detail"]


def test_evaluate_requires_clean_worktree_when_requested(tmp_path: Path):
    root = _root(tmp_path)

    def run(command, _root):
        if command[:2] == ["git", "status"]:
            return 0, " M README.md"
        return 0, "passed"

    _, checks = preflight.evaluate(root, tag=None, require_clean=True, run=run)

    clean_check = checks[-1]
    assert clean_check["name"] == "clean_tree"
    assert clean_check["status"] == "fail"


# ── tag_identity: refs/tags/v{version} vs HEAD ──────────────────────────────────


def test_tag_identity_fails_when_same_version_tag_points_to_another_commit(tmp_path: Path):
    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 0, "aaaaaaa\n"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, "bbbbbbb\n"
        raise AssertionError(f"unexpected command: {command}")

    check = preflight.check_tag_identity(tmp_path, "1.13.2", run)

    assert check["name"] == "tag_identity"
    assert check["status"] == "fail"
    assert "aaaaaaa" in check["detail"]
    assert "bbbbbbb" in check["detail"]


def test_tag_identity_passes_when_same_version_tag_matches_head(tmp_path: Path):
    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 0, "ccccccc\n"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, "ccccccc\n"
        raise AssertionError(f"unexpected command: {command}")

    check = preflight.check_tag_identity(tmp_path, "1.13.2", run)

    assert check == {
        "name": "tag_identity",
        "status": "ok",
        "detail": "tag v1.13.2 matches HEAD (ccccccc)",
    }


def test_tag_identity_passes_when_version_has_no_tag_yet(tmp_path: Path):
    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 1, "fatal: bad revision"
        raise AssertionError(f"unexpected command: {command}")

    check = preflight.check_tag_identity(tmp_path, "1.13.2", run)

    assert check == {
        "name": "tag_identity",
        "status": "ok",
        "detail": "no existing tag v1.13.2",
    }


def test_tag_identity_fails_closed_on_unexpected_tag_lookup_error(tmp_path: Path):
    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 128, "fatal: not a git repository (or any of the parent directories): .git"
        raise AssertionError(f"unexpected command: {command}")

    check = preflight.check_tag_identity(tmp_path, "1.13.2", run)

    assert check["name"] == "tag_identity"
    assert check["status"] == "fail"
    assert "128" in check["detail"]
    assert "not a git repository" in check["detail"]


def test_tag_identity_fails_closed_on_empty_successful_tag_lookup(tmp_path: Path):
    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 0, "   \n"
        raise AssertionError(f"unexpected command: {command}")

    check = preflight.check_tag_identity(tmp_path, "1.13.2", run)

    assert check["name"] == "tag_identity"
    assert check["status"] == "fail"
    assert "no commit" in check["detail"]


def test_tag_identity_fails_closed_on_empty_successful_head_lookup(tmp_path: Path):
    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 0, "aaaaaaa\n"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, ""
        raise AssertionError(f"unexpected command: {command}")

    check = preflight.check_tag_identity(tmp_path, "1.13.2", run)

    assert check["name"] == "tag_identity"
    assert check["status"] == "fail"
    assert "HEAD" in check["detail"]
    assert "no commit" in check["detail"]


def test_evaluate_surfaces_tag_identity_failure(tmp_path: Path):
    root = _root(tmp_path)

    def run(command, _root):
        if command[:2] == ["git", "rev-parse"] and "--verify" in command:
            return 0, "conflictsha\n"
        if command == ["git", "rev-parse", "HEAD"]:
            return 0, "headsha\n"
        return 0, "passed"

    _, checks = preflight.evaluate(root, tag=None, require_clean=False, run=run)

    tag_identity_check = checks[1]
    assert tag_identity_check["name"] == "tag_identity"
    assert tag_identity_check["status"] == "fail"
