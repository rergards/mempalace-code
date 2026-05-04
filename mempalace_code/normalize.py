#!/usr/bin/env python3
"""
normalize.py — Convert any chat export format to MemPalace transcript format.

Supported:
    - Plain text with > markers (pass through)
    - Claude.ai JSON export
    - ChatGPT conversations.json
    - Claude Code JSONL
    - OpenAI Codex CLI JSONL
    - Gemini CLI JSONL
    - Slack JSON export
    - Plain text (pass through for paragraph chunking)

No API key. No internet. Everything local.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

# --- Claude Code noise patterns ---
# Each pattern must consume the entire line to avoid stripping inline prose.
_NOISE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"CURRENT TIME:\s+\S.*"  # timestamp injections
    r"|Ran \d+ .+ hook"  # hook run notifications
    r"|\(ctrl\+[a-z] to [\w\s]+\)"  # keyboard hint overlays
    r")\s*$"
)

# Block-anchored: tag must open at the start of a line; strips the whole block.
_NOISE_BLOCK_RE = re.compile(r"(?m)^<[a-zA-Z][\w-]*>[\s\S]*?</[a-zA-Z][\w-]*>\n?")

_BASH_HEAD = 10
_BASH_TAIL = 5
_BASH_CAP = 20
_GREP_GLOB_CAP = 20
_GENERIC_BYTE_CAP = 500
_TOOL_INPUT_JSON_CAP = 100
_BASH_CMD_CAP = 80


def normalize(filepath: str, spellcheck: bool = True) -> str:
    """
    Load a file and normalize to transcript format if it's a chat export.
    Plain text files pass through unchanged.
    """
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        raise IOError(f"Could not read {filepath}: {e}")

    if not content.strip():
        return content

    # Already has > markers — pass through
    lines = content.split("\n")
    if sum(1 for line in lines if line.strip().startswith(">")) >= 3:
        return content

    # Try JSON normalization
    ext = Path(filepath).suffix.lower()
    if ext in (".json", ".jsonl") or content.strip()[:1] in ("{", "["):
        normalized = _try_normalize_json(content, spellcheck=spellcheck)
        if normalized:
            return normalized

    return content


def _try_normalize_json(content: str, spellcheck: bool = True) -> Optional[str]:
    """Try all known JSON chat schemas."""

    normalized = _try_claude_code_jsonl(content, spellcheck=spellcheck)
    if normalized:
        return normalized

    normalized = _try_codex_jsonl(content, spellcheck=spellcheck)
    if normalized:
        return normalized

    normalized = _try_gemini_jsonl(content, spellcheck=spellcheck)
    if normalized:
        return normalized

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    for parser in (_try_claude_ai_json, _try_chatgpt_json, _try_slack_json):
        normalized = parser(data, spellcheck=spellcheck)
        if normalized:
            return normalized

    return None


def _format_tool_use(block: dict) -> str:
    """Format a tool_use block as a compact one-line summary."""
    name = block.get("name", "unknown")
    raw_inp = block.get("input")
    inp = raw_inp if isinstance(raw_inp, dict) else {}

    if name == "Bash":
        cmd = inp.get("command", "")
        if len(cmd) > _BASH_CMD_CAP:
            cmd = cmd[: _BASH_CMD_CAP - 3] + "..."
        return f"[Bash: {cmd}]"
    if name in ("Read", "Edit", "Write"):
        path = inp.get("file_path", "")
        return f"[{name}: {path}]" if path else f"[{name}]"
    if name == "Grep":
        pattern = inp.get("pattern", "")
        return f"[Grep: {pattern}]" if pattern else "[Grep]"
    if name == "Glob":
        pattern = inp.get("pattern", "")
        return f"[Glob: {pattern}]" if pattern else "[Glob]"

    # Bounded fallback JSON for unknown tools. Use raw_inp here (not the
    # dict-coerced inp) so non-dict inputs like strings/lists round-trip via
    # json.dumps instead of being silently dropped to "{}".
    try:
        inp_str = json.dumps(raw_inp) if raw_inp is not None else ""
    except (TypeError, ValueError):
        inp_str = ""
    if len(inp_str) > _TOOL_INPUT_JSON_CAP:
        inp_str = inp_str[: _TOOL_INPUT_JSON_CAP - 3] + "..."
    return f"[{name}: {inp_str}]" if inp_str and inp_str != "{}" else f"[{name}]"


def _format_tool_result(block: dict, tool_name: str = "") -> str:
    """Format a tool_result block compactly; omit large file-content results."""
    raw = block.get("content", "")
    if isinstance(raw, list):
        parts = [
            item.get("text", "")
            for item in raw
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        text = "\n".join(parts).strip()
    elif isinstance(raw, str):
        text = raw.strip()
    else:
        text = ""

    if not text:
        return ""

    # Omit file-content style results (Read/Edit/Write return full file text)
    if tool_name in ("Read", "Edit", "Write"):
        return ""

    if tool_name == "Bash":
        result_lines = text.split("\n")
        if len(result_lines) > _BASH_CAP:
            head = "\n".join(result_lines[:_BASH_HEAD])
            tail = "\n".join(result_lines[-_BASH_TAIL:])
            return f"[{len(result_lines)} lines]\n{head}\n...\n{tail}"
        return text

    if tool_name in ("Grep", "Glob"):
        result_lines = text.split("\n")
        if len(result_lines) > _GREP_GLOB_CAP:
            extra = len(result_lines) - _GREP_GLOB_CAP
            return "\n".join(result_lines[:_GREP_GLOB_CAP]) + f"\n... ({extra} more)"
        return text

    if len(text) > _GENERIC_BYTE_CAP:
        return text[:_GENERIC_BYTE_CAP] + "..."
    return text


def _strip_claude_code_noise(text: str) -> str:
    """Remove Claude Code system injections that are line- or tag-anchored."""
    text = _NOISE_BLOCK_RE.sub("", text)
    cleaned = [line for line in text.split("\n") if not _NOISE_LINE_RE.match(line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()


def _try_claude_code_jsonl(content: str, spellcheck: bool = True) -> Optional[str]:
    """Claude Code JSONL sessions."""
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)

    # Build tool_use_id -> tool_name map from all assistant entries
    tool_use_map: dict = {}
    for entry in entries:
        if entry.get("type") == "assistant":
            msg_content = entry.get("message", {}).get("content", [])
            if isinstance(msg_content, list):
                for block in msg_content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        if tool_id:
                            tool_use_map[tool_id] = block.get("name", "")

    messages = []
    for entry in entries:
        msg_type = entry.get("type", "")
        msg_content = entry.get("message", {}).get("content", "")

        if msg_type in ("human", "user"):
            # Tool-result-only user turns belong to the preceding assistant turn
            if isinstance(msg_content, list) and all(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in msg_content
            ):
                tool_text = _extract_content(msg_content, tool_use_map=tool_use_map)
                if tool_text and messages and messages[-1][0] == "assistant":
                    _, prev_text = messages[-1]
                    messages[-1] = ("assistant", prev_text + "\n" + tool_text)
                continue

            text = _extract_content(msg_content, tool_use_map=tool_use_map)
            text = _strip_claude_code_noise(text)
            if text:
                messages.append(("user", text))

        elif msg_type == "assistant":
            text = _extract_content(msg_content, tool_use_map=tool_use_map)
            text = _strip_claude_code_noise(text)
            if text:
                messages.append(("assistant", text))

    if len(messages) >= 2:
        return _messages_to_transcript(messages, spellcheck=spellcheck)
    return None


def _try_gemini_jsonl(content: str, spellcheck: bool = True) -> Optional[str]:
    """Gemini CLI JSONL sessions.

    Requires a session_metadata sentinel to distinguish from other JSONL formats.
    Turns before the sentinel are discarded. message_update rows are skipped.
    """
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    has_session_metadata = False
    messages = []

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue

        entry_type = entry.get("type", "")

        if entry_type == "session_metadata":
            has_session_metadata = True
            continue

        if not has_session_metadata:
            continue

        if entry_type == "message_update":
            continue

        content_blocks = entry.get("content", [])
        if not isinstance(content_blocks, list) or not content_blocks:
            continue

        texts = [
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        text = "\n".join(t for t in texts if t).strip()
        if not text:
            continue

        if entry_type == "user":
            messages.append(("user", text))
        elif entry_type == "gemini":
            messages.append(("assistant", text))

    if len(messages) >= 2:
        return _messages_to_transcript(messages, spellcheck=spellcheck)
    return None


def _try_codex_jsonl(content: str, spellcheck: bool = True) -> Optional[str]:
    """OpenAI Codex CLI sessions (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl).

    Uses only event_msg entries (user_message / agent_message) which represent
    the canonical conversation turns. response_item entries are skipped because
    they include synthetic context injections and duplicate the real messages.
    """
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    messages = []
    has_session_meta = False
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue

        entry_type = entry.get("type", "")
        if entry_type == "session_meta":
            has_session_meta = True
            continue

        if entry_type != "event_msg":
            continue

        payload = entry.get("payload", {})
        if not isinstance(payload, dict):
            continue

        payload_type = payload.get("type", "")
        msg = payload.get("message")
        if not isinstance(msg, str):
            continue
        text = msg.strip()
        if not text:
            continue

        if payload_type == "user_message":
            messages.append(("user", text))
        elif payload_type == "agent_message":
            messages.append(("assistant", text))

    if len(messages) >= 2 and has_session_meta:
        return _messages_to_transcript(messages, spellcheck=spellcheck)
    return None


def _try_claude_ai_json(data, spellcheck: bool = True) -> Optional[str]:
    """Claude.ai JSON export: flat messages list or privacy export with chat_messages."""
    if isinstance(data, dict):
        data = data.get("messages", data.get("chat_messages", []))
    if not isinstance(data, list):
        return None

    # Privacy export: array of conversation objects with chat_messages inside each
    if data and isinstance(data[0], dict) and "chat_messages" in data[0]:
        all_messages = []
        for convo in data:
            if not isinstance(convo, dict):
                continue
            chat_msgs = convo.get("chat_messages", [])
            for item in chat_msgs:
                if not isinstance(item, dict):
                    continue
                role = item.get("role", "")
                text = _extract_content(item.get("content", ""))
                if role in ("user", "human") and text:
                    all_messages.append(("user", text))
                elif role in ("assistant", "ai") and text:
                    all_messages.append(("assistant", text))
        if len(all_messages) >= 2:
            return _messages_to_transcript(all_messages, spellcheck=spellcheck)
        return None

    # Flat messages list
    messages = []
    for item in data:
        if not isinstance(item, dict):
            continue
        role = item.get("role", "")
        text = _extract_content(item.get("content", ""))
        if role in ("user", "human") and text:
            messages.append(("user", text))
        elif role in ("assistant", "ai") and text:
            messages.append(("assistant", text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages, spellcheck=spellcheck)
    return None


def _try_chatgpt_json(data, spellcheck: bool = True) -> Optional[str]:
    """ChatGPT conversations.json with mapping tree."""
    if not isinstance(data, dict) or "mapping" not in data:
        return None
    mapping = data["mapping"]
    messages = []
    # Find root: prefer node with parent=None AND no message (synthetic root)
    root_id = None
    fallback_root = None
    for node_id, node in mapping.items():
        if node.get("parent") is None:
            if node.get("message") is None:
                root_id = node_id
                break
            elif fallback_root is None:
                fallback_root = node_id
    if not root_id:
        root_id = fallback_root
    if root_id:
        current_id = root_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            node = mapping.get(current_id, {})
            msg = node.get("message")
            if msg:
                role = msg.get("author", {}).get("role", "")
                content = msg.get("content", {})
                parts = content.get("parts", []) if isinstance(content, dict) else []
                text = " ".join(str(p) for p in parts if isinstance(p, str) and p).strip()
                if role == "user" and text:
                    messages.append(("user", text))
                elif role == "assistant" and text:
                    messages.append(("assistant", text))
            children = node.get("children", [])
            current_id = children[0] if children else None
    if len(messages) >= 2:
        return _messages_to_transcript(messages, spellcheck=spellcheck)
    return None


def _try_slack_json(data, spellcheck: bool = True) -> Optional[str]:
    """
    Slack channel export: [{"type": "message", "user": "...", "text": "..."}]
    Optimized for 2-person DMs. In channels with 3+ people, alternating
    speakers are labeled user/assistant to preserve the exchange structure.
    """
    if not isinstance(data, list):
        return None
    messages = []
    seen_users = {}
    last_role = None
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        user_id = item.get("user", item.get("username", ""))
        text = item.get("text", "").strip()
        if not text or not user_id:
            continue
        if user_id not in seen_users:
            # Alternate roles so exchange chunking works with any number of speakers
            if not seen_users:
                seen_users[user_id] = "user"
            elif last_role == "user":
                seen_users[user_id] = "assistant"
            else:
                seen_users[user_id] = "user"
        last_role = seen_users[user_id]
        messages.append((seen_users[user_id], text))
    if len(messages) >= 2:
        return _messages_to_transcript(messages, spellcheck=spellcheck)
    return None


def _extract_content(content, tool_use_map=None) -> str:
    """Pull text from content — handles str, list of blocks, or dict.

    When tool_use_map is not None (Claude Code path), tool_use and tool_result
    blocks are formatted compactly. Without it, only text blocks are extracted,
    preserving the existing behavior for Claude.ai JSON / ChatGPT / Slack.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                block_type = item.get("type")
                if block_type == "text":
                    text = item.get("text", "")
                    if text:
                        parts.append(text)
                elif block_type == "tool_use" and tool_use_map is not None:
                    formatted = _format_tool_use(item)
                    if formatted:
                        parts.append(formatted)
                elif block_type == "tool_result" and tool_use_map is not None:
                    tool_id = item.get("tool_use_id", "")
                    tool_name = tool_use_map.get(tool_id, "")
                    formatted = _format_tool_result(item, tool_name)
                    if formatted:
                        parts.append(formatted)
        if tool_use_map is not None:
            return "\n".join(parts).strip()
        return " ".join(parts).strip()
    if isinstance(content, dict):
        return content.get("text", "").strip()
    return ""


def _messages_to_transcript(messages: list, spellcheck: bool = True) -> str:
    """Convert [(role, text), ...] to transcript format with > markers."""
    if spellcheck:
        try:
            from mempalace_code.spellcheck import spellcheck_user_text

            _fix = spellcheck_user_text
        except ImportError:
            _fix = None
    else:
        _fix = None

    lines = []
    i = 0
    while i < len(messages):
        role, text = messages[i]
        if role == "user":
            if _fix is not None:
                text = _fix(text)
            lines.append(f"> {text}")
            if i + 1 < len(messages) and messages[i + 1][0] == "assistant":
                lines.append(messages[i + 1][1])
                i += 2
            else:
                i += 1
        else:
            lines.append(text)
            i += 1
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python normalize.py <filepath>")
        sys.exit(1)
    filepath = sys.argv[1]
    result = normalize(filepath)
    quote_count = sum(1 for line in result.split("\n") if line.strip().startswith(">"))
    print(f"\nFile: {os.path.basename(filepath)}")
    print(f"Normalized: {len(result)} chars | {quote_count} user turns detected")
    print("\n--- Preview (first 20 lines) ---")
    print("\n".join(result.split("\n")[:20]))
