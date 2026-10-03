# Upstream Comparison — Reviewed Snapshot

This is the canonical, source-pinned comparison between `rergards/mempalace-code` and the public upstream `mempalace` project. It records scope decisions; it does not claim runtime interoperability or benchmark equivalence.

## Snapshot

| Field | Value |
|---|---|
| Reviewed date | `2026-09-26` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `8c4865f70c49b6346c53474a9e5684c5f17d3fa9` |
| Previous reviewed commit | `e038af9703d2467bb7cfffdd3f7fb2bd212e58a4` |
| Previous reviewed date | `2026-09-20` |
| Upstream release described by its changelog | `3.10.0` |
| Fork commit at review time | this repository, release preparation branch |

Upstream code was reviewed at the pinned commit. It was not run, benchmarked, or compatibility-tested.

## Source Links

- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/README.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/.claude-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/.dsh-plugin/README.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/crates/README.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/benchmarks/PRIVATE_PALACE.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/docs/rfcs/005-agent-identity-routing.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/integrations/shared/coordination-protocol.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/website/guide/lightweight-mcp.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/config.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/split_mega_files.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/update_awareness.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/hub_client.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/logstream.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/mcp_server/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/mcp_server/http.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/mcp_server/protocol.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/mcp_server/runtime.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/searcher/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/searcher/ranking.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/embedding.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/backends/qdrant.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/backends/rust_exact.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/cli/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/cli/parser.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/cli_write_routing.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/knowledge_graph.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/mcp_light_server.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/query_parser.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/normalize.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/entity_registry.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/diary_ingest.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/daemon.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/source_identity.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/wal.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/sync.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/mcp_server/schemas.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/backends/_inproc_sqlite.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/mcp_proxy.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/cli/cmd_repair.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/palace/mined.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/docs/CLOSETS.md>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/convo_miner.py>
- <https://github.com/MemPalace/mempalace/blob/8c4865f70c49b6346c53474a9e5684c5f17d3fa9/mempalace/palace_audit.py>

Exact compare range: <https://github.com/MemPalace/mempalace/compare/e038af9703d2467bb7cfffdd3f7fb2bd212e58a4...8c4865f70c49b6346c53474a9e5684c5f17d3fa9>

## Upstream Delta Since the Previous Pin

The range contains exactly 10 commits. Each SHA is owned once by one review group.

| Delta decision | Upstream change | Stance | Release-critical | Review group |
|---|---|---|---|---|
| `sync-gitignored-directory-identity` | read the mined directory's inode around a gitignored sync verdict | `irrelevant` | no | `b0ba43df` |
| `bulk-drawer-mcp-tools` | add the mempalace_get_drawers and mempalace_delete_drawers bulk MCP tools, taking the registry from 45 to 47 tools | `deferred` | no | `56896741` |
| `chroma-inprocess-sqlite-locks` | route in-process Python sqlite3 readers of chroma.sqlite3 through one lock owner so they stop dropping ChromaDB's SQLite locks | `irrelevant` | no | `beb945f6` |
| `stdio-proxy-unserved-requests` | make the hub-forwarding stdio proxy answer the requests it cannot serve instead of dropping them | `irrelevant` | no | `64c7551b` |
| `stdio-parse-error-any-loads-failure` | keep the stdio servers up and answer -32700 when json.loads raises ValueError (integer digit limit) or RecursionError (deep nesting) | `adopted` | no | `5b837246` |
| `legacy-repair-palace-lease` | hold the palace mine lease across the legacy repair's extraction, backup, and rebuild | `equivalent-local` | yes | `1166d2d9` |
| `scoped-mined-set-prefetch` | scope prefetch_mined_set to the candidate files instead of paging the whole ChromaDB collection | `irrelevant` | no | `c4d3711e` |
| `closets-drawer-first-docs` | document closet search as drawer-first with a closet boost | `irrelevant` | no | `af818166` |
| `convo-exchange-chunker-text-loss` | stop the conversation exchange chunker from discarding text and stamp exchange rows so the next convos mine rebuilds them once | `equivalent-local` | yes | `66a354bf` |
| `palace-audit-guided-repair` | palace audit scoring and guided repair: LLM-proposed rooms, wing split, tunnel propose and prune, KG predicate normalization, hallway rebuild, and related hook, sqlite_exact, and MCP changes | `irrelevant` | no | `8c4865f7` |

Inventory anchor: `f44ba1ff64c373a59e18c265be151d6e8869b9481b1258904a757a989fc1879f` (`sha256`, 10 commits).

Review groups:

- `b0ba43df`
- `56896741`
- `beb945f6`
- `64c7551b`
- `5b837246`
- `1166d2d9`
- `c4d3711e`
- `af818166`
- `66a354bf`
- `8c4865f7`

The two release-critical groups, the conversation exchange chunker text loss and
the lease-less full `repair` rebuild, are fixed locally and recorded as
equivalent. The stdio parse-error change is adopted: the fork's server answers
those lines with `-32700` and keeps serving. Bulk drawer tools would
change the 29-tool contract. The other groups are bound to upstream sync,
ChromaDB, hub-proxy, closet, and audit owners that this fork does not have.

## Capability Comparison

| Area | Upstream at the reviewed commit | This fork today |
|---|---|---|
| Product and storage | General-purpose memory with ChromaDB, sqlite_exact, optional Rust exact search, and server backends | Code-first memory with one LanceDB owner |
| MCP and distribution | 47-tool full MCP registry (its README and plugin manifests still advertise 45 or 44), optional three-tool PQL facade, hub/daemon/logstream surfaces, plugins and native artifacts | 29-tool typed stdio profile plus four-tool portable minimal profile; pip/pipx package |
| Retrieval | Hybrid retrieval, optional LLM reranking, configurable weights, date provenance, and multiple backend optimizations | Local deterministic vector and code hybrid rerank; no LLM reranker |
| Palace upkeep | `audit` scoring plus guided repair: LLM-proposed rooms, wing split, tunnel propose/prune, KG predicate normalization | `health`, `repair`, `cleanup`, and receipt-bound wing migration; no audit score or LLM-assisted reorganization |
| Coordination | Hub routing, daemon write policy, logstream, shared-brain rules and replication foundations | Local watcher/miner ownership guards; no hub, logstream, or replication |
| Privacy | Entity-registry Wikipedia lookup removed at the reviewed commit; configured remote backends remain optional | No unconfigured entity-research network path; legacy wiki cache remains readable |

## Capability Identifiers

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
- `optional-native-rust-exact`
- `xdg-config-default-new-installs`
- `cli-daemon-write-routing`
- `configurable-hybrid-rank-weights`
- `drawer-last-modified`
- `search-date-provenance`
- `kg-timeline-pagination`
- `dsh-plugin`
- `entity-registry-no-unconfigured-network`
- `diary-pagination-beyond-legacy-limit`
- `mcp-tools-47-registry`
- `palace-audit-guided-repair`

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

Every upstream identifier is mapped in the manifest to one or more pinned sources. The complete tracked set is published above; the machine-readable mapping is authoritative.

- `embeddinggemma-default-for-new-onboarding`: `README.md`, `CHANGELOG.md`
- `hybrid-retrieval`: `README.md`
- `optional-llm-reranking`: `README.md`
- `backend-chromadb`: `README.md`
- `backend-sqlite-exact`: `README.md`
- `backend-milvus`: `README.md`
- `backend-qdrant`: `README.md`
- `backend-pgvector`: `README.md`
- `chroma-sqlite-metadata-read-paths`: `CHANGELOG.md`
- `sqlite-exact-indexed-structured-fields`: `CHANGELOG.md`
- `mcp-tools-45-readme`: `README.md`
- `claude-plugin-tools-45`: `.claude-plugin/plugin.json`
- `codex-plugin-tools-44`: `.codex-plugin/plugin.json`
- `codex-plugin-metadata`: `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `.mcp.json`
- `openai-compatible-embeddings`: `README.md`
- `search-date-window`: `CHANGELOG.md`
- `hermes-memory-provider-core`: `CHANGELOG.md`
- `source-adapters-mine`: `CHANGELOG.md`
- `agent-logstream-artifact-handoffs`: `CHANGELOG.md`, `docs/rfcs/003-agent-logstream-coordination.md`
- `logstream-multi-master-sync-foundation`: `CHANGELOG.md`, `docs/rfcs/004-replicated-palace.md`
- `live-palace-hub-write-routing`: `CHANGELOG.md`, `docs/rfcs/003-agent-logstream-coordination.md`
- `read-replica-mesh-preview`: `docs/rfcs/004-replicated-palace.md`
- `multiarch-docker-image`: `README.md`
- `process-lifetime-single-writer`: `CHANGELOG.md`
- `agent-logstream-watch`: `CHANGELOG.md`
- `opt-in-release-awareness`: `README.md`, `CHANGELOG.md`, `mempalace/update_awareness.py`
- `live-hub-cli-search-forwarding`: `CHANGELOG.md`, `mempalace/hub_client.py`, `mempalace/mcp_server/__init__.py`
- `concurrent-hub-palace-reads`: `CHANGELOG.md`, `mempalace/mcp_server/__init__.py`
- `agent-logstream-topic-routing`: `mempalace/logstream.py`, `docs/rfcs/003-agent-logstream-coordination.md`
- `agent-logstream-reverse-pagination`: `mempalace/logstream.py`, `docs/rfcs/003-agent-logstream-coordination.md`
- `embeddinggemma-batch-size-override`: `CHANGELOG.md`, `mempalace/embedding.py`
- `qdrant-bounded-get-scroll`: `CHANGELOG.md`, `mempalace/backends/qdrant.py`
- `closet-search-source-index`: `CHANGELOG.md`, `mempalace/searcher/__init__.py`
- `private-palace-search-benchmark`: `benchmarks/PRIVATE_PALACE.md`
- `lightweight-mcp-pql-three-tools`: `website/guide/lightweight-mcp.md`, `mempalace/mcp_light_server.py`, `mempalace/query_parser.py`, `mempalace/cli/__init__.py`, `pyproject.toml`
- `kg-entity-candidate-temporal-buckets`: `mempalace/mcp_server/__init__.py`, `mempalace/knowledge_graph.py`
- `on-demand-logstream-coordination`: `integrations/shared/coordination-protocol.md`
- `optional-native-rust-exact`: `README.md`, `CHANGELOG.md`, `crates/README.md`, `mempalace/backends/rust_exact.py`
- `xdg-config-default-new-installs`: `CHANGELOG.md`, `mempalace/config.py`
- `cli-daemon-write-routing`: `CHANGELOG.md`, `mempalace/cli_write_routing.py`
- `configurable-hybrid-rank-weights`: `CHANGELOG.md`, `mempalace/searcher/ranking.py`
- `drawer-last-modified`: `CHANGELOG.md`
- `search-date-provenance`: `CHANGELOG.md`, `mempalace/searcher/__init__.py`
- `kg-timeline-pagination`: `CHANGELOG.md`, `mempalace/knowledge_graph.py`
- `dsh-plugin`: `CHANGELOG.md`, `.dsh-plugin/README.md`
- `entity-registry-no-unconfigured-network`: `CHANGELOG.md`, `mempalace/entity_registry.py`
- `diary-pagination-beyond-legacy-limit`: `CHANGELOG.md`, `mempalace/diary_ingest.py`
- `mcp-tools-47-registry`: `mempalace/mcp_server/schemas.py`, `website/guide/lightweight-mcp.md`
- `palace-audit-guided-repair`: `README.md`, `CHANGELOG.md`, `mempalace/palace_audit.py`

## Fork Stance

**Adopted safety.** The fork refuses raw fallback for recognized incomplete Codex rollouts, preserves malformed or unreadable entity registries, bounds entity-registry temporary-name collisions, and contains no callable Wikipedia research path. Its stdio loop answers a line that `json.loads` rejects with `ValueError` or `RecursionError` with `-32700` and keeps serving.

**Equivalent protocol behavior.** Existing tests cover diary reads beyond the former limit, malformed JSON-RPC envelopes with preserved request IDs and session continuity, and `--palace` placement before or after a subcommand. MCP imports ignore host-process arguments; executable flag parsing is owned by `dispatch.main(argv)`.

**Storage boundary.** LanceDB remains the only current backend. Rust exact search, ChromaDB, sqlite_exact, pgvector, Qdrant, hub, daemon, logstream, upstream distributed sync, JSON write-audit WAL, closets, persistent hallway and tunnel files, and replication contracts are outside this release.

**Equivalent conversation chunking.** `mempalace_code/convo_miner.py` keeps every non-blank transcript line with its line breaks: text before a turn joins that turn, long exchanges split at paragraph or line boundaries, and short units merge into a neighbour. Exchange rows are stamped `convo_turn_v3` with a source hash, so the next convos mine rebuilds rows of earlier strategies once.

**Equivalent repair lease.** `mempalace_code/cli_commands/maintenance.py` runs the full `repair` rebuild, `repair --rollback`, and `cleanup` under the installation's exclusive operation lease. Every palace writer (mine, convos mine, import, backup, and MCP writes) holds the shared side of that lease through `operation_lock.palace_write_lease`, so no drawer can be written between the rebuild's extraction and its swap.

**Deferred additions.** Ranking weights, last-modified metadata, date provenance, KG pagination, XDG default migration, and bulk drawer MCP tools require their own acceptance and migration evidence.

## Evidence Limits

- Repository review only; upstream behavior was not executed.
- Fork-side statements come from this fork's code, its existing tests, and two local checks on 2026-09-26: a direct call of the exchange chunker and one stdio smoke of this fork's MCP server.
- No cross-project performance or quality claim is made.
- Decisions describe applicability to this fork at this release candidate.
- Only public `develop` at the pinned commit was reviewed.

## Automation Policy

Static mode validates manifest shape, pins, source links, capability mappings, decisions, local predicates, inventory count and digest, document synchronization, and the README snapshot's commit and review date. Live mode adds one credential-free read of the public upstream head and fails closed on drift.

Canonical release command:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

## Drift Recovery

If live mode reports a different upstream head, review the exact new range, update both comparison files and the README snapshot, run the static guard and focused predicates, then retry the release preflight. Do not tag against stale evidence.

Recovery command:

```bash
python scripts/upstream_comparison_guard.py --check-live --json
```
