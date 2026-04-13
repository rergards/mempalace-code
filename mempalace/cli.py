#!/usr/bin/env python3
"""
MemPalace — Give your AI a memory. No API key required.

Two ways to ingest:
  Projects:      mempalace mine ~/projects/my_app          (code, docs, notes)
  Conversations: mempalace mine ~/chats/ --mode convos     (Claude, ChatGPT, Slack)

Same palace. Same search. Different ingest strategies.

Commands:
    mempalace init <dir>                  Detect rooms from folder structure
    mempalace split <dir>                 Split concatenated mega-files into per-session files
    mempalace mine <dir>                  Mine project files (default)
    mempalace mine <dir> --mode convos    Mine conversation exports
    mempalace search "query"              Find anything, exact words
    mempalace wake-up                     Show L0 + L1 wake-up context
    mempalace wake-up --wing my_app       Wake-up for a specific project
    mempalace status                      Show what's been filed
    mempalace diary write --agent <name> --entry "<text>"  Write a diary entry

Examples:
    mempalace init ~/projects/my_app
    mempalace mine ~/projects/my_app
    mempalace mine ~/chats/claude-sessions --mode convos
    mempalace search "why did we switch to GraphQL"
    mempalace search "pricing discussion" --wing my_app --room costs
    mempalace diary write --agent claude-code --entry "Finished feature X" --topic dev
"""

import os
import sys
import argparse
from pathlib import Path

from .config import MempalaceConfig


def fetch_model(model_name: str, force: bool = False) -> None:
    """Download *model_name* to the HuggingFace Hub cache.

    Shared by ``cmd_fetch_model`` and ``cmd_init``.  When *force* is True the
    cached model directory is removed before downloading so a fresh copy is
    retrieved.
    """
    import shutil
    from sentence_transformers import SentenceTransformer

    # Compute cache dir at call time so HF_HOME env-var changes (e.g. in tests) are respected.
    # huggingface_hub.constants.HF_HUB_CACHE is a module-level string set at import time and
    # does not update when os.environ changes after Python starts.
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cache_dir = hf_home / "hub"
    # Standard Hub layout: models--{org}--{model}
    model_dir = cache_dir / f"models--sentence-transformers--{model_name}"

    if force and model_dir.exists():
        print(f"  Removing cached model: {model_dir}")
        shutil.rmtree(model_dir)

    print(f"  Downloading model '{model_name}' …")
    SentenceTransformer(model_name)

    # Report cache location and size
    if model_dir.exists():
        size_bytes = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
        size_mb = size_bytes / (1024 * 1024)
        print(f"  Cached at: {model_dir}")
        print(f"  Size on disk: {size_mb:.1f} MB")
    else:
        print(f"  Model ready (cache path not found at expected location: {model_dir})")


def cmd_fetch_model(args):
    from .storage import DEFAULT_EMBED_MODEL

    model_name = args.model or DEFAULT_EMBED_MODEL
    try:
        fetch_model(model_name, force=args.force)
        print("  Done — embedding model is ready for offline use.")
    except Exception as exc:
        print(f"  Error downloading model: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_init(args):
    import json
    from pathlib import Path
    from .entity_detector import scan_for_detection, detect_entities, confirm_entities
    from .room_detector_local import detect_rooms_local

    # Pass 1: auto-detect people and projects from file content
    print(f"\n  Scanning for entities in: {args.dir}")
    files = scan_for_detection(args.dir)
    if files:
        print(f"  Reading {len(files)} files...")
        detected = detect_entities(files)
        total = len(detected["people"]) + len(detected["projects"]) + len(detected["uncertain"])
        if total > 0:
            confirmed = confirm_entities(detected, yes=getattr(args, "yes", False))
            # Save confirmed entities to <project>/entities.json for the miner
            if confirmed["people"] or confirmed["projects"]:
                entities_path = Path(args.dir).expanduser().resolve() / "entities.json"
                with open(entities_path, "w") as f:
                    json.dump(confirmed, f, indent=2)
                print(f"  Entities saved: {entities_path}")
        else:
            print("  No entities detected — proceeding with directory-based rooms.")

    # Pass 2: detect rooms from folder structure
    detect_rooms_local(project_dir=args.dir, yes=getattr(args, "yes", False))
    MempalaceConfig().init()

    if not getattr(args, "skip_model_download", False):
        from .storage import DEFAULT_EMBED_MODEL

        print("\n  Downloading embedding model (~80 MB)…")
        try:
            fetch_model(DEFAULT_EMBED_MODEL)
        except Exception as exc:
            print(f"  Warning: model download failed: {exc}", file=sys.stderr)
            print(
                "  Run 'mempalace fetch-model' manually when network is available.", file=sys.stderr
            )


def cmd_mine(args):
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    include_ignored = []
    for raw in args.include_ignored or []:
        include_ignored.extend(part.strip() for part in raw.split(",") if part.strip())

    if args.mode == "convos":
        from .convo_miner import mine_convos

        mine_convos(
            convo_dir=args.dir,
            palace_path=palace_path,
            wing=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            extract_mode=args.extract,
        )
    else:
        from .miner import mine

        mine(
            project_dir=args.dir,
            palace_path=palace_path,
            wing_override=args.wing,
            agent=args.agent,
            limit=args.limit,
            dry_run=args.dry_run,
            respect_gitignore=not args.no_gitignore,
            include_ignored=include_ignored,
            incremental=not args.full,
        )


def cmd_search(args):
    from .searcher import search, SearchError

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    try:
        search(
            query=args.query,
            palace_path=palace_path,
            wing=args.wing,
            room=args.room,
            n_results=args.results,
        )
    except SearchError:
        sys.exit(1)


def cmd_wakeup(args):
    """Show L0 (identity) + L1 (essential story) — the wake-up context."""
    from .layers import MemoryStack

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    stack = MemoryStack(palace_path=palace_path)

    text = stack.wake_up(wing=args.wing)
    tokens = len(text) // 4
    print(f"Wake-up text (~{tokens} tokens):")
    print("=" * 50)
    print(text)


def cmd_split(args):
    """Split concatenated transcript mega-files into per-session files."""
    from .split_mega_files import main as split_main
    import sys

    # Rebuild argv for split_mega_files argparse
    argv = ["--source", args.dir]
    if args.output_dir:
        argv += ["--output-dir", args.output_dir]
    if args.dry_run:
        argv.append("--dry-run")
    if args.min_sessions != 2:
        argv += ["--min-sessions", str(args.min_sessions)]

    old_argv = sys.argv
    sys.argv = ["mempalace split"] + argv
    try:
        split_main()
    finally:
        sys.argv = old_argv


def cmd_status(args):
    from .miner import status

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    status(palace_path=palace_path)


def cmd_diary_write(args):
    import hashlib
    from datetime import datetime
    from .storage import open_store
    from .version import __version__

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    agent_name = args.agent
    entry = args.entry
    topic = args.topic
    wing = args.wing or f"wing_{agent_name.lower().replace(' ', '_')}"
    room = "diary"

    try:
        store = open_store(palace_path, create=True)
    except Exception as e:
        print(f"Cannot open palace at {palace_path}: {e}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now()
    entry_id = (
        f"diary_{wing}_{now.strftime('%Y%m%d_%H%M%S')}"
        f"_{hashlib.md5(entry[:50].encode()).hexdigest()[:8]}"
    )

    try:
        store.add(
            ids=[entry_id],
            documents=[entry],
            metadatas=[
                {
                    "wing": wing,
                    "room": room,
                    "hall": "hall_diary",
                    "topic": topic,
                    "type": "diary_entry",
                    "agent": agent_name,
                    "filed_at": now.isoformat(),
                    "date": now.strftime("%Y-%m-%d"),
                    "extractor_version": __version__,
                    "chunker_strategy": "diary_v1",
                }
            ],
        )
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def cmd_diary(args):
    if args.diary_command == "write":
        cmd_diary_write(args)
    else:
        args._diary_parser.print_help()
        sys.exit(2)


def cmd_migrate_storage(args):
    """Migrate a ChromaDB palace to a LanceDB palace."""
    from .migrate import migrate_chroma_to_lance, VerificationError

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


def cmd_repair(args):
    """Rebuild palace — extract all drawers, backup, and re-insert."""
    import shutil
    from .storage import open_store

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

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


def cmd_compress(args):
    """Compress drawers in a wing using AAAK Dialect."""
    from .storage import open_store
    from .dialect import Dialect

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    # Load dialect (with optional entity config)
    config_path = args.config
    if not config_path:
        for candidate in ["entities.json", os.path.join(palace_path, "entities.json")]:
            if os.path.exists(candidate):
                config_path = candidate
                break

    if config_path and os.path.exists(config_path):
        dialect = Dialect.from_config(config_path)
        print(f"  Loaded entity config: {config_path}")
    else:
        dialect = Dialect()

    # Connect to palace
    try:
        store = open_store(palace_path, create=False)
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace init <dir> then mempalace mine <dir>")
        sys.exit(1)

    # Query drawers in batches
    where = {"wing": args.wing} if args.wing else None
    _BATCH = 500
    docs, metas, ids = [], [], []
    offset = 0
    while True:
        try:
            batch = store.get(
                include=["documents", "metadatas"], limit=_BATCH, offset=offset, where=where
            )
        except Exception as e:
            if not docs:
                print(f"\n  Error reading drawers: {e}")
                sys.exit(1)
            break
        batch_docs = batch.get("documents", [])
        if not batch_docs:
            break
        docs.extend(batch_docs)
        metas.extend(batch.get("metadatas", []))
        ids.extend(batch.get("ids", []))
        offset += len(batch_docs)
        if len(batch_docs) < _BATCH:
            break

    if not docs:
        wing_label = f" in wing '{args.wing}'" if args.wing else ""
        print(f"\n  No drawers found{wing_label}.")
        return

    print(
        f"\n  Compressing {len(docs)} drawers"
        + (f" in wing '{args.wing}'" if args.wing else "")
        + "..."
    )
    print()

    total_original = 0
    total_compressed = 0
    compressed_entries = []

    for doc, meta, doc_id in zip(docs, metas, ids):
        compressed = dialect.compress(doc, metadata=meta)
        stats = dialect.compression_stats(doc, compressed)

        total_original += stats["original_chars"]
        total_compressed += stats["compressed_chars"]

        compressed_entries.append((doc_id, compressed, meta, stats))

        if args.dry_run:
            wing_name = meta.get("wing", "?")
            room_name = meta.get("room", "?")
            source = Path(meta.get("source_file", "?")).name
            print(f"  [{wing_name}/{room_name}] {source}")
            print(
                f"    {stats['original_tokens']}t -> {stats['compressed_tokens']}t ({stats['ratio']:.1f}x)"
            )
            print(f"    {compressed}")
            print()

    # Store compressed versions (unless dry-run)
    if not args.dry_run:
        try:
            # Upsert compressed drawers back into the main store
            for doc_id, compressed, meta, stats in compressed_entries:
                comp_meta = dict(meta)
                comp_meta["compression_ratio"] = round(stats["ratio"], 1)
                comp_meta["original_tokens"] = stats["original_tokens"]
                store.upsert(
                    ids=[doc_id],
                    documents=[compressed],
                    metadatas=[comp_meta],
                )
            print(f"  Stored {len(compressed_entries)} compressed drawers.")
        except Exception as e:
            print(f"  Error storing compressed drawers: {e}")
            sys.exit(1)

    # Summary
    ratio = total_original / max(total_compressed, 1)
    orig_tokens = Dialect.count_tokens("x" * total_original)
    comp_tokens = Dialect.count_tokens("x" * total_compressed)
    print(f"  Total: {orig_tokens:,}t -> {comp_tokens:,}t ({ratio:.1f}x compression)")
    if args.dry_run:
        print("  (dry run -- nothing stored)")


def cmd_export(args):
    from .storage import open_store
    from .knowledge_graph import KnowledgeGraph
    from .export import write_jsonl

    palace_path = args.palace or MempalaceConfig().palace_path
    store = open_store(palace_path, create=False)
    kg = KnowledgeGraph() if args.with_kg else None

    print(f"  Exporting from: {palace_path}")
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
        f"  Exported {summary['drawer_count']} drawers, {summary['kg_count']} KG triples → {args.out}"
    )


def cmd_import(args):
    from .storage import open_store
    from .knowledge_graph import KnowledgeGraph
    from .export import import_jsonl

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


def main():
    parser = argparse.ArgumentParser(
        description="MemPalace — Give your AI a memory. No API key required.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--palace",
        default=None,
        help="Where the palace lives (default: from ~/.mempalace/config.json or ~/.mempalace/palace)",
    )

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Detect rooms from your folder structure")
    p_init.add_argument("dir", help="Project directory to set up")
    p_init.add_argument(
        "--yes", action="store_true", help="Auto-accept all detected entities (non-interactive)"
    )
    p_init.add_argument(
        "--skip-model-download",
        action="store_true",
        dest="skip_model_download",
        help="Skip automatic embedding model download (run 'fetch-model' later)",
    )

    # mine
    p_mine = sub.add_parser("mine", help="Mine files into the palace")
    p_mine.add_argument("dir", help="Directory to mine")
    p_mine.add_argument(
        "--mode",
        choices=["projects", "convos"],
        default="projects",
        help="Ingest mode: 'projects' for code/docs (default), 'convos' for chat exports",
    )
    p_mine.add_argument("--wing", default=None, help="Wing name (default: directory name)")
    p_mine.add_argument(
        "--no-gitignore",
        action="store_true",
        help="Don't respect .gitignore files when scanning project files",
    )
    p_mine.add_argument(
        "--include-ignored",
        action="append",
        default=[],
        help="Always scan these project-relative paths even if ignored; repeat or pass comma-separated paths",
    )
    p_mine.add_argument(
        "--agent",
        default="mempalace",
        help="Your name — recorded on every drawer (default: mempalace)",
    )
    p_mine.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    p_mine.add_argument(
        "--dry-run", action="store_true", help="Show what would be filed without filing"
    )
    p_mine.add_argument(
        "--full",
        action="store_true",
        help="Force full rebuild — re-mine all files even if content is unchanged",
    )
    p_mine.add_argument(
        "--extract",
        choices=["exchange", "general"],
        default="exchange",
        help="Extraction strategy for convos mode: 'exchange' (default) or 'general' (5 memory types)",
    )

    # search
    p_search = sub.add_parser("search", help="Find anything, exact words")
    p_search.add_argument("query", help="What to search for")
    p_search.add_argument("--wing", default=None, help="Limit to one project")
    p_search.add_argument("--room", default=None, help="Limit to one room")
    p_search.add_argument("--results", type=int, default=5, help="Number of results")

    # compress
    p_compress = sub.add_parser(
        "compress", help="Compress drawers using AAAK Dialect (~30x reduction)"
    )
    p_compress.add_argument("--wing", default=None, help="Wing to compress (default: all wings)")
    p_compress.add_argument(
        "--dry-run", action="store_true", help="Preview compression without storing"
    )
    p_compress.add_argument(
        "--config", default=None, help="Entity config JSON (e.g. entities.json)"
    )

    # wake-up
    p_wakeup = sub.add_parser("wake-up", help="Show L0 + L1 wake-up context (~600-900 tokens)")
    p_wakeup.add_argument("--wing", default=None, help="Wake-up for a specific project/wing")

    # split
    p_split = sub.add_parser(
        "split",
        help="Split concatenated transcript mega-files into per-session files (run before mine)",
    )
    p_split.add_argument("dir", help="Directory containing transcript files")
    p_split.add_argument(
        "--output-dir",
        default=None,
        help="Write split files here (default: same directory as source files)",
    )
    p_split.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be split without writing files",
    )
    p_split.add_argument(
        "--min-sessions",
        type=int,
        default=2,
        help="Only split files containing at least N sessions (default: 2)",
    )

    # diary
    p_diary = sub.add_parser("diary", help="Diary commands")
    diary_sub = p_diary.add_subparsers(dest="diary_command")

    p_diary_write = diary_sub.add_parser("write", help="Write a diary entry")
    p_diary_write.add_argument("--agent", required=True, help="Agent name (e.g. claude-code)")
    p_diary_write.add_argument(
        "--entry", required=True, help="Diary entry content (stored verbatim)"
    )
    p_diary_write.add_argument("--topic", default="general", help="Topic tag (default: general)")
    p_diary_write.add_argument(
        "--wing", default=None, help="Override target wing (default: wing_<agent>)"
    )

    # migrate-storage
    p_migrate = sub.add_parser(
        "migrate-storage",
        help="Migrate a ChromaDB palace to LanceDB (requires mempalace[chroma])",
    )
    p_migrate.add_argument("src_palace", help="Source ChromaDB palace path")
    p_migrate.add_argument("dst_palace", help="Destination LanceDB palace path")
    p_migrate.add_argument(
        "--backup-dir",
        default=None,
        help="Directory for the source backup tar.gz (default: parent of src_palace)",
    )
    p_migrate.add_argument(
        "--force",
        action="store_true",
        help="Allow appending to a non-empty destination palace",
    )
    p_migrate.add_argument(
        "--embed-model",
        default=None,
        help="Embedding model for the destination (default: all-MiniLM-L6-v2)",
    )
    p_migrate.add_argument(
        "--verify",
        action="store_true",
        help="Verify per-wing counts after migration; exit non-zero on mismatch",
    )

    # repair
    sub.add_parser(
        "repair",
        help="Rebuild palace vector index from stored data (fixes segfaults after corruption)",
    )

    # status
    sub.add_parser("status", help="Show what's been filed")

    # fetch-model
    p_fetch = sub.add_parser("fetch-model", help="Download the embedding model (~80 MB)")
    p_fetch.add_argument(
        "--model",
        default=None,
        help="Model name (default: all-MiniLM-L6-v2)",
    )
    p_fetch.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )

    # export
    p_export = sub.add_parser("export", help="Export drawers (and KG) to a JSONL file for backup")
    p_export.add_argument(
        "--out",
        required=True,
        metavar="FILE",
        help="Output JSONL file path (use '-' for stdout)",
    )
    p_export.add_argument(
        "--only-manual",
        action="store_true",
        help="Export only manually-added drawers (chunker_strategy in manual_v1, diary_v1)",
    )
    p_export.add_argument("--wing", default=None, help="Limit export to one wing")
    p_export.add_argument("--room", default=None, help="Limit export to one room")
    p_export.add_argument(
        "--since",
        default=None,
        metavar="DATE",
        help="Export only drawers filed on or after this ISO date (e.g. 2026-01-01)",
    )
    p_export.add_argument("--with-kg", action="store_true", help="Include KG triples in export")
    p_export.add_argument(
        "--with-embeddings",
        action="store_true",
        help="Include raw embedding vectors (larger file)",
    )
    p_export.add_argument("--pretty", action="store_true", help="Pretty-print JSON (larger file)")

    # import
    p_import = sub.add_parser("import", help="Import drawers (and KG) from a JSONL export file")
    p_import.add_argument("jsonl_file", help="JSONL export file to import (use '-' for stdin)")
    p_import.add_argument(
        "--skip-dedup",
        action="store_true",
        help="Skip duplicate detection (import all records regardless of similarity)",
    )
    p_import.add_argument("--skip-kg", action="store_true", help="Skip KG triple import")
    p_import.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be imported without writing anything",
    )
    p_import.add_argument(
        "--wing-override",
        default=None,
        metavar="WING",
        help="Override the wing for all imported drawers",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "diary" and not args.diary_command:
        p_diary.print_help()
        sys.exit(2)

    if args.command == "diary":
        args._diary_parser = p_diary

    dispatch = {
        "init": cmd_init,
        "mine": cmd_mine,
        "split": cmd_split,
        "search": cmd_search,
        "compress": cmd_compress,
        "wake-up": cmd_wakeup,
        "migrate-storage": cmd_migrate_storage,
        "repair": cmd_repair,
        "status": cmd_status,
        "diary": cmd_diary,
        "fetch-model": cmd_fetch_model,
        "export": cmd_export,
        "import": cmd_import,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
