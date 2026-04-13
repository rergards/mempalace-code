"""
export.py — Export and import drawers + KG triples as JSONL

Provides backup/restore for manually-added drawers, diary entries, and knowledge
graph triples that would otherwise be lost when nuking and re-seeding a palace.

Typical workflow:
    # Before nuke-and-re-seed:
    mempalace export --only-manual --with-kg --out backup.jsonl

    # After re-mine:
    mempalace import backup.jsonl
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from .version import __version__

# Chunker strategies produced by manual writes (MCP add_drawer + diary)
_MANUAL_STRATEGIES = ("manual_v1", "diary_v1")


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
            record = {"type": "drawer"}
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
            ):
                record[key] = row.get(key, "")
            # `type` is overloaded — store drawer metadata `type` under `drawer_type`
            record["drawer_type"] = row.get("type", "")
            yield record


def export_kg(
    kg,
    since: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """Yield one KG triple dict per record."""
    for batch in kg.iter_all_triples():
        for triple in batch:
            if since and triple.get("valid_from") and triple.get("valid_from") < since:
                continue
            record = {"type": "kg_triple"}
            record.update(triple)
            yield record


def _count_drawers(
    store,
    only_manual: bool = False,
    wing: Optional[str] = None,
    room: Optional[str] = None,
    since: Optional[str] = None,
) -> int:
    """Count matching drawers for the export header."""
    return sum(
        1 for _ in export_drawers(store, only_manual=only_manual, wing=wing, room=room, since=since)
    )


def _count_kg(kg, since: Optional[str] = None) -> int:
    return sum(1 for _ in export_kg(kg, since=since))


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
    pretty: bool = False,
    palace_path: str = "",
) -> Dict[str, int]:
    """Write export JSONL to *path* (use '-' for stdout).

    Returns summary dict: {drawer_count, kg_count}.
    """
    indent = 2 if pretty else None

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
    drawer_count = _count_drawers(store, only_manual=only_manual, wing=wing, room=room, since=since)
    kg_count = _count_kg(kg, since=since) if (include_kg and kg is not None) else 0

    header = _make_header(
        palace_path=palace_path,
        filters=filters,
        drawer_count=drawer_count,
        kg_count=kg_count,
    )

    fh = sys.stdout if path == "-" else open(path, "w", encoding="utf-8")
    try:
        fh.write(json.dumps(header, indent=indent) + "\n")

        for record in export_drawers(
            store,
            only_manual=only_manual,
            wing=wing,
            room=room,
            since=since,
            include_vectors=include_vectors,
        ):
            fh.write(json.dumps(record, indent=indent) + "\n")

        if include_kg and kg is not None:
            for record in export_kg(kg, since=since):
                fh.write(json.dumps(record, indent=indent) + "\n")
    finally:
        if fh is not sys.stdout:
            fh.close()

    return {"drawer_count": drawer_count, "kg_count": kg_count}


# ── Import ────────────────────────────────────────────────────────────────────


def read_jsonl(path: str) -> Iterator[Dict[str, Any]]:
    """Yield parsed JSON objects from a JSONL file."""
    fh = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
    finally:
        if fh is not sys.stdin:
            fh.close()


def import_jsonl(
    path: str,
    store,
    kg=None,
    skip_dedup: bool = False,
    skip_kg: bool = False,
    dry_run: bool = False,
    wing_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Import drawers and KG triples from a JSONL export file.

    Returns summary: {imported_drawers, skipped_duplicates, imported_triples, warnings}.
    """
    imported_drawers = 0
    skipped_duplicates = 0
    imported_triples = 0
    warnings: List[str] = []

    header_seen = False
    no_header_warned = False

    for record in read_jsonl(path):
        rtype = record.get("type")

        if rtype == "export_header":
            header_seen = True
            file_version = record.get("version", "")
            if file_version and file_version != __version__:
                msg = (
                    f"Version mismatch: export was created with {file_version}, "
                    f"current is {__version__}. Proceeding anyway."
                )
                warnings.append(msg)
                print(f"WARNING: {msg}", file=sys.stderr)
            continue

        if not header_seen and not no_header_warned:
            warnings.append("No export_header found at start of file — format may be invalid.")
            no_header_warned = True

        if rtype == "drawer":
            wing = wing_override or record.get("wing", "")
            room = record.get("room", "")
            text = record.get("text", "")
            drawer_id = record.get("id", "")

            if not text:
                continue

            # Dedup check via cosine similarity
            if not skip_dedup:
                try:
                    results = store.query(
                        query_texts=[text],
                        n_results=1,
                        include=["distances"],
                    )
                    dists = results.get("distances", [[]])[0]
                    if dists:
                        # LanceDB returns L2 distance; convert to approximate cosine similarity
                        # For unit vectors: cosine_sim ≈ 1 - (L2^2 / 2)
                        # At threshold 0.9 cosine → L2^2 ≈ 0.2 → L2 ≈ 0.447
                        l2 = dists[0]
                        cosine_sim = max(0.0, 1.0 - (l2 * l2) / 2.0)
                        if cosine_sim >= 0.9:
                            skipped_duplicates += 1
                            continue
                except Exception:
                    pass  # If dedup check fails, proceed with import

            if dry_run:
                imported_drawers += 1
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
            )
            meta: Dict[str, Any] = {"wing": wing, "room": room}
            for k in meta_keys:
                if k in record:
                    meta[k] = record[k]
            # `drawer_type` was stored to avoid collision with the record `type` key
            if "drawer_type" in record:
                meta["type"] = record["drawer_type"]

            try:
                store.add(ids=[drawer_id], documents=[text], metadatas=[meta])
                imported_drawers += 1
            except Exception as exc:
                # Duplicate ID — try upsert
                try:
                    store.upsert(ids=[drawer_id], documents=[text], metadatas=[meta])
                    imported_drawers += 1
                except Exception:
                    warnings.append(f"Failed to import drawer {drawer_id}: {exc}")

        elif rtype == "kg_triple" and not skip_kg and kg is not None:
            if dry_run:
                imported_triples += 1
                continue
            try:
                kg.add_triple(
                    subject=record.get("subject", ""),
                    predicate=record.get("predicate", ""),
                    obj=record.get("object", ""),
                    valid_from=record.get("valid_from"),
                    valid_to=record.get("valid_to"),
                    confidence=record.get("confidence", 1.0),
                    source_closet=record.get("source_closet"),
                    source_file=record.get("source_file"),
                )
                imported_triples += 1
            except Exception as exc:
                warnings.append(f"Failed to import KG triple: {exc}")

    return {
        "imported_drawers": imported_drawers,
        "skipped_duplicates": skipped_duplicates,
        "imported_triples": imported_triples,
        "warnings": warnings,
    }
