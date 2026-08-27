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
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from release_smoke_support import agent_plugin_mcp_responses

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
_EXPECTED_MINIMAL_TOOLS = (
    "mempalace_status",
    "mempalace_search",
    "mempalace_check_duplicate",
    "mempalace_add_drawer",
)


@pytest.mark.parametrize(
    ("installer", "manager", "eligible"),
    [
        (smoke.INSTALLER_VENV, "pip", False),
        (smoke.INSTALLER_PIPX, "pipx", True),
        (smoke.INSTALLER_UV_TOOL, "uv-tool", True),
        (smoke.INSTALLER_BOOTSTRAP_VENV, "bootstrap-venv", True),
    ],
)
def test_evaluate_smoke_reports_exact_manager_and_update_eligibility(installer, manager, eligible):
    surfaces = [
        smoke.SurfaceResult(name, smoke.STATUS_OK, "passed", VERSION)
        for name in smoke.REQUIRED_SURFACES
    ]

    result = smoke.evaluate_smoke(surfaces, PACKAGE, "candidate.whl", installer)

    assert result.ok is True
    assert result.manager == manager
    assert result.update_eligible is eligible


# ── Mock run_subprocess factories ───────────────────────────────────────────────


def _probe_output(version: str) -> str:
    return f"METADATA={version}\nMODULE={version}\n"


def _cli_output(version: str) -> str:
    return f"  Version checks:  enabled\n  Current version: {version}\n  PyPI URL: https://pypi.org/pypi/mempalace-code/json\n"


def _alias_probe_response(
    args: list,
    version: str = VERSION,
    target_path: Path | None = None,
) -> tuple[int, str, str] | None:
    if args and Path(args[0]).name == "mempalace-code-alias":
        alias_dir = Path(args[0]).parent
        alias_path = alias_dir / "mempalace"
        if alias_path.exists() or alias_path.is_symlink():
            alias_path.unlink()
        alias_path.symlink_to(target_path or alias_dir / "mempalace-code")
        return 0, "Alias ready\n", ""
    if "install-alias" in args:
        alias_dir = (
            Path(args[args.index("--target-dir") + 1])
            if "--target-dir" in args
            else Path(args[0]).parent
        )
        alias_dir.mkdir(parents=True, exist_ok=True)
        alias_path = alias_dir / "mempalace"
        if alias_path.exists() or alias_path.is_symlink():
            alias_path.unlink()
        alias_path.symlink_to(target_path or Path(args[0]))
        return 0, "Alias ready\n", ""
    if args and Path(str(args[0])).name == "mempalace" and "version-check" in args:
        return 0, _cli_output(version), ""
    return None


def _runtime_probe_output() -> str:
    return "usage: mempalace-code\nmigrate-storage\nRUNTIME-NO-CHROMADB=ok\n"


def _is_runtime_probe(args: list) -> bool:
    return "-c" in args and any("RUNTIME-NO-CHROMADB" in str(arg) for arg in args)


def _write_agent_plugin_fixture(plugin_root: Path, *, version: str = VERSION) -> None:
    (plugin_root / "skills" / "mempalace").mkdir(parents=True)
    (plugin_root / "schemas" / "1.0.0").mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": "mempalace-code",
                "version": version,
            }
        ),
        encoding="utf-8",
    )
    (plugin_root / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                "mcpServers": {
                    "mempalace-code": {
                        "type": "stdio",
                        "command": "mempalace-code-mcp",
                        "args": ["--profile=minimal"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (plugin_root / "skills" / "mempalace" / "SKILL.md").write_text(
        "---\nname: mempalace\ndescription: Minimal memory.\n---\n", encoding="utf-8"
    )
    (plugin_root / "schemas" / "1.0.0" / "plugin.schema.json").write_text(
        json.dumps({"$id": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"}),
        encoding="utf-8",
    )
    (plugin_root / "schemas" / "1.0.0" / "mcp.schema.json").write_text(
        json.dumps({"$id": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"}),
        encoding="utf-8",
    )
    (plugin_root / "schemas" / "SCHEMA-NOTICE.md").write_text(
        "Apache License 2.0\n", encoding="utf-8"
    )


def _venv_ok_subprocess(
    metadata_version: str = VERSION,
    module_version: str | None = None,
    cli_version: str | None = None,
    calls: list | None = None,
    plugin_root: Path | None = None,
):
    module_version = module_version if module_version is not None else metadata_version
    cli_version = cli_version if cli_version is not None else metadata_version

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        if calls is not None:
            calls.append({"args": args, "env": env, "cwd": cwd})
        alias_response = _alias_probe_response(args, version=cli_version)
        if alias_response is not None:
            return alias_response
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            if plugin_root is None:
                return 1, "", "agent-plugin path unavailable"
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if args and args[0] == "mempalace-code-mcp":
            return 0, agent_plugin_mcp_responses(_EXPECTED_MINIMAL_TOOLS), ""
        if "-c" in args:
            if _is_runtime_probe(args):
                return 0, _runtime_probe_output(), ""
            return (
                0,
                f"METADATA={metadata_version}\nMODULE={module_version}\n",
                "",
            )
        if "version-check" in args:
            return 0, _cli_output(cli_version), ""
        return 0, "", ""

    return run_subprocess


# ── Alias provenance ───────────────────────────────────────────────────────────


def test_alias_probe_uses_absolute_console_script_despite_conflicting_path(tmp_path):
    script_dir = tmp_path / "venv" / "bin"
    script_dir.mkdir(parents=True)
    console_bin = script_dir / "mempalace-code"
    console_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    console_bin.chmod(0o755)
    probe_cwd = tmp_path / "probe-cwd"
    probe_cwd.mkdir()
    calls: list = []
    launcher_seen = False

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        nonlocal launcher_seen
        calls.append({"args": args, "env": env, "cwd": cwd})
        if "install-alias" in args:
            assert env is not None
            conflict_path = Path(env["PATH"].split(os.pathsep)[0]) / "mempalace-code"
            launcher = Path(args[0])
            launcher_seen = conflict_path.exists() and launcher.is_symlink()
            assert launcher.samefile(console_bin)
            assert "--target-dir" not in args
        alias_response = _alias_probe_response(args)
        if alias_response is not None:
            return alias_response
        return 1, "", f"unexpected command: {args}"

    result = smoke.probe_alias_provenance(
        str(console_bin), str(probe_cwd), run_subprocess, env={"PATH": str(script_dir)}
    )

    assert result.status == smoke.STATUS_OK
    assert result.version == VERSION
    install_call = next(c for c in calls if "install-alias" in c["args"])
    installer_call = next(c for c in calls if Path(c["args"][0]).name == "mempalace-code-alias")
    assert Path(install_call["args"][0]).name == "mempalace-code"
    assert Path(install_call["args"][0]).is_absolute()
    path_parts = install_call["env"]["PATH"].split(os.pathsep)
    assert path_parts[0] != str(script_dir)
    assert launcher_seen is True
    assert path_parts[1] == str(Path(install_call["args"][0]).parent)
    assert "--target-dir" not in installer_call["args"]
    assert installer_call["env"]["PATH"].split(os.pathsep)[0] == path_parts[0]


def test_alias_probe_rejects_ambient_executable_version_match_without_samefile_target(tmp_path):
    script_dir = tmp_path / "venv" / "bin"
    script_dir.mkdir(parents=True)
    console_bin = script_dir / "mempalace-code"
    console_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    console_bin.chmod(0o755)
    probe_cwd = tmp_path / "probe-cwd"
    probe_cwd.mkdir()

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        if "install-alias" in args:
            assert env is not None
            ambient = Path(env["PATH"].split(os.pathsep)[0]) / "mempalace-code"
            return _alias_probe_response(args, target_path=ambient)
        if args and Path(str(args[0])).name == "mempalace" and "version-check" in args:
            return 0, _cli_output(VERSION), ""
        return 1, "", f"unexpected command: {args}"

    result = smoke.probe_alias_provenance(
        str(console_bin), str(probe_cwd), run_subprocess, env={"PATH": str(script_dir)}
    )

    assert result.status == smoke.STATUS_FAIL
    assert result.version is None
    assert "does not target the invoked mempalace-code" in result.detail


def test_alias_probe_rejects_dedicated_installer_bound_to_ambient_target(tmp_path):
    script_dir = tmp_path / "venv" / "bin"
    script_dir.mkdir(parents=True)
    console_bin = script_dir / "mempalace-code"
    console_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    console_bin.chmod(0o755)
    probe_cwd = tmp_path / "probe-cwd"
    probe_cwd.mkdir()

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        if args and Path(args[0]).name == "mempalace-code-alias":
            assert env is not None
            ambient = Path(env["PATH"].split(os.pathsep)[0]) / "mempalace-code"
            return _alias_probe_response(args, target_path=ambient)
        alias_response = _alias_probe_response(args)
        if alias_response is not None:
            return alias_response
        return 1, "", f"unexpected command: {args}"

    result = smoke.probe_alias_provenance(
        str(console_bin), str(probe_cwd), run_subprocess, env={"PATH": str(script_dir)}
    )

    assert result.status == smoke.STATUS_FAIL
    assert result.version is None
    assert "dedicated alias installer did not bind to its sibling" in result.detail


# ── AC-1 / VER-2: venv smoke success ────────────────────────────────────────────


def test_venv_smoke_reports_matching_metadata_module_and_cli_versions(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-forwarded")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-forwarded")
    calls: list = []
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    run_subprocess = _venv_ok_subprocess(calls=calls, plugin_root=plugin_root)

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is True
    assert result.expected_version == VERSION
    assert result.installer == smoke.INSTALLER_VENV
    assert result.install_spec == "."

    surface_names = {s.name for s in result.surfaces}
    assert surface_names == set(smoke.REQUIRED_SURFACES)
    for s in result.surfaces:
        assert s.status == smoke.STATUS_OK, f"{s.name} expected ok, got {s.status}: {s.detail}"
        if s.name == smoke.SURFACE_RUNTIME_NO_CHROMADB:
            # Behavioral surface: no version extracted; only status matters.
            assert s.version is None
        else:
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
    create_call = next(c for c in calls if "-m" in c["args"] and "venv" in c["args"])
    for call in (create_call, install_calls[0]):
        assert call["env"] is not None
        assert "OPENAI_API_KEY" not in call["env"]
        assert "ANTHROPIC_API_KEY" not in call["env"]
        assert "mempalace-install-smoke-" in call["env"]["HOME"]
    assert create_call["env"]["HOME"] == install_calls[0]["env"]["HOME"]

    human = smoke.render_human(result)
    assert "OK" in human
    assert VERSION in human


def test_venv_smoke_json_output_has_required_top_level_keys(tmp_path):
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    run_subprocess = _venv_ok_subprocess(plugin_root=plugin_root)
    result = smoke.run_venv_smoke("mempalace-code==" + VERSION, PACKAGE, run_subprocess)
    data = result.to_dict()

    for key in ("ok", "expected_version", "installer", "install_spec", "surfaces", "diagnostics"):
        assert key in data, f"missing top-level key {key!r}"

    assert data["ok"] is True
    assert data["expected_version"] == VERSION
    assert data["installer"] == smoke.INSTALLER_VENV
    assert data["manager"] == "pip"
    assert data["update_eligible"] is False
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


def test_pipx_smoke_uses_disposable_tool_environment(monkeypatch, tmp_path):
    calls: list = []
    FAKE_PIPX = "/fake/bin/pipx"
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)

    monkeypatch.setattr(smoke, "find_pipx_executable", lambda: FAKE_PIPX)

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        calls.append({"args": args, "env": env, "cwd": cwd})
        alias_response = _alias_probe_response(args)
        if alias_response is not None:
            return alias_response
        if any(a.endswith("pipx") for a in args) and "install" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if args and args[0] == "mempalace-code-mcp":
            return 0, agent_plugin_mcp_responses(_EXPECTED_MINIMAL_TOOLS), ""
        if "-c" in args:
            if _is_runtime_probe(args):
                return 0, _runtime_probe_output(), ""
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


def test_pipx_smoke_install_failure_is_diagnostic_not_ok(monkeypatch):
    fake_pipx = "/fake/bin/pipx"
    monkeypatch.setattr(smoke, "find_pipx_executable", lambda: fake_pipx)

    def run_subprocess(args, env=None, cwd=None):
        if fake_pipx in args and "install" in args:
            return 1, "", "No matching distribution found for mempalace-code==9.9.9"
        return 0, "", ""

    result = smoke.run_pipx_smoke("mempalace-code==9.9.9", PACKAGE, run_subprocess)

    assert result.ok is False
    assert result.installer == smoke.INSTALLER_PIPX
    assert any(s.status == smoke.STATUS_FAIL for s in result.surfaces)


# ── AC-3 / VER-4: mismatch diagnostics, reinstall command, sanitization ───────


def test_mismatch_failure_names_surfaces_and_reinstall_command_without_private_paths(tmp_path):
    fake_path = "/Users/testuser/secret-project"
    fake_token = "ghp_" + "A" * 30
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        alias_response = _alias_probe_response(args, version="1.2.3")
        if alias_response is not None:
            return alias_response
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if args and args[0] == "mempalace-code-mcp":
            return 0, agent_plugin_mcp_responses(_EXPECTED_MINIMAL_TOOLS), ""
        if "-c" in args:
            if _is_runtime_probe(args):
                return 0, _runtime_probe_output(), ""
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


def test_mismatch_between_module_and_cli_is_detected(tmp_path):
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    run_subprocess = _venv_ok_subprocess(
        metadata_version="2.0.0",
        module_version="2.0.0",
        cli_version="1.9.9",
        plugin_root=plugin_root,
    )

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    diag_text = "\n".join(result.diagnostics)
    assert smoke.SURFACE_CLI in diag_text
    assert "1.9.9" in diag_text
    assert "2.0.0" in diag_text


def test_stale_agent_plugin_version_is_detected(tmp_path):
    """A plugin.json left over from an old wheel/sdist build must fail the smoke."""
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root, version="0.9.0")
    run_subprocess = _venv_ok_subprocess(plugin_root=plugin_root)

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    diag_text = "\n".join(result.diagnostics)
    assert smoke.SURFACE_AGENT_PLUGIN in diag_text
    assert "0.9.0" in diag_text
    assert VERSION in diag_text


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


def test_sanitize_redacts_known_values_credential_urls_and_explicit_local_paths(tmp_path):
    secret = "opaque-session-value"
    diagnostic = (
        f"secret={secret} "
        "index=https://user:pass@example.invalid/simple "
        "api=https://example.invalid/data?token=abc123 "
        f"artifact={tmp_path}/candidate.whl"
    )

    sanitized = smoke.sanitize(
        diagnostic,
        known_secrets=(secret,),
        local_paths=(tmp_path,),
    )

    assert secret not in sanitized
    assert "user:pass" not in sanitized
    assert "token=abc123" not in sanitized
    assert str(tmp_path) not in sanitized
    assert sanitized.count("[REDACTED-URL]") == 2
    assert "[REDACTED-PATH]" in sanitized


# ── Agent Plugin sensitive-content scan ──────────────────────────────────────────


def test_sensitive_key_name_is_detected():
    assert smoke._contains_sensitive_content({"api_key": "whatever"}) is True


def test_sensitive_token_literal_in_value_is_detected():
    # Concatenated (not a contiguous literal) so this file itself never contains
    # a token-shaped substring for the repo's own public-safety scanner to flag.
    fake_token = "ghp_" + "B" * 30
    assert smoke._contains_sensitive_content({"note": fake_token}) is True


def test_sensitive_pypi_token_literal_in_nested_list_is_detected():
    fake_token = "pypi-" + "C" * 25
    assert smoke._contains_sensitive_content({"extra": ["fine", fake_token]}) is True


def test_credential_bearing_url_userinfo_is_detected():
    url = "https://" + "user" + ":" + "hunter2" + "@example.com/mcp"
    assert smoke._contains_sensitive_content({"homepage": url}) is True


def test_credential_bearing_url_query_param_is_detected():
    url = "https://example.com/api?" + "token" + "=" + "abc123def456"
    assert smoke._contains_sensitive_content({"repository": url}) is True


def test_plain_manifest_values_are_not_flagged():
    plugin_like = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "mempalace-code",
        "version": "1.13.1",
        "homepage": "https://github.com/rergards/mempalace-code",
        "keywords": ["agent-plugins", "mcp", "memory"],
    }
    assert smoke._contains_sensitive_content(plugin_like) is False


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


@pytest.mark.parametrize(
    ("command", "expected_timeout"),
    [
        (["/tmp/venv/bin/pip", "install", "--no-cache-dir", "."], 600),
        (["/tmp/bootstrap/bin/pip", "install", "--no-cache-dir", "."], 600),
        (["/opt/homebrew/bin/pipx", "install", "."], 600),
        (["/opt/homebrew/bin/uv", "tool", "install", "--force", "."], 600),
        (["/tmp/venv/bin/python", "-c", "print('probe')"], 300),
    ],
)
def test_default_subprocess_uses_install_specific_timeout(monkeypatch, command, expected_timeout):
    seen: list[int] = []

    def fake_run(args, **kwargs):
        seen.append(kwargs["timeout"])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    assert smoke._default_run_subprocess(command) == (0, "", "")
    assert seen == [expected_timeout]

    seen.clear()
    assert smoke._default_run_subprocess(command, timeout_seconds=42) == (0, "", "")
    assert seen == [42]


def test_main_json_flag_round_trips_through_mocked_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke.sys, "platform", "linux")
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    run_subprocess = _venv_ok_subprocess(plugin_root=plugin_root)
    seen_timeouts: list[int] = []

    def fake_default(
        args, env=None, cwd=None, input_text=None, timeout_seconds=smoke.DEFAULT_TIMEOUT_SECONDS
    ):
        seen_timeouts.append(timeout_seconds)
        return run_subprocess(args, env=env, cwd=cwd, input_text=input_text)

    monkeypatch.setattr(smoke, "_default_run_subprocess", fake_default)

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = smoke.main(["--install-spec", ".", "--json"])

    assert exit_code == 0
    data = json.loads(buf.getvalue())
    assert data["ok"] is True
    assert data["expected_version"] == VERSION
    assert data["installer"] == smoke.INSTALLER_VENV
    assert seen_timeouts == [None] * len(seen_timeouts)

    seen_timeouts.clear()
    with redirect_stdout(io.StringIO()):
        override_exit_code = smoke.main(
            ["--install-spec", ".", "--timeout-seconds", "42", "--json"]
        )
    assert override_exit_code == 0
    assert set(seen_timeouts) == {42}


def test_all_installers_runs_canonical_order_once(monkeypatch):
    calls = []

    def runner(installer):
        def run(
            install_spec,
            package,
            run_subprocess,
            *,
            recovery_safety=False,
            linux_lifecycle=False,
        ):
            calls.append((installer, install_spec, package, recovery_safety, linux_lifecycle))
            result = smoke.SmokeResult(True, VERSION, installer, install_spec, [], [])
            if linux_lifecycle:
                result.lifecycle = smoke.LinuxSystemdLifecycleResult(
                    smoke.LIFECYCLE_STATUS_PASS, "passed"
                )
            return result

        return run

    monkeypatch.setattr(smoke, "run_venv_smoke", runner(smoke.INSTALLER_VENV))
    monkeypatch.setattr(smoke, "run_bootstrap_venv_smoke", runner(smoke.INSTALLER_BOOTSTRAP_VENV))
    monkeypatch.setattr(smoke, "run_pipx_smoke", runner(smoke.INSTALLER_PIPX))
    monkeypatch.setattr(smoke, "run_uv_tool_smoke", runner(smoke.INSTALLER_UV_TOOL))
    monkeypatch.setattr(smoke, "find_pipx_executable", lambda: "/tools/pipx")
    monkeypatch.setattr(smoke, "find_uv_executable", lambda: "/tools/uv")

    result = smoke.run_all_installers_smoke("candidate.whl", PACKAGE, lambda *a, **k: None)

    assert result.ok is True
    assert [call[0] for call in calls] == list(smoke.INSTALLERS)
    assert all(call[1:4] == ("candidate.whl", PACKAGE, True) for call in calls)
    assert [call[4] for call in calls] == [False, False, False, True]
    assert result.linux_systemd_update_lifecycle.status == smoke.LIFECYCLE_STATUS_PASS


def test_all_installers_missing_tool_fails_with_recovery(monkeypatch):
    def runner(installer):
        def run(
            install_spec,
            package,
            run_subprocess,
            *,
            recovery_safety=False,
            linux_lifecycle=False,
        ):
            ok = installer != smoke.INSTALLER_PIPX
            surface = smoke.SurfaceResult(
                smoke.SURFACE_INSTALL,
                smoke.STATUS_OK if ok else smoke.STATUS_ERROR,
                "complete" if ok else "pipx unavailable",
                VERSION if ok else None,
            )
            result = smoke.SmokeResult(
                ok, VERSION if ok else None, installer, install_spec, [surface], []
            )
            if linux_lifecycle:
                result.lifecycle = smoke.LinuxSystemdLifecycleResult(
                    smoke.LIFECYCLE_STATUS_PASS, "passed"
                )
            return result

        return run

    for name, installer in (
        ("run_venv_smoke", smoke.INSTALLER_VENV),
        ("run_bootstrap_venv_smoke", smoke.INSTALLER_BOOTSTRAP_VENV),
        ("run_pipx_smoke", smoke.INSTALLER_PIPX),
        ("run_uv_tool_smoke", smoke.INSTALLER_UV_TOOL),
    ):
        monkeypatch.setattr(smoke, name, runner(installer))
    monkeypatch.setattr(smoke, "find_pipx_executable", lambda: None)
    monkeypatch.setattr(smoke, "find_uv_executable", lambda: "/tools/uv")

    result = smoke.run_all_installers_smoke("candidate.whl", PACKAGE, lambda *a, **k: None)

    assert result.ok is False
    assert result.diagnostics == [
        "pipx: required tool unavailable; recovery: python -m pip install pipx"
    ]


def _linux_lifecycle_runner(home: Path, *, false_pass: str | None = None):
    unit_dir = home / ".config" / "systemd" / "user"
    rendered = {
        "mempalace-update.service": "[Service]\nExecStart=exact\n",
        "mempalace-update.timer": "[Timer]\nOnCalendar=daily\n",
    }
    lifecycle_installed = False
    package_mutated = False

    def run(args, env=None, cwd=None):
        nonlocal lifecycle_installed, package_mutated
        action = args[1:]
        if action == ["update", "status", "--json"]:
            version = "0.0.0" if false_pass == "candidate" else VERSION
            return (
                0,
                json.dumps(
                    {
                        "ok": True,
                        "stage": "status",
                        "provenance": {"current_version": version},
                    }
                ),
                "",
            )
        if action == ["update", "apply", "--json"]:
            return (
                2,
                json.dumps(
                    {
                        "ok": False,
                        "stage": "confirmation",
                        "recovery_command": "mempalace-code update apply --yes --json",
                    }
                ),
                "",
            )
        if action == ["update", "scheduler", "install", "--yes", "--json"]:
            lifecycle_installed = True
            unit_dir.mkdir(parents=True, exist_ok=True)
            for name, content in rendered.items():
                (unit_dir / name).write_text(content, encoding="utf-8")
            return 0, json.dumps({"ok": True, "stage": "scheduler-installed"}), ""
        if args[0] == "/installed/bin/python" and args[1] == "-c":
            if "metadata.distribution" in args[2]:
                return (
                    0,
                    json.dumps(
                        {
                            "version": VERSION,
                            "sha256": ("b" if package_mutated else "a") * 64,
                            "files": 1,
                        }
                    ),
                    "",
                )
            return 0, json.dumps(rendered), ""
        if args[:3] == ["systemctl", "--user", "show"]:
            if not lifecycle_installed:
                return 0, "FragmentPath=\nLoadState=not-found\n", ""
            fragment = unit_dir / args[3]
            if false_pass == "fragment":
                fragment = home / "foreign" / args[3]
            return (
                0,
                f"FragmentPath={fragment}\nLoadState=loaded\n"
                "ActiveState=active\nUnitFileState=enabled\n",
                "",
            )
        if args[:3] in (
            ["systemctl", "--user", "is-enabled"],
            ["systemctl", "--user", "is-active"],
        ):
            if not lifecycle_installed:
                return (1, "disabled\n", "") if args[2] == "is-enabled" else (3, "inactive\n", "")
            return (1, "disabled\n", "") if false_pass == "manager-state" else (0, "ok\n", "")
        if action == ["update", "scheduler", "remove", "--yes", "--json"]:
            if false_pass != "cleanup":
                for name in rendered:
                    (unit_dir / name).unlink(missing_ok=True)
                lifecycle_installed = False
            return 0, json.dumps({"ok": True, "stage": "scheduler-removed"}), ""
        if action == ["update", "apply", "--yes", "--json"]:
            package_mutated = false_pass == "package"
            assert env is not None
            marker = Path(env["MEMPALACE_SOCKET_GUARD_LOADED"])
            attempts = Path(env["MEMPALACE_SOCKET_ATTEMPTS"])
            marker.write_text("loaded\n", encoding="utf-8")
            if false_pass != "network-guard":
                attempts.write_text("('pypi.org', 443)\n", encoding="utf-8")
            return (
                2,
                json.dumps(
                    {
                        "ok": False,
                        "stage": "preflight",
                        "message": "no newer stable compatible-major wheel is published and installed version is not proven current",
                    }
                ),
                "",
            )
        if args[0] == "systemd-run":
            return 0, f"{home}\n", ""
        raise AssertionError(f"unexpected lifecycle command: {args}")

    return run


def _live_boundary(home: Path):
    return lambda _console, _env: (
        {
            "uid_match": True,
            "home_match": True,
            "absolute_installed_console": True,
            "home": home,
        },
        None,
    )


def test_linux_systemd_lifecycle_happy_path(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    guard = tmp_path / "guard-loaded"
    attempts = tmp_path / "socket-attempts"

    result = smoke.run_linux_systemd_update_lifecycle(
        "/installed/bin/mempalace-code",
        "/installed/bin/python",
        VERSION,
        str(tmp_path),
        _linux_lifecycle_runner(home),
        {
            "MEMPALACE_SOCKET_GUARD_LOADED": str(guard),
            "MEMPALACE_SOCKET_ATTEMPTS": str(attempts),
        },
        boundary_probe=_live_boundary(home),
    )

    assert result.status == smoke.LIFECYCLE_STATUS_PASS
    assert result.recovery_command is None
    assert result.evidence == {
        "uid_match": True,
        "home_match": True,
        "absolute_installed_console": True,
        "manager_home_match": True,
        "candidate_version": VERSION,
        "status_read_only": True,
        "confirmation_read_only": True,
        "fragment_content_match": True,
        "timer_enabled": True,
        "timer_active": True,
        "repeat_idempotent": True,
        "confirmed_removal": True,
        "apply_terminal_stage": "preflight",
        "package_snapshot_unchanged": True,
        "network_attempt_blocked": True,
        "unauthorized_mutation": False,
        "cleanup_complete": True,
    }


@pytest.mark.parametrize(
    "false_pass",
    ["candidate", "fragment", "manager-state", "cleanup", "package", "network-guard"],
)
def test_linux_systemd_lifecycle_false_pass_matrix(tmp_path, false_pass):
    home = tmp_path / "home"
    home.mkdir()

    result = smoke.run_linux_systemd_update_lifecycle(
        "/installed/bin/mempalace-code",
        "/installed/bin/python",
        VERSION,
        str(tmp_path),
        _linux_lifecycle_runner(home, false_pass=false_pass),
        {
            "MEMPALACE_SOCKET_GUARD_LOADED": str(tmp_path / "guard-loaded"),
            "MEMPALACE_SOCKET_ATTEMPTS": str(tmp_path / "socket-attempts"),
        },
        boundary_probe=_live_boundary(home),
    )

    assert result.status == smoke.LIFECYCLE_STATUS_FAIL
    assert result.ok is False


def test_linux_systemd_lifecycle_unavailable_is_blocking_unrun(tmp_path):
    result = smoke.run_linux_systemd_update_lifecycle(
        "/installed/bin/mempalace-code",
        "/installed/bin/python",
        VERSION,
        str(tmp_path),
        lambda *_args, **_kwargs: pytest.fail("commands must not run without boundary evidence"),
        {},
        boundary_probe=lambda _console, _env: (None, "systemd-user manager unavailable"),
    )

    assert result.status == smoke.LIFECYCLE_STATUS_UNRUN
    assert result.ok is False
    assert result.detail == "systemd-user manager unavailable"
    assert result.recovery_command == smoke.LIFECYCLE_RECOVERY_COMMAND


def test_probe_environment_isolates_state_and_excludes_ambient_tools(tmp_path):
    script_dir = tmp_path / "install" / "bin"
    script_dir.mkdir(parents=True)
    base_env = smoke._credential_free_env()
    base_env["PATH"] = "/ambient/bin"
    env = smoke._isolate_probe_state(base_env, tmp_path, script_dir)

    assert env["PATH"] == os.pathsep.join((str(script_dir), os.defpath))
    assert "/ambient/bin" not in env["PATH"]
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert env["PIP_KEYRING_PROVIDER"] == "disabled"
    for name in (
        "HOME",
        "USERPROFILE",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "PIP_CACHE_DIR",
        "HF_HOME",
        "TRANSFORMERS_CACHE",
    ):
        assert Path(env[name]).is_dir()
        assert Path(env[name]).is_relative_to(tmp_path)


def test_recovery_refusals_require_exact_json_and_zero_mutation(tmp_path):
    state_root = tmp_path / "state"
    state_root.mkdir()

    def run_subprocess(args, env=None, cwd=None):
        action = " ".join(args[1:-1])
        payload = {
            "ok": False,
            "stage": "confirmation",
            "exit_code": 2,
            "recovery_command": f"mempalace-code {action} --yes --json",
        }
        return 2, json.dumps(payload), ""

    result = smoke._probe_recovery_refusals(
        "/install/bin/mempalace-code",
        str(tmp_path),
        run_subprocess,
        {"HOME": str(state_root)},
    )

    assert result.status == smoke.STATUS_OK
    assert list(state_root.iterdir()) == []


class TestUnsupportedPlatformUpdateProbe:
    @staticmethod
    def _status_payload() -> dict[str, object]:
        boundary = {
            "platform": "darwin",
            "required_platform": "linux",
            "service_manager": "systemd-user",
            "recovery_command": "mempalace-code update status --json",
        }
        return {
            "ok": True,
            "stage": "status",
            "installation": {"kind": "bootstrap-venv", "supported": True},
            "provenance": {"current_version": VERSION},
            "watcher": {"active": False, "supported": False, **boundary},
            "scheduler": {"enabled": False, "supported": False, **boundary},
            **boundary,
        }

    @staticmethod
    def _mutation_payload() -> dict[str, object]:
        return {
            "ok": False,
            "stage": "unsupported-platform",
            "message": "update mutations require Linux systemd-user; current platform is darwin",
            "exit_code": 2,
            "platform": "darwin",
            "required_platform": "linux",
            "service_manager": "systemd-user",
            "recovery_command": "mempalace-code update status --json",
        }

    def test_probe_invokes_exact_installed_console_commands(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smoke.sys, "platform", "darwin")
        home = tmp_path / "home"
        home.mkdir()
        calls: list[tuple[list[str], dict[str, str] | None, str | None]] = []

        def run_subprocess(args, env=None, cwd=None):
            calls.append((args, env, cwd))
            payload = (
                self._status_payload()
                if args[1:] == ["update", "status", "--json"]
                else self._mutation_payload()
            )
            return (0 if payload["ok"] else 2), json.dumps(payload), ""

        env = {"HOME": str(home)}
        result = smoke._probe_unsupported_platform_updates(
            "/installed/bin/mempalace-code", str(tmp_path), run_subprocess, env
        )

        assert result == smoke.SurfaceResult(
            smoke.SURFACE_UPDATE_PLATFORM,
            smoke.STATUS_OK,
            "status and all confirmed update mutations returned stable unsupported-platform JSON",
        )
        assert [call[0] for call in calls] == [
            ["/installed/bin/mempalace-code", "update", "status", "--json"],
            ["/installed/bin/mempalace-code", "update", "apply", "--yes", "--json"],
            [
                "/installed/bin/mempalace-code",
                "update",
                "scheduler",
                "install",
                "--yes",
                "--json",
            ],
            [
                "/installed/bin/mempalace-code",
                "update",
                "scheduler",
                "remove",
                "--yes",
                "--json",
            ],
        ]
        assert all(call[1] is env and call[2] == str(tmp_path) for call in calls)
        assert list(home.iterdir()) == []

    def test_probe_rejects_raw_executable_diagnostic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smoke.sys, "platform", "darwin")
        home = tmp_path / "home"
        home.mkdir()

        def run_subprocess(args, env=None, cwd=None):
            if args[1:] == ["update", "status", "--json"]:
                return 0, json.dumps(self._status_payload()), ""
            payload = self._mutation_payload()
            payload["message"] = "[Errno 2] systemctl executable missing"
            return 2, json.dumps(payload), ""

        result = smoke._probe_unsupported_platform_updates(
            "/installed/bin/mempalace-code",
            str(tmp_path),
            run_subprocess,
            {"HOME": str(home)},
        )

        assert result.status == smoke.STATUS_FAIL
        assert result.detail == (
            "confirmed update mutation did not return the unsupported-platform contract"
        )

    def test_probe_rejects_status_mutating_disposable_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(smoke.sys, "platform", "darwin")
        data_home = tmp_path / "xdg-data"
        data_home.mkdir()

        def run_subprocess(args, env=None, cwd=None):
            assert env is not None
            Path(env["XDG_DATA_HOME"], "application-state").write_text(
                "mutated\n", encoding="utf-8"
            )
            return 0, json.dumps(self._status_payload()), ""

        result = smoke._probe_unsupported_platform_updates(
            "/installed/bin/mempalace-code",
            str(tmp_path),
            run_subprocess,
            {"XDG_DATA_HOME": str(data_home)},
        )

        assert result == smoke.SurfaceResult(
            smoke.SURFACE_UPDATE_PLATFORM,
            smoke.STATUS_FAIL,
            "update status mutated disposable state",
        )

    @pytest.mark.parametrize(
        ("platform", "expected_recovery_safety"),
        [("darwin", True), ("linux", False)],
    )
    def test_main_enables_installed_probe_only_on_unsupported_hosts(
        self, monkeypatch, platform, expected_recovery_safety
    ):
        monkeypatch.setattr(smoke.sys, "platform", platform)
        calls: list[bool] = []

        def runner(install_spec, package, run_subprocess, *, recovery_safety=False):
            calls.append(recovery_safety)
            return smoke.SmokeResult(True, VERSION, smoke.INSTALLER_VENV, install_spec, [], [])

        monkeypatch.setattr(smoke, "run_venv_smoke", runner)

        with redirect_stdout(io.StringIO()):
            exit_code = smoke.main(["--install-spec", ".", "--json"])

        assert exit_code == 0
        assert calls == [expected_recovery_safety]


@pytest.mark.parametrize("target_name", ["sitecustomize.py", smoke._SITE_GUARD_PTH])
def test_version_guard_refuses_existing_guard_path_without_overwrite(tmp_path, target_name):
    site_dir = tmp_path / "site-packages"
    site_dir.mkdir()
    guard = site_dir / target_name
    guard.write_text("owned\n", encoding="utf-8")
    calls = []

    def run_subprocess(args, env=None, cwd=None):
        calls.append(args)
        return 0, json.dumps([str(site_dir)]), ""

    result = smoke._probe_version_check_no_network(
        "/install/bin/python",
        "/install/bin/mempalace-code",
        str(tmp_path),
        tmp_path,
        run_subprocess,
        {},
    )

    assert result.status == smoke.STATUS_FAIL
    assert guard.read_text(encoding="utf-8") == "owned\n"
    assert len(calls) == 1


def test_interpreter_site_guard_loads_and_records_all_socket_paths(tmp_path):
    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv_dir)], check=True)
    python_bin = venv_dir / "bin" / "python"
    site_paths = json.loads(
        subprocess.run(
            [python_bin, "-c", smoke._SITE_PACKAGES_SCRIPT],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert len(site_paths) == 1
    site_dir = Path(site_paths[0])
    guard = site_dir / "sitecustomize.py"
    guard.write_text(smoke._SITE_GUARD, encoding="utf-8")
    (site_dir / smoke._SITE_GUARD_PTH).write_text(
        f"import runpy; runpy.run_path({str(guard)!r})\n", encoding="utf-8"
    )
    marker = tmp_path / "loaded"
    attempts = tmp_path / "attempts"
    env = os.environ.copy()
    env.update(
        {
            "MEMPALACE_SOCKET_GUARD_LOADED": str(marker),
            "MEMPALACE_SOCKET_ATTEMPTS": str(attempts),
        }
    )
    program = (
        "import socket\n"
        "try:\n socket.create_connection(('example.invalid', 80))\nexcept OSError:\n pass\n"
        "try:\n socket.socket().connect(('example.invalid', 80))\nexcept OSError:\n pass\n"
        "try:\n socket.socket().connect_ex(('example.invalid', 80))\nexcept OSError:\n pass\n"
    )

    result = subprocess.run([python_bin, "-c", program], capture_output=True, text=True, env=env)

    assert result.returncode == 0
    assert marker.is_file(), (result.stdout, result.stderr, str(site_dir))
    assert marker.read_text(encoding="utf-8") == "loaded\n"
    assert len(attempts.read_text(encoding="utf-8").splitlines()) == 3


# ── AC-9 / VER-7: uv-tool skip, notification probes, bootstrap-venv layout ────


def test_uv_tool_smoke_reports_explicit_error_when_uv_unavailable(monkeypatch):
    monkeypatch.setattr(smoke, "find_uv_executable", lambda: None)

    result = smoke.run_uv_tool_smoke(".", PACKAGE, lambda *args, **kwargs: (0, "", ""))

    assert result.ok is False
    assert result.installer == smoke.INSTALLER_UV_TOOL
    assert result.surfaces[0].status == smoke.STATUS_ERROR
    assert "uv not found" in result.surfaces[0].detail


def test_uv_tool_smoke_uses_disposable_tool_dirs_and_neutral_cwd(monkeypatch, tmp_path):
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    calls: list[tuple[list[str], dict[str, str] | None, str | None]] = []
    lifecycle_envs: list[dict[str, str]] = []
    monkeypatch.setattr(smoke, "find_uv_executable", lambda: "/test/bin/uv")

    def lifecycle_runner(
        console_bin,
        python_bin,
        expected_version,
        probe_cwd,
        run_subprocess,
        env,
    ):
        lifecycle_envs.append(env)
        return smoke.LinuxSystemdLifecycleResult(smoke.LIFECYCLE_STATUS_PASS, "passed")

    monkeypatch.setattr(smoke, "run_linux_systemd_update_lifecycle", lifecycle_runner)

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        calls.append((args, env, cwd))
        alias_response = _alias_probe_response(args)
        if alias_response is not None:
            return alias_response
        if args[:4] == ["/test/bin/uv", "tool", "install", "--force"]:
            assert env is not None
            tool_python = Path(env["UV_TOOL_DIR"]) / PACKAGE / "bin" / "python"
            tool_python.parent.mkdir(parents=True)
            tool_python.touch()
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if args and args[0].endswith("mempalace-code-mcp"):
            return 0, agent_plugin_mcp_responses(_EXPECTED_MINIMAL_TOOLS), ""
        if "-c" in args:
            if _is_runtime_probe(args):
                return 0, _runtime_probe_output(), ""
            return 0, f"METADATA={VERSION}\nMODULE={VERSION}\n", ""
        if "version-check" in args:
            return 0, _cli_output(VERSION), ""
        return 1, "", f"unexpected command: {args}"

    result = smoke.run_uv_tool_smoke(".", PACKAGE, run_subprocess, linux_lifecycle=True)

    assert result.ok is True
    assert result.installer == smoke.INSTALLER_UV_TOOL
    install_call = next(call for call in calls if call[0][0] == "/test/bin/uv")
    install_env = install_call[1]
    assert install_env is not None
    assert {"UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_CACHE_DIR"} <= install_env.keys()
    assert all(str(tmp_path) not in install_env[key] for key in ("UV_TOOL_DIR", "UV_TOOL_BIN_DIR"))
    assert len(lifecycle_envs) == 1
    lifecycle_path = lifecycle_envs[0]["PATH"].split(os.pathsep)
    assert lifecycle_path[:2] == [install_env["UV_TOOL_BIN_DIR"], "/test/bin"]
    assert lifecycle_path[2:] == os.defpath.split(os.pathsep)
    probe_cwds = [cwd for _args, _env, cwd in calls if cwd is not None]
    assert probe_cwds
    assert all(str(ROOT) not in cwd for cwd in probe_cwds)


def test_venv_smoke_probes_version_check_status_for_executable_reporting(tmp_path):
    """The venv smoke uses 'version-check --status' (executable-based) for CLI version.

    This proves the smoke can report CLI version from an isolated install without
    relying on ambient system python3 to import mempalace_code.
    """
    plugin_root = tmp_path / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    calls: list = []

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        calls.append(args)
        alias_response = _alias_probe_response(args)
        if alias_response is not None:
            return alias_response
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if args and args[0] == "mempalace-code-mcp":
            return 0, agent_plugin_mcp_responses(_EXPECTED_MINIMAL_TOOLS), ""
        if "-c" in args:
            if _is_runtime_probe(args):
                return 0, _runtime_probe_output(), ""
            return 0, f"METADATA={VERSION}\nMODULE={VERSION}\n", ""
        if "version-check" in args:
            return 0, _cli_output(VERSION), ""
        return 0, "", ""

    result = smoke.run_venv_smoke(".", PACKAGE, run_subprocess)
    assert result.ok is True

    # The smoke must have invoked the CLI with 'version-check' (executable-based)
    cli_calls = [c for c in calls if "version-check" in c]
    assert cli_calls, (
        "venv smoke must probe CLI version via 'version-check' (installed executable), "
        "not only via python -c import"
    )
    cli_surface = next((s for s in result.surfaces if s.name == smoke.SURFACE_CLI), None)
    assert cli_surface is not None
    assert cli_surface.version == VERSION


def test_bootstrap_venv_layout_probes_from_neutral_directory(tmp_path):
    """Bootstrap-venv smoke mimics ~/.mempalace/venv topology and probes from neutral cwd.

    The probe cwd must not contain the source checkout path to prevent
    pyproject.toml shadowing the installed package.
    """
    plugin_root = tmp_path / "fake_home" / ".mempalace" / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    probe_cwds: list[str] = []
    create_calls: list[tuple[list[str], dict[str, str] | None]] = []

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        if cwd is not None:
            probe_cwds.append(cwd)
        alias_response = _alias_probe_response(args)
        if alias_response is not None:
            return alias_response
        if "-m" in args and "venv" in args:
            create_calls.append((args, env))
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if args and args[0] == "mempalace-code-mcp":
            return 0, agent_plugin_mcp_responses(_EXPECTED_MINIMAL_TOOLS), ""
        if "-c" in args:
            if _is_runtime_probe(args):
                return 0, _runtime_probe_output(), ""
            return 0, f"METADATA={VERSION}\nMODULE={VERSION}\n", ""
        if "version-check" in args:
            return 0, _cli_output(VERSION), ""
        return 0, "", ""

    result = smoke.run_bootstrap_venv_smoke(".", PACKAGE, run_subprocess)
    assert result.ok is True
    assert result.installer == smoke.INSTALLER_BOOTSTRAP_VENV
    assert len(create_calls) == 1
    create_args, create_env = create_calls[0]
    assert create_args[-1].endswith("/home/.mempalace/venv")
    assert create_env is not None
    assert create_args[-1].startswith(create_env["HOME"])

    # Every probe cwd that was recorded must not be the source checkout root
    source_root = str(ROOT)
    for cwd in probe_cwds:
        assert source_root not in cwd, (
            f"probe cwd {cwd!r} must not be inside the source checkout {source_root!r}"
        )


def test_bootstrap_venv_install_timeout_fails_closed_with_installer_detail():
    def run_subprocess(args, env=None, cwd=None):
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 124, "", "pip timed out after 600s"
        raise AssertionError(f"unexpected command after failed install: {args}")

    result = smoke.run_bootstrap_venv_smoke(".", PACKAGE, run_subprocess)

    assert result.ok is False
    assert result.installer == smoke.INSTALLER_BOOTSTRAP_VENV
    assert result.surfaces[0].name == smoke.SURFACE_INSTALL
    assert result.surfaces[0].status == smoke.STATUS_FAIL
    assert result.surfaces[0].detail == "install failed: pip timed out after 600s"


def test_candidate_extra_metadata_reconciliation_fails_closed(tmp_path):
    expected_root = tmp_path / "venv"
    payload = {
        "version": "1.2.3",
        "root": str(expected_root / "lib" / "python" / "site-packages"),
        "provides_extra": [
            "dev",
            "spellcheck",
            "watch",
            "treesitter",
            "chroma-migration",
            "chroma",
        ],
    }

    def probe(candidate):
        def run(_command, **_kwargs):
            return 0, json.dumps(candidate), ""

        return smoke.probe_candidate_extra_metadata(
            "/candidate/bin/python",
            str(tmp_path),
            run,
            expected_root=str(expected_root),
            expected_version="1.2.3",
        )

    result = probe(payload)
    assert result.ok is True
    assert result.extras == (
        "chroma",
        "chroma-migration",
        "dev",
        "spellcheck",
        "treesitter",
        "watch",
    )
    assert result.runtime_extras == (
        "chroma",
        "chroma-migration",
        "spellcheck",
        "treesitter",
        "watch",
    )
    hostile = [
        {**payload, "provides_extra": []},
        {**payload, "provides_extra": ["dev", "watch", "watch"]},
        {**payload, "provides_extra": ["dev", "bad_name"]},
        {**payload, "root": str(tmp_path / "source")},
        {**payload, "version": "9.9.9"},
        {**payload, "unexpected": True},
    ]
    for candidate in hostile:
        failed = probe(candidate)
        assert failed.ok is False
        assert failed.runtime_extras == ()
        assert str(tmp_path) not in failed.detail

    def raw_probe(returncode, stdout, stderr):
        def run(_command, **_kwargs):
            return returncode, stdout, stderr

        return smoke.probe_candidate_extra_metadata("/candidate/bin/python", str(tmp_path), run)

    for failed in (
        raw_probe(1, "", "probe failed"),
        raw_probe(0, json.dumps(payload), "unexpected stderr"),
        raw_probe(0, "not-json", ""),
        raw_probe(0, "x" * (smoke._EXTRA_METADATA_OUTPUT_LIMIT + 1), ""),
        raw_probe(0, json.dumps([payload]), ""),
        raw_probe(0, json.dumps({**payload, "provides_extra": [1]}), ""),
    ):
        assert failed.ok is False
        assert failed.extras == ()
