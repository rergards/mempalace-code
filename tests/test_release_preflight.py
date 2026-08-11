"""Tests for local, non-mutating release preflight checks."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = _load_module("release_preflight", ROOT / "scripts" / "release_preflight.py")


def _root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    return tmp_path


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
