"""Query command handlers: search, wake-up, compress, read."""

import os
import shlex
import sys
from pathlib import Path

from ..config import MempalaceConfig


def cmd_search(args):
    if not args.query.strip():
        print("Error: query must not be blank.", file=sys.stderr)
        print("Try: mempalace-code search 'your search query'", file=sys.stderr)
        sys.exit(2)

    from ..searcher import SearchError, search
    from ..taxonomy_filters import TaxonomyValidationError, format_cli_lines

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    try:
        search(
            query=args.query,
            palace_path=palace_path,
            wing=args.wing,
            room=args.room,
            n_results=args.results,
        )
    except TaxonomyValidationError as e:
        for line in format_cli_lines(e.payload):
            print(line, file=sys.stderr)
        sys.exit(2)
    except SearchError:
        sys.exit(1)


def cmd_wakeup(args):
    """Show L0 (identity) + L1 (essential story) — the wake-up context."""
    from ..layers import MemoryStack
    from ..taxonomy_filters import format_cli_lines, validate_taxonomy_filters

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if args.wing is not None:
        taxonomy_error = validate_taxonomy_filters(palace_path, wing=args.wing)
        if taxonomy_error:
            for line in format_cli_lines(taxonomy_error):
                print(line, file=sys.stderr)
            sys.exit(2)

    stack = MemoryStack(palace_path=palace_path)

    text = stack.wake_up(wing=args.wing)
    tokens = len(text) // 4
    print(f"Wake-up text (~{tokens} tokens):")
    print("=" * 50)
    print(text)


def cmd_compress(args):
    """Compress drawers in a wing using AAAK Dialect."""
    from ..backup import create_backup
    from ..dialect import Dialect
    from ..knowledge_graph import palace_kg_path
    from ..storage import open_store
    from ..taxonomy_filters import format_cli_lines, validate_taxonomy_filters

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if args.wing:
        taxonomy_error = validate_taxonomy_filters(palace_path, wing=args.wing)
        if taxonomy_error:
            for line in format_cli_lines(taxonomy_error):
                print(line, file=sys.stderr)
            sys.exit(2)

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

    # Connect to palace — dry-run only reads rows; live mode upserts compressed drawers.
    try:
        store = open_store(palace_path, create=False, read_only=args.dry_run)
    except Exception:
        print(f"\n  No palace found at {palace_path}")
        print("  Run: mempalace-code init <dir> then mempalace-code mine <dir>")
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
        print("  Next: check --wing/--room filters, or run mempalace-code mine <project-dir>.")
        return

    pending = []
    already_compressed = []
    for doc, meta, doc_id in zip(docs, metas, ids):
        original_tokens = meta.get("original_tokens", 0) or 0
        compression_ratio = meta.get("compression_ratio", 0.0) or 0.0
        entry = (doc, meta, doc_id)
        if original_tokens > 0 or compression_ratio != 0.0:
            already_compressed.append(entry)
        else:
            pending.append(entry)

    print(
        f"\n  Selected {len(docs)} drawers" + (f" in wing '{args.wing}'" if args.wing else "") + "."
    )
    print(f"  Pending: {len(pending)}; skipped already compressed: {len(already_compressed)}.")

    if not pending:
        print("  No pending drawers; nothing stored.")
        if args.dry_run:
            print("  (dry run -- nothing stored)")
        return

    print(f"  Compressing {len(pending)} pending drawers...")
    print()

    total_original = 0
    total_compressed = 0
    total_original_tokens = 0
    total_compressed_tokens = 0
    compressed_entries = []

    for doc, meta, doc_id in pending:
        compressed = dialect.compress(doc, metadata=meta)
        stats = dialect.compression_stats(doc, compressed)

        total_original += stats["original_chars"]
        total_compressed += stats["summary_chars"]
        total_original_tokens += stats["original_tokens_est"]
        total_compressed_tokens += stats["summary_tokens_est"]

        compressed_entries.append((doc_id, compressed, meta, stats))

        if args.dry_run:
            wing_name = meta.get("wing", "?")
            room_name = meta.get("room", "?")
            source = Path(meta.get("source_file", "?")).name
            print(f"  [{wing_name}/{room_name}] {source}")
            print(
                f"    {stats['original_tokens_est']}t -> {stats['summary_tokens_est']}t ({stats['size_ratio']:.1f}x)"
            )
            print(f"    {compressed}")
            print()

    # Store compressed versions (unless dry-run)
    if not args.dry_run:
        kg_path = palace_kg_path(palace_path) if args.palace else None
        try:
            _, archive_path = create_backup(palace_path, kind="manual", kg_path=kg_path)
        except Exception as e:
            print(f"  Error creating pre-compression backup: {e}", file=sys.stderr)
            sys.exit(1)

        recovery_command = shlex.join(
            [
                "mempalace-code",
                "--palace",
                os.path.abspath(palace_path),
                "restore",
                str(archive_path),
                "--force",
            ]
        )
        print(f"  Recovery archive: {archive_path}")
        print(f"  Recovery command: {recovery_command}")

        try:
            # Upsert compressed drawers back into the main store
            for doc_id, compressed, meta, stats in compressed_entries:
                comp_meta = dict(meta)
                comp_meta["compression_ratio"] = round(stats["size_ratio"], 1)
                comp_meta["original_tokens"] = stats["original_tokens_est"]
                store.upsert(
                    ids=[doc_id],
                    documents=[compressed],
                    metadatas=[comp_meta],
                )
        except Exception as e:
            print(f"  Error storing compressed drawers: {e}", file=sys.stderr)
            print(f"  Recover with: {recovery_command}", file=sys.stderr)
            sys.exit(1)

        expected = {
            doc_id: (
                compressed,
                round(stats["size_ratio"], 1),
                stats["original_tokens_est"],
            )
            for doc_id, compressed, _meta, stats in compressed_entries
        }
        try:
            stored = store.get(
                ids=list(expected),
                include=["documents", "metadatas"],
                limit=len(expected),
            )
            stored_rows = list(
                zip(
                    stored.get("ids", []),
                    stored.get("documents", []),
                    stored.get("metadatas", []),
                )
            )
            verified = (
                len(stored_rows) == len(expected)
                and len({row[0] for row in stored_rows}) == len(expected)
                and all(
                    doc_id in expected
                    and document == expected[doc_id][0]
                    and round(float(metadata.get("compression_ratio", 0.0)), 1)
                    == expected[doc_id][1]
                    and metadata.get("original_tokens") == expected[doc_id][2]
                    for doc_id, document, metadata in stored_rows
                )
            )
        except Exception:
            verified = False

        if not verified:
            print("  Error verifying stored compressed drawers.", file=sys.stderr)
            print(f"  Recover with: {recovery_command}", file=sys.stderr)
            sys.exit(1)

        print(f"  Stored and verified {len(compressed_entries)} compressed drawers.")

    # Summary
    ratio = total_original / max(total_compressed, 1)
    print(
        f"  Total: {total_original_tokens:,}t -> {total_compressed_tokens:,}t "
        f"({ratio:.1f}x compression)"
    )
    if args.dry_run:
        print("  (dry run -- nothing stored)")


def cmd_read(args):
    """Print stored source lines for a file and line range."""
    from ..config import MempalaceConfig
    from ..reader import read_slice
    from ..storage import open_store

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(
            "  Next: run mempalace-code init <dir>, then mempalace-code mine <dir>.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        store = open_store(palace_path, create=False, read_only=True)
    except Exception:
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(
            "  Next: run mempalace-code init <dir>, then mempalace-code mine <dir>.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = read_slice(store, args.source_file, args.start, args.end, wing=args.wing)

    error = result.get("error")
    if error in ("unknown_wing", "unknown_room", "unknown_wing_room"):
        from ..taxonomy_filters import format_cli_lines

        for line in format_cli_lines(result):
            print(line, file=sys.stderr)
        sys.exit(2)
    if error == "not_found":
        print(
            f"\n  Not found: no palace chunks for '{result.get('source_file', args.source_file)}'",
            file=sys.stderr,
        )
        print(
            '  Next: run mempalace-code search "<query>" and copy the exact Source path; '
            "if the file should be indexed, rerun mempalace-code mine <project-dir>.",
            file=sys.stderr,
        )
        sys.exit(1)
    if error == "stale_pointer":
        print(f"\n  Stale pointer: {result.get('detail', '')}", file=sys.stderr)
        print(f"  source_file: {result.get('source_file', args.source_file)}", file=sys.stderr)
        print(
            "  Next: rerun mempalace-code mine <project-dir> to refresh line metadata, "
            "then retry with the Source path from search.",
            file=sys.stderr,
        )
        sys.exit(1)
    if error == "invalid_range":
        print(f"\n  Invalid range: {result.get('detail', '')}", file=sys.stderr)
        print(
            "  Next: pass positive line numbers with --start less than or equal to --end.",
            file=sys.stderr,
        )
        sys.exit(1)
    if error == "ambiguous_source":
        print(
            f"\n  Ambiguous source: '{args.source_file}' matches multiple stored paths.",
            file=sys.stderr,
        )
        print(
            "  Next: retry with the full stored path from one of these candidates:", file=sys.stderr
        )
        for candidate in result.get("candidates", []):
            print(f"    {candidate}", file=sys.stderr)
        sys.exit(1)
    if error:
        print(f"\n  Error: {error}", file=sys.stderr)
        sys.exit(1)

    for entry in result.get("lines", []):
        print(f"{entry['line']:6}: {entry['text']}")
