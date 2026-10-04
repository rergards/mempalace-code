"""UAT regressions for mirror preflight, the ONNX Runtime telemetry default, and runbooks."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mempalace_code.mirror_preflight import classify_mirror_command

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_EXCLUDES = (
    "--exclude=palace/ --exclude=knowledge_graph.sqlite3 --exclude=config.json --exclude=backups/"
    " --exclude='palace.backup-*/' --exclude='palace.quarantine-*/'"
)
ALL_FAMILIES = ["palace", "kg", "config", "backups", "repair-backups", "quarantines"]


def _cli(capsys, *argv: str) -> tuple[int, str]:
    from mempalace_code.cli import main

    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, capsys.readouterr().out


# ── preflight mirror ──────────────────────────────────────────────────────


def test_compound_rsync_proved_by_its_own_arguments_is_classified_normally():
    """REG preflight-1 review: an rsync after another command is UNVERIFIED only when a
    cd or HOME change could alter what its paths mean."""
    assert classify_mirror_command("cd /srv && rsync -a site/ host:site/").ok
    safe = f"rsync -a --delete {REQUIRED_EXCLUDES} ~/.mempalace/ user@host:.mempalace/"
    result = classify_mirror_command(f"mempalace-code backup create && {safe}")
    assert result.ok, result
    # Arguments that prove danger stay BLOCKED after another command.
    blocked = classify_mirror_command("backup-it && rsync -a --delete ~/.mempalace/ host:x/")
    assert blocked.dangerous
    for command in (
        "cd ~/.mempalace && rsync -a --delete ./ user@host:backup/",
        f"export HOME=/elsewhere && {safe}",
        "cd ~/.mempalace && sh -c 'rsync -a --delete ./ user@host:backup/'",
    ):
        result = classify_mirror_command(command)
        assert not result.ok, command
        assert not result.dangerous, command
        assert result.pattern_id == "unverifiable-compound-command", command


def test_remove_sent_files_alias_is_blocked():
    """REG preflight-1 review: rsync's deprecated --remove-sent-files alias removes sources."""
    result = classify_mirror_command("rsync -a --remove-sent-files ~/.mempalace/ host:.mempalace/")
    assert result.dangerous
    assert result.pattern_id == "remove-source-files-state-mirror"


@pytest.mark.parametrize(
    "command",
    [
        "rsync -a --del ~/.mempalace/ user@host:.mempalace/",
        "sudo -u bob rsync -aH --del ~/.mempalace user@host:",
        "cd ~ && rsync -a --delete .mempalace/ user@host:.mempalace/",
        "nice -n 10 rsync -a --delete ~/.mempalace/ user@host:.mempalace/",
        "sh -c 'cd ~ && rsync -a --delete .mempalace/ user@host:.mempalace/'",
    ],
)
def test_delete_aliases_and_wrapped_state_mirrors_are_blocked(command):
    """REG preflight-1 / ops-17: --del and compound or runner-wrapped mirrors are not OK."""
    result = classify_mirror_command(command)
    assert not result.ok
    assert result.dangerous
    assert result.pattern_id == "delete-mode-state-mirror-missing-excludes"
    assert result.missing_excludes == ALL_FAMILIES


def test_remove_source_files_from_state_dir_is_blocked_even_with_excludes():
    """REG preflight-1: --remove-source-files deletes the local palace after sending it."""
    for command in (
        "rsync -a --remove-source-files ~/.mempalace/ user@host:.mempalace/",
        f"rsync -a --remove-source-files {REQUIRED_EXCLUDES} ~/.mempalace/ user@host:.mempalace/",
    ):
        result = classify_mirror_command(command)
        assert result.dangerous, command
        assert result.pattern_id == "remove-source-files-state-mirror"
    assert classify_mirror_command("rsync -a --remove-source-files ~/outbox/ user@host:inbox/").ok


def test_compound_command_with_unrecognised_rsync_paths_is_unverified():
    result = classify_mirror_command("cd ~/.mempalace && rsync -a --delete ./ user@host:backup/")
    assert not result.ok
    assert not result.dangerous
    assert result.pattern_id == "unverifiable-compound-command"
    # Only rsync in command position counts: echo merely mentions it.
    assert classify_mirror_command("echo rsync --delete ~/.mempalace/").ok
    assert classify_mirror_command("rsync -a --delete /src/ host:/dst/ && echo done").ok


@pytest.mark.parametrize(
    "command",
    [
        "rsync -a --delete /data/mempalace/palace/ user@host:/data/mempalace/palace/",
        "rsync -a --delete /data/mempalace/palace user@host:/data/mempalace/",
        "rsync -a --delete /data/mempalace/ user@host:/data/mempalace/",
        "rsync -a --delete /data/mempalace/palace/lance/ user@host:/data/palace-lance/",
        "rsync -a --delete user@host:/data/mempalace/palace/ /data/mempalace/palace/",
    ],
)
def test_custom_palace_path_mirror_is_blocked(command):
    """REG preflight-1: a palace at a configured non-default path is palace state."""
    result = classify_mirror_command(command, ["/data/mempalace/palace"])
    assert not result.ok
    assert result.dangerous
    assert result.pattern_id == "delete-mode-palace-mirror"
    assert result.missing_excludes == ["palace"]
    assert any("/data/mempalace/palace" in warning for warning in result.warnings)


def test_custom_palace_parent_mirror_is_ok_when_palace_is_excluded():
    palace = ["/data/mempalace/palace"]
    for exclude in ("--exclude=palace/", "--exclude=/palace/", "--exclude='palace/***'"):
        command = f"rsync -a --delete {exclude} /data/mempalace/ user@host:/data/mempalace/"
        assert classify_mirror_command(command, palace).ok, command
    assert classify_mirror_command(
        "rsync -a --delete --exclude=/mempalace/palace/ /data/mempalace user@host:/data/", palace
    ).ok
    assert not classify_mirror_command(
        "rsync -a --delete --exclude=/other/ /data/mempalace/ user@host:/data/mempalace/", palace
    ).ok
    assert classify_mirror_command("rsync -a --delete /data/docs/ user@host:/data/docs/", palace).ok


def test_cli_uses_configured_palace_path(tmp_path, monkeypatch, capsys):
    """REG preflight-1: the configured palace_path is compared, not only ~/.mempalace."""
    palace = tmp_path / "data" / "mp" / "palace"
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(palace))
    code, out = _cli(
        capsys, "preflight", "mirror", "--command", f"rsync -a --delete {palace}/ host:{palace}/"
    )
    assert code == 1
    assert out.startswith("BLOCKED [delete-mode-palace-mirror]")

    other = tmp_path / "custom-palace"
    code, out = _cli(
        capsys,
        "--palace",
        str(other),
        "preflight",
        "mirror",
        "--json",
        "--command",
        f"rsync -a --delete {other} host:/srv/",
    )
    assert code == 1
    assert json.loads(out)["pattern_id"] == "delete-mode-palace-mirror"


def test_filter_rules_are_recognised_as_excludes():
    """REG preflight-2: --filter/-f exclude rules count like --exclude."""
    for command in (
        "rsync -a --delete --filter='- palace*/' --filter='- knowledge_graph.sqlite3' "
        "--filter='- config.json' --filter='- backups/' ~/.mempalace/ user@host:.mempalace/",
        "rsync -a --delete -f'- palace*/' -f '- knowledge_graph.sqlite3' "
        "--filter='exclude config.json' --filter=-_backups/ ~/.mempalace/ user@host:.mempalace/",
    ):
        result = classify_mirror_command(command)
        assert result.ok, (command, result)


def test_rules_from_files_are_reported_unverified_not_missing(capsys):
    """REG preflight-2: exclude-from/merge rules cannot be read, so say so."""
    command = "rsync -a --delete --exclude-from=/tmp/ex.txt ~/.mempalace/ user@host:.mempalace/"
    result = classify_mirror_command(command)
    assert not result.ok
    assert not result.dangerous
    assert result.pattern_id == "unverifiable-filter-rules"
    assert result.unverified_excludes == ALL_FAMILIES
    assert result.missing_excludes == []

    code, out = _cli(capsys, "preflight", "mirror", "--command", command)
    assert code == 1
    assert out.startswith("UNVERIFIED [unverifiable-filter-rules]")
    assert "unverified exclude: palace" in out

    # Inline excludes that already cover every family stay OK beside an extra file.
    assert classify_mirror_command(
        f"rsync -a --delete {REQUIRED_EXCLUDES} --exclude-from=/tmp/ex.txt "
        "~/.mempalace/ user@host:.mempalace/"
    ).ok
    # A merge file may re-include, so it must not precede the covering excludes.
    assert not classify_mirror_command(
        f"rsync -a --delete --filter='merge /tmp/rules' {REQUIRED_EXCLUDES} "
        "~/.mempalace/ user@host:.mempalace/"
    ).ok


def test_include_before_exclude_is_not_counted_as_protection():
    """rsync applies the first matching rule, so an earlier include can re-include palace/."""
    result = classify_mirror_command(
        f"rsync -a --delete --include='*/' {REQUIRED_EXCLUDES} ~/.mempalace/ user@host:.mempalace/"
    )
    assert not result.ok
    assert "palace" in result.unverified_excludes
    assert classify_mirror_command(
        f"rsync -a --delete {REQUIRED_EXCLUDES} --include='*' ~/.mempalace/ user@host:.mempalace/"
    ).ok


def test_adopted_marker_advisory_and_readme_safe_command():
    """REG preflight-2: the README's safe command carries the .adopted exclude."""
    without = classify_mirror_command(f"rsync -a --delete {REQUIRED_EXCLUDES} ~/.mempalace/ h:x/")
    assert without.ok
    assert any("knowledge_graph.sqlite3.adopted" in warning for warning in without.warnings)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("**Remote mirror risk", 1)[1].split("\n---", 1)[0]
    blocks = re.findall(r"```bash\n(.*?)```", section, re.S)
    safe = " ".join(blocks[0].replace("\\\n", " ").split())
    assert "--exclude=knowledge_graph.sqlite3.adopted" in safe
    result = classify_mirror_command(safe)
    assert result.ok
    assert not any("adopted" in warning for warning in result.warnings)
    guide = (ROOT / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")
    assert "--exclude=knowledge_graph.sqlite3.adopted" in guide.split("## Remote Mirror Risk")[1]


# ── ONNX Runtime telemetry ─────────────────────────────────────────────────


def _onnxruntime_store_files(home: Path) -> list[Path]:
    return [path for path in home.rglob("*") if ".onnxruntime" in path.parts]


def _run_python(code: str, home: Path, **env: str) -> None:
    import subprocess

    environment = {
        **os.environ,
        "HOME": str(home),
        "HF_HOME": str(home / "hf"),
        "PYTHONPATH": str(ROOT),
        **env,
    }
    environment.pop("ORT_DISABLE_TELEMETRY", None)
    environment.update(env)
    subprocess.run([sys.executable, "-c", code], env=environment, cwd=ROOT, check=True, timeout=120)


def test_embedder_construction_disables_onnxruntime_telemetry_store(tmp_path):
    """REG mcp-12: building the embedder must not create ONNX Runtime's usage DB."""
    control = tmp_path / "control-home"
    (control / "hf").mkdir(parents=True)
    _run_python("import onnxruntime", control)
    if not _onnxruntime_store_files(control):
        pytest.skip("this ONNX Runtime build does not create a local telemetry store")

    home = tmp_path / "home"
    (home / "hf").mkdir(parents=True)
    _run_python(
        "from mempalace_code.storage import _FastEmbedder\n"
        "try:\n"
        "    _FastEmbedder(local_files_only=True)\n"
        "except Exception:\n"
        "    pass  # no model cache here; FastEmbed and ONNX Runtime are already imported\n"
        "import sys, os\n"
        "assert 'onnxruntime' in sys.modules\n"
        "assert os.environ['ORT_DISABLE_TELEMETRY'] == '1'\n",
        home,
    )
    assert _onnxruntime_store_files(home) == []


def test_explicit_onnxruntime_telemetry_setting_is_kept(monkeypatch):
    from mempalace_code.storage import _disable_onnxruntime_telemetry

    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    _disable_onnxruntime_telemetry()
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "0"
    monkeypatch.delenv("ORT_DISABLE_TELEMETRY")
    _disable_onnxruntime_telemetry()
    assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"


# ── BACKUP_RESTORE rebuild and machine-transfer runbooks ─────────────────

_STUB_CLI = r"""#!/usr/bin/env python3
# Stub mempalace-code: a palace is a directory whose "wings" file lists its wings.
import os, subprocess, sys
args = sys.argv[1:]
palace = args[args.index("--palace") + 1]
args = args[args.index("--palace") + 2 :]
command, rest = args[0], args[1:]
wings = os.path.join(palace, "wings")
def add(name):
    os.makedirs(os.path.join(palace, "lance"), exist_ok=True)
    with open(wings, "a") as handle:
        handle.write(name + "\n")
if command == "status":
    print("  MemPalace Status")
    for name in sorted(set(open(wings).read().split())):
        print(f"  WING: {name}")
elif command == "export":
    open(rest[rest.index("--out") + 1], "w").write("{}\n")
elif command == "import" and "--dry-run" not in rest:
    add("people")
elif command == "backup":
    out = rest[rest.index("--out") + 1]
    subprocess.run(["tar", "-czf", out, "-C", palace, "."], check=True)
elif command == "mine":
    add(os.path.basename(os.path.normpath(rest[0])))
"""


def _rebuild_script(tmp_path: Path, projects: list[Path]) -> Path:
    guide = (ROOT / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")
    section = guide.split("## Recommended Rebuild Workflow", 1)[1]
    block = re.search(r"```bash\n(.*?)```", section, re.S)
    assert block is not None
    script = block.group(1)
    assert "PROJECTS=(" in script
    quoted = " ".join(f'"{project}"' for project in projects)
    script = re.sub(r"^PROJECTS=\(.*\)$", f"PROJECTS=({quoted})", script, flags=re.M)
    path = tmp_path / "rebuild.sh"
    path.write_text(script, encoding="utf-8")
    return path


def _run_rebuild(tmp_path: Path, projects: list[str]):
    import subprocess

    home = tmp_path / "home"
    palace = home / ".mempalace" / "palace"
    (palace / "lance").mkdir(parents=True)
    (palace / "wings").write_text("billing\nfrontend\npeople\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "mempalace-code"
    stub.write_text(_STUB_CLI.replace("/usr/bin/env python3", sys.executable, 1), encoding="utf-8")
    stub.chmod(0o755)
    sources = []
    for name in projects:
        source = tmp_path / "projects" / name
        source.mkdir(parents=True)
        sources.append(source)
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    result = subprocess.run(
        ["bash", str(_rebuild_script(tmp_path, sources))],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, home / ".mempalace"


@pytest.mark.skipif(sys.platform == "win32", reason="the runbook is a POSIX shell script")
def test_rebuild_runbook_remines_every_project_and_passes(tmp_path):
    """REG docs-rebuild-1: the documented rebuild mines every listed source."""
    result, state = _run_rebuild(tmp_path, ["billing", "frontend"])
    assert result.returncode == 0, result.stdout + result.stderr
    after = (state / "recovery-wings-after.txt").read_text(encoding="utf-8").split()
    assert after == ["billing", "frontend", "people"]


@pytest.mark.skipif(sys.platform == "win32", reason="the runbook is a POSIX shell script")
def test_rebuild_runbook_detects_a_dropped_project(tmp_path):
    """REG docs-rebuild-1: a project missing from PROJECTS fails the wing comparison."""
    result, state = _run_rebuild(tmp_path, ["billing"])
    assert result.returncode != 0
    assert "-frontend" in result.stdout
    assert list(state.glob("palace.quarantine-*")), "the original palace must stay quarantined"


def test_machine_transfer_runbook_moves_only_non_regenerable_content():
    """REG gap-4: a full export plus a mine at a new path duplicates mined drawers."""
    guide = (ROOT / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")
    section = guide.split("## Airgap / Machine Transfer Scenario", 1)[1].split("\n---", 1)[0]
    normalized = " ".join(section.split())
    assert "export --only-manual --with-kg" in section
    assert "Mined drawers are path-bound" in normalized
    assert "Never combine a full export with a mine of a moved directory" in normalized
    assert "(e.g., migrating to a new machine)" not in guide


def test_machine_transfer_runbook_keeps_conversation_wings():
    """REG gap-4 review: --only-manual skips convo_turn_v1, so the flow must re-mine
    conversation directories (or carry their wings) and fail loudly on a missing wing."""
    guide = (ROOT / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")
    section = guide.split("## Airgap / Machine Transfer Scenario", 1)[1].split("\n---", 1)[0]
    blocks = re.findall(r"```bash\n(.*?)```", section, re.S)
    connected, carried, target = blocks[0], blocks[1], blocks[2]
    inventory = "mempalace-code status | sed -n 's/^  WING: //p' | sort"
    assert f"{inventory} > palace_wings.txt" in connected
    assert connected.index(inventory) < connected.index("export --only-manual")
    assert "--mode convos" in target
    assert f"{inventory} | diff -u palace_wings.txt -" in target
    assert target.index("import palace_manual.jsonl") < target.index("diff -u")
    assert "export --wing" in carried
    assert "import palace_wing_" in carried
