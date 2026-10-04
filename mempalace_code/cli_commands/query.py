"""Query command handlers: search, wake-up, compress, read."""

import argparse
import contextlib
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import NoReturn

from ..cli_invocation import cli_command, degraded_palace_next_step, no_palace_next_step
from ..config import MempalaceConfig


def search_results_count(value: str) -> int:
    """Argparse type for search --results: an integer in 1..MAX_SEARCH_RESULTS."""
    from ..searcher import MAX_SEARCH_RESULTS

    try:
        count = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid integer")
    if count < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {count}")
    if count > MAX_SEARCH_RESULTS:
        raise argparse.ArgumentTypeError(f"must be at most {MAX_SEARCH_RESULTS}, got {count}")
    return count


def cmd_search(args):
    as_json = getattr(args, "json", False)
    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    if not args.query.strip():
        if as_json:
            _print_json({"error": "query must not be blank"})
        else:
            print("Error: query must not be blank.", file=sys.stderr)
            print(
                f"Try: {cli_command('search', 'your search query', palace=args.palace)}",
                file=sys.stderr,
            )
        sys.exit(2)

    if as_json:
        _search_json(args, palace_path)
        return

    from ..searcher import SearchError, search
    from ..taxonomy_filters import TaxonomyValidationError, format_cli_lines

    try:
        search(
            query=args.query,
            palace_path=palace_path,
            wing=args.wing,
            room=args.room,
            n_results=args.results,
            compact=args.compact,
        )
    except TaxonomyValidationError as e:
        for line in format_cli_lines(e.payload):
            print(line, file=sys.stderr)
        sys.exit(2)
    except SearchError:
        sys.exit(1)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _search_json(args, palace_path: str) -> None:
    """Print search_memories() output as one JSON object; runtime errors are JSON too.

    search_memories() keeps the MCP error payloads; the CLI swaps in next steps
    bound to this install and the user's --palace.
    """
    from ..searcher import search_memories

    no_palace = {
        "error": "No palace found",
        "palace_path": palace_path,
        "hint": f"Next: {no_palace_next_step(palace_path)}",
    }
    if not os.path.isdir(palace_path):
        _print_json(no_palace)
        sys.exit(1)
    result = search_memories(
        args.query, palace_path, wing=args.wing, room=args.room, n_results=args.results
    )
    error = result.get("error")
    if error == "No palace found":
        result = no_palace
    elif (
        isinstance(error, str)
        and error.startswith("Search error:")
        and "fetch-model" not in error
        and "Next:" not in error
    ):
        # A missing model cache names its own fetch-model recovery (palace repair cannot
        # help), and an unreadable palace names its own recovery: add no second Next.
        result = {**result, "hint": f"Next: {degraded_palace_next_step(palace_path, 'search')}"}
    _print_json(result)
    if error in ("unknown_wing", "unknown_room", "unknown_wing_room"):
        sys.exit(2)
    if error:
        sys.exit(1)


def cmd_wakeup(args):
    """Show L0 (identity) + L1 (essential story) — the wake-up context.

    Only the context goes to stdout, so it can be piped into a system prompt; the token
    estimate and warnings go to stderr.
    """
    from ..layers import MemoryStack
    from ..taxonomy_filters import format_cli_lines, validate_taxonomy_filters
    from .common import palace_holds_state

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path

    if args.wing is not None and not args.wing.strip():
        print("Error: --wing must not be blank.", file=sys.stderr)
        print(
            "  Next: pass a wing name from mempalace-code status, or omit --wing for every wing.",
            file=sys.stderr,
        )
        sys.exit(2)
    # A project or empty directory holds no drawers and no KG: it is not a palace.
    if not os.path.isdir(palace_path) or not palace_holds_state(palace_path):
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(
            f"  Next: run {cli_command('init', '<dir>')}, then "
            f"{_palace_command(palace_path, 'mine', '<dir>')}.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.wing is not None:
        taxonomy_error = validate_taxonomy_filters(palace_path, wing=args.wing)
        if taxonomy_error:
            for line in format_cli_lines(taxonomy_error):
                print(line, file=sys.stderr)
            sys.exit(2)

    stack = MemoryStack(palace_path=palace_path)

    text = stack.wake_up(wing=args.wing)
    print(f"Wake-up text (~{len(text) // 4} tokens):", file=sys.stderr)
    if stack.l0.truncated:
        print(
            f"  Warning: {stack.identity_path} is longer than {stack.l0.MAX_CHARS} characters; "
            "L0 shows only its beginning. Shorten it to about 100 tokens.",
            file=sys.stderr,
        )
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except BrokenPipeError:
        # The reader (for example `head`) stopped early. Point stdout at /dev/null so the
        # interpreter's final flush does not raise again, and exit quietly.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        sys.exit(0)


_COMPRESS_READ_BATCH = 500
_RECOVER_BATCH = 256
_RECOVER_LIST_LIMIT = 10


def _is_legacy_compressed(meta) -> bool:
    """Return whether a pre-1.15.0 ``compress`` replaced this drawer's text with AAAK."""
    from ..storage import is_legacy_compressed

    return is_legacy_compressed(meta)


def _load_compress_dialect(config_path):
    """Return the AAAK dialect for ``compress``; exit 2 when ``--config`` is unusable."""
    from ..dialect import Dialect

    if config_path is None:
        return Dialect()
    try:
        dialect = Dialect.from_config(config_path)
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
        print(f"Error: cannot use entity config {config_path}: {reason}", file=sys.stderr)
        print(
            '  Next: pass a JSON file such as {"people": ["Alice"], "projects": ["Apollo"]} '
            "(what mempalace-code init <dir> --detect-entities writes) or "
            '{"entities": {"Alice": "ALC"}}, or omit --config.',
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"  Loaded entity config: {os.path.abspath(config_path)}")
    return dialect


def _compress_rows(store, where) -> list:
    """Return ``(id, text, metadata)`` for every drawer in scope."""
    rows = []
    offset = 0
    while True:
        batch = store.get(
            include=["documents", "metadatas"],
            limit=_COMPRESS_READ_BATCH,
            offset=offset,
            where=where,
        )
        documents = batch.get("documents", [])
        if not documents:
            break
        rows.extend(zip(batch.get("ids", []), documents, batch.get("metadatas", [])))
        offset += len(documents)
        if len(documents) < _COMPRESS_READ_BATCH:
            break
    return rows


def _palace_command(palace_path: str, *args: str) -> str:
    """Return a runnable command for *palace_path*; ``<placeholder>`` args stay unquoted."""
    return cli_command(*args, palace=os.path.abspath(palace_path))


def cmd_compress(args):
    """Print lossy AAAK summaries of drawers. Drawers are never modified.

    ``--recover-from ARCHIVE`` is the only writing mode: it restores, from a backup
    archive, the verbatim text of drawers that ``compress`` before 1.15.0 overwrote.
    """
    from ..dialect import Dialect
    from ..storage import open_store
    from ..taxonomy_filters import format_cli_lines, validate_taxonomy_filters

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    recover_from = getattr(args, "recover_from", None)

    if args.wing is not None and not args.wing.strip():
        print("Error: --wing must not be blank.", file=sys.stderr)
        print(
            "  Next: pass a wing name from mempalace-code status, or omit --wing for every wing.",
            file=sys.stderr,
        )
        sys.exit(2)
    if recover_from is not None and not os.path.isfile(recover_from):
        print(f"Error: backup archive not found: {recover_from}", file=sys.stderr)
        print(
            f"  Next: list archives with {_palace_command(palace_path, 'backup', 'list')}, "
            "then rerun with one of them.",
            file=sys.stderr,
        )
        sys.exit(2)
    # --config is validated before the palace is touched; recovery does not summarize.
    dialect = _load_compress_dialect(args.config) if recover_from is None else Dialect()

    if not os.path.isdir(palace_path):
        print(f"\n  No palace found at {palace_path}", file=sys.stderr)
        print(
            f"  Next: run {cli_command('init', '<dir>')}, then "
            f"{_palace_command(palace_path, 'mine', '<dir>')}.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.wing:
        taxonomy_error = validate_taxonomy_filters(palace_path, wing=args.wing)
        if taxonomy_error:
            for line in format_cli_lines(taxonomy_error):
                print(line, file=sys.stderr)
            sys.exit(2)

    # Every mode reads through a read-only handle; only a recovery reopens for writing.
    try:
        store = open_store(palace_path, create=False, read_only=True)
        rows = _compress_rows(store, {"wing": args.wing} if args.wing else None)
    except Exception as exc:
        print(f"\n  Error reading drawers: {exc}", file=sys.stderr)
        print(f"  Next: {_palace_command(palace_path, 'health')}", file=sys.stderr)
        sys.exit(1)

    wing_label = f" in wing '{args.wing}'" if args.wing else ""
    if recover_from is not None:
        _recover_compressed_drawers(palace_path, recover_from, rows, args.wing, args.dry_run)
        return

    if not rows:
        print(f"\n  No drawers found{wing_label}.")
        print("  Next: check --wing, or run mempalace-code mine <project-dir>.")
        return

    legacy = [row for row in rows if _is_legacy_compressed(row[2])]
    print(f"\n  Selected {len(rows)} drawers{wing_label}.")
    print(
        "  AAAK is a lossy summary. compress only prints it: "
        "drawers keep their verbatim text and nothing is stored."
    )
    print()

    total_original = 0
    total_summary = 0
    summarized = 0
    not_shorter = 0
    for doc_id, text, meta in rows:
        if _is_legacy_compressed(meta):
            continue
        summary = dialect.compress(text, metadata=meta)
        stats = dialect.compression_stats(text, summary)
        if stats["summary_tokens_est"] >= stats["original_tokens_est"]:
            not_shorter += 1
            continue
        summarized += 1
        total_original += stats["original_tokens_est"]
        total_summary += stats["summary_tokens_est"]
        source = Path(meta.get("source_file") or "?").name
        print(f"  [{meta.get('wing', '?')}/{meta.get('room', '?')}] {source} ({doc_id})")
        print(
            f"    {stats['original_tokens_est']}t -> {stats['summary_tokens_est']}t "
            f"({stats['size_ratio']:.1f}x)"
        )
        print(textwrap.indent(summary, "    "))
        print()

    # One metric everywhere: the token estimates shown on every row above.
    ratio = total_original / total_summary if total_summary else 0.0
    print(f"  Total: {total_original:,}t -> {total_summary:,}t ({ratio:.1f}x compression)")
    print(
        f"  Summarized {summarized} drawers; skipped {not_shorter} whose AAAK summary "
        "was not shorter than the drawer."
    )
    if legacy:
        sys.stdout.flush()
        print(
            f"\n  Warning: {len(legacy)} drawers{wing_label} already hold AAAK text that "
            "compress wrote into them before 1.15.0; their verbatim text is not in the "
            "palace, so they were not summarized again.",
            file=sys.stderr,
        )
        print(
            "  Next: find the archive that compress created with "
            f"{_palace_command(palace_path, 'backup', 'list')}, then preview the recovery with "
            f"{_palace_command(palace_path, 'compress', '--recover-from', '<archive>', '--dry-run')}.",
            file=sys.stderr,
        )
    if args.dry_run:
        print("  (dry run -- nothing stored)")


def _recover_compressed_drawers(palace_path, archive_path, rows, wing, dry_run):
    """Restore drawers that a pre-1.15.0 ``compress`` overwrote with AAAK from *archive_path*."""
    import tempfile

    from ..backup import restore_backup
    from ..storage import open_store

    wing_label = f" in wing '{wing}'" if wing else ""
    rerun_args = ["compress", "--recover-from", os.path.abspath(archive_path)]
    if wing:
        rerun_args += ["--wing", wing]
    rerun = _palace_command(palace_path, *rerun_args)
    legacy = {doc_id: meta for doc_id, _text, meta in rows if _is_legacy_compressed(meta)}
    if not legacy:
        print(f"\n  No drawers{wing_label} hold AAAK text from an earlier compress; nothing to do.")
        return

    originals = {}
    with tempfile.TemporaryDirectory(prefix="mempalace-compress-recover-") as scratch:
        scratch_palace = os.path.join(scratch, "palace")
        try:
            restore_backup(
                archive_path,
                scratch_palace,
                kg_path=os.path.join(scratch, "knowledge_graph.sqlite3"),
                private_target=True,
            )
            archived = open_store(scratch_palace, create=False, read_only=True)
            ids = sorted(legacy)
            for start in range(0, len(ids), _RECOVER_BATCH):
                found = archived.get(
                    ids=ids[start : start + _RECOVER_BATCH], include=["documents", "metadatas"]
                )
                for doc_id, text, meta in zip(found["ids"], found["documents"], found["metadatas"]):
                    if doc_id in legacy and not _is_legacy_compressed(meta):
                        originals[doc_id] = (text, meta)
        except Exception as exc:
            print(f"\n  Error: cannot read backup archive {archive_path}: {exc}", file=sys.stderr)
            print(
                f"  Next: pick another archive from "
                f"{_palace_command(palace_path, 'backup', 'list')} and rerun.",
                file=sys.stderr,
            )
            sys.exit(1)

    missing = sorted(set(legacy) - set(originals))
    print(f"\n  Drawers{wing_label} holding AAAK text from an earlier compress: {len(legacy)}")
    print(f"  Recoverable from {archive_path}: {len(originals)}")
    if dry_run:
        print("  (dry run -- nothing stored)")
    elif originals:
        restored, unchanged = _restore_originals(palace_path, originals, rerun)
        print(f"  Restored verbatim text for {restored} drawers.")
        if unchanged:
            print(
                f"  Left {unchanged} drawers as they are: they changed after the archive was read."
            )
    if not missing:
        return

    sys.stdout.flush()
    print(f"\n  Not recoverable from this archive: {len(missing)}", file=sys.stderr)
    for doc_id in missing[:_RECOVER_LIST_LIMIT]:
        meta = legacy[doc_id]
        source = meta.get("source_file") or ""
        print(
            f"    {doc_id} [{meta.get('wing', '?')}/{meta.get('room', '?')}] {source}".rstrip(),
            file=sys.stderr,
        )
    if len(missing) > _RECOVER_LIST_LIMIT:
        print(f"    ... and {len(missing) - _RECOVER_LIST_LIMIT} more", file=sys.stderr)
    # Rebuild hints match the drawers listed. Conversation drawers come back from an
    # incremental convos mine (it re-files sources whose drawers hold AAAK text);
    # manual and diary drawers have no source to rebuild from.
    kinds = {_rebuild_kind(legacy[doc_id]) for doc_id in missing}
    rebuild = []
    if "project" in kinds:
        rebuild.append(
            "project-file drawers with "
            + _palace_command(palace_path, "mine", "<project-dir>", "--full")
        )
    if "convos" in kinds:
        rebuild.append(
            "conversation drawers with "
            + _palace_command(palace_path, "mine", "<conversations-dir>", "--mode", "convos")
        )
    alternative = f", or rebuild {' and '.join(rebuild)}" if rebuild else ""
    print(f"  Next: rerun with an older archive{alternative}.", file=sys.stderr)
    # A preview reports the outcome the real run would have.
    sys.exit(1)


def _rebuild_kind(meta) -> str:
    """How a drawer can be rebuilt without an archive: "convos", "project" or ""."""
    if meta.get("ingest_mode") == "convos":
        return "convos"
    if meta.get("source_file") and meta.get("chunker_strategy") not in ("manual_v1", "diary_v1"):
        return "project"
    return ""


def _restore_originals(palace_path, originals, rerun) -> tuple:
    """Write archived verbatim text back under the palace write lease; return (restored, unchanged).

    Only drawers that still hold AAAK text are replaced, in batched upserts, and every
    replaced drawer is read back before success is reported.
    """
    from ..operation_lock import OperationLockedError, palace_write_lease
    from ..storage import open_store

    with contextlib.ExitStack() as held:
        try:
            held.enter_context(palace_write_lease(palace_path, "compress-recover"))
        except OperationLockedError as exc:
            print(f"\n  Error: recovery did not start: {exc}", file=sys.stderr)
            print(f"  Next: wait for that operation to finish, then rerun {rerun}", file=sys.stderr)
            sys.exit(1)
        try:
            live = open_store(palace_path, create=False)
            ids = sorted(originals)
            current = {}
            for start in range(0, len(ids), _RECOVER_BATCH):
                found = live.get(ids=ids[start : start + _RECOVER_BATCH], include=["metadatas"])
                current.update(zip(found["ids"], found["metadatas"]))
            # Anything re-mined or deleted since the archive was read keeps its current state.
            pending = [doc_id for doc_id in ids if _is_legacy_compressed(current.get(doc_id, {}))]
            for start in range(0, len(pending), _RECOVER_BATCH):
                batch = pending[start : start + _RECOVER_BATCH]
                live.upsert(
                    ids=batch,
                    documents=[originals[doc_id][0] for doc_id in batch],
                    metadatas=[originals[doc_id][1] for doc_id in batch],
                )
            restored = 0
            for start in range(0, len(pending), _RECOVER_BATCH):
                batch = pending[start : start + _RECOVER_BATCH]
                found = live.get(ids=batch, include=["documents", "metadatas"])
                restored += sum(
                    1
                    for doc_id, text, meta in zip(
                        found["ids"], found["documents"], found["metadatas"]
                    )
                    if text == originals[doc_id][0] and not _is_legacy_compressed(meta)
                )
        except Exception as exc:
            print(f"\n  Error restoring drawers: {exc}", file=sys.stderr)
            print(f"  Next: rerun {rerun} (restoring is idempotent).", file=sys.stderr)
            sys.exit(1)
    if restored != len(pending):
        print(
            f"\n  Error: verified {restored} of {len(pending)} restored drawers.", file=sys.stderr
        )
        print(f"  Next: rerun {rerun} (restoring is idempotent).", file=sys.stderr)
        sys.exit(1)
    return restored, len(originals) - len(pending)


def cmd_read(args):
    """Print stored source lines for a file and line range."""
    from ..config import MempalaceConfig
    from ..reader import read_slice
    from ..storage import open_store

    palace_path = os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path
    palace_arg = args.palace

    def _fail(lines: list[str], code: int = 1) -> NoReturn:
        for line in lines:
            print(line, file=sys.stderr)
        sys.exit(code)

    no_palace = [
        f"\n  No palace found at {palace_path}",
        f"  Next: {no_palace_next_step(palace_arg)}.",
    ]
    if not os.path.isdir(palace_path):
        _fail(no_palace)

    try:
        store = open_store(palace_path, create=False, read_only=True)
    except Exception:
        _fail(no_palace)

    result = read_slice(store, args.source_file, args.start, args.end, wing=args.wing)

    error = result.get("error")
    source = result.get("source_file", args.source_file)
    wing_args = ["--wing", args.wing] if args.wing else []
    search_cmd = cli_command("search", "<query>", *wing_args, palace=palace_arg)
    if error in ("unknown_wing", "unknown_room", "unknown_wing_room"):
        from ..taxonomy_filters import format_cli_lines

        _fail(format_cli_lines(result), 2)
    if error == "not_found":
        _fail(
            [
                f"\n  Not found: no palace chunks for '{source}'",
                f"  Next: run {search_cmd} and copy the exact Source path; "
                f"if the file should be indexed, run "
                f"{cli_command('mine', '<project-dir>', palace=palace_arg)}.",
            ]
        )
    if error == "store_error":
        _fail(
            [
                f"\n  Read error: {result.get('detail', '')}",
                f"  Next: {degraded_palace_next_step(palace_arg, 'read')}",
            ]
        )
    if error == "out_of_range":
        last = int(result.get("last_indexed_line") or 1)
        unplaced = int(result.get("unplaced_chunks") or 0)
        if unplaced:
            _fail(
                [
                    f"\n  Out of range: {result.get('detail', '')}",
                    f"  Next: lines 1-{last} are readable by line number; to see the other "
                    f"{unplaced} chunk(s), run {search_cmd} or use the MCP "
                    "mempalace_file_context tool.",
                ]
            )
        tail = cli_command(
            "read",
            source,
            "--start",
            str(max(1, last - 19)),
            "--end",
            str(last),
            *wing_args,
            palace=palace_arg,
        )
        _fail(
            [
                f"\n  Out of range: {result.get('detail', '')}",
                f"  Next: pick lines 1-{last}; for the last lines run {tail}",
            ]
        )
    if error == "no_line_metadata":
        _fail(
            [
                f"\n  No line ranges: {result.get('detail', '')}",
                f"  Next: run {search_cmd} to see the stored text.",
            ]
        )
    if error == "invalid_range":
        _fail(
            [
                f"\n  Invalid range: {result.get('detail', '')}",
                "  Next: pass positive line numbers with --start less than or equal to --end.",
            ]
        )
    if error == "ambiguous_source":
        _fail(
            [
                f"\n  Ambiguous source: '{args.source_file}' matches multiple stored paths.",
                "  Next: retry with the full stored path from one of these candidates:",
                *(f"    {candidate}" for candidate in result.get("candidates", [])),
            ]
        )
    if error:
        _fail([f"\n  Error: {error}"])

    # Lines and gaps partition [start, end]; print them in line order.
    first_indexed = int(result.get("first_indexed_line") or 1)
    events = [(gap["start"], gap["end"], None) for gap in result.get("gaps", [])]
    events += [(entry["line"], entry["line"], entry["text"]) for entry in result.get("lines", [])]
    for first, last, text in sorted(events, key=lambda event: event[0]):
        if text is None:
            span = f"line {first}" if first == last else f"lines {first}-{last}"
            if last < first_indexed:
                reason = f"mining stored nothing before line {first_indexed}"
            else:
                reason = "usually blank lines between indexed chunks"
            print(f"     …: ({span} not stored; {reason})")
        else:
            print(f"{first:6}: {text}")
    unplaced = int(result.get("unplaced_chunks") or 0)
    if result["end"] < args.end:
        where = "line-addressed" if unplaced else "indexed"
        print(f"     …: (end of {where} content at line {result['last_indexed_line']})")
    if unplaced:
        print(
            f"     …: ({unplaced} stored chunk(s) of this file carry no line range and are "
            f"not shown; run {search_cmd} or use the MCP mempalace_file_context tool to see "
            "them)"
        )
