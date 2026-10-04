"""Export and import command handlers."""

import contextlib
import os
import shlex
import sqlite3
import sys

from ..config import MempalaceConfig


def cmd_export(args):
    from ..export import validate_since, write_jsonl
    from ..knowledge_graph import ensure_kg_readable, open_palace_kg, palace_kg_path
    from ..storage import ChromaRuntimeRetiredError, open_store
    from ..taxonomy_filters import format_cli_lines, validate_taxonomy_filters
    from .common import no_palace_next_step, palace_command, palace_holds_state

    palace_path = args.palace or MempalaceConfig().palace_path
    try:
        validate_since(args.since)
    except ValueError as exc:
        print(f"  Error: {exc}", file=sys.stderr)
        print("  Next: pass --since as YYYY-MM-DD, e.g. --since 2026-01-01.", file=sys.stderr)
        sys.exit(1)
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
    except ChromaRuntimeRetiredError:
        raise  # names its one recovery command; the global CLI handler prints it
    except Exception as exc:
        print(f"  Error: cannot open palace at {palace_path}: {exc}", file=sys.stderr)
        print(
            "  Next: if this is the wrong palace, pass the correct --palace path. "
            f"If this is your palace, run {palace_command(palace_path, 'health')}, "
            f"then {palace_command(palace_path, 'repair', '--rollback', '--dry-run')} "
            "before retrying export.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not palace_holds_state(palace_path):
        # A project directory or an empty one: no drawers and no knowledge graph.
        print(f"  Error: no palace found at {palace_path}", file=sys.stderr)
        print(f"  Next: {no_palace_next_step(palace_path)}", file=sys.stderr)
        sys.exit(1)
    taxonomy_error = validate_taxonomy_filters(palace_path, wing=args.wing, room=args.room)
    if taxonomy_error:
        for line in format_cli_lines(taxonomy_error):
            print(line, file=sys.stderr)
        sys.exit(2)
    kg = None
    if args.with_kg:
        # A corrupt KG fails here, naming the file and its recovery, before any output.
        ensure_kg_readable(palace_kg_path(palace_path), palace_path)
        kg = open_palace_kg(palace_path)

    print(f"  Exporting from: {palace_path}", file=sys.stderr)
    try:
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
            palace_path=palace_path,
        )
    except FileExistsError:
        print(f"  Error: cannot write export to {args.out}: it already exists", file=sys.stderr)
        print(
            "  Next: rerun with --out set to a new file path; export never overwrites.",
            file=sys.stderr,
        )
        sys.exit(1)
    except OSError as exc:
        print(f"  Error: cannot write export to {args.out}: {exc.strerror or exc}", file=sys.stderr)
        print("  Next: pass --out a writable file path (or - for stdout).", file=sys.stderr)
        sys.exit(1)
    except sqlite3.DatabaseError as exc:
        # The KG became unreadable mid-export; the partial output file was removed.
        print(
            f"  Error: knowledge graph {palace_kg_path(palace_path)} is unreadable ({exc}); "
            "nothing was exported.",
            file=sys.stderr,
        )
        print(
            f"  Next: {palace_command(palace_path, 'health')}; to save the drawers only, "
            "rerun export without --with-kg.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"  Exported {summary['drawer_count']} drawers, {summary['kg_count']} KG triples → {args.out}",
        file=sys.stderr,
    )
    if args.with_kg and summary.get("kg_scope") == "drawer_sources":
        print(
            "  KG scope: only facts extracted from the exported drawers' source files; "
            "export without --wing/--room to include the whole palace KG.",
            file=sys.stderr,
        )
    if summary["drawer_count"] == 0 and summary["kg_count"] == 0:
        print(
            "  Next: relax export filters (--only-manual/--wing/--room/--since), "
            "or mine/add content before exporting.",
            file=sys.stderr,
        )


_SUMMARY_COUNTS = (
    "imported_drawers",
    "skipped_duplicates",
    "skipped_invalid",
    "failed_drawers",
    "imported_triples",
    "skipped_kg_duplicates",
    "invalid_triples",
    "kg_invalidations_applied",
    "kg_conflicts",
    "imported_kg_entities",
    "rejected",
)


def _import_command(palace_path: str, args, *, skip_kg: bool = False) -> str:
    """Return the ``import`` command line for *args*, keeping every import option."""
    argv = ["mempalace-code", "--palace", palace_path, "import", args.jsonl_file]
    if args.wing_override is not None:
        argv += ["--wing-override", args.wing_override]
    if args.skip_dedup:
        argv.append("--skip-dedup")
    if args.skip_kg or skip_kg:
        argv.append("--skip-kg")
    if args.dry_run:
        argv.append("--dry-run")
    return shlex.join(argv)


def _refuse_respelled_wing_override(store, wing: str) -> None:
    """Exit 2 when a new --wing-override only re-spells an existing wing (the add_drawer rule)."""
    from ..taxonomy_filters import near_duplicate_names

    try:
        taxonomy = store.count_by_pair("wing", "room")
    except Exception:
        return  # an absent or degraded palace: the import itself reports real failures
    similar = near_duplicate_names(wing, taxonomy)
    if similar:
        print(
            f"  Error: --wing-override {wing!r} differs from the existing wing {similar[0]!r} "
            "only by case, spacing or punctuation; wing names are case-sensitive.",
            file=sys.stderr,
        )
        print(
            f"  Next: pass --wing-override {shlex.quote(similar[0])} to import into the "
            "existing wing, or choose a clearly different name.",
            file=sys.stderr,
        )
        sys.exit(2)


def _refuse_legacy_kg_export(records: list, args, palace_path: str) -> None:
    """Stop or warn before any write when a pre-1.15.0 export may hold the legacy global KG.

    Through 1.14.2, ``export --with-kg`` without ``--palace`` wrote the legacy
    ``~/.mempalace/knowledge_graph.sqlite3`` instead of the palace KG. Replaying it
    would leave out every fact added through MCP and reopen facts the palace ended.
    The header does not record ``--palace``, so the triple ids decide: all of them
    in the legacy file proves the legacy source; when there are no ids or no legacy
    file, the source is unknown, and the import refuses only when it would be lossless
    to skip the file's (empty) KG while a palace KG holds facts, and warns otherwise.
    """
    from .. import knowledge_graph
    from .common import palace_command

    header = next((r for r in records if r.get("type") == "export_header"), None) or {}
    version = header.get("version")
    if not knowledge_graph._predates_adoption(version):
        return
    raw_filters = header.get("filters")
    filters: dict = raw_filters if isinstance(raw_filters, dict) else {}
    triple_ids = [r.get("id") for r in records if r.get("type") == "kg_triple"]
    if not triple_ids and not filters.get("with_kg"):
        return  # the export carries no KG at all: nothing to replay or lose
    origin = knowledge_graph.pre_adoption_kg_origin(triple_ids)
    if origin == "palace":
        return
    legacy = knowledge_graph.DEFAULT_KG_PATH
    header_palace = header.get("palace_path")
    source = header_palace if isinstance(header_palace, str) else palace_path
    if not os.path.isdir(source):
        source = palace_path
    flags = ["--only-manual"] if filters.get("only_manual") else []
    for name in ("wing", "room", "since"):
        if isinstance(filters.get(name), str):
            flags += [f"--{name}", filters[name]]
    stem = "export" if args.jsonl_file == "-" else os.path.splitext(args.jsonl_file)[0]
    export = palace_command(source, "export", *flags, "--with-kg", "--out", f"{stem}-palace.jsonl")
    reexport = (
        f"export the palace again with this release: {export} (if that palace was moved "
        "aside for a rebuild, pass its new path), then import that file"
    )
    if origin == "unknown":
        kg_paths = [knowledge_graph.palace_kg_path(palace_path)]
        if isinstance(header_palace, str) and os.path.isdir(header_palace):
            kg_paths.append(knowledge_graph.palace_kg_path(header_palace))
        held = max(
            ((knowledge_graph.kg_ids_missing_from(p, triple_ids), p) for p in kg_paths),
            key=lambda pair: pair[0],
        )
        if not triple_ids and held[0]:
            print(
                f"  Error: {args.jsonl_file} was exported by mempalace-code {version} with "
                f"--with-kg but holds no KG records, while the palace knowledge graph "
                f"{held[1]} holds {held[0]} fact(s). Through 1.14.2 an export run without "
                "--palace wrote the legacy global knowledge graph, so this file may lack "
                "every fact added through MCP, and a palace rebuilt from it would lose "
                "them. Nothing was imported.",
                file=sys.stderr,
            )
            print(
                f"  Next: {reexport}. To import this file anyway, add --skip-kg (it holds "
                "no KG records, so nothing is skipped).",
                file=sys.stderr,
            )
            sys.exit(1)
        what = (
            "holds no KG records"
            if not triple_ids
            else f"holds {len(triple_ids)} KG record(s) and the legacy file {legacy} is gone"
        )
        print(
            f"  WARNING: {args.jsonl_file} was exported by mempalace-code {version} and {what}. "
            "If that export ran without --palace, its KG is the legacy global knowledge "
            "graph, not the palace KG: facts added through MCP are missing from it. If "
            f"you are rebuilding a palace, {reexport}.",
            file=sys.stderr,
        )
        return
    print(
        f"  Error: {args.jsonl_file} was exported by mempalace-code {version} without "
        f"--palace: its {len(triple_ids)} KG record(s) are the legacy global knowledge graph "
        f"{legacy}, not the palace knowledge graph. Importing them would leave out facts "
        "added through MCP and reopen facts the palace ended. Nothing was imported.",
        file=sys.stderr,
    )
    print(
        f"  Next: {reexport}. To import only this file's drawers, add --skip-kg.",
        file=sys.stderr,
    )
    sys.exit(1)


def cmd_import(args):
    from ..cli_invocation import cli_command
    from ..errors import InvalidArgumentError
    from ..export import JsonlInputError, import_jsonl, read_jsonl
    from ..knowledge_graph import (
        KnowledgeGraph,
        LazyKnowledgeGraph,
        adopt_legacy_kg,
        palace_kg_path,
    )
    from ..operation_lock import OperationLockedError, palace_write_lease
    from ..storage import CanonicalModelCacheError, ChromaRuntimeRetiredError, open_store
    from ..taxonomy_filters import clean_write_name
    from .common import palace_command

    # These already name their one recovery command; the global CLI handler prints them.
    self_explaining = (ChromaRuntimeRetiredError, CanonicalModelCacheError)

    palace_path = args.palace or MempalaceConfig().palace_path
    rerun = _import_command(palace_path, args)

    # Reject a missing input file before touching storage.
    if args.jsonl_file != "-" and not os.path.isfile(args.jsonl_file):
        print(f"  Error: import file not found: {args.jsonl_file}", file=sys.stderr)
        print(
            f"  Next: verify the path, or export first with: "
            f"{cli_command('export', '--out', args.jsonl_file)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Validate (and fully buffer) the JSONL input before opening/creating any
    # palace or KG state, so malformed input — including from stdin, which can
    # only be read once — never leaves partial CLI-created state behind.
    try:
        records = list(read_jsonl(args.jsonl_file))
    except JsonlInputError as exc:
        print(f"  Error: malformed JSONL input: {exc}", file=sys.stderr)
        sys.exit(1)

    wing_override = args.wing_override
    if wing_override is not None:
        try:
            wing_override = clean_write_name(wing_override, "--wing-override")
        except InvalidArgumentError as exc:
            print(f"  Error: {exc}.", file=sys.stderr)
            print(
                "  Next: pass a non-blank wing name without '/', '\\' or control "
                "characters, or omit --wing-override to keep each record's wing.",
                file=sys.stderr,
            )
            sys.exit(2)
    if not args.skip_kg:
        _refuse_legacy_kg_export(records, args, palace_path)

    # A live import writes the palace: hold its write lease (which also takes the
    # shared install lease).  A dry run only reads, so it stays lease-free.
    with contextlib.ExitStack() as held:
        if not args.dry_run:
            try:
                held.enter_context(palace_write_lease(palace_path, "import"))
            except OperationLockedError as exc:
                print(f"  Error: import did not start: {exc}", file=sys.stderr)
                print(
                    f"  Next: wait for that operation to finish, then run: {rerun}",
                    file=sys.stderr,
                )
                sys.exit(1)
        try:
            if args.dry_run:
                store = open_store(palace_path, create=False, read_only=True)
                kg = None if args.skip_kg else LazyKnowledgeGraph(palace_path)
            else:
                store = open_store(palace_path, create=True)
                # Legacy facts are adopted after the replay, not before: adoption adds only
                # combinations the palace KG lacks, so a replayed invalidation stays bounded.
                kg = None if args.skip_kg else KnowledgeGraph(db_path=palace_kg_path(palace_path))
        except self_explaining:
            raise
        except Exception as exc:
            print(f"  Error: cannot open palace at {palace_path}: {exc}", file=sys.stderr)
            print(
                f"  Next: run {palace_command(palace_path, 'health')}, "
                "or pass the correct --palace path.",
                file=sys.stderr,
            )
            sys.exit(1)

        if wing_override is not None:
            _refuse_respelled_wing_override(store, wing_override)

        print(f"  Importing into: {palace_path}")
        if args.dry_run:
            print("  (dry run — nothing will be written)")

        try:
            summary = import_jsonl(
                path=args.jsonl_file,
                store=store,
                kg=kg,
                skip_dedup=args.skip_dedup,
                skip_kg=args.skip_kg,
                dry_run=args.dry_run,
                wing_override=wing_override,
                records=records,
            )
        except self_explaining:
            raise
        except Exception as exc:
            print(f"  Error: import stopped: {exc}", file=sys.stderr)
            if not args.dry_run:
                print(
                    "  Drawers imported before the failure stay in the palace; re-running "
                    "import skips them as duplicates.",
                    file=sys.stderr,
                )
            print(
                f"  Next: run {palace_command(palace_path, 'health')}, then: {rerun}",
                file=sys.stderr,
            )
            sys.exit(1)
        kg_error = summary.get("kg_error")
        if not (args.dry_run or args.skip_kg or kg_error):
            adopt_legacy_kg(palace_path, after_import_of_version=summary.get("export_version"))

    counts = {key: summary.get(key, 0) for key in _SUMMARY_COUNTS}
    print(f"  Imported drawers:   {counts['imported_drawers']}")
    print(f"  Skipped duplicates: {counts['skipped_duplicates']}")
    print(f"  Skipped invalid:    {counts['skipped_invalid']}")
    if counts["failed_drawers"]:
        print(f"  Failed drawers:     {counts['failed_drawers']}")
    print(f"  Imported KG triples:{counts['imported_triples']}")
    if not args.skip_kg:
        print(f"  Skipped KG duplicates: {counts['skipped_kg_duplicates']}")
        print(f"  Invalid KG triples:    {counts['invalid_triples']}")
        if counts["kg_invalidations_applied"]:
            print(f"  KG invalidations applied: {counts['kg_invalidations_applied']}")
        if counts["kg_conflicts"]:
            print(f"  KG conflicts kept as invalidated: {counts['kg_conflicts']}")
        if counts["imported_kg_entities"]:
            print(f"  Imported KG entities: {counts['imported_kg_entities']}")
    if args.dry_run:
        print("  (dry run — no changes made)")
    for w in summary.get("warnings", []):
        print(f"  WARNING: {w}")
    if kg_error:
        sys.stdout.flush()  # keep the summary above the error when both streams are piped
        applied = "nothing was written" if args.dry_run else "the drawers above were imported"
        stdin_note = " (pipe the same export on stdin)" if args.jsonl_file == "-" else ""
        print(f"  Error: KG records were not imported ({kg_error}); {applied}.", file=sys.stderr)
        print(
            "  Next: stop other mempalace-code processes writing this palace, then re-run "
            f"the import; already imported records are not duplicated: {rerun}{stdin_note}",
            file=sys.stderr,
        )
    if counts["rejected"]:
        sys.stdout.flush()  # keep the summary above the error when both streams are piped
        verb = "would be rejected" if args.dry_run else "were rejected"
        print(
            f"  Error: {counts['rejected']} record(s) {verb}; see the warnings above.",
            file=sys.stderr,
        )
        # Every KG triple already landed: the rerun needs only the corrected drawers.
        kg_done = not (
            args.dry_run or args.skip_kg or kg_error or counts["invalid_triples"]
        ) and bool(counts["imported_triples"] + counts["skipped_kg_duplicates"])
        rerun = _import_command(palace_path, args, skip_kg=kg_done)
        note = " (its KG triples are already imported)" if kg_done else ""
        print(
            f"  Next: fix those records in {args.jsonl_file}, then run: {rerun}{note}",
            file=sys.stderr,
        )
    if kg_error or counts["rejected"]:
        sys.exit(1)
