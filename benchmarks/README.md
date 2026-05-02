# Historical MemPal Benchmarks — Reproduction Guide

This file preserves the inherited conversation-memory benchmark reproduction
commands from the old `mempal` benchmark branch. It is not the current
mempalace-code release benchmark. Current release-facing token-savings numbers
live in [`../docs/BENCH_TOKEN_DELTA.md`](../docs/BENCH_TOKEN_DELTA.md).

Run these commands only when reproducing the historical LongMemEval/LoCoMo/
ConvoMem results discussed in [`BENCHMARKS.md`](BENCHMARKS.md).

## Setup

```bash
git clone -b ben/benchmarking https://github.com/aya-thekeeper/mempal.git
cd mempal
pip install chromadb pyyaml
```

## Benchmark 1: LongMemEval (500 questions)

Tests retrieval across ~53 conversation sessions per question. The standard benchmark for AI memory.

```bash
# Download data
mkdir -p /tmp/longmemeval-data
curl -fsSL -o /tmp/longmemeval-data/longmemeval_s_cleaned.json \
  https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json

# Run (raw mode — our headline 96.6% result)
python benchmarks/longmemeval_bench.py /tmp/longmemeval-data/longmemeval_s_cleaned.json

# Run with AAAK compression (84.2%)
python benchmarks/longmemeval_bench.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --mode aaak

# Run with room-based boosting (89.4%)
python benchmarks/longmemeval_bench.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --mode rooms

# Quick test on 20 questions first
python benchmarks/longmemeval_bench.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --limit 20

# Turn-level granularity
python benchmarks/longmemeval_bench.py /tmp/longmemeval-data/longmemeval_s_cleaned.json --granularity turn
```

**Expected output (raw mode, full 500):**
```
Recall@5:  0.966
Recall@10: 0.982
NDCG@10:   0.889
Time:      ~5 minutes on Apple Silicon
```

## Benchmark 2: LoCoMo (1,986 QA pairs)

Tests multi-hop reasoning across 10 long conversations (19-32 sessions each, 400-600 dialog turns).

```bash
# Clone LoCoMo
git clone https://github.com/snap-research/locomo.git /tmp/locomo

# Run (session granularity — our 60.3% result)
python benchmarks/locomo_bench.py /tmp/locomo/data/locomo10.json --granularity session

# Dialog granularity (harder — 48.0%)
python benchmarks/locomo_bench.py /tmp/locomo/data/locomo10.json --granularity dialog

# Higher top-k (77.8% at top-50)
python benchmarks/locomo_bench.py /tmp/locomo/data/locomo10.json --top-k 50

# Quick test on 1 conversation
python benchmarks/locomo_bench.py /tmp/locomo/data/locomo10.json --limit 1
```

**Expected output (session, top-10, full 10 conversations):**
```
Avg Recall: 0.603
Temporal:   0.692
Time:       ~2 minutes
```

## Benchmark 3: ConvoMem (Salesforce, 75K+ QA pairs)

Tests six categories of conversational memory. Downloads from HuggingFace automatically.

```bash
# Run all categories, 50 items each (our 92.9% result)
python benchmarks/convomem_bench.py --category all --limit 50

# Single category
python benchmarks/convomem_bench.py --category user_evidence --limit 100

# Quick test
python benchmarks/convomem_bench.py --category user_evidence --limit 10
```

**Categories available:** `user_evidence`, `assistant_facts_evidence`, `changing_evidence`, `abstention_evidence`, `preference_evidence`, `implicit_connection_evidence`

**Expected output (all categories, 50 each):**
```
Avg Recall: 0.929
Assistant Facts: 1.000
User Facts:      0.980
Time:            ~2 minutes
```

## Benchmark 4: Code Retrieval Chunking

Tests whether retrieval surfaces the right source file for developer-style code questions.
It compares three chunking modes while holding the embedding model fixed at
`all-MiniLM-L6-v2`:

- `naive`: benchmark-only fixed line windows.
- `smart`: production regex/adaptive chunking with tree-sitter suppressed for this run.
- `treesitter`: production AST-capable chunking; records degraded fallback when grammars are unavailable.

```bash
# Validate the known-answer dataset without embedding or querying
python benchmarks/code_retrieval_bench.py --repo-dir . --validate-dataset

# Fast smoke run
python benchmarks/code_retrieval_bench.py --repo-dir . --modes smart --limit 5 --out /tmp/code-bench.json

# Compare all modes
python benchmarks/code_retrieval_bench.py \
  --repo-dir . \
  --modes naive,smart,treesitter \
  --limit 5 \
  --out /tmp/code-bench.json
```

The JSON report contains `meta`, a `modes` map, and a compact `comparison`
section. Each mode includes `chunk_count`, `embed_time_s`,
`query_latency_avg_ms`, `R@5`, `R@10`, `MRR`, `per_category`, and per-query
`top5_files` / `top5_symbols`. Recall answers only "did retrieval surface the
right code file?" It does not prove an LLM would generate a correct answer.

## Benchmark 5: .NET Code Retrieval

Tests C#/.NET retrieval on a pinned CleanArchitecture corpus. The known-answer
dataset targets `jasontaylordev/CleanArchitecture` tag `v7.0.0` at commit
`5a600ab8749c110384bc3bd436b9c67f3067b489`.

```bash
# Fetch the pinned commit (reproducible; does not depend on a mutable tag)
git init /tmp/CleanArchitecture
git -C /tmp/CleanArchitecture remote add origin https://github.com/jasontaylordev/CleanArchitecture.git
git -C /tmp/CleanArchitecture fetch --depth=1 origin 5a600ab8749c110384bc3bd436b9c67f3067b489
git -C /tmp/CleanArchitecture checkout --detach FETCH_HEAD

# Validate that the known-answer files exist in the pinned corpus
python benchmarks/dotnet_bench.py \
  --repo-dir /tmp/CleanArchitecture \
  --validate-queries

# Run the benchmark and write a JSON report (warning-only, local dev)
python benchmarks/dotnet_bench.py \
  --repo-dir /tmp/CleanArchitecture \
  --out /tmp/dotnet-bench.json

# Run with the CI gate threshold (exits 1 when R@5 < 0.800)
python benchmarks/dotnet_bench.py \
  --repo-dir /tmp/CleanArchitecture \
  --out /tmp/dotnet-bench.json \
  --fail-under-r5 0.800
```

The benchmark mines the target repo into a temporary LanceDB palace, then
measures R@5/R@10 across symbol lookup, cross-project interface/implementation,
service registration, and project dependency queries.

Current v1.6.0 baseline on the pinned corpus:

| Metric | Value |
|---|---:|
| Chunks | 271 |
| R@5 | 0.600 |
| R@10 | 0.850 |
| Embed time | 10.0s |
| Avg query latency | 13.9ms |

> **Note:** R@5 is currently 0.600, below the CI gate threshold of 0.800. The
> `.NET Benchmark` GitHub Actions workflow will therefore **fail on every run**
> until retrieval quality improves. This is intentional — the gate documents the
> quality target, not the current state. Do not lower the threshold; track
> quality improvement separately.

### CI Gate

The workflow `.github/workflows/dotnet-bench.yml` runs on every pull request to
`main` and every push to `main`. It:

1. Fetches `jasontaylordev/CleanArchitecture` at the pinned commit
   `5a600ab8749c110384bc3bd436b9c67f3067b489` and verifies `HEAD` matches.
2. Runs `--validate-queries` to confirm expected files are present in the corpus.
3. Runs the benchmark with `--fail-under-r5 0.800`; exits 1 when overall R@5
   falls below 0.800.
4. Uploads `benchmarks/results_dotnet_bench_ci.json` as a build artifact, even
   on failure, so the report is always available.

To skip the benchmark on a pull request (e.g. for documentation-only changes),
add the **`skip-bench`** label. The job is skipped before cloning
CleanArchitecture or downloading the embedding model. Pushes to `main` always
run the benchmark regardless of labels.

## What Each Benchmark Tests

| Benchmark | What it measures | Why it matters |
|---|---|---|
| **LongMemEval** | Can you find a fact buried in 53 sessions? | Tests basic retrieval quality — the "needle in a haystack" |
| **LoCoMo** | Can you connect facts across conversations over weeks? | Tests multi-hop reasoning and temporal understanding |
| **ConvoMem** | Does your memory system work at scale? | Tests all memory types: facts, preferences, changes, abstention |
| **Code Retrieval** | Can you retrieve the right source files for code questions? | Tests code mining and chunker quality separately from answer generation |
| **.NET Retrieval** | Can you retrieve the right C#/.NET files across projects? | Tests .NET mining, project files, and architecture-oriented query coverage |

## Results Files

Historical raw result files from the original benchmark runs are not committed to this repository. The benchmark scripts write full result JSONL/JSON files when run — every question, every retrieved document, every score. Regenerate them using the commands above. See `benchmarks/BENCHMARKS.md` for the full list of expected output filenames per mode.

## Requirements for the Historical Benchmark Branch

- Python 3.9+ for the historical `ben/benchmarking` branch; the current
  mempalace-code package requires Python 3.11+
- `chromadb` (the only dependency)
- ~300MB disk for LongMemEval data
- ~5 minutes for each full benchmark run
- No API key. No internet during benchmark (after data download). No GPU.

## Next Benchmarks (Planned)

- **Scale testing** — ConvoMem at 50/100/300 conversations per item
- **Hybrid AAAK** — search raw text, deliver AAAK-compressed results
- **End-to-end QA** — retrieve + generate answer + measure F1 (needs LLM API key)
