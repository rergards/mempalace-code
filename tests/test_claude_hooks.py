"""Behavior tests for the legacy Claude Code hook scripts in hooks/."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SAVE_HOOK = ROOT / "hooks" / "mempal_save_hook.sh"
PRECOMPACT_HOOK = ROOT / "hooks" / "mempal_precompact_hook.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="hook scripts need bash and python3",
)


def _run(hook: Path, payload: dict, home: Path, bin_dir: Path | None = None):
    env = {**os.environ, "HOME": str(home)}
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=30,
    )


def _prompt(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def _tool_round(i: int) -> list[dict]:
    tool_use = {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {}}
    tool_result = {"type": "tool_result", "tool_use_id": f"t{i}", "content": "ok"}
    return [
        {"type": "assistant", "message": {"role": "assistant", "content": [tool_use]}},
        {"type": "user", "message": {"role": "user", "content": [tool_result]}},
    ]


def _transcript(path: Path, prompts: int, tool_rounds: int) -> Path:
    entries: list[dict] = []
    for p in range(prompts):
        entries.append(_prompt(f"prompt {p}"))
        for t in range(tool_rounds):
            entries.extend(_tool_round(p * tool_rounds + t))
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def _log(home: Path) -> str:
    return (home / ".mempalace" / "hook_state" / "hook.log").read_text(encoding="utf-8")


def test_save_hook_counts_only_human_prompts(tmp_path):
    transcript = _transcript(tmp_path / "t.jsonl", prompts=1, tool_rounds=16)
    harness_entries = [
        {**_prompt("<local-command-caveat>x</local-command-caveat>"), "isMeta": True},
        _prompt("<command-message>verify</command-message>\n<command-name>/verify</command-name>"),
        _prompt("<local-command-stdout>ok</local-command-stdout>"),
        _prompt("<task-notification>done</task-notification>"),
        {**_prompt("Summary of the earlier conversation"), "isCompactSummary": True},
        {**_prompt("subagent task"), "isSidechain": True},
    ]
    with transcript.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(e) + "\n" for e in harness_entries)
    payload = {"session_id": "tools", "stop_hook_active": False, "transcript_path": str(transcript)}

    result = _run(SAVE_HOOK, payload, tmp_path)

    assert json.loads(result.stdout) == {}
    assert "Session tools: 1 exchanges, 1 since last save" in _log(tmp_path)


def test_save_hook_blocks_once_per_interval_of_human_prompts(tmp_path):
    transcript = _transcript(tmp_path / "t.jsonl", prompts=15, tool_rounds=2)
    payload = {"session_id": "chat", "stop_hook_active": False, "transcript_path": str(transcript)}

    first = _run(SAVE_HOOK, payload, tmp_path)
    looped = _run(SAVE_HOOK, {**payload, "stop_hook_active": True}, tmp_path)
    second = _run(SAVE_HOOK, payload, tmp_path)

    assert json.loads(first.stdout)["decision"] == "block"
    assert "TRIGGERING SAVE at exchange 15" in _log(tmp_path)
    assert json.loads(looped.stdout) == {}
    assert json.loads(second.stdout) == {}


def test_precompact_hook_never_blocks_compaction(tmp_path):
    payload = {"session_id": "pc", "hook_event_name": "PreCompact", "trigger": "auto"}

    result = _run(PRECOMPACT_HOOK, payload, tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert "PRE-COMPACT triggered for session pc" in _log(tmp_path)


@pytest.mark.parametrize("hook", [SAVE_HOOK, PRECOMPACT_HOOK], ids=["save", "precompact"])
def test_hooks_mine_mempal_dir_in_convos_mode(tmp_path, hook):
    convos = tmp_path / "convos"
    convos.mkdir()
    args_file = tmp_path / "mine-args.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_cli = bin_dir / "mempalace-code"
    fake_cli.write_text(
        f"#!/bin/bash\nprintf '%s\\n' \"$@\" > '{args_file}.tmp' && mv '{args_file}.tmp' '{args_file}'\n",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    configured = tmp_path / hook.name
    script = hook.read_text(encoding="utf-8").replace('MEMPAL_DIR=""', f'MEMPAL_DIR="{convos}"', 1)
    assert f'MEMPAL_DIR="{convos}"' in script
    configured.write_text(script, encoding="utf-8")
    transcript = _transcript(tmp_path / "t.jsonl", prompts=15, tool_rounds=0)
    payload = {"session_id": "mine", "stop_hook_active": False, "transcript_path": str(transcript)}

    _run(configured, payload, tmp_path, bin_dir=bin_dir)

    deadline = time.monotonic() + 10
    while not args_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "mine",
        str(convos),
        "--mode",
        "convos",
    ]


def _blocks(text: str) -> dict:
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def test_save_hook_ignores_interrupts_and_system_reminders_in_list_content(tmp_path):
    """REG hooks-6: list-form harness entries are not human prompts."""
    entries = [_blocks(f"real prompt {i}") for i in range(10)]
    entries += [_blocks("[Request interrupted by user for tool use]") for _ in range(5)]
    entries += [_blocks("<system-reminder>background task finished</system-reminder>")] * 5
    entries.append(_prompt("[Request interrupted by user]"))
    entries.append(_prompt("<system-reminder>todo list changed</system-reminder>"))
    # A reminder attached to a real prompt, and an image-only prompt, still count.
    entries.append(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<system-reminder>context</system-reminder>"},
                    {"type": "text", "text": "real prompt with reminder"},
                ],
            },
        }
    )
    entries.append(
        {"type": "user", "message": {"role": "user", "content": [{"type": "image", "source": {}}]}}
    )
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    payload = {"session_id": "intr", "stop_hook_active": False, "transcript_path": str(transcript)}

    result = _run(SAVE_HOOK, payload, tmp_path)

    assert json.loads(result.stdout) == {}
    assert "Session intr: 12 exchanges, 12 since last save" in _log(tmp_path)


@pytest.mark.parametrize("separator", ["\n", " "])
def test_save_hook_counts_text_typed_after_an_interrupt_notice(tmp_path, separator):
    """A leading interrupt notice is dropped; the prompt typed after it still counts."""
    entries = [
        _prompt(f"[Request interrupted by user]{separator}Actually do Y instead"),
        _blocks(f"[Request interrupted by user for tool use]{separator}and also Z"),
        _prompt("[Request interrupted by user]"),
    ]
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    payload = {"session_id": "typed", "stop_hook_active": False, "transcript_path": str(transcript)}

    _run(SAVE_HOOK, payload, tmp_path)

    assert "Session typed: 2 exchanges, 2 since last save" in _log(tmp_path)


def _configured_copy(hook: Path, target: Path, **values: str) -> Path:
    script = hook.read_text(encoding="utf-8")
    for name, value in values.items():
        assert f'{name}=""' in script
        script = script.replace(f'{name}=""', f'{name}="{value}"', 1)
    target.write_text(script, encoding="utf-8")
    return target


@pytest.mark.parametrize("hook", [SAVE_HOOK, PRECOMPACT_HOOK], ids=["save", "precompact"])
def test_copied_hook_uses_mempalace_bin_outside_path(tmp_path, hook):
    """REG hooks-8: a hook copied out of the repository reaches a non-PATH install."""
    convos = tmp_path / "convos"
    convos.mkdir()
    args_file = tmp_path / "mine-args.txt"
    install = tmp_path / "venv" / "bin"
    install.mkdir(parents=True)
    fake_cli = install / "mempalace-code"
    fake_cli.write_text(
        f"#!/bin/bash\nprintf '%s\\n' \"$@\" > '{args_file}.tmp' && mv '{args_file}.tmp' '{args_file}'\n",
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)
    copied_dir = tmp_path / "downloaded"
    copied_dir.mkdir()
    configured = _configured_copy(
        hook, copied_dir / hook.name, MEMPAL_DIR=str(convos), MEMPALACE_BIN=str(fake_cli)
    )
    transcript = _transcript(tmp_path / "t.jsonl", prompts=15, tool_rounds=0)
    payload = {"session_id": "bin", "stop_hook_active": False, "transcript_path": str(transcript)}
    env = {**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}

    subprocess.run(
        ["bash", str(configured)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=True,
        timeout=30,
    )

    deadline = time.monotonic() + 10
    while not args_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "mine",
        str(convos),
        "--mode",
        "convos",
    ]


@pytest.mark.parametrize("hook", [SAVE_HOOK, PRECOMPACT_HOOK], ids=["save", "precompact"])
def test_copied_hook_without_cli_logs_recovery_and_never_imports_cwd(tmp_path, hook):
    """REG hooks-8: no CLI means one actionable log line, not a cwd package import."""
    convos = tmp_path / "convos"
    convos.mkdir()
    decoy = tmp_path / "work" / "mempalace_code"
    decoy.mkdir(parents=True)
    marker = tmp_path / "decoy-imported"
    (decoy / "__init__.py").write_text(f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")
    (decoy / "__main__.py").write_text("", encoding="utf-8")
    copied_dir = tmp_path / "downloaded"
    copied_dir.mkdir()
    configured = _configured_copy(hook, copied_dir / hook.name, MEMPAL_DIR=str(convos))
    transcript = _transcript(tmp_path / "t.jsonl", prompts=15, tool_rounds=0)
    payload = {"session_id": "none", "stop_hook_active": False, "transcript_path": str(transcript)}
    env = {**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}

    result = subprocess.run(
        ["bash", str(configured)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path / "work",
        check=True,
        timeout=30,
    )

    assert result.returncode == 0
    deadline = time.monotonic() + 10
    while "MEMPALACE_BIN" not in _log(tmp_path) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "set MEMPALACE_BIN in" in _log(tmp_path)
    assert not marker.exists()
