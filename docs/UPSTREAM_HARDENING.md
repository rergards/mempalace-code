# Upstream Hardening — What the Fork Keeps, Negates, and Ignores

> Historical audit note: this document preserves the April 2026 upstream-hardening
> analysis. Status lines have been updated where release blockers were resolved,
> but old backlog IDs and command names may still appear inside task descriptions
> for traceability. Current install and CLI instructions live in
> [`README.md`](../README.md) and [`docs/AGENT_INSTALL.md`](AGENT_INSTALL.md).

The upstream project `milla-jovovich/mempalace` went viral in early April 2026 and was immediately the subject of several large community audits. Three issues document the core findings:

- **`milla-jovovich/mempalace#27`** — "Multiple issues between README claims and codebase" (by `@lhl`) — the canonical 7-item punch list
- **`milla-jovovich/mempalace#524`** — "Remove Baldfaced Lies Please" (by `@nanoscopic`) — community pushback, closed without full resolution
- **`milla-jovovich/mempalace#469`** — "palace data gone after upgrade to v3.1.0" (by `@R0uter`) — ChromaDB version-cliff data-loss bug

This fork (`rergards/mempalace-code`) is a code-first rewrite that inherited the codebase in early-April state and has since diverged significantly. This document catalogs the upstream findings against the fork's current state and explains what is already resolved, what was resolved before launch, and what we consider out-of-scope.

## Summary Table

| Upstream issue | Source | Fork status | Action |
|---|---|---|---|
| "Contradiction detection" feature does not exist | #27 item 1 | **Already negated** — `fact_checker.py` is not in the fork at all, and our README makes no such claim | None — verify in FORK-README-NEGATE-STALE-CLAIMS |
| "30× lossless" AAAK claim is false | #27 item 2 | **Resolved in release docs** — README no longer presents AAAK as lossless; benchmark caveats document the 96.6% → 84.2% regression | None |
| 96.6% LongMemEval R@5 attributed to palace structure is misleading | #27 item 3 | **Resolved in README** — release-facing retrieval quality keeps the inherited 96.6% only with methodology caveats; the benchmark file is marked historical | None |
| "+34% palace structure boost" is metadata filtering, not novel | #27 item 4 | **Already negated** — not claimed in the fork README | None |
| "100% with Haiku rerank" unverifiable | #27 item 5 | **Resolved in README** — the 100% number is not a release headline; the historical benchmark file warns not to quote it without caveats | None |
| "Closets as compressed summaries" nomenclature mismatch | #27 item 6 | **Already negated** — closets are referenced in the ASCII diagram only, not claimed as a feature | None |
| Hall types not enforced at retrieval time | #27 item 7 | **Already negated** — fork describes halls as metadata connections, makes no enforcement claim | None |
| "Local, no network after install" is false (ChromaDB ONNX model downloads from AWS S3 on first use) | #524 `@gaby` | **Resolved in fork docs and CLI** — `mempalace-code init` and `mempalace-code fetch-model` make the one-time `all-MiniLM-L6-v2` download explicit; release docs state that indexing/search are offline after model setup | None |
| LongMemEval benchmark game: `n_results=min(n_results, len(corpus))` degenerates R@k into ranking over a fully-retrieved set when corpus ≤ 50 | #524 `@jtatum` | **Inherited** — `benchmarks/longmemeval_bench.py:225,303,456,606,689` use the same pattern | **FORK-BENCH-LONGMEMEVAL-CORPUS-AUDIT** |
| LongMemEval benchmark drops assistant turns at line 189-190 | #242 `@bobmatnyc` | **Partially addressed** — fork's `longmemeval_bench.py` has a `Full-turn mode` (line 641) that indexes user+assistant turns; needs audit to confirm upstream bias is fully removed | Fold into `FORK-BENCH-LONGMEMEVAL-CORPUS-AUDIT` |
| v3.0.0 → v3.1.0 silently tightens ChromaDB version and deletes users' palace data (no migration path) | #469 | **Already negated by architecture** — LanceDB is now the default backend with crash-safe columnar Arrow storage. ChromaDB is opt-in `.[chroma]` extra, marked deprecated. Upgrade path for existing LanceDB palaces is tracked by `STORE-MIGRATION-CLI` already in pre_release | Document the chroma-extra caveat in FORK-DOCS-CLEANUP |
| "Highest-scoring AI memory system ever benchmarked" tagline | #27, #524 repeatedly | **Already negated** — fork tagline is "Crash-safe LanceDB memory for developers — code-first, local-first, no API key" — no superlative, no "highest", no "ever" | None |
| AAAK encoding benchmark regresses LongMemEval 96.6 → 84.2% | #27 `@lhl` measurement | **Inherited in benchmark code** — fork keeps the AAAK path in `longmemeval_bench.py`. Not claimed as lossless in our README. Decision: inherit without claim | Out of scope — not a launch blocker |
| Community rage about marketing framing, celebrity endorsement, "vibe code + publicity stunt" concerns | #524 comment thread | **Out of scope** — the fork distances itself from upstream marketing in `README.md:276-290` ("This Fork vs Upstream") | None |
| `fact_checker.py` missing from repo but referenced in README | #27 item 1 + #524 `@nanoscopic` | **Already negated** — file genuinely does not exist in the fork, and our README does not reference it | None |

## Already Negated (9 items — nothing to do)

These are items from the upstream issues that are either (a) architectural differences the fork already has (LanceDB backend → #469 immune), (b) claims the fork never made (contradiction detection, closets-as-summaries, hall-type enforcement, +34% palace boost, highest-scoring superlative), or (c) files that simply do not exist in the fork (`fact_checker.py`).

No action required. These are listed here for auditability so a future contributor can confirm the negation still holds.

## Resolved Before Launch (historical backlog tasks)

### FORK-MODEL-OFFLINE-HANDOFF — **completed before v1.0**

**Problem**: An older README said "No internet after install. Everything local." This was false. On first mine or first search, `sentence-transformers` downloads `all-MiniLM-L6-v2` (80 MB) from HuggingFace Hub. This is the same class of overclaim gaby caught upstream in #524.

**Fix**: `mempalace-code fetch-model [--model MODEL_NAME]` explicitly downloads the embedding model during setup, and `mempalace-code init` calls it unless `--skip-model-download` is passed. Current docs say: after a one-time model download during setup, indexing and search run locally without API calls.

**Acceptance**:
- `mempalace-code fetch-model` downloads the configured embedding model into the sentence-transformers cache and verifies it can be loaded with `HF_HUB_OFFLINE=1` set
- `mempalace-code init <dir>` calls `fetch-model` automatically unless `--skip-model-download` is passed
- README explains the one-time download plainly
- `docs/OFFLINE_USAGE.md` explains how to run on an airgapped machine (pre-seed `~/.cache/huggingface/hub/`)
- Offline verification is documented with `HF_HUB_OFFLINE=1 mempalace-code search "test"`

**Why it mattered**: shipping a local-first tagline with a silent HuggingFace download on first use would repeat exactly upstream's mistake.

### FORK-README-NEGATE-STALE-CLAIMS — **completed before v1.0**

**Problem**: Older README drafts carried three inherited upstream claims flagged by `@lhl` in #27 and `@lhl`/`@nanoscopic` in #524:

1. Lines 381-386: Benchmarks table displays "LongMemEval R@5 — Raw verbatim (ChromaDB) — 96.6%" and "LongMemEval R@5 — Hybrid + Haiku rerank — 100%". The 100% Haiku rerank number is specifically the one lhl flagged as "unverifiable from the repo as shipped" and upstream ultimately removed from its headline.
2. Lines 390-395: `AAAK Dialect` section describes AAAK as "compressed memory format…readable by any LLM without a decoder". Upstream's own LongMemEval regresses 96.6 → 84.2% under AAAK — a 12.4pp loss, disqualifying the "lossless" adjective.
3. Line 318: "No internet after install. Everything local." — overlaps with FORK-MODEL-OFFLINE-HANDOFF but is specifically an overclaim separate from the fix.

**Fix**: one README audit pass that:

1. **Removes the 100% Haiku rerank row entirely.** It is an upstream number, not ours, and upstream itself retracted it from the headline.
2. **Keeps the 96.6% raw number but re-labels the row** as "LongMemEval R@5 (raw verbatim, inherited upstream baseline) — 96.6%" with a footnote pointing to `benchmarks/BENCHMARKS.md` for the methodology caveats (including the corpus-cap issue from jtatum).
3. **Rewrites the `AAAK Dialect` section** to lead with "AAAK is a lossy abbreviation format" — specifically cite the 96.6 → 84.2% R@5 regression and link to #27. Keep the section because AAAK is still useful for diary compression, but do not claim losslessness.
4. **Rewrites line 318** per FORK-MODEL-OFFLINE-HANDOFF.
5. **Adds a pointer** from the README to this document (`docs/UPSTREAM_HARDENING.md`) so the audit trail is discoverable.

**Acceptance**: Completed. Current README avoids the lossless AAAK claim, avoids the 100% Haiku headline, and is explicit about the one-time model download.

### FORK-BENCH-LONGMEMEVAL-CORPUS-AUDIT — **completed 2026-04-12**

**Problem**: `benchmarks/longmemeval_bench.py` retains the upstream pattern `n_results=min(n_results, len(corpus))` at lines 225, 303, 456, 606, and 689. LongMemEval-S has 30–50 sessions per question. When `n_results = 50` and corpus size ≤ 50, ChromaDB/LanceDB returns the full corpus, and R@5 degenerates from a retrieval metric into a ranking-within-fully-retrieved-set metric. This is exactly the jtatum critique in #524.

**Fix**: either

**(A) — minimum effort, honest label**: leave the code unchanged but add a `CORPUS_SIZE_WARNING` section to `benchmarks/BENCHMARKS.md` explaining that the 96.6% and 100% numbers are measured under `n_results = len(corpus)` for small-corpus LongMemEval-S questions, and that they therefore measure reranking quality rather than recall at scale. Make the warning a prerequisite that every benchmark result table links to.

**(B) — correct the methodology**: change the cap to `n_results = max(5, len(corpus) // 10)` or `min(5, len(corpus))` depending on the question, so R@5 measures genuine retrieval-over-larger-corpus. This changes the headline number and is a bigger scope.

**Decision recorded at launch**: option (A) was the pragmatic move — honest label, don't relitigate the upstream benchmark, scope it as "inherited, documented". Option (B) remains the right move long-term but requires rerunning the full benchmark grid.

**Acceptance**: `benchmarks/BENCHMARKS.md` has a `## Methodology Caveats` section that names the corpus-cap issue and links to upstream #524; every results table in the doc links back to that caveat section.

**Completed**: Option (A) implemented. `benchmarks/BENCHMARKS.md` now has a `## Methodology Caveats` section covering corpus-cap, assistant-turn indexing (`build_palace_and_retrieve_full`, line 639), and AAAK compression regression (96.6% → 84.2%, −12.4pp). See `benchmarks/BENCHMARKS.md#methodology-caveats`.

### FORK-DOCS-CLEANUP — **already in pre_release**

**Fold in**: add a subsection to CONTRIBUTING.md or the installation docs warning users who opt into `.[chroma]` extra that ChromaDB v0.5→v0.6 migrations can silently delete palace data (upstream #469), and that the only safe upgrade paths are (a) pin `chromadb` yourself, (b) export drawers to JSONL before upgrading, (c) use `chroma-migrate` at your own risk. Link upstream #469 so users have the full context.

**Note**: LanceDB default users are not affected by this. The warning is specifically for the opt-in legacy path.

## Out of Scope for v1.0

### AAAK encoding benchmark regression (96.6 → 84.2)

AAAK is kept in the codebase because it has a plausible niche in diary compression (`mempalace_diary_write` agents that want to pack more context into L1 wake-up). Upstream's mistake was shipping AAAK as a "lossless compression" claim on the LongMemEval headline. Our fork neither headlines LongMemEval nor claims losslessness. We keep the code, re-label the README section, and document the 96.6 → 84.2 regression in `BENCHMARKS.md` so anyone considering AAAK mode knows the tradeoff.

Not a launch blocker. Not a pre_release task. Not filed as a backlog item.

### Celebrity endorsement / vibe-code / "publicity stunt" community rage

The upstream #524 thread contains substantial community anger about marketing framing, AI-written README, and the disconnect between claims and code. Our fork:

1. Is not affiliated with the upstream project's marketing.
2. Has a dedicated "This Fork vs Upstream" section in the README that directly names the differences.
3. Is positioned as a developer tool, not a breakthrough-in-AI-memory.

We do not need to respond to upstream's drama. We do need to not inherit it. This document is part of how we do that.

### `fact_checker.py` contradiction detection

Not in the fork. Not claimed. No action required beyond the verification pass in FORK-README-NEGATE-STALE-CLAIMS. Post-launch, a proper contradiction-detection layer is a reasonable v1.2 direction but it is not a launch item.

### Knowledge graph "identical-triple blocking is the only dedup"

Upstream audit correctly noted that `knowledge_graph.py` only blocks identical open triples and does not detect conflicting values (two different `married_to` targets accumulate silently). Our fork has the same limitation. Fixing it requires wiring per-predicate cardinality rules ("single-valued predicates like `married_to` should invalidate the previous active triple when a new one is added") and is genuinely useful future work, not a launch-blocking documentation issue.

### Upstream `#242` — assistant-turn drop in longmemeval_bench.py line 189-190

Our fork's `longmemeval_bench.py` has a `Full-turn mode` (line 641) that explicitly indexes both user and assistant turns. A cursory scan suggests the upstream bias has been addressed, but a proper audit is part of FORK-BENCH-LONGMEMEVAL-CORPUS-AUDIT (which covers the same file) and does not need a separate task.

### Graphify-style always-on PreToolUse hook

Not upstream-driven, but related: the decision to NOT ship an always-on hook by default is documented in `docs/COMPARISON_GRAPHIFY.md` and backed by autopilot's mempalace-code usage audit (76% ceremonial, 19% substantive). See that document, not this one, for the reasoning.

## Bottom Line

Of the three upstream issues this audit tracks:

- **#27 punch list** — resolved or negated in release-facing docs. Inherited benchmark details are retained only with caveats.
- **#524 "baldfaced lies"** — the one-time model download is now explicit in CLI and docs; indexing/search are local after model setup.
- **#469 data loss on chromadb upgrade** — architecturally immune because LanceDB is the default backend. The opt-in chroma legacy path inherits the risk and gets a documentation warning.

No upstream issue is ignored without justification. This document remains as the audit trail; current install, privacy, and benchmark positioning should be read from the README and release-facing docs.
