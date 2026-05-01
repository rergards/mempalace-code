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
import logging
import os
import shutil
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mempalace")


def create_backup(
    palace_path: str,
    out_path: Optional[str] = None,
    kg_path: Optional[str] = None,
) -> tuple:
    """Create a .tar.gz backup of the palace.

    Parameters
    ----------
    palace_path:
        Root directory of the palace (``lance/`` subdirectory lives here).
    out_path:
        Destination ``.tar.gz`` file.  Defaults to
        ``<palace_parent>/backups/mempalace_backup_YYYYMMDD_HHMMSS.tar.gz``.
    kg_path:
        Path to the knowledge-graph SQLite file.  Defaults to
        ``knowledge_graph.DEFAULT_KG_PATH``.

    Returns
    -------
    tuple
        ``(metadata, out_path)`` — the metadata dict written to ``metadata.json``
        and the resolved output path of the archive.
    """
    from .knowledge_graph import DEFAULT_KG_PATH
    from .storage import open_store
    from .version import __version__

    if kg_path is None:
        kg_path = DEFAULT_KG_PATH

    if out_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backups_dir = os.path.join(os.path.dirname(os.path.abspath(palace_path)), "backups")
        os.makedirs(backups_dir, exist_ok=True)
        os.chmod(backups_dir, 0o700)  # F-9: restrict to owner only — backups contain personal data
        out_path = os.path.join(backups_dir, f"mempalace_backup_{ts}.tar.gz")

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
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)  # F-10: auto-create parent dir for explicit --out paths

    # Write atomically: build archive in a temp file, then rename into place.
    # A partial/interrupted write therefore never corrupts the destination.
    tmp_fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".tar.gz.tmp")
    os.close(tmp_fd)
    try:
        with tarfile.open(tmp_path, "w:gz") as tar:
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
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(meta_bytes))

        os.replace(tmp_path, out_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return metadata, out_path


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

            # Move KG into its canonical location (atomic: copy to .tmp, then rename)
            extracted_kg = os.path.join(tmpdir, "knowledge_graph.sqlite3")
            if os.path.isfile(extracted_kg):
                if os.path.isfile(kg_path):
                    print(
                        f"  Warning: overwriting existing knowledge graph at {kg_path}",
                        file=sys.stderr,
                    )
                kg_dir = os.path.dirname(os.path.abspath(kg_path))
                os.makedirs(kg_dir, exist_ok=True)
                kg_tmp = kg_path + ".tmp"
                shutil.copy2(extracted_kg, kg_tmp)
                os.replace(kg_tmp, kg_path)

    return metadata


def list_backups(palace_path: str, extra_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """List backup archives under <palace_parent>/backups/ (plus extra_dir if given).

    Parameters
    ----------
    palace_path:
        Root directory of the palace.
    extra_dir:
        Optional additional directory to scan (e.g. a legacy CWD backup location).

    Returns
    -------
    list of dicts, sorted newest-first, each with keys:
        path, size_bytes, mtime, timestamp, drawer_count, wings, kind
    """
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(palace_path)), "backups")

    dirs_to_scan = [backups_dir]
    if extra_dir is not None:
        abs_extra = os.path.abspath(extra_dir)
        if abs_extra != os.path.abspath(backups_dir):
            dirs_to_scan.append(abs_extra)

    seen_paths: set = set()
    entries = []

    for scan_dir in dirs_to_scan:
        if not os.path.isdir(scan_dir):
            continue
        for fname in os.listdir(scan_dir):
            if not fname.endswith(".tar.gz"):
                continue
            fpath = os.path.abspath(os.path.join(scan_dir, fname))
            if fpath in seen_paths:
                continue
            seen_paths.add(fpath)

            try:
                stat = os.stat(fpath)
            except (FileNotFoundError, PermissionError) as exc:
                logger.warning("Could not stat backup file (skipped): %s (%s)", fpath, exc)
                continue
            entry: Dict[str, Any] = {
                "path": fpath,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "timestamp": None,
                "drawer_count": None,
                "wings": [],
                "kind": _classify_backup_kind(fname),
            }

            # Try to open the archive and read metadata.
            # If the tar itself is unreadable, skip the entry entirely.
            try:
                with tarfile.open(fpath, "r:gz") as tar:
                    members = {m.name for m in tar.getmembers()}
                    if "mempalace_backup/metadata.json" in members:
                        try:
                            f = tar.extractfile(tar.getmember("mempalace_backup/metadata.json"))
                            if f is not None:
                                meta = json.loads(f.read().decode())
                                entry["timestamp"] = meta.get("timestamp")
                                entry["drawer_count"] = meta.get("drawer_count")
                                entry["wings"] = meta.get("wings", [])
                        except Exception:
                            logger.warning("Could not parse metadata.json in archive: %s", fpath)
            except Exception:
                logger.warning("Could not open backup archive (skipped): %s", fpath)
                continue

            entries.append(entry)

    # Sort newest-first by mtime
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries


def _classify_backup_kind(filename: str) -> str:
    """Classify a backup archive filename into a kind string."""
    if filename.startswith("pre_optimize_"):
        return "pre_optimize"
    if filename.startswith("scheduled_"):
        return "scheduled"
    if filename.startswith("mempalace_backup_"):
        return "manual"
    return "other"


def render_schedule(
    freq: str,
    palace_path: str,
    platform: str,
    mempalace_bin: Optional[str] = None,
) -> str:
    """Render a scheduler snippet (launchd plist or cron line) for scheduled backups.

    Parameters
    ----------
    freq:
        One of: daily, weekly, hourly.
    palace_path:
        Root directory of the palace (determines the output backup directory).
    platform:
        'darwin' for launchd plist, 'linux' for cron line.
    mempalace_bin:
        Override the mempalace-code binary path (default: resolved via shutil.which).

    Returns
    -------
    str
        Launchd plist XML (darwin) or cron line (linux).

    Raises
    ------
    ValueError
        If freq or platform is unsupported.
    """
    import shlex as _shlex
    import shutil as _shutil

    valid_freqs = ("daily", "weekly", "hourly")
    if freq not in valid_freqs:
        raise ValueError(f"Unsupported freq {freq!r}; must be one of: {valid_freqs}")
    if platform not in ("darwin", "linux"):
        raise ValueError(f"Unsupported platform {platform!r}; must be 'darwin' or 'linux'")

    backups_dir = os.path.join(os.path.dirname(os.path.abspath(palace_path)), "backups")

    if mempalace_bin is None:
        resolved_bin = _shutil.which("mempalace-code")
        if resolved_bin is None:
            safe_bin = f"{_shlex.quote(sys.executable)} -m mempalace_code"
        else:
            safe_bin = _shlex.quote(resolved_bin)
    else:
        safe_bin = _shlex.quote(mempalace_bin)

    # F-8: shell-quote binary and dir to handle paths with spaces or special characters.
    # The $(date ...) suffix is kept unquoted so the shell expands it at runtime.
    safe_dir = _shlex.quote(backups_dir)
    out_arg = f"{safe_dir}/scheduled_$(date +%Y%m%d_%H%M%S).tar.gz"

    if platform == "linux":
        # cron: minute hour dom month dow command
        if freq == "daily":
            cron_time = "0 3 * * *"
        elif freq == "weekly":
            cron_time = "0 3 * * 0"
        else:  # hourly
            cron_time = "0 * * * *"
        return f"{cron_time} {safe_bin} backup create --out {out_arg}\n"

    # darwin: launchd plist
    def _xml_escape(s: str) -> str:
        """Escape XML special characters for embedding in a plist <string> element."""
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    label = "com.mempalace.backup"

    if freq == "daily":
        schedule_xml = (
            "    <key>StartCalendarInterval</key>\n"
            "    <dict>\n"
            "        <key>Hour</key>\n"
            "        <integer>3</integer>\n"
            "        <key>Minute</key>\n"
            "        <integer>0</integer>\n"
            "    </dict>"
        )
    elif freq == "weekly":
        schedule_xml = (
            "    <key>StartCalendarInterval</key>\n"
            "    <dict>\n"
            "        <key>Hour</key>\n"
            "        <integer>3</integer>\n"
            "        <key>Minute</key>\n"
            "        <integer>0</integer>\n"
            "        <key>Weekday</key>\n"
            "        <integer>0</integer>\n"
            "    </dict>"
        )
    else:  # hourly
        schedule_xml = "    <key>StartInterval</key>\n    <integer>3600</integer>"

    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
        '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{label}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        "        <string>/bin/sh</string>\n"
        "        <string>-c</string>\n"
        f"        <string>{_xml_escape(f'{safe_bin} backup create --out {out_arg}')}</string>\n"
        "    </array>\n"
        f"{schedule_xml}\n"
        "    <key>RunAtLoad</key>\n"
        "    <false/>\n"
        "</dict>\n"
        "</plist>\n"
    )
    return plist
