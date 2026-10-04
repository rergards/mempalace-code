# How mempalace-code Search Works

mempalace-code does **semantic vector search** — it finds content by *meaning*, not keywords. You can search `"how does authorization work"` and find a file that never uses the word "authorization" but defines `login()` and handles `session` tokens.

## The Algorithm in 5 Steps

1. **During mining** (`mempalace-code mine`), every source file is split into chunks. Each chunk is passed through the `all-MiniLM-L6-v2` model, which converts the text into a **384-dimensional vector** — a numeric fingerprint of its meaning. The vector is stored in LanceDB alongside metadata (`wing`, `room`, `source_file`, `language`, `symbol_name`, `symbol_type`). Markdown drawers also store section metadata (`heading`, `heading_level`, `heading_path`, `doc_section_type`) and flags for Mermaid diagrams, fenced code blocks, and tables.

2. **At query time**, the query string (e.g. `"detect language file extension"`) goes through the same model and produces another 384-dimensional vector in the same semantic space.

3. **LanceDB runs an exact nearest-neighbor scan.** MemPalace builds no vector index, so every query is compared with every stored vector that passes the filters, using LanceDB's default metric: squared Euclidean (L2) distance. All vectors are L2-normalized, so that distance equals `2 - 2 × cosine similarity`, and ranking by it is exactly ranking by cosine similarity. Vectors that point in similar directions represent similar meanings. The scan is exact, so it never misses a closer match the way an approximate (ANN) index can; its cost grows linearly with the number of rows scanned.

4. **Optional filters** are applied as standard SQL `WHERE` predicates. MemPalace uses LanceDB's default pre-filtering, so every filter narrows the candidate rows before the vector scan ranks them: `wing` / `room` everywhere, and `language`, `symbol_type`, `symbol_name`, and `file_glob` in `code_search`. `symbol_name` (case-insensitive substring) and `file_glob` (`fnmatch` against the stored path; a glob that does not start with `/` or `*` also matches the end of the stored path at a `/` boundary, so repo-relative globs such as `src/*.py` or `storage.py` work) are resolved first with a metadata-only scan of the distinct stored symbol names or paths, then applied as an `IN` predicate, so a filter finds every matching chunk however far down the vector ranking it sits. A filter that matches nothing returns an empty result without a vector query.

5. **Top-N results are returned** with a `similarity` score: the cosine similarity between the query and the chunk, computed from the distance as `1 - distance / 2` and rounded to 3 decimals. It ranges from -1.0 to 1.0: 1.0 is the same direction (identical text), about 0.0 is unrelated, and negative values point in opposite directions. Programmatic search returns the drawer `id` and the stored metadata with each hit so agents can cite the file, symbol, language, line range, and Markdown section path when available, and can pass the `id` to `mempalace_delete_drawer`. CLI `search`, `search_memories()` / `mempalace_search`, and `mempalace_check_duplicate` return hits in descending similarity. Only code search reorders: it has a deterministic rerank pass for .NET project-file and CamelCase symbol-intent queries (so its `similarity` is not always monotonic; `ranking.storage_rank` and `ranking.vector_distance` show the evidence), plus an optional `rerank="hybrid"` mode that applies BM25-style token overlap over the retrieved candidate pool.

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
                                           │   LanceDB exact kNN scan    │
                                           │                             │
                                           │   WHERE wing = 'mempalace'  │  ← filter
                                           │   ORDER BY l2_sq(v,q)       │  ← ranking
                                           │   LIMIT 5                   │  ← top-N
                                           └────────────┬────────────────┘
                                                        │
                                                        ▼
                                    ┌──────────────────────────────────────┐
                                    │ [1] mempalace / miner                │
                                    │     source: languages.py  sim: 0.698 │
                                    │     def detect_language(path): ...   │
                                    │                                      │
                                    │ [2] mempalace / language_catalog     │
                                    │     source: language_catalog.py      │
                                    │     sim: 0.676                       │
                                    │     _EXTENSION_LANG_MAP = { ... }    │
                                    │                                      │
                                    │ [3] ...                              │
                                    └──────────────────────────────────────┘
```

## Key Details

- **The model runs locally after setup.** `mempalace-code init` or `mempalace-code fetch-model` downloads the canonical 384d MiniLM ONNX artifact once. Indexing and search use CPU FastEmbed with normalized vectors and validate immutable provenance under `$HF_HOME/mempalace-fastembed/all-MiniLM-L6-v2-v1/` before cached offline loading.
- **Only the first 256 tokens of a chunk are embedded.** The model's context window is 256 tokens (~1000 characters of prose); anything after that is silently truncated before embedding. The chunker (`mempalace_code/mining/chunkers.py`) cuts on structural boundaries (`def`, `class`, headings) so each drawer is one logical unit: every named declaration, including each method of a class, starts its own drawer (unnamed declarations such as constants under 400 characters together may share one), other content merges up to 2500 characters, and nothing exceeds 4000 — an oversized declaration is split at blank lines, then lines, and a single line longer than 4000 characters is cut into pieces. A chunk longer than the window is still stored and returned verbatim, but only its opening part shapes its vector.
- **Drawers are exact source slices.** Each mined drawer is a contiguous run of source lines stored byte-for-byte (indentation included) with its `line_start`/`line_end`. Small blocks under 100 characters are merged into a neighbouring drawer rather than dropped, so every non-blank line of a mined file can be found by search and returned by `read`. Continuation pieces of a split declaration keep its `symbol_name`; with tree-sitter, top-level code that follows a declaration (a large constant table, an `if __name__` block) is not treated as part of it.
- **Chunker versions trigger a re-chunk.** Drawers record the chunker that produced them (`chunker_strategy`, currently `regex_structural_v3`, `treesitter_v3`, `treesitter_adaptive_v2`, or `dotnet_project_xml_v2`). An incremental mine re-chunks any file whose drawers carry an older strategy, so an upgrade rebuilds old drawers without `--full`.
- **Euclidean distance on normalized vectors, equivalent to cosine.** Because every vector has length 1, only direction matters: the squared L2 distance LanceDB returns and the cosine similarity MemPalace reports rank results identically. `code_search` exposes the raw distance as `ranking.vector_distance`.
- **No approximate index.** Search is a flat, exact scan. MemPalace does not create an IVF-PQ or other ANN index, so there is no recall trade-off to tune.
- **Similarity is not a probability.** A score of 0.7 does not mean "70% match". Scores are only comparable *within the same query* — 0.7 beats 0.6 for the same query, but a 0.7 on one query and a 0.7 on another are not the same thing. The `mempalace_check_duplicate` threshold (default 0.9) uses the same cosine scale.
- **Older releases used a different scale.** Up to v1.14.2, scores were reported as `1 - distance`, which equals `2 × cosine - 1` and was often negative. An old score `s` corresponds to `(s + 1) / 2` on the current scale.
- **`wing` / `room` filters are cheap.** They are plain columns in LanceDB, evaluated as SQL predicates.
- **Language filters share the miner catalog.** `code_search(language=...)` validates against the same language labels the miner emits, and the MCP schema hint is generated from that catalog.
- **Some language labels are context-detected, not extension-only.** Kubernetes, Helm, and Ansible are assigned from file content or repository path context (`kind`/`apiVersion`, `Chart.yaml`/`values.yaml`/`templates/`, playbooks/roles/inventory). Helm templates are indexed as raw YAML/Go-template text; Ansible files are indexed statically without Jinja evaluation or inventory resolution.
- **Code-search reranking is bounded and local.** In `code_search`, project-file/symbol-intent queries overfetch a capped candidate pool and then rerank locally; plain search never applies this pass (`LanceStore.query(intent_rerank=False)`). `code_search(rerank="hybrid")` adds token-overlap scoring for cases where exact identifiers or package names matter, without changing embeddings or making network calls. Hybrid score components are reported rounded to 3 decimals.
- **Result counts are bounded.** CLI `search --results`, `mempalace_search` `limit`, and `code_search` `n_results` accept at most 50 hits: the CLI and MCP reject larger values (MCP with `-32602`), and the Python `search_memories()` / `code_search()` clamp them to 50. A count below 1 is rejected everywhere; the Python functions raise `InvalidArgumentError` (a `ValueError`). Note the argument order: `search_memories(query, palace_path, ...)` but `code_search(palace_path, query, ...)`; pass both by keyword when in doubt (a swapped call returns `No palace found` with a hint naming the order). A hit's `source_file` is `null` (`None`) for a drawer filed without a source, such as a manual or diary drawer. `mempalace-code search --json` prints one JSON object with the same hit shape as `search_memories()`; runtime errors are JSON too (exit 1, or 2 for an unknown wing/room), while argument errors such as `--results 100` exit 2 with the usual usage text on stderr.
- **Markdown location survives retrieval.** For `.md` files, `search_memories()` and `code_search()` results include `heading`, `heading_level`, `heading_path`, `doc_section_type`, `contains_mermaid`, `contains_code`, and `contains_table` when the drawer came from a headed section; hits without section metadata omit these fields. When the miner merges adjacent short sections into one drawer, `heading` and `heading_path` join the merged sections' values with ` | ` in document order and `heading_level` is the shallowest level.

- **MCP search count alias.** `mempalace_search` accepts `max_results` as an alias for
  `limit`, with the same range of 1 to 50 and default of 5. Supply either name.
  If both names are supplied, their values must match; conflicting values return
  JSON-RPC `-32602` before search. For example, `{"query": "storage", "max_results": 3}`
  requests three hits. This alias applies to `mempalace_search`.

## What Gets Indexed

`scan_project()` in `mempalace_code/mining/scanner.py` decides which files are passed to the chunker and embedder.
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

Only files in the miner language/readability catalog are scanned by default, plus
extension-less files whose first line is a shebang naming a known interpreter
(bash/sh/zsh, Python, Node, Ruby, Perl). Recognized but structurally simple formats
fall back to adaptive line-count chunks. Unrecognized extensions are skipped by
normal scans and counted in the mine summary; an exact
`--include-ignored path/to/file.ext` override (project-relative, or an absolute path
inside the project) can force that one file through adaptive chunking, but it will
not create a first-class language label for `code_search(language=...)`.

After discovery, each file is read and classified before chunking:

- **Empty** (whitespace only) files produce no drawers. Every other file is indexed,
  however small — a short config file becomes one drawer.
- **Binary** content (NUL bytes, or mostly undecodable/control characters) is skipped
  even when the extension looks like source.
- **Too large** files, above `max_file_bytes` (1,000,000 bytes by default; set
  `max_file_bytes:` in `mempalace.yaml`, `0` disables the cap), are skipped.
- **Minified or generated** files are skipped: `*.min.js`/`*.min.css`, and script,
  stylesheet, JSON, HTML, or XML files dominated by lines longer than 4,000
  characters. Prose and other source files are never classified this way; a long
  line in them is stored in several drawers that share its line number, and `read`
  joins them back into the whole line.
- **Kubernetes Secret manifests** — YAML with a document that has a top-level
  `kind: Secret` and a `data:` or `stringData:` block — are skipped whole (every
  document in the file), because they hold credentials. No other
  secret-bearing file is detected; exclude those with `.gitignore` or `scan_skip_globs`.
- Text that is not valid UTF-8 is decoded with a declared `coding:` cookie on its
  first two lines when there is one; otherwise undecodable bytes become U+FFFD and
  the file is reported. A UTF-8 byte-order mark is not stored, and a file that starts
  with a UTF-16 or UTF-32 byte-order mark is decoded with that encoding.
- A file over the size cap is recognised after reading at most `max_file_bytes + 1`
  bytes, and change detection hashes files in 1 MiB blocks, so a huge file costs
  little memory to skip.

The mine summary names the skipped files per reason. An exact `--include-ignored`
path overrides the size, minified, and Kubernetes Secret checks (never the binary
check). When a changed file is now skipped for one of these reasons, its next mine removes
its drawers and counts them with the stale removals. Incremental mining keeps unchanged
files without rechecking these content rules. After changing `max_file_bytes`, run
`mempalace-code mine <dir> --full` to recheck unchanged files against the new cap.

Every `mempalace-code mine <dir>` that walks the whole project (no `--limit`) ends with a
stale-file sweep: it removes the drawers of files that were indexed before but are no
longer discovered, whether they were deleted, moved (including every file under a
deleted or renamed directory), replaced by a symlink or other non-regular node, or now
fall under an exclusion rule. The summary reports how many drawers and files it removed.
A plain incremental mine is enough to purge newly excluded files. `--full` runs the same
sweep and also re-chunks and re-embeds every remaining file. The sweep only touches
drawers that this project mined into its wing, and a run with `--limit` never sweeps.
Neither the sweep nor re-mining a changed file deletes manual (`mempalace_add_drawer`)
or diary drawers, even when their `source_file` names a mined file.

A file's room is chosen in this order: the `.csproj` project that contains it (with
`dotnet_structure`), the outermost folder on its path that names a room or keyword (an
exact name before one that only contains it), its
file name, then the room whose name and keywords occur most often in its first 2,000
characters, else `general`. Names are compared as lowercase letter/digit tokens of any
script, so a folder room such as `моды` receives `моды/модуль.py`. A folder room (one `init`
describes as `Files from <dir>/`) receives only files inside a folder whose name equals the
room's name or one of its keywords, at any depth. It is not matched by file names, by folder
names that only contain it, or by the content count, so a root `README.md`, `pyproject.toml`
or `mempalace_notes.md` that names the package does not land in the package's folder room.
A tie in the content count (such as a `.sln` that lists several projects) goes to `general`.

An incremental mine also notices edits to `mempalace.yaml`: when the rooms or the
`architecture:` block change, unchanged files whose room changed are re-filed in their
new room and the architecture pass runs again. A release that changes the routing rules
above triggers the same re-filing on the next mine. `--dry-run` applies the same routing,
skip, and incremental rules as a real run and reports what it would file.

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

## Reading Stored Lines

`mempalace-code read <file> --start N --end N` and `mempalace_read` return lines from
stored chunks only — never from the live file. The file may be given as the stored
path from a search hit, a symlinked or `..`-containing spelling of it (resolved the
same way `mine` resolves project paths: a relative path against the working
directory, then symlinks), or a unique basename/path suffix;
`mempalace_file_context` resolves paths the same way and pages chunks with
`limit`/`offset`.

- **Gaps are explicit.** Chunks are stored without the blank separator lines between
  them, so requested lines that no stored chunk covers are listed in `gaps` (the CLI
  prints a `…` marker) instead of being skipped silently. A gap before
  `first_indexed_line` is lines mining did not store, not blank separators.
- **The range is clamped.** `end` never goes past `last_indexed_line`; a `start`
  after it is `out_of_range` with that line number.
- **Some drawers have no lines.** Conversation drawers, and chunks the miner could
  not map to exact source lines, carry no line range: a file with only such drawers
  returns `no_line_metadata` (with `conversation: true` for transcripts). A partly
  mapped file reports `unplaced_chunks` on both a successful read and an
  `out_of_range` error, because the content after `last_indexed_line` may be stored
  in those chunks. Use search or `mempalace_file_context` for their text.
- **A palace read failure is not a missing file.** When the store itself cannot be
  read, `read` and `mempalace_file_context` return `store_error` with the storage
  error as `detail`; the CLI and MCP name `health` and `repair --rollback --dry-run`
  as the next step.

## Where the Code Lives

- `mempalace_code/searcher.py` — high-level `search()`, `search_memories()`, and `code_search()` functions and the shared hit projection.
- `mempalace_code/reader.py` — stored-line reads behind `mempalace-code read` / `mempalace_read` and path resolution for `mempalace_file_context`.
- `mempalace_code/taxonomy_filters.py` — shared explicit wing/room validation contract used by every retrieval surface.
- `mempalace_code/storage.py` — `LanceStore.query()`, which owns the embedding model, the LanceDB handle, the actual vector search call, and the deterministic project-file/symbol rerank; `distance_to_similarity()` is the one conversion from a returned distance to the reported cosine similarity.
- `mempalace_code/retrieval_rerank.py` — deterministic overfetch/rerank for project-file and CamelCase symbol-intent queries.
- `mempalace_code/search_reranker.py` — optional hybrid token-overlap reranker used by `code_search(rerank="hybrid")` and the .NET benchmark comparison.
- `mempalace_code/mining/` — the project miner behind `mempalace-code mine`: `scanner.py` (file discovery and scan excludes), `chunkers.py` (smart chunking), `languages.py` (language detection), `symbols.py` (symbol extraction), `orchestrator.py` (the mine loop, batch embedding, and stale-file sweep), and `batching.py` (embedding batch size). `mempalace_code/miner.py` is only a compatibility shim that re-exports them.
- `mempalace_code/config.py` — `MempalaceConfig.scan_skip_dirs/files/globs` properties that expose app-level scan exclusion config.
