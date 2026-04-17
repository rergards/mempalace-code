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

## Steps

### Step 1: Check Prerequisites

```bash
# Verify benchmark data exists
ls benchmarks/data/ 2>/dev/null || echo "No benchmark data"

# Verify current model
python -c "from mempalace.embeddings import get_embedder; e=get_embedder(); print(f'Model: {e.model_name}')"
```

### Step 2: Code Retrieval Benchmark

Run the standard code retrieval benchmark:

```bash
python benchmarks/code_retrieval_bench.py --output benchmarks/results_$(date +%Y%m%d).json
```

Metrics collected:
- **R@5**: Recall at 5 (target: >= 0.95)
- **R@10**: Recall at 10 (target: 1.0)
- **Embed time**: Seconds to embed all chunks
- **Query time**: Milliseconds per query
- **Index size**: MB on disk

### Step 3: Category Breakdown

If benchmark supports categories:

| Category | Description |
|----------|-------------|
| architecture | High-level design questions |
| class_lookup | Find specific class definitions |
| cross_file | References spanning multiple files |
| function_lookup | Find specific functions |

### Step 4: Compare Models (optional)

If comparing multiple models:

```bash
# Test each candidate
for model in "all-MiniLM-L6-v2" "all-mpnet-base-v2"; do
  MEMPALACE_EMBED_MODEL=$model python benchmarks/code_retrieval_bench.py --output benchmarks/results_${model}_$(date +%Y%m%d).json
done
```

### Step 5: Text Retrieval Gate (if changing models)

Per project policy, any embedding model change must also pass text retrieval benchmarks:

```bash
python benchmarks/text_retrieval_bench.py --dataset longmemeval
```

Target: Match or beat current model on LongMemEval R@5.

## Output Format

```
## Benchmark Results

Model: all-MiniLM-L6-v2
Dataset: mempalace code retrieval (20 queries, N chunks)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| R@5 | 0.950 | >= 0.95 | PASS |
| R@10 | 1.000 | 1.0 | PASS |
| Embed time | 15.2s | < 60s | PASS |
| Query time | 15.9ms | < 100ms | PASS |
| Index size | 17.0 MB | < 50 MB | PASS |

Category R@5:
- architecture: 0.800
- class_lookup: 1.000
- cross_file: 1.000
- function_lookup: 1.000

**Verdict: PASS** — Model meets all targets.
```

## Model Comparison Table

When comparing models, produce:

```
| Model | R@5 | R@10 | Embed(s) | Query(ms) | Index(MB) |
|-------|-----|------|----------|-----------|-----------|
| all-MiniLM-L6-v2 | 0.950 | 1.000 | 15.2 | 15.9 | 17.0 |
| all-mpnet-base-v2 | 0.900 | 1.000 | 47.5 | 30.5 | 17.7 |

**Recommendation:** minilm remains default (better R@5, 3x faster).
```
