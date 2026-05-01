# Changelog

Current command/package names: the CLI is `mempalace-code`, the import package is
`mempalace_code`, and the MCP module is `python -m mempalace_code.mcp_server`.
Older historical entries may mention legacy `mempalace` names that were valid
when those changes landed.

## v1.7.0 — Unreleased

### Added

- Architecture extraction mode: `mempalace-code mine` now emits higher-level KG
  facts for .NET (C#, F#, VB.NET) and Python projects, including pattern, layer,
  namespace, and project membership facts.
- Multi-repo palace sync: `mempalace-code mine-all` now mines multiple initialized
  projects into one palace with one wing per project, explicit `wing:` overrides,
  git-remote/folder wing auto-naming, duplicate-wing rejection before mining, and
  incremental per-repo re-mining by default.
- Release-grade coverage for backup/restore CLI dispatch, storage migration CLI
  passthrough/error handling, Python multi-import dependency extraction,
  devops/config file scanning, benchmark CI gates, watcher rule reloads, and
  tree-sitter detached-comment behavior.

### Changed

- The shipped Python import namespace is `mempalace_code`; docs and generated
  scheduler snippets prefer `mempalace-code` / `python -m mempalace_code` while
  preserving the source-checkout `mempalace.mcp_server` compatibility shim.
- Package metadata now matches the Python 3.11+ support floor.

### Fixed

- Watchers reload `scan_skip_dirs`, `scan_skip_files`, and `scan_skip_globs`
  without restarting `mempalace-code watch`.
- Generated backup/watch scheduler fallbacks no longer reference the legacy
  `python -m mempalace` module path.

## 2026-05-02 · ARCH-EXTRACTION-MODE

Architecture extraction mode: `mempalace-code mine` now runs a post-mining pass
that emits higher-level KG facts for .NET (C#, F#, VB.NET) and Python projects.

### Added

- `mempalace_code/architecture.py` — new module with pattern detection
  (`is_pattern`: Service, Repository, Controller, ViewModel, Factory), layer
  classification (`is_layer`: UI, Business, Data, Infrastructure), namespace
  tagging (`in_namespace`), and project membership (`in_project`).
- `KnowledgeGraph.invalidate_by_source_file` gains an optional `predicates`
  parameter so architecture facts can be refreshed without expiring type
  dependency facts (implements, inherits, depends_on, etc.).
- Architecture config block in `mempalace.yaml` under `architecture:` — supports
  custom `patterns` (name, suffixes, explicit `type_names`) and `layers`
  (name, namespace_globs, type_suffixes, priority). Invalid rule entries are
  silently ignored; the pass continues with built-in defaults.
- KG queries: `entity="Service", direction="incoming"` shows all services;
  `entity="Data", direction="incoming"` shows all data-layer types.

## 2026-05-02 · FUT-MULTI-REPO

Multi-repo palace sync: `mine-all` command mines multiple project directories into one palace with per-repo wing isolation, wing auto-naming from git remote/folder, and incremental per-repo re-mining.

## 2026-05-01 · Recent completed task review

### Added

- `MINE-SCAN-RULES-LIVE-RELOAD`: watcher loops now reload `scan_skip_dirs`,
  `scan_skip_files`, and `scan_skip_globs` between scan cycles, so app-level
  exclude changes take effect without restarting `mempalace-code watch`.
- `QUAL-E2E-REMAINING-MODULES`: end-to-end coverage now includes `convo_miner`,
  `layers`, and `palace_graph` scenarios, including idempotent conversation
  re-mining, tiered context loading, tunnel detection, traversal, and missing-room
  boundary behavior.

### Changed

- `CLEAN-ONBOARDING`: `mempalace-code init` is config-file-first by default;
  interactive guided setup is routed through explicit onboarding paths instead
  of blocking the normal init flow.
- The shipped Python import namespace is now `mempalace_code`. Packaged
  `mempalace-code` installs no longer claim the top-level `mempalace` module,
  allowing same-environment coexistence with upstream/vanilla MemPalace.
- New MCP setup examples use `python -m mempalace_code.mcp_server`. Source
  checkouts keep a minimal `mempalace.mcp_server` shim so older repo-local
  Codex/Autopilot configs with checkout `PYTHONPATH` continue to start.

### Fixed

- `MINE-SCAN-GLOB-DIR-PRUNE`: glob rules that cover an entire generated
  directory now prune that subtree during the walk instead of filtering only
  after file discovery.
- Legacy hook fallbacks and active docs now call `mempalace-code` or
  `python -m mempalace_code`, matching the renamed package.

## 2026-05-01 · MINE-APP-SCAN-EXCLUDES-PR4

App-level scan excludes (`scan_skip_dirs`, `scan_skip_files`, `scan_skip_globs`) implemented in miner and watcher with hardened, tested outputs.

## v1.6.2 — 2026-05-01

### Added

- Shared language catalog for miner detection, `code_search` validation, and MCP language hints.
- `code_search(language=...)` now accepts Kotlin, XML project files, and Perl shebang-detected files, matching mined language labels from the catalog.

### Changed

- The `mempalace_code_search` MCP language description is generated from the same catalog used by search validation, reducing future drift when language support changes.
- PR #4's scan-exclude proposal is split into backlog item `MINE-APP-SCAN-EXCLUDES-PR4` instead of being merged with the catalog refactor.

## v1.6.1 — 2026-04-30

### Added

- Markdown section metadata in mined drawers: heading, heading level, heading path, document section type, and flags for Mermaid diagrams, fenced code blocks, and Markdown tables.
- `search_memories` now returns Markdown section context with each result when available.

### Changed

- Markdown prose chunking treats `#` through `######` headings as section boundaries and preserves section metadata through small-section merges and oversized-section splits.

## v1.6.0 — 2026-04-27

### Added

- Code retrieval benchmark for mempalace itself, with dataset validation and malformed-dataset hardening.
- .NET benchmark release pin: `jasontaylordev/CleanArchitecture` `v7.0.0` at `5a600ab8749c110384bc3bd436b9c67f3067b489`; current baseline is R@5 0.600 / R@10 0.850.

### Changed

- Code mining cleanup defaults: entity detection is opt-in during init, spellcheck is disabled by default for code mining, and emotional extraction is opt-in for conversation mining.
- Search and health paths avoid unnecessary LanceDB vector-column materialization and return full `source_file` paths consistently.
- README and install docs now document `--detect-entities`, its sampling limits, output file, and code-repo caveats.

### Fixed

- ChromaDB count fallbacks for status/taxonomy views.
- Kubernetes YAML separator handling inside block scalars.
- C# expression-bodied property extraction, Java package-private method extraction, Swift distributed actor detection, HCL block boundaries, and JSX/TSX language filters.
- Architecture MCP reference coverage and `extract_reusable` glue classification.

## 2026-04-26 · EXTRACT-REUSABLE-REFERENCES-PROJECT-GLUE

Promote extract_reusable entities to glue when they reference platform projects.

## 2026-04-26 · ARCH-REF-COVERAGE

Add find_references coverage for depended_by and referenced_by relationship categories.

## 2026-04-26 · HEALTH-SCAN-PROJECTION

Use projected metadata scans for health check and recovery probes to avoid vector-column materialization.

## 2026-04-26 · STORE-SEARCH-SOURCE-FILE-FULL-PATH

Return full source_file paths from search_memories to match code_search.

## 2026-04-26 · MINE-LANCE-VECTOR-SCAN

Harden LanceStore metadata scans to avoid vector-column materialization.

## 2026-04-25 · STORE-CHROMA-COUNTBY-FALLBACK

Add ChromaDB count fallbacks so wings, rooms, taxonomy, and status reflect existing drawers.

## 2026-04-25 · TEST-STORAGE-EDGE

Add LanceStore edge-case tests for empty ID lookups and SQL filter operators.

## 2026-04-25 · MINE-K8S-YAML-SEPARATOR

Keep Kubernetes YAML document separators inside block scalar values from splitting manifest chunks.

## 2026-04-25 · CLEAN-EMOTION-EXTRACT

Remove emotional memories from default general extraction while keeping them opt-in for conversation mining.

## 2026-04-25 · CLEAN-SPELLCHECK

Disable spellcheck by default for code mining while keeping conversation mining spellcheck enabled.

## 2026-04-25 · CLEAN-ENTITY-DETECT

Make heuristic people/project detection opt-in during init.

## 2026-04-25 · STORAGE-BACKUP-RETENTION

Prune pre-optimize backup archives according to configurable retention settings.

## 2026-04-25 · MINE-K8S-LARGE-DOC

Propagate Kubernetes manifest symbol metadata across large-document sub-chunks.

## 2026-04-24 · MINE-SWIFT-DISTRIBUTED

Detect Swift distributed actors as mining boundaries and symbols.

## 2026-04-24 · MINE-CSHARP-EXPR-BODY

Detect C# expression-bodied properties as mining boundaries and symbols.

## 2026-04-24 · MINE-JAVA-PKG-PRIVATE-METHODS

Extract package-private Java methods during symbol extraction.

## 2026-04-24 · CODE-SEARCH-LANG-JSX-TSX

Add jsx and tsx code_search language filters for React and TypeScript projects.

## 2026-04-24 · MINE-HCL-BOUNDARY-MODERN

Add Terraform 1.1+ HCL block boundaries for moved, import, check, and removed.

## v1.5.0 — 2026-04-21

### Added

- **5 new languages in the code miner:**
  - **Dart** — classes, mixins, extensions, enums, functions; named/factory constructors, async/await (MINE-DART)
  - **Scala** — classes, case classes, objects, traits, enums, functions; implicits, type aliases, generics, access modifiers (MINE-SCALA)
  - **Kubernetes manifests** — Deployments, Services, ConfigMaps, Secrets, Ingresses, CRDs from `.yaml`/`.yml`, indexed by kind, namespace, name, labels (MINE-K8S)
  - **PHP** — classes, interfaces, traits, enums (PHP 8.1+), functions, methods, namespaces; Laravel / WordPress / Symfony project recognition (MINE-PHP)
  - **Swift** — classes, structs, enums, protocols, functions, properties, extensions, actors, async/await (MINE-SWIFT)
- **2 new MCP tools:**
  - `mempalace_mine` — agents can trigger incremental or full project re-mining without CLI access; returns structured counts of files processed and drawers filed (MCP-MINE-TRIGGER)
  - `mempalace_file_context` — returns all indexed chunks for a specific source file, ordered by `chunk_index`; useful for reviewing what was mined, handling deleted/renamed files, or getting ordered file context without reading from disk (MCP-FILE-CONTEXT)

### Changed

- **LLM usage rules rewritten as LLM-agnostic** — `docs/LLM_USAGE_RULES.md` now targets any MCP-capable agent (Claude Code, Codex, Cursor, Windsurf, Continue, Zed, Aider, …); routing table maps 16 common tasks to the right specialist tool; `MEMPALACE_AGENT_NAME` env var for diary attribution; extended Never list covering destructive-delete guards, diary non-authoritativeness, and absence-from-search-miss; correction recipe added. `docs/AGENT_INSTALL.md` §7.3 synced. README's misleading "AI learns the protocol automatically" claim replaced with a concrete pointer to the usage rules. (LLM-USAGE-RULES)

## v1.4.1 — 2026-04-20

### Changed
- **Docs: hooks are legacy** — MCP tools + usage rules are now the recommended approach for all agents (Claude Code, Codex, Cursor); hooks demoted to optional Claude Code-only extra
- **Docs: unified saving story** — README, AGENT_INSTALL, and hooks README all consistently describe watcher for code mining + MCP for conversation context

## v1.4.0 — 2026-04-19

### Added
- **Watcher quiet mode** — re-mines suppress verbose output; only logs a one-line summary when drawers are actually filed; no-op commits produce zero log noise; optimize skipped on empty batches
- **Per-project `bin/` skip** — `bin/` no longer globally skipped; only excluded when .NET project markers (`.csproj`, `.sln`, `.fsproj`, `.vbproj`) are present (MINE-BIN-SKIP-DIRS)
- **Kotlin nested generic receiver** — `fun <T> List<Pair<K,V>>.ext()` now parsed correctly (MINE-KOTLIN-GENERIC-RECEIVER-NESTED)
- `mine()` now returns stats dict (`files_processed`, `drawers_filed`, `elapsed_secs`)

### Fixed
- **Watcher on-commit detection** — `watchfiles.DefaultFilter` ignores `.git/` by default; on-commit mode now passes `watch_filter=None` so `.git/refs/heads/` changes are detected
- **Watcher log buffering** — flush Python stdout/stderr before restoring file descriptors to prevent mine() output leaking to real stdout
- **HuggingFace/safetensors noise** — suppress BertModel LOAD REPORT and progress bars via OS fd-level redirect during model init

## v1.3.0 — 2026-04-19

First-class C#/.NET support — delivers [rergards/mempalace-code#1](https://github.com/rergards/mempalace-code/issues/1) in full.

### Added
- **C# structural mining** — parse `.cs` files by namespace, class, interface, enum, record, method, property, event; partial class support, XML doc preservation (MINE-CSHARP)
- **.NET solution/project awareness** — `.sln` and `.csproj` parsing with project references, package references, target frameworks; queryable via KG (MINE-DOTNET)
- **F#, VB.NET, XAML mining** — `.fs`/`.fsi`, `.vb`, `.xaml` with structured symbol extraction and code-behind linking (MINE-DOTNET, MINE-XAML, MINE-XAML-NAME-ATTR)
- **Cross-project symbol relationships** — interface implementations, inheritance, type usage stored as KG triples (DOTNET-SYMBOL-GRAPH)
- **C# multi-line base-type declarations** — `class Foo :\n    IBar, IBaz` now parsed correctly (DOTNET-CS-MULTILINE-BASE)
- **6 architecture MCP tools** — `find_implementations`, `find_references`, `show_project_graph`, `show_type_dependencies`, `explain_subsystem`, `extract_reusable` (MCP-ARCH-TOOLS, ARCH-RETRIEVAL, LOGIC-EXTRACTION)
- **Python type extraction to KG** — class inheritance and ABC/Protocol implementations (PY-TYPE-KG)
- **`mine-all` command** — batch mine all projects in a parent directory (MINE-MULTI)
- **`--watch` flag** — auto-incremental re-mining on file changes via watchdog (MINE-WATCH)
- **Auto-organize by .NET structure** — `.sln` creates wing, `.csproj` maps to room (REPO-STRUCTURE-DEFAULTS)
- **.NET benchmark suite** — 20-query R@5/R@10 benchmark targeting CleanArchitecture (BENCH-DOTNET)

### Fixed
- `find_implementations` now includes Python ABC/Protocol subclasses (FIND-IMPL-INHERITS)
- `.gitignore` patterns respected in `--watch` mode (MINE-WATCH-GITIGNORE-CACHE)

### Stats
- 27 MCP tools (was 18)
- 1002 tests (was 527)

## 2026-04-19 · REPO-STRUCTURE-DEFAULTS

Auto-organize wings/rooms by .NET solution/project structure: mining a repo with `.sln` files now creates a wing named after the solution and maps each `.csproj` to a room, using KG project info for defaults and supporting configurable folder-based room detection.

## 2026-04-18 · FIND-IMPL-INHERITS

Fix `mempalace_find_implementations` to include Python ABC/Protocol subclasses: when the queried interface is itself abstract (has an outgoing `implements → ABC/ABCMeta/Protocol` edge), incoming `inherits` triples are now included alongside `implements` triples, so concrete subclasses are returned instead of an empty list.

## 2026-04-18 · MINE-WATCH

Add `--watch` flag to `mempalace mine` for auto-incremental re-indexing: uses `watchdog` to monitor file changes, debounces updates (5s), and only re-indexes modified files — keeping the palace in sync automatically with low CPU overhead when idle.

## 2026-04-18 · PY-TYPE-KG

Add Python type extraction to the knowledge graph in `miner.py`: class inheritance (`class Foo(Bar)` → `extends` triple) and ABC/Protocol implementations are now extracted for Python codebases, making architecture retrieval tools (`find_implementations`, `find_references`, `show_type_dependencies`, `extract_reusable`) functional for Python projects.

## 2026-04-18 · MINE-MULTI

Add `mempalace mine-all <parent-dir>` command for batch multi-project mining: scans immediate subdirectories for project markers (`.git`, `pyproject.toml`, `package.json`, `*.sln`, `go.mod`, `Cargo.toml`, `go.sum`), mines each detected project into its own wing, and reports per-project results with a summary table.

## 2026-04-18 · LOGIC-EXTRACTION

Add `mempalace_extract_reusable` MCP tool: classifies transitive dependencies of a symbol/subsystem as core, platform-specific, or glue, and identifies the minimal public interface needed for safe extraction.

## 2026-04-18 · ARCH-RETRIEVAL

Add `mempalace_explain_subsystem` MCP tool: combines semantic search with KG traversal to answer "how does this subsystem work?" queries, returning entry points, extracted symbols, and expanded relationships.

## 2026-04-18 · MCP-ARCH-TOOLS

Add 4 architecture-oriented MCP tools for .NET type analysis: `mempalace_find_implementations`, `mempalace_find_references`, `mempalace_show_project_graph`, and `mempalace_show_type_dependencies`.

## 2026-04-17 · SKILLS-HOOKS

Add Claude Code skills and hooks from wh40k workflow: 12 skills (`/start`, `/status`, `/verify`, `/palace-health`, `/task-plan`, `/task-hardening`, `/doc-refresh`, `/ship`, `/release`, `/entropy-gc`, `/mine`, `/bench`), 3 shared modules (mode-classification, task-state, commit-checkpoint), Codex review integration, pre-commit verification gate, and edit logging hooks.

## 2026-04-17 · BENCH-DOTNET

Add .NET benchmark suite: `benchmarks/dotnet_bench.py` measures R@5/R@10 retrieval quality on C#/.NET repositories, validates symbol extraction accuracy, and reports embedding/query timing. Integrated with CI for regression detection.

## 2026-04-17 · MINE-XAML

Add XAML and WPF code-behind linking support: `.xaml` files are mined with control hierarchy extraction; `x:Name` references link to code-behind `.xaml.cs` files via KG triples; resource dictionaries and style references are indexed.

## 2026-04-17 · DOTNET-SYMBOL-GRAPH

Cross-project symbol relationships via KG: interface implementations, inheritance, and type usage references are now detected during .NET mining and stored as KG triples, enabling `mempalace_kg_query` to surface all implementers or subclasses of a given type across projects.

## 2026-04-17 · MINE-DOTNET

Add .NET ecosystem support to code miner: F# (`.fs`, `.fsi`), VB.NET (`.vb`), project files (`.csproj`, `.fsproj`, `.vbproj`), and solution files (`.sln`) are now mined with structured symbol extraction and KG triples for project dependencies, package references, and solution structure.

## 2026-04-17 · MINE-CSHARP

Add C# language support to code miner: `.cs` files are now mined with structured symbol extraction for classes, interfaces, structs, enums, records, methods, properties, fields, constructors, and events; namespaces, partial classes, attributes, XML doc comments, and nested types with generic constraints are handled correctly.

## 2026-04-17 · MINE-KOTLIN

Add Kotlin language support to code miner: `.kt` and `.kts` files are now mined with structured symbol extraction for classes, objects, interfaces, functions, properties, data classes, sealed classes, enums, companion objects, extension functions, and coroutine/DSL constructs.

## 2026-04-17 · MINE-JAVA-SMART

Add smart symbol extraction for Java: classes, interfaces, enums, records, methods, fields, and annotations are now extracted as structured drawers instead of plain chunks; generics, inner classes, and annotation types are handled correctly.

## 2026-04-17 · CODE-SEARCH-LANG-PROSE

Add markdown, text, and csv to `SUPPORTED_LANGUAGES` so `code_search(language="markdown"|"text"|"csv")` validates and filters correctly instead of returning an error.

## 2026-04-16 · STORAGE-AUTO-BACKUP

Auto-backup palace before risky operations: `safe_optimize` triggers a backup by default, `backup list` and `backup schedule` subcommands added, and `auto_backup_before_optimize` is enabled out-of-the-box.

## 2026-04-16 · FIX-LANCE-CORRUPT

Detect and recover from missing LanceDB fragment files: `safe_open_table` probes the table with a count query on open and rolls back to the last clean version automatically when fragment corruption is detected.

## 2026-04-14 · MINE-DEVOPS-INFRA

Add DevOps/infrastructure file support to the miner: Terraform (`.tf`, `.tfvars`, `.hcl`), Dockerfiles, Makefiles, Helm templates (`.tpl`), Ansible Jinja2 templates (`.j2`, `.jinja2`), and general config files (`.conf`, `.cfg`, `.ini`) are now scanned and indexed.

## 2026-04-14 · STORE-CHROMA-DELETE-WING-LIMIT

`ChromaStore.delete_wing` now calls `self.get()` instead of `self._col.get()`, so the `limit=10000` wrapper applies. Wings with more drawers than ChromaDB's default page size were silently partially deleted. (ChromaDB is deprecated; cleanup only.)

## 2026-04-14 · STORE-REMOVE-CHROMA-DEFAULT

ChromaStore isolated into `mempalace/_chroma_store.py` with lazy import — ChromaDB is no longer imported unless `.[chroma]` is installed and explicitly selected. Reduces default import time and dependency surface.

## 2026-04-14 · STORE-WHERE-ARROW-OPS

`_where_to_arrow_mask` now handles operator dicts (`$gt`, `$gte`, `$lt`, `$lte`, `$ne`, `$in`) in LanceDB filter translation. Previously only equality filters were supported; comparison and set-membership queries silently returned incorrect results.

## 2026-04-14 · CODE-SEARCH-LANG-CPP

C/C++ language support: `.c`, `.h`, `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hxx` extensions recognized by the miner with struct/enum/union/typedef/function symbol extraction for C and class/struct/enum/function extraction for C++. `code_search(language="c")` and `code_search(language="cpp")` now work.

## 2026-04-14 · CODE-SEARCH-LANG-CONFIG

`yaml`, `json`, and `toml` added to `SUPPORTED_LANGUAGES` in searcher.py so `code_search(language="yaml")` etc. return results. These file types were already mined but not filterable by language.

## 2026-04-14 · CODE-SYMBOL-META-GO-TYPES

Go symbol extraction now captures scalar types (`type Foo int`), function types (`type Handler func(...)`), and type aliases (`type ID = string`) in addition to struct/interface/func declarations.

## 2026-04-14 · MINE-EAGER-EMBED-INIT

Embedding model is now loaded eagerly during `MinerConfig` init instead of lazily on first chunk. Prevents a multi-second stall mid-mining when the model loads for the first time.

## 2026-04-14 · CODE-SMART-CHUNK-VAR-BOUNDARY

Non-exported `var` and `let`/`const` declarations at module scope added to `TS_BOUNDARY`, so top-level JS/TS variable declarations start a new chunk instead of being merged into the preceding function.

## 2026-04-14 · LANG-DETECT-GO-VAR-BODY

Removed `var\s+\w+` from `GO_BOUNDARY` — it was matching `var` declarations inside function bodies, causing mid-function chunk splits. Go var blocks are now only boundaries at the package level via `var (` syntax.

## 2026-04-14 · LANG-DETECT-NODEJS-SHEBANG

`detect_language` now recognizes `#!/usr/bin/env node` and similar Node.js shebangs, mapping them to `javascript`. Previously, Node.js scripts without a `.js` extension were classified as unknown.

## 2026-04-14 · CODE-TREESITTER-TS

Tree-sitter AST-aware TypeScript/JavaScript/TSX/JSX chunking: extracts function/class/method/export/import boundaries from the AST; falls back to regex when tree-sitter grammars are unavailable.

## 2026-04-14 · STORE-BACKUP-RESTORE

Add `mempalace backup` and `mempalace restore` CLI commands: backup creates a .tar.gz of the LanceDB lance/ directory plus knowledge_graph.db and a metadata.json (drawer count, wing list, timestamp, version, backend); restore extracts into the palace path with an optional --force flag to overwrite.

## 2026-04-14 · CODE-TREESITTER-EXPAND

Tree-sitter AST-aware Go and Rust chunking: extracts func/type/var/const boundaries for Go and fn/struct/enum/trait/impl/mod boundaries for Rust; falls back to regex when grammars are unavailable.

## 2026-04-14 · CODE-TREESITTER-PYTHON

Tree-sitter AST-aware Python chunking: extracts function/class/method boundaries from `function_definition`, `class_definition`, and `decorated_definition` nodes; falls back to regex when py-tree-sitter is unavailable.

## 2026-04-14 · CODE-TREESITTER-INFRA

Tree-sitter optional infra: `.[treesitter]` extra, grammar download/cache, parser init, and automatic regex fallback when py-tree-sitter is absent or grammar unavailable.

## v1.0.0 — 2026-04-12

First public release of **mempalace-code**, a code-first fork of
[milla-jovovich/mempalace](https://github.com/milla-jovovich/mempalace).

### Storage — LanceDB rewrite

- **LanceDB backend** replaces ChromaDB as the default. Crash-safe columnar Arrow storage, no server required.
- **Automatic schema migration** — palaces created by older versions are upgraded transparently on open. No manual migration commands needed.
- **NULL-safe migration defaults** — `CAST('' AS string)` prevents null corruption in existing rows during schema evolution.
- **Table handle reload** after migration — fixes "missing fields" error on multi-drawer writes to migrated palaces.
- ChromaDB retained as optional `[chroma]` extra (deprecated).

### Code mining

- **Language-aware structural chunking** — Python, TypeScript/JavaScript, Go, Markdown. Splits at function/class/type boundaries, not arbitrary line counts.
- **Language detection** — file extension + shebang + content heuristics. 20+ languages recognized.
- **Symbol metadata extraction** — `symbol_name`, `symbol_type`, `language` on every chunk. Enables code-search filtering.
- **Incremental re-mining** — content-hash based. Only changed files are re-chunked. `--full` flag forces rebuild.
- **Batch embedding with upsert** — deduplicates on write, idempotent re-mines. Batched writes reduce LanceDB overhead on large projects.

### MCP tools (18 tools)

- **`mempalace_code_search`** — filter by language, symbol name/type, file glob. Returns symbol metadata.
- **`mempalace_add_drawer`** — now writes `chunker_strategy: "manual_v1"` provenance for backup/restore filtering.
- **`mempalace_delete_wing`** — delete all drawers in a wing.
- AAAK dialect tool removed from default MCP exposure (code preserved, dormant).

### Export / Import

- **`mempalace export`** — JSONL dump with `--only-manual` filter (preserves drawers the miner can't regenerate).
- **`mempalace import`** — restore from JSONL with dedup, dry-run, wing override.
- Streaming via `iter_all()` — no full-table memory load.

### CLI

- **`mempalace init`** — downloads embedding model (~80 MB) explicitly during setup.
- **`mempalace fetch-model`** — pre-download the model for offline use.
- **`mempalace mine --full`** — force full rebuild instead of incremental.
- **`mempalace export / import`** — backup and restore commands.
- **`mempalace diary write / read`** — agent session journals.

### Knowledge graph

- Temporal entity-relationship triples in local SQLite.
- `kg_add`, `kg_query`, `kg_invalidate`, `kg_timeline`, `kg_stats` — all via MCP.

### Quality

- **419 tests** across 15 test files. Every feature acceptance-gated.
- Schema migration regression tests (multi-write, NULL safety, partial migration).
- Storage edge-case tests ($in operator, empty IDs, comparison operators).
- Export/import round-trip tests with dedup verification.

### Docs

- `docs/AGENT_INSTALL.md` — decision-tree runbook for agent-driven installation.
- `docs/UPSTREAM_HARDENING.md` — full audit of upstream claims vs fork status.
- `docs/BACKUP_RESTORE.md` — backup workflow for manual drawers.
- `docs/OFFLINE_USAGE.md` — offline operation guide.
- `docs/STORAGE.md` — automatic schema migration documentation.
- `benchmarks/BENCHMARKS.md` — methodology caveats for upstream benchmark numbers.

### Upstream issues addressed

- [#469](https://github.com/milla-jovovich/mempalace/issues/469) — ChromaDB version-cliff data deletion → LanceDB, no version-cliff risk.
- [#524](https://github.com/milla-jovovich/mempalace/issues/524) — Silent ONNX model download → explicit `mempalace init` + `fetch-model`.
- [#27](https://github.com/milla-jovovich/mempalace/issues/27) — Unverifiable 100% R@5 claim → removed. AAAK "lossless" claim → labeled lossy.

### License

Changed from MIT to Apache 2.0 for trademark protection and attribution requirements.
