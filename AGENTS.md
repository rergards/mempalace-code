# mempalace — Agent Guide

## 0. Rule Zero — smallest justified solution

Rule Zero is owned by the "Rule Zero — smallest justified solution" section of the
maintainer's user-level `~/.codex/AGENTS.md`; Claude Code reads the identical
section from `~/.claude/CLAUDE.md`. It is not restated here; every rule in this file
is a local addition to it.

**Release credential boundary.** Release preparation, qualification, admission,
and publication gates must never execute external AI clients such as `codex`,
`claude`, or `gemini`; run their authentication commands or provider/model calls;
or read, copy, inspect, require, or transmit user credentials, API keys, OAuth
tokens, keychains, or paid-account state. Verify MemPalace with its local CLI,
credential-free stdio MCP protocol checks, installed-package behavior, and
credential-free hosted workflows. An optional interoperability exercise with an
AI client requires separate explicit owner authorization, runs outside the
release gate, and cannot block a release.

**Direct functional release boundary.** Before release candidate publication,
run the exact installed wheel through its real CLI and credential-free stdio MCP
interfaces in disposable environments. Reconcile every discovered command and
subcommand, every enabled tool in every profile, and supported runtime extras
with concrete success or documented refusal evidence and relevant failure/retry
postconditions. Help, parser errors, tool listings, handler-only calls and source
pytest counts do not prove functional execution. Missing required coverage blocks
release even when CI passes. Record confirmed problems through backlog-utility
and retain a public-safe acceptance report. Follow `docs/RELEASING.md` section 1a.

**Commit attribution boundary.** Commits in this repository must not contain a
Claude `Co-Authored-By` trailer. Configure automation to omit it; do not add it
and clean it up later.

## Audience and default scope

- The default audience is developers asking questions about repository code.
  Ground answers in current source, tests, repository documentation, and Git history.
- Users preserve valuable project results in repository artifacts and commits.
  Use those version-controlled artifacts as durable project context.
- Inspecting or mining stored user conversations, maintaining diaries, and adding,
  enabling, or repairing conversation-save reminders or persistence guarantees
  require an explicit request for that workflow. An audit finding about an optional
  conversation workflow does not bring it into a code-question task.

## Stack

- **Python** 3.11+ (supports 3.11–3.14)
- **Storage**: LanceDB (core, crash-safe vector DB — no server required)
- **Embeddings**: FastEmbed/ONNX by default; SentenceTransformer only in `[custom-models]`
- **MCP**: the official `mcp` Python SDK
- **Config**: PyYAML
- **Runtime dependencies**: declared once in `[project].dependencies` of `pyproject.toml`
- **Linting / formatting / typing**: Ruff + Pyright
- **Tests**: pytest
- **Package manager**: uv (preferred) or pip

## Dev Setup

```bash
# With uv (preferred)
uv pip install -e ".[dev,spellcheck,treesitter]"

# With pip
pip install -e ".[dev,spellcheck,treesitter]"
```

These are the extras the CI type check installs; with `.[dev]` alone Pyright
reports the Tree-sitter imports as missing.

No Docker required. Everything runs locally in a venv or with pipx.

Optional extras:

- `.[custom-models]` — arbitrary SentenceTransformer models; follow `docs/OFFLINE_USAGE.md`
- `.[dev]` — test, lint, type-check, build, and release tooling
- `.[spellcheck]` — autocorrect helper API (`mempalace_code.spellcheck`); mining never applies it
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
python -m pyright -p pyrightconfig.strict.json

# Auto-fix lint
ruff check --fix mempalace_code/ tests/ scripts/

# Auto-fix format
ruff format mempalace_code/ tests/ scripts/
```

Line length: 100. Target: py311. Quote style: double.

The complete gate set the **Tests** workflow runs on every pull request is listed
once, in `CONTRIBUTING.md` under "Running Tests".

## Key Modules

The main owners under `mempalace_code/`. The full module guide is
`mempalace_code/README.md`.

| Module | Purpose |
|--------|---------|
| `storage.py` | LanceDB vector storage — add, search, delete, health_check, recover |
| `backup.py` | Tarball backup/restore — `mempalace-code backup`, scheduled backups |
| `mining/` | Project miner package — scanning, language detection, chunking, symbols, batching, orchestration; `miner.py` is a compatibility shim |
| `convo_miner.py` | Conversation miner — ingests Claude/ChatGPT/Slack exports |
| `searcher.py` | Semantic search — query palace with optional wing/room filters |
| `knowledge_graph.py` | Temporal KG — entity-relationship triples with validity windows |
| `layers.py` | Tiered context loading — L0/L1/L2/L3 wake-up layers for local models |
| `palace_graph.py` | Graph traversal and tunnel detection across wings/rooms |
| `mcp/` | MCP server package — `registry.py` (the `TOOLS` dict), `dispatch.py`, `runtime.py`, `tools/`; `mcp_server.py` is the public entrypoint shim and `mcp_launcher.py` backs `mempalace-code-mcp` |
| `watcher.py` | File watcher — `watch_and_mine`, `watch_all`, launchd/cron schedule rendering |
| `cli_commands/` | CLI command handlers; `cli.py` is the thin `mempalace-code` entry point and compatibility facade |

## Architecture Principles

1. **Verbatim-first** — store content exactly as provided; do not summarize or compress drawers.
2. **Local-first** — no external APIs required; default embeddings run on-device via CPU FastEmbed/ONNX.
3. **Zero-API-by-default** — LanceDB and FastEmbed work offline after explicit model setup.

## Storage Backend

- **LanceDB** is the core backend (installed by default via `lancedb>=0.20`).
- **ChromaDB** support is retired from current packages because every available
  release is advisory-affected. Back up a legacy source palace before upgrading,
  then use the last public bridge release in isolation:
  `uvx --python 3.12 --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify`.

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
- **No code-only models**: CodeBERT, UniXcoder, etc. improve code at the expense of prose. Only general-purpose sentence-transformers that handle both are candidates.

### Text gate

An embedding model change is gated behind A/B benchmark results
(`benchmarks/embed_ab_bench.py`) and must pass both the code gate (the A/B
code-retrieval results) and the text gate: match or beat MiniLM on LongMemEval R@5
(text retrieval). Text quality is non-negotiable — this is a code-first fork but
natural language search (conversations, commits, decisions) must not degrade. The
only LongMemEval harness, `benchmarks/longmemeval_bench.py`, is the legacy upstream
ChromaDB-based script. It imports `chromadb`, which current packages do not install
and whose available releases carry known advisories, so it runs only in an isolated,
disposable legacy environment. No text baseline has been recorded, so a model change
must first record one there. The gate cannot be skipped: without that environment and
baseline it has not run, and the model change is blocked.

### Historical Benchmark Results — 2026-04-09 (BENCH-EMBED-AB)

Historical record, measured with the fixed 20-query set that
`benchmarks/embed_ab_bench.py` used at the time. It is not comparable with the current
`benchmarks/code_retrieval_bench.py` dataset (symbol and file-only truth,
schema-2 report), and no current baseline has been recorded.
Record a fresh dated baseline on the current dataset before the next model
decision.

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
- [Text-gate](#text-gate) (LongMemEval) evidence was not collected — prerequisites missing (`benchmarks/data/longmemeval_s_cleaned.json` not present, `fastembed` not installed).
- Full results: `benchmarks/results_embed_ab_2026-04-09.json`.

## Git Workflow

- **Two histories**: local `main` is the development trunk; work reaches it from
  topic branches. Public `main` carries one squashed commit per release and advances
  only by fast-forwarding a release candidate built and admitted per
  `docs/RELEASING.md`.
- **Branch naming**: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>` for
  development; `release/vX.Y.Z` (rebuilds `release/vX.Y.Z-rc2`, `-rc3`, …) for
  public release candidates only.
- **Conventional commits**:
  - `feat:` — new feature or capability
  - `fix:` — bug fix
  - `docs:` — documentation only
  - `test:` — test additions or changes
  - `bench:` — benchmarks
  - `chore:` — maintenance, deps, tooling
  - Release candidate commits use the subject `release vX.Y.Z`.
- **No force-push to `main`**.
- Pull requests on GitHub, including Dependabot updates, are never merged on
  public `main`: the next release candidate would silently revert them. Port an
  accepted change into the development trunk, ship it in the next release, then
  close the pull request with a note naming that release.

## Maintainer-Local Tools

The `autopilot` and `backlog-utility` tools are maintainer-local; they are not
distributed with this repository. `/task-plan` and `/task-hardening` admit
executor state only through `autopilot` and stop when it is unavailable.
Current task contracts and planning are owned by `.backlog` (backlog-files/v2).
Read `backlog_context`, `backlog_workset_context`, and `backlog_workset_queue`
through the verified project-bound MCP connection. CLI fallback uses a verified
absolute `backlog-utility` binary with `call --store .backlog --project
mempalace-code --principal <principal> --name <tool> --arguments-file <json>`.
Unavailable or mismatched access means unknown backlog state; never fall back
to active YAML or edit canonical JSON by hand. `docs/BACKLOG.yaml` retains section
metadata; `docs/BACKLOG-archived.yaml` retains historical completion evidence.
Recovery: `<absolute-backlog-utility> validate --store .backlog`.
Edits still require admitted authority and no conflicting writer.

## Operational Lessons

- **Keep this file and public docs public-safe.** `AGENTS.md` is the canonical public instruction file; `CLAUDE.md` is only its pointer. Public docs may name package ranges, workflow categories, advisory IDs, and reproducible commands. Private remotes, hostnames, tokens, credentials, local machine paths, customer/project details, incident specifics, and non-public operational history never go here or in other public docs; put private or machine-local lessons only in an ignored local-only note outside the published tree, such as `.codex-local/LESSONS.md`.
- **Audit privacy before every public delivery.** Follow the privacy audit in
  `docs/RELEASING.md` section 2. Inspect the exact tracked/staged/committed tree,
  including hidden LLM instructions, prompts, settings, examples and sealed backlog
  history, then both distribution archives and the history reachable from the
  outgoing ref. Secret scanning alone cannot establish that operational or personal
  information is public-safe. Retain redacted findings and the reviewed identities;
  a confirmed private disclosure or consequential unresolved classification blocks
  its public delivery. Preserve private local evidence and sealed records; never
  rewrite history, scrub canonical JSON or weaken detectors to pass this gate.
- **Record reusable lessons only when they are public knowledge.** When a session exposes a project gotcha, publish step, verification boundary, or agent-behavior correction that is safe for public readers and useful to future contributors, rewrite the matching lesson here in place, or add one when none matches.
- **Verify on the surface that will run the change, and name what was not run.** Python tests alone do not prove GitHub Actions runtime changes: use local YAML/static checks such as `actionlint`, then verify the real hosted workflow run when action runtime behavior matters. Direct handler calls are useful for MCP compatibility but do not prove a separate stdio MCP client, and CLI help does not prove the command executes. A release-readiness summary must distinguish unit tests, focused integration tests, direct API smoke, real CLI execution, and hosted/daemon behavior that was not run; a tag-only or release-only workflow without a real trigger run is reported as syntax-checked and version-checked, not execution-tested. Never imply full local coverage for hosted-only behavior.
- **Check the intended public release target.** Before publishing, verify the repository, branch, tag, and workflow that public users will see. Do not assume local remote names or private mirrors represent public release truth.
- **Treat release status as multiple independent facts.** Branch Tests, tag-triggered PyPI publish, GitHub Release creation, PyPI version visibility, and any deployment/release-environment status can diverge. Check all of them before calling a release published or latest; if one is red or missing, either fix it now or record the explicit remaining blocker.
- **Test dependency drift with a fresh resolver.** Local `.venv` and `uv.lock` success can hide what GitHub Actions or users get from an unlocked `pip install`. For dependency-sensitive failures, reproduce in a clean pip environment matching the hosted workflow before declaring the tests fixed.
- **Audit dependency targets before raising bounds.** For runtime, dev, and optional extras, check current and target versions against OSV or an equivalent advisory source, then run a resolver-level audit on a fresh environment. Do not raise optional legacy backends into advisory-affected ranges; hold or cap them and backlog the upgrade gate instead.
- **Keep benchmark gates tied to measured baselines.** If a release benchmark fails, reproduce it locally against the pinned fixture, update the CI threshold only to the observed stable baseline, and backlog any desired quality increase separately.
- **Do not call tests "local feature testing."** When asked to test new features locally, run the public CLI/MCP/API behavior itself, not only pytest. For each new feature, exercise at least one success path and one important failure/guard path when safe, record the exact command or request, and name any behavior that was covered only by tests.
- **Clean up smoke-test artifacts immediately.** Real backup, cleanup, and benchmark smokes can create archives, temp palaces, and result JSON. Put them under disposable temp paths, verify success/failure, then remove artifacts or explicitly report what remains.
- **Treat palace disk growth as storage forensics first.** Compare backup size, live storage stats, row counts, and cleanup output before deleting anything. Preserve non-regenerable manual drawers and KG data, stop active writers when needed, use supported cleanup APIs, and verify health/status afterward.

## LDR adoption and problem handoff

- LDR (`ldr/v1`) is the default format for current durable architectural decisions.
  Canonical accepted records live under `docs/decisions` when present. Historical
  ADRs remain evidence; do not migrate them or invent records for routine tasks.
  Reuse unchanged applicable accepted decisions without a new proposal or repeated
  record approval. No applicable records means an explicit empty selection with
  its applicability reason in the existing task context.

- Apply this rule before architecture, durable-contract, lifecycle, ownership or
  recovery changes. Start with one decision needed by the current task; keep task
  state and execution evidence with their existing owners.
- Discover applicability from the task and repository-owned references. Resolve
  the exact accepted key/revision; inspect status first and apply only active
  records. Check current committed bytes, owner, local references and fitness.
  Search results and historical prose cannot accept a decision.
- A missing or stale binding blocks only the dependent change. Propose a record
  outside the canonical accepted root; only the operator accepts active records.
  Same-key changes advance revision by one and preserve lifecycle/recovery.
- Use the existing adopter and pinned validator when present. Do not replace a
  pin, install a utility, add a runtime gate, or migrate historical decisions as
  part of this instruction. Run the current task's existing relevant checks.
- For a reproduced LDR problem, prepare and deliver the targeted handoff below
  during the same work session without waiting for a separate request. Identify
  whether the failure belongs to LDR or the adopter; record uncertainty. Continue
  independent safe work while the affected action remains blocked.

- Private maintainer routing and the first scoped adoption candidate are in
  .codex-local/LDR.md when present. Read that note before sending an LDR finding.
  If no route is configured, retain the sanitized draft and report missing_route.
  Keep machine paths, private transport and incident evidence out of public docs.
