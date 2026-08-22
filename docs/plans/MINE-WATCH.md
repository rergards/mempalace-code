---
slug: MINE-WATCH
status: completed
authority: non_authoritative
goal: "Add --watch flag to `mempalace mine` that uses OS-native file events to auto re-mine changed files"
risk: low
risk_note: "New module wrapping existing mine() — main integration risk is matching scan_project() filtering semantics and preserving KG behavior on re-mines. Mitigated by delegating to mine() wholesale rather than reimplementing."
files:
  - path: mempalace/watcher.py
    change: "New module — watch loop using watchfiles, debounce, signal handling, file filtering"
  - path: mempalace/cli.py
    change: "Add --watch flag to mine subcommand; dispatch to watcher when set"
  - path: pyproject.toml
    change: "Add [watch] optional dependency: watchfiles>=1.0"
  - path: tests/test_watcher.py
    change: "New test file — unit tests for debounce, filtering, graceful shutdown, incremental re-mine on change"
acceptance:
  - id: AC-1
    when: "User runs `mempalace mine <dir> --watch`"
    then: "Watcher starts, prints status line, and blocks (foreground daemon)"
  - id: AC-2
    when: "A source file in <dir> is modified or created while watcher is running"
    then: "Changed file is re-indexed within 10s (5s debounce + incremental mine)"
  - id: AC-3
    when: "Watcher is running and no files are changing"
    then: "CPU usage is near zero (watchfiles uses fsevents/inotify, no polling)"
  - id: AC-4
    when: "SIGTERM or SIGINT (Ctrl-C) is sent to the watcher process"
    then: "Watcher exits cleanly, flushes any pending batch, prints summary"
out_of_scope:
  - "Background daemon mode (launchd/systemd service) — foreground only for v1"
  - "Watch mode for --mode convos (conversation mining)"
  - "Watch mode for mine-all (multi-project)"
  - "Per-file surgical re-mine (reuses existing mine() with incremental=True)"
  - "Config file watching (mempalace.yaml changes)"
  - "README/docs update for --watch flag (separate docs PR)"
---

## Design Notes

### Library choice: `watchfiles` (not `watchdog`)

- `watchfiles` is Rust-backed (via `notify` crate), uses fsevents (macOS) and inotify (Linux) natively.
- Already a transitive dependency in the lock file (uvicorn pulls it in). Adding as explicit optional dep avoids relying on transitive availability.
- Simpler API than `watchdog`: `watchfiles.watch()` is a blocking iterator that yields sets of `(change_type, path)` tuples with built-in debounce.
- Pure sync API — no need for asyncio or threading.

### Architecture

```
cli.py --watch flag
  └── watcher.watch_and_mine(project_dir, palace_path, ...)
        ├── Load config, validate dir
        ├── Initial mine() call (incremental=True) — bring palace up to date
        ├── Register SIGTERM/SIGINT handler → sets shutdown flag
        └── watchfiles.watch(project_dir, ...) loop:
              ├── Filter changes through _is_relevant_change() (mirrors scan_project())
              ├── If any relevant changes remain → call mine(incremental=True)
              ├── mine() handles hash comparison, stale sweep, batching
              └── Check shutdown flag → break
```

### Key decisions

- **Reuse `mine()` wholesale** rather than extracting single-file re-mine. The incremental path in `mine()` already computes hashes for all files, skips unchanged ones in O(1), and only re-embeds changed files. For a watcher triggered by 1-3 file changes, the overhead is: one `scan_project()` walk + one `_bulk_existing_file_hashes()` query. Both are fast (<100ms for typical repos). This avoids duplicating complex logic (chunking, batching, KG extraction, stale sweep, optimize).

- **Debounce at 5000ms** via `watchfiles.watch(debounce=5000)`. This is the `watchfiles` built-in debounce — it waits until 5s of quiet before yielding the batch. Matches the task's "wait 5s after last change" requirement.

- **Filter before mining**: The watcher receives raw OS events including changes to `.git/`, `node_modules/`, `.pyc` files, etc. Before calling `mine()`, filter the change set through `_is_relevant_change()` which mirrors `scan_project()` semantics (miner.py:1875-1928): `READABLE_EXTENSIONS`, `KNOWN_FILENAMES` (Dockerfile, Makefile, etc.), `SKIP_FILENAMES`, `should_skip_dir()` on parent path components, `.gitignore` awareness (via `respect_gitignore` flag), and `include_ignored` overrides. If no relevant files remain after filtering, skip the mine cycle entirely. Note: `_is_relevant_change()` operates on path strings from OS events and must not require the file to exist on disk (delete events have no file to stat).

- **Foreground daemon**: `--watch` runs in the foreground (blocking). No daemonization for v1. User can background it with `&` or run in tmux/screen.

- **Signal handling**: Register `signal.signal(signal.SIGTERM, handler)` that sets a `threading.Event`. The approach does NOT rely on `watchfiles.watch()` being interrupted by the signal — instead, we pass `stop_event=shutdown_event` to `watchfiles.watch()` (supported since watchfiles 0.19). When the event is set, the iterator terminates cleanly on the next debounce tick. SIGINT (Ctrl-C) raises `KeyboardInterrupt` which breaks the loop naturally. After breaking, flush any pending mine cycle before exiting.

- **Mutual exclusion with --dry-run**: `--watch` + `--dry-run` is rejected with an error — watching without writing is pointless.

- **Mutual exclusion with --full**: `--watch` always uses incremental mode. `--full` + `--watch` is rejected.

- **Mutual exclusion with --limit**: `--watch` + `--limit` (any value > 0) is rejected. Reason: `mine()` slices the file list when `limit > 0` (miner.py:2574), making change detection partial and non-deterministic. Stale-file cleanup only runs when `limit == 0` (miner.py:2718), so limited watch would silently skip deleted-file sweeps. Watch mode always processes the full file set.

- **KG preservation**: `watch_and_mine()` accepts a `kg: KnowledgeGraph` parameter and passes it through to every `mine()` call, matching the existing `cmd_mine()` behavior (cli.py:154-165). KG triples are extracted/invalidated on each incremental re-mine exactly as they would be in a manual `mempalace mine` run.

- **Delete handling**: When a watched file is deleted, `watchfiles` emits a `Change.deleted` event. The watcher does NOT need to handle this specially — `mine(incremental=True, limit=0)` already performs stale-file sweep (miner.py:2716-2718) on every run, removing drawers for files no longer on disk. The watcher simply calls `mine()` on any event (including deletes), and the existing stale sweep handles cleanup. Note: `_is_relevant_change()` must accept delete events even for paths it cannot stat — it checks only path patterns, not file existence.

- **AC-3 (idle CPU) verification**: AC-3 "low CPU usage when idle" is a design property of `watchfiles` (Rust `notify` crate using fsevents/inotify kernel APIs — no polling). This is not gated by an automated test. Manual verification: run watcher on a quiet directory, confirm <1% CPU in Activity Monitor/top over 30s. The test suite verifies functional correctness; idle efficiency is a library guarantee.

### CLI changes (cli.py)

Add to `p_mine` parser:
```python
p_mine.add_argument(
    "--watch",
    action="store_true",
    help="Watch for file changes and re-mine automatically (requires mempalace[watch])",
)
```

In `cmd_mine()`, when `args.watch` is set:
1. Validate: reject `--watch` with `--dry-run`, `--full`, `--limit`, or `--mode convos`.
2. Import `watcher.watch_and_mine()` with an ImportError guard that tells the user to install `mempalace[watch]`.
3. Construct `KnowledgeGraph()` and delegate to `watch_and_mine()` with the same args that `mine()` would receive (including `kg`, `respect_gitignore`, `include_ignored`).

### Dependency (pyproject.toml)

```toml
watch = ["watchfiles>=1.0"]
```

Added as an optional extra, same pattern as `[chroma]`, `[spellcheck]`, `[treesitter]`.

### watcher.py module outline

```python
"""watcher.py — File watcher for auto-incremental mining."""

import signal
import sys
import threading
from pathlib import Path
from typing import Optional

def watch_and_mine(
    project_dir: str,
    palace_path: str,
    wing_override: str = None,
    agent: str = "mempalace",
    respect_gitignore: bool = True,
    include_ignored: list = None,
    kg = None,  # KnowledgeGraph instance — passed through to mine()
):
    """Watch project_dir for changes and re-mine incrementally."""
    # 1. Import watchfiles (fail with clear message if not installed)
    # 2. Initial incremental mine(incremental=True, kg=kg) to bring palace up to date
    # 3. Set up shutdown event + signal handler
    # 4. Build gitignore matchers for _is_relevant_change() if respect_gitignore
    # 5. Enter watchfiles.watch() loop with debounce=5000
    #    - Filter changes through _is_relevant_change()
    #    - Call mine(incremental=True, kg=kg) for relevant changes
    #    - Break on shutdown event
    # 6. Print summary on exit (files re-mined, cycles, duration)

def _is_relevant_change(
    path: str,
    project_path: Path,
    respect_gitignore: bool = True,
    include_ignored: Optional[list] = None,
) -> bool:
    """Return True if the changed path should trigger a re-mine.

    Mirrors scan_project() filtering: READABLE_EXTENSIONS, KNOWN_FILENAMES,
    SKIP_FILENAMES, should_skip_dir() on parents, gitignore, include_ignored.
    Must work for deleted paths (no file existence check).
    """
```

### Test plan (tests/test_watcher.py)

- **test_watch_rejects_dry_run**: `--watch --dry-run` exits with error.
- **test_watch_rejects_full**: `--watch --full` exits with error.
- **test_watch_rejects_limit**: `--watch --limit 5` exits with error.
- **test_watch_rejects_convos**: `--watch --mode convos` exits with error.
- **test_is_relevant_change_accepts**: `.py`, `.js`, `.rs`, `Dockerfile`, `Makefile` return True.
- **test_is_relevant_change_rejects**: `.pyc`, `.git/config`, `node_modules/x.js`, `package-lock.json`, `.DS_Store` return False.
- **test_is_relevant_change_known_filenames**: Files in `KNOWN_FILENAMES` (no extension match) are accepted.
- **test_is_relevant_change_include_ignored**: Force-included paths bypass gitignore and skip-dir filters.
- **test_is_relevant_change_deleted_path**: Delete event for a `.py` file returns True even though the file no longer exists on disk.
- **test_watch_detects_file_change**: Create a temp project, start watcher in a thread, modify a file, assert re-mine runs within timeout. Uses `threading.Timer` to stop watcher after assertion.
- **test_watch_detects_file_deletion**: Create a temp project, mine it, start watcher, delete a mined file, assert its drawers are removed after re-mine.
- **test_watch_handles_sigterm**: Start watcher in a subprocess, send SIGTERM, assert clean exit code 0.
- **test_import_error_message**: Mock `watchfiles` import failure, assert clear error message.
- **test_cli_watch_dispatch**: Verify `cmd_mine()` dispatches to `watch_and_mine()` when `--watch` is set (mock watcher, assert called with correct args including `kg`).
