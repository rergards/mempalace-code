"""
backup.py — Palace backup and restore via .tar.gz archives.

Creates and extracts self-contained snapshots of the palace:

    mempalace_backup/
    ├── lance/                        # Full copy of <palace>/lance/
    │   └── ...                       # LanceDB columnar files, transactions, etc.
    ├── knowledge_graph.sqlite3       # Copy of the KG SQLite database (omitted if absent)
    └── metadata.json                 # Backup metadata (drawer_count, wings, timestamp, …)

The ``mempalace_backup/`` prefix prevents tarbomb extraction.
"""

import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
from datetime import datetime
from typing import Optional


def create_backup(
    palace_path: str,
    out_path: Optional[str] = None,
    kg_path: Optional[str] = None,
) -> dict:
    """Create a .tar.gz backup of the palace.

    Parameters
    ----------
    palace_path:
        Root directory of the palace (``lance/`` subdirectory lives here).
    out_path:
        Destination ``.tar.gz`` file.  Defaults to
        ``mempalace_backup_YYYYMMDD_HHMMSS.tar.gz`` in the current working directory.
    kg_path:
        Path to the knowledge-graph SQLite file.  Defaults to
        ``knowledge_graph.DEFAULT_KG_PATH``.

    Returns
    -------
    dict
        The metadata dict written to ``metadata.json`` inside the archive.
    """
    from .knowledge_graph import DEFAULT_KG_PATH
    from .storage import open_store
    from .version import __version__

    if kg_path is None:
        kg_path = DEFAULT_KG_PATH

    if out_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(os.getcwd(), f"mempalace_backup_{ts}.tar.gz")

    # Gather metadata — open store read-only; tolerate missing palace.
    try:
        store = open_store(palace_path, create=False)
        drawer_count = store.count()
        wings = sorted(store.count_by("wing").keys())
    except Exception:
        drawer_count = 0
        wings = []

    metadata = {
        "drawer_count": drawer_count,
        "wings": wings,
        "timestamp": datetime.now().isoformat(),
        "mempalace_version": __version__,
        "backend_type": "lancedb",
    }

    lance_dir = os.path.join(palace_path, "lance")

    with tarfile.open(out_path, "w:gz") as tar:
        # Lance vector data
        if os.path.isdir(lance_dir):
            tar.add(lance_dir, arcname="mempalace_backup/lance")

        # Knowledge graph (optional — may not exist)
        if os.path.isfile(kg_path):
            tar.add(kg_path, arcname="mempalace_backup/knowledge_graph.sqlite3")

        # Metadata JSON (in-memory, no temp file needed)
        meta_bytes = json.dumps(metadata, indent=2).encode()
        info = tarfile.TarInfo(name="mempalace_backup/metadata.json")
        info.size = len(meta_bytes)
        tar.addfile(info, io.BytesIO(meta_bytes))

    return metadata


def restore_backup(
    archive_path: str,
    palace_path: str,
    force: bool = False,
    kg_path: Optional[str] = None,
) -> dict:
    """Extract a backup archive into the target palace path.

    Parameters
    ----------
    archive_path:
        Path to the ``.tar.gz`` archive created by :func:`create_backup`.
    palace_path:
        Root directory where the palace should be restored.
    force:
        When ``True``, an existing non-empty ``lance/`` directory is removed
        before extraction.  When ``False`` (default) a non-empty palace raises
        :class:`FileExistsError`.
    kg_path:
        Destination for the knowledge-graph SQLite file.  Defaults to
        ``knowledge_graph.DEFAULT_KG_PATH``.

    Returns
    -------
    dict
        The parsed ``metadata.json`` from the archive.

    Raises
    ------
    FileExistsError
        If the palace already contains data and *force* is ``False``.
    """
    from .knowledge_graph import DEFAULT_KG_PATH

    if kg_path is None:
        kg_path = DEFAULT_KG_PATH

    lance_dir = os.path.join(palace_path, "lance")

    # AC-4 — non-empty palace guard
    if os.path.isdir(lance_dir) and os.listdir(lance_dir):
        if not force:
            raise FileExistsError(
                f"Palace at {palace_path!r} already contains data (lance/ is non-empty). "
                "Use --force to overwrite."
            )
        shutil.rmtree(lance_dir)

    metadata: dict = {}

    with tarfile.open(archive_path, "r:gz") as tar:
        member_names = {m.name for m in tar.getmembers()}

        # Read metadata first (always available, no extraction needed)
        if "mempalace_backup/metadata.json" in member_names:
            f = tar.extractfile(tar.getmember("mempalace_backup/metadata.json"))
            if f is not None:
                metadata = json.loads(f.read().decode())

        # Safe manual extraction into a temp dir to prevent path traversal
        with tempfile.TemporaryDirectory(prefix="mempalace_restore_") as tmpdir:
            for member in tar.getmembers():
                name = member.name

                # Only process entries inside our known prefix
                if not name.startswith("mempalace_backup/"):
                    continue

                rel = name[len("mempalace_backup/") :]
                if not rel:
                    continue  # skip the prefix directory entry itself

                # Reject any path-traversal attempts
                parts = rel.replace("\\", "/").split("/")
                if any(p in ("", "..") for p in parts):
                    continue

                dest = os.path.join(tmpdir, *parts)

                if member.isdir():
                    os.makedirs(dest, exist_ok=True)
                elif member.isfile():
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    src = tar.extractfile(member)
                    if src is not None:
                        with open(dest, "wb") as dst:
                            dst.write(src.read())

            # Move lance/ into the target palace
            extracted_lance = os.path.join(tmpdir, "lance")
            if os.path.isdir(extracted_lance):
                os.makedirs(palace_path, exist_ok=True)
                shutil.copytree(extracted_lance, lance_dir)

            # Move KG into its canonical location
            extracted_kg = os.path.join(tmpdir, "knowledge_graph.sqlite3")
            if os.path.isfile(extracted_kg):
                if os.path.isfile(kg_path):
                    print(
                        f"  Warning: overwriting existing knowledge graph at {kg_path}",
                        file=sys.stderr,
                    )
                kg_dir = os.path.dirname(os.path.abspath(kg_path))
                os.makedirs(kg_dir, exist_ok=True)
                shutil.copy2(extracted_kg, kg_path)

    return metadata
