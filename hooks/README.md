# mempalace-code Hooks — Claude Code Save Reminders (Legacy)

Optional Claude Code hooks that prompt the AI to save memories during conversations. They are
independent of the Agent Plugin instruction-loading boundary in `docs/AGENT_INSTALL.md` Section 7.

## What They Do

| Hook | When It Fires | What Happens |
|------|--------------|-------------|
| **Save Hook** | Every 15 human messages | Blocks the AI from stopping and tells it to save durable decisions, root causes, and concise evidence via MCP, plus a diary note when `mempalace_diary_write` is exposed |
| **PreCompact Hook** | Right before context compaction | Never blocks. Logs the event and, if `MEMPAL_DIR` is set, mines that conversations directory in the background |

The AI does the actual filing with MCP tools and the canonical usage rules, including duplicate checks, one topic per drawer, and diary vs drawer separation. The Save hook only decides when to block. Human messages are the prompts you send; tool results, slash-command wrappers, compaction summaries, subagent prompts, `[Request interrupted by user]` notice lines, and `<system-reminder>` entries in the transcript do not count (a prompt typed after a notice in the same entry does), whether their content is a string or a list of blocks.

The PreCompact hook cannot ask the AI to save: Claude Code gives the AI no turn before compaction, and a block decision cancels the compaction instead. A refused `/compact` or skipped auto-compact leaves the context full, and a compaction that recovers from a context-limit error fails the request.

## Install — Claude Code

The scripts live in this repository's `hooks/` directory; the installed package (wheel) does
not contain them. With a pip, pipx, or uv tool install, download both scripts first, from the
release tag of the version you have installed so they match it (download them again after an
upgrade):

```bash
MEMPALACE_VERSION="$(mempalace-code --version | awk '{print $NF}')"   # e.g. 1.15.0
mkdir -p ~/.local/share/mempalace-code/hooks
cd ~/.local/share/mempalace-code/hooks
curl -fsSLO "https://raw.githubusercontent.com/rergards/mempalace-code/v${MEMPALACE_VERSION}/hooks/mempal_save_hook.sh"
curl -fsSLO "https://raw.githubusercontent.com/rergards/mempalace-code/v${MEMPALACE_VERSION}/hooks/mempal_precompact_hook.sh"
```

Add to `.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/hooks/mempal_save_hook.sh",
        "timeout": 30
      }]
    }],
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "/absolute/path/to/hooks/mempal_precompact_hook.sh",
        "timeout": 30
      }]
    }]
  }
}
```

Make them executable (use the directory your settings point to; in a source checkout that is
the repository's `hooks/` directory):
```bash
chmod +x ~/.local/share/mempalace-code/hooks/mempal_save_hook.sh \
  ~/.local/share/mempalace-code/hooks/mempal_precompact_hook.sh
```

## Codex CLI / Other Agents

These hooks are **Claude Code-only** — they rely on Claude Code's `Stop` and `PreCompact` hook events (JSON with `session_id`, `stop_hook_active`, and `transcript_path` on stdin). Other agents (Codex CLI, Cursor, etc.) do not support these events.

**What to use instead:**

| Concern | Solution |
|---------|----------|
| **Code mining** (indexing source files) | `mempalace-code watch` — works with any client, re-mines on commit |
| **Conversation context** (decisions, discussions) | MCP tools — `mempalace_add_drawer`, `mempalace_diary_write` |
| **Session continuity** | Compatible clients load the Agent Plugin discovered by `mempalace-code agent-plugin path --json`; other clients use explicit MCP calls allowed by their client policy |

For Codex specifically, wire the MCP server in `~/.codex/config.toml` (see
`docs/AGENT_INSTALL.md` Step 5.2). If the client supports Agent Plugins 1.0, use
`mempalace-code agent-plugin path --json` and follow Section 7. Otherwise stop after MCP wiring.
`docs/LLM_USAGE_RULES.md` remains read-only reference material; mutation of `AGENTS.md` or any
other instruction file is unsupported.

## Configuration

Edit `mempal_save_hook.sh` to change:

- **`SAVE_INTERVAL=15`** — How many human messages between save requests. Lower = more frequent reminders, higher = less interruption.
- **`STATE_DIR`** — Where hook state is stored (defaults to `~/.mempalace/hook_state/`)
- **`MEMPAL_DIR`** — Optional, in both scripts. Set to a conversations directory to run `mempalace-code mine <dir> --mode convos` in the background on each save trigger (Save hook) or before each compaction (PreCompact hook). Leave blank (default) to skip the mine; the Save hook still asks the AI to save via the block reason message. Each mine re-chunks sessions that grew. It keeps the drawers of transcripts that are gone from the directory, for example sessions Claude Code deleted after `cleanupPeriodDays`, so the palace may hold the only copy of those conversations. A manual `mempalace-code mine <dir> --mode convos --full` removes those drawers; run it only when you want them gone.
- **`MEMPALACE_BIN`** — Optional, in both scripts. The absolute path of the `mempalace-code` executable (the output of `command -v mempalace-code`). Set it when the environment Claude Code gives hooks has a `PATH` without it, as is common for pipx, uv tool, and virtualenv installs.

### mempalace-code CLI

The hooks run the conversation miner:

```bash
mempalace-code mine <dir> --mode convos # Mine conversation transcripts
```

Without `--mode convos`, `mine` expects a project directory initialized with `mempalace-code init`.
The hooks run `MEMPALACE_BIN` when it is set, otherwise `mempalace-code` from `PATH`. Only
when the scripts are still inside a source checkout do they fall back to `python3 -m
mempalace_code` run from the checkout root, and only with Python 3.11 or newer. Otherwise they
log one line naming `MEMPALACE_BIN` to `~/.mempalace/hook_state/hook.log` and skip the mine;
neither hook ever blocks because of it.

## How It Works (Technical)

### Save Hook (Stop event)

1. Claude Code fires Stop after the AI response. The hook counts human prompts.
2. At the configured interval, it writes the current count to the legacy
   `${session_id}_last_save` file and emits a blocking save request.
3. The AI can attempt filing through the available MCP tools. Optional background
   conversation mining is a separate operation.
4. A Stop with `stop_hook_active=true` is allowed to finish. An inactive Stop at
   the same count also finishes because that interval was already requested.
5. Another interval of human prompts produces another request.

The state filename, numeric format, interval and reentry guard remain compatible.
The hook has no input reporting the result of the AI's MCP filing. Its checkpoint
and `TRIGGERING SAVE` log entry show that a request was triggered. A successful
save needs evidence from the operation that wrote the intended content.

### Result evidence and recovery

Keep three observations separate: a reminder was issued, a write was attempted,
and the intended content was verified in the intended palace. A skipped or failed
write leaves saving unconfirmed even when the hook allows the AI to stop. The
current hook waits until the next interval before issuing another reminder.

After a missed reminder or failed write, review the intended content and use the
existing MCP filing tools only within the current task's authority. Preserve the
reentry guard; editing the checkpoint to force repeated Stop blocks cannot prove
that content was saved. For partial writes, verify each required item before
deciding which remaining items need an authorized retry.

After a lost response or lost context, recover the target palace, wing, intended
content and current authority first. Inspect existing content before retrying.
Use the existing `mempalace_search` and `mempalace_check_duplicate` tools when
available. The CLI provides the same read-only search path below. Assign the
three variables from the verified target and intended content; the guards prevent
an unset value from selecting a default palace or dropping the wing filter.

```bash
: "${MEMPALACE_SAVE_PALACE:?set the verified palace path}"
: "${MEMPALACE_SAVE_WING:?set the verified wing}"
: "${MEMPALACE_SAVE_QUERY:?set distinctive intended content}"
mempalace-code --palace "$MEMPALACE_SAVE_PALACE" search "$MEMPALACE_SAVE_QUERY" \
  --wing "$MEMPALACE_SAVE_WING" --results 3 --compact
```

Follow a hit's printed `read` command when one is available. If recovery is
unavailable, including conversation drawers without line ranges, rerun the same
guarded search with the same palace, wing and query, removing only `--compact`,
to display full stored text.
A compact preview can omit required details. A matching verified item can be reconciled
without writing it again. Empty semantic search results alone do not prove
absence. If presence or absence remains uncertain, retain that status and stop
the dependent retry. A retry requires the existing duplicate checks and supported
write identity; a new deduplication or acknowledgement mechanism needs a separately
accepted requirement. Any accepted promise to checkpoint only after successful
filing must define the supported observation before changing this legacy state.

### PreCompact Hook

```
Context window getting full → Claude Code fires PreCompact
                                        ↓
                                Hook logs the event
                                        ↓
                                MEMPAL_DIR set? → background `mine <dir> --mode convos`
                                        ↓
                                Hook exits 0 with no decision
                                        ↓
                                Compaction proceeds
```

The hook never returns a block decision. The Save hook is what asks the AI to save before
detailed context is compacted away.

## Debugging

Check the hook log:
```bash
cat ~/.mempalace/hook_state/hook.log
```

Example output:
```
[14:30:15] Session abc123: 12 exchanges, 12 since last save
[14:35:22] Session abc123: 15 exchanges, 15 since last save
[14:35:22] TRIGGERING SAVE at exchange 15
[14:40:01] Session abc123: 18 exchanges, 3 since last save
```

## Cost

**Zero extra tokens.** The hooks are bash scripts that run locally. They don't call any API. The only "cost" is the AI spending a few seconds organizing memories at each checkpoint — and it's doing that with context it already has loaded.
