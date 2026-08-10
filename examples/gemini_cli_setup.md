# Gemini CLI Integration Guide

This guide explains how to connect mempalace-code to the [Gemini CLI](https://github.com/google/gemini-cli) through MCP.

## Prerequisites

- Python 3.11+
- Gemini CLI installed and configured

## 1. Installation

On many Linux systems, installing Python packages globally is restricted. Use an isolated virtual environment; a source checkout is not required.

```bash
# Create an isolated environment and install the released package
python3 -m venv ~/.local/share/mempalace-code
~/.local/share/mempalace-code/bin/pip install --upgrade pip mempalace-code

# Reuse these paths in the commands below (run them in this shell)
export MPALACE=~/.local/share/mempalace-code/bin/mempalace-code
export MPALACE_PYTHON=~/.local/share/mempalace-code/bin/python
```

## 2. Initialization

Set up the palace, then mine the project you want the agent to search.

```bash
# Initialize a project and cache the local embedding model if needed
"$MPALACE" init ~/projects/my-project
"$MPALACE" mine ~/projects/my-project
```

### Optional Identity
`mempalace-code wake-up` can include a local identity note:

- **`~/.mempalace/identity.txt`**: A plain-text file describing your role and focus.

Project wings come from the directory or explicit mining options. Do not create an undocumented `wing_config.json` as part of this setup.

## 3. Connect to Gemini CLI (MCP)

Add mempalace-code to Gemini CLI's MCP settings. Edit `~/.gemini/settings.json`
for every project, or `.gemini/settings.json` in a project for that project only.
Merge this `mcpServers` entry into an existing JSON object; do not overwrite
unrelated settings.

```json
{
  "mcpServers": {
    "mempalace-code": {
      "command": "/absolute/path/to/mempalace-code/bin/python",
      "args": ["-m", "mempalace_code.mcp_server"]
    }
  }
}
```

Replace the placeholder with the absolute value of `$MPALACE_PYTHON` printed by
your shell. An absolute Python path lets the server start from any working
directory.

## 4. Teach Gemini When to Use Memory

MCP wiring exposes the tools. To make Gemini use them proactively, add the canonical usage rules from `docs/LLM_USAGE_RULES.md` to `~/.gemini/GEMINI.md` for global use or `<project>/GEMINI.md` for project use. Reload instruction context with `/memory reload` after editing a file during a session.

Do not use the scripts in `hooks/` for Gemini. They are Claude Code-only legacy hooks and expect Claude Code hook events.

## 5. Usage

When Gemini CLI starts, it connects to the configured MCP server and discovers its tools. The usage rules determine when the agent should search or file memory; tool calls remain subject to the active model and tool policy.

### Manual Mining
If you want the AI to learn from your existing code or docs immediately, run the "mine" command:
```bash
"$MPALACE" mine /path/to/your/project
```

### Verification
In a Gemini CLI session, you can run:
- `/mcp list`: Verify `mempalace-code` is `CONNECTED`.
- `/memory show`: Confirm the intended `GEMINI.md` instructions are loaded.
- Ask Gemini to follow `docs/LLM_USAGE_RULES.md`, then give it a task-specific recall question that requires `mempalace_search`.
