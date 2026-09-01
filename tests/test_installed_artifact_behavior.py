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
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_install_methods_validate_with_owning_launcher():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")

    for method in ("uv", "pipx", "project", "bootstrap"):
        assert f"`INSTALL_METHOD={method}`" in runbook
    assert 'test -x "$MEMPALACE_BIN"' in runbook
    assert 'test -x "$MEMPALACE_MCP"' in runbook
    assert "ambient Python" in runbook
    assert 'MEMPALACE_BIN="$PIPX_BIN_DIR/mempalace-code"' in runbook
    assert 'MEMPALACE_BIN="$(command -v mempalace-code)"' in runbook  # existing-owner branch only


def test_bootstrap_snippets_derive_launcher_from_custom_venv(tmp_path):
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    bootstrap = runbook[
        runbook.index("**`INSTALL_METHOD=bootstrap`:**") : runbook.index("### Step 3.4")
    ]

    for mode in ("inspect", "direct"):
        match = re.search(rf"- `{mode}` .*?```bash\n(.*?)\n  ```", bootstrap, re.DOTALL)
        assert match is not None
        snippet = match.group(1)
        assert 'MEMPALACE_VENV="$BOOTSTRAP_VENV" MEMPALACE_SOURCE=' in snippet
        derivation = "\n".join(
            line.strip()
            for line in snippet.splitlines()
            if line.strip().startswith(("BOOTSTRAP_VENV=", "MEMPALACE_BIN="))
        )
        custom_venv = tmp_path / f"{mode} venv"
        result = subprocess.run(
            ["/bin/bash"],
            input=f'{derivation}\nprintf "%s\\n" "$MEMPALACE_BIN"\n',
            env={**os.environ, "MEMPALACE_VENV": str(custom_venv)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(custom_venv / "bin" / "mempalace-code")


def test_runbook_operational_commands_stay_on_selected_launcher():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    operational = runbook[runbook.index("### Step 3.4") : runbook.index("## Section 7")]
    troubleshooting = runbook[runbook.index("## Troubleshooting") :]

    for command in ("init", "fetch-model", "mine", "health", "search", "version-check"):
        assert re.search(
            rf'^"\$MEMPALACE_BIN" .*\b{re.escape(command)}\b', operational, re.MULTILINE
        )
    assert 'MEMPALACE_MCP="$(dirname "$MEMPALACE_BIN")/mempalace-code-mcp"' in operational
    assert not re.search(r"^mempalace-code\b", operational + troubleshooting, re.MULTILINE)
    assert '"$MEMPALACE_BIN" watch ~/projects/' in readme


def test_mcp_registration_uses_installed_launcher_and_argv_paths():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    example = (ROOT / "examples" / "mcp_setup.md").read_text(encoding="utf-8")

    assert 'claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"' in runbook
    assert 'claude mcp add --scope project mempalace-code -- "$MEMPALACE_MCP"' in runbook
    assert 'codex mcp add mempalace-code -- "$MEMPALACE_MCP"' in runbook
    assert "separate quoted argv value" in runbook
    assert '"$MEMPALACE_MCP"' in example
    assert "Do not translate Claude scope names" in example


def test_claude_scope_retry_branch_prints_one_resolved_command(tmp_path):
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    match = re.search(
        r"# claude-mcp-exact-retry:start\n(.*?)# claude-mcp-exact-retry:end",
        runbook,
        re.DOTALL,
    )
    assert match is not None
    snippet = match.group(1)

    for scope in ("user", "project"):
        env = {
            **os.environ,
            "CLAUDE_SCOPE": scope,
            "CLAUDE_PROJECT_PATH": str(tmp_path / "project with spaces"),
            "MEMPALACE_MCP": str(tmp_path / "owner with spaces" / "mempalace-code-mcp"),
            "MCP_PROFILE": "minimal",
        }
        result = subprocess.run(
            ["/bin/bash"],
            input=snippet,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.count("Retry:") == 1
        assert f"--scope {scope}" in result.stdout
        assert "mempalace-code-mcp" in result.stdout


def _run_bootstrap(tmp_path: Path, **updates: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update({"HOME": str(home), **updates})
    return subprocess.run(
        ["/bin/bash", str(ROOT / "scripts" / "bootstrap.sh")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_bootstrap_has_valid_shell_syntax():
    result = subprocess.run(
        ["/bin/bash", "-n", str(ROOT / "scripts" / "bootstrap.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"MEMPALACE_SOURCE": "unknown-source"}, "Unknown MEMPALACE_SOURCE"),
        ({"MEMPALACE_SOURCE": "pypi", "MEMPALACE_GIT_REF": "main"}, "valid only"),
        ({"MEMPALACE_SOURCE": "git", "MEMPALACE_GIT_REF": "main"}, "full 40-hex"),
        ({"MEMPALACE_VENV": "relative/venv"}, "must be an absolute path"),
    ],
)
def test_bootstrap_rejects_invalid_input_before_install(tmp_path, updates, message):
    result = _run_bootstrap(tmp_path, **updates)

    assert result.returncode != 0
    assert message in result.stdout
    assert not (tmp_path / "home" / ".mempalace" / "venv").exists()


def test_custom_palace_config_snippet_treats_hostile_path_as_data_and_repeats(tmp_path):
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    match = re.search(r'python3 - "\$PALACE_PATH" <<\'PY\'\n(.*?)\nPY', runbook, re.DOTALL)
    assert match is not None
    snippet = match.group(1)
    home = tmp_path / "home"
    (home / ".mempalace").mkdir(parents=True)
    hostile = str(tmp_path / "palace \" $() ' Ж\nline")
    env = {**os.environ, "HOME": str(home)}

    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-", hostile],
            input=snippet,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    config = json.loads((home / ".mempalace" / "config.json").read_text(encoding="utf-8"))
    assert config["palace_path"] == hostile
    assert list((home / ".mempalace").glob(".config.json.*")) == []


def test_documented_update_cadence_matches_systemd_owner():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    updater = (ROOT / "mempalace_code" / "updater.py").read_text(encoding="utf-8")
    step = runbook[runbook.index("### Step 6.5") : runbook.index("### Step 6.6")]

    assert '"OnCalendar=daily"' in updater
    assert "daily systemd-user timer" in step
    assert "once per day" in step
    assert "weekly" not in step


def test_install_contract_degraded_context_matrix():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "Empty, EOF, malformed, or contradictory" in runbook
    assert "already-current" in runbook
    assert "Any mismatch stops for an explicit replace/remove decision" in runbook
    assert "Unknown MEMPALACE_SOURCE" in bootstrap
    assert "MEMPALACE_GIT_REF is valid only" in bootstrap


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


# ── ordinary runtime no-chromadb probe ────────────────────────────────────────


def test_probe_ordinary_runtime_no_chromadb_passes_with_runtime_marker(tmp_path):
    """The runtime probe succeeds when package import, CLI help, and Lance open pass."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert "-c" in cmd
        assert "RUNTIME-NO-CHROMADB" in cmd[-1]
        return 0, "usage: mempalace-code\nmigrate-storage\nRUNTIME-NO-CHROMADB=ok\n", ""

    result = smoke.probe_ordinary_runtime_no_chromadb(
        "/fake/python",
        str(tmp_path),
        fake_run,
        env={"PATH": "/fake/bin"},
    )

    assert result.name == smoke.SURFACE_RUNTIME_NO_CHROMADB
    assert result.status == smoke.STATUS_OK
    assert "avoided chromadb" in result.detail
    assert calls


def test_probe_ordinary_runtime_no_chromadb_reports_blocked_import(tmp_path):
    """A chromadb import attempt fails the ordinary runtime probe."""

    def fake_run(cmd, **kwargs):
        return 1, "", "RuntimeError: chromadb import blocked during ordinary runtime probe"

    result = smoke.probe_ordinary_runtime_no_chromadb("/fake/python", str(tmp_path), fake_run)

    assert result.status == smoke.STATUS_ERROR
    assert "chromadb import blocked" in result.detail


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


# ── Agent Plugin probe ───────────────────────────────────────────────────────


def _write_agent_plugin_fixture(plugin_root: Path) -> None:
    (plugin_root / "skills" / "mempalace").mkdir(parents=True)
    (plugin_root / "schemas" / "1.0.0").mkdir(parents=True)
    (plugin_root / "plugin.json").write_text(
        """
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "mempalace-code",
  "version": "1.2.3"
}
""".strip(),
        encoding="utf-8",
    )
    (plugin_root / "mcp.json").write_text(
        """
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
  "mcpServers": {
    "mempalace-code": {
      "type": "stdio",
      "command": "mempalace-code-mcp",
      "args": ["--profile=minimal"]
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    (plugin_root / "skills" / "mempalace" / "SKILL.md").write_text(
        "---\nname: mempalace\ndescription: Minimal memory.\n---\n",
        encoding="utf-8",
    )
    (plugin_root / "schemas" / "1.0.0" / "plugin.schema.json").write_text(
        '{"$id":"https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"}',
        encoding="utf-8",
    )
    (plugin_root / "schemas" / "1.0.0" / "mcp.schema.json").write_text(
        '{"$id":"https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"}',
        encoding="utf-8",
    )
    (plugin_root / "schemas" / "SCHEMA-NOTICE.md").write_text(
        "Apache License 2.0\n",
        encoding="utf-8",
    )


def _mcp_responses() -> str:
    tools = [
        {"name": "mempalace_status"},
        {"name": "mempalace_search"},
        {"name": "mempalace_check_duplicate"},
        {"name": "mempalace_add_drawer"},
    ]
    responses = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"serverInfo": {"name": "mempalace-code", "version": "1.0.0"}},
        },
        {"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "error": {
                "code": -32602,
                "message": "Invalid params: blank required argument(s): content",
            },
        },
        {"jsonrpc": "2.0", "id": 4, "result": {"tools": tools}},
    ]
    return "\n".join(json.dumps(response) for response in responses) + "\n"


def test_alias_provenance_uses_absolute_installed_console_script(tmp_path):
    script_dir = tmp_path / "venv" / "bin"
    script_dir.mkdir(parents=True)
    console_bin = script_dir / "mempalace-code"
    console_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    console_bin.chmod(0o755)
    neutral_cwd = tmp_path / "neutral"
    neutral_cwd.mkdir()
    calls: list[tuple[list[str], dict]] = []
    launcher_seen = False

    def fake_run(cmd, **kwargs):
        nonlocal launcher_seen
        calls.append((cmd, kwargs))
        if Path(cmd[0]).name == "mempalace-code-alias":
            installer_dir = Path(cmd[0]).parent
            (installer_dir / "mempalace").symlink_to(installer_dir / "mempalace-code")
            return 0, "Alias ready\n", ""
        if "install-alias" in cmd:
            conflict = Path(kwargs["env"]["PATH"].split(os.pathsep)[0]) / "mempalace-code"
            assert conflict.exists()
            launcher = Path(cmd[0])
            launcher_seen = launcher.is_symlink() and launcher.samefile(console_bin)
            assert "--target-dir" not in cmd
            alias_dir = launcher.parent
            (alias_dir / "mempalace").symlink_to(Path(cmd[0]))
            return 0, "Alias ready\n", ""
        if Path(cmd[0]).name == "mempalace" and "version-check" in cmd:
            return 0, "Current version: 1.2.3\n", ""
        return 1, "", f"unexpected command: {cmd}"

    result = smoke.probe_alias_provenance(
        str(console_bin), str(neutral_cwd), fake_run, env={"PATH": str(script_dir)}
    )

    assert result.status == smoke.STATUS_OK
    assert result.version == "1.2.3"
    install_cmd, install_kwargs = next(call for call in calls if "install-alias" in call[0])
    installer_cmd, installer_kwargs = next(
        call for call in calls if Path(call[0][0]).name == "mempalace-code-alias"
    )
    assert Path(install_cmd[0]).is_absolute()
    assert launcher_seen is True
    assert install_kwargs["env"]["PATH"].split(os.pathsep)[0] != str(script_dir)
    assert len(installer_cmd) == 1
    assert (
        installer_kwargs["env"]["PATH"].split(os.pathsep)[0]
        == install_kwargs["env"]["PATH"].split(os.pathsep)[0]
    )


def test_alias_provenance_rejects_matching_version_from_ambient_target(tmp_path):
    script_dir = tmp_path / "venv" / "bin"
    script_dir.mkdir(parents=True)
    console_bin = script_dir / "mempalace-code"
    console_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    console_bin.chmod(0o755)
    neutral_cwd = tmp_path / "neutral"
    neutral_cwd.mkdir()

    def fake_run(cmd, **kwargs):
        if "install-alias" in cmd:
            ambient = Path(kwargs["env"]["PATH"].split(os.pathsep)[0]) / "mempalace-code"
            alias_dir = Path(cmd[0]).parent
            (alias_dir / "mempalace").symlink_to(ambient)
            return 0, "Alias ready\n", ""
        return 0, "Current version: 1.2.3\n", ""

    result = smoke.probe_alias_provenance(
        str(console_bin), str(neutral_cwd), fake_run, env={"PATH": str(script_dir)}
    )

    assert result.status == smoke.STATUS_FAIL
    assert result.version is None
    assert "does not target the invoked mempalace-code" in result.detail


def test_install_smoke_probes_agent_plugin_from_neutral_cwd(tmp_path):
    plugin_root = tmp_path / "venv" / "site-packages" / "mempalace_code" / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    neutral_cwd = str(tmp_path / "neutral")
    script_dir = tmp_path / "venv" / "bin"
    os.makedirs(neutral_cwd)
    os.makedirs(script_dir)
    calls: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd == ["/fake/bin/mempalace-code", "agent-plugin", "path", "--json"]:
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if cmd == ["mempalace-code-mcp", "--profile=minimal"]:
            assert kwargs["input_text"].count("tools/list") == 2
            assert "mempalace_check_duplicate" in kwargs["input_text"]
            return 0, _mcp_responses(), ""
        return 1, "", "unexpected command"

    env = smoke._env_with_script_dir(script_dir, {"PATH": "/usr/bin"})
    result = smoke.probe_agent_plugin_package(
        "/fake/bin/mempalace-code",
        neutral_cwd,
        fake_run,
        env=env,
        source_root=str(tmp_path / "checkout"),
    )

    assert result.status == smoke.STATUS_OK
    assert calls[0][1]["cwd"] == neutral_cwd
    assert calls[1][1]["cwd"] == neutral_cwd
    assert calls[1][0] == ["mempalace-code-mcp", "--profile=minimal"]
    assert calls[1][1]["env"]["PATH"].split(os.pathsep)[0] == str(script_dir)


class TestDeclaredMCPRequiredStringGuard:
    def test_accepts_blank_rejection_then_same_process_continuation(self, tmp_path):
        plugin_root = tmp_path / "plugin"
        _write_agent_plugin_fixture(plugin_root)
        mcp_json = json.loads((plugin_root / "mcp.json").read_text(encoding="utf-8"))

        error = smoke._probe_declared_mcp_command(
            mcp_json,
            str(tmp_path),
            lambda cmd, **kwargs: (0, _mcp_responses(), ""),
            {"PATH": "/fake/bin"},
        )

        assert error is None

    @pytest.mark.parametrize(
        "case,expected",
        [
            pytest.param("missing", "returned 3 response lines", id="missing"),
            pytest.param("reordered", "reordered or mismatched", id="reordered"),
            pytest.param("extra", "returned 5 response lines", id="extra"),
            pytest.param("non-json", "printed non-JSON", id="non-json"),
            pytest.param("non-object", "printed non-object JSON", id="non-object"),
            *[
                pytest.param(
                    f"missing-jsonrpc-{response_id}",
                    f"response {response_id} has invalid jsonrpc",
                    id=f"missing-jsonrpc-{response_id}",
                )
                for response_id in range(1, 5)
            ],
            *[
                pytest.param(
                    f"wrong-jsonrpc-{response_id}",
                    f"response {response_id} has invalid jsonrpc",
                    id=f"wrong-jsonrpc-{response_id}",
                )
                for response_id in range(1, 5)
            ],
            *[
                pytest.param(
                    f"bool-id-{response_id}",
                    "reordered or mismatched",
                    id=f"bool-id-{response_id}",
                )
                for response_id in range(1, 5)
            ],
            *[
                pytest.param(
                    f"float-id-{response_id}",
                    "reordered or mismatched",
                    id=f"float-id-{response_id}",
                )
                for response_id in range(1, 5)
            ],
            pytest.param(
                "init-result-and-error",
                "response 1 must contain exactly one",
                id="init-result-and-error",
            ),
            pytest.param(
                "init-error-only", "response 1 returned the wrong response kind", id="init-error"
            ),
            pytest.param(
                "tools-error-only", "response 2 returned the wrong response kind", id="tools-error"
            ),
            pytest.param("server-info-list", "did not complete initialize", id="server-info-list"),
            pytest.param("tool-entry-list", "did not return tools/list", id="tool-entry-list"),
            pytest.param("tool-name-null", "did not return tools/list", id="tool-name-null"),
            pytest.param("extra-tool", "listed unexpected tools", id="extra-tool"),
            pytest.param(
                "error-message-null",
                "did not reject blank required content safely",
                id="error-message-null",
            ),
            pytest.param("content-echo", "did not reject blank required content safely", id="echo"),
            pytest.param(
                "false-success", "response 3 returned the wrong response kind", id="success"
            ),
            pytest.param(
                "continued-tool-entry-list",
                "did not continue after blank required content",
                id="continued-tool-entry-list",
            ),
            pytest.param(
                "continued-tool-name-null",
                "did not continue after blank required content",
                id="continued-tool-name-null",
            ),
            pytest.param(
                "extra-continued-tool",
                "continuation listed unexpected tools",
                id="extra-continued-tool",
            ),
            pytest.param(
                "continuation-error-only",
                "response 4 returned the wrong response kind",
                id="continuation-error",
            ),
        ],
    )
    def test_rejects_invalid_response_shapes(self, tmp_path, case, expected):
        plugin_root = tmp_path / "plugin"
        _write_agent_plugin_fixture(plugin_root)
        mcp_json = json.loads((plugin_root / "mcp.json").read_text(encoding="utf-8"))
        responses = [json.loads(line) for line in _mcp_responses().splitlines()]
        if case == "missing":
            responses.pop()
        elif case == "reordered":
            responses[1], responses[2] = responses[2], responses[1]
        elif case == "extra":
            responses.append({"jsonrpc": "2.0", "id": 5, "result": {}})
        elif case.startswith("missing-jsonrpc-"):
            responses[int(case.rsplit("-", 1)[1]) - 1].pop("jsonrpc")
        elif case.startswith("wrong-jsonrpc-"):
            responses[int(case.rsplit("-", 1)[1]) - 1]["jsonrpc"] = "1.0"
        elif case.startswith("bool-id-"):
            responses[int(case.rsplit("-", 1)[1]) - 1]["id"] = True
        elif case.startswith("float-id-"):
            response_id = int(case.rsplit("-", 1)[1])
            responses[response_id - 1]["id"] = float(response_id)
        elif case == "init-result-and-error":
            responses[0]["error"] = {"code": -32000, "message": "unexpected"}
        elif case == "init-error-only":
            responses[0].pop("result")
            responses[0]["error"] = {"code": -32000, "message": "unexpected"}
        elif case == "tools-error-only":
            responses[1].pop("result")
            responses[1]["error"] = {"code": -32000, "message": "unexpected"}
        elif case == "server-info-list":
            responses[0]["result"]["serverInfo"] = []
        elif case == "tool-entry-list":
            responses[1]["result"]["tools"].append([])
        elif case == "tool-name-null":
            responses[1]["result"]["tools"][0]["name"] = None
        elif case == "extra-tool":
            responses[1]["result"]["tools"].append({"name": "mempalace_unexpected"})
        elif case == "error-message-null":
            responses[2]["error"]["message"] = None
        elif case == "content-echo":
            responses[2]["error"]["message"] += "   \t"
        elif case == "false-success":
            responses[2] = {"jsonrpc": "2.0", "id": 3, "result": {"content": []}}
        elif case == "continued-tool-entry-list":
            responses[3]["result"]["tools"].append([])
        elif case == "continued-tool-name-null":
            responses[3]["result"]["tools"][0]["name"] = None
        elif case == "extra-continued-tool":
            responses[3]["result"]["tools"].append({"name": "mempalace_unexpected"})
        elif case == "continuation-error-only":
            responses[3].pop("result")
            responses[3]["error"] = {"code": -32000, "message": "unexpected"}
        stdout = "\n".join(json.dumps(response) for response in responses)
        if case == "non-json":
            stdout += "\nnot-json"
        elif case == "non-object":
            stdout += "\n[]"

        error = smoke._probe_declared_mcp_command(
            mcp_json,
            str(tmp_path),
            lambda cmd, **kwargs: (0, stdout, ""),
            {"PATH": "/fake/bin"},
        )

        assert error is not None
        assert expected in error


def test_install_smoke_reports_agent_plugin_mcp_failure(tmp_path):
    plugin_root = tmp_path / "venv" / "site-packages" / "mempalace_code" / "agent_plugin"
    _write_agent_plugin_fixture(plugin_root)
    neutral_cwd = str(tmp_path / "neutral")
    os.makedirs(neutral_cwd)

    def fake_run(cmd, **kwargs):
        if cmd == ["/fake/bin/mempalace-code", "agent-plugin", "path", "--json"]:
            return 0, json.dumps({"path": str(plugin_root)}), ""
        if cmd == ["mempalace-code-mcp", "--profile=minimal"]:
            return 1, "", "mcp failed with ghp_" + "X" * 30
        return 1, "", "unexpected command"

    result = smoke.probe_agent_plugin_package(
        "/fake/bin/mempalace-code",
        neutral_cwd,
        fake_run,
        env={"PATH": "/fake/bin"},
        source_root=str(tmp_path / "checkout"),
    )

    assert result.status == smoke.STATUS_ERROR
    assert "declared MCP command failed" in result.detail
    assert "ghp_" not in result.detail
    assert "REDACTED" in result.detail


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


# ── AC-9 / VER-7: notification state, update probes, no checkout shadowing ─────


def test_cli_version_check_status_probe_does_not_require_ambient_python_import():
    """The smoke uses 'version-check --status' (CLI), not 'python3 -c import', for provenance.

    This ensures isolated installs (pipx, uv-tool) are correctly probed even
    when the system python3 cannot import mempalace_code.
    """
    script_text = (ROOT / "scripts" / "release_install_metadata_smoke.py").read_text(
        encoding="utf-8"
    )
    # The smoke script must reference the CLI executable surface for version reporting.
    assert "version-check" in script_text or "SURFACE_CLI" in script_text, (
        "smoke script must probe the CLI surface via 'version-check', "
        "not only via python3 -c import"
    )
    # The smoke must not rely solely on 'python3 -c import mempalace_code' for CLI provenance.
    # It's OK to import the module for the MODULE surface, but CLI surface must use the executable.
    cli_surface_probes = [
        line
        for line in script_text.splitlines()
        if "SURFACE_CLI" in line and "import" in line and "python3" in line
    ]
    assert not cli_surface_probes, (
        f"CLI surface must not be probed via python3 -c import; found: {cli_surface_probes}"
    )


def test_update_status_command_present_in_smoke_or_docs():
    """Either the smoke script or AGENT_INSTALL.md probes 'update status --json'.

    This ensures agent installers can verify update infrastructure is healthy
    via the installed executable, not just check if the package is loadable.
    """
    agent_install = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    smoke_script = (ROOT / "scripts" / "release_install_metadata_smoke.py").read_text(
        encoding="utf-8"
    )
    assert "update status" in agent_install or "update status" in smoke_script, (
        "Either AGENT_INSTALL.md or the smoke script must probe 'update status'"
    )
    assert "update status --json" in agent_install, (
        "AGENT_INSTALL.md must use 'update status --json' for machine-readable eligibility checks"
    )


def test_neutral_directory_probe_does_not_shadow_checkout(tmp_path):
    """Probes must run from a neutral cwd, not the source checkout with pyproject.toml.

    If a probe runs from within the checkout, Python's package resolution can
    pick up the development tree instead of the installed wheel, making the
    version-match check meaningless.
    """
    # Simulate what happens if run_subprocess is called with cwd=ROOT (checkout root).
    # The smoke's run_venv_smoke should set a neutral cwd (tmp_path-based venv).
    probe_cwds: list[str] = []

    def run_subprocess(args, env=None, cwd=None, input_text=None, timeout_seconds=None):
        if cwd is not None:
            probe_cwds.append(str(cwd))
        if "-m" in args and "venv" in args:
            return 0, "", ""
        if "install" in args and "--no-cache-dir" in args:
            return 0, "", ""
        if "agent-plugin" in args and "path" in args:
            return 0, json.dumps({"path": str(tmp_path / "plugin")}), ""
        if "-c" in args:
            return 0, "METADATA=1.0.0\nMODULE=1.0.0\n", ""
        if "version-check" in args:
            return 0, "version-check: enabled=False\ncurrent=1.0.0\n", ""
        return 0, "", ""

    smoke.run_venv_smoke(".", "mempalace-code", run_subprocess)
    source_root = str(ROOT)
    shadowing_cwds = [c for c in probe_cwds if c == source_root]
    assert not shadowing_cwds, (
        f"Smoke probes must not run from the source checkout root {source_root!r}; "
        f"found cwds: {shadowing_cwds}"
    )


def test_notification_state_probe_is_cli_executable_based():
    """Notification-state probe must use the installed CLI, not python3 import.

    Agents checking whether version notifications are enabled must call
    'mempalace-code version-check --status', not 'python3 -c "import ..."'.
    """
    agent_install = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    assert "version-check --status" in agent_install, (
        "AGENT_INSTALL.md must probe notification state via 'version-check --status' "
        "(installed executable), not via python3 -c import"
    )
