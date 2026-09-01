"""Backup and restore command handlers."""

import os
import shlex
import sys

from ..config import MempalaceConfig


def cmd_backup_create(args):
    from ..backup import create_backup
    from ..knowledge_graph import palace_kg_path

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    kind = getattr(args, "kind", "manual") or "manual"
    # When --palace is explicit, scope the KG to the palace-local path so the backup
    # never captures the default global KG from a different location.
    kg_path = palace_kg_path(palace_path) if args.palace else None
    try:
        meta, out_path = create_backup(
            palace_path, out_path=args.out or None, kind=kind, kg_path=kg_path
        )
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
        print("Next: create one with mempalace-code backup create.")
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
    from ..backup import render_schedule
    from .alias import resolve_invoked_canonical_cli

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    try:
        invoked_launcher = resolve_invoked_canonical_cli()
    except RuntimeError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)
    selected_launcher = str(invoked_launcher) if invoked_launcher is not None else None
    safe_launcher = shlex.quote(selected_launcher or "mempalace-code")
    safe_palace = shlex.quote(os.path.abspath(palace_path))
    safe_freq = shlex.quote(args.freq)
    plist_path = os.path.expanduser("~/Library/LaunchAgents/com.mempalace.backup.plist")
    safe_plist = shlex.quote(plist_path)
    render_command = f"{safe_launcher} --palace {safe_palace} backup schedule --freq {safe_freq}"

    if getattr(args, "install", False):
        print(
            "  owner action required: --install is not supported.\n"
            f"  Print the snippet with: {render_command}\n"
            f"  Save it with: {render_command} > {safe_plist} (macOS)\n"
            f"  then install it yourself with: launchctl load {safe_plist} (macOS)\n"
            "  or: crontab -e (Linux).",
            file=sys.stderr,
        )
        sys.exit(2)

    platform = sys.platform
    if platform.startswith("darwin"):
        platform = "darwin"
    elif platform.startswith("linux"):
        platform = "linux"
    else:
        print(
            f"  Error: backup scheduling is not supported on {sys.platform}.\n"
            "  'mempalace-code backup schedule' works on macOS (launchd) and Linux (cron) only.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        snippet = render_schedule(args.freq, palace_path, platform, mempalace_bin=selected_launcher)
    except ValueError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(snippet, end="")
    if platform == "darwin":
        print(
            f"\n  # Re-render: {render_command}\n"
            f"  # Save: {render_command} > {safe_plist}\n"
            f"  # To install: launchctl load {safe_plist}",
            file=sys.stderr,
        )
    else:
        print(
            f"\n  # Re-render: {render_command}\n"
            "  # To install: crontab -e  (paste the line above)",
            file=sys.stderr,
        )


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
    from ..backup import BackupArchiveError, restore_backup

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    # Resolve KG destination: explicit --kg-path wins; explicit --palace scopes KG
    # to <palace>/knowledge_graph.sqlite3; no --palace preserves restore_backup() default.
    kg_path: str | None
    if args.kg_path is not None:
        kg_path = os.path.expanduser(args.kg_path)
    elif args.palace is not None:
        kg_path = os.path.join(palace_path, "knowledge_graph.sqlite3")
    else:
        kg_path = None

    try:
        meta = restore_backup(args.archive, palace_path, force=args.force, kg_path=kg_path)
    except FileExistsError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        print(
            "  Next: back up the reported destination state, then use --force only if "
            "you intend to replace it.",
            file=sys.stderr,
        )
        sys.exit(1)
    except BackupArchiveError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        print(
            "  Next: create a valid backup with: "
            "mempalace-code backup create --out mempalace-backup.tar.gz",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    restored_lance = getattr(meta, "has_lance", os.path.isdir(os.path.join(palace_path, "lance")))
    restored_kg = getattr(meta, "has_kg", kg_path is not None and os.path.isfile(kg_path))
    if restored_lance:
        print(f"  Restored palace to: {palace_path}")
    elif restored_kg:
        print(f"  Restored knowledge graph to: {kg_path}")
    else:
        print("  Restored empty backup: no palace or knowledge graph state was declared.")
    if meta:
        print(f"  Drawers: {meta.get('drawer_count', '?')}")
        print(f"  Wings: {', '.join(meta.get('wings', [])) or '(none)'}")
        print(f"  Backup timestamp: {meta.get('timestamp', '?')}")
