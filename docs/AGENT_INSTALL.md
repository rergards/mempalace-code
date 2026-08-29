# AGENT_INSTALL — mempalace-code Install Runbook for Coding Agents

> **Audience:** Coding agents (Claude Code, Codex, Cursor, autopilot orchestrators) installing
> mempalace-code on behalf of a human. This is a decision-tree script, not prose. Execute steps
> sequentially; each step has a shell check, a **Pass →** branch, and a **Fail →** branch.
>
> **Hard constraints:**
> - NEVER use `sudo`. All install paths are user-level.
> - NEVER make path or scope decisions without asking the human first.
> - When a step says **ASK HUMAN**, pause and wait for a reply before continuing.
> - All commands target Unix/macOS. Windows is out of scope for v1.0.

---

## Section 0 — Capability Map for Install Evaluation

Use this section when the human asks whether mempalace-code is worth installing. It is a
feature checklist, not an install step.

| Surface | Current capability |
|---------|--------------------|
| Code/docs mining | `mempalace-code mine <dir>` indexes supported source, docs, prose, config, and data files into LanceDB |
| Conversation/log ingest | `mempalace-code mine <dir> --mode convos` ingests Claude Code JSONL, Codex CLI JSONL, Gemini CLI JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, and plain text transcripts |
| Multi-project sync | `mempalace-code mine-all <parent>` assigns one wing per initialized project; `--new-only` skips already-known wings |
| Auto-watch | `mempalace-code watch <initialized-project>` watches one project directly; `mempalace-code watch <parent>` watches all initialized projects in a parent directory; re-mines on commit by default; `--on-save` is available but noisier |
| MCP tools | 29 tools (direct-registration default `full` profile): semantic search, code search, file context/read, manual drawers, KG, architecture retrieval, graph tunnels, diary, re-mine; named profiles (`minimal`, `kg`, `code`, `notes`) reduce the exposed subset at startup |
| Agent Plugin package | Installed Agent Plugins 1.0 root discoverable with `mempalace-code agent-plugin path --json`; portable `mcp.json` uses `mempalace-code-mcp --profile=minimal` plus bundled `skills/mempalace/SKILL.md` |
| KG / architecture | Temporal facts plus .NET/Python architecture extraction; .NET project/type graph tools require pre-mined symbols |
| Local-model fallback | `mempalace-code wake-up` emits memory layers for agents without MCP support |
| Safety/ops | Local embeddings, no API key, backup/restore/export/import, health/repair/cleanup, scan excludes, disk-budget guards |

Language support summary:
- `code_search(language=...)` accepts 45 searchable labels from the shared miner catalog.
- Tree-sitter AST when `[treesitter]` is installed: Python, TypeScript, JavaScript, TSX, JSX, Go, Rust.
- Regex structural: Java, Kotlin, C#, F#, VB.NET, XAML, Swift, PHP, Scala, Dart, Lua, Ruby, Terraform/HCL.
- YAML-aware/static: Kubernetes manifests, Helm charts/templates, Ansible playbooks/roles/inventory.
- Prose/metadata: Markdown and plain text keep heading paths and section flags.
- Adaptive/searchable: C/C++, shell, SQL, HTML/CSS, JSON/YAML/TOML, CSV, Dockerfile, Make, templates, config.
- Extensions outside the miner catalog are skipped by normal scans unless an exact file path is force-included.

Evaluation output contract:
1. Estimate token/context waste from repeated explanation and repeated file reads.
2. Rank high-ROI indexed surfaces in the target repo.
3. List supported and unsupported stack pieces from the table above.
4. If the repo already has curated memory docs, recommend a complement strategy:
   KG for volatile current facts, drawers/indexes for verbatim source material,
   curated docs for compressed narrative and reasoning.
5. Recommend adoption order: KG first, docs/drawers second, one scoped code project last.
6. Recommend MCP scope: `project` for trial/tool-surface control, `global` for mature cross-project use, or skip.
7. Name the cost: direct registration without selectors exposes 29 MCP tools; the portable Agent Plugin defaults to 4 and bundles its concise skill. Recommend the smallest profile that covers the workflow.
8. Give decision: install now, try scoped, wait for a named feature, or skip; include exact first commands. If recommending a trial, suggest `--profile=minimal` or `--profile=code` to limit tool surface.

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

**Pass →** Python is 3.11 or later. Record Python binary as `PYTHON=python3`. Continue to Step 1.2.

**Fail →** Python is absent or version < 3.11. **ASK HUMAN:** "Python 3.11 or later is required but was not found (or is too old). Please install Python 3.11+ and re-run this script. Reply `ready` when done."
Wait for `ready`. Re-run Step 1.1. If still failing after one retry, halt and report: "Cannot proceed — Python 3.11+ is required."

---

### Step 1.2: Existing mempalace-code install

**Check:**
```bash
command -v mempalace-code
```

Exit code 0 = binary found; non-zero = not installed.

**Pass →** Binary found. Treat the invoked executable as the `existing` owner and resolve its
sibling MCP launcher without importing through ambient Python:
```bash
MEMPALACE_BIN="$(command -v mempalace-code)"
test -x "$MEMPALACE_BIN"
```
If the selected launcher exists, set `INSTALL_METHOD=existing` and `ALREADY_INSTALLED=true`.
Skip package installation, then run Step 3.4 to resolve its sibling once and persist notification
consent before prompt-capable commands.
The `mempalace` command name may belong to upstream/vanilla MemPalace; do not use it
to detect this fork unless it was explicitly created by `mempalace-code install-alias`.

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

Ask each applicable question below before its dependent action. Record the literal answers; they
parameterize Sections 3–7. Step 6.5 may ask one additional scheduler question only after its
read-only Linux eligibility checks pass.

---

### Q1 — Install method

**Condition:** `ALREADY_INSTALLED=false`

**ASK HUMAN:** "Choose one install owner: `uv`, `pipx`, `project`, or `bootstrap`. No branch falls back to another owner. Bootstrap is a separate remote-script choice."

**Parse response:**
- `uv` → Set `INSTALL_METHOD=uv`.
- `pipx` → Set `INSTALL_METHOD=pipx`.
- `project` → Set `INSTALL_METHOD=project`; require an already-active virtual environment.
- `bootstrap` → Set `INSTALL_METHOD=bootstrap`; continue only after the separate source/ref choice in Step 3.0.
- Anything else → Repeat once. If still unclear, stop; do not infer an installer from availability.

**Skip if:** `ALREADY_INSTALLED=true` — no install needed.

---

### Q2 — Palace storage path

**ASK HUMAN:** "Where should the memory palace be stored? The default location is `~/.mempalace/palace`. Reply `default` to use it, or provide a custom absolute path (e.g. `/data/mempalace/palace`). Advanced: you can also set the `MEMPALACE_PALACE_PATH` environment variable instead."

**Parse response:**
- `default` → Set `PALACE_PATH=~/.mempalace/palace`.
- An absolute path (starts with `/` or `~/`) → Set `PALACE_PATH=<that path>`.
- A `MEMPALACE_PALACE_PATH=...` export → Record the env var; set `PALACE_PATH` from it.
- Anything else → Repeat once. If still unclear, stop and ask the human for `default`, an absolute path, or an environment-variable export; do not choose a storage path.

**Note:** `PALACE_PATH` is the vector DB storage location. It is separate from the project directory passed to `mempalace-code init`.

---

### Q3 — Model download consent

**ASK HUMAN:** "mempalace-code uses a local CPU FastEmbed/ONNX model cached once with immutable MemPalace provenance. This requires internet access only if the model is not already cached; after that everything runs offline. Reply `yes` to cache/verify now, `no` to skip (you can run `mempalace-code fetch-model` later), or `offline` if this machine has no internet access."

**Parse response:**
- `yes` → Set `DOWNLOAD_MODEL=yes`.
- `no` → Set `DOWNLOAD_MODEL=no`.
- `offline` → Set `DOWNLOAD_MODEL=no`. Note: airgapped setup — see `docs/OFFLINE_USAGE.md`.
- Anything else → Repeat once; default to `no` to be safe.

---

### Q4 — MCP clients and supported scope

**ASK HUMAN:** "Which installed clients should be configured: `claude`, `codex`, `both`, or `skip`? For Claude, choose CLI scope `user` or `project`. Codex CLI registration uses its supported user configuration owner and has no project-scope choice here."

**Parse response:**
- Record `MCP_CLIENTS` exactly.
- If `MCP_CLIENTS=claude|both`, require `CLAUDE_SCOPE=user|project`.
- If `MCP_CLIENTS=codex|skip`, do not require or set `CLAUDE_SCOPE`.
- If `CLAUDE_SCOPE=project`, also require an existing absolute `CLAUDE_PROJECT_PATH`; do not
  reuse `MINE_PATH` implicitly.
- A Codex `project` answer is contradictory and stops before configuration.
- Empty, malformed, or unsupported values stop; no client is configured implicitly.

### Q5 — Version notifications

**ASK HUMAN:** "Enable weekly new-version notifications from PyPI? Reply `yes` or `no` (default). Empty, EOF, malformed, or contradictory input means `no`. This choice does not enable package updates."

Each notification check reads package metadata only and does not install packages.

- `yes` → Set `NOTIFICATION_CHOICE=enabled`.
- Any other result → Set `NOTIFICATION_CHOICE=disabled`.

---

### Q6 — MCP tool profile

**ASK HUMAN:** "Which tool profile should the mempalace-code MCP server use? Reply with one of:
- `full` — all 29 tools (direct-server default; no surface reduction)
- `minimal` — 4 tools: status, search, duplicate check, and store
- `kg` — 8 tools: minimal + temporal knowledge graph
- `code` — 10 tools: code archaeology (no drawer-write/diary)
- `notes` — 12 tools: knowledge management + diary (no code-search)

If unsure, reply `minimal` for a bounded memory-only trial. Choose `code` for code
archaeology or `full` only when the workflow needs the broader surfaces."

**Parse response:**
- `full` → Set `MCP_PROFILE=full`.
- `minimal` → Set `MCP_PROFILE=minimal`.
- `kg` → Set `MCP_PROFILE=kg`.
- `code` → Set `MCP_PROFILE=code`.
- `notes` → Set `MCP_PROFILE=notes`.
- Anything else → Repeat once. If still unclear, stop and ask the human to choose a profile; do not silently add tools to the agent context.

---

### Q7 — Project or corpus to mine

**ASK HUMAN:** "Should I index something into the palace now? Reply `project:/abs/path` for code/docs, `convos:/abs/path` for conversation/log exports, a bare absolute path for code/docs, or `skip` to do it later. For large monorepos, a high-ROI docs/spec subdirectory is valid for the first trial."

**Parse response:**
- `project:/abs/path` → Set `MINE_PATH=<path>` and `MINE_MODE=projects`.
- `convos:/abs/path` → Set `MINE_PATH=<path>` and `MINE_MODE=convos`.
- A bare absolute path → Set `MINE_PATH=<that path>` and `MINE_MODE=projects`.
- `skip` → Set `MINE_PATH=skip` and `MINE_MODE=projects`.
- Anything else → Repeat once. If still unclear, stop and ask the human for a path or `skip`; do not infer a corpus to mine.

---

## Section 3 — Install

**Skip this section if `ALREADY_INSTALLED=true`.**

For side-by-side use with upstream/vanilla MemPalace, prefer an isolated user-level
install (`uv tool install` or `pipx`). Packaged installs use the console command
`mempalace-code` and the Python import package `mempalace_code`, so they can
share a Python environment with upstream/vanilla `mempalace`.

---

### Step 3.0: Execute exactly the selected install branch

Each value is terminal. A missing command or failed install stops with that branch's retry
command. Changing installers requires a new explicit Q1 answer.

**`INSTALL_METHOD=uv`:**

```bash
command -v uv
uv tool install mempalace-code
MEMPALACE_BIN="$(uv tool dir --bin)/mempalace-code"
```

**`INSTALL_METHOD=pipx`:**

```bash
command -v pipx
pipx install mempalace-code
PIPX_BIN_DIR="$(pipx environment --value PIPX_BIN_DIR)"
MEMPALACE_BIN="$PIPX_BIN_DIR/mempalace-code"
```

**`INSTALL_METHOD=project`:** require an active, human-selected virtual environment.

```bash
test -n "${VIRTUAL_ENV:-}"
python -m pip install mempalace-code
MEMPALACE_BIN="$VIRTUAL_ENV/bin/mempalace-code"
```

**`INSTALL_METHOD=bootstrap`:** first ask for `BOOTSTRAP_SOURCE=pypi|git`. A `git`
source also requires `PACKAGE_REF=<full 40-hex commit>`. Reject an unknown source, a ref with
`pypi`, or any missing, tag-shaped, abbreviated, or malformed Git ref before download or
installation. Resolve a reviewed release tag to its commit outside this unattended flow.
Then ask for one execution mode:

Validate both answers before either copy-paste branch:

```bash
is_full_commit() {
  [[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]
}
case "$BOOTSTRAP_SOURCE" in
  pypi) test -z "${PACKAGE_REF:-}" || { echo "PACKAGE_REF contradicts pypi source" >&2; exit 2; } ;;
  git) is_full_commit "${PACKAGE_REF:-}" || { echo "git requires full-commit PACKAGE_REF" >&2; exit 2; } ;;
  *) echo "BOOTSTRAP_SOURCE must be pypi or git" >&2; exit 2 ;;
esac
is_full_commit "${BOOTSTRAP_REF:-}" || { echo "BOOTSTRAP_REF must be a full commit" >&2; exit 2; }
```

- `inspect` (preferred): choose `BOOTSTRAP_REF=<full 40-hex commit>`,
  download a named file, show it to the human, then execute that exact file.

  ```bash
  BOOTSTRAP_VENV="${MEMPALACE_VENV:-$HOME/.mempalace/venv}"
  BOOTSTRAP_FILE="$(mktemp -t mempalace-bootstrap.XXXXXX)" || exit 1
  (
    trap 'rm -f -- "$BOOTSTRAP_FILE"' EXIT
    curl -fL "https://raw.githubusercontent.com/rergards/mempalace-code/$BOOTSTRAP_REF/scripts/bootstrap.sh" -o "$BOOTSTRAP_FILE" || exit 1
    less "$BOOTSTRAP_FILE" || exit 1
    MEMPALACE_VENV="$BOOTSTRAP_VENV" MEMPALACE_SOURCE="$BOOTSTRAP_SOURCE" MEMPALACE_GIT_REF="$PACKAGE_REF" bash "$BOOTSTRAP_FILE" || exit 1
  ) || exit 1
  MEMPALACE_BIN="$BOOTSTRAP_VENV/bin/mempalace-code"
  ```

- `direct` (explicit convenience choice): execute only a full-commit `BOOTSTRAP_REF`; report
  that this skips local inspection of the downloaded script.

  ```bash
  BOOTSTRAP_VENV="${MEMPALACE_VENV:-$HOME/.mempalace/venv}"
  BOOTSTRAP_FILE="$(mktemp -t mempalace-bootstrap.XXXXXX)" || exit 1
  (
    trap 'rm -f -- "$BOOTSTRAP_FILE"' EXIT
    curl -fL "https://raw.githubusercontent.com/rergards/mempalace-code/$BOOTSTRAP_REF/scripts/bootstrap.sh" -o "$BOOTSTRAP_FILE" || exit 1
    MEMPALACE_VENV="$BOOTSTRAP_VENV" MEMPALACE_SOURCE="$BOOTSTRAP_SOURCE" MEMPALACE_GIT_REF="$PACKAGE_REF" bash "$BOOTSTRAP_FILE" || exit 1
  ) || exit 1
  MEMPALACE_BIN="$BOOTSTRAP_VENV/bin/mempalace-code"
  ```

Any branch failure stops. Retry the same displayed branch command or return to Q1 for a new
human choice; never fall through to another installer.

Bootstrap accepts only an absolute venv path whose final node is absent or a real directory. It
reuses an existing venv only when its interpreter prefix matches that directory. It never replaces
`~/.local/bin/mempalace-code` and leaves any existing `mempalace` alias untouched. On a launcher
collision, inspect the reported path and move it aside only with the owner's approval before retrying.

---

### Step 3.4: Post-install verification

Resolve both installed launchers from the selected owner. Do not use ambient Python as proof.
Persist the Q5 notification choice before any `init`, `mine`, `health`, `search`, or bootstrap
post-install command that could otherwise show the first-run prompt.

```bash
test -x "$MEMPALACE_BIN"
MEMPALACE_MCP="$(dirname "$MEMPALACE_BIN")/mempalace-code-mcp"
test -x "$MEMPALACE_MCP"
"$MEMPALACE_BIN" version-check --disable  # Q5 default/No/empty/EOF/malformed
# or, only for an explicit Q5 yes:
"$MEMPALACE_BIN" version-check --enable
"$MEMPALACE_BIN" version-check --status
"$MEMPALACE_BIN" update status --json
```

Run exactly one of `--disable` or `--enable`. Record the resolved absolute launcher paths,
selected installer, notification state, and `Current version:` as `MEMPALACE_VERSION`.

**Pass →** All three commands exit 0 and print coherent output. Confirm the version shown by `version-check --status` and the `provenance.current_version` field in `update status --json` agree.

**Fail →** Executable not found. Likely cause: shell PATH not updated after pipx or uv tool install. Try:
```bash
hash -r && test -x "$MEMPALACE_BIN" && test -x "$MEMPALACE_MCP"
```
If still failing, **ASK HUMAN:** "mempalace-code was installed but is not on PATH. This usually means pipx/uv PATH was not sourced in the current shell. Reply `retry` after sourcing your shell profile (`. ~/.bashrc` or `. ~/.zshrc`) or `abort`."

---

### Step 3.5: Optional `mempalace` alias

The default executable is `mempalace-code` so this fork can coexist with
upstream/vanilla `mempalace` on the same machine. Only create the shorter alias if
the command name is unused:

```bash
command -v mempalace || "$MEMPALACE_BIN" install-alias
```

If `command -v mempalace` prints a path, leave it untouched. It may belong to
upstream/vanilla MemPalace or another local install.

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
test -n "${PALACE_PATH:-}"
case "$PALACE_PATH" in
  /*) ;;
  "~/"*) PALACE_PATH="$HOME/${PALACE_PATH#\~/}" ;;
  *) echo "PALACE_PATH must be absolute" >&2; exit 2 ;;
esac
export MEMPALACE_PALACE_PATH="$PALACE_PATH"
```
To make it permanent, update `~/.mempalace/config.json` atomically. Pass the custom path as
an argument; never interpolate it into Python or shell source:
```bash
mkdir -p ~/.mempalace
python3 - "$PALACE_PATH" <<'PY'
import json
import os
import pathlib
import tempfile
import sys

palace_path = sys.argv[1]
cfg = pathlib.Path.home() / ".mempalace" / "config.json"
data = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
data["palace_path"] = palace_path
payload = (json.dumps(data, indent=2) + "\n").encode()
fd, name = tempfile.mkstemp(prefix=f".{cfg.name}.", dir=cfg.parent)
tmp = pathlib.Path(name)
try:
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, cfg)
    dir_fd = os.open(cfg.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
finally:
    tmp.unlink(missing_ok=True)
print("palace_path written")
PY
```

**Pass →** Output is `palace_path written`. Continue to Step 4b.

**Fail →** The previous config remains in place. Exact session-only recovery:
`export MEMPALACE_PALACE_PATH="$PALACE_PATH"`. Fix the reported permission or JSON error before
rerunning the same bounded persistence block once.

**Default path case:** No action needed — `mempalace-code init` will create `~/.mempalace/palace` automatically.

---

### Step 4b: Initialize a project directory

**Condition:** `MINE_PATH != skip`

Run:
```bash
"$MEMPALACE_BIN" init "<MINE_PATH>" --skip-model-download
```

Every init uses `--skip-model-download`, including the affirmative model branch. This makes
declined and offline setup network-safe and retry order independent. `mempalace-code init` is
otherwise non-interactive by default — it detects rooms from the folder structure
and writes `mempalace.yaml` without prompting. The `--yes` flag is accepted for backward
compatibility with existing scripts but is no longer required.
Heuristic people/project entity detection is opt-in; add `--detect-entities` only when the
human explicitly wants entity detection during initialization.

`--detect-entities` is intended for prose-heavy folders (meeting notes, client notes,
personal notes, conversation exports), not ordinary code repos. It samples up to 10
readable files, prefers prose extensions (`.md`, `.txt`, `.rst`, `.csv`), reads the first
5 KB of each sampled file, and looks for heuristic people/project signals. If candidates
are confirmed, init writes `<MINE_PATH>/entities.json` with:

```json
{"people": ["Alice"], "projects": ["Apollo"]}
```

For unattended setup, use `--detect-entities` only after the human accepts the
tradeoff: detected people/projects are auto-accepted and uncertain candidates are skipped.
Do not add the flag just because a directory is a source repo; code symbols are handled by
`mempalace-code mine`, and broad entity scans over code create false positives.

**Pass →** Exit code 0. Config and room setup complete. Continue to Step 4c.

**Fail →** Non-zero exit. Common causes: directory does not exist, permissions error. **ASK HUMAN:** "Could not initialize `<MINE_PATH>`. Error: `<paste stderr>`. Please confirm the path exists and is readable, then reply `retry` with a corrected path, or `skip`."
- `retry <path>` → Re-run with the corrected path.
- `skip` → Set `MINE_PATH=skip`. Continue to Step 4c.

---

### Step 4c: Cache or verify embedding model

**Condition:** `DOWNLOAD_MODEL=yes`

Run:
```bash
"$MEMPALACE_BIN" fetch-model
```

`fetch-model` is idempotent — if the model is already cached it verifies local-only model resolution from disk (no network call). Expected output ends with `Done — embedding model is ready for offline use.`

The canonical cache authority is
`$HF_HOME/mempalace-fastembed/all-MiniLM-L6-v2-v1/.mempalace-model.json`.
For an explicit custom model or local SentenceTransformer path, ask for authority before
running `python -m pip install 'mempalace-code[custom-models]'`; only that path may execute
trusted remote model code.

Exit code 0 = success. Set `MODEL_READY=true`. Continue to Step 4d.

**Fail →** Retry once with `"$MEMPALACE_BIN" fetch-model`. If it still fails, **ASK HUMAN:**
"Model cache/verify failed. Reply `retry` to run the same resolved launcher once more, or
`continue` to skip model-dependent mining and search."

**Condition:** `DOWNLOAD_MODEL=no` → Set `MODEL_READY=false`. Print exactly one later recovery
command: `"$MEMPALACE_BIN" fetch-model`. Do not run it during init, verification, or MCP setup.

---

### Step 4d: Mine the project (if applicable)

**Condition:** `MINE_PATH != skip` and `MODEL_READY=true`

```bash
"$MEMPALACE_BIN" mine "<MINE_PATH>" --mode "<MINE_MODE>"
```

**Pass →** Exit code 0. Output ends with a filed-drawer count. Continue to Section 5.

**Fail →** Mine failed. **ASK HUMAN:** "Mining `<MINE_PATH>` failed. Error: `<paste stderr>`. Reply `retry` or `skip`."

**Condition:** `MODEL_READY=false` → Skip mining. Print the single recovery command from Step 4c;
after it succeeds, retry this step with the same `"$MEMPALACE_BIN"` launcher.

---

## Section 5 — MCP Wiring

Wire the mempalace-code MCP server so your AI assistant can call it during conversations.
Use `mempalace-code` as the MCP server registration name. The exposed MCP tool
identifiers stay `mempalace_*` for compatibility with existing agents and usage rules.

Compatible Agent Plugins 1.0 clients should use Step 5.0 first. Direct Claude or Codex
registration uses the already-resolved installed `$MEMPALACE_MCP` launcher. Pass it and every
profile/path as a separate quoted argv value. Never interpolate paths into Python, JSON, TOML,
or shell source.

**Compatibility note:** source checkouts also provide `python -m mempalace.mcp_server`
when the checkout is on `PYTHONPATH`, so older repo-local Codex/Autopilot MCP
configs keep working. New installed-package registrations use `mempalace-code-mcp`.

**Protocol note:** both entrypoints negotiate the protocol per request — a
modern client calling `server/discover` gets the stable **2026-07-28**
revision, while a legacy client calling `initialize` gets the same handshake
it always has. Existing operator registrations for either entrypoint do not
need to change to pick this up.

**Fail →** If `$MEMPALACE_MCP` is missing, return to Step 3.4 and repair the selected install
owner. Do not switch owners or use ambient Python.

---

### Step 5.0: Portable Agent Plugin Path

**Condition:** The target client supports Agent Plugins 1.0 package loading.

**Check:**
```bash
"$MEMPALACE_BIN" agent-plugin path --json
```

**Pass →** Read the JSON `path` field and give that directory to the compatible client. It
contains `plugin.json`, `mcp.json`, `skills/mempalace/SKILL.md`, and vendored
schemas. Its `mcp.json` declares stdio transport with the installed
`mempalace-code-mcp --profile=minimal` launcher, so the portable default exposes
only `mempalace_status`, `mempalace_search`, `mempalace_check_duplicate`, and
`mempalace_add_drawer`.

If the human selected `minimal` in Q6 and the client accepts the Agent Plugin
directory, set MCP wiring complete and continue to Section 6.

If the human selected `kg`, `code`, `notes`, or `full`, use Step 5.1 or Step 5.2
for direct MCP registration with `--profile=kg`, `--profile=code`,
`--profile=notes`, or `--profile=full`. A client may also load a copied plugin
directory with edited `mcp.json` args, but do not modify the installed package.

**Fail →** Use direct MCP registration below. Report the `agent-plugin path --json`
stderr as the compatibility diagnostic; do not guess a package path.

---

### Step 5.1: Claude Code MCP Wiring

**Check — already wired?**
```bash
claude mcp list 2>/dev/null | grep -i mempalace-code
```

**Pass →** Run `claude mcp get mempalace-code` and require the selected scope, exact
`$MEMPALACE_MCP` command, and `--profile=$MCP_PROFILE` argument. Matching state is
already-current. Any mismatch stops for an explicit replace/remove decision.

**Fail →** Not wired. Proceed based on `CLAUDE_SCOPE`.

#### 5.1-A: User scope (`CLAUDE_SCOPE=user`)

Preferred (CLI):
```bash
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" "--profile=$MCP_PROFILE"
```

Exit code 0 = success. Claude user scope writes `~/.claude.json`.

**Fail (CLI unavailable or add fails) →** Stop this client branch without editing JSON. Install
or repair Claude CLI, then retry the exact `claude mcp add` command above.

#### 5.1-B: Project scope (`CLAUDE_SCOPE=project`)

Preferred (CLI):
```bash
test -d "$CLAUDE_PROJECT_PATH"
(cd "$CLAUDE_PROJECT_PATH" && claude mcp add --scope project mempalace-code -- "$MEMPALACE_MCP" "--profile=$MCP_PROFILE")
```

Exit code 0 = success. Claude project scope writes `<project>/.mcp.json`.

**Fail (CLI unavailable or add fails) →** Stop this client branch without editing `.mcp.json`.
The recovery command is the exact `claude mcp add --scope project ...` command above.

**Post-wire check:**
```bash
claude mcp list 2>/dev/null | grep -i mempalace-code
```

**Pass →** Set `CLAUDE_WIRED=true`. Continue to Step 5.2.

**Fail →** Stop this client branch and print exactly one retry command with resolved values:

```bash
# claude-mcp-exact-retry:start
case "$CLAUDE_SCOPE" in
  user)
    printf 'Retry: claude mcp add --scope user mempalace-code -- %q %q\n' \
      "$MEMPALACE_MCP" "--profile=$MCP_PROFILE"
    ;;
  project)
    printf 'Retry: (cd %q && claude mcp add --scope project mempalace-code -- %q %q)\n' \
      "$CLAUDE_PROJECT_PATH" "$MEMPALACE_MCP" "--profile=$MCP_PROFILE"
    ;;
  *) echo "invalid CLAUDE_SCOPE" >&2; exit 2 ;;
esac
# claude-mcp-exact-retry:end
```

Print only the command matching `CLAUDE_SCOPE`; the case never prints both.

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
codex mcp add mempalace-code -- "$MEMPALACE_MCP" "--profile=$MCP_PROFILE"
```

Exit code 0 = success. Set `CODEX_WIRED=true`.

`codex mcp add` writes the supported user configuration at `~/.codex/config.toml`. Codex also
supports a project-scoped `.codex/config.toml` in a trusted project; its CLI currently exposes no
persisted `--scope` flag for `mcp add`, so this runbook does not translate `CLAUDE_SCOPE` into a
Codex scope or silently hand-edit TOML. If `codex mcp` is unavailable or add fails, stop and print
exactly one retry command with resolved values:
```bash
printf 'Retry: codex mcp add mempalace-code -- %q %q\n' \
  "$MEMPALACE_MCP" "--profile=$MCP_PROFILE"
```

---

### Step 5.3: Auto-save for conversation context

Code mining is handled by the watcher (`mempalace-code watch`) and works independently of the
client. MCP-capable clients can expose the conversation-context storage tools; instruction loading
depends on Agent Plugins 1.0 support.

For MCP-capable clients:
1. Wire the MCP server (Steps 5.1/5.2) so the agent can call `mempalace_add_drawer` and `mempalace_diary_write`.
2. For an Agent Plugins 1.0 client, load the package discovered in Section 7. Other clients stop
   after MCP wiring; this runbook does not configure their instruction files.

That's it. No hooks needed.

> **Legacy: Claude Code auto-save hooks.** Claude Code also supports optional bash hooks that fire on Stop/PreCompact events and remind the AI to save at fixed intervals. They are independent of the Agent Plugin instruction-loading boundary and are documented in [`hooks/README.md`](../hooks/README.md).

---

## Section 6 — Verification

Run all checks. Each one is a pass/fail with an explicit failure action.

---

### Step 6.1: Palace integrity

```bash
"$MEMPALACE_BIN" --palace "$PALACE_PATH" health --json
```

**Pass →** Exit code 0 and JSON contains `"ok": true`. The explicit `--palace` value verifies the target selected in Section 2.

**Fail →** Exit code non-zero or JSON reports `"ok": false`. Likely causes: wrong `PALACE_PATH`,
an uninitialized palace, or a storage read error. **ASK HUMAN:** "Palace integrity check failed.
Error: `<paste stderr>`. Check `MEMPALACE_PALACE_PATH` or run
`\"$MEMPALACE_BIN\" init <project_dir> --skip-model-download`, then reply `retry` or `skip`."

`mempalace-code status` prints the full wing/room inventory and can grow with palace size. Do not use it as an automated verification step. When shell-based readiness metrics are needed, prefer `mempalace-code status --summary`, which prints only bounded drawer/wing/room-pair and storage metrics.

---

### Step 6.2: Search smoke test

**Condition:** `MODEL_READY=true`

```bash
"$MEMPALACE_BIN" --palace "$PALACE_PATH" search "test" --results 1
```

**Pass →** Exit code 0. Output contains a formatted result block with `wing`, `room`, and `similarity` fields, or an `empty palace` message (acceptable for a fresh palace). Either is a pass.

**Fail →** Exit code non-zero. Common causes: palace not initialized, embedding model not downloaded.
- If model resolution fails: run `"$MEMPALACE_BIN" fetch-model` (see Step 4c), then retry.
- Otherwise: **ASK HUMAN:** "Search smoke test failed. Error: `<paste stderr>`. Reply `retry` or `skip`."

**Condition:** `MODEL_READY=false` → Skip this model-dependent check. Print only:
`"$MEMPALACE_BIN" fetch-model`. After it succeeds, rerun this step.

---

### Step 6.3: MCP tool availability

For Claude Code:
```bash
claude mcp list 2>/dev/null | grep mempalace-code
```

**Pass →** mempalace-code appears in the list. Wiring is confirmed.

**Fail →** Print and run once the exact retry command selected in Step 5.1. If the post-check
still fails, stop with that same single command; do not suggest inspecting or editing multiple files.

---

### Step 6.4: Confirm the persisted version-notification choice

The human answered Q5 and Step 3.4 persisted it before prompt-capable commands. Do not ask
again here and do not change it implicitly.

> **Important:** Version notifications contact PyPI for package metadata only. They do **not** install packages, update dependencies, change any running service, or download anything other than the JSON metadata response.

To change this choice later:
```bash
"$MEMPALACE_BIN" version-check --enable    # opt in
"$MEMPALACE_BIN" version-check --disable   # opt out
"$MEMPALACE_BIN" version-check --status    # view current setting
```

---

### Step 6.5: Scheduled package update choice (Linux + systemd-user only)

Scheduled package updates are a **separate**, Linux-only opt-in. Run **read-only** eligibility checks first — no mutation until an explicit affirmative answer.

**Read-only preflight checks (no mutation):**

1. **OS check:**
   ```bash
   uname -s
   ```
   Output must be `Linux`. On macOS, Windows, or any other OS: print manual update commands (see below) and skip to Step 6.6. macOS and Windows are not supported for scheduled updates in this release.

2. **systemd-user check:**
   ```bash
   systemctl --user show-environment
   ```
   Exit code must be 0. If systemd-user is unavailable or the command reports a bus error: print manual update commands and skip to Step 6.6.

3. **Installer and scheduler support check:**
   ```bash
   "$MEMPALACE_BIN" update status --json
   ```
   Parse the JSON output. If `installation.supported` is not `true` (project pip, editable/source, distro-managed, or ambiguous environment): print manual update commands and skip to Step 6.6. If `scheduler.supported` is not `true`: print manual update commands and skip to Step 6.6.

**If any read-only check fails**, print manual update commands only (no prompt, no mutation):
```bash
"$MEMPALACE_BIN" update status        # read-only: installer, extras, provenance, service, timer
"$MEMPALACE_BIN" update apply --yes   # explicit package and managed-watcher transaction
```
Record `SCHEDULER_CHOICE=unsupported`. Continue to Step 6.6.

**If all read-only checks pass**, ask:

**ASK HUMAN:** "This Linux machine has a supported isolated installer and systemd-user is available. Should I set up the daily systemd-user timer implemented by this release? It runs `\"$MEMPALACE_BIN\" update apply --yes --scheduled` once per day. Reply `yes` to install the timer, or `no` (default) to skip."

**Parse response:**

- Affirmative (`yes`, `y`) → Preview units, install, then verify:
  ```bash
  "$MEMPALACE_BIN" update scheduler render
  "$MEMPALACE_BIN" update scheduler install --yes
  "$MEMPALACE_BIN" update scheduler status
  ```
  Record `SCHEDULER_CHOICE=enabled`.

- Any other reply → No action. Record `SCHEDULER_CHOICE=disabled`. Manual update commands remain available:
  ```bash
  "$MEMPALACE_BIN" update status        # read-only: installer, extras, provenance, service, timer
  "$MEMPALACE_BIN" update apply --yes   # explicit package and managed-watcher transaction
  ```

To change the scheduler later:
```bash
"$MEMPALACE_BIN" update scheduler install --yes   # enable daily timer
"$MEMPALACE_BIN" update scheduler remove --yes    # disable
"$MEMPALACE_BIN" update scheduler status          # view state
```

---

### Step 6.6: Final state report

Print a summary of the completed install. This records exactly what was configured and provides the commands to change any choice later.

```
Installed version:   <MEMPALACE_VERSION>
Installer:           <existing|uv|pipx|project|bootstrap>
Notification checks: <enabled|disabled>   (change: mempalace-code version-check --enable/--disable)
Updater installer:   <kind> (supported: <true|false>)
Scheduler support:   <true|false>
Scheduler enabled:   <true|false> (default: false; choice: <enabled|disabled|unsupported>)
                     (install: mempalace-code update scheduler install --yes)
```

To inspect current state at any time:
```bash
"$MEMPALACE_BIN" version-check --status      # notification choice and last check time
"$MEMPALACE_BIN" update status               # installer, extras, provenance, watcher, scheduler
"$MEMPALACE_BIN" update status --json        # machine-readable version of the above
```

---

## Section 7 — Agent Instruction Loading (Agent Plugin Only)

After successful installation and verification, configure instruction loading only through the
existing Agent Plugins 1.0 package boundary.

### Step 7.1: Discover the installed package

**Condition:** The target client supports Agent Plugins 1.0 package loading.

**Check (read-only):**
```bash
"$MEMPALACE_BIN" agent-plugin path --json
```

**Pass →** Read the JSON `path` field, give that directory to the compatible client, and load it as an
Agent Plugin. Its bundled `skills/mempalace/SKILL.md` is the supported instruction source for
the portable `minimal` profile. Instruction files stay unchanged.

**Fail or unsupported client →** Stop instruction setup. Default or skipped setup, legacy or
malformed content, a missing or wrong target, a symlinked target or parent, a duplicate retry,
and partial prior execution all have the same result: no instruction-file operation.

Print exactly one recovery command:

```bash
mempalace-code agent-plugin path --json
```

Run package discovery again only after Agent Plugins 1.0 support is available. Repeated discovery
is read-only and does not create an instruction-loading fallback.

## End State

A successful install produces:

| Item | Expected state |
|------|---------------|
| `"$MEMPALACE_BIN" version-check --status` | Prints installed version and notification state |
| `test -x "$MEMPALACE_MCP"` | Confirms the sibling installed MCP launcher |
| `"$MEMPALACE_BIN" --palace "$PALACE_PATH" health --json` | Exit 0, JSON contains `"ok": true` |
| `"$MEMPALACE_BIN" --palace "$PALACE_PATH" search "test" --results 1` | Required only when `MODEL_READY=true` |
| `claude mcp list \| grep mempalace-code` | Shows entry (if Claude Code target) |
| `~/.codex/config.toml` contains `mcp_servers.mempalace-code` | Present (if Codex target) |

### Version Check (opt-in)

The installer does **not** enable periodic version checks. Users may opt in interactively
(the CLI will prompt once on the first interactive command) or explicitly:

```bash
mempalace-code version-check --enable   # opt in
mempalace-code version-check --disable  # opt out (suppress future prompts)
mempalace-code version-check --status   # show current status (local-only)
mempalace-code version-check --check-now  # fetch now when the env kill switch permits it
```

For automated installs, CI pipelines, and non-interactive agents:
- The first-run prompt is suppressed automatically when stdin/stdout/stderr are not TTYs.
- To permanently disable prompts and checks: `mempalace-code version-check --disable` or set
  `MEMPALACE_VERSION_CHECK=0` in the environment.
- `MEMPALACE_VERSION_CHECK=0` and invalid values block every version-check network call, including
  explicit `--check-now`. Run `unset MEMPALACE_VERSION_CHECK` (or set it to `1`) before retrying.
- Without that process override, `--check-now` bypasses the interval and persisted preference.

### Opt-in package updates (supported Linux installs)

Version checks only report metadata. Package updates use the separate explicit command surface:

```bash
mempalace-code update status
mempalace-code update check
mempalace-code update apply --yes
```

`status` and `check` do not install packages, stop services, enable a timer, or replace update
state. They report canonical PyPI provenance, the stable compatible-major candidate, detected
installer, retained extras, watcher state, and next systemd-user run. `apply --yes` is required for
mutation. The supported install boundary is `uv tool`, `pipx`, or the bootstrap
`~/.mempalace/venv`; system Python, distro-managed, editable/source, and ambiguous environments
remain visible refusals.

The updater selects either the legacy `mempalace-watch.service` or one active named
`mempalace-watch-<root>.service` with a supported MemPalace `watch` ExecStart. Ambiguous, malformed,
unrelated, or unavailable systemd-user discovery refuses the update before package, lease, or service
mutation. For a selected active watcher, the updater acquires the exclusive operation lease, retains
detected extras, validates the new console and palace, then restarts that same unit. Every
post-preflight failure rolls back through the same installer and records the failed stage plus a
bounded log in `~/.mempalace/updates/logs/`. A watcher requires the retained `watch` extra; missing
required extras fail before service or package mutation.

Automatic checks are disabled by default. The update timer remains disabled until
`mempalace-code update scheduler install --yes` completes.
The scheduler is disabled until install runs. Linux operators using systemd-user may inspect then
opt in:

```bash
mempalace-code update scheduler render
mempalace-code update scheduler install --yes
mempalace-code update scheduler status
```

The scheduler uses a guarded systemd-user service and timer. It has no machine-wide, cron, launchd,
or Windows equivalent in this release. Use `mempalace-code update status` and the log path returned
by an update attempt to diagnose a refusal or rollback; do not retry through a system package manager.

---

## Reference

| Topic | Source |
|-------|--------|
| Palace path config | `MempalaceConfig.palace_path` in `mempalace_code/config.py` — env → config.json → default |
| All CLI flags | `mempalace-code --help` / `mempalace-code <cmd> --help` |
| MCP tool list and profiles | `README.md` → MCP Server section and MCP Tool Profiles table |
| Auto-save hooks | `hooks/README.md` |
| Airgapped / offline setup | `docs/OFFLINE_USAGE.md` |
| Manual MCP setup examples | `examples/mcp_setup.md` |

---

## Troubleshooting

### Search returns empty or counts don't match

```bash
"$MEMPALACE_BIN" --palace "$PALACE_PATH" health
```

If `ok: false` or errors reported:

```bash
"$MEMPALACE_BIN" --palace "$PALACE_PATH" repair --rollback --dry-run
"$MEMPALACE_BIN" --palace "$PALACE_PATH" repair --rollback
```

### MCP tools return empty wings/rooms

Same as above — likely fragment corruption. Run
`"$MEMPALACE_BIN" --palace "$PALACE_PATH" health`.

### "Table unreadable" or LanceDB errors

Storage corruption. Use `"$MEMPALACE_BIN" --palace "$PALACE_PATH" repair --rollback`. Data added after corruption point is lost. This is why auto-backup exists (`~/.mempalace/backups/pre_optimize_*.tar.gz`). Pre-optimize archives are bounded by default (newest 5 kept); scheduled archives are bounded by default (newest 14 kept); set `MEMPALACE_BACKUP_RETAIN_COUNT=0` to keep all kinds unbounded. Successful optimize runs also perform best-effort verified stale-version cleanup; use `"$MEMPALACE_BIN" cleanup` manually for older accumulations or emergency disk recovery after stopping writers.

### Re-mine doesn't fix the issue

Manual drawers are not regenerated by mining. Check if you have a backup:

```bash
"$MEMPALACE_BIN" backup list
"$MEMPALACE_BIN" restore <backup.tar.gz>
```

### Stale installed metadata vs. imported module

Symptom: `python3 -c "import mempalace_code; print(mempalace_code.__version__)"`
and `mempalace-code version-check --status` print different versions, or one
of them lags behind the version you expect. This means the installed tool
environment (pipx, `uv tool`, or a venv) is stale — a partial or interrupted
install left package metadata, the imported module, and the console script
out of sync.

`scripts/release_install_metadata_smoke.py` in this repo checks exactly this:
it proves `importlib.metadata.version("mempalace-code")`,
`mempalace_code.__version__`, and `mempalace-code version-check --status` all
agree before a release ships. It also creates the optional alias through a
temporary symlinked launcher under a conflicting `PATH`, then proves the alias
targets that launcher and reports the same version. Check the three version
surfaces locally when troubleshooting an operator install; use
`command -v mempalace` to inspect an existing alias. Remove or rename it only
after confirming that it is stale and owned by this install, then rerun
`"$MEMPALACE_BIN" install-alias`.

Reinstall with the tool that manages the install, using the exact pinned
version if known:

```bash
# pip / venv install
python -m pip install --upgrade --force-reinstall mempalace-code

# pipx install
pipx reinstall mempalace-code

# uv tool install
uv tool install --force mempalace-code
```

After reinstalling, re-run Step 3.4's post-install verification and
`"$MEMPALACE_BIN" version-check --status` and confirm both report the same
version.

---

## Validation Log

Keep run-specific evidence outside this public runbook. Record the current
validation contour with this format:

```
Executor:   <local operator | CI job>
Revision:   <40-hex candidate SHA>
Contour:    <clean VM | CI container | disposable local install>
Deviations: <list any step where agent deviated from script, or "none">
Questions outside script: <list any, or "none">
Result:     <pass | fail>
```
