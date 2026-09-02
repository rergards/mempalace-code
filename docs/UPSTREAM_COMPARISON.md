# Upstream Comparison — Reviewed Snapshot

This is the canonical comparison between `rergards/mempalace-code` (this fork)
and the upstream `mempalace` project. It records the public upstream surfaces
reviewed at one commit, this fork's current documented surfaces, and decisions
about scope. It is a factual snapshot, not an evaluation of either project.

The machine-readable form is
[`docs/quality/upstream-comparison.json`](quality/upstream-comparison.json). The
stdlib-only `scripts/upstream_comparison_guard.py` keeps the manifest, this
document, and the README pointer consistent.

## Snapshot

| Field | Value |
|---|---|
| Reviewed date | `2026-09-02` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `d9f059076c866fa6f29195679d75712436986024` |
| Previous reviewed commit | `e8098348ddfce59964fe536e5deffb81da579e6b` |
| Previous reviewed date | `2026-08-31` |
| Upstream release described by its changelog | `3.9.0` |
| Upstream paths tracked for drift | `README.md`, `CHANGELOG.md`, `pyproject.toml`, plugin/MCP metadata, update awareness, hub, logstream, MCP, lightweight MCP/PQL, KG, CLI, search, embedding, Qdrant, benchmark, coordination, configuration, split-file, and RFC 003–005 sources |
| Fork commit at review time | this repository, `main` |

All upstream statements below are limited to the pinned public sources. Upstream
code was read only where a source named a surface; it was not run, benchmarked,
or independently compatibility-tested.

## Source Links

Pinned primary upstream sources, all at the reviewed commit:

- <https://github.com/MemPalace/mempalace/tree/d9f059076c866fa6f29195679d75712436986024>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/README.md>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/.claude-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/config.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/split_mega_files.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/update_awareness.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/hub_client.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/logstream.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/mcp_server.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/searcher.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/embedding.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/backends/qdrant.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/benchmarks/PRIVATE_PALACE.md>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/docs/rfcs/005-agent-identity-routing.md>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/integrations/shared/coordination-protocol.md>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/cli.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/knowledge_graph.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/mcp_light_server.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/mempalace/query_parser.py>
- <https://github.com/MemPalace/mempalace/blob/d9f059076c866fa6f29195679d75712436986024/website/guide/lightweight-mcp.md>

The exact public range between the previous pin and this one is:

- <https://github.com/MemPalace/mempalace/compare/e8098348ddfce59964fe536e5deffb81da579e6b...d9f059076c866fa6f29195679d75712436986024>

## Upstream Delta Since the Previous Pin

The compare range contains 10 commits. Each commit is owned exactly once by the
single first-parent merge group below. The group has one stance from the
closed set `adopted`, `equivalent-local`, `migration-only`, `deferred`, or
`irrelevant`.

| Delta decision | Upstream change, as its sources describe it | Stance | Release-critical | Merge group |
|---|---|---|---|---|
| `lightweight-mcp-pql` | Optional three-tool MCP facade with PQL/structured inputs, KG temporal buckets, and on-demand logstream coordination guidance | `irrelevant` | no | `d9f05907` |

The manifest records the exact 10-commit full-range inventory for
`e8098348..d9f05907`: one top-level merge commit, zero nested merge commits,
and a nine-commit non-merge constituent subset. Its SHA-256 anchor is
`127aa2ccb94b5e549c305a9cc4317ba4a2f6c0488b5db1707ead7e8cb4a5d24c`.
Grouped by the top-level merge commits:

- `d9f05907`: `85d60c90`, `17936626`, `478ecee9`, `66b3b23d`, `4aa1e7f1`, `bf30db9b`, `be27f731`, `57ab367a`, `ea0c780b`

**Not applicable.** The fork already has one typed MCP registry: 29 tools in the
full profile and four tools in the portable minimal profile. Importing a second
free-form PQL parser and server would duplicate that owner and add hub,
logstream, and fuzzy-resolution contracts absent from this fork. The local KG
retains typed tool arguments and returns explicit temporal state on its existing
query surfaces.

The range has no release-critical decisions and imports no upstream runtime
behavior.

## Capability Comparison

| Area | Upstream, as advertised at the reviewed commit | This fork today |
|---|---|---|
| Product focus | General-purpose AI memory | Code-first memory: repository mining, `code_search`, symbol/type/project-graph tools |
| Storage and retrieval | ChromaDB default; `sqlite_exact`, Milvus, Qdrant, and pgvector are offered; hybrid retrieval and optional LLM reranking are described; 3.9.0 adds bounded safe Qdrant `get()` scrolling and a closet source index | LanceDB-only current package with ChromaDB support retired; local deterministic `code_search(rerank="hybrid")`; no LLM reranker or server-vector backends |
| Embeddings | New onboarding offers multilingual `embeddinggemma-300m`; opt-in `openai-compat` targets an OpenAI-compatible endpoint; 3.9.0 adds an EmbeddingGemma sub-batch override | `all-MiniLM-L6-v2`; no supported multilingual configuration or migration path, and no remote embedding-provider integration |
| Search | Date-window filtering is advertised; 3.9.0 can forward compatible CLI searches to a live hub and reports raw vector similarity for closet-enriched search | No date-window or live-hub forwarding surface; local Lance search remains process-local |
| Agent integration | A Hermes `MemoryProvider`, source adapters, shared-hub routing, and skill-first coordination are advertised | No Hermes provider, source-adapter ingestion, or shared-hub surface |
| MCP count and plugin wording | README and Claude plugin wording say 45 MCP tools; the Codex plugin wording says 44; an optional lightweight facade exposes three PQL/structured tools | Direct stdio MCP registration defaults to the typed 29-tool profile; the portable package defaults to four typed tools |
| Plugin metadata | Codex manifest identifies `mempalace` version 3.9.0 and points at `.mcp.json` | Standards-conformant Agent Plugins 1.0 portable package with a four-tool default |
| Coordination and replication | Logstream includes watcher behavior, topic routing, reverse pagination, artifact handoffs, on-demand coordination guidance, and an RFC 004 multi-master foundation | No logstream, palace replication, mesh, or live-hub transport |
| KG query shape | Entity candidates can be resolved through the lightweight facade and partitioned into active, historical, and future facts | Existing typed KG tools return each fact with explicit temporal state; no PQL or fuzzy entity-resolution layer |
| Hub concurrency | HTTP MCP permits concurrent palace reads while retaining exclusive writes | Stdio-only MCP; no shared HTTP palace lock |
| Update awareness | Stable-release checks are opt-in, cached, agent-visible, and do not install automatically | Disabled-by-default version checks plus explicit `update status`, `update check`, and confirmed `update apply --yes`; no upstream MCP cached-status compatibility claim |
| Benchmarks | A private-palace search benchmark procedure is published | Independent local benchmark gates; no cross-project result equivalence claim |
| Distribution | Python package and advertised multi-arch Docker image | Python package and pipx installation; no published Docker image |
| Writer ownership | Shared write routing and process-lifetime single-writer recovery are described | Local watcher/miner/maintenance ownership guards |
| Non-regular-file ingest | Nonblocking opens, discovery-time skips, and per-command type gates are described | Descriptor-validated ingest and generated split outputs with bounded diagnostics |

The table reports source wording and documented surfaces. It establishes no
runtime interoperability, performance, or completeness beyond those sources.

## Capability Identifiers

The manifest records every identifier below, and the guard requires this
document to list each one.

Upstream, advertised at the reviewed commit:

- `embeddinggemma-default-for-new-onboarding`
- `hybrid-retrieval`
- `optional-llm-reranking`
- `backend-chromadb`
- `backend-sqlite-exact`
- `backend-milvus`
- `backend-qdrant`
- `backend-pgvector`
- `chroma-sqlite-metadata-read-paths`
- `sqlite-exact-indexed-structured-fields`
- `mcp-tools-45-readme`
- `claude-plugin-tools-45`
- `codex-plugin-tools-44`
- `codex-plugin-metadata`
- `openai-compatible-embeddings`
- `search-date-window`
- `hermes-memory-provider-core`
- `source-adapters-mine`
- `agent-logstream-artifact-handoffs`
- `logstream-multi-master-sync-foundation`
- `live-palace-hub-write-routing`
- `read-replica-mesh-preview`
- `multiarch-docker-image`
- `process-lifetime-single-writer`
- `agent-logstream-watch`
- `opt-in-release-awareness`
- `live-hub-cli-search-forwarding`
- `concurrent-hub-palace-reads`
- `agent-logstream-topic-routing`
- `agent-logstream-reverse-pagination`
- `embeddinggemma-batch-size-override`
- `qdrant-bounded-get-scroll`
- `closet-search-source-index`
- `private-palace-search-benchmark`
- `lightweight-mcp-pql-three-tools`
- `kg-entity-candidate-temporal-buckets`
- `on-demand-logstream-coordination`

This fork, current:

- `code-first-mining`
- `backend-lancedb-default`
- `local-deterministic-code-search-hybrid-rerank`
- `no-llm-reranker`
- `no-supported-multilingual-configuration-migration`
- `no-server-vector-backends`
- `mcp-tools-29`
- `stdio-mcp-only`
- `agent-plugins-1-0-portable-package`
- `agent-plugin-minimal-profile-four-tools`
- `direct-mcp-full-profile-29-tools`
- `no-agent-logstream`
- `no-palace-replication`
- `no-published-docker-image`

## Capability Sources

The manifest carries the exact source mapping. Established capabilities remain
pinned to README, changelog, plugin/MCP metadata, and RFC 003–005. The newest
delta uses these reviewed sources:

| Upstream identifier | Read from |
|---|---|
| `mcp-tools-45-readme` | `README.md` |
| `claude-plugin-tools-45` | `.claude-plugin/plugin.json` |
| `codex-plugin-tools-44` | `.codex-plugin/plugin.json` |
| `opt-in-release-awareness` | `README.md`, `CHANGELOG.md`, `mempalace/update_awareness.py` |
| `live-hub-cli-search-forwarding` | `CHANGELOG.md`, `mempalace/hub_client.py`, `mempalace/mcp_server.py` |
| `concurrent-hub-palace-reads` | `CHANGELOG.md`, `mempalace/mcp_server.py` |
| `agent-logstream-topic-routing` | `mempalace/logstream.py`, RFC 003 |
| `agent-logstream-reverse-pagination` | `mempalace/logstream.py`, RFC 003 |
| `embeddinggemma-batch-size-override` | `CHANGELOG.md`, `mempalace/embedding.py` |
| `qdrant-bounded-get-scroll` | `CHANGELOG.md`, `mempalace/backends/qdrant.py` |
| `closet-search-source-index` | `CHANGELOG.md`, `mempalace/searcher.py` |
| `private-palace-search-benchmark` | `benchmarks/PRIVATE_PALACE.md` |
| `lightweight-mcp-pql-three-tools` | lightweight MCP guide, `mempalace/mcp_light_server.py`, `mempalace/query_parser.py`, `mempalace/cli.py`, `pyproject.toml` |
| `kg-entity-candidate-temporal-buckets` | `mempalace/mcp_server.py`, `mempalace/knowledge_graph.py` |
| `on-demand-logstream-coordination` | `integrations/shared/coordination-protocol.md` |

`mempalace/config.py` is also pinned for the live-hub search fingerprint.
`mempalace/split_mega_files.py` and RFC 005 remain tracked because changes to
their ingest and identity-routing surfaces would alter existing comparison
rows. The manifest is authoritative for the complete capability-to-source map.

## Fork Stance

**Embeddings.** The supported default remains `all-MiniLM-L6-v2`. A model
change requires the text and code retrieval evidence and migration support
defined in `AGENTS.md`.

**Retrieval and reranking.** The fork retains one local deterministic hybrid
path, `code_search(rerank="hybrid")`. It has no remote hub, closet layer, or
general LLM reranking layer.

**Update awareness.** The existing local version-check and updater owners provide
the equivalent opt-in outcomes listed above. The fork does not claim upstream MCP
cached-status response compatibility.

**Agent and distributed surfaces.** Hermes integration, source adapters,
logstream, live-hub routing, and replication remain outside the local code-memory
scope.

**MCP and packages.** Direct MCP defaults to 29 tools. The separate Agent
Plugins 1.0 portable package defaults to the four-tool `minimal` profile. The
fork keeps this one typed registry and does not import the optional PQL facade.

## Evidence Limits

- **Repository review only.** Claims come from the exact compare range and the
  pinned README, changelog, package, plugin/MCP, runtime, benchmark, and RFC
  sources. No upstream behavior was run.
- **Nothing was measured.** This document contains no cross-project benchmark,
  quality, performance, adoption, or compatibility measurement.
- **Delta stances are about this fork.** Every commit is assigned to the one
  merge group. Its `irrelevant` stance imports no local predicate claim.
- **Plugin counts are source-local wording.** The pinned README and Claude plugin
  say 45 tools; the pinned Codex plugin says 44. The fork's 29-tool direct profile
  and four-tool portable default are independent.
- **One branch, one commit.** Only `develop` at the pinned commit was reviewed.
- **Historical criticism is separate.** `docs/UPSTREAM_HARDENING.md` describes
  earlier material and is not evidence about this reviewed commit.

## Automation Policy

Static mode validates manifest shape, dates, pins, source links, capabilities,
decisions, inventory count and digest, and document/README synchronization
without network access. Live mode adds one read-only GitHub head query and
fails closed on drift or an untrusted response.

The canonical release-time command remains:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

## Drift Recovery

When live comparison reports `upstream-drift`, review the printed exact range,
classify every new commit once, update the manifest and this document together,
and run the single recovery command:

```bash
python scripts/upstream_comparison_guard.py --check-live --json
```

A release-critical row must cite a tracked upstream file. An `adopted` or
`equivalent-local` row must name an existing local test or module.
