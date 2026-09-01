# How mempalace-code Search Works

mempalace-code does **semantic vector search** — it finds content by *meaning*, not keywords. You can search `"how does authorization work"` and find a file that never uses the word "authorization" but defines `login()` and handles `session` tokens.

## The Algorithm in 5 Steps

1. **During mining** (`mempalace-code mine`), every source file is split into chunks. Each chunk is passed through the `all-MiniLM-L6-v2` model, which converts the text into a **384-dimensional vector** — a numeric fingerprint of its meaning. The vector is stored in LanceDB alongside metadata (`wing`, `room`, `source_file`, `language`, `symbol_name`, `symbol_type`). Markdown drawers also store section metadata (`heading`, `heading_level`, `heading_path`, `doc_section_type`) and flags for Mermaid diagrams, fenced code blocks, and tables.

2. **At query time**, the query string (e.g. `"detect language file extension"`) goes through the same model and produces another 384-dimensional vector in the same semantic space.

3. **LanceDB computes cosine distance** between the query vector and every stored vector. Vectors that are close in direction represent similar meanings. An ANN (Approximate Nearest Neighbor) index is used so the search runs in milliseconds even over tens of thousands of rows — it does not brute-force every row.

4. **Optional `wing` / `room` filters** are applied as standard SQL `WHERE` predicates. LanceDB decides whether to pre-filter before the vector search or post-filter after it.

5. **Top-N results are returned** with a `similarity = 1 - distance` score (1.0 = perfect match, 0.0 = unrelated). Programmatic search returns the stored metadata with each hit so agents can cite the file, symbol, language, and Markdown section path when available. Code search also has a deterministic rerank pass for .NET project-file and CamelCase symbol-intent queries, plus an optional `rerank="hybrid"` mode that applies BM25-style token overlap over the retrieved candidate pool.

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

- **The model runs locally after setup.** `mempalace-code init` or `mempalace-code fetch-model` downloads the canonical 384d MiniLM ONNX artifact once. Indexing and search use CPU FastEmbed with normalized vectors and validate immutable provenance under `$HF_HOME/mempalace-fastembed/all-MiniLM-L6-v2-v1/` before cached offline loading.
- **Model context window is 256 tokens (~1000 characters).** Chunks larger than that get their tail silently truncated. This is why `miner.py` does *smart chunking*: it cuts on structural boundaries (`def`, `class`) and targets 400–2500 characters per chunk.
- **Cosine distance, not Euclidean.** Vectors are normalized — what matters is direction, not magnitude.
- **The ANN index is approximate.** LanceDB uses IVF-PQ, which trades a tiny amount of recall for a massive speedup. On palaces with ~20k rows, the difference between the ANN search and exact brute force is negligible.
- **Similarity is not a probability.** A score of 0.396 does not mean "40% match". Scores are only comparable *within the same query* — 0.4 beats 0.3 for the same query, but a 0.4 on one query and a 0.4 on another are not the same thing.
- **`wing` / `room` filters are cheap.** They are plain columns in LanceDB, evaluated as SQL predicates.
- **Language filters share the miner catalog.** `code_search(language=...)` validates against the same language labels the miner emits, and the MCP schema hint is generated from that catalog.
- **Some language labels are context-detected, not extension-only.** Kubernetes, Helm, and Ansible are assigned from file content or repository path context (`kind`/`apiVersion`, `Chart.yaml`/`values.yaml`/`templates/`, playbooks/roles/inventory). Helm templates are indexed as raw YAML/Go-template text; Ansible files are indexed statically without Jinja evaluation or inventory resolution.
- **Code-search reranking is bounded and local.** Project-file/symbol-intent queries overfetch a capped candidate pool and then rerank locally. `code_search(rerank="hybrid")` adds token-overlap scoring for cases where exact identifiers or package names matter, without changing embeddings or making network calls.
- **Markdown location survives retrieval.** For `.md` files, `search_memories()` results include `heading`, `heading_level`, `heading_path`, `doc_section_type`, `contains_mermaid`, `contains_code`, and `contains_table` when the drawer came from a headed section.

## What Gets Indexed

`scan_project()` in `miner.py` decides which files are passed to the chunker and embedder.
Files are skipped before any embedding happens if they match:

1. **Built-in hardcoded skips** — `node_modules`, `__pycache__`, `.git`, and similar common
   generated directories; `SKIP_FILENAMES` like `package-lock.json`, `mempalace.yaml`,
   and generated `entities.json`.
2. **App-level scan excludes** — configured in `~/.mempalace/config.json` as
   `scan_skip_dirs`, `scan_skip_files`, and `scan_skip_globs`. These run before the vector
   indexing pipeline and apply equally to `mempalace-code mine` and the auto-watcher.
   Watcher loops reload these rules between scan cycles, so app-level config edits
   apply to subsequent re-mines without a watcher restart.
3. **Gitignore rules** — applied when `respect_gitignore=True` (the default).

Only files in the miner language/readability catalog are scanned by default.
Recognized but structurally simple formats fall back to adaptive line-count
chunks. Unrecognized extensions are skipped by normal scans; an exact
`--include-ignored path/to/file.ext` override can force that one file through
adaptive chunking, but it will not create a first-class language label for
`code_search(language=...)`.

Previously indexed files that now fall under an exclusion rule are **not automatically
removed** from the palace. Run `mempalace-code mine <dir> --full` to force a clean rebuild
that sweeps stale drawers for files no longer discovered by the scanner.

## Taxonomy Filter Validation

Every explicit `wing` and/or `room` filter — CLI `search`/`read`, the Python `search_memories()`/`code_search()`/`read_slice()` APIs, and the MCP `mempalace_search`/`mempalace_code_search`/`mempalace_file_context`/`mempalace_read`/`mempalace_explain_subsystem` tools — is validated against the palace taxonomy *before* any embedding or row retrieval happens. Validation is metadata-only (`count_by_pair("wing", "room")` on a read-only store) and never initializes the embedding model.

- **A valid empty result is still success.** If the requested wing/room scope exists in the taxonomy but the query has no matches, the response is a normal successful empty result (`results: []`, CLI exit status 0) — not an error.
- **An unknown taxonomy filter is different from a valid empty result.** If the supplied wing, room, or wing/room pair does not exist in the taxonomy, retrieval returns a structured validation error instead of running the query:
  - `unknown_wing` — the wing does not exist.
  - `unknown_room` — the room does not exist anywhere in the palace (rooms are validated globally when no wing is supplied).
  - `unknown_wing_room` — the wing and the room both exist individually, but not as that exact pair.

  Every error payload has the shape `{"error": <code>, "filter": <"wing"|"room"|"wing_room">, "value": <supplied value(s)>, "suggestions": [...]}`. The CLI prints the same information to stderr and exits with status 2.
- **Suggestions are bounded and advisory only.** Up to 3 close taxonomy identifiers are ranked by casefolded, punctuation-stripped similarity (so `migrate_openclaw` ranks `migrate-openclaw` highly), but a suggestion is never auto-selected or used to rewrite the request — the `value` in the error payload always matches exactly what was supplied.
- **Validation only runs against a readable, non-empty taxonomy.** A missing palace (nothing on disk yet), a palace whose taxonomy read fails, and a palace that has been initialized but has no wings or rooms mined yet all skip taxonomy validation rather than reporting every supplied filter as unknown — those cases fall through to each surface's existing no-palace/degraded-palace handling, and retrieval proceeds normally (a `--wing` typo against a freshly initialized, never-mined palace returns a valid empty result rather than a validation error).

## Where the Code Lives

- `mempalace_code/searcher.py` — high-level `search()` and `search_memories()` functions.
- `mempalace_code/taxonomy_filters.py` — shared explicit wing/room validation contract used by every retrieval surface.
- `mempalace_code/storage.py` — `LanceStore.query()`, which owns the embedding model, the LanceDB handle, the actual vector search call, and the deterministic project-file/symbol rerank.
- `mempalace_code/retrieval_rerank.py` — deterministic overfetch/rerank for project-file and CamelCase symbol-intent queries.
- `mempalace_code/search_reranker.py` — optional hybrid token-overlap reranker used by `code_search(rerank="hybrid")` and the .NET benchmark comparison.
- `mempalace_code/miner.py` — smart chunker, language detection, symbol extraction, and the batch embedding loop used during `mempalace-code mine`.
- `mempalace_code/config.py` — `MempalaceConfig.scan_skip_dirs/files/globs` properties that expose app-level scan exclusion config.
