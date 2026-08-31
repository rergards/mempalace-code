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
| Reviewed date | `2026-08-31` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `e8098348ddfce59964fe536e5deffb81da579e6b` |
| Previous reviewed commit | `a9f345cc63254eb4dea7abad36963b85c9f8453a` |
| Previous reviewed date | `2026-08-29` |
| Upstream release described by its changelog | `3.9.0` |
| Upstream paths tracked for drift | `README.md`, `CHANGELOG.md`, `pyproject.toml`, plugin/MCP metadata, update awareness, hub, logstream, MCP, search, embedding, Qdrant, benchmark, configuration, split-file, and RFC 003–005 sources |
| Fork commit at review time | this repository, `main` |

All upstream statements below are limited to the pinned public sources. Upstream
code was read only where a source named a surface; it was not run, benchmarked,
or independently compatibility-tested.

## Source Links

Pinned primary upstream sources, all at the reviewed commit:

- <https://github.com/MemPalace/mempalace/tree/e8098348ddfce59964fe536e5deffb81da579e6b>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/README.md>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/.claude-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/config.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/split_mega_files.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/update_awareness.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/hub_client.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/logstream.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/mcp_server.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/searcher.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/embedding.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/mempalace/backends/qdrant.py>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/benchmarks/PRIVATE_PALACE.md>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/e8098348ddfce59964fe536e5deffb81da579e6b/docs/rfcs/005-agent-identity-routing.md>

The exact public range between the previous pin and this one is:

- <https://github.com/MemPalace/mempalace/compare/a9f345cc63254eb4dea7abad36963b85c9f8453a...e8098348ddfce59964fe536e5deffb81da579e6b>

## Upstream Delta Since the Previous Pin

The compare range contains 47 commits. Each commit is owned exactly once by one
of the 12 first-parent merge groups below. Each group has one stance from the
closed set `adopted`, `equivalent-local`, `migration-only`, `deferred`, or
`irrelevant`.

| Delta decision | Upstream change, as its sources describe it | Stance | Release-critical | Merge group |
|---|---|---|---|---|
| `opt-in-release-awareness` | Disabled-by-default stable-release checks, cached agent status, and installer-specific upgrade plans | `equivalent-local` | yes | `dae19f61` |
| `release-history-sync` | Develop imports the 3.7.1 and 3.8.0 main release merge ancestry | `irrelevant` | no | `45ee7608` |
| `logstream-topic-reverse-pagination` | Logstream topic routing plus status, before-event, and ordering filters | `irrelevant` | no | `c524d11a` |
| `ruff-precommit-pin` | Upstream pre-commit Ruff pin alignment | `irrelevant` | no | `b54f64cd` |
| `docker-login-action-update` | Upstream image workflow raises docker/login-action to 4.6.0 | `irrelevant` | no | `6242edfb` |
| `qdrant-bounded-get-scroll` | Qdrant bounds safe paged `get()` scrolling by offset plus limit | `irrelevant` | no | `49737d50` |
| `concurrent-hub-palace-reads` | HTTP MCP palace reads use a shared lock while writes remain exclusive | `irrelevant` | no | `da245c6c` |
| `closet-search-source-index` | Closet search indexes source lookups and reports raw vector similarity | `irrelevant` | no | `6597908a` |
| `private-palace-search-benchmark` | A private-palace search benchmark harness and operator procedure | `irrelevant` | no | `b0b10aa8` |
| `embeddinggemma-batch-size-override` | EmbeddingGemma sub-batch size becomes configurable | `irrelevant` | no | `dc43751c` |
| `live-hub-cli-search-forwarding` | CLI search reuses a compatible live hub with configuration, output, and token guards | `irrelevant` | no | `307a6765` |
| `release-3-9-0-metadata` | Package, plugin, integration, badge, lockfile, and changelog sources move to 3.9.0 | `irrelevant` | no | `e8098348` |

The manifest records the exact 47-commit full-range inventory for
`a9f345cc..e8098348`: 12 top-level merge commits, four nested merge commits,
and a 31-commit non-merge constituent subset. Its SHA-256 anchor is
`4ee827c643113410c17140162f4650930586a5b4ea92d28ca720b2ec6cd648df`.
Grouped by the top-level merge commits:

- `dae19f61`: `c83f1ebc`, `8baf1df4`
- `45ee7608`: `359c579d` (nested merge), `87e6f383` (nested merge), `98a0f824` (nested merge)
- `c524d11a`: `148bc6f2`
- `b54f64cd`: `59ce3588`
- `6242edfb`: `238b5ce9`
- `49737d50`: `720f3d81`
- `da245c6c`: `dc085859`
- `6597908a`: `fe98bfce`
- `b0b10aa8`: `3bf31aaa`
- `dc43751c`: `a616a577`
- `307a6765`: `b232fa3d`, `87ec8545`, `460924eb`, `90e8214b`, `67be3950`, `ae8a4e8c`, `fd556bee`, `e9616245`, `bd94b7f4`, `733a0c6d`, `e016aff4`, `2edd215b`, `24dc2e6b`, `4a971ef3`, `90dcd41f`, `f19ea69f`, `648ef944`, `75770f4f`, `722bf22a`, `e20384c7`, `c044acda` (nested merge)
- `e8098348`: `434f00b5`

**Equivalent locally.** `opt-in-release-awareness` maps to the fork's existing
version-check and updater owners. Checks and scheduling are disabled by default;
`update status` and `update check` are explicit read-only paths; `update apply
--yes` requires confirmation and a supported installer; malformed configuration,
unsupported platforms, and overlapping scheduled work fail closed. The cited
predicates verify those outcomes. Upstream's MCP cached-status response shape is
outside this equivalence claim.

**Not applicable.** The fork has no live HTTP hub, logstream database, closet
index, EmbeddingGemma runtime, Qdrant backend, upstream Docker publication, or
upstream release-metadata owner. The private benchmark supplies no comparable
fork measurement. Repository-only dependency, history, and version changes
remain owned by each repository.

The release-critical update-awareness row is closed by existing local predicates.
The range therefore has zero unresolved release-critical decisions and imports no
upstream runtime behavior.

## Capability Comparison

| Area | Upstream, as advertised at the reviewed commit | This fork today |
|---|---|---|
| Product focus | General-purpose AI memory | Code-first memory: repository mining, `code_search`, symbol/type/project-graph tools |
| Storage and retrieval | ChromaDB default; `sqlite_exact`, Milvus, Qdrant, and pgvector are offered; hybrid retrieval and optional LLM reranking are described; 3.9.0 adds bounded safe Qdrant `get()` scrolling and a closet source index | LanceDB-only current package with ChromaDB support retired; local deterministic `code_search(rerank="hybrid")`; no LLM reranker or server-vector backends |
| Embeddings | New onboarding offers multilingual `embeddinggemma-300m`; opt-in `openai-compat` targets an OpenAI-compatible endpoint; 3.9.0 adds an EmbeddingGemma sub-batch override | `all-MiniLM-L6-v2`; no supported multilingual configuration or migration path, and no remote embedding-provider integration |
| Search | Date-window filtering is advertised; 3.9.0 can forward compatible CLI searches to a live hub and reports raw vector similarity for closet-enriched search | No date-window or live-hub forwarding surface; local Lance search remains process-local |
| Agent integration | A Hermes `MemoryProvider`, source adapters, shared-hub routing, and skill-first coordination are advertised | No Hermes provider, source-adapter ingestion, or shared-hub surface |
| MCP count and plugin wording | README and Claude plugin wording say 45 MCP tools; the Codex plugin wording says 44 | Direct stdio MCP registration defaults to the full 29-tool profile |
| Plugin metadata | Codex manifest identifies `mempalace` version 3.9.0 and points at `.mcp.json` | Standards-conformant Agent Plugins 1.0 portable package with a four-tool default |
| Coordination and replication | Logstream includes watcher behavior, topic routing, reverse pagination, artifact handoffs, and an RFC 004 multi-master foundation | No logstream, palace replication, mesh, or live-hub transport |
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

The manifest carries the exact source mapping. The established capabilities
remain pinned to README, changelog, plugin/MCP metadata, and RFC 003–005. The
new 3.9.0 capabilities use these reviewed sources:

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
Plugins 1.0 portable package defaults to the four-tool `minimal` profile.

## Evidence Limits

- **Repository review only.** Claims come from the exact compare range and the
  pinned README, changelog, package, plugin/MCP, runtime, benchmark, and RFC
  sources. No upstream behavior was run.
- **Nothing was measured.** This document contains no cross-project benchmark,
  quality, performance, adoption, or compatibility measurement.
- **Delta stances are about this fork.** Every commit is assigned to one merge
  group. The update-awareness row claims only equivalent local outcomes backed
  by the named predicates; the other 11 rows are repository-only `irrelevant`
  decisions with no local predicate claim.
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
