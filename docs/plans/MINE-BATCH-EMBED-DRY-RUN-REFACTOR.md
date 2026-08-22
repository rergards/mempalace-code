---
slug: MINE-BATCH-EMBED-DRY-RUN-REFACTOR
status: completed
authority: non_authoritative
goal: "Eliminate dry-run code duplication in process_file() by delegating to _collect_specs_for_file(mined_files=set())"
risk: low
risk_note: "Single-function change in process_file(); _collect_specs_for_file() signature unchanged; collection=None safe when mined_files=set() bypasses the file_already_mined() call"
files:
  - path: mempalace/miner.py
    change: "Replace dry-run branch in process_file() with _collect_specs_for_file() call using mined_files=set() to skip the already-mined guard; extract room from specs[0]['metadata']['room'] for the print line"
  - path: tests/test_miner.py
    change: "Add test_process_file_dry_run_matches_chunk_count verifying that process_file(dry_run=True) returns the same chunk count as process_file(dry_run=False) for a file not yet in the palace"
---

## Design Notes

- **`mined_files=set()` trick**: `_collect_specs_for_file` skips the already-mined check when
  `mined_files is not None` — it does `if source_file in mined_files: return []`. Passing
  `mined_files=set()` (empty set) satisfies `is not None`, always evaluates to `False` for
  membership, and never touches `collection`. This is correct for dry-run: we want to see what
  *would* be filed, not skip already-mined files.

- **`collection=None` is safe**: In `mine()`, `collection` is set to `None` when `dry_run=True`
  (line 1574). With `mined_files=set()`, `_collect_specs_for_file` never reaches
  `file_already_mined(collection, ...)`, so `None` is harmless. No signature change needed.

- **Room extraction**: After the refactor, `specs[0]["metadata"]["room"]` replaces the
  separate `detect_room(...)` call that was in the old dry-run branch. If specs is empty
  (OSError or below MIN_CHUNK), skip the print — same behavior as today.

- **`mine()` also calls `detect_room` post-process_file**: Line 1615 calls
  `detect_room(filepath, "", rooms, project_path)` separately for `room_counts`. This is
  pre-existing behavior and is unaffected. The refactor only touches `process_file`.

- **New test shape**:
  ```python
  def test_process_file_dry_run_matches_chunk_count():
      # Write a multi-chunk Python file to a tmpdir
      # Call process_file(dry_run=False) → count_real
      # Open a fresh empty palace (so dry-run file isn't "already mined")
      # Call process_file(dry_run=True, collection=None) → count_dry
      # assert count_dry == count_real
  ```
  The test exercises AC-1 and ensures the paths stay in sync.

- **No changes to `_collect_specs_for_file` signature**: `mined_files` already defaults to
  `None`. No new parameter needed.

- **Timestamps in specs**: `_collect_specs_for_file` sets `filed_at: datetime.now()` on each
  spec. In dry-run mode these specs are discarded immediately — no functional impact, negligible
  overhead.
