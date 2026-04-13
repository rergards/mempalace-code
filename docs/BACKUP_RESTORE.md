# Backup and Restore — Protecting Manual Drawers

## The Silent Data Loss Problem

The intuitive "fix my palace" workflow is:

```bash
rm -rf ~/.mempalace/palace && mempalace mine ~/projects/my_app
```

This silently destroys:

- **Drawers added via `mempalace_add_drawer`** (MCP tool) — architectural decisions, people facts, debugging notes, meeting context
- **Diary entries** written via `mempalace_diary_write` — agent session journals and continuity entries
- **Knowledge graph triples** stored in `~/.mempalace/knowledge_graph.sqlite3` — if you rely on KG for temporal facts

The miner only regenerates code-chunked drawers (`chunker_strategy: regex_structural_v1`). It knows nothing about manually-added content.

---

## Recommended Workflow: Export Before Nuke

**Step 1 — Export your manual drawers and KG before nuking:**

```bash
mempalace export --only-manual --with-kg --out ~/.mempalace/backup.jsonl
```

This produces a JSONL file containing:
- All drawers with `chunker_strategy` in `manual_v1` (MCP `add_drawer`) or `diary_v1` (diary entries)
- All KG triples (no `--only-manual` filtering for KG — it's always fully exported)

**Step 2 — Nuke and re-mine:**

```bash
rm -rf ~/.mempalace/palace
mempalace mine ~/projects/my_app
```

**Step 3 — Restore from backup:**

```bash
mempalace import ~/.mempalace/backup.jsonl
```

Import deduplicates against the freshly-mined palace so you won't get doubles.

---

## Restore Procedure

```bash
# Restore drawers + KG from a backup
mempalace import backup.jsonl

# Restore drawers only, skip KG
mempalace import backup.jsonl --skip-kg

# Dry run — see what would be imported without writing
mempalace import backup.jsonl --dry-run

# Override wing for all imported drawers
mempalace import backup.jsonl --wing-override my_project

# Skip dedup check (force-import all records)
mempalace import backup.jsonl --skip-dedup
```

---

## Filter Semantics

### `--only-manual`

Exports only drawers that the miner **cannot regenerate**:

| `chunker_strategy` | Source | Regenerable by miner? |
|--------------------|--------|-----------------------|
| `regex_structural_v1` | `mempalace mine` | Yes — skip |
| `convo_turn_v1` | `mempalace mine --mode convos` | Yes — skip |
| `manual_v1` | MCP `add_drawer` tool | **No — include** |
| `diary_v1` | MCP `diary_write` / CLI `diary write` | **No — include** |

Use `--only-manual` for the standard nuke-and-re-seed workflow. Omit it if you want a full snapshot (e.g., migrating to a new machine).

### `--wing`, `--room`, `--since`

Scope the export to a subset of your palace:

```bash
# Only the 'people' wing
mempalace export --out backup.jsonl --wing people

# Decisions room in the mempalace wing
mempalace export --out backup.jsonl --wing mempalace --room decisions

# Only drawers filed on or after 2026-01-01
mempalace export --out backup.jsonl --since 2026-01-01
```

### `--with-embeddings`

Include raw embedding vectors in the JSONL. This makes the file larger (~1.5 KB per drawer) but allows offline import without re-embedding (the current import path re-embeds regardless — this is for future use).

---

## Airgap / Machine Transfer Scenario

To move your palace to an airgapped machine or a new workstation:

**On the connected machine:**

```bash
# Full export (not --only-manual, to preserve everything)
mempalace export --with-kg --out palace_full.jsonl
```

Copy `palace_full.jsonl` to the target machine (USB, encrypted transfer, etc.).

**On the airgap machine:**

```bash
# Ensure embedding model is cached first
mempalace fetch-model

# Import — will re-embed content using the local model
mempalace import palace_full.jsonl
```

The JSONL format is backend-agnostic. If the source used ChromaDB and the target uses LanceDB, import still works.

---

## Export Format Reference

The JSONL file starts with a header line, followed by drawer and KG records:

```jsonl
{"type": "export_header", "version": "3.0.0", "palace_path": "...", "exported_at": "...", "filters": {...}, "drawer_count": 42, "kg_count": 7}
{"type": "drawer", "id": "drawer_notes_decisions_abc123", "text": "...", "wing": "notes", "room": "decisions", "chunker_strategy": "manual_v1", "embedding": null, ...}
{"type": "kg_triple", "id": "t_alice_works_on_mempalace_...", "subject": "Alice", "predicate": "works_on", "object": "mempalace", "valid_from": "2026-01-01", "valid_to": null, ...}
```

The format is human-readable, version-control-friendly, and streamable. You can inspect or edit it with standard text tools.

---

## Related

- `STORE-BACKUP-RESTORE` backlog item — opaque tarball backup of the full palace directory (different use case: full binary snapshot vs. selective human-readable export)
- Upstream data loss context: issue #469 in the original ChromaDB-based fork
