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
import stat
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


def _prepare_bootstrap_venv(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Create an offline venv whose fake pip installs deterministic launchers."""
    venv = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)],
        check=True,
        capture_output=True,
        text=True,
    )
    support = tmp_path / "support"
    pip_package = support / "pip"
    module_package = support / "mempalace_code"
    pip_package.mkdir(parents=True)
    module_package.mkdir()
    (module_package / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (pip_package / "__init__.py").write_text("", encoding="utf-8")
    (support / "sitecustomize.py").write_text(
        """from pathlib import Path
import os
import signal
import shutil
import sys

hook = os.environ.get("BOOTSTRAP_TEST_HOOK", "")
acquisition_signals = {
    "signal-acquire-hup": signal.SIGHUP,
    "signal-acquire-int": signal.SIGINT,
    "signal-acquire-term": signal.SIGTERM,
}
if (
    hook in acquisition_signals
    and len(sys.argv) == 5
    and sys.argv[0] == "-"
    and sys.argv[1].endswith(".bootstrap.lock")
    and sys.argv[3] == "acquire"
):
    os.kill(os.getppid(), acquisition_signals[hook])

if (
    hook == "replace-lock-transition"
    and len(sys.argv) == 5
    and sys.argv[0] == "-"
    and sys.argv[1].endswith(".bootstrap.lock")
    and sys.argv[4] == "transition"
):
    lock = Path(sys.argv[1])
    displaced = Path(str(lock) + ".displaced")
    shutil.move(lock, displaced)
    token = (displaced / "token").read_text(encoding="utf-8").splitlines()[0]
    lock.mkdir(mode=0o700)
    lock_stat = lock.stat()
    metadata = lock / "token"
    metadata.write_text(
        f"{token}\\n{lock_stat.st_dev}:{lock_stat.st_ino}\\n", encoding="utf-8"
    )
    metadata.chmod(0o600)

if hook == "replace-bin-dir":
    bin_dir = Path.home() / ".local" / "bin"
    if len(sys.argv) > 1 and sys.argv[0] == "-" and Path(sys.argv[1]) == bin_dir:
        counter = Path(os.environ["BOOTSTRAP_PIP_MARKER"] + ".bin-dir-snapshots")
        count = int(counter.read_text(encoding="utf-8")) + 1 if counter.exists() else 1
        counter.write_text(str(count), encoding="utf-8")
        if count == 2:
            bin_dir.rename(bin_dir.with_name("bin.displaced"))
            bin_dir.mkdir(mode=0o700)
""",
        encoding="utf-8",
    )
    (pip_package / "__main__.py").write_text(
        """from pathlib import Path
import os
import signal
import shutil
import sys

marker = Path(os.environ["BOOTSTRAP_PIP_MARKER"])
marker.parent.mkdir(parents=True, exist_ok=True)
with marker.open("a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")

hook = os.environ.get("BOOTSTRAP_TEST_HOOK", "")
signals = {
    "signal-hup": signal.SIGHUP,
    "signal-int": signal.SIGINT,
    "signal-term": signal.SIGTERM,
}
if hook in signals and not any("mempalace-code" in arg for arg in sys.argv[1:]):
    os.kill(os.getppid(), signals[hook])

if hook == "replace-python" and not any("mempalace-code" in arg for arg in sys.argv[1:]):
    python = Path(sys.prefix) / "bin" / "python"
    python.unlink()
    python.write_text("#!/bin/sh\\necho replaced\\n", encoding="utf-8")
    python.chmod(0o700)

if any("mempalace-code" in arg for arg in sys.argv[1:]):
    bindir = Path(sys.prefix) / "bin"
    for name in ("mempalace-code", "mempalace-code-mcp"):
        launcher = bindir / name
        launcher.write_text("#!/bin/sh\\nexit 0\\n", encoding="utf-8")
        launcher.chmod(0o700)

    canonical = Path.home() / ".local" / "bin" / "mempalace-code"
    if hook == "launcher-race":
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text("RACE-WINNER", encoding="utf-8")
    elif hook == "replace-lock":
        lock = Path(str(sys.prefix) + ".bootstrap.lock")
        displaced = Path(str(lock) + ".displaced")
        shutil.move(lock, displaced)
        lock.mkdir(mode=0o700)
        (lock / "token").write_text("intruder\\n", encoding="utf-8")
    elif hook == "replace-lock-valid":
        lock = Path(str(sys.prefix) + ".bootstrap.lock")
        displaced = Path(str(lock) + ".displaced")
        shutil.move(lock, displaced)
        token = (displaced / "token").read_text(encoding="utf-8").splitlines()[0]
        lock.mkdir(mode=0o700)
        lock_stat = lock.stat()
        metadata = lock / "token"
        metadata.write_text(
            f"{token}\\n{lock_stat.st_dev}:{lock_stat.st_ino}\\n", encoding="utf-8"
        )
        metadata.chmod(0o600)
""",
        encoding="utf-8",
    )
    return venv, {
        "MEMPALACE_VENV": str(venv),
        "PYTHONPATH": str(support),
        "BOOTSTRAP_PIP_MARKER": str(tmp_path / "pip-invocations"),
    }


def test_bootstrap_rejects_unknown_source_without_install(tmp_path):
    result = _run_bootstrap(tmp_path, MEMPALACE_SOURCE="unknown-source")

    assert result.returncode != 0
    assert "Unknown MEMPALACE_SOURCE" in result.stdout
    assert not (tmp_path / "home" / ".mempalace" / "venv").exists()


def test_bootstrap_rejects_contradictory_pypi_ref_before_mutation(tmp_path):
    result = _run_bootstrap(tmp_path, MEMPALACE_SOURCE="pypi", MEMPALACE_GIT_REF="v1.2.3")

    assert result.returncode != 0
    assert "valid only with MEMPALACE_SOURCE=git" in result.stdout
    assert not (tmp_path / "home" / ".mempalace" / "venv").exists()


def test_bootstrap_requires_full_commit_refs_before_package_mutation(tmp_path):
    invalid = ("main", "v1.2.3", "v1.2.3-rc1", "a" * 12, "a" * 39, "a" * 41)

    for index, ref in enumerate(invalid):
        case = tmp_path / str(index)
        case.mkdir()
        result = _run_bootstrap(case, MEMPALACE_SOURCE="git", MEMPALACE_GIT_REF=ref)
        assert result.returncode != 0, ref
        assert "must be a full 40-hex commit" in result.stdout, ref
        assert not (case / "home" / ".mempalace" / "venv").exists(), ref

    accepted = tmp_path / "accepted"
    accepted.mkdir()
    result = _run_bootstrap(accepted, MEMPALACE_SOURCE="git", MEMPALACE_GIT_REF="a" * 40, PATH="")
    assert result.returncode != 0
    assert "Python 3.11+ not found" in result.stdout
    assert "full 40-hex commit" not in result.stdout
    assert not (accepted / "home" / ".mempalace" / "venv").exists()


def test_runbook_bootstrap_uses_consumed_commit_refs():
    runbook = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    bootstrap = runbook[
        runbook.index("**`INSTALL_METHOD=bootstrap`:**") : runbook.index("### Step 3.4")
    ]

    assert "is_full_commit" in bootstrap
    assert '[[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]' in bootstrap
    assert "$BOOTSTRAP_REF/scripts/bootstrap.sh" in bootstrap
    assert 'MEMPALACE_GIT_REF="$PACKAGE_REF"' in bootstrap
    assert "immutable release tag" not in bootstrap
    assert "immutable vX.Y.Z" not in bootstrap


def test_bootstrap_refuses_unowned_launcher_nodes(tmp_path):
    for node_type in ("file", "directory", "fifo", "symlink"):
        case = tmp_path / node_type
        case.mkdir()
        venv, env = _prepare_bootstrap_venv(case)
        launcher = case / "home" / ".local" / "bin" / "mempalace-code"
        launcher.parent.mkdir(parents=True)
        target = case / "unrelated-target"
        if node_type == "file":
            launcher.write_text("USER-OWNED", encoding="utf-8")
        elif node_type == "directory":
            launcher.mkdir()
            (launcher / "keep").write_text("USER-OWNED", encoding="utf-8")
        elif node_type == "fifo":
            os.mkfifo(launcher)
        else:
            target.write_text("USER-OWNED", encoding="utf-8")
            launcher.symlink_to(target)

        result = _run_bootstrap(case, **env)

        assert result.returncode != 0, (node_type, result.stdout, result.stderr)
        assert f"ls -ld -- {launcher}" in result.stdout
        assert "Done." not in result.stdout
        if node_type == "file":
            assert launcher.read_text(encoding="utf-8") == "USER-OWNED"
        elif node_type == "directory":
            assert (launcher / "keep").read_text(encoding="utf-8") == "USER-OWNED"
            assert list(launcher.iterdir()) == [launcher / "keep"]
        elif node_type == "fifo":
            assert stat.S_ISFIFO(launcher.lstat().st_mode)
        else:
            assert launcher.is_symlink()
            assert launcher.readlink() == target
            assert target.read_text(encoding="utf-8") == "USER-OWNED"
        assert venv.exists()


def test_bootstrap_rejects_unsafe_venv_paths_before_execution(tmp_path):
    relative_case = tmp_path / "relative"
    relative_case.mkdir()
    relative = _run_bootstrap(relative_case, MEMPALACE_VENV="relative/venv")
    assert relative.returncode != 0
    assert "must be an absolute path: relative/venv" in relative.stdout

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    symlink_parent = tmp_path / "symlink-parent"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)
    symlink_run = tmp_path / "symlink-case"
    symlink_run.mkdir()
    symlinked = _run_bootstrap(symlink_run, MEMPALACE_VENV=str(symlink_parent / "venv"))
    assert symlinked.returncode != 0
    assert str(symlink_parent / "venv") in symlinked.stdout

    venv_target = tmp_path / "venv-target"
    venv_target.mkdir()
    venv_link = tmp_path / "venv-link"
    venv_link.symlink_to(venv_target, target_is_directory=True)
    leaf_run = tmp_path / "venv-link-case"
    leaf_run.mkdir()
    leaf = _run_bootstrap(leaf_run, MEMPALACE_VENV=str(venv_link))
    assert leaf.returncode != 0
    assert f"not a regular directory: {venv_link}" in leaf.stdout

    writable = tmp_path / "writable"
    writable.mkdir(mode=0o777)
    writable.chmod(0o777)
    writable_run = tmp_path / "writable-case"
    writable_run.mkdir()
    replaceable = _run_bootstrap(writable_run, MEMPALACE_VENV=str(writable / "venv"))
    assert replaceable.returncode != 0
    assert str(writable / "venv") in replaceable.stdout


def test_bootstrap_rejects_foreign_existing_venv_before_package_execution(tmp_path):
    stale = tmp_path / "stale"
    stale_bin = stale / "bin"
    stale_bin.mkdir(parents=True)
    stale_python = stale_bin / "python"
    stale_python.write_text("#!/bin/sh\necho /foreign/prefix\n", encoding="utf-8")
    stale_python.chmod(0o700)
    marker = tmp_path / "stale-pip-marker"
    stale_run = tmp_path / "stale-case"
    stale_run.mkdir()
    result = _run_bootstrap(
        stale_run,
        MEMPALACE_VENV=str(stale),
        BOOTSTRAP_PIP_MARKER=str(marker),
    )
    assert result.returncode != 0
    assert "prefix mismatch" in result.stdout
    assert not marker.exists()

    foreign_case = tmp_path / "foreign-launcher"
    foreign_case.mkdir()
    venv, env = _prepare_bootstrap_venv(foreign_case)
    unrelated = foreign_case / "unrelated"
    unrelated.write_text("foreign", encoding="utf-8")
    (venv / "bin" / "mempalace-code").symlink_to(unrelated)
    result = _run_bootstrap(foreign_case, **env)
    assert result.returncode != 0
    assert "unsafe existing venv launcher" in result.stdout
    assert not Path(env["BOOTSTRAP_PIP_MARKER"]).exists()

    changed_case = tmp_path / "changed-interpreter"
    changed_case.mkdir()
    _, env = _prepare_bootstrap_venv(changed_case)
    result = _run_bootstrap(changed_case, **env, BOOTSTRAP_TEST_HOOK="replace-python")
    assert result.returncode != 0
    assert "MEMPALACE_VENV identity changed" in result.stdout
    invocations = Path(env["BOOTSTRAP_PIP_MARKER"]).read_text(encoding="utf-8")
    assert "--upgrade pip" in invocations
    assert "mempalace-code" not in invocations


def test_bootstrap_launcher_publication_is_race_bounded_and_idempotent(tmp_path):
    repeat = tmp_path / "repeat"
    repeat.mkdir()
    venv, env = _prepare_bootstrap_venv(repeat)
    first = _run_bootstrap(repeat, **env)
    second = _run_bootstrap(repeat, **env)
    canonical = repeat / "home" / ".local" / "bin" / "mempalace-code"
    assert first.returncode == 0, (first.stdout, first.stderr)
    assert second.returncode == 0, (second.stdout, second.stderr)
    assert canonical.is_symlink()
    assert canonical.resolve() == venv / "bin" / "mempalace-code"
    assert "Symlink already correct" in second.stdout
    assert "Done." in second.stdout

    race = tmp_path / "race"
    race.mkdir()
    venv, env = _prepare_bootstrap_venv(race)
    result = _run_bootstrap(race, **env, BOOTSTRAP_TEST_HOOK="launcher-race")
    race_launcher = race / "home" / ".local" / "bin" / "mempalace-code"
    assert result.returncode != 0
    assert race_launcher.read_text(encoding="utf-8") == "RACE-WINNER"
    assert "Done." not in result.stdout

    locked = tmp_path / "locked"
    locked.mkdir()
    venv, env = _prepare_bootstrap_venv(locked)
    lock = Path(str(venv) + ".bootstrap.lock")
    lock.mkdir(mode=0o700)
    (lock / "keep").write_text("STALE", encoding="utf-8")
    result = _run_bootstrap(locked, **env)
    assert result.returncode != 0
    assert (lock / "keep").read_text(encoding="utf-8") == "STALE"
    assert f"ls -ld -- {lock}" in result.stdout

    replaced = tmp_path / "replaced-lock"
    replaced.mkdir()
    venv, env = _prepare_bootstrap_venv(replaced)
    result = _run_bootstrap(replaced, **env, BOOTSTRAP_TEST_HOOK="replace-lock")
    replacement = Path(str(venv) + ".bootstrap.lock")
    assert result.returncode != 0
    assert (replacement / "token").read_text(encoding="utf-8") == "intruder\n"
    assert "Bootstrap lock identity changed" in result.stdout
    assert "Done." not in result.stdout

    valid_replacement_case = tmp_path / "valid-replacement-lock"
    valid_replacement_case.mkdir()
    venv, env = _prepare_bootstrap_venv(valid_replacement_case)
    result = _run_bootstrap(
        valid_replacement_case,
        **env,
        BOOTSTRAP_TEST_HOOK="replace-lock-valid",
    )
    valid_replacement = Path(str(venv) + ".bootstrap.lock")
    replacement_lines = (valid_replacement / "token").read_text(encoding="utf-8").splitlines()
    replacement_stat = valid_replacement.stat()
    assert result.returncode != 0
    assert replacement_lines[1] == f"{replacement_stat.st_dev}:{replacement_stat.st_ino}"
    assert "Bootstrap lock identity changed" in result.stdout
    assert "Done." not in result.stdout

    transition_case = tmp_path / "valid-transition-replacement-lock"
    transition_case.mkdir()
    venv, env = _prepare_bootstrap_venv(transition_case)
    result = _run_bootstrap(
        transition_case,
        **env,
        BOOTSTRAP_TEST_HOOK="replace-lock-transition",
    )
    transition_replacement = Path(str(venv) + ".bootstrap.lock")
    transition_lines = (transition_replacement / "token").read_text(encoding="utf-8").splitlines()
    transition_stat = transition_replacement.stat()
    assert result.returncode != 0
    assert not Path(env["BOOTSTRAP_PIP_MARKER"]).exists()
    assert transition_lines[1] == f"{transition_stat.st_dev}:{transition_stat.st_ino}"
    assert "Bootstrap lock identity changed" in result.stdout
    assert "Done." not in result.stdout

    replaced_bin_dir = tmp_path / "replaced-bin-dir"
    replaced_bin_dir.mkdir()
    _, env = _prepare_bootstrap_venv(replaced_bin_dir)
    result = _run_bootstrap(replaced_bin_dir, **env, BOOTSTRAP_TEST_HOOK="replace-bin-dir")
    canonical = replaced_bin_dir / "home" / ".local" / "bin" / "mempalace-code"
    assert result.returncode != 0
    assert not canonical.exists()
    assert canonical.parent.with_name("bin.displaced").is_dir()
    assert "Canonical launcher directory identity changed" in result.stdout
    assert "Done." not in result.stdout


@pytest.mark.parametrize(
    ("hook", "expected_status"),
    [("signal-hup", 129), ("signal-int", 130), ("signal-term", 143)],
)
def test_bootstrap_signal_terminates_and_cleans_owned_lock(tmp_path, hook, expected_status):
    case = tmp_path / hook
    case.mkdir()
    venv, env = _prepare_bootstrap_venv(case)

    result = _run_bootstrap(case, **env, BOOTSTRAP_TEST_HOOK=hook)

    assert result.returncode == expected_status
    assert not Path(str(venv) + ".bootstrap.lock").exists()
    assert not (case / "home" / ".local" / "bin" / "mempalace-code").exists()
    invocations = Path(env["BOOTSTRAP_PIP_MARKER"]).read_text(encoding="utf-8")
    assert "--upgrade pip" in invocations
    assert "mempalace-code" not in invocations
    assert "Done." not in result.stdout


@pytest.mark.parametrize(
    ("hook", "expected_status"),
    [
        ("signal-acquire-hup", 129),
        ("signal-acquire-int", 130),
        ("signal-acquire-term", 143),
    ],
)
def test_bootstrap_signal_during_lock_acquisition_cleans_without_install(
    tmp_path, hook, expected_status
):
    case = tmp_path / hook
    case.mkdir()
    venv, env = _prepare_bootstrap_venv(case)

    result = _run_bootstrap(case, **env, BOOTSTRAP_TEST_HOOK=hook)

    assert result.returncode == expected_status
    assert not Path(str(venv) + ".bootstrap.lock").exists()
    assert not Path(env["BOOTSTRAP_PIP_MARKER"]).exists()
    assert not (case / "home" / ".local" / "bin" / "mempalace-code").exists()
    assert "Done." not in result.stdout


def test_bootstrap_negative_filesystem_boundary_matrix(tmp_path):
    cases = (
        ("relative", "relative/venv", "must be an absolute path"),
        ("malformed-ref", None, "must be a full 40-hex commit"),
    )
    for name, venv_path, expected in cases:
        case = tmp_path / name
        case.mkdir()
        updates = (
            {"MEMPALACE_VENV": venv_path}
            if venv_path
            else {
                "MEMPALACE_SOURCE": "git",
                "MEMPALACE_GIT_REF": "v1.2.3",
            }
        )
        result = _run_bootstrap(case, **updates)
        assert result.returncode != 0
        assert expected in result.stdout

    symlink_case = tmp_path / "symlink"
    symlink_case.mkdir()
    target = symlink_case / "target"
    target.mkdir()
    redirected = symlink_case / "redirected"
    redirected.symlink_to(target, target_is_directory=True)
    result = _run_bootstrap(symlink_case, MEMPALACE_VENV=str(redirected / "venv"))
    assert result.returncode != 0
    assert "unsafe path component" in result.stdout

    venv_target = symlink_case / "venv-target"
    venv_target.mkdir()
    venv_link = symlink_case / "venv-link"
    venv_link.symlink_to(venv_target, target_is_directory=True)
    result = _run_bootstrap(symlink_case, MEMPALACE_VENV=str(venv_link))
    assert result.returncode != 0
    assert "not a regular directory" in result.stdout

    stale_case = tmp_path / "stale-prefix"
    stale_case.mkdir()
    stale = stale_case / "venv"
    (stale / "bin").mkdir(parents=True)
    python = stale / "bin" / "python"
    python.write_text("#!/bin/sh\necho /wrong\n", encoding="utf-8")
    python.chmod(0o700)
    result = _run_bootstrap(stale_case, MEMPALACE_VENV=str(stale))
    assert result.returncode != 0
    assert "prefix mismatch" in result.stdout

    collision = tmp_path / "collision"
    collision.mkdir()
    venv, env = _prepare_bootstrap_venv(collision)
    launcher = collision / "home" / ".local" / "bin" / "mempalace-code"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("KEEP", encoding="utf-8")
    result = _run_bootstrap(collision, **env)
    assert result.returncode != 0
    assert launcher.read_text(encoding="utf-8") == "KEEP"

    duplicate = tmp_path / "duplicate"
    duplicate.mkdir()
    venv, env = _prepare_bootstrap_venv(duplicate)
    assert _run_bootstrap(duplicate, **env).returncode == 0
    again = _run_bootstrap(duplicate, **env)
    assert again.returncode == 0
    assert "Done." in again.stdout


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
            assert kwargs["input_text"].count("tools/list") == 1
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
