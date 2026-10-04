"""Tests for local, non-mutating release preflight checks."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

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


_FIXTURE_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        env=_FIXTURE_GIT_ENV,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--no-gpg-sign", "-m", message)


def _package_repo(tmp_path: Path) -> Path:
    """Return a committed fixture repository with the three bound package inputs."""
    root = tmp_path / "repo"
    (root / "mempalace_code").mkdir(parents=True)
    (root / "mempalace_code" / "__init__.py").write_text(
        '__version__ = "1.2.3"\n', encoding="utf-8"
    )
    (root / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(root, "init", "-q")
    _commit_all(root, "fixture package")
    return root


def _head_ids(root: Path) -> dict[str, str]:
    return {
        field: _git(root, "rev-parse", f"HEAD:{path}")
        for field, path in preflight.ACCEPTANCE_BOUND_OBJECTS
    }


def _report_text(fields: dict[str, str], *, sections: tuple[str, ...] | None = None) -> str:
    header = "\n".join(f"{key}: {value}" for key, value in fields.items())
    body = "\n\n".join(
        f"## {section}\n\n| Column |\n|---|\n"
        for section in (preflight.ACCEPTANCE_REQUIRED_SECTIONS if sections is None else sections)
    )
    return f"---\n{header}\n---\n\n# Installed-candidate acceptance: v1.2.3\n\n{body}"


def _commit_report(
    root: Path,
    overrides: dict[str, str | None] | None = None,
    *,
    sections: tuple[str, ...] | None = None,
    extra_body: str = "",
    commit: bool = True,
) -> Path:
    fields: dict[str, str] = {
        "version": "1.2.3",
        "date": "2026-09-27",
        "result": "PASS",
        **_head_ids(root),
        "wheel_sha256": "0123456789abcdef" * 4,
    }
    for key, value in (overrides or {}).items():
        if value is None:
            fields.pop(key, None)
        else:
            fields[key] = value
    path = root / preflight.acceptance_report_path("1.2.3")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_report_text(fields, sections=sections) + extra_body, encoding="utf-8")
    if commit:
        _commit_all(root, "acceptance report")
    return path


def _git_or_passing_script(command: list[str], root: Path) -> tuple[int, str]:
    """Run git reads for real; report every release script as passing."""
    if command[0] == "git":
        return preflight._run(command, root)
    return 0, "passed"


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
    root = _package_repo(tmp_path)
    _commit_report(root)

    version, checks = preflight.evaluate(
        root, tag="v1.2.3", require_clean=True, run=_git_or_passing_script
    )

    assert version == "1.2.3"
    assert [check["name"] for check in checks] == [
        "tag_version",
        "tag_identity",
        "acceptance_report",
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
    assert "manifest_inventory_commits=36" in upstream["detail"]


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
                    "headBranch": "main",
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


# ── acceptance_report: installed-candidate acceptance bound to HEAD ─────────────


def _acceptance_row(root: Path) -> dict[str, object]:
    return preflight.check_acceptance_report(root, "1.2.3")


def _assert_acceptance_fails(row: dict[str, object], *needles: str) -> None:
    assert row["name"] == "acceptance_report"
    assert row["status"] == "fail", row
    for needle in needles:
        assert needle in str(row["detail"]), row
    remediation = str(row["remediation"])
    assert "\n" not in remediation
    assert "docs/RELEASING.md section 1a" in remediation
    assert "docs/quality/acceptance/v1.2.3.md" in remediation


def test_acceptance_report_passes_for_committed_pass_report_bound_to_head(tmp_path: Path):
    root = _package_repo(tmp_path)
    _commit_report(root)

    row = _acceptance_row(root)

    assert row == {
        "name": "acceptance_report",
        "status": "ok",
        "detail": (
            "docs/quality/acceptance/v1.2.3.md records PASS on 2026-09-27 for the HEAD "
            "mempalace_code tree, pyproject.toml, and uv.lock"
        ),
    }


def test_acceptance_report_survives_documentation_only_commits(tmp_path: Path):
    root = _package_repo(tmp_path)
    _commit_report(root)
    (root / "README.md").write_text("# fixture\n\nRelease notes polished.\n", encoding="utf-8")
    (root / "docs" / "CHANGES.md").write_text("docs only\n", encoding="utf-8")
    _commit_all(root, "docs after acceptance")

    assert _acceptance_row(root)["status"] == "ok"


def test_acceptance_report_missing_fails_with_one_bounded_remediation(tmp_path: Path):
    root = _package_repo(tmp_path)

    _assert_acceptance_fails(
        _acceptance_row(root), "docs/quality/acceptance/v1.2.3.md is not committed at HEAD"
    )


def test_acceptance_report_only_in_worktree_is_not_accepted(tmp_path: Path):
    root = _package_repo(tmp_path)
    _commit_report(root, commit=False)

    _assert_acceptance_fails(_acceptance_row(root), "is not committed at HEAD")


def test_acceptance_report_outside_a_git_checkout_fails_closed(tmp_path: Path):
    root = _root(tmp_path)

    _assert_acceptance_fails(_acceptance_row(root), "is not committed at HEAD")


@pytest.mark.parametrize(
    ("changed_path", "field_label"),
    [
        ("mempalace_code/__init__.py", "mempalace_code changed after acceptance testing"),
        ("pyproject.toml", "pyproject.toml changed after acceptance testing"),
        ("uv.lock", "uv.lock changed after acceptance testing"),
    ],
)
def test_acceptance_report_rejects_package_change_after_testing(
    tmp_path: Path, changed_path: str, field_label: str
):
    root = _package_repo(tmp_path)
    recorded = _head_ids(root)
    _commit_report(root)
    path = root / changed_path
    path.write_text(path.read_text(encoding="utf-8") + "# changed after testing\n")
    _commit_all(root, "package change after acceptance")

    row = _acceptance_row(root)

    _assert_acceptance_fails(row, field_label)
    field = next(f for f, p in preflight.ACCEPTANCE_BOUND_OBJECTS if changed_path.startswith(p))
    assert recorded[field][:12] in str(row["detail"])
    assert _head_ids(root)[field][:12] in str(row["detail"])


def test_acceptance_report_rejects_a_fail_result(tmp_path: Path):
    root = _package_repo(tmp_path)
    _commit_report(root, {"result": "FAIL"})

    _assert_acceptance_fails(_acceptance_row(root), "result is 'FAIL', not 'PASS'")


def test_acceptance_report_rejects_another_version(tmp_path: Path):
    root = _package_repo(tmp_path)
    _commit_report(root, {"version": "1.2.2"})

    _assert_acceptance_fails(_acceptance_row(root), "records version '1.2.2', not '1.2.3'")


def test_acceptance_report_rejects_missing_and_malformed_header_fields(tmp_path: Path):
    root = _package_repo(tmp_path)
    _commit_report(
        root,
        {
            "uv_lock_blob": None,
            "wheel_sha256": "not-a-digest",
            "date": "27.09.2026",
            "mempalace_code_tree": "HEAD",
        },
    )

    _assert_acceptance_fails(
        _acceptance_row(root),
        "missing header fields: uv_lock_blob",
        "wheel_sha256 is not a lowercase 64-hex digest",
        "date '27.09.2026' is not a valid YYYY-MM-DD date",
        "mempalace_code_tree is not a lowercase git object id",
    )


def test_acceptance_report_requires_front_matter_and_sections(tmp_path: Path):
    root = _package_repo(tmp_path)
    path = root / preflight.acceptance_report_path("1.2.3")
    path.parent.mkdir(parents=True)
    path.write_text("# Acceptance\n\nresult: PASS\n", encoding="utf-8")
    _commit_all(root, "stub report")

    _assert_acceptance_fails(
        _acceptance_row(root),
        "does not start with a '---' front-matter header",
        "missing '## Coverage' section",
        "missing '## Issues' section",
        "missing '## Re-test' section",
    )


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"date": "2026-99-99"}, "date '2026-99-99' is not a valid YYYY-MM-DD date"),
        ({"version": "v1.2.3"}, "records version 'v1.2.3', not '1.2.3'"),
    ],
)
def test_acceptance_report_rejects_impossible_date_and_prefixed_version(
    tmp_path: Path, overrides: dict[str, str | None], needle: str
):
    root = _package_repo(tmp_path)
    _commit_report(root, overrides)

    _assert_acceptance_fails(_acceptance_row(root), needle)


def test_acceptance_report_ignores_sections_inside_fenced_blocks(tmp_path: Path):
    root = _package_repo(tmp_path)
    _commit_report(
        root,
        sections=(),
        extra_body="\n```markdown\n## Coverage\n## Issues\n## Re-test\n```\n",
    )

    _assert_acceptance_fails(
        _acceptance_row(root),
        "missing '## Coverage' section",
        "missing '## Issues' section",
        "missing '## Re-test' section",
    )


def test_acceptance_report_bounds_the_listed_problems(tmp_path: Path):
    root = _package_repo(tmp_path)
    path = root / preflight.acceptance_report_path("1.2.3")
    path.parent.mkdir(parents=True)
    junk = "".join(f"junk line {index}\n" for index in range(200))
    path.write_text(f"---\n{junk}---\n", encoding="utf-8")
    _commit_all(root, "junk report")

    row = _acceptance_row(root)

    _assert_acceptance_fails(row, "junk line 0", "(+198 more)")
    assert "junk line 199" not in str(row["detail"])
    assert len(str(row["detail"])) < 500


def test_cli_reports_non_utf8_acceptance_report_as_a_json_row(tmp_path: Path, monkeypatch, capsys):
    root = _package_repo(tmp_path)
    path = root / preflight.acceptance_report_path("1.2.3")
    path.parent.mkdir(parents=True)
    path.write_bytes("---\nversion: 1.2.3\n---\n".encode("utf-16"))
    _commit_all(root, "utf-16 report")
    evaluate = preflight.evaluate
    monkeypatch.setattr(
        preflight,
        "evaluate",
        lambda root, **kwargs: evaluate(root, run=_git_or_passing_script, **kwargs),
    )

    assert preflight.main(["--root", str(root), "--tag", "v1.2.3", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)

    row = next(check for check in result["checks"] if check["name"] == "acceptance_report")
    _assert_acceptance_fails(row, "docs/quality/acceptance/v1.2.3.md is not UTF-8 text")
    assert {"tag_version", "tag_identity"} <= {check["name"] for check in result["checks"]}


def test_acceptance_report_rejects_duplicate_header_fields():
    fields, problems = preflight.parse_acceptance_header(
        "---\nresult: PASS\nresult: FAIL\nnot a field\n---\n"
    )

    assert fields == {"result": "PASS"}
    assert problems == ["duplicate header field 'result'", "malformed header line 'not a field'"]


def test_acceptance_report_rejects_local_paths(tmp_path: Path):
    root = _package_repo(tmp_path)
    local_path = "/" + "/".join(("home", "someone", "palace"))
    _commit_report(root, extra_body=f"\nReproduced with `mempalace-code --palace {local_path}`.\n")

    _assert_acceptance_fails(_acceptance_row(root), "not public-safe", "linux-home-root")


def test_evaluate_requires_acceptance_report_only_for_tag_admission(tmp_path: Path):
    root = _package_repo(tmp_path)

    _, untagged = preflight.evaluate(
        root, tag=None, require_clean=False, run=_git_or_passing_script
    )
    _, tagged = preflight.evaluate(
        root, tag="v1.2.3", require_clean=False, run=_git_or_passing_script
    )

    assert "acceptance_report" not in [check["name"] for check in untagged]
    assert all(check["status"] == "ok" for check in untagged)
    row = next(check for check in tagged if check["name"] == "acceptance_report")
    assert row["status"] == "fail"


def test_cli_prints_acceptance_failure_and_remediation(tmp_path: Path, monkeypatch, capsys):
    root = _package_repo(tmp_path)
    evaluate = preflight.evaluate
    monkeypatch.setattr(
        preflight,
        "evaluate",
        lambda root, **kwargs: evaluate(root, run=_git_or_passing_script, **kwargs),
    )

    assert preflight.main(["--root", str(root), "--tag", "v1.2.3", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)

    assert result["ok"] is False
    row = next(check for check in result["checks"] if check["name"] == "acceptance_report")
    assert row["status"] == "fail"
    assert "section 1a" in row["remediation"]


def test_acceptance_format_doc_template_matches_the_parser():
    text = (ROOT / preflight.ACCEPTANCE_FORMAT_DOC).read_text(encoding="utf-8")
    match = re.search(r"^```markdown\n(?P<template>.*?)^```$", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "the acceptance README must carry a markdown template"
    template = match.group("template")

    fields, problems = preflight.parse_acceptance_header(template)

    assert problems == []
    assert set(preflight.ACCEPTANCE_REQUIRED_FIELDS) <= set(fields)
    for section in preflight.ACCEPTANCE_REQUIRED_SECTIONS:
        assert re.search(rf"^## {re.escape(section)}\b", template, re.MULTILINE)
    for field in preflight.ACCEPTANCE_REQUIRED_FIELDS:
        assert f"`{field}`" in text, f"{field} is not documented in the header table"


def test_publish_workflow_runs_tag_admission_that_includes_acceptance():
    publish = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    invocations = re.findall(
        r"python scripts/release_preflight\.py \\\n\s+--tag \"\$TAG_NAME\"", publish
    )
    assert len(invocations) == 2
