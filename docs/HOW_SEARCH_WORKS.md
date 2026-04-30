# How mempalace-code Search Works

mempalace-code does **semantic vector search** — it finds content by *meaning*, not keywords. You can search `"how does authorization work"` and find a file that never uses the word "authorization" but defines `login()` and handles `session` tokens.

## The Algorithm in 5 Steps

1. **During mining** (`mempalace mine`), every source file is split into chunks. Each chunk is passed through the `all-MiniLM-L6-v2` model, which converts the text into a **384-dimensional vector** — a numeric fingerprint of its meaning. The vector is stored in LanceDB alongside metadata (`wing`, `room`, `source_file`, `language`, `symbol_name`, `symbol_type`). Markdown drawers also store section metadata (`heading`, `heading_level`, `heading_path`, `doc_section_type`) and flags for Mermaid diagrams, fenced code blocks, and tables.

2. **At query time**, the query string (e.g. `"detect language file extension"`) goes through the same model and produces another 384-dimensional vector in the same semantic space.

3. **LanceDB computes cosine distance** between the query vector and every stored vector. Vectors that are close in direction represent similar meanings. An ANN (Approximate Nearest Neighbor) index is used so the search runs in milliseconds even over tens of thousands of rows — it does not brute-force every row.

4. **Optional `wing` / `room` filters** are applied as standard SQL `WHERE` predicates. LanceDB decides whether to pre-filter before the vector search or post-filter after it.

5. **Top-N results are returned** with a `similarity = 1 - distance` score (1.0 = perfect match, 0.0 = unrelated). Programmatic search returns the stored metadata with each hit so agents can cite the file, symbol, language, and Markdown section path when available.

## ASCII Diagram

```
  INDEXING (once, during mine)
  ────────────────────────────
                                                    ┌─────────────────┐
   file.py ──► chunker ──► "def detect_lang(path):  │  all-MiniLM-L6  │
                            ext = path.suffix..."──►│  (384-dim model)│
                                                    └────────┬────────┘
                                                             │
                                                    [0.12, -0.48, ..., 0.31]
                                                             │
                                                             ▼
                                           ┌─────────────────────────────┐
                                           │          LanceDB            │
                                           │  ┌───────┬──────┬────────┐  │
                                           │  │vector │ wing │ room   │  │
                                           │  ├───────┼──────┼────────┤  │
                                           │  │ [..]  │memp..│miner   │  │
                                           │  │ [..]  │auto..│cmd     │  │
                                           │  │ [..]  │wh40..│frontend│  │
                                           │  └───────┴──────┴────────┘  │
                                           └─────────────────────────────┘


  QUERY (every search)
  ────────────────────
                                                    ┌─────────────────┐
   "detect language by extension"  ────────────────►│  all-MiniLM-L6  │
                                                    └────────┬────────┘
                                                             │
                                                    [0.15, -0.44, ..., 0.29]   ← query vector
                                                             │
                                                             ▼
                                           ┌─────────────────────────────┐
                                           │   LanceDB ANN search        │
                                           │                             │
                                           │   WHERE wing = 'mempalace'  │  ← filter
                                           │   ORDER BY cosine_dist(v,q) │  ← ranking
                                           │   LIMIT 5                   │  ← top-N
                                           └────────────┬────────────────┘
                                                        │
                                                        ▼
                                    ┌──────────────────────────────────────┐
                                    │ [1] mempalace / miner                │
                                    │     source: miner.py   sim: 0.396    │
                                    │     def detect_language(path): ...   │
                                    │                                      │
                                    │ [2] mempalace / language_catalog     │
                                    │     source: language_catalog.py       │
                                    │     sim: 0.351                        │
                                    │     _EXTENSION_LANG_MAP = { ... }     │
                                    │                                      │
                                    │ [3] ...                              │
                                    └──────────────────────────────────────┘
```

## Key Details

- **The model runs locally.** No API keys, no network — everything happens on CPU/GPU on the host machine.
- **Model context window is 256 tokens (~1000 characters).** Chunks larger than that get their tail silently truncated. This is why `miner.py` does *smart chunking*: it cuts on structural boundaries (`def`, `class`) and targets 400–2500 characters per chunk.
- **Cosine distance, not Euclidean.** Vectors are normalized — what matters is direction, not magnitude.
- **The ANN index is approximate.** LanceDB uses IVF-PQ, which trades a tiny amount of recall for a massive speedup. On palaces with ~20k rows, the difference between the ANN search and exact brute force is negligible.
- **Similarity is not a probability.** A score of 0.396 does not mean "40% match". Scores are only comparable *within the same query* — 0.4 beats 0.3 for the same query, but a 0.4 on one query and a 0.4 on another are not the same thing.
- **`wing` / `room` filters are cheap.** They are plain columns in LanceDB, evaluated as SQL predicates.
- **Language filters share the miner catalog.** `code_search(language=...)` validates against the same language labels the miner emits, and the MCP schema hint is generated from that catalog.
- **Markdown location survives retrieval.** For `.md` files, `search_memories()` results include `heading`, `heading_level`, `heading_path`, `doc_section_type`, `contains_mermaid`, `contains_code`, and `contains_table` when the drawer came from a headed section.

## Where the Code Lives

- `mempalace/searcher.py` — high-level `search()` and `search_memories()` functions.
- `mempalace/storage.py` — `LanceStore.query()`, which owns the embedding model, the LanceDB handle, and the actual vector search call.
- `mempalace/miner.py` — smart chunker, language detection, symbol extraction, and the batch embedding loop used during `mempalace mine`.
