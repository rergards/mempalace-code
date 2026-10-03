"""UAT round-2 regressions for install, help, and configuration surfaces."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _cli(args: list[str], *, env: dict[str, str] | None = None, cwd: Path | None = None):
    merged = {**os.environ, "MEMPALACE_VERSION_CHECK": "0", **(env or {})}
    merged["PYTHONPATH"] = os.pathsep.join([str(ROOT), merged.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-m", "mempalace_code.cli", *args],
        capture_output=True,
        text=True,
        env=merged,
        cwd=cwd,
        timeout=120,
    )


# ── install-r2-1: the runbook keys the not-created state on the JSON error code ──


def test_agent_install_step_6_1_matches_health_json_for_a_missing_palace(tmp_path):
    result = _cli(["--palace", str(tmp_path / "never"), "health", "--json"])

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error_code"] == "no_palace"
    step = (ROOT / "docs" / "AGENT_INSTALL.md").read_text(encoding="utf-8")
    step = step[step.index("### Step 6.1") : step.index("### Step 6.2")]
    assert '"error_code": "no_palace"' in step
    assert "on stderr" not in step
    assert "other than `no_palace`" in step


# ── install-r2-2: a relative configured palace path is reported, not silently cwd-bound ──


def test_relative_palace_path_from_env_or_config_warns_once(tmp_path, monkeypatch, capsys):
    from mempalace_code import config as config_module

    monkeypatch.setattr(config_module, "_WARNED_INVALID_SETTINGS", set())
    monkeypatch.chdir(tmp_path)
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(json.dumps({"palace_path": "palaces/rel"}))
    monkeypatch.delenv("MEMPALACE_PALACE_PATH", raising=False)
    monkeypatch.delenv("MEMPAL_PALACE_PATH", raising=False)
    cfg = config_module.MempalaceConfig(config_dir=str(config_dir))

    assert cfg.palace_path == str(tmp_path / "palaces" / "rel")
    assert cfg.palace_path == str(tmp_path / "palaces" / "rel")
    err = capsys.readouterr().err
    assert err.count("is the relative path 'palaces/rel'") == 1
    assert "Set an absolute path." in err

    monkeypatch.setenv("MEMPALACE_PALACE_PATH", "relative/pal")
    assert cfg.palace_path == str(tmp_path / "relative" / "pal")
    assert "MEMPALACE_PALACE_PATH is the relative path 'relative/pal'" in capsys.readouterr().err

    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(tmp_path / "abs"))
    assert cfg.palace_path == str(tmp_path / "abs")
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", "~/pal")
    assert cfg.palace_path == os.path.expanduser("~/pal")
    assert capsys.readouterr().err == ""


# ── install-r2-4: status, search, and health print one next step that keeps --palace ──


def test_missing_palace_next_step_is_identical_and_keeps_palace(tmp_path):
    palace = str(tmp_path / "nowhere")
    lines = []
    for command in (["status", "--summary"], ["search", "foo"], ["health"]):
        result = _cli(["--palace", palace, *command], env={"HF_HUB_OFFLINE": "1"})
        assert result.returncode == 1, command
        output = result.stdout + result.stderr
        (line,) = [text.strip() for text in output.splitlines() if "Next:" in text]
        lines.append(line.rstrip("."))
    assert len(set(lines)) == 1, lines
    assert f"--palace {palace} init <dir>" in lines[0]
    assert f"--palace {palace} mine <dir>" in lines[0]


# ── chroma-1: a legacy ChromaDB palace names the migration on every surface ──


def _chroma_palace(tmp_path: Path) -> Path:
    palace = tmp_path / "chroma" / "src"
    palace.mkdir(parents=True)
    (palace / "chroma.sqlite3").write_text("x")
    return palace


def test_status_and_search_name_the_chroma_migration(tmp_path):
    palace = _chroma_palace(tmp_path)
    for command in (["status"], ["status", "--summary"], ["search", "x"]):
        result = _cli(["--palace", str(palace), *command], env={"HF_HUB_OFFLINE": "1"})
        assert result.returncode == 1, command
        assert "ChromaDB migration support is retired" in result.stderr, command
        assert "migrate-storage" in result.stderr
        assert "No palace found" not in result.stdout + result.stderr
        assert "Traceback" not in result.stderr
    assert sorted(path.name for path in palace.iterdir()) == ["chroma.sqlite3"]


def test_mcp_tools_name_the_chroma_migration(tmp_path, monkeypatch):
    from mempalace_code.config import MempalaceConfig
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.read import tool_status

    palace = _chroma_palace(tmp_path)
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(palace))
    monkeypatch.setattr(runtime, "_config", MempalaceConfig(config_dir=str(tmp_path / "cfg")))
    monkeypatch.setattr(runtime, "_store", None)

    result = tool_status()

    assert result["error_code"] == "chroma_migration_required"
    assert "migrate-storage" in result["hint"]


# ── install-r2-7: a second Ctrl-C skips the pending-batch save; the rerun resumes ──


def test_second_ctrl_c_skips_the_pending_flush_and_rerun_files_everything(
    tmp_path, monkeypatch, capsys
):
    import pytest
    import yaml

    from mempalace_code.mining import orchestrator
    from mempalace_code.storage import open_store

    project = tmp_path / "proj"
    project.mkdir()
    for name in ("a", "b", "c"):
        (project / f"{name}.md").write_text(f"# {name}\n\nNotes about the {name} ledger.\n")
    (project / "mempalace.yaml").write_text(
        yaml.safe_dump({"wing": "proj", "rooms": [{"name": "general", "description": ""}]})
    )
    palace = tmp_path / "palace"
    original = orchestrator.add_drawers_batch
    original_collect = orchestrator._collect_specs_for_file
    collected = {"n": 0}
    calls = {"n": 0}

    def interrupted_while_scanning(*args, **kwargs):
        collected["n"] += 1
        if collected["n"] == 3:
            raise KeyboardInterrupt  # first Ctrl-C: two files wait in the pending batch
        return original_collect(*args, **kwargs)

    def interrupted_save(*args, **kwargs):
        calls["n"] += 1
        raise KeyboardInterrupt  # second Ctrl-C, during the pending-batch save

    monkeypatch.setattr(orchestrator, "_collect_specs_for_file", interrupted_while_scanning)
    monkeypatch.setattr(orchestrator, "add_drawers_batch", interrupted_save)

    with pytest.raises(KeyboardInterrupt):
        orchestrator.mine(str(project), str(palace), skip_optimize=True)

    out = capsys.readouterr().out
    assert calls["n"] == 1
    assert "press Ctrl-C again to stop now" in out
    assert "Stopped without saving" in out
    assert "0 drawers filed before interrupt" in out

    monkeypatch.setattr(orchestrator, "add_drawers_batch", original)
    monkeypatch.setattr(orchestrator, "_collect_specs_for_file", original_collect)
    orchestrator.mine(str(project), str(palace), skip_optimize=True)
    store = open_store(str(palace), create=False, read_only=True)
    sources = {row["source_file"] for batch in store.iter_all() for row in batch}
    assert {Path(source).name for source in sources} == {"a.md", "b.md", "c.md"}


# ── r1-update-1: recovery commands name the launcher that was invoked ──


def _invoke_as_other_launcher(tmp_path, monkeypatch) -> Path:
    launcher = tmp_path / "other" / "mempalace-code"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    monkeypatch.setattr(sys, "argv", [str(launcher), "update", "status"])
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    return launcher


def test_update_recoveries_name_the_invoked_launcher(tmp_path, monkeypatch):
    from mempalace_code import updater

    launcher = _invoke_as_other_launcher(tmp_path, monkeypatch)

    assert updater.status_recovery_command() == f"{launcher} update status --json"
    assert f"{launcher} update status --json" in updater._account_home_recovery()
    data = updater.UpdateManager._unsupported_manual_platform_data()
    if data is not None:
        assert data["recovery_command"] == f"{launcher} update status --json"


def test_update_recovery_stays_bare_when_path_finds_the_same_launcher(tmp_path, monkeypatch):
    from mempalace_code import updater

    launcher = _invoke_as_other_launcher(tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", str(launcher.parent))

    assert updater.status_recovery_command() == "mempalace-code update status --json"


def test_watch_schedule_model_warning_names_the_invoked_launcher(tmp_path, monkeypatch, capsys):
    from mempalace_code.cli_commands import watch

    launcher = _invoke_as_other_launcher(tmp_path, monkeypatch)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-empty"))

    watch._warn_uncached_model()

    assert f"#     {launcher} fetch-model" in capsys.readouterr().err


def test_foreground_watch_recoveries_name_the_invoked_launcher(tmp_path, monkeypatch):
    import pytest

    from mempalace_code import watcher

    pytest.importorskip("watchfiles")
    launcher = _invoke_as_other_launcher(tmp_path, monkeypatch)
    seen = {}

    def fake_plan(root, **kwargs):
        seen.update(kwargs)
        raise watcher.WatchRootError("stop")

    monkeypatch.setattr(watcher, "plan_watch_root", fake_plan)

    with pytest.raises(SystemExit):
        watcher.watch_all(str(tmp_path), str(tmp_path / "palace"))

    assert seen["cli"] == str(launcher)


# ── update-2: a uv tool in a custom UV_TOOL_DIR is found by its receipt ──


def _custom_uv_tool(tmp_path: Path) -> tuple[Path, Path]:
    tool_dir = tmp_path / "uvtools2"
    bin_dir = tmp_path / "uvbin2"
    prefix = tool_dir / "mempalace-code"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text(
        "[tool]\n"
        'requirements = [{ name = "mempalace-code", extras = ["spellcheck"] }]\n'
        "entrypoints = [\n"
        f'    {{ name = "mempalace-code", install-path = "{bin_dir}/mempalace-code" }},\n'
        "]\n",
        encoding="utf-8",
    )
    return prefix, bin_dir


def test_custom_uv_tool_dir_is_detected_without_the_variable(tmp_path, monkeypatch):
    from mempalace_code import updater

    prefix, bin_dir = _custom_uv_tool(tmp_path)
    monkeypatch.setattr(updater, "_has_editable_metadata", lambda: False)

    installation = updater.detect_installation(
        prefix=prefix,
        base_prefix=tmp_path / "system",
        environ={"XDG_DATA_HOME": str(tmp_path / "xdg")},
        which=lambda name: f"/usr/bin/{name}",
        extras=frozenset({"spellcheck"}),
    )

    assert installation.kind == "uv-tool"
    assert installation.install_command("1.16.0") == [
        "env",
        f"UV_TOOL_DIR={prefix.parent.resolve()}",
        f"UV_TOOL_BIN_DIR={bin_dir}",
        "/usr/bin/uv",
        "tool",
        "install",
        "--force",
        "mempalace-code[spellcheck]==1.16.0",
    ]


def test_default_uv_tool_dir_needs_no_location(tmp_path, monkeypatch):
    from mempalace_code import updater

    xdg = tmp_path / "xdg"
    prefix = xdg / "uv" / "tools" / "mempalace-code"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "mempalace-code" }]\n'
    )
    monkeypatch.setattr(updater, "_has_editable_metadata", lambda: False)

    installation = updater.detect_installation(
        prefix=prefix,
        base_prefix=tmp_path / "system",
        environ={"XDG_DATA_HOME": str(xdg)},
        which=lambda name: f"/usr/bin/{name}",
        extras=frozenset(),
    )

    assert installation.kind == "uv-tool"
    assert installation.install_command("1.16.0")[0] == "/usr/bin/uv"


def test_watch_extra_hint_names_a_custom_uv_tool_dir(tmp_path, monkeypatch):
    from mempalace_code import storage

    prefix, bin_dir = _custom_uv_tool(tmp_path)
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    command = storage.extra_install_command("watch")

    assert command.startswith(
        f"UV_TOOL_DIR={prefix.parent.resolve()} UV_TOOL_BIN_DIR={bin_dir} uv tool install --force "
    )
    assert "mempalace-code[" in command
    assert "spellcheck" in command
    assert "watch" in command


# ── r1-ops-8: no surface still claims spellcheck rewrites mined text ──


def test_docs_and_help_do_not_claim_spellcheck_rewrites_mined_text():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "turns are spell-corrected" not in readme
    assert "for spellcheck" not in readme
    help_text = _cli(["--help"]).stdout
    assert "for spellcheck" not in help_text
    onboarding = (ROOT / "mempalace_code" / "onboarding.py").read_text(encoding="utf-8")
    assert "When spellcheck is on" not in onboarding


# ── r1-ops-23 / install-r2-5: `help <command> [<subcommand>]` matches `--help` ──


def test_help_walks_nested_subcommands():
    nested = _cli(["help", "update", "status"])
    direct = _cli(["update", "status", "--help"])

    assert nested.returncode == 0, nested.stderr
    assert nested.stdout == direct.stdout


def test_help_wing_migration_lists_the_operator_actions():
    result = _cli(["help", "wing-migration"])

    assert result.returncode == 0, result.stderr
    for action in ("inventory", "snapshot", "apply", "classify", "recover", "qualify"):
        assert action in result.stdout
    assert "wing_migration_args" not in result.stdout
    assert _cli(["help", "wing-migration", "apply"]).stdout.startswith(
        "usage: mempalace-code wing-migration apply"
    )


def test_help_rejects_unknown_nested_subcommands_precisely():
    result = _cli(["help", "update", "bogus"])

    assert result.returncode == 2
    assert "unknown subcommand 'bogus' for 'update'" in result.stderr
    assert "unrecognized arguments" not in result.stderr
    assert _cli(["help", "nope"]).returncode == 2


# ── gap-8: a group-level backup --out is never silently ignored ──


def test_backup_group_out_is_refused_where_it_would_be_ignored(tmp_path):
    palace = tmp_path / "palace"
    first, second, listed = (tmp_path / f"bk{n}.tar.gz" for n in (2, 3, 9))

    conflict = _cli(
        ["--palace", str(palace), "backup", "--out", str(first), "create", "--out", str(second)]
    )
    listing = _cli(["--palace", str(palace), "backup", "--out", str(listed), "list"])
    schedule = _cli(
        ["--palace", str(palace), "backup", "--out", str(listed), "schedule", "--freq", "daily"]
    )

    assert conflict.returncode == 2
    assert "two different --out values" in conflict.stderr
    assert f"backup create --out {second}" in conflict.stderr
    assert listing.returncode == 2
    assert "--out has no effect on 'backup list'" in listing.stderr
    assert schedule.returncode == 2
    assert "backup schedule --freq daily" in schedule.stderr
    assert not any(path.exists() for path in (first, second, listed))


def test_backup_group_out_refusal_replays_every_other_flag_and_honours_json(tmp_path):
    palace = tmp_path / "palace"
    extra = tmp_path / "old backups"
    listed = tmp_path / "bk.tar.gz"

    result = _cli(
        [
            "--palace",
            str(palace),
            "backup",
            "--out",
            str(listed),
            "list",
            "--dir",
            str(extra),
            "--json",
        ]
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "--out has no effect on 'backup list'" in payload["error"]
    assert payload["next"].endswith(
        f"--palace {palace} backup list --dir {shlex.quote(str(extra))} --json"
    )
    assert str(listed) not in payload["next"]
    assert not listed.exists()


def test_backup_group_out_still_selects_the_archive_for_create(tmp_path, monkeypatch):
    from argparse import Namespace

    from mempalace_code.cli_commands import backup_restore

    seen = []
    monkeypatch.setattr(backup_restore, "cmd_backup_create", lambda args: seen.append(args.out))

    backup_restore.cmd_backup(Namespace(backup_command=None, group_out="a.tar.gz", palace=None))
    backup_restore.cmd_backup(Namespace(backup_command="create", group_out="b.tar.gz", palace=None))
    backup_restore.cmd_backup(
        Namespace(backup_command="create", group_out="c.tar.gz", out="c.tar.gz", palace=None)
    )
    backup_restore.cmd_backup(Namespace(backup_command="create", group_out=None, palace=None))

    assert seen == ["a.tar.gz", "b.tar.gz", "c.tar.gz", None]


# ── install-r2-6: init and mine-all on a regular file say "not a directory" ──


def test_init_and_mine_all_on_a_file_say_not_a_directory(tmp_path):
    target = tmp_path / "auth.py"
    target.write_text("x = 1\n")

    init = _cli(["init", str(target), "--skip-model-download"])
    mine_all = _cli(["--palace", str(tmp_path / "palace"), "mine-all", str(target)])
    missing = _cli(["init", str(tmp_path / "missing"), "--skip-model-download"])

    assert init.returncode == 1
    assert f"Error: not a directory: {target}" in init.stderr
    assert mine_all.returncode == 1
    assert "Error: not a directory:" in mine_all.stderr
    assert "directory not found" in missing.stderr


# ── install-r2-8: the per-palace lease files and their safe cleanup are documented ──


def test_readme_documents_lease_file_cleanup():
    from mempalace_code.operation_lock import palace_lock_path

    readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
    lock = palace_lock_path("/tmp/any-palace")
    assert lock.parent.name == "locks"
    assert "`.lock.metadata.lock`, `.lock.owners.json`" in readme
    assert "the whole `~/.mempalace/locks` directory can be deleted" in readme
