# mempalace — Agent Guide

## 0. Rule Zero — smallest justified solution

Before non-trivial architecture, implementation, review, delegated writer prompts,
or operational mutation, apply this decision filter. It has no categorical ban on
implementation forms: choose the lowest total complexity that meets current
acceptance, correctness, and reversibility.

- State the outcome and acceptance. Find implementations and owners by behavior.
  Compare delete/simplify, extend/replace, a same-owner module, and any relevant
  architecture boundary using paths/lines, owners, interfaces/state, tests,
  rollout/rollback, operations, and removal cost. Record evidence and the
  cheapest decisive falsifier.
- DRY keeps one responsibility and owner; reuse when the comparison wins. KISS
  minimizes end-to-end complexity, not files or lines. YAGNI serves current
  acceptance only. Remove superseded copies, parallel owners, and temporary
  artifacts. Use build-versus-buy for a substantial shared capability and count
  build, integration, operation, migration, lock-in, and removal costs.
- The drunk-user/LLM path states current status, one action, authority, and one
  recovery command; it remains safe under stale context, malformed input,
  retries, duplicates, and reordered actions.
- A FAIL or decision-critical UNKNOWN blocks only its dependent action. Refresh,
  narrow, or report the blocker; unrelated work continues explicitly.
- A same-owner module or abstraction is allowed for distinct responsibility when
  comparison proves lower complexity, clearer ownership, and safer lifecycle. A
  new service, state owner/store, durable contract, or live mutation route needs
  explicit architecture/operations approval; build-versus-buy evidence is required
  only for a substantial shared capability or new architecture boundary.
- Size thresholds are review signals only. They may trigger responsibility,
  readability, ownership, and testability review; no threshold alone mandates
  extraction, splitting, or approval.
- Changing implementation path or shape within the same deliverable requires
  replanning/review. User approval is required only when deliverable, repo/target,
  authority, acceptance, irreversible/live effect, architecture/ownership boundary,
  or a user-fixed path changes.
- Repository rules may add serialization, commands, gates, sources of truth, and
  stricter safety constraints; those local mechanisms are not universal semantics.

**Release credential boundary.** Release preparation, qualification, admission,
and publication gates must never execute external AI clients such as `codex`,
`claude`, or `gemini`; run their authentication commands or provider/model calls;
or read, copy, inspect, require, or transmit user credentials, API keys, OAuth
tokens, keychains, or paid-account state. Verify MemPalace with its local CLI,
credential-free stdio MCP protocol checks, installed-package behavior, and
credential-free hosted workflows. An optional interoperability exercise with an
AI client requires separate explicit owner authorization, runs outside the
release gate, and cannot block a release.

**Commit attribution boundary.** Commits in this repository must not contain a
Claude `Co-Authored-By` trailer. Configure automation to omit it; do not add it
and clean it up later.

## Stack

- **Python** 3.11+ (supports 3.11–3.14)
- **Storage**: LanceDB (core, crash-safe vector DB — no server required)
- **Embeddings**: FastEmbed/ONNX by default; SentenceTransformer only in `[custom-models]`
- **Config**: PyYAML
- **Linting / formatting / typing**: Ruff + Pyright
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

- `.[custom-models]` — arbitrary SentenceTransformer models; follow `docs/OFFLINE_USAGE.md`
- `.[dev]` — test, lint, type-check, build, and release tooling
- `.[spellcheck]` — autocorrect support for room/wing names
- `.[treesitter]` — Tree-sitter AST parsing
- `.[watch]` — automatic mining on file changes

## Running Tests

**Important**: Use the Python from your mempalace virtualenv (pipx venv, `.venv`, etc.), not the system Python which may lack dev deps.

```bash
# Full suite (stop on first failure)
python -m pytest tests/ -x -q -m "not needs_network"

# Per-module
python -m pytest tests/test_storage.py -v
python -m pytest tests/test_mcp_server.py -v
python -m pytest tests/test_miner.py -v
python -m pytest tests/test_convo_miner.py -v
```

## Linting / Formatting

```bash
# Check
ruff check mempalace_code/ tests/ scripts/

# Format check
ruff format --check mempalace_code/ tests/ scripts/

# Type check (gating in CI — must exit 0)
python -m pyright --pythonpath "$(python -c 'import sys; print(sys.executable)')"

# Auto-fix lint
ruff check --fix mempalace_code/ tests/ scripts/

# Auto-fix format
ruff format mempalace_code/ tests/ scripts/
```

Line length: 100. Target: py311. Quote style: double.

## Key Modules

| Module | Purpose |
|--------|---------|
| `storage.py` | LanceDB vector storage — add, search, delete, health_check, recover |
| `backup.py` | Tarball backup/restore — `mempalace-code backup`, scheduled backups |
| `miner.py` | Code project miner — walks source files, extracts drawers |
| `convo_miner.py` | Conversation miner — ingests Claude/ChatGPT/Slack exports |
| `searcher.py` | Semantic search — query palace with optional wing/room filters |
| `knowledge_graph.py` | Temporal KG — entity-relationship triples with validity windows |
| `layers.py` | Tiered context loading — L0/L1/L2/L3 wake-up layers for local models |
| `palace_graph.py` | Graph traversal and tunnel detection across wings/rooms |
| `mcp_server.py` | MCP server — exposes palace tools to Claude Code and other MCP clients |
| `watcher.py` | File watcher — `watch_and_mine`, `watch_all`, launchd/cron schedule rendering |
| `cli.py` | `mempalace-code` CLI entry point — init, mine, mine-all, watch, search, health, repair, backup |

## Architecture Principles

1. **Verbatim-first** — store content exactly as provided; do not summarize or compress drawers.
2. **Local-first** — no external APIs required; default embeddings run on-device via CPU FastEmbed/ONNX.
3. **Zero-API-by-default** — LanceDB and FastEmbed work offline after explicit model setup.

## Storage Backend

- **LanceDB** is the core backend (installed by default via `lancedb>=0.20`).
- **ChromaDB** support is retired from current packages because every available
  release is advisory-affected. Back up a legacy source palace before upgrading,
  then use the last public bridge release in isolation:
  `uvx --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify`.

## Embedding Model Policy

- **Current default**: `all-MiniLM-L6-v2` (384d, normalized CPU FastEmbed/ONNX).
- **Cache authority**: `$HF_HOME/mempalace-fastembed/all-MiniLM-L6-v2-v1/` plus its
  immutable `.mempalace-model.json` provenance. Recovery is
  `mempalace-code fetch-model` while online.
- **Custom-model boundary**: arbitrary Hugging Face names and local
  SentenceTransformer paths use the explicit `[custom-models]` extra. On CPU-only Linux,
  follow the ordered installation and recovery contour in `docs/OFFLINE_USAGE.md`; only
  that explicit custom-model path may use `trust_remote_code=True`, and canonical MiniLM
  aliases never do.
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

## Operational Lessons

- **Keep this file public-safe.** `AGENTS.md` is the canonical public instruction file; `CLAUDE.md` is only its pointer. Do not write private remotes, hostnames, credentials, local machine paths, customer/project details, incident specifics, or non-public operational history here. Put private or machine-local lessons in a local-only note outside the published tree.
- **Record reusable lessons only when they are public knowledge.** When a session exposes a project gotcha, publish step, verification boundary, or agent-behavior correction, add a concise durable note here only if it is safe for public readers and useful to future contributors.
- **Verify the environment that will actually run the change.** GitHub Actions runtime changes are not proven by Python tests alone. Use local YAML/static checks such as `actionlint`, then verify the real hosted workflow run when action runtime behavior matters.
- **Name the verification boundary.** If a workflow is tag-only or release-only, say that it was syntax-checked and version-checked but not execution-tested unless a real trigger was run. Do not imply full local coverage for hosted-only behavior.
- **Check the intended public release target.** Before publishing, verify the repository, branch, tag, and workflow that public users will see. Do not assume local remote names or private mirrors represent public release truth.
- **Treat release status as multiple independent facts.** Branch Tests, tag-triggered PyPI publish, GitHub Release creation, PyPI version visibility, and any deployment/release-environment status can diverge. Check all of them before calling a release published or latest; if one is red or missing, either fix it now or record the explicit remaining blocker.
- **Test dependency drift with a fresh resolver.** Local `.venv` and `uv.lock` success can hide what GitHub Actions or users get from an unlocked `pip install`. For dependency-sensitive failures, reproduce in a clean pip environment matching the hosted workflow before declaring the tests fixed.
- **Audit dependency targets before raising bounds.** For runtime, dev, and optional extras, check current and target versions against OSV or an equivalent advisory source, then run a resolver-level audit on a fresh environment. Do not raise optional legacy backends into advisory-affected ranges; hold or cap them and backlog the upgrade gate instead.
- **Separate public and local release information.** Public docs may name package ranges, workflow categories, advisory IDs, and reproducible commands. Private remotes, tokens, local paths, hostnames, and non-public incident details belong only in ignored local notes such as `.codex-local/LESSONS.md`.
- **Keep benchmark gates tied to measured baselines.** If a release benchmark fails, reproduce it locally against the pinned fixture, update the CI threshold only to the observed stable baseline, and backlog any desired quality increase separately.
- **Do not call tests "local feature testing."** When asked to test new features locally, run the public CLI/MCP/API behavior itself, not only pytest. For each new feature, exercise at least one success path and one important failure/guard path when safe, record the exact command or request, and name any behavior that was covered only by tests.
- **Exercise real integration surfaces before release claims.** Direct handler calls are useful for MCP compatibility, but they are not the same as a separate stdio MCP client. CLI help is not the same as executing the command. A release-readiness summary must distinguish unit tests, focused integration tests, direct API smoke, real CLI execution, and hosted/daemon behavior that was not run.
- **Clean up smoke-test artifacts immediately.** Real backup, cleanup, and benchmark smokes can create archives, temp palaces, and result JSON. Put them under disposable temp paths, verify success/failure, then remove artifacts or explicitly report what remains.
- **Treat palace disk growth as storage forensics first.** Compare backup size, live storage stats, row counts, and cleanup output before deleting anything. Preserve non-regenerable manual drawers and KG data, stop active writers when needed, use supported cleanup APIs, and verify health/status afterward.
