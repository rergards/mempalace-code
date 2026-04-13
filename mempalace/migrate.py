"""
migrate.py — ChromaDB → LanceDB palace migration
=================================================

Provides migrate_chroma_to_lance() to copy all drawers from a
ChromaDB palace to a LanceDB palace. Used by the 'mempalace migrate-storage'
CLI subcommand.
"""

from __future__ import annotations

import os
import tarfile
from datetime import datetime
from typing import Optional


class VerificationError(Exception):
    """Raised when post-migration count verification fails."""


def migrate_chroma_to_lance(
    src_path: str,
    dst_path: str,
    backup_dir: Optional[str] = None,
    force: bool = False,
    embed_model: Optional[str] = None,
    verify: bool = False,
    no_backup: bool = False,
) -> tuple[int, int]:
    """
    Copy all drawers from a ChromaDB palace to a LanceDB palace.

    Returns (src_count, dst_count).

    Args:
        src_path:   Path to the source ChromaDB palace directory.
        dst_path:   Path to the destination LanceDB palace directory.
        backup_dir: Directory where the source backup tar.gz is written.
                    Defaults to the parent directory of src_path.
        force:      If True, allow writing to a non-empty destination
                    (appends rather than refusing).
        embed_model: Sentence-transformers model name for the destination
                    LanceDB store. None = LanceStore default (all-MiniLM-L6-v2).
        verify:     If True, compare accumulated per-wing source counts against
                    the destination counts after migration. Raises VerificationError
                    on any mismatch.
        no_backup:  If True, skip creating a backup of the source palace.
                    Intended for tests; not exposed in the public CLI.
    """
    from .storage import ChromaStore, LanceStore

    # Open source ChromaDB palace — wrap chromadb ImportError with a helpful message.
    try:
        src_store = ChromaStore(src_path, create=False)
    except ImportError:
        raise RuntimeError("chromadb not installed — run: pip install mempalace[chroma]")

    if src_store._col is None:
        raise RuntimeError(f"No ChromaDB collection found at {src_path}")

    src_total = src_store.count()
    if src_total == 0:
        print("Source palace is empty — nothing to migrate.")
        return (0, 0)

    # Open destination LanceDB palace.
    os.makedirs(dst_path, exist_ok=True)
    dst_store = LanceStore(dst_path, create=True, embed_model=embed_model)

    # Guard against writing to a non-empty destination.
    if dst_store.count() > 0 and not force:
        raise RuntimeError(
            f"Destination palace at {dst_path!r} already contains rows. "
            "Pass --force to append to it."
        )

    # Backup source palace.
    if not no_backup:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_filename = f"chroma-pre-migrate-{ts}.tar.gz"
        if backup_dir is None:
            effective_backup_dir = str(os.path.dirname(os.path.abspath(src_path)))
        else:
            effective_backup_dir = backup_dir
        os.makedirs(effective_backup_dir, exist_ok=True)
        backup_path = os.path.join(effective_backup_dir, backup_filename)
        print(f"Backing up {src_path} → {backup_path} ...")
        with tarfile.open(backup_path, "w:gz") as tar:
            tar.add(src_path, arcname=os.path.basename(src_path))
        print(f"Backup created: {backup_path}")

    # Migrate in pages of 1000.
    BATCH_SIZE = 1000
    offset = 0
    running_total = 0
    src_wing_counts: dict[str, int] = {}

    print(f"Migrating {src_total} drawers from ChromaDB → LanceDB ...")

    while offset < src_total:
        try:
            batch = src_store.get(
                limit=BATCH_SIZE,
                offset=offset,
                include=["documents", "metadatas"],
            )
        except Exception as e:
            raise RuntimeError(
                f"Error reading batch at offset {offset}: {e}. "
                f"Migration aborted. {running_total} drawers written so far."
            ) from e

        batch_ids = batch.get("ids", [])
        batch_docs = batch.get("documents", [])
        batch_metas = batch.get("metadatas", [])

        if not batch_ids:
            break

        # Accumulate per-wing counts from source metadata (free — we already read them).
        for meta in batch_metas:
            wing = (meta.get("wing", "") if meta else "") or ""
            src_wing_counts[wing] = src_wing_counts.get(wing, 0) + 1

        try:
            dst_store.add(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
        except Exception as e:
            raise RuntimeError(
                f"Error writing batch at offset {offset}: {e}. "
                f"Migration aborted. {running_total} drawers written so far."
            ) from e

        running_total += len(batch_ids)
        print(f"Migrated {running_total}/{src_total} drawers...", flush=True)
        offset += BATCH_SIZE

    dst_total = dst_store.count()

    # Optional per-wing verification.
    if verify:
        dst_wing_counts = dst_store.count_by("wing")
        mismatches = []
        for wing, src_cnt in src_wing_counts.items():
            dst_cnt = dst_wing_counts.get(wing, 0)
            if src_cnt != dst_cnt:
                mismatches.append(f"  wing={wing!r}: src={src_cnt}, dst={dst_cnt}")
        if mismatches:
            diff = "\n".join(mismatches)
            raise VerificationError(f"Per-wing count mismatch after migration:\n{diff}")

    print(f"Migration complete: {src_total} drawers migrated.")
    return (src_total, dst_total)
