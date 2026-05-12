"""Backup and restore command handlers."""

import os
import sys

from ..config import MempalaceConfig


def cmd_backup_create(args):
    from ..backup import create_backup

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    kind = getattr(args, "kind", "manual") or "manual"
    try:
        meta, out_path = create_backup(palace_path, out_path=args.out or None, kind=kind)
    except Exception as exc:
        # Includes the disk-space guard's RuntimeError("insufficient free space …").
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Backed up {meta['drawer_count']} drawers from {len(meta['wings'])} wing(s).")
    print(f"  Wings: {', '.join(meta['wings']) if meta['wings'] else '(none)'}")
    print(f"  Archive: {out_path}")


def cmd_backup_list(args):
    from ..backup import list_backups

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    extra_dir = getattr(args, "dir", None)
    config = MempalaceConfig()

    try:
        entries = list_backups(palace_path, extra_dir=extra_dir, config=config)
    except Exception as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not entries:
        print("No backups found.")
        return

    # Fixed-width table: TIMESTAMP  SIZE  DRAWERS  KIND  FLAGS  PATH
    print(f"{'TIMESTAMP':<25}  {'SIZE':>10}  {'DRAWERS':>7}  {'KIND':<14}  {'FLAGS':<10}  PATH")
    print("-" * 90)
    for e in entries:
        ts = e["timestamp"] or "unknown"
        if len(ts) > 19:
            ts = ts[:19]
        size_kb = e["size_bytes"] / 1024
        drawers = str(e["drawer_count"]) if e["drawer_count"] is not None else "?"
        kind = e["kind"]
        path = e["path"]
        flags_parts = []
        if e.get("stale"):
            flags_parts.append("stale")
        if e.get("oversized"):
            flags_parts.append("oversized")
        flags = ",".join(flags_parts) if flags_parts else ""
        print(f"{ts:<25}  {size_kb:>9.1f}K  {drawers:>7}  {kind:<14}  {flags:<10}  {path}")

    # Totals by kind
    print()
    by_kind: dict = {}
    for e in entries:
        k = e["kind"]
        if k not in by_kind:
            by_kind[k] = {"count": 0, "bytes": 0}
        by_kind[k]["count"] += 1
        by_kind[k]["bytes"] += e["size_bytes"]

    print("Totals by kind:")
    for k in sorted(by_kind):
        total_mb = by_kind[k]["bytes"] / (1024 * 1024)
        print(f"  {k:<14}  {by_kind[k]['count']} archive(s)  {total_mb:.1f} MB")


def cmd_backup_schedule(args):
    import sys as _sys

    from ..backup import render_schedule

    if getattr(args, "install", False):
        print(
            "  owner action required: --install is not supported.\n"
            "  Print the snippet with 'mempalace-code backup schedule --freq <freq>'\n"
            "  then install it yourself with: launchctl load <plist> (macOS)\n"
            "  or: crontab -e (Linux).",
            file=sys.stderr,
        )
        sys.exit(2)

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    platform = _sys.platform
    if platform.startswith("darwin"):
        platform = "darwin"
    elif platform.startswith("linux"):
        platform = "linux"
    else:
        print(
            f"  Error: backup scheduling is not supported on {_sys.platform}.\n"
            "  'mempalace-code backup schedule' works on macOS (launchd) and Linux (cron) only.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        snippet = render_schedule(args.freq, palace_path, platform)
    except ValueError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(snippet, end="")
    if platform == "darwin":
        print("\n  # To install: launchctl load ~/Library/LaunchAgents/com.mempalace.backup.plist")
    else:
        print("\n  # To install: crontab -e  (paste the line above)")


def cmd_backup(args):
    backup_command = getattr(args, "backup_command", None)
    if backup_command == "create":
        cmd_backup_create(args)
    elif backup_command == "list":
        cmd_backup_list(args)
    elif backup_command == "schedule":
        cmd_backup_schedule(args)
    else:
        # No verb — back-compat: behaves as 'create'
        cmd_backup_create(args)


def cmd_restore(args):
    from ..backup import restore_backup

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    try:
        meta = restore_backup(args.archive, palace_path, force=args.force)
    except FileExistsError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"  Restored palace to: {palace_path}")
    if meta:
        print(f"  Drawers: {meta.get('drawer_count', '?')}")
        print(f"  Wings: {', '.join(meta.get('wings', [])) or '(none)'}")
        print(f"  Backup timestamp: {meta.get('timestamp', '?')}")
