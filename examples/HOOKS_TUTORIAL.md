# How to Use mempalace-code Hooks (Auto-Save)

mempalace-code hooks are a legacy Claude Code "Auto-Save" feature. Compatible Agent Plugins 1.0
clients use the package discovered by `mempalace-code agent-plugin path --json`; follow
`docs/AGENT_INSTALL.md` Section 7. Other clients stop after MCP wiring and may consult
`docs/LLM_USAGE_RULES.md` only as read-only reference material. Instruction-file mutation is
unsupported.

### 1. What are these hooks?
* **Save Hook** (`hooks/mempal_save_hook.sh`): Every 15 human messages, blocks Claude from
  stopping and asks it to save durable decisions, root causes, and a diary note with the MCP tools.
* **PreCompact Hook** (`hooks/mempal_precompact_hook.sh`): Never blocks. Logs each compaction and,
  if `MEMPAL_DIR` is set, mines that conversations directory in the background. Claude Code gives
  the AI no turn before compaction, so this hook cannot ask it to save.

Apart from the optional `MEMPAL_DIR` mine, the hooks write no memories themselves; the AI files
them through MCP.

### 2. Setup for Claude Code
Follow [`hooks/README.md`](../hooks/README.md). It has the settings JSON with absolute script
paths and timeouts, the `chmod +x` step, and the `MEMPAL_DIR` option. Hook commands run from
Claude Code's current directory, so relative paths such as `./hooks/...` resolve only inside a
mempalace-code checkout.
