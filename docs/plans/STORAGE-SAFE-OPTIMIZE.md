---
slug: STORAGE-SAFE-OPTIMIZE
status: completed
authority: non_authoritative
goal: "Harden safe_optimize to fail-closed on backup error and add coverage for config paths"
risk: low
risk_note: "Additive test changes + small behavioural fix in safe_optimize (opt-in path only); no schema, API, or default-behaviour changes. Only affects users who set backup_before_optimize=True."
files:
  - path: mempalace/storage.py
    change: "safe_optimize(): when backup_first=True and create_backup() raises, return False WITHOUT running optimize. Normalise palace_path (rstrip '/'). Keep backup failure as logger.error, not warning."
  - path: mempalace/miner.py
    change: "Mine loop: split the 'Backing up...' and 'Optimizing storage...' prints onto separate lines so they do not glue together. On safe_optimize() returning False, print an unmissable WARNING block (not a tail-of-line note)."
  - path: mempalace/convo_miner.py
    change: "Same print-formatting and failure-surfacing fix as miner.py, applied to mine_convos()."
  - path: tests/test_storage.py
    change: "Add TestSafeOptimize class: (1) happy path returns True and data is readable post-optimize; (2) backup_first=True creates a backup file under <palace_parent>/backups/; (3) backup failure (monkeypatched create_backup) returns False AND the table was NOT optimized (no .optimize() call on underlying table)."
  - path: tests/test_miner.py
    change: "Add two tests: (1) mine() with MEMPALACE_OPTIMIZE_AFTER_MINE=0 (or monkeypatched config) does NOT call safe_optimize/optimize; (2) mine() with MEMPALACE_BACKUP_BEFORE_OPTIMIZE=1 calls safe_optimize with backup_first=True."
acceptance:
  - id: AC-1
    when: "safe_optimize(palace_path, backup_first=False) is called on a healthy LanceStore"
    then: "returns True; table row count is unchanged; a follow-up get(limit=1) succeeds"
  - id: AC-2
    when: "safe_optimize(palace_path, backup_first=True) succeeds"
    then: "returns True; a file matching pre_optimize_*.tar.gz exists under <palace_parent>/backups/"
  - id: AC-3
    when: "safe_optimize(palace_path, backup_first=True) is called but create_backup raises OSError"
    then: "returns False; the underlying _table.optimize() is NOT invoked; an error is logged"
  - id: AC-4
    when: "mine() runs with optimize_after_mine=False (via env var or file config)"
    then: "neither safe_optimize() nor optimize() is called on the store; mine completes successfully"
  - id: AC-5
    when: "mine() runs with backup_before_optimize=True (via env var)"
    then: "safe_optimize() is called with backup_first=True"
  - id: AC-6
    when: "safe_optimize prints progress during a real mine with backup_before_optimize=True"
    then: "the 'Backing up...' and 'Optimizing storage...' messages appear on separate lines"
out_of_scope:
  - "Backup retention / rotation policy (pre_optimize_*.tar.gz files pile up forever) — file as new backlog STORAGE-BACKUP-RETENTION."
  - "Deeper post-optimize verification (vector search roundtrip, schema assertion) — the row-count + head(1) check is sufficient for the Apr 2026 incident being hardened."
  - "Promoting safe_optimize to the DrawerStore abstract base class — callers already use hasattr() gating; legacy ChromaStore has no compaction semantics."
  - "Changing default values of optimize_after_mine (True) or backup_before_optimize (False)."
  - "CLI flag to override optimize-after-mine for a single run."
---

## Design Notes

- **Fail-closed contract.** The whole point of `backup_before_optimize=True` is that the backup is a *gate*. Today `create_backup` errors become `logger.warning` and `optimize()` runs anyway — this is the bug to fix. New contract: if the caller opted into a backup and the backup cannot be written, `safe_optimize` returns False without touching the table. Callers (miner.py / convo_miner.py) already handle `success=False` with a WARNING print; tighten that print so it is visible, not a trailing tag on the same line.
- **Keep the method signature stable.** `safe_optimize(palace_path, backup_first=False) -> bool` stays as-is. No new kwargs, no promotion to DrawerStore ABC. Callers already use `hasattr(collection, "safe_optimize")`.
- **Verification stays shallow.** Row-count + `head(1).to_pydict()` matches what the current implementation does and what the incident demands (detect a table that becomes unreadable). A full search roundtrip is out of scope — would add embed cost to every mine and is not what the checklist asked for.
- **Test seams.**
  - For AC-3 (backup failure), monkeypatch `mempalace.storage.create_backup` (imported locally inside safe_optimize — adjust import to module level OR patch `mempalace.backup.create_backup` at the source). Prefer lifting the import to module top so the patch target is stable. Guard against circular imports: `backup.py` imports `storage.open_store`, so `storage.py` cannot top-level-import `backup` — keep the import inside the function, and let the test patch `mempalace.backup.create_backup`.
  - For AC-4/AC-5, set `MEMPALACE_OPTIMIZE_AFTER_MINE` / `MEMPALACE_BACKUP_BEFORE_OPTIMIZE` env vars via `monkeypatch.setenv`. `MempalaceConfig` reads env vars first (see `config.py:132–144`), so this is the cleanest injection point — no need to monkeypatch the config class itself.
- **Path normalisation.** `safe_optimize` builds `backup_dir = os.path.join(os.path.dirname(palace_path), "backups")`. If the caller passes `/foo/palace/` (trailing slash), `dirname` returns `/foo/palace`, so backups land *inside* the palace rather than as a sibling. Add a `palace_path = palace_path.rstrip("/\\")` at the top of the function. Minor robustness, not load-bearing.
- **Print formatting fix.** Current miner.py line 1678–1679:
  ```
  if backup_first: print("  >> Backing up before optimize...", end="", flush=True)
  print("  >> Optimizing storage...", end="", flush=True)
  ```
  With `end=""` on both, and both always executing when `backup_first=True`, the output glues. Fix: the "Backing up..." line should end with a proper newline (remove `end=""`, or emit "done/failed" tail before the next print). The cleanest shape is:
  ```
  if backup_first: print("  >> Backing up before optimize...", flush=True)
  print("  >> Optimizing storage...", end="", flush=True)
  ```
  The actual "backup done" ack comes out of `safe_optimize` via log — acceptable; the print line is purely "we are about to do a backup".
- **Failure surfacing.** When `safe_optimize` returns False, change the tail from ` WARNING: verification failed (…s)` (appended to the same line as "Optimizing storage...") to a fresh line starting with `  !! WARNING:` so it is not swallowed by subsequent progress output. Apply identically in both miner.py and convo_miner.py.
- **No test for print formatting (AC-6)** is required as an automated assertion — capsys-based assertions on print order are brittle. AC-6 is validated by manual inspection during the implement phase; record it in the PR description, not as a test.
- **Backlog spin-off.** The retention/rotation gap for `pre_optimize_*.tar.gz` is real and worth a separate ticket; capture as STORAGE-BACKUP-RETENTION during the implement phase (use `backlog add`, do not hand-edit BACKLOG.yaml).
