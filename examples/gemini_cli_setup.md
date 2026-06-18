# Gemini CLI Integration Guide

This guide explains how to set up mempalace-code as a permanent memory for the [Gemini CLI](https://github.com/google/gemini-cli).

## Prerequisites

- Python 3.9+
- Gemini CLI installed and configured

## 1. Installation

On many Linux systems, installing Python packages globally is restricted. We recommend using a local virtual environment within the mempalace-code directory.

```bash
# Clone the repository (if you haven't already)
git clone https://github.com/rergards/mempalace-code.git
cd mempalace-code

# Create a virtual environment
python3 -m venv .venv

# Install dependencies and mempalace-code in editable mode
.venv/bin/pip install -e .
```

## 2. Initialization

Set up your "Palace" (the database) and configure your identity.

```bash
# Initialize the palace in the current directory
.venv/bin/mempalace-code init .
```

### Identity and Wings (Optional but Recommended)
You can manually define who you are and what projects you work on by creating/editing these files in `~/.mempalace/`:

- **`~/.mempalace/identity.txt`**: A plain text file describing your role and focus.
- **`~/.mempalace/wing_config.json`**: A JSON file mapping projects and name variants to "Wings".

## 3. Connect to Gemini CLI (MCP)

Register mempalace-code as an MCP server so Gemini CLI can use its tools.

```bash
gemini mcp add mempalace-code /absolute/path/to/mempalace-code/.venv/bin/python3 -m mempalace_code.mcp_server --scope user
```
*Note: Use the absolute path to ensure it works from any directory.*

## 4. Teach Gemini When to Use Memory

MCP wiring exposes the tools. To make Gemini use them proactively, add the canonical usage rules from `docs/LLM_USAGE_RULES.md` to your Gemini instruction file.

Do not use the scripts in `hooks/` for Gemini. They are Claude Code-only legacy hooks and expect Claude Code hook events.

## 5. Usage

Once connected, Gemini CLI will automatically:
- Start the mempalace-code server on launch.
- Use `mempalace_search` to find relevant past discussions.
- Use the usage rules to decide when to save decisions, root causes, concise evidence, and diary notes.

### Manual Mining
If you want the AI to learn from your existing code or docs immediately, run the "mine" command:
```bash
.venv/bin/mempalace-code mine /path/to/your/project
```

### Verification
In a Gemini CLI session, you can run:
- `/mcp list`: Verify `mempalace-code` is `CONNECTED`.
- Ask Gemini to follow `docs/LLM_USAGE_RULES.md`, then verify it can call `mempalace_status`.
