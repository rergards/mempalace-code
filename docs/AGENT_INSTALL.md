# AGENT_INSTALL — mempalace-code Install Runbook for Coding Agents

> **Audience:** Coding agents (Claude Code, Codex, Cursor, autopilot orchestrators) installing
> mempalace on behalf of a human. This is a decision-tree script, not prose. Execute steps
> sequentially; each step has a shell check, a **Pass →** branch, and a **Fail →** branch.
>
> **Hard constraints:**
> - NEVER use `sudo`. All install paths are user-level.
> - NEVER make path or scope decisions without asking the human first.
> - When a step says **ASK HUMAN**, pause and wait for a reply before continuing.
> - All commands target Unix/macOS. Windows is out of scope for v1.0.

---

## Section 1 — Preflight

Run all preflight checks before asking the human anything. Record results; they feed later branching.

---

### Step 1.1: Python version

**Check:**
```bash
python3 --version
```

Parse `major.minor` from stdout (e.g. `Python 3.11.4` → `3.11`).

**Pass →** `major >= 3` and `minor >= 9`. Record Python binary as `PYTHON=python3`. Continue to Step 1.2.

**Fail →** Python is absent or version < 3.11. **ASK HUMAN:** "Python 3.11 or later is required but was not found (or is too old). Please install Python 3.11+ and re-run this script. Reply `ready` when done."
Wait for `ready`. Re-run Step 1.1. If still failing after one retry, halt and report: "Cannot proceed — Python 3.11+ is required."

---

### Step 1.2: Existing mempalace install

**Check:**
```bash
command -v mempalace
```

Exit code 0 = binary found; non-zero = not installed.

**Pass →** Binary found. Record version — try the pipx venv Python first (works for any install method), fall back to system python3:
```bash
MPALACE_VER=$(
  "$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null)/mempalace/bin/python" \
    -c "import mempalace; print(mempalace.__version__)" 2>/dev/null \
  || python3 -c "import mempalace; print(mempalace.__version__)" 2>/dev/null
)
echo "$MPALACE_VER"
```
If this prints a version string, record `MEMPALACE_VERSION=$MPALACE_VER` and set `ALREADY_INSTALLED=true`. Skip Section 3 (Install). Continue to Step 1.3.

**Note:** For pipx installs, system `python3` cannot import mempalace — only the pipx venv Python can. The two-command fallback above handles both cases.

**Fail →** Binary not found. Set `ALREADY_INSTALLED=false`. Continue to Step 1.3.

---

### Step 1.3: Existing palace directory

**Check:**
```bash
test -d ~/.mempalace/palace && echo "exists" || echo "absent"
```

**Pass →** Output is `exists`. Set `PALACE_EXISTS=true`. Continue to Step 1.4.

**Fail →** Output is `absent`. Set `PALACE_EXISTS=false`. Continue to Step 1.4.

---

### Step 1.4: pipx availability

**Check:**
```bash
command -v pipx
```

**Pass →** Set `HAS_PIPX=true`. Continue to Step 1.5.

**Fail →** Set `HAS_PIPX=false`. Continue to Step 1.5.

---

### Step 1.5: uv availability

**Check:**
```bash
command -v uv
```

**Pass →** Set `HAS_UV=true`. Continue to Section 2.

**Fail →** Set `HAS_UV=false`. Continue to Section 2.

---

## Section 2 — Human-in-the-loop Questions

Ask all five questions before acting. Record answers; they parameterize Sections 3–5.

---

### Q1 — Install method

**Condition:** `ALREADY_INSTALLED=false`

**ASK HUMAN:** "I can install mempalace at the user level (recommended: `uv tool install` or `pipx`, isolated from other packages) or as a project dependency in the current virtual environment (`pip`). Reply `user` for isolated install or `project` for the current venv."

**Parse response:**
- `user` → Set `INSTALL_METHOD=user`. Prefer `uv tool install` if `HAS_UV=true`, else fall back to `pipx`.
- `project` → Set `INSTALL_METHOD=project`.
- Anything else → Repeat the question once. If still unclear, default to `user` and inform the human.

**Skip if:** `ALREADY_INSTALLED=true` — no install needed.

---

### Q2 — Palace storage path

**ASK HUMAN:** "Where should the memory palace be stored? The default location is `~/.mempalace/palace`. Reply `default` to use it, or provide a custom absolute path (e.g. `/data/mempalace/palace`). Advanced: you can also set the `MEMPALACE_PALACE_PATH` environment variable instead."

**Parse response:**
- `default` → Set `PALACE_PATH=~/.mempalace/palace`.
- An absolute path (starts with `/` or `~/`) → Set `PALACE_PATH=<that path>`.
- A `MEMPALACE_PALACE_PATH=...` export → Record the env var; set `PALACE_PATH` from it.
- Anything else → Repeat once; default to `~/.mempalace/palace` if still unclear.

**Note:** `PALACE_PATH` is the vector DB storage location. It is separate from the project directory passed to `mempalace init`.

---

### Q3 — Model download consent

**ASK HUMAN:** "mempalace uses a local embedding model (~80 MB) downloaded once from HuggingFace. This requires internet access during setup; after that everything runs offline. Reply `yes` to download now, `no` to skip (you can run `mempalace fetch-model` later), or `offline` if this machine has no internet access."

**Parse response:**
- `yes` → Set `DOWNLOAD_MODEL=yes`.
- `no` → Set `DOWNLOAD_MODEL=no`.
- `offline` → Set `DOWNLOAD_MODEL=no`. Note: airgapped setup — see `docs/OFFLINE_USAGE.md`.
- Anything else → Repeat once; default to `no` to be safe.

---

### Q4 — MCP scope

**ASK HUMAN:** "Should the mempalace MCP server be registered globally (available in all projects) or only for the current project? Reply `global` to register in `~/.mcp.json` (Claude Code) / `~/.codex/config.toml` (Codex), or `project` to register in `.mcp.json` in the current directory."

**Parse response:**
- `global` → Set `MCP_SCOPE=global`.
- `project` → Set `MCP_SCOPE=project`.
- Anything else → Repeat once; default to `global`.

---

### Q5 — Project to mine

**ASK HUMAN:** "Should I index a code project into the palace now? Reply with an absolute path to the project directory (e.g. `/home/user/projects/myapp`), or `skip` to do it later."

**Parse response:**
- An absolute path → Set `MINE_PATH=<that path>`.
- `skip` → Set `MINE_PATH=skip`.
- Anything else → Repeat once; default to `skip`.

---

## Section 3 — Install

**Skip this section if `ALREADY_INSTALLED=true`.**

---

### Step 3.0: Bootstrap script (preferred)

The bootstrap script handles venv creation, pip upgrade, install, and PATH symlink in one step.
It is the recommended path for servers, CI, and any machine where system pip may be outdated.

```bash
# From PyPI (default, once published)
curl -fsSL https://raw.githubusercontent.com/rergards/mempalace-code/main/scripts/bootstrap.sh | bash

# From git (before PyPI publish)
curl -fsSL https://raw.githubusercontent.com/rergards/mempalace-code/main/scripts/bootstrap.sh | MEMPALACE_SOURCE=git bash
```

**Pass →** Script exits 0 and prints `Done. mempalace <version> is ready.` Skip to Section 4.

**Fail →** Script exits non-zero. Read the error output. Common causes: no Python 3.11+, no `venv` module (`apt install python3-venv`). Fix and re-run, or fall through to manual Steps 3.1–3.3.

---

### Step 3.1: Install via pipx (INSTALL_METHOD=user, HAS_PIPX=true)

**Check:**
```bash
command -v pipx
```

**Pass →** Run:
```bash
pipx install mempalace-code
```
Exit code 0 = success. Continue to Step 3.4.

**Fail →** pipx not found but `INSTALL_METHOD=user`. Attempt to install pipx:
```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```
If that succeeds, re-run `pipx install mempalace-code`. If pipx install fails, fall through to Step 3.2.

---

### Step 3.2: Install via uv (INSTALL_METHOD=user and HAS_UV=true, or pipx unavailable)

**Check:**
```bash
command -v uv
```

**Pass →** Run:
```bash
uv tool install mempalace-code
```
Exit code 0 = success. Continue to Step 3.4.

**Fail →** uv not found. Fall through to Step 3.3.

---

### Step 3.3: Install via pip in venv (fallback)

No pipx, no uv. Create a venv and install.

**Important:** Ubuntu 22.04 and similar distros ship pip 22.x, which cannot build hatchling metadata. Upgrade pip inside the venv first.

```bash
python3 -m venv ~/.mempalace/venv
~/.mempalace/venv/bin/pip install --upgrade pip
~/.mempalace/venv/bin/pip install mempalace-code
```

Exit code 0 = success. Set `PYTHON=~/.mempalace/venv/bin/python`. Continue to Step 3.4.

**Fail →** pip install failed. **ASK HUMAN:** "Installation failed. Common causes: network error, Python too old, or permissions issue. Error output: `<paste stderr>`. Please check your network and Python version, then reply `retry` or `abort`."
- `retry` → Re-run Step 3.3 once.
- `abort` → Halt. Report error to human.

---

### Step 3.4: Post-install verification

```bash
python3 -c "import mempalace; print(mempalace.__version__)"
```

**Pass →** Prints a version string (e.g. `3.0.0`). Record `MEMPALACE_VERSION`. Continue to Section 4.

**Fail →** Import error. Likely cause: shell PATH not updated after pipx install. Try:
```bash
hash -r && python3 -c "import mempalace; print(mempalace.__version__)"
```
If still failing, **ASK HUMAN:** "mempalace was installed but cannot be imported. This usually means the pipx venv Python is not on PATH, or install was into a different environment. Reply `retry` after sourcing your shell profile (`. ~/.bashrc` or `. ~/.zshrc`) or `abort`."

---

## Section 4 — Init + Model Download

---

### Step 4a: Configure palace storage path

The palace storage path resolves in this priority order:
1. `MEMPALACE_PALACE_PATH` environment variable (highest)
2. `palace_path` key in `~/.mempalace/config.json`
3. Default: `~/.mempalace/palace`

**Check (custom path case):**
If `PALACE_PATH != ~/.mempalace/palace`, set the env var so all subsequent commands use it:
```bash
export MEMPALACE_PALACE_PATH="<PALACE_PATH>"
```
To make it permanent, also write to `~/.mempalace/config.json`:
```bash
mkdir -p ~/.mempalace
python3 -c "
import json, pathlib
cfg = pathlib.Path.home() / '.mempalace' / 'config.json'
data = json.loads(cfg.read_text()) if cfg.exists() else {}
data['palace_path'] = '<PALACE_PATH>'
cfg.write_text(json.dumps(data, indent=2))
print('palace_path written')
"
```

**Pass →** Output is `palace_path written`. Continue to Step 4b.

**Fail →** Write failed. **ASK HUMAN:** "Could not write `~/.mempalace/config.json`. The `MEMPALACE_PALACE_PATH` env var is still set for this session. Reply `continue` to proceed with session-only config, or `abort` to stop."

**Default path case:** No action needed — `mempalace init` will create `~/.mempalace/palace` automatically.

---

### Step 4b: Initialize a project directory

**Condition:** `MINE_PATH != skip`

Run:
```bash
mempalace init "<MINE_PATH>" --yes
```

The `--yes` flag auto-accepts all detected entities — required for non-interactive execution.

**Pass →** Exit code 0. Output includes `Entities saved` or `No entities detected`. Continue to Step 4c.

**Fail →** Non-zero exit. Common causes: directory does not exist, permissions error. **ASK HUMAN:** "Could not initialize `<MINE_PATH>`. Error: `<paste stderr>`. Please confirm the path exists and is readable, then reply `retry` with a corrected path, or `skip`."
- `retry <path>` → Re-run with the corrected path.
- `skip` → Set `MINE_PATH=skip`. Continue to Step 4c.

---

### Step 4c: Download embedding model

**Condition:** `DOWNLOAD_MODEL=yes`

Run:
```bash
mempalace fetch-model
```

`fetch-model` is idempotent — if the model is already cached it loads instantly from disk (no network call). Expected output ends with `Done — embedding model is ready for offline use.`

Exit code 0 = success. Set `MODEL_READY=true`. Continue to Step 4d.

**Fail →** Retry once. If still failing, **ASK HUMAN:** "Model download failed (network error or HuggingFace unavailable). The palace will work without the model, but search quality will degrade until it is available. Reply `retry` to try again, or `continue` to proceed without the model (run `mempalace fetch-model` later)."

**Condition:** `DOWNLOAD_MODEL=no` → Set `MODEL_READY=false`. Note to human: run `mempalace fetch-model` before first search.

---

### Step 4d: Mine the project (if applicable)

**Condition:** `MINE_PATH != skip`

```bash
mempalace mine "<MINE_PATH>"
```

**Pass →** Exit code 0. Output ends with a filed-drawer count. Continue to Section 5.

**Fail →** Mine failed. **ASK HUMAN:** "Mining `<MINE_PATH>` failed. Error: `<paste stderr>`. Reply `retry` or `skip`."

---

## Section 5 — MCP Wiring

Wire the mempalace MCP server so your AI assistant can call it during conversations.

**Important:** The MCP server is `python -m mempalace.mcp_server`, not a CLI subcommand. The Python interpreter used must be the one that has `mempalace` importable:
- **pipx install:** `$(pipx environment --value PIPX_LOCAL_VENVS)/mempalace/bin/python`
- **uv / pip-in-venv:** the venv Python (e.g. `~/.mempalace/venv/bin/python` or `.venv/bin/python`)
- **pip --user install:** `python3` if the package is on PATH

Resolve the Python path before Step 5.1:
```bash
MPALACE_PYTHON=$(python3 -c "import sys; print(sys.executable)")
# Verify mempalace is importable from this Python:
"$MPALACE_PYTHON" -c "import mempalace; print('ok')"
```

**Pass →** Output is `ok`. Use `$MPALACE_PYTHON` in all MCP wiring below.

**Fail →** Find the pipx venv Python:
```bash
MPALACE_PYTHON=$(pipx environment --value PIPX_LOCAL_VENVS)/mempalace/bin/python
"$MPALACE_PYTHON" -c "import mempalace; print('ok')"
```

---

### Step 5.1: Claude Code MCP Wiring

**Check — already wired?**
```bash
claude mcp list 2>/dev/null | grep -i mempalace
```

**Pass →** mempalace is already in the MCP list. Set `CLAUDE_WIRED=true`. Skip to Step 5.2.

**Fail →** Not wired. Proceed based on `MCP_SCOPE`.

#### 5.1-A: Global scope (MCP_SCOPE=global)

Preferred (CLI):
```bash
claude mcp add --scope user mempalace -- "$MPALACE_PYTHON" -m mempalace.mcp_server
```

Exit code 0 = success. This writes to `~/.mcp.json` under the `mcpServers` key.

**Fail (CLI not available) →** Manual fallback — edit `~/.mcp.json` (create if absent):
```json
{
  "mcpServers": {
    "mempalace": {
      "type": "stdio",
      "command": "<MPALACE_PYTHON>",
      "args": ["-m", "mempalace.mcp_server"]
    }
  }
}
```
If `~/.mcp.json` already exists with other entries, merge only the `"mempalace"` key into `"mcpServers"` without overwriting other keys.

#### 5.1-B: Project scope (MCP_SCOPE=project)

Preferred (CLI):
```bash
claude mcp add --scope project mempalace -- "$MPALACE_PYTHON" -m mempalace.mcp_server
```

**Fail (CLI not available) →** Manual fallback — create or update `.mcp.json` in the current working directory:
```json
{
  "mcpServers": {
    "mempalace": {
      "command": "<MPALACE_PYTHON>",
      "args": ["-m", "mempalace.mcp_server"]
    }
  }
}
```

**Post-wire check:**
```bash
claude mcp list 2>/dev/null | grep -i mempalace
```

**Pass →** Set `CLAUDE_WIRED=true`. Continue to Step 5.2.

**Fail →** **ASK HUMAN:** "Claude Code MCP wiring appears to have failed — `claude mcp list` does not show mempalace. Manual fix: add the entry to `~/.claude.json` (global) or `.mcp.json` (project) as shown above, then reply `done` to continue."

---

### Step 5.2: Codex MCP Wiring

**Check — codex CLI available?**
```bash
command -v codex
```

**Pass →** Codex CLI found. Check if `codex mcp` subcommand exists:
```bash
codex mcp --help 2>/dev/null && echo "has_mcp" || echo "no_mcp"
```

If `has_mcp`:
```bash
codex mcp add mempalace -- "$MPALACE_PYTHON" -m mempalace.mcp_server
```

Exit code 0 = success. Set `CODEX_WIRED=true`.

If `no_mcp` or CLI add fails → Fall through to manual TOML edit below.

**Fail (no codex CLI) →** Skip Codex wiring or use manual TOML if the human uses Codex.

#### Manual TOML fallback (any Codex install)

Edit `~/.codex/config.toml`. Resolve `MPALACE_PYTHON` first (see Step 5 preamble), then append:

```toml
[mcp_servers.mempalace]
command = "<MPALACE_PYTHON>"
args = ["-m", "mempalace.mcp_server"]
```

If `~/.codex/config.toml` does not exist, create the directory first:
```bash
mkdir -p ~/.codex
```

**Pass →** File written. Set `CODEX_WIRED=true`.

**Fail →** **ASK HUMAN:** "Could not write `~/.codex/config.toml`. Error: `<paste>`. Please create the file manually using the TOML snippet above, then reply `done`."

---

### Step 5.3: Auto-save for conversation context

Code mining is handled by the watcher (`mempalace watch-all`) and works with any client. Conversation context (decisions, discussions, debugging notes) is saved via **MCP tools + usage rules** — this works identically across all agents.

The recommended approach for **all agents** (Claude Code, Codex, Cursor, etc.):
1. Wire the MCP server (Steps 5.1/5.2) so the agent can call `mempalace_add_drawer` and `mempalace_diary_write`.
2. Add usage rules to the agent's instructions (Section 7) so it knows when to save.

That's it. No hooks needed.

> **Legacy: Claude Code auto-save hooks.** Claude Code also supports optional bash hooks that fire on Stop/PreCompact events and remind the AI to save at fixed intervals. These are redundant if you have MCP + usage rules set up, but are documented in [`hooks/README.md`](../hooks/README.md) for users who want belt-and-suspenders.

---

## Section 6 — Verification

Run all checks. Each one is a pass/fail with an explicit failure action.

---

### Step 6.1: Palace status

```bash
mempalace status
```

**Pass →** Exit code 0. Output shows palace path, total drawers, and wing list. Confirm `palace_path` in the output matches `PALACE_PATH`.

**Fail →** Exit code non-zero or output is empty/error. Likely causes: wrong `PALACE_PATH`, palace not initialized. **ASK HUMAN:** "Palace status check failed. Error: `<paste stderr>`. Common fix: check `MEMPALACE_PALACE_PATH` env var or run `mempalace init <project_dir>`. Reply `retry` after fixing, or `skip`."

---

### Step 6.2: Search smoke test

```bash
mempalace search "test" --results 1
```

**Pass →** Exit code 0. Output contains a formatted result block with `wing`, `room`, and `similarity` fields, or an `empty palace` message (acceptable for a fresh palace). Either is a pass.

**Fail →** Exit code non-zero. Common causes: palace not initialized, embedding model not downloaded.
- If model not downloaded: run `mempalace fetch-model` (see Step 4c), then retry.
- Otherwise: **ASK HUMAN:** "Search smoke test failed. Error: `<paste stderr>`. Reply `retry` or `skip`."

---

### Step 6.3: MCP tool availability

For Claude Code:
```bash
claude mcp list 2>/dev/null | grep mempalace
```

**Pass →** mempalace appears in the list. Wiring is confirmed.

**Fail →** Not in list. Re-run Step 5.1 wiring. If still failing after one retry, **ASK HUMAN:** "MCP wiring could not be confirmed. Please check `~/.claude.json` or `.mcp.json` manually and reply `done` when corrected."

---

## Section 7 — Usage Rules (CLAUDE.md injection)

After a successful install and verification, offer to inject mempalace usage rules into the human's CLAUDE.md. These rules teach the AI assistant *how* to use mempalace effectively — without them, the tools are available but the assistant won't know when or how to call them.

---

### Step 7.1: Offer injection

**ASK HUMAN:** "mempalace is installed and working. Should I add usage rules to your CLAUDE.md so your AI assistant knows how to use mempalace effectively? This teaches it when to search, when to store, and how to organize memories. Reply `yes` (recommended) or `skip`."

- `yes` → Continue to Step 7.2.
- `skip` → Skip Section 7 entirely.

---

### Step 7.2: Determine target file

Based on `MCP_SCOPE`:

- `global` → Target: `~/.claude/CLAUDE.md` (or create if absent)
- `project` → Target: `CLAUDE.md` in the current working directory

If the target file already contains `mempalace` (case-insensitive), **ASK HUMAN:** "Your CLAUDE.md already mentions mempalace. Should I append the usage rules anyway? Reply `yes` or `skip`."

---

### Step 7.3: Append usage rules

Append the following block to the target file. Do not modify any existing content.

````markdown

# mempalace-code — Usage Rules

mempalace-code is a semantic AI memory system available via MCP tools. It stores verbatim content in a local vector database — no cloud, no API keys.

## Core Concepts

- **Wings** — a project or knowledge domain (e.g. `myapp`, `people`, `decisions`)
- **Rooms** — topics within a wing (e.g. `backend`, `architecture`, `debugging`)
- **Drawers** — verbatim content stored in a room. Never summarized, never compressed.
- **Knowledge Graph** — temporal entity-relationship triples for facts that change over time

## When to Search (`mempalace_search`)

Search mempalace **before** reading files, grepping code, or planning work when the task involves:
- A new feature request — search the feature name and adjacent domain
- A bug investigation — search the symptom and component
- Questions about past decisions, people, project history, or timelines
- Any topic that may have been discussed in a previous session

Try 2–3 phrasings if the first query returns nothing. For entity-specific facts, also use `mempalace_kg_query`.

Skip searching only for pure mechanical operations (running tests, formatting) where there is nothing to look up.

## When to Write (`mempalace_add_drawer`)

Write a drawer after:
- A significant decision or architectural discussion — store the reasoning verbatim
- Debugging a hard problem — store the root cause analysis
- Learning context about people, timelines, or project goals
- Session wrap-up — summarize what was accomplished and key decisions

**Do not write** routine code changes (git log has this), information already in project files, or duplicate content (the tool checks automatically at 0.9 similarity).

**Content rules:**
- Store **verbatim** — do not summarize or compress
- Include context: who decided, why, what alternatives were rejected
- One topic per drawer

## Wing/Room Conventions

| Wing | Use for |
|------|---------|
| `<project_slug>` | Project-specific knowledge |
| `people` | Facts about collaborators and stakeholders |
| `decisions` | Cross-project architectural or process decisions |

Use `mempalace_list_rooms` to check existing rooms before creating new ones.

## Knowledge Graph (`mempalace_kg_*`)

Use for facts that **change over time**: version numbers, team roles, project status, tech stack choices.

- Always `mempalace_kg_invalidate` the old fact before adding a replacement
- Good: "myapp uses Postgres", "deploy freeze starts 2026-03-05"
- Bad: code patterns, debugging notes (use drawers instead)

## Agent Diary (`mempalace_diary_write`)

Write at end of significant sessions to maintain continuity across conversations. Use `agent_name` matching your assistant identity (e.g. `"claude-code"`).
````

**Pass →** Content appended. Inform human: "Added mempalace usage rules to `<target file>`. Your AI assistant will now use mempalace proactively."

**Fail →** File write failed. Print the snippet above and **ASK HUMAN:** "Could not write to `<target file>`. Please paste the block above into your CLAUDE.md manually."

---

## End State

A successful install produces:

| Item | Expected state |
|------|---------------|
| `python3 -c "import mempalace; print(mempalace.__version__)"` | Prints version string |
| `command -v mempalace` | Returns path to binary |
| `mempalace status` | Exit 0, shows palace path |
| `mempalace search "test" --results 1` | Exit 0, formatted output |
| `claude mcp list \| grep mempalace` | Shows entry (if Claude Code target) |
| `~/.codex/config.toml` contains `mcp_servers.mempalace` | Present (if Codex target) |

---

## Reference

| Topic | Source |
|-------|--------|
| Palace path config | `mempalace/config.py:93–98` — env → config.json → default |
| All CLI flags | `mempalace --help` / `mempalace <cmd> --help` |
| MCP tool list (27 tools) | `README.md` → MCP Server section |
| Auto-save hooks | `hooks/README.md` |
| Airgapped / offline setup | `docs/OFFLINE_USAGE.md` |
| Manual MCP setup examples | `examples/mcp_setup.md` |

---

## Troubleshooting

### Search returns empty or counts don't match

```bash
mempalace health
```

If `ok: false` or errors reported:

```bash
mempalace repair --dry-run    # see what would be recovered
mempalace repair --rollback   # roll back to last working version
```

### MCP tools return empty wings/rooms

Same as above — likely fragment corruption. Run `mempalace health`.

### "Table unreadable" or LanceDB errors

Storage corruption. Use `mempalace repair --rollback`. Data added after corruption point is lost. This is why auto-backup exists (`~/.mempalace/backups/pre_optimize_*.tar.gz`).

### Re-mine doesn't fix the issue

Manual drawers are not regenerated by mining. Check if you have a backup:

```bash
mempalace backup list
mempalace restore <backup.tar.gz>
```

---

## Validation Log

*End-to-end validation status: pending — to be recorded after first clean-machine agent run.*

Record format (fill in after validation):
```
Agent:      <Claude Code | Codex | other>
Date:       <ISO date>
Machine:    <clean VM / CI container / other>
Deviations: <list any step where agent deviated from script, or "none">
Questions outside script: <list any, or "none">
Result:     <pass | fail>
```
