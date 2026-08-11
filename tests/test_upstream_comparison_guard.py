"""Tests for the stdlib-only upstream comparison guard."""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_module("upstream_comparison_guard", ROOT / "scripts" / "upstream_comparison_guard.py")

COMMIT = "a" * 40
REPOSITORY = "https://github.com/Example/example"
BRANCH = "main"
REVIEWED_DATE = "2026-07-01"


def _manifest(**overrides) -> dict:
    manifest = {
        "schema_version": 1,
        "reviewed_date": REVIEWED_DATE,
        "canonical_repository": REPOSITORY,
        "branch": BRANCH,
        "commit": COMMIT,
        "canonical_document": "docs/UPSTREAM_COMPARISON.md",
        "readme_path": "README.md",
        "tracked_source_paths": ["README.md"],
        "readme_markers": ["## This Fork vs Upstream"],
        "comparison_markers": ["## Snapshot"],
        "capabilities": {
            "upstream_advertised": ["some-capability"],
            "fork_current": ["other-capability"],
        },
    }
    manifest.update(overrides)
    return manifest


def _root(tmp_path: Path, *, manifest: dict | None = None) -> Path:
    manifest = manifest if manifest is not None else _manifest()

    quality_dir = tmp_path / "docs" / "quality"
    quality_dir.mkdir(parents=True)
    (quality_dir / "upstream-comparison.json").write_text(json.dumps(manifest), encoding="utf-8")

    (tmp_path / "README.md").write_text(
        "# Example\n\n## This Fork vs Upstream\n\nSee the comparison doc.\n",
        encoding="utf-8",
    )

    doc_lines = [
        "# Upstream Comparison",
        "",
        "## Snapshot",
        "",
        f"repository: {REPOSITORY}",
        f"branch: {BRANCH}",
        f"commit: {COMMIT}",
        f"reviewed_date: {REVIEWED_DATE}",
        "some-capability",
        "other-capability",
        "",
    ]
    (tmp_path / "docs" / "UPSTREAM_COMPARISON.md").write_text(
        "\n".join(doc_lines), encoding="utf-8"
    )

    return tmp_path


def test_evaluate_accepts_valid_static_snapshot(tmp_path: Path):
    root = _root(tmp_path)

    facts, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert errors == []
    assert facts["commit"] == COMMIT
    assert facts["review_age_days"] == 9


def test_evaluate_rejects_stale_review_date(tmp_path: Path):
    root = _root(tmp_path)

    _, errors = guard.evaluate(root, max_age_days=30, today=date(2026, 9, 1))

    assert any("review-stale" in error for error in errors)


def test_evaluate_rejects_missing_readme_marker(tmp_path: Path):
    root = _root(tmp_path)
    (root / "README.md").write_text("# Example\n\nNo marker here.\n", encoding="utf-8")

    _, errors = guard.evaluate(root, today=date(2026, 7, 10))

    assert any("readme-pointer" in error for error in errors)


def test_check_live_accepts_matching_sha_from_injected_fetcher(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)
    source_before = {
        "manifest": (root / "docs" / "quality" / "upstream-comparison.json").read_bytes(),
        "comparison": (root / "docs" / "UPSTREAM_COMPARISON.md").read_bytes(),
        "readme": (root / "README.md").read_bytes(),
    }

    def fetch(_url: str) -> str:
        return json.dumps({"sha": COMMIT})

    facts, errors = guard.check_live(manifest, fetch=fetch)

    assert errors == []
    assert facts["live_head"] == COMMIT
    assert source_before == {
        "manifest": (root / "docs" / "quality" / "upstream-comparison.json").read_bytes(),
        "comparison": (root / "docs" / "UPSTREAM_COMPARISON.md").read_bytes(),
        "readme": (root / "README.md").read_bytes(),
    }


def test_check_live_rejects_mismatching_sha(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)
    other_sha = "b" * 40

    def fetch(_url: str) -> str:
        return json.dumps({"sha": other_sha})

    facts, errors = guard.check_live(manifest, fetch=fetch)

    assert facts["live_head"] == other_sha
    assert any("upstream-drift" in error for error in errors)


def test_check_live_rejects_invalid_json(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)

    def fetch(_url: str) -> str:
        return "not json"

    facts, errors = guard.check_live(manifest, fetch=fetch)

    assert facts["live_head"] is None
    assert any("live-response" in error for error in errors)


def test_check_live_fails_closed_on_fetch_failure(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)

    def fetch(_url: str) -> str:
        raise guard.LiveCheckError("live-response: upstream head request failed (offline)")

    facts, errors = guard.check_live(manifest, fetch=fetch)

    assert facts["live_head"] is None
    assert errors == ["live-response: upstream head request failed (offline)"]


def test_default_fetch_wraps_network_failure_as_untrusted_live_response(monkeypatch):
    def urlopen(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(guard.urllib.request, "urlopen", urlopen)

    try:
        guard._default_fetch("https://api.github.com/example")
    except guard.LiveCheckError as exc:
        assert "live-response" in str(exc)
        assert "offline" in str(exc)
    else:
        raise AssertionError("network failure must fail closed")


def test_check_live_rejects_empty_or_malformed_head_resolution(tmp_path: Path):
    root = _root(tmp_path)
    manifest = guard.load_manifest(root)

    for payload in ("{}", '{"sha": ""}', '{"sha": "not-a-commit"}'):
        facts, errors = guard.check_live(manifest, fetch=lambda _url, payload=payload: payload)
        assert facts["live_head"] is None
        assert errors == ["live-response: upstream head reply carried no 40-hex commit sha"]


def test_evaluate_rejects_negative_max_age_days(tmp_path: Path):
    root = _root(tmp_path)

    _, errors = guard.evaluate(root, max_age_days=-1, today=date(2026, 7, 10))

    assert any("config-invalid" in error for error in errors)
