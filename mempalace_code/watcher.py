"""watcher.py — File watcher for auto-incremental mining.

Provides ``watch_and_mine()`` (single project) and ``watch_all()`` (multi-project),
plus ``render_watch_schedule()`` for generating launchd/cron daemon configs.

Uses the ``watchfiles`` library (Rust-backed, uses fsevents/inotify — no polling).

Install the optional extra before use:
    pip install 'mempalace-code[watch]'
"""

import json
import os
import shlex
import signal
import sys
import threading
import time
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from types import FrameType

from .backup import create_backup
from .config import MempalaceConfig
from .disk_budget import DiskBudgetStatus, check_watch_budget, format_bytes
from .knowledge_graph import palace_kg_path as _palace_kg_path
from .mining.orchestrator import get_collection, mine
from .mining.scanner import (
    KNOWN_FILENAMES,
    READABLE_EXTENSIONS,
    SKIP_DIRS,
    SKIP_FILENAMES,
    ScanFilterRules,
    get_scan_filter_rules,
    is_dir_subtree_excluded,
    is_exact_force_include,
    is_force_included,
    is_gitignored,
    is_scan_excluded,
    load_gitignore_matcher,
    normalize_include_paths,
    scan_project,
    should_skip_dir,
)
from .operation_lock import OperationLock, OperationLockedError
from .storage import optimize_store

_UNSET: object = object()  # sentinel for _ScanRulesSnapshot._bad_mtime

# Throttle: print disk-budget skip message at most once per this many seconds.
_BUDGET_LOG_INTERVAL = 300  # 5 minutes


class _WatcherShutdownSignals:
    """Install and restore the supported graceful watcher signal handlers."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self._original_handlers: list[
            tuple[int, Callable[[int, FrameType | None], object] | int | None]
        ] = []

    def install(self) -> threading.Event:
        """Register one idempotent event handler, rolling back partial setup."""
        supported_signals = [signal.SIGTERM]
        sighup = getattr(signal, "SIGHUP", None)
        if sighup is not None:
            supported_signals.append(sighup)

        def handle_shutdown(_signum, _frame) -> None:
            self.event.set()

        try:
            for shutdown_signal in supported_signals:
                original_handler = signal.getsignal(shutdown_signal)
                signal.signal(shutdown_signal, handle_shutdown)
                self._original_handlers.append((shutdown_signal, original_handler))
        except Exception:
            self.restore()
            raise
        return self.event

    def restore(self) -> None:
        """Restore every replaced handler once, in reverse registration order."""
        while self._original_handlers:
            shutdown_signal, original_handler = self._original_handlers.pop()
            signal.signal(shutdown_signal, original_handler)


class _WatcherMiningStore:
    """Own one reusable drawer store and its warmup state for a watcher run."""

    def __init__(self, palace_path: str):
        self._palace_path = palace_path
        self._collection = None
        self._embedder_warmed = False

    @property
    def collection(self):
        if self._collection is None:
            self._collection = get_collection(self._palace_path)
        return self._collection

    def mine_kwargs(self) -> dict:
        """Return injected mine() arguments for the current lifecycle state."""
        return {"collection": self.collection, "warmup": not self._embedder_warmed}

    def note_mine(self, stats: dict) -> None:
        """Record a successful explicit warmup performed by mine()."""
        self._embedder_warmed = self._embedder_warmed or stats.get("embedder_warmed", False)

    def recreate(self) -> None:
        """Discard a stale post-rollback handle before retrying initial mining."""
        self._collection = get_collection(self._palace_path)
        self._embedder_warmed = False


def _with_watcher_lease(func: Callable) -> Callable:
    """Hold a shared operation lease for a watcher invocation's full lifetime."""

    @wraps(func)
    def wrapped(*args, **kwargs):
        operation_lock = kwargs.get("operation_lock") or OperationLock.default()
        try:
            lease = operation_lock.acquire_shared("watcher")
        except OperationLockedError as exc:
            owner = exc.owner
            owner_text = " ".join(
                f"{key}={value}" for key, value in owner.items() if key in {"operation", "pid"}
            )
            print(
                f"  Watcher refused: update operation owns this installation. {owner_text}".rstrip(),
                file=sys.stderr,
            )
            raise SystemExit(3) from exc
        with lease:
            return func(*args, **kwargs)

    return wrapped


def _load_watch_min_free() -> int:
    """Load the watcher disk-budget threshold from config."""
    return MempalaceConfig().watch_disk_min_free_bytes


def _format_budget_skip_message(status: DiskBudgetStatus, palace_path: str) -> str:
    """Build the actionable disk-budget skip message for watcher cycles."""
    lines = [
        "  [disk budget] Skipping watcher cycle — not enough free disk space.",
        f"  Palace:   {palace_path}",
        f"  Free:     {format_bytes(status.free_bytes)} (need {format_bytes(status.min_free_bytes)})",
        f"  Palace:   {format_bytes(status.palace_bytes)} used,"
        f" backups: {format_bytes(status.backups_bytes)} used",
        "  To stop:  launchctl unload ~/Library/LaunchAgents/com.mempalace.watch.plist",
        "  (or Ctrl-C if running interactively)",
    ]
    return "\n".join(lines)


def _invalidate_gitignore_cache(changes, matcher_cache: dict) -> None:
    """Evict matcher_cache entries for directories whose .gitignore file changed.

    Called at the top of every watchfiles event batch so that _is_relevant_change()
    picks up fresh matcher state for any files processed in the same batch.
    """
    for _change_type, path in changes:
        if Path(path).name == ".gitignore":
            matcher_cache.pop(Path(path).parent, None)


class _ScanRulesSnapshot:
    """Polls ~/.mempalace/config.json mtime and refreshes ScanFilterRules per batch.

    Designed for use at debounce batch boundaries in watcher loops. Missing config,
    permission errors, and malformed JSON are handled gracefully — the last good rules
    are retained and the watcher keeps running.
    """

    def __init__(self, rules: ScanFilterRules) -> None:
        self._rules = rules
        self._config_path = Path(os.path.expanduser("~/.mempalace/config.json"))
        self._last_mtime: Optional[float] = self._read_mtime()
        self._bad_mtime: object = _UNSET

    def _read_mtime(self) -> Optional[float]:
        try:
            return self._config_path.stat().st_mtime
        except OSError:
            return None

    def refresh(self) -> ScanFilterRules:
        """Check config mtime; reload ScanFilterRules if the file changed.

        Returns the current (possibly refreshed) rules. Call once per watchfiles
        batch before relevance filtering. Safe without locks — ScanFilterRules is
        immutable and batches are processed sequentially.
        """
        current_mtime = self._read_mtime()
        if current_mtime == self._last_mtime:
            return self._rules
        if self._bad_mtime is not _UNSET and current_mtime == self._bad_mtime:
            return self._rules
        try:
            if self._config_path.exists():
                with open(self._config_path, encoding="utf-8") as f:
                    json.load(f)  # validate JSON before delegating to full reload
            self._rules = get_scan_filter_rules()
            self._last_mtime = current_mtime
            self._bad_mtime = _UNSET
        except (OSError, ValueError):
            self._bad_mtime = current_mtime
        return self._rules


def _is_relevant_change(
    path: str,
    project_path: Path,
    respect_gitignore: bool = True,
    include_ignored: Optional[list] = None,
    matcher_cache: Optional[dict] = None,
    scan_rules: Optional[ScanFilterRules] = None,
) -> bool:
    """Return True if the changed path should trigger a re-mine.

    Mirrors scan_project() filtering: READABLE_EXTENSIONS, KNOWN_FILENAMES,
    SKIP_FILENAMES, should_skip_dir() on parents, app-level scan_rules, gitignore,
    include_ignored. Works for deleted paths (no file-existence check required).
    """
    file_path = Path(path)
    filename = file_path.name

    # Ensure the changed path is inside the project directory
    try:
        relative = file_path.relative_to(project_path)
    except ValueError:
        return False

    include_paths = normalize_include_paths(include_ignored or [])

    # Reject files inside skip dirs (built-in or app-level), unless force-included.
    # Mirrors the dirs[:] pruning in scan_project().
    for i, part in enumerate(relative.parts[:-1]):
        parent_path = project_path.joinpath(*relative.parts[: i + 1])
        excluded_dir = should_skip_dir(part) or (
            scan_rules is not None and part in scan_rules.skip_dirs
        )
        if excluded_dir and not is_force_included(parent_path, project_path, include_paths):
            return False
        if (
            scan_rules is not None
            and is_dir_subtree_excluded(parent_path, project_path, scan_rules)
            and not is_force_included(parent_path, project_path, include_paths)
        ):
            return False

    force_include = is_force_included(file_path, project_path, include_paths)
    exact_force_include = is_exact_force_include(file_path, project_path, include_paths)

    # Reject known-skip filenames unless the file is explicitly force-included.
    if not force_include and filename in SKIP_FILENAMES:
        return False

    # Reject app-level file/glob excludes unless force-included.
    if scan_rules is not None and not force_include:
        if is_scan_excluded(file_path, project_path, scan_rules):
            return False

    # Reject files with non-readable extensions unless explicitly included or a known
    # special filename (Dockerfile, Makefile, etc.).
    if file_path.suffix.lower() not in READABLE_EXTENSIONS and not exact_force_include:
        if filename not in KNOWN_FILENAMES:
            return False

    # Check gitignore — builds ancestor-ordered matcher list from project root down.
    if respect_gitignore and not force_include:
        cache = matcher_cache if matcher_cache is not None else {}
        active_matchers = []
        try:
            current = project_path
            # Walk from project_path down to the file's immediate parent dir
            dirs_to_check = [project_path]
            for part in relative.parts[:-1]:
                current = current / part
                dirs_to_check.append(current)
            for d in dirs_to_check:
                m = load_gitignore_matcher(d, cache)
                if m is not None:
                    active_matchers.append(m)
        except Exception:
            pass

        if active_matchers and is_gitignored(file_path, active_matchers, is_dir=False):
            return False

    return True


def _make_run_id() -> str:
    """Generate a unique run identifier from UTC time and PID."""
    from datetime import UTC, datetime

    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-p{os.getpid()}"


def _emit_run_state(run_id: str, state: str, extra: str = "") -> None:
    """Emit a grep-friendly WATCH_RUN startup state line to stdout."""
    line = f"WATCH_RUN run_id={run_id} state={state}"
    if extra:
        line += f" {extra}"
    print(line, flush=True)


_SOURCE_DIAGNOSTIC_PREVIEW = 5


def _startup_source_discovery(
    project_path: Path,
    respect_gitignore: bool,
    include_ignored: Optional[list],
) -> tuple[int, list]:
    """Count regular sources and collect rejected-source diagnostics before mutation."""
    diagnostics: list = []
    files = scan_project(
        str(project_path),
        respect_gitignore=respect_gitignore,
        include_ignored=include_ignored,
        symlink_diagnostics=diagnostics,
    )
    return len(files), diagnostics


def _print_rejected_source_diagnostic(diagnostics: list) -> None:
    """Print bounded path-plus-kind diagnostics for rejected source candidates."""
    total = len(diagnostics)
    print(f"  Rejected {total} non-regular source(s):", flush=True)
    for entry in diagnostics[:_SOURCE_DIAGNOSTIC_PREVIEW]:
        print(f"    {entry['path']} ({entry['reason']})", flush=True)
    omitted = total - _SOURCE_DIAGNOSTIC_PREVIEW
    if omitted > 0:
        print(f"    (+{omitted} more)", flush=True)
    print(
        "    Remove or replace each path with a regular file, then rerun the watcher.",
        flush=True,
    )


@_with_watcher_lease
def watch_and_mine(
    project_dir: str,
    palace_path: str,
    wing_override: str | None = None,
    agent: str = "mempalace",
    respect_gitignore: bool = True,
    include_ignored: list | None = None,
    kg=None,
    operation_lock: OperationLock | None = None,
) -> None:
    """Watch *project_dir* for file changes and re-mine incrementally.

    Blocks until SIGTERM, POSIX SIGHUP, or KeyboardInterrupt (Ctrl-C). On exit, prints a
    one-line summary of cycles and events processed.

    Parameters match ``mine()`` (minus ``limit``, ``dry_run``, and
    ``incremental`` which are fixed in watch mode).

    Requires ``watchfiles`` (``pip install 'mempalace-code[watch]'``).
    """
    try:
        import watchfiles
    except ImportError:
        print(
            "  Error: 'watchfiles' is not installed.\n"
            "  Install it with:  pip install 'mempalace-code[watch]'\n"
            "  or:               pip install watchfiles",
            file=sys.stderr,
        )
        sys.exit(1)

    project_path = Path(project_dir).expanduser().resolve()

    if not project_path.is_dir():
        print(f"  Error: directory not found: {project_path}", file=sys.stderr)
        sys.exit(1)

    # Load app-level scan rules; snapshot polls config mtime at each batch boundary.
    scan_rules = get_scan_filter_rules()
    snapshot = _ScanRulesSnapshot(scan_rules)

    min_free = _load_watch_min_free()

    print(f"  Watching: {project_path}")
    print(f"  Palace:   {palace_path}")

    run_id = _make_run_id()
    _emit_run_state(run_id, "run-started")

    # Guarded startup source discovery — runs before pre-watch backup creation and
    # initial mine so rejected non-regular source nodes are diagnosed and excluded
    # before they can reach hashing.
    valid_source_count, source_diagnostics = _startup_source_discovery(
        project_path, respect_gitignore, include_ignored
    )
    if source_diagnostics:
        _print_rejected_source_diagnostic(source_diagnostics)
    invalid_only_startup = valid_source_count == 0 and bool(source_diagnostics)

    # Pre-watch backup: required when existing lance data is present.
    # Fail closed if backup creation fails so the initial mine cannot corrupt
    # the palace without a recoverable snapshot in place. Skipped entirely when
    # there are no valid regular sources — there is nothing safe to mine, so creating
    # an archive here would just churn on every restart.
    _local_kg_path = _palace_kg_path(palace_path)
    mining_store = _WatcherMiningStore(palace_path)
    pre_watch_archive: Optional[str] = None
    if not invalid_only_startup and _has_existing_lance_data(palace_path):
        try:
            _, pre_watch_archive = create_backup(
                palace_path, kind="pre_watch", kg_path=_local_kg_path
            )
            print(f"  Pre-watch backup: {pre_watch_archive}", flush=True)
        except Exception as exc:
            _emit_run_state(run_id, "pre-watch-backup-failed")
            print(
                f"  Error: pre-watch backup failed: {exc}\n  Watcher did not start.",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)

    print("  Initial mine...", flush=True)

    # Initial incremental mine — brings the palace up to date before watching.
    # Skip if disk budget is too low; still start the watcher so it re-checks each cycle.
    _last_budget_log: list = [None]  # mutable container for closure

    def _should_run() -> bool:
        budget = check_watch_budget(palace_path, min_free)
        if not budget.allowed:
            now = time.monotonic()
            if _last_budget_log[0] is None or now - _last_budget_log[0] >= _BUDGET_LOG_INTERVAL:
                msg = _format_budget_skip_message(budget, palace_path)
                print(msg, flush=True)
                _last_budget_log[0] = now
            return False
        return True

    if invalid_only_startup:
        _emit_run_state(run_id, "initial-mine-skipped", "reason=no-valid-sources")
    elif _should_run():
        _emit_run_state(run_id, "initial-mine-started")
        mine_kwargs = dict(
            project_dir=str(project_path),
            palace_path=palace_path,
            wing_override=wing_override,
            agent=agent,
            limit=0,
            dry_run=False,
            respect_gitignore=respect_gitignore,
            include_ignored=include_ignored,
            incremental=True,
            kg=kg,
            skip_optimize=True,
            kg_path=_local_kg_path,
        )
        stats = _run_initial_mine_with_recovery(
            mine_kwargs, palace_path, None, pre_watch_archive, mining_store
        )
        if stats is None:
            sys.exit(1)
        _emit_run_state(run_id, "initial-mine-completed")
        filed = stats.get("drawers_filed", 0)
        if filed:
            print(
                f"    {stats['files_processed']} file(s), {filed} drawer(s)",
                flush=True,
            )
            # Guarded optimize: only if drawers were filed and budget still allows it
            if _should_run():
                from .storage import open_store

                outcome = _optimize_once(
                    palace_path,
                    open_store,
                    kg_path=_local_kg_path,
                    store=mining_store.collection,
                )
                if outcome == "completed":
                    _emit_run_state(run_id, "optimize-completed")
                elif outcome == "skipped:backup-gate":
                    _emit_run_state(run_id, "optimize-skipped", "reason=backup-gate")
                else:
                    _emit_run_state(run_id, "optimize-skipped", "reason=error")
    else:
        _emit_run_state(run_id, "initial-mine-skipped", "reason=disk-budget")

    print("  Watching for changes... (Ctrl-C to stop)", flush=True)

    # Shared gitignore matcher cache — loaded lazily, keyed by directory Path.
    matcher_cache: dict = {}

    shutdown_signals = _WatcherShutdownSignals()
    shutdown_event = shutdown_signals.install()

    cycles = 0
    event_count = 0
    start_time = time.monotonic()

    try:
        _emit_run_state(run_id, "watch-ready")

        for changes in watchfiles.watch(
            str(project_path),
            debounce=5000,
            stop_event=shutdown_event,
        ):
            # Evict stale gitignore matchers before filtering — same-batch events
            # (e.g. .gitignore change + affected file) must see fresh state.
            _invalidate_gitignore_cache(changes, matcher_cache)

            # Refresh scan rules once per batch before relevance filtering.
            scan_rules = snapshot.refresh()

            # Discard irrelevant OS events (compiled files, git internals, etc.)
            relevant = [
                (change_type, path)
                for change_type, path in changes
                if _is_relevant_change(
                    path,
                    project_path,
                    respect_gitignore=respect_gitignore,
                    include_ignored=include_ignored,
                    matcher_cache=matcher_cache,
                    scan_rules=scan_rules,
                )
            ]

            if not relevant:
                continue

            # Budget check before re-mine — skip whole cycle if disk is low.
            if not _should_run():
                continue

            stats = _run_watcher_mine(
                {
                    "project_dir": str(project_path),
                    "palace_path": palace_path,
                    "wing_override": wing_override,
                    "agent": agent,
                    "limit": 0,
                    "dry_run": False,
                    "respect_gitignore": respect_gitignore,
                    "include_ignored": include_ignored,
                    "incremental": True,
                    "kg": kg,
                    "skip_optimize": True,
                    "kg_path": _local_kg_path,
                },
                mining_store,
            )
            filed = stats.get("drawers_filed", 0)
            if filed:
                names = [Path(p).name for _, p in relevant]
                preview = ", ".join(names[:3])
                if len(relevant) > 3:
                    preview += f" (+{len(relevant) - 3} more)"
                secs = stats.get("elapsed_secs", 0)
                print(
                    f"  [{len(relevant)} change(s): {preview}] "
                    f"{stats['files_processed']} file(s), "
                    f"{filed} drawer(s) ({secs:.0f}s)",
                    flush=True,
                )
                # Guarded optimize after batch
                if _should_run():
                    from .storage import open_store

                    _optimize_once(
                        palace_path,
                        open_store,
                        kg_path=_local_kg_path,
                        store=mining_store.collection,
                    )
            cycles += 1
            event_count += len(relevant)

    except KeyboardInterrupt:
        pass
    finally:
        shutdown_signals.restore()

    elapsed = time.monotonic() - start_time
    print(
        f"\n  Watch stopped after {elapsed:.0f}s — "
        f"{cycles} re-mine cycle(s), {event_count} file event(s)."
    )


def _optimize_once(
    palace_path: str,
    open_store_fn,
    kg_path: Optional[str] = None,
    *,
    store=None,
) -> str:
    """Run a single optimize pass; return 'completed', 'skipped:backup-gate', or 'skipped:error'."""
    from .config import MempalaceConfig

    try:
        t0 = time.time()
        print("  >> Optimizing storage...", end="", flush=True)
        if store is None:
            store = open_store_fn(palace_path, create=False)
        config = MempalaceConfig()
        result = optimize_store(
            store, palace_path, backup_first=config.backup_before_optimize, kg_path=kg_path
        )
        if not result.ok:
            print(" skipped (backup gate failed)", flush=True)
            return "skipped:backup-gate"
        print(f" done ({time.time() - t0:.1f}s)", flush=True)
        return "completed"
    except Exception as exc:
        print(f" skipped ({exc})", flush=True)
        return "skipped:error"


def _quiet_mine(**kwargs) -> dict:
    """Run mine() with stdout/stderr suppressed; return stats dict."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_out = os.dup(1)
    old_err = os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        return mine(**kwargs) or {}
    finally:
        # Flush Python buffers while fds still point to /dev/null,
        # otherwise buffered text leaks to real stdout on restore.
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(old_out, 1)
        os.dup2(old_err, 2)
        os.close(devnull)
        os.close(old_out)
        os.close(old_err)


def _run_watcher_mine(mine_kwargs: dict, mining_store: _WatcherMiningStore) -> dict:
    """Run mine() with one watcher-owned store and record a successful warmup."""
    kwargs = dict(mine_kwargs)
    kwargs.update(mining_store.mine_kwargs())
    stats = _quiet_mine(**kwargs) or {}
    mining_store.note_mine(stats)
    return stats


def _has_existing_lance_data(palace_path: str) -> bool:
    """Return True when <palace_path>/lance/ exists and contains at least one entry."""
    lance_dir = Path(palace_path) / "lance"
    if not lance_dir.is_dir():
        return False
    try:
        return next(lance_dir.iterdir(), None) is not None
    except OSError:
        return False


def _is_mine_missing_fragment(exc: Exception, palace_path: str) -> bool:
    """Return True when the exception looks like a Lance missing-fragment error.

    Excludes Python FileNotFoundError raised for paths outside the palace's lance directory —
    those come from source files the miner tried to read, not from Lance internals.
    """
    msg = str(exc).lower()
    if not any(s in msg for s in ("no such file", "object not found", "io error", "not found")):
        return False
    # A Python FileNotFoundError whose filename is outside <palace>/lance/ is a
    # source-file read failure, not a Lance fragment error — don't roll back the palace.
    if isinstance(exc, FileNotFoundError) and exc.filename:
        lance_dir = str(Path(palace_path) / "lance")
        if not str(exc.filename).startswith(lance_dir):
            return False
    return True


def _print_recovery_commands(palace_path: str, pre_watch_archive: Optional[str]) -> None:
    """Print operator-safe recovery commands for degraded watcher startup."""
    q_palace = shlex.quote(palace_path)
    print("  To diagnose and recover, run:", flush=True)
    print(f"    mempalace-code --palace {q_palace} health", flush=True)
    print(f"    mempalace-code --palace {q_palace} repair --rollback --dry-run", flush=True)
    if pre_watch_archive:
        q_archive = shlex.quote(pre_watch_archive)
        print(
            f"    mempalace-code --palace {q_palace} restore {q_archive} --force",
            flush=True,
        )
    print("  Watcher did not start.", flush=True)


def _run_initial_mine_with_recovery(
    mine_kwargs: dict,
    palace_path: str,
    wing_label: Optional[str],
    pre_watch_archive: Optional[str],
    mining_store: Optional[_WatcherMiningStore] = None,
) -> Optional[dict]:
    """Run initial mine; on Lance missing-fragment error attempt rollback and retry once.

    Returns the stats dict on success, or None when the failure is unrecoverable
    (caller must call sys.exit after printing their own context if needed).
    Non-missing-fragment exceptions also return None without triggering rollback.
    """
    wing_prefix = f" [{wing_label}]" if wing_label else ""

    def run_mine() -> dict:
        if mining_store is None:
            return _quiet_mine(**mine_kwargs) or {}
        return _run_watcher_mine(mine_kwargs, mining_store)

    try:
        return run_mine()
    except Exception as exc:
        if not _is_mine_missing_fragment(exc, palace_path):
            print(
                f"  Error{wing_prefix}: initial mine failed: {exc}",
                file=sys.stderr,
                flush=True,
            )
            return None

        # Missing-fragment error: surface a DEGRADED state and attempt Lance rollback.
        print(
            f"  DEGRADED{wing_prefix}: Lance missing-fragment error during initial mine.",
            flush=True,
        )
        if pre_watch_archive:
            print(f"  Pre-watch backup: {pre_watch_archive}", flush=True)
        print("  Attempting recovery...", flush=True)

        try:
            from .storage import open_store

            store = open_store(palace_path, create=False, read_only=False)
            result = store.recover_to_last_working_version(dry_run=False)  # type: ignore[reportAttributeAccessIssue]  # reason: open_store returns Store; LanceStore method only reachable here
        except Exception as rec_exc:
            print(f"  Recovery failed: {rec_exc}", file=sys.stderr, flush=True)
            _print_recovery_commands(palace_path, pre_watch_archive)
            return None

        if not result.get("recovered"):
            print("  Recovery: no prior healthy version found.", flush=True)
            _print_recovery_commands(palace_path, pre_watch_archive)
            return None

        print(
            f"  Recovery: rolled back to version {result.get('restored_to')}, "
            f"{result.get('rows_after')} row(s). Retrying initial mine...",
            flush=True,
        )

        if mining_store is not None:
            mining_store.recreate()

        try:
            return run_mine()
        except Exception as retry_exc:
            print(
                f"  Retry{wing_prefix} failed after rollback: {retry_exc}",
                file=sys.stderr,
                flush=True,
            )
            _print_recovery_commands(palace_path, pre_watch_archive)
            return None


def _resolve_git_watch_paths(project_map: dict) -> dict:
    """Build a mapping from .git/refs/heads/ paths to project paths.

    Returns {git_refs_path: proj_path} for projects that have a .git/refs/heads/ dir.
    Projects without git are silently skipped.
    """
    git_to_project: dict = {}
    for proj_path in project_map:
        refs_dir = proj_path / ".git" / "refs" / "heads"
        if refs_dir.is_dir():
            git_to_project[refs_dir] = proj_path
    return git_to_project


@_with_watcher_lease
def watch_all(
    parent_dir: str,
    palace_path: str,
    agent: str = "mempalace",
    respect_gitignore: bool = True,
    on_commit: bool = True,
    operation_lock: OperationLock | None = None,
) -> None:
    """Watch initialized projects under *parent_dir* (or *parent_dir* itself) and re-mine on changes.

    When *parent_dir* is itself an initialized project (contains ``mempalace.yaml`` or
    ``mempal.yaml``), it is watched as a single project.  When it is a plain parent
    directory, all immediate child directories that are initialized projects are watched.
    Uninitialized project roots (project markers present but no init file) cause an
    actionable diagnostic and exit 1.

    When *on_commit* is True (default), only watches ``.git/refs/heads/`` for
    each project — triggers re-mine only when a commit, merge, or rebase occurs.
    This avoids re-mining half-written work-in-progress files.

    When *on_commit* is False, watches the full project tree and re-mines on
    any file save (5s debounce).

    Blocks until SIGTERM, POSIX SIGHUP, or KeyboardInterrupt.

    Requires ``watchfiles`` (``pip install 'mempalace-code[watch]'``).
    """
    try:
        import watchfiles
    except ImportError:
        print(
            "  Error: 'watchfiles' is not installed.\n"
            "  Install it with:  pip install 'mempalace-code[watch]'\n"
            "  or:               pip install watchfiles",
            file=sys.stderr,
        )
        sys.exit(1)

    from .knowledge_graph import KnowledgeGraph
    from .mining.projects import classify_project_root, detect_projects, resolve_wing_for_project
    from .storage import open_store

    parent_path = Path(parent_dir).expanduser().resolve()
    if not parent_path.is_dir():
        print(f"  Error: directory not found: {parent_path}", file=sys.stderr)
        sys.exit(1)

    root_kind, _ = classify_project_root(parent_path)

    if root_kind == "initialized":
        # Supplied directory is itself an initialized project — watch it directly.
        try:
            wing = resolve_wing_for_project(str(parent_path))
        except ValueError as exc:
            print(f"  ERROR  {parent_path.name}: {exc}", file=sys.stderr)
            sys.exit(1)
        project_map: dict = {parent_path: wing}
    elif root_kind == "project":
        # Has project markers but no mempalace init — print actionable diagnostic.
        print(
            f"  Error: {parent_path} is a project directory but has not been initialized.\n"
            f"  Run:  mempalace-code init {parent_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        # Plain parent directory — scan immediate child projects (existing behavior).
        projects = detect_projects(str(parent_path))
        initialized_list = [p for p in projects if p["initialized"]]

        if not initialized_list:
            print(f"  No initialized projects found in {parent_path}")
            print("  Run 'mempalace-code init <dir>' on projects first.")
            sys.exit(1)

        # Build project path -> wing name mapping using config-aware resolver.
        project_map = {}
        config_error_count = 0
        for proj in initialized_list:
            proj_path = Path(proj["path"]).resolve()
            try:
                wing = resolve_wing_for_project(proj["path"])
                project_map[proj_path] = wing
            except ValueError as exc:
                print(f"  ERROR  {proj_path.name}: {exc}", file=sys.stderr)
                config_error_count += 1

        if config_error_count:
            print(
                f"  {config_error_count} project(s) had config parse errors — fix them and retry.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Guard against duplicate wings — two repos mapped to the same wing would
        # silently corrupt the palace on every re-mine.
        wing_to_paths: dict = {}
        for pp, wing in project_map.items():
            wing_to_paths.setdefault(wing, []).append(pp)

        duplicate_wings = {w: paths for w, paths in wing_to_paths.items() if len(paths) > 1}
        if duplicate_wings:
            for w, paths in sorted(duplicate_wings.items()):
                path_list = ", ".join(str(p) for p in paths)
                print(
                    f"  ERROR  duplicate wing '{w}': {path_list}\n"
                    f"         Configure a unique 'wing:' in each project's mempalace.yaml.",
                    file=sys.stderr,
                )
            sys.exit(1)

    min_free = _load_watch_min_free()
    _last_budget_log_all: list = [None]

    def _should_run_all() -> bool:
        budget = check_watch_budget(palace_path, min_free)
        if not budget.allowed:
            now = time.monotonic()
            if (
                _last_budget_log_all[0] is None
                or now - _last_budget_log_all[0] >= _BUDGET_LOG_INTERVAL
            ):
                msg = _format_budget_skip_message(budget, palace_path)
                print(msg, flush=True)
                _last_budget_log_all[0] = now
            return False
        return True

    mode_label = "on commit" if on_commit else "on file save"
    print(f"  Watching {len(project_map)} project(s) ({mode_label}):")
    for pp in sorted(project_map):
        print(f"    {pp.name} -> {project_map[pp]}")
    print(f"  Palace: {palace_path}")

    run_id = _make_run_id()
    _emit_run_state(run_id, "run-started")

    # Guarded per-project startup source discovery — runs before the shared pre-watch
    # backup so rejected non-regular source nodes are diagnosed and excluded before
    # they can reach hashing. Projects with no valid regular sources are skipped for
    # initial mining below.
    project_valid_counts: dict = {}
    project_diagnostics: dict = {}
    any_valid_source = False
    for proj_path, wing in project_map.items():
        valid_count, diagnostics = _startup_source_discovery(proj_path, respect_gitignore, None)
        project_valid_counts[proj_path] = valid_count
        project_diagnostics[proj_path] = diagnostics
        if diagnostics:
            print(f"  [{wing}]", flush=True)
            _print_rejected_source_diagnostic(diagnostics)
        if valid_count > 0:
            any_valid_source = True
    invalid_only_startup = not any_valid_source and any(project_diagnostics.values())

    _all_local_kg_path = _palace_kg_path(palace_path)
    mining_store = _WatcherMiningStore(palace_path)
    # Pre-watch backup: one archive before the initial multi-project batch.
    # Fail closed if backup creation fails. Skipped entirely when there are no valid
    # regular sources across projects — there is nothing safe to mine.
    pre_watch_archive: Optional[str] = None
    if not invalid_only_startup and _has_existing_lance_data(palace_path):
        try:
            _, pre_watch_archive = create_backup(
                palace_path, kind="pre_watch", kg_path=_all_local_kg_path
            )
            print(f"  Pre-watch backup: {pre_watch_archive}", flush=True)
        except Exception as exc:
            _emit_run_state(run_id, "pre-watch-backup-failed")
            print(
                f"  Error: pre-watch backup failed: {exc}\n  Watcher did not start.",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)

    # Initial incremental mine for all projects — quiet, with a summary line
    # per project that actually had changes.
    print("  Initial mine...", flush=True)
    total_init_filed = 0
    if invalid_only_startup:
        _emit_run_state(run_id, "initial-mine-skipped", "reason=no-valid-sources")
    elif _should_run_all():
        _emit_run_state(run_id, "initial-mine-started")
        for proj_path, wing in project_map.items():
            if project_valid_counts[proj_path] == 0 and project_diagnostics[proj_path]:
                # Invalid-only project: nothing safe to mine, skip just this one.
                continue
            kg = KnowledgeGraph(db_path=_all_local_kg_path)
            mine_kwargs = dict(
                project_dir=str(proj_path),
                palace_path=palace_path,
                wing_override=wing,
                agent=agent,
                limit=0,
                dry_run=False,
                respect_gitignore=respect_gitignore,
                incremental=True,
                kg=kg,
                skip_optimize=True,
                kg_path=_all_local_kg_path,
            )
            stats = _run_initial_mine_with_recovery(
                mine_kwargs, palace_path, wing, pre_watch_archive, mining_store
            )
            if stats is None:
                sys.exit(1)
            filed = stats.get("drawers_filed", 0)
            total_init_filed += filed
            if filed:
                print(
                    f"    {wing}: {stats['files_processed']} file(s), {filed} drawer(s)",
                    flush=True,
                )
        _emit_run_state(run_id, "initial-mine-completed")
    else:
        _emit_run_state(run_id, "initial-mine-skipped", "reason=disk-budget")

    # Single guarded optimize after all initial mines (only if something was filed)
    if total_init_filed and _should_run_all():
        outcome = _optimize_once(
            palace_path,
            open_store,
            kg_path=_all_local_kg_path,
            store=mining_store.collection,
        )
        if outcome == "completed":
            _emit_run_state(run_id, "optimize-completed")
        elif outcome == "skipped:backup-gate":
            _emit_run_state(run_id, "optimize-skipped", "reason=backup-gate")
        else:
            _emit_run_state(run_id, "optimize-skipped", "reason=error")

    print("  Watching for changes... (Ctrl-C to stop)", flush=True)

    # Determine what to watch
    if on_commit:
        git_to_project = _resolve_git_watch_paths(project_map)
        if not git_to_project:
            print("  Error: no git repos found among initialized projects.", file=sys.stderr)
            sys.exit(1)
        watch_paths = [str(p) for p in git_to_project]
        skipped = len(project_map) - len(git_to_project)
        if skipped:
            print(f"  ({skipped} project(s) without .git skipped)")
    else:
        watch_paths = [str(p) for p in project_map]
        git_to_project = {}
        # Warn about high-churn directories found as immediate children of each project root.
        # A recursive watch still observes the whole tree; this informs the operator to prefer
        # on-commit mode for high-churn trees. Shallow check only — no recursive pre-walk.
        for proj_path in sorted(project_map):
            churn_found = sorted(d for d in SKIP_DIRS if (proj_path / d).is_dir())
            if churn_found:
                preview = ", ".join(churn_found[:6])
                suffix = f" (+{len(churn_found) - 6} more)" if len(churn_found) > 6 else ""
                print(
                    f"  Warning: [{proj_path.name}] high-churn directories detected: "
                    f"{preview}{suffix}.\n"
                    "    Events from these directories are filtered but FSEvents still observes\n"
                    "    the entire tree. Use on-commit mode (default) for large dependency trees.",
                    flush=True,
                )

    # Load app-level scan rules; snapshot polls config mtime at each batch boundary.
    scan_rules = get_scan_filter_rules()
    snapshot = _ScanRulesSnapshot(scan_rules)

    matcher_cache: dict = {}
    shutdown_signals = _WatcherShutdownSignals()
    shutdown_event = shutdown_signals.install()

    cycles = 0
    event_count = 0
    start_time = time.monotonic()

    # In on-commit mode we watch .git/refs/heads/ dirs — the default
    # watchfiles filter ignores .git, so we disable it entirely.
    # In on-save mode, extend the default ignore dirs with the miner's SKIP_DIRS catalog
    # so that events from high-churn dependency/build/cache dirs are dropped at the
    # watchfiles layer rather than reaching Python-level relevance filtering.
    if on_commit:
        commit_filter = None
    else:
        _default_ignore = frozenset(getattr(watchfiles.DefaultFilter, "ignore_dirs", ()))
        commit_filter = watchfiles.DefaultFilter(
            ignore_dirs=tuple(_default_ignore | frozenset(SKIP_DIRS))
        )

    try:
        _emit_run_state(run_id, "watch-ready")

        for changes in watchfiles.watch(
            *watch_paths,
            watch_filter=commit_filter,
            debounce=5000,
            stop_event=shutdown_event,
        ):
            batch_filed = 0

            if on_commit:
                # In on-commit mode, any change under .git/refs/heads/ means
                # a commit happened. Find which project(s) and re-mine them.
                triggered: dict = {}  # proj_path -> wing
                for _change_type, path in changes:
                    file_path = Path(path)
                    for refs_dir, proj_path in git_to_project.items():
                        try:
                            file_path.relative_to(refs_dir)
                            triggered[proj_path] = project_map[proj_path]
                        except ValueError:
                            continue

                # Budget check before re-mine batch
                if not _should_run_all():
                    continue

                for proj_path, wing in triggered.items():
                    kg = KnowledgeGraph(db_path=_all_local_kg_path)
                    stats = _run_watcher_mine(
                        {
                            "project_dir": str(proj_path),
                            "palace_path": palace_path,
                            "wing_override": wing,
                            "agent": agent,
                            "limit": 0,
                            "dry_run": False,
                            "respect_gitignore": respect_gitignore,
                            "incremental": True,
                            "kg": kg,
                            "skip_optimize": True,
                            "kg_path": _all_local_kg_path,
                        },
                        mining_store,
                    )
                    filed = stats.get("drawers_filed", 0)
                    batch_filed += filed
                    if filed:
                        secs = stats.get("elapsed_secs", 0)
                        print(
                            f"  [commit in {wing}] "
                            f"{stats['files_processed']} file(s), "
                            f"{filed} drawer(s) ({secs:.0f}s)",
                            flush=True,
                        )
                    cycles += 1
                    event_count += 1
            else:
                # File-save mode: filter and group by project
                _invalidate_gitignore_cache(changes, matcher_cache)

                # Refresh scan rules once per batch before relevance filtering.
                scan_rules = snapshot.refresh()

                by_project: dict = {}
                for change_type, path in changes:
                    file_path = Path(path)
                    for proj_path in project_map:
                        try:
                            file_path.relative_to(proj_path)
                        except ValueError:
                            continue
                        if _is_relevant_change(
                            path,
                            proj_path,
                            respect_gitignore=respect_gitignore,
                            matcher_cache=matcher_cache,
                            scan_rules=scan_rules,
                        ):
                            by_project.setdefault(proj_path, []).append((change_type, path))
                        break

                if not by_project:
                    continue

                # Budget check before re-mine batch
                if not _should_run_all():
                    continue

                for proj_path, relevant in by_project.items():
                    wing = project_map[proj_path]
                    kg = KnowledgeGraph(db_path=_all_local_kg_path)
                    stats = _run_watcher_mine(
                        {
                            "project_dir": str(proj_path),
                            "palace_path": palace_path,
                            "wing_override": wing,
                            "agent": agent,
                            "limit": 0,
                            "dry_run": False,
                            "respect_gitignore": respect_gitignore,
                            "incremental": True,
                            "kg": kg,
                            "skip_optimize": True,
                            "kg_path": _all_local_kg_path,
                        },
                        mining_store,
                    )
                    filed = stats.get("drawers_filed", 0)
                    batch_filed += filed
                    if filed:
                        secs = stats.get("elapsed_secs", 0)
                        print(
                            f"  [{wing}: {len(relevant)} change(s)] "
                            f"{stats['files_processed']} file(s), "
                            f"{filed} drawer(s) ({secs:.0f}s)",
                            flush=True,
                        )
                    cycles += 1
                    event_count += len(relevant)

            # Guarded optimize: only when something was filed and budget still allows it
            if batch_filed and _should_run_all():
                _optimize_once(
                    palace_path,
                    open_store,
                    kg_path=_all_local_kg_path,
                    store=mining_store.collection,
                )

    except KeyboardInterrupt:
        pass
    finally:
        shutdown_signals.restore()

    elapsed = time.monotonic() - start_time
    print(
        f"\n  Watch stopped after {elapsed:.0f}s — "
        f"{cycles} re-mine cycle(s), {event_count} event(s) "
        f"across {len(project_map)} project(s)."
    )


def render_watch_schedule(
    parent_dir: str,
    platform: str,
    mempalace_bin: Optional[str] = None,
) -> str:
    """Render a scheduler snippet (launchd plist or cron) for ``mempalace-code watch``.

    Parameters
    ----------
    parent_dir:
        Parent directory to watch (passed to ``mempalace-code watch <dir>``).
    platform:
        'darwin' for launchd plist, 'linux' for cron @reboot line.
    mempalace_bin:
        Override the mempalace-code binary path (default: invoked launcher, then PATH).

    Returns
    -------
    str
        Launchd plist XML (darwin) or cron @reboot line (linux).
    """
    import shlex as _shlex
    import shutil as _shutil

    if platform not in ("darwin", "linux"):
        raise ValueError(f"Unsupported platform {platform!r}; must be 'darwin' or 'linux'")

    if mempalace_bin is None:
        from .cli_commands.alias import resolve_invoked_canonical_cli

        invoked_bin = resolve_invoked_canonical_cli()
        resolved_bin = (
            str(invoked_bin) if invoked_bin is not None else _shutil.which("mempalace-code")
        )
        if resolved_bin is None:
            safe_bin = f"{_shlex.quote(sys.executable)} -m mempalace_code"
        else:
            safe_bin = _shlex.quote(resolved_bin)
    else:
        safe_bin = _shlex.quote(mempalace_bin)

    watch_root = Path(parent_dir).expanduser().resolve()

    # Validate root — refuse uninitialized roots that would crash-loop under KeepAlive.
    # Only validates when the directory already exists; future directories are allowed.
    if watch_root.is_dir():
        from .mining.projects import classify_project_root, detect_projects

        root_kind, _ = classify_project_root(watch_root)
        if root_kind == "project":
            raise ValueError(
                f"{watch_root} is a project directory but has not been initialized.\n"
                f"  Run:  {safe_bin} init {_shlex.quote(str(watch_root))}"
            )
        if root_kind == "parent":
            projects = detect_projects(str(watch_root))
            if not any(p.get("initialized") for p in projects):
                raise ValueError(
                    f"{watch_root} has no initialized MemPalace projects as immediate children.\n"
                    "  Supported watch roots:\n"
                    "    - An initialized project directory (contains mempalace.yaml)\n"
                    "    - A parent directory with at least one initialized immediate child project\n"
                    f"  Run {safe_bin} init <dir> on a project under "
                    f"{_shlex.quote(str(watch_root))} first."
                )

    safe_dir = _shlex.quote(str(watch_root))

    cmd = f"{safe_bin} watch {safe_dir}"

    if platform == "linux":
        return f"@reboot {cmd}\n"

    # darwin: launchd plist — long-running daemon, KeepAlive + RunAtLoad
    def _xml_escape(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    label = "com.mempalace.watch"
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
        '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{label}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        "        <string>/bin/sh</string>\n"
        "        <string>-c</string>\n"
        f"        <string>{_xml_escape(cmd)}</string>\n"
        "    </array>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "    <key>KeepAlive</key>\n"
        "    <true/>\n"
        "    <key>ThrottleInterval</key>\n"
        "    <integer>60</integer>\n"
        "    <key>StandardOutPath</key>\n"
        "    <string>/tmp/mempalace-watch.log</string>\n"
        "    <key>StandardErrorPath</key>\n"
        "    <string>/tmp/mempalace-watch.log</string>\n"
        "</dict>\n"
        "</plist>\n"
    )
    return plist
