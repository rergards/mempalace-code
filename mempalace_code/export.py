"""
export.py — Export and import drawers + KG triples as JSONL

Provides backup/restore for manually-added drawers, diary entries, and knowledge
graph triples that would otherwise be lost when nuking and re-seeding a palace.

Typical workflow:
    # Before nuke-and-re-seed:
    mempalace-code export --only-manual --with-kg --out backup.jsonl

    # After re-mine:
    mempalace-code import backup.jsonl
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import stat
import sys
from datetime import date, datetime
from typing import Any, Dict, Iterator, List, Optional

from .knowledge_graph import _parse_temporal, _validate_window
from .storage import DuplicateDrawerIdError, distance_to_similarity
from .version import __version__

# Chunker strategies produced by manual writes (MCP add_drawer + diary)
_MANUAL_STRATEGIES = ("manual_v1", "diary_v1")

# Import skips a drawer when its target wing already holds one at least this similar (cosine).
_IMPORT_DEDUP_SIMILARITY = 0.9
# Drawer ids per existence lookup, so a large import never builds one huge id filter.
_ID_LOOKUP_BATCH = 500


# ── Header ────────────────────────────────────────────────────────────────────


def _make_header(
    palace_path: str,
    filters: Dict[str, Any],
    drawer_count: int,
    kg_count: int,
) -> Dict[str, Any]:
    return {
        "type": "export_header",
        "version": __version__,
        "palace_path": palace_path,
        "exported_at": datetime.now().isoformat(),
        "filters": filters,
        "drawer_count": drawer_count,
        "kg_count": kg_count,
    }


# ── Export ────────────────────────────────────────────────────────────────────

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def validate_since(since: Optional[str]) -> Optional[str]:
    """Return *since* when it is an ISO date (YYYY-MM-DD); raise ValueError otherwise.

    ``--since`` is compared with stored ISO timestamps as a string, so any other
    spelling would silently match nothing.
    """
    if since is None:
        return None
    problem = "expected an ISO date YYYY-MM-DD, e.g. 2026-01-01"
    if not isinstance(since, str) or not _ISO_DATE_RE.fullmatch(since):
        raise ValueError(f"invalid --since value {since!r}: {problem}")
    try:
        date.fromisoformat(since)
    except ValueError as exc:
        raise ValueError(f"invalid --since value {since!r}: {exc}") from exc
    return since


def _build_drawer_where(
    only_manual: bool = False,
    wing: Optional[str] = None,
    room: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build a DrawerStore where-filter dict from export options."""
    clauses = []
    if only_manual:
        clauses.append({"$or": [{"chunker_strategy": s} for s in _MANUAL_STRATEGIES]})
    if wing:
        clauses.append({"wing": wing})
    if room:
        clauses.append({"room": room})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def export_drawers(
    store,
    only_manual: bool = False,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    since: Optional[str] = None,
    include_vectors: bool = False,
) -> Iterator[Dict[str, Any]]:
    """Yield one drawer dict per record from the store."""
    where = _build_drawer_where(only_manual=only_manual, wing=wing, room=room)
    for batch in store.iter_all(where=where, include_vectors=include_vectors):
        for row in batch:
            # Post-filter by `since` on filed_at (string ISO date comparison)
            if since and row.get("filed_at", "") < since:
                continue
            record: Dict[str, Any] = {"type": "drawer"}
            record["id"] = row.get("id", "")
            record["text"] = row.get("text", "")
            # Embed vector or null
            if include_vectors:
                vec = row.get("vector")
                record["embedding"] = list(vec) if vec is not None else None
            else:
                record["embedding"] = None
            # All metadata fields (exclude 'type' to avoid collision with record type marker)
            for key in (
                "wing",
                "room",
                "source_file",
                "chunk_index",
                "added_by",
                "filed_at",
                "hall",
                "topic",
                "agent",
                "date",
                "ingest_mode",
                "extract_mode",
                "compression_ratio",
                "original_tokens",
                "language",
                "symbol_name",
                "symbol_type",
                "source_hash",
                "extractor_version",
                "chunker_strategy",
                "line_start",
                "line_end",
            ):
                record[key] = row.get(key, "")
            # `type` is overloaded — store drawer metadata `type` under `drawer_type`
            record["drawer_type"] = row.get("type", "")
            yield record


def _kg_record_in_scope(
    triple: Dict[str, Any], since: Optional[str], source_files: Optional[set]
) -> bool:
    """Apply export scope to one KG triple.

    *source_files* (set when the export is scoped by wing or room) keeps only facts
    extracted from an exported drawer's source file. *since* keeps facts whose
    valid_from is on or after it, or that have no valid_from and were recorded on or
    after it.
    """
    if source_files is not None and triple.get("source_file") not in source_files:
        return False
    if since:
        started = triple.get("valid_from")
        if started:
            return started >= since
        return (triple.get("extracted_at") or "") >= since
    return True


def export_kg(
    kg,
    since: Optional[str] = None,
    source_files: Optional[set] = None,
) -> Iterator[Dict[str, Any]]:
    """Yield one KG record per entity with metadata (``kg_entity``), then per triple.

    Entity records carry types and properties that triples cannot; with a scope, only
    entities named by an exported triple are included. Triples are streamed.
    """

    def scoped_triples() -> Iterator[Dict[str, Any]]:
        for batch in kg.iter_all_triples():
            for triple in batch:
                if _kg_record_in_scope(triple, since, source_files):
                    yield triple

    iter_entities = getattr(kg, "iter_entities", None)
    if iter_entities is not None:
        named: Optional[set] = None
        if since is not None or source_files is not None:
            named = set()
            for triple in scoped_triples():
                named.add(kg._entity_id(triple["subject"]))
                named.add(kg._entity_id(triple["object"]))
        for entity in iter_entities(ids=named):
            yield {"type": "kg_entity", **entity}
    for triple in scoped_triples():
        record = {"type": "kg_triple"}
        record.update(triple)
        yield record


def _drawer_count_and_sources(
    store,
    only_manual: bool = False,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    since: Optional[str] = None,
) -> tuple[int, set]:
    """Count matching drawers for the export header and collect their source files."""
    count = 0
    sources: set = set()
    for record in export_drawers(store, only_manual=only_manual, wing=wing, room=room, since=since):
        count += 1
        if record.get("source_file"):
            sources.add(record["source_file"])
    return count, sources


def _is_character_device(path: str) -> bool:
    try:
        return stat.S_ISCHR(os.stat(path).st_mode)
    except OSError:
        return False


def write_jsonl(
    path: str,
    store,
    kg=None,
    only_manual: bool = False,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    since: Optional[str] = None,
    include_vectors: bool = False,
    include_kg: bool = False,
    palace_path: str = "",
) -> Dict[str, Any]:
    """Write export JSONL to *path* (use '-' for stdout).

    With *include_kg*, an export scoped by *wing* or *room* includes only the KG facts
    extracted from the exported drawers' source files, plus the wing's namespace→project
    architecture facts (facts without a source file,
    such as MCP ``kg_add`` facts, are palace-wide and left out), and *since* keeps facts
    that started, or when undated were recorded, on or after it. ``--only-manual`` does
    not filter KG records.

    Missing parent directories of *path* are created. *path* must not exist
    (``FileExistsError``) unless it is a character device such as ``/dev/null``; the
    new file is created with mode 0o600. Raises
    ValueError for an invalid *since* before reading or writing anything.

    Returns summary dict: {drawer_count, kg_count, kg_entity_count, kg_scope}.
    """
    validate_since(since)
    filters: Dict[str, Any] = {}
    if only_manual:
        filters["only_manual"] = True
    if wing:
        filters["wing"] = wing
    if room:
        filters["room"] = room
    if since:
        filters["since"] = since
    if include_vectors:
        filters["with_embeddings"] = True
    if include_kg:
        filters["with_kg"] = True

    # Pre-count for header (two passes — acceptable for the sizes we handle)
    drawer_count, drawer_sources = _drawer_count_and_sources(
        store, only_manual=only_manual, wing=wing, room=room, since=since
    )
    kg_sources = drawer_sources if (wing or room) else None
    if wing and kg_sources is not None:
        from .architecture import namespace_project_source_file

        # Namespace→project architecture facts carry a per-wing sentinel source.
        kg_sources = kg_sources | {namespace_project_source_file(wing)}
    kg_count = kg_entity_count = 0
    if include_kg and kg is not None:
        for record in export_kg(kg, since=since, source_files=kg_sources):
            if record["type"] == "kg_triple":
                kg_count += 1
            else:
                kg_entity_count += 1
    kg_scope = "drawer_sources" if kg_sources is not None else "all"
    if include_kg:
        filters["kg_scope"] = kg_scope

    header = _make_header(
        palace_path=palace_path,
        filters=filters,
        drawer_count=drawer_count,
        kg_count=kg_count,
    )
    header["kg_entity_count"] = kg_entity_count

    created = False
    if path == "-":
        fh = sys.stdout
    elif _is_character_device(path):
        # A sink such as /dev/null holds no data to protect: write to it as is.
        fh = open(path, "w", encoding="utf-8")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # Never overwrite: an existing file may be an earlier export or unrelated data.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        fh = os.fdopen(fd, "w", encoding="utf-8")
        created = True
    try:
        fh.write(json.dumps(header) + "\n")

        for record in export_drawers(
            store,
            only_manual=only_manual,
            wing=wing,
            room=room,
            since=since,
            include_vectors=include_vectors,
        ):
            fh.write(json.dumps(record) + "\n")

        if include_kg and kg is not None:
            for record in export_kg(kg, since=since, source_files=kg_sources):
                fh.write(json.dumps(record) + "\n")
        if fh is not sys.stdout:
            fh.close()
    except BaseException:
        if fh is not sys.stdout:
            with contextlib.suppress(OSError):
                fh.close()
        if created:
            # Drop the partial file this call created, so the same --out can be retried.
            with contextlib.suppress(OSError):
                os.unlink(path)
        raise

    return {
        "drawer_count": drawer_count,
        "kg_count": kg_count,
        "kg_entity_count": kg_entity_count,
        "kg_scope": kg_scope,
    }


# ── Import ────────────────────────────────────────────────────────────────────


class JsonlInputError(ValueError):
    """Raised when a JSONL input file/stream contains a malformed line.

    Attributes:
        code: stable machine-testable error code ("malformed_jsonl").
        line_number: 1-based line number of the offending line.
    """

    code = "malformed_jsonl"

    def __init__(self, line_number: int, detail: str):
        self.line_number = line_number
        self.detail = detail
        super().__init__(f"{self.code}: line {line_number}: {detail}")


def read_jsonl(path: str) -> Iterator[Dict[str, Any]]:
    """Yield parsed JSON objects from a JSONL file.

    Raises JsonlInputError (with the offending line number) if a non-blank line
    fails to parse as JSON, or parses to a JSON value that is not an object
    (e.g. a bare number, string, list, or null).
    """
    fh = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        for line_number, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise JsonlInputError(line_number, str(exc)) from exc
            if not isinstance(parsed, dict):
                raise JsonlInputError(
                    line_number,
                    f"top-level value must be a JSON object, got {type(parsed).__name__}",
                )
            yield parsed
    finally:
        if fh is not sys.stdin:
            fh.close()


def _existing_ids(store, ids: List[str]) -> set[str]:
    """Return the subset of *ids* already stored; lookup errors propagate."""
    existing: set[str] = set()
    for start in range(0, len(ids), _ID_LOOKUP_BATCH):
        existing.update(store.get(ids=ids[start : start + _ID_LOOKUP_BATCH])["ids"])
    return existing


def _record_label(index: int, record: Dict[str, Any]) -> str:
    """Name a record by its 1-based position in the file and, when present, its id."""
    record_id = record.get("id")
    return f"record {index + 1}" + (f" (id {record_id!r})" if record_id else "")


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _drawer_record_error(record: Dict[str, Any], wing_override: Optional[str]) -> Optional[str]:
    """Return why a drawer record cannot be imported, or None when it is valid."""
    text = record.get("text")
    if not isinstance(text, str) or not text:
        return "missing or empty 'text'"
    for field in ("id", "room") if wing_override else ("id", "wing", "room"):
        if _blank(record.get(field)):
            return f"missing or blank '{field}'"
    return None


def _kg_record_error(record: Dict[str, Any]) -> Optional[str]:
    """Return why a kg_triple record cannot be imported, or None when it is valid."""
    for field in ("subject", "predicate", "object"):
        if _blank(record.get(field)):
            return f"missing or blank '{field}'"
    for field in ("valid_from", "valid_to", "source_closet", "source_file"):
        if record.get(field) is not None and not isinstance(record.get(field), str):
            return f"'{field}' must be a string or null"
    confidence = record.get("confidence", 1.0)
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
    ):
        return "'confidence' must be a number"
    try:
        _validate_window(
            _parse_temporal(record.get("valid_from")), _parse_temporal(record.get("valid_to"))
        )
    except ValueError as exc:
        return str(exc)
    return None


def _duplicate_indexes(
    store,
    records: List[Dict[str, Any]],
    wing_override: Optional[str],
    candidates: List[int],
    check_similarity: bool = True,
) -> tuple[set[int], int]:
    """Return (indexes import must skip as duplicates, failed similarity checks).

    A drawer record is a duplicate when its id is already stored or repeats an
    earlier record's id, or (with *check_similarity*) when its target wing already
    holds a drawer with cosine similarity >= ``_IMPORT_DEDUP_SIMILARITY``. Similarity
    is judged against the palace as it was before the import, so distinct records
    from one file never dedup each other. Only *candidates* (valid drawer record
    indexes) are considered.
    """
    stored_ids = _existing_ids(store, [records[index]["id"] for index in candidates])
    seen_ids: set[str] = set()
    indexes: set[int] = set()
    failed_checks = 0
    for index in candidates:
        record = records[index]
        drawer_id = record["id"]
        if drawer_id in stored_ids or drawer_id in seen_ids:
            indexes.add(index)
            continue
        seen_ids.add(drawer_id)
        if not check_similarity:
            continue
        wing = wing_override or record["wing"]
        try:
            results = store.query(
                query_texts=[record["text"]],
                n_results=1,
                where={"wing": wing},
                include=["distances"],
                intent_rerank=False,  # compare with the nearest drawer, not the reranked top
            )
            dists = results.get("distances", [[]])[0]
        except Exception:
            failed_checks += 1
            continue  # Import the record; the summary reports the skipped check
        if dists and distance_to_similarity(dists[0]) >= _IMPORT_DEDUP_SIMILARITY:
            indexes.add(index)
    return indexes, failed_checks


def import_jsonl(
    path: str,
    store,
    kg=None,
    skip_dedup: bool = False,
    skip_kg: bool = False,
    dry_run: bool = False,
    wing_override: Optional[str] = None,
    records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Import drawers and KG triples from a JSONL export file.

    *records*, when given, is used instead of re-reading *path* — callers that must
    validate input before opening store/KG state (e.g. the CLI) parse once with
    :func:`read_jsonl` and pass the result here, which also lets stdin be consumed
    exactly once. When *records* is None, the whole file is parsed upfront so a
    malformed line raises :class:`JsonlInputError` before any drawer or KG write
    happens (all-or-nothing on malformed input).

    Drawer ids stay unique: a record whose id is already stored or repeats earlier in
    the file is a skipped duplicate even with *skip_dedup*, which only disables the
    similarity check. Invalid drawer and KG records are counted and named in
    ``warnings``; a dry run validates and counts exactly like a real import without
    writing palace or KG state.

    Valid KG records (``kg_entity`` and ``kg_triple``) are merged after the drawers in
    one KG transaction by ``kg.import_facts``: replaying the same export is a no-op,
    exported ids and ``extracted_at`` are kept, and a fact this palace invalidated
    after the export stays invalidated (reported as a conflict). A dry run runs the
    same merge against a read-only snapshot, so its KG counts match a live import.

    Returns summary: {imported_drawers, skipped_duplicates, skipped_invalid,
    failed_drawers, imported_triples, skipped_kg_duplicates, invalid_triples,
    kg_conflicts, kg_invalidations_applied, imported_kg_entities, ignored_records,
    rejected, export_version, kg_error, warnings}; ``rejected`` counts every invalid or
    failed drawer and KG record. ``kg_error`` is None, or the reason the KG transaction
    failed, in which case no KG record was imported.
    """
    if records is None:
        records = list(read_jsonl(path))

    imported_drawers = 0
    defaulted_manual = 0
    skipped_duplicates = 0
    failed_drawers = 0
    invalid_triples = 0
    warnings: List[str] = []

    export_version: Optional[str] = None
    if records and records[0].get("type") != "export_header":
        warnings.append("No export_header found at start of file — format may be invalid.")
    for record in records:
        if record.get("type") != "export_header":
            continue
        file_version = record.get("version", "")
        export_version = str(file_version) if file_version else None
        if file_version and file_version != __version__:
            warnings.append(
                f"Version mismatch: export was created with {file_version}, "
                f"current is {__version__}. Proceeding anyway."
            )
        break

    drawer_indexes: List[int] = []
    invalid_drawers = 0
    unknown_types: Dict[str, List[int]] = {}
    for index, record in enumerate(records):
        rtype = record.get("type")
        if rtype == "drawer":
            error = _drawer_record_error(record, wing_override)
            if error is None:
                drawer_indexes.append(index)
            else:
                invalid_drawers += 1
                warnings.append(f"Skipped invalid drawer {_record_label(index, record)}: {error}")
        elif rtype not in ("export_header", "kg_triple", "kg_entity"):
            unknown_types.setdefault(str(rtype), []).append(index + 1)
    for rtype, positions in unknown_types.items():
        shown = ", ".join(str(n) for n in positions[:10]) + (" ..." if len(positions) > 10 else "")
        warnings.append(
            f"Ignored {len(positions)} record(s) of unknown type {rtype!r} (records {shown})"
        )

    # Decide duplicates against the palace as it was before this import, so
    # distinct records from one file never dedup against each other.
    duplicate_indexes, failed_checks = _duplicate_indexes(
        store, records, wing_override, drawer_indexes, check_similarity=not skip_dedup
    )
    if failed_checks:
        warnings.append(
            f"Similarity check failed for {failed_checks} drawer(s); they were imported "
            "without near-duplicate detection."
        )

    valid_drawers = set(drawer_indexes)
    kg_active = not skip_kg and kg is not None
    kg_triples: List[Dict[str, Any]] = []
    kg_entities: List[Dict[str, Any]] = []

    for index, record in enumerate(records):
        rtype = record.get("type")

        if rtype == "drawer" and index in valid_drawers:
            text = record["text"]
            drawer_id = record["id"]
            if index in duplicate_indexes:
                skipped_duplicates += 1
                continue

            # No miner can regenerate a drawer without a source file: without a strategy
            # it would fall out of every --only-manual export, so it is a manual drawer.
            manual_default = _blank(record.get("chunker_strategy")) and _blank(
                record.get("source_file")
            )
            if dry_run:
                imported_drawers += 1
                defaulted_manual += int(manual_default)
                continue

            # Build metadata
            meta_keys = (
                "source_file",
                "chunk_index",
                "added_by",
                "filed_at",
                "hall",
                "topic",
                "agent",
                "date",
                "ingest_mode",
                "extract_mode",
                "compression_ratio",
                "original_tokens",
                "language",
                "symbol_name",
                "symbol_type",
                "source_hash",
                "extractor_version",
                "chunker_strategy",
                "line_start",
                "line_end",
            )
            meta: Dict[str, Any] = {"wing": wing_override or record["wing"], "room": record["room"]}
            for k in meta_keys:
                if k in record:
                    meta[k] = record[k]
            # `drawer_type` was stored to avoid collision with the record `type` key
            if "drawer_type" in record:
                meta["type"] = record["drawer_type"]
            if manual_default:
                meta["chunker_strategy"] = _MANUAL_STRATEGIES[0]

            try:
                store.add(ids=[drawer_id], documents=[text], metadatas=[meta])
                imported_drawers += 1
                defaulted_manual += int(manual_default)
            except DuplicateDrawerIdError:
                # Stored by another writer after the duplicate check; never overwrite it.
                skipped_duplicates += 1
            except Exception as exc:
                failed_drawers += 1
                warnings.append(f"Failed to import drawer {_record_label(index, record)}: {exc}")

        elif rtype == "kg_triple" and kg_active:
            error = _kg_record_error(record)
            if error is not None:
                invalid_triples += 1
                warnings.append(
                    f"Skipped invalid KG triple {_record_label(index, record)}: {error}"
                )
                continue
            kg_triples.append(record)
        elif rtype == "kg_entity" and kg_active:
            kg_entities.append(record)

    if defaulted_manual:
        warnings.append(
            f"{defaulted_manual} drawer(s) had no chunker_strategy and no source_file; "
            f"{'they would be' if dry_run else 'they were'} stored as "
            f"{_MANUAL_STRATEGIES[0]} (manual drawers), so export --only-manual keeps them."
        )

    kg_summary: Dict[str, Any] = {
        "inserted": 0,
        "duplicates": 0,
        "invalidations_applied": 0,
        "conflicts": [],
        "entities": 0,
        "failed": [],
    }
    kg_error: Optional[str] = None
    if (kg_triples or kg_entities) and kg is not None:
        try:
            kg_summary = kg.import_facts(kg_triples, kg_entities, dry_run=dry_run)
        except Exception as exc:
            # The merge is one transaction: nothing from the KG section was written.
            kg_error = f"{type(exc).__name__}: {exc}"
    imported_triples = kg_summary["inserted"]
    for failure in kg_summary["failed"]:
        invalid_triples += 1
        warnings.append(f"Failed to import KG record: {failure}")
    conflicts = kg_summary["conflicts"]
    if conflicts:
        shown = "; ".join(conflicts[:5]) + ("; ..." if len(conflicts) > 5 else "")
        warnings.append(
            f"{len(conflicts)} KG fact(s) open in the export stay invalidated because this "
            f"palace ended them; their open copies were not imported: {shown}"
        )

    return {
        "imported_drawers": imported_drawers,
        "skipped_duplicates": skipped_duplicates,
        "skipped_invalid": invalid_drawers,
        "failed_drawers": failed_drawers,
        "imported_triples": imported_triples,
        "skipped_kg_duplicates": kg_summary["duplicates"],
        "invalid_triples": invalid_triples,
        "kg_conflicts": len(conflicts),
        "kg_invalidations_applied": kg_summary["invalidations_applied"],
        "imported_kg_entities": kg_summary["entities"],
        "ignored_records": sum(len(positions) for positions in unknown_types.values()),
        "rejected": invalid_drawers + failed_drawers + invalid_triples,
        "export_version": export_version,
        "kg_error": kg_error,
        "warnings": warnings,
    }
