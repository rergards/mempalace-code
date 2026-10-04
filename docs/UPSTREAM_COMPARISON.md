# Upstream Comparison — Reviewed Snapshot

This is the canonical, source-pinned comparison between `rergards/mempalace-code` and the public upstream `mempalace` project. It records scope decisions; it does not claim runtime interoperability or benchmark equivalence.

## Snapshot

| Field | Value |
|---|---|
| Reviewed date | `2026-10-03` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `43122aefb8ed58e9fa4e1953e15ce70026339ec2` |
| Previous reviewed commit | `8c4865f70c49b6346c53474a9e5684c5f17d3fa9` |
| Previous reviewed date | `2026-09-26` |
| Upstream release described by its changelog | `3.11.0` |
| Fork commit at review time | this repository, release preparation branch |

Upstream code was reviewed at the pinned commit. It was not run, benchmarked, or compatibility-tested.

## Source Links

- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/README.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/.claude-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/.dsh-plugin/README.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/crates/README.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/benchmarks/PRIVATE_PALACE.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/docs/rfcs/005-agent-identity-routing.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/integrations/shared/coordination-protocol.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/website/guide/lightweight-mcp.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/config.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/split_mega_files.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/update_awareness.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/hub_client.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/logstream.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/http.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/protocol.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/runtime.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/searcher/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/searcher/ranking.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/embedding.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/backends/qdrant.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/backends/rust_exact.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/cli/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/cli/parser.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/cli_write_routing.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/knowledge_graph.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_light_server.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/query_parser.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/normalize.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/entity_registry.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/diary_ingest.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/daemon.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/source_identity.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/wal.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/sync.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/schemas.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/backends/_inproc_sqlite.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_proxy.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/cli/cmd_repair.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/palace/mined.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/docs/CLOSETS.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/convo_miner.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/palace_audit.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/backends/chroma.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/_session.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/searcher/candidates.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/_guards.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/tools_write.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/cli/cmd_sync.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/tools_coord.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/cli/_hub.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/website/reference/benchmarks.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/skills/mempalace-recall/SKILL.md>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/mcp_server/tools_read.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/hallways.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/tunnels_tool.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/hooks_cli.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/rooms.py>
- <https://github.com/MemPalace/mempalace/blob/43122aefb8ed58e9fa4e1953e15ce70026339ec2/mempalace/cli/cmd_rooms.py>

Exact compare range: <https://github.com/MemPalace/mempalace/compare/8c4865f70c49b6346c53474a9e5684c5f17d3fa9...43122aefb8ed58e9fa4e1953e15ce70026339ec2>

## Upstream Delta Since the Previous Pin

The range contains exactly 36 commits in 15 review groups. Each SHA is owned once.

| Delta decision | Upstream change | Stance | Release-critical | Review group |
|---|---|---|---|---|
| `release-history-and-docker` | release 3.11.0 metadata, version guards, Docker action upgrades and history merges | `irrelevant` | no | `22fd87f0` |
| `chroma-reader-and-latency` | Chroma SQLite reader locks, WAL snapshots, cache invalidation, hydration, responsive hub mining and folding duplicate search passages | `deferred` | no | `6a91fdb3` |
| `kg-peer-writer-exemption` | exempt KG mutations from the Chroma peer-writer lease | `irrelevant` | no | `e692c61b` |
| `case-only-drawer-rename` | preserve case-only wing and room changes in update_drawer | `irrelevant` | no | `a7610e2c` |
| `daemon-relative-paths` | resolve sweep and sync paths at the calling CLI before forwarding | `irrelevant` | no | `5ea40d30` |
| `mcp-annotations-and-session-description` | advertise readOnlyHint for inspection tools, omit it for checkpoint acknowledgements and describe search as past-session retrieval | `deferred` | no | `f353bd96` |
| `http-embedding-handle-lifecycle` | release HTTP locks around embedding inference and protect diary handles during reconnect | `irrelevant` | no | `e1b7b96b` |
| `logstream-writer-filter` | separate event writer filters from caller identity | `irrelevant` | no | `27d678a3` |
| `hub-include-ignored-mining` | forward include-ignored project mining through capable HTTP hubs | `irrelevant` | no | `a33c3d68` |
| `locomo-rerank-benchmark-docs` | clarify upstream LoCoMo rerank recall limits | `irrelevant` | no | `326c1c6e` |
| `agent-needed-context-guidance` | guide agents to retrieve only needed prior memory context | `irrelevant` | no | `90e814c8` |
| `persistent-hallway-and-tunnel-identity` | configure hallway co-occurrence thresholds and preserve distinct file extensions and ambiguous tunnel links | `irrelevant` | no | `fa429f5d` |
| `hook-count-units` | report filed drawers and folded messages as separate stop-hook units | `irrelevant` | no | `d8babcbf` |
| `kg-rewrite-future-successor` | reuse rewritten KG successors only when currently valid and provenance matches | `irrelevant` | no | `ae5a54da` |
| `approved-room-and-closet-replay` | preserve approved room spelling and resume closet moves by stable identity with validated pending snapshots | `irrelevant` | no | `165711cf` |

Inventory anchor: `e4f6add26a76ae742830f06931cc7272db7f122414522f4d38ad2062526d56b2` (`sha256`, 36 commits).

Review groups:

- `22fd87f0`: `0285c800`, `37c9cc0b`, `e101ad32`, `3c9d4e26`, `a33fdcc9`, `4b70143f`, `7b1a4ac2`
- `6a91fdb3`: `9ba1a470`, `e9cfad0a`, `7e090ccc`, `3f6052fa`, `56ece709`, `ad05d1b7`, `a90b1bc6`
- `e692c61b`
- `a7610e2c`
- `5ea40d30`
- `f353bd96`: `55008ed9`
- `e1b7b96b`: `b9c86655`
- `27d678a3`
- `a33c3d68`
- `326c1c6e`
- `90e814c8`
- `fa429f5d`: `6f3f755b`, `738913a6`
- `d8babcbf`
- `ae5a54da`
- `165711cf`: `29fc9932`, `062d8a83`, `43122aef`

### Applicability

- `release-history-and-docker`: The fork owns independent package and release metadata and does not publish the upstream Docker image. Merge bookkeeping is included in the exact inventory; its product delta is assessed in the other groups.
- `chroma-reader-and-latency`: The Chroma, HNSW, HTTP-hub and direct SQLite drawer owners are absent from this LanceDB-only fork. Folding copies changes the retrieval result contract and remains deferred; no equivalent latency, copy-folding or large-palace performance claim is made.
- `kg-peer-writer-exemption`: The fork has no upstream Chroma peer-writer lease or kg_supersede tool. Its existing installation fence and SQLite KG owners retain their current contracts.
- `case-only-drawer-rename`: The fork does not expose upstream's mempalace_update_drawer tool. Its taxonomy and mining paths are separate owners; this delta does not change their naming contract.
- `daemon-relative-paths`: The fork has no daemon-forwarded sweep/sync route. Its existing CWD precedence question remains outside this refresh and no path-resolution semantics change.
- `mcp-annotations-and-session-description`: The fork's 29-tool registry and code-question audience remain unchanged. New annotations require effect classification of the fork's own handlers; upstream's conversation-oriented search description is not applied to code search.
- `http-embedding-handle-lifecycle`: The fork serves stdio MCP and has no upstream HTTP request lock, hub reconnect or shared Chroma diary handle.
- `logstream-writer-filter`: The fork has no event-list/event-wait logstream or coordination parser.
- `hub-include-ignored-mining`: The fork has no CLI-to-hub forwarding route. Adding a new MCP mining option is outside this metadata refresh; current source filters and secret guards remain unchanged.
- `locomo-rerank-benchmark-docs`: The fork does not claim upstream's benchmark scores or use its LLM reranker. Its code and text benchmark gates remain independently owned.
- `agent-needed-context-guidance`: The fork's established audience asks questions about repository code. Current instruction and artifact owners retain that scope; conversation persistence is not added.
- `persistent-hallway-and-tunnel-identity`: The fork has no upstream persistent hallway/tunnel files or alias-pruning route. Its graph is computed from LanceDB metadata on read; no graph feature or destructive pruning contract changes.
- `hook-count-units`: Automatic conversation checkpointing is outside the fork's default code-question workflow. This refresh does not enable, repair or import an upstream conversation-save route.
- `kg-rewrite-future-successor`: The fork KnowledgeGraph exposes add/invalidate/sync/query operations and has no upstream rewrite operation or automatic successor reuse. Existing temporal tests and SQLite data remain unchanged.
- `approved-room-and-closet-replay`: The fork has no LLM-proposed approved room-set files, closet collection or pending closet-apply journal. Its local room detector and version-controlled configuration do not acquire this lifecycle.

The previous review's equivalent conversation chunking, repair lease and stdio parse-error controls remain in the fork. The current delta adds no adopted implementation or durable architecture decision. Runtime behavior, the 29-tool registry, storage ownership and model policy remain unchanged.

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
- Fork-side statements use current source and existing tests. The two direct chunker/stdio checks from 2026-09-26 remain historical evidence; this refresh reruns the manifest guard and affected documentation tests.
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
