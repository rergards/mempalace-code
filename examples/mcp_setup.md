# MCP Integration — Claude Code

## Setup

Agent Plugins 1.0 compatible clients can load the portable package installed
with mempalace-code:

```bash
MEMPALACE_BIN="$(command -v mempalace-code)"
"$MEMPALACE_BIN" agent-plugin path --json
```

Read the JSON `path` field and use that directory. It contains `plugin.json`, `mcp.json`, and the
`skills/mempalace/SKILL.md` instruction bundle. The portable MCP config uses
`mempalace-code-mcp --profile=minimal`, exposing only
`mempalace_status`, `mempalace_search`, `mempalace_check_duplicate`, and
`mempalace_add_drawer`. Use direct MCP registration below when a client needs
`--profile=kg`, `--profile=code`, `--profile=notes`, `--profile=full`, or
custom `--tools` / `--include` / `--exclude` selectors.

Resolve and run the installed MCP launcher (full 29-tool default):

```bash
MEMPALACE_MCP="$(dirname "$MEMPALACE_BIN")/mempalace-code-mcp"
test -x "$MEMPALACE_BIN" && test -x "$MEMPALACE_MCP"
"$MEMPALACE_MCP"
```

Or add it to Claude Code:

```bash
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"
```

## Protocol Compatibility

The stdio command above is unchanged across the protocol migration. The server
negotiates the protocol per request: a modern client calling `server/discover`
gets the stable **2026-07-28** revision (with per-request `_meta`), while a
legacy client calling `initialize` gets the same handshake it always has.
Existing registrations — including the source-checkout `mempalace.mcp_server`
compatibility shim — do not need any changes, and profiles still work
identically under both dialects.

## Tool Profiles

Pass `--profile` to reduce the exposed tool surface at startup (GitHub issue #6):

```bash
# Named profiles
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=minimal
claude mcp add --scope project mempalace-code -- "$MEMPALACE_MCP" --profile=kg
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=code
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=notes

# Explicit tool list — replaces the profile base set
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --tools=search,add_drawer,diary_*

# Add or remove tools from a profile
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=minimal --include=kg_query
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=full --exclude=delete_wing,delete_drawer
```

Codex CLI variant:

```bash
codex mcp add mempalace-code -- "$MEMPALACE_MCP" --profile=minimal
```

Claude `user` scope writes `~/.claude.json`; Claude `project` scope writes `<project>/.mcp.json`.
Codex CLI registration writes `~/.codex/config.toml`; trusted projects may instead own an explicit
project `.codex/config.toml`. Do not translate Claude scope names or file owners across clients.
Paths remain separate quoted argv values.

| Profile | Tools | Best for |
|---------|-------|----------|
| `full` _(default)_ | 29 | Full capability |
| `minimal` | 4 | Search + store only |
| `kg` | 8 | Minimal + temporal KG |
| `code` | 10 | Code archaeology; no drawer-write/diary (`mine` included) |
| `notes` | 12 | Knowledge mgmt + diary; no code-search |

## Available Tools

The server exposes the full mempalace-code MCP toolset by default. Common entry points include:

- **mempalace_status** — palace inventory (wings, rooms, drawer counts); use for an explicit overview, not every session start
- **mempalace_search** — semantic search across all memories
- **mempalace_list_wings** — list all projects in the palace

See `README.md → MCP Server section` for the complete tool list.

## Instruction Boundary

Once configured, Claude Code can call the tools during conversations, subject to its tool policy.
If the target client supports Agent Plugins 1.0, discover the supported instruction bundle with
`mempalace-code agent-plugin path --json` and follow `docs/AGENT_INSTALL.md` Section 7. Otherwise
stop after MCP wiring. `docs/LLM_USAGE_RULES.md` remains read-only reference material; mutation
of `CLAUDE.md` or any other instruction file is unsupported.
