# Token-Delta Benchmark

How many tokens does `mempalace_search` save compared to the naive "grep + read files" approach?

## Method

For each query:

1. **Baseline ("grep + read"):** Extract 1-3 keywords from the query, `grep -rl` to find candidate files, read the top-5 files entirely, count tokens via `tiktoken` (`cl100k_base` encoding). This simulates a plain AI coding session with no memory — the agent greps for keywords and reads matching files.

2. **mempalace-code:** Mine the project, call `search_memories(query, limit=5)`, concatenate the returned chunk content. Count tokens the same way.

3. **Ratio:** `baseline_tokens / mempalace_tokens`. Higher = more savings.

The query set is the same 20 known-answer queries from `benchmarks/embed_ab_bench.py`, covering function lookup, class lookup, architecture questions, and cross-file questions.

## Results — mempalace repo (self-dogfood)

555 chunks mined from the mempalace codebase itself. 20 queries.

| Metric | Value |
|--------|-------|
| **Median ratio** | **13.4x fewer tokens** |
| Mean ratio | 18.9x |
| P95 ratio | 41.8x |
| Aggregate | 910,867 baseline → 50,000 mempalace tokens |

### Per-category median ratios

| Category | Median | Queries |
|----------|--------|---------|
| class_lookup | 19.7x | 4 |
| cross_file | 13.7x | 5 |
| function_lookup | 9.7x | 6 |
| architecture | 6.2x | 5 |

### Per-query breakdown

| # | Category | Baseline | mempalace-code | Ratio | Query |
|---|----------|----------|-----------|-------|-------|
| 1 | function_lookup | 7,805 | 2,728 | 2.9x | detect programming language from file extension |
| 2 | function_lookup | 21,394 | 3,034 | 7.1x | chunk code at structural boundaries |
| 3 | function_lookup | 30,044 | 2,442 | 12.3x | extract symbol name and type from code chunk |
| 4 | function_lookup | 83,356 | 2,699 | 30.9x | semantic search across palace drawers |
| 5 | function_lookup | 16,920 | 2,370 | 7.1x | add drawer to palace with metadata |
| 6 | function_lookup | 123,656 | 2,108 | 58.7x | merge small chunks and split oversized ones |
| 7 | class_lookup | 57,361 | 2,601 | 22.1x | DrawerStore abstract interface for storage backend |
| 8 | class_lookup | 48,373 | 2,788 | 17.4x | LanceDB crash safe vector storage backend |
| 9 | class_lookup | 14,196 | 2,538 | 5.6x | ChromaStore legacy storage backend |
| 10 | class_lookup | 48,322 | 2,190 | 22.1x | gitignore pattern matcher for file scanning |
| 11 | architecture | 75,334 | 2,357 | 32.0x | how does the miner route files to rooms |
| 12 | architecture | 2,446 | 2,211 | 1.1x | how are embeddings generated and stored in LanceDB |
| 13 | architecture | 16,248 | 2,896 | 5.6x | what metadata fields are stored per drawer |
| 14 | architecture | 15,036 | 2,409 | 6.2x | how does smart chunking dispatch between code/prose |
| 15 | architecture | 93,514 | 2,758 | 33.9x | MCP server tool handler dispatch and request routing |
| 16 | cross_file | 32,283 | 2,358 | 13.7x | open_store factory function backend detection |
| 17 | cross_file | 97,077 | 2,805 | 34.6x | mine project directory files into palace drawers |
| 18 | cross_file | 27,320 | 2,515 | 10.9x | knowledge graph temporal entity relationship triples |
| 19 | cross_file | 66,322 | 1,622 | 40.9x | conversation mining Claude ChatGPT Slack exports |
| 20 | cross_file | 33,860 | 2,571 | 13.2x | tiered context loading wake-up layers for local models |

### Notes

- Query #12 (1.1x) is the floor case: "how are embeddings generated" matched only one small file via grep, so the baseline was already compact. mempalace-code still found the right content.
- The highest ratios (30-59x) occur on broad queries where grep matches many files containing the keyword but only one is relevant. mempalace-code's semantic search skips the noise.
- All ratios use `limit=5` (top-5 results). Higher limits would increase mempalace token count but also improve recall.

## Results — large private project (19k chunks)

A full-stack application with backend, frontend, infrastructure, tests, and documentation. 19,308 chunks mined. Same 20 queries.

| Metric | Value |
|--------|-------|
| **Median ratio** | **80.3x fewer tokens** |
| Mean ratio | 128.5x |
| P95 ratio | 279.3x |
| Aggregate | 5,978,207 baseline → 49,558 mempalace tokens |

### Per-category median ratios

| Category | Median | Queries |
|----------|--------|---------|
| cross_file | 155.9x | 5 |
| class_lookup | 91.2x | 4 |
| function_lookup | 77.1x | 6 |
| architecture | 60.0x | 5 |

### Scaling observation

Token savings grow with project size. On a 555-chunk project, the median is 13x. On a 19k-chunk project, it's 80x. The reason: grep noise scales linearly with project size (more files contain the keyword), while `mempalace-code search` stays constant (top-5 semantically relevant chunks regardless of project size).

## How to reproduce

```bash
# Install tiktoken (one-time)
pip install tiktoken

# Run on the mempalace repo itself
python benchmarks/token_delta_bench.py --project . --out benchmarks/results_token_delta_mempalace.json
```

Results file: `benchmarks/results_token_delta_mempalace.json`
