"""Tests for scripts/release_install_metadata_smoke.py.

Covers: venv install-smoke success, pipx-style disposable tool-environment
coverage, version mismatch diagnostics, probe failures, path/token
sanitization, and machine-readable JSON output.

All subprocess seams are mocked so no live pip, pipx, or network calls are
made by these tests (the real disposable install is exercised separately by
`python scripts/release_install_metadata_smoke.py --install-spec . --json`).
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_module_from_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]  # reason: known script path always returns a spec
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]  # reason: known script path has a loader
    return mod


smoke = _load_module_from_path(
    "release_install_metadata_smoke", ROOT / "scripts" / "release_install_metadata_smoke.py"
)

VERSION = "1.2.3"
PACKAGE = "mempalace-code"

# ── Mock run_subprocess factories ───────────────────────────────────────────────


def _probe_output(version: str) -> str:
    return f"METADATA={version}\nMODULE={version}\n"


def _cli_output(version: str) -> str:
    return f"  Version checks:  enabled\n  Current version: {version}\n  PyPI URL: https://pypi.org/pypi/mempalace-code/json\n"


def _venv_ok_subprocess(
    metadata_version: str = VERSION,
    module_version: str | None = None,
    cli_version: str | None = None,
    calls: list | None = None,
):
    module_version = module_version if module_version is not None else metadata_version
    cli_version = cli_version if cli_version is not None else metadata_version

    def run_subprocess(args, env=None, cwd=None):
        if calls is not None:
            calls.append({"args": args, "env": env, "cwd": cwd})
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "-c" in args:
            return (
                0,
                f"METADATA={metadata_version}\nMODULE={module_version}\n",
                "",
            )
        if "version-check" in args:
            return 0, _cli_output(cli_version), ""
        return 0, "", ""

    return run_subprocess


# ── AC-1 / VER-2: venv smoke success ────────────────────────────────────────────


def test_venv_smoke_reports_matching_metadata_module_and_cli_versions():
    calls: list = []
    run_subprocess = _venv_ok_subprocess(calls=calls)

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is True
    assert result.expected_version == VERSION
    assert result.installer == smoke.INSTALLER_VENV
    assert result.install_spec == "."

    surface_names = {s.name for s in result.surfaces}
    assert surface_names == set(smoke.REQUIRED_SURFACES)
    for s in result.surfaces:
        assert s.status == smoke.STATUS_OK, f"{s.name} expected ok, got {s.status}: {s.detail}"
        assert s.version == VERSION

    # Probes run from a cwd outside the source tree (RISK-1: no source shadowing).
    probe_calls = [c for c in calls if "-c" in c["args"] or "version-check" in c["args"]]
    assert probe_calls, "expected at least one probe call"
    for c in probe_calls:
        assert c["cwd"] is not None
        assert str(ROOT) not in c["cwd"]

    # Non-editable install: no -e/--editable flag passed to pip.
    install_calls = [c for c in calls if "install" in c["args"] and "--no-cache-dir" in c["args"]]
    assert install_calls
    assert "-e" not in install_calls[0]["args"]
    assert "--editable" not in install_calls[0]["args"]

    human = smoke.render_human(result)
    assert "OK" in human
    assert VERSION in human


def test_venv_smoke_json_output_has_required_top_level_keys():
    run_subprocess = _venv_ok_subprocess()
    result = smoke.run_venv_smoke("mempalace-code==" + VERSION, PACKAGE, run_subprocess)
    data = result.to_dict()

    for key in ("ok", "expected_version", "installer", "install_spec", "surfaces", "diagnostics"):
        assert key in data, f"missing top-level key {key!r}"

    assert data["ok"] is True
    assert data["expected_version"] == VERSION
    assert data["installer"] == smoke.INSTALLER_VENV
    assert data["install_spec"] == f"mempalace-code=={VERSION}"

    for s in data["surfaces"]:
        assert "name" in s
        assert "status" in s
        assert "detail" in s
        assert "version" in s

    serialized = json.dumps(data)
    roundtrip = json.loads(serialized)
    assert roundtrip["ok"] is True


# ── AC-2 / VER-3: pipx-style disposable tool environment coverage ─────────────


def test_pipx_smoke_uses_disposable_tool_environment(monkeypatch):
    calls: list = []
    FAKE_PIPX = "/fake/bin/pipx"

    monkeypatch.setattr(smoke, "find_pipx_executable", lambda: FAKE_PIPX)

    def run_subprocess(args, env=None, cwd=None):
        calls.append({"args": args, "env": env, "cwd": cwd})
        if any(a.endswith("pipx") for a in args) and "install" in args:
            return 0, "", ""
        if "-c" in args:
            return 0, _probe_output(VERSION), ""
        if "version-check" in args:
            return 0, _cli_output(VERSION), ""
        return 0, "", ""

    result = smoke.run_pipx_smoke(f"{PACKAGE}=={VERSION}", PACKAGE, run_subprocess)

    assert result.ok is True
    assert result.installer == smoke.INSTALLER_PIPX

    install_calls = [
        c for c in calls if any(a.endswith("pipx") for a in c["args"]) and "install" in c["args"]
    ]
    assert install_calls, "expected a pipx install call"
    install_env = install_calls[0]["env"]
    assert install_env is not None
    assert "PIPX_HOME" in install_env
    assert "PIPX_BIN_DIR" in install_env
    # Disposable — a fresh temp dir scoped to this smoke run, never the operator's real pipx home.
    assert install_env["PIPX_HOME"] != ""
    assert "mempalace-pipx-smoke-" in install_env["PIPX_HOME"]
    assert not install_env["PIPX_HOME"].startswith(str(Path.home()))

    # Every subsequent probe call reuses the same disposable env.
    probe_calls = [c for c in calls if c is not install_calls[0]]
    for c in probe_calls:
        assert c["env"] is not None
        assert c["env"].get("PIPX_HOME") == install_env["PIPX_HOME"]
        assert c["env"].get("PIPX_BIN_DIR") == install_env["PIPX_BIN_DIR"]

    surface_names = {s.name for s in result.surfaces}
    assert smoke.SURFACE_CLI in surface_names


def test_pipx_smoke_install_failure_is_diagnostic_not_ok():
    def run_subprocess(args, env=None, cwd=None):
        if "pipx" in args and "install" in args:
            return 1, "", "No matching distribution found for mempalace-code==9.9.9"
        return 0, "", ""

    result = smoke.run_pipx_smoke("mempalace-code==9.9.9", PACKAGE, run_subprocess)

    assert result.ok is False
    assert result.installer == smoke.INSTALLER_PIPX
    assert any(s.status == smoke.STATUS_FAIL for s in result.surfaces)


# ── AC-3 / VER-4: mismatch diagnostics, reinstall command, sanitization ───────


def test_mismatch_failure_names_surfaces_and_reinstall_command_without_private_paths():
    fake_path = "/Users/testuser/secret-project"
    fake_token = "ghp_" + "A" * 30

    def run_subprocess(args, env=None, cwd=None):
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "-c" in args:
            # Metadata and module disagree.
            return 0, f"METADATA=1.2.3\nMODULE=1.2.2\nnoise at {fake_path} token {fake_token}\n", ""
        if "version-check" in args:
            return 0, _cli_output("1.2.3"), ""
        return 0, "", ""

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    surface_by_name = {s.name: s for s in result.surfaces}
    assert surface_by_name[smoke.SURFACE_METADATA].version == "1.2.3"
    assert surface_by_name[smoke.SURFACE_MODULE].version == "1.2.2"
    assert surface_by_name[smoke.SURFACE_CLI].version == "1.2.3"

    # Diagnostics name each disagreeing surface.
    diag_text = "\n".join(result.diagnostics)
    assert smoke.SURFACE_METADATA in diag_text
    assert smoke.SURFACE_MODULE in diag_text
    assert "1.2.3" in diag_text
    assert "1.2.2" in diag_text

    # A recommended reinstall command is present.
    assert any("pip install" in d and "force-reinstall" in d for d in result.diagnostics)
    assert any("pipx reinstall" in d for d in result.diagnostics)
    assert any("uv tool install --force" in d for d in result.diagnostics)

    # No private path or token anywhere in the result.
    full_text = json.dumps(result.to_dict())
    assert fake_path not in full_text
    assert fake_token not in full_text
    assert "[REDACTED-PATH]" not in full_text or fake_path not in full_text


def test_mismatch_between_module_and_cli_is_detected():
    run_subprocess = _venv_ok_subprocess(
        metadata_version="2.0.0", module_version="2.0.0", cli_version="1.9.9"
    )

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    diag_text = "\n".join(result.diagnostics)
    assert smoke.SURFACE_CLI in diag_text
    assert "1.9.9" in diag_text
    assert "2.0.0" in diag_text


# ── Probe failures ──────────────────────────────────────────────────────────────


def test_venv_creation_failure_is_error_status():
    def run_subprocess(args, env=None, cwd=None):
        if "-m" in args and "venv" in args:
            return 1, "", "No module named venv"
        return 0, "", ""

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    assert len(result.surfaces) == 1
    assert result.surfaces[0].status == smoke.STATUS_ERROR
    assert "venv" in result.surfaces[0].detail.lower()


def test_pip_install_failure_is_fail_status_not_error():
    def run_subprocess(args, env=None, cwd=None):
        if "-m" in args and "venv" in args:
            return 0, "", ""
        return 1, "", "ERROR: Could not find a version that satisfies the requirement"

    result = smoke.run_venv_smoke("mempalace-code==0.0.1", PACKAGE, run_subprocess)

    assert result.ok is False
    assert len(result.surfaces) == 1
    assert result.surfaces[0].status == smoke.STATUS_FAIL


def test_cli_probe_missing_current_version_line_fails():
    def run_subprocess(args, env=None, cwd=None):
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "-c" in args:
            return 0, _probe_output(VERSION), ""
        if "version-check" in args:
            return 0, "  Version checks:  disabled\n", ""
        return 0, "", ""

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    cli_surf = next(s for s in result.surfaces if s.name == smoke.SURFACE_CLI)
    assert cli_surf.status == smoke.STATUS_FAIL
    assert "Current version" in cli_surf.detail


def test_metadata_probe_error_is_sanitized_and_surfaces_error_status():
    fake_path = "/Users/testuser/private"

    def run_subprocess(args, env=None, cwd=None):
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "-c" in args:
            return (
                0,
                f"METADATA-ERROR=PackageNotFoundError at {fake_path}\nMODULE-ERROR=No module named mempalace_code\n",
                "",
            )
        return 0, "", ""

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    metadata_surf = next(s for s in result.surfaces if s.name == smoke.SURFACE_METADATA)
    module_surf = next(s for s in result.surfaces if s.name == smoke.SURFACE_MODULE)
    assert metadata_surf.status == smoke.STATUS_ERROR
    assert module_surf.status == smoke.STATUS_ERROR
    assert fake_path not in metadata_surf.detail
    assert "[REDACTED-PATH]" in metadata_surf.detail


# ── Sanitize helper ─────────────────────────────────────────────────────────────


def test_sanitize_redacts_tokens_paths_and_remotes():
    fake_token = "ghp_" + "B" * 30
    fake_path = "/home/testuser/secret"
    fake_remote = "git@github.com:private-org/private-repo"

    assert smoke.sanitize(fake_token) == "[REDACTED-TOKEN]"
    assert smoke.sanitize(fake_path) == "[REDACTED-PATH]"
    assert smoke.sanitize(fake_remote) == "[REDACTED-REMOTE]"

    # The smoke's own tempfile.TemporaryDirectory() defaults to /tmp on Linux,
    # not /var/folders — must be redacted too.
    fake_linux_tmp = "/tmp/mempalace-install-smoke-abc123/venv/bin/pip"
    assert smoke.sanitize(fake_linux_tmp) == "[REDACTED-PATH]"


# ── Reinstall command builder ────────────────────────────────────────────────────


def test_build_reinstall_commands_are_generic_and_public_safe():
    commands = smoke.build_reinstall_commands(PACKAGE, f"{PACKAGE}=={VERSION}")

    assert any(cmd.startswith("python -m pip install") for cmd in commands)
    assert any(cmd.startswith("pipx reinstall") for cmd in commands)
    assert any(cmd.startswith("uv tool install --force") for cmd in commands)
    for cmd in commands:
        assert "/Users/" not in cmd
        assert "/home/" not in cmd


# ── CLI ────────────────────────────────────────────────────────────────────────


def test_cli_help_exits_cleanly():
    import subprocess

    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "release_install_metadata_smoke.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "--install-spec" in r.stdout
    assert "--installer" in r.stdout
    assert "--json" in r.stdout


def test_main_json_flag_round_trips_through_mocked_subprocess(monkeypatch):
    run_subprocess = _venv_ok_subprocess()

    def fake_default(args, env=None, cwd=None, timeout_seconds=smoke.DEFAULT_TIMEOUT_SECONDS):
        return run_subprocess(args, env=env, cwd=cwd)

    monkeypatch.setattr(smoke, "_default_run_subprocess", fake_default)

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = smoke.main(["--install-spec", ".", "--json"])

    assert exit_code == 0
    data = json.loads(buf.getvalue())
    assert data["ok"] is True
    assert data["expected_version"] == VERSION
    assert data["installer"] == smoke.INSTALLER_VENV
