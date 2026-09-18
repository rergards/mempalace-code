# Upstream Comparison — Reviewed Snapshot

This is the canonical, source-pinned comparison between `rergards/mempalace-code` and the public upstream `mempalace` project. It records scope decisions; it does not claim runtime interoperability or benchmark equivalence.

## Snapshot

| Field | Value |
|---|---|
| Reviewed date | `2026-09-18` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `25203ed6ee1a739103a77e87219a1f679dee81e9` |
| Previous reviewed commit | `d9f059076c866fa6f29195679d75712436986024` |
| Previous reviewed date | `2026-09-02` |
| Upstream release described by its changelog | `3.10.0` |
| Fork commit at review time | this repository, release preparation branch |

Upstream code was reviewed at the pinned commit. It was not run, benchmarked, or compatibility-tested.

## Source Links

- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/README.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/.claude-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/.dsh-plugin/README.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/crates/README.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/benchmarks/PRIVATE_PALACE.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/docs/rfcs/005-agent-identity-routing.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/integrations/shared/coordination-protocol.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/website/guide/lightweight-mcp.md>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/config.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/split_mega_files.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/update_awareness.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/hub_client.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/logstream.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/mcp_server/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/mcp_server/http.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/mcp_server/protocol.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/mcp_server/runtime.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/searcher/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/searcher/ranking.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/embedding.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/backends/qdrant.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/backends/rust_exact.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/cli/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/cli/parser.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/cli_write_routing.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/knowledge_graph.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/mcp_light_server.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/query_parser.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/normalize.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/entity_registry.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/diary_ingest.py>
- <https://github.com/MemPalace/mempalace/blob/25203ed6ee1a739103a77e87219a1f679dee81e9/mempalace/daemon.py>

Exact compare range: <https://github.com/MemPalace/mempalace/compare/d9f059076c866fa6f29195679d75712436986024...25203ed6ee1a739103a77e87219a1f679dee81e9>

## Upstream Delta Since the Previous Pin

The range contains exactly 89 commits. Each SHA is owned once by one review group. The legacy manifest field `merge_group` stores the first SHA of each review group; groups may contain direct commits as well as merge commits.

| Delta decision | Upstream change | Stance | Release-critical | Review group |
|---|---|---|---|---|
| `native-and-retired-backends` | optional Rust exact search plus sqlite_exact, ChromaDB, pgvector, Qdrant, HNSW, and native-wheel changes | `irrelevant` | no | `753f08f3` |
| `distributed-runtime-integrations` | hub and daemon writer routing, logstream lifecycle, shared-brain rules, DSH integration, and distributed coordination fixes | `irrelevant` | no | `92a8ac6b` |
| `structural-release-maintenance` | module and test splits, dependency and workflow maintenance, documentation, release metadata, and branch synchronization | `irrelevant` | no | `1beed5a3` |
| `protocol-cli-equivalents` | diary pagination beyond the legacy limit, total JSON-RPC replies for requests with ids, and natural --palace option placement | `equivalent-local` | yes | `87a01ddf` |
| `local-ingest-registry-safety` | raw Codex fallback refusal, registry preservation and bounded temporary names, plus removal of an unconfigured Wikipedia lookup | `adopted` | yes | `46406439` |
| `optional-retrieval-metadata` | optional ranking weights, drawer timestamps, search date provenance, KG pagination, XDG defaults, and retrieval performance changes | `deferred` | no | `39c1200d` |
| `upstream-runtime-specific-fixes` | repair, hook, collection-name, environment, and integrity fixes bound to upstream Chroma, hub, daemon, or hook implementations | `irrelevant` | no | `e32b1e84` |

Inventory anchor: `dc3a368fefa15cce6705eda7e3080264db7077eea726c7d5cc010fac0ba8e518` (`sha256`, 89 commits).

Review groups:

- `753f08f3`: `1ed2676e`, `1fd5c4c0`, `61e8a626`, `f1e5ef73`, `7e69c3f1`, `17465d29`, `1c3a125c`, `58af2f2e`, `c04d423d`, `7ff9502f`, `955ab13e`, `e7562c06`, `f2a6edad`, `7ac87d3b`, `c39007f4`, `863462c2`, `38260df5`, `7702a2df`
- `92a8ac6b`: `f9297a22`, `6c47daac`, `4f0e0af1`, `622b8b05`, `5affd624`, `a30c4516`, `df330d8c`, `99b1c970`, `527d0810`, `30cb69ab`, `752965d7`, `0a4059ff`, `48b262ee`, `8d13b0e6`, `cda984ee`, `a992af9a`
- `1beed5a3`: `3e24d4b4`, `ba27375c`, `0b8188c1`, `e7102f97`, `1e052302`, `c664e8a5`, `238ca21d`, `37e14155`, `7010a09a`, `37ffbbe3`, `4f2c0362`, `a855bc07`, `3b57f256`, `5e2fa639`, `b0774e73`, `f3a99cc9`, `50dc89a8`, `e59e3683`, `7b7a782b`, `319667a8`, `40ea737d`, `ce54d5dd`, `d5250c78`, `3206f45d`, `345bcfba`
- `87a01ddf`: `5a2abffe`, `40db9e5c`, `25203ed6`
- `46406439`: `5af2fc30`, `d81726a2`, `e7f79840`, `d30348d9`
- `39c1200d`: `687533ec`, `e4d0aa06`, `4591269e`, `0da09a20`, `636d9bc6`, `d27e515d`, `a07fb3f1`, `0fec3340`, `77da41d3`
- `e32b1e84`: `50fb09d2`, `d5a31d0e`, `c79f2d07`, `c0c96151`, `8dd30cba`, `e0c5d693`, `0818de9e`

The two release-critical groups are closed by named local predicates. Other groups add unsupported architecture, repository maintenance, or optional capabilities without a current release acceptance gap.

## Capability Comparison

| Area | Upstream at the reviewed commit | This fork today |
|---|---|---|
| Product and storage | General-purpose memory with ChromaDB, sqlite_exact, optional Rust exact search, and server backends | Code-first memory with one LanceDB owner |
| MCP and distribution | 45-tool full MCP, optional three-tool PQL facade, hub/daemon/logstream surfaces, plugins and native artifacts | 29-tool typed stdio profile plus four-tool portable minimal profile; pip/pipx package |
| Retrieval | Hybrid retrieval, optional LLM reranking, configurable weights, date provenance, and multiple backend optimizations | Local deterministic vector and code hybrid rerank; no LLM reranker |
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

## Fork Stance

**Adopted safety.** The fork refuses raw fallback for recognized incomplete Codex rollouts, preserves malformed or unreadable entity registries, bounds entity-registry temporary-name collisions, and contains no callable Wikipedia research path.

**Equivalent protocol behavior.** Existing tests cover diary reads beyond the former limit, malformed JSON-RPC envelopes with preserved request IDs and session continuity, and `--palace` placement before or after a subcommand.

**Storage boundary.** LanceDB remains the only current backend. Rust exact search, ChromaDB, sqlite_exact, pgvector, Qdrant, hub, daemon, logstream, and replication contracts are outside this release.

**Deferred additions.** Ranking weights, last-modified metadata, date provenance, KG pagination, and XDG default migration require their own acceptance and migration evidence.

## Evidence Limits

- Repository review only; upstream behavior was not executed.
- No cross-project performance or quality claim is made.
- Decisions describe applicability to this fork at this release candidate.
- Only public `develop` at the pinned commit was reviewed.

## Automation Policy

Static mode validates manifest shape, pins, source links, capability mappings, decisions, local predicates, inventory count and digest, and document synchronization. Live mode adds one credential-free read of the public upstream head and fails closed on drift.

Canonical release command:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

## Drift Recovery

If live mode reports a different upstream head, review the exact new range, update both comparison files, run the static guard and focused predicates, then retry the release preflight. Do not tag against stale evidence.

Recovery command:

```bash
python scripts/upstream_comparison_guard.py --check-live --json
```
