# MCP Integration — Claude Code

## Setup

Run the MCP server (full 28-tool default):

```bash
python -m mempalace_code.mcp_server
```

Or add it to Claude Code:

```bash
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server
```

## Tool Profiles

Pass `--profile` to reduce the exposed tool surface at startup (GitHub issue #6):

```bash
# Named profiles
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server --profile=minimal
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server --profile=kg
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server --profile=code
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server --profile=notes

# Explicit tool list — replaces the profile base set
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server --tools=search,add_drawer,diary_*

# Add or remove tools from a profile
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server --profile=minimal --include=kg_query
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server --profile=full --exclude=delete_wing,delete_drawer
```

Codex CLI variant:

```bash
codex mcp add mempalace-code -- python -m mempalace_code.mcp_server --profile=minimal
```

| Profile | Tools | Best for |
|---------|-------|----------|
| `full` _(default)_ | 28 | Full capability |
| `minimal` | 4 | Search + store only |
| `kg` | 8 | Minimal + temporal KG |
| `code` | 10 | Code archaeology; no drawer-write/diary (`mine` included) |
| `notes` | 12 | Knowledge mgmt + diary; no code-search |

## Available Tools

The server exposes the full mempalace-code MCP toolset by default. Common entry points include:

- **mempalace_status** — palace stats (wings, rooms, drawer counts)
- **mempalace_search** — semantic search across all memories
- **mempalace_list_wings** — list all projects in the palace

See `README.md → MCP Server section` for the complete tool list.

## Usage in Claude Code

Once configured, Claude Code can search your memories directly during conversations.
If you use a named profile, paste the matching profile block from `docs/LLM_USAGE_RULES.md`
into your `CLAUDE.md` so the agent knows which tools are available.
