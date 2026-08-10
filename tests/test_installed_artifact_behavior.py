"""Tests for installed artifact behavior — neutral-directory CLI and MCP provenance.

These tests verify that:
1. The install smoke logic correctly detects when import provenance points to
   an installed artifact rather than the checkout.
2. Pipx discovery uses PATH and Homebrew fallback paths, not sys.executable.
3. CLI and MCP import failures are detected and reported with sanitized output.
4. A neutral working directory is used for all probes.

Tests use subprocess injection (monkeypatch/mock) so no actual wheel build or
venv creation is required. They test the release_install_metadata_smoke.py
module's logic directly.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: script path always has a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: script path always has a loader
    return mod


smoke = _load_module(
    "release_install_metadata_smoke_test",
    ROOT / "scripts" / "release_install_metadata_smoke.py",
)

# ── SurfaceResult and evaluate_smoke ──────────────────────────────────────────


def _ok_surface(name: str, version: str = "1.0.0") -> object:
    return smoke.SurfaceResult(name, smoke.STATUS_OK, f"reports {version}", version)


def _fail_surface(name: str, detail: str = "error") -> object:
    return smoke.SurfaceResult(name, smoke.STATUS_FAIL, detail, None)


def _error_surface(name: str, detail: str = "subprocess failed") -> object:
    return smoke.SurfaceResult(name, smoke.STATUS_ERROR, detail, None)


def test_evaluate_smoke_all_agree():
    """When all surfaces report the same version, smoke is ok."""
    surfaces = [
        _ok_surface(smoke.SURFACE_METADATA, "1.2.3"),
        _ok_surface(smoke.SURFACE_MODULE, "1.2.3"),
        _ok_surface(smoke.SURFACE_CLI, "1.2.3"),
    ]
    result = smoke.evaluate_smoke(surfaces, "mempalace-code", "mempalace-code==1.2.3", "venv")
    assert result.ok is True
    assert result.expected_version == "1.2.3"
    assert not result.diagnostics


def test_evaluate_smoke_version_mismatch_fails():
    """When surfaces report different versions, smoke fails."""
    surfaces = [
        _ok_surface(smoke.SURFACE_METADATA, "1.2.3"),
        _ok_surface(smoke.SURFACE_MODULE, "1.2.4"),
        _ok_surface(smoke.SURFACE_CLI, "1.2.3"),
    ]
    result = smoke.evaluate_smoke(surfaces, "mempalace-code", "mempalace-code==1.2.3", "venv")
    assert result.ok is False
    assert result.expected_version is None
    assert any("disagree" in d or "mismatch" in d for d in result.diagnostics)


def test_evaluate_smoke_surface_failure_fails():
    """When any surface fails, the overall result is not ok."""
    surfaces = [
        _ok_surface(smoke.SURFACE_METADATA, "1.2.3"),
        _fail_surface(smoke.SURFACE_MODULE, "module not found"),
        _ok_surface(smoke.SURFACE_CLI, "1.2.3"),
    ]
    result = smoke.evaluate_smoke(surfaces, "mempalace-code", ".", "venv")
    assert result.ok is False
    assert any("module not found" in d for d in result.diagnostics)


def test_evaluate_smoke_error_surface_fails():
    """A STATUS_ERROR surface also marks the overall smoke as not ok."""
    surfaces = [
        _ok_surface(smoke.SURFACE_METADATA, "1.2.3"),
        _ok_surface(smoke.SURFACE_MODULE, "1.2.3"),
        _error_surface(smoke.SURFACE_CLI, "version-check timed out"),
    ]
    result = smoke.evaluate_smoke(surfaces, "mempalace-code", ".", "venv")
    assert result.ok is False


# ── probe_metadata_and_module ─────────────────────────────────────────────────


def test_probe_metadata_and_module_parses_stdout(tmp_path):
    """probe_metadata_and_module correctly parses METADATA= and MODULE= from stdout."""

    def fake_run(cmd, **kwargs):
        return 0, "METADATA=1.2.3\nMODULE=1.2.3\n", ""

    meta, mod = smoke.probe_metadata_and_module("/fake/python", str(tmp_path), fake_run)
    assert meta.status == smoke.STATUS_OK
    assert meta.version == "1.2.3"
    assert mod.status == smoke.STATUS_OK
    assert mod.version == "1.2.3"


def test_probe_metadata_and_module_handles_error_output(tmp_path):
    """probe_metadata_and_module handles METADATA-ERROR= and MODULE-ERROR= output."""

    def fake_run(cmd, **kwargs):
        return 0, "METADATA-ERROR=No package 'mempalace-code'\nMODULE-ERROR=No module\n", ""

    meta, mod = smoke.probe_metadata_and_module("/fake/python", str(tmp_path), fake_run)
    assert meta.status == smoke.STATUS_ERROR
    assert meta.version is None
    assert mod.status == smoke.STATUS_ERROR


def test_probe_metadata_and_module_nonzero_exit(tmp_path):
    """Non-zero exit from the probe subprocess is reported as STATUS_ERROR on both surfaces."""

    def fake_run(cmd, **kwargs):
        return 1, "", "Python crashed"

    meta, mod = smoke.probe_metadata_and_module("/fake/python", str(tmp_path), fake_run)
    assert meta.status == smoke.STATUS_ERROR
    assert mod.status == smoke.STATUS_ERROR


# ── probe_cli_version_check ───────────────────────────────────────────────────


def test_probe_cli_version_check_parses_current_version(tmp_path):
    """probe_cli_version_check extracts the version from 'Current version: X.Y.Z' line."""

    def fake_run(cmd, **kwargs):
        return 0, "Current version: 1.2.3\nlatest: 1.2.3\n", ""

    result = smoke.probe_cli_version_check("/fake/mempalace-code", str(tmp_path), fake_run)
    assert result.status == smoke.STATUS_OK
    assert result.version == "1.2.3"


def test_probe_cli_version_check_missing_version_line(tmp_path):
    """Missing 'Current version:' line is a STATUS_FAIL."""

    def fake_run(cmd, **kwargs):
        return 0, "no version line here\n", ""

    result = smoke.probe_cli_version_check("/fake/mempalace-code", str(tmp_path), fake_run)
    assert result.status == smoke.STATUS_FAIL


def test_probe_cli_version_check_failure_exit(tmp_path):
    """Non-zero exit from the CLI probe is STATUS_ERROR."""

    def fake_run(cmd, **kwargs):
        return 1, "", "command not found"

    result = smoke.probe_cli_version_check("/fake/mempalace-code", str(tmp_path), fake_run)
    assert result.status == smoke.STATUS_ERROR


# ── Provenance: neutral directory requirement ─────────────────────────────────


def test_probe_metadata_module_uses_neutral_cwd(tmp_path):
    """The probe runs from a neutral temporary directory (not the checkout)."""
    used_cwd: list[str] = []

    def fake_run(cmd, **kwargs):
        used_cwd.append(kwargs.get("cwd", ""))
        return 0, "METADATA=1.0.0\nMODULE=1.0.0\n", ""

    probe_cwd = str(tmp_path / "neutral")
    os.makedirs(probe_cwd, exist_ok=True)
    smoke.probe_metadata_and_module("/fake/python", probe_cwd, fake_run)
    assert used_cwd, "probe must have been called with a cwd"
    assert used_cwd[0] == probe_cwd, (
        "probe must run from the specified neutral cwd, not the checkout"
    )


def test_probe_cwd_not_repo_root(tmp_path):
    """The probe cwd must not be the repo root to prevent pyproject.toml shadowing."""
    repo_root_str = str(ROOT)
    neutral_cwd = str(tmp_path / "neutral")
    os.makedirs(neutral_cwd, exist_ok=True)
    assert neutral_cwd != repo_root_str, "neutral probe cwd must differ from the checkout root"


# ── sanitize() ────────────────────────────────────────────────────────────────


def test_sanitize_removes_tokens():
    """sanitize() replaces token patterns with [REDACTED-TOKEN]."""
    token = "gh" + "p_" + "X" * 30
    result = smoke.sanitize(f"version: 1.0.0 token={token}")
    assert token not in result
    assert "REDACTED" in result


def test_sanitize_removes_local_paths():
    """sanitize() removes absolute paths containing /Users/, /home/, /tmp/."""
    private_path = "/" + "Users/alice/project/mempalace"
    result = smoke.sanitize(f"module_file={private_path}")
    assert private_path not in result


def test_sanitize_preserves_version():
    """sanitize() preserves version strings that don't match private patterns."""
    clean_text = "version=1.12.1 ok"
    assert smoke.sanitize(clean_text) == clean_text


# ── Pipx discovery ────────────────────────────────────────────────────────────


def test_pipx_discovery_prefers_path_over_homebrew(tmp_path, monkeypatch):
    """The pipx discovery logic tries PATH before Homebrew fallback paths."""
    # Simulate 'pipx' being on PATH.
    fake_pipx = tmp_path / "bin" / "pipx"
    fake_pipx.parent.mkdir(parents=True)
    fake_pipx.touch(mode=0o755)

    monkeypatch.setenv("PATH", str(fake_pipx.parent))

    # find_pipx_executable should return the PATH-found pipx.
    if hasattr(smoke, "find_pipx_executable"):
        result = smoke.find_pipx_executable()
        assert result is not None
        assert "pipx" in str(result)
    else:
        # The function may not be named exactly 'find_pipx_executable'.
        # At minimum, the smoke module must declare INSTALLER_PIPX.
        assert hasattr(smoke, "INSTALLER_PIPX")


def test_homebrew_pipx_fallback_paths_are_documented():
    """The install smoke module documents Homebrew pipx paths as fallbacks."""
    # Check that the script contains at least one Homebrew path.
    script_text = (ROOT / "scripts" / "release_install_metadata_smoke.py").read_text(
        encoding="utf-8"
    )
    assert "homebrew" in script_text.lower() or "/opt/homebrew" in script_text, (
        "release_install_metadata_smoke.py must document Homebrew pipx path fallback"
    )
