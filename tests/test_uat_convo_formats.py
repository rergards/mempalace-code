"""UAT regressions for conversation formats, verbatim storage, and split.

Fixtures follow the documented export schemas with synthetic content only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mempalace_code.convo_miner import mine_convos
from mempalace_code.normalize import normalize
from mempalace_code.storage import open_store

ROOT = Path(__file__).parent.parent


def _drawers(palace: Path) -> list[str]:
    return open_store(str(palace), create=False).get(include=["documents"])["documents"]


def _user_turns(transcript: str) -> list[str]:
    return [line for line in transcript.split("\n") if line.startswith("> ")]


# ---------------------------------------------------------------------------
# Spellcheck never rewrites stored text (convos-1, hooks-2, ops-8)
# ---------------------------------------------------------------------------

_TECH_TERMS = "we use nginx pytest pydantic postgres pgvector async dedupe"


def _fake_autocorrect(text: str) -> str:
    """Stand-in for the [spellcheck] extra's autocorrect rewrites seen in UAT."""
    for wrong, right in (("pgvector", "vector"), ("pytest", "bytes"), ("nginx", "engine")):
        text = text.replace(wrong, right)
    return text


def test_normalize_keeps_plain_user_turns_verbatim_even_with_spellcheck(tmp_path):
    content = f"> {_TECH_TERMS}\nok noted.\n\n>  decidd insted invoises\nfine.\n"
    path = tmp_path / "words.txt"
    path.write_text(content, encoding="utf-8")

    with patch("mempalace_code.spellcheck.spellcheck_user_text", side_effect=_fake_autocorrect):
        assert normalize(str(path), spellcheck=True) == content
        assert normalize(str(path)) == content


def test_normalize_keeps_json_user_turns_verbatim_even_with_spellcheck(tmp_path):
    rows = [
        {"type": "user", "message": {"role": "user", "content": f"use {_TECH_TERMS}"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "Noted."}},
    ]
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    with patch("mempalace_code.spellcheck.spellcheck_user_text", side_effect=_fake_autocorrect):
        result = normalize(str(path), spellcheck=True)

    assert f"> use {_TECH_TERMS}" in result


def test_real_autocorrect_never_touches_mined_text(tmp_path):
    pytest.importorskip("autocorrect")
    content = f"> {_TECH_TERMS} retries backoff upserts cron jsonl yaml toml\nok.\n"
    path = tmp_path / "words.txt"
    path.write_text(content, encoding="utf-8")

    assert normalize(str(path), spellcheck=True) == content


def test_mine_convos_with_spellcheck_stores_verbatim_drawers(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    source = tmp_path / "spell"
    source.mkdir()
    lines = [
        f"> {_TECH_TERMS} one",
        "ok noted.",
        "",
        f"> {_TECH_TERMS} two",
        "ok noted too.",
        "",
        f"> {_TECH_TERMS} three",
        "fine.",
        "",
    ]
    (source / "words.txt").write_text("\n".join(lines), encoding="utf-8")
    palace = tmp_path / "palace"

    with patch("mempalace_code.spellcheck.spellcheck_user_text", side_effect=_fake_autocorrect):
        mine_convos(str(source), str(palace), wing="spell", spellcheck=True)

    drawers = _drawers(palace)
    assert len(drawers) == 3
    assert all(_TECH_TERMS in drawer for drawer in drawers)


def _run_mine_cli(argv, capsys):
    from mempalace_code.cli import main

    with patch.object(sys, "argv", argv):
        main()
    return capsys.readouterr()


def test_cli_convos_mode_defaults_spellcheck_off(tmp_path, capsys):
    with patch("mempalace_code.convo_miner.mine_convos") as mock_mine_convos:
        captured = _run_mine_cli(["mempalace", "mine", str(tmp_path), "--mode", "convos"], capsys)

    assert mock_mine_convos.call_args.kwargs["spellcheck"] is False
    assert "spellcheck" not in captured.err


def test_cli_explicit_spellcheck_prints_verbatim_notice(tmp_path, capsys):
    with patch("mempalace_code.convo_miner.mine_convos"):
        captured = _run_mine_cli(
            ["mempalace", "mine", str(tmp_path), "--mode", "convos", "--spellcheck"], capsys
        )

    assert "spellcheck no longer rewrites mined text" in captured.err
    assert "drawers are stored verbatim" in captured.err


# ---------------------------------------------------------------------------
# Claude Code transcripts (convos-9, hooks-5)
# ---------------------------------------------------------------------------


def _cc(entry_type: str, content, **flags) -> dict:
    role = "user" if entry_type == "user" else "assistant"
    return {"type": entry_type, "message": {"role": role, "content": content}, **flags}


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


_XML_CONFIG = (
    "Here is our Plover config, please review:\n<config>\n"
    "  <db>XML_DB_CANARY postgres-plover-primary</db>\n  <cache>redis</cache>\n</config>"
)
_HTML_ANSWER = (
    "Use this snippet:\n<details>\n"
    "HTML_BLOCK_CANARY: the admin page must escape user input before rendering.\n"
    "</details>\nThat keeps the page safe."
)


def test_claude_code_keeps_user_authored_html_and_xml(tmp_path):
    path = _write_jsonl(
        tmp_path / "html.jsonl",
        [
            _cc("user", _XML_CONFIG),
            _cc("assistant", [{"type": "text", "text": _HTML_ANSWER}]),
            _cc(
                "user",
                "<system-reminder>\nINJECTED_REMINDER_CANARY\n</system-reminder>\nLooks right.",
            ),
            _cc("assistant", "Ran make check; all green."),
        ],
    )

    result = normalize(str(path))

    assert f"> {_XML_CONFIG}\n{_HTML_ANSWER}\n" in result
    assert "INJECTED_REMINDER_CANARY" not in result
    assert "> Looks right." in result


def test_claude_code_strip_requires_matching_closing_tag(tmp_path):
    path = _write_jsonl(
        tmp_path / "mixed.jsonl",
        [
            _cc(
                "user",
                "<system-reminder>\nnoise</system-reminder>\n<note>\nKEEP_CANARY</note>\nplease",
            ),
            _cc("assistant", "Done."),
        ],
    )

    result = normalize(str(path))

    assert "noise" not in result
    assert "> <note>\nKEEP_CANARY</note>\nplease" in result


def _noisy_transcript(path: Path, prompts: int) -> Path:
    rows: list[dict] = []
    for n in range(1, prompts + 1):
        rows += [
            _cc("user", f"Real prompt {n}: explain part {n} of the Plover pipeline"),
            _cc("assistant", [{"type": "tool_use", "id": f"t{n}", "name": "Bash", "input": {}}]),
            _cc("user", [{"type": "tool_result", "tool_use_id": f"t{n}", "content": "ok"}]),
            _cc("user", "Caveat: the messages below were generated by the user.", isMeta=True),
            _cc("user", "<command-name>/status</command-name>\n<command-args></command-args>"),
            _cc("user", "<local-command-stdout>Status: ok</local-command-stdout>"),
            _cc("user", f"Subagent prompt: search part {n}", isSidechain=True),
            _cc("assistant", f"Subagent result {n}", isSidechain=True),
            _cc("user", "<task-notification>\nBackground task finished\n</task-notification>"),
            _cc("assistant", f"Answer {n}: part {n} validates and loads records."),
        ]
    rows.append(_cc("user", "COMPACT_SUMMARY_CANARY earlier context", isCompactSummary=True))
    return _write_jsonl(path, rows)


def test_claude_code_skips_meta_sidechain_and_compaction_entries(tmp_path):
    result = normalize(str(_noisy_transcript(tmp_path / "noise.jsonl", 15)))

    turns = _user_turns(result)
    assert turns == [
        f"> Real prompt {n}: explain part {n} of the Plover pipeline" for n in range(1, 16)
    ]
    for leaked in ("Caveat:", "Subagent", "COMPACT_SUMMARY_CANARY", "Status: ok", "/status"):
        assert leaked not in result
    assert "Answer 15: part 15 validates" in result


def _save_hook_prompt_count(transcript: Path) -> int:
    hook = (ROOT / "hooks" / "mempal_save_hook.sh").read_text(encoding="utf-8")
    counter = re.search(r"<<'PYEOF'\n(.*?)\nPYEOF", hook, re.DOTALL)
    assert counter, "save hook counter block not found"
    completed = subprocess.run(
        [sys.executable, "-c", counter.group(1), str(transcript)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return int(completed.stdout.strip())


def test_claude_code_user_turns_match_save_hook_prompt_count(tmp_path):
    transcript = _noisy_transcript(tmp_path / "noise.jsonl", 15)

    assert len(_user_turns(normalize(str(transcript)))) == _save_hook_prompt_count(transcript)


def test_claude_code_subagent_transcript_is_parsed_not_filed_raw(tmp_path):
    """A subagent's own agent-*.jsonl marks every entry isSidechain; it is still a transcript."""
    path = _write_jsonl(
        tmp_path / "agent-a1b2c3.jsonl",
        [
            _cc("user", "Search the Heron repo for AGENT_CANARY_Q.", isSidechain=True),
            _cc(
                "assistant",
                [{"type": "text", "text": "AGENT_CANARY_A: backoff."}],
                isSidechain=True,
            ),
            _cc("user", "And the alert threshold?", isSidechain=True),
            _cc("assistant", "AGENT_CANARY_B: five failures.", isSidechain=True),
        ],
    )

    assert normalize(str(path)) == (
        "> Search the Heron repo for AGENT_CANARY_Q.\nAGENT_CANARY_A: backoff.\n\n"
        "> And the alert threshold?\nAGENT_CANARY_B: five failures.\n"
    )


def test_claude_code_slash_command_session_keeps_the_typed_command(tmp_path):
    path = _write_jsonl(
        tmp_path / "slash.jsonl",
        [
            _cc(
                "user",
                "<command-message>review is running…</command-message>\n"
                "<command-name>/review</command-name>\n<command-args>PR 42</command-args>",
            ),
            _cc("user", [{"type": "text", "text": "Review PR 42 and list risks."}], isMeta=True),
            _cc("assistant", [{"type": "text", "text": "SLASH_ONLY_ANSWER: no rollback step."}]),
            _cc("user", "<command-name>/model</command-name>\n<command-args></command-args>"),
            _cc("user", "<local-command-stdout>Set model to opus</local-command-stdout>"),
        ],
    )

    result = normalize(str(path))

    assert result == "> /review PR 42\nSLASH_ONLY_ANSWER: no rollback step.\n"
    assert _save_hook_prompt_count(path) == 0


def test_claude_code_single_prompt_is_a_transcript(tmp_path):
    path = _write_jsonl(tmp_path / "one.jsonl", [_cc("user", "ONE_PROMPT_CANARY: plan Heron.")])

    assert normalize(str(path)) == "> ONE_PROMPT_CANARY: plan Heron.\n"


def test_claude_code_transcript_without_turns_refuses_raw_json(tmp_path):
    from mempalace_code.normalize import NotAConversationError

    path = _write_jsonl(
        tmp_path / "meta.jsonl",
        [
            _cc("user", "Caveat: the messages below were generated by the user.", isMeta=True),
            _cc("user", "<command-name>/clear</command-name>\n<command-args></command-args>"),
        ],
    )

    with pytest.raises(NotAConversationError, match="refusing raw JSON fallback"):
        normalize(str(path))


def test_claude_code_short_sessions_mine_as_exchanges(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    source = tmp_path / "sessions"
    (source / "subagents").mkdir(parents=True)
    _write_jsonl(
        source / "subagents" / "agent-a1.jsonl",
        [
            _cc("user", "Search the Heron repo for the retry policy.", isSidechain=True),
            _cc("assistant", "AGENT_CANARY_A: exponential backoff, 30s cap.", isSidechain=True),
        ],
    )
    _write_jsonl(
        source / "slash.jsonl",
        [
            _cc("user", "<command-name>/review</command-name>\n<command-args>PR 42</command-args>"),
            _cc("user", "Review PR 42 and list risks.", isMeta=True),
            _cc("assistant", "SLASH_ONLY_ANSWER: the migration lacks a rollback step."),
        ],
    )
    palace = tmp_path / "palace"

    mine_convos(str(source), str(palace), wing="cc")

    assert sorted(_drawers(palace)) == [
        "> /review PR 42\nSLASH_ONLY_ANSWER: the migration lacks a rollback step.",
        "> Search the Heron repo for the retry policy.\n"
        "AGENT_CANARY_A: exponential backoff, 30s cap.",
    ]


# ---------------------------------------------------------------------------
# ChatGPT exports (convos-3, convos-11)
# ---------------------------------------------------------------------------


def _gpt_node(node_id, parent, children, role=None, text=None, hidden=False) -> dict:
    message = None
    if role is not None:
        message = {
            "id": node_id,
            "author": {"role": role, "name": None, "metadata": {}},
            "create_time": 1758000000.5,
            "content": {"content_type": "text", "parts": [text]},
            "status": "finished_successfully",
            "metadata": {"is_visually_hidden_from_conversation": True} if hidden else {},
            "recipient": "all",
        }
    return {"id": node_id, "message": message, "parent": parent, "children": children}


def _gpt_conversation(cid: str, turns: list[tuple[str, str]]) -> dict:
    mapping = {
        "client-created-root": _gpt_node("client-created-root", None, [f"{cid}-sys"]),
        f"{cid}-sys": _gpt_node(
            f"{cid}-sys", "client-created-root", [f"{cid}-0"], "system", "", hidden=True
        ),
    }
    parent = f"{cid}-sys"
    for i, (role, text) in enumerate(turns):
        node_id = f"{cid}-{i}"
        children = [f"{cid}-{i + 1}"] if i + 1 < len(turns) else []
        mapping[node_id] = _gpt_node(node_id, parent, children, role, text)
        parent = node_id
    return {
        "title": f"Conversation {cid}",
        "create_time": 1758000000.0,
        "mapping": mapping,
        "current_node": parent,
        "id": cid,
    }


def test_official_chatgpt_export_array_is_normalized(tmp_path):
    export = [
        _gpt_conversation(
            "c1",
            [
                ("user", "What cache TTL should Kestrel use?"),
                ("assistant", "GPT_LIST_CANARY1: use a 300 second TTL."),
            ],
        ),
        _gpt_conversation(
            "c2",
            [
                ("user", "Which region hosts the Kestrel queue?"),
                ("assistant", "GPT_LIST_CANARY2: eu-west-1."),
            ],
        ),
    ]
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(export, indent=2), encoding="utf-8")

    assert normalize(str(path)) == (
        "> What cache TTL should Kestrel use?\nGPT_LIST_CANARY1: use a 300 second TTL.\n\n"
        "> Which region hosts the Kestrel queue?\nGPT_LIST_CANARY2: eu-west-1.\n"
    )


def test_official_chatgpt_export_mines_one_drawer_per_exchange(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    source = tmp_path / "chatgpt"
    source.mkdir()
    export = [
        _gpt_conversation(
            f"c{i}",
            [
                ("user", f"Question {i} about the Kestrel cache TTL?"),
                ("assistant", f"GPT_LIST_CANARY{i}: answer with enough detail."),
            ],
        )
        for i in range(3)
    ]
    (source / "conversations.json").write_text(json.dumps(export, indent=2), encoding="utf-8")
    palace = tmp_path / "palace"

    mine_convos(str(source), str(palace), wing="chatgpt")

    drawers = sorted(_drawers(palace))
    assert drawers == [
        f"> Question {i} about the Kestrel cache TTL?\nGPT_LIST_CANARY{i}: answer with enough detail."
        for i in range(3)
    ]


def _branched_mapping() -> dict:
    return {
        "root": _gpt_node("root", None, ["q1"]),
        "q1": _gpt_node("q1", "root", ["a_old", "a_new"], "user", "Which queue for jobs?"),
        "a_old": _gpt_node("a_old", "q1", [], "assistant", "OLD_BRANCH_CANARY: RabbitMQ."),
        "a_new": _gpt_node("a_new", "q1", ["q2"], "assistant", "NEW_BRANCH_CANARY: NATS."),
        "q2": _gpt_node("q2", "a_new", ["a2"], "user", "Why NATS?"),
        "a2": _gpt_node("a2", "q2", [], "assistant", "BRANCH_FOLLOWUP_CANARY: low ops cost."),
    }


def test_branched_chatgpt_conversation_follows_current_node(tmp_path):
    path = tmp_path / "branched.json"
    path.write_text(
        json.dumps({"mapping": _branched_mapping(), "current_node": "a2"}), encoding="utf-8"
    )

    assert normalize(str(path)) == (
        "> Which queue for jobs?\nNEW_BRANCH_CANARY: NATS.\n\n"
        "> Why NATS?\nBRANCH_FOLLOWUP_CANARY: low ops cost.\n"
    )


def test_branched_chatgpt_without_current_node_takes_newest_branch(tmp_path):
    path = tmp_path / "branched.json"
    path.write_text(json.dumps({"mapping": _branched_mapping()}), encoding="utf-8")

    result = normalize(str(path))

    assert "OLD_BRANCH_CANARY" not in result
    assert "NEW_BRANCH_CANARY" in result
    assert "BRANCH_FOLLOWUP_CANARY" in result


def test_chatgpt_export_skips_a_malformed_conversation_and_keeps_the_rest(tmp_path, capsys):
    export = [
        _gpt_conversation(
            "c1",
            [("user", "What cache TTL should Kestrel use?"), ("assistant", "GPT_OK_CANARY: 300s.")],
        ),
        {"title": "broken", "mapping": None, "current_node": None},
    ]
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(export), encoding="utf-8")

    assert normalize(str(path)) == "> What cache TTL should Kestrel use?\nGPT_OK_CANARY: 300s.\n"
    assert (
        "conversations.json: skipped 1 of 2 ChatGPT conversations without a message mapping"
        in capsys.readouterr().err
    )


def test_chatgpt_export_without_messages_refuses_raw_json(tmp_path):
    empty = _gpt_conversation("c1", [])
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps([empty]), encoding="utf-8")

    with pytest.raises(ValueError, match="refusing raw JSON fallback"):
        normalize(str(path))


# ---------------------------------------------------------------------------
# Claude.ai privacy export (convos-4)
# ---------------------------------------------------------------------------


def _claude_ai_message(sender: str, text: str, with_blocks: bool = True) -> dict:
    message = {
        "uuid": f"m-{sender}",
        "text": text,
        "sender": sender,
        "created_at": "2026-09-01T10:00:00.000000Z",
        "attachments": [],
        "files": [],
    }
    if with_blocks:
        message["content"] = [{"type": "text", "text": text, "citations": []}]
    return message


@pytest.mark.parametrize("with_blocks", [True, False])
def test_claude_ai_export_with_sender_and_text_is_normalized(tmp_path, with_blocks):
    export = [
        {
            "uuid": "d1",
            "name": "Borealis telemetry",
            "created_at": "2026-09-01T10:00:00.000000Z",
            "chat_messages": [
                _claude_ai_message("human", "Do we collect telemetry in Borealis?", with_blocks),
                _claude_ai_message(
                    "assistant", "REAL_CLAUDEAI_CANARY: telemetry is opt-in only.", with_blocks
                ),
            ],
        }
    ]
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(export, indent=2), encoding="utf-8")

    assert normalize(str(path)) == (
        "> Do we collect telemetry in Borealis?\nREAL_CLAUDEAI_CANARY: telemetry is opt-in only.\n"
    )


def test_claude_ai_export_without_messages_refuses_raw_json(tmp_path):
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps([{"uuid": "d1", "chat_messages": []}]), encoding="utf-8")

    with pytest.raises(ValueError, match="refusing raw JSON fallback"):
        normalize(str(path))


# ---------------------------------------------------------------------------
# Slack export (convos-12)
# ---------------------------------------------------------------------------


def _slack_export(root: Path) -> Path:
    users = [
        {"id": "U01ALICE", "name": "alice", "profile": {"display_name": "alice"}},
        {"id": "U02BOB", "name": "bob", "profile": {"display_name": "", "real_name": "Bob B"}},
        {"id": "U03CAROL", "name": "carol", "profile": {"display_name": "carol"}},
    ]
    channels = [{"id": "C1", "name": "general", "created": 1758000000, "members": ["U01ALICE"]}]
    (root / "general").mkdir(parents=True)
    (root / "users.json").write_text(json.dumps(users), encoding="utf-8")
    (root / "channels.json").write_text(json.dumps(channels), encoding="utf-8")
    day = root / "general" / "2026-09-20.json"
    day.write_text(
        json.dumps(
            [
                {"type": "message", "user": "U01ALICE", "text": "Who takes the Osprey migration?"},
                {"type": "message", "user": "U02BOB", "text": "Not me, out on Thursday."},
                {
                    "type": "message",
                    "user": "U03CAROL",
                    "text": "SLACK_CANARY2: I'll handle the database migration for Osprey.",
                },
                {
                    "type": "message",
                    "subtype": "channel_join",
                    "user": "U04DAN",
                    "text": "<@U04DAN> has joined the channel",
                },
            ]
        ),
        encoding="utf-8",
    )
    return day


def test_slack_messages_keep_speaker_names_and_skip_join_events(tmp_path):
    day = _slack_export(tmp_path / "slack")

    assert normalize(str(day)) == (
        "> [alice] Who takes the Osprey migration?\n[Bob B] Not me, out on Thursday.\n\n"
        "> [carol] SLACK_CANARY2: I'll handle the database migration for Osprey.\n"
    )


def test_slack_speaker_falls_back_to_user_profile_then_user_id(tmp_path):
    day = tmp_path / "2026-09-20.json"
    day.write_text(
        json.dumps(
            [
                {
                    "type": "message",
                    "user": "U9",
                    "text": "hello from profile",
                    "user_profile": {"real_name": "Pat Q", "display_name": ""},
                },
                {"type": "message", "user": "U10", "text": "hello from id"},
            ]
        ),
        encoding="utf-8",
    )

    result = normalize(str(day))

    assert "> [Pat Q] hello from profile" in result
    assert "[U10] hello from id" in result


@pytest.mark.parametrize("name", ["users.json", "channels.json"])
def test_slack_export_metadata_files_are_not_filed(tmp_path, name):
    from mempalace_code.normalize import NotAConversationError

    _slack_export(tmp_path / "slack")

    with pytest.raises(NotAConversationError, match="Slack export metadata"):
        normalize(str(tmp_path / "slack" / name))


def _slack_quiet_days(slack: Path) -> tuple[Path, Path]:
    join_only = slack / "general" / "2026-09-21.json"
    join_only.write_text(
        json.dumps(
            [
                {
                    "type": "message",
                    "subtype": "channel_join",
                    "user": "U04DAN",
                    "text": "<@U04DAN> has joined the channel",
                    "ts": "1758400000.000100",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    single = slack / "general" / "2026-09-22.json"
    single.write_text(
        json.dumps(
            [
                {
                    "type": "message",
                    "user": "U03CAROL",
                    "text": "SLACK_SINGLE_CANARY: the Osprey migration moved to Friday night.",
                    "ts": "1758500000.000100",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return join_only, single


def test_slack_single_message_day_keeps_its_speaker(tmp_path):
    _slack_export(tmp_path / "slack")
    _, single = _slack_quiet_days(tmp_path / "slack")

    assert normalize(str(single)) == (
        "> [carol] SLACK_SINGLE_CANARY: the Osprey migration moved to Friday night.\n"
    )


def test_slack_event_only_day_refuses_raw_json(tmp_path):
    from mempalace_code.normalize import NotAConversationError

    _slack_export(tmp_path / "slack")
    join_only, _ = _slack_quiet_days(tmp_path / "slack")

    with pytest.raises(NotAConversationError, match="refusing raw JSON fallback"):
        normalize(str(join_only))


def test_slack_quiet_days_never_file_raw_json(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    _slack_export(tmp_path / "slack")
    _slack_quiet_days(tmp_path / "slack")
    palace = tmp_path / "palace"

    mine_convos(str(tmp_path / "slack"), str(palace), wing="slack")

    drawers = _drawers(palace)
    assert "> [carol] SLACK_SINGLE_CANARY: the Osprey migration moved to Friday night." in drawers
    assert not any('"type": "message"' in drawer or "has joined" in drawer for drawer in drawers)


def test_slack_export_mining_files_only_channel_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    _slack_export(tmp_path / "slack")
    palace = tmp_path / "palace"

    mine_convos(str(tmp_path / "slack"), str(palace), wing="slack")

    drawers = _drawers(palace)
    assert any("[carol] SLACK_CANARY2" in drawer for drawer in drawers)
    assert not any("U01ALICE" in drawer or "has joined" in drawer for drawer in drawers)


def test_slack_metadata_files_are_skipped_not_failed_and_old_drawers_removed(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    slack = tmp_path / "slack"
    _slack_export(slack)
    palace = tmp_path / "palace"
    users = slack / "users.json"
    # An older release filed users.json as raw JSON.
    open_store(str(palace), create=True).add(
        ids=["drawer_slack_general_rawusers"],
        documents=[users.read_text(encoding="utf-8")],
        metadatas=[
            {
                "wing": "slack",
                "room": "general",
                "source_file": str(users),
                "chunk_index": 0,
                "ingest_mode": "convos",
                "extract_mode": "exchange",
                "chunker_strategy": "convo_turn_v2",
                "source_hash": "0" * 32,
            }
        ],
    )

    stats = mine_convos(str(slack), str(palace), wing="slack", incremental=False)
    captured = capsys.readouterr()

    assert stats["files_not_conversation"] == 2
    assert stats["files_failed"] == 0
    assert stats["drawers_removed"] == 1
    assert "skipped users.json: users.json is Slack export metadata" in captured.out
    assert "skipped channels.json: channels.json is Slack export metadata" in captured.out
    assert "Files skipped (not a conversation): 2" in captured.out
    assert "Files failed" not in captured.out
    assert "retried" not in captured.err
    assert not any("U01ALICE" in drawer for drawer in _drawers(palace))


# ---------------------------------------------------------------------------
# split (convos-6, convos-27, ops-25)
# ---------------------------------------------------------------------------


def _banner_session(prompt: str, body: list[str], stamp: str, compact: bool = False) -> str:
    if compact:
        head = [" ▐▛███▜▌   Claude Code v2.0.37", "▝▜█████▛▘  Sonnet · Claude Pro"]
    else:
        head = [
            "╭─── Claude Code v2.0.14 ─────────────────────╮",
            "│               Welcome back!                 │",
            "╰─────────────────────────────────────────────╯",
        ]
    return "\n".join([*head, f"⏺ {stamp}", f"> {prompt}", *body]) + "\n"


_LONG_BODY = [f"Heron answer line {i}" for i in range(12)]


def _run_split_cli(argv: list[str], capsys):
    from mempalace_code.cli import main

    with patch.object(sys, "argv", ["mempalace", "split", *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = exc.code
    return code, capsys.readouterr()


def test_split_keeps_short_sessions_and_preamble(tmp_path, capsys):
    from mempalace_code.split_mega_files import split_file

    source = (
        "MEGA_PREAMBLE_CANARY: exported from the Heron workstation\n\n"
        + _banner_session("Plan the rollout", _LONG_BODY, "9:00 AM Monday, September 14, 2026")
        + _banner_session(
            "Which port does Heron admin use",
            ["SHORT_SESSION_CANARY: Heron admin listens on port 9464."],
            "10:00 AM Monday, September 14, 2026",
            compact=True,
        )
        + _banner_session("Write the runbook", _LONG_BODY, "11:00 AM Monday, September 14, 2026")
    )
    mega = tmp_path / "two.txt"
    mega.write_text(source, encoding="utf-8")
    out = tmp_path / "out"

    written = split_file(mega, out)

    assert len(written) == 3
    texts = [path.read_text(encoding="utf-8") for path in written]
    assert "".join(texts) == source
    assert texts[0].startswith("MEGA_PREAMBLE_CANARY")
    assert "SHORT_SESSION_CANARY" in texts[1]
    assert "2 before the first session" in capsys.readouterr().out


def test_split_tiny_sessions_are_all_written(tmp_path):
    from mempalace_code.split_mega_files import split_file

    sessions = [
        _banner_session(f"tiny {n}", [], f"{n}:00 AM Monday, September 14, 2026")
        for n in (9, 10, 11)
    ]
    mega = tmp_path / "all_sessions.txt"
    mega.write_text("".join(sessions), encoding="utf-8")

    written = split_file(mega, tmp_path / "out")

    assert [path.read_text(encoding="utf-8") for path in written] == sessions


def test_split_ignores_claude_code_version_mentioned_in_a_prompt(tmp_path):
    from mempalace_code.split_mega_files import find_session_boundaries, split_file

    second = _banner_session(
        "Start session two",
        [
            "Some answer",
            "> Did you know Claude Code v2.1 changed the hooks format? Please check.",
            "Claude Code v2.1 changed the hooks format.",
            "HOOKS_CANARY: yes, hooks now use JSON.",
        ],
        "11:00 AM Monday, September 14, 2026",
    )
    first = _banner_session("Plan the rollout", _LONG_BODY, "9:00 AM Monday, September 14, 2026")
    mega = tmp_path / "heron_mega.txt"
    mega.write_text(first + second, encoding="utf-8")

    lines = (first + second).splitlines(keepends=True)
    assert len(find_session_boundaries(lines)) == 2
    written = split_file(mega, tmp_path / "out")

    assert [path.read_text(encoding="utf-8") for path in written] == [first, second]


def test_split_plain_version_banner_still_starts_a_session():
    from mempalace_code.split_mega_files import find_session_boundaries

    lines = ["Claude Code v1\n", "> hi\n", "Claude Code v1.0.3\n", "> again\n"]

    assert find_session_boundaries(lines) == [0, 2]


@pytest.mark.parametrize(
    ("missing", "kind"), [("nosuchdir", "directory"), ("nosuchfile.txt", "file")]
)
def test_split_missing_source_fails_loudly(tmp_path, capsys, missing, kind):
    code, captured = _run_split_cli([str(tmp_path / "gone" / missing)], capsys)

    assert code == 1
    assert f"Error: source {kind} not found: {tmp_path / 'gone' / missing}" in captured.err
    assert f"Next: ls {tmp_path}" in captured.err
    assert "No mega-files found" not in captured.out


def test_split_accepts_a_single_file_of_any_extension(tmp_path, capsys):
    nested = tmp_path / "sub"
    nested.mkdir()
    mega = nested / "notes.md"
    mega.write_text(
        _banner_session("Markdown one", _LONG_BODY, "9:00 AM Monday, September 14, 2026")
        + _banner_session("Markdown two", _LONG_BODY, "11:00 AM Monday, September 14, 2026"),
        encoding="utf-8",
    )

    code, captured = _run_split_cli([str(mega)], capsys)

    assert code == 0
    assert f"Source:      {mega}" in captured.out
    assert (nested / "notes.mega_backup").is_file()
    assert len(list(nested.glob("notes_*.txt"))) == 2
    assert "kept, not mined" in captured.out


def test_split_directory_without_mega_files_explains_the_scan_scope(tmp_path, capsys):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.txt").write_text(
        _banner_session("one", _LONG_BODY, "9:00 AM Monday, September 14, 2026") * 2,
        encoding="utf-8",
    )

    code, captured = _run_split_cli([str(tmp_path)], capsys)

    assert code == 0
    assert "scanned 0 top-level .txt files" in captured.out
    assert "pass a file path" in captured.out


def test_malformed_export_shapes_do_not_crash_normalize(tmp_path):
    chatgpt = tmp_path / "chatgpt.json"
    chatgpt.write_text(
        json.dumps(
            {
                "mapping": {
                    "root": {"message": None, "parent": None, "children": [{"bad": 1}]},
                    "q": _gpt_node("q", "root", [], "user", "Orphan question?"),
                },
                "current_node": ["not", "a", "string"],
            }
        ),
        encoding="utf-8",
    )
    slack = tmp_path / "2026-09-20.json"
    slack.write_text(
        json.dumps(
            [
                {"type": "message", "subtype": ["odd"], "user": "U1", "text": "first message"},
                {"type": "message", "user": "U2", "text": {"rich": "text"}},
                {"type": "message", "user": "U2", "text": "second message"},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="refusing raw JSON fallback"):
        normalize(str(chatgpt))
    assert normalize(str(slack)) == "> [U1] first message\n[U2] second message\n"


def test_split_unreadable_file_argument_exits_nonzero(tmp_path, capsys):
    target = tmp_path / "real.txt"
    target.write_text(
        _banner_session("one", _LONG_BODY, "9:00 AM Monday, September 14, 2026") * 2,
        encoding="utf-8",
    )
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    code, captured = _run_split_cli([str(link)], capsys)

    assert code == 1
    assert "not a regular file" in captured.err
    assert target.is_file()
    assert not (tmp_path / "real.mega_backup").exists()
