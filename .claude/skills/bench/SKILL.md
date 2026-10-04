---
name: bench
description: Run embedding benchmarks — R@5 code retrieval, timing, model comparison
disable-model-invocation: false
---

# Embedding Benchmarks

Run retrieval quality and performance benchmarks.

## When to Use

- Evaluating embedding model changes
- Performance regression testing
- Comparing model candidates
- User says "benchmark", "bench", "test embeddings"

## Baseline rule

There are no fixed pass/fail thresholds. The only recorded code-retrieval numbers
(the historical 2026-04-09 table in `AGENTS.md`) came from an older fixed list of
20 queries and are not comparable with the current dataset. Compare a candidate
only with a baseline measured by the same command, dataset, and environment — for
example the base commit run immediately before the candidate. Report a regression
or no regression against that baseline, never PASS/FAIL against a remembered
number.

Write every report under a disposable temp directory, never into the checkout,
and remove it when done.

## Steps

### Step 1: Check Prerequisites

```bash
OUT_DIR=$(mktemp -d)
python -c "from mempalace_code.storage import DEFAULT_EMBED_MODEL; print(f'Model: {DEFAULT_EMBED_MODEL}')"
python benchmarks/code_retrieval_bench.py --repo-dir . --validate-dataset
```

The embedding model must already be cached (`mempalace-code fetch-model`).

### Step 2: Code Retrieval Benchmark

```bash
python benchmarks/code_retrieval_bench.py \
  --repo-dir . \
  --modes smart \
  --out "$OUT_DIR/code_retrieval.json"
```

The report has `meta.report_schema_version` 2. For each mode it records
`chunk_count`, `embed_time_s`, and `index_size_mb`, plus one entry per search path
(`store.query`, `code_search`, `code_search_hybrid`). Each path reports R@5, R@10,
and MRR for two populations — `symbol` (the expected symbol must be retrieved)
and `file_only` (the expected file is enough) — and a `per_category` breakdown
over the dataset categories in `benchmarks/data/code_retrieval_queries.json`.
Compare each population separately; never merge them into one score.

### Step 3: Compare Models (optional)

`benchmarks/embed_ab_bench.py` loads `benchmarks/data/code_retrieval_queries.json`,
the same dataset as `code_retrieval_bench.py`. Its results are therefore not
comparable with the historical 2026-04-09 results, which came from an older fixed
list of 20 queries (see `AGENTS.md`).
Its numbers are comparable only with other `embed_ab_bench.py` runs. Models other
than the default need the `[custom-models]` extra.

```bash
python benchmarks/embed_ab_bench.py \
  --models minilm,mpnet \
  --skip-longmemeval \
  --out "$OUT_DIR/models.json"
```

### Step 4: Text Retrieval Gate (if changing models)

Switching models requires passing the [text gate](../../../AGENTS.md#text-gate)
in `AGENTS.md`; that section also names the only environment where it runs and
when the switch is blocked. In that environment, the Step 3 command with
`--longmemeval-data benchmarks/data/longmemeval_s_cleaned.json` in place of
`--skip-longmemeval` runs the LongMemEval harness in the same interpreter. When
the gate cannot run, fill the report's `Text gate:` line with `not run: <reason>`.

## Output Format

```
## Benchmark Results

Model: <model>   Commit: <candidate sha>   Baseline: <baseline sha, same command>
Dataset: benchmarks/data/code_retrieval_queries.json (<N> queries, <chunks> chunks)

| Path | Population | R@5 | R@10 | MRR | Baseline R@5 | Delta |
|------|------------|-----|------|-----|--------------|-------|
| code_search | symbol | ... | ... | ... | ... | ... |
| code_search | file_only | ... | ... | ... | ... | ... |

Embed time: <s> (baseline <s>)   Index size: <MB> (baseline <MB>)
Text gate: <R@5 vs baseline | not run: reason>

**Verdict:** <no regression | regression in: ... | blocked: ...>
```

## Model Comparison Table

When comparing models with `embed_ab_bench.py`, produce:

```
| Model | R@5 | R@10 | Embed(s) | Query(ms) | Index(MB) |
|-------|-----|------|----------|-----------|-----------|
| all-MiniLM-L6-v2 | ... | ... | ... | ... | ... |
| <candidate> | ... | ... | ... | ... | ... |

**Recommendation:** <keep the default | switch, with the text-gate result>
```
