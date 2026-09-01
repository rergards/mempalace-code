# mempalace-code vs Graphify — Honest Comparison

**Date**: 2026-08-10
**Graphify version surveyed**: v8 / 0.9.38, ~104.9k GitHub stars as of 2026-08-10 (approximate, date-bound — check [github.com/Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify) for current count). The repo previously lived at `safishamsi/graphify`; it now redirects to `Graphify-Labs/graphify` (YC S26). The OSS CLI declares Apache-2.0 and ships bundled MIT license notices; the org also runs an early-access hosted platform at graphify.com that is out of scope for this comparison.
**mempalace-code version surveyed**: v1.13.0 release state

This document is written for prospective users trying to decide which project fits their needs. It is deliberately honest about where each wins. There is no single "better" tool — the two projects solve adjacent problems using orthogonal techniques and their strengths do not overlap much.

## TL;DR

- **Graphify** builds a **static structural knowledge graph** from your repo using tree-sitter ASTs and (optionally) Leiden community detection. It has **no embeddings** — see [`README.md#what-it-does`](https://github.com/Graphify-Labs/graphify/blob/v0.9.38/README.md). Queries are graph traversals that find "god nodes" (highly-connected hubs) and community clusters. Output is a Markdown report and an interactive HTML graph, surfaced to the AI assistant before search tool calls via a per-platform hook or instruction file.
- **mempalace-code** builds a **semantic vector index** over code, prose, and conversations using CPU FastEmbed/ONNX and LanceDB. On top it tracks **temporal facts** via a separate SQLite knowledge graph with validity windows. Queries are cosine-distance retrieval filtered by wing/room.

If you want to answer "what are the structural hubs of my codebase and which files are unexpectedly central?" → graphify.
If you want to answer "what did we decide about auth last quarter?" or "find the function that detects language from a file extension" → mempalace.

## Architecture — Side by Side

| Dimension | Graphify | mempalace-code |
|-----------|----------|-----------|
| Core data structure | NetworkX MultiDiGraph (optional push to Neo4j / FalkorDB) | LanceDB columnar vector store + SQLite KG |
| Code understanding | tree-sitter AST, ~40 languages, cross-file `calls`/`imports`/`inherits`/`mixes_in` resolution ([README §What it does](https://github.com/Graphify-Labs/graphify/blob/v0.9.38/README.md#what-it-does)) | language-aware mining: optional tree-sitter chunks for Python/JS/TS/TSX/JSX/Go/Rust, regex/static structural chunks, YAML-aware Kubernetes/Helm/Ansible, adaptive config/prose chunks; 45 searchable language labels |
| Semantic layer | code parsing needs no LLM; the semantic pass over docs/PDFs/images uses whatever model the host IDE/assistant runs, or (headless `graphify extract`) an explicit backend: Gemini, Kimi, Claude, OpenAI, DeepSeek, Azure, Bedrock, or local Ollama | `all-MiniLM-L6-v2` embeddings (384d, local) |
| Graph clustering | **Leiden community detection**, now an *optional* extra (`graphifyy[leiden]`) and only available on Python < 3.13 (`graspologic` dependency) | no clustering; architecture extraction emits pattern/layer/namespace/project KG facts for .NET and Python |
| Search primitive | graph traversal, BFS with hop limits | cosine distance over vectors, filtered by wing/room |
| Temporal facts | none | SQLite KG triples with `valid_from` / `valid_until` |
| Cross-project memory | per-project `graphify-out/` directory (an optional shared HTTP MCP server can serve one project's graph to a team, but graphs are not merged across projects) | single palace spans all wings |
| Conversation mining | none | `convo_miner.py` ingests Claude/ChatGPT/Slack exports |
| Multimodal | **PDFs, images, videos, YouTube links.** Video/audio is now transcribed **locally** with `faster-whisper`; PDFs/images/office docs still go through a host or API model | text only |
| Visualization | **interactive HTML graph** (pyvis), plus optional SVG/Mermaid export | none |
| Incremental rebuild | **SHA256 file-level cache** | content-hash incremental mining; only changed files are re-chunked |
| Privacy on ingest | code (and now audio/video) processed fully locally, no API key needed with `--code-only`; **docs/PDFs/images/office files** are sent to the host assistant's model or a configured API (or `--backend ollama` for a fully local semantic pass) | no content leaves the host; one-time embedding model download during setup, then local-only model resolution |
| Embedding dependency | none (embeddings are not part of the architecture) | 80 MB `all-MiniLM-L6-v2` model cached once |
| MCP surface | optional MCP server (`graphifyy[mcp]`, stdio or Streamable HTTP): `query_graph`, `get_node`, `get_neighbors`, `shortest_path`, `list_prs`, `get_pr_impact`, `triage_prs` — 7 tools | 29 MCP tools (search, traverse, diary, KG, arch-retrieval, stats, …) |
| Always-on integration | hook or instruction-file fires before search-style tool calls (Claude Code/Gemini CLI use a real hook incl. Read/Glob; other platforms use `AGENTS.md`-style files); an opt-in **strict mode** on Claude Code blocks the first raw file read of a session and redirects to the graph | none — agent calls tools explicitly |
| Supported agents | 20+ via `graphify <platform> install`: Claude Code, CodeBuddy, Codex, OpenCode, Kilo Code, GitHub Copilot CLI, VS Code Copilot Chat, Aider, OpenClaw, Factory Droid, Trae/Trae CN, Cursor, Gemini CLI, Hermes, Kimi Code, Amp, Kiro, Pi, Devin CLI, Google Antigravity, plus a generic Agent Skills installer | Claude Code, Codex, any MCP client; hooks not shipped |
| Installation | `uv tool install graphifyy` (PyPI name unchanged) + `graphify install [--platform <x>]` | `uv tool install mempalace-code` + MCP registration as `mempalace-code` |
| Stars / visibility | ~104.9k stars as of 2026-08-10 (grew from 21.7k in mid-2026; treat as a snapshot, not a stable figure) | newer fork of upstream, lower public visibility |

## Where mempalace-code Wins

### 1. Full offline ingest — no files leave the host, with zero configuration

Graphify has narrowed this gap since v4: code parsing is tree-sitter only (always local), and video/audio is now transcribed locally with `faster-whisper`. A code-only corpus (`graphify extract --code-only`) is fully offline and needs no API key. But PDFs, images, and office docs still require a semantic pass through either the host IDE's assistant model or an explicit API backend (Gemini, Kimi, Claude, OpenAI, DeepSeek, Azure, Bedrock) — the one fully-local option for that layer is `--backend ollama`, which most users will not have running by default. See [Graphify README §Privacy](https://github.com/Graphify-Labs/graphify/blob/v0.9.38/README.md#privacy).

mempalace-code has no content-ingest API dependency at all — for code, prose, or conversations. The embedding model is downloaded once during setup (`init` or `fetch-model`); after that, model startup tries local-only resolution first, the chunker is pure Python, and the KG is SQLite. There is no network path from mine → store → query when the model cache is populated, and no per-content-type decision about which layer is local.

**Who this matters for**: consultants, regulated industries, researchers under NDA, anyone running on an air-gapped machine, or anyone who wants offline-by-default without having to remember `--code-only` or stand up a local Ollama instance.

### 2. Temporal knowledge graph

mempalace-code has a first-class temporal KG (`mempalace_kg_add`, `mempalace_kg_query` with `as_of`). Facts like "team lead for the billing service is X from 2026-01-15 to 2026-04-01" are stored with validity windows, and old facts are invalidated rather than deleted.

Graphify's graph is static — it is rebuilt from the current source tree. There is no representation of "this was true in Q1, this is true now".

**Who this matters for**: long-running projects where version numbers, deadlines, ownership, and tech stack choices change over time and an agent needs to reason about "as-of" state.

### 3. Conversation mining

`mempalace-code mine ~/chats/ --mode convos` ingests Claude, ChatGPT, Slack, and other chat exports into the same palace as code. You can then search across past design discussions and debugging sessions the same way you search source files.

Graphify does not ingest conversations.

### 4. Semantic fuzzy recall

"How does authorization work" → finds a file that defines `login()` and handles `session` tokens but never uses the word "authorization". That is vector search's home turf and graphify's graph traversal cannot do it — graphify needs a node whose *name* or *extracted concept* matches.

Graphify docs explicitly recommend its own primitive only for **architecture-level** questions ("what are the hubs of the graph"). For file-level "find the function that does X" it defers to the agent's own Glob/Grep.

### 5. Crash-safe LanceDB backend

LanceDB uses columnar Arrow storage with copy-on-write commits. `Ctrl+C` during a large mine does not corrupt the index. NetworkX serializes as JSON — an interrupted write is an invalid file.

### 6. Cross-project palace

mempalace-code stores all projects in a single palace with `wing` as the project namespace. A search without a wing filter spans everything. Remembering a pattern from project A while working in project B is one `mempalace_search` call.

Graphify is per-project — each repo has its own `graphify-out/` directory and each knowledge graph is independent.

## Where Graphify Wins

### 1. Interactive HTML visualization

`graphify-out/graph.html` is a pyvis-rendered, clickable, physics-simulated view of the entire knowledge graph. It is a genuinely useful on-ramp for humans trying to understand a new codebase.

mempalace-code has no visualization layer. Vector spaces do not visualize well; graph structures do.

### 2. Full AST graph precision across more languages

Graphify uses tree-sitter for parsing, now covering roughly 40 languages precisely (up from 20 at the v4 survey), with `calls`/`imports`/`inherits`/`mixes_in` edges resolved across files. Function calls, imports, class references, and type usages are captured at AST fidelity, and each edge is tagged `EXTRACTED` (read directly from source) or `INFERRED` (resolved by graphify), so provenance is explicit.

mempalace-code uses tree-sitter for chunk boundaries when optional grammars are installed for Python, TypeScript/JavaScript/TSX/JSX, Go, and Rust. It also uses regex structural chunking for Java, Kotlin, .NET languages, XAML, Swift, PHP, Scala, Dart, Lua, Ruby, and Terraform/HCL, YAML-aware/static splitting for Kubernetes manifests, Helm charts/templates, and Ansible playbooks/roles/inventory, and adaptive chunking for configs/data/prose. That is still not a call graph: it cannot track `foo()` → function definition of `foo` across files. Symbol metadata is per-chunk only, not cross-referenced.

**Consequence**: for "find all call sites of this function" graphify is the right tool. mempalace-code will not answer that precisely.

### 3. Leiden community detection / god nodes

The Leiden algorithm identifies tightly-coupled clusters and high-degree hub nodes. This is genuine structural insight — "this file is a god node, changes here ripple everywhere" — and it is surfaced at the top of graphify's `GRAPH_REPORT.md`. **Caveat as of v8**: Leiden clustering moved to the optional `graphifyy[leiden]` extra and depends on `graspologic`, which is only installable on Python < 3.13. A default `pip install graphifyy` on Python 3.13+ will not get community detection. God nodes (degree-based) are unaffected by this.

mempalace-code has partial architecture KG extraction now: it records pattern, layer, namespace, and project facts for .NET and Python. That is still not equivalent to Leiden clustering or a full structural graph. `palace_graph.py` handles cross-wing drawer connections, not source-code community detection.

### 4. Multimodal ingest (PDFs, images, videos, office docs, SQL schemas)

For projects that include research papers, architecture diagrams as PNGs, spreadsheets, or recorded walkthroughs, graphify ingests all of it into the same graph. Video/audio transcription now runs locally (`faster-whisper`); PDFs, images, and office docs still need a host or API model. The privacy trade-off for that remaining layer is real, but the capability is real too, and it keeps growing (SQL schema extraction, live Postgres introspection, and MCP-config parsing were all added since v4).

mempalace-code is text-only. No PDF parsing, no image captioning, no video transcription.

### 5. Incremental rebuild is no longer a Graphify-only win

Graphify caches parsed AST by file SHA256. Re-running on an unchanged file is a cache hit; only changed files are re-processed.

mempalace-code now also mines incrementally by content hash: unchanged drawers are skipped and only changed files are re-chunked unless `--full` is passed. Graphify still wins on full structural graph analysis, but the basic "do not rebuild every unchanged file" capability is now table stakes for both tools.

### 6. 20+-platform reach via installer

`graphify <platform> install` (Claude Code, CodeBuddy, Codex, OpenCode, Kilo Code, GitHub Copilot CLI, VS Code Copilot Chat, Aider, OpenClaw, Factory Droid, Trae/Trae CN, Cursor, Gemini CLI, Hermes, Kimi Code, Amp, Kiro, Pi, Devin CLI, Google Antigravity, plus a generic Agent Skills installer) ships per-platform adapters. Graphify runs on 20+ AI coding assistants out of the box, up from 10 at the v4 survey.

mempalace-code ships an MCP server that works in any MCP client. Codex now supports MCP natively (`codex mcp add`), so coverage includes the two dominant AI coding assistants. Other MCP clients (Cursor, Continue, etc.) are growing.

### 7. Always-on PreToolUse hook

This is graphify's flagship ergonomic feature and it deserves a separate section — see below.

### 8. Judge-validated cross-system benchmark (superseding the old marketing number)

The v4-era "71.5× token reduction" headline is gone from graphify's docs as of v8. In its place, graphify now publishes a much more rigorous evaluation in [`BENCHMARKS.md`](https://github.com/Graphify-Labs/graphify/blob/v0.9.38/BENCHMARKS.md): on LOCOMO (n=300) it reports recall@10 of 0.497 and QA accuracy of 45.3%, and on LongMemEval-S (n=50) 76% QA accuracy, tied with dense RAG. Every system in the comparison (graphify, mem0, supermemory, dense RAG, BM25, hybrid RRF) ran on the same harness, same model, same budgets, with a second judge blind-validating agreement (90.6%, Cohen's κ 0.81). This is a genuinely stronger evidentiary bar than a single unmethodologized number, and it directly compares graphify's graph-expand retrieval against dense/vector RAG on QA accuracy — a claim mempalace has not made or measured for itself.

mempalace-code publishes token-savings methodology in `docs/BENCH_TOKEN_DELTA.md`: on the canonical fixture, measured retrieval used 33.8x fewer tokens at peak and 14.5x fewer tokens at median than grep + read. That is a different axis (token cost vs. QA accuracy) and the two are not directly comparable.

## The Always-On Hook: Evidence Against Making It Default

Graphify's most talked-about feature is the `PreToolUse` hook — before every `Glob` / `Grep` / `Bash` tool call, the agent sees an injected reminder: "Knowledge graph exists. Read `GRAPH_REPORT.md` before searching raw files." This is graphify's answer to "how do we make sure agents actually use the thing".

Superficially, mempalace should ship something similar. The autopilot project's own empirical data says: **don't**.

### Autopilot's mempalace-code Usage Qualitative Audit (2026-04-10)

Autopilot already ran this experiment in a controlled form. It injects a mempalace_search instruction into the plan / implement / harden phase prompts of every task. 8 recent completed tasks were audited, yielding 21 mempalace tool calls across 19 phase-slots. Findings:

| Classification | Count | % |
|----------------|------:|--:|
| Ceremonial — agent searches, ignores result, proceeds as if nothing happened | 16 | **76%** |
| Substantive — agent explicitly acknowledges result and changes behavior | 4 | 19% |
| Mixed / unclear | 1 | 5% |

The audit's primary recommendation was not "add more hooks" but the opposite:

- **R1**: Require a mandatory post-search acknowledgment sentence. If the agent does not produce "what I found, how I'll apply it" text, it cannot proceed to other tools.
- **R2**: **Remove** the harden-phase mempalace injection entirely. In the phase where it was most ceremonial (100% ceremonial, 0% substantive), the injection was pure token overhead.

**The key insight**: passive context injection is a ritual by default. The bottleneck is not "did the tool fire" — it is "did the agent acknowledge the output and change behavior". An always-on hook that fires before every tool call maximizes the "did the tool fire" metric but **amplifies the noise ratio**, because the agent has no task-specific reason to look at the injected context in most cases.

Graphify's default hook does not gate by phase or task — it fires unconditionally before search-style tool calls. By autopilot's measurement, this is exactly the shape of intervention that produces 76% ceremonial usage. As of v8, graphify has added an opt-in **strict mode** (`graphify install --project --strict`, or `GRAPHIFY_HOOK_STRICT=1`) that actually *blocks* the first raw file read of a session and redirects it to the graph, rather than just nudging — a direct, if partial, answer to the "agent ignores the nudge" problem. But it has introduced its own friction: as of 2026-08-10 there is an open issue reporting that the strict-mode hook reminder reads as a prompt injection to a spawned subagent ([#2202](https://github.com/Graphify-Labs/graphify/issues/2202)), and another noting the hook does not cover subagent-spawned tool calls at all ([#2145](https://github.com/Graphify-Labs/graphify/issues/2145)) — i.e. the exact surface where most exploration happens in multi-agent workflows. Every platform still needs its own hook/instruction-file adapter, and the tracker shows a steady stream of platform-specific breakage (e.g. Windows interpreter path resolution, [#2581](https://github.com/Graphify-Labs/graphify/issues/2581)).

### When An Always-On Hook IS The Right Call

The always-on pattern earns its keep in exactly one scenario: when the **injected context is small, static, and universally applicable**. Graphify's injected payload is a one-line reminder pointing to `GRAPH_REPORT.md`. It is small. It is static. It is applicable anywhere the codebase matters. That is about as close to a free lunch as the pattern gets, and even so — autopilot's data says 76% of the time the agent still ignores it.

mempalace-code's natural injection would not be one line. It would be the result of a wing-scoped search, which is large (5–15 KB) and query-dependent. Injecting a 15 KB blob before every tool call would blow context windows within 5–10 turns.

### Recommendation

Do **not** ship an always-on PreToolUse hook as default-on for v1.0. If shipped at all, it must be:

1. **Opt-in**, disabled by default.
2. **Role-gated**: fire only in plan / implement phases, never in harden or verify. (Autopilot's R2.)
3. **Acknowledgment-gated at the prompt level**: the injected instruction must require a named-finding + next-step sentence from the agent. (Autopilot's R1.)
4. **Payload-bounded**: the injection must be a fixed-size pointer ("palace has drawers for this project — call `mempalace_search` if you need design context"), not a pre-run search result.

The better launch move is to double down on mempalace's differentiators — temporal KG, offline privacy, conversation mining, cross-project scope — and explicitly position graphify's always-on hook as a design choice we rejected with evidence.

## Adapt From Graphify — What To Borrow (Post-Launch)

These are genuinely good ideas from graphify that mempalace can incorporate without fighting its architecture:

| Idea | Cost | Value | Status |
|------|------|-------|--------|
| **Broader AST coverage / call graph extraction** | L | high | Post-launch candidate — current tree-sitter support is chunk-boundary only for Python/JS/TS/TSX/JSX/Go/Rust |
| **Explicit per-edge / per-drawer provenance label** | S | medium | New (not in backlog yet) — e.g. `confidence`, `extractor_version` |
| **Token-delta benchmark with one public number** | S | high | Done — see `docs/BENCH_TOKEN_DELTA.md` |
| **Minimal static HTML visualization** of palace structure (wings × rooms × drawer counts) | M | medium | New candidate for post-launch |
| **Per-platform installer** (`mempalace-code install --platform codex\|cursor\|gemini`) | L | low | Not urgent — Claude Code + Codex both have native MCP; per-platform hooks are maintenance burden |
| **Tree-sitter grammars beyond Python/JS/TS/Go/Rust** | M | medium | Not urgent — current regex/adaptive chunkers cover the launch languages, but not full AST semantics |

Note: the always-on PreToolUse hook is intentionally absent from this list. See the preceding section for why.

## What To Position Against, What To Leave Alone

**Attack**:
- offline privacy (files never leave host, for every content type — not just code)
- temporal KG (versioned facts, as-of queries)
- conversation mining (Claude / ChatGPT / Slack exports)
- cross-project palace (single wing-scoped search)
- crash-safe LanceDB (survives `Ctrl+C`)

**Do not claim**:
- full AST/code-graph precision — mempalace uses AST chunk boundaries for a subset, regex/static structural chunks for many languages and infrastructure files, and adaptive chunks for configs/data, but does not build call graphs
- multimodal ingest — mempalace is text-only
- visualization — mempalace has none
- community detection — different problem, different algorithm, not mempalace's game
- "beats graphify on code retrieval" — the two tools measure different things and a head-to-head benchmark would be misleading either way

**Do not attempt to match**:
- 20+-platform installer reach (MCP now covers the top 2 — Claude Code + Codex — without per-platform adapters)
- always-on hook default-on, including its opt-in strict-block mode (see evidence section)
- a cross-system QA-accuracy benchmark against mem0/supermemory/dense RAG — mempalace has not run this evaluation and should not imply it has
