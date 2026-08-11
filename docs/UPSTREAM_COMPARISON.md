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
| Reviewed date | `2026-08-11` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `b2104238d4491654f17118d12cf876ac5e41a0cf` |
| Upstream release described by its changelog | `3.7.0` |
| Upstream paths tracked for drift | `README.md`, `CHANGELOG.md`, `pyproject.toml`, `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `.mcp.json`, RFCs 003–005 |
| Fork commit at review time | this repository, `main` |

All upstream statements below are limited to the pinned public sources. Upstream
code was read only where the advertised source named a surface; it was not run,
benchmarked, or independently compatibility-tested.

## Source Links

Pinned primary upstream sources:

- <https://github.com/MemPalace/mempalace/tree/b2104238d4491654f17118d12cf876ac5e41a0cf>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/README.md>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/b2104238d4491654f17118d12cf876ac5e41a0cf/docs/rfcs/005-agent-identity-routing.md>

## Capability Comparison

| Area | Upstream, as advertised at the reviewed commit | This fork today |
|---|---|---|
| Product focus | General-purpose AI memory | Code-first memory: repository mining, `code_search`, symbol/type/project-graph tools |
| Storage and retrieval | ChromaDB default; `sqlite_exact`, Milvus, Qdrant, and pgvector are offered; hybrid retrieval and optional LLM reranking are described | LanceDB default; deprecated optional ChromaDB compatibility extra; local deterministic `code_search(rerank="hybrid")`; no LLM reranker or server-vector backends |
| Embeddings | New onboarding offers multilingual `embeddinggemma-300m`; opt-in `openai-compat` targets an OpenAI-compatible `/v1/embeddings` endpoint | `all-MiniLM-L6-v2`; no supported multilingual configuration or migration path, and no remote embedding-provider integration |
| Search filtering | `mempalace_search` and CLI search advertise `since` / `before` date windows | No matching documented date-window search surface |
| Agent integration | Changelog 3.7.0 advertises a core Hermes `MemoryProvider` and `mine --source <adapter>` source-adapter resolution | No Hermes provider or source-adapter ingestion surface |
| MCP count and plugin wording | README says 44 MCP tools. The separate Codex plugin manifest says 36 MCP tools, auto-save hooks, and guided setup; the two advertised count wordings are recorded separately rather than reconciled here | Direct stdio MCP registration defaults to the full 29-tool profile |
| Plugin metadata | Codex manifest identifies `mempalace` version 3.7.0, points at `.mcp.json`, and describes a Codex-oriented interface; marketplace metadata advertises a local plugin source | Standards-conformant Agent Plugins 1.0 portable package with `plugin.json`, `mcp.json`, vendored schemas, and a skill |
| Portable default | No Agent Plugins 1.0 package was reviewed in the pinned upstream sources | The portable Agent Plugins package defaults to exactly four tools: status, search, duplicate check, and add drawer |
| Coordination and replication | 3.7.0 advertises logstream events, artifact handoffs, and an RFC 004 logstream multi-master sync foundation; RFC 004 separates shipped early steps from later planned palace op-log work | No logstream, palace replication, mesh, or live-hub transport |
| Distribution | Python package and advertised multi-arch Docker image | Python package and pipx installation; no published Docker image |
| Writer ownership | Changelog describes shared write routing and process-lifetime single-writer recovery | Local watcher/miner/maintenance ownership guards |

The table reports source wording and documented surfaces. It does not establish
runtime interoperability, performance, or completeness beyond those sources.

## Capability Identifiers

The following identifiers are recorded in
[`docs/quality/upstream-comparison.json`](quality/upstream-comparison.json).
Every listed identifier must appear here.

Upstream, advertised at the reviewed commit:

- `embeddinggemma-default-for-new-onboarding`
- `hybrid-retrieval`
- `optional-llm-reranking`
- `backend-chromadb`
- `backend-sqlite-exact`
- `backend-milvus`
- `backend-qdrant`
- `backend-pgvector`
- `mcp-tools-44`
- `codex-plugin-manifest-tools-36`
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

This fork, current:

- `code-first-mining`
- `backend-lancedb-default`
- `backend-chromadb-optional-deprecated`
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

## Fork Stance

**Embeddings.** The supported default remains `all-MiniLM-L6-v2`. The fork has
no supported multilingual model configuration or migration flow. A model change
requires the text and code retrieval evidence and migration support defined in
`CLAUDE.md`.

**Retrieval and reranking.** The fork retains one local deterministic hybrid
path, `code_search(rerank="hybrid")`. It does not add a general remote or LLM
reranking layer.

**Agent and distributed surfaces.** Hermes integration, source adapters,
logstream, live-hub routing, and replication are outside the current local
code-memory scope. The upstream RFC 004 source explicitly distinguishes its
shipped logstream foundation from later planned replication work; this fork
makes no compatibility claim for either.

**MCP and packages.** A direct MCP registration without selectors exposes the
full 29-tool default. The separate Agent Plugins 1.0 portable package defaults
to the four-tool `minimal` profile. The profiles are an intentional prompt/tool
surface choice, not an upstream compatibility claim.

## Evidence Limits

- **Repository review only.** Claims come from the pinned README, changelog,
  package metadata, plugin/MCP files, and RFCs. No upstream behavior was run.
- **Nothing was measured.** This document contains no benchmark, quality,
  performance, adoption, or compatibility measurement.
- **Plugin counts are source-local wording.** The README's 44-tool claim and
  the Codex plugin manifest's 36-tool wording are both preserved as observed;
  this review does not infer a single reconciled count.
- **One branch, one commit.** Only `develop` at the pinned commit was reviewed.
  Upstream default-branch, tag, release, and future state can differ.
- **Historical criticism is separate.**
  [`UPSTREAM_HARDENING.md`](UPSTREAM_HARDENING.md) describes April 2026
  material and is not evidence about upstream at this reviewed commit.

## Automation Policy

`scripts/upstream_comparison_guard.py` has two modes.

**Static mode (default).** It validates manifest shape, pin format, review age,
README/document pointers, and capability identifiers using only the checkout.
It is deterministic and network-free. CI lint and the default
`scripts/release_preflight.py` use this mode.

**Live mode (`--check-live`, explicit).** It performs one read-only GitHub API
request for the pinned branch head and fails closed on drift, fetch failure, or
an unusable response. It never rewrites source or GitHub state. The canonical
pre-tag command is:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

That opt-in preflight path delegates to this guard's `--check-live` mode before
an immutable tag is made. `.github/workflows/publish.yml` retains its direct
live guard as defense in depth after a tag exists. On any failure, re-review
upstream at its current head and update this document and the manifest together.
