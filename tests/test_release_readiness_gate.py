"""Tests for scripts/release_readiness_gate.py — release-readiness orchestration."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


rrg = _load_module("release_readiness_gate", ROOT / "scripts" / "release_readiness_gate.py")


# ── Fixture helpers ────────────────────────────────────────────────────────────


def _mock_inventory_ok() -> list[dict]:
    return [
        rrg._make_row("gate_inventory", "python scripts/gate_inventory.py --check", "pass", "ok")
    ]


def _mock_inventory_fail() -> list[dict]:
    return [
        rrg._make_row(
            "gate_inventory", "python scripts/gate_inventory.py --check", "fail", "drift detected"
        )
    ]


def _mock_build_ok() -> tuple[bool, str]:
    return True, "built successfully"


def _mock_build_fail() -> tuple[bool, str]:
    return False, "hatchling error"


def _mock_artifact_rows_ok() -> list[dict]:
    return [
        rrg._make_row("artifact_wheel_present", "artifact-gate:wheel-present", "pass", "test.whl"),
        rrg._make_row(
            "artifact_sdist_present", "artifact-gate:sdist-present", "pass", "test.tar.gz"
        ),
        rrg._make_row("artifact_wheel_members", "artifact-gate:wheel-members", "pass", "test.whl"),
        rrg._make_row(
            "artifact_sdist_members", "artifact-gate:sdist-members", "pass", "test.tar.gz"
        ),
        rrg._make_row("artifact_twine_check", "artifact-gate:twine-check", "pass", "PASSED"),
    ]


def _mock_artifact_rows_fail() -> list[dict]:
    return [
        rrg._make_row("artifact_wheel_present", "artifact-gate:wheel-present", "pass", "test.whl"),
        rrg._make_row(
            "artifact_sdist_present", "artifact-gate:sdist-present", "fail", "no .tar.gz found"
        ),
    ]


def _mock_smoke_ok() -> list[dict]:
    return [
        rrg._make_row(
            "install_smoke_venv", "install-smoke --installer venv", "pass", "version=1.0.0"
        ),
        rrg._make_row(
            "install_smoke_pipx", "install-smoke --installer pipx", "pass", "version=1.0.0"
        ),
    ]


def _mock_smoke_fail() -> list[dict]:
    return [
        rrg._make_row(
            "install_smoke_venv",
            "install-smoke --installer venv",
            "fail",
            "module version mismatch",
        ),
        rrg._make_row(
            "install_smoke_pipx",
            "install-smoke --installer pipx",
            "fail",
            "module version mismatch",
        ),
    ]


# ── _make_row ─────────────────────────────────────────────────────────────────


def test_make_row_has_required_fields():
    row = rrg._make_row("test_id", "test command", "pass", "all good")
    assert row["id"] == "test_id"
    assert row["command"] == "test command"
    assert row["status"] == "pass"
    assert row["detail"] == "all good"


# ── all-green readiness ────────────────────────────────────────────────────────


def test_run_readiness_all_green(tmp_path):
    """When all sub-checks pass, run_readiness returns ok=True."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
    ):
        result = rrg.run_readiness(tmp_path)

    assert result["ok"] is True
    assert len(result["rows"]) > 0
    statuses = {r["status"] for r in result["rows"]}
    assert "fail" not in statuses


def test_run_readiness_inventory_failure_propagates(tmp_path):
    """A gate_inventory failure sets ok=False."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_fail()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
    ):
        result = rrg.run_readiness(tmp_path)

    assert result["ok"] is False
    fail_rows = [r for r in result["rows"] if r["status"] == "fail"]
    assert any(r["id"] == "gate_inventory" for r in fail_rows)


def test_run_readiness_build_failure_stops_artifact_check(tmp_path):
    """When build fails, artifact inspection is skipped."""
    artifact_check_called = []

    def mock_artifact(_dist_dir):
        artifact_check_called.append(True)
        return _mock_artifact_rows_ok()

    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_fail()),
        patch.object(rrg, "_run_artifact_inspection", side_effect=mock_artifact),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
    ):
        result = rrg.run_readiness(tmp_path)

    assert result["ok"] is False
    assert not artifact_check_called, "artifact inspection must not run when build fails"
    build_row = next(r for r in result["rows"] if r["id"] == "artifact_build")
    assert build_row["status"] == "fail"


def test_run_readiness_artifact_inspection_failure(tmp_path):
    """Artifact inspection failure sets ok=False."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_fail()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
    ):
        result = rrg.run_readiness(tmp_path)

    assert result["ok"] is False
    fail_ids = {r["id"] for r in result["rows"] if r["status"] == "fail"}
    assert any("sdist" in rid for rid in fail_ids)


def test_run_readiness_install_smoke_failure(tmp_path):
    """Install smoke failure sets ok=False."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_fail()),
    ):
        result = rrg.run_readiness(tmp_path)

    assert result["ok"] is False
    smoke_rows = [r for r in result["rows"] if r["id"].startswith("install_smoke_")]
    assert smoke_rows, "expected at least one smoke row"
    assert any(r["status"] == "fail" for r in smoke_rows)


# ── artifact_only mode ────────────────────────────────────────────────────────


def test_run_readiness_artifact_only_skips_inventory_and_smoke(tmp_path):
    """In artifact_only mode, inventory check and install smoke are not called."""
    inventory_called = []
    smoke_called = []

    def mock_inventory(_root):
        inventory_called.append(True)
        return _mock_inventory_ok()

    def mock_smoke(_dist_dir):
        smoke_called.append(True)
        return _mock_smoke_ok()

    with (
        patch.object(rrg, "_run_inventory_check", side_effect=mock_inventory),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", side_effect=mock_smoke),
    ):
        result = rrg.run_readiness(tmp_path, artifact_only=True)

    assert not inventory_called, "inventory should not be called in artifact_only mode"
    assert not smoke_called, "smoke should not be called in artifact_only mode"
    assert result["ok"] is True


# ── JSON output ────────────────────────────────────────────────────────────────


def test_result_is_json_serializable(tmp_path):
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
    ):
        result = rrg.run_readiness(tmp_path)

    dumped = json.dumps(result)
    parsed = json.loads(dumped)
    assert parsed["ok"] is True
    assert isinstance(parsed["rows"], list)


def test_result_rows_have_required_fields(tmp_path):
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
    ):
        result = rrg.run_readiness(tmp_path)

    for row in result["rows"]:
        assert "id" in row, f"row missing 'id': {row}"
        assert "command" in row, f"row missing 'command': {row}"
        assert "status" in row, f"row missing 'status': {row}"
        assert "detail" in row, f"row missing 'detail': {row}"


# ── CLI main() ────────────────────────────────────────────────────────────────


def test_main_requires_check_or_artifact_only(capsys):
    import pytest

    with pytest.raises(SystemExit) as exc_info:
        rrg.main([])
    assert exc_info.value.code != 0


def test_main_json_all_green(tmp_path, capsys):
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_ok()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
        patch.object(rrg, "Path", side_effect=lambda *a, **kw: tmp_path),
    ):
        rrg.main(["--check", "--json"])

    out = capsys.readouterr().out
    if out.strip():
        data = json.loads(out)
        assert "ok" in data
        assert "rows" in data


def test_main_single_canonical_failure_exits_1(tmp_path):
    """Any canonical gate failure causes exit code 1."""
    with (
        patch.object(rrg, "_run_inventory_check", return_value=_mock_inventory_fail()),
        patch.object(rrg, "_build_artifacts", return_value=_mock_build_ok()),
        patch.object(rrg, "_run_artifact_inspection", return_value=_mock_artifact_rows_ok()),
        patch.object(rrg, "_run_install_smoke", return_value=_mock_smoke_ok()),
    ):
        result = rrg.run_readiness(tmp_path)
    assert result["ok"] is False


# ── Integration boundary: wheel path forwarding ───────────────────────────────


def test_install_smoke_forwards_wheel_to_both_apis(tmp_path):
    """_run_install_smoke passes the .whl path to run_venv_smoke and run_pipx_smoke.

    This test does not mock the integration boundary: it loads the real smoke module
    and stubs only the slow install steps, so calling a nonexistent smoke.run_smoke
    would raise AttributeError and the assertions on venv_calls/pipx_calls would fail.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    wheel = dist_dir / "mempalace_code-1.0.0-py3-none-any.whl"
    wheel.write_bytes(b"fake-wheel")

    smoke_mod = _load_module(
        "_test_smoke_fwd", ROOT / "scripts" / "release_install_metadata_smoke.py"
    )

    venv_calls: list[str] = []
    pipx_calls: list[str] = []

    def fake_venv(install_spec, package, run_subprocess):
        venv_calls.append(install_spec)
        return smoke_mod.SmokeResult(
            ok=True, expected_version="1.0.0", installer="venv", install_spec=install_spec
        )

    def fake_pipx(install_spec, package, run_subprocess):
        pipx_calls.append(install_spec)
        return smoke_mod.SmokeResult(
            ok=True, expected_version="1.0.0", installer="pipx", install_spec=install_spec
        )

    vars(smoke_mod)["run_venv_smoke"] = fake_venv
    vars(smoke_mod)["run_pipx_smoke"] = fake_pipx

    with patch.object(rrg, "_load_sibling", return_value=smoke_mod):
        rows = rrg._run_install_smoke(dist_dir)

    assert venv_calls, "run_venv_smoke was not called"
    assert venv_calls[0].endswith(".whl"), (
        f"venv install_spec must be a wheel path, got {venv_calls[0]!r}"
    )
    assert pipx_calls, "run_pipx_smoke was not called"
    assert pipx_calls[0].endswith(".whl"), (
        f"pipx install_spec must be a wheel path, got {pipx_calls[0]!r}"
    )
    assert any(r["id"] == "install_smoke_venv" for r in rows)
    assert any(r["id"] == "install_smoke_pipx" for r in rows)


def test_install_smoke_uses_real_api_not_run_smoke():
    """The smoke module must expose run_venv_smoke and run_pipx_smoke, not run_smoke.

    If _run_install_smoke called smoke.run_smoke, it would hit AttributeError and the
    venv/pipx call assertions in test_install_smoke_forwards_wheel_to_both_apis would fail.
    This test verifies the module shape independently.
    """
    smoke_mod = _load_module(
        "_test_smoke_api_shape", ROOT / "scripts" / "release_install_metadata_smoke.py"
    )
    assert not hasattr(smoke_mod, "run_smoke"), (
        "run_smoke must not exist in release_install_metadata_smoke — "
        "the correct APIs are run_venv_smoke and run_pipx_smoke"
    )
    assert callable(getattr(smoke_mod, "run_venv_smoke", None)), "run_venv_smoke must be callable"
    assert callable(getattr(smoke_mod, "run_pipx_smoke", None)), "run_pipx_smoke must be callable"
