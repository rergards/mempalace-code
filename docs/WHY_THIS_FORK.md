# Why This Fork — Code-First Improvements Over Upstream

The original mempalace was designed as "universal memory for conversations": you dropped notes, chats, and decisions into it and everything was stored as flat text. It worked for code, but poorly — it did not understand file structure, cut chunks blindly, and silently lost meaning on anything larger than a paragraph.

This fork is **code-first**. The miner and storage layer were rebuilt so that code is searchable with precision, instead of being treated like a blog post.

## Major Differences

### 1. Structure-Aware Chunking (CODE-SMART-CHUNK)

**Before:** fixed ~1000-character chunks, cut wherever the character count ran out — mid-function, mid-docstring. The embedding model received "tail of one function + start of another", producing muddled vectors.

**After:** `miner.py` cuts on **structural boundaries** — `def`, `class`, `function`, `export`, and top-level blocks. It targets 400–2500 characters per chunk with a hard 4000-character ceiling. One function is one chunk is one vector — clean meaning.

### 2. Language Detection (CODE-LANG-DETECT)

Every chunk now carries a `language` field (python / go / typescript / rust / …), determined from the file extension with a shebang fallback. Searches can be filtered by language, and the chunker can select a language-specific splitting strategy.

### 3. Symbol Metadata (CODE-SYMBOL-META)

Every chunk stores `symbol_name` and `symbol_type` (function / class / method). When you search `"how does detect_language work"`, the top hit clearly identifies that the matched chunk is the `detect_language` function itself — not a paragraph that happens to mention the name.

### 4. Batch Embedding During Mining (MINE-BATCH-EMBED)

**Before:** every chunk was embedded and inserted into the store one row at a time. Slow on large repositories.

**After:** chunks are buffered in batches of 128, passed through the embedding model in a single call, and bulk-inserted into LanceDB. On a 5,653-file monorepo (`wh40kdh2calc_planner`) this is the difference between "until tonight" and "in a reasonable time".

### 5. LanceDB Instead of ChromaDB

The original backend was ChromaDB (SQLite + Python). It had no bulk operations, was slow on large repositories, and was fragile under interruption. This fork moved the core backend to **LanceDB** (Rust + Arrow, columnar, crash-safe). ChromaDB is kept as an opt-in `.[chroma]` extra and marked deprecated.

Direct effects:

- `delete_wing()` — a single SQL predicate instead of 10k per-row deletes.
- `status()` / `list_wings()` / `list_rooms()` — implemented with PyArrow `group_by` instead of loading every row into memory.
- The index survives `Ctrl+C` without corrupting data.

### 6. Mine Progress Output

Previously, `mempalace mine` on a large repo would appear to hang for 5+ minutes: the embedding model was loading, then it was running per-file "already mined?" checks, and nothing was printed until the first chunk was written.

Now:

```
  Loading embedding model...
  Model ready.

  Scanning [ 1234/5653]...
  >> Embedding batch 12 (128 chunks)... done (1.3s)
```

Keyboard interrupts are also handled cleanly: the current batch is flushed before exit.

### 7. A/B Embedding Model Benchmark (BENCH-EMBED-AB)

A code-first fork should not upgrade its embedding model on vibes. This fork ships an explicit benchmark with 20 known-answer queries across 4 categories (`function_lookup`, `class_lookup`, `architecture`, `cross_file`).

`all-MiniLM-L6-v2` was compared against `all-mpnet-base-v2` and `nomic-embed-text-v1.5`. MiniLM stays the default: R@5 = 0.950, fastest, 80 MB model. Any future model upgrade must pass both the code gate **and** the LongMemEval text gate — prose retrieval quality is non-negotiable.

Full results are in `benchmarks/results_embed_ab_2026-04-09.json` and summarized in the project `CLAUDE.md`.

### 8. Configurable Embedding Model

`open_store(..., embed_model="nomic")` — you can now run several palaces side by side with different models. Previously the model was a hard-coded constant.

### 9. Diary Write CLI (CLI-DIARY-WRITE)

`mempalace diary write --agent claude-code "..."` lets agents append journal entries about a session without going through MCP. This matters for code workflows because the autopilot task runner writes per-task reports directly into memory.

### 10. Storage Hygiene

- `STORE-DELETE-WING` — a proper bulk delete instead of an ad-hoc script.
- `STORE-STATUS-LIMIT` — removed a hard-coded `limit=10000` that silently hid 2 of 3 wings on a palace with 21k rows.
- `status`, `list_wings`, and `list_rooms` now show **everything**, not just the first 10k rows in insertion order.

## Summary Table

| Concern               | Upstream              | This Fork                          |
|-----------------------|-----------------------|------------------------------------|
| Code chunking         | fixed character count | structural (`def` / `class`)       |
| Chunk language        | unknown               | stored per chunk                   |
| Symbol metadata       | none                  | `symbol_name`, `symbol_type`       |
| Embedding at mine     | one chunk at a time   | batches of 128                     |
| Storage backend       | ChromaDB              | LanceDB (Rust / Arrow)             |
| Bulk delete wing      | none                  | `delete_wing()`                    |
| Mine progress         | silent                | per-file + per-batch progress      |
| Model choice          | hard-coded            | configurable + benchmark-gated     |
| Diary from CLI        | MCP only              | `mempalace diary write`            |
| `status` aggregations | `limit=10000`         | PyArrow `group_by`, full coverage  |

## The Net Effect

Taken together, these changes produce two concrete outcomes:

1. **Searching for "how does X work" finds the X function itself**, not a random paragraph nearby.
2. **Mining a large monorepo takes minutes, not hours**, and does not corrupt the index if you hit `Ctrl+C`.
