#!/bin/bash
# MEMPALACE SAVE HOOK — Request a save every N human prompts
#
# Claude Code "Stop" hook. After every assistant response:
# 1. Counts human messages in the session transcript
# 2. Every SAVE_INTERVAL messages, BLOCKS the AI from stopping
# 3. Returns a reason telling the AI to save structured diary + palace entries
# 4. AI attempts the filing with the available MCP tools
# 5. Next Stop fires with stop_hook_active=true → lets AI stop normally
#
# The AI does the classification — it knows what wing/hall/closet to use
# because it has context about the conversation. No regex needed.
#
# === INSTALL ===
# Add to .claude/settings.local.json:
#
#   "hooks": {
#     "Stop": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_save_hook.sh",
#         "timeout": 30
#       }]
#     }]
#   }
#
# Other agents: use MCP + usage rules instead of Claude Code hook events.
#
# === HOW IT WORKS ===
#
# Claude Code sends JSON on stdin with these fields:
#   session_id       — unique session identifier
#   stop_hook_active — true if AI is already in a save cycle (prevents infinite loop)
#   transcript_path  — path to the JSONL transcript file
#
# When we block, Claude Code shows our "reason" to the AI as a system message.
# When the AI tries to stop again, stop_hook_active=true lets it through.
# This reentry guard does not report whether any memory was written.
#
# === MEMPALACE CLI ===
# With MEMPAL_DIR set, the hook also runs: mempalace-code mine <dir> --mode convos
# Leave it blank to rely on the AI's own save instructions.
#
# === CONFIGURATION ===

SAVE_INTERVAL=15  # Request a save every N human messages (adjust to taste)
STATE_DIR="$HOME/.mempalace/hook_state"
mkdir -p "$STATE_DIR"

# Optional: set to a conversations directory to mine on each save trigger.
# Example: MEMPAL_DIR="$HOME/conversations"
# Leave empty to skip auto-ingest (AI handles saving via the block reason).
MEMPAL_DIR=""

# Optional: absolute path of the mempalace-code executable, for pipx, uv tool, or
# virtualenv installs whose bin directory is not on the hook's PATH.
# Example: MEMPALACE_BIN="$HOME/.local/bin/mempalace-code"
MEMPALACE_BIN=""

# Run `mempalace-code mine MEMPAL_DIR --mode convos`: MEMPALACE_BIN, then PATH, then a
# source checkout that contains this hooks/ directory. A copied hook needs one of the
# first two; it never imports whatever package happens to be in the current directory.
mine_conversations() {
    local dir hook_dir repo_dir
    dir="$(cd "$MEMPAL_DIR" && pwd)" || return 1
    if [ -n "$MEMPALACE_BIN" ]; then
        "$MEMPALACE_BIN" mine "$dir" --mode convos
    elif command -v mempalace-code >/dev/null 2>&1; then
        mempalace-code mine "$dir" --mode convos
    else
        hook_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        repo_dir="$(dirname "$hook_dir")"
        if [ -f "$repo_dir/mempalace_code/__init__.py" ] \
            && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            (cd "$repo_dir" && python3 -m mempalace_code mine "$dir" --mode convos)
        else
            echo "[$(date '+%H:%M:%S')] mempalace-code is not on PATH and no source checkout with Python 3.11+ is available: set MEMPALACE_BIN in ${BASH_SOURCE[0]} to the output of 'command -v mempalace-code'"
        fi
    fi
}

# Read JSON input from stdin
INPUT=$(cat)

# Parse fields from Claude Code's JSON
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null)
# Sanitize SESSION_ID to prevent path traversal (only allow alnum, dash, underscore)
SESSION_ID=$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9_-')
[ -z "$SESSION_ID" ] && SESSION_ID="unknown"
STOP_HOOK_ACTIVE=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stop_hook_active', False))" 2>/dev/null)
TRANSCRIPT_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))" 2>/dev/null)

# Expand ~ in path
TRANSCRIPT_PATH="${TRANSCRIPT_PATH/#\~/$HOME}"

# If we're already in a save cycle, let the AI stop normally
# Block once, then let an active cycle stop regardless of the filing outcome.
if [ "$STOP_HOOK_ACTIVE" = "True" ] || [ "$STOP_HOOK_ACTIVE" = "true" ]; then
    echo "{}"
    exit 0
fi

# Count human messages in the JSONL transcript. Claude Code also logs tool
# results, command wrappers, compaction summaries, subagent prompts, interrupt
# notices, and system reminders as role=user entries; only typed or submitted
# prompts count. The content checks apply to string and list-form content alike
# and also cover transcripts without the isMeta/isCompactSummary/isSidechain flags.
if [ -f "$TRANSCRIPT_PATH" ]; then
    EXCHANGE_COUNT=$(python3 - "$TRANSCRIPT_PATH" 2>/dev/null <<'PYEOF'
import json, re, sys
SYSTEM_PREFIXES = (
    '<command-',
    '<local-command-',
    '<task-notification>',
    '<system-reminder>',
)
REMINDER = re.compile(r'<system-reminder>.*?</system-reminder>', re.S)
# A leading interrupt notice line is not a prompt; text typed after it is.
INTERRUPT = re.compile(r'\A\s*\[Request interrupted by user(?: for tool use)?\](?:[ \t]*\r?\n)?')

def is_prompt_text(text):
    text = REMINDER.sub('', text).strip()
    while True:
        rest = INTERRUPT.sub('', text, count=1).strip()
        if rest == text:
            break
        text = rest
    return bool(text) and not text.startswith(SYSTEM_PREFIXES)

count = 0
with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
    for line in f:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        msg = entry.get('message')
        if not isinstance(msg, dict) or msg.get('role') != 'user':
            continue
        if entry.get('isMeta') or entry.get('isCompactSummary') or entry.get('isSidechain'):
            continue
        content = msg.get('content')
        if isinstance(content, list):
            # Tool results belong to the preceding assistant turn. A prompt is a text
            # block that is not harness text, or an attachment such as an image.
            blocks = [b for b in content if isinstance(b, dict) and b.get('type') != 'tool_result']
            if any(
                is_prompt_text(str(b.get('text', ''))) if b.get('type') == 'text' else True
                for b in blocks
            ):
                count += 1
        elif isinstance(content, str) and is_prompt_text(content):
            count += 1
print(count)
PYEOF
)
else
    EXCHANGE_COUNT=0
fi

# Legacy checkpoint name retained for state compatibility. The count advances
# when the save request is issued; no MCP persistence result is observed here.
LAST_SAVE_FILE="$STATE_DIR/${SESSION_ID}_last_save"
LAST_SAVE=0
if [ -f "$LAST_SAVE_FILE" ]; then
    LAST_SAVE=$(cat "$LAST_SAVE_FILE")
fi
# The state file is data: anything but a plain count is reset, never evaluated.
[[ "$LAST_SAVE" =~ ^[0-9]+$ ]] || LAST_SAVE=0
[[ "$EXCHANGE_COUNT" =~ ^[0-9]+$ ]] || EXCHANGE_COUNT=0

SINCE_LAST=$((EXCHANGE_COUNT - LAST_SAVE))

# Log for debugging (check ~/.mempalace/hook_state/hook.log)
echo "[$(date '+%H:%M:%S')] Session $SESSION_ID: $EXCHANGE_COUNT exchanges, $SINCE_LAST since last save" >> "$STATE_DIR/hook.log"

# Time to save?
if [ "$SINCE_LAST" -ge "$SAVE_INTERVAL" ] && [ "$EXCHANGE_COUNT" -gt 0 ]; then
    # Record the request count before optional mining or AI filing can complete.
    echo "$EXCHANGE_COUNT" > "$LAST_SAVE_FILE"

    echo "[$(date '+%H:%M:%S')] TRIGGERING SAVE at exchange $EXCHANGE_COUNT" >> "$STATE_DIR/hook.log"

    # Optional: mine conversations in the background if MEMPAL_DIR is set
    if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
        mine_conversations >> "$STATE_DIR/hook.log" 2>&1 &
    fi

    # Block the AI and give it an executable MCP save contract.
    # The "reason" becomes a system message the AI sees and acts on.
    cat << 'HOOKJSON'
{
  "decision": "block",
  "reason": "AUTO-SAVE checkpoint. Use only the MCP tools in your tool list. Call mempalace_check_duplicate before substantial drawer prose. Use mempalace_add_drawer only for decisions, root causes, or concise verbatim evidence; one topic per drawer, <=60 lines, paths/IDs instead of blobs. If mempalace_diary_write is listed, call it once for session continuity with agent_name set to your agent identity (omit it when the server sets MEMPALACE_AGENT_NAME); otherwise skip the diary. Continue conversation after saving."
}
HOOKJSON
else
    # Not time yet — let the AI stop normally
    echo "{}"
fi
