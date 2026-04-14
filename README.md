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
<td align="center"><strong>Tree-sitter AST Parsing</strong><br><sub>Chunks at function boundaries<br>not arbitrary line counts</sub></td>
<td align="center"><strong>18 MCP Tools</strong><br><sub>Native Claude Code integration<br>search, store, traverse</sub></td>
<td align="center"><strong>Temporal Knowledge Graph</strong><br><sub>Facts that change over time<br>with validity windows</sub></td>
</tr>
<tr>
<td align="center"><strong>595x Token Savings</strong><br><sub>measured peak · median 80x<br><a href="docs/BENCH_TOKEN_DELTA.md">scales with project size</a></sub></td>
<td align="center"><strong>Cross-Project Tunnels</strong><br><sub>Search <code>auth</code> in one project<br>find it everywhere</sub></td>
<td align="center"><strong>527 Tests · $0 Cost</strong><br><sub>Every feature acceptance-gated<br>fully offline after install</sub></td>
</tr>
</table>

</div>

---

## Quick Start

```bash
pip install mempalace-code

mempalace init ~/projects/myapp       # index your codebase
claude mcp add mempalace -- python -m mempalace.mcp_server  # connect to Claude
```

That's it. Ask Claude *"how did we handle auth?"* and it searches your palace automatically.

> Installing for a coding agent? See [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) — handles install, MCP wiring, verification, and injects usage rules into CLAUDE.md.

---

## How It Actually Works

You write code. You make decisions. You debug things. Between sessions, all that context vanishes.

mempalace-code **indexes it once** into a local vector store, then your AI finds it in milliseconds — using [595x fewer tokens](docs/BENCH_TOKEN_DELTA.md) than grep + read at measured peak (median 80x on a 19k-chunk project, and it keeps scaling). Think of it as `git log` for everything that *isn't* in the code: the *why*, the discussions, the dead ends, the decisions.

**What gets indexed:**
- Code files — functions, classes, modules (Python, TypeScript/JS, Go, Rust, C/C++, Markdown)
- Conversation exports — Claude, ChatGPT, Slack
- Architecture notes, decisions, anything you store manually

**How you use it:** After setup, your AI calls mempalace tools automatically. You don't type search commands.

---

## Features

### Language-Aware Code Mining

`mempalace mine` walks your source tree and chunks at **structural boundaries** — functions, classes, methods — not arbitrary line counts. Leading comments and docstrings stay attached to their declarations.

| Language | Strategy | AST Support |
|----------|----------|:-----------:|
| Python | Functions, classes, methods, decorators | Tree-sitter |
| TypeScript / JavaScript / TSX / JSX | Functions, classes, exports, imports | Tree-sitter |
| Go | Functions, types, methods, interfaces | Tree-sitter |
| Rust | Functions, structs, enums, traits, impls | Tree-sitter |
| C / C++ | Functions, structs, enums, classes | Regex |
| Markdown / plain text | Heading sections, paragraphs | — |
| YAML / JSON / TOML | Adaptive line-count | — |

Tree-sitter is optional (`pip install "mempalace-code[treesitter]"`). Without it, all languages fall back to regex boundary detection — still structural, just less precise.

```bash
mempalace mine ~/projects/myapp                  # all supported file types
mempalace mine ~/projects/myapp --wing myapp     # tag with a specific wing
mempalace mine ~/chats/ --mode convos            # mine conversation exports
```

Mining is **incremental** by default — content-hash based, only changed files are re-chunked. Use `--full` to force a rebuild.

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

### MCP Server — 18 Tools

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

<details>
<summary><strong>Palace — Read</strong></summary>

| Tool | What |
|------|------|
| `mempalace_status` | Palace overview — total drawers, wings, rooms |
| `mempalace_list_wings` | All wings with drawer counts |
| `mempalace_list_rooms` | Rooms within a wing |
| `mempalace_get_taxonomy` | Full wing → room → count tree |
| `mempalace_search` | Semantic search with optional wing/room filters |
| `mempalace_code_search` | Filter by language, symbol name/type, file glob |
| `mempalace_check_duplicate` | Similarity check before filing (0.9 threshold) |

</details>

<details>
<summary><strong>Palace — Write</strong></summary>

| Tool | What |
|------|------|
| `mempalace_add_drawer` | File verbatim content into a wing/room |
| `mempalace_delete_drawer` | Remove a drawer by ID |
| `mempalace_delete_wing` | Delete all drawers in a wing |

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
<summary><strong>Navigation & Diary</strong></summary>

| Tool | What |
|------|------|
| `mempalace_traverse` | Walk the graph from a room across wings |
| `mempalace_find_tunnels` | Find rooms bridging two wings |
| `mempalace_graph_stats` | Graph connectivity overview |
| `mempalace_diary_write` | Write a session journal entry |
| `mempalace_diary_read` | Read recent diary entries |

</details>

The AI learns the memory protocol automatically from the `mempalace_status` response. No manual configuration.

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

---

### Memory Layers

| Layer | What | When |
|-------|------|------|
| **L0** | Identity — project, persona | Always loaded (~50 tokens) |
| **L1** | Critical facts — team, decisions | Always loaded (~120 tokens) |
| **L2** | Room recall — current topic | On demand |
| **L3** | Deep search — full semantic query | On demand |

```bash
mempalace wake-up --wing myapp    # emit L0 + L1 context (~170 tokens)
```

For local models (Llama, Mistral) that don't speak MCP, pipe `wake-up` into the system prompt.

---

### Backup & Restore

```bash
mempalace backup                                  # → palace_backup_2026-04-14.tar.gz
mempalace backup --output ~/safe/my_palace.tar.gz  # custom path
mempalace restore palace_backup_2026-04-14.tar.gz  # restore
mempalace restore backup.tar.gz --force            # overwrite existing
```

Also available: `mempalace export --only-manual` for JSONL export of manually-stored drawers.

---

## This Fork vs Upstream

This is a code-first fork of [milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace). We inherited the good parts — the palace metaphor, the MCP integration, the LongMemEval harness — and rebuilt what was broken. Every claim here is backed by code, tests, and documented benchmarks.

| Upstream | This fork |
|---|---|
| ChromaDB — [silently deletes data on version bump](https://github.com/milla-jovovich/mempalace/issues/469) | LanceDB — crash-safe Arrow storage, no version-cliff |
| "No internet after install" — [false](https://github.com/milla-jovovich/mempalace/issues/524) | `mempalace init` downloads model explicitly; fully offline after |
| "100% R@5" — [unverifiable](https://github.com/milla-jovovich/mempalace/issues/27) | Number removed. Methodology caveats documented |
| ~30% test coverage | 527 tests, every feature acceptance-gated |
| No backup, no recovery | `backup` / `restore` / `export` / `import` |
| No incremental mining | Content-hash incremental: only changed files re-chunked |
| No code-search | `code_search` — filter by language, symbol, glob |
| Line-count chunking | Tree-sitter AST + regex structural chunking |

Full audit: [`docs/UPSTREAM_HARDENING.md`](docs/UPSTREAM_HARDENING.md).

---

## Benchmarks

### Token savings vs grep + read ([full methodology](docs/BENCH_TOKEN_DELTA.md))

| Project size | Median | Mean | P95 | Peak |
|-------------|--------|------|-----|------|
| Small (555 chunks) | **13x** | 19x | 42x | 59x |
| Large (19k chunks) | **80x** | 129x | 279x | **595x** |

Token savings **scale with project size** — grep noise grows linearly (more files contain the keyword), while mempalace search stays constant (top-5 semantically relevant chunks regardless of corpus size). These numbers are from a 19k-chunk project; larger codebases would push the ratios higher.

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
pip install "mempalace-code[treesitter]"  # AST parsing (Python 3.10+; TS/JS on 3.9+)
pip install "mempalace-code[chroma]"      # ChromaDB legacy backend (deprecated)
pip install "mempalace-code[spellcheck]"  # autocorrect for room/wing names
pip install "mempalace-code[dev]"         # pytest + ruff
```

**Requirements:** Python 3.9+. ~80 MB embedding model downloaded once during `mempalace init`.

</details>

<details>
<summary><strong>All CLI Commands</strong></summary>

```bash
# Setup
mempalace init <dir>                              # initialize + mine

# Mining
mempalace mine <dir>                              # mine code project
mempalace mine <dir> --wing myapp                 # tag with wing
mempalace mine <dir> --mode convos                # mine conversations
mempalace mine <dir> --full                       # force full rebuild

# Search
mempalace search "query"                          # search everything
mempalace search "query" --wing myapp             # scoped to wing
mempalace search "query" --room auth              # scoped to room

# Backup
mempalace backup                                  # create backup archive
mempalace restore <archive>                       # restore from backup
mempalace export --only-manual                    # JSONL export
mempalace import <file>                           # JSONL import

# Context
mempalace wake-up                                 # L0 + L1 context
mempalace wake-up --wing myapp                    # project-scoped
mempalace status                                  # palace overview

# Model
mempalace fetch-model                             # pre-download for offline use
```

</details>

<details>
<summary><strong>Auto-Save Hooks</strong></summary>

Two Claude Code hooks for automatic memory saving:

- **Stop Hook** — after each response, saves topics, decisions, and code changes
- **PreCompact Hook** — emergency save before context compression

```json
{
  "hooks": {
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "/path/to/mempalace/hooks/mempal_save_hook.sh"}]}],
    "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "/path/to/mempalace/hooks/mempal_precompact_hook.sh"}]}]
  }
}
```

</details>

<details>
<summary><strong>Project Structure</strong></summary>

```
mempalace/
├── mempalace/
│   ├── cli.py              ← CLI entry point
│   ├── mcp_server.py       ← MCP server (18 tools)
│   ├── storage.py          ← LanceDB vector storage
│   ├── miner.py            ← language-aware code chunking
│   ├── convo_miner.py      ← conversation ingest
│   ├── searcher.py         ← semantic search
│   ├── knowledge_graph.py  ← temporal entity graph (SQLite)
│   ├── palace_graph.py     ← room navigation graph
│   └── layers.py           ← 4-layer memory stack
├── benchmarks/             ← reproducible benchmark runners
├── hooks/                  ← Claude Code auto-save hooks
├── examples/               ← usage examples
└── tests/                  ← 527 tests
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
[version-shield]: https://img.shields.io/badge/version-1.0.0-4dc9f6?style=flat-square&labelColor=0a0e14
[release-link]: https://github.com/rergards/mempalace-code/releases
[python-shield]: https://img.shields.io/badge/python-3.9+-7dd8f8?style=flat-square&labelColor=0a0e14&logo=python&logoColor=7dd8f8
[python-link]: https://www.python.org/
[license-shield]: https://img.shields.io/badge/license-Apache_2.0-b0e8ff?style=flat-square&labelColor=0a0e14
[license-link]: https://github.com/rergards/mempalace-code/blob/main/LICENSE
