# Upstream Comparison - Reviewed Snapshot

This is the source-pinned comparison between `rergards/mempalace-code` and public upstream `mempalace`. It records applicability decisions for this fork. Upstream was not executed or benchmarked.

## Snapshot

| Field | Value |
|---|---|
| Reviewed date | `2026-10-31` (UTC) |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `da6e21fbbebff250193812a5786180bb65cfa459` |
| Previous reviewed commit | `43122aefb8ed58e9fa4e1953e15ce70026339ec2` |
| Previous reviewed date | `2026-10-03` |
| Upstream release described by its changelog | `3.12.0` |
| Fork commit at review time | release preparation worktree |

## Source Links

- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/README.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/.claude-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/.dsh-plugin/README.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/crates/README.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/benchmarks/PRIVATE_PALACE.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/docs/rfcs/005-agent-identity-routing.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/integrations/shared/coordination-protocol.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/website/guide/lightweight-mcp.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/config.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/split_mega_files.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/update_awareness.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/hub_client.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/logstream.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/http.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/protocol.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/runtime.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/searcher/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/searcher/ranking.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/embedding.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/backends/qdrant.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/backends/rust_exact.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/cli/__init__.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/cli/parser.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/cli_write_routing.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/knowledge_graph.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_light_server.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/query_parser.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/normalize.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/entity_registry.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/diary_ingest.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/daemon.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/source_identity.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/wal.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/sync.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/schemas.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/backends/_inproc_sqlite.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_proxy.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/cli/cmd_repair.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/palace/mined.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/docs/CLOSETS.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/convo_miner.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/palace_audit.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/backends/chroma.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/_session.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/searcher/candidates.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/_guards.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/tools_write.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/cli/cmd_sync.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/tools_coord.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/cli/_hub.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/website/reference/benchmarks.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/skills/mempalace-recall/SKILL.md>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/tools_read.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/hallways.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/tunnels_tool.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/hooks_cli.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/rooms.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/cli/cmd_rooms.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/palace/writes.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/embeddinggemma2.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/llm_client.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/tool_capabilities.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/paths.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/timeutil.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/fsio.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/backends/_filters.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/stored_text.py>

- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/.github/workflows/publish.yml>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/backends/sqlite_exact.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/entity_detector.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/mcp_server/tools_kg.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/miner.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/repair.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/tests/mcp/test_write_tools.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/tests/test_embeddinggemma2.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/tests/test_retention_env.py>

- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/tests/test_embedding.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/hooks/cursor/lib/common.sh>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/hooks/antigravity/lib/common.sh>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/benchmarks/longmemeval_bench.py>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/i18n/en.json>
- <https://github.com/MemPalace/mempalace/blob/da6e21fbbebff250193812a5786180bb65cfa459/mempalace/palace/palace_lock.py>

Exact compare range: <https://github.com/MemPalace/mempalace/compare/43122aefb8ed58e9fa4e1953e15ce70026339ec2...da6e21fbbebff250193812a5786180bb65cfa459>

## Upstream Delta Since the Previous Pin

The cumulative range contains exactly 438 commits in 46 behavior groups. It retains all 428 commits and 36 decisions from the preceding 2026-10-31 review, including all 413 commits and 21 decisions from the 2026-10-30 review. That review preserved all 409 commits and 19 decisions from 2026-10-23, whose range changed 443 paths; the complete local Git range supplied that inventory because the GitHub compare API listed only its first 300 files. Each SHA is owned once below.

The preceding refresh was reviewed on 2026-10-30 UTC. The incremental range from `f41e8e75ddaadf5588d5127715fa531d79eadb45` to `84582fb055a6429261f9c779da86c0561ec80adc` contains four commits dated 2026-10-25 and changes 14 paths. Public branch-head and compare responses bind this increment to the reviewed head. Incremental compare: <https://github.com/MemPalace/mempalace/compare/f41e8e75ddaadf5588d5127715fa531d79eadb45...84582fb055a6429261f9c779da86c0561ec80adc>.

The second refresh was reviewed on 2026-10-31 UTC. The incremental range from `84582fb055a6429261f9c779da86c0561ec80adc` to `d1069b991cedc757e2c1887fd1bef041f823421a` adds 15 commits and changes 51 paths. Primary branch-head and complete compare responses bind the increment to the reviewed head. Incremental compare: <https://github.com/MemPalace/mempalace/compare/84582fb055a6429261f9c779da86c0561ec80adc...d1069b991cedc757e2c1887fd1bef041f823421a>. The release-critical publisher update is adopted through the signed v1.14.3 action pin, fixing GHSA-5xjx-3w67-w9x9. Its primary advisory is <https://github.com/pypa/gh-action-pypi-publish/security/advisories/GHSA-5xjx-3w67-w9x9>. The remaining groups record equivalent local KG lookup behavior, a deferred local Git-exclude gap, and changes to upstream-only owners.

The third refresh was reviewed on 2026-10-31 UTC. The complete incremental range from `d1069b991cedc757e2c1887fd1bef041f823421a` to `da6e21fbbebff250193812a5786180bb65cfa459` adds 10 commits and changes 26 paths (+1228/-138 lines). Primary captured compare and diff responses cover the full increment. Incremental compare: <https://github.com/MemPalace/mempalace/compare/d1069b991cedc757e2c1887fd1bef041f823421a...da6e21fbbebff250193812a5786180bb65cfa459>. The release-critical cross-HOME writer guard is adopted in the local candidate through its existing lease owner and a permanent sibling anchor, pending qualification. Upstream was not executed.

| Delta decision | Commits | Stance | Release-critical | Review group |
|---|---|---|---|---|
| `embedding-and-native-media` | 8 | `deferred` | no | `59546275` |
| `integration-history` | 175 | `irrelevant` | no | `35dc6215` |
| `retrieval-and-time` | 27 | `deferred` | no | `6256ff37` |
| `source-mining-and-replacement` | 22 | `deferred` | no | `b10d49d7` |
| `alternative-backend-storage` | 21 | `irrelevant` | no | `8062d827` |
| `mcp-protocol-and-server` | 23 | `deferred` | no | `fb315bc3` |
| `configuration-and-state-publication` | 23 | `deferred` | no | `076f7054` |
| `release-documentation-and-ci` | 33 | `irrelevant` | no | `47d5d245` |
| `optional-upstream-maintenance` | 23 | `deferred` | no | `325aae03` |
| `network-and-process-routing` | 10 | `irrelevant` | no | `1392e181` |
| `agent-hooks` | 11 | `irrelevant` | no | `ec7264aa` |
| `entity-name-preservation` | 2 | `adopted` | yes | `e704a212` |
| `conversation-fidelity` | 10 | `deferred` | no | `44e62e1f` |
| `external-model-consent` | 5 | `irrelevant` | no | `50c1f959` |
| `graph-path-and-import-policy` | 3 | `deferred` | no | `bf750e94` |
| `shared-mcp-argument-guards` | 3 | `equivalent-local` | no | `59df4934` |
| `atomic-source-replacement` | 4 | `equivalent-local` | no | `3c3b0b0d` |
| `source-decoding-policy` | 3 | `deferred` | no | `52077e9c` |
| `verbatim-spellcheck-policy` | 3 | `equivalent-local` | no | `ce04e03a` |
| `windows-http-port-exclusivity` | 2 | `irrelevant` | no | `b2781d45` |
| `hallway-sqlite-store` | 2 | `irrelevant` | no | `84582fb0` |
| `upstream-20261031-publisher-trust-store-refresh` | 1 | `adopted` | yes | `476eb444` |
| `upstream-20261031-alternative-backend-metadata-streaming` | 1 | `irrelevant` | no | `6de95b04` |
| `upstream-20261031-uncapped-stored-kg-lookups` | 1 | `equivalent-local` | no | `d15d0580` |
| `upstream-20261031-http-call-timing` | 1 | `irrelevant` | no | `911b1fe5` |
| `upstream-20261031-daemon-standard-output` | 1 | `irrelevant` | no | `07804291` |
| `upstream-20261031-chroma-searchable-coverage` | 1 | `irrelevant` | no | `647674ea` |
| `upstream-20261031-embeddinggemma2-scipy-test` | 1 | `irrelevant` | no | `f1ee8823` |
| `upstream-20261031-daemon-module-retention-regression` | 1 | `irrelevant` | no | `9f94639a` |
| `upstream-20261031-case-variant-wing-rename-regression` | 1 | `irrelevant` | no | `3c184ada` |
| `upstream-20261031-repository-local-excludes` | 1 | `deferred` | no | `466968ce` |
| `upstream-20261031-language-aware-entity-filters` | 1 | `irrelevant` | no | `65fb76e9` |
| `upstream-20261031-codex-rollout-cwd-routing` | 1 | `irrelevant` | no | `f4764f68` |
| `upstream-20261031-conversation-authored-instant` | 1 | `irrelevant` | no | `a844900f` |
| `upstream-20261031-registered-cjk-entity-boundaries` | 1 | `irrelevant` | no | `5a249612` |
| `upstream-20261031-effective-embedding-device-reporting` | 1 | `irrelevant` | no | `d1069b99` |

| `upstream-20261031-per-call-peer-writer-lease` | 1 | `equivalent-local` | no | `38063ee0` |
| `upstream-20261031-embedder-heap-release` | 1 | `irrelevant` | no | `0b3d5177` |
| `upstream-20261031-pathname2url-surrogate-test` | 1 | `irrelevant` | no | `a36e15ef` |
| `upstream-20261031-hook-shell-path-parsers` | 1 | `irrelevant` | no | `ff4961dd` |
| `upstream-20261031-hook-worktree-wing-collapse` | 1 | `irrelevant` | no | `abe196f9` |
| `upstream-20261031-longmemeval-corpus-ndcg` | 1 | `irrelevant` | no | `b0c6cdf5` |
| `upstream-20261031-english-code-entity-stopwords` | 1 | `irrelevant` | no | `34b742f3` |
| `upstream-20261031-checkpoint-request-lock` | 1 | `irrelevant` | no | `c291f6c9` |
| `upstream-20261031-http-listen-backlog` | 1 | `irrelevant` | no | `7597c4cf` |
| `upstream-20261031-cross-home-writer-exclusion` | 1 | `adopted` | yes | `da6e21fb` |

Inventory anchor: `2afedde5c8817b864e689247756b56cef66de176c749bf11028be40071134ad1` (`sha256`, 438 commits).

Review groups:

- `59546275`: `70bba021`, `55ed1df4`, `1f0803a3`, `50907320`, `ed0080c8`, `1df2027e`, `857fbec4`
- `35dc6215`: `0b36d963`, `775cb669`, `9404981a`, `a0452516`, `7a69f2e8`, `74125442`, `602d796c`, `d9bf01e2`, `196f91e0`, `9b0cebf6`, `2776769e`, `7d439152`, `34b18a29`, `89067bfb`, `71b6c04c`, `aca9e13a`, `e3f1a596`, `535a97d3`, `3851d5aa`, `77520405`, `953dd327`, `f43e7bdb`, `2f4fc20e`, `f50be7bb`, `0bbd89e2`, `a618e6b6`, `a2c3df8f`, `a963b881`, `6fceaafe`, `3ce7486d`, `e8419fce`, `0d8b27de`, `f90760aa`, `7e0b26c1`, `aae7cbec`, `ae9a3a13`, `8155a90d`, `40c41a0c`, `6765742a`, `f9a09dab`, `9b0c7551`, `abb64424`, `adc09a23`, `0a9848a1`, `88eb6fd1`, `cab1d653`, `a75d5692`, `6710f273`, `37292840`, `d85066ba`, `261ae4d0`, `7fba7b9b`, `119ae8d5`, `66892d4c`, `555f10c0`, `b2225b90`, `103f0bea`, `8dfad107`, `c369cd61`, `22a5e2a7`, `b310d8e2`, `03cf4614`, `b43c8283`, `2e26458d`, `f45bef02`, `d50c8003`, `1ed85405`, `fe665495`, `ca7b370f`, `90c96f34`, `d3cf274b`, `272da43f`, `5cf2541a`, `40ed88cd`, `21c91645`, `2ddf01fb`, `0c4286ad`, `75b58c10`, `8dfd9f90`, `11117244`, `4703014f`, `bde4921b`, `f7cacaaa`, `7169b53c`, `b4efd9a3`, `75faf6b3`, `2d51b394`, `0e045b98`, `3b280ef0`, `b1e074ba`, `d9a370a7`, `ebde50d7`, `20996c01`, `da4fa3f8`, `7634934e`, `a673f716`, `a467a2d3`, `97b316ce`, `7ca764a1`, `fc863986`, `a44c6f2b`, `91f346c6`, `9a9d6e76`, `368326a2`, `7318fe13`, `995ab04d`, `700b95dc`, `9507de1d`, `08dda841`, `dd40b58e`, `cc93971d`, `e3c127a7`, `1a36a52a`, `45a7bd79`, `d53c84b7`, `bf26afe2`, `3da74e0f`, `4c14b162`, `17c0a1bd`, `49098f2b`, `4d5ea224`, `f31285a7`, `b2c44895`, `7f09b037`, `bd4fb7fd`, `0f531e0c`, `8784f817`, `2c103667`, `0c435e49`, `308152e1`, `9b7805c5`, `e8e9e720`, `1a4282b1`, `4b417743`, `11071994`, `d7fffb56`, `724b886b`, `db04a695`, `af791502`, `d523a3f5`, `c04ab950`, `36ee91e5`, `791943af`, `60a4f45a`, `5a97a666`, `e46130bc`, `391e8f91`, `9f91851c`, `166e55a9`, `a166d93a`, `bcb2edb3`, `417bb982`, `b81abe6f`, `ec98e19e`, `bc7557e7`, `36dbfae9`, `c21d34b9`, `a8a17238`, `a4ba4e43`, `ee728957`, `74df9fab`, `8970bfe6`, `b5a13ce6`, `3fe52ef1`, `3ec047e8`, `03a0918d`, `ee37474d`, `3b6061fd`, `38f7c78f`, `49baf516`, `2a96e4e0`, `4e7eab04`, `f884dd4c`, `f41e8e75`
- `6256ff37`: `0a41b363`, `3de80464`, `6e0acfd1`, `8024b45c`, `432fa4fa`, `e1c7b488`, `18e6a3fb`, `3d2523e2`, `59388b8e`, `e07e13fd`, `d2c0d389`, `7bfdeea2`, `f92a4e24`, `f888f321`, `b5319d1b`, `947474c8`, `0740543d`, `96169415`, `f34bf1d5`, `d094a5a4`, `a6b97bd5`, `072a332a`, `25f6f373`, `8693e7ce`, `85498c06`, `d2476723`
- `b10d49d7`: `3762dc16`, `d439d1e6`, `22e3627d`, `b2471587`, `c3fec40e`, `9e013e9e`, `155b4475`, `662adc0c`, `03557f56`, `82338ca6`, `e97b81e2`, `1747e5ca`, `1a2b44a3`, `686454f6`, `a778964f`, `dcfc3e14`, `579abf8a`, `1627bfeb`, `2098beeb`, `e622f564`, `779992a9`
- `8062d827`: `fd0133a0`, `f0a23f02`, `7da9bd19`, `45074ca6`, `722e8fac`, `119505da`, `4d6f151c`, `edf80ffc`, `5483c5a8`, `ea996233`, `74092c94`, `d7e67e4a`, `e03a200f`, `dcfdb9d9`, `cfa57ea5`, `d65f64ce`, `1be5ceea`, `616e7c38`, `1febb8d2`, `1f768ccf`
- `fb315bc3`: `d4038612`, `f3dfae89`, `55fe447b`, `7bad1ecd`, `45bff470`, `d42074c2`, `cca1f4ab`, `eccbb6a5`, `b29529c2`, `1683156f`, `f5915003`, `5d531fe7`, `3428b87f`, `d6e1a682`, `2e70bdc8`, `6d275357`, `4dd9b35c`, `7558d80c`, `80d3eb6f`, `43bffd71`, `2a11534e`, `484d8091`
- `076f7054`: `1aa276a6`, `4f15d56b`, `72531d86`, `1ac3a4c8`, `cd92dd8a`, `0647c99e`, `70c22b49`, `23a56ae6`, `4ca0a6a4`, `9ef21c5d`, `ef94cd14`, `931c80da`, `28f12c54`, `83da7333`, `48838f9f`, `4af367cc`, `b708fe47`, `a1e7a4fe`, `4a932d21`, `293b81c0`, `37d04d37`, `28ed775e`
- `47d5d245`: `643134bc`, `927ad73c`, `1a60c408`, `71394308`, `5a22d238`, `f9b19f97`, `aa319ef1`, `e7ff3fa0`, `9da2aa32`, `9199b73f`, `719d678e`, `7e645f0f`, `c63ba1c5`, `654a083d`, `ee8313db`, `ef4a22df`, `f90cc8b2`, `37b07e8b`, `534dd99b`, `f74451af`, `0f0a50a8`, `950581fe`, `1cd72d26`, `fc58e301`, `b5b40229`, `6a7b0062`, `951b2314`, `e35a584e`, `17d352ae`, `b7d76122`, `8f48f2e1`, `98ac69ac`
- `325aae03`: `20d396c8`, `a8881614`, `d5f00dc9`, `569beda6`, `9bbcebcc`, `6981b124`, `21e5fdf4`, `0c18e0e5`, `d5a01317`, `f83eb0e1`, `4a80e318`, `1156ab03`, `bb1f2a1f`, `fe8900df`, `eeb92059`, `9368be02`, `fa8efbad`, `9f77b877`, `759e876b`, `8dd706ab`, `93aac28c`, `0d706124`
- `1392e181`: `6bc21b3e`, `5528b8ac`, `501e8d71`, `3d91f06a`, `909549e1`, `490c446f`, `0741fd5a`, `ee41fd81`, `07f928eb`
- `ec7264aa`: `6e2a0fda`, `b4bf16ba`, `47b25712`, `45349c1e`, `8b0070cd`, `2cd12648`, `6b828093`, `c3376ea6`, `4d8707ef`, `4d6cb17e`
- `e704a212`: `0c70e213`
- `44e62e1f`: `ad4b40f6`, `b9460dc4`, `071d1807`, `a66d5cd8`, `1798e405`, `bb85f72e`, `30046f94`, `1a1733d2`, `79022e32`
- `50c1f959`: `64b8a2b2`, `a92e4da5`, `a84a9c72`, `3137000c`
- `bf750e94`: `df06dc86`, `e55c7e44`
- `59df4934`: `d0405ddd`, `9958c87b`
- `3c3b0b0d`: `4da9ee7d`, `8fc9ab2e`, `383d0e88`
- `52077e9c`: `43d42bbd`, `ab5021f0`
- `ce04e03a`: `a8229654`, `8ed0d9c4`
- `b2781d45`: `9a377de8`
- `84582fb0`: `5ffa138a`
- `476eb444`
- `6de95b04`
- `d15d0580`
- `911b1fe5`
- `07804291`
- `647674ea`
- `f1ee8823`
- `9f94639a`
- `3c184ada`
- `466968ce`
- `65fb76e9`
- `f4764f68`
- `a844900f`
- `5a249612`
- `d1069b99`
- `38063ee0`
- `0b3d5177`
- `a36e15ef`
- `ff4961dd`
- `abe196f9`
- `b0c6cdf5`
- `34b742f3`
- `c291f6c9`
- `7597c4cf`
- `da6e21fb`

### Applicability

- `embedding-and-native-media`: DirectML serialization, EmbeddingGemma2/media and model-wrapper changes belong to upstream embedding owners. The fork keeps canonical CPU MiniLM/FastEmbed provenance and model/dimension checks; no model, media interface, accelerator or benchmark claim changes. Any model change retains the independent code/text gates.
- `integration-history`: Merge history integrates the behavior groups below. Remerge resolutions in palace writes, normalization, search, backend helpers and filesystem helpers were inspected with Git; they are assessed at the final frozen source rather than treated as independent features. No merge or history contract is imported.
- `retrieval-and-time`: The fork has normalized LanceDB vectors and its own deterministic code ranking. Upstream multi-backend cosine scales, closet boosts, BM25 union/ties and timezone/date-window contracts are not the same interface. No ranking migration, benchmark equivalence or new time-filter capability is claimed.
- `source-mining-and-replacement`: Upstream source formats, registry rows, quick-check shortcuts, general-mode rewrites and media/daemon forwarding differ from fork scanner and generated-copy policy. Exact source replacement is assessed separately; no broad parser or ingest-version migration is imported.
- `alternative-backend-storage`: Chroma/raw-SQLite, sqlite_exact, Rust, remote backend filters/vector validation and backend-specific stored-text escaping have no corresponding current storage backend in this LanceDB-only package. The fork does not gain those dependencies or backend contracts.
- `mcp-protocol-and-server`: Upstream capability refactoring, HTTP locks/tokens, light PQL facade, revision logs and tunnel bookkeeping are separate owners and interfaces. The fork retains its typed stdio registry and no update_drawer/revision-log or HTTP service. Shared argument-validation safety is assessed in its own group; no blanket protocol equivalence is claimed.
- `configuration-and-state-publication`: The fork has its own configuration, atomic publication and lock owners. Upstream shared fsio, Windows retry, alternate YAML naming, environment parser and path consolidation are not copied wholesale. Existing invalid-registry and backup/restore refusal evidence remains scoped to its actual owners, without claiming equivalent behavior for every upstream state file.
- `release-documentation-and-ci`: The projects have independent release versions, Python ranges, lint rules, Docker/native artifacts and CI. Upstream3.12.0 requires Python3.10; this fork retains its reviewed3.11-3.14 matrix. Upstream export/removed onboarding information updates the comparison only and does not change fork commands.
- `optional-upstream-maintenance`: Upstream closets, AAAK collections, wing aliases/splitting, format miners, persistent tunnels and short-drawer dedup retirement are not imported. Fork cleanup keeps its manual/unique data protections and receipt-bound migration. New upstream maintenance semantics do not authorize deletion or reorganization here.
- `network-and-process-routing`: The fork exposes stdio MCP and local watcher ownership, without upstream hub, daemon forwarding, HTTP proxy or mesh. Upstream token/proxy/browser and process-routing changes have no such reachable surface in this release.
- `agent-hooks`: Upstream hook interpreter routing, asynchronous checkpointing and Hermes diary ownership are outside the fork default code-question workflow. This review neither enables conversation persistence nor changes global client instructions or hook installation.
- `entity-name-preservation`: The fork reproduced silent entity-name collisions at its legacy normalized IDs. Its existing KG owner now refuses distinct names before writes, import, invalidation and name-scoped reads, with transaction and snapshot guards. Existing IDs and schema stay unchanged. Upstream punctuation-preserving new IDs and property-merge semantics are not imported; the pre-existing add_entity property-replacement contract remains separate.
- `conversation-fidelity`: The fork uses per-source content hashes, explicit decoding refusal and its own transcript rendering/chunking contracts. Upstream branch selection, transform stamps, multipart rendering and cross-file conversation migration are not asserted as identical. No conversation corpus was inspected or re-mined for this review.
- `external-model-consent`: The fork has no upstream LLM client, closet generator or OpenAI-compatible embedding endpoint. Upstream now defaults its LLM client to local Ollama and requires consent for external endpoints; API credentials are not intrinsic to local reranking. No external-model feature is added.
- `graph-path-and-import-policy`: The fork already resolves its palace-owned SQLite KG through open_palace_kg and a guarded legacy-adoption owner. Upstream graph-selection and import-conflict policy are different durable contracts; automatic graph switching, merging and a new import command are not added. The confirmed name collision in the local adoption path is fixed in the separate preservation group.
- `shared-mcp-argument-guards`: The fork already validates required strings, booleans, enums, ranges, text bounds, unknown arguments and sanitized handler failures in its dispatcher. Its existing real stdio regressions exercise refusal and continued service. No upstream coercion or network-token contract is copied.
- `atomic-source-replacement`: The fork add_drawers_batch delegates changed-source replacement to one LanceDB composite merge. Failure leaves old source rows and manual rows outside the replacement scope. Existing source-failure and storage merge regressions are the evidence; upstream closet/AAAK cleanup contracts are absent.
- `source-decoding-policy`: Upstream now carries stray bytes and records transforms through its own wire/storage paths. The fork refuses undecodable sources instead of filing replacement characters. A reversible stored-text representation would change its durable contract and requires separate acceptance; no such migration is introduced.
- `verbatim-spellcheck-policy`: The fork already passes spellcheck=False for supported conversation mining and preserves code identifiers. Upstream opt-in spell correction and transform stamps are not enabled; the existing local predicates establish the refusal to silently spell-correct.

The adopted preservation guard refuses ambiguity; it does not assign new upstream-style IDs or repair facts that an older version already merged. Such data stays preserved for operator investigation. The complete inventory is in the manifest. A stance describes only the stated behavior, not every implementation detail in a merge commit.

- `windows-http-port-exclusivity`: `irrelevant`. Upstream reserves its Windows HTTP hub port with SO_EXCLUSIVEADDRUSE to prevent another server from receiving hub connections and Authorization headers. The fork exposes stdio MCP through its existing launcher and dispatcher and has no HTTP hub or listening socket on this path. No HTTP transport or socket state owner is introduced.
- `hallway-sqlite-store`: `irrelevant`. Upstream imports persistent hallway JSON into SQLite on first write, retains the imported source, pages reads and updates only the mined wing. Mixed upstream versions can still write retired JSON. This fork has no persistent hallway sidecar or hallway migration route; its graph owner derives room relationships from LanceDB metadata. Persistent hallway storage and its lifecycle remain outside this release.

- `upstream-20261031-per-call-peer-writer-lease`: `equivalent-local`. The fork already takes and releases its palace write lease around each writing tool call through mempalace_code/mcp/runtime.py. Read calls do not retain a process-lifetime writer lease. Source inspection establishes per-call ownership. The named regression verifies release after a lease-body error; it does not exercise MCP transport.
- `upstream-20261031-embedder-heap-release`: `irrelevant`. Upstream releases its embedder arena and allocator heap after mining. The fork uses a different FastEmbed/ONNX embedding owner and cache lifecycle. This source change does not establish a corresponding fork regression or a measured RAM improvement; no memory-release or benchmark claim is made.
- `upstream-20261031-pathname2url-surrogate-test`: `irrelevant`. Upstream corrects a test-only Python-version boundary for pathname2url surrogate handling. The fork does not use this upstream test or its embedding path conversion owner; no runtime change is adopted.
- `upstream-20261031-hook-shell-path-parsers`: `irrelevant`. Upstream preserves filesystem path characters in Cursor and Antigravity shell stdin parsers. Those hook parsers are absent from the fork. Existing fork hook ownership remains unchanged.
- `upstream-20261031-hook-worktree-wing-collapse`: `irrelevant`. Upstream collapses its project-local .worktrees directories into a project wing in its hook CLI. The fork uses a different hook/mining owner and does not import this wing identity rule.
- `upstream-20261031-longmemeval-corpus-ndcg`: `irrelevant`. Upstream normalizes LongMemEval NDCG against the full corpus. The fork legacy LongMemEval harness requires an isolated ChromaDB environment and has no qualified text baseline. The default model is unchanged; this review neither qualifies that harness nor relaxes the independent code and text gates.
- `upstream-20261031-english-code-entity-stopwords`: `irrelevant`. Upstream adds generic code terms to its English entity stopwords. The fork uses different parser/symbol and knowledge-graph extraction owners and does not import the upstream language stopword pipeline.
- `upstream-20261031-checkpoint-request-lock`: `irrelevant`. Upstream releases its global REQUEST_LOCK around checkpoint embedding phases. The fork has no corresponding checkpoint REQUEST_LOCK owner. This absence establishes inapplicability, without claiming equivalent checkpoint lock behavior.
- `upstream-20261031-http-listen-backlog`: `irrelevant`. Upstream increases its HTTP MCP server listen backlog. The fork exposes credential-free stdio MCP and has no corresponding HTTP listener or socket backlog.
- `upstream-20261031-cross-home-writer-exclusion`: `adopted`. The local candidate adopts cross-HOME writer exclusion through the existing palace_write_lease owner with a permanent canonical-palace sibling anchor, while retaining the legacy HOME lease. The parent must exist and be usable; unsafe or unavailable anchors fail closed, without a HOME-only fallback. Existing safe regular single-link same-UID anchors are opened without content writes, truncation or removal, including read-only and nonempty anchors. Older different-HOME clients need an upgrade to participate. This is a local release candidate pending qualification, not a released behavior claim.

## Capability Comparison

| Area | Upstream at the reviewed commit | This fork today |
|---|---|---|
| Product and storage | General-purpose memory with ChromaDB, sqlite_exact, optional Rust exact search, and server backends | Code-first memory with one LanceDB owner |
| MCP and distribution | 47-tool full MCP registry, advertised consistently by its README and both plugin manifests, optional three-tool PQL facade, hub/daemon/logstream surfaces, plugins and native artifacts | 29-tool typed stdio profile plus four-tool portable minimal profile; pip/pipx package |
| Retrieval | Hybrid retrieval, optional local or explicitly accepted external LLM reranking, configurable weights, date provenance, and multiple backend optimizations | Local deterministic vector and code hybrid rerank; no LLM reranker |
| Palace upkeep | `audit` scoring plus guided repair: LLM-proposed rooms, wing split, tunnel propose/prune, KG predicate normalization | `health`, `repair`, `cleanup`, and receipt-bound wing migration; no audit score or LLM-assisted reorganization |
| Coordination | Hub routing, daemon write policy, logstream, shared-brain rules and replication foundations | Local watcher/miner ownership guards; no hub, logstream, or replication |
| Privacy | Entity-registry Wikipedia lookup removed at the reviewed commit; configured remote backends remain optional | No unconfigured entity-research network path; legacy wiki cache remains readable |

## Capability Identifiers

Upstream, advertised at the reviewed commit:

- `embeddinggemma-init-recommendation`
- `hybrid-retrieval`
- `optional-llm-reranking`
- `backend-chromadb`
- `backend-sqlite-exact`
- `backend-milvus`
- `backend-qdrant`
- `backend-pgvector`
- `chroma-sqlite-metadata-read-paths`
- `sqlite-exact-indexed-structured-fields`
- `mcp-tools-47-readme`
- `claude-plugin-tools-47`
- `codex-plugin-tools-47`
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
- `opt-in-embeddinggemma2-native-media`
- `external-llm-explicit-consent`
- `mcp-schema-argument-validation`
- `kg-preserved-entity-punctuation`

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

- `embeddinggemma-init-recommendation`: `README.md`, `CHANGELOG.md`
- `hybrid-retrieval`: `README.md`
- `optional-llm-reranking`: `README.md`
- `backend-chromadb`: `README.md`
- `backend-sqlite-exact`: `README.md`
- `backend-milvus`: `README.md`
- `backend-qdrant`: `README.md`
- `backend-pgvector`: `README.md`
- `chroma-sqlite-metadata-read-paths`: `CHANGELOG.md`
- `sqlite-exact-indexed-structured-fields`: `CHANGELOG.md`
- `mcp-tools-47-readme`: `README.md`
- `claude-plugin-tools-47`: `.claude-plugin/plugin.json`
- `codex-plugin-tools-47`: `.codex-plugin/plugin.json`
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
- `opt-in-embeddinggemma2-native-media`: `mempalace/embeddinggemma2.py`, `CHANGELOG.md`
- `external-llm-explicit-consent`: `mempalace/llm_client.py`, `CHANGELOG.md`
- `mcp-schema-argument-validation`: `mempalace/mcp_server/_guards.py`, `mempalace/mcp_server/protocol.py`
- `kg-preserved-entity-punctuation`: `mempalace/knowledge_graph.py`, `CHANGELOG.md`

## Fork Stance

**Previously adopted safety.** The fork refuses raw fallback for recognized incomplete Codex rollouts, preserves malformed or unreadable entity registries, bounds entity-registry temporary-name collisions, and contains no callable Wikipedia research path. Its stdio loop answers a line that `json.loads` rejects with `ValueError` or `RecursionError` with `-32700` and keeps serving.

**Equivalent protocol behavior.** Existing tests cover diary reads beyond the former limit, malformed JSON-RPC envelopes with preserved request IDs and session continuity, and `--palace` placement before or after a subcommand. MCP imports ignore host-process arguments; executable flag parsing is owned by `dispatch.main(argv)`.

**Storage boundary.** LanceDB remains the only current backend. Rust exact search, ChromaDB, sqlite_exact, pgvector, Qdrant, hub, daemon, logstream, upstream distributed sync, JSON write-audit WAL, closets, persistent hallway and tunnel files, and replication contracts are outside this release.

**Equivalent conversation chunking.** `mempalace_code/convo_miner.py` keeps every non-blank transcript line with its line breaks: text before a turn joins that turn, long exchanges split at paragraph or line boundaries, and short units merge into a neighbour. Exchange rows are stamped `convo_turn_v3` with a source hash, so the next convos mine rebuilds rows of earlier strategies once.

**Equivalent repair lease.** `mempalace_code/cli_commands/maintenance.py` runs the full `repair` rebuild, `repair --rollback`, and `cleanup` under the installation's exclusive operation lease. Every palace writer (mine, convos mine, import, backup, and MCP writes) holds the shared side of that lease through `operation_lock.palace_write_lease`, so no drawer can be written between the rebuild's extraction and its swap.

**Deferred additions.** Ranking weights, last-modified metadata, date provenance, KG pagination, XDG default migration, and bulk drawer MCP tools require their own acceptance and migration evidence.

**Entity-name preservation.** Distinct names that collide at an existing normalized KG ID are refused before mutation. The guard covers direct entity/triple writes, synchronization, import, legacy adoption, invalidation and name-scoped reads. Case differences and surrounding whitespace still resolve together. Existing IDs and schema remain unchanged; queries use one snapshot and writers serialize their check and mutation.

**Model and plugin changes.** Upstream now selects models through `init --embedding-model`; its old onboarding module is removed. EmbeddingGemma2 and native media retrieval are optional and experimental. Its local Ollama reranker needs a local model/service, while external LLM endpoints require explicit acceptance. The fork retains its current model policy, stdio profiles and rejection of LLM reranking.

## Evidence Limits

- Upstream source/history review only; no upstream build, benchmark or interoperability run.
- The inventory covers all commits and changed paths; behavioral review focuses on applicability to fork owners and their acceptance. It is not an exhaustive proof of every upstream implementation.
- New KG regressions reproduce the old misattribution and verify atomic refusal, read snapshots, legacy adoption and concurrent writers. Independent engineering review is separate from release qualification.
- Existing source predicates and exact-wheel evidence retain their own dates and identities. A runtime change requires a rebuilt wheel and fresh affected installed acceptance before release.
- No cross-project performance or quality claim is made. Deferred and absent-owner features remain outside this release.

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
