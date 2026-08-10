# Upstream Comparison — Reviewed Snapshot

This is the canonical comparison between `rergards/mempalace-code` (this fork) and the
upstream `mempalace` project. It records what upstream advertised at a specific commit,
what this fork does today, and which upstream directions the fork has deliberately not
adopted. It is a factual snapshot, not an evaluation of which project is better.

The machine-readable form of this snapshot is
[`docs/quality/upstream-comparison.json`](quality/upstream-comparison.json), which is
enforced by `scripts/upstream_comparison_guard.py`.

## Snapshot

| Field | Value |
|---|---|
| Reviewed date | `2026-08-10` |
| Canonical upstream repository | <https://github.com/MemPalace/mempalace> |
| Branch reviewed | `develop` |
| Commit reviewed | `8516db7fbc7f0840bf67132c5bf95c6e446d6acc` |
| Upstream paths tracked for drift | `README.md`, `CHANGELOG.md`, RFCs 003–005 |
| Fork commit at review time | this repository, `main` |

The older upstream URL `milla-jovovich/mempalace` redirects to
<https://github.com/MemPalace/mempalace>. Links written against the old path still
resolve, but the repository above is the canonical one.

Everything attributed to upstream below is taken from upstream's `README.md`,
`CHANGELOG.md`, RFCs 003–005, package metadata, or the linked public issues at the
reviewed commit. Upstream code was inspected where needed to confirm the documented
surface. It was not executed, benchmarked, or otherwise measured for this comparison.

## Source Links

Upstream repository and reviewed tree:

- <https://github.com/MemPalace/mempalace>
- <https://github.com/MemPalace/mempalace/tree/8516db7fbc7f0840bf67132c5bf95c6e446d6acc>
- <https://github.com/MemPalace/mempalace/blob/8516db7fbc7f0840bf67132c5bf95c6e446d6acc/README.md>
- <https://github.com/MemPalace/mempalace/blob/8516db7fbc7f0840bf67132c5bf95c6e446d6acc/CHANGELOG.md>
- <https://github.com/MemPalace/mempalace/blob/8516db7fbc7f0840bf67132c5bf95c6e446d6acc/docs/rfcs/003-agent-logstream-coordination.md>
- <https://github.com/MemPalace/mempalace/blob/8516db7fbc7f0840bf67132c5bf95c6e446d6acc/docs/rfcs/004-replicated-palace.md>
- <https://github.com/MemPalace/mempalace/blob/8516db7fbc7f0840bf67132c5bf95c6e446d6acc/docs/rfcs/005-agent-identity-routing.md>

Public upstream issues consulted, with their state at the reviewed date:

| Link | State at review | What it shows |
|---|---|---|
| <https://github.com/MemPalace/mempalace/issues/1663> | open, unassigned, labelled P2 | The broader configurable-model request remains open even though new onboarding now recommends and selects EmbeddingGemma |
| <https://github.com/MemPalace/mempalace/issues/1858> | open | A reported Apple Silicon migration / re-embedding failure |
| <https://github.com/MemPalace/mempalace/issues/2045> | closed on 2026-08-02, labelled P1 | The reported `sqlite_exact` co-writer corruption class was closed after process-lifetime single-writer ownership landed |
| <https://github.com/MemPalace/mempalace/issues/875> | closed | Historical hybrid-retrieval / reranking user critique |
| <https://github.com/MemPalace/mempalace/issues/367> | closed | Historical hybrid-retrieval / reranking user critique |
| <https://github.com/MemPalace/mempalace/issues/29> | closed | Historical hybrid-retrieval / reranking user critique |

The closed issues (#875, #367, #29) are historical user critiques: they show that
hybrid-retrieval and reranking behaviour was disputed by users at some point in the
past, not that it is disputed today. Issues #1663 and #1858 remain open at the reviewed
date; #2045 is now closed. Taken together, these links set the evidence limits for this
comparison — they bound what can be claimed from public issue history — and do not by
themselves establish a present defect in upstream or any claim about upstream's popularity.

## Capability Comparison

| Area | Upstream, as advertised at the reviewed commit | This fork today |
|---|---|---|
| Product focus | General-purpose AI memory | Code-first memory: repository mining, `code_search`, symbol/type/project-graph tools |
| Default storage backend | ChromaDB | LanceDB |
| Other storage backends offered | `sqlite_exact`, Milvus, Qdrant, pgvector | ChromaDB only, as a deprecated optional `.[chroma]` extra; no server-backed backends |
| Embedding model | New onboarding recommends and selects `embeddinggemma-300m`; existing installs without an explicit selection remain on `all-MiniLM-L6-v2` | `all-MiniLM-L6-v2`; no supported multilingual configuration or migration flow |
| Retrieval | Hybrid retrieval | Vector search, plus a local deterministic `code_search(rerank="hybrid")` that blends vector score with lexical/symbol signals |
| Reranking | Optional LLM reranking | None. No LLM reranker exists in this fork; this direction is explicitly rejected |
| MCP surface | 44 tools, including logstream events and artifact handoffs | 29 tools over stdio, with startup profiles reducing the exposed set |
| Coordination and replication | Agent logstream, artifact handoffs, live-hub write routing, and preview read-replica/mesh flows | No logstream, palace replication, mesh, or live-hub transport |
| Distribution | Python package plus a published multi-arch Docker image | Python package and pipx installation; no published Docker image |
| Writer ownership | Process-lifetime single-writer ownership for local backends; read-only coexistence | Single-process local storage model with explicit watcher/miner/maintenance ownership guards |
| Network dependency | Core local flows require no API key; server backends, peer replication, and optional LLM reranking add network surfaces when selected | Offline after the one-time embedding model download; no API keys |

Reading of the table: upstream offers a broader configuration and distributed-operation
surface. This fork keeps a narrower local code-memory boundary. Neither column is a
claim about correctness or speed.

## Capability Identifiers

These are the identifiers recorded in
[`docs/quality/upstream-comparison.json`](quality/upstream-comparison.json). The guard
requires that every identifier in the manifest also appears here, so the manifest and
this document cannot drift apart silently.

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
- `agent-logstream-artifact-handoffs`
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
- `no-agent-logstream`
- `no-palace-replication`
- `no-published-docker-image`

## Fork Stance

The fork has reviewed upstream's current directions and adopted none of them. The
decisions below are the current position, and each is revisited whenever this document
is re-reviewed.

**Multilingual embeddings — not adopted.** The supported default remains
`all-MiniLM-L6-v2`; this fork has no supported multilingual configuration and migration
flow. Any model change is gated by the no-regression rule in `CLAUDE.md`: a candidate
must match or beat MiniLM on LongMemEval R@5 for text retrieval and must not regress code
retrieval. Adding a second, larger model also adds a second download, a second cache, and
a re-embedding migration for existing palaces. Upstream now ships an onboarding path for
EmbeddingGemma while its broader configurable-model request (#1663) and the reported Apple
Silicon migration failure (#1858) remain open. The fork requires its own text and code
retrieval evidence plus a supported migration before changing this contract.

**Broad hybrid retrieval — not adopted.** The fork does not add a general hybrid
retrieval layer across all search paths. It does ship one narrow, local, deterministic
hybrid path: `code_search(rerank="hybrid")`, which reorders vector results using lexical
and symbol signals computed on the machine, with no model call and no network access.
That is the scope the fork is willing to maintain.

**LLM reranking — explicitly rejected.** An LLM reranker would introduce an API key, a
per-query network call, per-query cost, and non-deterministic results into a tool whose
stated contract is that indexing and search stay local after the one-time model
download. This is a rejection on product grounds, and it is not conditional on any
future upstream evidence.

**Additional storage backends — not adopted.** The fork stays LanceDB-default and
single-process. ChromaDB remains only as a deprecated optional extra for compatibility
with palaces created before the LanceDB default, and it is capped below ChromaDB 1.x
while GHSA-f4j7-r4q5-qw2c affects the available 1.x line. Milvus, Qdrant, and pgvector
would each add a server to operate, which contradicts the fork's no-server premise.

**Agent logstream, live-hub routing, and palace replication — not adopted.** Upstream
3.7.0 adds coordination events, artifact handoffs, a live service routing seam, and
preview read-replica/mesh flows. This fork has no corresponding daemon, network transport,
replication protocol, or cross-agent event log. Adopting that surface would add distributed
identity, authentication, consistency, migration, and operations contracts beyond the
fork's local code-memory scope.

**Published Docker image — not adopted.** Upstream publishes an amd64/arm64 image and
documents mounted `/data` persistence. This fork's supported installation paths remain
Python environments and pipx. A container distribution would add another release artifact,
runtime compatibility matrix, cache/mount contract, and ongoing image-security workload.

## Evidence Limits

State these limits before quoting anything from this document.

- **Repository review only.** Upstream claims are read from the pinned README, changelog,
  RFCs, package metadata, and relevant implementation surfaces. Runtime behaviour was not
  executed or independently validated.
- **Nothing was measured.** No upstream build, benchmark, or retrieval run was performed.
  This document contains no performance comparison and supports none.
- **No popularity or adoption claims.** Stars, downloads, issue volume, and contributor
  counts are not evidence used here and must not be inferred from it.
- **Issue links are point-in-time.** Issue state, labels, and assignment can change after
  the reviewed date. Each row above states the state observed at review time only.
- **Open issues are not defect proof.** An open issue shows that a topic is contested; it
  does not establish that upstream is broken, nor that this fork is unaffected by the same
  class of problem.
- **One branch, one commit.** Only `develop` at the pinned commit was reviewed. Upstream's
  default branch, tags, and releases may differ.
- **Historical criticism is separate.** The April 2026 upstream audit material lives in
  [`UPSTREAM_HARDENING.md`](UPSTREAM_HARDENING.md) and describes upstream as it was in
  April 2026. It is not evidence about upstream today.

## Automation Policy

`scripts/upstream_comparison_guard.py` enforces this snapshot. It is stdlib-only and has
two modes.

**Static mode (default).** Validates the manifest shape, the 40-hex commit, the ISO
review date, the maximum review age (default 30 days), the README pointer and required
markers, the required section markers in this document, and consistency between the
manifest and this document's stated repository, branch, commit, review date, and
capability identifiers. Static mode performs no network access.

Static mode runs in:

- CI lint, on every push and pull request to `main`
- the local release preflight, `scripts/release_preflight.py`

Because both of those surfaces must stay network-free, neither performs the live check.

**Live mode (`--check-live`, explicit).** Performs one read-only GitHub API request for
the head commit of the manifest's branch and fails if it differs from the pinned commit,
or if the reply is not a usable JSON object containing a 40-hex sha. It never writes a
file and never performs a GitHub mutation.

Live mode runs in:

- `.github/workflows/upstream-drift.yml`, daily and on `workflow_dispatch`
- `.github/workflows/publish.yml`, before publication, so an upstream source change blocks
  a release until this document is re-reviewed

When the guard fails, the remedy is the same in every case: re-review upstream at its
current head, update this document and the manifest together, and record the new reviewed
date. The guard never updates either file on its own.
