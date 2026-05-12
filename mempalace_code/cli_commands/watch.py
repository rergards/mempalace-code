"""Watch command handlers: watch, watch schedule, watch status."""

import os
import sys

from ..config import MempalaceConfig


def cmd_watch(args):
    watch_command = getattr(args, "watch_command", None)
    if watch_command == "schedule":
        cmd_watch_schedule(args)
        return
    if watch_command == "status":
        cmd_watch_status(args)
        return

    # Default: run the watcher
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    try:
        from ..watcher import watch_all
    except ImportError as exc:
        print(f"  Error importing watcher: {exc}", file=sys.stderr)
        sys.exit(1)

    watch_all(
        parent_dir=args.dir,
        palace_path=palace_path,
        agent=args.agent,
        respect_gitignore=not args.no_gitignore,
        on_commit=not getattr(args, "on_save", False),
    )


def cmd_watch_schedule(args):
    import sys as _sys

    if getattr(args, "install", False):
        print(
            "  owner action required: --install is not supported.\n"
            "  Print the snippet with 'mempalace-code watch <dir> schedule'\n"
            "  then install it yourself with: launchctl load <plist> (macOS)\n"
            "  or: crontab -e (Linux).",
            file=sys.stderr,
        )
        sys.exit(2)

    platform = _sys.platform
    if platform.startswith("darwin"):
        platform = "darwin"
    elif platform.startswith("linux"):
        platform = "linux"
    else:
        print(
            f"  Error: watch scheduling is not supported on {_sys.platform}.\n"
            "  'mempalace-code watch schedule' works on macOS (launchd) and Linux (cron) only.",
            file=sys.stderr,
        )
        sys.exit(1)

    from ..watcher import render_watch_schedule

    try:
        snippet = render_watch_schedule(args.dir, platform)
    except ValueError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(snippet, end="")
    if platform == "darwin":
        plist_path = "~/Library/LaunchAgents/com.mempalace.watch.plist"
        print("\n  # To install:", file=sys.stderr)
        print(f"  #   mempalace-code watch {args.dir} schedule > {plist_path}", file=sys.stderr)
        print(f"  #   launchctl load {plist_path}", file=sys.stderr)
        print("  # To stop:", file=sys.stderr)
        print(f"  #   launchctl unload {plist_path}", file=sys.stderr)
    else:
        print("\n  # To install: crontab -e  (paste the line above)", file=sys.stderr)


def cmd_watch_status(args):
    """Print disk-budget summary and launchd state for the watch daemon."""
    import subprocess

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    from ..disk_budget import check_watch_budget, format_bytes

    cfg = MempalaceConfig()
    min_free = cfg.watch_disk_min_free_bytes

    try:
        status = check_watch_budget(palace_path, min_free)
    except Exception as exc:
        print(f"  Error checking disk budget: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Palace:   {palace_path}")
    print(f"  Free:     {format_bytes(status.free_bytes)}")
    print(f"  Required: {format_bytes(status.min_free_bytes)} (watch_disk_min_free_bytes)")
    print(f"  Palace sz:{format_bytes(status.palace_bytes)}")
    print(f"  Backups:  {format_bytes(status.backups_bytes)}")
    runnable = "yes" if status.allowed else "no  (disk budget exceeded)"
    print(f"  Runnable: {runnable}")

    # LaunchAgent state (macOS only)
    if sys.platform.startswith("darwin"):
        try:
            uid = os.getuid()
            result = subprocess.run(
                ["launchctl", "print", f"gui/{uid}/com.mempalace.watch"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout
                state = "unknown"
                watched_root = None
                for line in output.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("state ="):
                        state = stripped.split("=", 1)[1].strip()
                    # Command in launchctl print output looks like:
                    #   /path/to/mempalace-code watch /watched/dir
                    if "mempalace" in stripped and "watch" in stripped:
                        parts = stripped.split()
                        for i, part in enumerate(parts):
                            if part in ("watch", "watch_all") and i + 1 < len(parts):
                                candidate = parts[i + 1]
                                if candidate.startswith("/") and candidate != palace_path:
                                    watched_root = candidate
                                break
                print(f"  LaunchAgent: com.mempalace.watch  state = {state}")
                if watched_root:
                    print(f"  Watched root: {watched_root}")
            else:
                print("  LaunchAgent: com.mempalace.watch  (not loaded)")
        except FileNotFoundError:
            print("  LaunchAgent: launchctl not found")
        except subprocess.TimeoutExpired:
            print("  LaunchAgent: state unavailable (launchctl timed out)")
        except Exception as exc:
            print(f"  LaunchAgent: state unavailable ({exc})")
    else:
        print("  LaunchAgent: not available (launchd is macOS-only)")
