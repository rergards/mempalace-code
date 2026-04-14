---
slug: STORE-BACKUP-RESTORE
goal: "Add `mempalace backup` and `mempalace restore` CLI commands that create/extract .tar.gz archives of the palace (lance/ directory + knowledge_graph.sqlite3 + metadata.json)"
risk: low
risk_note: "New additive commands; no changes to existing storage or KG code; tarball ops use stdlib tarfile module"
files:
  - path: mempalace/backup.py
    change: "New module — create_backup() and restore_backup() functions using tarfile + json"
  - path: mempalace/cli.py
    change: "Add 'backup' and 'restore' subcommands with argparse; add cmd_backup/cmd_restore handlers; wire into dispatch dict"
  - path: tests/test_backup.py
    change: "New test module — unit tests for backup/restore logic including round-trip verification"
acceptance:
  - id: AC-1
    when: "User runs `mempalace backup [--palace PATH] [--out FILE]`"
    then: "A .tar.gz is created containing lance/ directory contents, knowledge_graph.sqlite3, and metadata.json"
  - id: AC-2
    when: "The backup archive is inspected"
    then: "metadata.json contains drawer_count, wings (list), timestamp (ISO 8601), mempalace_version, and backend_type ('lancedb')"
  - id: AC-3
    when: "User runs `mempalace restore FILE [--palace PATH]`"
    then: "Tarball is extracted into the target palace path, restoring lance/ and knowledge_graph.sqlite3"
  - id: AC-4
    when: "User runs `mempalace restore FILE` targeting a non-empty palace path without --force"
    then: "Command refuses with a clear error message and exits non-zero"
  - id: AC-5
    when: "Round-trip test: seed palace with drawers + KG triples, backup, restore to a new path, then search"
    then: "Search against the restored palace returns the same results as the original"
  - id: AC-6
    when: "`ruff check mempalace/ tests/` and `ruff format --check mempalace/ tests/`"
    then: "No errors"
out_of_scope:
  - "Incremental/differential backups"
  - "Backup encryption or compression algorithm selection"
  - "Remote/cloud backup targets (S3, GCS)"
  - "Scheduled/automatic backups"
  - "ChromaDB legacy backend backup support"
  - "MCP tool exposure for backup/restore"
---

## Design Notes

### Tarball structure

```
mempalace_backup/
├── lance/                        # Full copy of <palace>/lance/
│   └── ...                       # LanceDB columnar files, transactions, etc.
├── knowledge_graph.sqlite3       # Copy of the KG SQLite database
└── metadata.json                 # Backup metadata (see AC-2)
```

- The `mempalace_backup/` prefix inside the tarball prevents tarbomb extraction.
- Lance files are added recursively via `tarfile.add(lance_dir, arcname="mempalace_backup/lance")`.

### Knowledge graph location

- The KG lives globally at `~/.mempalace/knowledge_graph.sqlite3` (not per-palace). Backup copies it from `DEFAULT_KG_PATH`. Restore writes it back to `DEFAULT_KG_PATH`.
- If the KG file doesn't exist at backup time, it is simply omitted (the palace may have no KG data). Restore handles archives with or without the KG file gracefully.
- Restore overwrites the existing KG file — the `--force` check on AC-4 covers the palace path only (lance/ directory non-empty). A warning is printed if an existing KG will be overwritten.

### Default output filename

- `mempalace_backup_YYYYMMDD_HHMMSS.tar.gz` in the current working directory.
- `--out FILE` overrides this. Parent directory must exist.

### Non-empty palace check (AC-4)

- "Non-empty" = `<palace_path>/lance/` directory exists and is not empty.
- `--force` bypasses this check. The existing lance/ directory is removed before extraction.

### backup.py module API

```python
def create_backup(
    palace_path: str,
    out_path: str | None = None,
    kg_path: str | None = None,
) -> dict:
    """Create a .tar.gz backup of the palace.
    
    Returns metadata dict written to metadata.json.
    """

def restore_backup(
    archive_path: str,
    palace_path: str,
    force: bool = False,
    kg_path: str | None = None,
) -> dict:
    """Extract a backup archive into the target palace path.
    
    Returns the parsed metadata.json from the archive.
    Raises FileExistsError if palace is non-empty and force=False.
    """
```

- `kg_path` defaults to `knowledge_graph.DEFAULT_KG_PATH` when None, making it overridable for tests.
- `create_backup` gathers metadata by opening the store read-only (`open_store(palace_path, create=False)`) to call `store.count()` and `store.count_by("wing")`.

### CLI integration

- Follows the existing argparse pattern: subparser registration near the other commands, `cmd_backup`/`cmd_restore` handler functions, dispatch dict entries.
- Palace path resolution uses the same `args.palace or MempalaceConfig().palace_path` pattern.

### Test strategy

- Uses existing `palace_path`, `seeded_collection`, `kg`, and `seeded_kg` fixtures from `conftest.py`.
- `test_backup_creates_tarball` — verifies archive exists and contains expected members.
- `test_backup_metadata_contents` — verifies metadata.json fields match expectations.
- `test_restore_to_empty_palace` — extracts to a fresh path, verifies lance/ exists.
- `test_restore_refuses_non_empty_without_force` — asserts FileExistsError raised.
- `test_restore_with_force_overwrites` — verifies --force replaces existing data.
- `test_roundtrip_drawers` — seed → backup → restore to new path → open_store → query → verify same results.
- `test_roundtrip_kg` — seed KG → backup → restore → query_entity → verify same triples.
- `test_backup_without_kg` — palace with no KG file → backup succeeds, archive has no KG entry.
