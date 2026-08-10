"""Tests for scripts/release_artifact_gate.py — artifact member inspection."""

from __future__ import annotations

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


rag = _load_module("release_artifact_gate", ROOT / "scripts" / "release_artifact_gate.py")


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _make_wheel(dist_dir: Path, members: list[str]) -> Path:
    """Create a minimal .whl (zip) archive with the given member names."""
    wheel_path = dist_dir / "mempalace_code-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as zf:
        for member in members:
            zf.writestr(member, "placeholder content")
    return wheel_path


def _make_sdist(dist_dir: Path, members: list[str]) -> Path:
    """Create a minimal .tar.gz archive with the given member names (sdist-style)."""
    sdist_path = dist_dir / "mempalace_code-1.0.0.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for member in members:
            content = b"placeholder content"
            info = tarfile.TarInfo(name=f"mempalace_code-1.0.0/{member}")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    sdist_path.write_bytes(buf.getvalue())
    return sdist_path


# ── Clean artifact tests ───────────────────────────────────────────────────────


def test_clean_wheel_passes_member_check(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "mempalace_code-1.0.0.dist-info/METADATA",
            "mempalace_code-1.0.0.dist-info/RECORD",
        ],
    )
    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)
    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert wheel_row["status"] == "pass"
    assert result["wheel_found"] is not None


def test_clean_sdist_passes_member_check(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "pyproject.toml",
            "README.md",
        ],
    )
    result = rag.inspect_dist(dist_dir, require_sdist=True, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "pass"
    assert result["sdist_found"] is not None


def test_clean_wheel_and_sdist_both_pass(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py"])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py"])
    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=False)
    assert result["ok"] is True
    assert result["wheel_found"] is not None
    assert result["sdist_found"] is not None


# ── Forbidden member rejection ─────────────────────────────────────────────────


def test_wheel_with_codex_local_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".codex-local/LESSONS.md",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    member_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert member_row["status"] == "fail"
    assert ".codex-local" in member_row["detail"]
    assert result["ok"] is False


def test_wheel_with_tasks_dir_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".tasks/TASK-demo/raw.txt",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    member_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert member_row["status"] == "fail"
    assert result["ok"] is False


def test_sdist_with_protocols_dir_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".protocols/some-protocol.md",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_sdist_with_docs_audits_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "docs/audits/internal-audit.md",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_sdist_with_verify_state_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            ".verify-state",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-members")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_wheel_with_pycache_fails(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(
        dist_dir,
        [
            "mempalace_code/__init__.py",
            "__pycache__/module.cpython-311.pyc",
        ],
    )
    result = rag.inspect_dist(dist_dir, run_twine=False)
    member_row = next(r for r in result["rows"] if r["check"] == "wheel-members")
    assert member_row["status"] == "fail"
    assert result["ok"] is False


# ── Missing distribution file tests ───────────────────────────────────────────


def test_missing_wheel_fails_when_required(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_sdist(dist_dir, ["mempalace_code/__init__.py"])
    result = rag.inspect_dist(dist_dir, require_wheel=True, run_twine=False)
    wheel_row = next(r for r in result["rows"] if r["check"] == "wheel-present")
    assert wheel_row["status"] == "fail"
    assert result["ok"] is False


def test_missing_sdist_fails_when_required(tmp_path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py"])
    result = rag.inspect_dist(dist_dir, require_sdist=True, run_twine=False)
    sdist_row = next(r for r in result["rows"] if r["check"] == "sdist-present")
    assert sdist_row["status"] == "fail"
    assert result["ok"] is False


def test_missing_both_no_require_is_ok_with_no_twine(tmp_path):
    """When neither require_wheel nor require_sdist, an empty dist dir is ok (no files = no checks)."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    result = rag.inspect_dist(dist_dir, run_twine=False)
    assert result["ok"] is True
    assert result["wheel_found"] is None
    assert result["sdist_found"] is None


# ── Twine failure reporting ────────────────────────────────────────────────────


def test_twine_check_failure_sets_ok_false(tmp_path, monkeypatch):
    """When twine check fails, ok is False and detail captures the failure."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py"])

    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (False, "FAIL bad metadata"))
    result = rag.inspect_dist(dist_dir, run_twine=True)
    twine_row = next(r for r in result["rows"] if r["check"] == "twine-check")
    assert twine_row["status"] == "fail"
    assert "bad metadata" in twine_row["detail"]
    assert result["ok"] is False


def test_twine_check_pass_sets_ok_true(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py"])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py"])

    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))
    result = rag.inspect_dist(dist_dir, require_wheel=True, require_sdist=True, run_twine=True)
    twine_row = next(r for r in result["rows"] if r["check"] == "twine-check")
    assert twine_row["status"] == "pass"
    assert result["ok"] is True


# ── CLI main() ────────────────────────────────────────────────────────────────


def test_main_missing_dist_dir_exits_1(tmp_path):
    rc = rag.main(["--dist", str(tmp_path / "no-such-dir")])
    assert rc == 1


def test_main_clean_artifacts_exits_0(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py"])
    _make_sdist(dist_dir, ["mempalace_code/__init__.py"])
    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))

    rc = rag.main(
        [
            "--dist",
            str(dist_dir),
            "--require-wheel",
            "--require-sdist",
        ]
    )
    assert rc == 0


def test_main_forbidden_member_exits_1(tmp_path, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, [".tasks/TASK-leak/raw.txt"])
    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))

    rc = rag.main(["--dist", str(dist_dir)])
    assert rc == 1


def test_main_json_output(tmp_path, capsys, monkeypatch):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    _make_wheel(dist_dir, ["mempalace_code/__init__.py"])
    monkeypatch.setattr(rag, "_run_twine_check", lambda _d: (True, "PASSED"))

    rc = rag.main(["--dist", str(dist_dir), "--json"])
    assert rc == 0
    import json as _json

    out = capsys.readouterr().out
    data = _json.loads(out)
    assert "ok" in data
    assert "rows" in data
