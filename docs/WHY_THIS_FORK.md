# Why This Fork — Code-First Improvements Over Upstream

> **Dated comparison.** Every "Before" and the "Upstream" column below describe upstream
> `mempalace` at the April 2026 fork point (upstream `develop` merge base `71736a3f`,
> 2026-04-07). Upstream has since changed several of these points, including batched drawer
> writes, a configurable embedding model, and full-coverage status counts, so none of this is a
> claim about upstream today. The current, source-pinned comparison is
> [`docs/UPSTREAM_COMPARISON.md`](UPSTREAM_COMPARISON.md).

The original mempalace was designed as "universal memory for conversations": you dropped notes, chats, and decisions into it and everything was stored as flat text. It worked for code, but poorly — it did not understand file structure, cut chunks blindly, and silently lost meaning on anything larger than a paragraph.

This fork is **code-first**. The miner and storage layer were rebuilt so that code is searchable with precision, instead of being treated like a blog post.

## Major Differences

### 1. Structure-Aware Chunking (CODE-SMART-CHUNK)

**Before:** ~800-character chunks sized by character count, cut at the last paragraph or line break in the second half of the window when there was one — so cuts still landed mid-function and mid-docstring. The embedding model received "tail of one function + start of another", producing muddled vectors.

**After:** the miner (`mempalace_code/mining/chunkers.py`) cuts on **structural boundaries** — `def`, `class`, `function`, `export`, and top-level blocks. It targets 400–2500 characters per chunk with a hard 4000-character ceiling. One function is one chunk is one vector — clean meaning.

### 2. Language Detection (CODE-LANG-DETECT)

Every chunk now carries a `language` field (python / go / typescript / rust / …), determined from the file extension with a shebang fallback. Searches can be filtered by language, and the chunker can select a language-specific splitting strategy.

### 3. Symbol Metadata (CODE-SYMBOL-META)

Every chunk stores `symbol_name` and `symbol_type` (function / class / method). When you search `"how does detect_language work"`, the top hit clearly identifies that the matched chunk is the `detect_language` function itself — not a paragraph that happens to mention the name.

### 4. Batch Embedding During Mining (MINE-BATCH-EMBED)

**Before:** every chunk was embedded and inserted into the store one row at a time. Slow on large repositories.

**After:** chunks are buffered in batches of 128 (64 on hosts with 4 GB of RAM or less), passed through the embedding model in a single call, and bulk-inserted into LanceDB. On a 5,653-file monorepo benchmark fixture this is the difference between "until tonight" and "in a reasonable time".

### 5. LanceDB Instead of ChromaDB

The original backend was ChromaDB (SQLite + Python). It had no bulk operations, was slow on large repositories, and was fragile under interruption. This fork moved the runtime backend to **LanceDB** (Rust + Arrow, columnar, crash-safe). Current packages fully retire ChromaDB support and carry no ChromaDB dependency.

Direct effects:

- `delete_wing()` — a single SQL predicate instead of 10k per-row deletes.
- `status()` / `list_wings()` / `list_rooms()` — implemented with PyArrow `group_by` instead of loading every row into memory.
- The index survives `Ctrl+C` without corrupting data.

### 6. Mine Progress Output

Previously, `mempalace-code mine` on a large repo would appear to hang for 5+ minutes: the embedding model was loading, then it was running per-file "already mined?" checks, and nothing was printed until the first chunk was written.

Now:

```
  Loading embedding model...
  Model ready.

  Scanning [ 1234/5653]...
  >> Embedding batch 12 (128 chunks)... done (1.3s)
```

Keyboard interrupts are also handled cleanly: the current batch is flushed before exit.

### 7. A/B Embedding Model Benchmark (BENCH-EMBED-AB)

A code-first fork should not upgrade its embedding model on vibes. This fork ships an explicit A/B benchmark, `benchmarks/embed_ab_bench.py`, that scores each candidate model on the known-answer queries in `benchmarks/data/code_retrieval_queries.json`, the same dataset `benchmarks/code_retrieval_bench.py` uses.

In the 2026-04-09 run, which used an earlier fixed list of 20 queries, `all-MiniLM-L6-v2` was compared against `all-mpnet-base-v2` and `nomic-embed-text-v1.5`. MiniLM stays the default: R@5 = 0.950, fastest, 80 MB model. A future model upgrade is governed by the [text gate](../AGENTS.md#text-gate) in `AGENTS.md`.

Full results are in `benchmarks/results_embed_ab_2026-04-09.json` and summarized in the project `AGENTS.md`.

### 8. Configurable Embedding Model

`open_store(..., embed_model="sentence-transformers/all-mpnet-base-v2")` can run palaces with explicit alternative Hugging Face models or local SentenceTransformer paths when `mempalace-code[custom-models]` is installed. The ordinary install keeps the canonical MiniLM FastEmbed/ONNX runtime and does not load trusted remote code.

### 9. Diary Write CLI (CLI-DIARY-WRITE)

`mempalace-code diary write --agent claude-code --entry "..."` lets agents append journal entries about a session without going through MCP. This matters for code workflows because the autopilot task runner writes per-task reports directly into memory.

### 10. Storage Hygiene

- `STORE-DELETE-WING` — a proper bulk delete instead of an ad-hoc script.
- `STORE-STATUS-LIMIT` — removed a hard-coded `limit=10000` that silently hid 2 of 3 wings on a palace with 21k rows.
- `status`, `list_wings`, and `list_rooms` now show **everything**, not just the first 10k rows in insertion order.

## Summary Table

| Concern               | Upstream at fork point (April 2026) | This Fork                          |
|-----------------------|-------------------------------------|------------------------------------|
| Code chunking         | ~800 characters, line-break aware   | structural (`def` / `class`)       |
| Chunk language        | unknown                             | stored per chunk                   |
| Symbol metadata       | none                                | `symbol_name`, `symbol_type`       |
| Embedding at mine     | one chunk at a time                 | batches of 128 (64 on ≤4 GB RAM)   |
| Storage backend       | ChromaDB                            | LanceDB (Rust / Arrow)             |
| Bulk delete wing      | none                                | `delete_wing()`                    |
| Mine progress         | a line per filed file only          | per-file + per-batch progress      |
| Model choice          | hard-coded                          | configurable + benchmark-gated     |
| Diary from CLI        | MCP only                            | `mempalace-code diary write`       |
| `status` aggregations | `limit=10000`                       | PyArrow `group_by`, full coverage  |

## The Net Effect

Taken together, these changes produce two concrete outcomes:

1. **Searching for "how does X work" finds the X function itself**, not a random paragraph nearby.
2. **Mining a large monorepo takes minutes, not hours**, and does not corrupt the index if you hit `Ctrl+C`.
