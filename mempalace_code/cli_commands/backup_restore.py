"""Backup and restore command handlers."""

import contextlib
import json
import os
import shlex
import sys

from ..config import MempalaceConfig
from .common import (
    acquire_operation_lease,
    exit_writer_busy,
    no_palace_next_step,
    palace_command,
)


def _os_error_text(exc: OSError) -> str:
    """One line for an OSError: its reason and the path, without errno noise."""
    if exc.filename:
        return f"{exc.strerror or exc}: {exc.filename}"
    return str(exc)


def cmd_backup_create(args):
    from ..backup import BackupSourceError, create_backup
    from ..knowledge_graph import adopt_legacy_kg, palace_kg_path
    from ..operation_lock import OperationLockedError
    from ..storage import ChromaRuntimeRetiredError

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    kind = getattr(args, "kind", "manual") or "manual"
    out = args.out or None
    if out is not None and not os.path.isdir(out) and not out.endswith((".tar.gz", ".tgz")):
        print(
            f"  Warning: {out} will hold a gzip-compressed tar archive; name it *.tar.gz so "
            "other tools recognize it.",
            file=sys.stderr,
        )
    # The archive carries the selected palace's own KG; legacy global facts are
    # adopted into it first so the archive includes them.
    adopt_legacy_kg(palace_path)
    try:
        meta, out_path = create_backup(
            palace_path, out_path=out, kind=kind, kg_path=palace_kg_path(palace_path)
        )
    except ChromaRuntimeRetiredError:
        raise
    except BackupSourceError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        print(f"  Next: {no_palace_next_step(palace_path)}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"  Error: {_os_error_text(exc)}", file=sys.stderr)
        sys.exit(1)
    except OperationLockedError as exc:
        # Another writer holds the palace, or maintenance holds the install lease.
        exit_writer_busy(exc)
    except Exception as exc:
        # Includes the disk-space guard's RuntimeError("insufficient free space …").
        print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if meta.get("degraded"):
        reason = str(meta.get("degraded_error") or "")
        kg_only = reason.startswith("kg_corrupt:")
        detail = (
            "its knowledge graph is corrupt"
            if kg_only
            else f"{meta['drawer_count']} drawers declared, not all readable"
        )
        print(f"  Archived a DEGRADED palace ({detail}).")
        print(f"  Archive: {os.path.abspath(out_path)}", flush=True)
        print(
            f"  Warning: the palace is degraded ({reason}). This archive is "
            "a forensic copy: restore refuses it, and it never replaces a healthy backup in "
            "retention.",
            file=sys.stderr,
        )
        # health names the KG recovery; repair only rebuilds the drawer table.
        next_step = palace_command(palace_path, "health")
        if not kg_only:
            next_step += (
                f", then {palace_command(palace_path, 'repair', '--rollback', '--dry-run')}"
            )
        print(f"  Next: {next_step}", file=sys.stderr)
        sys.exit(1)
    print(f"  Backed up {meta['drawer_count']} drawers from {len(meta['wings'])} wing(s).")
    print(f"  Wings: {', '.join(meta['wings']) if meta['wings'] else '(none)'}")
    print(f"  Archive: {os.path.abspath(out_path)}")
    pruned = meta.get("pruned") or []
    if pruned:
        print(f"  Retention pruned {len(pruned)} older {kind} archive(s).")


def cmd_backup_list(args):
    from ..backup import list_backups

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    extra_dir = getattr(args, "dir", None)
    config = MempalaceConfig()

    json_output = bool(getattr(args, "json", False))
    try:
        entries = list_backups(palace_path, extra_dir=extra_dir, config=config)
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(f"  Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if json_output:
        print(json.dumps({"ok": True, "palace": palace_path, "backups": entries}, indent=2))
        return

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
        if e.get("degraded"):
            flags_parts.append("degraded")
        if e.get("location") == "shared":
            flags_parts.append("shared")
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
    if any(e.get("location") == "shared" for e in entries):
        print(
            "\nFLAGS 'shared': written by an older release into the shared backups/ directory; "
            "it may belong to another palace in the same parent directory. Check its "
            "Wings before restoring. Retention never deletes it."
        )


def cmd_backup_schedule(args):
    from ..backup import backup_launchd_label, render_schedule
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
    plist_path = os.path.expanduser(
        f"~/Library/LaunchAgents/{backup_launchd_label(palace_path)}.plist"
    )
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
    if not os.path.isdir(palace_path):
        print(
            f"\n  # Warning: no palace exists at {os.path.abspath(palace_path)} yet; every "
            "scheduled run fails with 'No palace found' until one is created there.\n"
            "  #   Check --palace, or mine into this palace before loading the job.",
            file=sys.stderr,
        )
    if platform == "darwin":
        from ..launchd import launchd_log_path

        log = launchd_log_path(backup_launchd_label(palace_path))
        print(
            f"\n  # Re-render: {render_command}\n"
            f"  # Save: {render_command} > {safe_plist}\n"
            f"  # To install: launchctl load {safe_plist}\n"
            f"  # Log (refusals and failures of each run): {log}\n"
            "  # Re-render after changing HF_HOME or MEMPALACE_* settings; the job keeps the "
            "values of this shell.",
            file=sys.stderr,
        )
    else:
        print(
            f"\n  # Re-render: {render_command}\n"
            "  # To install: crontab -e  (paste the line above)",
            file=sys.stderr,
        )


def _retry_without_group_out(palace_path: str) -> str:
    """Return the invoked command with only the group-level ``backup --out`` removed."""
    from ..cli_invocation import cli_command

    argv = sys.argv[1:]
    if "backup" not in argv:  # called programmatically: nothing to replay
        return cli_command("backup", palace=os.path.abspath(palace_path))
    root: list[str] = []
    index = 0
    while index < len(argv) and argv[index] != "backup":
        token = argv[index]
        if token == "--palace":
            index += 2
            continue
        if not token.startswith("--palace="):
            root.append(token)
        index += 1
    group = argv[index + 1 :]
    kept: list[str] = []
    position = 0
    while position < len(group) and group[position].startswith("-"):
        if group[position] == "--out":
            position += 2
            continue
        if not group[position].startswith("--out="):
            kept.append(group[position])
        position += 1
    tokens = [*root, "backup", *kept, *group[position:]]
    return cli_command(*tokens, palace=os.path.abspath(palace_path))


def cmd_backup(args):
    backup_command = getattr(args, "backup_command", None)
    group_out = getattr(args, "group_out", None)
    create_out = getattr(args, "out", None)
    if group_out is not None and (
        backup_command in ("list", "schedule")
        or (create_out is not None and create_out != group_out)
    ):
        # A --out that would be ignored or silently overridden is refused before any write.
        palace_path = (
            os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
        )
        if backup_command == "create":
            problem = f"two different --out values ({group_out} and {create_out})"
        else:
            problem = f"--out has no effect on 'backup {backup_command}'"
        retry = _retry_without_group_out(palace_path)
        if getattr(args, "json", False):
            print(
                json.dumps({"ok": False, "error": f"{problem}; nothing was written", "next": retry})
            )
        else:
            print(f"  Error: {problem}; nothing was written.", file=sys.stderr)
            print(f"  Next: {retry}", file=sys.stderr)
        sys.exit(2)
    args.out = create_out if create_out is not None else group_out
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
    from ..backup import BackupArchiveError, RestoreTargetError, restore_backup
    from ..knowledge_graph import palace_kg_path
    from ..operation_lock import OperationLockedError

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    # Explicit --kg-path wins; otherwise the KG belongs to the selected palace.
    if args.kg_path is not None:
        kg_path = os.path.expanduser(args.kg_path)
    else:
        kg_path = palace_kg_path(palace_path)

    archive = os.path.abspath(os.path.expanduser(args.archive))
    list_archives = palace_command(palace_path, "backup", "list")
    if args.kg_path is not None and os.path.isdir(kg_path):
        print(
            f"  Error: --kg-path {kg_path} is a directory; pass a file path such as "
            f"{os.path.join(os.path.abspath(kg_path), 'knowledge_graph.sqlite3')}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not os.path.isfile(archive):
        print(f"  Error: cannot restore from {archive}: no such file", file=sys.stderr)
        print(f"  Next: list this palace's archives with: {list_archives}", file=sys.stderr)
        sys.exit(1)
    check_archive = (
        f"  Next: check the archive with: tar -tzf {shlex.quote(archive)}; list this "
        f"palace's archives with: {list_archives}"
    )
    # --force replaces live palace files, so no other MemPalace process may hold the
    # palace. Without --force, restore only publishes into an absent or empty
    # destination with no-replace operations, which a live reader cannot observe;
    # restore_backup itself holds the palace write lease against concurrent writers.
    lease = (
        acquire_operation_lease(
            "exclusive", "restore --force", palace_path, ["restore", archive, "--force"]
        )
        if args.force
        else contextlib.nullcontext()
    )
    with lease:
        try:
            meta = restore_backup(archive, palace_path, force=args.force, kg_path=kg_path)
        except RestoreTargetError as exc:
            # The message already names the command to run instead.
            print(f"  Error: {exc}", file=sys.stderr)
            sys.exit(1)
        except FileExistsError as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            print(
                "  Next: back up the reported destination state, then use --force only if "
                "you intend to replace it.",
                file=sys.stderr,
            )
            sys.exit(1)
        except BackupArchiveError as exc:
            if exc.code == "degraded_archive":
                print(
                    f"  Error: {archive} is a forensic copy of a degraded palace "
                    f"({exc.reason}); restore refuses it. Nothing was changed.",
                    file=sys.stderr,
                )
                print(
                    "  Next: restore an archive without the degraded flag listed by: "
                    f"{list_archives}",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(
                f"  Error: {archive} is not a restorable MemPalace backup ({exc}).",
                file=sys.stderr,
            )
            print(check_archive, file=sys.stderr)
            sys.exit(1)
        except OSError as exc:
            print(f"  Error: cannot restore from {archive}: {_os_error_text(exc)}", file=sys.stderr)
            print(check_archive, file=sys.stderr)
            sys.exit(1)
        except OperationLockedError as exc:
            exit_writer_busy(exc)
        except Exception as exc:
            print(f"  Error: cannot restore from {archive}: {exc}", file=sys.stderr)
            print(check_archive, file=sys.stderr)
            sys.exit(1)

    restored_lance = getattr(meta, "has_lance", os.path.isdir(os.path.join(palace_path, "lance")))
    restored_kg = getattr(meta, "has_kg", os.path.isfile(kg_path))
    if restored_lance:
        print(f"  Restored palace to: {palace_path}")
    if restored_kg:
        print(f"  Restored knowledge graph to: {kg_path}")
    if not (restored_lance or restored_kg):
        print("  Restored empty backup: no palace or knowledge graph state was declared.")
    if meta:
        print(f"  Drawers: {meta.get('drawer_count', '?')}")
        print(f"  Wings: {', '.join(meta.get('wings', [])) or '(none)'}")
        print(f"  Backup timestamp: {meta.get('timestamp', '?')}")
    if getattr(meta, "legacy_kg", False):
        sys.stdout.flush()  # keep the summary above the warning when both are piped
        print(
            f"  Warning: this archive was made by mempalace-code {meta.get('mempalace_version')} "
            f"without --palace, so the knowledge graph restored to {kg_path} is the legacy "
            "global knowledge graph, not the palace's own: facts that were added through "
            "MCP are not in it.",
            file=sys.stderr,
        )
    elif getattr(meta, "legacy_kg_possible", False):
        sys.stdout.flush()
        print(
            f"  Warning: this archive was made by mempalace-code {meta.get('mempalace_version')}; "
            f"if it was made without --palace, the knowledge graph restored to {kg_path} is "
            "the legacy global knowledge graph, not the palace's own, and facts that were "
            "added through MCP are not in it (an empty archived KG, or a missing legacy file, "
            "cannot be told apart).",
            file=sys.stderr,
        )
