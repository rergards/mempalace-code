"""UAT round-2 regressions for conversation mining, split, diary, compress hints and hooks."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mempalace_code import convo_miner
from mempalace_code.convo_miner import (
    EXCHANGE_CHUNKER_STRATEGY,
    GENERAL_CHUNKER_STRATEGY,
    chunk_exchanges,
    mine_convos,
)
from mempalace_code.normalize import normalize
from mempalace_code.storage import open_store

REPO = Path(__file__).resolve().parents[1]
INTERRUPT = "[Request interrupted by user for tool use]"


def _user(content, **extra):
    return {"type": "user", "message": {"role": "user", "content": content}, **extra}


def _assistant(content):
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _jsonl(rows):
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def _messages(transcript) -> tuple:
    """The ``(role, text)`` turns a structured export was normalized from."""
    return getattr(transcript, "messages", ())


def _rows(palace):
    store = open_store(palace, create=False, read_only=True)
    return store.get(include=["documents", "metadatas"], limit=100000)


def _run_cli(argv):
    from mempalace_code.cli import main

    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        main()


@pytest.fixture(autouse=True)
def _no_optimize(monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")


# ── r1-hooks-5: interrupt notices are harness events, not user turns ───────────


@pytest.mark.parametrize(
    "notice",
    [[{"type": "text", "text": INTERRUPT}], INTERRUPT, "[Request interrupted by user]"],
    ids=["list", "string", "string-short"],
)
def test_interrupt_notice_keeps_the_answer_with_its_prompt(tmp_path, notice):
    source = tmp_path / "s.jsonl"
    source.write_text(
        _jsonl(
            [
                _user("Real prompt ALPHA about caching"),
                _assistant(
                    [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]
                ),
                _user([{"type": "tool_result", "tool_use_id": "t1", "content": "out"}]),
                _user(notice),
                _assistant([{"type": "text", "text": "Answer ALPHA: use an LRU cache."}]),
                _user("Real prompt BETA"),
                _assistant("Answer BETA"),
            ]
        ),
        encoding="utf-8",
    )

    chunks = chunk_exchanges(normalize(str(source)))

    text = "\n".join(chunk["content"] for chunk in chunks)
    assert "Request interrupted" not in text
    alpha = next(chunk["content"] for chunk in chunks if "ALPHA" in chunk["content"])
    assert alpha.startswith("> Real prompt ALPHA about caching\n[Bash: ls]\nout")
    assert "Answer ALPHA: use an LRU cache." in alpha


def test_standalone_interrupt_notice_is_not_filed(tmp_path):
    source = tmp_path / "s.jsonl"
    rows = []
    for n in range(10):
        rows += [
            _user([{"type": "text", "text": f"Prompt {n}: detail marker HUMAN{n:03d} please"}]),
            _user([{"type": "text", "text": INTERRUPT}]),
            _assistant(f"Answer {n}: ANSWER{n:03d} done with the change."),
        ]
    rows.append(_user([{"type": "text", "text": INTERRUPT}]))
    source.write_text(_jsonl(rows), encoding="utf-8")

    normalized = normalize(str(source))

    assert [role for role, _ in _messages(normalized)].count("user") == 10
    assert "Request interrupted" not in normalized


def test_interrupt_after_system_reminder_is_not_a_prompt(tmp_path):
    source = tmp_path / "s.jsonl"
    source.write_text(
        _jsonl(
            [
                _user("Real prompt ALPHA about caching"),
                _user(
                    [
                        {
                            "type": "text",
                            "text": "<system-reminder>\nnote\n</system-reminder>\n" + INTERRUPT,
                        }
                    ]
                ),
                _assistant("Answer ALPHA: use an LRU cache."),
            ]
        ),
        encoding="utf-8",
    )

    normalized = normalize(str(source))

    assert _messages(normalized) == (
        ("user", "Real prompt ALPHA about caching"),
        ("assistant", "Answer ALPHA: use an LRU cache."),
    )


@pytest.mark.parametrize(
    "entry",
    [
        [
            {"type": "tool_result", "tool_use_id": "t1", "content": INTERRUPT, "is_error": True},
            {"type": "text", "text": "Actually do X instead, CANARY_TYPED"},
        ],
        "[Request interrupted by user]\nActually do X instead, CANARY_TYPED",
        "[Request interrupted by user]Actually do X instead, CANARY_TYPED",
        [{"type": "text", "text": INTERRUPT + "Actually do X instead, CANARY_TYPED"}],
        [{"type": "text", "text": INTERRUPT + "\n\nActually do X instead, CANARY_TYPED"}],
    ],
    ids=[
        "tool-result-then-text",
        "string-notice-then-text",
        "string-same-line-text",
        "block-same-line-text",
        "block-notice-then-text",
    ],
)
def test_text_typed_after_an_interrupt_notice_is_kept(tmp_path, entry):
    source = tmp_path / "s.jsonl"
    source.write_text(
        _jsonl(
            [
                _user("First prompt here please"),
                _assistant(
                    [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls"}}]
                ),
                _user(entry),
                _assistant("ok doing X"),
            ]
        ),
        encoding="utf-8",
    )

    normalized = normalize(str(source))

    assert _messages(normalized) == (
        ("user", "First prompt here please"),
        ("assistant", "[Bash: ls]"),
        ("user", "Actually do X instead, CANARY_TYPED"),
        ("assistant", "ok doing X"),
    )


# ── convos-2: shell-mode wrappers on one line ──────────────────────────────────


def test_shell_mode_stdout_and_stderr_on_one_line_are_dropped(tmp_path):
    source = tmp_path / "s.jsonl"
    source.write_text(
        _jsonl(
            [
                _user("<bash-input>ls -la</bash-input>"),
                _user("<bash-stdout>total 0</bash-stdout><bash-stderr>errLEAK</bash-stderr>"),
                _user("Real prompt about the deploy"),
                _assistant("Answer about the deploy."),
            ]
        ),
        encoding="utf-8",
    )

    normalized = normalize(str(source))

    assert "bash-" not in normalized
    assert "errLEAK" not in normalized
    assert _messages(normalized)[0] == ("user", "Real prompt about the deploy")


# ── convos-3: block and part boundaries keep a newline ─────────────────────────


def test_claude_ai_blocks_and_chatgpt_parts_keep_line_breaks(tmp_path):
    claude_ai = tmp_path / "claude.json"
    claude_ai.write_text(
        json.dumps(
            [
                {
                    "uuid": "c1",
                    "chat_messages": [
                        {
                            "sender": "human",
                            "content": [
                                {"type": "text", "text": "First para MB_Q1."},
                                {"type": "text", "text": "Second para MB_Q2."},
                            ],
                        },
                        {
                            "sender": "assistant",
                            "content": [
                                {"type": "text", "text": "Block one.\n```sh\nmake deploy\n```"},
                                {"type": "text", "text": "Block two MB_A2."},
                            ],
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    mapping = {
        "root": {"id": "root", "parent": None, "message": None, "children": ["u"]},
        "u": {
            "id": "u",
            "parent": "root",
            "children": ["a"],
            "message": {"author": {"role": "user"}, "content": {"parts": ["GPT question"]}},
        },
        "a": {
            "id": "a",
            "parent": "u",
            "children": [],
            "message": {
                "author": {"role": "assistant"},
                "content": {"parts": ["GPT part one GP1.", "GPT part two GP2."]},
            },
        },
    }
    chatgpt = tmp_path / "conversations.json"
    chatgpt.write_text(json.dumps([{"mapping": mapping, "current_node": "a"}]), encoding="utf-8")

    claude_text = normalize(str(claude_ai))
    assert "> First para MB_Q1.\nSecond para MB_Q2." in claude_text
    assert "```sh\nmake deploy\n```\nBlock two MB_A2." in claude_text
    assert "GPT part one GP1.\nGPT part two GP2." in normalize(str(chatgpt))


# ── convos-4: only the first line of a user turn is marked ─────────────────────


def test_multiline_user_turn_is_stored_verbatim_after_its_marker(tmp_path):
    pasted = "Here is our config, please review:\n<config>\n  <db>XML_DB_CANARY</db>\n</config>"
    source = tmp_path / "s.jsonl"
    source.write_text(
        _jsonl([_user(pasted), _assistant("The config looks right to me.")]), encoding="utf-8"
    )

    chunks = chunk_exchanges(normalize(str(source)))

    assert chunks[0]["content"] == f"> {pasted}\nThe config looks right to me."


# ── convos-8: a UTF-8 byte-order mark is not text ──────────────────────────────


def test_byte_order_mark_is_not_stored(tmp_path):
    source = tmp_path / "bom.txt"
    source.write_bytes(
        b"\xef\xbb\xbf> BOM question about widgets here?\nBOM_CANARY: widgets ship Friday.\n"
    )
    bom_json = tmp_path / "bom.jsonl"
    bom_json.write_bytes(
        b"\xef\xbb\xbf" + _jsonl([_user("BOM prompt"), _assistant("BOM answer")]).encode()
    )

    assert normalize(str(source)).startswith("> BOM question")
    assert _messages(normalize(str(bom_json)))[0] == ("user", "BOM prompt")


# ── chunker strategy: normalization changes rebuild old rows ───────────────────


def test_strategies_are_bumped_so_old_rows_are_rebuilt():
    assert EXCHANGE_CHUNKER_STRATEGY == "convo_turn_v3"
    assert GENERAL_CHUNKER_STRATEGY == "convo_general_v2"
    doc = (REPO / "docs" / "BACKUP_RESTORE.md").read_text(encoding="utf-8")
    assert f"`{EXCHANGE_CHUNKER_STRATEGY}`" in doc
    assert f"`{GENERAL_CHUNKER_STRATEGY}`" in doc


# ── convos-5: a short transcript is filed; an empty one is named ───────────────


def test_short_transcript_is_filed_and_empty_one_is_named(tmp_path, capsys):
    convos = tmp_path / "short"
    convos.mkdir()
    (convos / "quick.jsonl").write_text(
        _jsonl([_user("Use pnpm?"), _assistant("Yes, pnpm.")]), encoding="utf-8"
    )
    (convos / "empty.txt").write_text("  \n\n", encoding="utf-8")
    palace = str(tmp_path / "palace")

    result = mine_convos(str(convos), palace)

    out = capsys.readouterr().out
    assert result["drawers_filed"] == 1
    assert result["files_tiny"] == 1
    assert "skipped empty.txt: no conversation text" in out
    assert _rows(palace)["documents"] == ["> Use pnpm?\nYes, pnpm."]


# ── convos-6: one transcript mined on its own keeps its wing ───────────────────


def test_single_file_mine_reuses_the_wing_that_holds_it(tmp_path, capsys):
    convos = tmp_path / "c3"
    (convos / "plain").mkdir(parents=True)
    transcript = convos / "plain" / "heron_meeting.txt"
    transcript.write_text(
        "> Who owns the schema registry?\nThe platform team owns the schema registry.\n",
        encoding="utf-8",
    )
    palace = str(tmp_path / "palace")
    mine_convos(str(convos), palace)
    capsys.readouterr()

    dry = mine_convos(str(transcript), palace, dry_run=True)
    assert "Wing:    c3 (the wing that already holds this transcript)" in capsys.readouterr().out
    assert dry["files_skipped"] == 1

    transcript.write_text(transcript.read_text() + "> And the rollout?\nNext sprint.\n")
    mine_convos(str(transcript), palace)

    assert {meta["wing"] for meta in _rows(palace)["metadatas"]} == {"c3"}

    other = tmp_path / "fresh" / "new.txt"
    other.parent.mkdir()
    other.write_text("> A new question here?\nA new answer here.\n", encoding="utf-8")
    mine_convos(str(other), palace)
    assert {meta["wing"] for meta in _rows(palace)["metadatas"]} == {"c3", "fresh"}


# ── r1-convos-30: printed commands run this install, without --no-spellcheck ───


def test_convos_hints_use_this_install_and_omit_no_spellcheck(tmp_path, capsys):
    convos = tmp_path / "cv"
    convos.mkdir()
    gone = convos / "old.txt"
    gone.write_text("> Old question here?\nOld answer text here.\n", encoding="utf-8")
    (convos / "keep.txt").write_text("> Kept question?\nKept answer here.\n", encoding="utf-8")
    palace = str(tmp_path / "palace")
    mine_convos(str(convos), palace)
    gone.unlink()
    capsys.readouterr()

    with patch.object(convo_miner, "cli_command", wraps=convo_miner.cli_command) as command:
        mine_convos(str(convos), palace)

    out = capsys.readouterr().out
    assert "Next: mempalace-code" not in out
    assert ": mempalace-code --palace" not in out
    assert "--no-spellcheck" not in out
    remove_line = next(line for line in out.splitlines() if "To remove those drawers:" in line)
    tokens = shlex.split(remove_line.split("To remove those drawers: ", 1)[1])
    assert tokens[tokens.index("--palace") :] == [
        "--palace",
        palace,
        "mine",
        str(convos),
        "--mode",
        "convos",
        "--wing",
        "cv",
        "--full",
    ]
    assert command.call_count == 2


# ── convos-7: general excerpts stay inside one exchange ────────────────────────


def test_general_excerpts_never_span_exchanges(tmp_path):
    steps = "\n".join(
        f"{n}. Roll shard {n} after checking the replication lag." for n in range(1, 41)
    )
    transcript = (
        "> Give me the full 40-step shard rollout plan\n"
        f"We decided on this plan:\n{steps}\n\n"
        "> Which serialization format for Heron?\n"
        "Decision: Heron uses Protobuf, because we need schema evolution.\n"
    )
    source = tmp_path / "plan.txt"
    source.write_text(transcript, encoding="utf-8")
    palace = str(tmp_path / "palace")

    mine_convos(str(tmp_path), palace, wing="gx", extract_mode="general")

    excerpts = [
        doc
        for doc, meta in zip(*(_rows(palace)[key] for key in ("documents", "metadatas")))
        if meta["extract_mode"] == "general"
    ]
    exchanges = [chunk["content"] for chunk in chunk_exchanges(transcript)]
    assert excerpts
    for excerpt in excerpts:
        assert any(excerpt in exchange for exchange in exchanges), excerpt
    assert not any("Roll shard" in e and "Protobuf" in e for e in excerpts)


# ── docs: spellcheck is a no-op everywhere ─────────────────────────────────────


def test_readme_never_claims_mined_turns_are_spell_corrected():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "spell-corrected unless" not in readme
    assert "`--spellcheck`/`--no-spellcheck` are deprecated no-ops" in readme


# ── gap-12: the watch-extra snippet lists every extra ──────────────────────────


def test_readme_watch_extra_snippet_keeps_other_extras():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert 'uv tool install "mempalace-code[watch]"   # or: pipx inject' not in readme
    assert 'uv tool install --force "mempalace-code[watch,treesitter]"' in readme


# ── hooks: state file and session id are data, never code ──────────────────────


def _hook_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMPAL")}
    env["HOME"] = str(home)
    return env


@pytest.mark.skipif(sys.platform == "win32", reason="bash hooks")
def test_save_hook_never_evaluates_its_state_file(tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(_jsonl([_user(f"prompt {n}") for n in range(20)]), encoding="utf-8")
    state = tmp_path / ".mempalace" / "hook_state"
    state.mkdir(parents=True)
    pwned = tmp_path / "PWNED"
    payload = json.dumps(
        {"session_id": "s1", "stop_hook_active": False, "transcript_path": str(transcript)}
    )
    for content in (f"x[$(touch {pwned})]", "5 + 100"):
        (state / "s1_last_save").write_text(content + "\n", encoding="utf-8")
        result = subprocess.run(
            ["bash", str(REPO / "hooks" / "mempal_save_hook.sh")],
            input=payload,
            capture_output=True,
            text=True,
            env=_hook_env(tmp_path),
            check=False,
        )
        assert result.returncode == 0
        assert not pwned.exists()
        assert '"decision": "block"' in result.stdout
    log = (state / "hook.log").read_text(encoding="utf-8")
    assert "Session s1: 20 exchanges, 20 since last save" in log
    assert "-85" not in log


@pytest.mark.skipif(sys.platform == "win32", reason="bash hooks")
def test_precompact_hook_sanitizes_the_logged_session_id(tmp_path):
    payload = json.dumps({"session_id": "x\nTRIGGERING SAVE at exchange 99"})
    result = subprocess.run(
        ["bash", str(REPO / "hooks" / "mempal_precompact_hook.sh")],
        input=payload,
        capture_output=True,
        text=True,
        env=_hook_env(tmp_path),
        check=False,
    )
    assert result.returncode == 0
    log = (tmp_path / ".mempalace" / "hook_state" / "hook.log").read_text(encoding="utf-8")
    assert log.count("\n") == 1
    assert "PRE-COMPACT triggered for session xTRIGGERINGSAVEatexchange99" in log


def test_hooks_readme_downloads_scripts_of_the_installed_version():
    readme = (REPO / "hooks" / "README.md").read_text(encoding="utf-8")
    assert "mempalace-code/main/hooks/" not in readme
    assert "mempalace-code/v${MEMPALACE_VERSION}/hooks/mempal_save_hook.sh" in readme
    assert "mempalace-code/v${MEMPALACE_VERSION}/hooks/mempal_precompact_hook.sh" in readme


# ── split-1 / split-2: backups are never replaced; failed splits leave no outputs ─


def _banner_session(when: str, prompt: str) -> str:
    return (
        "▐▛███▜▌   Claude Code v2.0.14\n\n"
        f"⏺ {when}\n\n> {prompt} question here\n\n⏺ {prompt} answer.\n"
    )


def _split(monkeypatch, directory):
    from mempalace_code import split_mega_files as smf

    monkeypatch.setattr(sys, "argv", ["split", "--source", str(directory)])
    smf.main()


def test_second_split_keeps_the_first_backup(tmp_path, monkeypatch):
    mega = tmp_path / "t.txt"
    first = _banner_session("9:15 AM Monday, September 21, 2026", "FIRSTEXPORT-a")
    first += _banner_session("10:15 AM Monday, September 21, 2026", "FIRSTEXPORT-b")
    mega.write_text(first, encoding="utf-8")
    _split(monkeypatch, tmp_path)
    second = _banner_session("11:15 AM Monday, September 21, 2026", "SECONDEXPORT-a")
    second += _banner_session("12:15 PM Monday, September 21, 2026", "SECONDEXPORT-b")
    mega.write_text(second, encoding="utf-8")

    _split(monkeypatch, tmp_path)

    assert (tmp_path / "t.mega_backup").read_text(encoding="utf-8") == first
    assert (tmp_path / "t.1.mega_backup").read_text(encoding="utf-8") == second
    assert not mega.exists()


def test_failed_split_removes_its_partial_outputs(tmp_path, monkeypatch, capsys):
    short = "▐▛███▜▌   Claude Code v2.0.14\n\n> short-one question\n\n⏺ short.\n"
    mega = tmp_path / "t.txt"
    mega.write_text(
        _banner_session("9:15 AM Monday, September 21, 2026", "KESTREL-first") + short,
        encoding="utf-8",
    )
    _split(monkeypatch, tmp_path)
    before = sorted(path.name for path in tmp_path.iterdir())
    retry = _banner_session("9:15 AM Tuesday, September 22, 2026", "How should Kestrel retry")
    mega.write_text(retry + short, encoding="utf-8")
    capsys.readouterr()

    with pytest.raises(SystemExit) as raised:
        _split(monkeypatch, tmp_path)

    assert raised.value.code == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted([*before, "t.txt"])
    assert "no split files kept; original left in place as t.txt" in capsys.readouterr().out


# ── compress-1: a recovery preview exits like the real run; convos hint ────────


def _cli(capsys, *argv):
    try:
        _run_cli(list(argv))
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_recovery_preview_exits_1_and_names_the_convos_rebuild(tmp_path, capsys):
    from mempalace_code.backup import create_backup

    other = tmp_path / "other"
    open_store(str(other), create=True).add(
        ids=["drawer_unrelated"],
        documents=["An unrelated drawer in another palace."],
        metadatas=[{"wing": "x", "room": "y", "chunker_strategy": "manual_v1"}],
    )
    _meta, archive = create_backup(str(other), kind="manual")

    convos = tmp_path / "c2"
    convos.mkdir()
    (convos / "chat.txt").write_text(
        "> Which queue for Kestrel?\nKestrel uses the durable queue with retries.\n",
        encoding="utf-8",
    )
    palace = str(tmp_path / "palace")
    mine_convos(str(convos), palace)
    store = open_store(palace, create=False)
    got = store.get(include=["documents", "metadatas"])
    for doc_id, meta in zip(got["ids"], got["metadatas"]):
        legacy = {**meta, "original_tokens": 12, "compression_ratio": 3.1}
        store.upsert(ids=[doc_id], documents=["KSTRL|queue:durable"], metadatas=[legacy])
    capsys.readouterr()

    results = [
        _cli(capsys, "--palace", palace, "compress", "--recover-from", str(archive), *extra)
        for extra in (["--dry-run"], [])
    ]

    for code, out, err in results:
        assert code == 1
        assert f"Recoverable from {archive}: 0" in out
        assert "Not recoverable from this archive: 1" in err
        assert "conversation drawers with" in err
        assert "mine '<conversations-dir>' --mode convos" not in err
        assert "mine <conversations-dir> --mode convos" in err
        assert "<project-dir>" not in err


# ── r1-convos-17: one agent identity, one diary wing ───────────────────────────


def test_hyphen_and_underscore_agent_names_share_one_diary_wing(tmp_path, capsys):
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.diary import _diary_write

    palace = str(tmp_path / "palace")
    _run_cli(["--palace", palace, "diary", "write", "--agent", "claude-code", "--entry", "DIARY_1"])
    assert "Wing: wing_claude_code" in capsys.readouterr().out
    legacy = open_store(palace, create=False)
    legacy.add(
        ids=["diary_legacy_entry"],
        documents=["LEGACY_ENTRY without agent metadata"],
        metadatas=[{"wing": "wing_claude-code", "room": "diary", "filed_at": "2020-01-01"}],
    )

    # The handler body, without the MCP lease wrapper, against this test palace.
    with patch.object(runtime, "_get_store", lambda create=False: open_store(palace)):
        result = _diary_write.__wrapped__(
            agent_name="claude_code", entry="MCP_DIARY", topic="general"
        )

    assert result["wing"] == "wing_claude_code"
    from mempalace_code.diary import read_entries

    read = read_entries(open_store(palace, create=False), "claude-code")
    assert {entry["content"] for entry in read["entries"]} == {
        "DIARY_1",
        "MCP_DIARY",
        "LEGACY_ENTRY without agent metadata",
    }
    wings = {
        meta["wing"] for meta in _rows(palace)["metadatas"] if meta.get("type") == "diary_entry"
    }
    assert wings == {"wing_claude_code"}


def test_upgraded_palace_keeps_the_hyphenated_diary_wing(tmp_path, capsys):
    """A diary filed by an earlier release under wing_claude-code is not split in two."""
    from mempalace_code.mcp import runtime
    from mempalace_code.mcp.tools.diary import _diary_write

    palace = str(tmp_path / "palace")
    store = open_store(palace, create=True)
    store.add(
        ids=["diary_wing_claude-code_old"],
        documents=["OLD_ENTRY from 1.14"],
        metadatas=[
            {
                "wing": "wing_claude-code",
                "room": "diary",
                "hall": "hall_diary",
                "topic": "general",
                "type": "diary_entry",
                "agent": "claude-code",
                "filed_at": "2026-01-01T00:00:00",
                "date": "2026-01-01",
            }
        ],
    )

    _run_cli(["--palace", palace, "diary", "write", "--agent", "claude-code", "--entry", "NEW_1"])
    assert "Wing: wing_claude-code" in capsys.readouterr().out
    with patch.object(runtime, "_get_store", lambda create=False: open_store(palace)):
        result = _diary_write.__wrapped__(agent_name="Claude Code", entry="NEW_2", topic="general")

    assert result["wing"] == "wing_claude-code"
    taxonomy = open_store(palace, create=False).count_by_pair("wing", "room")
    assert taxonomy == {"wing_claude-code": {"diary": 3}}


def test_blank_diary_field_hint_runs_this_install_on_the_users_palace(tmp_path, capsys):
    from mempalace_code.cli_invocation import cli_prefix

    palace = str(tmp_path / "my palace")
    with pytest.raises(SystemExit) as exc:
        _run_cli(["--palace", palace, "diary", "write", "--agent", "a", "--entry", ""])

    assert exc.value.code == 2
    hint = capsys.readouterr().err.splitlines()[-1]
    with patch.object(sys, "argv", ["mempalace-code"]):
        prefix = " ".join(shlex.quote(token) for token in cli_prefix())
    assert hint == (
        f"Try: {prefix} --palace {shlex.quote(palace)} diary write --agent agent-name "
        "--entry 'your diary entry'"
    )


def test_split_backup_never_replaces_a_backup_created_after_the_check(tmp_path, monkeypatch):
    """A concurrent split that takes the backup name first keeps its backup."""
    from mempalace_code import split_mega_files

    source = tmp_path / "t.txt"
    source.write_text("SECOND ORIGINAL", encoding="utf-8")
    real_link = os.link

    def racing_link(src, dst):
        if Path(dst).name == "t.mega_backup":
            Path(dst).write_text("FIRST EXPORT", encoding="utf-8")
        real_link(src, dst)

    monkeypatch.setattr(split_mega_files.os, "link", racing_link)

    backup = split_mega_files._move_to_unused_backup(source)

    assert backup.name == "t.1.mega_backup"
    assert (tmp_path / "t.mega_backup").read_text(encoding="utf-8") == "FIRST EXPORT"
    assert backup.read_text(encoding="utf-8") == "SECOND ORIGINAL"
    assert not source.exists()
