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
| Reviewed date | `2026-08-24` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0` |
| Previous reviewed commit | `3e56979fb456c7478a4b57414027873bd78f2d37` |
| Previous reviewed date | `2026-08-24` |
| Upstream release described by its changelog | `3.8.0` |
| Upstream paths tracked for drift | `README.md`, `CHANGELOG.md`, `pyproject.toml`, `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `.mcp.json`, `mempalace/split_mega_files.py`, RFCs 003–005 |
| Fork commit at review time | this repository, `main` |

All upstream statements below are limited to the pinned public sources. Upstream
code was read only where the advertised source named a surface; it was not run,
benchmarked, or independently compatibility-tested.

## Source Links

Pinned primary upstream sources, all at the reviewed commit:

- <https://github.com/MemPalace/mempalace/tree/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/README.md>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/pyproject.toml>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/.codex-plugin/plugin.json>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/.agents/plugins/marketplace.json>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/.mcp.json>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/mempalace/split_mega_files.py>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0/docs/rfcs/005-agent-identity-routing.md>

The full range between the previous pin and this one is published as a single
compare link:

- <https://github.com/MemPalace/mempalace/compare/3e56979fb456c7478a4b57414027873bd78f2d37...dfba59b0f3b1c5b57a3d606317b2fd37a4fef6f0>

## Upstream Delta Since the Previous Pin

The compare link above carries the whole diff. Every changed item below is
recorded in the manifest as a delta decision with one stance from a closed set:
`adopted`, `equivalent-local`, `migration-only`, `deferred`, or `irrelevant`.
The stance says what this fork did about the change; it makes no claim about
upstream's own choice.

Release-critical rows must cite a tracked public upstream source. Rows whose
only public evidence is the commit range itself cite `compare`.

| Delta decision | Upstream change, as its sources describe it | Stance | Release-critical |
|---|---|---|---|
| `sync-deletion-corroboration` | `sync --apply` removes a missing-source drawer only when another known regular source file remains reachable in the same directory; unresolved paths are reported and kept | `irrelevant` | no |
| `sync-fix-changelog-placement` | The deletion-corroboration fix moves from Unreleased into the upstream 3.8.0 bug-fix section | `irrelevant` | no |
| `shared-brain-logstream-watch-guidance` | The shared-brain guide adds watcher wake filters, separate watcher and inbox cursors, batch replay, NDJSON envelopes, and event-id resume guidance | `deferred` | no |
| `plugin-manifest-tool-count-correction` | Claude, Codex, and Cursor plugin descriptions correct their advertised MCP tool count from 36 to 44 | `irrelevant` | no |
| `upstream-release-entrypoint-instructions` | Release checks now expect upstream's `mcp_proxy` entry point and root `.mcp.json` ownership instead of a plugin-local Codex MCP file | `irrelevant` | no |

**`sync-deletion-corroboration` — irrelevant.** The fork has no `sync_palace`,
`sync --apply`, `removable_ids`, `unresolved_by_source`, or `_classify_drawer`
owner under `mempalace_code/`, `tests/`, or `scripts/`. Its explicit
drawer/wing deletion tools and Lance stale-fragment cleanup act on
operator-selected targets; they do not infer deletion from source-file
reachability. No speculative sync or prune implementation is planned.

**`sync-fix-changelog-placement` — irrelevant.** This is an upstream changelog
correction for the same upstream-only sync lifecycle. It changes no fork
runtime, release note, or capability claim.

**`shared-brain-logstream-watch-guidance` — deferred.** The fork has no
logstream, watcher cursor, inbox cursor, replication, or agent wake-up runtime
owner. The upstream guidance therefore remains outside the fork's current
local-first scope; no compatibility or monitoring claim is added.

**`plugin-manifest-tool-count-correction` — irrelevant.** The comparison records
the upstream plugin wording as 44 tools. The fork has different plugin and
registration contracts: direct stdio exposes 29 tools and the portable Agent
Plugin defaults to four, so the upstream description-only correction does not
map to a fork implementation.

**`upstream-release-entrypoint-instructions` — irrelevant.** Upstream's
`mempalace.mcp_proxy:main` and root `.mcp.json` layout do not match this fork's
release contract. The fork retains `mempalace-code-mcp =
mempalace_code.mcp_launcher:main` in `pyproject.toml` and its packaged minimal
profile in `mempalace_code/agent_plugin/mcp.json`; no fork release instruction
changes in this review.

## Capability Comparison

| Area | Upstream, as advertised at the reviewed commit | This fork today |
|---|---|---|
| Product focus | General-purpose AI memory | Code-first memory: repository mining, `code_search`, symbol/type/project-graph tools |
| Storage and retrieval | ChromaDB default; `sqlite_exact`, Milvus, Qdrant, and pgvector are offered; hybrid retrieval and optional LLM reranking are described; 3.8.0 documents indexed/paged metadata paths for Chroma and `sqlite_exact` | LanceDB-only runtime; one-way ChromaDB-to-LanceDB migration bridge; local deterministic `code_search(rerank="hybrid")`; no LLM reranker or server-vector backends |
| Embeddings | New onboarding offers multilingual `embeddinggemma-300m`; opt-in `openai-compat` targets an OpenAI-compatible `/v1/embeddings` endpoint | `all-MiniLM-L6-v2`; no supported multilingual configuration or migration path, and no remote embedding-provider integration |
| Search filtering | `mempalace_search` and CLI search advertise `since` / `before` date windows | No matching documented date-window search surface |
| Agent integration | Changelog 3.7.0 advertises a core Hermes `MemoryProvider` and `mine --source <adapter>` source-adapter resolution | No Hermes provider or source-adapter ingestion surface |
| MCP count and plugin wording | README and the Claude, Codex, and Cursor plugin descriptions say 44 MCP tools | Direct stdio MCP registration defaults to the full 29-tool profile |
| Plugin metadata | Codex manifest identifies `mempalace` version 3.8.0, points at `.mcp.json`, and describes a Codex-oriented interface; marketplace metadata advertises a local plugin source | Standards-conformant Agent Plugins 1.0 portable package with `plugin.json`, `mcp.json`, vendored schemas, and a skill |
| Portable default | No Agent Plugins 1.0 package was reviewed in the pinned upstream sources | The portable Agent Plugins package defaults to exactly four tools: status, search, duplicate check, and add drawer |
| Coordination and replication | 3.8.0 adds a stateful background logstream watcher and monitoring protocol on top of logstream events, artifact handoffs, and the RFC 004 multi-master sync foundation | No logstream, palace replication, mesh, or live-hub transport |
| Distribution | Python package and advertised multi-arch Docker image | Python package and pipx installation; no published Docker image |
| Writer ownership | Changelog describes shared write routing and process-lifetime single-writer recovery; 3.7.1 adds SIGTERM/SIGHUP lease release | Local watcher/miner/maintenance ownership guards |
| Non-regular-file ingest | Changelog describes `O_NONBLOCK` opens, discovery-time `SKIP` lines, and per-command type gates | Ingest reads and generated split outputs are descriptor-validated; discovery skips rejected sources with a bounded diagnostic |

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
- `chroma-sqlite-metadata-read-paths`
- `sqlite-exact-indexed-structured-fields`
- `mcp-tools-44`
- `plugin-manifests-tools-44`
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

This fork, current:

- `code-first-mining`
- `backend-lancedb-default`
- `backend-chromadb-migration-bridge-only`
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

Each upstream identifier names the tracked upstream files it was read from, so a
reader can check the claim against the pinned links above rather than trusting
this summary. The manifest carries the same mapping and the guard rejects any
advertised capability that names no tracked source.

| Upstream identifier | Read from |
|---|---|
| `embeddinggemma-default-for-new-onboarding` | `README.md`, `CHANGELOG.md` |
| `hybrid-retrieval` | `README.md` |
| `optional-llm-reranking` | `README.md` |
| `backend-chromadb` | `README.md` |
| `backend-sqlite-exact` | `README.md` |
| `backend-milvus` | `README.md` |
| `backend-qdrant` | `README.md` |
| `backend-pgvector` | `README.md` |
| `chroma-sqlite-metadata-read-paths` | `CHANGELOG.md` |
| `sqlite-exact-indexed-structured-fields` | `CHANGELOG.md` |
| `mcp-tools-44` | `README.md` |
| `plugin-manifests-tools-44` | `.codex-plugin/plugin.json` |
| `codex-plugin-metadata` | `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `.mcp.json` |
| `openai-compatible-embeddings` | `README.md` |
| `search-date-window` | `CHANGELOG.md` |
| `hermes-memory-provider-core` | `CHANGELOG.md` |
| `source-adapters-mine` | `CHANGELOG.md` |
| `agent-logstream-artifact-handoffs` | `CHANGELOG.md`, `docs/rfcs/003-agent-logstream-coordination.md` |
| `logstream-multi-master-sync-foundation` | `CHANGELOG.md`, `docs/rfcs/004-replicated-palace.md` |
| `live-palace-hub-write-routing` | `CHANGELOG.md`, `docs/rfcs/003-agent-logstream-coordination.md` |
| `read-replica-mesh-preview` | `docs/rfcs/004-replicated-palace.md` |
| `multiarch-docker-image` | `README.md` |
| `process-lifetime-single-writer` | `CHANGELOG.md` |
| `agent-logstream-watch` | `CHANGELOG.md` |

`pyproject.toml`, `mempalace/split_mega_files.py`, and
`docs/rfcs/005-agent-identity-routing.md` are tracked for
drift without backing a capability identifier: the first carries the advertised
package version and dependency declarations, the second provides immutable
evidence for the release-critical name-detection delta, and the third is watched
because an identity routing surface would change the coordination row if it shipped.

## Fork Stance

**Embeddings.** The supported default remains `all-MiniLM-L6-v2`. The fork has
no supported multilingual model configuration or migration flow. A model change
requires the text and code retrieval evidence and migration support defined in
`AGENTS.md`.

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

**Non-regular ingest and split paths.** Each source accepted by the ingest
boundary and each generated split output is opened through a descriptor and
revalidated with `fstat`. Split outputs use `O_NOFOLLOW` and `O_NONBLOCK` where
available. A platform missing either flag creates only new outputs with `O_EXCL`
and refuses to replace an existing output. A refused entry stops the operation
that named it, leaves the input in place, and makes the CLI exit nonzero.

## Evidence Limits

- **Repository review only.** Claims come from the pinned README, changelog,
  package metadata, plugin/MCP files, and RFCs. No upstream behavior was run.
- **Nothing was measured.** This document contains no benchmark, quality,
  performance, adoption, or compatibility measurement.
- **Delta stances are about this fork.** Each applicable adaptation decision
  records what this fork did and cites a local test or module as evidence.
  Repository-only `irrelevant` rows require no local predicate. None of the rows
  evaluates upstream's own decision or its correctness.
- **Plugin counts are source-local wording.** The README and reviewed plugin
  descriptions now agree on 44 tools. The fork's 29-tool direct profile and
  four-tool portable default remain independently tested fork claims.
- **One branch, one commit.** Only `develop` at the pinned commit was reviewed.
  Upstream default-branch, tag, release, and future state can differ.
- **Historical criticism is separate.**
  [`UPSTREAM_HARDENING.md`](UPSTREAM_HARDENING.md) describes April 2026
  material and is not evidence about upstream at this reviewed commit.

## Automation Policy

`scripts/upstream_comparison_guard.py` has two modes.

**Static mode (default).** It validates manifest shape, pin format, review age,
README/document pointers, capability identifiers, published source links, delta
decision stances, and the local files those stances name, using only the
checkout. It is deterministic and network-free. CI lint and the default
`scripts/release_preflight.py` use this mode.

**Live mode (`--check-live`, explicit).** Live drift detection runs only at
release time. It performs one read-only GitHub API request for the pinned branch
head and fails closed on drift, fetch failure, or an unusable response. It never
rewrites source or GitHub state. The canonical pre-tag owner is
`scripts/release_preflight.py`; invoke it with:

```bash
python scripts/release_preflight.py --tag vX.Y.Z --require-clean --check-live-upstream
```

That opt-in preflight path delegates to this guard's `--check-live` mode before
an immutable tag is made. The tag-only publish owner,
`.github/workflows/publish.yml`, retains its direct live guard as defense in
depth after a tag exists.

## Drift Recovery

When the pre-tag release preflight or tag-only publish workflow reports
`upstream-drift`, the failure names the current upstream head and the compare
range from the pin. Refresh the review rather than moving the pin alone:

1. Read the compare range the failure prints, and classify every changed public
   surface into one delta decision with a stance from the closed set above.
2. Update `docs/quality/upstream-comparison.json` together: `commit`,
   `previous_commit`, `reviewed_date`, `previous_reviewed_date`, `compare_ref`,
   `source_refs`, `capability_sources`, and `delta_decisions`.
3. Update this document to match, including the delta table and the pinned
   source links. The guard fails if either side moves without the other.
4. Confirm with the recovery command:

```bash
python scripts/upstream_comparison_guard.py --check-live --json
```

A stance of `adopted` or `equivalent-local` must name a local test or module
that exists in the checkout; the guard rejects a claim whose named evidence is
missing. A release-critical row must cite a tracked upstream file, not the
compare range alone.
