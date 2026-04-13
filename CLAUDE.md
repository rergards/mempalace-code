# mempalace — Project Guide for Claude Code

## Stack

- **Python** 3.9+ (supports 3.9–3.12)
- **Storage**: LanceDB (core, crash-safe vector DB — no server required)
- **Embeddings**: sentence-transformers (local, no API key)
- **Config**: PyYAML
- **Linting / formatting**: Ruff
- **Tests**: pytest
- **Package manager**: uv (preferred) or pip

## Dev Setup

```bash
# With uv (preferred)
uv pip install -e ".[dev]"

# With pip
pip install -e ".[dev]"
```

No Docker required. Everything runs locally in a venv or with pipx.

Optional extras:
- `.[chroma]` — ChromaDB legacy backend (deprecated; use LanceDB)
- `.[spellcheck]` — autocorrect support for room/wing names

## Running Tests

**Important**: Use the Python from your mempalace virtualenv (pipx venv, `.venv`, etc.), not the system Python which may lack dev deps.

```bash
# Full suite (stop on first failure)
python -m pytest tests/ -x -q

# Per-module
python -m pytest tests/test_storage.py -v
python -m pytest tests/test_mcp_server.py -v
python -m pytest tests/test_miner.py -v
python -m pytest tests/test_convo_miner.py -v
```

## Linting / Formatting

```bash
# Check
ruff check mempalace/ tests/

# Format check
ruff format --check mempalace/ tests/

# Auto-fix lint
ruff check --fix mempalace/ tests/

# Auto-fix format
ruff format mempalace/ tests/
```

Line length: 100. Target: py39. Quote style: double.

## Key Modules

| Module | Purpose |
|--------|---------|
| `storage.py` | LanceDB vector storage — add, search, delete drawers |
| `miner.py` | Code project miner — walks source files, extracts drawers |
| `convo_miner.py` | Conversation miner — ingests Claude/ChatGPT/Slack exports |
| `searcher.py` | Semantic search — query palace with optional wing/room filters |
| `knowledge_graph.py` | Temporal KG — entity-relationship triples with validity windows |
| `layers.py` | Tiered context loading — L0/L1/L2/L3 wake-up layers for local models |
| `palace_graph.py` | Graph traversal and tunnel detection across wings/rooms |
| `mcp_server.py` | MCP server — exposes palace tools to Claude Code and other MCP clients |
| `cli.py` | `mempalace` CLI entry point — init, mine, search, wake-up |

## Architecture Principles

1. **Verbatim-first** — store content exactly as provided; do not summarize or compress drawers.
2. **Local-first** — no external APIs required; all embeddings run on-device via sentence-transformers.
3. **Zero-API-by-default** — LanceDB and sentence-transformers work offline; API integrations are opt-in.

## Storage Backend

- **LanceDB** is the core backend (installed by default via `lancedb>=0.17`).
- **ChromaDB** is a legacy optional backend: install with `.[chroma]`. It is deprecated and will be removed in a future major version.

## Embedding Model Policy

- **Current default**: `all-MiniLM-L6-v2` (384d, sentence-transformers).
- **No-regression rule**: any embedding model change must match or beat MiniLM on LongMemEval R@5 (text retrieval). Text quality is non-negotiable — this is a code-first fork but natural language search (conversations, commits, decisions) must not degrade.
- **No code-only models**: CodeBERT, UniXcoder, etc. improve code at the expense of prose. Only general-purpose sentence-transformers that handle both are candidates.
- **Gate**: model upgrades are gated behind A/B benchmark results.

### Benchmark Results — 2026-04-09 (BENCH-EMBED-AB)

Code retrieval on the mempalace repo (20 known-answer queries, 469 chunks):

| Model              | R@5   | R@10  | Embed(s) | Query(ms) | Index(MB) |
|--------------------|-------|-------|----------|-----------|-----------|
| all-MiniLM-L6-v2   | 0.950 | 1.000 | 15.2     | 15.9      | 17.0      |
| all-mpnet-base-v2  | 0.900 | 1.000 | 47.5     | 30.5      | 17.7      |
| nomic-embed-text-v1.5 | 0.950 | 1.000 | 85.4  | 45.8      | 17.7      |

Per-category R@5:

| Model              | architecture | class_lookup | cross_file | function_lookup |
|--------------------|:---:|:---:|:---:|:---:|
| all-MiniLM-L6-v2   | 0.800 | 1.000 | 1.000 | 1.000 |
| all-mpnet-base-v2  | 0.600 | 1.000 | 1.000 | 1.000 |
| nomic-embed-text-v1.5 | 1.000 | 1.000 | 1.000 | 0.833 |

**Recommendation: minilm remains default.**

- mpnet regresses on code R@5 (0.900 vs 0.950) while being 3× slower to embed and 2× slower at query. Eliminated.
- nomic ties minilm on code R@5 (0.950) but is 5.6× slower to embed and 2.9× slower at query, with a 550 MB model vs 80 MB. No net gain.
- Text-gate (LongMemEval) evidence was not collected — prerequisites missing (`benchmarks/data/longmemeval_s_cleaned.json` not present, `fastembed` not installed). Any future upgrade must pass the text gate before switching.
- Full results: `benchmarks/results_embed_ab_2026-04-09.json`.

## Git Workflow

- **Branch naming**: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`
- **Conventional commits**:
  - `feat:` — new feature or capability
  - `fix:` — bug fix
  - `docs:` — documentation only
  - `test:` — test additions or changes
  - `bench:` — benchmarks
  - `chore:` — maintenance, deps, tooling
- **No force-push to `main`**.
- PR merges go through the `feat/*` → `main` flow; squash if the branch is noisy.
