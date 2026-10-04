"""Maintenance command handlers: health, cleanup, repair, migrate-storage."""

import contextlib
import errno
import json
import os
import shlex
import shutil
import sys
import tempfile
from datetime import UTC, datetime

from ..config import MempalaceConfig
from .common import (
    acquire_operation_lease,
    fail,
    fmt_bytes,
    no_palace_next_step,
    palace_command,
)

_SEPARATOR = "=" * 55


def _selected_palace(args) -> str:
    return os.path.expanduser(args.palace) if args.palace else MempalaceConfig().palace_path


def _open_lance_palace(palace_path: str, *, read_only: bool, json_output: bool = False):
    """Open an existing Lance palace or exit 1 with one precise reason.

    A missing directory, or a directory without a drawer table (for example a
    project directory, or a palace whose first mine failed), is "No palace found".
    A drawer table that exists but cannot be opened is returned with ``_table``
    unset so callers can report it as degraded.
    """
    from ..storage import (
        _LANCE_TABLE,
        CHROMA_RUNTIME_RETIRED_MESSAGE,
        ChromaRuntimeRetiredError,
        LanceStore,
        open_store,
    )

    lance_dir = os.path.join(palace_path, "lance")
    table_dir = os.path.join(lance_dir, f"{_LANCE_TABLE}.lance")
    if not os.path.exists(lance_dir) and os.path.exists(
        os.path.join(palace_path, "chroma.sqlite3")
    ):
        fail(
            CHROMA_RUNTIME_RETIRED_MESSAGE,
            json_output=json_output,
            code="chroma_retired",
            palace=palace_path,
        )
    if not os.path.isdir(palace_path) or not os.path.isdir(table_dir):
        fail(
            f"No palace found at {palace_path}",
            next_step=no_palace_next_step(palace_path),
            json_output=json_output,
            code="no_palace",
            palace=palace_path,
        )
    try:
        store = open_store(palace_path, create=False, read_only=read_only)
    except ChromaRuntimeRetiredError as exc:
        fail(str(exc), json_output=json_output, code="chroma_retired", palace=palace_path)
    except Exception as exc:
        fail(
            f"Cannot open palace at {palace_path}: {exc}",
            next_step=palace_command(palace_path, "repair", "--rollback", "--dry-run"),
            json_output=json_output,
            code="open_failed",
            palace=palace_path,
        )
    if not isinstance(store, LanceStore):  # pragma: no cover - open_store returns LanceStore
        fail("only LanceDB palaces are supported", json_output=json_output, palace=palace_path)
    return store


def _probe_kg(palace_path: str) -> dict | None:
    """Run SQLite's quick_check on the palace KG; return a health error, or None when fine."""
    from ..knowledge_graph import kg_integrity_problem, palace_kg_path

    return kg_integrity_problem(palace_kg_path(palace_path))


def cmd_health(args):
    """Probe the palace for fragment-missing or read errors, and its KG for corruption."""
    json_output = bool(getattr(args, "json", False))
    palace_path = _selected_palace(args)
    store = _open_lance_palace(palace_path, read_only=True, json_output=json_output)

    report = store.health_check()
    report.setdefault("warnings", [])
    kg_problem = _probe_kg(palace_path)
    if kg_problem is not None:
        if kg_problem["kind"] == "warning":
            report["warnings"].append(kg_problem)
        else:
            report["errors"].append(kg_problem)
            report["ok"] = False

    next_step = None
    if not report["ok"]:
        probes = {err["probe"] for err in report["errors"]}
        if probes - {"kg_quick_check", "embedding_model"}:
            next_step = (
                f"run {palace_command(palace_path, 'repair', '--rollback', '--dry-run')}; "
                "apply rollback only if the candidate looks right."
            )
        elif "embedding_model" in probes:
            next_step = (
                "the drawers are readable, but no command can embed into this palace until "
                "its embedding model matches its vectors: follow the embedding_model error "
                "above (repair keeps the stored vectors and cannot fix this)."
            )
        else:
            from ..knowledge_graph import palace_kg_path

            kg_file = shlex.quote(palace_kg_path(palace_path))
            next_step = (
                "the drawer store is fine but the knowledge graph is corrupt. Keep a copy of "
                "the file, then restore the knowledge graph from a backup archive listed by "
                f"{palace_command(palace_path, 'backup', 'list')} (restore it into a scratch "
                "palace, not with --force over this one, which also replaces its drawers; "
                "see 'Health Check and Repair' in docs/BACKUP_RESTORE.md). If no archive "
                f"holds a healthy one, move the file aside (mv {kg_file} {kg_file}.corrupt) "
                "and rebuild the mined facts with mine <project> --full; facts added through "
                "MCP are then lost."
            )
        report["next"] = next_step
    report["palace"] = palace_path

    if json_output:
        print(json.dumps(report, indent=2))
    else:
        status = "ok" if report["ok"] else "DEGRADED"
        print(f"  Palace: {palace_path}")
        print(f"  Status: {status}")
        print(f"  Total rows: {report['total_rows']}")
        print(f"  Current version: {report['current_version']}")
        embedding = report.get("embedding")
        if embedding:
            recorded = (
                "recorded by the palace" if embedding["recorded"] else "assumed; not recorded"
            )
            print(
                f"  Embedding model: {embedding['model']} ({recorded})  "
                f"vector dimension: {embedding['vector_dim'] or 'unknown'}"
            )
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
        if next_step:
            print(f"  Next: {next_step}")

    if not report["ok"]:
        sys.exit(1)


def _cleanup_preview(store, older_than_days: int, unsafe_now: bool) -> dict:
    """Describe what cleanup would remove, without removing anything.

    Uses the same reader-grace rule as the real cleanup, so the versions it lists
    are the versions a run started now removes.
    """
    from ..storage import cleanup_plan

    table = store._table
    stats = store.storage_stats()
    versions = table.list_versions() if table is not None else []
    plan = cleanup_plan(versions, datetime.now(UTC), older_than_days, unsafe_now=unsafe_now)
    return {
        "ok": True,
        "dry_run": True,
        "version_count": len(versions),
        "current_version": versions[-1]["version"] if versions else None,
        "versions_to_remove": plan["remove"],
        "versions_kept_for_readers": plan["kept_for_readers"],
        "compacts_first": plan["compacts_first"],
        "estimated_reclaimable_bytes": stats["estimated_reclaimable_bytes"],
        "cleanup_older_than_days": 0 if unsafe_now else older_than_days,
        "delete_unverified": unsafe_now,
    }


def _cleanup_retry_hint(palace_path: str) -> str:
    return (
        f"run {palace_command(palace_path, 'health')} and retry cleanup after stopping "
        "watchers, miners, maintenance commands, and MCP servers."
    )


def cmd_cleanup(args):
    """Reclaim disk space from stale Lance versions after repeated mine/watch cycles."""
    from ..storage import LanceStoreDependencyError

    json_output = bool(getattr(args, "json", False))
    palace_path = _selected_palace(args)
    unsafe_now = args.unsafe_now
    older_than_days = args.older_than_days
    dry_run = bool(getattr(args, "dry_run", False))

    if older_than_days < 0:
        fail(
            f"--older-than-days must be 0 or greater (got {older_than_days})",
            next_step=palace_command(palace_path, "cleanup", "--older-than-days", "7"),
            json_output=json_output,
            code="invalid_argument",
            exit_code=2,
        )

    if dry_run:
        store = _open_lance_palace(palace_path, read_only=True, json_output=json_output)
        preview = _cleanup_preview(store, older_than_days, unsafe_now)
        if json_output:
            print(json.dumps(preview, indent=2))
            return
        removable = preview["versions_to_remove"]
        print(f"  Palace: {palace_path}")
        print("  Mode: dry-run (no changes will be made)")
        print(
            f"  Versions: {preview['version_count']}  current: {preview['current_version']}  "
            f"would remove: {len(removable)}"
            + (f" ({', '.join(str(v) for v in removable)})" if removable else "")
        )
        print(
            "  Reclaimable in the whole palace (estimate, not only these versions): "
            f"{fmt_bytes(preview['estimated_reclaimable_bytes'])}"
        )
        kept = preview["versions_kept_for_readers"]
        if kept:
            print(
                f"  Kept for live readers: {len(kept)} ({', '.join(str(v) for v in kept)}): "
                "current within the last minute, or committed within a second before one "
                "that was; run cleanup again after a minute to remove them."
            )
        if removable and preview["compacts_first"]:
            print("  Compaction first commits new versions; they stay as the current state.")
        if removable:
            print(
                "  Removed versions are no longer available to repair --rollback. Run without "
                "--dry-run to apply."
            )
        return

    retry_parts = ["cleanup"]
    retry_parts += ["--unsafe-now"] if unsafe_now else ["--older-than-days", str(older_than_days)]
    lease = acquire_operation_lease(
        "exclusive", "cleanup", palace_path, retry_parts, json_output=json_output
    )
    with lease:
        store = _open_lance_palace(palace_path, read_only=False, json_output=json_output)

        if not json_output:
            if unsafe_now:
                print(
                    "  WARNING: --unsafe-now is for known-no-writer maintenance only.\n"
                    "  Do not run this while any mine/watch process is active."
                )
            elif older_than_days == 0:
                print(
                    "  WARNING: --older-than-days 0 removes every older version no live reader "
                    "can still be on, so repair --rollback loses its history."
                )

        try:
            result = store.cleanup_stale_fragments(
                older_than_days=older_than_days,
                unsafe_now=unsafe_now,
            )
        except LanceStoreDependencyError as e:
            fail(str(e), json_output=json_output, code="dependency_missing")
        except Exception as e:
            fail(
                f"Cleanup failed: {e}",
                next_step=_cleanup_retry_hint(palace_path),
                json_output=json_output,
                code="cleanup_failed",
            )

        if not result["ok"]:
            # A failed cleanup reports a placeholder; re-read what is really on disk.
            try:
                result["version_count_after"] = store.storage_stats()["version_count"]
            except Exception:
                result["version_count_after"] = None
            result["next"] = _cleanup_retry_hint(palace_path)

    if json_output:
        print(json.dumps(result, indent=2))
    else:
        status = "ok" if result["ok"] else "FAILED"
        after = result["version_count_after"]
        print(f"  Status: {status}")
        print(f"  Rows before: {result['rows_before']}  Rows after: {result['rows_after']}")
        print(
            f"  Versions before: {result['version_count_before']}  "
            f"after: {'unknown' if after is None else after}"
        )
        if {
            "estimated_reclaimable_bytes_before",
            "estimated_reclaimable_bytes_after",
        } <= result.keys():
            print(
                "  Reclaimable before: "
                f"{fmt_bytes(result['estimated_reclaimable_bytes_before'])}  "
                f"after: {fmt_bytes(result['estimated_reclaimable_bytes_after'])}"
            )
        print(f"  Freed: {fmt_bytes(result['freed_bytes'])}")
        kept = result.get("versions_kept_for_readers") or 0
        if result["ok"] and kept:
            print(
                f"  Kept for live readers: {kept} older version(s) that were current within "
                "the last minute, or committed within a second before one that was; run "
                "cleanup again after a minute to remove them."
            )
        if not result["ok"]:
            print(f"  Error: {result.get('error', 'unknown')}", file=sys.stderr)
            print(f"  Next: {result['next']}", file=sys.stderr)

    if not result["ok"]:
        sys.exit(1)


def _format_row_change(result: dict, *, applied: bool) -> str:
    current_rows = result.get("current_rows")
    candidate_rows = result.get("candidate_rows")
    if current_rows is None or candidate_rows is None:
        return f"  Rows at version {result.get('candidate_version')}: {candidate_rows}"
    lost = max(current_rows - candidate_rows, 0)
    if applied:
        return f"  Rows before rollback: {current_rows}  rows lost: {lost}"
    return (
        f"  Rows now: {current_rows}  rows after rollback: {candidate_rows}  "
        f"rows that would be lost: {lost}"
    )


def _cmd_rollback(args, palace_path: str, dry_run: bool) -> None:
    lease = (
        contextlib.nullcontext()
        if dry_run
        else acquire_operation_lease(
            "exclusive", "repair --rollback", palace_path, ["repair", "--rollback"]
        )
    )
    with lease:
        store = _open_lance_palace(palace_path, read_only=dry_run)
        header_lines = [
            f"\n{_SEPARATOR}",
            "  MemPalace Repair — Version Rollback",
            _SEPARATOR,
            "",
            f"  Palace: {palace_path}",
        ]
        if dry_run:
            header_lines.extend(["  Mode: dry-run (no changes will be made)", ""])
        else:
            header_lines.extend(["  Mode: live (will restore if candidate found)", ""])

        try:
            result = store.recover_to_last_working_version(dry_run=dry_run)
        except Exception as e:
            print("\n".join(header_lines))
            print(f"  Restore failed: {e}", file=sys.stderr)
            print("  Palace may still be in a degraded state.", file=sys.stderr)
            print(f"  Next: {palace_command(palace_path, 'health')}", file=sys.stderr)
            print(f"\n{_SEPARATOR}\n")
            sys.exit(1)

    if result.get("healthy"):
        print("\n".join(header_lines))
        print(
            f"  Palace is healthy: current version {result.get('current_version')} "
            f"({result.get('current_rows')} rows) passes all health probes."
        )
        print("  Nothing to roll back; no changes were made.")
        print(f"\n{_SEPARATOR}\n")
        return

    if result.get("recovered"):
        print("\n".join(header_lines))
        print(f"  Restored to version: {result['restored_to']}")
        print(f"  Rows after restore: {result['rows_after']}")
        print(_format_row_change(result, applied=True))
        print(f"\n{_SEPARATOR}\n")
        return

    if result.get("candidate_version") is not None:
        print("\n".join(header_lines))
        print(
            f"  Candidate version found: {result['candidate_version']} "
            f"(current: {result.get('current_version')})"
        )
        print(_format_row_change(result, applied=False))
        discarded = result.get("discarded_versions") or []
        if discarded:
            print(
                "  Changes from versions "
                f"{', '.join(str(v) for v in discarded)} would be dropped from the palace."
            )
        print("  (dry-run — no changes made)")
        print("  Run without --dry-run to apply the rollback.")
        print(f"\n{_SEPARATOR}\n")
        return

    msg = result.get("message") or result.get("error") or "no healthy prior version found"
    if dry_run:
        outcome_lines = [
            f"  No candidate version: {msg}",
            "  Mutation: preview completed; no changes were made; "
            "no restore or full rebuild occurred.",
            "  Exit status: 0 (completed non-mutating preview).",
        ]
        output_stream = sys.stdout
    else:
        outcome_lines = [
            f"  No candidate version: {msg}",
            "  Mutation: rollback attempted; no restore or full rebuild occurred; "
            "palace remained unchanged.",
            "  Exit status: 1 (rollback failed because no candidate was found).",
        ]
        output_stream = sys.stderr
    summary = "\n".join(
        [
            *header_lines,
            *outcome_lines,
            f"  Try: {palace_command(palace_path, 'repair')} (full rebuild; it stops "
            "without changes if any drawer is unreadable), or restore an archive listed by "
            f"{palace_command(palace_path, 'backup', 'list')}",
            "",
            _SEPARATOR,
            "",
        ]
    )
    print(summary, file=output_stream)
    if not dry_run:
        sys.exit(1)


def _unique_backup_dir(palace_path: str) -> str:
    """Create and return a new ``<palace>.backup-<UTC timestamp>`` sibling; never reuse one."""
    base = f"{os.path.abspath(palace_path)}.backup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    candidate = base
    suffix = 0
    while True:
        try:
            os.mkdir(candidate, 0o700)
            return candidate
        except FileExistsError:
            suffix += 1
            candidate = f"{base}-{suffix}"


class _PalaceChanged(Exception):
    """Another process committed to the palace after repair read it."""


def _save_and_swap(
    palace_path: str, staging: str, backup_path: str, commit_state: tuple[str, ...]
) -> None:
    """Copy the palace (minus lance/) to *backup_path*, move lance/ there, swap in staging.

    Raises :class:`_PalaceChanged`, before touching the live palace, when its Lance
    commit state is no longer *commit_state* (the state the rebuilt rows were read at).
    """
    from ..storage import lance_commit_state

    live_lance = os.path.join(palace_path, "lance")
    staging_name = os.path.basename(staging)
    # Everything except lance/ stays in place; the copy makes the backup complete.
    for entry in sorted(os.listdir(palace_path)):
        if entry in ("lance", staging_name):
            continue
        src = os.path.join(palace_path, entry)
        dst = os.path.join(backup_path, entry)
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
    if lance_commit_state(palace_path) != commit_state:
        raise _PalaceChanged
    backup_lance = os.path.join(backup_path, "lance")
    try:
        os.replace(live_lance, backup_lance)
        previous = backup_lance
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copytree(live_lance, backup_lance, symlinks=True)
        previous = os.path.join(staging, "previous-lance")
        os.replace(live_lance, previous)
    try:
        os.replace(os.path.join(staging, "lance"), live_lance)
    except OSError:
        os.replace(previous, live_lance)
        raise


def _unique_rebuild_rows(rows: list[dict]) -> list[dict]:
    """Give extracted rows unique ids before the rebuild, keeping every distinct text.

    Palaces written before ids were enforced unique can hold repeated or empty ids;
    :func:`storage.unique_drawer_rows` drops exact copies and renames the rest.
    """
    from ..storage import unique_drawer_rows

    metas = [{k: v for k, v in row.items() if k not in ("id", "text", "vector")} for row in rows]
    index_of = {id(meta): i for i, meta in enumerate(metas)}
    out_ids, _docs, out_metas, dropped, renamed = unique_drawer_rows(
        [row["id"] for row in rows], [row["text"] for row in rows], metas
    )
    if dropped:
        print(f"  Dropped {dropped} exact duplicate row(s) (same id, text and metadata)")
    if renamed:
        shown = ", ".join(f"{old!r} -> {new!r}" for old, new in renamed[:5])
        more = f" (+{len(renamed) - 5} more)" if len(renamed) > 5 else ""
        print(
            f"  Kept {len(renamed)} row(s) with an empty or reused id under new ids: {shown}{more}"
        )
    unique: list[dict] = []
    for new_id, meta in zip(out_ids, out_metas):
        row = rows[index_of[id(meta)]]
        row["id"] = new_id
        unique.append(row)
    return unique


def _cmd_full_rebuild(args, palace_path: str) -> None:
    from ..storage import lance_commit_state

    salvage = bool(getattr(args, "salvage", False))
    retry = ["repair", "--salvage"] if salvage else ["repair"]
    with acquire_operation_lease("exclusive", "repair", palace_path, retry):
        store = _open_lance_palace(palace_path, read_only=False)

        print(f"\n{_SEPARATOR}")
        print("  MemPalace Repair")
        print(f"{_SEPARATOR}\n")
        print(f"  Palace: {palace_path}")

        rollback_preview = palace_command(palace_path, "repair", "--rollback", "--dry-run")
        backup_list = palace_command(palace_path, "backup", "list")
        salvage_command = palace_command(palace_path, "repair", "--salvage")
        if store._table is None:
            fail(
                "the drawer table exists but cannot be opened; nothing was changed.",
                next_step=f"run {rollback_preview}, or restore an archive listed by {backup_list}",
            )

        print("\n  Extracting drawers...")
        try:
            # Record the commit state, then read the newest version: the swap below
            # proceeds only while the state is unchanged, so no commit made by another
            # process after this point can be dropped from the live palace.
            commit_state = lance_commit_state(palace_path)
            store._reopen_table()
            extracted = store.read_all_for_rebuild(salvage=salvage)
        except Exception as exc:
            fail(
                f"cannot read the palace: {exc}. Nothing was changed.",
                next_step=f"run {rollback_preview}, or restore an archive listed by {backup_list}",
            )
        total = extracted["total"]
        rows = extracted["rows"]
        unreadable = extracted["unreadable"]
        stopped_early = extracted.get("stopped_at") is not None
        print(f"  Drawers found: {total}")
        if stopped_early:
            print(f"  Extracted {len(rows)} of {total} drawers before a read failed")
        else:
            print(f"  Extracted {len(rows)} of {total} drawers")

        if total == 0:
            print("  Nothing to repair: the palace holds no drawers.")
            print(f"\n{_SEPARATOR}\n")
            return
        if unreadable:
            sys.stdout.flush()
            for error in extracted["errors"]:
                print(f"    read error: {error}", file=sys.stderr)
            if not salvage or not rows:
                steps = [
                    f"restore an archive listed by {backup_list}",
                    f"or check {rollback_preview}",
                ]
                if stopped_early:
                    # A plain repair stops at the first failed read; salvage counts exactly.
                    reason = f"at least one of the {total} drawers could not be read"
                    steps.append(
                        "or rebuild from the drawers that are still readable (it reads the "
                        "rest row by row, reports how many were lost, and keeps the "
                        f"unreadable ones only in the pre-repair copy): {salvage_command}"
                    )
                elif not rows:
                    reason = f"none of the {total} drawers can be read"
                else:
                    reason = f"{unreadable} of {total} drawers could not be read"
                    steps.append(
                        f"or rebuild from the {len(rows)} readable drawers (the {unreadable} "
                        f"unreadable ones stay only in the pre-repair copy): {salvage_command}"
                    )
                fail(
                    f"repair stopped: {reason}. The palace was not changed.",
                    next_step="; ".join(steps),
                )

        rows = _unique_rebuild_rows(rows)

        staging = tempfile.mkdtemp(dir=palace_path, prefix=".mempalace-repair-")
        try:
            print("  Rebuilding the drawer table in a staging directory...")
            try:
                rebuilt = store.write_rebuilt_table(staging, rows)
            except Exception as exc:
                fail(f"rebuild failed: {exc}. The palace was not changed.")
            if rebuilt != len(rows):
                fail(f"rebuild wrote {rebuilt} of {len(rows)} drawers. The palace was not changed.")
            print(f"  Re-filed {rebuilt}/{len(rows)} drawers")

            changed_message = (
                "another process wrote to the palace while repair was reading it. "
                "The palace was not changed."
            )
            changed_next = (
                "stop miners, watchers, and MCP servers that use this palace, then run "
                f"{palace_command(palace_path, *retry)}"
            )
            if lance_commit_state(palace_path) != commit_state:
                fail(changed_message, next_step=changed_next)
            parent = os.path.dirname(os.path.abspath(palace_path))
            try:
                backup_path = _unique_backup_dir(palace_path)
            except OSError as exc:
                fail(
                    f"repair cannot create its pre-repair copy next to the palace: {exc}. "
                    "The palace was not changed.",
                    next_step=f"make {parent} writable (and free space there), then run "
                    f"{palace_command(palace_path, *retry)}",
                )
            print(f"  Saving the pre-repair palace to {backup_path}...")
            try:
                _save_and_swap(palace_path, staging, backup_path, commit_state)
            except _PalaceChanged:
                shutil.rmtree(backup_path, ignore_errors=True)
                fail(changed_message, next_step=changed_next)
            except OSError as exc:
                fail(
                    f"repair could not save the pre-repair copy or swap in the rebuilt table: "
                    f"{exc}. The live palace was left as it was; {backup_path} may hold a "
                    "partial copy.",
                    next_step=f"free disk space if needed, then run {palace_command(palace_path, 'health')}",
                )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        from ..storage import open_store

        final = open_store(palace_path, create=False, read_only=True)
        report = final.health_check()
        if not report["ok"] or final.count() != len(rows):
            fail(
                f"the rebuilt palace failed verification. The pre-repair copy is at {backup_path}.",
                next_step=f"run {palace_command(palace_path, 'health')}",
            )

    kept = [e for e in sorted(os.listdir(palace_path)) if e != "lance"]
    if unreadable:
        print(
            f"\n  Repair complete (salvage): {len(rows)} of {total} drawers rebuilt; "
            f"{unreadable} unreadable drawers were not carried over; they remain only in "
            "the pre-repair copy."
        )
    else:
        print(f"\n  Repair complete. {len(rows)} of {total} drawers rebuilt.")
    if kept:
        print(f"  Kept in place: {', '.join(kept)}")
    print(f"  Pre-repair copy saved at {backup_path}")
    print(
        "  backup list and retention do not manage this copy; once health reports ok and "
        f"you no longer need it, remove it with: rm -rf {shlex.quote(backup_path)}"
    )
    print(f"  Next: {palace_command(palace_path, 'health')}")
    print(f"\n{_SEPARATOR}\n")


def cmd_repair(args):
    """Rebuild palace — rollback to last working version, or extract-and-rebuild."""
    palace_path = _selected_palace(args)
    dry_run = getattr(args, "dry_run", False)
    rollback = getattr(args, "rollback", False)

    # --dry-run without --rollback is not supported for the full rebuild path
    if dry_run and not rollback:
        print("  --dry-run is only supported with --rollback for version restore.", file=sys.stderr)
        print("  Full rebuild (without --rollback) always modifies the palace.", file=sys.stderr)
        sys.exit(2)
    if rollback and getattr(args, "salvage", False):
        print("  --salvage applies to the full rebuild, not to --rollback.", file=sys.stderr)
        sys.exit(2)

    if rollback:
        _cmd_rollback(args, palace_path, dry_run)
    else:
        _cmd_full_rebuild(args, palace_path)


def cmd_migrate_storage(args):
    """Fail closed for every legacy migration invocation without inspecting its arguments."""
    from ..storage import CHROMA_RUNTIME_RETIRED_MESSAGE, ChromaRuntimeRetiredError

    raise ChromaRuntimeRetiredError(CHROMA_RUNTIME_RETIRED_MESSAGE)
