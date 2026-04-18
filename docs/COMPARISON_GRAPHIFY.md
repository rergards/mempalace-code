# mempalace-code vs Graphify — Honest Comparison

**Date**: 2026-04-10
**Graphify version surveyed**: v4 / 0.3.28 (21.7k stars, `safishamsi/graphify`)
**mempalace-code version surveyed**: v1.0 target state (`feat/lancedb-backend` branch)

This document is written for prospective users trying to decide which project fits their needs. It is deliberately honest about where each wins. There is no single "better" tool — the two projects solve adjacent problems using orthogonal techniques and their strengths do not overlap much.

## TL;DR

- **Graphify** builds a **static structural knowledge graph** from your repo using tree-sitter ASTs and Leiden community detection. It has **no embeddings**. Queries are graph traversals that find "god nodes" (highly-connected hubs) and community clusters. Output is a Markdown report surfaced to the AI assistant before every search tool call via a PreToolUse hook.
- **mempalace-code** builds a **semantic vector index** over code, prose, and conversations using `sentence-transformers` and LanceDB. On top it tracks **temporal facts** via a separate SQLite knowledge graph with validity windows. Queries are cosine-distance retrieval filtered by wing/room.

If you want to answer "what are the structural hubs of my codebase and which files are unexpectedly central?" → graphify.
If you want to answer "what did we decide about auth last quarter?" or "find the function that detects language from a file extension" → mempalace.

## Architecture — Side by Side

| Dimension | Graphify | mempalace-code |
|-----------|----------|-----------|
| Core data structure | NetworkX MultiDiGraph | LanceDB columnar vector store + SQLite KG |
| Code understanding | tree-sitter AST, 20 languages | regex-based structural chunking (def/class/export) + language detection |
| Semantic layer | Claude subagent extracts concepts into graph nodes | `all-MiniLM-L6-v2` embeddings (384d, local) |
| Graph clustering | **Leiden community detection** (produces "god nodes" + clusters) | none — query-time ranked retrieval only |
| Search primitive | graph traversal, BFS with hop limits | cosine distance over vectors, filtered by wing/room |
| Temporal facts | none | SQLite KG triples with `valid_from` / `valid_until` |
| Cross-project memory | per-project `graphify-out/` directory | single palace spans all wings |
| Conversation mining | none | `convo_miner.py` ingests Claude/ChatGPT/Slack exports |
| Multimodal | **PDFs, images, videos, YouTube links** (via host LLM API) | text only |
| Visualization | **interactive HTML graph** (pyvis) | none |
| Incremental rebuild | **SHA256 file-level cache** | not yet (planned: CODE-INCREMENTAL) |
| Privacy on ingest | code stays local; **docs/PDFs/images sent to host LLM API** | **nothing leaves the host, ever** (fully offline) |
| Embedding dependency | none | 80 MB `all-MiniLM-L6-v2` model downloaded once |
| MCP surface | `/graphify query`, `/graphify path`, `/graphify explain` | 27 MCP tools (search, traverse, diary, KG, arch-retrieval, stats, …) |
| Always-on integration | **PreToolUse hook** fires before every Glob/Grep/Bash | none — agent calls tools explicitly |
| Supported agents | Claude Code, Codex, OpenCode, Cursor, Gemini CLI, Aider, OpenClaw, Factory Droid, Trae | Claude Code, Codex, any MCP client; hooks not shipped |
| Installation | `pip install graphifyy` + `graphify install --platform <x>` | `uv pip install -e .` + `~/.mcp.json` entry |
| Stars / visibility | 21.7k (launched ~Mar 2026) | fork of upstream, pre-launch |

## Where mempalace-code Wins

### 1. Full offline ingest — no files leave the host

Graphify's docs-and-multimodal layer sends PDFs, images, and video frames to the **host LLM API** (Claude, GPT, Gemini) during extraction to produce concept nodes. Code stays local, but the non-code layer does not.

mempalace-code has no API dependency at any stage. The embedding model runs locally, the chunker is pure Python, the KG is SQLite. There is no network path from mine → store → query.

**Who this matters for**: consultants, regulated industries, researchers under NDA, anyone running on an air-gapped machine.

### 2. Temporal knowledge graph

mempalace-code has a first-class temporal KG (`mempalace_kg_add`, `mempalace_kg_query` with `as_of`). Facts like "team lead for the billing service is X from 2026-01-15 to 2026-04-01" are stored with validity windows, and old facts are invalidated rather than deleted.

Graphify's graph is static — it is rebuilt from the current source tree. There is no representation of "this was true in Q1, this is true now".

**Who this matters for**: long-running projects where version numbers, deadlines, ownership, and tech stack choices change over time and an agent needs to reason about "as-of" state.

### 3. Conversation mining

`mempalace mine ~/chats/ --mode convos` ingests Claude, ChatGPT, Slack, and other chat exports into the same palace as code. You can then search across past design discussions and debugging sessions the same way you search source files.

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

### 2. Tree-sitter AST, 20 languages

Graphify uses tree-sitter for parsing, covering 20 languages precisely. Function calls, imports, class references, and type usages are captured at AST fidelity.

mempalace-code uses regex-based structural chunking. It handles Python, JS, TS, Go, Rust reasonably well but it is not an AST — it cannot track `foo()` → function definition of `foo` across files. Symbol metadata is per-chunk only, not cross-referenced.

**Consequence**: for "find all call sites of this function" graphify is the right tool. mempalace-code will not answer that precisely.

### 3. Leiden community detection / god nodes

The Leiden algorithm identifies tightly-coupled clusters and high-degree hub nodes. This is genuine structural insight — "this file is a god node, changes here ripple everywhere" — and it is surfaced at the top of graphify's `GRAPH_REPORT.md`.

mempalace-code has no equivalent. There is `palace_graph.py` with tunnel detection, but that is for cross-wing drawer connections, not for structural analysis of source code.

### 4. Multimodal ingest (PDFs, images, videos)

For projects that include research papers, architecture diagrams as PNGs, or recorded walkthroughs, graphify ingests all of it into the same graph. The privacy trade-off is real (non-code content is sent to the host LLM API) but the capability is real too.

mempalace-code is text-only. No PDF parsing, no image captioning, no video transcription.

### 5. Shipped SHA256 incremental rebuild

Graphify caches parsed AST by file SHA256. Re-running on an unchanged file is a cache hit; only changed files are re-processed.

mempalace-code's incremental re-mine is on the pre_release backlog (`CODE-INCREMENTAL`) but not yet shipped. Today, `mempalace mine` against a large repo is full-rebuild.

### 6. 10-platform reach via installer

`graphify install --platform codex|cursor|gemini|aider|droid|...` ships per-platform adapters. Graphify runs on 10 AI coding assistants out of the box.

mempalace-code ships an MCP server that works in any MCP client. Codex now supports MCP natively (`codex mcp add`), so coverage includes the two dominant AI coding assistants. Other MCP clients (Cursor, Continue, etc.) are growing.

### 7. Always-on PreToolUse hook

This is graphify's flagship ergonomic feature and it deserves a separate section — see below.

### 8. Concrete published benchmark number

Graphify's landing page claims **71.5× token reduction per query** on a 100-file Python repo. The methodology is not published but the number is out there and it is memorable.

mempalace-code has internal embedding-model A/B benchmarks (`BENCH-EMBED-AB`) but no user-facing "tokens saved per query" number. This is filed as `LAUNCH-BENCH-TOKEN-DELTA` (owner task).

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

Graphify's hook does not gate by phase or task. It fires unconditionally. By autopilot's measurement, this is exactly the shape of intervention that produces 76% ceremonial usage. Graphify's own GitHub issue tracker shows the cost side: #182 (broken hook format on Codex upgrade), PR #54 (PreToolUse hook output fix), #178 (version drift warning breaks the hook). Every platform needs its own hook adapter and every one is a potential breakage surface.

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
| **SHA256 file cache for incremental re-mine** | M | high | Already in pre_release as `CODE-INCREMENTAL` |
| **Explicit per-edge / per-drawer provenance label** | S | medium | New (not in backlog yet) — e.g. `confidence`, `extractor_version` |
| **`benchmarks/TOKEN_DELTA.md` with one public number** | S | high | Filed as `LAUNCH-BENCH-TOKEN-DELTA` (owner task) |
| **Minimal static HTML visualization** of palace structure (wings × rooms × drawer counts) | M | medium | New candidate for post-launch |
| **Per-platform installer** (`mempalace install --platform codex\|cursor\|gemini`) | L | low | Not urgent — Claude Code + Codex both have native MCP; per-platform hooks are maintenance burden |
| **Tree-sitter backend for structural chunking** | L | medium | Not urgent — current regex chunker scores R@5 = 0.95 on the internal bench |

Note: the always-on PreToolUse hook is intentionally absent from this list. See the preceding section for why.

## What To Position Against, What To Leave Alone

**Attack**:
- offline privacy (files never leave host)
- temporal KG (versioned facts, as-of queries)
- conversation mining (Claude / ChatGPT / Slack exports)
- cross-project palace (single wing-scoped search)
- crash-safe LanceDB (survives `Ctrl+C`)

**Do not claim**:
- AST precision — mempalace uses regex chunking
- multimodal ingest — mempalace is text-only
- visualization — mempalace has none
- community detection — different problem, different algorithm, not mempalace's game
- "beats graphify on code retrieval" — the two tools measure different things and a head-to-head benchmark would be misleading either way

**Do not attempt to match**:
- 10-platform installer reach (MCP now covers the top 2 — Claude Code + Codex — without per-platform adapters)
- always-on hook default-on (see evidence section)
- marketing hero number like "71.5× fewer tokens" (mempalace's honest number will be reported with methodology, as a footnote, not a headline)
