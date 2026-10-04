"""UAT regressions for conversation mining: verbatim chunking and incremental upkeep.

The verbatim coverage checker below runs every supported transcript format through
``normalize`` and ``chunk_exchanges`` and requires the drawers to reproduce every
non-blank transcript line, in order, with its line breaks.
"""

import json
import shlex
import sys
from unittest.mock import patch

import pytest

from mempalace_code.convo_miner import (
    EXCHANGE_CHUNKER_STRATEGY,
    GENERAL_CHUNKER_STRATEGY,
    MAX_CHUNK_CHARS,
    MIN_CHUNK_SIZE,
    chunk_exchanges,
    mine_convos,
)
from mempalace_code.normalize import normalize
from mempalace_code.storage import OptimizeResult, open_store

# ── Shared conversation fixture ────────────────────────────────────────────────

LONG_ANSWER = "\n".join(
    [
        "Here is the full migration plan.",
        "",
        "```python",
        "def migrate(conn):",
        "",
        "    conn.execute('CREATE EXTENSION vector')",
        "    conn.commit()",
        "```",
        "",
    ]
    + [
        line
        for n in range(1, 41)
        for line in (
            [f"Step {n}: LONG_ANSWER_LINE_{n:02d} explains one more detail of the rollout."]
            + ([""] if n % 10 == 0 else [])
        )
    ]
    + [
        "---",
        "AFTER_SEPARATOR_CANARY: Eli publishes the registry on Friday.",
        "",
        "Final recommendation: FINAL_RECOMMENDATION_CANARY.",
    ]
)

CONVERSATION = [
    (
        "user",
        "Line one of a multi-line question.\n"
        "MULTILINE_USER_CANARY: second line asks about sharding by tenant_id.",
    ),
    ("assistant", LONG_ANSWER),
    ("user", "ok"),
    ("assistant", "Sure."),
    ("user", "Any quotes from the design review?"),
    (
        "assistant",
        "Yes, the reviewer said:\n"
        "> BLOCKQUOTE_CANARY: never store raw embeddings in Redis.\n"
        "We agreed with that.",
    ),
    ("user", "How do I run the migration?"),
    (
        "assistant",
        "Run:\n> npm run migrate -- --env=prod\nSHELL_PROMPT_CANARY: it takes about two minutes.",
    ),
]


def _rendered_lines(messages):
    """The transcript lines drawers must reproduce for a structured export."""
    lines = []
    for role, text in messages:
        text_lines = text.split("\n")
        if role == "user":
            # Only a user turn's first line carries the marker; the rest is verbatim.
            text_lines[0] = f"> {text_lines[0]}"
        lines.extend(text_lines)
    return lines


def _claude_code_jsonl(messages):
    rows = []
    for role, text in messages:
        if role == "user":
            rows.append({"type": "user", "message": {"content": text}})
        else:
            rows.append(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}
            )
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def _codex_jsonl(messages):
    rows = [{"type": "session_meta", "payload": {"id": "session"}}]
    for role, text in messages:
        kind = "user_message" if role == "user" else "agent_message"
        rows.append({"type": "event_msg", "payload": {"type": kind, "message": text}})
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def _gemini_jsonl(messages):
    rows: list[dict] = [{"type": "session_metadata", "sessionId": "s"}]
    for role, text in messages:
        rows.append(
            {
                "type": "user" if role == "user" else "gemini",
                "content": [{"type": "text", "text": text}],
            }
        )
    return "\n".join(json.dumps(row) for row in rows) + "\n"


def _claude_ai_flat(messages):
    return json.dumps([{"role": role, "content": text} for role, text in messages])


def _claude_ai_privacy(messages):
    return json.dumps(
        [{"uuid": "c1", "chat_messages": [{"role": r, "content": t} for r, t in messages]}]
    )


def _chatgpt_mapping(messages):
    mapping = {"root": {"id": "root", "parent": None, "message": None, "children": ["m0"]}}
    for n, (role, text) in enumerate(messages):
        mapping[f"m{n}"] = {
            "id": f"m{n}",
            "parent": "root" if n == 0 else f"m{n - 1}",
            "message": {"author": {"role": role}, "content": {"parts": [text]}},
            "children": [f"m{n + 1}"] if n + 1 < len(messages) else [],
        }
    return json.dumps({"title": "t", "mapping": mapping})


def _slack(messages):
    return json.dumps(
        [
            {"type": "message", "user": "U1" if role == "user" else "U2", "text": text}
            for role, text in messages
        ]
    )


STRUCTURED_FORMATS = {
    "claude_code.jsonl": _claude_code_jsonl,
    "codex_rollout.jsonl": _codex_jsonl,
    "gemini_session.jsonl": _gemini_jsonl,
    "claude_ai.json": _claude_ai_flat,
    "claude_ai_privacy.json": _claude_ai_privacy,
    "chatgpt.json": _chatgpt_mapping,
    "slack.json": _slack,
}

PLAIN_MARKER = """PREAMBLE_CANARY: Heron design meeting notes, 2026-09-21.
Context: attendees Dana, Eli, Mo.

> What serialization format should Heron use?
> MULTILINE_PLAIN_CANARY: we need schema evolution.
We compared Avro and Protobuf.
Line 2 of the answer.
Line 3 of the answer.
Line 4 of the answer.
Line 5 of the answer.
Line 6 of the answer.
Line 7 of the answer.
Line 8 of the answer.
PLAIN_LINE9_CANARY: we chose Protobuf.

> ok
Sure.

> What did we decide about schema versioning?
PLAIN_VERSIONING_CANARY: every schema carries a major version.
---
AFTER_SEPARATOR_CANARY: Eli will publish the registry by Friday.

> Who owns the schema registry?
Dana owns the schema registry.
"""

SPEAKER_TRANSCRIPT = """User: What port does the Plover API listen on?

Assistant: UA_CANARY1: the Plover API listens on port 8443.
It terminates TLS itself.

User: And health checks?

Assistant: UA_CANARY2: /healthz on the same port.
"""

SPLIT_SESSION = """▐▛███▜▌   Claude Code v2.0.14
▝▜█████▛▘  Opus · Claude Max
  ▘▘ ▝▝    ~/projects/heron

⏺ 9:15 AM Monday, September 21, 2026

> Single session question here

⏺ SINGLE_CANARY: port 9464.
"""

PROSE_NOTES = "\n\n".join(
    f"PROSE_CANARY{n}: paragraph {n} of the retro notes, kept verbatim." for n in range(1, 60)
)

PLAIN_FORMATS = {
    "plain_marker.txt": PLAIN_MARKER,
    "speaker.txt": SPEAKER_TRANSCRIPT,
    "split_session.txt": SPLIT_SESSION,
    "retro.md": PROSE_NOTES,
}


def assert_verbatim_coverage(chunks, expected_lines):
    """Every non-blank expected line appears once, in order, as a whole drawer line."""
    got = [line for chunk in chunks for line in chunk["content"].split("\n") if line.strip()]
    want = [line for line in expected_lines if line.strip()]
    assert got == want
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk["content"] == chunk["content"].strip("\n")
        assert len(chunk["content"]) <= MAX_CHUNK_CHARS + 2 * MIN_CHUNK_SIZE
        if len(chunks) > 1:
            assert len(chunk["content"].strip()) >= MIN_CHUNK_SIZE


def _chunk_containing(chunks, needle):
    matches = [chunk["content"] for chunk in chunks if needle in chunk["content"]]
    assert len(matches) == 1, needle
    return matches[0]


# ── convos-2 / convos-10 / convos-22: verbatim coverage across formats ─────────


@pytest.mark.parametrize("filename", sorted(STRUCTURED_FORMATS))
def test_structured_formats_keep_every_line_and_role(tmp_path, filename):
    source = tmp_path / filename
    source.write_text(STRUCTURED_FORMATS[filename](CONVERSATION), encoding="utf-8")

    chunks = chunk_exchanges(normalize(str(source), spellcheck=False))

    # Slack messages keep their [speaker] label on the first line of each message.
    user, answer = ("[U1] ", "[U2] ") if filename == "slack.json" else ("", "")
    labelled = [(role, (user if role == "user" else answer) + text) for role, text in CONVERSATION]
    assert_verbatim_coverage(chunks, _rendered_lines(labelled))
    # The whole multi-line user message is the user turn.
    first = chunks[0]["content"]
    assert first.startswith(
        f"> {user}Line one of a multi-line question.\nMULTILINE_USER_CANARY: second line"
    )
    # Answer lines starting with '>' stay inside their answer.
    quote = _chunk_containing(chunks, "BLOCKQUOTE_CANARY")
    assert quote.startswith(
        f"> {user}Any quotes from the design review?\n{answer}Yes, the reviewer said:"
    )
    shell = _chunk_containing(chunks, "npm run migrate")
    assert shell.startswith(f"> {user}How do I run the migration?\n{answer}Run:\n> npm run migrate")
    # A long answer is split into several drawers; its code block stays whole.
    assert sum("LONG_ANSWER_LINE" in chunk["content"] for chunk in chunks) >= 2
    code = _chunk_containing(chunks, "def migrate(conn):")
    assert "def migrate(conn):\n\n    conn.execute(" in code
    assert "    conn.commit()\n```" in code
    # The short exchange is merged, not dropped.
    assert f"> {user}ok\n{answer}Sure." in _chunk_containing(chunks, f"> {user}ok")


@pytest.mark.parametrize("filename", sorted(PLAIN_FORMATS))
def test_plain_text_formats_keep_every_line(tmp_path, filename):
    source = tmp_path / filename
    source.write_text(PLAIN_FORMATS[filename], encoding="utf-8")

    chunks = chunk_exchanges(normalize(str(source), spellcheck=False))

    assert_verbatim_coverage(chunks, PLAIN_FORMATS[filename].split("\n"))


def test_plain_marker_transcript_boundaries():
    chunks = chunk_exchanges(PLAIN_MARKER)

    first = chunks[0]["content"]
    assert first.startswith("PREAMBLE_CANARY")
    assert "> What serialization format should Heron use?\n> MULTILINE_PLAIN_CANARY" in first
    assert "PLAIN_LINE9_CANARY: we chose Protobuf.\n\n> ok\nSure." in first
    versioning = _chunk_containing(chunks, "PLAIN_VERSIONING_CANARY")
    assert versioning.endswith(
        "---\nAFTER_SEPARATOR_CANARY: Eli will publish the registry by Friday."
    )


def test_speaker_prefixed_transcript_keeps_question_with_answer():
    chunks = chunk_exchanges(SPEAKER_TRANSCRIPT)

    assert [chunk["content"] for chunk in chunks] == [
        "User: What port does the Plover API listen on?\n\n"
        "Assistant: UA_CANARY1: the Plover API listens on port 8443.\nIt terminates TLS itself.",
        "User: And health checks?\n\nAssistant: UA_CANARY2: /healthz on the same port.",
    ]


def test_single_exchange_session_keeps_banner_with_the_exchange():
    chunks = chunk_exchanges(SPLIT_SESSION)

    assert len(chunks) == 1
    assert chunks[0]["content"].endswith(
        "> Single session question here\n\n⏺ SINGLE_CANARY: port 9464."
    )


def test_mid_file_session_banner_starts_the_next_exchange():
    text = (
        "> Where do failed deliveries go?\n⏺ They go to the dead-letter queue.\n\n"
        "> How should Heron retry failed deliveries?\n⏺ Exponential backoff with jitter.\n\n"
        "▐▛███▜▌   Claude Code v2.0.14\n⏺ 2:30 PM Tuesday\n\n"
        "> What is the max backoff?\n⏺ Max backoff is 10 minutes.\n"
    )

    chunks = chunk_exchanges(text)

    assert chunks[1]["content"].endswith("⏺ Exponential backoff with jitter.")
    assert chunks[2]["content"].startswith("▐▛███▜▌   Claude Code v2.0.14")
    assert chunks[2]["content"].endswith("> What is the max backoff?\n⏺ Max backoff is 10 minutes.")


def test_mined_drawers_store_chunks_verbatim(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    convos.mkdir()
    (convos / "session.jsonl").write_text(_claude_code_jsonl(CONVERSATION), encoding="utf-8")
    (convos / "meeting.txt").write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")

    mine_convos(str(convos), palace, wing="convos", spellcheck=False)

    store = open_store(palace, create=False)
    for name, expected in (
        ("session.jsonl", _rendered_lines(CONVERSATION)),
        ("meeting.txt", PLAIN_MARKER.split("\n")),
    ):
        rows = store.get(
            where={"source_file": str(convos / name)}, include=["documents", "metadatas"]
        )
        ordered = sorted(
            zip(rows["documents"], rows["metadatas"]), key=lambda pair: pair[1]["chunk_index"]
        )
        chunks = [{"content": doc, "chunk_index": meta["chunk_index"]} for doc, meta in ordered]
        assert_verbatim_coverage(chunks, expected)
        assert {meta["chunker_strategy"] for _, meta in ordered} == {EXCHANGE_CHUNKER_STRATEGY}


# ── convos-5 / hooks-1: growing sessions are re-mined ──────────────────────────


def _session(n_prompts):
    messages = []
    for n in range(1, n_prompts + 1):
        messages.append(("user", f"Detail marker HUMAN{n:03d}: what about step {n}?"))
        messages.append(("assistant", f"Step {n} answer ASSISTANT{n:03d} with enough words."))
    return _claude_code_jsonl(messages)


def _run_cli(argv):
    from mempalace_code.cli import main

    with patch.object(sys, "argv", ["mempalace-code", *argv]):
        main()


def _rows(palace, wing=None):
    store = open_store(palace, create=False, read_only=True)
    where = {"wing": wing} if wing else None
    return store.get(where=where, include=["documents", "metadatas"], limit=100000)


def test_growing_session_is_remined_by_the_hook_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "cv1"
    convos.mkdir()
    session = convos / "session-a.jsonl"
    palace = str(tmp_path / "palace")
    hook_argv = ["--palace", palace, "mine", str(convos), "--mode", "convos", "--no-spellcheck"]

    session.write_text(_session(15), encoding="utf-8")
    _run_cli(hook_argv)
    assert len(_rows(palace)["ids"]) == 15

    session.write_text(_session(30), encoding="utf-8")
    capsys.readouterr()
    _run_cli(hook_argv)
    out = capsys.readouterr().out
    assert "Files processed: 1" in out
    assert "Files skipped (already filed): 0" in out

    rows = _rows(palace)
    assert len(rows["ids"]) == len(set(rows["ids"])) == 30
    text = "\n".join(rows["documents"])
    assert all(f"HUMAN{n:03d}" in text for n in range(1, 31))
    assert {meta["source_hash"] for meta in rows["metadatas"]} != {""}

    _run_cli(hook_argv)
    out = capsys.readouterr().out
    assert "Files skipped (already filed): 1" in out
    assert "Drawers filed: 0" in out


def test_legacy_strategy_rows_are_rebuilt_by_an_incremental_mine(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    convos.mkdir()
    source = convos / "meeting.txt"
    source.write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")
    store = open_store(palace, create=True)
    store.add(
        ids=["drawer_convos_general_legacy0"],
        documents=["> What serialization format should Heron use?\nWe compared Avro and"],
        metadatas=[
            {
                "wing": "convos",
                "room": "general",
                "source_file": str(source),
                "chunk_index": 0,
                "ingest_mode": "convos",
                "extract_mode": "exchange",
                "chunker_strategy": "convo_turn_v1",
            }
        ],
    )

    mine_convos(str(convos), palace, wing="convos", spellcheck=False)

    rows = _rows(palace, "convos")
    assert "drawer_convos_general_legacy0" not in rows["ids"]
    assert {meta["chunker_strategy"] for meta in rows["metadatas"]} == {EXCHANGE_CHUNKER_STRATEGY}
    assert "PLAIN_LINE9_CANARY" in "\n".join(rows["documents"])


def test_drawers_compressed_before_1_15_are_refiled_by_an_incremental_mine(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    convos.mkdir()
    (convos / "meeting.txt").write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")
    mine_convos(str(convos), palace, wing="convos", spellcheck=False)
    store = open_store(palace, create=False)
    result = store.get(include=["documents", "metadatas"], limit=1)
    drawer_id, verbatim = result["ids"][0], result["documents"][0]
    store.upsert(
        ids=[drawer_id],
        documents=["AAAK|summary"],
        metadatas=[{**result["metadatas"][0], "original_tokens": 90, "compression_ratio": 3.5}],
    )

    stats = mine_convos(str(convos), palace, wing="convos", spellcheck=False)

    assert stats["files_processed"] == 1
    rows = _rows(palace, "convos")
    assert rows["documents"][rows["ids"].index(drawer_id)] == verbatim
    again = mine_convos(str(convos), palace, wing="convos", spellcheck=False)
    assert again["files_processed"] == 0
    assert again["files_skipped"] == 1


# ── convos-13: a --full mine sweeps deleted, renamed, split, and shrunk sources ─


def test_deleted_renamed_and_shrunk_sources_are_swept(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    (convos / "plain").mkdir(parents=True)
    notes = convos / "plain" / "new_notes.txt"
    notes.write_text("> Who is on call for Heron?\nDana is on call this week.\n", encoding="utf-8")
    mega = convos / "heron_mega.txt"
    mega.write_text(PLAIN_MARKER, encoding="utf-8")
    retro = convos / "retro.txt"
    retro.write_text(PROSE_NOTES, encoding="utf-8")
    palace = str(tmp_path / "palace")
    store = open_store(palace, create=True)
    store.add(
        ids=["manual_note"],
        documents=["A manual note filed against the same source path."],
        metadatas=[
            {
                "wing": "convos",
                "room": "notes",
                "source_file": str(notes),
                "chunker_strategy": "manual_v1",
            }
        ],
    )
    mine_convos(str(convos), palace, wing="convos", spellcheck=False)

    notes.unlink()
    mega.rename(convos / "heron_mega_2026-09-21.txt")
    retro.write_text("tiny.", encoding="utf-8")
    capsys.readouterr()
    mine_convos(str(convos), palace, wing="convos", spellcheck=False, incremental=False)
    out = capsys.readouterr().out

    rows = _rows(palace, "convos")
    sources = {meta["source_file"] for meta in rows["metadatas"]}
    assert str(mega) not in sources
    # A shrunk transcript is re-filed whole, however short it now is.
    assert sources == {str(convos / "heron_mega_2026-09-21.txt"), str(notes), str(retro)}
    retro_docs = [
        doc
        for doc, meta in zip(rows["documents"], rows["metadatas"])
        if meta["source_file"] == str(retro)
    ]
    assert retro_docs == ["tiny."]
    assert rows["ids"].count("manual_note") == 1
    assert "plain/new_notes.txt (source no longer present)" in out
    assert "drawers of heron_mega.txt (source no longer present)" in out
    assert "retro.txt (now too small" not in out
    assert "Drawers removed:" in out


def test_incremental_mine_keeps_drawers_of_missing_transcripts(tmp_path, monkeypatch, capsys):
    """Tools prune old transcripts, so only an explicit --full mine removes their drawers."""
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "cv1"
    convos.mkdir()
    old = convos / "session-old.jsonl"
    old.write_text(_session(15), encoding="utf-8")
    session = convos / "session-a.jsonl"
    session.write_text(_session(5), encoding="utf-8")
    palace = str(tmp_path / "palace")
    hook_argv = ["--palace", palace, "mine", str(convos), "--mode", "convos", "--no-spellcheck"]
    _run_cli(hook_argv)

    old.unlink()  # e.g. Claude Code deleted it after cleanupPeriodDays
    session.write_text(_session(8), encoding="utf-8")
    capsys.readouterr()
    _run_cli(hook_argv)
    out = capsys.readouterr().out

    sources = [meta["source_file"] for meta in _rows(palace)["metadatas"]]
    assert sources.count(str(old)) == 15
    assert sources.count(str(session)) == 8
    assert "Drawers removed" not in out
    assert "Transcripts no longer present: 1 (drawers kept" in out
    command = next(line for line in out.splitlines() if "To remove those drawers:" in line)
    tokens = shlex.split(command.split("To remove those drawers: ", 1)[1])
    argv = tokens[tokens.index("--palace") :]
    assert argv[:2] == ["--palace", palace]
    assert argv[-1] == "--full"
    assert "--no-spellcheck" not in argv

    summary = mine_convos(str(convos), palace, wing="cv1", spellcheck=False, dry_run=True)
    assert summary["sources_missing"] == 1
    assert summary["drawers_removed"] == 0
    assert len(_rows(palace)["ids"]) == 23

    capsys.readouterr()
    _run_cli(argv)
    out = capsys.readouterr().out
    assert "removing 15 drawers of session-old.jsonl (source no longer present)" in out
    assert "Transcripts no longer present" not in out
    assert {meta["source_file"] for meta in _rows(palace)["metadatas"]} == {str(session)}


def test_limit_and_skipped_directories_never_sweep(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    (convos / "memory").mkdir(parents=True)
    (convos / "memory" / "notes.txt").write_text(PLAIN_MARKER, encoding="utf-8")
    (convos / "a.txt").write_text(SPEAKER_TRANSCRIPT, encoding="utf-8")
    (convos / "b.txt").write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")

    mine_convos(str(convos / "memory"), palace, wing="convos", spellcheck=False)
    mine_convos(str(convos), palace, wing="convos", spellcheck=False, incremental=False)
    before = sorted(_rows(palace, "convos")["ids"])
    (convos / "b.txt").unlink()
    summary = mine_convos(
        str(convos), palace, wing="convos", spellcheck=False, incremental=False, limit=1
    )

    assert summary["drawers_removed"] == 0
    assert sorted(_rows(palace, "convos")["ids"]) == before
    assert "Skipped: memory/ (excluded names; mine one directly" in capsys.readouterr().out


# ── convos-14 / convos-20 / convos-21 / convos-26 / convos-28 / convos-32 ──────


def test_missing_path_exits_nonzero_without_creating_a_palace(tmp_path, capsys):
    palace = tmp_path / "p_edge2"

    with pytest.raises(SystemExit) as exc:
        _run_cli(["--palace", str(palace), "mine", str(tmp_path / "nosuchdir"), "--mode", "convos"])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Error: directory or file not found:" in err
    assert f"--palace {palace} mine <conversations-dir-or-file> --mode convos" in err
    assert not palace.exists()


def test_single_file_is_mined_and_other_extensions_are_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    source = tmp_path / "chats" / "heron_meeting.txt"
    source.parent.mkdir()
    source.write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")

    summary = mine_convos(str(source), palace, spellcheck=False)

    assert summary["drawers_filed"] == len(chunk_exchanges(PLAIN_MARKER))
    assert {meta["wing"] for meta in _rows(palace)["metadatas"]} == {"chats"}

    other = tmp_path / "chats" / "notes.py"
    other.write_text("print('hi')\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        mine_convos(str(other), palace, spellcheck=False)
    assert exc.value.code == 1
    assert "not a conversation file" in capsys.readouterr().err


def test_noop_mine_skips_backup_and_optimize(tmp_path):
    convos = tmp_path / "convos"
    convos.mkdir()
    (convos / "chat.txt").write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")

    with patch(
        "mempalace_code.convo_miner.optimize_store",
        return_value=OptimizeResult(ok=True, supported=True),
    ) as optimize:
        mine_convos(str(convos), palace, wing="convos", spellcheck=False)
        mine_convos(str(convos), palace, wing="convos", spellcheck=False)
        empty = tmp_path / "empty"
        empty.mkdir()
        mine_convos(str(empty), str(tmp_path / "other_palace"), spellcheck=False)

    assert optimize.call_count == 1


def test_unparseable_and_undecodable_files_are_reported_and_counted(tmp_path, capsys):
    edge = tmp_path / "edge"
    (edge / "codex").mkdir(parents=True)
    (edge / "misc").mkdir()
    rollout = edge / "codex" / "rollout-2026-09-21-onlyuser.jsonl"
    rollout.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": "s"}})
        + "\n"
        + json.dumps(
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "CODEX_ORPHAN_CANARY: hi"},
            }
        ),
        encoding="utf-8",
    )
    (edge / "misc" / "latin1.txt").write_bytes(
        "> Question about café prices at Plover?\nThe answer is long enough.\n".encode("latin-1")
    )
    (edge / "misc" / "binary.txt").write_bytes(b"BINARY\x00\x00\xff BINARY stuff and more text\n")
    palace = str(tmp_path / "palace")

    summary = mine_convos(str(edge), palace, wing="edge", spellcheck=False)

    captured = capsys.readouterr()
    assert summary["files_failed"] == 2
    assert "Files failed: 2" in captured.out
    # A rollout without a complete exchange is skipped on purpose, not a failure.
    assert summary["files_not_conversation"] == 1
    assert "Files skipped (not a conversation): 1" in captured.out
    assert "skipped codex/rollout-2026-09-21-onlyuser.jsonl: Codex rollout" in captured.out
    assert "skipped misc/latin1.txt: not valid UTF-8" in captured.err
    assert "skipped misc/binary.txt: binary or UTF-16 content" in captured.err
    assert open_store(palace, create=False).count() == 0


def test_dry_run_applies_the_already_filed_skip(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    convos.mkdir()
    (convos / "chat.txt").write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")

    fresh = mine_convos(str(convos), str(tmp_path / "missing"), wing="c", dry_run=True)
    assert fresh["drawers_filed"] == len(chunk_exchanges(PLAIN_MARKER))
    assert not (tmp_path / "missing").exists()

    mine_convos(str(convos), palace, wing="c", spellcheck=False)
    capsys.readouterr()
    summary = mine_convos(str(convos), palace, wing="c", spellcheck=False, dry_run=True)

    out = capsys.readouterr().out
    assert summary["files_skipped"] == 1
    assert summary["drawers_filed"] == 0
    assert "Files that would be processed: 0" in out
    assert "Drawers that would be filed: 0" in out


def test_success_lines_use_paths_relative_to_the_source(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "skipt"
    for sub in ("ok", "other", "build"):
        (convos / sub).mkdir(parents=True)
        (convos / sub / "notes.txt").write_text(PLAIN_MARKER, encoding="utf-8")

    mine_convos(str(convos), str(tmp_path / "palace"), spellcheck=False)

    out = capsys.readouterr().out
    assert "ok/notes.txt" in out
    assert "other/notes.txt" in out
    assert "Skipped: build/ (excluded names" in out


# ── convos-15 / convos-31: general extraction coexists; rooms are consistent ───

DECISION_TRANSCRIPT = """> Which queue should we use?
We decided to go with SQLite instead of Redis; we chose it over the alternative.

> What about the Python bug in the parser function?
The code had an error in the API test; debug the function and refactor it.
"""


def test_general_extraction_never_replaces_verbatim_exchange_drawers(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    convos.mkdir()
    (convos / "chat.txt").write_text(DECISION_TRANSCRIPT, encoding="utf-8")
    palace = str(tmp_path / "palace")

    mine_convos(str(convos), palace, wing="c", spellcheck=False)
    exchange = sorted(_rows(palace, "c")["ids"])
    general = mine_convos(str(convos), palace, wing="c", spellcheck=False, extract_mode="general")
    mine_convos(
        str(convos),
        palace,
        wing="c",
        spellcheck=False,
        extract_mode="general",
        incremental=False,
    )

    assert general["files_processed"] == 1
    assert general["drawers_filed"] >= 1
    rows = _rows(palace, "c")
    by_mode: dict = {}
    for drawer_id, meta in zip(rows["ids"], rows["metadatas"]):
        by_mode.setdefault(meta["extract_mode"], []).append((drawer_id, meta))
    assert sorted(drawer_id for drawer_id, _ in by_mode["exchange"]) == exchange
    assert {meta["chunker_strategy"] for _, meta in by_mode["general"]} == {
        GENERAL_CHUNKER_STRATEGY
    }
    assert {meta["room"] for _, meta in by_mode["general"]} <= {
        "decisions",
        "preferences",
        "milestones",
        "problems",
        "emotional",
    }


def test_rooms_are_detected_per_exchange(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "convos"
    convos.mkdir()
    (convos / "chat.txt").write_text(DECISION_TRANSCRIPT, encoding="utf-8")
    palace = str(tmp_path / "palace")

    mine_convos(str(convos), palace, wing="c", spellcheck=False)

    rooms = {meta["chunk_index"]: meta["room"] for meta in _rows(palace, "c")["metadatas"]}
    assert rooms == {0: "decisions", 1: "technical"}
    assert "decisions            1 drawers" in capsys.readouterr().out


def test_scan_wing_metadata_projects_one_wing_without_text(tmp_path):
    store = open_store(str(tmp_path / "palace"), create=True)
    store.add(
        ids=["a", "b"],
        documents=["first drawer text", "second drawer text"],
        metadatas=[
            {"wing": "w1", "source_file": "/x/a.txt", "ingest_mode": "convos"},
            {"wing": "w2", "source_file": "/x/b.txt", "ingest_mode": "convos"},
        ],
    )

    rows = store.scan_wing_metadata("w1", ["id", "source_file", "source_hash"])

    assert rows == [{"wing": "w1", "id": "a", "source_file": "/x/a.txt", "source_hash": ""}]
    with pytest.raises(ValueError, match="text"):
        store.scan_wing_metadata("w1", ["id", "text"])


def test_changed_source_in_a_wing_with_a_quote_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMPALACE_OPTIMIZE_AFTER_MINE", "0")
    convos = tmp_path / "bob's chats"
    convos.mkdir()
    source = convos / "a.txt"
    source.write_text(PLAIN_MARKER, encoding="utf-8")
    palace = str(tmp_path / "palace")
    mine_convos(str(convos), palace, spellcheck=False)

    source.write_text("> Changed question?\nChanged answer entirely, much shorter.\n")
    summary = mine_convos(str(convos), palace, spellcheck=False)

    assert summary["drawers_removed"] >= 1
    assert _rows(palace, "bob's_chats")["documents"] == [
        "> Changed question?\nChanged answer entirely, much shorter."
    ]
