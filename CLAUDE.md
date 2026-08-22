# mempalace — Project Guide for Claude Code

## 0. Pre-apply simplicity, reuse, and boundary review

This rule runs before any edit, patch, backlog mutation, commit, deploy, or
delegated executor prompt. Review the planned change before applying it; finding
the problem after implementation is already a process failure. Write one verdict
line for every check below. An unwritten check was not run.

- **DRY** — search by behavior before searching by name. Use
  `mempalace_code_search` or `mempalace_explain_subsystem` first when available,
  then bounded `rg -l`, signature, and call-site checks. Name the existing owner
  found. Extend it when it has the same contract, lifecycle, and state store.
- **KISS** — state the task in one sentence and select the smallest change that
  closes it. Prefer deletion or extension over addition.
- **YAGNI** — add no layer, abstraction, option, mode, gate, or generality that
  the stated task does not require now.
- **Duplicates** — create or retain no second helper, client, config loader,
  mutation route, manifest, or documentation paragraph. Consolidate shared
  production behavior into its existing owning module under `mempalace_code/`;
  consolidate script-only behavior into the existing owning script. Do not
  create catch-all `utils`, `helpers`, or `scripts/lib` modules without a proven
  incompatible owner or lifecycle. Run the owning suite before and after shared
  code changes.
- **Garbage** — remove what the change supersedes. Leave no dead code or flags,
  orphaned files, stale docs, scratch or `tmp/` artifacts, commented-out blocks,
  or one-shot scripts.
- **Drunk-user path** — assume a human can lose context, hold stale assumptions,
  omit or contradict facts, provide malformed input, repeat or reorder steps,
  and retry after an ambiguous result. Use safe defaults, explicit state and
  authority checks, bounded idempotent actions, contradiction detection,
  confirmation proportional to irreversibility, and one concrete recovery
  command. Test critical paths with lost context, stale state, malformed input,
  duplicate or reordered actions, and partial execution. Never require retained
  conversational context to avoid destructive or irreversible behavior.
- **Drunk-LLM path** — apply the same failure model to prompts, specifications,
  schemas, APIs, handoffs, approvals, and recovery procedures across
  human-to-LLM, LLM-to-human, and LLM-to-LLM boundaries. Avoid near-identical
  names or paths, silent flag meaning changes, ambiguous omitted-argument modes,
  mutating defaults, and split instructions that disagree. Make state,
  authority, inputs, outputs, invariants, and recovery machine-verifiable where
  practical. If an agent can plausibly choose the wrong path, fix the design.

A failed check ends the attempt. Revise the plan, write all seven verdicts again,
and proceed only when every check passes. Re-run the gate after scope, state,
authority, or ownership changes.

Reuse-first is mandatory before creating a file, module, helper, script, route,
manifest, or documentation block. A new implementation requires one concrete
incompatibility: a different owner, contract, lifecycle, or state store.
"Cleaner", "safer", "isolated", "easier to reason about", effort, and fear of
changing the existing owner are not incompatibilities. A near-copy is a defect;
fixing the existing owner is the task.

Preserve the requested change class and use the existing generator, validator,
commit, and release path for data, copy, layout, and generated-artifact changes.
Limit the diff to the owning source, required generated artifacts, and the
smallest existing regression. The first unrelated tool or gate failure ends that
attempt: restore or confirm safe state, report the blocker, and request a separate
owner decision before changing tooling, publishers, runbooks, or architecture.
Stop when a repair grows beyond roughly three times its initial estimate or
crosses the stated component boundary.

Add a gate only for a failure that already occurred in this repository, citing
its date, commit, or backlog item. Data loss and a live user outage are the only
exceptions. The default number of new gates is zero; prefer backup, atomic
replace, and post-state verification. Ask the owner before adding any other gate,
naming the prior failure and what breaks without the gate.

## Stack

- **Python** 3.11+ (supports 3.11–3.14)
- **Storage**: LanceDB (core, crash-safe vector DB — no server required)
- **Embeddings**: sentence-transformers (local, no API key)
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
- `.[chroma-migration]` — ChromaDB-to-LanceDB migration bridge; capped below
  ChromaDB 1.x while GHSA-f4j7-r4q5-qw2c affects the available 1.x line
- `.[chroma]` — deprecated compatibility alias for the migration bridge
- `.[spellcheck]` — autocorrect support for room/wing names

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
2. **Local-first** — no external APIs required; all embeddings run on-device via sentence-transformers.
3. **Zero-API-by-default** — LanceDB and sentence-transformers work offline; API integrations are opt-in.

## Storage Backend

- **LanceDB** is the core backend (installed by default via `lancedb>=0.20`).
- **ChromaDB** is supported only as migration input through
  `mempalace-code migrate-storage SRC DST --verify`. Install
  `.[chroma-migration]` for that bridge. The deprecated `.[chroma]` alias is
  retained for existing scripts, and the dependency stays capped below 1.x while
  GHSA-f4j7-r4q5-qw2c affects the available 1.x line.

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

## Operational Lessons

- **Keep this file public-safe.** `CLAUDE.md` is part of the publishable repository. Do not write private remotes, hostnames, credentials, local machine paths, customer/project details, incident specifics, or non-public operational history here. Put private or machine-local lessons in a local-only note outside the published tree.
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
