<div align="center">

<img src="assets/mempalace_banner.jpg" alt="mempalace-code" width="640">

# mempalace-code

### Your AI's long-term memory. Local. Instant. Private.

One command indexes your codebase. Your AI remembers *everything* — architecture decisions, debugging sessions, API patterns — across sessions and projects. **Forever.**

No cloud. No API keys. No subscription. Nothing leaves your machine.

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]

<br>

[**Get Started in 30 seconds**](#quick-start) · [How It Works](#the-palace) · [All Features](#features) · [Benchmarks](#benchmarks)

<br>

<table>
<tr>
<td align="center"><strong>Language-Aware Mining</strong><br><sub>AST, regex, and adaptive chunking<br>matched to each file type</sub></td>
<td align="center"><strong>28 MCP Tools</strong><br><sub>Native Claude Code integration<br>search, store, traverse</sub></td>
<td align="center"><strong>Temporal Knowledge Graph</strong><br><sub>Facts that change over time<br>with validity windows</sub></td>
</tr>
<tr>
<td align="center"><strong>595x Token Savings</strong><br><sub>measured peak · median 80x<br><a href="docs/BENCH_TOKEN_DELTA.md">scales with project size</a></sub></td>
<td align="center"><strong>Cross-Project Tunnels</strong><br><sub>Search <code>auth</code> in one project<br>find it everywhere</sub></td>
<td align="center"><strong>1515 Tests · $0 Cost</strong><br><sub>Every feature acceptance-gated<br>fully offline after install</sub></td>
</tr>
</table>

</div>

---

## Quick Start

```bash
uv tool install mempalace-code        # recommended (fast, Rust-based)
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

Then ask your AI to read [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) — it will handle setup, MCP wiring, prompt injection, and verification automatically.

<details>
<summary>Or do it manually</summary>

```bash
mempalace-code init ~/projects/myapp       # detect rooms, download embedding model (~80 MB)
mempalace-code init ~/projects/myapp --detect-entities  # optional people/project detection for notes/convos
mempalace-code mine ~/projects/myapp       # index your codebase
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server  # connect to Claude Code
```

**Optional: auto-sync on commit** (requires `[watch]` extra — see [Auto-Watch](#auto-watch)):
```bash
mempalace-code watch ~/projects/           # re-mines on every commit, zero noise
```

This makes the 28 tools available to your AI. For proactive search and storage (without you asking), you'll also need to add usage rules to your `CLAUDE.md` (or equivalent agent-instruction file) — copy from [`docs/LLM_USAGE_RULES.md`](docs/LLM_USAGE_RULES.md), or let [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) Section 7 inject them for you.

</details>

### Do you need it? Ask your LLM:

```
Read https://github.com/rergards/mempalace-code/blob/main/docs/AGENT_INSTALL.md

1. How much context do I re-explain to you each session? Estimate tokens wasted.
2. Would auto-indexing this codebase as it grows save tokens over time? By how much?
3. Is my language/stack supported? If not, what's missing?
4. Decision: install now, wait for [feature], or skip — with reasoning.
5. If waiting: ask me if I want to draft a feature request for GitHub.
```

### Supported MCP Clients

mempalace-code works with any [MCP](https://modelcontextprotocol.io/)-compatible client:

- **Claude Code** (CLI, desktop, web) — `claude mcp add mempalace-code -- python -m mempalace_code.mcp_server`
- **Claude Desktop** — add to `claude_desktop_config.json`
- **Cursor** — add as MCP server in settings
- **Windsurf** — add as MCP server in settings
- **Any MCP client** — point it at `python -m mempalace_code.mcp_server` (stdio transport)

For local models without MCP support (Llama, Mistral, etc.), use `mempalace-code wake-up` to pipe context into the system prompt — see [Memory Layers](#memory-layers).

---

## How It Actually Works

You write code. You make decisions. You debug things. Between sessions, all that context vanishes.

mempalace-code **indexes it once** into a local vector store, then your AI finds it in milliseconds — using [595x fewer tokens](docs/BENCH_TOKEN_DELTA.md) than grep + read at measured peak (median 80x on a 19k-chunk project, and it keeps scaling). Think of it as `git log` for everything that *isn't* in the code: the *why*, the discussions, the dead ends, the decisions.

**What gets indexed:**
- Code files — structural chunks for Python, TypeScript/JS/TSX/JSX, Go, Rust, Java, Kotlin, C#, F#, VB.NET, XAML, Swift, PHP, Scala, Dart, Terraform/HCL, Markdown, and Kubernetes manifests; adaptive chunks for C/C++, Ruby, shell, SQL, HTML/CSS, JSON/YAML/TOML, CSV, Dockerfile, Make, templates, and config files
- .NET solutions — `.sln`/`.csproj` project graphs, cross-project symbol relationships, interface implementations
- Conversation exports — Claude, ChatGPT, Slack
- Architecture notes, decisions, anything you store manually

**How you use it:** After setup, your AI calls mempalace tools automatically. You don't type search commands.

---

## Features

### Language-Aware Code Mining

`mempalace-code mine` walks your source tree and chooses the best chunker for each file type: AST boundaries where optional tree-sitter grammars are available, regex structural boundaries for supported languages, YAML-aware Kubernetes resource splits, Markdown/prose sections, or adaptive line-count chunks for formats without reliable declarations. Leading comments and docstrings stay attached to declarations where structural chunking is active; Markdown drawers keep heading path, section type, and Mermaid/code/table flags in search metadata.

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
| Markdown / plain text | Heading sections (`#`-`######`), heading paths, section metadata, paragraphs | — |
| C / C++ | Indexed and searchable with best-effort symbol metadata; chunked adaptively today | — |
| Ruby / shell / SQL | Indexed and searchable; chunked adaptively today | — |
| HTML / CSS / CSV | Indexed and searchable; chunked adaptively today | — |
| YAML / JSON / TOML | Adaptive line-count; Kubernetes YAML auto-detected separately | — |
| Dockerfile / Make / templates / config | Dockerfile, Containerfile, Makefile, GNUmakefile, Vagrantfile, Go templates, Jinja2, `.conf`, `.cfg`, `.ini` | — |

The `mempalace_code_search` language filter is generated from the same language
catalog as the miner. If a file type is mined with a language label, the MCP
schema and unsupported-language hints stay aligned with that catalog.

Tree-sitter is optional (`pip install "mempalace-code[treesitter]"`). When a grammar is missing, Python, TypeScript/JavaScript/TSX/JSX, Go, and Rust fall back to regex structural chunking. Other recognized formats use their regex, YAML-aware, prose, or adaptive chunker as listed above.

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
mempalace-code watch ~/projects/                      # watch all projects (on commit, default)
mempalace-code watch ~/projects/ --on-save            # watch all file saves instead (noisier)
mempalace-code watch ~/projects/ schedule             # print launchd/cron snippet for daemon
```

**Install as persistent daemon (macOS):**

```bash
mempalace-code watch ~/projects/ schedule > ~/Library/LaunchAgents/com.mempalace.watch.plist
launchctl load ~/Library/LaunchAgents/com.mempalace.watch.plist
```

Starts at login, restarts if crashed. Logs to `/tmp/mempalace-watch.log`.

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

### MCP Server — 28 Tools

```bash
claude mcp add mempalace-code -- python -m mempalace_code.mcp_server
```

The MCP server registration name defaults to `mempalace-code`. The MCP tool
identifiers remain `mempalace_*` for compatibility with existing agents and
usage rules.

<details>
<summary><strong>Palace — Read</strong></summary>

| Tool | What |
|------|------|
| `mempalace_status` | Palace overview — total drawers, wings, rooms |
| `mempalace_list_wings` | All wings with drawer counts |
| `mempalace_list_rooms` | Rooms within a wing |
| `mempalace_get_taxonomy` | Full wing → room → count tree |
| `mempalace_search` | Semantic search with optional wing/room filters; Markdown hits include heading path and section metadata |
| `mempalace_code_search` | Filter by language, symbol name/type, file glob |
| `mempalace_file_context` | All indexed chunks for a source file, ordered by chunk_index |
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

MCP tools are discoverable by any MCP-capable client automatically. To teach the AI *when* and *how* to use them, paste the usage rules from [`docs/LLM_USAGE_RULES.md`](docs/LLM_USAGE_RULES.md) into your agent's instructions (CLAUDE.md, AGENTS.md, `.cursorrules`, etc.) — otherwise the tools are available but the assistant will not know the protocol.

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
| **L0** | Identity — project, persona | Always loaded (~50 tokens) |
| **L1** | Critical facts — team, decisions | Always loaded (~120 tokens) |
| **L2** | Room recall — current topic | On demand |
| **L3** | Deep search — full semantic query | On demand |

```bash
mempalace-code wake-up --wing myapp    # emit L0 + L1 context (~170 tokens)
```

For local models (Llama, Mistral) that don't speak MCP, pipe `wake-up` into the system prompt.

---

### Backup & Restore

```bash
mempalace-code backup create                           # create backup archive (default: <palace_parent>/backups/)
mempalace-code backup create --out ~/safe/my.tar.gz   # custom path
mempalace-code backup                                  # back-compat: same as 'backup create'
mempalace-code backup --out ~/safe/my.tar.gz           # back-compat: same as 'backup create --out ...'
mempalace-code backup list                             # list existing backups
mempalace-code backup list --dir ~/old_backups/        # include extra directory in discovery
mempalace-code restore palace_backup_2026-04-14.tar.gz # restore
mempalace-code restore backup.tar.gz --force           # overwrite existing
```

Backups are written to `<palace_parent>/backups/` by default. For a palace at `~/.mempalace/palace`, that is `~/.mempalace/backups/`.

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
# → 0 3 * * * /usr/local/bin/mempalace-code backup create --out /path/to/backups/scheduled_$(date +%Y%m%d_%H%M%S).tar.gz
```

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

Also available: `mempalace-code export --only-manual` for JSONL export of manually-stored drawers.

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

mempalace-code repair --dry-run    # show what would be recovered
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

---

## This Fork vs Upstream

This is a code-first fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace). We inherited the good parts — the palace metaphor, the MCP integration, the LongMemEval harness — and rebuilt what was broken. Every claim here is backed by code, tests, and documented benchmarks.

| Upstream | This fork |
|---|---|
| ChromaDB — [silently deletes data on version bump](https://github.com/milla-jovovich/mempalace/issues/469) | LanceDB — crash-safe Arrow storage, no version-cliff |
| "No internet after install" — [false](https://github.com/milla-jovovich/mempalace/issues/524) | `mempalace-code init` downloads model explicitly; fully offline after |
| "100% R@5" — [unverifiable](https://github.com/milla-jovovich/mempalace/issues/27) | Number removed. Methodology caveats documented |
| ~30% test coverage | 1312 tests, every feature acceptance-gated |
| No backup, no recovery | `backup` / `restore` / `export` / `import` |
| No incremental mining | Content-hash incremental: only changed files re-chunked |
| No code-search | `code_search` — filter by language, symbol, glob |
| Line-count chunking | Language-aware mining: tree-sitter AST for supported grammars, regex structural chunking, YAML-aware Kubernetes splits, prose sections, and adaptive chunks for configs/data |

Full audit: [`docs/UPSTREAM_HARDENING.md`](docs/UPSTREAM_HARDENING.md).

---

## Benchmarks

### Token savings vs grep + read ([full methodology](docs/BENCH_TOKEN_DELTA.md))

| Project size | Median | Mean | P95 | Peak |
|-------------|--------|------|-----|------|
| Small (555 chunks) | **13x** | 19x | 42x | 59x |
| Large (19k chunks) | **80x** | 129x | 279x | **595x** |

Token savings **scale with project size** — grep noise grows linearly (more files contain the keyword), while mempalace-code search stays constant (top-5 semantically relevant chunks regardless of corpus size). These numbers are from a 19k-chunk project; larger codebases would push the ratios higher.

### Retrieval quality

| Benchmark | Score |
|-----------|-------|
| Code retrieval R@5 (MiniLM, 469 chunks) | **95.0%** |
| Code retrieval R@10 | **100%** |

Upstream LongMemEval result (96.6% R@5 on conversations) retained with [methodology caveats](benchmarks/BENCHMARKS.md).

---

<details>
<summary><strong>Installation Details</strong></summary>

```bash
pip install mempalace-code
# or
uv pip install mempalace-code
```

**Bootstrap script** (recommended for servers/CI):

```bash
curl -fsSL https://raw.githubusercontent.com/rergards/mempalace-code/main/scripts/bootstrap.sh | bash
```

**Optional extras:**

```bash
pip install "mempalace-code[treesitter]"  # AST parsing
pip install "mempalace-code[chroma]"      # ChromaDB legacy backend (deprecated)
pip install "mempalace-code[spellcheck]"  # autocorrect for room/wing names
pip install "mempalace-code[dev]"         # pytest + ruff
```

**Requirements:** Python 3.11+. ~80 MB embedding model downloaded once during `mempalace-code init`.

</details>

<details>
<summary><strong>All CLI Commands</strong></summary>

```bash
# Setup
mempalace-code init <dir>                              # initialize rooms
mempalace-code init <dir> --detect-entities            # optional prose entity bootstrap

# Mining
mempalace-code mine <dir>                              # mine code project
mempalace-code mine <dir> --wing myapp                 # tag with wing
mempalace-code mine <dir> --mode convos                # mine conversations
mempalace-code mine <dir> --full                       # force full rebuild
mempalace-code mine <dir> --watch                      # auto-incremental on file changes
mempalace-code mine-all <parent-dir>                   # sync all projects incrementally (one wing per project)
mempalace-code mine-all <parent-dir> --new-only        # only mine projects not yet in the palace

# Watch (multi-project auto-sync)
mempalace-code watch <parent-dir>                      # watch all initialized projects
mempalace-code watch <parent-dir> schedule             # print launchd/cron daemon snippet

# Search
mempalace-code search "query"                          # search everything
mempalace-code search "query" --wing myapp             # scoped to wing
mempalace-code search "query" --room auth              # scoped to room

# Backup & Recovery
mempalace-code backup create                           # create backup (default: <palace_parent>/backups/)
mempalace-code backup list                             # list existing backups
mempalace-code backup schedule --freq daily            # print daily scheduler snippet
mempalace-code restore <archive>                       # restore from backup
mempalace-code export --only-manual                    # JSONL export
mempalace-code import <file>                           # JSONL import
mempalace-code health                                  # probe for fragment corruption
mempalace-code repair --rollback                       # roll back to last working version

# Context
mempalace-code wake-up                                 # L0 + L1 context
mempalace-code wake-up --wing myapp                    # project-scoped
mempalace-code status                                  # palace overview

# Model
mempalace-code fetch-model                             # pre-download for offline use
```

</details>

<details>
<summary><strong>Saving Conversation Context</strong></summary>

Code mining is automatic via `mempalace-code watch`. For conversation context (decisions, discussions, debugging notes), the AI uses MCP tools directly — works with **any agent** (Claude Code, Codex, Cursor, etc.):

1. Wire the MCP server (see [install docs](docs/AGENT_INSTALL.md))
2. Add usage rules to your agent's instructions (CLAUDE.md, system prompt, etc.)
3. The agent calls `mempalace_add_drawer` and `mempalace_diary_write` during sessions

> **Legacy:** Claude Code also supports optional [auto-save hooks](hooks/README.md) that remind the AI to save at fixed intervals. These are redundant if MCP + usage rules are set up.

</details>

<details>
<summary><strong>Project Structure</strong></summary>

```
mempalace/
├── mempalace_code/
│   ├── cli.py              ← CLI entry point
│   ├── mcp_server.py       ← MCP server (28 tools)
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
└── tests/                  ← 1312 tests
```

</details>

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
python -m pytest tests/ -x -q    # full suite, all local, no network
```

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

<!-- Link Definitions -->
[version-shield]: https://img.shields.io/badge/version-1.7.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/rergards/mempalace-code/releases
[python-shield]: https://img.shields.io/badge/python-3.11+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-Apache_2.0-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/rergards/mempalace-code/blob/main/LICENSE
