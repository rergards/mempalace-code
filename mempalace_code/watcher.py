"""watcher.py — File watcher for auto-incremental mining.

Provides ``watch_and_mine()`` (single project) and ``watch_all()`` (multi-project),
plus ``render_watch_schedule()`` for generating launchd/cron daemon configs.

Uses the ``watchfiles`` library (Rust-backed, uses fsevents/inotify — no polling).

Install the optional extra before use:
    pip install 'mempalace-code[watch]'
"""

import hashlib
import importlib.util
import json
import os
import re
import shlex
import signal
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from functools import partial, wraps
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, NoReturn, Optional

if TYPE_CHECKING:
    from types import FrameType

from .backup import BackupSourceError, create_backup
from .config import MempalaceConfig
from .disk_budget import DiskBudgetStatus, check_watch_budget, format_bytes
from .knowledge_graph import palace_kg_path as _palace_kg_path
from .launchd import daemon_environment, launchd_label, launchd_log_path
from .mining.orchestrator import get_collection, mine
from .mining.projects import INIT_MARKERS
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
    is_shebang_script,
    load_gitignore_matcher,
    normalize_include_paths,
    scan_project,
    should_skip_dir,
)
from .operation_lock import (
    OperationLock,
    OperationLockedError,
    PalaceBusyError,
    owner_palace_kwargs,
    palace_write_lease,
)
from .storage import extra_install_command, optimize_store

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows has no advisory flock
    _fcntl = None  # type: ignore[assignment]  # reason: None is the intended platform sentinel

_UNSET: object = object()  # sentinel for _ScanRulesSnapshot._bad_mtime

# Throttle: print disk-budget skip message at most once per this many seconds.
_BUDGET_LOG_INTERVAL = 300  # 5 minutes

# Idle watch loops wake this often to notice a removed or de-initialized project.
_LIVENESS_CHECK_MS = 10_000
# watchfiles.Change values, compared by value so the module imports without watchfiles.
_CHANGE_MODIFIED = 2
_CHANGE_DELETED = 3
# Desktop metadata files that are never sources nor directories.
_OS_METADATA_NAMES = frozenset({".DS_Store", ".localized"})


class _IndexedSourcePrefixes:
    """Answer "does the palace hold sources under this vanished path?" once per batch.

    A vanished dotted name (``lib.v2``, ``config.d``) looks like a file with an
    unreadable suffix, but it may have been a directory whose drawers must be swept.
    Only the palace knows, so its source paths are read lazily, at most once per batch,
    and only when such a path appears. Any read failure answers True: one extra
    incremental cycle is safer than leaving moved-away sources searchable.
    """

    def __init__(self, mining_store: "_WatcherMiningStore") -> None:
        self._mining_store = mining_store
        self._sources: Optional[list[str]] = None
        self._failed = False

    def __call__(self, path: str) -> bool:
        if self._sources is None and not self._failed:
            try:
                self._sources = list(self._mining_store.collection.count_by("source_file"))
            except Exception:
                self._failed = True
        if self._failed or self._sources is None:
            return True
        prefixes = {path.rstrip(os.sep) + os.sep, os.path.realpath(path).rstrip(os.sep) + os.sep}
        return any(source.startswith(tuple(prefixes)) for source in self._sources)


class _MineCapture:
    """The real stdout descriptor while :func:`_quiet_mine` captures mine() output."""

    stdout_fd: Optional[int] = None


_STOP_ACKNOWLEDGEMENT = b"  Stop requested; finishing the current batch before exiting...\n"


def _acknowledge_stop() -> None:
    """Tell the operator promptly that a stop arrived while a mine is running.

    mine() output is captured during a watcher mine, so its own ``Interrupted`` line is
    never shown and a long batch flush would otherwise look like a hang.
    """
    fd = _MineCapture.stdout_fd
    if fd is None:
        return
    try:
        os.write(fd, _STOP_ACKNOWLEDGEMENT)
    except OSError:
        pass


class _WatcherShutdownSignals:
    """Install and restore the supported graceful watcher signal handlers.

    Handlers are installed before the startup backup and initial mine. Until
    :meth:`start_watching` is called a signal raises KeyboardInterrupt once, so a long
    startup stops like Ctrl-C and its leases are released; afterwards it only sets the
    event that ends the watch loop. Ctrl-C (SIGINT) keeps raising KeyboardInterrupt, and
    any stop that arrives during a mine is acknowledged before its batch flush ends.
    """

    def __init__(self) -> None:
        self.event = threading.Event()
        self._watching = False
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
            first = not self.event.is_set()
            self.event.set()
            if first:
                _acknowledge_stop()
            if first and not self._watching:
                raise KeyboardInterrupt

        def handle_interrupt(_signum, _frame) -> None:
            _acknowledge_stop()
            raise KeyboardInterrupt

        handlers: list = [(sig, handle_shutdown) for sig in supported_signals]
        # Only replace Python's default Ctrl-C handler; an ignored SIGINT stays ignored.
        if signal.getsignal(signal.SIGINT) is signal.default_int_handler:
            handlers.append((signal.SIGINT, handle_interrupt))
        try:
            for shutdown_signal, handler in handlers:
                original_handler = signal.getsignal(shutdown_signal)
                signal.signal(shutdown_signal, handler)
                self._original_handlers.append((shutdown_signal, original_handler))
        except Exception:
            self.restore()
            raise
        return self.event

    def start_watching(self) -> threading.Event:
        """Switch from startup to the watch loop, where a signal only sets the event."""
        self._watching = True
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
        palace = kwargs.get("palace_path") or (args[1] if len(args) > 1 else None)
        try:
            lease = operation_lock.acquire_shared(
                "watcher", **owner_palace_kwargs(operation_lock, palace)
            )
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


def _format_budget_skip_message(
    status: DiskBudgetStatus, palace_path: str, watch_root: Optional[Path] = None
) -> str:
    """Build the actionable disk-budget skip message for watcher cycles."""
    root = shlex.quote(str(watch_root)) if watch_root is not None else "<dir>"
    lines = [
        "  [disk budget] Skipping watcher cycle — not enough free disk space.",
        f"  Palace:   {palace_path}",
        f"  Free:     {format_bytes(status.free_bytes)} (need {format_bytes(status.min_free_bytes)})",
        f"  Palace:   {format_bytes(status.palace_bytes)} used,"
        f" backups: {format_bytes(status.backups_bytes)} used",
        f"  To stop:  mempalace-code watch {root} status  (names the launchctl job to stop)",
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
    indexed_under: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Return True if the changed path should trigger a re-mine.

    Mirrors scan_project() filtering: READABLE_EXTENSIONS, KNOWN_FILENAMES,
    extension-less shebang scripts, SKIP_FILENAMES, should_skip_dir() on parents,
    app-level scan_rules, gitignore, include_ignored. Works for deleted paths with a
    recognised name.

    A directory renamed, moved in, or moved out produces one event for the directory
    itself, not one per file, so directories are relevant too: an existing directory
    when it holds a relevant file, and a vanished extension-less path (a moved-away
    directory or a deleted shebang script) when its name is not skipped or ignored. A
    vanished dotted name such as ``lib.v2`` counts when *indexed_under* reports that the
    palace holds sources under it.
    The re-mine that follows sweeps every source that no longer exists.
    """
    file_path = Path(path)
    filename = file_path.name

    # Ensure the changed path is inside the project directory
    try:
        relative = file_path.relative_to(project_path)
    except ValueError:
        return False

    include_paths = normalize_include_paths(include_ignored, project_path)

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

    is_directory = file_path.is_dir() and not file_path.is_symlink()
    vanished = (
        filename not in KNOWN_FILENAMES
        and filename not in _OS_METADATA_NAMES
        and not os.path.lexists(path)
    )
    # A vanished dotted name (lib.v2, config.d) is a directory candidate only when the
    # palace holds sources under it; otherwise it is a deleted non-source file (x.pyc).
    vanished_dir_candidate = vanished and (
        not file_path.suffix
        or (
            file_path.suffix.lower() not in READABLE_EXTENSIONS
            and indexed_under is not None
            and indexed_under(path)
        )
    )
    if is_directory or vanished_dir_candidate:
        return _is_relevant_directory_change(
            file_path,
            project_path,
            relative,
            exists=is_directory,
            force_include=force_include,
            respect_gitignore=respect_gitignore,
            include_ignored=include_ignored,
            matcher_cache=matcher_cache,
            scan_rules=scan_rules,
        )

    # Reject files with non-readable extensions unless explicitly included or a known
    # special filename (Dockerfile, Makefile, etc.). Extension-less files are decided
    # by their shebang after the gitignore check, as in scan_project().
    source_name = (
        file_path.suffix.lower() in READABLE_EXTENSIONS
        or filename in KNOWN_FILENAMES
        or exact_force_include
    )
    if not source_name and file_path.suffix:
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

    return source_name or is_shebang_script(file_path)


def _is_relevant_directory_change(
    dir_path: Path,
    project_path: Path,
    relative: Path,
    *,
    exists: bool,
    force_include: bool,
    respect_gitignore: bool,
    include_ignored: Optional[list],
    matcher_cache: Optional[dict],
    scan_rules: Optional[ScanFilterRules],
) -> bool:
    """Decide a directory event (or a vanished directory candidate) like scan_project().

    The directory itself must survive the skip-dir, subtree-exclude, and gitignore rules.
    An existing directory is relevant only when it holds at least one relevant file, so
    creating an empty or ignored directory does not start a cycle.
    """
    if relative == Path("."):
        return False
    if not force_include:
        if should_skip_dir(dir_path.name) or (
            scan_rules is not None and dir_path.name in scan_rules.skip_dirs
        ):
            return False
        if scan_rules is not None and is_dir_subtree_excluded(dir_path, project_path, scan_rules):
            return False
        if respect_gitignore:
            cache = matcher_cache if matcher_cache is not None else {}
            matchers = []
            current = project_path
            dirs_to_check = [project_path]
            for part in relative.parts[:-1]:
                current = current / part
                dirs_to_check.append(current)
            try:
                for directory in dirs_to_check:
                    matcher = load_gitignore_matcher(directory, cache)
                    if matcher is not None:
                        matchers.append(matcher)
            except Exception:
                matchers = []
            if matchers and (
                is_gitignored(dir_path, matchers, is_dir=True)
                or (not exists and is_gitignored(dir_path, matchers, is_dir=False))
            ):
                return False
    if not exists:
        return True
    try:
        for current_dir, dirnames, filenames in os.walk(dir_path):
            dirnames[:] = sorted(d for d in dirnames if not should_skip_dir(d))
            for name in sorted(filenames):
                if _is_relevant_change(
                    os.path.join(current_dir, name),
                    project_path,
                    respect_gitignore=respect_gitignore,
                    include_ignored=include_ignored,
                    matcher_cache=matcher_cache,
                    scan_rules=scan_rules,
                ):
                    return True
    except OSError:
        return True
    return False


def _exit_missing_watchfiles() -> NoReturn:
    """Name the one command that adds the watch extra to this installation."""
    print(
        "  Error: 'watchfiles' is not installed.\n"
        "  Install the watch extra into this mempalace-code environment "
        "(uv tool, pipx, or venv) with:\n"
        f"    {extra_install_command('watch')}",
        file=sys.stderr,
    )
    sys.exit(1)


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


# ---------------------------------------------------------------------------
# Watch-root planning — shared by the watcher and the schedule renderer so a
# rendered daemon is refused for exactly the roots the watcher would refuse.
# ---------------------------------------------------------------------------

DEFAULT_WATCH_AGENT = "mempalace"
# VCS metadata is present in every repository and already dropped by the watchfiles
# default filter, so naming it in the high-churn warning is only noise.
_VCS_METADATA_DIRS = frozenset({".git", ".hg", ".svn"})


class WatchRootError(ValueError):
    """A watch root that cannot run; the message names the recovery command."""


@dataclass(frozen=True)
class _GitWatchTarget:
    """One git metadata directory whose changes mean a project's checkout moved."""

    path: Path
    project: Path
    # A reflog directory: only ``<path>/HEAD`` (commit, checkout, merge, reset) counts.
    head_only: bool = False

    def matches(self, changed: Path) -> bool:
        try:
            relative = changed.relative_to(self.path)
        except ValueError:
            return False
        return relative == Path("HEAD") if self.head_only else True


@dataclass
class WatchPlan:
    """The validated projects one watcher run will mine and watch."""

    root: Path
    projects: dict  # resolved project path -> wing
    parent_mode: bool
    git_targets: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def format_watch_flags(
    *, on_save: bool = False, agent: str = DEFAULT_WATCH_AGENT, respect_gitignore: bool = True
) -> str:
    """Return the shell-quoted ``watch`` options that reproduce one invocation."""
    flags = " --on-save" if on_save else ""
    if agent != DEFAULT_WATCH_AGENT:
        flags += f" --agent {shlex.quote(agent)}"
    if not respect_gitignore:
        flags += " --no-gitignore"
    return flags


def format_watch_command(
    cli: str, palace_path: Optional[str], root: Path, flags: str = "", suffix: str = ""
) -> str:
    """Return one runnable ``watch`` command that keeps the operator's palace."""
    palace = f" --palace {shlex.quote(palace_path)}" if palace_path else ""
    return f"{cli}{palace} watch {shlex.quote(str(root))}{flags}{suffix}"


def _mine_watch_command(
    palace_path: Optional[str],
    project: Path,
    wing: Optional[str],
    agent: str,
    respect_gitignore: bool,
    include_ignored: Optional[list],
) -> str:
    """Return the ``mine --watch`` command that restarts one project watcher."""
    palace = f" --palace {shlex.quote(palace_path)}" if palace_path else ""
    command = f"mempalace-code{palace} mine {shlex.quote(str(project))} --watch"
    if wing:
        command += f" --wing {shlex.quote(wing)}"
    if agent != DEFAULT_WATCH_AGENT:
        command += f" --agent {shlex.quote(agent)}"
    if not respect_gitignore:
        command += " --no-gitignore"
    for path in include_ignored or []:
        command += f" --include-ignored {shlex.quote(str(path))}"
    return command


def _wing_label(project: Path, wing_override: str | None = None) -> str:
    """Return the wing a project mines into, for messages; fall back to its name.

    A ``--wing`` is shown normalized, as mine stores it.
    """
    from .mining.projects import load_config, mine_wing, resolve_wing_for_project

    try:
        if not wing_override:
            return resolve_wing_for_project(str(project))
        if any((project / name).is_file() for name in ("mempalace.yaml", "mempal.yaml")):
            return mine_wing(load_config(str(project)), wing_override)
        return mine_wing({"wing": wing_override}, wing_override)
    except ValueError:
        return wing_override or project.name


def _resolve_git_dirs(project: Path) -> Optional[tuple[Path, Path]]:
    """Return ``(git_dir, common_dir)`` for a checkout, following worktree ``.git`` files."""
    dot_git = project / ".git"
    try:
        if dot_git.is_dir():
            git_dir = dot_git.resolve()
        elif dot_git.is_file():
            lines = dot_git.read_text(encoding="utf-8", errors="replace").splitlines()
            if not lines or not lines[0].startswith("gitdir:"):
                return None
            pointer = Path(lines[0][len("gitdir:") :].strip())
            git_dir = (pointer if pointer.is_absolute() else project / pointer).resolve()
            if not git_dir.is_dir():
                return None
        else:
            return None
        common_dir = git_dir
        commondir_file = git_dir / "commondir"
        if commondir_file.is_file():
            pointer = Path(commondir_file.read_text(encoding="utf-8", errors="replace").strip())
            common_dir = (pointer if pointer.is_absolute() else git_dir / pointer).resolve()
    except OSError:
        return None
    return git_dir, common_dir


def _git_commit_targets(project: Path) -> list:
    """Return the git metadata directories that change on commit or checkout.

    Handles a normal checkout, a linked worktree (``.git`` file) and the reftable ref
    backend. Branch refs live in the common directory; ``HEAD`` and its reflog are per
    worktree, so a checkout of another branch is seen too.
    """
    dirs = _resolve_git_dirs(project)
    if dirs is None:
        return []
    git_dir, common_dir = dirs
    reftable = common_dir / "reftable"
    if reftable.is_dir():
        targets = [_GitWatchTarget(reftable, project)]
        worktree_reftable = git_dir / "reftable"
        if worktree_reftable != reftable and worktree_reftable.is_dir():
            targets.append(_GitWatchTarget(worktree_reftable, project))
        return targets
    targets = []
    heads = common_dir / "refs" / "heads"
    if heads.is_dir():
        targets.append(_GitWatchTarget(heads, project))
    logs = git_dir / "logs"
    if logs.is_dir():
        targets.append(_GitWatchTarget(logs, project, head_only=True))
    return targets


def _nearest_initialized_dir(start: Path) -> Optional[Path]:
    """Return the closest directory at or above *start* that holds an init file."""
    for candidate in (start, *start.parents):
        if any((candidate / marker).is_file() for marker in INIT_MARKERS):
            return candidate
    return None


def plan_watch_root(
    root_arg: str,
    *,
    on_commit: bool,
    cli: str = "mempalace-code",
    palace_path: Optional[str] = None,
    flags: str = "",
    suffix: str = "",
) -> WatchPlan:
    """Resolve and validate a watch root before any backup, mine, or rendered daemon.

    *flags* and *suffix* reproduce the operator's other options in recovery commands.
    Raises :class:`WatchRootError` naming one recovery command.
    """
    from .mining.projects import classify_project_root, detect_projects, resolve_wing_for_project

    root = Path(root_arg).expanduser().resolve()
    if not root.exists():
        raise WatchRootError(f"directory not found: {root}")
    if not root.is_dir():
        target = _nearest_initialized_dir(root.parent) or root.parent
        raise WatchRootError(
            f"{root} is a file; watch takes a directory (an initialized project root or a "
            "parent directory of initialized projects).\n"
            f"  Run:  {format_watch_command(cli, palace_path, target, flags, suffix)}"
        )

    notes: list = []
    root_kind, _ = classify_project_root(root)
    if root_kind == "initialized":
        try:
            projects = {root: resolve_wing_for_project(str(root))}
        except ValueError as exc:
            raise WatchRootError(f"{root.name}: {exc}") from exc
        parent_mode = False
    elif root_kind == "project":
        raise WatchRootError(
            f"{root} is a project directory but has not been initialized.\n"
            f"  Run:  {cli} init {shlex.quote(str(root))}"
        )
    else:
        parent_mode = True
        projects = {}
        config_errors = []
        uninitialized: list = []
        for detected in detect_projects(str(root)):
            project = Path(detected["path"]).resolve()
            if not detected["initialized"]:
                uninitialized.append(project)
                notes.append(
                    f"Skipping {project.name}: project files found but not initialized.\n"
                    f"    Run:  {cli} init {shlex.quote(str(project))}"
                )
                continue
            try:
                projects[project] = resolve_wing_for_project(detected["path"])
            except ValueError as exc:
                config_errors.append(f"{project.name}: {exc}")
        if config_errors:
            raise WatchRootError(
                "\n  ".join(config_errors)
                + f"\n  {len(config_errors)} project(s) had config parse errors — fix them and retry."
            )
        if not projects:
            if uninitialized:
                next_step = "  Initialize a project first:\n" + "\n".join(
                    f"    {cli} init {shlex.quote(str(project))}" for project in uninitialized
                )
            else:
                next_step = (
                    f"  Run {cli} init <dir> on a project under {shlex.quote(str(root))} first."
                )
            raise WatchRootError(
                f"No initialized projects found in {root}.\n"
                "  Supported watch roots:\n"
                "    - An initialized project directory (contains mempalace.yaml)\n"
                "    - A parent directory with at least one initialized immediate child project\n"
                f"{next_step}"
            )
        # Two repos mapped to one wing would overwrite each other on every re-mine.
        wing_to_paths: dict = {}
        for project, wing in projects.items():
            wing_to_paths.setdefault(wing, []).append(project)
        duplicates = {w: paths for w, paths in wing_to_paths.items() if len(paths) > 1}
        if duplicates:
            raise WatchRootError(
                "\n  ".join(
                    f"duplicate wing '{wing}': {', '.join(str(p) for p in paths)}"
                    for wing, paths in sorted(duplicates.items())
                )
                + "\n  Configure a unique 'wing:' in each project's mempalace.yaml."
            )

    plan = WatchPlan(root=root, projects=projects, parent_mode=parent_mode, notes=notes)
    if not on_commit:
        return plan

    on_save_flags = " --on-save" + flags
    watched: dict = {}
    for project, wing in projects.items():
        targets = _git_commit_targets(project)
        if targets:
            watched[project] = wing
            plan.git_targets.extend(targets)
        elif parent_mode:
            plan.notes.append(
                f"Skipping {project.name}: not a git repository, and commit mode re-mines "
                "only on git commits.\n"
                f"    Watch it on every save instead:  "
                f"{format_watch_command(cli, palace_path, project, on_save_flags, suffix)}"
            )
    if not watched:
        raise WatchRootError(
            f"no git repository found among the initialized projects under {root}; "
            "commit mode (the default) re-mines only on git commits.\n"
            f"  Watch every save instead:  "
            f"{format_watch_command(cli, palace_path, root, on_save_flags, suffix)}"
        )
    plan.projects = watched
    return plan


def _print_plan_notes(plan: WatchPlan) -> None:
    for note in plan.notes:
        print(f"  {note}", flush=True)


# ---------------------------------------------------------------------------
# One watcher per (palace, project)
# ---------------------------------------------------------------------------


class _ProjectWatchGuards:
    """Advisory per-(palace, project) claims so two watchers never re-mine one project.

    A watcher holds one flock-ed claim file per palace (whatever the number of projects),
    listing the projects it watches. Claims are read and written under a short-lived
    registry mutex, so two watchers starting together cannot both claim a project. Files
    sit beside the installation's operation lock and exist only while a watcher holds
    them: release removes them, and the claim of a crashed watcher is unlocked by the
    kernel and swept by the next watcher. Without a lock directory (an injected operation
    lock that has no path) nothing is guarded.
    """

    _ATTEMPTS = 3

    def __init__(self, lock_dir: Optional[Path], palace_path: str) -> None:
        self._lock_dir = lock_dir
        palace = os.path.realpath(os.path.expanduser(palace_path))
        self._key = hashlib.sha256(palace.encode()).hexdigest()[:16]
        self._claim: Optional[tuple] = None  # (fd, path)
        self._held: list = []

    @property
    def _enabled(self) -> bool:
        return _fcntl is not None and self._lock_dir is not None

    def _open_mutex(self) -> Optional[tuple]:
        """Take the registry mutex; return (fd, path), or None when it cannot be held."""
        assert _fcntl is not None
        assert self._lock_dir is not None
        path = self._lock_dir / f"watch-{self._key}.lock"
        self._lock_dir.mkdir(parents=True, exist_ok=True)
        for _attempt in range(self._ATTEMPTS):
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX)
                # The previous holder removes the file on release; a lock taken on an
                # inode that is no longer at *path* excludes nobody, so open it again.
                current = os.stat(path).st_ino == os.fstat(fd).st_ino
            except FileNotFoundError:
                current = False
            except BaseException:
                os.close(fd)
                raise
            if current:
                return fd, path
            os.close(fd)
        return None

    @staticmethod
    def _close_mutex(mutex: tuple) -> None:
        fd, path = mutex
        try:
            path.unlink()  # before unlocking, so a waiter re-opens a fresh file
        except FileNotFoundError:
            pass
        finally:
            os.close(fd)

    def _live_claims(self) -> list:
        """Return (owner, projects) for every other live claim; sweep dead ones."""
        assert _fcntl is not None
        assert self._lock_dir is not None
        own = self._claim[1] if self._claim else None
        claims = []
        for path in sorted(self._lock_dir.glob(f"watch-{self._key}-*.claim")):
            if path == own:
                continue
            try:
                fd = os.open(path, os.O_RDONLY)
            except FileNotFoundError:
                continue
            try:
                try:
                    _fcntl.flock(fd, _fcntl.LOCK_SH | _fcntl.LOCK_NB)
                except BlockingIOError:
                    text = os.read(fd, 1 << 20).decode("utf-8", errors="replace")
                    owner, _sep, body = text.partition("\n")
                    claims.append((owner.strip() or "another watcher", set(body.splitlines())))
                else:
                    path.unlink(missing_ok=True)  # nobody holds it: a crashed watcher's
            finally:
                os.close(fd)
        return claims

    def _write_claim(self) -> None:
        assert _fcntl is not None
        assert self._lock_dir is not None
        if self._claim is None:
            path = self._lock_dir / f"watch-{self._key}-{os.getpid()}-{time.time_ns()}.claim"
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            try:
                _fcntl.flock(fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            except BaseException:
                os.close(fd)
                path.unlink(missing_ok=True)
                raise
            self._claim = (fd, path)
        fd = self._claim[0]
        body = "".join(f"{project}\n" for project in self._held)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"pid {os.getpid()}\n{body}".encode(), 0)

    def acquire_many(self, projects: list) -> dict:
        """Claim *projects*; return {project: owner} for the ones another watcher holds."""
        if not self._enabled:
            return {}
        mutex = self._open_mutex()
        if mutex is None:  # pragma: no cover - the mutex file kept vanishing
            return {}
        taken: dict = {}
        try:
            claims = self._live_claims()
            for project in projects:
                owner = next((o for o, held in claims if str(project) in held), None)
                if owner is not None:
                    taken[project] = owner
                elif str(project) not in self._held:
                    self._held.append(str(project))
            self._write_claim()
        finally:
            self._close_mutex(mutex)
        return taken

    def acquire(self, project: Path) -> Optional[str]:
        """Hold *project*; return the current owner's description when it is taken."""
        return self.acquire_many([project]).get(project)

    def release_all(self) -> None:
        if self._claim is None:
            return
        fd, path = self._claim
        self._claim = None
        self._held = []
        mutex = None
        try:
            # Under the mutex, so no scanner sees a claim that is half released.
            mutex = self._open_mutex()
        except OSError:  # pragma: no cover - releasing must never fail the watcher
            pass
        try:
            path.unlink(missing_ok=True)
        finally:
            os.close(fd)
            if mutex is not None:
                self._close_mutex(mutex)


def _acquire_project_guards(
    projects: dict, palace_path: str, operation_lock: Optional[OperationLock], run_id: str
) -> _ProjectWatchGuards:
    """Guard every planned project; skip ones another watcher owns, exit if none remain."""
    lock_path = getattr(operation_lock or OperationLock.default(), "path", None)
    lock_dir = Path(lock_path).parent if lock_path is not None else None
    guards = _ProjectWatchGuards(lock_dir, palace_path)
    try:
        taken = guards.acquire_many(list(projects))
    except OSError as exc:
        guards.release_all()
        print(
            f"  Warning: could not check for other watchers of this palace ({exc}); "
            "watching without the one-watcher-per-project guard.",
            file=sys.stderr,
            flush=True,
        )
        return _ProjectWatchGuards(None, palace_path)
    for project, owner in taken.items():
        wing = projects.pop(project)
        print(
            f"  Skipping [{wing}] {project}: already watched into this palace ({owner}).",
            file=sys.stderr,
            flush=True,
        )
    if not projects:
        guards.release_all()
        _emit_run_state(run_id, "preflight-failed", "reason=already-watched")
        pids = sorted({o[4:] for o in taken.values() if re.fullmatch(r"pid \d+", o)})
        stop = f"  kill {' '.join(pids)}" if pids else " stop the other watcher"
        print(
            f"  Error: every project is already watched into {palace_path} by another "
            f"watcher.\n  Stop it first:{stop}\n  (or watch into a different --palace).",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    return guards


# ---------------------------------------------------------------------------
# Watched-project liveness
# ---------------------------------------------------------------------------


def _has_init_marker(project: Path) -> bool:
    return any((project / marker).is_file() for marker in INIT_MARKERS)


def _drop_dead_projects(
    project_map: dict,
    initialized: set,
    run_id: str,
    *,
    require_git: bool = False,
    restart: str = "",
) -> None:
    """Stop watching removed, de-initialized, or (commit mode) de-git'ed projects.

    *restart* is the exact command that restarts this watcher once the project is back.

    Exits 1 with ``WATCH_RUN state=stopped`` when no project remains.
    """
    for project in list(project_map):
        if not project.is_dir():
            reason = "removed"
            detail = "was removed or moved (directory not found)"
            resume = "restore the directory"
        elif project in initialized and not _has_init_marker(project):
            reason = "uninitialized"
            detail = "is no longer initialized (mempalace.yaml is missing)"
            resume = f"run: mempalace-code init {shlex.quote(str(project))}"
        elif require_git and not _git_commit_targets(project):
            reason = "not-git"
            detail = "is no longer a git repository, and commit mode re-mines only on commits"
            resume = "restore its git metadata or watch it with --on-save"
        else:
            continue
        wing = project_map.pop(project)
        print(
            f"  Warning: [{wing}] {project} {detail}; no longer watching it.\n"
            f"    Its drawers stay in the palace. To resume, {resume}, then restart the "
            + (f"watcher:  {restart}" if restart else "watcher."),
            file=sys.stderr,
            flush=True,
        )
        _emit_run_state(run_id, "project-dropped", f"wing={wing} reason={reason}")
    if not project_map:
        print("  Error: no watched projects remain; the watcher stopped.", file=sys.stderr)
        _emit_run_state(run_id, "stopped", "reason=no-projects")
        sys.exit(1)


def _watch_batches(
    watchfiles,
    watch_paths: Callable[[], list],
    recheck: Callable[[], None],
    run_id: str,
    **watch_kwargs,
):
    """Yield watchfiles batches, restarting the watch when a watched path vanished.

    A project removed between startup and the start of the watch makes the backend
    refuse its path; *recheck* drops it (or exits when none remain) and the watch
    restarts on what is left.
    """
    while True:
        paths = watch_paths()
        try:
            yield from watchfiles.watch(*paths, **watch_kwargs)
            return
        except FileNotFoundError as exc:
            recheck()
            if watch_paths() == paths:
                print(
                    f"  Error: cannot watch {', '.join(paths)}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                _emit_run_state(run_id, "stopped", "reason=watch-failed")
                sys.exit(1)


def _dedupe_changes(changes: list) -> list:
    """Collapse several events for one path into one, typed by whether it still exists."""
    paths = sorted({path for _change_type, path in changes})
    return [
        (_CHANGE_DELETED if not os.path.lexists(path) else _CHANGE_MODIFIED, path) for path in paths
    ]


def _change_preview(changes: list, *, mark_deleted: bool = True) -> str:
    """Name up to three changed files, marking deletions."""
    names = [
        f"{Path(path).name} (deleted)"
        if mark_deleted and change_type == _CHANGE_DELETED
        else Path(path).name
        for change_type, path in changes
    ]
    preview = ", ".join(names[:3])
    if len(names) > 3:
        preview += f" (+{len(names) - 3} more)"
    return preview


def _swept_preview(paths: list, project: Optional[Path]) -> str:
    """Name up to three swept sources, relative to their project when known."""
    names = []
    for path in sorted(paths):
        name = Path(path).name
        if project is not None:
            try:
                name = Path(path).relative_to(project).as_posix()
            except ValueError:
                pass
        names.append(name)
    preview = ", ".join(names[:3])
    if len(names) > 3:
        preview += f" (+{len(names) - 3} more)"
    return preview


def _print_cycle(
    label: str,
    stats: dict,
    changes: Optional[list] = None,
    project: Optional[Path] = None,
) -> None:
    """Report every re-mine cycle, including deletion-only ones.

    The swept sources come from the mine's own stale sweep, so a commit, checkout, or
    directory move that removed files names them in every watch mode; the event list
    is only a fallback for stats that do not carry the sweep.
    """
    secs = stats.get("elapsed_secs", 0)
    line = (
        f"  {label} {stats.get('files_processed', 0)} file(s), "
        f"{stats.get('drawers_filed', 0)} drawer(s) ({secs:.0f}s)"
    )
    swept_sources = stats.get("stale_sources_removed")
    if swept_sources is None:
        swept_sources = [p for t, p in (changes or []) if t == _CHANGE_DELETED]
    if swept_sources:
        line += f"; deleted source(s) swept: {_swept_preview(swept_sources, project)}"
    failed = stats.get("files_failed", 0)
    if failed:
        line += f"; {failed} file(s) failed to read"
    print(line, flush=True)


class WatcherMineExit(RuntimeError):
    """mine() stopped through ``sys.exit``; the message is the diagnostic it printed."""


_CAPTURE_TAIL_BYTES = 16 * 1024
_CAPTURE_TAIL_LINES = 20


def _capture_tail(handle) -> str:
    """Return the last lines written to a capture file, bounded for log output."""
    handle.flush()
    size = handle.seek(0, os.SEEK_END)
    handle.seek(max(0, size - _CAPTURE_TAIL_BYTES))
    lines = handle.read().decode("utf-8", errors="replace").splitlines()
    lines = [line for line in lines if line.strip()]
    tail = lines[-_CAPTURE_TAIL_LINES:]
    if len(lines) > len(tail):
        tail.insert(0, f"  (+{len(lines) - len(tail)} earlier line(s))")
    return "\n".join(tail)


def _quiet_mine(**kwargs) -> dict:
    """Run mine() with its progress output captured.

    Progress on stdout is discarded after a successful run; mine()'s own warnings on
    stderr (unreadable files, stale-sweep failures) are always replayed, and a
    ``sys.exit`` inside mine() becomes :class:`WatcherMineExit` carrying what it printed
    instead of silently ending the watcher.
    """
    out_capture = tempfile.TemporaryFile()
    err_capture = tempfile.TemporaryFile()
    sys.stdout.flush()
    sys.stderr.flush()
    old_out = os.dup(1)
    old_err = os.dup(2)
    exit_code: object = None
    exited = False
    try:
        os.dup2(out_capture.fileno(), 1)
        os.dup2(err_capture.fileno(), 2)
        _MineCapture.stdout_fd = old_out
        try:
            return mine(**kwargs) or {}
        except SystemExit as exc:
            exited = True
            exit_code = exc.code
    finally:
        _MineCapture.stdout_fd = None
        # Flush Python buffers while fds still point at the captures, otherwise
        # buffered text leaks to the real stdout on restore.
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(old_out, 1)
        os.dup2(old_err, 2)
        os.close(old_out)
        os.close(old_err)
        warnings = _capture_tail(err_capture)
        output = _capture_tail(out_capture) if exited else ""
        out_capture.close()
        err_capture.close()
        if warnings and not exited:
            print(warnings, file=sys.stderr, flush=True)
    detail = "\n".join(part for part in (output, warnings) if part)
    raise WatcherMineExit(detail or f"mine exited with status {exit_code}")


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
    # source-file read failure, not a Lance fragment error.
    if isinstance(exc, FileNotFoundError) and exc.filename:
        lance_dir = str(Path(palace_path) / "lance")
        if not str(exc.filename).startswith(lance_dir):
            return False
    return True


# Another process committing, compacting, or cleaning up the shared table can surface as
# a missing fragment on a stale handle or as a commit conflict; both clear on a fresh
# handle once the palace head itself is readable.
_CONCURRENT_COMMIT_MARKERS = ("commit conflict", "incompatible transaction", "retryable")
_TRANSIENT_MINE_ATTEMPTS = 3
_TRANSIENT_RETRY_DELAY_SECS = 1.0


def _is_storage_retry_candidate(exc: Exception, palace_path: str) -> bool:
    if _is_mine_missing_fragment(exc, palace_path):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _CONCURRENT_COMMIT_MARKERS)


def _probe_palace_head(palace_path: str) -> dict:
    """Probe the latest table version through a fresh read-only handle.

    A palace without table data has nothing to corrupt, so it reports healthy.
    """
    if not _has_existing_lance_data(palace_path):
        return {"ok": True, "total_rows": 0, "errors": []}
    try:
        from .storage import open_store

        report = open_store(palace_path, create=False, read_only=True).health_check()
    except Exception as exc:
        return {"ok": False, "errors": [{"probe": "open", "message": str(exc)}]}
    if not isinstance(report, dict):
        return {"ok": False, "errors": [{"probe": "health_check", "message": repr(report)}]}
    return report


class _MineFailure(Exception):
    """A watcher mine that did not complete.

    *degraded* means the palace head is unreadable; *busy* carries the
    :class:`PalaceBusyError` of another writer that kept the palace write lease past
    the wait budget.
    """

    def __init__(
        self,
        message: str,
        *,
        degraded: bool = False,
        health: Optional[dict] = None,
        busy: Optional[PalaceBusyError] = None,
    ):
        super().__init__(message)
        self.degraded = degraded
        self.health = health or {}
        self.busy = busy


def _mine_with_transient_retry(
    mine_kwargs: dict,
    palace_path: str,
    mining_store: Optional[_WatcherMiningStore],
    wing_prefix: str,
) -> dict:
    """Run one watcher mine, retrying storage errors caused by concurrent writers.

    The watcher never restores the shared table to an older version: a storage error
    is retried on a fresh handle while the palace head passes its read probes, and it
    is escalated as degraded only when a fresh probe of the head itself fails.

    The palace write lease is taken here, before mine()'s output is captured, so the
    notice that another writer is being waited for reaches the log; mine() re-enters it.
    """
    attempt = 1
    reopen = False
    while True:
        try:
            with palace_write_lease(palace_path, "watch"):
                if mining_store is None:
                    return _quiet_mine(**mine_kwargs) or {}
                if reopen:
                    mining_store.recreate()
                return _run_watcher_mine(mine_kwargs, mining_store)
        except PalaceBusyError as exc:
            raise _MineFailure(str(exc), busy=exc) from exc
        except WatcherMineExit as exc:
            raise _MineFailure(str(exc)) from exc
        except Exception as exc:
            if not _is_storage_retry_candidate(exc, palace_path):
                raise _MineFailure(str(exc)) from exc
            health = _probe_palace_head(palace_path)
            if health.get("ok") is not True:
                raise _MineFailure(str(exc), degraded=True, health=health) from exc
            if attempt >= _TRANSIENT_MINE_ATTEMPTS:
                raise _MineFailure(
                    f"{exc} (still failing after {attempt} attempts while the palace head "
                    "stays readable; another process may be rewriting this palace)"
                ) from exc
            attempt += 1
            print(
                f"  Transient storage error{wing_prefix}: {exc}\n"
                f"    The palace head is readable ({health.get('total_rows', 0)} row(s)); "
                f"reopening the store and retrying (attempt {attempt}/"
                f"{_TRANSIENT_MINE_ATTEMPTS}). No rollback is performed.",
                flush=True,
            )
            reopen = True
            time.sleep(_TRANSIENT_RETRY_DELAY_SECS * (attempt - 1))


def _create_pre_watch_backup(palace_path: str, kg_path: str, run_id: str) -> Optional[str]:
    """Archive the palace before the initial mine; fail closed, exit 1, on a real failure.

    Another process's commit or cleanup can remove a Lance file while it is being
    archived; that is retried on a fresh snapshot rather than stopping the watcher.
    Returns None when there is nothing to back up (no drawer table or KG yet, e.g.
    after a failed first mine).
    """
    attempt = 1
    while True:
        try:
            _, archive = create_backup(palace_path, kind="pre_watch", kg_path=kg_path)
            print(f"  Pre-watch backup: {archive}", flush=True)
            return archive
        except BackupSourceError:
            return None
        except FileNotFoundError as exc:
            if attempt >= _TRANSIENT_MINE_ATTEMPTS:
                failure: Exception = exc
                break
            attempt += 1
            print(
                f"  Transient backup error: {exc}\n"
                "    Another process changed the palace while it was archived; retrying "
                f"(attempt {attempt}/{_TRANSIENT_MINE_ATTEMPTS}).",
                flush=True,
            )
            time.sleep(_TRANSIENT_RETRY_DELAY_SECS * (attempt - 1))
        except Exception as exc:
            failure = exc
            break
    _emit_run_state(run_id, "pre-watch-backup-failed")
    print(
        f"  Error: pre-watch backup failed: {failure}\n  Watcher did not start.",
        file=sys.stderr,
        flush=True,
    )
    sys.exit(1)


def _print_recovery_commands(
    palace_path: str, pre_watch_archive: Optional[str], *, started: bool = False
) -> None:
    """Print operator-safe recovery commands for a degraded palace."""
    from .cli_invocation import cli_command

    print("  To diagnose and recover, run:", flush=True)
    print(f"    {cli_command('health', palace=palace_path)}", flush=True)
    print(f"    {cli_command('repair', '--rollback', '--dry-run', palace=palace_path)}", flush=True)
    if pre_watch_archive:
        restore = cli_command("restore", pre_watch_archive, "--force", palace=palace_path)
        print(f"    {restore}", flush=True)
    print("  Watcher stopped." if started else "  Watcher did not start.", flush=True)


def _report_degraded(
    failure: _MineFailure,
    palace_path: str,
    wing_prefix: str,
    stage: str,
    pre_watch_archive: Optional[str],
    run_id: str,
    *,
    started: bool,
) -> None:
    """Explain a verified-unreadable palace head; the operator owns any rollback."""
    print(
        f"  DEGRADED{wing_prefix}: Lance storage error during {stage}: {failure}",
        file=sys.stderr,
        flush=True,
    )
    for error in failure.health.get("errors", [])[:3]:
        print(
            f"    head probe {error.get('probe')}: {error.get('message')}",
            file=sys.stderr,
            flush=True,
        )
    if pre_watch_archive:
        print(f"  Pre-watch backup: {pre_watch_archive}", flush=True)
    print(
        "  The watcher never rolls back a shared palace on its own; other processes may "
        "still be writing to it.",
        flush=True,
    )
    _emit_run_state(run_id, "degraded")
    _print_recovery_commands(palace_path, pre_watch_archive, started=started)


def _report_startup_interrupt(run_id: str) -> None:
    """Record that a signal or Ctrl-C stopped the watcher before its watch loop began."""
    _emit_run_state(run_id, "interrupted", "stage=startup")
    print("  Watcher stopped during startup; restart it to finish the initial mine.", flush=True)


def _run_initial_mine_with_recovery(
    mine_kwargs: dict,
    palace_path: str,
    wing_label: Optional[str],
    pre_watch_archive: Optional[str],
    mining_store: Optional[_WatcherMiningStore] = None,
    run_id: str = "",
) -> Optional[dict]:
    """Run the initial mine; retry concurrent-writer storage errors, never roll back.

    Returns the stats dict on success, or None after printing why the watcher cannot
    start (the caller exits 1).
    """
    wing_prefix = f" [{wing_label}]" if wing_label else ""
    try:
        return _mine_with_transient_retry(mine_kwargs, palace_path, mining_store, wing_prefix)
    except _MineFailure as failure:
        if failure.degraded:
            _report_degraded(
                failure,
                palace_path,
                wing_prefix,
                "initial mine",
                pre_watch_archive,
                run_id,
                started=False,
            )
            return None
        print(
            f"  Error{wing_prefix}: initial mine failed: {failure}",
            file=sys.stderr,
            flush=True,
        )
        _emit_run_state(run_id, "initial-mine-failed")
        return None


def _run_cycle_mine(
    mine_kwargs: Callable[[], dict],
    palace_path: str,
    mining_store: _WatcherMiningStore,
    wing: str,
    run_id: str,
) -> Optional[dict]:
    """Run one watch-loop re-mine; a failure is reported and the watcher keeps running.

    *mine_kwargs* builds the mine() arguments inside the cycle, so a failure there (for
    example opening the knowledge graph) fails only this cycle. A palace kept busy by
    another writer past the wait budget skips the cycle. A verified-unreadable palace
    head stops the watcher (exit 1) with recovery commands.
    """
    try:
        try:
            kwargs = mine_kwargs()
        except Exception as exc:
            raise _MineFailure(str(exc)) from exc
        return _mine_with_transient_retry(kwargs, palace_path, mining_store, f" [{wing}]")
    except _MineFailure as failure:
        if failure.busy is not None:
            owner = ", ".join(
                f"{key}={value}"
                for key, value in failure.busy.owner.items()
                if key in {"operation", "pid"}
            )
            print(
                f"  Skipped [{wing}]: another MemPalace writer held the palace past the wait"
                f"{f' ({owner})' if owner else ''}; the watcher retries on the next change.",
                flush=True,
            )
            _emit_run_state(run_id, "cycle-skipped", f"wing={wing} reason=palace-busy")
            return None
        if failure.degraded:
            _report_degraded(
                failure, palace_path, f" [{wing}]", "re-mine", None, run_id, started=True
            )
            sys.exit(1)
        print(
            f"  Error [{wing}]: re-mine failed: {failure}\n"
            "    The watcher keeps running and retries on the next change.",
            file=sys.stderr,
            flush=True,
        )
        _emit_run_state(run_id, "cycle-failed", f"wing={wing}")
        return None


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
        _exit_missing_watchfiles()

    project_path = Path(project_dir).expanduser().resolve()

    if not project_path.is_dir():
        problem = "not a directory" if project_path.exists() else "directory not found"
        print(f"  Error: {problem}: {project_path}", file=sys.stderr)
        sys.exit(1)

    print(f"  Watching: {project_path}")
    print(f"  Palace:   {palace_path}")

    run_id = _make_run_id()
    _emit_run_state(run_id, "run-started")

    project_map = {project_path: _wing_label(project_path, wing_override)}
    restart = _mine_watch_command(
        palace_path, project_path, wing_override, agent, respect_gitignore, include_ignored
    )
    guards = _acquire_project_guards(project_map, palace_path, operation_lock, run_id)
    shutdown_signals = _WatcherShutdownSignals()
    try:
        shutdown_signals.install()
        _watch_single_project(
            watchfiles,
            project_map,
            palace_path,
            run_id,
            shutdown_signals,
            wing_override=wing_override,
            agent=agent,
            respect_gitignore=respect_gitignore,
            include_ignored=include_ignored,
            kg=kg,
            restart=restart,
        )
    except KeyboardInterrupt:
        # The watch loop handles its own interrupts; this one arrived during startup.
        _report_startup_interrupt(run_id)
    finally:
        shutdown_signals.restore()
        guards.release_all()


def _watch_single_project(
    watchfiles,
    project_map: dict,
    palace_path: str,
    run_id: str,
    shutdown_signals: _WatcherShutdownSignals,
    *,
    wing_override: str | None,
    agent: str,
    respect_gitignore: bool,
    include_ignored: list | None,
    kg,
    restart: str = "",
) -> None:
    """Run the ``mine --watch`` startup and loop for one guarded project."""
    (project_path,) = project_map
    label = project_map[project_path]
    initialized = {project_path} if _has_init_marker(project_path) else set()

    # Load app-level scan rules; snapshot polls config mtime at each batch boundary.
    scan_rules = get_scan_filter_rules()
    snapshot = _ScanRulesSnapshot(scan_rules)

    min_free = _load_watch_min_free()

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
        pre_watch_archive = _create_pre_watch_backup(palace_path, _local_kg_path, run_id)

    print("  Initial mine...", flush=True)

    # Initial incremental mine — brings the palace up to date before watching.
    # Skip if disk budget is too low; still start the watcher so it re-checks each cycle.
    _last_budget_log: list = [None]  # mutable container for closure

    def _should_run() -> bool:
        budget = check_watch_budget(palace_path, min_free)
        if not budget.allowed:
            now = time.monotonic()
            if _last_budget_log[0] is None or now - _last_budget_log[0] >= _BUDGET_LOG_INTERVAL:
                msg = _format_budget_skip_message(budget, palace_path, project_path)
                print(msg, flush=True)
                _last_budget_log[0] = now
            return False
        return True

    def mine_kwargs() -> dict:
        return {
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
        }

    if invalid_only_startup:
        _emit_run_state(run_id, "initial-mine-skipped", "reason=no-valid-sources")
    elif _should_run():
        _emit_run_state(run_id, "initial-mine-started")
        stats = _run_initial_mine_with_recovery(
            mine_kwargs(), palace_path, None, pre_watch_archive, mining_store, run_id
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
                elif outcome == "skipped:safety-check":
                    _emit_run_state(run_id, "optimize-skipped", "reason=safety-check")
                else:
                    _emit_run_state(run_id, "optimize-skipped", "reason=error")
    else:
        _emit_run_state(run_id, "initial-mine-skipped", "reason=disk-budget")

    print("  Watching for changes... (Ctrl-C to stop)", flush=True)

    # Shared gitignore matcher cache — loaded lazily, keyed by directory Path.
    matcher_cache: dict = {}

    shutdown_event = shutdown_signals.start_watching()

    cycles = 0
    event_count = 0
    start_time = time.monotonic()

    try:
        _emit_run_state(run_id, "watch-ready")
        for changes in _watch_batches(
            watchfiles,
            lambda: [str(p) for p in project_map],
            lambda: _drop_dead_projects(project_map, initialized, run_id, restart=restart),
            run_id,
            debounce=5000,
            stop_event=shutdown_event,
            yield_on_timeout=True,
            rust_timeout=_LIVENESS_CHECK_MS,
        ):
            # A removed or de-initialized project produces no further events, so its
            # liveness is checked on every batch, including idle timeouts.
            _drop_dead_projects(project_map, initialized, run_id, restart=restart)
            if not changes:
                continue

            # Evict stale gitignore matchers before filtering — same-batch events
            # (e.g. .gitignore change + affected file) must see fresh state.
            _invalidate_gitignore_cache(changes, matcher_cache)

            # Refresh scan rules once per batch before relevance filtering.
            scan_rules = snapshot.refresh()

            indexed_under = _IndexedSourcePrefixes(mining_store)
            # Discard irrelevant OS events (compiled files, git internals, etc.)
            relevant = _dedupe_changes(
                [
                    (change_type, path)
                    for change_type, path in changes
                    if _is_relevant_change(
                        path,
                        project_path,
                        respect_gitignore=respect_gitignore,
                        include_ignored=include_ignored,
                        matcher_cache=matcher_cache,
                        scan_rules=scan_rules,
                        indexed_under=indexed_under,
                    )
                ]
            )

            if not relevant:
                continue

            # Budget check before re-mine — skip whole cycle if disk is low.
            if not _should_run():
                continue

            stats = _run_cycle_mine(mine_kwargs, palace_path, mining_store, label, run_id)
            if stats is None:
                _drop_dead_projects(project_map, initialized, run_id, restart=restart)
                continue
            _print_cycle(
                f"[{len(relevant)} change(s): {_change_preview(relevant)}]",
                stats,
                project=project_path,
            )
            # Guarded optimize after batch
            if stats.get("drawers_filed", 0) and _should_run():
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

    elapsed = time.monotonic() - start_time
    _emit_run_state(run_id, "stopped", "reason=signal")
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
    """Run a single optimize pass; return 'completed', 'skipped:safety-check', or 'skipped:error'."""
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
            print(" skipped (safety check failed; see preceding error)", flush=True)
            return "skipped:safety-check"
        print(f" done ({time.time() - t0:.1f}s)", flush=True)
        return "completed"
    except Exception as exc:
        print(f" skipped ({exc})", flush=True)
        return "skipped:error"


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
    directory, all immediate child directories that are initialized projects are watched;
    uninitialized children are named and skipped.  Uninitialized project roots (project
    markers present but no init file) cause an actionable diagnostic and exit 1.

    When *on_commit* is True (default), only git metadata is watched — branch refs plus
    each checkout's ``HEAD`` reflog (normal checkouts, linked worktrees, and reftable
    repositories) — so a commit, merge, rebase, reset, or branch checkout triggers a
    re-mine, never a half-written work-in-progress file.  Projects without git are named
    and skipped before any backup or mine; if none remain the watcher exits 1 and names
    the ``--on-save`` command.

    When *on_commit* is False, watches the full project tree and re-mines on
    any file save (5s debounce).

    Blocks until SIGTERM, POSIX SIGHUP, or KeyboardInterrupt.

    Requires ``watchfiles`` (``pip install 'mempalace-code[watch]'``).
    """
    try:
        import watchfiles
    except ImportError:
        _exit_missing_watchfiles()

    from .cli_invocation import cli_command

    run_id = _make_run_id()
    _emit_run_state(run_id, "run-started")
    try:
        plan = plan_watch_root(
            parent_dir,
            on_commit=on_commit,
            cli=cli_command(),
            palace_path=palace_path,
            flags=format_watch_flags(
                on_save=not on_commit, agent=agent, respect_gitignore=respect_gitignore
            ),
        )
    except WatchRootError as exc:
        _emit_run_state(run_id, "preflight-failed")
        print(f"  Error: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    _print_plan_notes(plan)

    guards = _acquire_project_guards(plan.projects, palace_path, operation_lock, run_id)
    plan.git_targets = [t for t in plan.git_targets if t.project in plan.projects]
    shutdown_signals = _WatcherShutdownSignals()
    try:
        shutdown_signals.install()
        _watch_planned_projects(
            watchfiles,
            plan,
            palace_path,
            run_id,
            shutdown_signals,
            agent=agent,
            respect_gitignore=respect_gitignore,
            on_commit=on_commit,
        )
    except KeyboardInterrupt:
        # The watch loop handles its own interrupts; this one arrived during startup.
        _report_startup_interrupt(run_id)
    finally:
        shutdown_signals.restore()
        guards.release_all()


def _watch_planned_projects(
    watchfiles,
    plan: WatchPlan,
    palace_path: str,
    run_id: str,
    shutdown_signals: _WatcherShutdownSignals,
    *,
    agent: str,
    respect_gitignore: bool,
    on_commit: bool,
) -> None:
    """Run the startup backup, initial mines, and watch loop for a validated plan."""
    from .knowledge_graph import open_palace_kg
    from .storage import open_store

    project_map = plan.projects
    initialized = {project for project in project_map if _has_init_marker(project)}
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
                msg = _format_budget_skip_message(budget, palace_path, plan.root)
                print(msg, flush=True)
                _last_budget_log_all[0] = now
            return False
        return True

    mode_label = "on commit" if on_commit else "on file save"
    print(f"  Watching {len(project_map)} project(s) ({mode_label}):")
    for pp in sorted(project_map):
        print(f"    {pp.name} -> {project_map[pp]}")
    print(f"  Palace: {palace_path}")
    if plan.parent_mode:
        print(
            f"  Projects initialized under {plan.root} after startup are picked up "
            "when the watcher restarts."
        )

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
        pre_watch_archive = _create_pre_watch_backup(palace_path, _all_local_kg_path, run_id)

    def mine_kwargs(proj_path: Path, wing: str) -> dict:
        return {
            "project_dir": str(proj_path),
            "palace_path": palace_path,
            "wing_override": wing,
            "agent": agent,
            "limit": 0,
            "dry_run": False,
            "respect_gitignore": respect_gitignore,
            "incremental": True,
            "kg": open_palace_kg(palace_path),
            "skip_optimize": True,
            "kg_path": _all_local_kg_path,
        }

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
            stats = _run_initial_mine_with_recovery(
                mine_kwargs(proj_path, wing),
                palace_path,
                wing,
                pre_watch_archive,
                mining_store,
                run_id,
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
        elif outcome == "skipped:safety-check":
            _emit_run_state(run_id, "optimize-skipped", "reason=safety-check")
        else:
            _emit_run_state(run_id, "optimize-skipped", "reason=error")

    print("  Watching for changes... (Ctrl-C to stop)", flush=True)

    restart = format_watch_command(
        "mempalace-code",
        palace_path,
        plan.root,
        format_watch_flags(on_save=not on_commit, agent=agent, respect_gitignore=respect_gitignore),
    )

    def recheck() -> None:
        _drop_dead_projects(
            project_map, initialized, run_id, require_git=on_commit, restart=restart
        )

    # Determine what to watch
    def watch_paths() -> list:
        if not on_commit:
            return [str(p) for p in project_map]
        plan.git_targets = [t for p in project_map for t in _git_commit_targets(p)]
        return sorted({str(target.path) for target in plan.git_targets})

    if not on_commit:
        # Warn about high-churn directories found as immediate children of each project root.
        # A recursive watch still observes the whole tree; this informs the operator to prefer
        # on-commit mode for high-churn trees. Shallow check only — no recursive pre-walk.
        for proj_path in sorted(project_map):
            churn_found = sorted(
                d for d in SKIP_DIRS if d not in _VCS_METADATA_DIRS and (proj_path / d).is_dir()
            )
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
    shutdown_event = shutdown_signals.start_watching()

    cycles = 0
    event_count = 0
    start_time = time.monotonic()

    # In on-commit mode we watch git metadata directories — the default
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
        for changes in _watch_batches(
            watchfiles,
            watch_paths,
            recheck,
            run_id,
            watch_filter=commit_filter,
            debounce=5000,
            stop_event=shutdown_event,
            yield_on_timeout=True,
            rust_timeout=_LIVENESS_CHECK_MS,
        ):
            # A removed or de-initialized project produces no further events, so
            # liveness is checked on every batch, including idle timeouts.
            recheck()
            if not changes:
                continue
            batch_filed = 0

            if on_commit:
                # Any change to a branch ref or a checkout's HEAD reflog means a commit,
                # merge, rebase, reset, or checkout happened. Re-mine those projects.
                triggered: dict = {}  # proj_path -> wing
                for _change_type, path in changes:
                    file_path = Path(path)
                    for target in plan.git_targets:
                        if target.project in project_map and target.matches(file_path):
                            triggered[target.project] = project_map[target.project]

                if not triggered:
                    continue

                # Budget check before re-mine batch
                if not _should_run_all():
                    continue

                for proj_path, wing in triggered.items():
                    if proj_path not in project_map:
                        continue
                    stats = _run_cycle_mine(
                        partial(mine_kwargs, proj_path, wing),
                        palace_path,
                        mining_store,
                        wing,
                        run_id,
                    )
                    if stats is None:
                        recheck()
                        continue
                    batch_filed += stats.get("drawers_filed", 0)
                    _print_cycle(f"[git update in {wing}]", stats, project=proj_path)
                    cycles += 1
                    event_count += 1
            else:
                # File-save mode: filter and group by project
                _invalidate_gitignore_cache(changes, matcher_cache)

                # Refresh scan rules once per batch before relevance filtering.
                scan_rules = snapshot.refresh()

                indexed_under = _IndexedSourcePrefixes(mining_store)
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
                            indexed_under=indexed_under,
                        ):
                            by_project.setdefault(proj_path, []).append((change_type, path))
                        break

                if not by_project:
                    continue

                # Budget check before re-mine batch
                if not _should_run_all():
                    continue

                for proj_path, project_changes in by_project.items():
                    if proj_path not in project_map:
                        continue
                    relevant = _dedupe_changes(project_changes)
                    wing = project_map[proj_path]
                    stats = _run_cycle_mine(
                        partial(mine_kwargs, proj_path, wing),
                        palace_path,
                        mining_store,
                        wing,
                        run_id,
                    )
                    if stats is None:
                        recheck()
                        continue
                    batch_filed += stats.get("drawers_filed", 0)
                    _print_cycle(
                        f"[{wing}: {len(relevant)} change(s)]", stats, relevant, project=proj_path
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

    elapsed = time.monotonic() - start_time
    _emit_run_state(run_id, "stopped", "reason=signal")
    print(
        f"\n  Watch stopped after {elapsed:.0f}s — "
        f"{cycles} re-mine cycle(s), {event_count} event(s) "
        f"across {len(project_map)} project(s)."
    )


# ---------------------------------------------------------------------------
# Daemon rendering
# ---------------------------------------------------------------------------

WATCH_LAUNCHD_LABEL_PREFIX = "com.mempalace.watch"
# launchd sends SIGKILL this many seconds after SIGTERM; a re-mine or optimize in
# flight needs longer than launchd's 20-second default to finish cleanly.
_LAUNCHD_EXIT_TIMEOUT_SECS = 120


def watch_launchd_label(watch_root: str | Path) -> str:
    """Return the launchd label for one watch root: ``com.mempalace.watch.<name>-<hash>``.

    Each root gets its own job, so scheduling a second root never replaces the first,
    and re-rendering the same root replaces only its own job.
    """
    return launchd_label(WATCH_LAUNCHD_LABEL_PREFIX, watch_root)


def watch_launchd_log_path(label: str) -> Path:
    """Return the per-user, per-job daemon log (never a shared world-writable path)."""
    return launchd_log_path(label)


def render_watch_schedule(
    parent_dir: str,
    platform: str,
    mempalace_bin: Optional[str] = None,
    *,
    palace_path: Optional[str] = None,
    on_save: bool = False,
    agent: str = DEFAULT_WATCH_AGENT,
    respect_gitignore: bool = True,
    environment: Optional[Mapping[str, str]] = None,
) -> str:
    """Render a scheduler snippet (launchd plist or cron) for ``mempalace-code watch``.

    Parameters
    ----------
    parent_dir:
        Directory to watch (passed to ``mempalace-code watch <dir>``).
    platform:
        'darwin' for launchd plist, 'linux' for cron @reboot line.
    mempalace_bin:
        Override the mempalace-code binary path (default: invoked launcher, then PATH).
    palace_path, on_save, agent, respect_gitignore:
        Reproduced in the daemon command as ``--palace``, ``--on-save``, ``--agent``,
        and ``--no-gitignore``.
    environment:
        Environment to select daemon settings from (default: ``os.environ``); see
        :func:`daemon_environment`.

    Returns
    -------
    str
        Launchd plist XML (darwin) or cron @reboot line (linux).

    Raises
    ------
    ValueError
        When the platform is unsupported, the watch extra is missing, or the root would
        crash-loop under ``KeepAlive`` (see :func:`plan_watch_root`).
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

    if importlib.util.find_spec("watchfiles") is None:
        raise ValueError(
            "'watchfiles' is not installed, so this daemon would exit at every start.\n"
            "  Install the watch extra into this mempalace-code environment with:\n"
            f"    {extra_install_command('watch')}"
        )

    palace = os.path.abspath(os.path.expanduser(palace_path)) if palace_path else None
    flags = format_watch_flags(agent=agent, respect_gitignore=respect_gitignore)
    # Refuse every root the watcher itself would refuse: under KeepAlive it would
    # otherwise restart, back up, and fail forever.
    plan = plan_watch_root(
        parent_dir,
        on_commit=not on_save,
        cli=safe_bin,
        palace_path=palace,
        flags=(" --on-save" if on_save else "") + flags,
        suffix=" schedule",
    )
    watch_root = plan.root

    # Options follow the subcommand so the command keeps the `<cli> watch <root>` shape
    # that update discovery attributes; the CLI accepts --palace in any position.
    cmd = f"{safe_bin} watch {_shlex.quote(str(watch_root))}"
    if palace:
        cmd += f" --palace {_shlex.quote(palace)}"
    cmd += format_watch_flags(on_save=on_save, agent=agent, respect_gitignore=respect_gitignore)
    env = daemon_environment(os.environ if environment is None else environment)

    if platform == "linux":
        assignments = "".join(f"{name}={_shlex.quote(value)} " for name, value in env.items())
        # cron turns an unescaped % into a newline.
        return f"@reboot {assignments}{cmd}\n".replace("%", "\\%")

    # darwin: launchd plist — long-running daemon, KeepAlive + RunAtLoad
    def _xml_escape(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    label = watch_launchd_label(watch_root)
    log_path = _xml_escape(str(watch_launchd_log_path(label)))
    env_xml = "".join(
        f"        <key>{_xml_escape(name)}</key>\n        <string>{_xml_escape(value)}</string>\n"
        for name, value in env.items()
    )
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
        "    <key>EnvironmentVariables</key>\n"
        "    <dict>\n"
        f"{env_xml}"
        "    </dict>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "    <key>KeepAlive</key>\n"
        "    <true/>\n"
        "    <key>ThrottleInterval</key>\n"
        "    <integer>60</integer>\n"
        "    <key>ExitTimeOut</key>\n"
        f"    <integer>{_LAUNCHD_EXIT_TIMEOUT_SECS}</integer>\n"
        "    <key>StandardOutPath</key>\n"
        f"    <string>{log_path}</string>\n"
        "    <key>StandardErrorPath</key>\n"
        f"    <string>{log_path}</string>\n"
        "</dict>\n"
        "</plist>\n"
    )
    return plist
