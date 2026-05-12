"""Maintenance command handlers: health, cleanup, repair, migrate-storage."""

import os
import sys

from ..config import MempalaceConfig
from .common import fmt_bytes


def cmd_health(args):
    """Probe the palace for fragment-missing or read errors."""
    import json as _json

    from ..storage import LanceStore, open_store

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if not os.path.isdir(palace_path):
        print(f"  No palace found at {palace_path}", file=sys.stderr)
        sys.exit(1)

    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        print(f"  Cannot open palace at {palace_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(store, LanceStore):
        print("  health check is only supported for LanceDB palaces", file=sys.stderr)
        sys.exit(1)

    report = store.health_check()

    if getattr(args, "json", False):
        print(_json.dumps(report, indent=2))
    else:
        status = "ok" if report["ok"] else "DEGRADED"
        print(f"  Palace: {palace_path}")
        print(f"  Status: {status}")
        print(f"  Total rows: {report['total_rows']}")
        print(f"  Current version: {report['current_version']}")
        if report["errors"]:
            print("  Errors:")
            for err in report["errors"]:
                print(f"    [{err['kind']}] {err['probe']}: {err['message']}")
        else:
            print("  No errors detected.")
        if report.get("warnings"):
            print("  Warnings:")
            for w in report["warnings"]:
                print(f"    [{w['kind']}] {w['probe']}: {w['message']}")
        s = report.get("storage")
        if s and not s.get("error"):
            print(
                f"  Storage: logical={fmt_bytes(s['logical_bytes'])} "
                f"on-disk={fmt_bytes(s['on_disk_bytes'])} "
                f"reclaimable={fmt_bytes(s['estimated_reclaimable_bytes'])}"
            )
            print(
                f"  Versions: {s['version_count']}  "
                f"data-files: current={s['current_data_files']} "
                f"on-disk={s['on_disk_data_files']}  "
                f"deletion-files: current={s['current_deletion_files']} "
                f"on-disk={s['on_disk_deletion_files']}"
            )

    if not report["ok"]:
        sys.exit(1)


def cmd_cleanup(args):
    """Reclaim disk space from stale Lance versions after repeated mine/watch cycles."""
    import json as _json

    from ..storage import LanceStore, LanceStoreDependencyError, open_store

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if not os.path.isdir(palace_path):
        print(f"  No palace found at {palace_path}", file=sys.stderr)
        sys.exit(1)

    try:
        store = open_store(palace_path, create=False)
    except Exception as e:
        print(f"  Cannot open palace at {palace_path}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(store, LanceStore):
        print("  cleanup is only supported for LanceDB palaces", file=sys.stderr)
        sys.exit(1)

    unsafe_now = args.unsafe_now
    older_than_days = args.older_than_days

    if unsafe_now and not getattr(args, "json", False):
        print(
            "  WARNING: --unsafe-now is for known-no-writer maintenance only.\n"
            "  Do not run this while any mine/watch process is active."
        )

    try:
        result = store.cleanup_stale_fragments(
            older_than_days=older_than_days,
            unsafe_now=unsafe_now,
        )
    except LanceStoreDependencyError as e:
        print(f"  Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"  Cleanup failed: {e}", file=sys.stderr)
        sys.exit(1)

    if getattr(args, "json", False):
        print(_json.dumps(result, indent=2))
    else:
        status = "ok" if result["ok"] else "FAILED"
        print(f"  Status: {status}")
        print(f"  Rows before: {result['rows_before']}  Rows after: {result['rows_after']}")
        print(
            f"  Versions before: {result['version_count_before']}  "
            f"after: {result['version_count_after']}"
        )
        print(f"  Freed: {fmt_bytes(result['freed_bytes'])}")
        if not result["ok"]:
            print(f"  Error: {result.get('error', 'unknown')}", file=sys.stderr)

    if not result["ok"]:
        sys.exit(1)


def cmd_repair(args):
    """Rebuild palace — rollback to last working version, or extract-and-rebuild."""
    import shutil

    from ..storage import LanceStore, open_store

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    dry_run = getattr(args, "dry_run", False)
    rollback = getattr(args, "rollback", False)

    # --dry-run without --rollback is not supported for the full rebuild path
    if dry_run and not rollback:
        print("  --dry-run is only supported with --rollback for version restore.", file=sys.stderr)
        print("  Full rebuild (without --rollback) always modifies the palace.", file=sys.stderr)
        sys.exit(2)

    if rollback:
        if not os.path.isdir(palace_path):
            print(f"  No palace found at {palace_path}", file=sys.stderr)
            sys.exit(1)
        try:
            store = open_store(palace_path, create=False)
        except Exception as e:
            print(f"  Cannot open palace at {palace_path}: {e}", file=sys.stderr)
            sys.exit(1)
        if not isinstance(store, LanceStore):
            print("  --rollback is only supported for LanceDB palaces", file=sys.stderr)
            sys.exit(1)

        print(f"\n{'=' * 55}")
        print("  MemPalace Repair — Version Rollback")
        print(f"{'=' * 55}\n")
        print(f"  Palace: {palace_path}")
        if dry_run:
            print("  Mode: dry-run (no changes will be made)\n")
        else:
            print("  Mode: live (will restore if candidate found)\n")

        try:
            result = store.recover_to_last_working_version(dry_run=dry_run)
        except Exception as e:
            print(f"  Restore failed: {e}", file=sys.stderr)
            print("  Palace may still be in a degraded state.", file=sys.stderr)
            print("  Try: mempalace-code repair (full rebuild)", file=sys.stderr)
            print(f"\n{'=' * 55}\n")
            sys.exit(1)

        if result.get("recovered"):
            print(f"  Restored to version: {result['restored_to']}")
            print(f"  Rows after restore: {result['rows_after']}")
        elif result.get("candidate_version") is not None:
            print(f"  Candidate version found: {result['candidate_version']}")
            if dry_run:
                print("  (dry-run — no changes made)")
                print("  Run without --dry-run to apply the rollback.")
        else:
            msg = result.get("message") or result.get("error") or "no healthy prior version found"
            print(f"  No candidate version: {msg}", file=sys.stderr)
            print("  Try: mempalace-code repair (full rebuild)", file=sys.stderr)
            print(f"\n{'=' * 55}\n")
            if not dry_run:
                sys.exit(1)
        print(f"\n{'=' * 55}\n")
        return

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}")
        return

    print(f"\n{'=' * 55}")
    print("  MemPalace Repair")
    print(f"{'=' * 55}\n")
    print(f"  Palace: {palace_path}")

    # Try to read existing drawers
    try:
        store = open_store(palace_path, create=False)
        total = store.count()
        print(f"  Drawers found: {total}")
    except Exception as e:
        print(f"  Error reading palace: {e}")
        print("  Cannot recover — palace may need to be re-mined from source files.")
        return

    if total == 0:
        print("  Nothing to repair.")
        return

    # Extract all drawers in batches
    print("\n  Extracting drawers...")
    batch_size = 5000
    all_ids = []
    all_docs = []
    all_metas = []
    offset = 0
    while offset < total:
        batch = store.get(limit=batch_size, offset=offset, include=["documents", "metadatas"])
        all_ids.extend(batch["ids"])
        all_docs.extend(batch["documents"])
        all_metas.extend(batch["metadatas"])
        offset += batch_size
    print(f"  Extracted {len(all_ids)} drawers")

    # Backup and rebuild
    backup_path = palace_path + ".backup"
    if os.path.exists(backup_path):
        shutil.rmtree(backup_path)
    print(f"  Backing up to {backup_path}...")
    shutil.copytree(palace_path, backup_path)

    print("  Rebuilding palace from extracted data...")
    # Remove old data and recreate
    shutil.rmtree(palace_path)
    new_store = open_store(palace_path, create=True)

    filed = 0
    for i in range(0, len(all_ids), batch_size):
        batch_ids = all_ids[i : i + batch_size]
        batch_docs = all_docs[i : i + batch_size]
        batch_metas = all_metas[i : i + batch_size]
        new_store.add(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)
        filed += len(batch_ids)
        print(f"  Re-filed {filed}/{len(all_ids)} drawers...")

    print(f"\n  Repair complete. {filed} drawers rebuilt.")
    print(f"  Backup saved at {backup_path}")
    print(f"\n{'=' * 55}\n")


def cmd_migrate_storage(args):
    """Migrate a ChromaDB palace to a LanceDB palace."""
    from ..migrate import VerificationError, migrate_chroma_to_lance

    try:
        src_count, dst_count = migrate_chroma_to_lance(
            src_path=args.src_palace,
            dst_path=args.dst_palace,
            backup_dir=args.backup_dir,
            force=args.force,
            embed_model=args.embed_model,
            verify=args.verify,
            no_backup=False,
        )
    except VerificationError as e:
        print(f"Verification failed: {e}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Source drawers: {src_count}  Destination drawers: {dst_count}")
