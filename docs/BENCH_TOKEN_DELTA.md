# Token-Delta Benchmark

How many tokens does `mempalace_search` save compared to the naive "grep + read files" approach?

## Method

For each query:

1. **Baseline ("grep + read"):** Extract 1-3 keywords from the query, `grep -rl` to find candidate files, read the top-5 files entirely, count tokens via `tiktoken` (`cl100k_base` encoding). This simulates a plain AI coding session with no memory — the agent greps for keywords and reads matching files.

2. **mempalace-code:** Mine the project, call `search_memories(query, limit=5)`, concatenate the returned chunk content. Count tokens the same way.

3. **Ratio:** `baseline_tokens / mempalace_tokens`. Higher = more savings.

The query set is the same 20 known-answer queries from `benchmarks/embed_ab_bench.py`, covering function lookup, class lookup, architecture questions, and cross-file questions.

## Results — canonical fixture

Measured on the current canonical large-repo fixture: 378 tracked files, 2,024 chunks
mined, 20 queries, top-5 results per query.

| Metric | Value |
|--------|-------|
| **Median ratio** | **14.5x fewer tokens** |
| Mean ratio | 15.8x |
| P95 ratio | 27.8x |
| Peak ratio | 33.8x |
| Retrieval precision@5 | 50% |
| Aggregate | 750,741 baseline → 48,960 mempalace tokens |

### Per-category median ratios

| Category | Median | Queries |
|----------|--------|---------|
| architecture | 20.7x | 5 |
| class_lookup | 13.4x | 4 |
| cross_file | 11.3x | 5 |
| function_lookup | 15.7x | 6 |

### Freshness

These are measured, reproducible facts, not marketing copy: the median, mean, peak, and
retrieval-precision figures above are read directly from
[`benchmarks/token_delta_fixture_facts.json`](../benchmarks/token_delta_fixture_facts.json),
a committed, sanitized (no fixture name, no local paths) summary of the last real benchmark
run. `scripts/docs_drift_guard.py` fails CI if those four figures drift from that file, or
if this page references a stale, superseded project-size claim from a prior fixture that no
longer matches the committed metadata. The P95 ratio, aggregate token totals, per-category
medians, and tracked-file/mined-drawer counts above are reported from the same run but are
not individually guard-checked field by field — re-run the benchmark below and refresh this
page together with the committed facts file before citing new numbers.

The facts file's `commit` field identifies the specific working tree that was measured; on
a squash-merged branch that commit may not be reachable from public history. Treat
`fixture_ref` plus the tracked-file/mined-drawer counts as the durable reproducibility
anchor, not the commit hash alone.

## How to reproduce

```bash
# Install tiktoken (one-time)
pip install tiktoken

# Run on the mempalace repo itself and refresh the committed fixture facts
python benchmarks/token_delta_bench.py \
  --project . \
  --out benchmarks/results_token_delta_mempalace.json \
  --fixture-facts-out benchmarks/token_delta_fixture_facts.json \
  --baseline-facts benchmarks/token_delta_fixture_facts.json \
  --drift-threshold-pct 10
```

The committed `benchmarks/results_token_delta_mempalace.json` is a detailed per-query dump
from one past run — a worked example, not a CI-guarded artifact, and it is not guaranteed to
numerically match the current published figures above (individual runs vary with
embedding/ANN retrieval non-determinism and corpus drift). The canonical, CI-checked source
of truth is `benchmarks/token_delta_fixture_facts.json` — commit a refreshed facts file
alongside any public doc update that cites new numbers.

Token savings scale with project size: grep noise grows with the number of files
containing a keyword, while `mempalace-code search` stays constant at the top-5
semantically relevant chunks regardless of corpus size. Treat the figures above as
benchmark results for this fixture's query set and corpus size; re-run the benchmark
before applying them to a different corpus.
