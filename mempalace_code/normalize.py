#!/usr/bin/env python3
"""
normalize.py — Convert any chat export format to MemPalace transcript format.

Supported:
    - Claude.ai JSON export (privacy export ``sender``/``text`` or ``role``/``content``)
    - ChatGPT ``conversations.json`` (the official array of conversations, or one
      conversation); the branch selected by ``current_node`` is followed
    - Claude Code JSONL
    - OpenAI Codex CLI JSONL
    - Gemini CLI JSONL
    - Slack channel export JSON (speakers kept as ``[name]`` labels)
    - Plain text (returned unchanged)

Message text is kept verbatim: nothing here spell-corrects or rewrites it.

No API key. No internet. Everything local.
"""

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional, TypeGuard

from .source_io import read_regular_text

# --- Claude Code noise patterns ---
# Each pattern must consume the entire line to avoid stripping inline prose.
_NOISE_LINE_RE = re.compile(
    r"^\s*(?:"
    r"CURRENT TIME:\s+\S.*"  # timestamp injections
    r"|Ran \d+ .+ hook"  # hook run notifications
    r"|\(ctrl\+[a-z] to [\w\s]+\)"  # keyboard hint overlays
    r")\s*$"
)

# Wrapper tags Claude Code injects into logged user/assistant text. Only these are
# stripped; any other markup (HTML, XML, JSX) is conversation content and is kept.
_CLAUDE_CODE_INJECTED_TAGS = (
    "system-reminder",
    "command-name",
    "command-message",
    "command-args",
    "command-contents",
    "local-command-stdout",
    "local-command-stderr",
    "local-command-caveat",
    "user-prompt-submit-hook",
    "task-notification",
    "bash-input",
    "bash-stdout",
    "bash-stderr",
    "ide_opened_file",
    "ide_selection",
)

# Block-anchored: an allowlisted tag must open at the start of a line and the block
# ends at the matching closing tag of the same name.
_NOISE_BLOCK_RE = re.compile(
    r"(?m)^<(" + "|".join(re.escape(tag) for tag in _CLAUDE_CODE_INJECTED_TAGS) + r")>"
    r"[\s\S]*?</\1>[ \t]*\n?"
)

# User entries (or list-form text blocks) that start with one of these are Claude Code
# harness events, not typed prompts: command wrappers and notifications. Keep in sync
# with the Save hook's counter (hooks/mempal_save_hook.sh).
_CLAUDE_CODE_SYSTEM_PREFIXES = (
    "<command-",
    "<local-command-",
    "<task-notification>",
)

# The "[Request interrupted by user]" / "[Request interrupted by user for tool use]"
# notice Claude Code logs when a turn is cancelled. Only the notice line itself is
# removed: text the user typed after it in the same entry is a prompt and is kept.
# The Save hook's counter strips the same leading notice lines.
_INTERRUPT_NOTICE_LINE_RE = re.compile(
    r"\A[ \t]*\[Request interrupted by user(?: for tool use)?\](?:[ \t]*\r?\n)?"
)
_LEADING_BLANK_LINES_RE = re.compile(r"\A(?:[ \t]*\n)+")

# The slash command a user typed, as Claude Code logs it in a command wrapper entry.
_COMMAND_NAME_RE = re.compile(r"<command-name>([\s\S]*?)</command-name>")
_COMMAND_ARGS_RE = re.compile(r"<command-args>([\s\S]*?)</command-args>")


class NotAConversationError(ValueError):
    """A recognized export file that holds no conversation to file.

    Raised instead of returning the raw JSON, so callers can report the file as
    skipped (for example Slack ``users.json``) rather than filing it or failing.
    """


_BASH_HEAD = 10
_BASH_TAIL = 5
_BASH_CAP = 20
_GREP_GLOB_CAP = 20
_GENERIC_BYTE_CAP = 500
_TOOL_INPUT_JSON_CAP = 100
_BASH_CMD_CAP = 80


def normalize(filepath: str, spellcheck: bool = False) -> str:
    """
    Load a file and normalize it to transcript format if it is a chat export.

    Plain text is returned unchanged. *spellcheck* is accepted for backward
    compatibility and ignored: conversation text is always kept verbatim.

    Raises NotAConversationError (a ValueError) for a recognized export that holds
    no conversation (for example Slack ``users.json``), instead of filing its raw JSON.
    """
    try:
        # utf-8-sig drops a leading byte-order mark: an encoding marker, not text.
        content = read_regular_text(filepath, encoding="utf-8-sig", errors="replace")
    except OSError as e:
        raise IOError(f"Could not read {filepath}: {e}")

    if not content.strip():
        return content

    # Try JSON normalization
    ext = Path(filepath).suffix.lower()
    if ext in (".json", ".jsonl") or content.strip()[:1] in ("{", "["):
        normalized = _try_normalize_json(content, filepath=filepath)
        if normalized:
            return normalized

    return content


def _try_normalize_json(content: str, filepath: Optional[str] = None) -> Optional[str]:
    """Try all known JSON chat schemas."""

    normalized = _try_claude_code_jsonl(content)
    if normalized:
        return normalized

    normalized = _try_codex_jsonl(content)
    if normalized:
        return normalized

    normalized = _try_gemini_jsonl(content)
    if normalized:
        return normalized

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    if filepath is not None and _is_slack_export_metadata(filepath, data):
        raise NotAConversationError(
            f"{Path(filepath).name} is Slack export metadata, not a conversation; not filed"
        )

    normalized = _try_claude_ai_json(data)
    if normalized:
        return normalized

    normalized = _try_chatgpt_json(data, filepath=filepath)
    if normalized:
        return normalized

    return _try_slack_json(data, filepath=filepath)


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
    # Repeat until stable: a wrapper that follows another on the same line (shell mode
    # logs "<bash-stdout>..</bash-stdout><bash-stderr>..</bash-stderr>") reaches the
    # start of the line only once the one before it is removed.
    while True:
        stripped = _NOISE_BLOCK_RE.sub("", text)
        if stripped == text:
            break
        text = stripped
    cleaned = [line for line in text.split("\n") if not _NOISE_LINE_RE.match(line)]
    return "\n".join(cleaned).strip()


def _is_claude_code_turn_entry(entry: dict) -> bool:
    """A Claude Code user or assistant entry (``type`` plus a ``message`` object)."""
    return entry.get("type") in ("human", "user", "assistant") and isinstance(
        entry.get("message"), dict
    )


def _is_claude_code_side_entry(entry: dict, skip_sidechain: bool) -> bool:
    """Meta and compaction-summary entries, and inline subagent (sidechain) entries."""
    if entry.get("isMeta") or entry.get("isCompactSummary"):
        return True
    return skip_sidechain and bool(entry.get("isSidechain"))


def _is_claude_code_system_text(content) -> TypeGuard[str]:
    """A string user entry that is only a Claude Code command/notification wrapper."""
    return isinstance(content, str) and content.lstrip().startswith(_CLAUDE_CODE_SYSTEM_PREFIXES)


def _strip_interrupt_notices(text: str) -> str:
    """``text`` without leading interrupt-notice lines; the rest is kept verbatim."""
    while True:
        stripped = _INTERRUPT_NOTICE_LINE_RE.sub("", text, count=1)
        if stripped == text:
            return text
        text = _LEADING_BLANK_LINES_RE.sub("", stripped)


def _is_harness_block(block) -> bool:
    """A list-form text block that is only harness text (a wrapper or interrupt notice)."""
    if not isinstance(block, dict) or block.get("type") != "text":
        return False
    text = block.get("text")
    if not isinstance(text, str):
        return False
    return _is_claude_code_system_text(text) or not _strip_interrupt_notices(text).strip()


def _without_harness_blocks(content):
    """List-form user content without text blocks that are Claude Code harness events.

    The Save hook skips such blocks too, so an entry holding only an interrupt notice
    (``[{"type": "text", "text": "[Request interrupted by user for tool use]"}]``) is
    not a user turn and the answer that follows stays with the real prompt.
    """
    if not isinstance(content, list):
        return content
    return [block for block in content if not _is_harness_block(block)]


def _claude_code_command(content: str) -> str:
    """``/name args`` as the user typed it, from a slash-command wrapper entry."""
    name = _COMMAND_NAME_RE.search(content)
    if not name or not name.group(1).strip():
        return ""
    command = name.group(1).strip()
    if not command.startswith("/"):
        command = "/" + command
    args = _COMMAND_ARGS_RE.search(content)
    if args and args.group(1).strip():
        command += " " + args.group(1).strip()
    return command


def _try_claude_code_jsonl(content: str) -> Optional[str]:
    """Claude Code JSONL sessions, including a subagent's own ``agent-*.jsonl``.

    Human turns follow the Save hook's definition of a prompt: isMeta, isCompactSummary
    and command/notification wrapper entries are skipped, and so are sidechain entries
    when the file also has main-thread turns (an inline subagent). A slash command the
    model answered is kept as the user turn ``/name args`` before that answer.

    Once the file is recognized as Claude Code it never falls back to raw JSON: with
    no conversation messages left it raises NotAConversationError.
    """
    lines = [line.strip() for line in content.strip().split("\n") if line.strip()]
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)

    turn_entries = [entry for entry in entries if _is_claude_code_turn_entry(entry)]
    if not turn_entries:
        return None
    # A file whose turns are all sidechain is a subagent's own transcript: keep them.
    skip_sidechain = any(not entry.get("isSidechain") for entry in turn_entries)

    # Build tool_use_id -> tool_name map from all assistant entries
    tool_use_map: dict = {}
    for entry in turn_entries:
        if entry["type"] == "assistant":
            msg_content = entry["message"].get("content", [])
            if isinstance(msg_content, list):
                for block in msg_content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id", "")
                        if tool_id:
                            tool_use_map[tool_id] = block.get("name", "")

    messages = []
    # A slash command waits for the model's answer; local commands (/status, /model)
    # only print local-command output, so they never become a turn.
    pending_command = ""
    for entry in turn_entries:
        if _is_claude_code_side_entry(entry, skip_sidechain):
            continue
        msg_type = entry["type"]
        msg_content = entry["message"].get("content", "")

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
            if _is_claude_code_system_text(msg_content):
                if msg_content.lstrip().startswith("<command-"):
                    pending_command = _claude_code_command(msg_content)
                elif msg_content.lstrip().startswith("<local-command-"):
                    pending_command = ""
                continue

            text = _extract_content(_without_harness_blocks(msg_content), tool_use_map=tool_use_map)
            # As in the Save hook, a leading interrupt notice (also one left once system
            # reminders are removed) is dropped; text typed after it is the prompt.
            text = _strip_interrupt_notices(_strip_claude_code_noise(text))
            if text and not text.startswith(_CLAUDE_CODE_SYSTEM_PREFIXES):
                pending_command = ""
                messages.append(("user", text))

        elif msg_type == "assistant":
            text = _extract_content(msg_content, tool_use_map=tool_use_map)
            text = _strip_claude_code_noise(text)
            if text:
                if pending_command:
                    messages.append(("user", pending_command))
                    pending_command = ""
                messages.append(("assistant", text))

    if messages:
        return _messages_to_transcript(messages)
    raise NotAConversationError(
        "Claude Code transcript contains no conversation messages; refusing raw JSON fallback"
    )


def _try_gemini_jsonl(content: str) -> Optional[str]:
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
        return _messages_to_transcript(messages)
    return None


def _try_codex_jsonl(content: str) -> Optional[str]:
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
        return _messages_to_transcript(messages)
    if has_session_meta:
        raise NotAConversationError(
            "Codex rollout contains no complete supported conversation; refusing raw JSON fallback"
        )
    return None


def _claude_ai_message(item) -> Optional[tuple]:
    """(role, text) for one Claude.ai message in ``role``/``content`` or ``sender``/``text`` form."""
    if not isinstance(item, dict):
        return None
    role = item.get("role") or item.get("sender") or ""
    text = _extract_content(item.get("content", ""))
    if not text and isinstance(item.get("text"), str):
        text = item["text"].strip()
    if not text:
        return None
    if role in ("user", "human"):
        return ("user", text)
    if role in ("assistant", "ai"):
        return ("assistant", text)
    return None


def _try_claude_ai_json(data) -> Optional[str]:
    """Claude.ai JSON export: flat messages list or privacy export with chat_messages."""
    if isinstance(data, dict):
        data = data.get("messages", data.get("chat_messages", []))
    if not isinstance(data, list):
        return None

    # Privacy export: array of conversation objects with chat_messages inside each
    if data and isinstance(data[0], dict) and "chat_messages" in data[0]:
        all_messages = []
        for convo in data:
            chat_msgs = convo.get("chat_messages") if isinstance(convo, dict) else None
            if not isinstance(chat_msgs, list):
                continue
            for item in chat_msgs:
                message = _claude_ai_message(item)
                if message:
                    all_messages.append(message)
        if all_messages:
            return _messages_to_transcript(all_messages)
        raise NotAConversationError(
            "Claude.ai export contains no conversation messages; refusing raw JSON fallback"
        )

    # Flat messages list
    messages = [message for message in map(_claude_ai_message, data) if message]
    if len(messages) >= 2:
        return _messages_to_transcript(messages)
    return None


def _chatgpt_node_path(mapping: dict, current_node) -> list:
    """Node ids of the branch ChatGPT displays, root first.

    The export keeps every edited or regenerated branch; ``current_node`` names the
    leaf of the one shown in the UI, so walk its parent links. Without it, follow
    the newest (last) child at each fork.
    """
    path: list = []
    seen: set = set()
    if isinstance(current_node, str) and current_node in mapping:
        node_id = current_node
        while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            path.append(node_id)
            node = mapping[node_id]
            node_id = node.get("parent") if isinstance(node, dict) else None
        path.reverse()
        return path

    # Find root: prefer node with parent=None AND no message (synthetic root)
    root_id = None
    fallback_root = None
    for node_id, node in mapping.items():
        if not isinstance(node, dict) or node.get("parent") is not None:
            continue
        if node.get("message") is None:
            root_id = node_id
            break
        if fallback_root is None:
            fallback_root = node_id
    node_id = root_id or fallback_root
    while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        path.append(node_id)
        node = mapping[node_id]
        children = node.get("children") if isinstance(node, dict) else None
        node_id = children[-1] if isinstance(children, list) and children else None
    return path


def _chatgpt_message(node) -> Optional[tuple]:
    """(role, text) for one visible user/assistant node of a ChatGPT mapping."""
    msg = node.get("message") if isinstance(node, dict) else None
    if not isinstance(msg, dict):
        return None
    metadata = msg.get("metadata")
    if isinstance(metadata, dict) and metadata.get("is_visually_hidden_from_conversation"):
        return None
    author = msg.get("author")
    role = author.get("role", "") if isinstance(author, dict) else ""
    content = msg.get("content")
    parts = content.get("parts", []) if isinstance(content, dict) else []
    if not isinstance(parts, list):
        return None
    # Parts are separate blocks: a newline keeps a closing code fence on its own line.
    text = "\n".join(p for p in parts if isinstance(p, str) and p).strip()
    if text and role in ("user", "assistant"):
        return (role, text)
    return None


def _try_chatgpt_json(data, filepath: Optional[str] = None) -> Optional[str]:
    """ChatGPT export: the official conversations.json array, or one conversation.

    Every item must be an object with a ``mapping`` key, and at least one mapping an
    object. A conversation whose mapping is not an object is skipped and counted on
    stderr; the others are still filed.
    """
    conversations = data if isinstance(data, list) else [data]
    if not all(isinstance(convo, dict) and "mapping" in convo for convo in conversations):
        return None
    usable = [convo for convo in conversations if isinstance(convo["mapping"], dict)]
    if not usable:
        return None
    skipped = len(conversations) - len(usable)
    if skipped:
        name = Path(filepath).name if filepath else "ChatGPT export"
        print(
            f"  {name}: skipped {skipped} of {len(conversations)} ChatGPT conversations"
            " without a message mapping",
            file=sys.stderr,
        )
    messages = []
    for convo in usable:
        mapping = convo["mapping"]
        for node_id in _chatgpt_node_path(mapping, convo.get("current_node")):
            message = _chatgpt_message(mapping.get(node_id))
            if message:
                messages.append(message)
    if messages:
        return _messages_to_transcript(messages)
    raise NotAConversationError(
        "ChatGPT export contains no conversation messages; refusing raw JSON fallback"
    )


# Slack export event subtypes that carry no message content (joins, renames, pins...).
_SLACK_EVENT_SUBTYPES = frozenset(
    {
        "channel_join",
        "channel_leave",
        "group_join",
        "group_leave",
        "channel_archive",
        "channel_unarchive",
        "group_archive",
        "group_unarchive",
        "channel_name",
        "group_name",
        "pinned_item",
        "unpinned_item",
        "bot_add",
        "bot_remove",
        "tombstone",
    }
)

# Workspace-level files of a Slack export; channel messages live in <channel>/<date>.json.
_SLACK_METADATA_FILES = frozenset(
    {
        "users.json",
        "channels.json",
        "groups.json",
        "dms.json",
        "mpims.json",
        "integration_logs.json",
        "canvases.json",
    }
)


def _is_slack_export_metadata(filepath: str, data) -> bool:
    """True for a Slack export metadata file (users, channels, ...) rather than messages."""
    name = Path(filepath).name.lower()
    if name not in _SLACK_METADATA_FILES:
        return False
    if name == "integration_logs.json":
        return isinstance(data, dict) and "logs" in data
    return isinstance(data, list) and all(
        isinstance(item, dict) and "id" in item and item.get("type") != "message" for item in data
    )


def _slack_label(profile) -> str:
    """Best human label from a Slack user or user_profile object."""
    if not isinstance(profile, dict):
        return ""
    for key in ("display_name", "real_name", "name"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@lru_cache(maxsize=8)
def _load_slack_user_names(path: str, _mtime_ns: int, _size: int) -> dict:
    """Parse one users.json into {user_id: label}; cached per file version."""
    try:
        users = json.loads(read_regular_text(path, errors="replace"))
    except (OSError, ValueError):
        return {}
    names: dict = {}
    if isinstance(users, list):
        for user in users:
            if isinstance(user, dict) and isinstance(user.get("id"), str):
                label = _slack_label(user.get("profile")) or _slack_label(user)
                if label:
                    names[user["id"]] = label
    return names


def _slack_user_names(filepath: Optional[str]) -> dict:
    """User-id to name map from the export's users.json (same folder or export root)."""
    if filepath is None:
        return {}
    here = Path(filepath).parent
    for candidate in (here / "users.json", here.parent / "users.json"):
        try:
            st = os.stat(candidate)
        except OSError:
            continue
        return _load_slack_user_names(str(candidate), st.st_mtime_ns, st.st_size)
    return {}


def _try_slack_json(data, filepath: Optional[str] = None) -> Optional[str]:
    """
    Slack channel export: [{"type": "message", "user": "...", "text": "..."}]

    Each message keeps its speaker as a ``[name]`` label, resolved from the export's
    users.json or the message's user_profile, else the raw user id. Speakers alternate
    user/assistant roles only so exchange chunking works with any number of people.
    Join/leave/rename/pin events carry no content and are skipped. A recognized day
    file (a list with a ``"type": "message"`` item) never falls back to raw JSON: with
    no conversation message left it raises NotAConversationError.
    """
    if not isinstance(data, list) or not any(
        isinstance(item, dict) and item.get("type") == "message" for item in data
    ):
        return None
    names = _slack_user_names(filepath)
    messages = []
    seen_users: dict = {}
    last_role = None
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        subtype = item.get("subtype")
        if isinstance(subtype, str) and subtype in _SLACK_EVENT_SUBTYPES:
            continue
        user_id = item.get("user") or item.get("username") or item.get("bot_id") or ""
        text = item.get("text")
        if not isinstance(text, str) or not isinstance(user_id, str):
            continue
        text = text.strip()
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
        speaker = names.get(user_id) or _slack_label(item.get("user_profile")) or user_id
        messages.append((seen_users[user_id], f"[{speaker}] {text}"))
    if messages:
        return _messages_to_transcript(messages)
    raise NotAConversationError(
        "Slack export day contains no conversation messages; refusing raw JSON fallback"
    )


def _extract_content(content, tool_use_map=None) -> str:
    """Pull text from content — handles str, list of blocks, or dict.

    When tool_use_map is not None (Claude Code path), tool_use and tool_result
    blocks are formatted compactly. Without it, only text blocks are extracted
    (Claude.ai JSON). Blocks are joined with a newline either way, so a code fence
    that closes one block never runs into the next block's text.
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
                    if isinstance(text, str) and text:
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
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        text = content.get("text", "")
        return text.strip() if isinstance(text, str) else ""
    return ""


class NormalizedTranscript(str):
    """Transcript text that also carries the ``(role, text)`` turns it was rendered from.

    The ``>``-marked text cannot express where a multi-line user turn ends or that an
    answer line starting with ``>`` is not a user turn. Structured exports know each
    speaker, so the conversation chunker reads ``messages`` when it is present.
    """

    messages: tuple[tuple[str, str], ...] = ()


def _messages_to_transcript(messages: list) -> str:
    """Convert [(role, text), ...] to transcript format with > markers."""
    lines = []
    rendered: list[tuple[str, str]] = []
    i = 0
    while i < len(messages):
        role, text = messages[i]
        if role == "user":
            lines.append(f"> {text}")
            rendered.append(("user", text))
            if i + 1 < len(messages) and messages[i + 1][0] == "assistant":
                lines.append(messages[i + 1][1])
                rendered.append(("assistant", messages[i + 1][1]))
                i += 2
            else:
                i += 1
        else:
            lines.append(text)
            rendered.append((role, text))
            i += 1
        lines.append("")
    transcript = NormalizedTranscript("\n".join(lines))
    transcript.messages = tuple(rendered)
    return transcript


if __name__ == "__main__":
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
