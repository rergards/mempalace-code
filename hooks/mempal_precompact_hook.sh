#!/bin/bash
# MEMPALACE PRE-COMPACT HOOK — Non-blocking log and optional ingest before compaction
#
# Claude Code "PreCompact" hook. Fires RIGHT BEFORE the conversation
# gets compressed to free up context window space.
#
# This hook NEVER blocks. Claude Code gives the AI no turn at PreCompact:
# a block decision (or exit 2) cancels the compaction instead of letting the
# AI save first. A refused /compact or skipped auto-compact keeps the context
# full, and a compaction that recovers from a context-limit error fails the
# request. Save prompting belongs to the Stop hook (mempal_save_hook.sh).
#
# === INSTALL ===
# Add to .claude/settings.local.json:
#
#   "hooks": {
#     "PreCompact": [{
#       "hooks": [{
#         "type": "command",
#         "command": "/absolute/path/to/mempal_precompact_hook.sh",
#         "timeout": 30
#       }]
#     }]
#   }
#
# Other agents: use MCP + usage rules instead of Claude Code hook events.
#
# === HOW IT WORKS ===
#
# Claude Code sends JSON on stdin with:
#   session_id — unique session identifier
#
# We log the event, optionally start a background conversation mine of
# MEMPAL_DIR, and exit 0 with no decision so compaction proceeds. Compaction
# does not delete the transcript file on disk, so the mine does not need to
# finish first.
#
# === MEMPALACE CLI ===
# With MEMPAL_DIR set, the hook runs: mempalace-code mine <dir> --mode convos
# Leave it blank to only log the event.

STATE_DIR="$HOME/.mempalace/hook_state"
mkdir -p "$STATE_DIR"

# Optional: set to a conversations directory to mine before compaction.
# Example: MEMPAL_DIR="$HOME/conversations"
# Leave empty to skip auto-ingest.
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

SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id','unknown'))" 2>/dev/null)
# Sanitize SESSION_ID as the Save hook does, so it cannot add lines to the log
SESSION_ID=$(echo "$SESSION_ID" | tr -cd 'a-zA-Z0-9_-')
[ -z "$SESSION_ID" ] && SESSION_ID="unknown"

echo "[$(date '+%H:%M:%S')] PRE-COMPACT triggered for session $SESSION_ID" >> "$STATE_DIR/hook.log"

# Optional: mine conversations in the background so compaction is not delayed
if [ -n "$MEMPAL_DIR" ] && [ -d "$MEMPAL_DIR" ]; then
    mine_conversations >> "$STATE_DIR/hook.log" 2>&1 &
fi

# Never block: no decision, so compaction proceeds.
exit 0
