"""Export and import command handlers."""

import os
import sys

from ..config import MempalaceConfig


def cmd_export(args):
    from ..export import write_jsonl
    from ..knowledge_graph import KnowledgeGraph
    from ..storage import open_store

    palace_path = args.palace or MempalaceConfig().palace_path
    if not os.path.isdir(palace_path):
        print(f"  Error: no palace found at {palace_path}", file=sys.stderr)
        print(
            "  Next: run mempalace-code init <dir> then mempalace-code mine <dir>, "
            "or pass the correct --palace path.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        store = open_store(palace_path, create=False, read_only=True)
    except Exception as exc:
        print(f"  Error: cannot open palace at {palace_path}: {exc}", file=sys.stderr)
        print(
            "  Next: if this is the wrong palace, pass the correct --palace path. "
            f"If this is your palace, run mempalace-code --palace {palace_path} health, "
            "then mempalace-code repair --rollback --dry-run before retrying export.",
            file=sys.stderr,
        )
        sys.exit(1)
    kg = KnowledgeGraph() if args.with_kg else None

    print(f"  Exporting from: {palace_path}", file=sys.stderr)
    summary = write_jsonl(
        path=args.out,
        store=store,
        kg=kg,
        only_manual=args.only_manual,
        wing=args.wing,
        room=args.room,
        since=args.since,
        include_vectors=args.with_embeddings,
        include_kg=args.with_kg,
        pretty=args.pretty,
        palace_path=palace_path,
    )
    print(
        f"  Exported {summary['drawer_count']} drawers, {summary['kg_count']} KG triples → {args.out}",
        file=sys.stderr,
    )
    if summary["drawer_count"] == 0 and summary["kg_count"] == 0:
        print(
            "  Next: relax export filters (--only-manual/--wing/--room/--since), "
            "or mine/add content before exporting.",
            file=sys.stderr,
        )


def cmd_import(args):
    from ..export import import_jsonl
    from ..knowledge_graph import KnowledgeGraph
    from ..storage import open_store

    palace_path = args.palace or MempalaceConfig().palace_path
    store = open_store(palace_path, create=True)
    kg = None if args.skip_kg else KnowledgeGraph()

    print(f"  Importing into: {palace_path}")
    if args.dry_run:
        print("  (dry run — nothing will be written)")

    summary = import_jsonl(
        path=args.jsonl_file,
        store=store,
        kg=kg,
        skip_dedup=args.skip_dedup,
        skip_kg=args.skip_kg,
        dry_run=args.dry_run,
        wing_override=args.wing_override,
    )

    print(f"  Imported drawers:   {summary['imported_drawers']}")
    print(f"  Skipped duplicates: {summary['skipped_duplicates']}")
    print(f"  Imported KG triples:{summary['imported_triples']}")
    if args.dry_run:
        print("  (dry run — no changes made)")
    for w in summary["warnings"]:
        print(f"  WARNING: {w}")
