# mempalace_code/ — Core Package

The Python package that powers mempalace-code. All modules, all logic.

## Modules

| Module | What it does |
|--------|-------------|
| `cli.py` | CLI entry point — routes to init, mine, search, watch, backup/restore, export/import, health, and wake-up |
| `config.py` | Configuration loading — `~/.mempalace/config.json`, env vars, defaults |
| `language_catalog.py` | Shared language metadata for miner detection, `code_search` validation, and MCP language hints |
| `normalize.py` | Converts 5 chat formats (Claude Code JSONL, Claude.ai JSON, ChatGPT JSON, Slack JSON, plain text) to standard transcript format |
| `miner.py` | Project file ingest — scans directories, detects languages, chunks code/prose/config, stores drawers; Markdown chunks keep heading path and section metadata |
| `convo_miner.py` | Conversation ingest — chunks by exchange pair (Q+A), detects rooms from content |
| `searcher.py` | Semantic search via LanceDB vectors — filters by wing/room/language/symbol, returns verbatim text, scores, and stored metadata such as Markdown heading path |
| `layers.py` | 4-layer memory stack: L0 (identity), L1 (critical facts), L2 (room recall), L3 (deep search) |
| `dialect.py` | AAAK lossy summary dialect — entity codes, topic markers, and token-saving estimates |
| `knowledge_graph.py` | Temporal entity-relationship graph — SQLite, time-filtered queries, fact invalidation |
| `palace_graph.py` | Room-based navigation graph — BFS traversal, tunnel detection across wings |
| `mcp_server.py` | MCP server — 28 tools, AAAK auto-teach, Palace Protocol, agent diary |
| `onboarding.py` | Guided first-run setup — asks about people/projects, generates AAAK bootstrap + wing config |
| `entity_registry.py` | Entity code registry — maps names to AAAK codes, handles ambiguous names |
| `entity_detector.py` | Auto-detect people and projects from file content |
| `general_extractor.py` | Classifies text into default memory types (decision, preference, milestone, problem); emotional extraction is opt-in for conversation-focused mining |
| `room_detector_local.py` | Maps folders to room names using 70+ patterns — no API |
| `spellcheck.py` | Name-aware spellcheck — won't "correct" proper nouns in your entity registry |
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

The palace (LanceDB) stores verbatim drawer content and vector metadata. The knowledge graph (SQLite) stores structured relationships. The MCP server exposes both to any AI tool. ChromaDB is a deprecated optional legacy backend only.
