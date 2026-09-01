# Backup and Restore — Protecting Manual Drawers

## The Silent Data Loss Problem

Replacing the active palace before validating recovery artifacts can destroy:

- **Drawers added via `mempalace_add_drawer`** (MCP tool) — architectural decisions, people facts, debugging notes, meeting context
- **Diary entries** written via `mempalace_diary_write` — agent session journals and continuity entries
- **Knowledge graph triples** stored in `~/.mempalace/knowledge_graph.sqlite3` — if you rely on KG for temporal facts

The miner only regenerates code-chunked drawers (`chunker_strategy: regex_structural_v1`). It knows nothing about manually-added content.

---

## Recommended Rebuild Workflow

This is the complete rebuild procedure. Keep every command in one shell so the
same explicit paths are used throughout. Replace `SOURCE` and `KNOWN_QUERY`
before running anything. `KNOWN_QUERY` must identify content you expect to find
after rebuilding.

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
SOURCE="${HOME}/projects/my_app"
KNOWN_QUERY="a known decision or source phrase"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"
BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"
QUARANTINE="${PALACE}.quarantine-$(date -u +%Y%m%dT%H%M%SZ)"

: "${PALACE:?set PALACE to the inspected active palace}"
: "${SOURCE:?set SOURCE to the source directory}"
: "${KNOWN_QUERY:?set KNOWN_QUERY to expected content}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to a new JSONL path}"
: "${BACKUP_TAR:?set BACKUP_TAR to a new tar path}"
: "${QUARANTINE:?set QUARANTINE to a new sibling path}"
test -d "$PALACE/lance"
test -d "$SOURCE"
PALACE_ID="$(cd "$PALACE" && pwd -P)"
SOURCE_ID="$(cd "$SOURCE" && pwd -P)"
: "${PALACE_ID:?failed to resolve PALACE identity}"
: "${SOURCE_ID:?failed to resolve SOURCE identity}"
test ! -e "$EXPORT_JSONL"
test ! -e "$BACKUP_TAR"
test ! -e "$QUARANTINE"

mempalace-code --palace "$PALACE" export --only-manual --with-kg --out "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run
mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"
tar -tzf "$BACKUP_TAR"

test "$(cd "$PALACE" && pwd -P)" = "$PALACE_ID"
test "$(cd "$SOURCE" && pwd -P)" = "$SOURCE_ID"
test -d "$PALACE/lance"
test ! -e "$QUARANTINE"
mv "$PALACE" "$QUARANTINE"
mempalace-code --palace "$PALACE" mine "$SOURCE"
mempalace-code --palace "$PALACE" import "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" health
mempalace-code --palace "$PALACE" search "$KNOWN_QUERY" --limit 5
```

The fail-fast setting stops the workflow when any command fails. The JSONL
import dry run validates input and opens existing palace state read-only when
present. It does not write palace or KG state. When the selected palace and KG
are absent, it does not create them or initialize temporary, embedding-model, or
cache state. Here it previews record import without applying records. Inspect
the `tar -tzf` listing and confirm it contains `metadata.json` and the expected
`lance/` content. The JSONL contains:

- All drawers with `chunker_strategy` in `manual_v1` (MCP `add_drawer`) or `diary_v1` (diary entries)
- All triples from the separate global KG at
  `~/.mempalace/knowledge_graph.sqlite3`; `--only-manual` does not filter KG records

That global KG is separate from a palace-local `<palace>/knowledge_graph.sqlite3`.

Import deduplicates against the freshly mined palace. Keep `$QUARANTINE`,
`$EXPORT_JSONL`, and `$BACKUP_TAR` until the import summary, health result, and
bounded known-result search are all correct. Only then may you dispose of the
quarantine.

### Failure recovery

If validation fails, stop the new palace process and recover the
original palace with the standalone workflow below. Replace the quarantine
timestamp with the exact path created above.

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
QUARANTINE="${PALACE}.quarantine-REPLACE_WITH_ORIGINAL_TIMESTAMP"
FAILED_REBUILD="${PALACE}.failed-rebuild-$(date -u +%Y%m%dT%H%M%SZ)"

: "${PALACE:?set PALACE to the failed rebuilt palace}"
: "${QUARANTINE:?set QUARANTINE to the original quarantine path}"
: "${FAILED_REBUILD:?set FAILED_REBUILD to a new sibling path}"
test -d "$QUARANTINE/lance"
test ! -e "$FAILED_REBUILD"
if test -e "$PALACE" || test -L "$PALACE"; then
  mv "$PALACE" "$FAILED_REBUILD"
fi
test ! -e "$PALACE"
test ! -L "$PALACE"
mv "$QUARANTINE" "$PALACE"
mempalace-code --palace "$PALACE" health
```

When present, the failed rebuild is preserved at `$FAILED_REBUILD`. The original
palace is restored for inspection. Do not delete either state during recovery.

---

## Restore Procedure

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"

: "${PALACE:?set PALACE to the inspected existing palace}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to the inspected JSONL path}"
test -d "$PALACE/lance"
test -f "$EXPORT_JSONL"

mempalace-code --palace "$PALACE" import "$EXPORT_JSONL"
mempalace-code --palace "$PALACE" health
```

Use `--skip-kg` to omit KG triples, `--wing-override NAME` to replace drawer
wings, or `--skip-dedup` to import every record. Preview the inspected file
against the inspected existing palace with:

```bash
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
EXPORT_JSONL="${HOME}/.mempalace/recovery-manual.jsonl"

: "${PALACE:?set PALACE to the inspected existing palace}"
: "${EXPORT_JSONL:?set EXPORT_JSONL to the inspected JSONL path}"
test -d "$PALACE/lance"
test -f "$EXPORT_JSONL"

mempalace-code --palace "$PALACE" import "$EXPORT_JSONL" --dry-run
```

This validates input and opens existing palace state read-only when present. It
does not write palace or KG state. When the selected palace and KG are absent,
it does not create them or initialize temporary, embedding-model, or cache
state. It previews record import without applying records.

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
# Ensure the canonical FastEmbed model and provenance are cached first
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
set -euo pipefail

PALACE="${HOME}/.mempalace/palace"
BACKUP_TAR="${HOME}/.mempalace/recovery-full.tar.gz"
RESTORE_TARGET="${HOME}/.mempalace/restored-palace"
ARCHIVE="${HOME}/.mempalace/archive-to-restore.tar.gz"

: "${PALACE:?set PALACE to the inspected source palace}"
: "${BACKUP_TAR:?set BACKUP_TAR to a new backup artifact path}"
: "${RESTORE_TARGET:?set RESTORE_TARGET to a new restore target}"
: "${ARCHIVE:?set ARCHIVE to the inspected archive being restored}"
test -d "$PALACE/lance"
test ! -e "$BACKUP_TAR"
mempalace-code --palace "$PALACE" backup create --out "$BACKUP_TAR"
tar -tzf "$BACKUP_TAR"
test -f "$ARCHIVE"
tar -tzf "$ARCHIVE"
test ! -e "$RESTORE_TARGET"
mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE"
mempalace-code --palace "$RESTORE_TARGET" health
```

Without `--force`, the CLI refuses when its checks find state in the selected
palace or at the selected KG destination. A real empty palace directory remains
reusable. At publication, restore claims the exact `lance/` name exclusively and
creates the exact KG destination with an atomic no-replace hard link. If either
name is raced in, restore preserves it; a KG publication failure also removes
the Lance root still owned by that invocation. Unsupported hard links fail
closed. This boundary does not make arbitrary concurrent edits elsewhere under
the palace transactional and does not protect concurrent replacement of the
palace root or its ancestors. The safe flow above uses absent destinations so
retries cannot overwrite managed publication names.

`--force` replaces the target's managed `lance/` data and atomically replaces the
selected KG after archive validation. It preserves unrelated entries in a real
palace directory. Symlink objects found at the selected palace, Lance, or KG
validation boundary are replaced without modifying their referents; concurrent
replacement of the palace root or its ancestors remains outside this boundary.
Use `--force` only after inspecting the archive and exact destinations, then
creating and inspecting a fresh backup of the current target. If `--kg-path`
selects a KG outside that target, back up that file separately before adding
`--force`:

```bash
set -euo pipefail

ARCHIVE="${HOME}/.mempalace/archive-to-restore.tar.gz"
RESTORE_TARGET="${HOME}/.mempalace/palace"
CURRENT_BACKUP="${HOME}/.mempalace/pre-force-restore.tar.gz"
KG_DEST="${RESTORE_TARGET}/knowledge_graph.sqlite3"

: "${ARCHIVE:?set ARCHIVE to the archive being restored}"
: "${RESTORE_TARGET:?set RESTORE_TARGET to the exact destination}"
: "${CURRENT_BACKUP:?set CURRENT_BACKUP to a new backup path}"
: "${KG_DEST:?set KG_DEST to the selected KG destination}"
test -f "$ARCHIVE"
test -d "$RESTORE_TARGET/lance"
test ! -e "$CURRENT_BACKUP"
printf 'Restore target: %s\n' "$RESTORE_TARGET"
printf 'KG destination: %s\n' "$KG_DEST"
tar -tzf "$ARCHIVE"
mempalace-code --palace "$RESTORE_TARGET" backup create --out "$CURRENT_BACKUP"
tar -tzf "$CURRENT_BACKUP"
mempalace-code --palace "$RESTORE_TARGET" restore "$ARCHIVE" --force
mempalace-code --palace "$RESTORE_TARGET" health
```

### Tarball Restore — KG Destination

When a tarball archive includes `knowledge_graph.sqlite3`, the restore command decides
where to write it based on your invocation:

| Invocation | KG written to |
|------------|---------------|
| `mempalace-code restore FILE` | `~/.mempalace/knowledge_graph.sqlite3` (global default) |
| `mempalace-code --palace <dir> restore FILE` | `<dir>/knowledge_graph.sqlite3` (palace-scoped) |
| `mempalace-code --palace <dir> restore FILE --kg-path <path>` | `<path>` (explicit override) |
| `mempalace-code restore FILE --kg-path <path>` | `<path>` (explicit override) |

**Important:** When you restore to an explicit `--palace <dir>`, the archived KG data
is written to `<dir>/knowledge_graph.sqlite3` — not to the global default — to avoid
silently overwriting an unrelated knowledge graph.

Use `--kg-path` to direct the KG to any arbitrary destination, including the global
default path, a shared location, or a testing path:

```bash
# Restore Lance data to a custom palace, KG to the custom palace (default scoping)
mempalace-code --palace ~/my_palace restore ~/backup.tar.gz

# Override the KG destination explicitly
mempalace-code --palace ~/my_palace restore ~/backup.tar.gz --kg-path ~/shared_kg.sqlite3

# Restore without --palace: KG goes to the global default (backward-compatible)
mempalace-code restore ~/backup.tar.gz
```

> **Note:** This tarball restore behavior is separate from JSONL import/export KG
> handling. The `--skip-kg` and `--with-kg` flags documented in the [Restore
> Procedure](#restore-procedure) section above apply to JSONL imports only.

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
| `pre_watch` | `pre_watch_` | Auto-backup before watcher initial mine |

### Watch Pre-Run Backups

When an existing palace is detected on watcher startup, `mempalace-code watch` (and
`mempalace-code mine --watch`) creates a `pre_watch` archive **before** the initial
incremental mine.  The archive path is printed to stdout:

```
  Pre-watch backup: /path/to/.mempalace/backups/pre_watch_20260101_120000.tar.gz
```

If the archive cannot be created (e.g. disk budget too low), the watcher **exits
immediately** — the initial mine is never run and the palace is not mutated.

### Startup State Markers

The watcher emits grep-friendly `WATCH_RUN` lines at each startup transition so that the appended daemon log (default `/tmp/mempalace-watch.log`) can be searched to determine the state of any startup attempt:

| State line | Meaning |
|-----------|---------|
| `WATCH_RUN run_id=<id> state=run-started` | Daemon startup began |
| `WATCH_RUN run_id=<id> state=pre-watch-backup-failed` | Pre-watch backup failed; daemon exited before mine |
| `WATCH_RUN run_id=<id> state=initial-mine-started` | Initial mine is running |
| `WATCH_RUN run_id=<id> state=initial-mine-completed` | Initial mine finished successfully |
| `WATCH_RUN run_id=<id> state=initial-mine-skipped reason=disk-budget` | Mine skipped because disk budget is too low |
| `WATCH_RUN run_id=<id> state=optimize-completed` | Post-mine optimize pass succeeded |
| `WATCH_RUN run_id=<id> state=optimize-skipped reason=backup-gate` | Optimize skipped (backup gate rejected) |
| `WATCH_RUN run_id=<id> state=watch-ready` | All startup gates passed; daemon entered the watch loop |

The `run_id` is unique per startup attempt. An appended log file may contain `WATCH_RUN` lines from older runs that exited with disk-budget or backup failures. To find the latest healthy startup, locate the last `state=watch-ready` line and use its `run_id` to filter the associated transitions:

```bash
# Find the latest run that reached watch-ready
grep -a 'state=watch-ready' /tmp/mempalace-watch.log | tail -1
# WATCH_RUN run_id=20260616T120102Z-p12345 state=watch-ready

# See all transitions for that startup (replace the run_id from above)
grep -a 'run_id=20260616T120102Z-p12345' /tmp/mempalace-watch.log
```

If `state=pre-watch-backup-failed` appears for the current `run_id`, the daemon exited before modifying the palace. See [Degraded Startup Recovery](#degraded-startup-recovery) for next steps.

### Degraded Startup Recovery

If the initial mine fails with a Lance missing-fragment error (a symptom of prior
cleanup/restore history leaving stale fragment references), the watcher:

1. Prints `DEGRADED` and the error context.
2. Attempts an automatic Lance version rollback to the most recent healthy version
   (`repair --rollback`).
3. If rollback succeeds, retries the initial mine once.  The watcher enters the
   normal watch loop only after the retry succeeds.
4. If rollback finds no healthy candidate, or the retry still fails, the watcher
   exits **before watching** and prints operator-safe recovery commands:

```
  To diagnose and recover, run:
    mempalace-code --palace /path/palace health
    mempalace-code --palace /path/palace repair --rollback --dry-run
```

The watcher may also print a `restore --force` suggestion for its `pre_watch`
tarball when Lance version rollback cannot recover. Do not run that suggestion
directly. Set its palace as `RESTORE_TARGET`, set the tarball as `ARCHIVE`, and
follow the inspected force-restore procedure in [Tarball Backup](#tarball-backup-full-snapshot).

### Auto-Backup Before Optimize

Enabled by default. Every `mempalace-code mine` creates a backup before compacting storage:

```
~/.mempalace/backups/pre_optimize_YYYYMMDD_HHMMSS.tar.gz
```

To disable: set `auto_backup_before_optimize: false` in `~/.mempalace/config.json` or `MEMPALACE_AUTO_BACKUP_BEFORE_OPTIMIZE=0`.

### Retention (automatic pruning)

**`pre_optimize` archives are bounded by default** to the newest 5.  A long-running
`mempalace-code watch` daemon creates one archive before every compaction, so without a
bound the `backups/` directory can fill the local volume even when the palace itself
is small.

**`scheduled` archives are bounded by default** to the newest 14.  Cron and launchd
jobs create one archive per run, so without a bound the `backups/` directory
accumulates archives indefinitely.

**`manual` archives are unbounded by default** — they are never pruned unless you
set `backup_retain_count` explicitly.

```bash
# Override the implicit pre_optimize bound and set an explicit limit for all kinds:
export MEMPALACE_BACKUP_RETAIN_COUNT=10
# Or in ~/.mempalace/config.json:
# {"backup_retain_count": 10}

# Deliberate keep-all opt-out — disables pruning for every kind, including pre_optimize:
export MEMPALACE_BACKUP_RETAIN_COUNT=0
```

Retention prunes **only the managed backups directory** (`<palace_parent>/backups/`).
Archives written with explicit `--out` paths are never pruned.

`backup list` annotates stale (would-be-pruned) archives with `[stale]` and oversized ones with `[oversized]`.

After a successful optimize and readability check, MemPalace also runs
best-effort verified Lance cleanup so future backups do not keep archiving stale
table versions. Optimize and cleanup verification re-opens the Lance table, so
it checks the same fresh-handle path the next CLI, MCP server, or watcher
process will use. Manual `cleanup` remains the recovery tool for older
installations that already accumulated stale versions or for emergency disk
recovery.

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
With current defaults, future managed `pre_optimize` backups keep the newest 5
and managed `scheduled` backups keep the newest 14; `manual` backups stay
unbounded unless you set an explicit retain count.

If LanceDB stale versions/fragments are the problem rather than backup archives,
run storage cleanup only after stopping MemPalace watchers, miners, maintenance
commands, and MCP servers:

```bash
mempalace-code cleanup --older-than-days 7
mempalace-code cleanup --unsafe-now  # emergency only; no MemPalace process may be running
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
mempalace-code repair --rollback --dry-run  # show what rollback would recover
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
2. List existing backups and remove stale ones manually if immediate space is needed:
   ```bash
   mempalace-code backup list
   ls -lh ~/.mempalace/backups/
   rm ~/.mempalace/backups/<stale_archive>.tar.gz
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

## Legacy Chroma Palace Recovery Before Upgrade

Current releases contain no ChromaDB dependency or migration bridge. A legacy
palace with `chroma.sqlite3` fails closed without modifying the source, marker,
destination, backup, or archive.

Create and verify a separate source backup before upgrading. Then run the last
public bridge release in an isolated `uvx` environment:

```bash
uvx --from 'mempalace-code[chroma]==1.13.4' mempalace-code migrate-storage SRC DST --verify
```

Inspect the destination and retain the source backup until the LanceDB palace has
passed `mempalace-code --palace DST health`. Re-running a current-version
`migrate-storage` invocation only prints the retirement recovery message and exits
nonzero; it performs no filesystem reads or writes.

---

## Remote Mirror Risk

Managed backups and Lance cleanup protect **local** palace state. They do not protect
against a separate class of operator risk: delete-mode file mirroring between independent
hosts (`rsync --delete`).

When `rsync --delete` syncs a whole MemPalace state directory from one host to another,
it removes files on the destination that are absent on the source. If the destination host
holds **remote-owned** drawers, diary entries, or KG triples that were never synced back
to the source, those are permanently deleted — even though local backups and Lance cleanup
are healthy.

### Why managed backups do not protect against this

- Backups archive the **source** palace. A delete-mode mirror of the source removes content
  from the **destination** that the source never knew about.
- Backup retention and Lance cleanup run on the source; they have no visibility into remote
  state or what `rsync --delete` will remove on the destination.

### Safe rsync with recommended excludes

If you must mirror the palace state directory between hosts, exclude the live palace data,
KG database, config, and managed backups directory so a delete sweep cannot remove
remote-owned content:

```bash
rsync -a --delete \
  --exclude=palace/ \
  --exclude=knowledge_graph.sqlite3 \
  --exclude=config.json \
  --exclude=backups/ \
  ~/.mempalace/ user@host:.mempalace/
```

Add `--exclude='*.log'` if you route MemPalace watch logs into the state directory
(by default, logs go to `/tmp/mempalace-watch.log` and do not need excluding).

### Preflight check before installing a mirror job

Before installing a launchd or cron mirror job, run the preflight command to verify your
rsync invocation is safe (the command is inspected only — it is never executed):

```bash
mempalace-code preflight mirror --command \
  "rsync -a --delete --exclude=palace/ --exclude=knowledge_graph.sqlite3 \
   --exclude=config.json --exclude=backups/ ~/.mempalace/ user@host:.mempalace/"
# OK

mempalace-code preflight mirror --command "rsync -a --delete ~/.mempalace/ user@host:.mempalace/"
# BLOCKED [delete-mode-state-mirror-missing-excludes]
#   missing exclude: palace
#   missing exclude: kg
#   missing exclude: config
#   missing exclude: backups
```

Use `--json` for automation scripts that parse the result.

### Recommended alternative: export/import instead of whole-state mirrors

Whole-state mirrors transfer regenerable code-chunked drawers along with the irreplaceable
manual content. A safer cross-host transfer uses the export/import flow:

```bash
# On source host: export only manual drawers and KG (non-regenerable content)
mempalace-code export --only-manual --with-kg --out ~/transfer.jsonl

# Copy the JSONL to the destination host, then import
mempalace-code import ~/transfer.jsonl
```

This preserves remote-owned content on both sides and avoids delete-sweep risk entirely.

---

## Related

- Upstream data loss context: issue #469 in the original ChromaDB-based fork
