#!/usr/bin/env python3
"""
split_mega_files.py — Split concatenated transcript files into per-session files
=================================================================================

Scans a directory for .txt files that contain multiple Claude Code sessions
(identified by "Claude Code v" headers). Splits each into individual files
named with: date, time, people detected, and subject from first prompt.

Distinguishes true session starts from mid-session context restores
(which show "Ctrl+E to show X previous messages").

Output files are written to --output-dir (default: same dir as source).
Original files are renamed with .mega_backup extension (not deleted).

Usage:
    python3 split_mega_files.py                          # scan ~/Desktop/transcripts
    python3 split_mega_files.py --source ~/Desktop/transcripts  # explicit source
    python3 split_mega_files.py --dry-run                # show what would happen
    python3 split_mega_files.py --min-sessions 2         # only files with 2+ sessions

By: Ben, 2026-03-30
"""

import argparse
import errno
import json
import os
import re
import stat
import sys
from pathlib import Path

from .source_io import (
    RegularSourceError,
    is_regular_source_path,
    read_regular_text,
    regular_source_diagnostic,
    stat_regular_source,
)

HOME = Path.home()

_HAS_O_NONBLOCK = bool(getattr(os, "O_NONBLOCK", 0))
_HAS_O_NOFOLLOW = bool(getattr(os, "O_NOFOLLOW", 0))
_O_BINARY = getattr(os, "O_BINARY", 0)
_OUTPUT_MODE = 0o644
_OUTPUT_TARGET_REASON = "not a regular output target"
_OUTPUT_REPLACE_REASON = "cannot safely replace an existing output target on this platform"
LUMI_DIR = Path(os.environ.get("MEMPALACE_SOURCE_DIR", str(HOME / "Desktop/transcripts")))

# People explicitly configured for name detection in content.
_KNOWN_NAMES_PATH = HOME / ".mempalace" / "known_names.json"
_KNOWN_NAMES_CACHE = None


def _load_known_names_config(force_reload: bool = False):
    """Load and cache the optional known-names config file."""
    global _KNOWN_NAMES_CACHE

    if force_reload:
        _KNOWN_NAMES_CACHE = None

    if _KNOWN_NAMES_CACHE is not None:
        return _KNOWN_NAMES_CACHE

    if _KNOWN_NAMES_PATH.exists():
        try:
            _KNOWN_NAMES_CACHE = json.loads(read_regular_text(_KNOWN_NAMES_PATH))
            return _KNOWN_NAMES_CACHE
        except (json.JSONDecodeError, OSError):
            pass

    _KNOWN_NAMES_CACHE = None
    return None


def _load_known_people() -> list:
    """Load explicitly configured known names."""
    data = _load_known_names_config()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("names", [])
    return []


KNOWN_PEOPLE = _load_known_people()


def _load_username_map() -> dict:
    """Load username-to-name mapping from config file."""
    data = _load_known_names_config()
    if isinstance(data, dict):
        return data.get("username_map", {})
    return {}


def is_true_session_start(lines, idx):
    """
    True session start: 'Claude Code v' header NOT followed by 'Ctrl+E'/'previous messages'
    within the next 6 lines (those are context restores, not new sessions).
    """
    nearby = "".join(lines[idx : idx + 6])
    return "Ctrl+E" not in nearby and "previous messages" not in nearby


def find_session_boundaries(lines):
    """Return list of line indices where true new sessions begin."""
    boundaries = []
    for i, line in enumerate(lines):
        if "Claude Code v" in line and is_true_session_start(lines, i):
            boundaries.append(i)
    return boundaries


def _read_session_lines(path: Path) -> list[str]:
    return read_regular_text(path, errors="replace").splitlines(keepends=True)


def discover_text_sources(src_dir: Path) -> list[Path]:
    """Return regular .txt sources for split scanning."""
    files = []
    for path in sorted(src_dir.glob("*.txt")):
        if not is_regular_source_path(path):
            print(regular_source_diagnostic(path), file=sys.stderr)
            continue
        files.append(path)
    return files


def extract_timestamp(lines):
    """
    Find the first timestamp line: ⏺ H:MM AM/PM Weekday, Month DD, YYYY
    Returns (datetime_str, iso_str) or (None, None).
    """
    ts_pattern = re.compile(r"⏺\s+(\d{1,2}:\d{2}\s+[AP]M)\s+\w+,\s+(\w+)\s+(\d{1,2}),\s+(\d{4})")
    months = {
        "January": "01",
        "February": "02",
        "March": "03",
        "April": "04",
        "May": "05",
        "June": "06",
        "July": "07",
        "August": "08",
        "September": "09",
        "October": "10",
        "November": "11",
        "December": "12",
    }
    for line in lines[:50]:
        m = ts_pattern.search(line)
        if m:
            time_str, month, day, year = m.groups()
            mon = months.get(month, "00")
            day_z = day.zfill(2)
            time_safe = time_str.replace(":", "").replace(" ", "")
            iso = f"{year}-{mon}-{day_z}"
            human = f"{year}-{mon}-{day_z}_{time_safe}"
            return human, iso
    return None, None


def extract_people(lines):
    """
    Detect people mentioned as speakers or by name in first 100 lines.
    Returns sorted list of detected names.
    """
    found = set()
    text = "".join(lines[:100])

    # Speaker tags: "Alice:", "Ben:", etc.
    for person in KNOWN_PEOPLE:
        if re.search(rf"(?<!\w){re.escape(person)}(?!\w)", text, re.IGNORECASE):
            found.add(person)

    # Working directory username hint — map to known people if configured
    dir_match = re.search(r"/Users/(\w+)/", text)
    if dir_match:
        username = dir_match.group(1)
        # User can map usernames to names in ~/.mempalace/known_names.json
        # under a "username_map" key, e.g. {"username_map": {"jdoe": "John"}}
        username_map = _load_username_map()
        if username in username_map:
            found.add(username_map[username])

    return sorted(found)


def extract_subject(lines):
    """
    Find the first meaningful user prompt (> line that isn't a shell command).
    Returns cleaned, filename-safe subject string.
    """
    skip_patterns = re.compile(
        r"^(\.\/|cd |ls |python|bash|git |cat |source |export |claude|./activate)"
    )
    for line in lines:
        if line.startswith("> "):
            prompt = line[2:].strip()
            if prompt and not skip_patterns.match(prompt) and len(prompt) > 5:
                # Clean for filename
                subject = re.sub(r"[^\w\s-]", "", prompt)
                subject = re.sub(r"\s+", "-", subject.strip())
                return subject[:60]
    return "session"


def _reject_non_regular_output_entry(out_path: Path) -> None:
    """Refuse a synthesized output name that already exists as a non-regular entry.

    ``os.lstat`` is deliberate: ``Path.exists`` follows links and answers False for a
    dangling symlink, so an existence probe would let the write create the link target
    outside the requested output directory.
    """
    try:
        st = os.lstat(out_path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise RegularSourceError(out_path, _OUTPUT_TARGET_REASON)


def _open_regular_output_descriptor(out_path: Path) -> int:
    """Open a validated regular-file descriptor for a generated split chunk.

    O_NOFOLLOW refuses a symlink at the synthesized name and O_NONBLOCK keeps a
    reader-less FIFO from blocking the open forever; ``fstat`` re-validates the
    descriptor that will actually be written.
    """
    _reject_non_regular_output_entry(out_path)

    flags = os.O_WRONLY | os.O_CREAT | _O_BINARY
    if _HAS_O_NOFOLLOW:
        flags |= os.O_NOFOLLOW
    if _HAS_O_NONBLOCK:
        flags |= os.O_NONBLOCK
    protected_reopen = _HAS_O_NOFOLLOW and _HAS_O_NONBLOCK
    if not protected_reopen:
        # O_CREAT|O_EXCL refuses every raced-in object without following or opening it.
        # Existing regular outputs are deliberately fail-closed on this fallback path.
        flags |= os.O_EXCL

    try:
        fd = os.open(out_path, flags, _OUTPUT_MODE)
    except OSError as exc:
        if _output_entry_is_unsafe(out_path):
            raise RegularSourceError(out_path, _OUTPUT_TARGET_REASON) from exc
        if not protected_reopen and exc.errno == errno.EEXIST:
            raise RegularSourceError(out_path, _OUTPUT_REPLACE_REASON) from exc
        raise

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise RegularSourceError(out_path, _OUTPUT_TARGET_REASON)
        os.ftruncate(fd, 0)
        _clear_nonblocking(fd)
    except Exception:
        os.close(fd)
        raise

    return fd


def _output_entry_is_unsafe(out_path: Path) -> bool:
    """Report whether a failed open was caused by a hostile entry rather than plain I/O."""
    try:
        st = os.lstat(out_path)
    except OSError:
        return False
    return not stat.S_ISREG(st.st_mode) or st.st_nlink != 1


def _clear_nonblocking(fd: int) -> None:
    """Drop O_NONBLOCK once the descriptor is known to be a regular file."""
    if not _HAS_O_NONBLOCK:
        return

    import fcntl

    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)


def _write_regular_output(out_path: Path, text: str) -> None:
    """Write a generated chunk through a descriptor validated as a regular file."""
    payload = memoryview(text.encode("utf-8"))
    fd = _open_regular_output_descriptor(out_path)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written == 0:
                raise OSError("regular output write made no progress")
            offset += written
    finally:
        os.close(fd)


def split_file(filepath, output_dir, dry_run=False, *, _progress=None):
    """
    Split a single mega-file into per-session files.
    Returns list of output paths written (or would be written if dry_run).
    """
    path = Path(filepath)
    lines = _read_session_lines(path)

    boundaries = find_session_boundaries(lines)
    if len(boundaries) < 2:
        return []  # Not a mega-file

    # Add sentinel at end
    boundaries.append(len(lines))

    out_dir = Path(output_dir) if output_dir else path.parent
    written = _progress if _progress is not None else []

    for i, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        chunk = lines[start:end]
        if len(chunk) < 10:
            continue  # Skip tiny fragments

        ts_human, ts_iso = extract_timestamp(chunk)
        people = extract_people(chunk)
        subject = extract_subject(chunk)

        # Build filename: SOURCESTEM__DATE_TIME_People_subject.txt
        # Source stem prefix prevents collisions when multiple mega-files
        # produce sessions with the same timestamp/people/subject.
        ts_part = ts_human or f"part{i + 1:02d}"
        people_part = "-".join(people[:3]) if people else "unknown"
        src_stem = re.sub(r"[^\w-]", "_", path.stem)[:40]
        name = f"{src_stem}__{ts_part}_{people_part}_{subject}.txt"
        # Sanitize
        name = re.sub(r"[^\w\.\-]", "_", name)
        name = re.sub(r"_+", "_", name)

        out_path = out_dir / name

        if dry_run:
            print(f"  [{i + 1}/{len(boundaries) - 1}] {name}  ({len(chunk)} lines)")
        else:
            _write_regular_output(out_path, "".join(chunk))
            print(f"  ✓ {name}  ({len(chunk)} lines)")

        written.append(out_path)

    return written


def main():
    parser = argparse.ArgumentParser(
        description="Split concatenated transcript mega-files into per-session files"
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source directory (default: MEMPALACE_SOURCE_DIR or ~/Desktop/transcripts)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None, help="Output directory (default: same as source)"
    )
    parser.add_argument(
        "--min-sessions",
        type=int,
        default=2,
        help="Only split files with at least N sessions (default: 2)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would happen without writing files"
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Split a single specific file instead of scanning dir",
    )
    args = parser.parse_args()

    src_dir = Path(args.source) if args.source else LUMI_DIR
    output_dir = args.output_dir or None  # None = same dir as file

    if args.file:
        files = [Path(args.file)]
    else:
        files = discover_text_sources(src_dir)

    mega_files = []
    for f in files:
        try:
            lines = _read_session_lines(f)
        except OSError as exc:
            print(f"{f}: {exc}", file=sys.stderr)
            continue
        boundaries = find_session_boundaries(lines)
        if len(boundaries) >= args.min_sessions:
            mega_files.append((f, len(boundaries)))

    if not mega_files:
        print(f"No mega-files found in {src_dir} (min {args.min_sessions} sessions).")
        return

    print(f"\n{'=' * 60}")
    print(f"  Mega-file splitter — {'DRY RUN' if args.dry_run else 'SPLITTING'}")
    print(f"{'=' * 60}")
    print(f"  Source:      {src_dir}")
    print(f"  Output:      {output_dir or 'same dir as source'}")
    print(f"  Mega-files:  {len(mega_files)}")
    print(f"{'─' * 60}\n")

    total_written = 0
    failed_files = 0
    for f, n_sessions in mega_files:
        try:
            size_kb = stat_regular_source(f).st_size // 1024
        except OSError as exc:
            print(f"{f}: {exc}", file=sys.stderr)
            failed_files += 1
            continue
        print(f"  {f.name}  ({n_sessions} sessions, {size_kb}KB)")
        progress = []
        try:
            written = split_file(f, output_dir, dry_run=args.dry_run, _progress=progress)
        except OSError as exc:
            # A refused output target must not cost the operator the source mega-file.
            total_written += len(progress)
            failed_files += 1
            print(f"{f}: {exc}", file=sys.stderr)
            print(f"  → Split aborted; original left in place as {f.name}\n")
            continue
        total_written += len(written)

        if not args.dry_run and written:
            backup = f.with_suffix(".mega_backup")
            f.rename(backup)
            print(f"  → Original renamed to {backup.name}\n")
        else:
            print()

    print(f"{'─' * 60}")
    if args.dry_run:
        print(f"  DRY RUN — would create {total_written} files from {len(mega_files)} mega-files")
    elif failed_files:
        print(
            f"  Done with errors — created {total_written} files; "
            f"failed {failed_files} of {len(mega_files)} mega-files"
        )
    else:
        print(f"  Done — created {total_written} files from {len(mega_files)} mega-files")
    print()
    if failed_files:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
