# Gemini CLI Integration Guide

This guide explains how to connect mempalace-code to the [Gemini CLI](https://github.com/google-gemini/gemini-cli) through MCP.

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
export MPALACE_MCP=~/.local/share/mempalace-code/bin/mempalace-code-mcp
```

## 2. Initialization

Set up the project, cache the embedding model once, then mine the project you want the agent to
search. `init --skip-model-download` never downloads; `fetch-model` caches the ~80 MB model with
network access (see `docs/OFFLINE_USAGE.md` for airgapped machines).

```bash
"$MPALACE" init ~/projects/my-project --skip-model-download
"$MPALACE" fetch-model
"$MPALACE" mine ~/projects/my-project
```

The palace lives at `~/.mempalace/palace` unless `palace_path` in `~/.mempalace/config.json` names
another one (see `docs/AGENT_INSTALL.md` Step 4a). Gemini CLI starts the MCP server without your
shell's environment, so do not rely on an exported `MEMPALACE_PALACE_PATH`.

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
      "command": "/absolute/path/to/mempalace-code/bin/mempalace-code-mcp",
      "args": ["--profile=minimal"]
    }
  }
}
```

Replace the placeholder with the absolute value of `$MPALACE_MCP` printed by
your shell (`echo "$MPALACE_MCP"`); JSON does not expand `~`. An absolute launcher
path lets the server start from any working directory. `--profile=minimal` exposes
four tools (status, search, duplicate check, add drawer); use `--profile=kg`,
`--profile=code`, `--profile=notes`, or `--profile=full` (all 29 tools) as described
in `examples/mcp_setup.md`. To use a palace other than the one `config.json` names,
add `"env": {"MEMPALACE_PALACE_PATH": "/absolute/path/to/palace"}` to this entry.

## 4. Instruction Boundary

MCP wiring exposes the tools. If the target client supports Agent Plugins 1.0, discover the
supported instruction bundle with `mempalace-code agent-plugin path --json` and follow
`docs/AGENT_INSTALL.md` Section 7. Otherwise stop after MCP wiring. The full rules in
`docs/LLM_USAGE_RULES.md` remain read-only reference material; mutation of `GEMINI.md` or any
other instruction file is unsupported.

Do not use the scripts in `hooks/` for Gemini. They are Claude Code-only legacy hooks and expect Claude Code hook events.

## 5. Usage

When Gemini CLI starts, it connects to the configured MCP server and discovers its tools. Tool
calls remain subject to the active model and tool policy.

### Manual Mining
If you want the AI to learn from your existing code or docs immediately, run the "mine" command:
```bash
"$MPALACE" mine /path/to/your/project
```

### Verification
In a Gemini CLI session, you can run:
- `/mcp list`: Verify `mempalace-code` is `CONNECTED`.
- Ask Gemini to call `mempalace_search` for a task-specific recall question and verify that the
  tool result is returned.
