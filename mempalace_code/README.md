# mempalace_code/ — Core Package

The Python package that powers mempalace-code.

## Modules

| Module | What it does |
|--------|-------------|
| `cli.py` | Thin CLI entry point and compatibility facade |
| `__main__.py` | `python -m mempalace_code` entry point |
| `cli_commands/` | CLI command handlers, one module per command family — ingest (init, onboarding, mine, mine-all, split, status), query (search, read, wake-up, compress), watch, backup/restore, export/import, maintenance (health, cleanup, repair, retired migrate-storage), model, alias, diary, version-check, update, preflight, agent-plugin, and wing-migration |
| `storage.py` | LanceDB drawer store — `open_store`, add/upsert/query/delete, health check, safe optimize, stale-version cleanup, and rollback recovery; legacy ChromaDB palaces fail closed with the recovery command |
| `export.py` | JSONL export/import of drawers and KG triples (`--only-manual`, `--with-kg`, dedup on import) |
| `config.py` | Configuration loading — `~/.mempalace/config.json`, env vars, defaults, scan excludes, disk-budget floors |
| `disk_budget.py` | Shared disk-budget parsing, footprint measurement, and watcher/backup guard checks |
| `backup.py` | Safe palace archives and restore validation — managed-member allowlist, retention kinds, and palace-local KG scoping |
| `mirror_preflight.py` | Pure rsync command inspection for `preflight mirror`; never executes the command |
| `operation_lock.py` | Per-install shared/exclusive operation lease (watchers, MCP servers, mines vs. updates) and the per-palace write lease that serializes mines, watcher cycles, optimize, and cleanup |
| `source_io.py` | Descriptor-validated regular-file reads for ingest sources |
| `language_catalog.py` | Shared language metadata for miner detection, `code_search` validation, and MCP language hints |
| `normalize.py` | Converts 7 chat formats (Claude Code JSONL, Codex CLI JSONL, Gemini CLI JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, plain text) to standard transcript format, keeping message text verbatim |
| `miner.py` | Public mining facade kept for compatibility; implementation lives under `mining/` |
| `treesitter.py` | Optional tree-sitter parser factory; returns no parser when the `[treesitter]` extra or a grammar is missing |
| `architecture.py` | Post-mining architecture pass — pattern, layer, namespace, and project KG facts for .NET and Python types |
| `mining/` | Project file ingest package — scans directories, detects languages, chunks code/prose/config, extracts symbols, batches embeddings, and stores drawers; Markdown chunks keep heading path and section metadata |
| `convo_miner.py` | Conversation ingest — verbatim exchange chunks (every line kept), content-hash incremental re-mine, missing-transcript sweep only on `--full`, rooms per exchange |
| `searcher.py` | Semantic search via LanceDB vectors — filters by wing/room/language/symbol/file glob before ranking, returns verbatim text, drawer ids, scores, and stored metadata such as Markdown heading path |
| `reader.py` | Guarded stored-source reads with palace taxonomy validation, filesystem-equivalent path resolution (symlinks, `..`, macOS `/var`), gap and end-of-content reporting; shared by `read` and `mempalace_file_context` |
| `launchd.py` | Per-directory launchd job labels (`<prefix>.<dir-name>-<hash>`) shared by watch and backup schedules |
| `cli_invocation.py` | Printable recovery/next-step commands bound to the running installation (never a bare PATH lookup) |
| `taxonomy_filters.py` | Shared wing/room validation and bounded suggestions for CLI, Python, and MCP retrieval surfaces, plus the write-side name rule (trimmed, no path separators, no re-spelled duplicates) |
| `diary.py` | Agent diary entries shared by `diary write` and the MCP diary tools — validation, `MEMPALACE_AGENT_NAME` default, entry metadata, and identity-matched reads |
| `errors.py` | Shared exception types; `InvalidArgumentError` marks a caller-supplied value the MCP dispatcher answers with `-32602` |
| `retrieval_rerank.py` | Deterministic project-file and CamelCase symbol reranking for code retrieval |
| `search_reranker.py` | Optional hybrid token-overlap reranker for `code_search(rerank="hybrid")` and benchmark comparisons |
| `layers.py` | 4-layer memory stack: L0 (identity, capped), L1 (ranked essential story: notes and decisions first), L2 (room recall), L3 (deep search) |
| `dialect.py` | AAAK lossy summary dialect — entity codes, topic markers, and token-saving estimates; printed by `compress`, never stored in drawers |
| `knowledge_graph.py` | Temporal entity-relationship graph — SQLite, time-filtered queries, fact invalidation |
| `palace_graph.py` | Room-based navigation graph — BFS traversal, tunnel detection across wings |
| `mcp_server.py` | MCP server public entrypoint shim — re-exports `TOOLS`, `handle_request`, `main`, and all `tool_*` handlers; implementation lives under `mcp/` |
| `mcp/` | MCP implementation package: `runtime.py` (shared state), `registry.py` (29-tool TOOLS dict), `dispatch.py` (handle_request/main; negotiates legacy `initialize` vs. stable 2026-07-28 `server/discover` per request), `protocol_compat.py` (SDK-backed 2026-07-28 metadata validation, error/result construction via the official `mcp` SDK types), `protocol_text.py` (AAAK/protocol strings), `tools/` (one module per tool family) |
| `mcp_tool_profiles.py` | Static MCP tool profiles and selector resolution (`--profile`, `--tools`, `--include`, `--exclude`) |
| `mcp_launcher.py` | `mempalace-code-mcp` console-script entry point for the MCP stdio server |
| `agent_plugins.py`, `agent_plugin/` | Installed Agent Plugins 1.0 package (`plugin.json`, `mcp.json`, bundled skill, schemas) and helpers that locate it |
| `watcher.py` | Commit/save watchers with guarded startup, disk budgets, scoped backups, and one reusable store/model lifecycle per run |
| `version_check.py` | Strictly opt-in PyPI version checks, first-run prompt state, throttling, and env/config overrides |
| `version.py` | Single source of truth for the package version |
| `updater.py` | Explicit `update status/check/apply` orchestration and the Linux systemd-user scheduler for supported isolated installs |
| `wing_migration.py` | Receipt-bound wing merge operator behind `mempalace-code wing-migration` |
| `_stdio.py` | Windows-only UTF-8 stdio reconfiguration; no-op elsewhere |
| `onboarding.py` | Guided first-run setup — asks about people/projects, generates AAAK bootstrap + wing config |
| `entity_registry.py` | Entity code registry — maps names to AAAK codes, handles ambiguous names |
| `entity_detector.py` | Auto-detect people and projects from file content |
| `general_extractor.py` | Classifies text into default memory types (decision, preference, milestone, problem); emotional extraction is opt-in for conversation-focused mining |
| `room_detector_local.py` | Maps folders to room names using 70+ patterns — no API |
| `spellcheck.py` | Optional autocorrect helper for explicit callers; never applied to mined or stored text |
| `split_mega_files.py` | Splits concatenated transcript files into per-session files |

## Architecture

```
User → CLI → miner/convo_miner → LanceDB (palace)
                                     ↕
                              knowledge_graph (SQLite)
                                     ↕
User → MCP Server → searcher → results
                  → kg_query → entity facts
                  → diary    → agent journal
```

The palace uses LanceDB for verbatim drawer content and vector metadata. The knowledge graph uses SQLite for structured relationships. The MCP server exposes both to any AI tool with 29 tools by default; startup profiles reduce the surface. Current packages contain no ChromaDB bridge or dependency.
