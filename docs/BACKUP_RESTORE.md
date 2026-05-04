# Backup and Restore — Protecting Manual Drawers

## The Silent Data Loss Problem

The intuitive "fix my palace" workflow is:

```bash
rm -rf ~/.mempalace/palace && mempalace-code mine ~/projects/my_app
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
mempalace-code export --only-manual --with-kg --out ~/.mempalace/backup.jsonl
```

This produces a JSONL file containing:
- All drawers with `chunker_strategy` in `manual_v1` (MCP `add_drawer`) or `diary_v1` (diary entries)
- All KG triples (no `--only-manual` filtering for KG — it's always fully exported)

**Step 2 — Nuke and re-mine:**

```bash
rm -rf ~/.mempalace/palace
mempalace-code mine ~/projects/my_app
```

**Step 3 — Restore from backup:**

```bash
mempalace-code import ~/.mempalace/backup.jsonl
```

Import deduplicates against the freshly-mined palace so you won't get doubles.

---

## Restore Procedure

```bash
# Restore drawers + KG from a backup
mempalace-code import backup.jsonl

# Restore drawers only, skip KG
mempalace-code import backup.jsonl --skip-kg

# Dry run — see what would be imported without writing
mempalace-code import backup.jsonl --dry-run

# Override wing for all imported drawers
mempalace-code import backup.jsonl --wing-override my_project

# Skip dedup check (force-import all records)
mempalace-code import backup.jsonl --skip-dedup
```

---

## Filter Semantics

### `--only-manual`

Exports only drawers that the miner **cannot regenerate**:

| `chunker_strategy` | Source | Regenerable by miner? |
|--------------------|--------|-----------------------|
| `regex_structural_v1` | `mempalace-code mine` | Yes — skip |
| `convo_turn_v1` | `mempalace-code mine --mode convos` | Yes — skip |
| `manual_v1` | MCP `add_drawer` tool | **No — include** |
| `diary_v1` | MCP `diary_write` / CLI `diary write` | **No — include** |

Use `--only-manual` for the standard nuke-and-re-seed workflow. Omit it if you want a full snapshot (e.g., migrating to a new machine).

### `--wing`, `--room`, `--since`

Scope the export to a subset of your palace:

```bash
# Only the 'people' wing
mempalace-code export --out backup.jsonl --wing people

# Decisions room in the mempalace wing
mempalace-code export --out backup.jsonl --wing mempalace --room decisions

# Only drawers filed on or after 2026-01-01
mempalace-code export --out backup.jsonl --since 2026-01-01
```

### `--with-embeddings`

Include raw embedding vectors in the JSONL. This makes the file larger (~1.5 KB per drawer) but allows offline import without re-embedding (the current import path re-embeds regardless — this is for future use).

---

## Airgap / Machine Transfer Scenario

To move your palace to an airgapped machine or a new workstation:

**On the connected machine:**

```bash
# Full export (not --only-manual, to preserve everything)
mempalace-code export --with-kg --out palace_full.jsonl
```

Copy `palace_full.jsonl` to the target machine (USB, encrypted transfer, etc.).

**On the airgap machine:**

```bash
# Ensure embedding model is cached first
mempalace-code fetch-model

# Import — will re-embed content using the local model
mempalace-code import palace_full.jsonl
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

## Tarball Backup (Full Snapshot)

For full binary snapshots (faster, includes everything, not human-readable):

```bash
mempalace-code backup create                    # creates ~/.mempalace/backups/mempalace_backup_YYYYMMDD_HHMMSS.tar.gz
mempalace-code backup create --out ~/safe.tar.gz
mempalace-code backup list                      # show existing backups
mempalace-code restore ~/safe.tar.gz            # restore (prompts before overwrite)
mempalace-code restore ~/safe.tar.gz --force    # overwrite without prompt
```

### Scheduled Backups

```bash
mempalace-code backup schedule --freq daily     # prints launchd plist (macOS) or cron line (Linux)
```

Install the printed snippet manually — mempalace-code does not write to system directories.

### Backup Kinds

Each backup has a kind that controls its filename prefix and per-kind retention:

| Kind | Prefix | Created by |
|------|--------|-----------|
| `manual` | `mempalace_backup_` | `backup create` (default) |
| `scheduled` | `scheduled_` | `backup create --kind scheduled` / cron |
| `pre_optimize` | `pre_optimize_` | Auto-backup before optimize |

### Auto-Backup Before Optimize

Enabled by default. Every `mempalace-code mine` creates a backup before compacting storage:

```
~/.mempalace/backups/pre_optimize_YYYYMMDD_HHMMSS.tar.gz
```

To disable: set `auto_backup_before_optimize: false` in `~/.mempalace/config.json` or `MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE=0`.

### Retention (automatic pruning)

By default retention is disabled (`backup_retain_count: 0`). To enable, set a per-kind limit:

```bash
# Keep only the 5 newest backups of each kind
export MEMPALACE_BACKUP_RETAIN_COUNT=5
# Or in ~/.mempalace/config.json:
# {"backup_retain_count": 5}
```

Retention prunes **only the managed backups directory** (`<palace_parent>/backups/`). Archives written with explicit `--out` paths are never pruned.

`backup list` annotates stale (would-be-pruned) archives with `[stale]` and oversized ones with `[oversized]`.

### Disk-budget quick setup

To change the backup disk floor:

```bash
export MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES=2GiB    # require 2 GiB projected free after backup
# Legacy alias still accepted:
export MEMPALACE_BACKUP_MIN_FREE_BYTES=2GiB
```

The guard is enabled by default through `disk_min_free_bytes` (1 GiB). See the
full [Disk-Budget Guard](#disk-budget-guard) section below for precedence and
failure behavior.

### Emergency cleanup

If the backups directory has grown large, inspect with:

```bash
mempalace-code backup list
```

Then delete old archives manually, or set `MEMPALACE_BACKUP_RETAIN_COUNT` to let future backups prune automatically.

If LanceDB stale versions/fragments are the problem rather than backup archives,
run storage cleanup after confirming no writer process is active:

```bash
mempalace-code cleanup --older-than-days 7
mempalace-code cleanup --unsafe-now  # emergency only; no watcher/miner may be running
```

---

## Health Check and Repair

If your palace seems corrupted (search returns empty, counts don't match):

```bash
mempalace-code health              # probe for fragment corruption
mempalace-code health --json       # machine-readable report
mempalace-code cleanup --older-than-days 7  # reclaim stale Lance versions
```

If corruption is detected:

```bash
mempalace-code repair --dry-run    # show what would be recovered, how many rows lost
mempalace-code repair --rollback   # roll back to last working LanceDB version
```

This uses LanceDB's version history to find the most recent uncorrupted state. Data added after corruption is lost — this is why auto-backup exists.

---

## Disk-Budget Guard

`backup create` checks available disk space before opening any file handles. If the projected post-backup free space would fall below the configured floor, the command exits with an error and **no archive or temp file is written**.

```
Error: disk budget: not enough free space to create backup.
Free: 450.0 MiB, required floor after archive: 1.0 GiB.
Palace: /Users/you/.mempalace/palace.
Free up disk space or lower backup_disk_min_free_bytes.
```

The projection is conservative: it assumes the archive size equals the uncompressed palace + KG size. Actual compressed archives are usually smaller, but the guard refuses when even the worst-case estimate would leave insufficient headroom.

### Configuring the backup floor

```bash
# Preferred environment variable
export MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES=2GiB

# Legacy alias accepted for existing installs
export MEMPALACE_BACKUP_MIN_FREE_BYTES=2GiB

# ~/.mempalace/config.json
{
  "backup_disk_min_free_bytes": 2147483648   // 2 GiB
}
```

The backup floor resolves as:

1. `MEMPALACE_BACKUP_DISK_MIN_FREE_BYTES`
2. legacy `MEMPALACE_BACKUP_MIN_FREE_BYTES`
3. `backup_disk_min_free_bytes` in `~/.mempalace/config.json`
4. legacy `backup_min_free_bytes` in `~/.mempalace/config.json`
5. `disk_min_free_bytes`
6. **1 GiB default**

### Emergency cleanup

If the backup guard refuses because disk is nearly full:

1. Check what is taking space:
   ```bash
   du -sh ~/.mempalace/palace ~/.mempalace/backups
   ```
2. List existing backups and remove old ones manually:
   ```bash
   mempalace-code backup list
   ls -lh ~/.mempalace/backups/
   rm ~/.mempalace/backups/pre_optimize_<old_date>.tar.gz
   ```
3. Re-run the backup once enough space is freed.

### Relationship to watcher thresholds

The watcher (`mempalace-code watch`) uses its own `watch_disk_min_free_bytes` threshold (also defaults to 1 GiB via `disk_min_free_bytes`). Set `disk_min_free_bytes` once to control both:

```json
{
  "disk_min_free_bytes": 1073741824
}
```

Or set them independently to give the watcher a tighter budget:

```json
{
  "disk_min_free_bytes": 1073741824,
  "watch_disk_min_free_bytes": 2147483648,
  "backup_disk_min_free_bytes": 1073741824
}
```

---

## Related

- Upstream data loss context: issue #469 in the original ChromaDB-based fork
