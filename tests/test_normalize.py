import json
import os
import tempfile
from unittest.mock import patch

from mempalace_code.normalize import (
    _extract_content,
    _format_tool_result,
    _format_tool_use,
    _strip_claude_code_noise,
    _try_gemini_jsonl,
    normalize,
)

# ---------------------------------------------------------------------------
# Existing regression tests
# ---------------------------------------------------------------------------


def test_plain_text():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.write("Hello world\nSecond line\n")
    f.close()
    result = normalize(f.name)
    assert "Hello world" in result
    os.unlink(f.name)


def test_claude_json():
    data = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name)
    assert "Hi" in result
    os.unlink(f.name)


def test_empty():
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    f.close()
    result = normalize(f.name)
    assert result.strip() == ""
    os.unlink(f.name)


def test_json_normalize_spellcheck_enabled_calls_user_text_speller():
    data = [{"role": "user", "content": "pleese help"}, {"role": "assistant", "content": "Ok"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    try:
        with patch("mempalace_code.spellcheck.spellcheck_user_text", return_value="please help"):
            result = normalize(f.name, spellcheck=True)
    finally:
        os.unlink(f.name)

    assert "> please help" in result
    assert "pleese help" not in result


def test_json_normalize_spellcheck_disabled_preserves_user_text():
    data = [{"role": "user", "content": "pleese help"}, {"role": "assistant", "content": "Ok"}]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    try:
        with patch("mempalace_code.spellcheck.spellcheck_user_text", return_value="please help"):
            result = normalize(f.name, spellcheck=False)
    finally:
        os.unlink(f.name)

    assert "> pleese help" in result
    assert "> please help" not in result


# ---------------------------------------------------------------------------
# Claude.ai JSON regression: tool_use_map=None must not change behavior
# ---------------------------------------------------------------------------


def test_claude_ai_json_no_tool_blocks_unchanged():
    data = [
        {"role": "user", "content": "Explain recursion"},
        {"role": "assistant", "content": "Recursion is a function calling itself."},
    ]
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(data, f)
    f.close()
    result = normalize(f.name, spellcheck=False)
    os.unlink(f.name)
    assert "> Explain recursion" in result
    assert "Recursion is a function calling itself." in result


# ---------------------------------------------------------------------------
# AC-1: Gemini CLI JSONL basic normalization
# ---------------------------------------------------------------------------


def _write_jsonl(lines: list) -> str:
    """Write JSONL lines to a temp file and return the path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.write("\n".join(lines))
    f.close()
    return f.name


def test_gemini_jsonl_basic_transcript():
    """AC-1: session_metadata + user + gemini → proper > user / assistant transcript."""
    lines = [
        '{"type": "session_metadata", "sessionId": "abc"}',
        '{"type": "user", "content": [{"type": "text", "text": "Hello Gemini"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Hi there!"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "> Hello Gemini" in result
    assert "Hi there!" in result


def test_gemini_jsonl_user_turn_has_gt_marker():
    """AC-1: user turns in Gemini output must use the > marker."""
    lines = [
        '{"type": "session_metadata"}',
        '{"type": "user", "content": [{"type": "text", "text": "Question"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Answer"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    user_lines = [ln for ln in result.split("\n") if ln.startswith("> ")]
    assert len(user_lines) == 1
    assert user_lines[0] == "> Question"


# ---------------------------------------------------------------------------
# AC-2: Gemini edge cases
# ---------------------------------------------------------------------------


def test_gemini_jsonl_pre_sentinel_turns_discarded():
    """AC-2: turns before session_metadata are not emitted."""
    lines = [
        '{"type": "user", "content": [{"type": "text", "text": "Before sentinel"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Also before"}]}',
        '{"type": "session_metadata", "sessionId": "abc"}',
        '{"type": "user", "content": [{"type": "text", "text": "After sentinel"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Real response"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "Before sentinel" not in result
    assert "Also before" not in result
    assert "> After sentinel" in result
    assert "Real response" in result


def test_gemini_jsonl_message_update_skipped():
    """AC-2: message_update rows must not appear in output."""
    lines = [
        '{"type": "session_metadata"}',
        '{"type": "user", "content": [{"type": "text", "text": "Q"}]}',
        '{"type": "message_update", "content": [{"type": "text", "text": "streaming..."}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "A"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "streaming..." not in result
    assert "> Q" in result
    assert "A" in result


def test_gemini_jsonl_empty_content_skipped():
    """AC-2: entries with empty content lists do not create turns."""
    lines = [
        '{"type": "session_metadata"}',
        '{"type": "user", "content": []}',
        '{"type": "user", "content": [{"type": "text", "text": "Real Q"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Real A"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    user_turns = [ln for ln in result.split("\n") if ln.startswith("> ")]
    assert len(user_turns) == 1
    assert user_turns[0] == "> Real Q"


def test_gemini_jsonl_multi_block_content_ordered():
    """AC-2: multiple text blocks in one entry are joined in source order."""
    lines = [
        '{"type": "session_metadata"}',
        '{"type": "user", "content": [{"type": "text", "text": "Q"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Part1"}, {"type": "text", "text": "Part2"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "Part1" in result
    assert "Part2" in result
    assert result.index("Part1") < result.index("Part2")


def test_gemini_jsonl_malformed_rows_dont_abort():
    """AC-2: malformed rows are skipped without aborting."""
    lines = [
        '{"type": "session_metadata"}',
        "not valid json {{{{",
        '{"type": "user", "content": [{"type": "text", "text": "Valid Q"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Valid A"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "> Valid Q" in result
    assert "Valid A" in result


def test_gemini_jsonl_non_text_blocks_skipped():
    """AC-2: non-text block types within content are ignored."""
    lines = [
        '{"type": "session_metadata"}',
        '{"type": "user", "content": [{"type": "image", "data": "..."}, {"type": "text", "text": "Describe this"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "I see an image"}]}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "> Describe this" in result
    assert "I see an image" in result


# ---------------------------------------------------------------------------
# AC-3: Gemini requires session_metadata; Codex dispatch still wins
# ---------------------------------------------------------------------------


def test_gemini_jsonl_declines_without_session_metadata():
    """AC-3: _try_gemini_jsonl returns None if session_metadata is absent."""
    lines = [
        '{"type": "user", "content": [{"type": "text", "text": "Hello"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Hi"}]}',
    ]
    result = _try_gemini_jsonl("\n".join(lines))
    assert result is None


def test_codex_jsonl_still_parsed_correctly():
    """AC-3: Codex JSONL with session_meta (not session_metadata) still works."""
    lines = [
        '{"type": "session_meta", "session_id": "xyz"}',
        '{"type": "event_msg", "payload": {"type": "user_message", "message": "How to sort?"}}',
        '{"type": "event_msg", "payload": {"type": "agent_message", "message": "Use sorted()"}}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "> How to sort?" in result
    assert "Use sorted()" in result


def test_codex_response_item_rows_ignored():
    """AC-3: response_item entries in Codex JSONL are not emitted."""
    lines = [
        '{"type": "session_meta"}',
        '{"type": "response_item", "payload": {"type": "user_message", "message": "synthetic"}}',
        '{"type": "event_msg", "payload": {"type": "user_message", "message": "Real Q"}}',
        '{"type": "event_msg", "payload": {"type": "agent_message", "message": "Real A"}}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "synthetic" not in result
    assert "> Real Q" in result


# ---------------------------------------------------------------------------
# AC-4: Claude Code tool_use / tool_result compact formatting
# ---------------------------------------------------------------------------


def test_claude_code_tool_use_compact_bash():
    """AC-4: tool_use Bash block appears as [Bash: cmd] in transcript."""
    lines = [
        '{"type": "user", "message": {"content": "Run a command"}}',
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Sure."}, {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "echo hello"}}]}}',
        '{"type": "assistant", "message": {"content": "Done!"}}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    assert "[Bash: echo hello]" in result


def test_claude_code_tool_result_no_separate_user_turn():
    """AC-4: tool_result-only user turn does not produce a > chunk."""
    lines = [
        '{"type": "user", "message": {"content": "Run it"}}',
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Running."}, {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "ls"}}]}}',
        '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "file.txt"}]}}',
        '{"type": "assistant", "message": {"content": "Finished."}}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    # Only one > turn: the original user message
    user_turns = [ln for ln in result.split("\n") if ln.startswith("> ")]
    assert len(user_turns) == 1
    assert user_turns[0] == "> Run it"
    # Tool output merged into assistant turn
    assert "file.txt" in result


def test_claude_code_read_tool_result_omitted():
    """AC-4: Read tool_result content (file body) is omitted from output."""
    lines = [
        '{"type": "user", "message": {"content": "Show me the file"}}',
        '{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/foo.py"}}]}}',
        '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "def main(): pass"}]}}',
        '{"type": "assistant", "message": {"content": "Here it is."}}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    # File content should not appear in output
    assert "def main(): pass" not in result
    assert "[Read: /foo.py]" in result


def test_format_tool_use_known_tools():
    """AC-4: _format_tool_use produces stable summaries for common tools."""
    assert _format_tool_use({"name": "Bash", "input": {"command": "ls -la"}}) == "[Bash: ls -la]"
    assert _format_tool_use({"name": "Read", "input": {"file_path": "/a.py"}}) == "[Read: /a.py]"
    assert _format_tool_use({"name": "Edit", "input": {"file_path": "/b.py"}}) == "[Edit: /b.py]"
    assert _format_tool_use({"name": "Write", "input": {"file_path": "/c.py"}}) == "[Write: /c.py]"
    assert _format_tool_use({"name": "Grep", "input": {"pattern": "def foo"}}) == "[Grep: def foo]"
    assert _format_tool_use({"name": "Glob", "input": {"pattern": "**/*.py"}}) == "[Glob: **/*.py]"


def test_format_tool_use_unknown_tool_bounded():
    """AC-4: unknown tool input JSON is capped at 100 chars."""
    big_input = {"key": "x" * 200}
    result = _format_tool_use({"name": "MyTool", "input": big_input})
    assert result.startswith("[MyTool:")
    assert len(result) < 130  # 100 cap + name overhead


def test_format_tool_use_bash_command_truncated():
    """AC-4: Bash commands beyond _BASH_CMD_CAP are truncated with '...'."""
    big_cmd = "echo " + "x" * 200
    result = _format_tool_use({"name": "Bash", "input": {"command": big_cmd}})
    assert result.startswith("[Bash: ")
    assert result.endswith("...]")
    # cap is 80, plus "[Bash: " (7) + "]" (1) = 88 max
    assert len(result) <= 90


def test_format_tool_use_non_dict_input_known_tool():
    """AC-4: non-dict input (defensive) does not crash for known tools."""
    # Real Claude Code always sends dict input, but a malformed JSONL row
    # could carry a string/list. We must not raise AttributeError.
    result = _format_tool_use({"name": "Bash", "input": "weird-string"})
    assert result == "[Bash: ]"
    result = _format_tool_use({"name": "Read", "input": ["a", "b"]})
    assert result == "[Read]"


def test_format_tool_use_non_dict_input_unknown_tool():
    """AC-4: non-dict input on unknown tool round-trips through json.dumps."""
    result = _format_tool_use({"name": "BadTool", "input": "weird-string"})
    assert result == '[BadTool: "weird-string"]'
    result = _format_tool_use({"name": "BadTool", "input": [1, 2, 3]})
    assert result == "[BadTool: [1, 2, 3]]"


def test_format_tool_result_generic_byte_cap():
    """AC-4: tool result for unknown tool is truncated at the generic 500-char cap."""
    big_text = "x" * 1000
    result = _format_tool_result({"content": big_text}, tool_name="OtherTool")
    assert result.endswith("...")
    assert len(result) == 503  # 500 chars + "..."


def test_format_tool_result_list_of_text_blocks():
    """AC-4: tool_result content as a list of text blocks is concatenated."""
    block = {"content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]}
    result = _format_tool_result(block, tool_name="Bash")
    assert "first" in result
    assert "second" in result


def test_format_tool_result_empty_content_returns_empty():
    """AC-4: empty / missing tool_result content yields empty string, no crash."""
    assert _format_tool_result({"content": ""}, tool_name="Bash") == ""
    assert _format_tool_result({}, tool_name="Bash") == ""
    assert _format_tool_result({"content": None}, tool_name="Bash") == ""


def test_format_tool_result_bash_long_capped():
    """AC-4: long Bash output is represented with head/tail."""
    many_lines = "\n".join(f"line{i}" for i in range(50))
    block = {"content": many_lines}
    result = _format_tool_result(block, tool_name="Bash")
    assert "[50 lines]" in result
    assert "line0" in result
    assert "line49" in result
    assert "..." in result


def test_format_tool_result_read_omitted():
    """AC-4: Read tool result content is omitted."""
    block = {"content": "import os\nimport sys\n"}
    assert _format_tool_result(block, tool_name="Read") == ""


def test_format_tool_result_grep_capped():
    """AC-4: Grep results beyond cap show truncation notice."""
    many_matches = "\n".join(f"file{i}:1: match" for i in range(30))
    block = {"content": many_matches}
    result = _format_tool_result(block, tool_name="Grep")
    assert "... (10 more)" in result


# ---------------------------------------------------------------------------
# AC-5: Claude Code noise stripping — standalone removed, inline preserved
# ---------------------------------------------------------------------------


def test_strip_standalone_current_time():
    """AC-5: standalone CURRENT TIME line is stripped."""
    text = "CURRENT TIME: 2024-01-01 12:00:00\nHere is my answer."
    result = _strip_claude_code_noise(text)
    assert "CURRENT TIME:" not in result
    assert "Here is my answer." in result


def test_strip_inline_current_time_preserved():
    """AC-5: 'CURRENT TIME:' inline in user prose must not be stripped."""
    text = "I noticed CURRENT TIME: is showing incorrectly in the logs"
    result = _strip_claude_code_noise(text)
    assert "CURRENT TIME:" in result


def test_strip_hook_notification():
    """AC-5: standalone hook notification line is stripped."""
    text = "Ran 2 Stop hook\nDone processing."
    result = _strip_claude_code_noise(text)
    assert "Ran 2 Stop hook" not in result
    assert "Done processing." in result


def test_strip_system_reminder_single_line():
    """AC-5: single-line <system-reminder> tag is stripped."""
    text = "<system-reminder>Some injected text</system-reminder>\nUser prose here"
    result = _strip_claude_code_noise(text)
    assert "system-reminder" not in result
    assert "User prose here" in result


def test_strip_system_reminder_multiline():
    """AC-5: multi-line <system-reminder> block is stripped."""
    text = "<system-reminder>\nLine one\nLine two\n</system-reminder>\nUser prose here"
    result = _strip_claude_code_noise(text)
    assert "system-reminder" not in result
    assert "Line one" not in result
    assert "User prose here" in result


def test_strip_neighboring_turns_intact():
    """AC-5: noise in one assistant message doesn't affect neighboring user prose."""
    lines = [
        '{"type": "user", "message": {"content": "I see CURRENT TIME: mentioned in docs"}}',
        '{"type": "assistant", "message": {"content": "CURRENT TIME: 2024-01-01\\nHere is the answer."}}',
    ]
    path = _write_jsonl(lines)
    result = normalize(path, spellcheck=False)
    os.unlink(path)
    # User prose mentioning CURRENT TIME inline should survive
    assert "I see CURRENT TIME:" in result
    # Standalone injection in assistant should be gone
    assert "Here is the answer." in result


def test_strip_ctrl_hint():
    """AC-5: (ctrl+o to expand) keyboard hint is stripped."""
    text = "(ctrl+o to expand)\nNormal text"
    result = _strip_claude_code_noise(text)
    assert "ctrl+o" not in result
    assert "Normal text" in result


# ---------------------------------------------------------------------------
# AC-6: Spellcheck applies to Gemini user turns, not assistant
# ---------------------------------------------------------------------------


def test_gemini_jsonl_spellcheck_enabled():
    """AC-6: spellcheck applies to Gemini user turns when enabled."""
    lines = [
        '{"type": "session_metadata"}',
        '{"type": "user", "content": [{"type": "text", "text": "pleese help"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Of course"}]}',
    ]
    path = _write_jsonl(lines)
    try:
        with patch("mempalace_code.spellcheck.spellcheck_user_text", return_value="please help"):
            result = normalize(path, spellcheck=True)
    finally:
        os.unlink(path)
    assert "> please help" in result
    assert "pleese help" not in result


def test_gemini_jsonl_spellcheck_disabled():
    """AC-6: spellcheck does not alter user text when disabled."""
    lines = [
        '{"type": "session_metadata"}',
        '{"type": "user", "content": [{"type": "text", "text": "pleese help"}]}',
        '{"type": "gemini", "content": [{"type": "text", "text": "Of course"}]}',
    ]
    path = _write_jsonl(lines)
    try:
        with patch("mempalace_code.spellcheck.spellcheck_user_text", return_value="please help"):
            result = normalize(path, spellcheck=False)
    finally:
        os.unlink(path)
    assert "> pleese help" in result
    assert "> please help" not in result


# ---------------------------------------------------------------------------
# _extract_content unit tests — tool_use_map=None preserves old behavior
# ---------------------------------------------------------------------------


def test_extract_content_string():
    assert _extract_content("hello") == "hello"


def test_extract_content_list_text_only():
    blocks = [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    assert _extract_content(blocks) == "a b"


def test_extract_content_list_tool_use_ignored_without_map():
    """tool_use blocks are ignored when tool_use_map is None."""
    blocks = [{"type": "text", "text": "Before"}, {"type": "tool_use", "name": "Bash"}]
    result = _extract_content(blocks)
    assert result == "Before"
    assert "Bash" not in result


def test_extract_content_list_tool_use_formatted_with_map():
    """tool_use blocks are formatted when tool_use_map is provided."""
    blocks = [
        {"type": "text", "text": "Running"},
        {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "ls"}},
    ]
    result = _extract_content(blocks, tool_use_map={"tu_1": "Bash"})
    assert "Running" in result
    assert "[Bash: ls]" in result
