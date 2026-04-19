"""watcher.py — File watcher for auto-incremental mining.

Provides ``watch_and_mine()`` (single project) and ``watch_all()`` (multi-project),
plus ``render_watch_schedule()`` for generating launchd/cron daemon configs.

Uses the ``watchfiles`` library (Rust-backed, uses fsevents/inotify — no polling).

Install the optional extra before use:
    pip install 'mempalace[watch]'
"""

import signal
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .miner import (
    KNOWN_FILENAMES,
    READABLE_EXTENSIONS,
    SKIP_FILENAMES,
    is_exact_force_include,
    is_force_included,
    is_gitignored,
    load_gitignore_matcher,
    mine,
    normalize_include_paths,
    should_skip_dir,
)


def _invalidate_gitignore_cache(changes, matcher_cache: dict) -> None:
    """Evict matcher_cache entries for directories whose .gitignore file changed.

    Called at the top of every watchfiles event batch so that _is_relevant_change()
    picks up fresh matcher state for any files processed in the same batch.
    """
    for _change_type, path in changes:
        if Path(path).name == ".gitignore":
            matcher_cache.pop(Path(path).parent, None)


def _is_relevant_change(
    path: str,
    project_path: Path,
    respect_gitignore: bool = True,
    include_ignored: Optional[list] = None,
    matcher_cache: Optional[dict] = None,
) -> bool:
    """Return True if the changed path should trigger a re-mine.

    Mirrors scan_project() filtering: READABLE_EXTENSIONS, KNOWN_FILENAMES,
    SKIP_FILENAMES, should_skip_dir() on parents, gitignore, include_ignored.
    Works for deleted paths (no file-existence check required).
    """
    file_path = Path(path)
    filename = file_path.name

    # Ensure the changed path is inside the project directory
    try:
        relative = file_path.relative_to(project_path)
    except ValueError:
        return False

    include_paths = normalize_include_paths(include_ignored or [])

    # Reject files inside skip dirs, unless a descendant is explicitly force-included.
    # Mirrors the dirs[:] pruning in scan_project().
    for i, part in enumerate(relative.parts[:-1]):
        if should_skip_dir(part):
            parent_path = project_path.joinpath(*relative.parts[: i + 1])
            if not is_force_included(parent_path, project_path, include_paths):
                return False

    force_include = is_force_included(file_path, project_path, include_paths)
    exact_force_include = is_exact_force_include(file_path, project_path, include_paths)

    # Reject known-skip filenames unless the file is explicitly force-included.
    if not force_include and filename in SKIP_FILENAMES:
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


def watch_and_mine(
    project_dir: str,
    palace_path: str,
    wing_override: str = None,
    agent: str = "mempalace",
    respect_gitignore: bool = True,
    include_ignored: list = None,
    kg=None,
) -> None:
    """Watch *project_dir* for file changes and re-mine incrementally.

    Blocks until SIGTERM or KeyboardInterrupt (Ctrl-C). On exit, prints a
    one-line summary of cycles and events processed.

    Parameters match ``mine()`` (minus ``limit``, ``dry_run``, and
    ``incremental`` which are fixed in watch mode).

    Requires ``watchfiles`` (``pip install 'mempalace[watch]'``).
    """
    try:
        import watchfiles
    except ImportError:
        print(
            "  Error: 'watchfiles' is not installed.\n"
            "  Install it with:  pip install 'mempalace[watch]'\n"
            "  or:               pip install watchfiles",
            file=sys.stderr,
        )
        sys.exit(1)

    project_path = Path(project_dir).expanduser().resolve()

    if not project_path.is_dir():
        print(f"  Error: directory not found: {project_path}", file=sys.stderr)
        sys.exit(1)

    print(f"  Watching: {project_path}")
    print(f"  Palace:   {palace_path}")
    print("  Running initial mine...")

    # Initial incremental mine — brings the palace up to date before watching.
    mine(
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
    )

    print("  Watching for changes... (Ctrl-C to stop)")

    # Shared gitignore matcher cache — loaded lazily, keyed by directory Path.
    matcher_cache: dict = {}

    # Shutdown flag — set by SIGTERM handler; checked by watchfiles via stop_event.
    shutdown_event = threading.Event()

    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _handle_sigterm(_signum, _frame):
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    cycles = 0
    event_count = 0
    start_time = time.monotonic()

    try:
        for changes in watchfiles.watch(
            str(project_path),
            debounce=5000,
            stop_event=shutdown_event,
        ):
            # Evict stale gitignore matchers before filtering — same-batch events
            # (e.g. .gitignore change + affected file) must see fresh state.
            _invalidate_gitignore_cache(changes, matcher_cache)

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
                )
            ]

            if not relevant:
                continue

            names = [Path(p).name for _, p in relevant]
            preview = ", ".join(names[:3])
            if len(relevant) > 3:
                preview += f" (+{len(relevant) - 3} more)"
            print(f"  [{len(relevant)} change(s): {preview}] re-mining...")

            mine(
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
            )
            cycles += 1
            event_count += len(relevant)

    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, original_sigterm)

    elapsed = time.monotonic() - start_time
    print(
        f"\n  Watch stopped after {elapsed:.0f}s — "
        f"{cycles} re-mine cycle(s), {event_count} file event(s)."
    )


def _optimize_once(palace_path: str, open_store_fn) -> None:
    """Run a single optimize pass on the palace store."""
    try:
        t0 = time.time()
        print("  >> Optimizing storage...", end="", flush=True)
        store = open_store_fn(palace_path, create=False)
        store.optimize()
        print(f" done ({time.time() - t0:.1f}s)", flush=True)
    except Exception as exc:
        print(f" skipped ({exc})", flush=True)


def watch_all(
    parent_dir: str,
    palace_path: str,
    agent: str = "mempalace",
    respect_gitignore: bool = True,
) -> None:
    """Watch all initialized projects under *parent_dir* for file changes.

    Discovers projects via ``detect_projects()``, filters to initialized ones,
    then watches all directories in a single ``watchfiles.watch()`` call.
    On each change batch, routes events to the correct project and re-mines it.

    Blocks until SIGTERM or KeyboardInterrupt.

    Requires ``watchfiles`` (``pip install 'mempalace[watch]'``).
    """
    try:
        import watchfiles
    except ImportError:
        print(
            "  Error: 'watchfiles' is not installed.\n"
            "  Install it with:  pip install 'mempalace[watch]'\n"
            "  or:               pip install watchfiles",
            file=sys.stderr,
        )
        sys.exit(1)

    from .knowledge_graph import KnowledgeGraph
    from .miner import derive_wing_name, detect_projects
    from .storage import open_store

    parent_path = Path(parent_dir).expanduser().resolve()
    if not parent_path.is_dir():
        print(f"  Error: directory not found: {parent_path}", file=sys.stderr)
        sys.exit(1)

    projects = detect_projects(str(parent_path))
    initialized = [p for p in projects if p["initialized"]]

    if not initialized:
        print(f"  No initialized projects found in {parent_path}")
        print("  Run 'mempalace init <dir>' on projects first.")
        sys.exit(1)

    # Build project path -> wing name mapping
    project_map: dict = {}  # resolved Path -> wing name
    watch_paths: list = []
    for proj in initialized:
        proj_path = Path(proj["path"]).resolve()
        wing = derive_wing_name(proj["path"])
        project_map[proj_path] = wing
        watch_paths.append(str(proj_path))

    print(f"  Watching {len(watch_paths)} project(s):")
    for wp in sorted(watch_paths):
        print(f"    {Path(wp).name} -> {project_map[Path(wp)]}")
    print(f"  Palace: {palace_path}")

    # Initial incremental mine for all projects — skip per-project optimize,
    # run a single optimize at the end to avoid N costly compaction passes.
    print("  Running initial mine...")
    for proj_path, wing in project_map.items():
        kg = KnowledgeGraph()
        mine(
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
        )

    # Single optimize after all initial mines
    _optimize_once(palace_path, open_store)

    print("  Watching for changes... (Ctrl-C to stop)")

    matcher_cache: dict = {}
    shutdown_event = threading.Event()
    original_sigterm = signal.getsignal(signal.SIGTERM)

    def _handle_sigterm(_signum, _frame):
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    cycles = 0
    event_count = 0
    start_time = time.monotonic()

    try:
        for changes in watchfiles.watch(
            *watch_paths,
            debounce=5000,
            stop_event=shutdown_event,
        ):
            _invalidate_gitignore_cache(changes, matcher_cache)

            # Group changes by project
            by_project: dict = {}  # proj_path -> list of (change_type, path)
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
                    ):
                        by_project.setdefault(proj_path, []).append((change_type, path))
                    break

            if not by_project:
                continue

            for proj_path, relevant in by_project.items():
                wing = project_map[proj_path]
                names = [Path(p).name for _, p in relevant]
                preview = ", ".join(names[:3])
                if len(relevant) > 3:
                    preview += f" (+{len(relevant) - 3} more)"
                print(f"  [{wing}: {len(relevant)} change(s): {preview}] re-mining...")

                kg = KnowledgeGraph()
                mine(
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
                )
                cycles += 1
                event_count += len(relevant)

            # Optimize once per watch batch (not per-project)
            _optimize_once(palace_path, open_store)

    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, original_sigterm)

    elapsed = time.monotonic() - start_time
    print(
        f"\n  Watch stopped after {elapsed:.0f}s — "
        f"{cycles} re-mine cycle(s), {event_count} file event(s) "
        f"across {len(project_map)} project(s)."
    )


def render_watch_schedule(
    parent_dir: str,
    platform: str,
    mempalace_bin: Optional[str] = None,
) -> str:
    """Render a scheduler snippet (launchd plist or cron) for ``mempalace watch``.

    Parameters
    ----------
    parent_dir:
        Parent directory to watch (passed to ``mempalace watch <dir>``).
    platform:
        'darwin' for launchd plist, 'linux' for cron @reboot line.
    mempalace_bin:
        Override the mempalace binary path (default: resolved via shutil.which).

    Returns
    -------
    str
        Launchd plist XML (darwin) or cron @reboot line (linux).
    """
    import shlex as _shlex
    import shutil as _shutil

    if platform not in ("darwin", "linux"):
        raise ValueError(f"Unsupported platform {platform!r}; must be 'darwin' or 'linux'")

    safe_dir = _shlex.quote(str(Path(parent_dir).expanduser().resolve()))

    if mempalace_bin is None:
        mempalace_bin = _shutil.which("mempalace")
        if mempalace_bin is None:
            mempalace_bin = f"{sys.executable} -m mempalace"

    safe_bin = _shlex.quote(mempalace_bin)
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
        "    <key>StandardOutPath</key>\n"
        "    <string>/tmp/mempalace-watch.log</string>\n"
        "    <key>StandardErrorPath</key>\n"
        "    <string>/tmp/mempalace-watch.log</string>\n"
        "</dict>\n"
        "</plist>\n"
    )
    return plist
