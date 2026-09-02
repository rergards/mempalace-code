<div align="center">

<img src="assets/mempalace_banner.jpg" alt="mempalace-code" width="640">

# mempalace-code

### Your AI's long-term memory. Local. Instant. Private.

Index your codebase once. Your AI can recall architecture decisions, debugging sessions, and API patterns across sessions and projects without re-reading the repo.

No cloud service, no API keys, no subscription. After the one-time embedding model download, indexing and search stay on your machine.

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]

<br>

[**Get Started in 30 seconds**](#quick-start) · [How It Works](#the-palace) · [All Features](#features) · [Benchmarks](#benchmarks)

<br>

<table>
<tr>
<td align="center"><strong>Language-Aware Mining</strong><br><sub>AST, regex, and adaptive chunking<br>matched to each file type</sub></td>
<td align="center"><strong>29 MCP Tools</strong><br><sub>Any MCP-capable agent<br>search, store, traverse · static profiles</sub></td>
<td align="center"><strong>Temporal Knowledge Graph</strong><br><sub>Facts that change over time<br>with validity windows</sub></td>
</tr>
<tr>
<td align="center"><strong>33.8x Token Savings</strong><br><sub>measured peak · median 14.5x<br><a href="docs/BENCH_TOKEN_DELTA.md">scales with project size</a></sub></td>
<td align="center"><strong>Cross-Project Tunnels</strong><br><sub>Search <code>auth</code> in one project<br>find it everywhere</sub></td>
<td align="center"><strong>3,000+ Tests · $0 Cost</strong><br><sub>Local test suite<br>offline after model setup</sub></td>
</tr>
</table>

</div>

---

## Quick Start

```bash
uv tool install mempalace-code        # recommended isolated install
# or
pipx install mempalace-code           # alternative
# or
pip install mempalace-code            # into current environment
# or
uvx --from mempalace-code mempalace-code --help  # try without installing
```

`mempalace-code` is the default command name so this fork can coexist with
upstream/vanilla `mempalace` on the same machine. If `mempalace` is unused on
your PATH and you want the shorter alias, run `mempalace-code install-alias`.
Packaged installs use the Python import package `mempalace_code`, so they can
coexist with vanilla MemPalace in the same Python environment. Source checkouts
keep a small `mempalace.mcp_server` shim only so older repo-local MCP configs
that run with `PYTHONPATH=/path/to/mempalace-code` continue to start.

Use [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) for a human-in-the-loop setup sequence. It covers installation, MCP wiring, supported Agent Plugin discovery, the unsupported-client stop boundary, and verification, and asks before choosing install scope, storage path, or model download.

Compatible [Agent Plugins 1.0](https://agent-plugins.org/) clients can load the
installed portable package. Discover it with:

```bash
mempalace-code agent-plugin path --json
```

Read the JSON `path` field and use that directory. It contains `plugin.json`, `mcp.json`, and
`skills/mempalace/SKILL.md`. Its MCP config runs the installed
`mempalace-code-mcp --profile=minimal` launcher, exposing only
`mempalace_status`, `mempalace_search`, `mempalace_check_duplicate`, and
`mempalace_add_drawer` by default. Use direct MCP registration, or edit a copy
of `mcp.json`, when a client needs richer profiles such as `--profile=kg`,
`--profile=code`, `--profile=notes`, or `--profile=full`.

<details>
<summary>Or do it manually</summary>

```bash
MEMPALACE_BIN="$(command -v mempalace-code)"
MEMPALACE_MCP="$(dirname "$MEMPALACE_BIN")/mempalace-code-mcp"
"$MEMPALACE_BIN" init ~/projects/myapp --skip-model-download
# After explicit consent to download/cache the ~80 MB embedding model:
"$MEMPALACE_BIN" fetch-model
"$MEMPALACE_BIN" mine ~/projects/myapp
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"  # Claude user scope
codex mcp add mempalace-code -- "$MEMPALACE_MCP"                # Codex user config
```

**Optional: auto-sync on commit** (requires `[watch]` extra — see [Auto-Watch](#auto-watch)):
```bash
"$MEMPALACE_BIN" watch ~/projects/         # re-mines on every commit, zero noise
```

This registers all 29 tools with the configured MCP client. To expose a reduced subset, add a
`--profile` argv value (for example, `-- "$MEMPALACE_MCP" --profile=minimal`). Compatible Agent
Plugins 1.0 clients should discover the supported instruction bundle with
`mempalace-code agent-plugin path --json` and follow
[`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) Section 7. For other clients,
[`docs/LLM_USAGE_RULES.md`](docs/LLM_USAGE_RULES.md) is read-only reference material;
instruction-file mutation is unsupported.

</details>

### Do you need it? Ask your LLM:

```
Read:
- https://github.com/rergards/mempalace-code/blob/main/README.md
- https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md
- https://github.com/rergards/mempalace-code/blob/main/docs/LLM_USAGE_RULES.md

Evaluate mempalace-code for this repo specifically, not generic memory tooling.

1. Current context burn: what do I re-explain, and how many tokens/week are spent re-reading files?
2. Highest-ROI surfaces: rank code, docs/prose, design notes, conversation/log exports, manual decisions, KG facts, architecture relationships.
3. Stack support: list supported languages/file types actually indexed; name unsupported extensions that are skipped by default. Distinguish tree-sitter AST, regex structural, Markdown/prose, Kubernetes YAML, and adaptive chunking.
4. Agent workflow fit: which MCP tools should you use proactively (`mempalace_search`, `mempalace_code_search`, `mempalace_file_context`, KG, tunnels, diary, manual drawers)?
5. Ops fit: recommend global MCP, project-scoped MCP, or no MCP; cover 29-tool prompt surface and profile subsetting options (`--profile`, `--tools`, `--exclude`), `mine` vs `mine-all`, `watch` cadence, backup/repair, and offline/model constraints.
6. Decision: install now, try scoped for a week, wait for a named feature, or skip. Give the first 3 commands you would run.
7. If waiting: ask me whether to draft a GitHub feature request.
```

For repos that already have a hand-curated memory file, evaluate mempalace-code
as a complement, not a replacement. A good trial order is:
1. **KG first** — move volatile current facts (active branch, phase, owner, deadline,
   status) into temporal triples; keep curated prose for reasoning and narrative.
2. **Drawers + docs second** — mine design docs, specs, long decision notes, and
   conversation/log exports where semantic retrieval beats manual grep.
3. **Code mining last** — start with one high-value subproject, then expand if
   agents actually use the results.

Cost caveat: a direct MCP registration without selectors defaults to all 29 tools;
the portable Agent Plugin defaults to the four-tool `minimal` profile. Use
`--profile=minimal` or `--tools=search,add_drawer` with direct registration to
reduce the prompt/tool-surface cost.
For proactive use, compatible Agent Plugins 1.0 clients load the package discovered by
`mempalace-code agent-plugin path --json` as described in
[`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) Section 7. Other clients may use
[`docs/LLM_USAGE_RULES.md`](docs/LLM_USAGE_RULES.md) as read-only reference material;
instruction-file mutation is unsupported.
Prefer project-scoped MCP for trials, and keep it only if searches, KG lookups,
or drawer writes show up in real sessions.

### Supported MCP Clients

mempalace-code works with any [MCP](https://modelcontextprotocol.io/)-compatible client:

- **Claude Code** — `claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"`
- **Codex CLI** — `codex mcp add mempalace-code -- "$MEMPALACE_MCP"`
- **Agent Plugins 1.0 clients** — parse the JSON `path` field from `mempalace-code agent-plugin path --json` and load that directory
- **Claude Desktop** — add to `claude_desktop_config.json`
- **Cursor** — add as MCP server in settings
- **Windsurf** — add as MCP server in settings
- **Any MCP client** — point it at the resolved installed `mempalace-code-mcp` launcher

For local models without MCP support (Llama, Mistral, etc.), use `mempalace-code wake-up` to pipe context into the system prompt — see [Memory Layers](#memory-layers).

---

## How It Actually Works

You write code. You make decisions. You debug things. Between sessions, all that context vanishes.

mempalace-code **indexes it once** into a local vector store, then an MCP-capable AI can retrieve it in milliseconds — using [33.8x fewer tokens](docs/BENCH_TOKEN_DELTA.md) than grep + read at measured peak (median 14.5x on the canonical fixture). Think of it as `git log` for everything that *isn't* in the code: the *why*, the discussions, the dead ends, the decisions.

**What gets indexed or stored:**
- Code files — structural chunks for Python, TypeScript/JS/TSX/JSX, Go, Rust, Java, Kotlin, C#, F#, VB.NET, XAML, Swift, PHP, Scala, Dart, Lua, Ruby, Terraform/HCL, Markdown, Kubernetes manifests, Helm charts/templates, and Ansible playbooks/roles/inventory; adaptive chunks for C/C++, shell, SQL, HTML/CSS, JSON/YAML/TOML, CSV, Dockerfile, Make, templates, and config files
- .NET solutions — `.sln`/`.csproj` project graphs, cross-project symbol relationships, interface implementations
- Architecture facts — pattern, layer, namespace, and project membership facts for .NET and Python projects
- Conversation/log exports — Claude Code JSONL, OpenAI Codex CLI JSONL, Gemini CLI JSONL, Claude.ai JSON, ChatGPT `conversations.json`, Slack JSON, plain text transcripts
- MCP-saved context — manual drawers are vector-indexed; diary entries and temporal KG facts are stored in their own retrieval surfaces
- Architecture notes, decisions, anything else you store manually

Generated helper files such as `entities.json` are skipped during project
mining by default, because they are created by init/entity detection and should
not become source-code drawers unless explicitly force-included.

**How you use it:** An MCP-capable agent can call mempalace tools during a session when its client policy permits the calls. Compatible Agent Plugins 1.0 clients load the supported instruction bundle discovered by `mempalace-code agent-plugin path --json`; see [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) Section 7. Other clients treat [`docs/LLM_USAGE_RULES.md`](docs/LLM_USAGE_RULES.md) as read-only reference material because instruction-file mutation is unsupported. The CLI remains available for direct use.

---

## Features

### Language-Aware Code Mining

`mempalace-code mine` walks your source tree and chooses the best chunker for each file type: AST boundaries where optional tree-sitter grammars are available, regex structural boundaries for supported languages, YAML-aware Kubernetes/Helm/Ansible resource splits, Markdown/prose sections, or adaptive line-count chunks for formats without reliable declarations. The shared catalog currently exposes **45 searchable language labels** to `code_search(language=...)`. Leading comments and docstrings stay attached to declarations where structural chunking is active; Markdown drawers keep heading path, section type, and Mermaid/code/table flags in search metadata.

| Language | Strategy | AST Support |
|----------|----------|:-----------:|
| Python | Functions, classes, methods, decorators | Optional tree-sitter |
| TypeScript / JavaScript / TSX / JSX | Functions, classes, exports, imports | Optional tree-sitter |
| Go | Functions, types, methods, interfaces | Optional tree-sitter |
| Rust | Functions, structs, enums, traits, impls | Optional tree-sitter |
| Java | Classes, interfaces, methods, annotations | Regex |
| Kotlin | Classes, objects, functions, extensions | Regex |
| Scala | Classes, case classes, objects, traits, enums, functions, implicits, type aliases, generics | Regex |
| Swift | Classes, structs, enums, protocols, functions, properties, extensions, actors, async/await | Regex |
| Dart | Classes, mixins, extensions, enums, functions, named/factory constructors, async/await | Regex |
| PHP | Classes, interfaces, traits, enums (8.1+), functions, methods, namespaces (Laravel/WP/Symfony aware) | Regex |
| C# | Classes, interfaces, records, methods, properties | Regex |
| F# / VB.NET | Modules, types, functions | Regex |
| XAML | Controls, resources, code-behind linking | Regex |
| Terraform / HCL | Terraform/HCL top-level blocks (`resource`, `module`, `variable`, `moved`, `import`, `check`, etc.) | Regex |
| Kubernetes manifests | Deployments, Services, ConfigMaps, Secrets, Ingresses, CRDs (indexed by kind/name) | YAML-aware |
| Helm charts | `Chart.yaml`, `values*.yaml`, raw templates with kind/name metadata; no template rendering | YAML/Go-template aware |
| Ansible | Playbooks, role tasks/handlers/defaults/vars, inventories; no Jinja evaluation or inventory semantics | YAML/Jinja tolerant |
| Markdown / plain text | Heading sections (`#`-`######`), heading paths, section metadata, paragraphs | — |
| Lua | Functions, local functions, methods (dot/colon), module/table declarations | Regex |
| C / C++ | Indexed and searchable with best-effort symbol metadata; chunked adaptively today | — |
| Ruby | Static classes, modules, methods, singleton methods, attrs, and constants; Rails DSL/metaprogramming not interpreted | Regex |
| shell / SQL | Indexed and searchable; chunked adaptively today | — |
| HTML / CSS / CSV | Indexed and searchable; chunked adaptively today | — |
| YAML / JSON / TOML | Adaptive line-count; Kubernetes YAML auto-detected separately | — |
| Dockerfile / Make / templates / config | Dockerfile, Containerfile, Makefile, GNUmakefile, Vagrantfile, Go templates, Jinja2, `.conf`, `.cfg`, `.ini` | — |

The `mempalace_code_search` language filter is generated from the same language
catalog as the miner. If a file type is mined with a language label, the MCP
schema and unsupported-language hints stay aligned with that catalog.

Tree-sitter is optional (`pip install "mempalace-code[treesitter]"`). When a grammar is missing, Python, TypeScript/JavaScript/TSX/JSX, Go, and Rust fall back to regex structural chunking. Other recognized formats use their regex, YAML-aware, prose, or adaptive chunker as listed above.

Extensions outside the miner catalog are skipped by normal project scans unless
you explicitly force-include an exact path with `--include-ignored path/to/file`.

Mining indexes only ordinary readable regular files. Source-shaped FIFO, socket,
character device, block device, symlink, and directory entries are rejected or skipped
before their source content is opened. An ordinary regular file that cannot be read is
reported as a read error; it is not necessarily reported as
`<path>: not a regular file (<kind>)`. Mining continues with other ordinary readable
regular files, and its diagnostics are bounded and actionable. After replacing or
removing the offending entry, run `mempalace-code mine <dir> --full`.

```bash
mempalace-code mine ~/projects/myapp                  # all supported file types
mempalace-code mine ~/projects/myapp --wing myapp     # tag with a specific wing
mempalace-code mine ~/chats/ --mode convos            # mine conversation exports
mempalace-code mine-all ~/projects/                   # sync all projects incrementally (one wing per project)
mempalace-code mine-all ~/projects/ --new-only        # skip projects whose wing already exists (first-run only)
```

Mining is **incremental** by default — content-hash based, only changed files are re-chunked. Use `--full` to force a rebuild.

**Multi-project wing naming** — `mine-all` assigns one wing per project using this priority:
1. `wing:` in the project's `mempalace.yaml` (explicit override)
2. Git origin repo name (e.g. `my-repo.git` → `my_repo`)
3. Normalized folder name

If two projects resolve to the same wing name, `mine-all` exits with an error before mining anything. Fix this by adding a unique `wing:` value to each project's `mempalace.yaml`. Use `--new-only` to skip projects already present in the palace (useful for first-run batch ingestion).

### Optional Entity Detection

`mempalace-code init <dir>` is config-first by default: it detects rooms from the directory
structure and does not scan file contents for names. Add `--detect-entities` only when
the directory contains prose where people or project names matter, such as meeting notes,
client notes, personal notes, or conversation exports:

```bash
mempalace-code init ~/notes --detect-entities        # prompts to confirm detected people/projects
mempalace-code init ~/notes --detect-entities --yes  # auto-accept entity confirmation (no room prompts)
```

The detector is a lightweight bootstrap step, not the main miner. It samples up to 10
readable files, prefers prose files (`.md`, `.txt`, `.rst`, `.csv`), reads the first 5 KB
of each sampled file, and looks for heuristic signals such as `Alice said`, `thanks Bob`,
`Apollo repo`, `deploy Apollo`, or `import Apollo`. Confirmed results are written to
`<dir>/entities.json`:

```json
{
  "people": ["Alice", "Bob"],
  "projects": ["Apollo"]
}
```

Use it for human/project context. Leave it off for normal code repos unless their docs
contain the entities you want captured. Full-repo scanning would be slower and noisier:
class names, packages, examples, and variables often look like people or products to a
heuristic pass. Code structure, symbols, languages, and architecture relationships are
handled by `mempalace-code mine`, not by entity detection.

### Auto-Watch

Keep your palace in sync automatically. By default, watches `.git/refs/heads/` and re-mines only on **commit** — no noise from work-in-progress saves. Handles multiple branches and worktrees.

Requires the `watch` extra:
```bash
uv tool install "mempalace-code[watch]"   # or: pipx install "mempalace-code[watch]"
```

Already installed without it? Add watchfiles:
```bash
uv tool inject mempalace-code watchfiles  # or: pipx inject mempalace-code watchfiles
```

```bash
mempalace-code watch ~/projects/my-app                # watch an initialized project (on commit)
mempalace-code watch ~/projects/                      # watch all initialized projects in a parent directory
mempalace-code watch ~/projects/ --on-save            # watch all file saves instead (noisier)
mempalace-code watch ~/projects/ schedule             # print launchd/cron snippet for daemon
```

`watch` accepts either an **initialized project directory** (has `mempalace.yaml`) or a **parent directory** containing immediate initialized project subdirectories. Pointing it at a project root that has project files but no `mempalace.yaml` exits with the correct `mempalace-code init <dir>` command.

Startup resolves and validates each watcher source root as a directory before creating a
pre-watch backup. Nested non-regular or unreadable source entries follow the mining
contract above: other ordinary readable regular files continue through the mine, and
such an entry does not by itself abort or restart the watcher. A watcher run also reuses
one warmed store and embedding-model lifecycle across remine cycles; regression tests
bound post-warm-up RSS, file descriptors, archive retention, disk growth, and SIGINT
shutdown.

**Install as persistent daemon (macOS):**

```bash
mempalace-code watch ~/projects/ schedule > ~/Library/LaunchAgents/com.mempalace.watch.plist
launchctl load ~/Library/LaunchAgents/com.mempalace.watch.plist
```

Starts at login, restarts if crashed. Logs to `/tmp/mempalace-watch.log`.

**Disk-budget guard:** the daemon automatically skips mine/optimize cycles when free disk space falls below the configured floor (default **1 GiB**). Use `watch status` to check the current state:

```bash
mempalace-code watch ~/projects/ status      # print disk-budget summary + launchd state
```

To pause or stop the daemon when disk is low:

```bash
launchctl unload ~/Library/LaunchAgents/com.mempalace.watch.plist   # stop until next login
launchctl load   ~/Library/LaunchAgents/com.mempalace.watch.plist   # re-enable after freeing space
```

**Diagnosing and stopping a crash-looping job:**

If the daemon was pointed at an uninitialized directory it will crash-loop under `KeepAlive`. Confirm with:

```bash
mempalace-code watch ~/projects/ status   # shows state, runs count, and last exit code
```

Stop and optionally remove it:

```bash
# macOS 10.11+ preferred — unregisters the job immediately:
launchctl bootout gui/$(id -u)/com.mempalace.watch

# Older macOS / alternative:
launchctl unload ~/Library/LaunchAgents/com.mempalace.watch.plist

# Remove permanently (re-install after fixing the watch root):
rm ~/Library/LaunchAgents/com.mempalace.watch.plist
```

**Daemon health check:**

The daemon emits `WATCH_RUN` lines at each startup transition so the appended log at `/tmp/mempalace-watch.log` can be searched to confirm the latest startup reached the watch loop. Use this sequence to diagnose daemon state:

```bash
# 1. Process state — is the daemon running?
launchctl print gui/$(id -u)/com.mempalace.watch
# Or use the watch status shortcut:
mempalace-code watch ~/projects/ status

# 2. Palace storage health
mempalace-code --palace ~/.mempalace/palace health

# 3. Find the latest startup that reached watch-ready
grep -a 'state=watch-ready' /tmp/mempalace-watch.log | tail -1
# Example output: WATCH_RUN run_id=20260616T120102Z-p12345 state=watch-ready

# 4. Filter that run's context (replace the run_id from step 3):
grep -a 'run_id=20260616T120102Z-p12345' /tmp/mempalace-watch.log
```

A log file may contain `WATCH_RUN` lines from older runs that exited with disk-budget or backup failures. The `run_id` on the latest `state=watch-ready` line identifies the current healthy startup — lines from prior runs with different `run_id` values are stale and can be ignored. If no `watch-ready` line appears, check the most recent `run-started` line and the state that followed it (for example `state=pre-watch-backup-failed` or `state=initial-mine-skipped reason=disk-budget`).

Configure the threshold via environment variable or `~/.mempalace/config.json`:

```bash
# Environment variable (bytes or human suffix)
export MEMPALACE_WATCH_DISK_MIN_FREE_BYTES=2GiB    # watcher-specific floor
export MEMPALACE_DISK_MIN_FREE_BYTES=1GiB          # global floor (watcher + backup)

# ~/.mempalace/config.json
{
  "disk_min_free_bytes": 1073741824,         // 1 GiB global default
  "watch_disk_min_free_bytes": 2147483648,   // 2 GiB for watcher specifically
  "backup_disk_min_free_bytes": 2147483648   // 2 GiB for backups specifically
}
```

MCP read/search behavior is **not affected** by a paused watcher — agents can still search the palace while the daemon waits for disk space.

---

### The Palace

mempalace-code organizes memories into a navigable structure — the same mental model ancient Greek orators used to memorize speeches.

```
  ┌─────────────────────────────────────────────────────────────┐
  │  WING: myapp                                               │
  │    ┌──────────┐  ──hall──  ┌──────────┐                    │
  │    │  backend │            │  frontend│                    │
  │    └────┬─────┘            └──────────┘                    │
  │         ▼                                                  │
  │    ┌──────────┐      ┌──────────┐                          │
  │    │  Closet  │ ───▶ │  Drawer  │  (verbatim content)     │
  │    └──────────┘      └──────────┘                          │
  └─────────┼──────────────────────────────────────────────────┘
            │ tunnel (auto-created when room names match)
  ┌─────────┼──────────────────────────────────────────────────┐
  │  WING: otherapp                                            │
  │    ┌────┴─────┐  ──hall──  ┌──────────┐                    │
  │    │  backend │            │  infra   │                    │
  │    └──────────┘            └──────────┘                    │
  └─────────────────────────────────────────────────────────────┘
```

| Concept | What it is |
|---------|-----------|
| **Wing** | A project, person, or domain. As many as you need. |
| **Room** | A topic within a wing: `backend`, `auth`, `deploy`, `decisions`. |
| **Drawer** | Verbatim content. Never summarized, never rewritten. |
| **Hall** | Connection between rooms in the same wing. |
| **Tunnel** | Auto-connection between wings when the same room name appears. |

---

### MCP Server — 29 Tools {#mcp-tool-profiles}

Agent Plugins-compatible clients can discover the portable package with:

```bash
mempalace-code agent-plugin path --json
```

That package declares the installed stdio launcher
`mempalace-code-mcp --profile=minimal`. This is the portable default for
low tool-schema cost. Direct MCP registrations below remain supported for the
full surface or richer startup profiles.

```bash
MEMPALACE_BIN="$(command -v mempalace-code)"
MEMPALACE_MCP="$(dirname "$MEMPALACE_BIN")/mempalace-code-mcp"
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP"
```

The MCP server registration name defaults to `mempalace-code`. The MCP tool
identifiers remain `mempalace_*` for compatibility with existing agents and
usage rules.

**Protocol compatibility:** the server speaks both the stable **2026-07-28**
protocol revision (via `server/discover` and per-request metadata) and the
legacy `initialize`-based handshake, negotiated automatically per request —
existing `python -m mempalace_code.mcp_server` registrations (and the
source-checkout `mempalace.mcp_server` shim) keep working unchanged; there is
nothing to reconfigure.

Direct registration without a selector exposes all 29 tools. The portable Agent
Plugin above selects `minimal` and exposes four. Use startup flags to reduce the
direct tool surface (GitHub issue #6 — static profiles lower prompt cost while
preserving stable named-tool trigger patterns in usage rules):

```bash
# Named profiles — select a pre-defined subset at server startup
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=minimal
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=kg
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=code
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=notes

# Explicit tool list (replaces profile base set)
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --tools=search,add_drawer,diary_*

# Add or remove tools from a profile
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=minimal --include=kg_query
claude mcp add --scope user mempalace-code -- "$MEMPALACE_MCP" --profile=full --exclude=delete_wing,delete_drawer
```

| Profile | Tools | Best for |
|---------|-------|----------|
| `full` _(default)_ | all 29 | Full capability; no surface reduction |
| `minimal` | 4 | Search + store only |
| `kg` | 8 | Minimal + temporal knowledge graph |
| `code` | 10 | Code archaeology; no drawer-write/diary tools (`mine` included) |
| `notes` | 12 | Knowledge management + diary; no code-search |

Selector rules for `--tools`, `--include`, `--exclude`:
- Accept full names (`mempalace_search`), short names (`search`), or wildcards (`diary_*`).
- `--tools` replaces the profile base set; cannot be combined with `--include`.
- `--include` adds to the profile base set; `--exclude` removes last (wins over everything).
- Invalid profile name, unknown selector, or empty result → process exits with nonzero status and a stderr message.

An explicit `wing`/`room` filter passed to CLI `search`/`read` or the MCP
search/read/architecture tools is validated against the palace taxonomy
before retrieval runs (when the palace has a readable, non-empty taxonomy
to validate against). A valid scope with zero matches is still a normal
success (`results: []`, CLI exit status 0); an unknown wing, room, or
wing/room pair returns a structured `{error, filter, value, suggestions}`
validation error instead (CLI exit status 2), with up to 3 advisory
suggestions that are never auto-applied. See
[`docs/HOW_SEARCH_WORKS.md`](docs/HOW_SEARCH_WORKS.md#taxonomy-filter-validation)
for the full contract, including when validation is skipped.

A malformed MCP call is bounded, not fatal. Arguments that are not an object,
undeclared argument names, type mismatches, and missing required arguments are
each rejected with JSON-RPC `-32602` naming exactly what was wrong — correct
those arguments and retry the same tool. Malformed JSON returns `-32700` with a
null id, and an unknown tool name returns `-32601`. None of these end the
session: the server answers and keeps reading, so the next valid request is
served normally and no restart is needed.

<details>
<summary><strong>Palace — Read</strong></summary>

| Tool | What |
|------|------|
| `mempalace_status` | Palace overview — total drawers, wings, rooms |
| `mempalace_list_wings` | All wings with drawer counts |
| `mempalace_list_rooms` | Rooms within a wing |
| `mempalace_get_taxonomy` | Full wing → room → count tree |
| `mempalace_search` | Semantic search with optional wing/room filters; Markdown hits include heading path and section metadata |
| `mempalace_code_search` | Filter by language, symbol name/type, file glob; optional `rerank="hybrid"` |
| `mempalace_file_context` | All indexed chunks for a source file, ordered by chunk_index |
| `mempalace_read` | Surgical read of stored source lines in a range for a file; use after a search/file_context hit to avoid reading the whole file |
| `mempalace_check_duplicate` | Similarity check before filing (0.9 threshold) |

</details>

<details>
<summary><strong>Palace — Write</strong></summary>

| Tool | What |
|------|------|
| `mempalace_add_drawer` | File verbatim content into a wing/room |
| `mempalace_delete_drawer` | Remove a drawer by ID |
| `mempalace_delete_wing` | Delete all drawers in a wing |
| `mempalace_mine` | Trigger re-mining of a project directory (incremental or full) |

</details>

<details>
<summary><strong>Knowledge Graph</strong></summary>

| Tool | What |
|------|------|
| `mempalace_kg_query` | Entity relationships with time filtering |
| `mempalace_kg_add` | Add a fact with optional validity window |
| `mempalace_kg_invalidate` | Mark a fact as no longer true |
| `mempalace_kg_timeline` | Chronological story of an entity |
| `mempalace_kg_stats` | Graph overview |

</details>

<details>
<summary><strong>Architecture Retrieval</strong></summary>

| Tool | What |
|------|------|
| `mempalace_find_implementations` | Find all types implementing a given interface |
| `mempalace_find_references` | Find all usages of a type (implementors, subclasses, deps) |
| `mempalace_show_project_graph` | Project-level dependency graph, optionally filtered by solution |
| `mempalace_show_type_dependencies` | Inheritance/implementation chain (ancestors + descendants) |
| `mempalace_explain_subsystem` | Explain how a subsystem works: semantic search + KG expansion |
| `mempalace_extract_reusable` | Classify deps as core/platform/glue; identify extraction boundary |
| `mempalace_kg_query` (entity="Service", direction="incoming") | Show all services in the project |
| `mempalace_kg_query` (entity="Data",    direction="incoming") | Show all types in the data layer |

</details>

<details>
<summary><strong>Navigation & Diary</strong></summary>

| Tool | What |
|------|------|
| `mempalace_traverse` | Walk the graph from a room across wings |
| `mempalace_find_tunnels` | Find rooms bridging two wings |
| `mempalace_graph_stats` | Graph connectivity overview |
| `mempalace_diary_write` | Write a session journal entry |
| `mempalace_diary_read` | Read recent diary entries |

</details>

MCP-capable clients discover the registered tools. Compatible Agent Plugins 1.0 clients get the supported instruction bundle from `mempalace-code agent-plugin path --json`; follow [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) Section 7. Other clients may consult [`docs/LLM_USAGE_RULES.md`](docs/LLM_USAGE_RULES.md) as read-only reference material, including its profile-scoped routing guidance. Instruction-file and system-prompt mutation are unsupported.

---

### Knowledge Graph

Temporal entity-relationship triples — local SQLite, no Neo4j, no cloud.

```python
kg = KnowledgeGraph()
kg.add_triple("myapp", "uses", "Postgres", valid_from="2025-11-03")
kg.add_triple("myapp", "uses", "Redis",    valid_from="2026-01-15")

kg.query_entity("myapp")                    # → Postgres (current), Redis (current)
kg.query_entity("myapp", as_of="2025-12-01")  # → Postgres only

kg.invalidate("myapp", "uses", "Postgres", ended="2026-03-01")  # fact expired
```

**Good candidates:** version numbers, team assignments, tech stack choices, deployment states, deadlines.

**Architecture extraction** — `mempalace-code mine` automatically emits higher-level KG facts for .NET and Python projects after each mine:

| Predicate | Example | Query |
|-----------|---------|-------|
| `is_pattern` | `UserService → is_pattern → Service` | `kg_query(entity="Service", direction="incoming")` |
| `is_layer` | `UserRepository → is_layer → Data` | `kg_query(entity="Data", direction="incoming")` |
| `in_namespace` | `UserService → in_namespace → Company.App` | `kg_query(entity="UserService")` |
| `in_project` | `UserService → in_project → myapp` | `kg_query(entity="myapp", direction="incoming")` |

Default patterns: Service, Repository, Controller, ViewModel, Factory.
Default layers: UI (`*.UI`, `*.Web`, `*.Presentation`), Business (`*.Application`, `*.Domain`), Data (`*.Data`, `*.Persistence`), Infrastructure (`*.Infrastructure`).

Re-mining a project refreshes architecture facts for that project's wing only,
so a multi-project palace can update one repo without expiring facts from
another.

Override or extend via the `architecture:` block in `mempalace.yaml`:

```yaml
architecture:
  enabled: true
  patterns:
    - name: Service
      suffixes: [Service]
      type_names: [AuditHandler]   # explicit names bypass suffix matching
  layers:
    - name: Business
      namespace_globs: ["*.Application", "*.Domain", "*.Audit"]
      type_suffixes: [Service]
      priority: 1
```

Set `enabled: false` to disable the pass entirely.

---

### Memory Layers

| Layer | What | When |
|-------|------|------|
| **L0** | Identity — project, persona | Always loaded (~100 tokens) |
| **L1** | Critical facts — team, decisions | Always loaded (~500–800 tokens) |
| **L2** | Room recall — current topic | On demand |
| **L3** | Deep search — full semantic query | On demand |

```bash
mempalace-code wake-up --wing myapp    # emit L0 + L1 context (~600–900 tokens)
```

For local models (Llama, Mistral) that don't speak MCP, pipe `wake-up` into the system prompt.

---

### Backup & Restore

Create and inspect both recovery artifacts before rebuilding. The import preview
must target the inspected, already-existing palace.

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"
BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"

: "${PALACE:?set PALACE to the inspected existing palace}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to a new JSONL path}"
: "${BACKUP_TAR:?set BACKUP_TAR to a new tar path}"
test -d "$PALACE/lance"
test ! -e "$EXPORT_JSONL"
test ! -e "$BACKUP_TAR"

mempalace-code --palace "$PALACE" export --only-manual --with-kg --out "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run
mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"
tar -tzf "$BACKUP_TAR"
```

The preview validates the JSONL and opens existing palace state read-only when
present. It does not write palace or KG state. When the selected palace and KG
are absent, it does not create them or initialize temporary, embedding-model, or
cache state. It previews record import without applying records. Without
`--force`, tar restore refuses state found at the selected palace or KG during
its checks, claims the exact `lance/` name exclusively, and publishes the KG with
an atomic no-replace operation. An existing real empty palace directory is the
only reusable initial state. Unsupported no-replace KG publication fails closed.
This boundary is not a transaction for concurrent replacement of the palace
root or its ancestors, or for arbitrary edits elsewhere in the palace. Back up
every reported destination before an intentional `--force` restore.

KG boundary: JSONL `--with-kg` uses the separate global KG. Explicit `--palace`
tar operations use `<palace>/knowledge_graph.sqlite3`, omit it from the archive
when absent, and never fall back to the global KG; `--kg-path` selects another
restore destination. The complete quarantine, rebuild, restore, force-restore,
and failure-recovery procedure is in [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md).

**Backup kinds:** Each archive has a kind that controls its filename prefix and per-kind retention:

| Kind | Prefix | Created by |
|------|--------|-----------|
| `manual` | `mempalace_backup_` | `backup create` (default) |
| `scheduled` | `scheduled_` | `backup create --kind scheduled` / cron |
| `pre_optimize` | `pre_optimize_` | Auto-backup before optimize |

**Scheduled backups:**

```bash
# Print a scheduler snippet (does NOT install — owner action required)
mempalace-code backup schedule --freq daily    # daily at 03:00
mempalace-code backup schedule --freq weekly   # weekly on Sunday at 03:00
mempalace-code backup schedule --freq hourly   # every hour

# macOS: save and load the launchd plist
mempalace-code backup schedule --freq daily > ~/Library/LaunchAgents/com.mempalace.backup.plist
launchctl load ~/Library/LaunchAgents/com.mempalace.backup.plist

# Linux: paste the printed cron line into crontab -e
mempalace-code backup schedule --freq daily
# → 0 3 * * * /usr/local/bin/mempalace-code backup create --kind scheduled --palace /path/to/palace
```

**Retention (automatic pruning):**

`pre_optimize` archives are **bounded by default** to the newest 5 (implicit safe default for watcher daemons).
`scheduled` archives are **bounded by default** to the newest 14 (implicit safe default for cron and launchd jobs).
`manual` archives are **unbounded by default** (retain all, no pruning).

```bash
export MEMPALACE_BACKUP_RETAIN_COUNT=5   # explicit limit for all kinds; overrides implicit pre_optimize and scheduled bounds
# Deliberate keep-all opt-out (including pre_optimize and scheduled):
export MEMPALACE_BACKUP_RETAIN_COUNT=0   # 0 disables pruning for every kind
```

Or in `~/.mempalace/config.json`: `{"backup_retain_count": 5}`. Retention only affects archives in the managed `backups/` directory; explicit `--out` archives are never pruned.

`backup list` shows `[stale]` for archives that would be pruned at the current retain count, and `[oversized]` for archives larger than `MEMPALACE_BACKUP_WARN_SIZE_BYTES`.

After a successful optimize and readability check, MemPalace also runs
best-effort verified Lance cleanup (`cleanup_stale_fragments` with
`unsafe_now=false`) so future backups do not keep archiving stale table versions.
Optimize and cleanup verification re-opens the Lance table, so it checks the
same fresh-handle path the next CLI, MCP server, or watcher process will use.
Use the manual `cleanup` command for older installations that already
accumulated stale versions or for emergency recovery.

**Disk-budget guard (1 GiB default):**

```bash
export MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES=2GiB    # require 2 GiB projected free after backup
# Legacy alias still accepted:
export MEMPALACE_BACKUP_MIN_FREE_BYTES=2GiB
```

When projected free space after the archive would fall below the configured
floor, backup raises a `disk budget` error before writing the archive and
optimize is skipped (fail-closed). The backup floor falls back to
`backup_disk_min_free_bytes` → `disk_min_free_bytes` → **1 GiB default**.
Set the backup-specific floor to `0` to disable the backup guard.

**Auto-backup before optimize (on by default):**

`backup_before_optimize` is **`true` by default**. A backup is created under `<palace_parent>/backups/pre_optimize_*.tar.gz` before every `optimize()` call (runs after mining).

To opt out, add to `~/.mempalace/config.json`:
```json
{
  "auto_backup_before_optimize": false
}
```

Or set env var: `MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE=0` (preferred) or `MEMPALACE_BACKUP_BEFORE_OPTIMIZE=0`.

**Disable auto-optimize (paranoid mode):**

```json
{
  "optimize_after_mine": false
}
```

Skips compaction entirely. Storage will grow with more fragments but avoids any compaction-related corruption risk.

**Why backup matters:** Manual drawer additions (via `mempalace_add_drawer`) are not recoverable from source code. If LanceDB storage gets corrupted, only backups preserve this data. Code-mined drawers can be restored by re-running `mempalace-code mine`.

Also available: `mempalace-code export --only-manual --out <backup.jsonl>` for JSONL export of manually-stored drawers.

**Remote mirror risk — backups vs file mirroring:**

Managed backups and Lance cleanup protect **local** palace state. They do not protect against
delete-mode rsync between independent hosts. `rsync --delete` syncing a whole MemPalace state
directory removes remote-owned drawers, diary entries, and KG triples that were never synced
back to the source — even when local backups are healthy.

Use these recommended excludes for any delete-mode state-directory mirror:

```bash
rsync -a --delete \
  --exclude=palace/ \
  --exclude=knowledge_graph.sqlite3 \
  --exclude=config.json \
  --exclude=backups/ \
  ~/.mempalace/ user@host:.mempalace/
```

Run a preflight check before installing a mirror job (the command is never executed):

```bash
mempalace-code preflight mirror --command \
  "rsync -a --delete --exclude=palace/ --exclude=knowledge_graph.sqlite3 \
   --exclude=config.json --exclude=backups/ ~/.mempalace/ user@host:.mempalace/"
# OK
```

See [docs/BACKUP_RESTORE.md](docs/BACKUP_RESTORE.md) for the full mirror-risk guidance and
the safer export/import alternative for cross-host transfer of non-regenerable content.

---

### Scan Excludes

By default `mempalace-code mine` already skips common generated directories (`node_modules`,
`__pycache__`, `.git`, etc.). For project-specific noise — generated LSP state, build
artifacts, IDE files — configure app-level excludes in `~/.mempalace/config.json`:

```json
{
  "scan_skip_dirs":  [".kotlin-lsp"],
  "scan_skip_files": ["workspace.json"],
  "scan_skip_globs": ["generated/**/*.js", "build/**"]
}
```

| Key | Match rule | Default |
|-----|------------|---------|
| `scan_skip_dirs` | directory **basename** — prunes the whole subtree | `[".kotlin-lsp"]` |
| `scan_skip_files` | file **basename** — skips matching files anywhere | `[]` |
| `scan_skip_globs` | project-relative POSIX glob — skips matching file paths | `[]` |

**`workspace.json` as opt-in example:** a root `workspace.json` can be a legitimate
monorepo config file, so it is *not* excluded by default. Add it to `scan_skip_files`
only if your LSP generates it as noise inside generated directories.

These rules apply to both `mempalace-code mine` and the auto-watcher (`mempalace-code mine --watch`
and `mempalace-code watch`). Force-include paths (`--include-ignored`) always win over
app-level excludes.

Watcher loops reload these app-level rules between scan cycles, so edits to
`~/.mempalace/config.json` apply to subsequent re-mines without restarting
`mempalace-code watch`.

**Removing previously indexed noise:** scan excludes prevent *future* scans from indexing
the excluded paths. To remove content that was indexed before adding the exclusion, run a
full re-mine:

```bash
mempalace-code mine <dir> --full
```

`--full` forces a clean rebuild and sweeps drawers from files that are no longer
discovered by the scanner — including previously indexed files that now fall under an
exclusion rule.

---

### Health & Repair

```bash
mempalace-code health              # probe palace for fragment corruption
mempalace-code health --json       # machine-readable report
mempalace-code cleanup --older-than-days 7  # reclaim stale Lance versions
mempalace-code cleanup --unsafe-now         # emergency only; stop MemPalace processes first

mempalace-code repair --rollback --dry-run  # show what rollback would recover
mempalace-code repair --rollback   # roll back to last working version
```

**What `health` checks:**
1. Manifest read (count_rows)
2. Data fragment read (head)
3. Metadata scan (count_by_pair) - catches the silent-failure surface

**What `repair --rollback` does:**
1. Walks LanceDB version history from newest to oldest
2. Finds the most recent version where all probes pass
3. Restores to that version (loses data added after corruption)

Use `--dry-run` first to see how many rows would be lost.

Normal optimize runs already prune verified stale Lance versions after a
successful compaction and fresh-handle verification. Manual `cleanup` is still
useful after older installs, large historical accumulations, or emergency disk
recovery after stopping watchers, miners, maintenance commands, and MCP servers.

---

### Version Check (opt-in)

mempalace-code can notify you when a newer release is available on PyPI. This feature
is **strictly opt-in** — no network calls are made by default.

```bash
# Check your current status (local-only, no network)
mempalace-code version-check

# Opt in to periodic checks (contacts PyPI for package metadata only)
mempalace-code version-check --enable

# Opt out (suppresses future first-run prompts)
mempalace-code version-check --disable

# Check right now regardless of the interval or persisted preference
mempalace-code version-check --check-now
```

**How it works:**

- On the first interactive command after a fresh install, the CLI prompts once: *"Enable periodic new-version checks?"* — answering `n` records the opt-out permanently. Non-interactive (piped, CI, non-TTY) invocations **never prompt**.
- When opted in, a background check runs at most once per interval (default: 168 hours / 1 week). Any update hint appears on **stderr only** — stdout remains machine-parseable.
- Explicit `--check-now` ignores the interval and persisted preference, then contacts PyPI and
  prints current/latest/error to stdout. `MEMPALACE_VERSION_CHECK=0` and invalid values still block
  the request; run `unset MEMPALACE_VERSION_CHECK` (or set it to `1`) before retrying.
- Only `https://pypi.org/pypi/mempalace-code/json` is contacted. No telemetry, no user IDs, no installed-package inventory.

**Environment overrides:**

| Variable | Effect |
|---|---|
| `MEMPALACE_VERSION_CHECK=1` | Force-enable (overrides config and state) |
| `MEMPALACE_VERSION_CHECK=0` | Force-disable (overrides config and state) |
| `MEMPALACE_VERSION_CHECK_INTERVAL_HOURS=N` | Override interval (default: 168) |

Setting `MEMPALACE_VERSION_CHECK=0` in a CI pipeline guarantees no version-check network calls,
including explicit `--check-now`, regardless of any saved preference. Invalid values fail closed in
the same way. Run `unset MEMPALACE_VERSION_CHECK` (or set it to `1`) before an explicit check.

---

## This Fork vs Upstream

This is a code-first fork of the upstream `mempalace` project. The canonical upstream repository is [MemPalace/mempalace](https://github.com/MemPalace/mempalace); the older `milla-jovovich/mempalace` URL redirects there.

Snapshot reviewed on 2026-08-11 against upstream `develop` at commit `b2104238d4491654f17118d12cf876ac5e41a0cf`, using pinned upstream public sources. Nothing below is a performance, quality, or adoption comparison — no upstream build or benchmark was run.

| Area | Upstream, as advertised at that commit | This fork |
|---|---|---|
| Focus | General-purpose AI memory | Code-first: repository mining, `code_search`, symbol/type/project-graph tools |
| Default storage | ChromaDB | LanceDB |
| Other backends offered | `sqlite_exact`, Milvus, Qdrant, pgvector | LanceDB-only current package; ChromaDB support is retired; no server-backed backends |
| Embedding model | `all-MiniLM-L6-v2`, plus an optional `embeddinggemma` multilingual model | `all-MiniLM-L6-v2`; no supported multilingual configuration or migration flow |
| Retrieval | Hybrid retrieval | Vector search, plus a local deterministic `code_search(rerank="hybrid")` |
| Reranking | Optional LLM reranking | None — no LLM reranker; this direction is explicitly rejected |

This fork has not adopted upstream's multilingual embedding, broad hybrid-retrieval, or multi-server-backend paths. LLM reranking is explicitly rejected: it would put an API key, a per-query network call, and non-deterministic results into a tool that stays local after the one-time model download.

Reviewed comparison with source links, evidence limits, and the reasoning behind each decision: [`docs/UPSTREAM_COMPARISON.md`](docs/UPSTREAM_COMPARISON.md).

Historical community criticism of upstream from April 2026, and how this fork responded at the time, is archived in [`docs/UPSTREAM_HARDENING.md`](docs/UPSTREAM_HARDENING.md). Those findings describe April 2026 and are not claims about upstream today.

---

## Benchmarks

### Token savings vs grep + read ([full methodology](docs/BENCH_TOKEN_DELTA.md))

Measured on the canonical fixture (378 tracked files, 2,024 mined chunks, 20 queries):

| Median | Mean | P95 | Peak |
|--------|------|-----|------|
| **14.5x** | 15.8x | 27.8x | **33.8x** |

These are read from the committed [`benchmarks/token_delta_fixture_facts.json`](benchmarks/token_delta_fixture_facts.json); `scripts/docs_drift_guard.py` fails CI if the Median or Peak columns drift from that file (Mean and P95 are reported from the same run but are not individually guard-checked). Treat the figures as benchmark results for this fixture's query set and corpus size; re-run the benchmark before applying them to a different corpus.

### Retrieval quality

| Benchmark | Score |
|-----------|-------|
| Code retrieval R@5 (MiniLM, 469 chunks) | **95.0%** |
| Code retrieval R@10 | **100%** |
| .NET retrieval R@5 (CleanArchitecture pinned corpus, vector) | **90.0%** |
| .NET retrieval R@5 (same corpus, `rerank="hybrid"`) | **100%** |

These are read from the committed [`benchmarks/retrieval_quality_facts.json`](benchmarks/retrieval_quality_facts.json); `scripts/docs_drift_guard.py` fails CI if these values drift from that file.

Upstream LongMemEval result (96.6% R@5 on conversations) retained with [methodology caveats](benchmarks/BENCHMARKS.md).

---

<details>
<summary><strong>Installation Details</strong></summary>

```bash
pip install mempalace-code
# or
uv pip install mempalace-code
```

**Bootstrap script** (explicit remote-script option for servers/CI):

```bash
[[ "${BOOTSTRAP_REF:-}" =~ ^[0-9a-fA-F]{40}$ ]] || { echo "BOOTSTRAP_REF must be a reviewed 40-hex commit" >&2; exit 2; }
BOOTSTRAP_FILE="$(mktemp -t mempalace-bootstrap.XXXXXX)" || exit 1
(
  trap 'rm -f -- "$BOOTSTRAP_FILE"' EXIT
  curl -fL "https://raw.githubusercontent.com/rergards/mempalace-code/$BOOTSTRAP_REF/scripts/bootstrap.sh" -o "$BOOTSTRAP_FILE" || exit 1
  less "$BOOTSTRAP_FILE" || exit 1
  bash "$BOOTSTRAP_FILE" || exit 1
) || exit 1
```

**Optional extras:**

```bash
# mempalace-code[custom-models]            # CPU-only Linux: docs/OFFLINE_USAGE.md
pip install "mempalace-code[treesitter]"  # AST parsing
pip install "mempalace-code[spellcheck]"  # autocorrect for room/wing names
pip install "mempalace-code[watch]"       # optional watcher (auto-mine on file changes)
pip install "mempalace-code[dev]"         # pytest + ruff + pyright
```

CPU-only Linux custom models require the ordered CPU PyTorch contour and bounded recovery
in [Using a Custom Model Offline](docs/OFFLINE_USAGE.md#3-using-a-custom-model-offline).
That guide also covers arbitrary SentenceTransformer names and local paths.

**Requirements:** Python 3.11+. Use `mempalace-code init <dir> --skip-model-download` for an
offline-safe init. Run `mempalace-code fetch-model` later only after explicit consent to cache
the ~80 MB embedding model.

The default `all-MiniLM-L6-v2` runtime is CPU FastEmbed/ONNX and stores its
immutable MemPalace provenance under
`$HF_HOME/mempalace-fastembed/all-MiniLM-L6-v2-v1/`. Canonical aliases never
enable trusted remote code. Explicit custom models require `[custom-models]`;
that path retains SentenceTransformer's `trust_remote_code=True` compatibility
boundary. Recovery: run `mempalace-code fetch-model` while online, then retry
with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`.

</details>

<details>
<summary><strong>All CLI Commands</strong></summary>

```bash
mempalace-code help                                    # show top-level help message and exit
mempalace-code --version                               # print the installed package version and exit

# Setup
mempalace-code init <dir>                              # initialize rooms
mempalace-code init <dir> --detect-entities            # optional prose entity bootstrap
mempalace-code onboarding <dir>                        # guided interactive setup (people, projects, taxonomy)
mempalace-code split <dir>                             # split concatenated transcript mega-files before mining
mempalace-code install-alias                           # create optional 'mempalace' alias next to mempalace-code
mempalace-code install-alias --target-dir <dir>        # create it in <dir> instead; only <dir> is inspected

# Mining
mempalace-code mine <dir>                              # mine code project
mempalace-code mine <dir> --wing myapp                 # tag with wing
mempalace-code mine <dir> --mode convos                # mine conversations
mempalace-code mine <dir> --full                       # force full rebuild
mempalace-code mine <dir> --watch                      # auto-incremental on file changes
mempalace-code mine-all <parent-dir>                   # sync all projects incrementally (one wing per project)
mempalace-code mine-all <parent-dir> --new-only        # only mine projects not yet in the palace

# Watch (project auto-sync)
mempalace-code watch <initialized-project>             # watch a single initialized project
mempalace-code watch <parent-dir>                      # watch all initialized projects in a parent directory
mempalace-code watch <parent-dir> schedule             # print launchd/cron daemon snippet
mempalace-code watch <parent-dir> status               # disk-budget + launchd state

# Search
mempalace-code search "query"                          # search everything
mempalace-code search "query" --wing myapp             # scoped to wing
mempalace-code search "query" --room auth              # scoped to room
mempalace-code read <file> --start N --end N           # print stored source lines for a file/range
mempalace-code compress                                # lossy structured summarization/abbreviation of drawers via AAAK Dialect

# Diary
mempalace-code diary write --agent <name> --entry "<text>"  # write a diary entry
```

A successful direct diary write prints `Diary entry stored.`, stable `ID`, `Wing`, `Room`, and
`Topic` poststate, then a bounded `Verify before retry` search command. If that output is retained
after an ambiguous result, run the printed search before any retry. An exact hit means success: do
not repeat the write. If the response or printed command is unavailable, do not retry; inspect
recent same-agent entries with exposed `mempalace_diary_read`, or stop for owner reconciliation.

```bash

# Backup & Recovery
mempalace-code backup create                           # create backup (default: <palace_parent>/backups/)
mempalace-code backup list                             # list existing backups
mempalace-code backup schedule --freq daily            # print daily scheduler snippet
mempalace-code restore <archive>                       # restore from backup
mempalace-code export --only-manual --out backup.jsonl # JSONL export
mempalace-code import <file>                           # JSONL import
mempalace-code health                                  # probe for fragment corruption
mempalace-code cleanup                                 # reclaim stale Lance versions
mempalace-code repair --rollback                       # roll back to last working version

# Context
mempalace-code wake-up                                 # L0 + L1 context
mempalace-code wake-up --wing myapp                    # project-scoped
mempalace-code status                                  # detailed overview; grows with wing/room count
mempalace-code status --summary                        # bounded agent-facing status (drawer/wing/room-pair counts + storage)
mempalace-code health --json                           # compact integrity report

# Model
mempalace-code fetch-model                             # cache or verify model for offline use

# Advanced / Ops
# Legacy Chroma palace recovery: back up SRC before upgrading, then run the last bridge in isolation
mempalace-code migrate-storage SRC DST --verify         # retired; exits before mutation and points here
uvx --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify
mempalace-code preflight mirror --command "<cmd>"      # inspect an rsync command for state-dir risks
mempalace-code version-check                           # show version-check status (opt-in PyPI checks)
mempalace-code version-check --check-now               # check PyPI now; prints a pip fallback for unmanaged installs
mempalace-code update status                            # inspect upgrade eligibility (supported installs)
mempalace-code agent-plugin path --json                # locate the installed Agent Plugins package directory
```

Plain `status` prints a full wing/room breakdown, so its output grows with palace size. Do not use it as a routine agent bootstrap or machine-readable health check; use `status --summary` for bounded shell-based CLI discovery, task-specific MCP retrieval, or `mempalace-code health --json` for a compact CLI integrity report.

</details>

<details>
<summary><strong>Saving Conversation Context</strong></summary>

Code mining is automatic via `mempalace-code watch`. For conversation context (decisions, discussions, debugging notes), an MCP-capable client can expose the storage tools:

1. Wire the MCP server (see [install docs](docs/AGENT_INSTALL.md))
2. For compatible Agent Plugins 1.0 clients, load the package reported by `mempalace-code agent-plugin path --json`; follow [Section 7](docs/AGENT_INSTALL.md#section-7--agent-instruction-loading-agent-plugin-only)
3. For other clients, stop after MCP wiring. [`docs/LLM_USAGE_RULES.md`](docs/LLM_USAGE_RULES.md) remains read-only reference material; instruction-file and system-prompt mutation are unsupported
4. Subject to client policy, call `mempalace_add_drawer` and `mempalace_diary_write` during sessions

> **Legacy:** Claude Code also supports optional [auto-save hooks](hooks/README.md) that remind the AI to save at fixed intervals. They are independent of the Agent Plugin instruction-loading boundary.

</details>

<details>
<summary><strong>Project Structure</strong></summary>

```
mempalace/
├── mempalace_code/
│   ├── cli.py              ← CLI entry point
│   ├── mcp_server.py       ← MCP server (29 tools, profiled at startup)
│   ├── storage.py          ← LanceDB vector storage
│   ├── miner.py            ← language-aware code chunking
│   ├── convo_miner.py      ← conversation ingest
│   ├── searcher.py         ← semantic search
│   ├── knowledge_graph.py  ← temporal entity graph (SQLite)
│   ├── palace_graph.py     ← room navigation graph
│   └── layers.py           ← 4-layer memory stack
├── mempalace/              ← source-only MCP compatibility shim
├── benchmarks/             ← reproducible benchmark runners
├── hooks/                  ← Claude Code auto-save hooks (legacy, optional)
├── examples/               ← usage examples
└── tests/                  ← 3,000+ tests
```

</details>

---

## Opt-in updates

Supported isolated installs can inspect and explicitly apply upgrades. The command never runs
from ordinary MemPalace startup, and its systemd-user scheduler is disabled until installed by
the operator.

```bash
mempalace-code update status                 # read-only: installer, extras, provenance, service, timer
mempalace-code update check                  # read-only canonical PyPI provenance refresh
mempalace-code update apply --yes            # explicit package and managed-watcher transaction
mempalace-code update scheduler render       # inspect systemd-user units without writing them
mempalace-code update scheduler install --yes # explicit daily scheduler opt-in (Linux systemd-user)
```

Omitting `--yes` from `update apply`, `update scheduler install`, or `update scheduler remove`
exits 2 before mutation. Human output prints `Recovery: <command>`; JSON output supplies the exact
guarded command in `recovery_command`. Review current mutation authority before running that
emitted command. See [the update runbook](docs/UPDATES.md) for the complete refusal contract.

The first slice supports `uv tool`, `pipx`, and the documented `~/.mempalace/venv` bootstrap
install. It refuses system Python, distro-managed, editable/source, and ambiguous environments
before stopping a watcher or changing package state. If you installed with plain `pip`, upgrade
yourself — `mempalace-code version-check --check-now` prints the exact pinned `python -m pip install`
command for the interpreter that is running mempalace-code. Stable, compatible-major releases
are selected from canonical PyPI provenance; prereleases, yanked files, and releases without a
wheel are refused.
Detected extras are retained. A configured watcher missing its required `watch` extra is also a
preflight refusal.

An update serializes with watchers, records its stage and bounded log under `~/.mempalace/updates/`,
validates the new console and palace, then restores a previously active managed watcher. Any failure
after version recording invokes the same installer to roll back the prior version and restores the
prior watcher state. See [the update runbook](docs/UPDATES.md) for recovery.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
Maintainers should follow [docs/RELEASING.md](docs/RELEASING.md) before tagging or publishing.

```bash
python -m pytest tests/ -x -q    # full suite, all local, no network
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"  # type-check baseline
```

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-1.13.7-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/rergards/mempalace-code/releases
[python-shield]: https://img.shields.io/badge/python-3.11+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-Apache_2.0-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/rergards/mempalace-code/blob/main/LICENSE
