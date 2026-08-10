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
