<div align="center">

<img src="assets/mempalace_banner.jpg" alt="mempalace-code" width="640">

# mempalace-code

**Offline-first AI memory for coding** — vectors, temporal facts, and conversations in one palace. The embedding model ships as part of the install; after setup, nothing leaves your machine.

<br>

Mine your codebase into a searchable palace. Your AI assistant finds architecture decisions, API patterns, and past debugging sessions — across sessions and projects — without re-reading every file.

> Built by a developer for developers — no celebrity endorsement, no marketing claims,
> just a local-first memory system that does what the README says it does.

[![][version-shield]][release-link]
[![][python-shield]][python-link]
[![][license-shield]][license-link]

<br>

[Quick Start](#quick-start) · [The Palace](#the-palace) · [MCP Tools](#mcp-server) · [Knowledge Graph](#knowledge-graph) · [Benchmarks](#benchmarks)

<br>

<table>
<tr>
<td align="center"><strong>LanceDB</strong><br><sub>Crash-safe vector storage<br>no server required</sub></td>
<td align="center"><strong>18 MCP tools</strong><br><sub>Native Claude Code integration<br>search, store, traverse</sub></td>
<td align="center"><strong>$0</strong><br><sub>No subscription<br>No cloud. Local only.</sub></td>
</tr>
</table>

</div>

---

## Quick Start

```bash
pip install mempalace-code

# Index a code project
mempalace init ~/projects/myapp
mempalace mine ~/projects/myapp

# Connect to Claude Code — one-time setup
claude mcp add mempalace -- python -m mempalace.mcp_server

# Search from the CLI
mempalace search "rate limiting implementation"
mempalace search "why did we choose Postgres"
```

After `mine`, your AI assistant can call `mempalace_search` automatically during conversations. No manual search commands needed.

Installing mempalace for a coding agent? See [`docs/AGENT_INSTALL.md`](docs/AGENT_INSTALL.md) — a decision-tree runbook that handles install, MCP wiring, verification, and optionally injects usage rules into your CLAUDE.md so the assistant knows when to search, when to store, and how to organize memories.

---

## Why mempalace-code

Every architecture decision, debugging session, and design discussion lives in your codebase and chat history. Between sessions, all of that context disappears. mempalace-code indexes it once into a crash-safe local vector store, then makes it findable in milliseconds — using [13–80x fewer tokens](docs/BENCH_TOKEN_DELTA.md) than grep + read.

**What it indexes:**

- Code files — functions, classes, modules (Python, TypeScript/JS, Go, Markdown)
- Conversation exports — Claude, ChatGPT, Slack exports
- Decisions, architecture notes, and anything else you mine

**How you use it:**

After setup, your AI assistant calls mempalace tools automatically. Ask Claude "how did we handle auth?" and it queries the palace without you typing a search command.

---

## The Palace

mempalace-code organizes everything into a navigable structure — the same mental model ancient Greek orators used to memorize speeches by placing ideas in rooms of an imaginary building.

```
  ┌─────────────────────────────────────────────────────────────┐
  │  WING: myapp                                               │
  │                                                            │
  │    ┌──────────┐  ──hall──  ┌──────────┐                    │
  │    │  backend │            │  frontend│                    │
  │    └────┬─────┘            └──────────┘                    │
  │         │                                                  │
  │         ▼                                                  │
  │    ┌──────────┐      ┌──────────┐                          │
  │    │  Closet  │ ───▶ │  Drawer  │                          │
  │    └──────────┘      └──────────┘                          │
  └─────────┼──────────────────────────────────────────────────┘
            │
          tunnel
            │
  ┌─────────┼──────────────────────────────────────────────────┐
  │  WING: otherapp                                            │
  │         │                                                  │
  │    ┌────┴─────┐  ──hall──  ┌──────────┐                    │
  │    │  backend │            │  infra   │                    │
  │    └────┬─────┘            └──────────┘                    │
  │         │                                                  │
  │         ▼                                                  │
  │    ┌──────────┐      ┌──────────┐                          │
  │    │  Closet  │ ───▶ │  Drawer  │                          │
  │    └──────────┘      └──────────┘                          │
  └─────────────────────────────────────────────────────────────┘
```

**Wings** — a project or person. As many as you need.
**Rooms** — topics within a wing: `backend`, `auth`, `deploy`, `decisions`.
**Halls** — connections between related rooms within the same wing.
**Tunnels** — connections between wings. When `auth` appears in two projects, a tunnel links them.
**Drawers** — verbatim content. Never summarized, never rewritten.

When the same room name appears across wings, mempalace-code creates a tunnel automatically. Searching `auth` in one project surfaces related `auth` content from others.

---

## Language-Aware Code Mining

`mempalace mine` walks your source tree and chunks files at structural boundaries — not arbitrary line counts.

| Language | Chunking strategy |
|----------|------------------|
| Python (`.py`) | Functions, classes, methods |
| TypeScript / JavaScript (`.ts`, `.tsx`, `.js`, `.jsx`) | Functions, classes, exports, import groups |
| Go (`.go`) | Functions, types |
| Markdown / plain text (`.md`, `.txt`) | Heading sections, then paragraphs |
| Other | Adaptive line-count fallback |

Leading comments and docstrings are attached to the declaration they document. Import groups are collected as a single chunk. Small fragments are merged with neighbors to stay above a minimum useful size.

```bash
mempalace mine ~/projects/myapp           # all supported file types
mempalace mine ~/projects/myapp --wing myapp   # tag with a specific wing
```

---

## MCP Server

```bash
claude mcp add mempalace -- python -m mempalace.mcp_server
```

### 18 Tools

**Palace — read**

| Tool | What |
|------|------|
| `mempalace_status` | Palace overview — total drawers, wings, rooms |
| `mempalace_list_wings` | All wings with drawer counts |
| `mempalace_list_rooms` | Rooms within a wing |
| `mempalace_get_taxonomy` | Full wing → room → count tree |
| `mempalace_search` | Semantic search with optional wing/room filters |
| `mempalace_check_duplicate` | Check before filing — 0.9 similarity threshold |

**Palace — write**

| Tool | What |
|------|------|
| `mempalace_add_drawer` | File verbatim content into a wing/room |
| `mempalace_delete_drawer` | Remove a drawer by ID |

**Knowledge Graph**

| Tool | What |
|------|------|
| `mempalace_kg_query` | Entity relationships with time filtering |
| `mempalace_kg_add` | Add a fact with optional validity window |
| `mempalace_kg_invalidate` | Mark a fact as no longer true |
| `mempalace_kg_timeline` | Chronological story of an entity |
| `mempalace_kg_stats` | Graph overview — entities, triples, relationship types |

**Navigation**

| Tool | What |
|------|------|
| `mempalace_traverse` | Walk the graph from a room across wings |
| `mempalace_find_tunnels` | Find rooms bridging two wings |
| `mempalace_graph_stats` | Graph connectivity overview |

**Agent Diary**

| Tool | What |
|------|------|
| `mempalace_diary_write` | Write a diary entry for an agent |
| `mempalace_diary_read` | Read recent diary entries for an agent |

The AI learns the memory protocol automatically from the `mempalace_status` response on first wake-up. No manual configuration.

---

## Knowledge Graph

Temporal entity-relationship triples — local SQLite, no Neo4j, no cloud.

```python
from mempalace.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()
kg.add_triple("Kai", "works_on", "myapp", valid_from="2025-06-01")
kg.add_triple("myapp", "uses", "Postgres", valid_from="2025-11-03")
kg.add_triple("myapp", "uses", "Redis", valid_from="2026-01-15")

# What does myapp use?
kg.query_entity("myapp")
# → [myapp → uses → Postgres (current), myapp → uses → Redis (current)]

# What was true in December 2025?
kg.query_entity("myapp", as_of="2025-12-01")
# → [myapp → uses → Postgres (active)]

# Expire a fact when it changes
kg.invalidate("myapp", "uses", "Postgres", ended="2026-03-01")
```

**Good KG candidates:** version numbers, team assignments, tech stack decisions, deployment states, deadlines.

---

## Memory Layers

| Layer | What | Size | When loaded |
|-------|------|------|-------------|
| **L0** | Identity — project context, AI persona | ~50 tokens | Always |
| **L1** | Critical facts — team, key decisions | ~120 tokens | Always |
| **L2** | Room recall — recent sessions, current topic | On demand | When topic comes up |
| **L3** | Deep search — semantic query across all drawers | On demand | When explicitly asked |

```bash
mempalace wake-up              # emit L0 + L1 context (~170 tokens)
mempalace wake-up --wing myapp # project-scoped
```

For local models (Llama, Mistral) that don't speak MCP, pipe `wake-up` output into the system prompt:

```bash
mempalace wake-up > context.txt
# Paste context.txt into your local model's system prompt
```

---

## Auto-Save Hooks

Two Claude Code hooks that save memories automatically:

**Stop Hook** — after each response, triggers a structured save of topics, decisions, and code changes.

**PreCompact Hook** — fires before context compression. Emergency save before the window shrinks.

```json
{
  "hooks": {
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "/path/to/mempalace/hooks/mempal_save_hook.sh"}]}],
    "PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "/path/to/mempalace/hooks/mempal_precompact_hook.sh"}]}]
  }
}
```

---

## Conversation Mining

Mining conversation exports is a secondary capability — useful for importing existing Claude/ChatGPT/Slack history.

```bash
mempalace mine ~/chats/ --mode convos              # Claude/ChatGPT/Slack exports
mempalace mine ~/chats/ --mode convos --wing myapp # tag to a specific project wing
```

Five chat export formats are supported (Claude, ChatGPT, Slack, and two others) — `normalize.py` converts them to a standard transcript before chunking.

---

## This Fork vs Upstream

This fork exists because the original project shipped claims that
[didn't hold up to scrutiny](https://github.com/milla-jovovich/mempalace/issues/27).
We inherited the good parts — the palace metaphor, the MCP integration, the
LongMemEval harness — and rebuilt the foundation. Every claim in this README is
backed by code you can read, tests you can run, and benchmarks with documented
methodology.

| What upstream ships | What this fork ships |
|---|---|
| ChromaDB backend — [silently deletes palace data on version bump](https://github.com/milla-jovovich/mempalace/issues/469) | LanceDB — crash-safe columnar Arrow storage, no version-cliff risk |
| "No internet after install" — [false, downloads ONNX model silently](https://github.com/milla-jovovich/mempalace/issues/524) | `mempalace init` downloads the model explicitly during setup; after that, fully offline |
| "100% R@5 with Haiku rerank" — [unverifiable, retracted by upstream](https://github.com/milla-jovovich/mempalace/issues/27) | Number removed. Raw R@5 kept with methodology caveats |
| AAAK "lossless compression" — [actually loses 12.4pp retrieval quality](https://github.com/milla-jovovich/mempalace/issues/27) | AAAK labeled as experimental lossy format, not storage default |
| ~30% test coverage at launch | 419 tests, every feature acceptance-gated |
| No backup/export, no recovery path | `mempalace export --only-manual` + `mempalace import` |
| No incremental re-mining | Content-hash incremental: only changed files re-chunked |
| No code-search tool | `mempalace_code_search` — filter by language, symbol, file glob |

For the complete audit trail of what the fork inherits, negates, or leaves
out-of-scope, see [`docs/UPSTREAM_HARDENING.md`](docs/UPSTREAM_HARDENING.md).

---

## Installation

```bash
pip install mempalace-code
# or with uv
uv pip install mempalace-code
```

**Bootstrap script** (recommended for servers and CI — creates an isolated venv, upgrades pip, avoids system-level conflicts):

```bash
# From PyPI (default)
curl -fsSL https://raw.githubusercontent.com/rergards/mempalace-code/main/scripts/bootstrap.sh | bash

# From git (if not yet on PyPI)
curl -fsSL https://raw.githubusercontent.com/rergards/mempalace-code/main/scripts/bootstrap.sh | MEMPALACE_SOURCE=git bash

# Custom venv location
MEMPALACE_VENV=/opt/mempalace/venv bash scripts/bootstrap.sh
```

The script installs into `~/.mempalace/venv` and symlinks the binary to `~/.local/bin/mempalace`.

**Core dependencies** (installed automatically):

```
lancedb>=0.17
sentence-transformers>=2.2
pyyaml>=6.0
```

**Optional extras:**

```bash
pip install "mempalace-code[chroma]"      # ChromaDB legacy backend (deprecated)
pip install "mempalace-code[spellcheck]" # autocorrect for room/wing names
pip install "mempalace-code[treesitter]" # tree-sitter AST parser (Python 3.10+; TS/JS on 3.9+)
pip install "mempalace-code[dev]"        # pytest + ruff (development)
```

**Requirements:** Python 3.9+. `mempalace init` downloads the embedding model (~80 MB) once during setup as part of the project install. After that, mining, searching, and the knowledge graph run entirely offline — no API keys, no cloud calls, no network access needed.

> **Note:** Ubuntu 22.04 and similar distros ship pip 22.x, which cannot build hatchling metadata. The bootstrap script handles this automatically. If installing manually, run `python3 -m pip install --upgrade pip` first.

---

## All Commands

```bash
# Setup
mempalace init <dir>                              # initialize palace + mine the directory

# Mining
mempalace mine <dir>                              # mine code project (Python, TS/JS, Go, Markdown)
mempalace mine <dir> --wing myapp                 # tag with a wing name
mempalace mine <dir> --mode convos                # mine conversation exports
mempalace mine <dir> --mode convos --wing myapp   # conversation exports, tagged

# Search
mempalace search "query"                          # search everything
mempalace search "query" --wing myapp             # within a wing
mempalace search "query" --room auth              # within a room

# Memory stack
mempalace wake-up                                 # emit L0 + L1 context
mempalace wake-up --wing myapp                    # project-scoped

# Status
mempalace status                                  # palace overview
```

All commands accept `--palace <path>` to override the default location (`~/.mempalace/palace`).

---

## Project Structure

```
mempalace/
├── README.md
├── mempalace/
│   ├── cli.py                 ← CLI entry point
│   ├── mcp_server.py          ← MCP server (19 tools)
│   ├── storage.py             ← LanceDB vector storage
│   ├── miner.py               ← code project ingest (language-aware chunking)
│   ├── convo_miner.py         ← conversation ingest
│   ├── searcher.py            ← semantic search
│   ├── knowledge_graph.py     ← temporal entity graph (SQLite)
│   ├── palace_graph.py        ← room navigation graph
│   ├── layers.py              ← 4-layer memory stack
│   └── ...
├── benchmarks/                ← reproducible benchmark runners
│   ├── BENCHMARKS.md          ← full results and methodology
│   └── ...
├── hooks/                     ← Claude Code auto-save hooks
├── examples/                  ← usage examples and MCP setup guide
└── tests/
```

---

## Benchmarks

Upstream benchmark results (ChromaDB, conversation workloads — see [benchmarks/BENCHMARKS.md](benchmarks/BENCHMARKS.md)):

| Benchmark | Mode | Score |
|-----------|------|-------|
| LongMemEval R@5 | Raw verbatim (ChromaDB) | 96.6%[^1] |

[^1]: Upstream-reported result. The methodology is contested: with a corpus ≤ 50 documents, `n_results=min(n_results, len(corpus))` causes R@k evaluation to degenerate into ranking over a fully-retrieved set, making the score a near-ceiling artefact rather than a retrieval difficulty measurement (upstream issues #27, #524).

These numbers apply to the conversation retrieval use case, not code-mining. Code-mining benchmarks are tracked in the backlog (BENCH-EMBED-AB).

See also: [docs/UPSTREAM_HARDENING.md](docs/UPSTREAM_HARDENING.md) for a full audit of upstream benchmark claims.

---

## AAAK Dialect (experimental, disabled by default)

AAAK is an inherited **lossy** compressed memory format from upstream. Independent measurement shows a retrieval regression from 96.6% to 84.2% R@5 on LongMemEval (upstream issue #27). It is not exposed in the default MCP tool set and not used for storage. The code remains in the codebase for future experimentation.

---

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and guidelines.

### Test Coverage

419 tests across 15 test files. Every feature is acceptance-gated — no code
merges to main without passing tests. Run the full suite:

```bash
python -m pytest tests/ -x -q    # ~8 minutes, all local, no network needed
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
